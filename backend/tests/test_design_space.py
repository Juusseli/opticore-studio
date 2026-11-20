"""Design space map (designspace.py, workers.py): exact Pareto front, seeded plans and candidates, metrics equal
to the normal analyses of the stored design, the f/5 100 mm doublet benchmark, cancel keeping finished candidates,
and field-batched tracing identical to tracing field by field."""

import math
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore import workers
from opticore.api.main import app
from opticore.designspace import (
    ELEMENTS,
    METRICS,
    DesignSpaceError,
    DesignSpaceJobs,
    DesignSpaceSpec,
    glass_table,
    metrics,
    pareto_front,
    plan,
    run_candidate,
)
from opticore.model import OpticalSystem
from opticore.paraxial import compute_pupil
from opticore.project import Project
from opticore.raytrace import gauss_pupil, trace_fields, trace_pupil
from opticore.samples import SAMPLES, get_sample
from opticore.system import compile_system

client = TestClient(app, raise_server_exceptions=False)
F5 = DesignSpaceSpec(focal_length=100.0, f_number=5.0, half_field_deg=2.0, tolerances=False)


@pytest.fixture
def pool(monkeypatch):
    workers.shutdown()
    monkeypatch.setenv("OPTICORE_WORKERS", "2")
    yield
    workers.shutdown()


# ---------------------------------------------------------------------------------------------- Pareto front
def _brute_front(points, objectives):
    """Independent definition: keep p unless some q is no worse in every objective and better in one."""
    keep = []
    vals = {}
    for k, p in enumerate(points):
        if p is None or any(p.get(o) is None or not math.isfinite(p[o]) for o in objectives):
            continue
        vals[k] = [METRICS[o][0] * p[o] for o in objectives]
    for k, a in vals.items():
        dominated = False
        for j, b in vals.items():
            if j != k and all(y <= x for x, y in zip(a, b)) and any(y < x for x, y in zip(a, b)):
                dominated = True
                break
        if not dominated:
            keep.append(k)
    return keep


@pytest.mark.parametrize("seed", range(6))
def test_pareto_front_is_the_exact_non_dominated_set(seed):
    rng = np.random.default_rng(seed)
    objectives = [["rms_spot_um", "length_mm"], ["rms_spot_um", "length_mm", "mass_g"], ["mtf", "length_mm", "glass_cost"]][seed % 3]
    pts = []
    for _ in range(80):
        # coarse values make ties and duplicates common; some points miss a value
        p = {o: float(rng.integers(0, 6)) for o in METRICS}
        if rng.random() < 0.1:
            p[objectives[-1]] = None
        pts.append(p if rng.random() > 0.05 else None)
    front = pareto_front(pts, objectives)
    assert front == _brute_front(pts, objectives)
    # duplicates of a front point are all on the front; a larger MTF is better
    assert pareto_front([{"mtf": 0.5, "length_mm": 1.0}, {"mtf": 0.5, "length_mm": 1.0}, {"mtf": 0.6, "length_mm": 1.0}], ["mtf", "length_mm"]) == [2]
    assert pareto_front([{"rms_spot_um": 1.0, "length_mm": 2.0}] * 2, ["rms_spot_um", "length_mm"]) == [0, 1]
    with pytest.raises(DesignSpaceError):
        pareto_front(pts, ["nonsense"])


# ---------------------------------------------------------------------------------------------- plans and candidates
def test_plan_is_seeded_and_respects_the_specification():
    spec = DesignSpaceSpec(candidates=60, max_elements=3)
    a, b = plan(spec), plan(spec)
    assert a == b
    assert plan(spec.model_copy(update={"seed": 2})) != a
    topos = {t["topology"] for t in a}
    assert topos == {"singlet", "cemented_doublet", "air_spaced_doublet", "triplet"}
    assert all(ELEMENTS[t["topology"]] <= 3 for t in a) and len(a) == 60
    v = {g["name"]: g["V"] for g in glass_table(spec)}
    for t in a:
        if t["topology"] != "singlet":
            crown, flint = t["glasses"]
            assert v[flint] <= 0.8 * v[crown]
    # pairs are not repeated before every pair of the topology has been used once
    first = [tuple(t["glasses"]) for t in a if t["topology"] == "triplet" and t["variant"] == 0]
    assert len(first) == len(set(first))


