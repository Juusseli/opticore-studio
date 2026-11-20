import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opticore.analysis.spot import spot_diagram
from opticore.api.main import app
from opticore.io.zmx import ZmxError, decode_zmx, parse_zmx
from opticore.paraxial import paraxial_data
from opticore.samples import achromat
from opticore.system import compile_system

DATA = Path(__file__).parent / "data"


def load(name: str) -> str:
    return (DATA / name).read_text(encoding="utf-8")


def test_inch_doublet_matches_native_sample():
    """The same prescription written in inches imports to the native mm design."""
    proj, diags = parse_zmx(load("doublet_inches.zmx"), "doublet_inches.zmx")
    s = proj.system
    assert [x.material for x in s.surfaces] == ["AIR", "N-BK7", "F2", "AIR", "AIR"]
    assert s.surfaces[1].radius == pytest.approx(49.5259, rel=1e-6)
    assert s.surfaces[2].radius == pytest.approx(-38.6718, rel=1e-6)
    assert s.surfaces[3].thickness == pytest.approx(94.8055, rel=1e-9)
    assert s.surfaces[1].is_stop
    assert s.aperture.type == "epd" and s.aperture.value == pytest.approx(20.0, rel=1e-9)
    assert [f.y for f in s.fields] == [0.0, 1.4, 2.0]
    assert s.primary_wavelength == 1
    assert any(d.status == "conversion" and "IN" in d.message for d in diags)
    assert any(d.status == "partial" and "Coating" in d.message for d in diags)
    # engineering results agree with the native sample
    a = paraxial_data(compile_system(s), 1)
    b = paraxial_data(compile_system(achromat(True).system), 1)
    assert a.efl == pytest.approx(b.efl, rel=1e-6)
    ra = [f["rms_radius_um"] for f in spot_diagram(compile_system(s))["fields"]]
    rb = [f["rms_radius_um"] for f in spot_diagram(compile_system(achromat(True).system))["fields"]]
    assert ra == pytest.approx(rb, rel=1e-4)


def test_feature_coverage_and_diagnostics():
    proj, diags = parse_zmx(load("features.zmx"), "features.zmx")
    s = proj.system
    by = {d.status for d in diags}
    assert {"imported", "unsupported", "missing_material", "conversion"} <= by
    assert s.aperture.type == "image_fnum" and s.aperture.value == 4
    asph = s.surfaces[1]
    assert asph.type == "even_asphere" and asph.conic == -0.5
    assert asph.aspheric[:2] == pytest.approx([1e-6, -2e-9])
    assert s.surfaces[2].type == "standard" and s.surfaces[2].radius is None  # TOROIDAL -> plane dummy
    assert s.surfaces[2].material == "AIR"
    assert any(d.status == "missing_material" and "UNOBTAINIUM-7" in d.message for d in diags)
    model = s.surfaces[3].material
    assert model.startswith("MODEL_")
    cm = proj.custom_materials[0]
    from opticore.materials import MaterialLibrary

    lib = MaterialLibrary(proj.custom_materials)
    assert lib.get(model).nd == pytest.approx(1.6, abs=1e-12)
    assert lib.get(model).vd == pytest.approx(40.0, rel=1e-9)
    assert s.surfaces[5].type == "coordinate_break" and s.surfaces[5].tilt_x == 45
    assert s.surfaces[6].material == "MIRROR"
    compile_system(s, proj.custom_materials)  # the imported system is traceable
    assert proj.provenance.imports[0]["format"] == "zmx"


def test_asphere_coefficients_scale_with_units():
    text = load("features.zmx").replace("UNIT MM", "UNIT CM")
    proj, _ = parse_zmx(text)
    a = proj.system.surfaces[1].aspheric
    # A4 [cm^-3] -> mm^-3: x 10^-3 ; A6 [cm^-5] -> x 10^-5
    assert a[0] == pytest.approx(1e-6 * 1e-3)
    assert a[1] == pytest.approx(-2e-9 * 1e-5)
    assert proj.system.surfaces[1].radius == pytest.approx(500.0)


def test_rejects_non_lens_and_nsc():
    with pytest.raises(ZmxError):
        parse_zmx("hello world")
    with pytest.raises(ZmxError):
        parse_zmx("MODE NSC\nSURF 0\n")


def test_decode_utf16():
    raw = load("doublet_inches.zmx").encode("utf-16")
    assert decode_zmx(raw).startswith("VERS")


def test_api_import():
    c = TestClient(app)
    b64 = base64.b64encode(load("doublet_inches.zmx").encode("utf-16")).decode()
    r = c.post("/api/v1/import/zmx", json={"filename": "d.zmx", "content_base64": b64})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project"]["format"] == "opticore-project"
    assert body["diagnostics"][0]["status"] == "imported"
    r = c.post("/api/v1/import/zmx", json={"filename": "x.zmx", "content_base64": base64.b64encode(b"garbage").decode()})
    assert r.status_code == 422 and r.json()["error"]["code"] == "IMPORT_ERROR"
