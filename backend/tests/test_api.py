import time

import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.project import dump_project
from opticore.samples import achromat

client = TestClient(app)


def sample_system():
    return dump_project(achromat(True))["system"]


def test_health():
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_materials_list_and_curves():
    r = client.get("/api/v1/materials")
    names = [m["name"] for m in r.json()["materials"]]
    assert "N-BK7" in names
    r = client.post("/api/v1/materials/curves", json={"materials": ["N-BK7", "F2"], "samples": 11})
    assert r.status_code == 200
    assert len(r.json()["curves"][0]["index"]) == 11
    r = client.post("/api/v1/materials/resolve", json={"materials": ["N-BK7"], "wavelengths": [0.5875618]})
    assert r.json()["materials"]["N-BK7"]["index"][0] == pytest.approx(1.5168, abs=1e-5)


def test_evaluate_and_analyses():
    sysd = sample_system()
    r = client.post("/api/v1/system/evaluate", json={"system": sysd})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["paraxial"]["1"]["efl"] == pytest.approx(100.0, abs=0.01)
    assert len(body["rays"]) > 0
    for ep in ("spot", "rayfan", "field", "longitudinal", "chromatic", "paraxial", "wavefront", "opdfan", "psf", "mtf", "encircled", "throughput"):
        r = client.post(f"/api/v1/analysis/{ep}", json={"system": sysd})
        assert r.status_code == 200, (ep, r.text)


def test_structured_validation_error():
    r = client.post("/api/v1/system/evaluate", json={"system": {"surfaces": []}})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR" and err["details"]


def test_structured_system_error():
    sysd = sample_system()
    sysd["surfaces"][1]["material"] = "UNOBTAINIUM"
    r = client.post("/api/v1/system/evaluate", json={"system": sysd})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "SYSTEM_ERROR"


def test_samples_and_project_validate():
    r = client.get("/api/v1/samples")
    ids = [s["id"] for s in r.json()["samples"]]
    assert "achromat" in ids
    proj = client.get("/api/v1/samples/achromat").json()
    r = client.post("/api/v1/project/validate", json=proj)
    assert r.status_code == 200 and r.json()["notes"] == []
    assert client.get("/api/v1/samples/nope").status_code == 404


def test_optimisation_job_roundtrip():
    proj = client.get("/api/v1/samples/achromat-start").json()
    r = client.post("/api/v1/optimize/start", json={"system": proj["system"], "optimization": proj["optimization"]})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    for _ in range(600):
        s = client.get(f"/api/v1/optimize/{job_id}").json()
        if s["state"] in ("finished", "failed", "cancelled"):
            break
        time.sleep(0.1)
    assert s["state"] == "finished", s
    assert s["result"]["final_merit"] < s["result"]["initial_merit"]
    assert client.get("/api/v1/optimize/unknown").status_code == 404


def test_optimisation_config_error_is_reported():
    proj = client.get("/api/v1/samples/achromat").json()
    r = client.post("/api/v1/optimize/start", json={"system": proj["system"], "optimization": {"variables": [], "operands": []}})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "OPTIMIZATION_CONFIG"


def test_merit_endpoint():
    proj = client.get("/api/v1/samples/achromat-start").json()
    r = client.post("/api/v1/optimize/merit", json={"system": proj["system"], "optimization": proj["optimization"]})
    assert r.status_code == 200
    assert r.json()["merit"] > 0


def test_out_of_range_field_is_a_structured_error():
    r = client.post("/api/v1/analysis/psf", json={"system": sample_system(), "field": 9})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "BAD_REQUEST"
