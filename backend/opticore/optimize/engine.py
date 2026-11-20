"""Optimisation drivers built on SciPy.

local       scipy.optimize.least_squares, Trust Region Reflective ('trf'),
            bounded damped least squares on the residual vector
global      scipy.optimize.differential_evolution on the scalar merit
            (requires finite bounds; deferred updating, its population evaluated
            on the process pool when that pays), polished with the local solver
multistart  local solver from several Latin-hypercube starting points
            within the bounds; the best result is kept

Exact constraints (spec.constraints = "exact", the default, when the merit function has constraint operands,
merit.operand_role): the local solver runs inside an augmented Lagrangian (constrained.py) that meets the
constraints to their tolerances, and the result reports each constraint with its Lagrange multiplier's price. The
best design follows the feasibility rules (constrained.Constraints.key): a design that meets every constraint beats
any that does not. With "penalty" every operand is a weighted residual of one merit function. The global search
polishes differential evolution's own optimum (its lowest penalty), and the solver's run is returned only when it
converged. A limit that cannot be evaluated at the start is refused (check_limits).

Status max_evaluations: a local run, the global polish or any multistart run stopped on its share of the budget
before converging. Evaluations: `evaluations` counts the search, at most max_evaluations and the same with and
without the pool (a finite-difference Jacobian starts only when all its columns fit); the closing evaluation of the
design returned and its 2n sensitivity points are `closing_evaluations`.

The original system is never modified: the result contains a new system.

Robustness: an error inside the search (not in the set-up) ends the run with status "error" and the best
design found so far, instead of losing the run. Global and multistart searches give curvatures without
bounds the physical limit of their clear aperture (search_bounds). The result lists the image-quality
operands that got worse while the merit improved (objective_worse), the violated targets that no
variable can change (fixed_operands, with their share of the final merit function) and the variables
that do not change the merit function at all (inert_variables).
"""

from __future__ import annotations

import math
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from scipy.optimize import differential_evolution, least_squares
from scipy.stats import qmc

from ..model import OpticalSystem
from . import parallel
from .constrained import MAX_OUTER, RHO_MAX, V_TOL, Constraints
from .merit import MeritFunction, OptimizationSpec, exact_constraints, report_scale


class Cancelled(Exception):
    pass


class BudgetExhausted(Exception):
    pass


@dataclass
class Progress:
    evaluations: int = 0
    current: float = math.nan
    best: float = math.nan
    initial: float = math.nan
    best_x: np.ndarray | None = None
    history: list[tuple[int, float, float]] = field(default_factory=list)  # (eval, current, best)
    phase: str = "starting"
    constraints: int = 0  # exact constraints of the run
    unmet: int | None = None  # of those, not met by the best design
    started: float = field(default_factory=time.time)
    best_materials: dict | None = None  # glass substitution: surface id -> material of the best design


@dataclass
class Control:
    cancel: threading.Event = field(default_factory=threading.Event)
    pause: threading.Event = field(default_factory=threading.Event)


