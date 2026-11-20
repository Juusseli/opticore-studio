"""Unit conversion helpers.

The engine works internally in millimetres (lengths) and micrometres
(wavelengths). Conversions are exact decimal factors; no rounding is applied.
"""

from __future__ import annotations

import math
from decimal import Decimal

LENGTH_FACTORS_TO_MM: dict[str, float] = {
    "nm": 1e-6,
    "um": 1e-3,
    "µm": 1e-3,
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "in": 25.4,
}

WAVELENGTH_FACTORS_TO_UM: dict[str, float] = {
    "nm": 1e-3,
    "um": 1.0,
    "µm": 1.0,
    "mm": 1e3,
}


class UnitError(ValueError):
    pass


def _scale(value: float, factor: float) -> float:
    """Scale by a unit factor. Power-of-ten factors shift the decimal exponent of
    the shortest round-trip representation, so 587.5618 nm -> exactly 0.5875618 um
    (plain multiplication by 1e-3 gives 0.5875617999999999)."""
    k = math.log10(factor)
    if abs(k - round(k)) < 1e-12:
        return float(Decimal(repr(float(value))).scaleb(round(k)))
    return value * factor


def length_to_mm(value: float, unit: str) -> float:
    try:
        return _scale(value, LENGTH_FACTORS_TO_MM[unit])
    except KeyError as exc:  # pragma: no cover - message path tested
        raise UnitError(f"Unknown length unit '{unit}'") from exc


def mm_to_length(value_mm: float, unit: str) -> float:
    try:
        f = LENGTH_FACTORS_TO_MM[unit]
        return _scale(value_mm, 1.0 / f)
    except KeyError as exc:
        raise UnitError(f"Unknown length unit '{unit}'") from exc


def convert_length(value: float, from_unit: str, to_unit: str) -> float:
    return mm_to_length(length_to_mm(value, from_unit), to_unit)


def wavelength_to_um(value: float, unit: str) -> float:
    try:
        return _scale(value, WAVELENGTH_FACTORS_TO_UM[unit])
    except KeyError as exc:
        raise UnitError(f"Unknown wavelength unit '{unit}'") from exc


def deg_to_rad(value: float) -> float:
    return value * math.pi / 180.0


def rad_to_deg(value: float) -> float:
    return value * 180.0 / math.pi
