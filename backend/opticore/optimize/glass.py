"""Glass substitution: discrete optimisation of materials.

A `material` variable lets the optimiser replace the glass after a surface by
any glass from its candidate list (default: every built-in material of
category "glass" whose data range covers all system wavelengths, plus the
current glass).

Algorithm (greedy coordinate search with re-optimisation):

  1. Optimise the continuous variables locally with the current glasses.
  2. For each material variable in turn, try every candidate. For each trial
     the continuous variables are re-optimised locally (trust-region least
     squares, warm-started from the best design so far, with an equal share
     of the evaluation budget); the candidate is kept if the re-optimised
     merit is lower than the best so far. With exact limits a trial that
     meets every limit within one tolerance (the report's rule) beats any
     that misses one, whatever their merits (constrained.report_key).
  3. Repeat full passes until a pass brings no improvement (at most
     `MAX_PASSES`) or the budget is exhausted.

This finds a local optimum in the discrete x continuous space. It is not an
exhaustive search over glass combinations; the result notes how many
combinations were tried. Material variables cannot be per-configuration and
cannot act on a material that the configuration editor controls.
"""

from __future__ import annotations

import time

import numpy as np

from ..materials import MaterialLibrary
from ..model import OpticalSystem
from .merit import MeritFunction, OptimizationSpec, Variable, config_operand_index, exact_constraints, get_variable_value

MAX_PASSES = 3
NON_GLASS = {"AIR", "VACUUM", "MIRROR", ""}


def split_variables(spec: OptimizationSpec) -> tuple[OptimizationSpec, list[Variable]]:
    glass = [v for v in spec.variables if v.enabled and v.parameter == "material"]
    cont = spec.model_copy(update={"variables": [v for v in spec.variables if v.parameter != "material"]})
    return cont, glass


def candidates_for(system: OpticalSystem, v: Variable, lib: MaterialLibrary) -> list[str]:
    s = next(x for x in system.surfaces if x.id == v.surface_id)
    names = [n.upper() for n in v.candidates] if v.candidates else [m.name for m in lib.all() if m.category == "glass"]
    out = []
    for n in dict.fromkeys([s.material.upper(), *names]):
        if not lib.has(n) or n in NON_GLASS:
            continue
        m = lib.get(n)
        if all(m.in_range(w.value) for w in system.wavelengths):
            out.append(n)
    return out


def validate_glass_variables(system: OpticalSystem, glass: list[Variable], custom_materials=()) -> dict[str, list[str]]:
    lib = MaterialLibrary(custom_materials)
    pos = {s.id: i for i, s in enumerate(system.surfaces)}
    out: dict[str, list[str]] = {}
    for v in glass:
        if v.surface_id not in pos:
            raise ValueError(f"Variable refers to unknown surface id '{v.surface_id}'")
        i = pos[v.surface_id]
        s = system.surfaces[i]
        if v.configuration is not None:
            raise ValueError("Material variables cannot be per-configuration")
        if config_operand_index(system, v.surface_id, "material") is not None or (
            system.multi_config and any(o.parameter == "material" and o.surface_id == v.surface_id for o in system.multi_config.operands)
        ):
            raise ValueError(f"Surface {i}: the material is set per configuration and cannot be substituted")
        if s.type == "coordinate_break" or s.material.upper() in NON_GLASS or i in (0, len(system.surfaces) - 1):
            raise ValueError(f"Surface {i}: glass substitution needs a glass after the surface")
        if v.surface_id in out:
            raise ValueError(f"Surface {i}: duplicate material variable")
        for c in v.candidates or []:
            if not lib.has(c):
                raise ValueError(f"Surface {i}: unknown candidate material '{c}'")
        cands = candidates_for(system, v, lib)
        if len(cands) < 2:
            raise ValueError(f"Surface {i}: fewer than two usable candidate glasses (data must cover all system wavelengths)")
        out[v.surface_id] = cands
    return out


def _with_materials(system: OpticalSystem, mats: dict[str, str]) -> OpticalSystem:
    d = system.model_dump()
    for s in d["surfaces"]:
        if s["id"] in mats:
            s["material"] = mats[s["id"]]
    return OpticalSystem.model_validate(d)


