import base64
import math
import os
import tempfile

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.integrate import quad

from opticore.api.main import app
from opticore.io.cad import CadError, export_system_cad, import_cad
from opticore.io.stl import parse_stl
from opticore.samples import get_sample
from opticore.system import compile_system

from .conftest import make_system
from .test_stl import _tris, binary_stl

OPTS = dict(include_rays=False, include_stop=False, include_image=False)


def _numeric_volume(cs, i, h):
    """∫ 2πr (z_back(r) - z_front(r)) dr for the element starting at surface i (independent of the CAD kernel)."""
    t = cs.model.surfaces[i].thickness
    f, b = cs.shapes[i], cs.shapes[i + 1]
    v, _ = quad(lambda r: 2 * math.pi * r * (t + float(b.sag(r * r)) - float(f.sag(r * r))), 0.0, h, epsabs=1e-13, epsrel=1e-13, limit=200)
    return abs(v)


def test_singlet_volume_matches_closed_form():
    cs = compile_system(get_sample("singlet").system)
    rep = export_system_cad(cs, "step", **OPTS)["report"]
    s = rep["solids"][0]
    h, R, t = s["rim_radius_mm"], 51.68, 5.0
    cap = R - math.sqrt(R * R - h * h)
    v = math.pi * h * h * (t - cap) + math.pi * cap * cap * (3 * R - cap) / 3
    assert s["volume_mm3"] == pytest.approx(v, rel=1e-9)
    assert s["front"] == "sphere" and s["back"] == "plane"
    assert rep["max_profile_deviation_mm"] == 0.0


@pytest.mark.parametrize("sample", ["achromat", "cooke-triplet"])
def test_element_volumes_match_profile_integration(sample):
    cs = compile_system(get_sample(sample).system)
    rep = export_system_cad(cs, "step", **OPTS)["report"]
    assert len(rep["solids"]) == {"achromat": 2, "cooke-triplet": 3}[sample]
    for s in rep["solids"]:
        i = s["surfaces"][0]
        assert s["volume_mm3"] == pytest.approx(_numeric_volume(cs, i, s["rim_radius_mm"]), rel=1e-9)
        # the front vertex of an axial element lies on the axis at its global z
        assert s["bbox_min"][0] == pytest.approx(-s["rim_radius_mm"], abs=1e-6)


def test_aspheric_and_conic_profiles_are_splines_within_tolerance():
    sysm = make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "a1", "type": "even_asphere", "radius": 40.0, "conic": -0.6, "aspheric": [-2e-6, 1e-9], "thickness": 6.0, "material": "N-BK7", "is_stop": True},
            {"id": "a2", "radius": -120.0, "conic": 2.0, "thickness": 60.0},
            {"id": "img"},
        ],
        wavelengths=[{"value": 0.5875618}],
        aperture={"type": "epd", "value": 16.0},
    )
    cs = compile_system(sysm)
    rep = export_system_cad(cs, "step", **OPTS)["report"]
    s = rep["solids"][0]
    assert s["front"] == "asphere" and s["back"] == "conic"
    assert 0 < rep["max_profile_deviation_mm"] < 1e-6
    assert s["volume_mm3"] == pytest.approx(_numeric_volume(cs, 1, s["rim_radius_mm"]), rel=1e-7)
    assert any("B-spline" in n for n in rep["notes"])


@pytest.mark.parametrize("fmt,ext", [("step", "step"), ("iges", "igs")])
def test_round_trip_preserves_names_and_volumes(fmt, ext):
    cs = compile_system(get_sample("cooke-triplet").system)
    out = export_system_cad(cs, fmt)
    data = base64.b64decode(out["data_base64"])
    back = import_cad(data, "triplet." + ext)
    names = [b["name"] for b in back["bodies"]]
    exported = {s["name"]: s["volume_mm3"] for s in out["report"]["solids"]}
    for name, v in exported.items():
        assert name in names
        body = next(b for b in back["bodies"] if b["name"] == name)
        assert body["solids"] == 1
        assert body["volume_mm3"] == pytest.approx(v, rel=1e-7)
    assert any(n.startswith("Aperture stop") for n in names) and any(n.startswith("Rays field") for n in names)
    assert back["triangles"] > 0 and back["source_b64"]


def test_folded_system_places_mirror_at_its_vertex():
    cs = compile_system(get_sample("fold-mirror").system)
    rep = export_system_cad(cs, "step", **OPTS)["report"]
    m = next(s for s in rep["solids"] if s["name"].startswith("M1"))
    j = m["surfaces"][0]
    v = cs.frames[j].origin
    lo, hi = np.array(m["bbox_min"]), np.array(m["bbox_max"])
    assert np.all(v >= lo - 1e-6) and np.all(v <= hi + 1e-6)
    assert any("global frame" in n for n in rep["notes"])


