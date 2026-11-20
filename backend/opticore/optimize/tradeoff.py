"""Trade-off curves: the best merit function the design reaches as one limit moves (exact constraints, ADR-042).

A limit's price (constrained.py) is the slope of this curve at the current target; the curve shows how far the
slope holds. For each target the optimisation is run again with that limit as an exact constraint:

* Start: the optimised design (`start`), so each point continues from a nearby optimum; every point is reported
  against the design before optimisation (`base`): its variables' initial values, objective merit and operands
  are evaluated there, so a point can be applied like any optimisation result.
* The operand becomes a constraint (role "constraint", constraints "exact"), whatever its role in the run, and the
  algorithm is local with `budget` evaluations per point. Glass variables are left out: the glasses stay those of
  the start.
* The points run on the shared process pool (workers.py), one per worker (each optimisation serial there), through
  the design-space job machinery (designspace.DesignSpaceJobs: results as they finish, cancel, abandon).
* The front (`envelope`): a design that meets a bound also meets every looser value of it. Each point of a bound
  therefore reports the best design found at its own or any tighter target (`envelope`, `envelope_from`). Local
  optimisations from one start end in different minima, so a tighter target can find a better design than a
  looser one; the front is the best design known for each value, and it never gets worse as the bound loosens.
  For a target (an equality) the front is the point itself. When the front at the run's own target is better
  than the run's result, the run had not reached the best design its limits allow (the UI says so).
* Default targets (`default_targets`): the current target and four relax steps (merit.relax_step) of two steps
  each to either side: tighter and looser. A target at or below zero for a quantity that must be positive is left
  out, fractions (MTF, throughput, ...) are capped to [0, 1], and duplicates are dropped.
* Units: targets (requested and reported), the current target and the points' values are in the unit of the
  limit's constraint row (merit.report_scale: the RMS spot in um, although its operand's target is in mm).
"""

from __future__ import annotations

import time

from ..model import OpticalSystem
from .merit import EQUALITY, MeritFunction, OptimizationSpec, constraint_met, constraint_value, is_active, relax_step, report_scale, target_sign

POINTS = 9
# quantities that are positive (a target <= 0 is impossible or trivial), and fractions, at most 1
POSITIVE = {
    "min_thickness", "max_thickness", "min_edge_thickness", "max_total_track", "total_track", "efl", "fnum", "working_fnum",
    "max_lateral_color", "min_relative_illumination", "max_cra", "max_distortion",
    "rms_spot", "rms_wavefront", "detector_size", "surface_reflectance", "throughput", "detector_power", "mtf",
}
FRACTION = {"mtf", "throughput", "detector_power", "min_relative_illumination", "surface_reflectance"}


class TradeoffError(ValueError):
    pass


def active_index(spec: OptimizationSpec, operand: int) -> int:
    """Index into spec.operands of the `operand`-th active operand (merit.is_active): the numbering of an
    optimisation result's operands and constraints."""
    active = [k for k, o in enumerate(spec.operands) if is_active(o)]
    if not 0 <= operand < len(active):
        raise TradeoffError(f"There is no active operand {operand + 1}")
    return active[operand]


def default_targets(spec: OptimizationSpec, operand: int, points: int = POINTS) -> list[float]:
    """Targets around the current one in steps of two relax steps, in the limit's reported unit (module notes)."""
    o = spec.operands[active_index(spec, operand)]
    step = 2.0 * relax_step(o)
    half = points // 2
    out = []
    for k in range(-half, points - half):
        t = o.target + target_sign(o) * k * step
        if o.type in FRACTION:
            t = min(max(t, 0.0), 1.0)
        if o.type in POSITIVE and t <= 0:
            continue
        out.append(float(t * report_scale(o)))
    return sorted(dict.fromkeys(out))


def point_spec(spec: OptimizationSpec, operand: int, target: float, budget: int) -> OptimizationSpec:
    k = active_index(spec, operand)
    ops = [o.model_copy(update={"target": float(target), "role": "constraint"}) if i == k else o for i, o in enumerate(spec.operands)]
    variables = [v for v in spec.variables if v.parameter != "material"]
    return spec.model_copy(update={"operands": ops, "variables": variables, "constraints": "exact", "algorithm": "local", "max_evaluations": int(budget)})


