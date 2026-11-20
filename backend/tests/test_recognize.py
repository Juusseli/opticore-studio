import base64
import os
import tempfile

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.analysis.evaluate import lens_elements
from opticore.api.main import app
from opticore.io.cad import CadError, export_system_cad, import_cad
from opticore.io.recognize import insert_elements, recognize_asset
from opticore.materials import MaterialLibrary
from opticore.model import OpticalSystem
from opticore.paraxial import paraxial_data
from opticore.samples import get_sample
from opticore.system import compile_system

from .conftest import make_system

LIB = MaterialLibrary()
OPTS = dict(include_rays=False, include_stop=False, include_image=False)


def _asset_from_system(sysm, transform=None, fmt="step"):
    cs = compile_system(sysm)
    data = base64.b64decode(export_system_cad(cs, fmt, **OPTS)["data_base64"])
    imp = import_cad(data, "part." + ("step" if fmt == "step" else "igs"))
    return {"format": fmt, "source_b64": imp["source_b64"], "transform": transform or {"translate": [0, 0, 0], "rotate_deg": [0, 0, 0]}}, cs


def _base(src: OpticalSystem, length: float) -> OpticalSystem:
    return OpticalSystem.model_validate(
        {
            "surfaces": [{"id": "obj", "thickness": None}, {"id": "dummy", "thickness": length, "is_stop": True}, {"id": "img"}],
            "wavelengths": [w.model_dump() for w in src.wavelengths],
            "primary_wavelength": src.primary_wavelength,
            "fields": [f.model_dump() for f in src.fields],
            "aperture": src.aperture.model_dump(),
        }
    )


def _step_bytes(shape) -> bytes:
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
    return data


@pytest.mark.parametrize("sample", ["singlet", "achromat", "cooke-triplet"])
def test_exported_samples_are_recognised_and_reproduce_first_order_optics(sample):
    src = get_sample(sample).system
    asset, cs = _asset_from_system(src)
    rec = recognize_asset(asset)
    assert not rec["skipped"]
    els = lens_elements(cs)
    assert len(rec["elements"]) == len(els)
    for e, el in zip(rec["elements"], els):
        i = el["front"]
        assert e["thickness"] == pytest.approx(src.surfaces[i].thickness, abs=1e-9)
        for face, k in ((e["front"], i), (e["back"], el["back"])):
            r = src.surfaces[k].radius
            assert (face["radius"] is None) == (r is None)
            if r is not None:
                assert face["radius"] == pytest.approx(r, rel=1e-10)
    total = sum(s.thickness for s in src.surfaces[1:-1])
    new, rep = insert_elements(_base(src, total), rec["elements"], "lens", [el["material"] for el in els], 1, "cad", 0.0, "front", LIB)
    p0, p1 = paraxial_data(cs), paraxial_data(compile_system(new))
    assert p1.efl == pytest.approx(p0.efl, rel=1e-11)
    if sample == "achromat":  # cemented doublet -> one group with a shared surface
        assert rep["count"] == 3


def test_foreign_step_lens_with_true_spherical_faces():
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    R1, R2, t, h = 60.0, -80.0, 6.0, 12.0
    s1 = BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, R1), abs(R1)).Shape()
    s2 = BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, t + R2), abs(R2)).Shape()
    cyl = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, -50), gp_Dir(0, 0, 1)), h, 100).Shape()
    lens = BRepAlgoAPI_Common(BRepAlgoAPI_Common(s1, s2).Shape(), cyl).Shape()
    data = _step_bytes(lens)
    imp = import_cad(data, "biconvex.step")
    rec = recognize_asset({"format": "step", "source_b64": imp["source_b64"], "transform": {"translate": [0, 0, 0], "rotate_deg": [0, 0, 0]}})
    e = rec["elements"][0]
    assert e["front"]["type"] == "sphere" and e["back"]["type"] == "sphere"
    assert e["front"]["radius"] == pytest.approx(R1, rel=1e-10)
    assert e["back"]["radius"] == pytest.approx(R2, rel=1e-10)
    assert e["thickness"] == pytest.approx(t, abs=1e-9)
    assert e["front"]["semi_diameter"] == pytest.approx(h, rel=1e-6)
    # lensmaker (thick lens) check after insertion
    sysm = make_system([{"id": "obj", "thickness": None}, {"id": "d", "thickness": 200.0, "is_stop": True}, {"id": "img"}], wavelengths=[{"value": 0.5875618}], aperture={"type": "epd", "value": 10.0})
    new, _ = insert_elements(sysm, rec["elements"], "lens", ["N-BK7"], 1, "axis", 5.0, "front", LIB)
    n = compile_system(new).n_after[0, 2]
    phi = (n - 1) * (1 / R1 - 1 / R2 + (n - 1) * t / (n * R1 * R2))
    assert paraxial_data(compile_system(new)).efl == pytest.approx(1 / phi, rel=1e-11)
    assert new.surfaces[1].thickness == pytest.approx(5.0)  # the gap


