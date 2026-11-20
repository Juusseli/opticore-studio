"""Exact constraints: an augmented Lagrangian around the bounded least-squares solver (engine.py).

Problem, in the split merit function (merit.py): minimise f(x) = |r_obj(x)|^2 subject to g_j(x) = 0 (targets) and
g_j(x) <= 0 (bounds). Each g is normalised by its constraint's tolerance s (|g| <= 1 is met); the variable bounds
stay with the solver itself.

* Residual form (Powell-Hestenes-Rockafellar):
  |T(R)|^2 = f/f0 + (rho/2) sum_targets (g + lam/rho)^2 + (rho/2) sum_bounds max(0, g + lam/rho)^2 + const,
  T = [r_obj / sqrt(f0), sqrt(rho/2) (g + lam/rho), sqrt(rho/2) max(0, g + lam/rho)].
  Its Jacobian is the raw Jacobian with scaled rows (the max is C1 in the square), so the parallel Jacobian of the
  raw residuals serves it. f0 is the objective at the start (1 when that is 0), so f/f0 = 1 there.
* Outer loop: after each inner solve lam <- lam + rho g (targets), max(0, lam + rho g) (bounds).
  rho grows tenfold when V = max(|g_target|, max(g_bound, -lam/rho)) is above V_TOL and did not fall below a
  quarter of the previous value (the first time: of its value at the start). rho0 = 10 / max(1, |c0|^2 / 2), c0
  being the violations at the start (Birgin & Martinez, Practical Augmented Lagrangian Methods for Constrained
  Optimization, SIAM 2014, ch. 4 and 12): at a start that meets the constraints a violation of one tolerance
  costs five times the starting objective; far from them the penalty starts at ten times the objective. Tried
  and rejected: a constant rho0 (feasibility first) drove a distant start into a poor region (merit 6.2 against
  0.94); 100 times the formula slowed a start that meets its constraints (cell phone lens, 2000 evaluations:
  RMS 5.28 against 4.96 um).
  An inner solve may use all but a small reserve of the budget: it is the optimisation itself.
  Converged: every constraint met, V <= V_TOL, the inner solve converged, and the next inner solve (restarted with
  a fresh trust region) improved the objective by less than 1e-6. Give up when rho exceeds RHO_MAX (the
  constraints cannot be met together within the bounds).
* Prices: the Lagrange multipliers lam of f/f0 + sum lam g, estimated at the design returned by least squares on
  the stationarity condition over the free variables (not at a bound), in the variables' scales D:
  min |D (grad f/f0 + sum_active lam_j grad g_j)|, lam_j >= 0 for bounds. The gradients come from the central
  differences of the sensitivities, so the estimate needs no evaluation of its own and exists also when the run
  ended on its budget. Active: the targets and the bounds within one tolerance of their limit. The remaining
  relative gradient |D (grad + G^T lam)| / |D grad| is reported as the stationarity; above STATIONARY the design is
  not a constrained optimum yet and the prices are marked approximate.
  Moving a target by dt changes the optimum by df = -f0 lam sigma dt / s to first order (sigma =
  merit.target_sign). This is reported as the objective merit predicted when the constraint is relaxed by its
  step (merit.relax_step). A row's target, tolerance, step, relaxed target and dmerit_dtarget are in the unit of its
  before/after values (merit.report_scale: the RMS spot in um, although its operand's target is in mm).
* Constraints no variable can change (merit.MeritFunction.fixed_operands) stay out of the solve and the ordering
  of designs: they are constant. A violated one is reported (fixed, not met) and makes the run infeasible.
* Global search: differential evolution minimises f/f0 + sum (violation s / step)^2. A violation of one relax
  step costs as much as the starting objective; the augmented Lagrangian then polishes the best point exactly.
"""

from __future__ import annotations

import math

import numpy as np

from .merit import EQUALITY, FAILED_CONSTRAINT, MeritFunction, constraint_scale, relax_step, report_scale, target_sign

V_TOL = 0.05  # complementarity and target error at convergence, in tolerances
RHO0 = 10.0  # at a start that meets the constraints a violation of one tolerance costs five times its objective
STATIONARY = 0.05  # relative gradient left at a constrained optimum (prices beyond it are approximate)
RHO_MAX = 1e10
MAX_OUTER = 30