def run_point(task: dict, payload: dict, slot: int | None = None) -> dict:
    """Optimise one target (a worker task; also callable directly). The result is rebased on the design before
    optimisation (module notes)."""
    from ..jsonutil import jsonable
    from .engine import Control, optimize

    t0 = time.time()
    base = OpticalSystem.model_validate(payload["base"])
    start = OpticalSystem.model_validate(payload["start"])
    spec = OptimizationSpec.model_validate(payload["spec"])
    custom = payload["custom"]
    ns = payload.get("ns")
    head = {"index": task["index"], "target": task["target"]}
    ctl = Control()
    if slot is not None:
        from ..workers import flag

        ctl.cancel = flag(slot)
        if ctl.cancel.is_set():
            return {**head, "status": "cancelled"}
    ps = point_spec(spec, payload["operand"], task.get("operand_target", task["target"]), payload["budget"])
    try:
        res = optimize(start, ps, custom, control=ctl, ns=ns)
    except (ValueError, ArithmeticError) as exc:
        return {**head, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    if res["status"] == "cancelled":
        return {**head, "status": "cancelled"}
    k = payload["operand"]
    row = next((c for c in res["constraints"] or [] if c["index"] == k), None)
    _rebase(res, base, ps, custom, ns)
    res.pop("history", None)
    return jsonable(
        {
            **head,
            "status": "finished",
            "merit": res["final_merit"],
            "feasible": not any(not c["met"] for c in res["constraints"] or []),
            "value": row["after"] if row else None,
            "multiplier": row["multiplier"] if row else None,
            "price": row["price"] if row else None,
            "optimiser_status": res["status"],
            "evaluations": res["evaluations"],
            "elapsed_s": time.time() - t0,
            "result": res,
        }
    )


def _rebase(res: dict, base: OpticalSystem, spec: OptimizationSpec, custom, ns) -> None:
    """Report a point against the design before optimisation: initial values, objective merit, operands and the
    constraints' values before."""
    mf = MeritFunction(base, spec, custom, ns=ns, split=True)
    r0, b0 = mf.evaluate(mf.x0)
    res["initial_merit"] = mf.merit_from_residuals(r0)
    mb = res["final_merit"]
    res["improvement_percent"] = (1 - mb / res["initial_merit"]) * 100 if res["initial_merit"] > 0 else 0.0
    res["operands_before"] = b0
    for v, x in zip(res["variables"], mf.x0):
        v["initial"] = float(x)
    for c in res["constraints"] or []:
        o = mf.operands[c["index"]]
        b = b0[c["index"]]
        c["before"] = b.get("value")
        v = None if b.get("error") else b.get("value")
        if v is not None:
            v = v / report_scale(o)  # the breakdown's unit to the target's
        c["met_before"] = bool(constraint_met(o, constraint_value(o, v)))


def start_job(jobs, base: OpticalSystem, start: OpticalSystem, spec: OptimizationSpec, operand: int, targets: list[float] | None, budget: int, custom_materials=(), ns=None) -> dict:
    """Start a trade-off curve on the shared pool (designspace.DesignSpaceJobs); configuration errors are raised
    here (synchronously)."""
    k = active_index(spec, operand)
    o = spec.operands[k]
    u = report_scale(o)  # targets are in the constraint row's unit (module notes)
    targets = sorted(float(t) for t in (targets or default_targets(spec, operand)))
    if len(targets) < 2:
        raise TradeoffError("A trade-off curve needs at least two targets")
    if len(targets) > 41:
        raise TradeoffError("At most 41 targets")
    # the set-up must be valid for every target (a failing set-up would fail every point alike)
    MeritFunction(start, point_spec(spec, operand, targets[0] / u, budget), list(custom_materials), ns=ns, split=True)
    payload = {
        "base": base.model_dump(mode="json"),
        "start": start.model_dump(mode="json"),
        "spec": spec.model_dump(mode="json"),
        "custom": list(custom_materials),
        "ns": ns,
        "operand": operand,
        "budget": int(budget),
    }
    tasks = [{"index": i, "target": t, "operand_target": t / u} for i, t in enumerate(targets)]

    def runner(job, pool, fl):
        futures = {pool.submit(run_point, t, payload, fl.slot): t["index"] for t in tasks}
        jobs.gather(job, futures, lambda i, r: jobs.store(job, i, r))

    job = jobs.start(spec, custom_materials, runner=runner, total=len(tasks), topologies=[])
    job["tradeoff"] = {"operand": operand, "type": o.type, "kind": "target" if o.type in EQUALITY else "bound", "sign": target_sign(o), "current": o.target * u, "targets": targets}
    return job


def snapshot(jobs, job: dict) -> dict:
    """Progress and the finished points (by target), without their full results."""
    job["polled"] = time.time()
    results = dict(job["results"])
    points = [{k: v for k, v in results[i].items() if k != "result"} for i in sorted(results)]
    envelope(points, job.get("tradeoff", {}))
    end = job["finished"] or time.time()
    return {
        "id": job["id"],
        "state": job["state"],
        "total": job["total"],
        "done": len(job["order"]),
        "failed": job["failed"],
        "elapsed_s": end - job["created"],
        "error": job["error"],
        "abandoned": job["abandoned"],
        **job.get("tradeoff", {}),
        "points": points,
    }


def envelope(points: list[dict], info: dict) -> None:
    """The front (module notes): `envelope` and `envelope_from` on every point, None where nothing feasible is known."""
    bound = info.get("kind") == "bound"
    sign = info.get("sign", 1.0)
    best = None
    for p in sorted(points, key=lambda p: sign * p["target"]) if bound else points:
        ok = p.get("status") == "finished" and p.get("feasible")
        if not bound:
            best = p if ok else None
        elif ok and (best is None or p["merit"] < best["merit"]):
            best = p
        p["envelope"] = best["merit"] if best is not None else None
        p["envelope_from"] = best["index"] if best is not None else None


def point_result(job: dict, index: int) -> dict | None:
    """The full optimisation result of a finished point (to show and apply like any result)."""
    r = job["results"].get(index)
    if not r or r.get("status") != "finished":
        return None
    return r["result"]
