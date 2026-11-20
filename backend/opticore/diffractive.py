"""Diffractive surfaces: linear gratings and radially symmetric phase profiles.

Any refracting surface or mirror can carry a diffractive phase (in radians)

    phi(x, y) = 2 pi f y + sum_i A_i (r / R)^(2 i),    r^2 = x^2 + y^2

f: grating frequency in lines/mm (grating lines parallel to the local x axis),
A_i: radial phase coefficients (radians at the normalisation radius R, mm).
The ray is sent into diffraction order m.

Direction (vector grating equation on the local tangent plane, exact):

    n2 d2_t = n1 d1_t + m lambda0 G_t,    G = grad(phi) / (2 pi)  [cycles/mm]
    n2 d2_n = +-sqrt(n2^2 - |n2 d2_t|^2)

(transmission keeps the side of propagation, reflection reverses it; for a
mirror n2 = n1). When |n2 d2_t| > n2 the order is evanescent and the ray is
terminated with status EVANESCENT.

Optical path: by Fermat's principle for a surface phase the path length
gains m lambda0 phi / (2 pi), so wavefronts, OPD, PSF and MTF include the
diffractive phase consistently.

Paraxial power of the radial term: phi_d = -m lambda0 A_1 / (pi R^2)
(added to the refractive power in the y-nu trace; higher terms and linear
gratings have no paraxial power). Efficiency is assumed 100 % in the
selected order (scalar, thin-element model; no rigorous grating theory).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Doe:
    order: int
    frequency: float  # lines/mm along local y
    coeffs: tuple[float, ...]  # A1, A2, ... (radians)
    norm_radius: float  # mm

    def phase(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        ph = 2 * math.pi * self.frequency * y
        u = (x * x + y * y) / (self.norm_radius**2)
        p = u.copy()
        for a in self.coeffs:
            ph = ph + a * p
            p = p * u
        return ph

    def grating_vector(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """grad(phi) / (2 pi) in the local x-y plane (cycles/mm), shape (N, 3)."""
        u = (x * x + y * y) / (self.norm_radius**2)
        # d phi / d(r^2) = sum_i i A_i u^(i-1) / R^2
        dp = np.zeros_like(u)
        p = np.ones_like(u)
        for i, a in enumerate(self.coeffs, start=1):
            dp = dp + i * a * p
            p = p * u
        dp = dp / (self.norm_radius**2)
        gx = 2 * x * dp / (2 * math.pi)
        gy = 2 * y * dp / (2 * math.pi) + self.frequency
        return np.stack([gx, gy, np.zeros_like(gx)], axis=1)

    def paraxial_power(self, lam_mm: float) -> float:
        if not self.coeffs:
            return 0.0
        return -self.order * lam_mm * self.coeffs[0] / (math.pi * self.norm_radius**2)


def diffract(d: np.ndarray, normals: np.ndarray, n1: float, n2: float, G: np.ndarray, order: int, lam_mm: float, reflection: bool):
    """New unit directions after diffraction into `order`; returns (dirs, evanescent_mask)."""
    cn = np.einsum("ij,ij->i", d, normals)
    N = normals * np.where(cn < 0.0, -1.0, 1.0)[:, None]  # oriented along the propagation
    dn_ = np.einsum("ij,ij->i", d, N)
    d_t = d - dn_[:, None] * N
    gn = np.einsum("ij,ij->i", G, N)
    G_t = G - gn[:, None] * N
    nout = n1 if reflection else n2
    t = n1 * d_t + order * lam_mm * G_t
    tt = np.einsum("ij,ij->i", t, t)
    evan = tt > nout * nout
    c = np.sqrt(np.clip(nout * nout - tt, 0.0, None))
    out = t + (-c if reflection else c)[:, None] * N
    out = out / nout
    out /= np.linalg.norm(out, axis=1, keepdims=True)
    return out, evan