def report_key(breakdown: list[dict], m: float) -> tuple[float, float]:
    """Order of designs by the report's rule, from a split merit function's breakdown (glass trials): a design whose
    limits are all met within one tolerance (the rows' 'met') beats any that misses one; among those the lower
    objective merit m, otherwise the smaller total violation beyond the tolerances. Limits no variable changes are
    left out (constant). Constraints.key is stricter (V_TOL): it orders the evaluations inside one solve."""
    unmet, excess = 0, 0.0
    for b in breakdown:
        if b.get("role") != "constraint" or b.get("fixed"):
            continue
        g = float(b.get("g", FAILED_CONSTRAINT))
        v = abs(g) if b["type"] in EQUALITY else max(0.0, g)
        unmet += 0 if b.get("met") else 1
        excess += max(0.0, v - 1.0)
    return (0.0, m) if unmet == 0 else (1.0, excess)


class Constraints:
    """The constraint part of a split merit function's residual vector R (merit.MeritFunction.layout)."""

    def __init__(self, mf: MeritFunction):
        self.mf = mf
        self.mask, self.cidx = mf.layout()
        self.index = list(mf.constraint_ops)  # operand indices
        self.ops = [mf.operands[k] for k in self.index]
        self.eq = np.array([o.type in EQUALITY for o in self.ops], dtype=bool)
        self.s = np.array([constraint_scale(o) for o in self.ops], dtype=float)
        self.sigma = np.array([target_sign(o) for o in self.ops], dtype=float)
        self.step = np.array([relax_step(o) for o in self.ops], dtype=float)
        self.live = np.array([k not in mf.fixed for k in self.index], dtype=bool)  # some variable can change it
        self.lam = np.zeros(len(self.ops))
        self.rho = 1.0
        self.f0 = 1.0

    # ------------------------------------------------------------------ measures
    def g(self, r: np.ndarray) -> np.ndarray:
        return np.asarray(r, dtype=float)[self.cidx]

    def f(self, r: np.ndarray) -> float:
        ro = np.asarray(r, dtype=float)[self.mask]
        return float(ro @ ro)

    def violations(self, g: np.ndarray) -> np.ndarray:
        """|g| for targets, max(0, g) for bounds (in tolerances); 0 for the constraints no variable changes."""
        return np.where(self.live, np.where(self.eq, np.abs(g), np.maximum(0.0, g)), 0.0)

    def excess(self, r: np.ndarray) -> float:
        """Sum of the violations beyond the tolerance: 0 when every constraint is met."""
        return float(np.sum(np.maximum(0.0, self.violations(self.g(r)) - 1.0)))

    def unmet(self, r: np.ndarray) -> int:
        return int(np.count_nonzero(self.violations(self.g(r)) > 1.0))

    def key(self, r: np.ndarray, m: float) -> tuple[float, float]:
        """Order of designs (feasibility rules, Deb 2000): every design that meets the constraints is better than
        any that does not; among those that meet them the lower objective, otherwise the smaller violation. Here a
        constraint counts as met within V_TOL of its tolerance, so the best design does not gain by using the
        tolerance up."""
        v = float(np.sum(np.maximum(0.0, self.violations(self.g(r)) - V_TOL)))
        return (0.0, m) if v == 0.0 else (1.0, v)

    # ------------------------------------------------------------------ augmented Lagrangian
    def start(self, r0: np.ndarray) -> None:
        f = self.f(r0)
        self.f0 = f if f > 1e-300 else 1.0
        c = self.violations(self.g(r0))
        self.rho = float(np.clip(RHO0 / max(1.0, 0.5 * float(c @ c)), 1e-12, RHO0))
        self.lam = np.zeros(len(self.ops))

    def residual(self, r: np.ndarray) -> np.ndarray:
        r = np.asarray(r, dtype=float)
        a = self.g(r) + self.lam / self.rho
        a = np.where(self.live, np.where(self.eq, a, np.maximum(0.0, a)), 0.0)
        return np.concatenate([r[self.mask] / math.sqrt(self.f0), math.sqrt(self.rho / 2.0) * a])

    def row_scale(self, r: np.ndarray) -> np.ndarray:
        """d T / d R, row by row (T's rows are ordered objective first, then the constraints)."""
        a = self.g(r) + self.lam / self.rho
        d = np.where(self.live & (self.eq | (a > 0.0)), math.sqrt(self.rho / 2.0), 0.0)
        return np.concatenate([np.full(int(self.mask.sum()), 1.0 / math.sqrt(self.f0)), d])

    def jacobian(self, r: np.ndarray, J: np.ndarray) -> np.ndarray:
        """T's Jacobian from the raw residuals' Jacobian J (rows in R's order)."""
        J = np.asarray(J, dtype=float)
        return self.row_scale(r)[:, None] * np.vstack([J[self.mask], J[self.cidx]])

    def measure(self, r: np.ndarray) -> float:
        g = self.g(r)
        v = np.where(self.live, np.where(self.eq, np.abs(g), np.abs(np.maximum(g, -self.lam / self.rho))), 0.0)
        return float(np.max(v)) if v.size else 0.0

    def update(self, r: np.ndarray) -> None:
        g = self.g(r)
        lam = self.lam + self.rho * g
        self.lam = np.where(self.live, np.where(self.eq, lam, np.maximum(0.0, lam)), 0.0)

    def penalty(self, r: np.ndarray) -> float:
        """The scalar for the global search (module notes)."""
        c = self.violations(self.g(r)) * self.s / np.maximum(self.step, 1e-300)
        return self.f(r) / self.f0 + float(c @ c)

    # ------------------------------------------------------------------ report
    def multipliers(self, r: np.ndarray, J: np.ndarray, free: np.ndarray, scale: np.ndarray) -> tuple[np.ndarray, float] | None:
        """(lam, stationarity) at a design from the residuals' Jacobian J (module notes); None without free variables."""
        from scipy.optimize import lsq_linear

        r = np.asarray(r, dtype=float)
        free = np.asarray(free, dtype=bool) & np.all(np.isfinite(J), axis=0)
        if not free.any():
            return None
        D = np.asarray(scale, dtype=float)[free]
        Jf = J[:, free]
        grad = D * (2.0 * (Jf[self.mask].T @ r[self.mask]) / self.f0)
        G = Jf[self.cidx] * D[None, :]  # rows: scaled constraint gradients
        g = self.g(r)
        act = self.live & (self.eq | (g >= -1.0)) & (np.linalg.norm(G, axis=1) > 0.0)
        lam = np.zeros(len(self.ops))
        gn = float(np.linalg.norm(grad))
        if act.any():
            lb = np.where(self.eq[act], -np.inf, 0.0)
            sol = lsq_linear(G[act].T, -grad, bounds=(lb, np.full(int(act.sum()), np.inf)), method="bvls")
            lam[act] = sol.x
        rest = float(np.linalg.norm(grad + G.T @ lam))
        return lam, (rest / gn if gn > 0 else 0.0)

    def report(self, r_before: np.ndarray, b_before: list[dict], r_after: np.ndarray, b_after: list[dict], mult: tuple[np.ndarray, float] | None) -> list[dict]:
        """One row per constraint: values before and after, met, and the Lagrange multiplier's prediction of the
        objective merit when the constraint is relaxed by its step (mult = self.multipliers(...))."""
        g0, g1 = self.g(r_before), self.g(r_after)
        f = self.f(r_after)
        m = math.sqrt(f)
        lam_all, stationarity = mult if mult is not None else (None, None)
        out = []
        for j, (k, o) in enumerate(zip(self.index, self.ops)):
            eq = bool(self.eq[j])
            met0 = bool(abs(g0[j]) <= 1.0) if eq else bool(g0[j] <= 1.0)
            met1 = bool(abs(g1[j]) <= 1.0) if eq else bool(g1[j] <= 1.0)
            u = report_scale(o)  # a row is in the breakdown's unit (the spot in um; its target is in mm)
            row = {
                "index": k,
                "type": o.type,
                "kind": "target" if eq else "bound",
                "surface_id": o.surface_id,
                "field": o.field,
                "configuration": o.configuration,
                "target": o.target * u,
                "tolerance": float(self.s[j]) * u,
                "before": b_before[k].get("value"),
                "after": b_after[k].get("value"),
                "unit": b_after[k].get("unit", ""),
                "met_before": met0,
                "met": met1,
                "fixed": bool(b_after[k].get("fixed", False)),
                "active": eq or bool(g1[j] > -1.0),
                "multiplier": None,
                "price": None,
            }
            if lam_all is not None and np.isfinite(lam_all[j]):
                lam = float(lam_all[j])
                row["multiplier"] = lam
                # df / dt (objective f = merit^2), and the relaxed target: a bound loosened, a target moved the cheaper way
                dfdt = -self.f0 * lam * self.sigma[j] / self.s[j]
                if eq:
                    dt = -math.copysign(self.step[j], dfdt) if dfdt != 0 else self.step[j]
                else:
                    dt = self.sigma[j] * self.step[j]
                f_new = max(0.0, f + dfdt * dt)
                m_new = math.sqrt(f_new)
                row["price"] = {
                    "dmerit_dtarget": float(dfdt / (2.0 * m)) / u if m > 0 else 0.0,
                    "relaxed_target": float(o.target + dt) * u,
                    "step": float(dt) * u,
                    "merit": m,
                    "merit_relaxed": m_new,
                    "change_percent": (m_new / m - 1.0) * 100.0 if m > 0 else 0.0,
                    "stationarity": stationarity,
                    "approximate": bool(stationarity is None or stationarity > STATIONARY),
                }
            out.append(row)
        return out
