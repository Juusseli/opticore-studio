"""Regression tests for defects found in an audit of the optimiser (optimize/*.py, tolerance.py): each test names the
defect it covers and the numbers the code gave before the fix ("Before:").

* Global search, exact limits: the polish starts at differential evolution's own optimum; out of budget is
  max_evaluations in every driver; the final pick takes only a converged solver run.
* Glass substitution ranks trials by the report's rule; trials skip their sensitivities.
* Tolerancing with the criterion "merit": exact limits apart, per-configuration operands of the active configuration.
* Operands: explicit fields and wavelengths of weight 0, weight-0 limits, the RMS spot limit in um, index checks,
  limits that cannot be evaluated.
* Bookkeeping: at_bound, finite-difference steps at both bounds, evaluation counts, trade-off default targets.
"""

from __future__ import annotations

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.optimize._numdiff import _adjust_scheme_to_bounds

import opticore.optimize.engine as engine
from opticore.api.main import app
from opticore.model import OpticalSystem
from opticore.optimize import parallel, tradeoff
from opticore.optimize.constrained import V_TOL, Constraints
from opticore.optimize.engine import Progress, _at_bound, optimize, validate_spec
from opticore.optimize.merit import MeritFunction, Operand, OptimizationSpec, Variable, is_active
from opticore.samples import get_sample
from opticore.tolerance import Evaluator, Tolerance, ToleranceError, ToleranceSpec, analyze

BEND = [
    {"surface_id": "s1", "parameter": "curvature", "min": -0.05, "max": 0.05},
    {"surface_id": "s2", "parameter": "curvature", "min": -0.05, "max": 0.05},
    {"surface_id": "s2", "parameter": "thickness", "min": 50, "max": 200},
]
OPS = [{"type": "rms_spot"}, {"type": "efl", "target": 95.0}, {"type": "min_edge_thickness", "surface_id": "s1", "target": 1.0}]


@pytest.fixture(autouse=True)
def _serial(monkeypatch):
    monkeypatch.setenv("OPTICORE_PARALLEL_JACOBIAN", "0")


def _spec(variables, operands, **kw) -> OptimizationSpec:
    return OptimizationSpec(variables=[Variable(**v) for v in variables], operands=[Operand(**o) for o in operands], **kw)


def _key(system, spec, x):
    """Constraints.key of a design (feasible to V_TOL: (0, merit))."""
    mf = MeritFunction(system, spec, split=True)
    r, _ = mf.evaluate(np.asarray(x, dtype=float))
    return Constraints(mf).key(r, mf.merit_from_residuals(r))


def _final(res):
    return np.array([v["final"] for v in res["variables"]])


def _with(system: OpticalSystem, **changes) -> OpticalSystem:
    d = system.model_dump()
    for path, value in changes.items():
        kind, idx, attr = path.split("__")
        d[kind][int(idx)][attr] = value
    return OpticalSystem.model_validate(d)


# ------------------------------------------------------------------------------------------------ drivers
def test_1_global_polish_starts_at_the_differential_evolution_optimum(monkeypatch):
    """Before: the polish started at the design with the smallest violation (DE penalty 107.7, spot 355 um) and DE's
    own optimum (penalty 42.0) was discarded; the run returned 28.6 um at budget 600."""
    seen = {}
    de_orig, ls_orig = engine.differential_evolution, engine.least_squares

    def de(*a, **k):
        r = de_orig(*a, **k)
        seen["de"] = (np.array(r.x), float(r.fun))
        return r

    def ls(fun, x0, *a, **k):
        seen.setdefault("polish", np.array(x0, dtype=float))
        return ls_orig(fun, x0, *a, **k)

    monkeypatch.setattr(engine, "differential_evolution", de)
    monkeypatch.setattr(engine, "least_squares", ls)
    p = get_sample("singlet")
    sp = _spec(BEND, OPS, algorithm="global", max_evaluations=300)
    res = optimize(p.system, sp)
    x_de, f_de = seen["de"]
    assert np.array_equal(seen["polish"], x_de)
    mf = MeritFunction(p.system, sp, split=True)
    cons = Constraints(mf)
    cons.start(mf.evaluate(mf.x0)[0])
    assert cons.penalty(mf.evaluate(seen["polish"])[0]) == pytest.approx(f_de, rel=1e-12)
    assert all(c["met"] for c in res["constraints"])