def test_import_external_step_box():
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_StepModelType, STEPControl_Writer

    d = tempfile.mkdtemp()
    path = os.path.join(d, "box.step")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    w = STEPControl_Writer()
    w.Transfer(BRepPrimAPI_MakeBox(10, 20, 30).Shape(), STEPControl_StepModelType.STEPControl_AsIs)
    w.Write(path)
    data = open(path, "rb").read()
    os.remove(path)
    r = import_cad(data, "box.step")
    assert r["volume_mm3"] == pytest.approx(6000.0, rel=1e-9)
    assert r["surface_area_mm2"] == pytest.approx(2 * (200 + 300 + 600), rel=1e-9)
    assert r["size"] == pytest.approx([10, 20, 30], abs=1e-6)
    assert r["closed"] and len(r["bodies"]) == 1 and r["triangles"] >= 12


def test_export_includes_cad_models_with_placement():
    cs = compile_system(get_sample("singlet").system)
    cube = parse_stl(binary_stl(_tris(a=10.0)))
    stl_asset = {
        "name": "housing-stl",
        "format": "stl",
        "visible": True,
        "color": "#888888",
        "mesh": {"positions_b64": cube["positions_b64"], "indices_b64": cube["indices_b64"], "vertices": cube["vertices"], "triangles": cube["triangles"]},
        "transform": {"translate": [0, 0, 100], "rotate_deg": [0, 0, 0]},
    }
    hidden = {**stl_asset, "name": "hidden", "visible": False}
    out = export_system_cad(cs, "step", [stl_asset, hidden], **OPTS)
    assert out["report"]["cad_models"] == ["housing-stl"]
    assert any("Hidden CAD model 'hidden'" in n for n in out["report"]["notes"])
    back = import_cad(base64.b64decode(out["data_base64"]), "x.step")
    body = next(b for b in back["bodies"] if b["name"] == "housing-stl")
    assert body["volume_mm3"] == pytest.approx(1000.0, rel=1e-6)  # STL shell sewn into a solid
    assert body["bbox_min"][2] == pytest.approx(100.0, abs=1e-5)
    # a STEP asset is re-exported from its exact source with the new placement
    step_asset = {"name": "lens-copy", "format": "step", "visible": True, "color": "#888888", "source_b64": back["source_b64"], "mesh": stl_asset["mesh"], "transform": {"translate": [50, 0, 0], "rotate_deg": [0, 0, 90]}}
    out2 = export_system_cad(cs, "iges", [step_asset], **OPTS)
    assert out2["report"]["cad_models"] == ["lens-copy"]


def test_skips_elements_that_cannot_be_built():
    sysm = make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "s1", "radius": 6.0, "thickness": 3.0, "material": "N-BK7", "is_stop": True, "semi_diameter": 7.0, "semi_diameter_mode": "fixed"},
            {"id": "s2", "thickness": 10.0},
            {"id": "img"},
        ],
        wavelengths=[{"value": 0.55}],
        aperture={"type": "epd", "value": 4.0},
    )
    cs = compile_system(sysm)
    with pytest.raises(CadError):  # nothing exportable remains
        export_system_cad(cs, "step", **OPTS)
    out = export_system_cad(cs, "step", include_rays=False, include_stop=True, include_image=False)
    assert out["report"]["skipped"] and "exceeds the radius of curvature" in out["report"]["skipped"][0]["reason"]


def test_import_errors():
    with pytest.raises(CadError):
        import_cad(b"ISO-10303-21;\nthis is not a valid step file", "bad.step")
    with pytest.raises(CadError):
        import_cad(b"whatever", "model.obj")


def test_cad_api_round_trip():
    c = TestClient(app)
    sysm = get_sample("achromat").system.model_dump()
    r = c.post("/api/v1/export/cad", json={"system": sysm, "format": "step"})
    assert r.status_code == 200
    data = r.json()["data_base64"]
    assert base64.b64decode(data).startswith(b"ISO-10303-21")
    imp = c.post("/api/v1/import/cad", json={"filename": "doublet.step", "data_base64": data})
    assert imp.status_code == 200
    assert {b["name"] for b in imp.json()["bodies"]} >= {"L1 N-BK7 (S1-S2)", "L2 F2 (S2-S3)"}
    bad = c.post("/api/v1/import/cad", json={"filename": "x.step", "data_base64": base64.b64encode(b"junk").decode()})
    assert bad.status_code == 422
    ig = c.post("/api/v1/export/cad", json={"system": sysm, "format": "iges"})
    assert ig.status_code == 200
