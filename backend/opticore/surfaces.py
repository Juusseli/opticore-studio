"""Surface shape models: sag, normals and exact ray intersection (vectorised).

All functions work in the surface's local frame, with the vertex at the origin
and the optical axis along +z.

Standard surface (sphere / conic / plane), curvature c = 1/R, conic k:
    z(r) = c r^2 / (1 + sqrt(1 - (1+k) c^2 r^2))
Even asphere adds   sum_j A_{2j+4} r^(2j+4)   for coefficients [A4, A6, ...].
(The r^2 term is omitted because it duplicates the base curvature.)

Intersection: conics are solved in closed form using a numerically stable
quadratic root that selects the sheet containing the vertex. Aspheres are
refined with Newton iteration starting from the base-conic solution.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Ray status codes shared by the tracer
OK = 0
MISS = 1
TIR = 2
VIGNETTED = 3
OUT_OF_DOMAIN = 4
NO_CONVERGENCE = 5
EVANESCENT = 6
OBSCURED = 7

STATUS_TEXT = {
    OK: "ok",
    MISS: "ray misses surface",
    TIR: "total internal reflection",
    VIGNETTED: "clipped by aperture",
    OUT_OF_DOMAIN: "outside surface definition domain",
    NO_CONVERGENCE: "intersection did not converge",
    EVANESCENT: "diffraction order is evanescent",
    OBSCURED: "blocked by central obscuration",
}

NEWTON_TOL = 1e-12  # mm
NEWTON_MAX_ITER = 60


@dataclass(frozen=True)
class Shape:
    curvature: float = 0.0
    conic: float = 0.0
    aspheric: tuple[float, ...] = field(default_factory=tuple)

    @property
    def is_plane(self) -> bool:
        return self.curvature == 0.0 and not any(self.aspheric)

    @property
    def has_asphere(self) -> bool:
        return any(a != 0.0 for a in self.aspheric)

    # ------------------------------------------------------------------
    def _root_term(self, r2: np.ndarray) -> np.ndarray:
        c, k = self.curvature, self.conic
        return 1.0 - (1.0 + k) * c * c * r2

    def domain_ok(self, r2: np.ndarray) -> np.ndarray:
        return self._root_term(r2) >= -1e-14

    def sag(self, r2: np.ndarray | float) -> np.ndarray:
        r2 = np.asarray(r2, dtype=float)
        c = self.curvature
        root = np.sqrt(np.clip(self._root_term(r2), 0.0, None))
        z = c * r2 / (1.0 + root)
        rp = r2 * r2  # r^4
        for a in self.aspheric:
            if a != 0.0:
                z = z + a * rp
            rp = rp * r2
        return z

    def slope_over_r(self, r2: np.ndarray) -> np.ndarray:
        """(dz/dr) / r, finite at r = 0."""
        c = self.curvature
        root = np.sqrt(np.clip(self._root_term(r2), 1e-300, None))
        g = c / root
        rp = r2  # r^2 multiplies 4*A4 (d/dr r^4 = 4 r^3 -> /r = 4 r^2)
        for j, a in enumerate(self.aspheric):
            if a != 0.0:
                g = g + (2 * j + 4) * a * rp
            rp = rp * r2
        return g

    def sag_x(self, r2: np.ndarray | float) -> np.ndarray:
        """x-z profile (identical to the y-z profile for rotationally symmetric surfaces)."""
        return self.sag(r2)

    def sag_xy(self, x, y):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        return self.sag(x * x + y * y)

    def normals(self, p: np.ndarray) -> np.ndarray:
        """Unit surface normals at local points p (N,3), oriented towards +z."""
        r2 = p[:, 0] ** 2 + p[:, 1] ** 2
        g = self.slope_over_r(r2)
        n = np.stack([-g * p[:, 0], -g * p[:, 1], np.ones_like(g)], axis=1)
        return n / np.linalg.norm(n, axis=1, keepdims=True)

    # ------------------------------------------------------------------
    def intersect(self, P: np.ndarray, D: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return (s, status) such that P + s D lies on the surface.

        s may be negative (virtual propagation is allowed in sequential mode).
        """
        n = P.shape[0]
        s = np.full(n, np.nan)
        status = np.zeros(n, dtype=np.int8)
        c, k = self.curvature, self.conic

        if c == 0.0:
            with np.errstate(divide="ignore", invalid="ignore"):
                s0 = -P[:, 2] / D[:, 2]
            bad = ~np.isfinite(s0)
            status[bad] = MISS
            s[~bad] = s0[~bad]
        else:
            e = 1.0 + k
            a = c * (D[:, 0] ** 2 + D[:, 1] ** 2 + e * D[:, 2] ** 2)
            b = c * (P[:, 0] * D[:, 0] + P[:, 1] * D[:, 1] + e * P[:, 2] * D[:, 2]) - D[:, 2]
            cc = c * (P[:, 0] ** 2 + P[:, 1] ** 2 + e * P[:, 2] ** 2) - 2.0 * P[:, 2]
            disc = b * b - a * cc
            miss = disc < 0.0
            sq = np.sqrt(np.where(miss, 0.0, disc))
            # Both roots in cancellation-free form; q = -(b + sign(b) sq).
            sign_b = np.where(b >= 0.0, 1.0, -1.0)
            q = -(b + sign_b * sq)
            with np.errstate(divide="ignore", invalid="ignore"):
                s_a = np.where(q != 0.0, q / a, -b / a)
                s_b = np.where(q != 0.0, cc / q, -b / a)
            # The quadric has two sheets (sphere: two hemispheres); keep the root
            # on the vertex sheet z = sag(r). Choosing by sign(b) alone fails once
            # the ray origin lies beyond the centre of curvature.
            def sheet_ok(sr):
                fin = np.isfinite(sr) & ~miss
                qp = P + np.where(fin, sr, 0.0)[:, None] * D
                r2 = qp[:, 0] ** 2 + qp[:, 1] ** 2
                dom = self.domain_ok(r2)
                zs = self.sag(np.where(dom, r2, 0.0))
                on = fin & dom & (np.abs(qp[:, 2] - zs) <= 1e-7 * (1.0 + np.abs(zs)))
                return on, fin & ~dom, r2

            on_a, out_a, r2a = sheet_ok(s_a)
            on_b, out_b, r2b = sheet_ok(s_b)
            # both on the vertex sheet (possible for hyperboloids/paraboloids):
            # take the intersection nearer the axis
            pick_a = on_a & (~on_b | (r2a <= r2b))
            pick_b = on_b & ~pick_a
            s[pick_a] = s_a[pick_a]
            s[pick_b] = s_b[pick_b]
            none = ~(pick_a | pick_b)
            status[none] = MISS
            status[none & (out_a | out_b)] = OUT_OF_DOMAIN
            status[miss] = MISS

        if self.has_asphere:
            s, status = self._newton(P, D, s, status)
        return s, status

    def _newton(self, P: np.ndarray, D: np.ndarray, s: np.ndarray, status: np.ndarray):
        s = s.copy()
        status = status.copy()
        # rays where the base conic failed: start from the vertex plane
        restart = (status != OK) & (np.abs(D[:, 2]) > 0)
        s[restart] = -P[restart, 2] / D[restart, 2]
        status[restart] = OK
        active = status == OK
        converged = np.zeros_like(active)
        for _ in range(NEWTON_MAX_ITER):
            idx = np.nonzero(active & ~converged)[0]
            if idx.size == 0:
                break
            q = P[idx] + s[idx, None] * D[idx]
            r2 = q[:, 0] ** 2 + q[:, 1] ** 2
            dom = self.domain_ok(r2)
            f = q[:, 2] - self.sag(r2)
            g = self.slope_over_r(r2)
            fp = D[idx, 2] - g * (q[:, 0] * D[idx, 0] + q[:, 1] * D[idx, 1])
            with np.errstate(divide="ignore", invalid="ignore"):
                step = f / fp
            badstep = ~np.isfinite(step) | ~dom
            status[idx[badstep]] = OUT_OF_DOMAIN
            active[idx[badstep]] = False
            ok = ~badstep
            s[idx[ok]] -= step[ok]
            converged[idx[ok & (np.abs(step) < NEWTON_TOL)]] = True
        nc = active & ~converged
        status[nc] = NO_CONVERGENCE
        if np.any(converged):
            q = P[converged] + s[converged, None] * D[converged]
            r2 = q[:, 0] ** 2 + q[:, 1] ** 2
            status[np.nonzero(converged)[0][~self.domain_ok(r2)]] = OUT_OF_DOMAIN
        return s, status


