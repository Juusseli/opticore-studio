"""Surface scatter distributions (BSDF) for the non-sequential trace (docs/OPTICAL_ENGINE.md §8h).

Directions are described by their direction cosines beta (a 2-vector) in the scattering surface's tangent
plane; the projected solid angle is cos(theta) dOmega = d^2 beta, so a BSDF f(beta) in sr^-1 scatters the
power dP = P_in f(beta) d^2 beta into d^2 beta, and the total integrated scatter is
TIS = int_{|beta| < 1} f d^2 beta. beta_0 is the specular (or regular transmission) direction.

Models (x = |beta - beta_0|):
    lambertian   f = rho / pi                                  (TIS = rho at every incidence)
    gaussian     polar angle from beta_0 with a 2-D Gaussian of per-axis width sigma; TIS = fraction
                 (phenomenological, no closed-form f: not used for importance sampling)
    abg          f = A / (B + x^g)                             (Harvey-type empirical ABg)
    harvey       f = b0 (1 + (x / l)^2)^(s / 2)                (Harvey-Shack, s < 0 the fall-off slope)
For ABg and Harvey the amplitude (A, b0) follows from the requested TIS at normal incidence (`fraction`),
so the models are energy-normalised; at oblique incidence TIS(beta_0) is the integral over the part of the
lobe inside the unit circle,
    TIS(b) = int_0^{1+b} f(x) x theta_in(x, b) dx,   theta_in = 2 pi (x <= 1 - b), 0 (x >= 1 + b),
             2 arccos((x^2 + b^2 - 1) / (2 x b)) otherwise,  b = |beta_0|,
evaluated by adaptive quadrature. ABg with g = 0 is Lambertian with rho = pi A / (B + 1).

Sampling: x from q(x) ~ shape(x) x on [0, 1 + b] (inverse of a tabulated CDF on a grid dense near 0),
azimuth uniform, beta = beta_0 + x (cos phi, sin phi), rejected and redrawn while |beta| >= 1. The accepted
samples have density f(beta) / TIS on the unit disc exactly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.integrate import quad

MODELS = ("lambertian", "gaussian", "abg", "harvey")
_GRID = np.concatenate([[0.0], np.geomspace(1e-9, 2.0, 6000)])


def _basis(n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = np.cross(n, a)
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(n, e1)


def theta_in(x: float, b: float) -> float:
    """Angle (radians) of the circle |beta - beta_0| = x that lies inside the unit disc, |beta_0| = b."""
    if x <= 1.0 - b:
        return 2.0 * math.pi
    if x >= 1.0 + b or b == 0.0:
        return 0.0
    c = (x * x + b * b - 1.0) / (2.0 * x * b)
    return 2.0 * math.acos(max(-1.0, min(1.0, c)))


@dataclass
class Bsdf:
    model: str
    fraction: float  # lambertian: rho; gaussian: scattered fraction; abg/harvey: TIS at normal incidence
    sigma: float = 0.0  # gaussian width (rad)
    B: float = 1e-3
    g: float = 2.0
    l: float = 0.01  # noqa: E741 (Harvey shoulder, direction-cosine units)
    s: float = -2.0
    _tis_cache: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if self.model not in MODELS:
            raise ValueError(f"unknown scatter model '{self.model}'")
        if not 0.0 <= self.fraction <= 1.0:
            raise ValueError("the scatter fraction (TIS) must be within 0…1")
        if self.model == "abg" and (self.B <= 0.0 or self.g < 0.0):
            raise ValueError("ABg needs B > 0 and g >= 0")
        if self.model == "harvey" and (self.l <= 0.0 or self.s >= 0.0):
            raise ValueError("Harvey-Shack needs a shoulder l > 0 and a slope s < 0")
        self.amplitude = 0.0
        if self.model in ("abg", "harvey"):
            t0 = self._shape_tis(0.0)
            self.amplitude = self.fraction / t0 if t0 > 0 else 0.0
            q = self.shape(_GRID) * _GRID
            cdf = np.concatenate([[0.0], np.cumsum(0.5 * (q[1:] + q[:-1]) * np.diff(_GRID))])
            self._cdf = cdf
        elif self.model == "lambertian":
            self.amplitude = self.fraction / math.pi

    # ------------------------------------------------------------------ values
    def shape(self, x):
        x = np.asarray(x, dtype=float)
        if self.model == "abg":
            return 1.0 / (self.B + x**self.g)
        if self.model == "harvey":
            return (1.0 + (x / self.l) ** 2) ** (self.s / 2.0)
        return np.ones_like(x)

    def value(self, x) -> np.ndarray:
        """BSDF (sr^-1) at |beta - beta_0| = x (lambertian and the fitted models; not gaussian)."""
        if self.model == "gaussian":
            raise ValueError("the Gaussian scatter model has no closed-form BSDF")
        return self.amplitude * self.shape(x)

    @property
    def has_value(self) -> bool:
        return self.model != "gaussian"

    @property
    def abg_a(self) -> float | None:
        return self.amplitude if self.model == "abg" else None

    def _shape_tis(self, b: float) -> float:
        def f(x):
            return float(self.shape(x)) * x * theta_in(x, b)

        pts = sorted({p for p in (abs(1.0 - b), 1.0 + b, self.B ** (1.0 / self.g) if self.model == "abg" and self.g > 0 else self.l if self.model == "harvey" else 0.5) if 0.0 < p < 1.0 + b})
        val, _err = quad(f, 0.0, 1.0 + b, points=pts or None, limit=400, epsabs=1e-13, epsrel=1e-11)
        return val

    def tis(self, b: float) -> float:
        """Total integrated scatter for a specular direction with |beta_0| = b (fraction of the incident power)."""
        if self.model in ("lambertian", "gaussian"):
            return self.fraction
        key = round(b, 6)
        hit = self._tis_cache.get(key)
        if hit is None:
            hit = self.amplitude * self._shape_tis(key)
            self._tis_cache[key] = hit
        return hit

    # ------------------------------------------------------------------ sampling
    def _sample_x(self, b: float, rng) -> float:
        top = float(np.interp(1.0 + b, _GRID, self._cdf))
        return float(np.interp(rng.random() * top, self._cdf, _GRID))

    def sample(self, specular: np.ndarray, out_normal: np.ndarray, rng, tries: int = 2000) -> np.ndarray:
        """A scattered direction (unit) on the side of `out_normal`, distributed as the BSDF about `specular`."""
        if self.model == "lambertian":
            u1, u2 = rng.random(2)
            s, c, ph = math.sqrt(u1), math.sqrt(1.0 - u1), 2 * math.pi * u2
            e1, e2 = _basis(out_normal)
            return c * out_normal + s * (math.cos(ph) * e1 + math.sin(ph) * e2)
        if self.model == "gaussian":
            from .nonseq import sample_gaussian

            return sample_gaussian(specular, out_normal, self.sigma, rng)
        e1, e2 = _basis(out_normal)
        b0 = np.array([float(specular @ e1), float(specular @ e2)])
        b = float(np.hypot(*b0))
        for _ in range(tries):
            x = self._sample_x(b, rng)
            ph = 2 * math.pi * rng.random()
            beta = b0 + x * np.array([math.cos(ph), math.sin(ph)])
            r2 = float(beta @ beta)
            if r2 < 1.0:
                return beta[0] * e1 + beta[1] * e2 + math.sqrt(1.0 - r2) * out_normal
        return specular.copy()

    def density(self, d: np.ndarray, specular: np.ndarray, out_normal: np.ndarray) -> float:
        """BSDF value (sr^-1) for the outgoing direction d (unit, on the side of out_normal)."""
        e1, e2 = _basis(out_normal)
        b0 = np.array([float(specular @ e1), float(specular @ e2)])
        beta = np.array([float(d @ e1), float(d @ e2)])
        return float(self.value(np.hypot(*(beta - b0))))

    def describe(self) -> dict:
        out = {"model": self.model, "fraction": self.fraction}
        if self.model == "gaussian":
            out["sigma_deg"] = math.degrees(self.sigma)
        if self.model == "abg":
            out.update(A=self.amplitude, B=self.B, g=self.g)
        if self.model == "harvey":
            out.update(b0=self.amplitude, l=self.l, s=self.s)
        return out