def test_bad_specifications_are_refused():
    with pytest.raises(DesignSpaceError):
        plan(DesignSpaceSpec(glasses=["N-BK7", "NO-SUCH-GLASS"]))
    with pytest.raises(DesignSpaceError):
        plan(DesignSpaceSpec(max_elements=1, topologies=["triplet"]))
    with pytest.raises(DesignSpaceError):
        plan(DesignSpaceSpec(glasses=["N-BK7"], topologies=["cemented_doublet"]))  # no flint
    r = client.post("/api/v1/design-space/start", json={"spec": {"glasses": ["NOPE"]}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "DESIGN_SPACE"
    r = client.post("/api/v1/design-space/start", json={"spec": {"primary": 5}})
    assert r.status_code == 422


def test_candidate_is_reproducible_and_its_metrics_equal_the_normal_analyses():
    spec = F5.model_copy(update={"tolerances": True})
    task = {"index": 0, "topology": "cemented_doublet", "glasses": ["N-BAK1", "N-SF5"], "variant": 1, "seed": [1, 1, 7]}
    a = run_candidate(task, spec.model_dump(mode="json"), [])
    b = run_candidate(task, spec.model_dump(mode="json"), [])
    assert a["status"] == "finished" and a["feasible"], a.get("violations")
    assert a["metrics"] == b["metrics"] and a["system"] == b["system"]
    system = OpticalSystem.model_validate(a["system"])
    again = metrics(system, [], spec)
    assert again.keys() == a["metrics"].keys()
    for key, value in a["metrics"].items():  # one key at a time: pytest.approx does not compare nested values
        assert again[key] == (pytest.approx(value, rel=1e-12) if isinstance(value, (int, float, list)) and not isinstance(value, bool) else value), key
    m = a["metrics"]
    body = {"system": a["system"], "custom_materials": []}
    spot = client.post("/api/v1/analysis/spot", json=body).json()
    assert [f["rms_radius_um"] for f in spot["fields"]] == pytest.approx(m["rms_spot_fields_um"], rel=1e-12)
    mtf = client.post("/api/v1/analysis/mtf", json={**body, "max_frequency": spec.mtf_frequency, "samples": 4}).json()
    assert [0.5 * (f["tangential"][-1] + f["sagittal"][-1]) for f in mtf["fields"]] == pytest.approx(m["mtf_fields"], rel=1e-12)
    fc = client.post("/api/v1/analysis/field", json=body).json()
    prim = system.primary_wavelength
    row = next(p for p in fc["per_wavelength"] if p["wavelength"] == prim)
    assert row["distortion_percent"][-1] == pytest.approx(m["distortion_pct"], rel=1e-9)
    el = client.post("/api/v1/elements", json=body).json()
    assert el["total_mass_g"] == pytest.approx(m["mass_g"], rel=1e-12)
    ev = client.post("/api/v1/system/evaluate", json=body).json()
    assert ev["paraxial"][str(prim)]["total_track"] == pytest.approx(m["length_mm"], rel=1e-12)
    assert ev["paraxial"][str(prim)]["efl"] == pytest.approx(m["efl_mm"], rel=1e-12)
    assert m["tolerance_rss_um"] > 0


def test_f5_doublet_map_is_at_least_as_good_as_the_sample_achromat():
    """The specification of the sample achromat (f = 100 mm, F/5, 2 deg, F/d/C): the map's best doublet is at least as
    good as the sample (or within 5 %), by the field-mean RMS spot of the spot diagram."""
    sample = metrics(get_sample("achromat").system, [], F5)["rms_spot_um"]
    spec = F5.model_copy(update={"topologies": ["cemented_doublet", "air_spaced_doublet"], "candidates": 4})
    best = math.inf
    for t in plan(spec):
        r = run_candidate(t, spec.model_dump(mode="json"), [])
        if r["status"] == "finished" and r["feasible"]:
            best = min(best, r["metrics"]["rms_spot_um"])
    assert best <= 1.05 * sample, (best, sample)


# ---------------------------------------------------------------------------------------------- jobs on the process pool
def _wait(jobs, job, timeout=240.0):
    t0 = time.time()
    while job["state"] == "running":
        assert time.time() - t0 < timeout, "design space job did not finish"
        time.sleep(0.1)


def test_job_on_the_pool_matches_direct_runs_and_opens_as_a_project(pool):
    spec = F5.model_copy(update={"topologies": ["singlet", "cemented_doublet"], "candidates": 4})
    r = client.post("/api/v1/design-space/start", json={"spec": spec.model_dump(mode="json")})
    assert r.status_code == 200 and r.json()["total"] == 4
    jid = r.json()["job_id"]
    t0 = time.time()
    while True:
        s = client.get(f"/api/v1/design-space/{jid}").json()
        if s["state"] != "running":
            break
        assert time.time() - t0 < 240
        time.sleep(0.2)
    assert s["state"] == "finished" and s["done"] == 4 and s["failed"] == 0
    by_index = {c["index"]: c for c in s["candidates"]}
    assert "system" not in by_index[0] and by_index[0]["outline"]["items"]
    tasks = plan(spec)
    direct = run_candidate(tasks[2], spec.model_dump(mode="json"), [])
    assert by_index[2]["metrics"] == direct["metrics"]  # the worker computes the same numbers
    # the Pareto front over the default objectives (RMS spot, length, mass: the built-in glasses have no cost)
    assert s["objectives"] == ["rms_spot_um", "length_mm", "mass_g"]
    pts = [None] * 4
    for c in s["candidates"]:
        pts[c["index"]] = c["metrics"] if c["feasible"] else None
    assert s["pareto"] == pareto_front(pts, s["objectives"])
    two = client.get(f"/api/v1/design-space/{jid}", params={"objectives": "rms_spot_um,elements", "since": 3}).json()
    assert len(two["candidates"]) == 1 and two["pareto"] == pareto_front(pts, ["rms_spot_um", "elements"])
    # open: a valid project with the optimised prescription and its optimisation set-up
    c = client.get(f"/api/v1/design-space/{jid}/candidates/2").json()
    p = Project.model_validate(c["project"])
    assert p.system.model_dump(mode="json") == direct["system"] and p.optimization.variables
    assert client.get(f"/api/v1/design-space/{jid}/candidates/99").status_code == 404
    assert client.get("/api/v1/design-space/nope").status_code == 404


def test_cancel_stops_the_job_and_keeps_finished_candidates(pool):
    jobs = DesignSpaceJobs()
    spec = F5.model_copy(update={"topologies": ["singlet", "triplet"], "candidates": 12})
    job = jobs.start(spec)
    t0 = time.time()
    while not job["order"]:
        assert time.time() - t0 < 120
        time.sleep(0.05)
    jobs.cancel(job["id"])
    _wait(jobs, job, 60.0)
    s = jobs.snapshot(job)
    assert s["state"] == "cancelled" and 1 <= s["done"] < s["total"]
    assert all(c["status"] == "finished" for c in s["candidates"])
    assert time.time() - t0 < 60.0  # running candidates stop at their next merit evaluation


def test_a_run_nobody_watches_is_cancelled(pool):
    jobs = DesignSpaceJobs(abandon_s=0.5)
    job = jobs.start(F5.model_copy(update={"topologies": ["triplet"], "candidates": 6}))
    _wait(jobs, job, 60.0)
    s = jobs.snapshot(job)
    assert s["state"] == "cancelled" and s["abandoned"] and s["done"] < s["total"]


# ---------------------------------------------------------------------------------------------- batched tracing
@pytest.mark.parametrize("sid", list(SAMPLES))
def test_tracing_fields_together_equals_tracing_them_one_by_one(sid):
    """The merit function and the automatic apertures trace all fields of a wavelength in one call; every ray is
    traced on its own, so the results are identical to the last bit."""
    p = get_sample(sid)
    cs = compile_system(p.system, p.custom_materials)
    pupil = compute_pupil(cs)
    px, py, _ = gauss_pupil(4)
    nf = len(cs.model.fields)
    for w in range(len(cs.wavelengths)):
        for clip in (True, False):
            together = trace_fields(cs, w, range(nf), px, py, pupil, clip=clip, aim_cache={}, vignetting=True)
            for f in range(nf):
                alone = trace_pupil(cs, w, f, px, py, pupil, clip=clip, aim_cache={}, vignetting=True)
                for attr in ("local", "points", "dirs", "opl", "status", "intensity", "fail_surface"):
                    assert np.array_equal(getattr(alone, attr), getattr(together[f], attr), equal_nan=True), (sid, w, f, attr)
