"""Guided LP modes and dispersion of fibres with radially symmetric index profiles.

Profiles. The index is the cladding's plus an offset that does not depend on the wavelength,
n(r, lambda) = n_clad(lambda) + dn(r), with n_clad from a library material (or a constant):

    step     dn = dn_core for r < a
    graded   n(r)^2 = n1^2 (1 - 2 Delta (r/a)^alpha) for r < a, n_clad outside; n1 = n_clad + dn_core and
             2 Delta = 1 - n_clad^2 / n1^2, so the index is continuous at r = a (alpha = 2: parabolic)
    layers   rings (outer radius, dn) from the axis outwards, then the cladding (W and trench profiles)

Modes. Weakly guiding (scalar) LP_lm modes psi(r) cos(l phi) of

    psi'' + psi'/r + (k^2 n(r)^2 - beta^2 - l^2 / r^2) psi = 0,   n_eff = beta / k,   k = 2 pi / lambda.

* Piecewise-constant profiles (step, layers): exact. In each layer psi = A Z1(q r) + B Z2(q r) with (J_l, Y_l) where
  n > n_eff (q = k sqrt(n^2 - n_eff^2)) and (I_l, K_l) where n < n_eff; the axis keeps J_l or I_l only. (psi, psi')
  is carried through the interfaces (continuous) and the cladding must hold K_l alone:
  F(n_eff) = psi' - psi gamma K_l'(gamma R) / K_l(gamma R) = 0 at the last interface R, with (psi, psi') renormalised
  in every layer, so F is continuous and has no poles. Roots are bracketed on a grid and refined by Brent's method.
* Continuous profiles (graded): second-order finite differences of (1/r)(r psi')' on a cell-centred grid
  r_i = (i - 1/2) h (the axis needs no boundary condition), symmetrised with sqrt(r_i): a symmetric tridiagonal
  eigenproblem for beta^2. Two grids h and h/2 are combined by Richardson extrapolation (fourth order). The domain
  ends with psi = 0 where every reported mode has decayed by exp(-20) (it is enlarged until it does).

Derived quantities:
* LP01 mode field diameter: Petermann II, 2 sqrt(2) [int psi^2 r dr / int psi'^2 r dr]^(1/2) (any profile);
  effective area A_eff = 2 pi (int psi^2 r dr)^2 / int psi^4 r dr; core power fraction (r below the core radius: a,
  or the outer radius of a layered profile's highest ring).
* Dispersion of a mode: n_eff(lambda) on a five-point stencil (h = 2e-3 lambda), group index
  n_g = n_eff - lambda dn_eff/dlambda and D = -(lambda / c) d^2 n_eff / dlambda^2 in ps/(nm km); the cladding glass
  alone gives the material part (same stencil); the zero-dispersion wavelength is the root of D.
* LP_l cut-off (l >= 1): at n_eff = n_clad the cladding field is r^-l, so (r psi'/psi)(a) = -l at the edge a of the
  index structure. psi comes from the exact layer solutions (piecewise-constant profiles) or from integrating the
  radial equation from the axis (psi ~ r^l, graded profiles); the wavelength is found by scanning from long to short
  wavelengths and Brent's method. LP01 has no cut-off.
* LP01 field quantities: from the exact field (piecewise-constant profiles), or from the finite-difference fields on
  both grids (midpoint sums, derivatives on the cell faces) with Richardson extrapolation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.integrate import simpson, solve_ivp
from scipy.linalg import eigh_tridiagonal
from scipy.optimize import brentq
from scipy.special import iv, ivp, jv, jvp, kve, yv, yvp

from .fibermodes import FibreError

C_UM_PER_PS = 299.792458  # speed of light in um/ps
B_MIN = 1e-4  # modes closer to cut-off (normalised b) are not reported


@dataclass
class Profile:
    """kind: step | graded | layers; radii in um; dn relative to the cladding (constant in wavelength)."""

    kind: str
    a: float
    dn_core: float = 0.0
    alpha: float = 2.0
    layers: tuple[tuple[float, float], ...] = ()

    def __post_init__(self):
        if self.kind not in ("step", "graded", "layers"):
            raise FibreError(f"Unknown profile '{self.kind}'")
        if self.kind == "layers":
            if not self.layers:
                raise FibreError("A layered profile needs at least one ring")
            r_prev = 0.0
            for r, _ in self.layers:
                if not r > r_prev:
                    raise FibreError("Ring radii must increase from the axis outwards")
                r_prev = r
            self.a = float(self.layers[-1][0])
            if max(dn for _, dn in self.layers) <= 0:
                raise FibreError("A guiding profile needs a ring with an index above the cladding")
        else:
            if not self.a > 0:
                raise FibreError("The core radius must be positive")
            if not self.dn_core > 0:
                raise FibreError("The core index must exceed the cladding index")
            if self.kind == "graded" and not self.alpha > 0:
                raise FibreError("The profile exponent alpha must be positive")

    @property
    def piecewise_constant(self) -> bool:
        return self.kind in ("step", "layers")

    def rings(self) -> list[tuple[float, float]]:
        """(outer radius, dn) of the piecewise-constant profiles."""
        return [(self.a, self.dn_core)] if self.kind == "step" else [(float(r), float(d)) for r, d in self.layers]

    def n(self, r: np.ndarray, n_clad: float) -> np.ndarray:
        r = np.asarray(r, dtype=float)
        if self.kind == "graded":
            n1 = n_clad + self.dn_core
            two_delta = 1.0 - (n_clad / n1) ** 2
            inside = n1 * np.sqrt(np.clip(1.0 - two_delta * (np.minimum(r, self.a) / self.a) ** self.alpha, 0.0, None))
            return np.where(r < self.a, inside, n_clad)
        out = np.full_like(r, n_clad)
        r_in = 0.0
        for r_out, dn in self.rings():
            out = np.where((r >= r_in) & (r < r_out), n_clad + dn, out)
            r_in = r_out
        return out

    def n_max(self, n_clad: float) -> float:
        return n_clad + (self.dn_core if self.kind != "layers" else max(d for _, d in self.layers))

    @property
    def core_radius(self) -> float:
        """The core: a for step and graded profiles, the outer radius of the highest ring of a layered one (V number,
        core power fraction)."""
        if self.kind != "layers":
            return self.a
        top = max(d for _, d in self.layers)
        return float(next(r for r, d in self.layers if d == top))


# ---------------------------------------------------------------- exact transfer for piecewise-constant profiles
def _basis(l: int, n: float, neff: float, k: float, r: float):
    """Values and r-derivatives of the two radial solutions of one layer at r."""
    if n > neff:
        q = k * math.sqrt(n * n - neff * neff)
        return (jv(l, q * r), yv(l, q * r)), (q * jvp(l, q * r), q * yvp(l, q * r))
    q = k * math.sqrt(neff * neff - n * n)
    from scipy.special import kv, kvp

    return (iv(l, q * r), kv(l, q * r)), (q * ivp(l, q * r), q * kvp(l, q * r))


def _tmm_state(prof: Profile, l: int, neff: float, k: float, n_clad: float) -> list[tuple[float, float, float]]:
    """Normalised (psi, psi') just outside each interface radius, layer by layer from the axis:
    [(r, psi, psi'), ...]; the last entry is at the outer radius of the profile."""
    rings = prof.rings()
    r0, dn0 = rings[0]
    n0 = n_clad + dn0
    (f, _), (df, _) = _basis(l, n0, neff, k, r0)
    psi, dpsi = float(f), float(df)
    out = [(r0, psi, dpsi)]
    for (r_in, _), (r_out, dn) in zip(rings[:-1], rings[1:]):
        n = n_clad + dn
        (f1, g1), (df1, dg1) = _basis(l, n, neff, k, r_in)
        M = np.array([[f1, g1], [df1, dg1]], dtype=float)
        A, B = np.linalg.solve(M, [psi, dpsi])
        (f2, g2), (df2, dg2) = _basis(l, n, neff, k, r_out)
        psi, dpsi = float(A * f2 + B * g2), float(A * df2 + B * dg2)
        s = math.hypot(psi, r_out * dpsi)
        psi, dpsi = psi / s, dpsi / s
        out.append((r_out, psi, dpsi))
    return out


def _tmm_mismatch(prof: Profile, l: int, neff: float, k: float, n_clad: float) -> float:
    r, psi, dpsi = _tmm_state(prof, l, neff, k, n_clad)[-1]
    g = k * math.sqrt(max(neff * neff - n_clad * n_clad, 1e-300))
    x = g * r
    # K_l'(x) / K_l(x) from the scaled functions (no overflow): K' = -(K_{l-1} + K_{l+1}) / 2
    kr = -0.5 * (kve(l - 1, x) + kve(l + 1, x)) / kve(l, x)
    s = math.hypot(psi, r * dpsi)
    return (dpsi - psi * g * kr) / s * r


def _tmm_modes(prof: Profile, l: int, k: float, n_clad: float, nmax: float) -> list[float]:
    lo = math.sqrt(n_clad**2 + B_MIN * (nmax**2 - n_clad**2))
    hi = nmax * (1 - 1e-13)
    grid = np.linspace(lo, hi, 800)
    with np.errstate(all="ignore"):
        f = np.array([_tmm_mismatch(prof, l, x, k, n_clad) for x in grid])
    roots = []
    for i in np.nonzero(np.isfinite(f[:-1]) & np.isfinite(f[1:]) & (np.sign(f[:-1]) != np.sign(f[1:])))[0]:
        try:
            x = brentq(lambda v: _tmm_mismatch(prof, l, v, k, n_clad), grid[i], grid[i + 1], xtol=1e-15, rtol=1e-15, maxiter=200)
        except ValueError:  # pragma: no cover - a sign change across a non-finite point
            continue
        # a genuine root has a small mismatch; a sign change through a pole of the renormalised state does not
        if abs(_tmm_mismatch(prof, l, x, k, n_clad)) < 1e-6:
            roots.append(float(x))
    return sorted(roots, reverse=True)


def _tmm_field_slope(prof: Profile, l: int, neff: float, k: float, n_clad: float, r: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """psi(r) and psi'(r) of a mode found by the transfer method (arbitrary scale), from the layer solutions."""
    from scipy.special import kve as _kve

    r = np.asarray(r, dtype=float)
    rings = prof.rings()
    layers = []  # (r_in, r_out, n, A, B): psi = A Z1(q r) + B Z2(q r)
    n = n_clad + rings[0][1]
    layers.append((0.0, rings[0][0], n, 1.0, 0.0))
    (f, _), (df, _) = _basis(l, n, neff, k, rings[0][0])
    psi, dpsi = float(f), float(df)
    for (r_in, _), (r_out, dn) in zip(rings[:-1], rings[1:]):
        n = n_clad + dn
        (f1, g1), (df1, dg1) = _basis(l, n, neff, k, r_in)
        A, B = np.linalg.solve(np.array([[f1, g1], [df1, dg1]], dtype=float), [psi, dpsi])
        layers.append((r_in, r_out, n, float(A), float(B)))
        (f2, g2), (df2, dg2) = _basis(l, n, neff, k, r_out)
        psi, dpsi = float(A * f2 + B * g2), float(A * df2 + B * dg2)
    out, slope = np.zeros_like(r), np.zeros_like(r)
    for r_in, r_out, n, A, B in layers:
        m = ((r >= r_in) if r_in == 0.0 else (r > r_in)) & (r <= r_out)
        if not np.any(m):
            continue
        (f, g), (df, dg) = _basis(l, n, neff, k, r[m])
        if B == 0.0:  # the axis layer holds the regular solution only
            out[m], slope[m] = A * f, A * df
        else:
            out[m], slope[m] = A * f + B * g, A * df + B * dg
    R = rings[-1][0]
    gam = k * math.sqrt(neff * neff - n_clad * n_clad)
    m = r > R
    # K_l(g r) / K_l(g R) from the scaled functions, K_l' = -(K_{l-1} + K_{l+1}) / 2
    e = np.exp(-gam * (r[m] - R)) / _kve(l, gam * R)
    out[m] = psi * _kve(l, gam * r[m]) * e
    slope[m] = psi * (-0.5 * gam) * (_kve(l - 1, gam * r[m]) + _kve(l + 1, gam * r[m])) * e
    return out, slope


def _tmm_field(prof: Profile, l: int, neff: float, k: float, n_clad: float, r: np.ndarray) -> np.ndarray:
    """psi(r) of a mode found by the transfer method (arbitrary scale)."""
    return _tmm_field_slope(prof, l, neff, k, n_clad, r)[0]


# ---------------------------------------------------------------- finite differences for continuous profiles
B_MIN_FD = 1e-3  # finite differences: a mode nearer cut-off would need a very large domain


def _fd_once(prof: Profile, l: int, k: float, n_clad: float, R: float, h: float, bmin: float = B_MIN_FD):
    N = int(round(R / h))
    r = (np.arange(1, N + 1) - 0.5) * h
    rp = r + 0.5 * h
    rm = r - 0.5 * h
    n = prof.n(r, n_clad)
    d = -(rp + rm) / (r * h * h) - (l * l) / (r * r) + (k * n) ** 2
    e = rp[:-1] / (h * h * np.sqrt(r[:-1] * r[1:]))
    lo = (k * n_clad) ** 2 + bmin * k * k * (prof.n_max(n_clad) ** 2 - n_clad**2)
    vals, vecs = eigh_tridiagonal(d, e, select="v", select_range=(lo, (k * prof.n_max(n_clad)) ** 2 * 1.000001))
    order = np.argsort(-vals)
    return r, vals[order], vecs[:, order] / np.sqrt(r)[:, None]


def _aligned_step(prof: Profile, h_target: float) -> float:
    """A grid step that divides every interface radius (to 1e-4 um), so that each index step lies on a cell face and
    the scheme stays second order (a step inside a cell would make it first order)."""
    radii = [x for x, _ in prof.rings()] if prof.piecewise_constant else [prof.a]
    units = [int(round(x * 1e4)) for x in radii]
    if any(abs(u - x * 1e4) > 1e-6 for u, x in zip(units, radii)):
        return h_target
    g = units[0]
    for u in units[1:]:
        g = math.gcd(g, u)
    G = g * 1e-4
    n = math.ceil(G / h_target)
    return G / n if n <= 200000 else h_target


def _fd_modes(prof: Profile, l: int, k: float, n_clad: float):
    """[(neff, r, psi)] by finite differences with Richardson extrapolation; the domain grows until every mode has
    decayed by exp(-20) at its edge."""
    nmax = prof.n_max(n_clad)
    V = k * prof.a * math.sqrt(nmax**2 - n_clad**2)
    R = prof.a * (1.0 + 30.0 / max(V, 1.0))
    h = _aligned_step(prof, prof.a / max(200.0, 8.0 * V))
    for _ in range(12):
        r1, b1, v1 = _fd_once(prof, l, k, n_clad, R, h)
        if len(b1) == 0:
            return []
        g = k * np.sqrt(np.maximum(b1 / (k * k) - n_clad**2, 1e-30))
        if float(np.min(g)) * (R - prof.a) >= 20.0:
            break
        R = prof.a + 22.0 / float(np.min(g))
    # the fine grid with a lower threshold, so that every coarse eigenvalue finds its partner
    r2, b2, v2 = _fd_once(prof, l, k, n_clad, R, h / 2, bmin=0.5 * B_MIN_FD)
    out = []
    for j, x in enumerate(b1):
        i = int(np.argmin(np.abs(b2 - x)))
        neff = math.sqrt((4.0 * b2[i] - x) / 3.0) / k
        if (neff * neff - n_clad**2) < B_MIN_FD * (nmax**2 - n_clad**2):
            continue
        out.append((neff, r2, v2[:, i], r1, v1[:, j]))
    return out


def _cell_properties(r: np.ndarray, psi: np.ndarray, a: float) -> np.ndarray:
    """(MFD Petermann II, effective area, core power fraction) of a field on the cell-centred grid r_i = (i - 1/2) h:
    midpoint sums over the cells, the derivative on the cell faces (zero at r = 0 for l = 0); second order, so that
    two grids extrapolate to fourth order."""
    h = r[1] - r[0]
    p2 = float(np.sum(psi * psi * r) * h)
    d = np.diff(psi) / h
    rf = r[:-1] + 0.5 * h
    q = float(np.sum(d * d * rf) * h)
    p4 = float(np.sum(psi**4 * r) * h)
    core = float(np.sum((psi * psi * r)[r < a]) * h)
    return np.array([2 * math.sqrt(2.0) * math.sqrt(p2 / q), 2 * math.pi * p2 * p2 / p4, core / p2])


# ---------------------------------------------------------------- public
def _n_clad(clad, wavelength_um: float) -> float:
    return float(clad(wavelength_um)) if callable(clad) else float(clad)


def lp_modes(prof: Profile, wavelength_um: float, clad, l_max: int = 60, fields: bool = False, method: str | None = None) -> list[dict]:
    """Guided LP modes, sorted by n_eff. clad: cladding index or a function of the wavelength (um)."""
    lam = float(wavelength_um)
    if not lam > 0:
        raise FibreError("The wavelength must be positive")
    n_clad = _n_clad(clad, lam)
    k = 2 * math.pi / lam
    nmax = prof.n_max(n_clad)
    method = method or ("tmm" if prof.piecewise_constant else "fd")
    if method == "tmm" and not prof.piecewise_constant:
        raise FibreError("The transfer method needs a piecewise-constant profile")
    out = []
    for l in range(0, l_max + 1):
        if method == "tmm":
            found = [(x, None, None) for x in _tmm_modes(prof, l, k, n_clad, nmax)]
        else:
            found = [f[:3] for f in _fd_modes(prof, l, k, n_clad)]
        if not found:
            break
        for m, (neff, r, psi) in enumerate(found, start=1):
            mode = {"name": f"LP{l}{m}", "l": l, "m": m, "neff": float(neff), "b": float((neff**2 - n_clad**2) / (nmax**2 - n_clad**2)), "degeneracy": 2 if l == 0 else 4}
            if fields:
                mode["_r"], mode["_psi"] = r, psi
            out.append(mode)
    out.sort(key=lambda x: -x["neff"])
    if not out:
        raise FibreError("No guided mode at this wavelength")
    return out


def mode_field(prof: Profile, mode: dict, wavelength_um: float, clad) -> tuple[np.ndarray, np.ndarray]:
    """(r, psi) of a mode on a fine grid, psi(0) or its maximum normalised to 1."""
    n_clad = _n_clad(clad, wavelength_um)
    k = 2 * math.pi / wavelength_um
    g = k * math.sqrt(mode["neff"] ** 2 - n_clad**2)
    R = prof.a + 30.0 / g
    if prof.piecewise_constant:
        r = np.linspace(0.0, R, 60001)
        psi = _tmm_field(prof, mode["l"], mode["neff"], k, n_clad, r)
    else:
        found = [x for x in _fd_modes(prof, mode["l"], k, n_clad)]
        j = mode["m"] - 1
        r, psi = found[j][1], found[j][2]
        r = np.concatenate([[0.0], r])
        psi = np.concatenate([[psi[0] if mode["l"] == 0 else 0.0], psi])
    s = psi[np.argmax(np.abs(psi))]
    return r, psi / s


def lp01_properties(prof: Profile, wavelength_um: float, clad) -> dict:
    """Mode field diameter (Petermann II), effective area and core power fraction of LP01: from the exact field of a
    piecewise-constant profile, or for a continuous profile from the finite-difference fields on two grids with
    Richardson extrapolation."""
    modes = lp_modes(prof, wavelength_um, clad, l_max=0)
    if prof.piecewise_constant:
        # Simpson's rule layer by layer on the exact field and its exact slope (the interfaces are segment ends)
        n_clad = _n_clad(clad, wavelength_um)
        k = 2 * math.pi / wavelength_um
        neff = modes[0]["neff"]
        g = k * math.sqrt(neff * neff - n_clad * n_clad)
        edges = [0.0] + [x for x, _ in prof.rings()] + [prof.a + 40.0 / g]
        p2 = q = p4 = core = 0.0
        for r0, r1 in zip(edges[:-1], edges[1:]):
            r = np.linspace(r0, r1, 4001)
            psi, d = _tmm_field_slope(prof, 0, neff, k, n_clad, r)
            seg = simpson(psi * psi * r, x=r)
            p2 += seg
            q += simpson(d * d * r, x=r)
            p4 += simpson(psi**4 * r, x=r)
            if r1 <= prof.core_radius * (1 + 1e-12):
                core += seg
        mfd = 2 * math.sqrt(2.0) * math.sqrt(p2 / q)
        a_eff = 2 * math.pi * p2 * p2 / p4
        frac = core / p2
    else:
        n_clad = _n_clad(clad, wavelength_um)
        _, r2, v2, r1, v1 = _fd_modes(prof, 0, 2 * math.pi / wavelength_um, n_clad)[0]
        mfd, a_eff, frac = (4.0 * _cell_properties(r2, v2, prof.core_radius) - _cell_properties(r1, v1, prof.core_radius)) / 3.0
    return {"neff": modes[0]["neff"], "mfd_petermann2_um": float(mfd), "effective_area_um2": float(a_eff), "core_power_fraction": float(frac)}


def _radial_nodes(prof: Profile, l: int, neff: float, k: float, n_clad: float) -> int:
    """Sign changes of psi(r) for r > 0: LP_lm has m - 1 (the oscillation theorem of the radial equation)."""
    g = k * math.sqrt(max(neff * neff - n_clad * n_clad, 1e-300))
    r = np.linspace(prof.a * 1e-6, prof.a + 5.0 / g, 4001)
    psi = _tmm_field(prof, l, neff, k, n_clad, r)
    return int(np.count_nonzero(np.sign(psi[:-1]) * np.sign(psi[1:]) < 0))


def neff_of(prof: Profile, wavelength_um: float, clad, l: int, m: int, guess: float | None = None) -> float:
    """n_eff of LP_lm. With a guess (a nearby wavelength's value) a piecewise-constant profile's root is refined in a
    narrow bracket around it; the bracket must hold exactly one sign change and the root's field m - 1 radial nodes
    (so that it is LP_lm and not a neighbouring mode), otherwise the full search runs."""
    if guess is not None and prof.piecewise_constant:
        n_clad = _n_clad(clad, wavelength_um)
        k = 2 * math.pi / wavelength_um
        nmax = prof.n_max(n_clad)
        f = lambda v: _tmm_mismatch(prof, l, v, k, n_clad)  # noqa: E731
        for d in (2e-5, 2e-4):
            lo, hi = max(guess - d, n_clad * (1 + 1e-12)), min(guess + d, nmax * (1 - 1e-13))
            xs = np.linspace(lo, hi, 9)
            v = np.array([f(x) for x in xs])
            ch = np.nonzero(np.sign(v[:-1]) != np.sign(v[1:]))[0]
            if len(ch) == 1:
                i = int(ch[0])
                x = brentq(f, xs[i], xs[i + 1], xtol=1e-15, rtol=1e-15, maxiter=200)
                if abs(f(x)) < 1e-6 and _radial_nodes(prof, l, x, k, n_clad) == m - 1:
                    return float(x)
    for x in lp_modes(prof, wavelength_um, clad, l_max=l):
        if x["l"] == l and x["m"] == m:
            return x["neff"]
    raise FibreError(f"LP{l}{m} is not guided at {wavelength_um:g} um")


def dispersion(prof: Profile, wavelengths_um, clad, l: int = 0, m: int = 1, rel_step: float = 2e-3, guess: float | None = None) -> dict:
    """Effective index, group index and dispersion of LP_lm (and the cladding glass alone) at each wavelength. guess:
    n_eff near the first wavelength (each further wavelength starts from the previous one's value)."""
    rows = []
    for lam in np.atleast_1d(np.asarray(wavelengths_um, dtype=float)):
        h = rel_step * lam
        xs = lam + h * np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
        n0 = neff_of(prof, lam, clad, l, m, guess=guess)
        guess = n0
        ne = np.array([n0 if x == lam else neff_of(prof, x, clad, l, m, guess=n0) for x in xs])
        nc = np.array([_n_clad(clad, x) for x in xs])

        def derivs(f):
            d1 = (f[0] - 8 * f[1] + 8 * f[3] - f[4]) / (12 * h)
            d2 = (-f[0] + 16 * f[1] - 30 * f[2] + 16 * f[3] - f[4]) / (12 * h * h)
            return d1, d2

        d1, d2 = derivs(ne)
        c1, c2 = derivs(nc)
        D = -(lam / C_UM_PER_PS) * d2 * 1e6  # ps/(nm km): (um/ (um/ps)) * 1/um^2 -> ps/um^2 = 1e6 ps/(nm km)
        Dm = -(lam / C_UM_PER_PS) * c2 * 1e6
        rows.append({"wavelength_um": float(lam), "neff": float(ne[2]), "group_index": float(ne[2] - lam * d1), "D_ps_nm_km": float(D),
                     "D_material_ps_nm_km": float(Dm), "D_waveguide_ps_nm_km": float(D - Dm), "n_clad": float(nc[2])})
    zero = None
    Ds = [x["D_ps_nm_km"] for x in rows]
    for a, b in zip(range(len(rows) - 1), range(1, len(rows))):
        if Ds[a] == 0 or Ds[a] * Ds[b] < 0:
            g = rows[a]["neff"]
            zero = brentq(lambda x: dispersion(prof, [x], clad, l, m, rel_step, guess=g)["rows"][0]["D_ps_nm_km"], rows[a]["wavelength_um"], rows[b]["wavelength_um"], xtol=1e-7)
            break
    return {"rows": rows, "zero_dispersion_um": zero, "mode": f"LP{l}{m}"}


def _cut_shoot(prof: Profile, l: int, lam: float, clad) -> float:
    """(a psi' + l psi) / |(psi, a psi')| at the edge a of the index structure for n_eff = n_clad, psi ~ r^l on the
    axis: the radial equation integrated numerically (any profile)."""
    n_clad = _n_clad(clad, lam)
    k = 2 * math.pi / lam
    a = prof.a
    r0 = 1e-6 * a

    def rhs(r, y):
        n = float(prof.n(np.array([r]), n_clad)[0])
        return [y[1], -y[1] / r - (k * k * (n * n - n_clad * n_clad) - l * l / (r * r)) * y[0]]

    breaks = [x for x, _ in prof.rings()] if prof.piecewise_constant else [a]
    y = [r0**l, l * r0 ** (l - 1)]
    r_prev = r0
    for rb in breaks:
        sol = solve_ivp(rhs, (r_prev, rb), y, rtol=1e-12, atol=1e-14 * abs(y[0]) + 1e-300, method="DOP853")
        y = [sol.y[0, -1], sol.y[1, -1]]
        s = math.hypot(y[0], rb * y[1])
        y = [y[0] / s, y[1] / s]
        r_prev = rb
    return (a * y[1] + l * y[0]) / math.hypot(y[0], a * y[1])


def _cut_exact(prof: Profile, l: int, lam: float, clad) -> float:
    """The same function for a piecewise-constant profile from the exact layer solutions at n_eff = n_clad:
    J_l, Y_l (ring above the cladding), I_l, K_l (below) or r^l, r^-l (equal)."""
    n_clad = _n_clad(clad, lam)
    k = 2 * math.pi / lam
    from scipy.special import kv, kvp

    def basis(dn: float, r: float):
        d2 = k * k * ((n_clad + dn) ** 2 - n_clad**2)
        if d2 > 0:
            q = math.sqrt(d2)
            return (jv(l, q * r), yv(l, q * r)), (q * jvp(l, q * r), q * yvp(l, q * r))
        if d2 < 0:
            q = math.sqrt(-d2)
            return (iv(l, q * r), kv(l, q * r)), (q * ivp(l, q * r), q * kvp(l, q * r))
        return (r**l, r ** (-l)), (l * r ** (l - 1), -l * r ** (-l - 1))

    rings = prof.rings()
    r0, dn0 = rings[0]
    (f, _), (df, _) = basis(dn0, r0)
    s = math.hypot(f, r0 * df)
    psi, dpsi = f / s, df / s
    for (r_in, _), (r_out, dn) in zip(rings[:-1], rings[1:]):
        (f1, g1), (df1, dg1) = basis(dn, r_in)
        A, B = np.linalg.solve(np.array([[f1, g1], [df1, dg1]], dtype=float), [psi, dpsi])
        (f2, g2), (df2, dg2) = basis(dn, r_out)
        psi, dpsi = float(A * f2 + B * g2), float(A * df2 + B * dg2)
        s = math.hypot(psi, r_out * dpsi)
        psi, dpsi = psi / s, dpsi / s
    a = rings[-1][0]
    return (a * dpsi + l * psi) / math.hypot(psi, a * dpsi)


def cutoff_wavelength(prof: Profile, clad, l: int = 1, lam_range: tuple[float, float] = (0.2, 5.0)) -> float | None:
    """Wavelength (um) at which LP_l1 (l >= 1) reaches cut-off (n_eff = n_clad); None if not in lam_range.

    The edge function F(lambda) is positive for lambda -> infinity and changes sign at each LP_lm cut-off, so the
    number of sign changes above lambda is the number of guided LP_l modes there: F(lambda_max) < 0, or an LP_l
    mode guided at lambda_max, puts the LP_l1 cut-off above the range."""
    if l < 1:
        raise FibreError("LP0m modes have no cut-off condition of this form (LP01 has none)")
    edge = _cut_exact if prof.piecewise_constant else _cut_shoot

    def f(lam: float) -> float:
        return edge(prof, l, lam, clad)

    def f_safe(lam: float) -> float:
        try:  # a wavelength outside the cladding material's formula range is skipped
            return f(lam)
        except Exception:  # noqa: BLE001
            return float("nan")

    # scanning from long to short wavelengths the LP_l1 cut-off is the first sign change (short wavelengths, where
    # the integration is costly, are not reached)
    prev = None
    for x in np.geomspace(lam_range[1], lam_range[0], 200):
        v = f_safe(float(x))
        if not math.isfinite(v):
            continue
        if v == 0.0:
            return float(x)
        if prev is None:
            if v < 0:
                return None
            try:
                if any(m["l"] == l for m in lp_modes(prof, float(x), clad, l_max=l)):
                    return None
            except FibreError:
                pass
        elif (v > 0) != (prev[1] > 0):
            return float(brentq(f, float(x), prev[0], xtol=1e-12))
        prev = (float(x), v)
    return None
