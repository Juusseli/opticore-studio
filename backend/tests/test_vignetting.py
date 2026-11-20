"""Field vignetting factors (VDX, VDY, VCX, VCY) and their automatic setting."""

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from opticore.analysis.evaluate import evaluate_system
from opticore.analysis.spot import spot_diagram
from opticore.analysis.vignetting import vignetting_factors
from opticore.api.main import app
from opticore.model import FieldPoint, OpticalSystem
from opticore.paraxial import compute_pupil
from opticore.raytrace import hexapolar, trace_pupil, vignetted_pupil
from opticore.samples import get_sample
from opticore.system import compile_system


def _without_factors(p):
    d = p.system.model_dump()
    for f in d["fields"]:
        f.update(vdx=0.0, vdy=0.0, vcx=0.0, vcy=0.0)
    return OpticalSystem.model_validate(d)


def test_mapping_of_the_pupil():
    p = get_sample("double-gauss")
    cs = compile_system(p.system, p.custom_materials)
    f = p.system.fields[3]
    px, py = vignetted_pupil(cs, 3, np.array([0.0, 1.0, -1.0, 0.5]), np.array([1.0, 0.0, -1.0, 0.5]))
    assert np.allclose(px, f.vdx + np.array([0.0, 1.0, -1.0, 0.5]) * (1 - f.vcx))
    assert np.allclose(py, f.vdy + np.array([1.0, 0.0, -1.0, 0.5]) * (1 - f.vcy))
    a, b = vignetted_pupil(cs, 0, np.array([0.3]), np.array([-0.2]))  # on-axis field: no factors
    assert a[0] == 0.3 and b[0] == -0.2
    with pytest.raises(ValidationError):
        FieldPoint(y=1.0, vcy=1.0)
    with pytest.raises(ValidationError):
        FieldPoint(y=1.0, vdy=1.5)


def test_set_vignetting_finds_the_edges_of_the_passed_pupil():
    p = get_sample("double-gauss")
    sysd = _without_factors(p)
    cs = compile_system(sysd, p.custom_materials)
    res = vignetting_factors(cs)
    fs = res["fields"]
    assert all(f["ok"] for f in fs)
    assert fs[0] == {"vdx": 0.0, "vdy": 0.0, "vcx": 0.0, "vcy": 0.0, "ok": True, "note": None}
    assert [f["vcy"] for f in fs] == sorted(f["vcy"] for f in fs)  # more compression with field
    pupil = compute_pupil(cs)
    for k, f in enumerate(fs[1:], start=1):
        top, bottom = f["vdy"] + 1 - f["vcy"], f["vdy"] - 1 + f["vcy"]
        right = f["vdx"] + 1 - f["vcx"]
        inside = trace_pupil(cs, 1, k, np.array([0.0, 0.0, right, -right]), np.array([top, bottom, f["vdy"], f["vdy"]]), pupil)
        assert inside.ok.all()
        out = trace_pupil(cs, 1, k, np.array([0.0, 0.0]), np.array([top + 1e-5, bottom - 1e-5]), pupil)
        assert not out.ok.any()  # the edges are on the aperture to 1e-5 of the pupil radius
        if f["vcx"] > 0:
            assert not trace_pupil(cs, 1, k, np.array([right + 1e-5]), np.array([f["vdy"]]), pupil).ok[0]


def test_vignetting_factors_clear_the_marginal_ray_warnings_and_sample_the_beam():
    p = get_sample("double-gauss")
    bare = compile_system(_without_factors(p), p.custom_materials)
    vig = compile_system(p.system, p.custom_materials)
    codes = lambda cs: [d["code"] if isinstance(d, dict) else d.code for d in evaluate_system(cs, layout_rays_per_field=5, ring_rays=0)["diagnostics"]]  # noqa: E731
    assert "RAY_FAILED" in codes(bare)
    assert "RAY_FAILED" not in codes(vig)
    s_bare = spot_diagram(bare)
    s_vig = spot_diagram(vig)
    # the factors describe an ellipse; the passed region of the double Gauss is the lens-shaped overlap of
    # aperture footprints, so rays in the ellipse's corners are still clipped (as in other lens-design
    # programs) -- but the sampling falls on the beam: at least as many rays pass, many more at full field
    prim = p.system.primary_wavelength
    frac = lambda f: next(w["n_ok"] / w["n_rays"] for w in f["per_wavelength"] if w["wavelength"] == prim)  # noqa: E731
    for fb, fv in zip(s_bare["fields"], s_vig["fields"]):
        assert frac(fv) >= frac(fb) - 1e-12
    assert frac(s_vig["fields"][-1]) > 1.5 * frac(s_bare["fields"][-1])
    # the on-axis field has no factors: identical results
    assert s_bare["fields"][0]["rms_radius_um"] == pytest.approx(s_vig["fields"][0]["rms_radius_um"], rel=1e-12)


def test_zero_factors_change_nothing():
    p = get_sample("achromat")
    cs = compile_system(p.system)
    px, py = hexapolar(6)
    a = trace_pupil(cs, 1, 2, px, py, compute_pupil(cs))
    b = trace_pupil(cs, 1, 2, px, py, compute_pupil(cs), vignetting=True)
    assert np.array_equal(a.image_xy(), b.image_xy())


def test_vignetting_api():
    p = get_sample("double-gauss")
    client = TestClient(app)
    r = client.post("/api/v1/system/vignetting", json={"system": _without_factors(p).model_dump(mode="json"), "custom_materials": p.custom_materials})
    assert r.status_code == 200, r.text
    fs = r.json()["fields"]
    assert len(fs) == 4 and fs[3]["vcy"] == pytest.approx(0.4977, abs=5e-4)
