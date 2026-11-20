"""Uniaxial birefringent media (docs/OPTICAL_ENGINE.md §8l).

Wave vectors K are in units of the vacuum wavenumber k0, so |K| is the phase index of the wave. A uniaxial
crystal with ordinary index no, extraordinary index ne and unit optic axis c has the dielectric tensor
eps = no^2 (I - c c^T) + ne^2 c c^T and two plane-wave modes:

  ordinary        |K| = no; E ∝ K × c (E ⊥ c); energy flows along K
  extraordinary   F(K) = (K·c)^2 / no^2 + (|K|^2 - (K·c)^2) / ne^2 = 1 (the index ellipsoid);
                  D ∝ K × (c × K), E = eps^-1 D; the ray (Poynting vector) S ∝ grad F
                  ∝ (K - (K·c) c) / ne^2 + (K·c) c / no^2, which leaves K by the walk-off angle

Refraction: the tangential part Kt of K is conserved at an interface with unit normal N (phase matching);
the normal component gamma of each mode follows from its dispersion relation, |Kt|^2 + gamma^2 = n^2 for an
isotropic medium or the ordinary wave and, for the extraordinary wave, the quadratic

    A gamma^2 + B gamma + C = 0,  u = 1/no^2, v = 1/ne^2, a = Kt·c, b = N·c,
    A = (u - v) b^2 + v,  B = 2 (u - v) a b,  C = (u - v) a^2 + v |Kt|^2 - 1.

Of the two roots, a wave leaving the interface on side sigma (= ±1 along N) is the one whose energy flows
that way, sigma S·N > 0 (for evanescent waves: decaying away from the interface).

Amplitudes: tangential E and H ∝ K × E are continuous (non-magnetic media), a 4 × 4 linear system for the
two reflected and the two transmitted modes of an incident wave. Power-normalised amplitudes
a = t sqrt(F_t / F_i) use the energy flux through the interface F = Re(E × H*)·N, so the |a|^2 of a
lossless interface add up to 1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

ORDINARY = "ordinary"
EXTRAORDINARY = "extraordinary"


def _dot(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.einsum("ij,ij->i", a, b)


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.sqrt(np.einsum("ij,ij->i", v, np.conj(v)).real)
    return v / np.where(n > 0, n, 1.0)[:, None]


@dataclass
class Uniaxial:
    """A uniaxial medium at one wavelength: indices and the unit optic axis (in the frame of the vectors used)."""

    no: float
    ne: float
    axis: np.ndarray
    mode: str = ORDINARY

    def __post_init__(self):
        a = np.asarray(self.axis, dtype=float)
        self.axis = a / np.linalg.norm(a)

    def phase_index_e(self, khat: np.ndarray) -> np.ndarray:
        """Extraordinary phase index along unit wave normals (n, 3)."""
        c2 = (np.asarray(khat) @ self.axis) ** 2
        return 1.0 / np.sqrt(c2 / self.no**2 + (1.0 - c2) / self.ne**2)

    def phase_index(self, khat: np.ndarray) -> np.ndarray:
        return np.full(len(khat), self.no) if self.mode == ORDINARY else self.phase_index_e(khat)

    def ray_e(self, K: np.ndarray) -> np.ndarray:
        """Unit ray (Poynting) direction of extraordinary waves K (n, 3)."""
        c = self.axis
        kc = K @ c
        S = K / self.ne**2 + (1.0 / self.no**2 - 1.0 / self.ne**2) * kc[:, None] * c[None, :]
        return _unit(S)

    def walkoff(self, khat: np.ndarray) -> np.ndarray:
        """Walk-off angle (rad) between the extraordinary wave normal and its ray."""
        K = self.phase_index_e(khat)[:, None] * khat
        return np.arccos(np.clip(_dot(_unit(K), self.ray_e(K)), -1.0, 1.0))


# ---------------------------------------------------------------- waves with a given tangential K
def tangential(K: np.ndarray, N: np.ndarray) -> np.ndarray:
    return K - _dot(K, N)[:, None] * N


def iso_wave(Kt: np.ndarray, N: np.ndarray, n: float, side: np.ndarray, allow_evanescent: bool = False):
    """Wave with tangential part Kt in an isotropic medium of index n leaving the interface on `side`.
    Returns (K, unit ray, propagating mask); K is complex when allow_evanescent."""
    g2 = n * n - _dot(Kt.real, Kt.real)
    prop = g2 >= 0.0
    if allow_evanescent:
        g = np.where(prop, side * np.sqrt(np.maximum(g2, 0.0)), 1j * side * np.sqrt(np.maximum(-g2, 0.0)))
        K = Kt.astype(complex) + g[:, None] * N
        return K, _unit(K.real), prop
    K = Kt + (side * np.sqrt(np.maximum(g2, 0.0)))[:, None] * N
    return K, _unit(K), prop


def e_wave(Kt: np.ndarray, N: np.ndarray, med: Uniaxial, side: np.ndarray, allow_evanescent: bool = False):
    """Extraordinary wave with tangential part Kt leaving the interface on `side` (see the module notes).
    Returns (K, unit ray direction S, propagating mask)."""
    c = med.axis
    u, v = 1.0 / med.no**2, 1.0 / med.ne**2
    Ktr = Kt.real
    a = Ktr @ c
    b = N @ c
    A = (u - v) * b * b + v
    B = 2.0 * (u - v) * a * b
    C = (u - v) * a * a + v * _dot(Ktr, Ktr) - 1.0
    disc = B * B - 4.0 * A * C
    prop = disc >= 0.0
    sq = np.sqrt(np.maximum(disc, 0.0))
    g1, g2 = (-B + sq) / (2.0 * A), (-B - sq) / (2.0 * A)
    K1 = Ktr + g1[:, None] * N
    K2 = Ktr + g2[:, None] * N
    S1 = K1 * v + (u - v) * (K1 @ c)[:, None] * c[None, :]
    S2 = K2 * v + (u - v) * (K2 @ c)[:, None] * c[None, :]
    pick1 = side * _dot(S1, N) >= side * _dot(S2, N)
    K = np.where(pick1[:, None], K1, K2)
    S = np.where(pick1[:, None], S1, S2)
    prop &= side * _dot(S, N) > 0.0
    if allow_evanescent and not np.all(prop):
        K = K.astype(complex)
        ev = disc < 0.0
        gi = np.sqrt(np.maximum(-disc, 0.0)) / (2.0 * A)
        gr = -B / (2.0 * A)
        g = gr + 1j * side * gi  # decays away from the interface on `side`
        K[ev] = Ktr[ev] + g[ev, None] * N[ev]
    return K, _unit(S), prop


def crystal_wave(Kt, N, med: Uniaxial, mode: str, side, allow_evanescent: bool = False):
    if mode == ORDINARY:
        return iso_wave(Kt, N, med.no, side, allow_evanescent)
    return e_wave(Kt, N, med, side, allow_evanescent)


# ---------------------------------------------------------------- refraction for the ray trace
def refract_aniso(K_in: np.ndarray, d_in: np.ndarray, N: np.ndarray, n_out: float, med_out: Uniaxial | None):
    """Refraction of waves K_in (rays travelling along d_in) into an isotropic medium of index n_out or into
    the selected mode of a uniaxial medium. Returns (unit ray direction, K_out, tir mask)."""
    side = np.where(_dot(d_in, N) >= 0.0, 1.0, -1.0)
    Kt = tangential(K_in, N)
    if med_out is None:
        K, ray, prop = iso_wave(Kt, N, n_out, side)
    elif med_out.mode == ORDINARY:
        K, ray, prop = iso_wave(Kt, N, med_out.no, side)
    else:
        K, ray, prop = e_wave(Kt, N, med_out, side)
    tir = ~prop
    ray = np.where(tir[:, None], d_in, ray)
    return ray, K, tir


# ---------------------------------------------------------------- mode fields and the interface solve
def s_vector(K: np.ndarray, N: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    """Unit s vector (K × N) / |K × N| of the plane of incidence; `fallback` at normal incidence."""
    s = np.cross(K.real, N)
    n = np.linalg.norm(s, axis=1)
    bad = n < 1e-12
    s = s / np.where(bad, 1.0, n)[:, None]
    s[bad] = fallback[bad]
    return s


def crystal_mode_field(K: np.ndarray, med: Uniaxial, mode: str, s: np.ndarray) -> np.ndarray:
    """Unit E vector of a crystal mode: ordinary E ∝ K × c, extraordinary E = eps^-1 K × (c × K); where K ∥ c
    (degenerate) the isotropic [s, k × s]."""
    c = med.axis.astype(complex)
    Kc = K.astype(complex)
    Eo = np.cross(Kc, c[None, :])
    deg = np.sqrt(np.einsum("ij,ij->i", Eo, np.conj(Eo)).real) < 1e-9 * np.maximum(1.0, np.abs(Kc).max(axis=1))
    if mode == ORDINARY:
        E = _unit(Eo)
        E[deg] = s[deg]
        return E
    D = c[None, :] * np.einsum("ij,ij->i", Kc, Kc)[:, None] - Kc * (Kc @ c)[:, None]
    E = D / med.no**2 + (1.0 / med.ne**2 - 1.0 / med.no**2) * (D @ c)[:, None] * c[None, :]
    E = _unit(E)
    if np.any(deg):
        E[deg] = _unit(np.cross(_unit(Kc[deg].real), s[deg])).astype(complex)
    return E


def flux(E: np.ndarray, K: np.ndarray, N: np.ndarray) -> np.ndarray:
    """Energy flux Re(E × H*)·N of a plane wave with H = K × E (units of the common factor)."""
    H = np.cross(K, E)
    return np.einsum("ij,ij->i", np.cross(E, np.conj(H)), N).real


@dataclass
class Side:
    """The medium on one side of an interface: isotropic (index n) or uniaxial."""

    n: float | None = None
    med: Uniaxial | None = None

    def modes(self, Kt, N, side, s):
        """[(K, E, ray, propagating)] of the two modes leaving the interface on `side`."""
        if self.med is None:
            K, ray, prop = iso_wave(Kt, N, self.n, side, allow_evanescent=True)
            E1, E2 = iso_fields(K, s)
            return [(K, E1, ray, prop), (K, E2, ray, prop)]
        out = []
        for mode in (ORDINARY, EXTRAORDINARY):
            K, ray, prop = crystal_wave(Kt, N, self.med, mode, side, allow_evanescent=True)
            out.append((K, crystal_mode_field(K, self.med, mode, s), ray, prop))
        return out


def iso_fields(K: np.ndarray, s: np.ndarray):
    """E vectors [s, k × s] of the two modes of an isotropic medium (k = K / sqrt(K·K), complex for
    evanescent waves)."""
    Kc = K.astype(complex)
    kn = np.sqrt(np.einsum("ij,ij->i", Kc, Kc))
    k = Kc / np.where(np.abs(kn) > 0, kn, 1.0)[:, None]
    return s.astype(complex), np.cross(k, s.astype(complex))


def interface_amplitudes(K_in, E_in, d_in, N, side_in: Side, side_out: Side, s):
    """Power-normalised amplitudes of an incident wave (K_in, unit E_in, travelling along d_in) at an
    interface: returns (reflected [(a, K, E, ray)] × 2, transmitted [(a, K, E, ray)] × 2), the modes ordered
    [s, p] (isotropic) or [ordinary, extraordinary]."""
    sigma = np.where(_dot(d_in, N) >= 0.0, 1.0, -1.0)
    Kt = tangential(K_in.real, N)
    refl = side_in.modes(Kt, N, -sigma, s)
    trans = side_out.modes(Kt, N, sigma, s)
    T1 = s.astype(complex)
    T2 = np.cross(N, s).astype(complex)
    n = len(K_in)
    M = np.zeros((n, 4, 4), dtype=complex)
    for col, (K, E, _, _), sgn in [(0, refl[0], 1), (1, refl[1], 1), (2, trans[0], -1), (3, trans[1], -1)]:
        H = np.cross(K, E)
        M[:, 0, col] = sgn * np.einsum("ij,ij->i", E, T1)
        M[:, 1, col] = sgn * np.einsum("ij,ij->i", E, T2)
        M[:, 2, col] = sgn * np.einsum("ij,ij->i", H, T1)
        M[:, 3, col] = sgn * np.einsum("ij,ij->i", H, T2)
    Ei = E_in.astype(complex)
    Hi = np.cross(K_in.astype(complex), Ei)
    rhs = -np.stack([np.einsum("ij,ij->i", Ei, T1), np.einsum("ij,ij->i", Ei, T2), np.einsum("ij,ij->i", Hi, T1), np.einsum("ij,ij->i", Hi, T2)], axis=1)
    x = np.linalg.solve(M, rhs[:, :, None])[:, :, 0]
    Fi = np.abs(flux(Ei, K_in.astype(complex), N))
    Fi = np.where(Fi > 0, Fi, 1.0)
    out_r, out_t = [], []
    for k, (K, E, ray, prop) in enumerate(refl):
        F = np.abs(flux(E, K, N))
        out_r.append((np.where(prop, x[:, k] * np.sqrt(F / Fi), 0.0), K, E, ray))
    for k, (K, E, ray, prop) in enumerate(trans):
        F = np.abs(flux(E, K, N))
        out_t.append((np.where(prop, x[:, 2 + k] * np.sqrt(F / Fi), 0.0), K, E, ray))
    return out_r, out_t
