"""Exact constraints: the augmented Lagrangian around the least-squares solver (optimize/constrained.py, ADR-042)."""

import math

import numpy as np
import pytest

from opticore.optimize.constrained import STATIONARY, V_TOL
from opticore.optimize.engine import optimize
from opticore.optimize.merit import MeritFunction, Operand, OptimizationSpec, Variable, constraint_scale, constraint_value
from opticore.samples import singlet

BEND = [{"surface_id": "s1", "parameter": "curvature"}, {"surface_id": "s2", "parameter": "curvature"}, {"surface_id": "s2", "parameter": "thickness", "min": 50, "max": 200}]
THICK = [{"surface_id": "s1", "parameter": "thickness", "min": 1.0, "max": 10.0}]


def _spec(variables, operands, **kw) -> OptimizationSpec:
    return OptimizationSpec(variables=[Variable(**v) for v in variables], operands=[Operand(**o) for o in operands], **kw)


def _row(res, type_):
    return next(c for c in res["constraints"] if c["type"] == type_)


def test_the_split_merit_function_keeps_constraints_apart():
    p = singlet()
    ops = [{"type": "rms_spot"}, {"type": "efl", "target": 95.0}, {"type": "min_edge_thickness", "surface_id": "s1", "target": 2.0}, {"type": "fnum", "target": 9.0, "role": "objective"}]
    spec = _spec(BEND, ops)
    mf = MeritFunction(p.system, spec, split=True)
    assert mf.roles == ["objective", "constraint", "constraint", "objective"]
    r, b = mf.evaluate(mf.x0)
    mask, cidx = mf.layout()
    assert len(r) == int(mask.sum()) + 2 and list(cidx) == [int(mask[: cidx[0]].sum()), int(mask[: cidx[0]].sum()) + 1]
    # a constraint's entry is its normalised signed value: (value - target) / tolerance, negative when a lower bound holds
    assert r[cidx[0]] == pytest.approx((b[1]["value"] - 95.0) / constraint_scale(mf.operands[1]), rel=1e-12)
    assert r[cidx[1]] == pytest.approx(-(b[2]["value"] - 2.0) / 1e-3, rel=1e-12) and b[2]["met"]
    # the objective's weights are its own: the same objective residuals as a penalty merit function of those operands
    ref = MeritFunction(p.system, _spec(BEND, [ops[0], ops[3]]))
    assert mf.merit_from_residuals(r) == pytest.approx(ref.merit(ref.x0), rel=1e-12)
    # |distortion| <= target: violated in either direction
    o = Operand(type="max_distortion", target=0.5)
    assert constraint_value(o, -0.7) == pytest.approx(0.2 / 1e-3) and constraint_value(o, 0.3) < 0


def test_a_target_is_met_to_its_tolerance_with_the_penalty_result():
    p = singlet()
    spec = _spec(BEND, [{"type": "rms_spot"}, {"type": "efl", "target": 95.0}], max_evaluations=600)
    res = optimize(p.system, spec)
    efl = _row(res, "efl")
    assert res["status"] == "converged" and res["constraint_mode"] == "exact" and efl["met"]
    assert abs(efl["after"] - 95.0) <= V_TOL * efl["tolerance"]
    pen = optimize(p.system, spec.model_copy(update={"constraints": "penalty"}))
    assert pen["constraints"] is None and pen["constraint_mode"] == "penalty"
    spot = lambda r: next(o["value"] for o in r["operands_after"] if o["type"] == "rms_spot")  # noqa: E731
    assert spot(res) == pytest.approx(spot(pen), rel=1e-3)


