"""Dispersion models for refractive index versus wavelength.

All formulas take the vacuum wavelength in micrometres. Catalogue glass data
are, by industry convention, relative to air at standard conditions; the engine
therefore treats AIR as n = 1 exactly (see docs/OPTICAL_ENGINE.md).

Supported models
----------------
sellmeier    n^2 - 1 = sum_i B_i L^2 / (L^2 - C_i)            (C_i in um^2)
sellmeier_sq n^2 - 1 = sum_i B_i L^2 / (L^2 - C_i^2)          (C_i in um)
schott       n^2 = A0 + A1 L^2 + A2 L^-2 + A3 L^-4 + A4 L^-6 + A5 L^-8
cauchy       n = A + B L^-2 + C L^-4
polynomial   n^2 = A + sum_i c_i L^e_i     (coefficients A, c1, e1, c2, e2, ...; refractiveindex.info formula 3)
constant     n = n0
tabulated    piecewise-cubic (monotone, PCHIP) interpolation of measured (L, n)

Further formulas used by glass catalogues (AGF formula numbers in brackets;
coefficients in the order the catalogues list them):
extended     n^2 = A0 + A1 L^2 + A2 L^-2 + A3 L^-4 + A4 L^-6 + A5 L^-8 + A6 L^-10 + A7 L^-12   [10]
extended2    n^2 = A0 + A1 L^2 + A2 L^-2 + A3 L^-4 + A4 L^-6 + A5 L^-8 + A6 L^4 + A7 L^6      [12]
extended3    n^2 = A0 + A1 L^2 + A2 L^4 + A3 L^-2 + A4 L^-4 + A5 L^-6 + A6 L^-8 + A7 L^-10 + A8 L^-12   [13]
herzberger   n = A + B Lh + C Lh^2 + D L^2 + E L^4 + F L^6,  Lh = 1/(L^2 - 0.028)        [3]
sellmeier2   n^2 - 1 = A + B1 L^2/(L^2 - l1^2) + B2/(L^2 - l2^2)   (A, B1, l1, B2, l2)    [4]
conrady      n = n0 + A/L + B/L^3.5                                                      [5]
handbook1    n^2 = A + B/(L^2 - C) - D L^2                                               [7]
handbook2    n^2 = A + B L^2/(L^2 - C) - D L^2                                           [8]
sellmeier4   n^2 = A + B L^2/(L^2 - C) + D L^2/(L^2 - E)                                 [9]
(Schott [1] is `schott`; Sellmeier 1, 3 and 5 [2, 6, 11] are `sellmeier`.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

import numpy as np
from scipy.interpolate import PchipInterpolator

FormulaName = Literal[
    "sellmeier", "sellmeier_sq", "schott", "cauchy", "polynomial", "constant", "tabulated",
    "extended", "extended2", "extended3", "herzberger", "sellmeier2", "conrady", "handbook1", "handbook2", "sellmeier4",
]

# maximum number of coefficients of the fixed-length catalogue formulas
FIXED_COUNTS = {"extended": 8, "extended2": 8, "extended3": 9, "herzberger": 6, "sellmeier2": 5, "conrady": 3, "handbook1": 4, "handbook2": 4, "sellmeier4": 5}

# Fraunhofer reference lines (um), as used for nd / Vd definitions.
LAMBDA_D = 0.5875618  # helium d line
LAMBDA_F = 0.4861327  # hydrogen F line
LAMBDA_C = 0.6562725  # hydrogen C line
LAMBDA_E = 0.546074  # mercury e line
LAMBDA_FP = 0.4799914  # cadmium F' line
LAMBDA_CP = 0.6438469  # cadmium C' line


class DispersionError(ValueError):
    pass


@dataclass(frozen=True)
class ThermalCoefficients:
    """Schott-type absolute dn/dT model coefficients (reference temperature T0)."""

    D0: float
    D1: float
    D2: float
    E0: float
    E1: float
    lambda_tk: float  # um
    T0: float = 20.0  # degC


@dataclass
class Dispersion:
    formula: FormulaName
    coefficients: Sequence[float] = field(default_factory=list)
    table: Sequence[Sequence[float]] | None = None  # [[lambda_um, n], ...]
    lambda_min: float = 0.0
    lambda_max: float = float("inf")
    thermal: ThermalCoefficients | None = None
    _interp: PchipInterpolator | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        c = list(self.coefficients)
        if self.formula in ("sellmeier", "sellmeier_sq"):
            if len(c) == 0 or len(c) % 2:
                raise DispersionError("Sellmeier needs pairs of (B, C) coefficients")
        elif self.formula == "schott":
            if not 1 <= len(c) <= 6:
                raise DispersionError("Schott formula takes 1..6 coefficients A0..A5")
        elif self.formula == "cauchy":
            if not 1 <= len(c) <= 3:
                raise DispersionError("Cauchy formula takes 1..3 coefficients A, B, C")
        elif self.formula == "polynomial":
            if len(c) % 2 == 0:
                raise DispersionError("Polynomial formula takes A followed by (coefficient, exponent) pairs")
        elif self.formula in FIXED_COUNTS:
            if not 1 <= len(c) <= FIXED_COUNTS[self.formula]:
                raise DispersionError(f"{self.formula} formula takes 1..{FIXED_COUNTS[self.formula]} coefficients")
        elif self.formula == "constant":
            if len(c) != 1:
                raise DispersionError("Constant index takes exactly one coefficient")
        elif self.formula == "tabulated":
            if not self.table or len(self.table) < 2:
                raise DispersionError("Tabulated data needs at least two (lambda, n) points")
            arr = np.asarray(self.table, dtype=float)
            if arr.ndim != 2 or arr.shape[1] != 2:
                raise DispersionError("Tabulated data must be [[lambda_um, n], ...]")
            order = np.argsort(arr[:, 0])
            arr = arr[order]
            if np.any(np.diff(arr[:, 0]) <= 0):
                raise DispersionError("Tabulated wavelengths must be unique")
            self._interp = PchipInterpolator(arr[:, 0], arr[:, 1], extrapolate=True)
            if self.lambda_min == 0.0 and self.lambda_max == float("inf"):
                self.lambda_min = float(arr[0, 0])
                self.lambda_max = float(arr[-1, 0])
        else:
            raise DispersionError(f"Unknown dispersion formula '{self.formula}'")

    # ------------------------------------------------------------------
    def in_range(self, wavelength_um: float) -> bool:
        return self.lambda_min - 1e-12 <= wavelength_um <= self.lambda_max + 1e-12

    def index(self, wavelength_um: float | np.ndarray) -> float | np.ndarray:
        """Refractive index at the given vacuum wavelength(s) in micrometres."""
        L = np.asarray(wavelength_um, dtype=float)
        if np.any(L <= 0):
            raise DispersionError("Wavelength must be positive")
        c = list(self.coefficients)
        f = self.formula
        if f in ("sellmeier", "sellmeier_sq"):
            L2 = L * L
            n2 = np.ones_like(L2)
            for B, C in zip(c[0::2], c[1::2]):
                Ceff = C * C if f == "sellmeier_sq" else C
                n2 = n2 + B * L2 / (L2 - Ceff)
            n = np.sqrt(n2)
        elif f == "schott":
            A = c + [0.0] * (6 - len(c))
            L2 = L * L
            n2 = A[0] + A[1] * L2 + A[2] / L2 + A[3] / L2**2 + A[4] / L2**3 + A[5] / L2**4
            n = np.sqrt(n2)
        elif f == "cauchy":
            A = c + [0.0] * (3 - len(c))
            n = A[0] + A[1] / L**2 + A[2] / L**4
        elif f == "polynomial":
            n2 = np.full_like(L, c[0])
            for k, e in zip(c[1::2], c[2::2]):
                n2 = n2 + k * L**e
            with np.errstate(invalid="ignore"):
                n = np.sqrt(n2)
        elif f in FIXED_COUNTS:
            n = _catalogue_formula(f, c + [0.0] * (FIXED_COUNTS[f] - len(c)), L)
        elif f == "constant":
            n = np.full_like(L, c[0])
        else:  # tabulated
            assert self._interp is not None
            n = self._interp(L)
        if np.any(~np.isfinite(n)):
            raise DispersionError(
                f"Dispersion formula produced a non-physical index at {wavelength_um} um"
            )
        return float(n) if np.ndim(n) == 0 else n

    def index_at_temperature(self, wavelength_um: float, temperature_c: float) -> float:
        """Index including the Schott absolute thermal model when coefficients exist.

        n(T) = n0 + (n0^2 - 1)/(2 n0) * [D0 dT + D1 dT^2 + D2 dT^3 +
                                       (E0 dT + E1 dT^2) / (L^2 - L_tk^2)]
        The air-relative/absolute distinction is ignored at this level of the
        model (documented limitation)."""
        n0 = float(self.index(wavelength_um))
        th = self.thermal
        if th is None or temperature_c == th.T0:
            return n0
        dT = temperature_c - th.T0
        L = wavelength_um
        dn = (n0 * n0 - 1.0) / (2.0 * n0) * (
            th.D0 * dT + th.D1 * dT**2 + th.D2 * dT**3
            + (th.E0 * dT + th.E1 * dT**2) / (L * L - th.lambda_tk**2)
        )
        return n0 + dn


def _catalogue_formula(f: str, a: list[float], L: np.ndarray) -> np.ndarray:
    L2 = L * L
    if f == "extended":
        n2 = a[0] + a[1] * L2 + a[2] / L2 + a[3] / L2**2 + a[4] / L2**3 + a[5] / L2**4 + a[6] / L2**5 + a[7] / L2**6
    elif f == "extended2":
        n2 = a[0] + a[1] * L2 + a[2] / L2 + a[3] / L2**2 + a[4] / L2**3 + a[5] / L2**4 + a[6] * L2**2 + a[7] * L2**3
    elif f == "extended3":
        n2 = a[0] + a[1] * L2 + a[2] * L2**2 + a[3] / L2 + a[4] / L2**2 + a[5] / L2**3 + a[6] / L2**4 + a[7] / L2**5 + a[8] / L2**6
    elif f == "herzberger":
        Lh = 1.0 / (L2 - 0.028)
        return a[0] + a[1] * Lh + a[2] * Lh**2 + a[3] * L2 + a[4] * L2**2 + a[5] * L2**3
    elif f == "sellmeier2":
        n2 = 1.0 + a[0] + a[1] * L2 / (L2 - a[2] ** 2) + a[3] / (L2 - a[4] ** 2)
    elif f == "conrady":
        return a[0] + a[1] / L + a[2] / L**3.5
    elif f == "handbook1":
        n2 = a[0] + a[1] / (L2 - a[2]) - a[3] * L2
    elif f == "handbook2":
        n2 = a[0] + a[1] * L2 / (L2 - a[2]) - a[3] * L2
    else:  # sellmeier4
        n2 = a[0] + a[1] * L2 / (L2 - a[2]) + a[3] * L2 / (L2 - a[4])
    with np.errstate(invalid="ignore"):
        return np.sqrt(n2)


def abbe_number(disp: Dispersion) -> float:
    nd = float(disp.index(LAMBDA_D))
    nF = float(disp.index(LAMBDA_F))
    nC = float(disp.index(LAMBDA_C))
    return (nd - 1.0) / (nF - nC)


def partial_dispersion_gF(disp: Dispersion) -> float:
    LAMBDA_G = 0.4358343
    nF = float(disp.index(LAMBDA_F))
    nC = float(disp.index(LAMBDA_C))
    ng = float(disp.index(LAMBDA_G))
    return (ng - nF) / (nF - nC)
