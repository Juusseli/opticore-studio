import math
import os
import tempfile

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.io.cad import import_cad
from opticore.nonseq import build_scene, trace_nonsequential
from opticore.paraxial import compute_pupil
from opticore.raytrace import launch, trace
from opticore.samples import get_sample
from opticore.system import SystemError_, compile_system

from .conftest import make_system


def _step_asset(shape, name, role, material=None, transform=None):
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_StepModelType, STEPControl_Writer

    d = tempfile.mkdtemp()
    path = os.path.join(d, "x.step")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    w = STEPControl_Writer()
    w.Transfer(shape, STEPControl_StepModelType.STEPControl_AsIs)
    w.Write(path)
    data = open(path, "rb").read()
    os.remove(path)
    imp = import_cad(data, name + ".step")
    return {
        "name": name,
        "format": "step",
        "source_b64": imp["source_b64"],
        "visible": True,
        "transform": transform or {"translate": [0, 0, 0], "rotate_deg": [0, 0, 0]},
        "optical": {"role": role, "material": material},
        "mesh": {"positions_b64": imp["positions_b64"], "indices_b64": imp["indices_b64"], "vertices": imp["vertices"], "triangles": imp["triangles"]},
    }


def _box(x0, y0, z0, dx, dy, dz):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), dx, dy, dz).Shape()


def _grid(n_rays, overfill=1.0):
    m = max(3, int(math.sqrt(n_rays * 4 / math.pi)))
    u = np.linspace(-overfill, overfill, m)
    gx, gy = np.meshgrid(u, u)
    ins = gx**2 + gy**2 <= overfill**2 + 1e-12
    return gx[ins], gy[ins]


def _empty(length=100.0, epd=10.0):
    return make_system(
        [{"id": "obj", "thickness": None}, {"id": "ap", "thickness": length, "is_stop": True}, {"id": "img", "semi_diameter": 20.0, "semi_diameter_mode": "fixed"}],
        wavelengths=[{"value": 0.5875618}],
        aperture={"type": "epd", "value": epd},
    )


@pytest.mark.parametrize("sample", ["singlet", "cooke-triplet"])
def test_lens_system_as_solids_matches_the_sequential_trace(sample):
    cs = compile_system(get_sample(sample).system)
    r = trace_nonsequential(cs, build_scene(cs, [], True), rays=300, overfill=1.0, split=False)
    px, py = _grid(300)
    pupil = compute_pupil(cs)
    w = cs.model.primary_wavelength
    P0, D0, opl = launch(cs, w, 0, px, py, pupil)
    s = trace(cs, w, P0, D0, opl, fresnel=True)
    xy, I = s.image_xy()[s.ok], s.intensity[s.ok]
    c = (xy * I[:, None]).sum(0) / I.sum()
    rms = math.sqrt((((xy - c) ** 2).sum(1) * I).sum() / I.sum())
    assert r["energy"]["detected_direct"] == pytest.approx(I.sum() / len(px), rel=1e-9)
    assert r["detector"]["direct_rms_mm"] == pytest.approx(rms, rel=1e-8)
    assert r["energy"]["total"] == pytest.approx(1.0, abs=1e-12)


def test_energy_is_conserved_with_ghost_splitting():
    cs = compile_system(get_sample("cooke-triplet").system)
    r = trace_nonsequential(cs, build_scene(cs, [], True), rays=120, overfill=1.0, split=True)
    e = r["energy"]
    assert e["total"] == pytest.approx(1.0, abs=1e-12)
    assert e["detected_after_reflections"] > 1e-3  # stray light from double reflections reaches the image


def test_absorber_blocks_exactly_the_rays_it_covers():
    cs0 = compile_system(get_sample("singlet").system)
    block = _step_asset(_box(-20, 1e-3, -30, 40, 20, 5), "baffle", "absorber")  # covers y > 0 in front of the lens
    sc = build_scene(cs0, [block], True)
    r = trace_nonsequential(cs0, sc, rays=300, overfill=1.0, split=False)
    px, py = _grid(300)
    pupil = compute_pupil(cs0)
    w = cs0.model.primary_wavelength
    sel = py <= 0  # rays with y <= 0 pass (the baffle starts at y = 1e-3)
    P0, D0, opl = launch(cs0, w, 0, px[sel], py[sel], pupil)
    s = trace(cs0, w, P0, D0, opl, fresnel=True)
    assert r["energy"]["detected_direct"] == pytest.approx((s.intensity * s.ok).sum() / len(px), rel=1e-9)
    assert r["energy"]["absorbed"]["baffle"] == pytest.approx(np.sum(~sel) / len(px), rel=1e-12)