@pytest.mark.parametrize(("algorithm", "budget", "mode"), [("multistart", 60, "exact"), ("global", 120, "exact"), ("multistart", 60, "penalty"), ("local", 30, "exact")])
def test_2_a_run_out_of_budget_is_max_evaluations(algorithm, budget, mode):
    """Before: exact global (120) and multistart (60), and weighted multistart (60), reported 'converged' with
    '3 of 3 local runs completed' although every run stopped on its share."""
    p = get_sample("singlet")
    res = optimize(p.system, _spec(BEND, OPS[:2], algorithm=algorithm, max_evaluations=budget, multistart_runs=3, constraints=mode))
    assert res["status"] == "max_evaluations"
    assert res["evaluations"] <= budget


def test_2_a_run_that_converges_within_its_share_is_converged():
    p = get_sample("singlet")
    res = optimize(p.system, _spec(BEND, OPS[:2], algorithm="multistart", max_evaluations=1200, multistart_runs=2))
    assert res["status"] == "converged" and res["message"].startswith("2 of 2")
    # with half the budget the second start's run stops on its share (299 evaluations): not completed
    half = optimize(p.system, _spec(BEND, OPS[:2], algorithm="multistart", max_evaluations=600, multistart_runs=2))
    assert half["status"] == "max_evaluations" and half["message"].startswith("1 of 2")


def test_9_the_final_pick_takes_only_a_converged_solver_run():
    """Before (local, budget 30): the pick returned the solver's last iterate, which met the EFL only within one
    tolerance (key (1, 0.785)), over a recorded design that met every limit to V_TOL (key (0, 0.02527))."""
    p = get_sample("singlet")
    sp = _spec(BEND, OPS, max_evaluations=30)
    pr = Progress()
    res = optimize(p.system, sp, progress=pr)
    assert res["status"] == "max_evaluations"
    best = _key(p.system, sp, pr.best_x)
    assert best[0] == 0.0
    assert _key(p.system, sp, _final(res)) == pytest.approx(best, rel=1e-12)


# ------------------------------------------------------------------------------------------------ glass substitution
def test_3_and_12_glass_trials_that_meet_every_limit_are_kept(monkeypatch):
    """Before (achromat, d2 glass, 300 evaluations, exact): every trial was rejected (keys (1, 0.126), (1, 0.0137),
    ...: not within V_TOL) although each met both limits; the result stayed F2 at 0.011453 after 196 evaluations,
    the trials ran their sensitivities and the evaluations exceeded their budgets (51 of 42)."""
    p = get_sample("achromat")
    inner = []
    orig = engine._optimize_continuous

    def wrapped(system, spec, *a, **k):
        res = orig(system, spec, *a, **k)
        inner.append((spec.max_evaluations, res, k.get("sensitivities", True)))
        return res

    monkeypatch.setattr(engine, "_optimize_continuous", wrapped)
    variables = [v.model_dump() for v in p.optimization.variables] + [{"surface_id": "d2", "parameter": "material", "candidates": ["F2", "SF2", "N-SF5", "N-SF6"]}]
    sp = _spec(variables, [o.model_dump() for o in p.optimization.operands], max_evaluations=300)
    res = optimize(p.system, sp)
    assert res["materials"][0]["final"] != "F2"
    assert res["final_merit"] < 0.9 * res["initial_merit"]
    assert all(c["met"] for c in res["constraints"])
    # the search keeps to the budget; the trials skip their sensitivities and each closes with one evaluation
    assert res["evaluations"] <= 300
    assert all(not sens and r["evaluations"] <= b and r["closing_evaluations"] == 1 for b, r, sens in inner)
    assert all(v["sensitivity"] is None for _, r, _ in inner for v in r["variables"])
    nvar = len(p.optimization.variables)
    assert res["closing_evaluations"] == len(inner) + 1 + 2 * nvar
    assert all(v["sensitivity"] is not None for v in res["variables"])


# ------------------------------------------------------------------------------------------------ tolerancing, criterion merit
def _tol_spec(**kw) -> ToleranceSpec:
    tols = [Tolerance(type="radius", surface_id="d1", min=-0.05, max=0.05), Tolerance(type="thickness", surface_id="d1", min=-0.05, max=0.05)]
    return ToleranceSpec(tolerances=tols, criterion="merit", monte_carlo_trials=4, compensators=[], **kw)


