"""Cases found by the analysis matrix (tests/test_analysis_matrix.py): limitations reported as NOT_APPLICABLE, a POP beam
that fills the pupil of an imaging lens, and a time limit for the non-sequential trace."""

import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.paraxial import compute_pupil
from opticore.samples import get_sample
from opticore.system import compile_system

from .beam_systems import relay, thick_lens

client = TestClient(app, raise_server_exceptions=False)


def body(sid, **extra):
    """The request body of a library sample (by id) or of a test system (a Project)."""
    p = get_sample(sid) if isinstance(sid, str) else sid
    return {"system": p.system.model_dump(mode="json"), "custom_materials": [m if isinstance(m, dict) else m.model_dump(mode="json") for m in p.custom_materials], **extra}


@pytest.mark.parametrize(
    "sid,endpoint",
    [("hubble", "ghosts"), ("spherical-mirror", "pop"), ("fold-mirror", "ghosts"), (thick_lens(), "live-image"), ("colour-mixing", "vector-psf"), ("colour-mixing", "chromatic"), ("led-downlight", "pop")],
)
def test_limitations_are_not_applicable(sid, endpoint):
    r = client.post(f"/api/v1/analysis/{endpoint}", json=body(sid))
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOT_APPLICABLE"


def test_live_image_refuses_a_field_smaller_than_the_blur():
    """The thick-lens test system images +-5 um: fewer than 8 Airy discs across the frame, so the picture would be one blur."""
    r = client.post("/api/v1/analysis/live-image", json=body(thick_lens()))
    assert "diffraction spots" in r.json()["error"]["message"]


def test_pop_beam_filling_the_entrance_pupil():
    p = get_sample("achromat")
    r_ep = compute_pupil(compile_system(p.system, p.custom_materials)).r_ep
    a = client.post("/api/v1/analysis/pop", json=body("achromat", source={"kind": "pupil"}, grid=64, out_grid=64)).json()
    b = client.post("/api/v1/analysis/pop", json=body("achromat", source={"kind": "tophat", "radius": r_ep}, grid=64, out_grid=64)).json()
    assert a["source"] == b["source"] and a["source"]["radius"] == pytest.approx(r_ep)
    assert a["target"]["power"] == pytest.approx(b["target"]["power"], rel=1e-12)
    # a finite object has no such beam
    r = client.post("/api/v1/analysis/pop", json=body(relay(), source={"kind": "pupil"}))
    assert r.status_code == 422 and r.json()["error"]["code"] == "POP_SOURCE"


def test_nonsequential_time_limit_is_a_scaled_random_subset():
    full = client.post("/api/v1/analysis/nonseq", json=body("achromat", rays=60)).json()
    roomy = client.post("/api/v1/analysis/nonseq", json=body("achromat", rays=60, max_seconds=600)).json()
    assert full["complete"] and roomy["complete"] and roomy["source_rays"] == full["source_rays"]
    for k in ("detected", "detected_direct", "escaped", "total"):
        assert roomy["energy"][k] == pytest.approx(full["energy"][k], rel=1e-9)  # the order does not matter
    part = client.post("/api/v1/analysis/nonseq", json=body("achromat", rays=60, max_seconds=1e-6)).json()
    assert not part["complete"] and part["source_rays"] == 1 and "Time limit" in part["notes"][-1]
    assert part["energy"]["total"] == pytest.approx(1.0, rel=1e-9)  # scaled to the whole source


def test_image_simulation_of_an_axial_field_only_is_not_applicable():
    """A system whose only field is on the axis has no field scale for the image simulation (it divided by zero)."""
    p = get_sample("singlet")
    d = p.system.model_dump(mode="json")
    d["fields"] = [{"y": 0.0}]
    r = client.post("/api/v1/analysis/image-simulation", json={"system": d, "custom_materials": [], "crop_px": 32, "grid": 3, "oversample": 1})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOT_APPLICABLE"
    assert "off-axis field" in r.json()["error"]["message"]