def test_window_multiple_reflections_follow_the_geometric_series():
    cs = compile_system(_empty())
    win = _step_asset(_box(-15, -15, 20, 30, 30, 4), "window", "refractive", "N-BK7")
    r = trace_nonsequential(cs, build_scene(cs, [win], False), rays=60, overfill=0.8, split=True, min_power=1e-12, max_events=60)
    n = cs.library.index("N-BK7", 0.5875618)
    R = ((n - 1) / (n + 1)) ** 2
    e = r["energy"]
    assert e["detected_direct"] == pytest.approx((1 - R) ** 2, rel=1e-12)
    assert e["detected_after_reflections"] == pytest.approx((1 - R) ** 2 * R * R / (1 - R * R), rel=1e-6)
    assert e["escaped"] == pytest.approx(R + (1 - R) ** 2 * R / (1 - R * R), rel=1e-6)  # back-reflections leave towards the source
    assert e["total"] == pytest.approx(1.0, abs=1e-12)


def test_right_angle_prism_total_internal_reflection():
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Pnt, gp_Vec

    # triangle in the y-z plane: legs along z (entry face z = 10) and y; hypotenuse at 45 degrees
    poly = BRepBuilderAPI_MakePolygon(gp_Pnt(-10, -10, 10), gp_Pnt(-10, 10, 10), gp_Pnt(-10, -10, 30), True)
    prism = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(poly.Wire(), True).Face(), gp_Vec(20, 0, 0)).Shape()
    cs = compile_system(_empty(epd=6.0))
    pr = _step_asset(prism, "prism", "refractive", "N-BK7")
    r = trace_nonsequential(cs, build_scene(cs, [pr], False), rays=40, overfill=1.0, split=False, keep_paths=40)
    n = cs.library.index("N-BK7", 0.5875618)
    R = ((n - 1) / (n + 1)) ** 2
    e = r["energy"]
    assert e["detected"] == pytest.approx(0.0, abs=1e-15)  # the beam is turned by 90 degrees away from the detector
    assert e["escaped"] == pytest.approx((1 - R) ** 2, rel=1e-9)  # two normal-incidence faces, TIR loses nothing
    path = next(p for p in r["paths"] if p["end"] == "escaped")
    a, b = np.array(path["points"][-2]), np.array(path["points"][-1])
    d = (b - a) / np.linalg.norm(b - a)
    assert abs(abs(d[1]) - 1) < 1e-9  # exits along -y


def test_cad_mirror_folds_the_beam_onto_a_detector():

    cs = compile_system(_empty())
    mirror = _step_asset(_box(-15, -15, 0, 30, 30, 1), "fold", "mirror", transform={"translate": [0, 0, 50], "rotate_deg": [45, 0, 0]})
    r = trace_nonsequential(cs, build_scene(cs, [mirror], False), rays=40, overfill=1.0, split=False, keep_paths=10)
    assert r["energy"]["detected"] == pytest.approx(0.0, abs=1e-15)
    assert r["energy"]["escaped"] == pytest.approx(1.0, rel=1e-12)  # ideal mirror, folded out of the detector's way
    path = r["paths"][0]
    a, b = np.array(path["points"][-2]), np.array(path["points"][-1])
    d = (b - a) / np.linalg.norm(b - a)
    assert abs(d[2]) < 1e-9 and abs(abs(d[1]) - 1) < 1e-9


def test_refractive_role_needs_a_material_and_stl_is_flagged():
    cs = compile_system(_empty())
    bad = _step_asset(_box(-5, -5, 10, 10, 10, 2), "lump", "refractive", None)
    with pytest.raises(SystemError_):
        build_scene(cs, [bad], False)
    from opticore.io.stl import parse_stl

    from .test_stl import _tris, binary_stl

    cube = parse_stl(binary_stl(_tris(a=5.0)))
    stl = {"name": "cube", "format": "stl", "visible": True, "transform": {"translate": [-2.5, -2.5, 30], "rotate_deg": [0, 0, 0]}, "optical": {"role": "absorber"}, "mesh": {"positions_b64": cube["positions_b64"], "indices_b64": cube["indices_b64"], "vertices": 8, "triangles": 12}}
    sc = build_scene(cs, [stl], False)
    assert any("STL mesh" in n for n in sc.notes)
    r = trace_nonsequential(cs, sc, rays=200, overfill=1.0, split=False)
    assert r["energy"]["absorbed"]["cube"] > 0


def test_nonseq_api():
    c = TestClient(app)
    r = c.post("/api/v1/analysis/nonseq", json={"system": get_sample("achromat").system.model_dump(), "rays": 60, "split": True, "pixels": 16})
    assert r.status_code == 200
    b = r.json()
    assert b["energy"]["total"] == pytest.approx(1.0, abs=1e-9)
    assert len(b["detector"]["irradiance"]) == 16
    bad = c.post("/api/v1/analysis/nonseq", json={"system": get_sample("achromat").system.model_dump(), "field": 9})
    assert bad.status_code == 422