def test_4_the_merit_criterion_keeps_exact_limits_apart():
    """Before: the criterion took every operand as a weighted residual whatever the optimisation's mode (achromat
    nominal 0.00672 against the optimiser's 0.011453)."""
    p = get_sample("achromat")
    ops = list(p.optimization.operands)
    mf = MeritFunction(p.system, p.optimization, split=True)
    objective = mf.merit_from_residuals(mf.evaluate(mf.x0)[0])
    r = analyze(p.system, _tol_spec(), merit_operands=ops, merit_constraints="exact")
    assert r["nominal"] == pytest.approx(objective, rel=1e-9) and objective == pytest.approx(0.011453, rel=1e-4)
    lim = {row["type"]: row for row in r["limits"]}
    assert set(lim) == {"efl", "min_edge_thickness"} and [row["index"] for row in r["limits"]] == [1, 3]
    assert lim["efl"]["nominal"] == pytest.approx(100.0, abs=1e-3) and lim["efl"]["met_nominal"] and lim["efl"]["kind"] == "target"
    assert lim["min_edge_thickness"]["target"] == 1.5 and lim["min_edge_thickness"]["monte_carlo"]["trials"] == 4
    assert all(len(t["limits"]) == 2 for t in [r["monte_carlo"]["best_trial"], r["monte_carlo"]["worst_trial"]])
    assert all(len(row["at_min_limits"]) == 2 for row in r["sensitivity"])
    assert any("reported apart" in n for n in r["notes"])
    # weighted limits: every operand in the criterion, as before
    pen = analyze(p.system, _tol_spec(), merit_operands=ops, merit_constraints="penalty")
    assert pen["nominal"] == pytest.approx(0.00672002, rel=1e-5) and pen["limits"] is None
    # a merit function of limits alone has no criterion with exact limits
    with pytest.raises(ToleranceError):
        Evaluator(p.system, _tol_spec(), [], [ops[1], ops[3]], merit_constraints="exact")


def test_4_compensators_minimise_the_goals_with_exact_limits():
    p = get_sample("achromat")
    from opticore.tolerance import Compensator

    spec = _tol_spec().model_copy(update={"compensators": [Compensator(surface_id="d3", parameter="thickness", range=2.0)]})
    ev = Evaluator(p.system, spec, [], list(p.optimization.operands), merit_constraints="exact")
    out = ev.evaluate(np.array([0.05, 0.0]))
    assert out["value"] < out["uncompensated"] and out["compensators"][0] != 0.0
    assert [q["met"] for q in out["limits"]] == [False, True]  # a radius error moves the EFL by more than its tolerance


def test_4_the_tolerance_api_passes_the_constraint_mode():
    p = get_sample("achromat")
    c = TestClient(app)
    body = {"system": p.system.model_dump(), "tolerance": _tol_spec().model_copy(update={"monte_carlo_trials": 0}).model_dump(), "optimization": p.optimization.model_dump()}
    jid = c.post("/api/v1/tolerance/start", json=body).json()["job_id"]
    t0 = time.time()
    while (s := c.get(f"/api/v1/tolerance/{jid}").json())["state"] not in ("finished", "failed", "cancelled"):
        assert time.time() - t0 < 120
        time.sleep(0.05)
    assert s["state"] == "finished", s["error"]
    assert s["result"]["nominal"] == pytest.approx(0.011453, rel=1e-4) and len(s["result"]["limits"]) == 2


def test_5_the_merit_criterion_uses_the_active_configuration():
    """Before: 'Operand rms_spot refers to configuration 2, which does not exist' (two conjugates); with
    configuration 2 active an operand pinned to configuration 1 silently evaluated configuration 2 (0.0181)."""
    p = get_sample("achromat-two-conjugates")
    spec = ToleranceSpec(tolerances=[Tolerance(type="thickness", surface_id="d1", min=-0.05, max=0.05)], criterion="merit", monte_carlo_trials=0, compensators=[])
    ops = list(p.optimization.operands)  # rms_spot in configuration 1 and in configuration 2

    def spot(system, k):
        mf = MeritFunction(system, OptimizationSpec(operands=[Operand(type="rms_spot", configuration=k)]))
        return mf.merit(mf.x0)

    r0 = analyze(p.system, spec, merit_operands=ops)
    assert r0["nominal"] == pytest.approx(spot(p.system, p.system.multi_config.active), rel=1e-9)
    assert any("other configurations are left out" in n for n in r0["notes"])
    d = p.system.model_dump()
    d["multi_config"]["active"] = 1
    s2 = OpticalSystem.model_validate(d)
    r1 = analyze(s2, spec, merit_operands=ops)
    assert r1["nominal"] == pytest.approx(spot(s2, 1), rel=1e-9)
    assert spot(s2, 0) != pytest.approx(spot(s2, 1), rel=1e-3)
    with pytest.raises(ToleranceError, match="active configuration"):
        analyze(s2, spec, merit_operands=[ops[0]])  # only configuration 1's operand: nothing to tolerance in 2
    with pytest.raises(ToleranceError, match="does not exist"):
        analyze(s2, spec, merit_operands=[Operand(type="rms_spot", configuration=5)])