def test_an_active_bound_is_a_kkt_point_and_its_price_predicts_the_relaxed_optimum():
    p = singlet()
    ops = [{"type": "rms_spot"}, {"type": "efl", "target": 95.0}, {"type": "max_thickness", "surface_id": "s1", "target": 6.0}]
    spec = _spec(BEND + THICK, ops, max_evaluations=1500)
    res = optimize(p.system, spec)
    th = _row(res, "max_thickness")
    assert res["status"] == "converged" and th["met"] and th["active"]
    assert 6.0 - 1e-3 <= th["after"] <= 6.0 + V_TOL * 1e-3  # the lens wants to be thicker (9.7 mm without the bound)
    assert th["multiplier"] > 0 and th["price"]["stationarity"] <= STATIONARY and not th["price"]["approximate"]

    # KKT, without the multiplier: the objective's gradient is normal to the active constraints (finite differences)
    mf = MeritFunction(p.system, spec, split=True)
    x = np.array([v["final"] for v in res["variables"]])
    mask, cidx = mf.layout()

    def fg(x):
        r, _ = mf.evaluate(x)
        return float(r[mask] @ r[mask]), r[cidx]

    f0, _ = fg(x)
    G = []
    for i in range(len(x)):
        h = 1e-6 * max(1.0, abs(x[i]))
        a, b = x.copy(), x.copy()
        a[i] += h
        b[i] -= h
        (fa, ga), (fb, gb) = fg(a), fg(b)
        G.append(np.concatenate([[(fa - fb) / (2 * h)], (ga - gb) / (2 * h)]) * max(abs(x[i]), 1e-3))
    G = np.array(G)  # rows: variables (scaled); columns: f, efl, thickness
    grad, A = G[:, 0], G[:, 1:]
    Q, _ = np.linalg.qr(A)
    assert np.linalg.norm(grad - Q @ (Q.T @ grad)) <= 0.02 * np.linalg.norm(grad)

    # the price: re-optimised with the bound relaxed by its step, the merit moves as predicted (first order)
    pr = th["price"]
    ops2 = [*ops[:2], {**ops[2], "target": pr["relaxed_target"]}]
    res2 = optimize(p.system, _spec(BEND + THICK, ops2, max_evaluations=1500))
    actual = res2["final_merit"] - res["final_merit"]
    predicted = pr["merit_relaxed"] - pr["merit"]
    assert actual < 0 and predicted < 0
    assert 0.8 <= predicted / actual <= 1.25


def test_conflicting_constraints_are_reported_not_hidden():
    p = singlet()
    ops = [{"type": "rms_spot"}, {"type": "min_thickness", "surface_id": "s1", "target": 8.0}, {"type": "max_thickness", "surface_id": "s1", "target": 6.0}]
    res = optimize(p.system, _spec(BEND + THICK, ops, max_evaluations=800))
    assert res["status"] == "infeasible"
    assert sum(not c["met"] for c in res["constraints"]) >= 1
    assert any("constraints are not met" in n for n in res["notes"])
    t = next(v for v in res["variables"] if v["parameter"] == "thickness" and v["surface_id"] == "s1")["final"]
    assert 6.0 - 1e-6 <= t <= 8.0 + 1e-6  # the least violation lies between the two limits


def test_constraint_weights_do_not_change_an_exact_result():
    p = singlet()
    base = [{"type": "rms_spot"}, {"type": "efl", "target": 95.0}, {"type": "max_thickness", "surface_id": "s1", "target": 6.0}]
    a = optimize(p.system, _spec(BEND + THICK, base, max_evaluations=800))
    b = optimize(p.system, _spec(BEND + THICK, [base[0], {**base[1], "weight": 100.0}, {**base[2], "weight": 0.01}], max_evaluations=800))
    assert b["final_merit"] == pytest.approx(a["final_merit"], rel=1e-12)
    assert _row(a, "max_thickness")["met"] and _row(b, "max_thickness")["met"]
    # weighted, a bound is traded against the spot: the lighter its weight, the further the lens grows past it
    def excess(w):
        r = optimize(p.system, _spec(BEND + THICK, [base[0], base[1], {**base[2], "weight": w}], constraints="penalty", max_evaluations=800))
        return next(o["value"] for o in r["operands_after"] if o["type"] == "max_thickness") - 6.0

    assert excess(0.01) > 20 * max(excess(1.0), 1e-12) > 0


@pytest.mark.parametrize("algorithm", ["global", "multistart"])
def test_global_searches_end_on_the_constraints(algorithm):
    p = singlet()
    variables = [{"surface_id": "s1", "parameter": "curvature", "min": -0.02, "max": 0.05}, {"surface_id": "s2", "parameter": "curvature", "min": -0.05, "max": 0.02}, BEND[2]]
    ops = [{"type": "rms_spot"}, {"type": "efl", "target": 95.0}, {"type": "min_edge_thickness", "surface_id": "s1", "target": 2.0}]
    res = optimize(p.system, _spec(variables, ops, algorithm=algorithm, max_evaluations=1200, multistart_runs=4))
    assert all(c["met"] for c in res["constraints"])
    assert abs(_row(res, "efl")["after"] - 95.0) <= V_TOL * _row(res, "efl")["tolerance"]
    assert res["final_merit"] < res["initial_merit"]


