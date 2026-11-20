"""Guided modes of a step-index optical fibre from Maxwell's equations.

Core radius a, indices n1 (core) > n2 (cladding), vacuum wavelength lambda, k0 = 2 pi / lambda.
With the propagation constant beta = k0 n_eff:

    u = a sqrt(k0^2 n1^2 - beta^2),  w = a sqrt(beta^2 - k0^2 n2^2),  u^2 + w^2 = V^2,
    V = k0 a sqrt(n1^2 - n2^2) = k0 a NA

Exact vector modes (Snitzer's eigenvalue equation; Snyder & Love, "Optical Waveguide Theory",
ch. 12; Okamoto, "Fundamentals of Optical Waveguides", ch. 3), with xi = J'_nu(u) / (u J_nu(u)),
kappa = K'_nu(w) / (w K_nu(w)), delta = n2^2 / n1^2:

    (xi + kappa)(xi + delta kappa) = nu^2 (1/u^2 + 1/w^2)(1/u^2 + delta/w^2)
    TE_0m:  xi + kappa = 0          TM_0m:  xi + delta kappa = 0
    hybrid: xi = -(1 + delta) kappa / 2 -+ sqrt(((1 - delta) kappa / 2)^2 + R)
            (minus: HE_nu,m, plus: EH_nu,m; R the right-hand side)

The equations are multiplied through by u J_nu(u) (and K_0) so that they have no poles; roots
are bracketed on a fine u grid and refined with Brent's method.

Weakly guiding (scalar LP) modes, the limit delta -> 1:

    u J_{l-1}(u) / J_l(u) = - w K_{l-1}(w) / K_l(w),   E(r) = J_l(u r/a)/J_l(u) (r < a),
                                                        K_l(w r/a)/K_l(w) (r > a), times cos(l phi)

Mode field diameters of LP01: Petermann II (2 sqrt(2) [int E^2 r dr / int E'^2 r dr]^(1/2), the
quantity that governs splice and lens coupling), the 1/e^2 intensity diameter, and the waist of
the Gaussian with the largest overlap (and that overlap).
"""

from __future__ import annotations

import math

import numpy as np
from scipy.integrate import trapezoid
from scipy.optimize import brentq, minimize_scalar
from scipy.special import jn_zeros, jv, jvp, kv, kvp

J01 = float(jn_zeros(0, 1)[0])  # 2.404826: single-mode cut-off of V
MAX_MODES = 400


class FibreError(ValueError):
    pass


def _roots(G, V: float, n: int = 6000) -> list[float]:
    """Roots of G(u) in (0, V), ascending; G is vectorised over u. The scan starts at 1e-3 V: the
    hybrid-mode functions vanish trivially as u -> 0, and no guided mode has b > 0.999999."""
    u = np.linspace(1e-3 * V, V * (1 - 1e-9), n)
    with np.errstate(all="ignore"):
        f = G(u)
    g = lambda x: float(G(np.array([x]))[0])  # noqa: E731
    out: list[float] = []
    idx = np.nonzero(np.isfinite(f[:-1]) & np.isfinite(f[1:]) & (np.sign(f[:-1]) * np.sign(f[1:]) < 0))[0]
    for i in idx:
        try:
            r = brentq(g, u[i], u[i + 1], xtol=1e-14, rtol=1e-14, maxiter=200)
        except ValueError:
            continue
        if not out or abs(r - out[-1]) > 1e-10 * V:
            out.append(float(r))
    return out


def _w(u, V: float):
    return np.sqrt(np.maximum(V * V - np.asarray(u, dtype=float) ** 2, 0.0))


def lp_equation(l: int, V: float):
    def G(u: np.ndarray) -> np.ndarray:
        w = _w(u, V)
        jm = -jv(1, u) if l == 0 else jv(l - 1, u)
        km = kv(1, w) if l == 0 else kv(l - 1, w)
        return np.where(w > 0, u * jm * kv(l, w) + w * km * jv(l, u), np.nan)

    return G


def vector_equation(kind: str, nu: int, V: float, delta: float):
    """kind: TE, TM (nu = 0), HE or EH (nu >= 1); continuous (pole-free) form, vectorised in u."""

    def G(u: np.ndarray) -> np.ndarray:
        w = _w(u, V)
        if kind in ("TE", "TM"):
            d = 1.0 if kind == "TE" else delta
            return np.where(w > 0, jv(1, u) * w * kv(0, w) + d * kv(1, w) * u * jv(0, u), np.nan)
        kap = kvp(nu, w) / (w * kv(nu, w))
        R = nu * nu * (1 / u**2 + 1 / w**2) * (1 / u**2 + delta / w**2)
        s = np.sqrt(((1 - delta) * kap / 2) ** 2 + R)
        xi = -(1 + delta) * kap / 2 + (-s if kind == "HE" else s)
        return np.where(w > 0, jvp(nu, u) - u * jv(nu, u) * xi, np.nan)

    return G


def lp_field(l: int, u: float, w: float, r_over_a: np.ndarray) -> np.ndarray:
    x = np.asarray(r_over_a, dtype=float)
    out = np.empty_like(x)
    core = x <= 1.0
    out[core] = jv(l, u * x[core]) / jv(l, u)
    out[~core] = kv(l, w * x[~core]) / kv(l, w)
    return out