def test_16_the_rms_wavefront_criterion_is_polychromatic():
    """ADR-039: the rms_wavefront operand without a wavelength is polychromatic, and so is the criterion (the docs
    said 'primary wavelength')."""
    p = get_sample("singlet")
    spec = ToleranceSpec(tolerances=[Tolerance(type="thickness", surface_id="s1", min=-0.1, max=0.1)], criterion="rms_wavefront", rings=3)
    nominal = Evaluator(p.system, spec, []).evaluate()["value"]

    def wavefront(wavelength):
        mf = MeritFunction(p.system, OptimizationSpec(operands=[Operand(type="rms_wavefront", rings=3, wavelength=wavelength)]))
        return mf.merit(mf.x0)

    assert nominal == pytest.approx(wavefront(None), rel=1e-12)
    assert nominal > 1.5 * wavefront(p.system.primary_wavelength)  # the singlet's colour


# ------------------------------------------------------------------------------------------------ operands
def test_6_a_selected_field_or_wavelength_of_weight_zero_is_measured():
    """Before: the singlet's field 3 with weight 0 gave rms_spot 0.0 at field 3 (true 43.9 um) and rms_wavefront 0,
    so a limit on it was always met."""
    p = get_sample("singlet")
    s_f = _with(p.system, fields__2__weight=0.0)
    s_w = _with(p.system, wavelengths__0__weight=0.0)
    s_fw = _with(s_f, wavelengths__0__weight=0.0)

    def value(system, **o):
        mf = MeritFunction(system, OptimizationSpec(operands=[Operand(**o)]))
        return mf.evaluate(mf.x0)[1][0]["value"]

    cases = [(s_f, {"type": "rms_spot", "field": 2}), (s_f, {"type": "rms_wavefront", "field": 2}), (s_w, {"type": "rms_spot", "wavelength": 0}), (s_w, {"type": "rms_wavefront", "wavelength": 0}), (s_fw, {"type": "rms_spot", "field": 2, "wavelength": 0})]
    for s, o in cases:
        v = value(s, **o)
        assert v > 0 and v == pytest.approx(value(p.system, **o), rel=1e-12)
    assert value(s_f, type="rms_spot", field=2) == pytest.approx(43.9, abs=0.1)
    # a limit on that field is not met
    mf = MeritFunction(s_f, OptimizationSpec(operands=[Operand(type="rms_spot", field=0), Operand(type="rms_spot", field=2, target=0.01, role="constraint")]), split=True)
    assert not mf.evaluate(mf.x0)[1][1]["met"]


def test_7_a_limit_with_weight_zero_is_still_a_limit():
    """Before: rms_spot + efl 95 with weight 0 ran in weighted mode without the EFL (constraints None, EFL 107.5 after the run)."""
    p = get_sample("singlet")
    variables = [{"surface_id": "s1", "parameter": "curvature"}, {"surface_id": "s2", "parameter": "curvature"}, BEND[2]]
    sp = _spec(variables, [{"type": "rms_spot"}, {"type": "mtf", "frequency": 20, "enabled": False}, {"type": "efl", "target": 95.0, "weight": 0.0}], max_evaluations=200)
    res = optimize(p.system, sp)
    assert res["constraint_mode"] == "exact"
    row = res["constraints"][0]
    assert row["index"] == 1 and row["type"] == "efl" and row["met"] and abs(row["after"] - 95.0) <= V_TOL * row["tolerance"]
    # one numbering everywhere: the merit function's operands, the breakdowns, the constraint rows, the trade-off
    assert [o.type for o in sp.operands if is_active(o)] == ["rms_spot", "efl"] == [b["type"] for b in res["operands_after"]]
    assert tradeoff.active_index(sp, 1) == 2
    # weighted limits: the weight-0 limit is in the breakdown and contributes nothing
    pen = MeritFunction(p.system, sp.model_copy(update={"constraints": "penalty"}))
    r, b = pen.evaluate(pen.x0)
    assert [x["type"] for x in b] == ["rms_spot", "efl"] and b[1]["contribution"] == 0.0
    # the merit endpoint decides the mode like the optimiser
    out = TestClient(app).post("/api/v1/optimize/merit", json={"system": p.system.model_dump(), "optimization": sp.model_dump()}).json()
    assert out["constraint_mode"] == "exact" and out["operands"][1]["role"] == "constraint"
    # weighted mode without any weight is still refused
    with pytest.raises(ValueError, match="weight above 0"):
        MeritFunction(p.system, _spec(variables, [{"type": "efl", "target": 95.0, "weight": 0.0}], constraints="penalty"))


