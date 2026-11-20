"""Forbes Q-polynomials for rotationally symmetric aspheres (Qcon, Qbfs) and XY-polynomial term indexing.

Qcon (G. W. Forbes, Opt. Express 15, 5218 (2007)): a conic plus a sag-orthogonal departure

    z(r) = c r^2 / (1 + sqrt(1 - (1+k) c^2 r^2)) + u^4 sum_m a_m Q_m^con(u^2),   u = r / r_n,
    Q_m^con(x) = P_m^(0,4)(2x - 1)   (Jacobi polynomials; Q_m^con(1) = 1),

orthogonal over the disc: int_0^1 x^4 Q_m^con(x) Q_n^con(x) dx = delta_mn / (2n + 5).

Qbfs (same paper): a best-fit sphere plus a slope-orthogonal departure along its normal

    z(r) = c r^2 / (1 + sqrt(1 - c^2 r^2)) + u^2 (1 - u^2) / sqrt(1 - c^2 r^2) sum_m a_m Q_m^bfs(u^2),

with Q_m^bfs orthonormal under <f, g> = (2/pi) int_0^1 D[f](u) D[g](u) du / sqrt(1 - u^2),
D[p](u) = d/du [u^2 (1 - u^2) p(u^2)], and Q_m^bfs(0) > 0. They are evaluated with the recurrence of
Forbes, Opt. Express 18, 19700 (2010), Appendix A:

    P_0 = 2, P_1 = 6 - 8x, P_n = (2 - 4x) P_{n-1} - P_{n-2},
    Q_0 = 1, Q_1 = (13 - 16x) / sqrt(19), Q_n = (P_n - g_{n-1} Q_{n-1} - h_{n-2} Q_{n-2}) / f_n,
    f_0 = 2, f_1 = sqrt(19) / 2, g_0 = -1/2,
    h_{n-2} = -n (n - 1) / (2 f_{n-2}), g_{n-1} = -(1 + g_{n-2} h_{n-2}) / f_{n-1},
    f_n = sqrt(n (n + 1) + 3 - g_{n-1}^2 - h_{n-2}^2).

Derivatives follow by differentiating the recurrences (Qbfs) or from
d/dt P_m^(a,b)(t) = (m + a + b + 1)/2 P_{m-1}^(a+1,b+1)(t) (Qcon). Coefficients a_m are in mm.

XY polynomial terms are ordered by total degree and, within a degree, by falling power of x:
x, y, x^2, xy, y^2, x^3, x^2 y, x y^2, y^3, ... (term k = 1, 2, ...), each in normalised coordinates
x / R, y / R.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from scipy.special import eval_jacobi

MAX_Q_TERMS = 30
MAX_XY_DEGREE = 10
MAX_XY_TERMS = (MAX_XY_DEGREE + 1) * (MAX_XY_DEGREE + 2) // 2 - 1  # 65


# ----------------------------------------------------------------------------- Qbfs recurrence constants
@lru_cache(maxsize=None)
def _f(n: int) -> float:
    if n == 0:
        return 2.0
    if n == 1:
        return math.sqrt(19.0) / 2.0
    return math.sqrt(n * (n + 1) + 3.0 - _g(n - 1) ** 2 - _h(n - 2) ** 2)


@lru_cache(maxsize=None)
def _g(m: int) -> float:  # g_m
    if m == 0:
        return -0.5
    return -(1.0 + _g(m - 1) * _h(m - 1)) / _f(m)


@lru_cache(maxsize=None)
def _h(m: int) -> float:  # h_m (used as h_{n-2} with n = m + 2)
    n = m + 2
    return -n * (n - 1) / (2.0 * _f(m))


def qbfs(x, count: int) -> tuple[np.ndarray, np.ndarray]:
    """Q_0^bfs .. Q_{count-1}^bfs and their derivatives d/dx at x (arrays of shape (count, len(x)))."""
    x = np.atleast_1d(np.asarray(x, dtype=float))
    Q = np.zeros((count, x.size))
    dQ = np.zeros((count, x.size))
    if count == 0:
        return Q, dQ
    Q[0] = 1.0
    if count == 1:
        return Q, dQ
    s19 = math.sqrt(19.0)
    Q[1] = (13.0 - 16.0 * x) / s19
    dQ[1] = -16.0 / s19
    P2, P1 = np.full_like(x, 2.0), 6.0 - 8.0 * x  # P_{n-2}, P_{n-1}
    dP2, dP1 = np.zeros_like(x), np.full_like(x, -8.0)
    for n in range(2, count):
        P = (2.0 - 4.0 * x) * P1 - P2
        dP = -4.0 * P1 + (2.0 - 4.0 * x) * dP1 - dP2
        g, h, f = _g(n - 1), _h(n - 2), _f(n)
        Q[n] = (P - g * Q[n - 1] - h * Q[n - 2]) / f
        dQ[n] = (dP - g * dQ[n - 1] - h * dQ[n - 2]) / f
        P2, P1, dP2, dP1 = P1, P, dP1, dP
    return Q, dQ


def qcon(x, count: int) -> tuple[np.ndarray, np.ndarray]:
    """Q_0^con .. Q_{count-1}^con and their derivatives d/dx at x."""
    x = np.atleast_1d(np.asarray(x, dtype=float))
    t = 2.0 * x - 1.0
    Q = np.zeros((count, x.size))
    dQ = np.zeros((count, x.size))
    for m in range(count):
        Q[m] = eval_jacobi(m, 0.0, 4.0, t)
        if m > 0:
            dQ[m] = 2.0 * (m + 5.0) / 2.0 * eval_jacobi(m - 1, 1.0, 5.0, t)  # d/dx = 2 d/dt
    return Q, dQ


def series(kind: str, coefficients, x) -> tuple[np.ndarray, np.ndarray]:
    """S(x) = sum a_m Q_m(x) and dS/dx for kind 'qcon' or 'qbfs'."""
    a = np.asarray(coefficients, dtype=float)
    x = np.atleast_1d(np.asarray(x, dtype=float))
    if a.size == 0:
        return np.zeros_like(x), np.zeros_like(x)
    Q, dQ = (qcon if kind == "qcon" else qbfs)(x, a.size)
    return a @ Q, a @ dQ


def monomial_coefficients(kind: str, coefficients) -> list[float]:
    """S(x) = sum_m a_m Q_m(x) as a power series sum_j b_j x^j (exact polynomial algebra; for drawing)."""
    a = list(coefficients)
    if not a:
        return []
    P = np.polynomial.Polynomial
    if kind == "qcon":
        # P_m^(a,b)(t) = sum_s C(m+a, m-s) C(m+b, s) ((t-1)/2)^s ((t+1)/2)^(m-s); with t = 2x - 1 the
        # factors are (x - 1) and x
        out = P([0.0])
        for m, am in enumerate(a):
            if am == 0.0:
                continue
            q = P([0.0])
            for s_ in range(m + 1):
                q = q + math.comb(m, m - s_) * math.comb(m + 4, s_) * P([-1.0, 1.0]) ** s_ * P([0.0, 1.0]) ** (m - s_)
            out = out + am * q
        return [float(v) for v in out.coef]
    # Qbfs: run the recurrence on polynomial objects
    Q = [P([1.0]), P([13.0, -16.0]) / math.sqrt(19.0)]
    Pm2, Pm1 = P([2.0]), P([6.0, -8.0])
    for n in range(2, len(a)):
        Pn = P([2.0, -4.0]) * Pm1 - Pm2
        Q.append((Pn - _g(n - 1) * Q[n - 1] - _h(n - 2) * Q[n - 2]) / _f(n))
        Pm2, Pm1 = Pm1, Pn
    out = P([0.0])
    for am, q in zip(a, Q):
        out = out + am * q
    return [float(v) for v in out.coef]


# ----------------------------------------------------------------------------- XY terms
def xy_exponents(count: int) -> list[tuple[int, int]]:
    """(power of x, power of y) of XY terms 1..count (degree order, falling power of x)."""
    out: list[tuple[int, int]] = []
    d = 1
    while len(out) < count:
        for px in range(d, -1, -1):
            out.append((px, d - px))
            if len(out) == count:
                break
        d += 1
    return out


def xy_poly(coefficients) -> np.ndarray:
    """2-D monomial coefficient array c[i, j] (x^i y^j, normalised coordinates) of an XY polynomial."""
    exps = xy_exponents(len(coefficients))
    deg = max((i + j for i, j in exps), default=0)
    c = np.zeros((deg + 1, deg + 1))
    for (i, j), a in zip(exps, coefficients):
        c[i, j] += a
    return c


# ----------------------------------------------------------------------------- conversion from even aspheres
def even_asphere_sag(c: float, k: float, aspheric, r) -> np.ndarray:
    r = np.asarray(r, dtype=float)
    r2 = r * r
    z = c * r2 / (1.0 + np.sqrt(np.clip(1.0 - (1.0 + k) * c * c * r2, 0.0, None)))
    rp = r2 * r2
    for a in aspheric:
        z = z + a * rp
        rp = rp * r2
    return z


def to_qcon(c: float, k: float, aspheric, norm_radius: float) -> list[float]:
    """Qcon coefficients with the same curvature and conic that reproduce an even asphere exactly:
    sum_j A_{2j+4} r^(2j+4) = u^4 sum_j A_{2j+4} r_n^(2j+4) u^(2j), expanded in Q_m^con (one term per
    asphere coefficient; least squares on Chebyshev points, exact for a polynomial of that degree)."""
    a = list(aspheric)
    while a and a[-1] == 0.0:
        a.pop()
    if not a:
        return []
    M = len(a)
    x = 0.5 * (1.0 - np.cos(np.pi * (np.arange(4 * M + 8) + 0.5) / (4 * M + 8)))
    target = sum(aj * norm_radius ** (2 * j + 4) * x**j for j, aj in enumerate(a))
    Q, _ = qcon(x, M)
    coef, *_ = np.linalg.lstsq(Q.T, target, rcond=None)
    return [float(v) for v in coef]


def to_qbfs(c: float, k: float, aspheric, norm_radius: float, terms: int) -> tuple[float, list[float]]:
    """Best-fit-sphere curvature (the sphere through the vertex and the surface at r_n) and Qbfs
    coefficients fitted to an even asphere by least squares in sag over the aperture."""
    rn = norm_radius
    zn = float(even_asphere_sag(c, k, aspheric, rn))
    cb = 2.0 * zn / (rn * rn + zn * zn)
    u = 0.5 * (1.0 - np.cos(np.pi * (np.arange(400) + 0.5) / 400))  # dense near the ends
    u = np.sqrt(u)
    r = u * rn
    sphere = cb * r * r / (1.0 + np.sqrt(np.clip(1.0 - cb * cb * r * r, 0.0, None)))
    target = even_asphere_sag(c, k, aspheric, r) - sphere
    Q, _ = qbfs(u * u, terms)
    basis = (u * u * (1.0 - u * u) / np.sqrt(np.clip(1.0 - cb * cb * r * r, 1e-300, None)))[None, :] * Q
    coef, *_ = np.linalg.lstsq(basis.T, target, rcond=None)
    return cb, [float(v) for v in coef]


def convert_surface(surface: dict, to: str, norm_radius: float, terms: int | None = None) -> dict:
    """An even-asphere (or standard/conic) surface rewritten as a Qcon or Qbfs surface over r <= norm_radius,
    with the sag residual against the original. Qcon keeps the curvature and conic and is exact; Qbfs
    fits a best-fit sphere and `terms` Q terms (default: asphere terms + 3) by least squares."""
    from .surfaces import QShape

    if surface.get("type") not in ("standard", "even_asphere"):
        raise ValueError("Only standard and even-asphere surfaces can be converted to Q-type")
    if to not in ("qcon", "qbfs"):
        raise ValueError("Convert to 'qcon' or 'qbfs'")
    if not norm_radius > 0:
        raise ValueError("The normalisation radius must be positive")
    c = 0.0 if surface.get("radius") is None else 1.0 / surface["radius"]
    k = float(surface.get("conic") or 0.0)
    asph = list(surface.get("aspheric") or []) if surface.get("type") == "even_asphere" else []
    if to == "qcon":
        coef = to_qcon(c, k, asph, norm_radius)
        new = {"type": "qcon", "radius": surface.get("radius"), "conic": k, "aspheric": [], "q_coefficients": coef, "q_norm_radius": norm_radius}
        shape = QShape(c, k, "qcon", tuple(coef), norm_radius)
    else:
        m = terms if terms is not None else min(MAX_Q_TERMS, len([a for a in asph if a != 0.0]) + 3)
        cb, coef = to_qbfs(c, k, asph, norm_radius, max(1, m))
        new = {"type": "qbfs", "radius": None if cb == 0.0 else 1.0 / cb, "conic": 0.0, "aspheric": [], "q_coefficients": coef, "q_norm_radius": norm_radius}
        shape = QShape(cb, 0.0, "qbfs", tuple(coef), norm_radius)
    r = np.linspace(0.0, norm_radius, 401)
    res = shape.sag(r * r) - even_asphere_sag(c, k, asph, r)
    return {"surface": new, "residual_rms_mm": float(np.sqrt(np.mean(res * res))), "residual_max_mm": float(np.max(np.abs(res))), "norm_radius_mm": norm_radius}
