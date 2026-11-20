"""Focus status: best polychromatic RMS focus in closed form (analysis/focus.py).

Benchmarks:
* an ideal lens images infinity perfectly on its focal plane, so with the image surface
  displaced by d the best focus is exactly -d and the best RMS is zero;
* for real lenses the closed-form optimum and its RMS equal a brute-force evaluation of
  the spot diagram with the image distance moved (same rays, exact for a plane image).
"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from opticore.analysis.focus import focus_status
from opticore.analysis.spot import spot_diagram
from opticore.api.main import app
from opticore.samples import cooke_triplet, singlet
from opticore.system import compile_system

from .test_ideal_fields import ideal_singlet


def _field_weighted_rms_um(cs) -> float:
    sd = spot_diagram(cs, "hexapolar", 6, "centroid")
    w = [cs.model.fields[f["field"]].weight for f in sd["fields"]]
    return math.sqrt(sum(wi * f["rms_radius_um"] ** 2 for wi, f in zip(w, sd["fields"])) / sum(w))


def _shift_image(system, delta):
    s = system.model_copy(deep=True)
    s.surfaces[-2].thickness = s.surfaces[-2].thickness + delta
    return s


@pytest.mark.parametrize("d", [0.5, -0.8])
def test_ideal_lens_best_focus_is_the_focal_plane(d):
    sys = ideal_singlet(img=100.0 + d)
    r = focus_status(compile_system(sys))
    assert r["best_defocus_mm"] == pytest.approx(-d, abs=1e-9)
    assert r["rms_best_um"] < 1e-4  # 0.1 nm: round-off of A + 2B d + C d^2 near zero
    assert r["rms_um"] > 10
    assert r["at_best_focus"] is False
    assert r["exact"] is True
    at = focus_status(compile_system(ideal_singlet()))
    assert at["best_defocus_mm"] == pytest.approx(0.0, abs=1e-9)
    assert at["at_best_focus"] is True


@pytest.mark.parametrize("make", [singlet, lambda: cooke_triplet(True)])
def test_closed_form_matches_the_spot_diagram_through_focus(make):
    p = make()
    cs = compile_system(p.system, p.custom_materials)
    r = focus_status(cs)
    d = r["best_defocus_mm"]
    # the current RMS is the spot diagram's field-weighted RMS
    assert r["rms_um"] == pytest.approx(_field_weighted_rms_um(cs), rel=1e-9)
    # moving the image surface by the predicted amount gives the predicted RMS, and it is a minimum
    best = compile_system(_shift_image(p.system, d), p.custom_materials)
    assert _field_weighted_rms_um(best) == pytest.approx(r["rms_best_um"], rel=1e-8)
    step = max(abs(d), 0.02) * 0.5
    for s in (-step, step):
        assert _field_weighted_rms_um(compile_system(_shift_image(p.system, d + s), p.custom_materials)) > r["rms_best_um"]
    # per field: the reported RMS equals the spot diagram's
    sd = spot_diagram(cs, "hexapolar", 6, "centroid")
    for a, b in zip(r["per_field"], sd["fields"]):
        assert a["rms_um"] == pytest.approx(b["rms_radius_um"], rel=1e-9)
    assert r["max_field_rms_um"] == pytest.approx(max(f["rms_radius_um"] for f in sd["fields"]), rel=1e-9)
    # after refocusing the system reports itself at best focus
    assert focus_status(best)["at_best_focus"] is True


def test_focus_endpoint():
    client = TestClient(app)
    p = singlet()
    body = client.post("/api/v1/analysis/focus", json={"system": p.system.model_dump(mode="json"), "custom_materials": []}).json()
    assert {"best_defocus_mm", "rms_um", "rms_best_um", "at_best_focus", "per_field", "method"} <= set(body)


def test_best_focus_with_real_image_height_fields_is_an_estimate():
    """Real image-height fields are re-solved when the image surface moves, so the closed-form defocus (rays held
    fixed) is first order there: the cell-phone lens predicted -0.040608 mm, the re-traced optimum is -0.039196 mm.
    It must not be labelled exact."""
    from opticore.samples import cell_phone_lens

    p = cell_phone_lens()
    assert p.system.field_type == "image_height"
    r = focus_status(compile_system(p.system, p.custom_materials))
    assert r["exact"] is False and r["best_defocus_mm"] is not None