@dataclass(frozen=True)
class OddShape:
    """Odd asphere: base conic plus a polynomial in r with odd and even powers,
    z = c r^2 / (1 + sqrt(1 - (1 + k) c^2 r^2)) + sum_i beta_i r^i (i = 1 ... N).

    `curvature` is the paraxial vertex curvature c + 2 beta_2; `seidel_b4` the fourth-order coefficient for the
    Seidel sums, 8 x (the r^4 sag coefficient (1 + k) c^3 / 8 + beta_4) - curvature^3 (k c^3 + 8 beta_4 when
    beta_2 = 0). The r^1 and r^3 terms have no paraxial or third-order equivalent (r^1 makes a cone at the
    vertex) and appear only in real-ray analyses. Intersection: Newton iteration from the base conic."""

    base_curvature: float = 0.0
    conic: float = 0.0
    coefficients: tuple[float, ...] = field(default_factory=tuple)
    aspheric: tuple[float, ...] = ()
    kind: str = "odd"  # profiles are B-spline interpolations in CAD export

    def __post_init__(self):
        object.__setattr__(self, "base", Shape(self.base_curvature, self.conic, ()))

    def _beta(self, i: int) -> float:
        return self.coefficients[i - 1] if 0 < i <= len(self.coefficients) else 0.0

    @property
    def curvature(self) -> float:
        return self.base_curvature + 2.0 * self._beta(2)

    @property
    def seidel_b4(self) -> float:
        c = self.base_curvature
        return (1.0 + self.conic) * c**3 + 8.0 * self._beta(4) - self.curvature**3

    @property
    def is_plane(self) -> bool:
        return self.base.is_plane and not any(self.coefficients)

    @property
    def has_asphere(self) -> bool:
        return True

    def _root_term(self, r2):
        return self.base._root_term(np.asarray(r2, dtype=float))

    def domain_ok(self, r2):
        return self.base.domain_ok(np.asarray(r2, dtype=float))

    def sag(self, r2):
        r2 = np.asarray(r2, dtype=float)
        r = np.sqrt(np.clip(r2, 0.0, None))
        z = self.base.sag(r2)
        rp = r
        for b in self.coefficients:
            if b != 0.0:
                z = z + b * rp
            rp = rp * r
        return z

    def slope_over_r(self, r2):
        """(dz/dr) / r; the r^1 term gives beta_1 / r (infinite at the vertex, a cone tip)."""
        r2 = np.asarray(r2, dtype=float)
        r = np.sqrt(np.clip(r2, 1e-300, None))
        g = self.base.slope_over_r(r2)
        rp = 1.0 / r  # d/dr beta_i r^i / r = i beta_i r^(i-2)
        for i, b in enumerate(self.coefficients, start=1):
            if b != 0.0:
                g = g + i * b * rp
            rp = rp * r
        return g

    def sag_x(self, r2):
        return self.sag(r2)

    def sag_xy(self, x, y):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        return self.sag(x * x + y * y)

    def normals(self, p: np.ndarray) -> np.ndarray:
        r2 = p[:, 0] ** 2 + p[:, 1] ** 2
        g = self.slope_over_r(r2)
        n = np.stack([-g * p[:, 0], -g * p[:, 1], np.ones_like(g)], axis=1)
        return n / np.linalg.norm(n, axis=1, keepdims=True)

    def intersect(self, P: np.ndarray, D: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        s, status = self.base.intersect(P, D)
        return Shape._newton(self, P, D, s, status)


@dataclass(frozen=True)
class BiconicShape:
    """Biconic surface: separate curvature and conic in the x-z and y-z sections.

        z(x, y) = (cx x^2 + cy y^2) / (1 + sqrt(1 - (1+kx) cx^2 x^2 - (1+ky) cy^2 y^2))

    `curvature`/`conic` are the y-z (tangential) values, so code that works on
    the meridional section (paraxial y-nu trace, Seidel sums, 2D layout,
    solves) uses the y section. `sag(r2)` is the y-z profile (x = 0);
    `sag_x(r2)` the x-z profile. cx = cy and kx = ky reproduce the standard
    conic exactly. Intersection: Newton iteration on f(s) = z - z(x, y),
    started from the y-conic intersection (or the vertex plane).
    """

    curvature: float = 0.0  # cy
    conic: float = 0.0  # ky
    curvature_x: float = 0.0
    conic_x: float = 0.0
    aspheric: tuple[float, ...] = field(default_factory=tuple)

    @property
    def is_plane(self) -> bool:
        return self.curvature == 0.0 and self.curvature_x == 0.0

    @property
    def has_asphere(self) -> bool:
        return False

    def _q(self, x2, y2):
        return 1.0 - (1.0 + self.conic_x) * self.curvature_x**2 * x2 - (1.0 + self.conic) * self.curvature**2 * y2

    def _root_term(self, r2):
        """Worst case of both meridians (used for domain checks of a radius)."""
        r2 = np.asarray(r2, dtype=float)
        return np.minimum(self._q(r2, 0.0 * r2), self._q(0.0 * r2, r2))

    def domain_ok(self, r2):
        return self._root_term(r2) >= -1e-14

    def domain_ok_xy(self, x, y):
        return self._q(x * x, y * y) >= -1e-14

    def sag_xy(self, x, y):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        root = np.sqrt(np.clip(self._q(x * x, y * y), 0.0, None))
        return (self.curvature_x * x * x + self.curvature * y * y) / (1.0 + root)

    def sag(self, r2):
        r2 = np.asarray(r2, dtype=float)
        return self.sag_xy(0.0 * r2, np.sqrt(np.clip(r2, 0.0, None)))

    def sag_x(self, r2):
        r2 = np.asarray(r2, dtype=float)
        return self.sag_xy(np.sqrt(np.clip(r2, 0.0, None)), 0.0 * r2)

    def gradient(self, x, y):
        cx, cy, kx, ky = self.curvature_x, self.curvature, self.conic_x, self.conic
        Q = np.clip(self._q(x * x, y * y), 1e-300, None)
        S = np.sqrt(Q)
        den = 1.0 + S
        N = cx * x * x + cy * y * y
        dSdx = -(1.0 + kx) * cx * cx * x / S
        dSdy = -(1.0 + ky) * cy * cy * y / S
        zx = (2 * cx * x * den - N * dSdx) / (den * den)
        zy = (2 * cy * y * den - N * dSdy) / (den * den)
        return zx, zy

    def normals(self, p):
        zx, zy = self.gradient(p[:, 0], p[:, 1])
        n = np.stack([-zx, -zy, np.ones_like(zx)], axis=1)
        return n / np.linalg.norm(n, axis=1, keepdims=True)

    def intersect(self, P, D):
        n = P.shape[0]
        if self.is_plane:
            return Shape().intersect(P, D)
        # start from the y-conic (standard surface with cy, ky), otherwise from the vertex plane
        s, status = Shape(self.curvature, self.conic, ()).intersect(P, D)
        with np.errstate(divide="ignore", invalid="ignore"):
            plane = -P[:, 2] / D[:, 2]
        bad = (status != OK) | ~np.isfinite(s)
        s = np.where(bad, plane, s)
        status = np.where(np.isfinite(s), OK, MISS).astype(np.int8)
        active = status == OK
        converged = np.zeros(n, dtype=bool)
        for _ in range(NEWTON_MAX_ITER):
            idx = np.nonzero(active & ~converged)[0]
            if idx.size == 0:
                break
            q = P[idx] + s[idx, None] * D[idx]
            dom = self.domain_ok_xy(q[:, 0], q[:, 1])
            f = q[:, 2] - self.sag_xy(q[:, 0], q[:, 1])
            zx, zy = self.gradient(q[:, 0], q[:, 1])
            fp = D[idx, 2] - zx * D[idx, 0] - zy * D[idx, 1]
            with np.errstate(divide="ignore", invalid="ignore"):
                step = f / fp
            badstep = ~np.isfinite(step) | ~dom
            status[idx[badstep]] = OUT_OF_DOMAIN
            active[idx[badstep]] = False
            ok = ~badstep
            s[idx[ok]] -= step[ok]
            converged[idx[ok & (np.abs(step) < NEWTON_TOL)]] = True
        status[active & ~converged] = NO_CONVERGENCE
        if np.any(converged):
            q = P[converged] + s[converged, None] * D[converged]
            status[np.nonzero(converged)[0][~self.domain_ok_xy(q[:, 0], q[:, 1])]] = OUT_OF_DOMAIN
        s = np.where(status == OK, s, np.nan)
        return s, status


# ----------------------------------------------------------------------
# Zernike sag surface
# ----------------------------------------------------------------------


def _pmul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Product of two 2D power-series coefficient arrays c[i, j] (x^i y^j)."""
    out = np.zeros((a.shape[0] + b.shape[0] - 1, a.shape[1] + b.shape[1] - 1))
    for i, j in zip(*np.nonzero(a)):
        out[i : i + b.shape[0], j : j + b.shape[1]] += a[i, j] * b
    return out


def _padd(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    out = np.zeros((max(a.shape[0], b.shape[0]), max(a.shape[1], b.shape[1])))
    out[: a.shape[0], : a.shape[1]] += a
    out[: b.shape[0], : b.shape[1]] += b
    return out


_MONO_CACHE: dict[int, np.ndarray] = {}
ZERNIKE_MAX_TERMS = 37


def fringe_monomials(index: int) -> np.ndarray:
    """Fringe Zernike term `index` (1-based, peak-normalised) as monomials c[i, j] u^i v^j
    in normalised coordinates (u, v) = (x, y) / R (exact integer coefficients)."""
    if index in _MONO_CACHE:
        return _MONO_CACHE[index]
    import math

    from .analysis.wavefront import fringe_nm

    n, m = fringe_nm(index)[index - 1]
    am = abs(m)
    # Re (m >= 0) or Im (m < 0) of (u + i v)^|m|
    trig = np.zeros((am + 1, am + 1))
    for j in range(am + 1):
        b = math.comb(am, j)
        if m >= 0 and j % 2 == 0:
            trig[am - j, j] += b * (-1) ** (j // 2)
        elif m < 0 and j % 2 == 1:
            trig[am - j, j] += b * (-1) ** ((j - 1) // 2)
    r2 = np.zeros((3, 3))
    r2[2, 0] = r2[0, 2] = 1.0
    out = np.zeros((1, 1))
    for k in range((n - am) // 2 + 1):
        c = (-1) ** k * math.factorial(n - k) / (math.factorial(k) * math.factorial((n + am) // 2 - k) * math.factorial((n - am) // 2 - k))
        p = (n - 2 * k - am) // 2  # rho^(n-2k) * trig = (u^2 + v^2)^p * Re/Im (u + iv)^|m|
        term = trig.copy()
        for _ in range(p):
            term = _pmul(term, r2)
        out = _padd(out, c * term)
    _MONO_CACHE[index] = out
    return out


@dataclass(frozen=True, eq=False)
class ZernikeShape:
    """Zernike sag surface: base conic / even asphere plus Fringe Zernike terms

        z(x, y) = z_base(r) + sum_i A_i [Z_i(x/R, y/R) - Z_i(0, 0)]

    A_i in mm (Fringe ordering, peak-normalised, i = 1..37), R the
    normalisation radius. The polynomial is referenced to its vertex value so
    the vertex stays at the local origin (piston has no effect). It is
    expanded once into exact monomials; sag and gradient are evaluated from
    them. `curvature` / `curvature_x` are the vertex curvatures of the y-z and
    x-z sections (c_base + 2 c_02 / R^2, c_base + 2 c_20 / R^2) used by the
    paraxial trace. Intersection: Newton iteration started from the base
    surface.
    """

    base_curvature: float = 0.0
    conic: float = 0.0
    aspheric: tuple[float, ...] = field(default_factory=tuple)
    coefficients: tuple[float, ...] = field(default_factory=tuple)
    norm_radius: float = 1.0

    def __post_init__(self):
        poly = np.zeros((1, 1))
        for i, a in enumerate(self.coefficients, start=1):
            if a != 0.0:
                poly = _padd(poly, a * fringe_monomials(i))
        poly = poly.copy()
        poly[0, 0] = 0.0  # vertex reference
        P = np.polynomial.polynomial
        dx = P.polyder(poly, axis=0) if poly.shape[0] > 1 else np.zeros((1, poly.shape[1]))
        dy = P.polyder(poly, axis=1) if poly.shape[1] > 1 else np.zeros((poly.shape[0], 1))
        object.__setattr__(self, "poly", poly)
        object.__setattr__(self, "poly_dx", dx)
        object.__setattr__(self, "poly_dy", dy)
        object.__setattr__(self, "base", Shape(self.base_curvature, self.conic, tuple(self.aspheric)))

    def _c(self, i: int, j: int) -> float:
        p = self.poly
        return float(p[i, j]) if i < p.shape[0] and j < p.shape[1] else 0.0

    @property
    def curvature(self) -> float:
        return self.base_curvature + 2.0 * self._c(0, 2) / self.norm_radius**2

    @property
    def curvature_x(self) -> float:
        return self.base_curvature + 2.0 * self._c(2, 0) / self.norm_radius**2

    @property
    def conic_x(self) -> float:
        return self.conic

    @property
    def vertex_slope(self) -> tuple[float, float]:
        """(dz/dx, dz/dy) at the vertex (Zernike tilt terms)."""
        return self._c(1, 0) / self.norm_radius, self._c(0, 1) / self.norm_radius

    @property
    def is_plane(self) -> bool:
        return self.base.is_plane and not np.any(self.poly)

    @property
    def has_asphere(self) -> bool:
        return True

    def _root_term(self, r2):
        return self.base._root_term(np.asarray(r2, dtype=float))

    def domain_ok(self, r2):
        return self.base.domain_ok(np.asarray(r2, dtype=float))

    def domain_ok_xy(self, x, y):
        return self.base.domain_ok(np.asarray(x, dtype=float) ** 2 + np.asarray(y, dtype=float) ** 2)

    def zernike_sag(self, x, y):
        R = self.norm_radius
        return np.polynomial.polynomial.polyval2d(np.asarray(x, dtype=float) / R, np.asarray(y, dtype=float) / R, self.poly)

    def sag_xy(self, x, y):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        return self.base.sag(x * x + y * y) + self.zernike_sag(x, y)

    def sag(self, r2):
        r2 = np.asarray(r2, dtype=float)
        return self.sag_xy(0.0 * r2, np.sqrt(np.clip(r2, 0.0, None)))

    def sag_x(self, r2):
        r2 = np.asarray(r2, dtype=float)
        return self.sag_xy(np.sqrt(np.clip(r2, 0.0, None)), 0.0 * r2)

    def gradient(self, x, y):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        R = self.norm_radius
        g = self.base.slope_over_r(x * x + y * y)
        u, v = x / R, y / R
        zx = g * x + np.polynomial.polynomial.polyval2d(u, v, self.poly_dx) / R
        zy = g * y + np.polynomial.polynomial.polyval2d(u, v, self.poly_dy) / R
        return zx, zy

    def normals(self, p):
        zx, zy = self.gradient(p[:, 0], p[:, 1])
        n = np.stack([-zx, -zy, np.ones_like(zx)], axis=1)
        return n / np.linalg.norm(n, axis=1, keepdims=True)

    def intersect(self, P, D):
        if not np.any(self.poly):
            return self.base.intersect(P, D)
        n = P.shape[0]
        s, status = self.base.intersect(P, D)
        with np.errstate(divide="ignore", invalid="ignore"):
            plane = -P[:, 2] / D[:, 2]
        bad = (status != OK) | ~np.isfinite(s)
        s = np.where(bad, plane, s)
        status = np.where(np.isfinite(s), OK, MISS).astype(np.int8)
        active = status == OK
        converged = np.zeros(n, dtype=bool)
        for _ in range(NEWTON_MAX_ITER):
            idx = np.nonzero(active & ~converged)[0]
            if idx.size == 0:
                break
            q = P[idx] + s[idx, None] * D[idx]
            dom = self.domain_ok_xy(q[:, 0], q[:, 1])
            f = q[:, 2] - self.sag_xy(q[:, 0], q[:, 1])
            zx, zy = self.gradient(q[:, 0], q[:, 1])
            fp = D[idx, 2] - zx * D[idx, 0] - zy * D[idx, 1]
            with np.errstate(divide="ignore", invalid="ignore"):
                step = f / fp
            badstep = ~np.isfinite(step) | ~dom
            status[idx[badstep]] = OUT_OF_DOMAIN
            active[idx[badstep]] = False
            ok = ~badstep
            s[idx[ok]] -= step[ok]
            converged[idx[ok & (np.abs(step) < NEWTON_TOL)]] = True
        status[active & ~converged] = NO_CONVERGENCE
        if np.any(converged):
            q = P[converged] + s[converged, None] * D[converged]
            status[np.nonzero(converged)[0][~self.domain_ok_xy(q[:, 0], q[:, 1])]] = OUT_OF_DOMAIN
        s = np.where(status == OK, s, np.nan)
        return s, status


@dataclass(frozen=True)
class XYPolyShape(ZernikeShape):
    """XY-polynomial freeform: base conic / even asphere plus sum_k A_k (x/R)^i (y/R)^j (qpoly.xy_exponents),
    A_k in mm. The polynomial machinery (sag, gradient, Newton intersection, vertex curvatures for the
    paraxial trace) is the Zernike surface's; only the terms differ."""

    def __post_init__(self):
        from .qpoly import xy_poly

        poly = xy_poly(self.coefficients) if self.coefficients else np.zeros((1, 1))
        P = np.polynomial.polynomial
        dx = P.polyder(poly, axis=0) if poly.shape[0] > 1 else np.zeros((1, poly.shape[1]))
        dy = P.polyder(poly, axis=1) if poly.shape[1] > 1 else np.zeros((poly.shape[0], 1))
        object.__setattr__(self, "poly", poly)
        object.__setattr__(self, "poly_dx", dx)
        object.__setattr__(self, "poly_dy", dy)
        object.__setattr__(self, "base", Shape(self.base_curvature, self.conic, tuple(self.aspheric)))


@dataclass(frozen=True)
class QShape:
    """Forbes Q-type asphere (qpoly): kind 'qcon' (conic + u^4 sum a_m Q_m^con) or 'qbfs' (sphere +
    u^2 (1-u^2) / sqrt(1 - c^2 r^2) sum a_m Q_m^bfs), u = r / norm_radius. Rotationally symmetric.

    `curvature` is the paraxial vertex curvature (Qbfs: c + 2 S(0) / r_n^2); `seidel_b4` the fourth-order
    coefficient the Seidel sums use (8 x the r^4 sag coefficient minus curvature^3, as conic c^3 k + 8 A4).
    Intersection: Newton iteration from the base conic, like even aspheres."""

    base_curvature: float = 0.0
    conic: float = 0.0
    kind: str = "qcon"
    coefficients: tuple[float, ...] = field(default_factory=tuple)
    norm_radius: float = 1.0

    def __post_init__(self):
        from .qpoly import series

        object.__setattr__(self, "base", Shape(self.base_curvature, self.conic if self.kind == "qcon" else 0.0, ()))
        s0, ds0 = series(self.kind, self.coefficients, [0.0])
        object.__setattr__(self, "_s0", float(s0[0]))
        object.__setattr__(self, "_ds0", float(ds0[0]))

    aspheric: tuple[float, ...] = ()

    @property
    def curvature(self) -> float:
        if self.kind == "qbfs":
            return self.base_curvature + 2.0 * self._s0 / self.norm_radius**2
        return self.base_curvature

    @property
    def seidel_b4(self) -> float:
        c, rn = self.base_curvature, self.norm_radius
        if self.kind == "qcon":
            return self.conic * c**3 + 8.0 * self._s0 / rn**4
        t4 = c**3 / 8.0 + (self._ds0 - self._s0) / rn**4 + self._s0 * c * c / (2.0 * rn**2)
        return 8.0 * t4 - self.curvature**3

    @property
    def is_plane(self) -> bool:
        return self.base.is_plane and not any(self.coefficients)

    @property
    def has_asphere(self) -> bool:
        return True

    def _root_term(self, r2):
        return self.base._root_term(np.asarray(r2, dtype=float))

    def domain_ok(self, r2):
        return self.base.domain_ok(np.asarray(r2, dtype=float))

    def sag(self, r2):
        from .qpoly import series

        r2 = np.asarray(r2, dtype=float)
        x = r2 / self.norm_radius**2
        S, _ = series(self.kind, self.coefficients, x.ravel())
        S = S.reshape(x.shape)
        z = self.base.sag(r2)
        if self.kind == "qcon":
            return z + x * x * S
        root = np.sqrt(np.clip(1.0 - self.base_curvature**2 * r2, 1e-300, None))
        return z + x * (1.0 - x) * S / root

    def slope_over_r(self, r2):
        """(dz/dr) / r, finite at r = 0."""
        from .qpoly import series

        r2 = np.asarray(r2, dtype=float)
        rn2 = self.norm_radius**2
        x = r2 / rn2
        S, dS = series(self.kind, self.coefficients, x.ravel())
        S, dS = S.reshape(x.shape), dS.reshape(x.shape)
        g = self.base.slope_over_r(r2)
        # d/dr F(x) = F'(x) 2 r / rn^2  ->  (1/r) d/dr = 2 F'(x) / rn^2
        if self.kind == "qcon":
            return g + 2.0 * (2.0 * x * S + x * x * dS) / rn2
        c2 = self.base_curvature**2
        w = 1.0 - c2 * r2
        root = np.sqrt(np.clip(w, 1e-300, None))
        F = x * (1.0 - x) * S
        dF = (1.0 - 2.0 * x) * S + x * (1.0 - x) * dS
        # d/dr [F / root] = F'(x) (2r/rn^2) / root + F c^2 r / root^3
        return g + 2.0 * dF / (rn2 * root) + F * c2 / (root * w)

    def sag_x(self, r2):
        return self.sag(r2)

    def sag_xy(self, x, y):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        return self.sag(x * x + y * y)

    def normals(self, p: np.ndarray) -> np.ndarray:
        r2 = p[:, 0] ** 2 + p[:, 1] ** 2
        g = self.slope_over_r(r2)
        n = np.stack([-g * p[:, 0], -g * p[:, 1], np.ones_like(g)], axis=1)
        return n / np.linalg.norm(n, axis=1, keepdims=True)

    def intersect(self, P: np.ndarray, D: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        s, status = self.base.intersect(P, D)
        return Shape._newton(self, P, D, s, status)
