import time

import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.model import OpticalSystem
from opticore.optimize.engine import Control, Progress, optimize, validate_spec
from opticore.optimize.merit import MeritFunction, Operand, OptimizationSpec, Variable
from opticore.samples import get_sample

CANDS = ["N-BK7", "N-SK16", "N-BAF10", "N-LASF9"]


def _singlet(material="N-BK7") -> OpticalSystem:
    d = get_sample("singlet").system.model_dump()
    d["surfaces"][1]["material"] = material
    d["fields"] = d["fields"][:2]
    return OpticalSystem.model_validate(d)


def _spec(cont=True, cands=CANDS, budget=600) -> OptimizationSpec:
    vs = [Variable(surface_id="s1", parameter="material", candidates=cands)]
    if cont:
        vs += [
            Variable(surface_id="s1", parameter="curvature", min=1 / 400, max=1 / 20),
            Variable(surface_id="s2", parameter="thickness", min=40.0, max=200.0),
        ]
    ops = [Operand(type="rms_spot", rings=2), Operand(type="efl", target=100.0, weight=5.0)]
    return OptimizationSpec(variables=vs, operands=ops, max_evaluations=budget)


def test_pure_substitution_equals_brute_force_minimum():
    # no continuous variables: the substitution must pick the argmin over candidates (weighted merit function)
    spec = _spec(cont=False).model_copy(update={"constraints": "penalty"})
    res = optimize(_singlet(), spec)
    merits = {}
    for g in CANDS:
        mf = MeritFunction(_singlet(g), OptimizationSpec(operands=spec.operands))
        merits[g] = mf.merit(mf.x0)
    best = min(merits, key=merits.get)
    assert res["materials"][0]["final"] == best
    assert res["final_merit"] == pytest.approx(merits[best], rel=1e-12)
    assert res["algorithm"] == "glass_substitution"


def test_pure_substitution_with_an_exact_target_picks_the_glass_nearest_to_meeting_it():
    # exact constraints: no glass meets the focal length without a variable, so the feasibility rules choose the
    # glass that misses it least, and the run says it is infeasible
    spec = _spec(cont=False)
    spec = spec.model_copy(update={"operands": [spec.operands[0], spec.operands[1].model_copy(update={"target": 90.0})]})
    res = optimize(_singlet(), spec)
    miss = {}
    for g in CANDS:
        mf = MeritFunction(_singlet(g), OptimizationSpec(operands=spec.operands))
        miss[g] = abs(mf.evaluate(mf.x0)[1][1]["value"] - 90.0)
    assert res["materials"][0]["final"] == min(miss, key=miss.get) == "N-SK16"  # 83.3 mm; N-BK7 gives 100 mm
    assert res["status"] == "infeasible" and res["constraint_mode"] == "exact" and not res["constraints"][0]["met"]
    # the glass that meets the focal length wins over the sharper one that does not
    spec = _spec(cont=False)
    res = optimize(_singlet("N-SK16"), spec)
    assert res["materials"][0]["final"] == "N-BK7" and res["status"] == "converged" and res["constraints"][0]["met"]


def test_substitution_with_reoptimisation_matches_exhaustive_search():
    spec = _spec()
    res = optimize(_singlet(), spec)
    exhaustive = {}
    cont = OptimizationSpec(variables=[v for v in spec.variables if v.parameter != "material"], operands=spec.operands, max_evaluations=400)
    for g in CANDS:
        exhaustive[g] = optimize(_singlet(g), cont)["final_merit"]
    best = min(exhaustive, key=exhaustive.get)
    assert res["materials"][0]["final"] == best
    assert res["final_merit"] <= exhaustive[best] * (1 + 1e-6)
    out = OpticalSystem.model_validate(res["system"])
    assert out.surfaces[1].material == best
    assert res["final_merit"] < res["initial_merit"]
    assert any("glass combinations" in n for n in res["notes"])


def test_candidates_must_cover_system_wavelengths_and_exist():
    # a tabulated custom glass measured only in the red cannot serve F, d, C
    red = {"name": "REDONLY", "formula": "tabulated", "table": [[0.6, 1.5], [0.7, 1.49]], "lambda_min": 0.6, "lambda_max": 0.7}
    sysm = _singlet()
    with pytest.raises(ValueError):
        validate_spec(sysm, _spec(cands=["REDONLY"]), [red])
    with pytest.raises(ValueError):
        validate_spec(sysm, _spec(cands=["N-BK7", "NOPE"]))


@pytest.mark.parametrize(
    "variable",
    [
        Variable(surface_id="s2", parameter="material"),  # air after the surface
        Variable(surface_id="s1", parameter="material", configuration=0),
    ],
)
def test_invalid_material_variables(variable):
    with pytest.raises(ValueError):
        validate_spec(_singlet(), OptimizationSpec(variables=[variable], operands=[Operand(type="efl", target=100)]))


def test_material_set_per_configuration_cannot_be_substituted():
    d = _singlet().model_dump()
    d["multi_config"] = {"names": ["a", "b"], "active": 0, "operands": [{"parameter": "material", "surface_id": "s1", "values": ["N-BK7", "F2"]}]}
    with pytest.raises(ValueError):
        validate_spec(OpticalSystem.model_validate(d), _spec(cont=False))


def test_merit_function_rejects_material_variables_directly():
    with pytest.raises(ValueError):
        MeritFunction(_singlet(), _spec())


def test_cancellation_returns_best_so_far():
    ctl = Control()
    prog = Progress()
    ctl.cancel.set()
    res = optimize(_singlet(), _spec(), (), prog, ctl)
    assert res["status"] == "cancelled"
    assert res["materials"][0]["final"] in CANDS


def test_glass_job_via_api():
    c = TestClient(app)
    body = {"system": _singlet().model_dump(), "optimization": _spec(cont=False).model_dump()}
    m = c.post("/api/v1/optimize/merit", json=body)
    assert m.status_code == 200  # live merit ignores material variables
    jid = c.post("/api/v1/optimize/start", json=body).json()["job_id"]
    t0 = time.time()
    while (s := c.get(f"/api/v1/optimize/{jid}").json())["state"] not in ("finished", "failed", "cancelled"):
        assert time.time() - t0 < 60
        time.sleep(0.05)
    assert s["state"] == "finished", s["error"]
    assert s["result"]["materials"][0]["final"] in CANDS
    assert s["best_materials"] is not None
    bad = c.post("/api/v1/optimize/start", json={**body, "optimization": {**body["optimization"], "variables": [{"surface_id": "s2", "parameter": "material"}]}})
    assert bad.status_code == 422