def test_8_an_rms_spot_limit_row_is_in_um():
    """Before: target 0.03, tolerance 1e-05 and relaxed target 0.0305 (mm) beside before/after 34.3 / 30.0 (um)."""
    p = get_sample("singlet")
    sp = _spec(BEND, [{"type": "efl", "target": 95.0, "role": "objective"}, {"type": "rms_spot", "target": 0.03, "role": "constraint"}], max_evaluations=300)
    res = optimize(p.system, sp)
    row = res["constraints"][0]
    assert row["unit"] == "um" and row["target"] == pytest.approx(30.0) and row["tolerance"] == pytest.approx(0.01)
    assert row["before"] > row["target"] and row["met"] and row["after"] <= row["target"] + row["tolerance"]
    pr = row["price"]
    assert pr["step"] == pytest.approx(0.5) and pr["relaxed_target"] == pytest.approx(row["target"] + pr["step"])
    # the trade-off speaks the row's unit
    ts = tradeoff.default_targets(sp, 1)
    assert all(t > 0 for t in ts) and any(t == pytest.approx(30.0, rel=1e-12) for t in ts) and min(ts) == pytest.approx(26.0)


def test_14_a_limit_that_cannot_be_evaluated_is_refused_at_set_up():
    """Before: magnification on the infinite-conjugate singlet gave g = 1e6 in every evaluation: 18 outer
    iterations, 307 evaluations, status max_evaluations."""
    p = get_sample("singlet")
    sp = _spec(BEND, [{"type": "rms_spot"}, {"type": "magnification", "target": -0.1}], max_evaluations=300)
    with pytest.raises(ValueError, match="cannot be evaluated at the starting design: magnification"):
        validate_spec(p.system, sp)
    t0 = time.time()
    with pytest.raises(ValueError, match="magnification"):
        optimize(p.system, sp)
    assert time.time() - t0 < 5
    r = TestClient(app).post("/api/v1/optimize/start", json={"system": p.system.model_dump(), "optimization": sp.model_dump()})
    assert r.status_code == 422 and r.json()["error"]["code"] == "OPTIMIZATION_CONFIG"
    # weighted, it stays a (failing) residual as before
    validate_spec(p.system, sp.model_copy(update={"constraints": "penalty"}))


def test_15_field_and_wavelength_indices_are_checked():
    """Before: rms_spot field 5 passed the set-up and raised IndexError in the first evaluation (/optimize/merit
    answered 500)."""
    p = get_sample("singlet")
    for o in ({"type": "rms_spot", "field": 5}, {"type": "rms_wavefront", "wavelength": 3}, {"type": "efl", "target": 95.0, "wavelength": 7}, {"type": "max_cra", "field": -1}):
        with pytest.raises(ValueError, match="does not exist"):
            MeritFunction(p.system, OptimizationSpec(operands=[Operand(**o)]))
    MeritFunction(p.system, OptimizationSpec(operands=[Operand(type="efl", target=95.0, field=9)]))  # efl reads no field
    r = TestClient(app).post("/api/v1/optimize/merit", json={"system": p.system.model_dump(), "optimization": _spec([], [{"type": "rms_spot", "field": 5}]).model_dump()})
    assert r.status_code == 422 and "field 6" in r.json()["error"]["message"]


