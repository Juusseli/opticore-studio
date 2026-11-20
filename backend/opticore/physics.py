"""Interface physics: vector refraction (Snell), reflection and Fresnel equations."""

from __future__ import annotations

import numpy as np


def refract(d: np.ndarray, n_hat: np.ndarray, n1: np.ndarray | float, n2: np.ndarray | float):
    """Vector form of Snell's law.

    d      incident unit directions (N,3)
    n_hat  unit surface normals (N,3) (either orientation)
    returns (t, tir_mask, cos_i, cos_t) with t the refracted unit directions.

    With N oriented along the propagation (cos_i = d.N > 0):
        t = mu d + (cos_t - mu cos_i) N,  mu = n1/n2,
        cos_t = sqrt(1 - mu^2 (1 - cos_i^2)).
    """
    cos_i = np.einsum("ij,ij->i", d, n_hat)
    sign = np.where(cos_i < 0.0, -1.0, 1.0)
    N = n_hat * sign[:, None]
    cos_i = np.abs(cos_i)
    mu = np.asarray(n1, dtype=float) / np.asarray(n2, dtype=float)
    mu = np.broadcast_to(mu, cos_i.shape)
    k = 1.0 - mu * mu * (1.0 - cos_i * cos_i)
    tir = k < 0.0
    cos_t = np.sqrt(np.where(tir, 0.0, k))
    t = mu[:, None] * d + (cos_t - mu * cos_i)[:, None] * N
    t = t / np.linalg.norm(t, axis=1, keepdims=True)
    return t, tir, cos_i, cos_t


def reflect(d: np.ndarray, n_hat: np.ndarray):
    """Law of reflection r = d - 2 (d.N) N. Returns (r, cos_i)."""
    dn = np.einsum("ij,ij->i", d, n_hat)
    r = d - 2.0 * dn[:, None] * n_hat
    r = r / np.linalg.norm(r, axis=1, keepdims=True)
    return r, np.abs(dn)


def fresnel(n1, n2, cos_i, cos_t):
    """Fresnel power coefficients for a lossless dielectric interface.

    Returns dict with Rs, Rp, Ts, Tp (intensity/power fractions) and the
    amplitude coefficients rs, rp, ts, tp. Power transmittance includes the
    beam cross-section and impedance factor n2 cos_t / (n1 cos_i), so that
    R + T = 1 holds exactly for each polarisation (verified in tests).
    """
    n1 = np.asarray(n1, dtype=float)
    n2 = np.asarray(n2, dtype=float)
    cos_i = np.asarray(cos_i, dtype=float)
    cos_t = np.asarray(cos_t, dtype=float)
    a = n1 * cos_i
    b = n2 * cos_t
    c = n2 * cos_i
    d = n1 * cos_t
    rs = (a - b) / (a + b)
    rp = (c - d) / (c + d)
    ts = 2.0 * a / (a + b)
    tp = 2.0 * a / (c + d)
    factor = np.where(a > 0, b / np.where(a > 0, a, 1.0), 0.0)
    Ts = factor * ts * ts
    Tp = factor * tp * tp
    return {"rs": rs, "rp": rp, "ts": ts, "tp": tp, "Rs": rs * rs, "Rp": rp * rp, "Ts": Ts, "Tp": Tp}


def unpolarized_transmittance(n1, n2, cos_i, cos_t):
    f = fresnel(n1, n2, cos_i, cos_t)
    return 0.5 * (f["Ts"] + f["Tp"])


def unpolarized_reflectance(n1, n2, cos_i, cos_t):
    f = fresnel(n1, n2, cos_i, cos_t)
    return 0.5 * (f["Rs"] + f["Rp"])