def optimize_with_glass(system, spec, custom_materials, progress, control, on_update, continuous_optimize, ns=None, parallel=None) -> dict:
    """Outer glass-substitution loop around `continuous_optimize` (engine._optimize_continuous). `evaluations` counts
    the search (the trials' own searches and the evaluations without continuous variables, at most max_evaluations);
    the trials' closing evaluations and the final design's sensitivities are `closing_evaluations`. The trials skip
    their sensitivities: only the design returned needs them."""
    from .constrained import Constraints, report_key
    from .engine import Cancelled, Progress, _at_bound, _scale_for, sensitivity  # noqa: F401

    cont, glass = split_variables(spec)
    # exact constraints (engine.py): a trial that meets every limit by the report's rule (within one tolerance)
    # beats any that misses one, then the objective merit (constrained.report_key). The stricter order inside a
    # solve (V_TOL) would reject trials whose short budget met the limits but not to V_TOL.
    exact = exact_constraints(cont)

    def merit_function(sysm):
        return MeritFunction(sysm, cont, custom_materials, ns=ns, split=exact)

    def key_of(breakdown, m):
        return report_key(breakdown, m) if exact else (0.0, m)

    cands = validate_glass_variables(system, glass, custom_materials)
    has_cont = any(v.enabled for v in cont.variables)
    budget = spec.max_evaluations
    n_trials_pass = sum(len(c) - 1 for c in cands.values())
    per = max(8, budget // (1 + 2 * max(1, n_trials_pass))) if has_cont else 1
    need = 4 if has_cont else 1  # the smallest trial worth starting
    used = 1  # the starting design's evaluation below
    closing = 0
    tried = 0
    seen: set[tuple] = set()
    notes: list[str] = []
    start = time.time()

    base_mf = merit_function(system)
    r0, breakdown0 = base_mf.evaluate(base_mf.x0)
    m_orig = base_mf.merit_from_residuals(r0)
    best_key = key_of(breakdown0, m_orig)
    progress.initial = m_orig
    progress.best = m_orig
    progress.current = m_orig
    progress.best_x = base_mf.x0.copy()
    progress.history.append((0, m_orig, m_orig))
    mats = {sid: next(s.material.upper() for s in system.surfaces if s.id == sid) for sid in cands}
    best_mats = dict(mats)
    progress.best_materials = dict(best_mats)
    best_system = system
    status = "converged"
    message = ""

    def trial(materials: dict[str, str], start_system: OpticalSystem, b: int) -> tuple[tuple, float, OpticalSystem]:
        """(order key, merit, system) of a glass combination, re-optimised when there are continuous variables."""
        nonlocal used, closing
        sysm = _with_materials(start_system, materials)
        if has_cont:
            inner = Progress()
            res = continuous_optimize(sysm, cont.model_copy(update={"max_evaluations": max(b, need), "algorithm": "local"}), custom_materials, inner, control, None, ns=ns, use_pool=parallel, sensitivities=False)
            used += res["evaluations"]
            closing += res["closing_evaluations"]
            if res["status"] == "cancelled":
                raise Cancelled()
            # the result's own breakdown of the design it returns: no evaluation of its own
            return key_of(res["operands_after"], res["final_merit"]), res["final_merit"], OpticalSystem.model_validate(res["system"])
        mf = merit_function(sysm)
        r, bd = mf.evaluate(mf.x0)
        used += 1
        m = mf.merit_from_residuals(r)
        return key_of(bd, m), m, sysm

    def record(m: float):
        progress.evaluations = used
        progress.current = m
        if len(progress.history) < 4000:
            progress.history.append((used, m, progress.best))
        if on_update:
            on_update(progress)

    try:
        progress.phase = "local (current glasses)"
        k, m, sysm = trial(best_mats, system, min(per, budget - used))
        if k < best_key:
            best_key = k
            progress.best = m
            best_system = sysm
            progress.best_x = merit_function(best_system).x0 if has_cont else progress.best_x
        record(m)
        for p in range(MAX_PASSES):
            improved = False
            for sid, options in cands.items():
                idx = next(i for i, s in enumerate(system.surfaces) if s.id == sid)
                for k, c in enumerate(options):
                    if c == best_mats[sid]:
                        continue
                    if budget - used < need:
                        raise _Budget()
                    progress.phase = f"glass pass {p + 1}: surface {idx} → {c} ({k + 1}/{len(options)})"
                    trial_mats = {**best_mats, sid: c}
                    try:
                        k, m, sysm = trial(trial_mats, best_system, min(per, budget - used))
                    except Cancelled:
                        raise
                    except Exception as exc:  # invalid combination: skip the candidate
                        notes.append(f"Surface {idx} with {c} skipped: {exc}")
                        continue
                    tried += 1
                    seen.add(tuple(sorted(trial_mats.items())))
                    if k[0] < best_key[0] or (k[0] == best_key[0] and k[1] < best_key[1] * (1 - 1e-9)):
                        best_key = k
                        progress.best = m
                        best_mats = trial_mats
                        best_system = sysm
                        progress.best_materials = dict(best_mats)
                        if has_cont:
                            progress.best_x = merit_function(best_system).x0
                        improved = True
                    record(m)
            if not improved:
                message = f"Glass substitution converged after {p + 1} pass(es); {tried} glass trials"
                break
        else:
            message = f"Stopped after {MAX_PASSES} passes; {tried} glass trials"
    except Cancelled:
        status = "cancelled"
        message = "Cancelled by user; best solution found so far is returned"
    except _Budget:
        status = "max_evaluations"
        message = f"Evaluation budget exhausted after {tried} glass trials; best solution found so far is returned"

    progress.phase = "done"
    final_mf = merit_function(best_system)
    rb, breakdown_b = final_mf.evaluate(final_mf.x0)
    mb = final_mf.merit_from_residuals(rb)
    xb = final_mf.x0
    sens, jac_b = sensitivity(final_mf, xb, mb, jacobian=True) if has_cont else ([], None)
    closing += final_mf.evaluations
    constraint_rows = None
    if exact:
        cons = Constraints(final_mf)
        cons.f0 = cons.f(r0) or 1.0
        mult = None
        if jac_b is not None:
            free = np.array([q is not None and not _at_bound(v, b) for v, b, q in zip(final_mf.variables, xb, sens)], dtype=bool)
            mult = cons.multipliers(rb, jac_b, free, _scale_for(final_mf))
        constraint_rows = cons.report(r0, breakdown0, rb, breakdown_b, mult)
        unmet = [c for c in constraint_rows if not c["met"]]
        if unmet:
            notes.append(f"{len(unmet)} of {len(constraint_rows)} constraints are not met by any glass combination tried; the design returned violates them least")
            if status == "converged":
                status = "infeasible"
    total = int(np.prod([len(c) for c in cands.values()]))
    seen.add(tuple(sorted(mats.items())))
    notes.append(
        f"Greedy glass substitution: {tried} trial(s) covering {len(seen)} of {total} possible glass combinations, each with local re-optimisation; "
        "the result is a local optimum, not an exhaustive search."
    )
    cont_vars = final_mf.variables
    return {
        "status": status,
        "message": message,
        "notes": notes,
        "algorithm": "glass_substitution",
        "constraints": constraint_rows,
        "constraint_mode": "exact" if exact else "penalty",
        "initial_merit": m_orig,
        "final_merit": mb,
        "improvement_percent": (1 - mb / m_orig) * 100 if m_orig > 0 else 0.0,
        "evaluations": used,
        "closing_evaluations": closing,
        "variables": [
            {
                "surface_id": v.surface_id,
                "configuration": v.configuration,
                "parameter": v.parameter,
                "initial": float(get_variable_value(system, v)),
                "final": float(b),
                "min": v.min,
                "max": v.max,
                "at_bound": _at_bound(v, b),
                "sensitivity": s,
            }
            for v, b, s in zip(cont_vars, xb, sens if sens else [None] * len(cont_vars))
        ],
        "materials": [
            {"surface_id": sid, "initial": mats[sid], "final": best_mats[sid], "candidates": cands[sid]} for sid in cands
        ],
        "operands_before": breakdown0,
        "operands_after": breakdown_b,
        "history": progress.history,
        "system": best_system.model_dump(),
        "elapsed_s": time.time() - start,
    }


class _Budget(Exception):
    pass