# ------------------------------------------------------------------------------------------------ bookkeeping
def test_10_a_variable_on_its_bound_is_at_bound():
    """Before: the weighted run ended at thickness 6 - 3.4e-11 against max 6 and reported at_bound False."""
    v = Variable(surface_id="s1", parameter="thickness", min=1.0, max=6.0)
    assert _at_bound(v, 6.0 - 3.4e-11) and _at_bound(v, 1.0 + 1e-10) and not _at_bound(v, 6.0 - 1e-7)
    p = get_sample("singlet")
    variables = [{"surface_id": "s1", "parameter": "curvature"}, {"surface_id": "s2", "parameter": "curvature"}, BEND[2], {"surface_id": "s1", "parameter": "thickness", "min": 1.0, "max": 6.0}]
    res = optimize(p.system, _spec(variables, [{"type": "rms_spot"}, {"type": "efl", "target": 95.0}], max_evaluations=400, constraints="penalty"))
    t = res["variables"][3]
    assert abs(t["final"] - 6.0) < 1e-9 and t["at_bound"]


def test_11_finite_difference_steps_respect_both_bounds_like_scipy():
    """Before: a step from a variable on its lower bound with x < 0 left the bound (only the upper one flipped)."""
    rng = np.random.default_rng(3)
    lo = np.array([-0.05, -0.05, 0.0, 1.0, -np.inf, -2.0, -1e-8])
    hi = np.array([0.05, 0.05, 1e-8, 6.0, np.inf, 2.0, 1e-8])
    for x in [lo.clip(-1e300), hi.clip(None, 1e300), np.clip(rng.normal(size=7), lo, hi), np.array([-0.05, 0.05, 0.0, 6.0, 0.0, -2.0, 0.0])]:
        x = np.clip(x, lo, hi)
        h = 1e-7 * np.where(x >= 0, 1.0, -1.0) * np.maximum(1.0, np.abs(x))
        ref, _ = _adjust_scheme_to_bounds(x, h, 1, "1-sided", lo, hi)
        dx = parallel.fd_steps(x, lo, hi, 1e-7)
        assert np.allclose(dx, (x + ref) - x, rtol=1e-12, atol=0.0)
        ulp = 1e-15 * np.maximum(1.0, np.abs(x))
        assert np.all(x + dx >= lo - ulp) and np.all(x + dx <= hi + ulp)
    assert parallel.fd_steps(np.array([-0.05]), np.array([-0.05]), np.array([0.05]), 1e-7)[0] > 0


def test_12_evaluations_count_the_search_and_agree_with_the_pool(monkeypatch):
    """Before: a local exact run with budget 30 reported 37 evaluations (the closing evaluation and 2n sensitivity
    points), and only 31 with the pool, which did not count its sensitivity points."""
    p = get_sample("singlet")
    sp = _spec(BEND, OPS[:2], max_evaluations=30)
    serial = optimize(p.system, sp)
    monkeypatch.setenv("OPTICORE_PARALLEL_JACOBIAN", "force")
    pool = optimize(p.system, sp)
    assert pool["parallel"] is not None
    for r in (serial, pool):
        assert r["evaluations"] <= 30 and r["closing_evaluations"] == 1 + 2 * len(BEND)
    assert pool["evaluations"] == serial["evaluations"]


def test_13_trade_off_default_targets_are_possible():
    """Before: rms_spot 0.002 -> [-0.002, -0.001, 0, ...]; mtf 0.95 -> [..., 0.99, 1.03, 1.07, 1.11]."""

    def targets(**o):
        return tradeoff.default_targets(OptimizationSpec(operands=[Operand(**o)]), 0)

    spot = targets(type="rms_spot", target=0.002, role="constraint")
    assert spot == pytest.approx([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]) and all(t > 0 for t in spot)  # um
    mtf = targets(type="mtf", target=0.95, frequency=30.0, role="constraint")
    assert max(mtf) == 1.0 and len(mtf) == len(set(mtf)) and min(mtf) == pytest.approx(0.79)
    for kind in ("throughput", "detector_power", "min_relative_illumination", "surface_reflectance"):
        ts = targets(type=kind, target=0.99 if kind != "surface_reflectance" else 0.002, role="constraint", detector_id="d" if kind == "detector_power" else None)
        assert all(0.0 < t <= 1.0 for t in ts) and len(ts) == len(set(ts))
    assert all(t > 0 for t in targets(type="rms_wavefront", target=0.01, role="constraint"))
    assert all(t > 0 for t in targets(type="detector_size", target=0.005, role="constraint", detector_id="d"))
    assert targets(type="max_thickness", surface_id="s1", target=6.0) == pytest.approx([6.0 + 0.24 * k for k in range(-4, 5)])