def _lp01_diameters(u: float, w: float, a: float) -> dict:
    """MFDs of LP01 (same length unit as a)."""
    r_max = a * (1.0 + 30.0 / max(w, 1e-3))
    r = np.linspace(0.0, r_max, 40001)
    E = lp_field(0, u, w, r / a)
    E = E / E[0]
    dE = np.gradient(E, r)
    mfd_p2 = 2 * math.sqrt(2.0) * math.sqrt(trapezoid(E * E * r, r) / trapezoid(dE * dE * r, r))
    # 1/e^2 intensity radius: E = E(0)/e
    k = int(np.argmax(E < math.exp(-1.0)))
    r1 = float(np.interp(math.exp(-1.0), [E[k], E[k - 1]], [r[k], r[k - 1]])) if k > 0 else float("nan")
    norm = trapezoid(E * E * r, r)

    def overlap(wg: float) -> float:
        G = np.exp(-(r / wg) ** 2)
        return trapezoid(E * G * r, r) ** 2 / (norm * trapezoid(G * G * r, r))

    best = minimize_scalar(lambda x: -overlap(x), bounds=(0.2 * a, 10 * a), method="bounded", options={"xatol": 1e-9 * a})
    return {"mfd_petermann2": mfd_p2, "mfd_1e2": 2 * r1, "gaussian_waist": float(best.x), "gaussian_overlap": float(-best.fun)}


def fibre_modes(wavelength_um: float, core_radius_um: float, n_core: float, n_clad: float, vector: bool = True, profiles: int = 8) -> dict:
    """LP modes (weak guidance) and, with `vector`, the exact vector modes of a step-index fibre."""
    lam, a = float(wavelength_um), float(core_radius_um)
    if lam <= 0 or a <= 0:
        raise FibreError("Wavelength and core radius must be positive")
    if not n_core > n_clad > 0:
        raise FibreError("The core index must exceed the cladding index (step-index guidance)")
    k0 = 2 * math.pi / lam
    NA = math.sqrt(n_core**2 - n_clad**2)
    V = k0 * a * NA
    delta = n_clad**2 / n_core**2
    neff = lambda u: math.sqrt(n_core**2 - (u / (k0 * a)) ** 2)  # noqa: E731

    lp = []
    l = 0
    while len(lp) < MAX_MODES:
        roots = _roots(lp_equation(l, V), V)
        if not roots:
            break
        for m, u in enumerate(roots, start=1):
            lp.append({"name": f"LP{l}{m}", "l": l, "m": m, "u": u, "w": float(_w(u, V)), "neff": neff(u), "b": 1 - (u / V) ** 2, "degeneracy": 2 if l == 0 else 4})
        l += 1
    lp.sort(key=lambda x: -x["neff"])
    if not lp:  # pragma: no cover - LP01 has no cut-off
        raise FibreError("No guided mode found")

    vec = []
    if vector:
        for kind in ("TE", "TM"):
            for m, u in enumerate(_roots(vector_equation(kind, 0, V, delta), V), start=1):
                vec.append({"name": f"{kind}0{m}", "kind": kind, "nu": 0, "m": m, "u": u, "neff": neff(u), "degeneracy": 1})
        nu = 1
        while nu <= 60 and len(vec) < MAX_MODES:
            found = False
            for kind in ("HE", "EH"):
                for m, u in enumerate(_roots(vector_equation(kind, nu, V, delta), V), start=1):
                    vec.append({"name": f"{kind}{nu}{m}", "kind": kind, "nu": nu, "m": m, "u": u, "neff": neff(u), "degeneracy": 2})
                    found = True
            if not found:
                break
            nu += 1
        vec.sort(key=lambda x: -x["neff"])

    u01, w01 = lp[0]["u"], lp[0]["w"]
    diam = _lp01_diameters(u01, w01, a)
    x = np.linspace(0.0, 3.0, 301)
    prof = [{"name": m["name"], "l": m["l"], "r_um": (x * a).tolist(), "field": lp_field(m["l"], m["u"], m["w"], x).tolist()} for m in lp[:profiles]]
    marcuse = 0.65 + 1.619 * V**-1.5 + 2.879 * V**-6  # w/a, Gaussian approximation (1.2 < V < 2.4)
    notes = []
    if V < 1.2:
        notes.append("V < 1.2: the mode spreads far into the cladding (bend-sensitive); MFDs are large")
    if 1 - delta > 0.05:
        notes.append("Large index contrast: the vector modes differ noticeably from the LP approximation")
    return {
        "wavelength_um": lam,
        "core_radius_um": a,
        "n_core": n_core,
        "n_clad": n_clad,
        "na": NA,
        "v_number": V,
        "single_mode": V < J01,
        "cutoff_wavelength_um": 2 * math.pi * a * NA / J01,
        "lp_modes": lp,
        "mode_count": int(sum(m["degeneracy"] for m in lp)),
        "vector_modes": vec,
        "lp01": {**diam, "marcuse_mfd": 2 * a * marcuse, "neff": lp[0]["neff"]},
        "profiles": prof,
        "notes": notes,
        "method": "Step-index fibre: exact vector eigenvalue equation (Snitzer) for TE, TM, HE and EH modes and the weakly guiding LP equation, solved in u by bracketing and Brent's method; LP01 mode field diameters by Petermann II, 1/e^2 intensity and best-overlap Gaussian",
    }
