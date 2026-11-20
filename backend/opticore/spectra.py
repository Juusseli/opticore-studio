"""Source spectra as wavelength samples with power weights.

A spectrum fills a light source's wavelength list: n bins of equal width over a band, each represented by its
centre, with the weight equal to the spectral power in the bin (normalised to a sum of one).

* Blackbody (temperature T): Planck's spectral radiance
      B(lambda, T) = 2 h c^2 / lambda^5 / (exp(h c / (lambda k T)) - 1),
  integrated over each bin by 16-point Gauss-Legendre quadrature. The fraction of the total radiance
  (sigma T^4 / pi) that falls in the band is reported.
* Gaussian line (centre, FWHM): intensity exp(-(lambda - c)^2 / (2 s^2)) with s = FWHM / (2 sqrt(2 ln 2)), over
  c +- 2 FWHM unless a band is given, integrated over each bin exactly (error functions). A model of an LED or a
  broadened laser line.
* Flat band: equal weights.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

H = 6.62607015e-34  # J s
C = 2.99792458e8  # m/s
K = 1.380649e-23  # J/K
SIGMA = 2.0 * math.pi**5 * K**4 / (15.0 * H**3 * C**2)  # Stefan-Boltzmann constant, W m^-2 K^-4
WIEN_UM_K = 2897.771955  # Wien's displacement constant, um K
_GL_X, _GL_W = np.polynomial.legendre.leggauss(16)


class SpectrumSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["blackbody", "gaussian", "flat"]
    temperature_k: float = Field(5778.0, gt=0.0, le=1e6)
    center_um: float = Field(0.55, gt=0.0, le=100.0)
    fwhm_um: float = Field(0.03, gt=0.0, le=10.0)
    lambda_min_um: float | None = Field(None, gt=0.0, le=100.0)
    lambda_max_um: float | None = Field(None, gt=0.0, le=100.0)
    samples: int = Field(9, ge=1, le=64)

    @model_validator(mode="after")
    def _check(self):
        if self.kind in ("blackbody", "flat") and (self.lambda_min_um is None or self.lambda_max_um is None):
            raise ValueError("a blackbody or flat spectrum needs a band (lambda_min_um, lambda_max_um)")
        if self.lambda_min_um is not None and self.lambda_max_um is not None and not self.lambda_min_um < self.lambda_max_um:
            raise ValueError("the band needs lambda_min_um < lambda_max_um")
        return self


def planck(lam_um, T: float) -> np.ndarray:
    """Spectral radiance B(lambda, T) in W sr^-1 m^-2 um^-1."""
    lam = np.asarray(lam_um, dtype=float) * 1e-6
    with np.errstate(over="ignore"):
        x = H * C / (lam * K * T)
        return np.where(x > 700, 0.0, 2.0 * H * C * C / lam**5 / np.expm1(np.minimum(x, 700))) * 1e-6


def _bin_integral(f, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    mid, half = 0.5 * (a + b), 0.5 * (b - a)
    x = mid[:, None] + half[:, None] * _GL_X[None, :]
    return (f(x) * _GL_W[None, :]).sum(1) * half


def generate(spec: SpectrumSpec) -> dict:
    """{'wavelengths': [{'value': um, 'weight': w}], 'info': {...}} (module docstring)."""
    if spec.kind == "gaussian":
        s = spec.fwhm_um / (2.0 * math.sqrt(2.0 * math.log(2.0)))
        lo = spec.lambda_min_um if spec.lambda_min_um is not None else max(1e-3, spec.center_um - 2.0 * spec.fwhm_um)
        hi = spec.lambda_max_um if spec.lambda_max_um is not None else spec.center_um + 2.0 * spec.fwhm_um
    else:
        lo, hi = float(spec.lambda_min_um), float(spec.lambda_max_um)
    n = spec.samples
    edges = np.linspace(lo, hi, n + 1)
    a, b = edges[:-1], edges[1:]
    centres = 0.5 * (a + b)
    info: dict = {"kind": spec.kind, "band_um": [lo, hi], "bin_um": (hi - lo) / n}
    if spec.kind == "blackbody":
        w = _bin_integral(lambda x: planck(x, spec.temperature_k), a, b)
        total = SIGMA * spec.temperature_k**4 / math.pi  # W sr^-1 m^-2
        info.update({"temperature_k": spec.temperature_k, "peak_um": WIEN_UM_K / spec.temperature_k, "band_fraction": float(w.sum() / total)})
    elif spec.kind == "gaussian":
        erf = np.vectorize(math.erf)
        w = 0.5 * (erf((b - spec.center_um) / (math.sqrt(2.0) * s)) - erf((a - spec.center_um) / (math.sqrt(2.0) * s)))
        info.update({"center_um": spec.center_um, "fwhm_um": spec.fwhm_um, "band_fraction": float(w.sum())})
    else:
        w = np.ones(n)
    if not w.sum() > 0:
        raise ValueError("The spectrum carries no power in the band")
    w = w / w.sum()
    return {"wavelengths": [{"value": float(c), "weight": float(x)} for c, x in zip(centres, w)], "info": info}