def search_bounds(mf: MeritFunction, lo: np.ndarray, hi: np.ndarray) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Finite bounds for the global and multistart searches. A curvature without bounds gets the physical
    limit of its clear aperture, |c| <= 1 / semi-diameter (at most a hemisphere; widened to the start value
    if that is steeper). Any other unbounded variable is an error naming it."""
    from ..analysis.evaluate import auto_semi_diameters, effective_semi_diameters
    from ..system import compile_system

    lo, hi = lo.copy(), hi.copy()
    need = [i for i in range(len(lo)) if not (math.isfinite(lo[i]) and math.isfinite(hi[i]))]
    if not need:
        return lo, hi, []
    sd = None
    curv = [i for i in need if mf.variables[i].parameter in ("curvature", "curvature_x") and mf.variables[i].configuration is None]
    if curv:
        cs = compile_system(mf.base, mf.custom_materials, mf.index_offsets)
        from ..paraxial import compute_pupil

        sd = effective_semi_diameters(cs, auto_semi_diameters(cs, compute_pupil(cs)))
    done = []
    for i in curv:
        k = mf.index_of[mf.variables[i].surface_id]
        h = float(sd[k]) if sd is not None else 0.0
        if not (h > 0 and math.isfinite(h)):
            continue
        c = max(1.0 / h, 1.1 * abs(float(mf.x0[i])))
        lo[i] = lo[i] if math.isfinite(lo[i]) else min(-c, hi[i] - c)
        hi[i] = hi[i] if math.isfinite(hi[i]) else max(c, lo[i] + c)
        done.append(f"S{k} ±{c:.4g} 1/mm")
    missing = [i for i in need if not (math.isfinite(lo[i]) and math.isfinite(hi[i]))]
    if missing:
        names = ", ".join(f"S{mf.index_of[mf.variables[i].surface_id]} {mf.variables[i].parameter}" for i in missing)
        raise ValueError(f"Global and multistart optimisation need a finite min and max for every variable; set them for: {names}")
    note = "Search bounds of the curvatures from their clear apertures (|c| ≤ 1/semi-diameter, at most a hemisphere): " + ", ".join(done)
    return lo, hi, [note]


def _scale_for(mf: MeritFunction) -> np.ndarray:
    lo, hi = mf.bounds()
    sc = np.abs(mf.x0).copy()
    for i, v in enumerate(mf.variables):
        if sc[i] == 0:
            if math.isfinite(lo[i]) and math.isfinite(hi[i]) and hi[i] > lo[i]:
                sc[i] = (hi[i] - lo[i]) / 10
            else:
                sc[i] = {"curvature": 0.01, "thickness": 1.0, "conic": 0.1}.get(v.parameter, 1e-6 if v.parameter.startswith("asph") else 1.0)
    return sc


def optimize(
    system: OpticalSystem,
    spec: OptimizationSpec,
    custom_materials=(),
    progress: Progress | None = None,
    control: Control | None = None,
    on_update: Callable[[Progress], None] | None = None,
    ns=None,
    parallel: bool | None = None,
) -> dict:
    """Optimise; enabled material variables switch to glass substitution (optimize/glass.py).
    `ns` = (sources, detectors) for the detector operands (nsdirect.py).
    `parallel`: None lets parallel.maybe decide (it measures the first evaluation, so the choice can depend on the
    machine's load); False always evaluates in this process, for results that must not depend on it (stored
    data, frozen samples). The pool and this process agree to the warm-start tolerances, but a run that ends on its
    budget far from a minimum can follow them to a different design."""
    progress = progress or Progress()
    control = control or Control()
    from .glass import optimize_with_glass, split_variables

    cont, glass = split_variables(spec)
    if glass:
        return optimize_with_glass(system, spec, custom_materials, progress, control, on_update, _optimize_continuous, ns=ns, parallel=parallel)
    return _optimize_continuous(system, cont, custom_materials, progress, control, on_update, ns=ns, use_pool=parallel)


def validate_spec(system: OpticalSystem, spec: OptimizationSpec, custom_materials=(), ns=None) -> None:
    """Raise ValueError for an invalid optimisation set-up (synchronous API check). With exact limits this evaluates
    the starting design once: a limit that cannot be evaluated there is refused (check_limits)."""
    from .glass import split_variables, validate_glass_variables

    cont, glass = split_variables(spec)
    exact = exact_constraints(cont)
    mf = MeritFunction(system, cont, custom_materials, ns=ns, split=exact)
    if glass:
        validate_glass_variables(system, glass, custom_materials)
    elif not any(v.enabled for v in cont.variables):
        raise ValueError("No enabled optimisation variables")
    if exact:
        lo, hi = mf.bounds()
        check_limits(mf, mf.evaluate(np.clip(mf.x0, lo, hi))[1])


def check_limits(mf: MeritFunction, breakdown: list[dict]) -> None:
    """Refuse limits (exact mode) that cannot be evaluated at the starting design, e.g. a magnification of an
    infinite-conjugate system: such a limit's violation is a constant failure value, which no step reduces, so the
    solver would spend its whole budget on it."""
    bad = [(k, b) for k, b in enumerate(breakdown) if mf.roles[k] == "constraint" and (b.get("error") or b.get("value") is None)]
    if bad:
        what = "; ".join(f"{b['type']}" + (f" at {mf.operands[k].surface_id}" if mf.operands[k].surface_id else "") + f" ({b.get('error') or 'no value'})" for k, b in bad)
        raise ValueError(f"A limit cannot be evaluated at the starting design: {what}. Remove the limit or change the design so that it is defined")


def _optimize_continuous(
    system: OpticalSystem,
    spec: OptimizationSpec,
    custom_materials=(),
    progress: Progress | None = None,
    control: Control | None = None,
    on_update: Callable[[Progress], None] | None = None,
    ns=None,
    use_pool: bool | None = None,
    sensitivities: bool = True,
) -> dict:
    """One continuous optimisation (module notes). `evaluations` in the result counts the search (at most
    spec.max_evaluations, the same with and without the pool); the closing evaluation of the design returned and
    the 2n points of its sensitivities are `closing_evaluations`. `sensitivities=False` (inner runs of the glass
    substitution) skips the sensitivities, and with them the prices and inert variables."""
    progress = progress or Progress()
    control = control or Control()
    exact = exact_constraints(spec)
    mf = MeritFunction(system, spec, custom_materials, ns=ns, split=exact)
    cons = Constraints(mf) if exact else None
    if not mf.variables:
        raise ValueError("No enabled optimisation variables")
    lo, hi = mf.bounds()
    if np.any(lo >= hi):
        raise ValueError("Each variable needs min < max")
    budget = spec.max_evaluations
    notes: list[str] = []
    if spec.algorithm in ("global", "multistart"):
        lo, hi, bnotes = search_bounds(mf, lo, hi)
        notes += bnotes

    # The true starting design is always the reference for "initial"; if some
    # values lie outside their bounds the search must start from the nearest
    # feasible point, which is reported explicitly (never silently).
    x_orig = mf.x0.copy()
    x0 = np.clip(x_orig, lo, hi)
    clamped = np.nonzero(x0 != x_orig)[0]
    t_first = time.perf_counter()
    r_orig, breakdown0 = mf.evaluate(x_orig)
    t_first = time.perf_counter() - t_first
    m_orig = mf.merit_from_residuals(r_orig)
    if clamped.size:
        names = ", ".join(f"{mf.variables[i].parameter} of surface {mf.variables[i].surface_id} ({x_orig[i]:.6g} -> {x0[i]:.6g})" for i in clamped)
        notes.append(f"Starting values outside their bounds were moved to the nearest bound: {names}")
        r0, b_start = mf.evaluate(x0)
        m0 = mf.merit_from_residuals(r0)
    else:
        r0, m0, b_start = r_orig, m_orig, breakdown0
    if cons is not None:
        check_limits(mf, b_start)  # a limit that cannot be evaluated where the search starts is refused
    progress.initial = m_orig
    progress.best = m0
    progress.current = m0
    progress.best_x = x0.copy()
    progress.history.append((mf.evaluations, m0, m0))
    best_key = [cons.key(r0, m0) if cons is not None else (0.0, m0)]
    if cons is not None:
        progress.constraints = len(cons.ops)
        progress.unmet = cons.unmet(r0)
    limit = [budget]  # evaluation limit of the current phase

    def check(n: int = 1):
        """Stop for a cancel (wait while paused), or when n more evaluations do not fit the phase's budget."""
        if control.cancel.is_set():
            raise Cancelled()
        while control.pause.is_set():
            if control.cancel.is_set():
                raise Cancelled()
            time.sleep(0.05)
        if mf.evaluations + n > min(limit[0], budget):
            raise BudgetExhausted()

    def record(x, r):
        m = mf.merit_from_residuals(r)
        progress.evaluations = mf.evaluations
        progress.current = m
        k = cons.key(r, m) if cons is not None else (0.0, m)
        if k < best_key[0]:
            best_key[0] = k
            progress.best = m
            progress.best_x = np.array(x, dtype=float)
            if cons is not None:
                progress.unmet = cons.unmet(r)
        if len(progress.history) < 4000:
            progress.history.append((mf.evaluations, m, progress.best))
        if on_update:
            on_update(progress)

    pj = None  # parallel finite-difference Jacobian on the process pool (parallel.py), when it pays

    def evaluate(x) -> np.ndarray:
        # with the pool, every evaluation runs in a worker process: the server's own requests (the views'
        # previews) then cannot slow the optimisation down through the interpreter lock
        if pj is not None:
            r = pj.run([np.asarray(x, dtype=float)])[0]
            if r is not None:
                mf.evaluations += 1
                return r
        return mf.evaluate(x)[0]

    last: list = [None, None]  # the latest point the solver evaluated and its residuals (serial Jacobian's f0)

    def resid(x):
        check()
        r = evaluate(x)
        record(x, r)
        if pj is not None:
            pj.remember(x, r)
        return r

    def fd_jacobian(x, f0):
        """Serial forward differences with the steps of the parallel Jacobian (parallel.fd_steps), so a run gives the
        same Jacobian with and without the pool. It starts only when all its columns fit the budget, as the parallel
        one."""
        check(len(x))
        dx = parallel.fd_steps(x, lo, hi, 1e-7)
        J = np.empty((len(f0), len(x)))
        for i in range(len(x)):
            xi = x.copy()
            xi[i] += dx[i]
            J[:, i] = (resid(xi) - f0) / dx[i]
        return J

    def fun(x):
        """The weighted solve's residuals; the latest point is kept for its Jacobian's f0."""
        x = np.asarray(x, dtype=float)
        r = resid(x)
        last[:] = [x.copy(), r]
        return r

    def serial_jac(x, *args, **kwargs):
        x = np.asarray(x, dtype=float)
        f0 = last[1] if last[0] is not None and np.array_equal(last[0], x) else None
        if f0 is None:
            f0 = resid(x)
        return fd_jacobian(x, f0)

    def column(x, r):  # a Jacobian column evaluated by a worker
        mf.evaluations += 1
        record(x, r)

    de_best: list = [math.inf, None]  # differential evolution's own optimum: its lowest scalar and that point

    def scalar_of(r, x) -> float:
        s = cons.penalty(r) if cons is not None else float(r @ r)
        if s < de_best[0]:
            de_best[:] = [s, np.array(x, dtype=float)]
        return s

    def scalar(x):
        check()
        r = evaluate(x)
        record(x, r)
        return scalar_of(r, x)

    def population(_func, xs):
        """differential_evolution's map: the population's residuals on the process pool (serially without it)."""
        xs = [np.asarray(x, dtype=float) for x in xs]
        if pj is None:
            return [scalar(x) for x in xs]
        check()
        out = []
        for x, r in zip(xs, pj.run(xs)):
            if r is None:
                out.append(scalar(x))
                continue
            check()
            mf.evaluations += 1
            record(x, r)
            out.append(scalar_of(r, x))
        return out

    # ---------------------------------------------------------------- exact constraints (constrained.py)
    al_seen: dict[bytes, np.ndarray] = {}  # raw residuals of the points the solver evaluated
    inner_best: list = [math.inf, None, None]  # (|T|^2, x, raw residuals) of the current inner solve
    al_runs: list[dict] = []

    def al_fun(x):
        x = np.asarray(x, dtype=float)
        r = resid(x)
        t = cons.residual(r)
        if len(al_seen) > 64:
            al_seen.clear()
        al_seen[x.tobytes()] = r
        v = float(t @ t)
        if v < inner_best[0]:
            inner_best[:] = [v, x.copy(), r]
        return t

    def raw_jac(x):
        if pj is not None:
            return pj(x)
        f0 = al_seen.get(x.tobytes())
        if f0 is None:
            f0 = resid(x)
        return fd_jacobian(x, f0)

    def al_jac(x, *args, **kwargs):
        x = np.asarray(x, dtype=float)
        J = raw_jac(x)
        r = al_seen.get(x.tobytes())
        if r is None:
            r = resid(x)
        return cons.jacobian(r, J)

    def al_solve(xs, share: int, label: str) -> dict:
        """One augmented-Lagrangian run from xs with at most `share` evaluations (constrained.py)."""
        end = min(budget, mf.evaluations + share)
        x = np.array(xs, dtype=float)
        r = al_seen.get(x.tobytes())
        if r is None:
            r = resid(x)
            al_seen[x.tobytes()] = r
        cons.start(r)
        v_prev = cons.measure(r)  # at the start (lam = 0): the first solve must reduce it too
        f_prev = None  # objective of the previous inner solve that met the constraints
        converged = False
        it = 0
        for it in range(1, MAX_OUTER + 1):
            if mf.evaluations >= end - 1:
                break
            progress.phase = f"{label}constraints {it}"
            # the inner solve is the optimisation itself: it may use most of what is left (a reserve stays for the
            # multiplier updates that follow)
            left = end - mf.evaluations
            limit[0] = min(end, mf.evaluations + max(4 * (nvar + 1), left - min(left // 6, 6 * (nvar + 1))))
            inner_best[:] = [math.inf, None, None]
            inner_ok = False
            try:
                res = least_squares(al_fun, x, jac=al_jac, bounds=(lo, hi), method="trf", x_scale=scale, max_nfev=budget)
                x = np.asarray(res.x, dtype=float)
                inner_ok = res.status > 0
            except BudgetExhausted:
                if inner_best[1] is not None:
                    x = inner_best[1]
            finally:
                limit[0] = budget
            r = al_seen.get(x.tobytes())
            if r is None:
                if inner_best[1] is None:
                    break
                x, r = inner_best[1], inner_best[2]
            v = cons.measure(r)
            f = cons.f(r) / cons.f0
            cons.update(r)
            met = inner_ok and v <= V_TOL and cons.unmet(r) == 0
            # converged: the constraints met and a restarted inner solve (a fresh trust region) no longer improves
            # the objective, or too little budget is left to try
            if met and ((f_prev is not None and f >= f_prev * (1.0 - 1e-6)) or end - mf.evaluations < 4 * (nvar + 1)):
                converged = True
                break
            f_prev = f if met else None
            if v > V_TOL and v > 0.25 * v_prev:
                cons.rho *= 10.0
                if cons.rho > RHO_MAX:
                    break
            v_prev = v
        # exhausted: stopped on its share of the budget before converging (not because the limits cannot be met)
        exhausted = not converged and mf.evaluations >= end - 1
        run = {"x": x, "r": r, "lam": cons.lam.copy(), "rho": cons.rho, "f0": cons.f0, "converged": converged, "exhausted": exhausted, "iterations": it, "feasible": r is not None and cons.unmet(r) == 0}
        al_runs.append(run)
        return run

    scale = _scale_for(mf)
    nvar = len(x0)
    status = "converged"
    message = ""
    evals_at_start = mf.evaluations
    if use_pool is not False and parallel.maybe(nvar, t_first):
        pj = parallel.ParallelJacobian(system, spec, custom_materials, mf.index_offsets, ns, lo, hi, 1e-7, resid, column, check, control.cancel.is_set, split=exact, reserve=check)
    # weighted limits: the parallel Jacobian, or serially the same steps (SciPy's own '2-point' steps 1e-7·|x| with
    # diff_step and about 1.5e-8·max(1, |x|) without it, so neither would match the pool)
    jac = {"jac": pj if pj is not None else serial_jac}
    try:
        if cons is not None:
            cons.start(r0)
        if spec.algorithm == "local":
            progress.phase = "local"
            if cons is not None:
                run = al_solve(x0, budget, "")
                message = _al_message(run)
                if run["exhausted"]:
                    status = "max_evaluations"
                elif _stopped(run):
                    status = "stopped"
            else:
                res = least_squares(fun, x0, bounds=(lo, hi), method="trf", x_scale=scale, max_nfev=budget, **jac)
                message = res.message
                if res.status == 0:
                    status = "max_evaluations"
        elif spec.algorithm == "global":
            if not (np.all(np.isfinite(lo)) and np.all(np.isfinite(hi))):
                raise ValueError("Global optimisation requires finite min and max for every variable")
            # 70 % of the budget for differential evolution, the rest for the
            # least-squares polish (DE uses popsize*N evaluations per generation)
            popsize = 15
            de_budget = int(0.7 * budget)
            limit[0] = mf.evaluations + de_budget
            progress.phase = "global"
            de_exhausted = False
            try:
                # deferred updating: a generation is one batch, evaluated on the process pool when that pays; the
                # same seed gives the same search with and without the pool
                de = differential_evolution(
                    scalar,
                    list(zip(lo, hi)),
                    seed=spec.seed,
                    popsize=popsize,
                    maxiter=max(1, de_budget // (popsize * nvar) - 1),
                    polish=False,
                    tol=1e-10,
                    init="latinhypercube",
                    x0=x0,
                    updating="deferred",
                    workers=population,
                )
                message = f"Differential evolution: {de.message}"
            except BudgetExhausted:
                message = "Differential evolution used its share of the budget"
                de_exhausted = True
            limit[0] = budget
            progress.phase = "polish"
            remaining = budget - mf.evaluations
            if remaining > nvar + 2 and cons is not None:
                # from differential evolution's own optimum (its lowest penalty), not from the design with the smallest
                # violation: that order ignores the objective while no design meets the limits
                run = al_solve(de_best[1] if de_best[1] is not None else progress.best_x, remaining, "polish, ")
                message += "; polish: " + _al_message(run)
                if run["exhausted"]:
                    status = "max_evaluations"
                elif _stopped(run):
                    status = "stopped"
            elif remaining > nvar + 2:
                res = least_squares(fun, progress.best_x, bounds=(lo, hi), method="trf", x_scale=scale, max_nfev=remaining, **jac)
                message += f"; polish: {res.message}"
                if res.status == 0:
                    status = "max_evaluations"
            elif de_exhausted:
                status = "max_evaluations"  # no budget left for a polish
        else:  # multistart
            if not (np.all(np.isfinite(lo)) and np.all(np.isfinite(hi))):
                raise ValueError("Multistart optimisation requires finite min and max for every variable")
            sampler = qmc.LatinHypercube(d=nvar, seed=spec.seed)
            starts = [x0] + list(qmc.scale(sampler.random(spec.multistart_runs - 1), lo, hi))
            per = max(nvar + 3, (budget - mf.evaluations) // len(starts))
            done = 0
            for k, xs in enumerate(starts):
                if mf.evaluations >= budget:
                    break
                progress.phase = f"multistart {k + 1}/{len(starts)}"
                limit[0] = min(budget, mf.evaluations + per)
                # a run that used its share before converging is not completed; continue with the next start
                try:
                    if cons is not None:
                        if al_solve(xs, per, f"multistart {k + 1}/{len(starts)}, ")["exhausted"]:
                            continue
                    elif least_squares(fun, xs, bounds=(lo, hi), method="trf", x_scale=scale, max_nfev=per, **jac).status == 0:
                        continue
                except BudgetExhausted:
                    continue
                done += 1
            limit[0] = budget
            message = f"{done} of {len(starts)} local runs completed within their share ({per} evaluations each)"
            if done < len(starts):
                status = "max_evaluations"
    except Cancelled:
        status = "cancelled"
        message = "Cancelled by user; best solution found so far is returned"
    except BudgetExhausted:
        status = "max_evaluations"
        message = "Evaluation budget exhausted; best solution found so far is returned"
    except Exception as exc:  # an error inside the search: keep the best design found so far (never lose a run)
        if mf.evaluations <= evals_at_start + 1:
            raise
        traceback.print_exc()
        status = "error"
        message = f"Stopped by an error after {mf.evaluations} evaluations ({type(exc).__name__}: {exc}); the best design found so far is returned"

    xb = progress.best_x if progress.best_x is not None else x0
    if cons is not None:
        # a converged solver run (its constraints met to V_TOL), unless the best design recorded is clearly better; a
        # run that stopped early may meet its limits only within one tolerance, which the recorded order does not
        runs = [q for q in al_runs if q["feasible"] and q["converged"]]
        q = min(runs, key=lambda q: cons.f(q["r"])) if runs else None
        if q is not None and best_key[0][0] == 0.0 and math.sqrt(cons.f(q["r"])) <= best_key[0][1] * (1 + 1e-3):
            xb = q["x"]
    search_evaluations = mf.evaluations  # the budget's count; the closing evaluations below are reported apart
    rb, breakdown_b = mf.evaluate(xb)
    mb = mf.merit_from_residuals(rb)
    progress.phase = "done"
    best_system = mf.system_for(xb)
    try:
        if sensitivities:
            sens, jac_b = sensitivity(mf, xb, mb, pj.run if pj is not None else None, jacobian=True)
        else:
            sens, jac_b = [None] * nvar, np.zeros((0, nvar))
    finally:
        if pj is not None:
            pj.close()
    # variables that change nothing: neither the merit function nor (exact) any constraint
    inert = [k for k, s in enumerate(sens) if s is not None and s == 0.0 and (jac_b.size == 0 or not np.any(jac_b[:, k]))]
    if cons is not None and not cons.mask.any():
        sens = [None] * len(sens)  # constraints only: there is no merit function to be sensitive
    constraint_rows = None
    if cons is not None:
        # prices: Lagrange multipliers estimated at the design returned, from the same central differences as the
        # sensitivities (constrained.Constraints.multipliers)
        free = np.array([s is not None and not _at_bound(v, b) for v, b, s in zip(mf.variables, xb, sens)], dtype=bool)
        constraint_rows = cons.report(r_orig, breakdown0, rb, breakdown_b, cons.multipliers(rb, jac_b, free, _scale_for(mf)))
        unmet = [c for c in constraint_rows if not c["met"]]
        progress.unmet = len(unmet)
        if unmet and status in ("converged", "max_evaluations", "stopped"):
            fixed = [c for c in unmet if c["fixed"]]
            if status in ("converged", "stopped") or fixed:  # out of budget it might still be met, unless no variable changes it
                status = "infeasible"
            notes.append(
                f"{len(unmet)} of {len(constraint_rows)} constraints are not met"
                + (" (no variable changes " + ", ".join(f"{c['type']} {c['surface_id'] or ''}".strip() for c in fixed) + ")" if fixed else "")
                + "; the design returned violates them least. Relax a constraint, free more variables or widen their bounds"
            )
    if clamped.size and mb > m_orig:
        notes.append("The best design within the bounds is worse than the original (out-of-bounds) design; widen the bounds or discard this result")
    return {
        "status": status,
        "message": message,
        "notes": notes,
        "algorithm": spec.algorithm,
        # exact constraints (constrained.py): one row per constraint (None: penalty merit function)
        "constraints": constraint_rows,
        "constraint_mode": "exact" if cons is not None else "penalty",
        "initial_merit": m_orig,
        "final_merit": mb,
        "improvement_percent": (1 - mb / m_orig) * 100 if m_orig > 0 else 0.0,
        "evaluations": search_evaluations,  # at most max_evaluations
        "closing_evaluations": mf.evaluations - search_evaluations,  # the design returned and its sensitivities
        "variables": [
            {
                "surface_id": v.surface_id,
                "configuration": v.configuration,
                "parameter": v.parameter,
                "initial": float(a),
                "final": float(b),
                "min": v.min,
                "max": v.max,
                "at_bound": _at_bound(v, b),
                "sensitivity": s,
            }
            for v, a, b, s in zip(mf.variables, x_orig, xb, sens)
        ],
        # Jacobian columns evaluated on the process pool (None: serial)
        "parallel": {"workers": pj.n_workers, "columns": pj.columns, "seconds": pj.seconds} if pj is not None else None,
        "operands_before": breakdown0,
        "operands_after": breakdown_b,
        # variables that do not change the merit function at all (e.g. an image distance that does not move a
        # detector placed in global coordinates): their sensitivity is exactly zero
        "inert_variables": inert,
        # image-quality operands that got worse although the merit function improved (constraints dominate)
        "objective_worse": _objective_worse(mf.operands, breakdown0, breakdown_b, mf.roles),
        # violated targets no variable can change (MeritFunction.fixed_operands): their share of the final MF^2
        "fixed_operands": [
            {"index": k, "type": b["type"], "surface_id": mf.operands[k].surface_id, "value": b["value"], "target": b["target"], "share": b["contribution"] / (mb * mb)}
            for k, b in enumerate(breakdown_b)
            if b.get("fixed") and mb > 0 and b.get("contribution", 0.0) > 0.0
        ],
        "history": progress.history,
        "system": best_system.model_dump(),
        "elapsed_s": time.time() - progress.started,
    }


def _objective_worse(operands, before: list[dict], after: list[dict], roles=None) -> list[dict]:
    """Image-quality operands (rms_spot, rms_wavefront, mtf) whose error grew by more than 1 %: the merit function
    can improve while one of them gets worse when other operands (constraints in mm, the focal length) dominate it.
    Exact constraints are reported with the constraints instead."""
    out = []
    for k, (o, b0, b1) in enumerate(zip(operands, before, after)):
        if roles is not None and roles[k] == "constraint":
            continue
        if o.type not in ("rms_spot", "rms_wavefront", "mtf") or b0.get("value") is None or b1.get("value") is None:
            continue
        t = o.target * report_scale(o)  # the breakdown reports the spot in um
        e0, e1 = abs(b0["value"] - t), abs(b1["value"] - t)
        if e1 > 1.01 * e0 + 1e-12:
            out.append({"index": k, "type": o.type, "before": b0["value"], "after": b1["value"], "target": t, "unit": b1.get("unit", "")})
    return out


def _stopped(run: dict) -> bool:
    """A run that ended on MAX_OUTER with budget left, neither converged nor given up (rho within RHO_MAX): its limits
    may be met, but its multipliers have not settled, so it is no optimum yet."""
    return not run["converged"] and not run["exhausted"] and run["rho"] <= RHO_MAX


def _al_message(run: dict) -> str:
    if run["converged"]:
        return f"The augmented Lagrangian converged in {run['iterations']} outer iterations with the constraints the variables control met"
    if run["rho"] > RHO_MAX:
        return "The constraints cannot all be met within the variable bounds"
    return f"Stopped after {run['iterations']} outer iterations of the augmented Lagrangian" + ("" if run["feasible"] else " with constraints not met")


def _at_bound(v, x: float, rel: float = 1e-9) -> bool:
    """On a bound to rel * max(1, |x|): the solver ends a few 1e-11 inside a bound it presses against."""
    return bool((v.min is not None and abs(x - v.min) < rel * max(1, abs(x))) or (v.max is not None and abs(x - v.max) < rel * max(1, abs(x))))


def sensitivity(mf: MeritFunction, x: np.ndarray, m: float, run=None, jacobian: bool = False):
    """d(merit)/d(variable) by central finite differences at the solution. ``run(points)`` (the parallel Jacobian's)
    evaluates the 2n points on the process pool; points it cannot deliver are evaluated here. Either way every point
    counts in mf.evaluations. With ``jacobian`` also the residuals' central-difference Jacobian (columns of NaN where
    a variable has no step or failed)."""
    sc = _scale_for(mf)
    lo, hi = mf.bounds()
    pairs = []
    for i in range(len(x)):
        h = 1e-6 * max(abs(x[i]), sc[i])
        a = x.copy()
        b = x.copy()
        a[i] = min(hi[i], x[i] + h)
        b[i] = max(lo[i], x[i] - h)
        pairs.append((a, b))
    live = [i for i, (a, b) in enumerate(pairs) if a[i] != b[i]]  # a variable without a step has no sensitivity
    todo = [p for i in live for p in pairs[i]]
    got = run(todo) if run is not None and todo else [None] * len(todo)
    mf.evaluations += sum(1 for g in got if g is not None)  # the pool's points count like the ones evaluated here
    at = {i: (got[2 * j], got[2 * j + 1]) for j, i in enumerate(live)}
    out: list[float | None] = []
    cols: list[np.ndarray | None] = []
    for i, (a, b) in enumerate(pairs):
        cols.append(None)
        if i not in at:
            out.append(None)
            continue
        try:
            ra, rb = at[i]
            ra = ra if ra is not None else mf.evaluate(a)[0]
            rb = rb if rb is not None else mf.evaluate(b)[0]
            out.append((mf.merit_from_residuals(ra) - mf.merit_from_residuals(rb)) / (a[i] - b[i]))
            cols[i] = (np.asarray(ra, dtype=float) - np.asarray(rb, dtype=float)) / (a[i] - b[i])
        except Exception:
            out.append(None)
    if not jacobian:
        return out
    size = next((len(c) for c in cols if c is not None), 0)
    J = np.full((size, len(x)), np.nan)
    for i, c in enumerate(cols):
        if c is not None and len(c) == size:
            J[:, i] = c
    return out, J
