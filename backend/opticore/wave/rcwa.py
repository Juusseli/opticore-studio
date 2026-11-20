"""Rigorous coupled-wave analysis (RCWA) of gratings periodic in x: diffraction efficiencies of every order.

Structure: an incident medium (z < 0, lossless, index n_in), layers stacked along +z, a substrate (index n_out). Each
layer is homogeneous or periodic in x with period L: a piecewise-constant permittivity eps(x) given by segments
(x0, x1, eps) in fractions of the period over a background. Continuous profiles (sinusoidal, sawtooth, trapezoid) are
cut into slices (a staircase), whose number the user sets.

Method (the S-matrix formulation of R. C. Rumpf, PIER B 35, 241 (2011), in the convention exp(+j w t): a lossy
medium has eps = n² with n = n′ − j k″; the physics' n + iκ is conjugated on input):

* Orders m = −M … M with the grating equation k_x,m = k_x,in + m λ/L (normalised by k0 = 2π/λ: n sin θ_m =
  n_in sin θ_in + m λ/L), k_y = k_y,in (conical incidence).
* In a layer the tangential fields obey d/dz′ [Ex, Ey] = P [Hx, Hy], d/dz′ [Hx, Hy] = Q [Ex, Ey] (z′ = k0 z, H scaled
  by −j sqrt(μ0/ε0)) with
      P = [[Kx Ezz⁻¹ Ky, I − Kx Ezz⁻¹ Kx], [Ky Ezz⁻¹ Ky − I, −Ky Ezz⁻¹ Kx]]
      Q = [[Kx Ky, Eyy − Kx²], [Ky² − Exx, −Ky Kx]]
  The Fourier factorisation follows L. Li (JOSA A 13, 1870 (1996)): Eyy and Ezz (fields tangential to the x-interfaces)
  are Toeplitz matrices of eps (Laurent's rule); Exx (normal to them) is the inverse of the Toeplitz matrix of 1/eps
  (inverse rule), which makes TM and metallic gratings converge.
* Modes: Ω² = P Q = W λ² W⁻¹, V = Q W λ⁻¹; homogeneous layers analytically (W = I, λ = j k_z).
* Layer scattering matrices relative to a zero-thickness gap whose modes have k_z = 1 in every order (its
  permittivity I + Kx² + Ky², which avoids singular gap modes at Wood anomalies), Redheffer star products, the
  incident and substrate half-spaces as in Rumpf.
* Efficiencies R_m = Re(−k_z,ref,m / k_z,in) |r_m|², T_m = Re(k_z,trn,m / k_z,in) |t_m|² with |r|² = |rx|² + |ry|² + |rz|²
  (rz from div E = 0); for a lossless structure Σ R + Σ T = 1 to rounding.

Polarisation: TE (s, E perpendicular to the plane of incidence) and TM (p) as the unit vectors of the incident wave;
"unpolarised" is their mean. Validated in tests/test_rcwa.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


class RcwaError(ValueError):
    pass


@dataclass
class GratingLayer:
    """thickness (um); eps_bg the background permittivity (physics convention, Im >= 0 for loss); segments
    [(x0, x1, eps)] in fractions of the period (0 <= x0 < x1 <= 1, not overlapping; later ones win)."""

    thickness: float
    eps_bg: complex
    segments: list[tuple[float, float, complex]] = field(default_factory=list)

    @property
    def uniform(self) -> bool:
        return not self.segments


def _coeffs(layer: GratingLayer, inv: bool, M2: int) -> np.ndarray:
    """Fourier coefficients c_m, m = −M2 … M2, of eps(x) (or 1/eps with inv) in the e^{+j2πmx/L} expansion."""
    m = np.arange(-M2, M2 + 1)
    f = (lambda e: 1.0 / e) if inv else (lambda e: e)
    bg = f(layer.eps_bg)
    c = np.zeros(len(m), complex)
    c[m == 0] = bg
    # paint the segments over the background: each contributes (value − value below it) over its interval
    # (non-overlapping segments: the value below is the background)
    for x0, x1, e in layer.segments:
        d = f(e) - bg
        w = x1 - x0
        with np.errstate(divide="ignore", invalid="ignore"):
            cm = d * (np.exp(-2j * np.pi * m * x0) - np.exp(-2j * np.pi * m * x1)) / (2j * np.pi * m)
        cm[m == 0] = d * w
        c += cm
    return c


def _toeplitz(c: np.ndarray, M: int) -> np.ndarray:
    n = 2 * M + 1
    i = np.arange(n)
    return c[(i[:, None] - i[None, :]) + 2 * M]


def _conv(c: np.ndarray, M: int) -> np.ndarray:
    """Convolution (Toeplitz) matrix of conj(f(x)) from the coefficients c of f(x) (physics convention): the solver works
    in exp(+j w t), where the medium is the pointwise conjugate, whose coefficient n is conj(c_−n). (Conjugating the
    Toeplitz matrix of f instead would mirror an asymmetric profile, x -> −x.)"""
    return _toeplitz(np.conj(c[::-1]), M)


def _star(SA, SB):
    """Redheffer star product of scattering matrices (S11, S12, S21, S22)."""
    A11, A12, A21, A22 = SA
    B11, B12, B21, B22 = SB
    I = np.eye(A11.shape[0])
    D = A12 @ np.linalg.inv(I - B11 @ A22)
    F = B21 @ np.linalg.inv(I - A22 @ B11)
    return (A11 + D @ B11 @ A21, D @ B12, F @ A21, B22 + F @ A22 @ B12)


def _check(layers: list[GratingLayer]):
    for k, L in enumerate(layers):
        if not L.thickness >= 0:
            raise RcwaError(f"Layer {k + 1}: the thickness must be zero or positive")
        prev = 0.0
        for x0, x1, _ in sorted(L.segments):
            if not (0.0 <= x0 < x1 <= 1.0):
                raise RcwaError(f"Layer {k + 1}: segments need 0 ≤ start < end ≤ 1 (fractions of the period)")
            if x0 < prev - 1e-12:
                raise RcwaError(f"Layer {k + 1}: segments overlap")
            prev = x1


def solve(period_um: float, layers: list[GratingLayer], eps_in: float, eps_out: complex, wavelength_um: float, theta_deg: float = 0.0, phi_deg: float = 0.0,
          pol: str = "TE", harmonics: int = 20) -> dict:
    """Diffraction efficiencies of the orders −harmonics … harmonics (module notes). pol: TE, TM or a pair (a_te, a_tm)."""
    if not (period_um > 0 and wavelength_um > 0):
        raise RcwaError("The period and the wavelength must be positive")
    if not (np.isreal(eps_in) and float(np.real(eps_in)) > 0):
        raise RcwaError("The incident medium must be lossless")
    _check(layers)
    M = int(harmonics)
    if M < 0 or M > 200:
        raise RcwaError("Harmonics must be between 0 and 200")
    N = 2 * M + 1
    lam, k0 = wavelength_um, 2 * math.pi / wavelength_um
    n_in = math.sqrt(float(np.real(eps_in)))
    th, ph = math.radians(theta_deg), math.radians(phi_deg)
    kin = n_in * np.array([math.sin(th) * math.cos(ph), math.sin(th) * math.sin(ph), math.cos(th)])
    m = np.arange(-M, M + 1)
    kx = kin[0] - m * lam / period_um
    ky = np.full(N, kin[1])
    Kx, Ky = np.diag(kx).astype(complex), np.diag(ky).astype(complex)
    I = np.eye(N)
    Z = np.zeros((N, N))
    I2 = np.eye(2 * N)
    conj = np.conj  # exp(+j w t): eps_rumpf = conj(eps_physics)

    # gap: k_z = 1 in every order (permittivity I + Kx² + Ky²)
    Q0 = np.block([[Kx @ Ky, I + Ky @ Ky], [-(I + Kx @ Kx), -Ky @ Kx]])
    W0 = I2
    V0 = Q0 / 1j  # λ0 = j I
    W0i, V0i = W0, np.linalg.inv(V0)

    def homogeneous(eps: complex):
        e = conj(eps)
        kz = conj(np.sqrt(conj(e) - kx * kx - ky * ky + 0j))
        Q = np.block([[Kx @ Ky, e * I - Kx @ Kx], [Ky @ Ky - e * I, -Ky @ Kx]])
        lam_ = np.concatenate([1j * kz, 1j * kz])
        return I2, Q / lam_[None, :], lam_, kz

    S = (np.zeros((2 * N, 2 * N), complex), I2.astype(complex), I2.astype(complex), np.zeros((2 * N, 2 * N), complex))
    # incident half-space (reference)
    Wr, Vr, _, kz_r = homogeneous(eps_in)
    A = W0i @ Wr + V0i @ Vr
    B = W0i @ Wr - V0i @ Vr
    Ai = np.linalg.inv(A)
    S_ref = (-Ai @ B, 2 * Ai, 0.5 * (A - B @ Ai @ B), B @ Ai)
    S = S_ref
    for L in layers:
        if L.thickness == 0:
            continue
        if L.uniform:
            W, V, lam_, _ = homogeneous(L.eps_bg)
        else:
            Eyy = _conv(_coeffs(L, False, 2 * M), M)
            Ezz_i = np.linalg.inv(Eyy)
            Exx = np.linalg.inv(_conv(_coeffs(L, True, 2 * M), M))
            P = np.block([[Kx @ Ezz_i @ Ky, I - Kx @ Ezz_i @ Kx], [Ky @ Ezz_i @ Ky - I, -Ky @ Ezz_i @ Kx]])
            Q = np.block([[Kx @ Ky, Eyy - Kx @ Kx], [Ky @ Ky - Exx, -Ky @ Kx]])
            l2, W = np.linalg.eig(P @ Q)
            lam_ = np.sqrt(l2 + 0j)
            V = Q @ W / lam_[None, :]
        Wi, Vi = np.linalg.inv(W), np.linalg.inv(V)
        A = Wi @ W0 + Vi @ V0
        B = Wi @ W0 - Vi @ V0
        X = np.diag(np.exp(-lam_ * k0 * L.thickness))
        Ai = np.linalg.inv(A)
        D = np.linalg.inv(A - X @ B @ Ai @ X @ B)
        S11 = D @ (X @ B @ Ai @ X @ A - B)
        S12 = D @ X @ (A - B @ Ai @ B)
        S = _star(S, (S11, S12, S12, S11))
    # substrate half-space (transmission)
    Wt, Vt, _, kz_t = homogeneous(eps_out)
    A = W0i @ Wt + V0i @ Vt
    B = W0i @ Wt - V0i @ Vt
    Ai = np.linalg.inv(A)
    S = _star(S, (B @ Ai, 0.5 * (A - B @ Ai @ B), 2 * Ai, -Ai @ B))

    # source: unit polarisation vector of the incident plane wave (TE along z x k, TM = k x TE)
    kh = kin / n_in
    if abs(kh[0]) < 1e-12 and abs(kh[1]) < 1e-12:
        a_te = np.array([0.0, 1.0, 0.0])
    else:
        a_te = np.cross([0.0, 0.0, 1.0], kh)
        a_te /= np.linalg.norm(a_te)
    a_tm = np.cross(kh, a_te)
    a_tm /= np.linalg.norm(a_tm)
    if isinstance(pol, str):
        p_te, p_tm = {"TE": (1.0, 0.0), "TM": (0.0, 1.0)}[pol.upper()]
    else:
        p_te, p_tm = pol
    Pv = p_te * a_te + p_tm * a_tm
    Pv = Pv / np.linalg.norm(Pv)
    esrc = np.zeros(2 * N, complex)
    esrc[M], esrc[N + M] = Pv[0], Pv[1]
    csrc = esrc  # W_ref = I
    r = Wr @ (S[0] @ csrc)
    t = Wt @ (S[2] @ csrc)
    rx, ry = r[:N], r[N:]
    tx, ty = t[:N], t[N:]
    kz_ref = -kz_r  # reflected waves travel towards −z
    with np.errstate(divide="ignore", invalid="ignore"):
        rz = -(kx * rx + ky * ry) / kz_ref
        tz = -(kx * tx + ky * ty) / kz_t
    kz_in = kin[2]
    R = np.real(-kz_ref / kz_in) * (np.abs(rx) ** 2 + np.abs(ry) ** 2 + np.abs(rz) ** 2)
    T = np.real(kz_t / kz_in) * (np.abs(tx) ** 2 + np.abs(ty) ** 2 + np.abs(tz) ** 2)
    R = np.where(np.isfinite(R), R, 0.0)
    T = np.where(np.isfinite(T), T, 0.0)
    prop_r = np.real(kz_r) > 1e-12
    prop_t = np.real(kz_t) > 1e-12 if np.isreal(eps_out) or abs(np.imag(eps_out)) < 1e-15 else np.zeros(N, bool)
    # reported orders follow the grating equation n sin(theta_m) = n_in sin(theta_in) + m lambda / L: the internal index
    # (k_x,m = k_x,in − m λ/L) is relabelled m -> −m and every per-order array reversed, so orders run −M … M
    rev = slice(None, None, -1)
    return {"orders": m, "kx": kx[rev], "ky": ky[rev], "R": np.where(prop_r, R, 0.0)[rev], "T": np.where(prop_t, T, 0.0)[rev],
            "r": (rx[rev], ry[rev], rz[rev]), "t": (tx[rev], ty[rev], tz[rev]), "kz_ref": kz_r[rev], "kz_trn": kz_t[rev],
            "propagating_r": prop_r[rev], "propagating_t": prop_t[rev]}