def test_a_trade_off_curve_is_the_relaxed_optima_and_its_slope_is_the_price():
    """optimize/tradeoff.py on the process pool: each target re-optimised with the limit exact; the points are
    reported against the design before optimisation, and the curve's slope at the current target is the price."""
    import time

    from opticore.designspace import DesignSpaceJobs
    from opticore.optimize import tradeoff

    p = singlet()
    ops = [{"type": "rms_spot"}, {"type": "efl", "target": 95.0}, {"type": "max_thickness", "surface_id": "s1", "target": 6.0}]
    spec = _spec(BEND + THICK, ops, max_evaluations=1500)
    res = optimize(p.system, spec)
    from opticore.model import OpticalSystem

    start = OpticalSystem.model_validate(res["system"])
    assert tradeoff.default_targets(spec, 2) == pytest.approx([6.0 + 0.24 * k for k in range(-4, 5)])
    jobs = DesignSpaceJobs()
    job = tradeoff.start_job(jobs, p.system, start, spec, 2, [5.76, 6.0, 6.24], 600)
    t0 = time.time()
    while job["state"] == "running" and time.time() - t0 < 300:
        time.sleep(0.2)
    snap = tradeoff.snapshot(jobs, job)
    assert snap["state"] == "finished" and snap["done"] == 3 and snap["type"] == "max_thickness"
    pts = snap["points"]
    assert [q["target"] for q in pts] == [5.76, 6.0, 6.24] and all(q["feasible"] for q in pts)
    for q in pts:
        assert q["value"] == pytest.approx(q["target"], abs=1e-3)
    m = [q["merit"] for q in pts]
    assert m[0] > m[1] > m[2]  # a thicker lens is allowed: a better one
    assert m[1] == pytest.approx(res["final_merit"], rel=1e-4)
    # the price at 6.0 against the curve's central difference
    slope = (m[2] - m[0]) / 0.48
    assert _row(res, "max_thickness")["price"]["dmerit_dtarget"] == pytest.approx(slope, rel=0.2)
    # a point is a whole optimisation result against the design before optimisation
    r = tradeoff.point_result(job, 2)
    assert r["initial_merit"] == pytest.approx(res["initial_merit"], rel=1e-12)
    assert [v["initial"] for v in r["variables"]] == pytest.approx([v["initial"] for v in res["variables"]], rel=1e-12)
    assert _row(r, "max_thickness")["target"] == 6.24 and _row(r, "max_thickness")["met"]


def test_the_trade_off_front_never_gets_worse_as_a_bound_loosens():
    """A design that meets a bound meets every looser value: the front at a target is the best design found there or
    at any tighter target (the cell-phone curve of lateral colour: 1.3 um found a better lens than 2.1-2.5 um)."""
    from opticore.optimize.tradeoff import envelope

    merits = {0.9: 0.004529, 1.1: 0.004368, 1.3: 0.004253, 1.5: 0.004358, 1.7: 0.004952, 1.9: 0.004537, 2.1: 0.004654}
    pts = [{"index": k, "target": t, "status": "finished", "feasible": True, "merit": m} for k, (t, m) in enumerate(merits.items())]
    pts[0]["feasible"] = False
    envelope(pts, {"kind": "bound", "sign": 1.0})
    env = [p["envelope"] for p in pts]
    assert env[0] is None and env[1] == 0.004368
    assert env[2:] == [0.004253] * 5 and [p["envelope_from"] for p in pts[2:]] == [2] * 5
    assert all(a >= b for a, b in zip(env[1:], env[2:]))
    # a lower bound loosens downwards; a target (equality) is its own front
    low = [{"index": k, "target": t, "status": "finished", "feasible": True, "merit": m} for k, (t, m) in enumerate([(0.5, 1.0), (0.6, 2.0), (0.7, 1.5)])]
    envelope(low, {"kind": "bound", "sign": -1.0})
    assert [p["envelope"] for p in low] == [1.0, 1.5, 1.5]
    eq = [{"index": 0, "target": 95.0, "status": "finished", "feasible": True, "merit": 2.0}, {"index": 1, "target": 96.0, "status": "finished", "feasible": True, "merit": 1.0}]
    envelope(eq, {"kind": "target", "sign": 1.0})
    assert [p["envelope_from"] for p in eq] == [0, 1]


def test_the_ui_knows_which_operands_are_limits():
    """frontend/src/lib/constraints.ts mirrors DEFAULT_CONSTRAINTS (the role shown before an evaluation)."""
    import pathlib
    import re

    from opticore.optimize.merit import DEFAULT_CONSTRAINTS

    ts = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "constraints.ts").read_text(encoding="utf-8")
    listed = re.search(r"DEFAULT_CONSTRAINTS: OperandType\[\] = \[([^\]]*)\]", ts).group(1)
    assert set(re.findall(r"'([a-z_]+)'", listed)) == DEFAULT_CONSTRAINTS


def test_constraints_alone_are_solved():
    p = singlet()
    res = optimize(p.system, _spec([BEND[0]], [{"type": "efl", "target": 80.0}], max_evaluations=200))
    assert res["status"] == "converged" and _row(res, "efl")["met"]
    assert math.isclose(_row(res, "efl")["after"], 80.0, rel_tol=1e-5)
