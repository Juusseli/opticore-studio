"""Material catalogue: built-in data plus user-defined (project) materials."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any, Iterable

import numpy as np

from .dispersion import (
    LAMBDA_C,
    LAMBDA_D,
    LAMBDA_F,
    Dispersion,
    DispersionError,
    ThermalCoefficients,
    abbe_number,
)

AIR_NAMES = {"", "AIR"}
VACUUM_NAMES = {"VACUUM"}
MIRROR_NAME = "MIRROR"


class MaterialError(ValueError):
    pass


# catalogue information carried through from imported glass catalogues (agf.py); display only
EXTRA_KEYS = ("catalog", "status", "verified", "excluded", "agf_formula", "mil", "comment", "density", "dpgf", "tce_m30_70", "relative_cost", "internal_transmission")


@dataclass
class Material:
    name: str
    dispersion: Dispersion
    family: str = "USER"
    category: str = "glass"
    source: str = ""
    absorption_per_mm: float = 0.0  # intensity attenuation coefficient alpha (1/mm)
    nd_ref: float | None = None
    vd_ref: float | None = None
    builtin: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
    extraordinary: Dispersion | None = None  # uniaxial crystals: n_e(lambda); `dispersion` is n_o
    # extinction coefficient k(lambda) (N = n - ik): films and metals; PCHIP between the tabulated points, the end values
    # outside them (the n range decides `in_range`)
    extinction_table: tuple[tuple[float, float], ...] | None = None
    _k: Any = field(default=None, init=False, repr=False, compare=False)

    def k(self, wavelength_um: float | np.ndarray) -> float | np.ndarray:
        """Extinction coefficient k >= 0 (0 without data)."""
        L = np.asarray(wavelength_um, dtype=float)
        if not self.extinction_table:
            out = np.zeros_like(L)
            return float(out) if out.ndim == 0 else out
        if self._k is None:
            from scipy.interpolate import PchipInterpolator

            arr = np.asarray(self.extinction_table, dtype=float)
            self._k = (PchipInterpolator(arr[:, 0], arr[:, 1], extrapolate=False), float(arr[0, 0]), float(arr[-1, 0]), float(arr[0, 1]), float(arr[-1, 1]))
        f, lo, hi, k_lo, k_hi = self._k
        out = np.where(L <= lo, k_lo, np.where(L >= hi, k_hi, f(np.clip(L, lo, hi))))
        out = np.clip(np.nan_to_num(out, nan=0.0), 0.0, None)
        return float(out) if out.ndim == 0 else out

    def complex_index(self, wavelength_um: float | np.ndarray) -> complex | np.ndarray:
        """N = n - ik."""
        n = self.dispersion.index(wavelength_um)
        return n - 1j * self.k(wavelength_um)

    @property
    def absorbing(self) -> bool:
        return bool(self.extinction_table) and max(r[1] for r in self.extinction_table) > 0.0

    def index(self, wavelength_um: float) -> float:
        """Refractive index (the ordinary index of a uniaxial crystal)."""
        return float(self.dispersion.index(wavelength_um))

    @property
    def birefringent(self) -> bool:
        return self.extraordinary is not None

    def index_e(self, wavelength_um: float) -> float:
        """Extraordinary index of a uniaxial crystal."""
        if self.extraordinary is None:
            raise MaterialError(f"'{self.name}' is not birefringent")
        return float(self.extraordinary.index(wavelength_um))

    def in_range(self, wavelength_um: float) -> bool:
        return self.dispersion.in_range(wavelength_um)

    @property
    def transmittance_table(self) -> list[tuple[float, float]] | None:
        """(wavelength um, alpha 1/mm) from the catalogue internal transmittance tau over thickness d:
        alpha = -ln(tau) / d (tau floored at 1e-12), sorted by wavelength; None without data."""
        rows = self.extra.get("internal_transmission")
        if not rows:
            return None
        out = []
        for r in rows:
            try:
                lam, tau, d = float(r[0]), float(r[1]), float(r[2])
            except (TypeError, ValueError, IndexError):
                continue
            if lam > 0 and d > 0 and math.isfinite(tau) and tau >= 0:
                out.append((lam, -math.log(max(tau, 1e-12)) / d))
        return sorted(out) or None

    def catalog_absorption(self, wavelength_um: float) -> tuple[float, bool] | None:
        """Absorption coefficient alpha (1/mm) at a wavelength from the catalogue internal transmittance,
        linear in wavelength between the tabulated points; outside them the nearest end value, flagged
        (second item True). None without data."""
        t = self.transmittance_table
        if t is None:
            return None
        lams = [x[0] for x in t]
        if wavelength_um <= lams[0] or wavelength_um >= lams[-1]:
            end = t[0] if wavelength_um <= lams[0] else t[-1]
            return end[1], not math.isclose(wavelength_um, end[0], rel_tol=0, abs_tol=1e-9)
        a = float(np.interp(wavelength_um, lams, [x[1] for x in t]))
        return a, False

    @property
    def nd(self) -> float:
        return self.index(LAMBDA_D)

    @property
    def vd(self) -> float:
        return abbe_number(self.dispersion)

    def summary(self) -> dict[str, Any]:
        d = self.dispersion
        try:
            nd = self.nd
            vd = self.vd
            nF = self.index(LAMBDA_F)
            nC = self.index(LAMBDA_C)
        except DispersionError:
            nd = vd = nF = nC = float("nan")
        return {
            "name": self.name,
            "family": self.family,
            "category": self.category,
            "formula": d.formula,
            "coefficients": list(d.coefficients),
            "table": [list(r) for r in d.table] if d.table is not None else None,
            "lambda_min": d.lambda_min,
            "lambda_max": d.lambda_max if np.isfinite(d.lambda_max) else None,
            "nd": nd if np.isfinite(nd) else None,
            "vd": vd if np.isfinite(vd) else None,
            "nF_minus_nC": (nF - nC) if np.isfinite(nF) else None,
            "absorption_per_mm": self.absorption_per_mm,
            "has_thermal_model": d.thermal is not None,
            "source": self.source,
            "builtin": self.builtin,
            "nd_ref": self.nd_ref,
            "vd_ref": self.vd_ref,
            **self.extra,
            **({"extraordinary": _extraordinary_summary(self.extraordinary)} if self.extraordinary is not None else {}),
            **({"extinction_table": [list(r) for r in self.extinction_table]} if self.extinction_table else {}),
        }


def _extraordinary_summary(e: Dispersion) -> dict[str, Any]:
    try:
        ned = float(e.index(LAMBDA_D))
    except DispersionError:
        ned = float("nan")
    return {
        "formula": e.formula,
        "coefficients": list(e.coefficients),
        "lambda_min": e.lambda_min,
        "lambda_max": e.lambda_max if np.isfinite(e.lambda_max) else None,
        "ne_d": ned if np.isfinite(ned) else None,
    }


def _extraordinary_from_record(rec: dict[str, Any]) -> Dispersion | None:
    e = rec.get("extraordinary")
    if not e:
        return None
    return Dispersion(
        formula=e["formula"],
        coefficients=e.get("coefficients") or [],
        table=e.get("table"),
        lambda_min=float(e.get("lambda_min") or 0.0),
        lambda_max=float(e["lambda_max"]) if e.get("lambda_max") is not None else float("inf"),
    )


def _material_from_record(rec: dict[str, Any], builtin: bool) -> Material:
    thermal = rec.get("thermal")
    try:
        disp = Dispersion(
            formula=rec["formula"],
            coefficients=rec.get("coefficients") or [],
            table=rec.get("table"),
            lambda_min=float(rec.get("lambda_min") or 0.0),
            lambda_max=float(rec["lambda_max"]) if rec.get("lambda_max") is not None else float("inf"),
            thermal=ThermalCoefficients(**thermal) if thermal else None,
        )
        ext = _extraordinary_from_record(rec)
        ktab = _extinction_from_record(rec)
    except (KeyError, TypeError, ValueError, DispersionError) as exc:
        raise MaterialError(f"Invalid material '{rec.get('name', '?')}': {exc}") from exc
    return Material(
        name=str(rec["name"]).upper(),
        dispersion=disp,
        family=rec.get("family", "USER"),
        category=rec.get("category", "glass"),
        source=rec.get("source", ""),
        absorption_per_mm=float(rec.get("absorption_per_mm") or 0.0),
        nd_ref=rec.get("nd_ref"),
        vd_ref=rec.get("vd_ref"),
        builtin=builtin,
        extra={k: rec[k] for k in EXTRA_KEYS if k in rec},
        extraordinary=ext,
        extinction_table=ktab,
    )


def _extinction_from_record(rec: dict[str, Any]) -> tuple[tuple[float, float], ...] | None:
    rows = rec.get("extinction_table")
    if not rows:
        return None
    arr = np.asarray(rows, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 2 or len(arr) < 1:
        raise ValueError("extinction_table must be [[lambda_um, k], ...]")
    arr = arr[np.argsort(arr[:, 0])]
    if np.any(arr[:, 0] <= 0) or np.any(arr[:, 1] < 0) or np.any(np.diff(arr[:, 0]) <= 0):
        raise ValueError("extinction_table needs positive, unique wavelengths and k >= 0")
    if len(arr) == 1:  # a constant k
        arr = np.vstack([arr, [arr[0, 0] * 1.000001, arr[0, 1]]])
    return tuple((float(a), float(b)) for a, b in arr)


@lru_cache(maxsize=1)
def builtin_materials() -> dict[str, Material]:
    """Glasses and crystals (data/catalog.json) and coating materials: thin films and metals with n and k
    (data/coating_materials.json, from the refractiveindex.info database, CC0; tools/coating_materials.py)."""
    mats = {}
    for fname in ("data/catalog.json", "data/coating_materials.json"):
        raw = resources.files("opticore.materials").joinpath(fname).read_text("utf-8")
        for rec in json.loads(raw)["materials"]:
            m = _material_from_record(rec, builtin=True)
            mats[m.name] = m
    return mats


class MaterialLibrary:
    """Resolves material names for one optical system (built-ins + custom)."""

    def __init__(self, custom: Iterable[dict[str, Any]] = ()):
        self._mats: dict[str, Material] = dict(builtin_materials())
        for rec in custom:
            m = _material_from_record(rec, builtin=False)
            if m.name in AIR_NAMES | VACUUM_NAMES | {MIRROR_NAME}:
                raise MaterialError(f"'{m.name}' is a reserved material name")
            self._mats[m.name] = m  # custom definitions override built-ins

    def names(self) -> list[str]:
        return sorted(self._mats)

    def get(self, name: str) -> Material:
        key = (name or "").strip().upper()
        if key in self._mats:
            return self._mats[key]
        raise MaterialError(f"Unknown material '{name}'")

    def has(self, name: str) -> bool:
        key = (name or "").strip().upper()
        return key in AIR_NAMES or key in VACUUM_NAMES or key == MIRROR_NAME or key in self._mats

    def index(self, name: str, wavelength_um: float) -> float:
        key = (name or "").strip().upper()
        if key in AIR_NAMES or key in VACUUM_NAMES:
            return 1.0
        return self.get(key).index(wavelength_um)

    def complex_index(self, name: str, wavelength_um: float) -> complex:
        """N = n - ik (k from the material's extinction data, 0 without)."""
        key = (name or "").strip().upper()
        if key in AIR_NAMES or key in VACUUM_NAMES:
            return 1.0 + 0j
        return complex(self.get(key).complex_index(wavelength_um))

    def all(self) -> list[Material]:
        return [self._mats[k] for k in sorted(self._mats)]