def test_aspheric_and_conic_faces_are_fitted():
    src = make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "a1", "type": "even_asphere", "radius": 40.0, "conic": -0.6, "aspheric": [-2e-6, 1e-9], "thickness": 6.0, "material": "N-BK7", "is_stop": True},
            {"id": "a2", "radius": -120.0, "conic": 2.0, "thickness": 60.0},
            {"id": "img"},
        ],
        wavelengths=[{"value": 0.5875618}],
        aperture={"type": "epd", "value": 16.0},
    )
    asset, cs = _asset_from_system(src)
    e = recognize_asset(asset)["elements"][0]
    assert not e["front"]["exact"] and e["front"]["fit_max_mm"] < 2e-6
    assert e["back"]["fit_max_mm"] < 2e-6
    # the fitted surfaces reproduce the exact sag over the clear aperture
    from opticore.io.recognize import _sag_model

    r = np.linspace(0, e["front"]["semi_diameter"] * 0.98, 50)
    exact = cs.shapes[1].sag(r * r)
    fit = _sag_model(r, 1 / e["front"]["radius"], e["front"]["conic"], np.array(e["front"]["aspheric"]))
    assert np.max(np.abs(fit - exact)) < 2e-6
    new, _ = insert_elements(_base(src, 66.0), [e], "lens", ["N-BK7"], 1, "cad", 0.0, "front", LIB)
    assert paraxial_data(compile_system(new)).efl == pytest.approx(paraxial_data(cs).efl, rel=1e-6)


def test_mirror_insertion_with_focus_solve():
    src = get_sample("spherical-mirror").system
    asset, _ = _asset_from_system(src)
    rec = recognize_asset(asset)
    e = rec["elements"][0]
    assert e["front"]["radius"] == pytest.approx(-200.0, rel=1e-10)
    base = make_system([{"id": "obj", "thickness": None}, {"id": "ent", "thickness": 120.0, "is_stop": True}, {"id": "img"}], wavelengths=[{"value": 0.5875618}], aperture={"type": "epd", "value": 20.0})
    new, rep = insert_elements(base, [e], "mirror", [], 1, "cad", 0.0, "front", LIB)
    cs = compile_system(new)
    pd = paraxial_data(cs)
    assert abs(pd.efl) == pytest.approx(100.0, rel=1e-9)
    assert cs.model.surfaces[2].material == "MIRROR"
    assert cs.model.surfaces[2].thickness == pytest.approx(-100.0, rel=1e-9)  # paraxial focus solve
    assert new.surfaces[1].thickness == pytest.approx(50.0, abs=1e-9)  # mirror vertex 50 mm after the entrance surface
    assert any("focus solve" in n for n in rep["notes"])


def test_decentred_tilted_part_is_placed_exactly():
    src = get_sample("singlet").system
    tr = {"translate": [0.0, 1.5, 20.0], "rotate_deg": [3.0, -2.0, 0.0]}
    asset, _ = _asset_from_system(src, tr)
    e = recognize_asset(asset)["elements"][0]
    base = _base(src, 150.0)
    new, rep = insert_elements(base, [e], "lens", ["N-BK7"], 1, "cad", 0.0, "front", LIB)
    cs = compile_system(new)
    k = rep["first_index"] + 1  # after the placement coordinate break
    assert np.allclose(cs.frames[k].origin, e["vertex"], atol=1e-9)
    assert np.allclose(cs.frames[k].matrix[:, 2], e["axis"], atol=1e-9)
    # downstream (the image) stays where it was
    assert np.allclose(cs.frames[-1].origin, compile_system(base).frames[-1].origin, atol=1e-9)


def test_axis_placement_keeps_downstream_positions_and_checks_space():
    src = get_sample("singlet").system
    asset, _ = _asset_from_system(src)
    e = recognize_asset(asset)["elements"][0]
    base = _base(src, 100.0)
    new, _ = insert_elements(base, [e], "lens", ["N-BK7"], 1, "axis", 10.0, "front", LIB)
    zs = [f.origin[2] for f in compile_system(new).frames]
    assert zs[2] == pytest.approx(10.0) and zs[-1] == pytest.approx(100.0)
    with pytest.raises(CadError):
        insert_elements(base, [e], "lens", ["N-BK7"], 1, "axis", 97.0, "front", LIB)  # 97 + 5 > 100


def test_parts_that_are_not_lenses_are_reported():
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    outer = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 20, 10).Shape()
    inner = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, -1), gp_Dir(0, 0, 1)), 12, 12).Shape()
    ring = BRepAlgoAPI_Cut(outer, inner).Shape()  # a lens mount: the axis passes through the hole
    imp = import_cad(_step_bytes(ring), "mount.step")
    rec = recognize_asset({"format": "step", "source_b64": imp["source_b64"], "transform": {}})
    assert not rec["elements"] and "crosses the part 0 times" in rec["skipped"][0]["reason"]
    with pytest.raises(CadError):
        recognize_asset({"format": "stl", "mesh": {}})


def test_cad_optics_api():
    c = TestClient(app)
    src = get_sample("singlet").system
    asset, _ = _asset_from_system(src)
    r = c.post("/api/v1/cad/recognize", json={"asset": asset})
    assert r.status_code == 200 and r.json()["elements"][0]["front"]["type"] == "sphere"
    body = {"system": _base(src, 120.0).model_dump(), "asset": asset, "elements": [0], "materials": ["N-BK7"], "after": 1, "placement": "axis", "gap": 2.0}
    ins = c.post("/api/v1/cad/insert", json=body)
    assert ins.status_code == 200
    assert len(ins.json()["system"]["surfaces"]) == 5
    bad = c.post("/api/v1/cad/insert", json={**body, "materials": ["UNOBTAINIUM"]})
    assert bad.status_code == 422
    bad = c.post("/api/v1/cad/insert", json={**body, "elements": [3]})
    assert bad.status_code == 422
