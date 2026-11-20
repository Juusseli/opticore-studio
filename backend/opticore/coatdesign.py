"""Thin-film coating design: spectral evaluation, targets, starting designs,
optimisation (refinement and needle insertion), Monte Carlo thickness errors
and a deposition recipe with optical-monitor and quartz-crystal data.

Design representation
---------------------
Layers are listed in DEPOSITION ORDER: layer 1 is deposited on the substrate,
the last layer faces the incident medium. Each layer references a palette
material (key, e.g. "H" / "L"), which is either a library material (n(lambda)
from its dispersion formula, optional extinction k) or a fixed index n - ik.
Nominal fixed indices are starting values only: production designs should
use the measured dispersion of the films from the user's own chamber (custom
materials, e.g. tabulated n(lambda)).

Spectral model: the characteristic-matrix method of thinfilm.py (Macleod),
vectorised over wavelength, coherent within the stack. Optionally the
uncoated back surface of the substrate is added incoherently (a real plate):

    T = Tf Tb / (1 - Rf' Rb),   R = Rf + Tf^2 Rb / (1 - Rf' Rb)

per polarisation, with Rf' the film reflectance seen from the substrate and
Rb, Tb the bare back surface into the incident medium (Tf' = Tf by
reciprocity). Validated in tests/test_coatdesign.py.
"""

from __future__ import annotations

import math
import time
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scipy.optimize import least_squares

from .materials import MaterialLibrary


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaletteMaterial(_M):
    key: str = Field(min_length=1, max_length=12)
    label: str = ""
    material: str = ""  # library material (dispersive); empty = fixed index
    index: float = Field(1.46, gt=0.0, le=10.0)
    extinction: float = Field(0.0, ge=0.0, le=50.0)
    tooling: float = Field(1.0, gt=0.0, le=10.0, description="tooling factor: film thickness on the part / thickness on the crystal")
    # corrections of the index, e.g. from a measurement fit: n(lambda) + index_offset + index_offset_b / lambda_um^2
    index_offset: float = Field(0.0, ge=-1.0, le=1.0)
    index_offset_b: float = Field(0.0, ge=-1.0, le=1.0, description="Cauchy B correction (um^2)")
    rate_nm_s: float = Field(0.5, gt=0.0, le=100.0, description="deposition rate (nm/s) for time estimates")


class DesignLayer(_M):
    material: str  # palette key
    thickness_nm: float = Field(ge=0.0, le=1e5)
    locked: bool = False


Quantity = Literal["R", "T", "A", "GD", "GDD", "phase", "retardance", "Rv", "Tv", "L*", "a*", "b*"]
FRACTION_Q = ("R", "T", "A", "Rv", "Tv")  # fractions 0...1
PHASE_Q = ("GD", "GDD", "phase", "retardance")  # from the complex amplitudes on the target's own grid
COLOUR_Q = ("Rv", "Tv", "L*", "a*", "b*")  # one value from the spectrum over 380-780 nm (D65, CIE 1931 2 degrees)
UNITS = {"R": "", "T": "", "A": "", "Rv": "", "Tv": "", "GD": "fs", "GDD": "fs²", "phase": "°", "retardance": "°", "L*": "", "a*": "", "b*": ""}
# Merit scale: a violation of SCALE[q] in the quantity's units weighs as much as 100 % in R, T or A; i.e. 1 % in R
# ~ 1 fs of GD ~ 10 fs² of GDD ~ 3.6° of phase ~ 1 unit of L*, a*, b*. Target weights adjust the balance.
SCALE = {"R": 1.0, "T": 1.0, "A": 1.0, "Rv": 1.0, "Tv": 1.0, "GD": 100.0, "GDD": 1000.0, "phase": 360.0, "retardance": 360.0, "L*": 100.0, "a*": 100.0, "b*": 100.0}


class Target(_M):
    """A design target. R, T, A: fractions against wavelength. GD (fs), GDD (fs²), phase (°) of the reflected or
    transmitted amplitude (`of`) and the retardance arg(rp / rs) or arg(tp / ts) (°) against wavelength. Rv, Tv
    (luminous fractions) and L*, a*, b* of the reflected or transmitted light: one value each (the wavelength range
    is not used)."""

    quantity: Quantity = "T"
    of: Literal["R", "T"] = "R"  # GD, GDD, phase, retardance, L*, a*, b*: of the reflected or the transmitted light
    polarization: Literal["avg", "s", "p"] = "avg"
    angle_deg: float = Field(0.0, ge=0.0, lt=90.0)
    lambda_min_nm: float = Field(gt=50.0, le=50000.0)
    lambda_max_nm: float = Field(gt=50.0, le=50000.0)
    value: float = Field(ge=-1e6, le=1e6)
    value_end: float | None = Field(None, ge=-1e6, le=1e6)  # linear ramp to this value at lambda_max
    kind: Literal["=", "<=", ">="] = "="
    weight: float = Field(1.0, ge=0.0)
    tolerance: float = Field(0.0, ge=0.0, le=1e6)
    points: int = Field(41, ge=1, le=801)
    # a tabulated target curve [(lambda_nm, value), ...] (e.g. imported); replaces value / value_end / points and sets
    # the wavelength range
    table: list[tuple[float, float]] | None = Field(None, max_length=20000)
    # colour targets: CIE illuminant and observer (coatanalysis.colour)
    illuminant: Literal["D65", "D50", "D55", "D75", "A", "C", "F2", "F7", "F11"] = "D65"
    observer: Literal["2", "10"] = "2"

    @model_validator(mode="after")
    def _range(self):
        if self.lambda_max_nm < self.lambda_min_nm:
            raise ValueError("Target wavelength range is reversed")
        if self.quantity in FRACTION_Q:
            for v in (self.value, self.value_end):
                if v is not None and not 0.0 <= v <= 1.0:
                    raise ValueError(f"{self.quantity} target values are fractions within 0...1")
            if self.tolerance > 1.0:
                raise ValueError(f"{self.quantity} tolerance is a fraction within 0...1")
        if self.quantity in COLOUR_Q and self.value_end is not None:
            raise ValueError(f"A {self.quantity} target has one value (no ramp)")
        if self.table is not None:
            if self.quantity in COLOUR_Q:
                raise ValueError(f"A {self.quantity} target has one value (no table)")
            if not self.table:
                raise ValueError("A tabulated target needs at least one point")
            lam = [w for w, _ in self.table]
            if any(not 50.0 < w <= 50000.0 for w in lam) or any(b <= a for a, b in zip(lam, lam[1:])):
                raise ValueError("Tabulated target wavelengths must increase within 50...50000 nm")
            if self.quantity in FRACTION_Q and any(not 0.0 <= v <= 1.0 for _, v in self.table):
                raise ValueError(f"{self.quantity} target values are fractions within 0...1")
            self.lambda_min_nm, self.lambda_max_nm = float(lam[0]), float(lam[-1])
        return self


class CoatingDesign(_M):
    name: str = "Coating design"
    incident: str = "AIR"
    incident_index: float | None = Field(None, ge=1.0, le=10.0, description="fixed, non-absorbing incident index (e.g. the glass of a cube beam splitter); overrides `incident`")
    substrate: str = "N-BK7"
    substrate_index: float | None = Field(None, gt=0.0, le=100.0, description="fixed substrate n (e.g. a metal mirror); overrides `substrate`")
    substrate_extinction: float = Field(0.0, ge=0.0, le=100.0, description="fixed substrate k")
    source_coating: str = ""  # project coating this design was opened from / saved to
    back_side: Literal["none", "uncoated", "coated"] = "none"
    # back-side coating (back_side "coated"): layers in deposition order on the back face, layer 1 on the substrate
    back_layers: list[DesignLayer] = Field(default_factory=list, max_length=400)
    # back_side "coated": the back face carries the front coating itself (a symmetric plate; optimised together)
    back_same_as_front: bool = False
    # substrate thickness: its bulk absorption in R and T and its group delay in the transmitted phase (None: neither)
    substrate_thickness_mm: float | None = Field(None, gt=0.0, le=1000.0)
    substrate_offset: float = Field(0.0, ge=-1.0, le=1.0, description="index correction of the substrate (e.g. from a fit)")
    palette: list[PaletteMaterial] = Field(min_length=1, max_length=8)
    layers: list[DesignLayer] = Field(default_factory=list, max_length=400)
    targets: list[Target] = Field(default_factory=list, max_length=40)
    design_wavelength_nm: float = Field(550.0, gt=50.0, le=50000.0)
    min_thickness_nm: float = Field(0.0, ge=0.0, le=1000.0)
    max_thickness_nm: float = Field(2000.0, gt=0.0, le=1e5)

    @model_validator(mode="after")
    def _check(self):
        keys = [p.key for p in self.palette]
        if len(set(keys)) != len(keys):
            raise ValueError("Palette keys must be unique")
        for i, L in enumerate(self.layers):
            if L.material not in keys:
                raise ValueError(f"Layer {i + 1}: material '{L.material}' is not in the palette")
        for i, L in enumerate(self.back_layers):
            if L.material not in keys:
                raise ValueError(f"Back-side layer {i + 1}: material '{L.material}' is not in the palette")
        if self.min_thickness_nm >= self.max_thickness_nm:
            raise ValueError("min_thickness_nm must be below max_thickness_nm")
        return self


class DesignError(ValueError):
    pass


# ----------------------------------------------------------------------
# Materials and spectra
# ----------------------------------------------------------------------
class Resolver:
    def __init__(self, design: CoatingDesign, custom_materials=()):
        self.d = design
        self.lib = MaterialLibrary(custom_materials)
        self.pal = {p.key: p for p in design.palette}
        self.warnings: set[str] = set()
        for p in design.palette:
            if p.material and not self.lib.has(p.material):
                raise DesignError(f"Palette material '{p.key}': unknown library material '{p.material}'")
        names = ([] if design.incident_index is not None else [design.incident]) + ([] if design.substrate_index is not None else [design.substrate])
        for nm in names:
            if not self.lib.has(nm):
                raise DesignError(f"Unknown material '{nm}'")
        if (design.incident_index is None and design.incident.strip().upper() == "MIRROR") or (design.substrate_index is None and design.substrate.strip().upper() == "MIRROR"):
            raise DesignError("For a mirror, set the substrate to a metal with n and k (fixed substrate)")
        # opaque (absorbing, semi-infinite) substrate: a mirror; nothing is transmitted. A library substrate is opaque
        # when its k at the design wavelength exceeds OPAQUE_K (a metal: light is absorbed within ~ lambda / (4 pi k))
        if design.substrate_index is not None:
            self.opaque = design.substrate_extinction > OPAQUE_K
        else:
            key = design.substrate.strip().upper()
            self.opaque = key not in ("", "AIR", "VACUUM") and float(self.lib.get(key).k(design.design_wavelength_nm * 1e-3)) > OPAQUE_K
        if design.incident_index is None and design.incident.strip().upper() not in ("", "AIR", "VACUUM"):
            if self.lib.get(design.incident).category == "metal":
                raise DesignError(f"{design.incident.upper()} is a metal: it cannot be the incident medium")
            if float(self.lib.get(design.incident).k(design.design_wavelength_nm * 1e-3)) > 1e-6:
                self.warnings.add(f"{design.incident}: the incident medium absorbs; its k is ignored (the incident medium is taken lossless)")

    def _lib_N(self, name: str, lam_nm: np.ndarray) -> np.ndarray:
        """Complex index n - ik of a library material (k from its extinction data; 0 without)."""
        lam_um = np.asarray(lam_nm, dtype=float) * 1e-3
        key = name.strip().upper()
        if key in ("", "AIR", "VACUUM"):
            return np.ones_like(lam_um) + 0j
        m = self.lib.get(key)
        out = np.asarray(m.dispersion.index(lam_um), dtype=float) - 1j * np.asarray(m.k(lam_um), dtype=float)
        if not all(m.in_range(float(x)) for x in (lam_um.min(), lam_um.max())):
            hi = f"{m.dispersion.lambda_max * 1e3:.0f}" if np.isfinite(m.dispersion.lambda_max) else "∞"
            self.warnings.add(f"{key}: n, k extrapolated beyond its data ({m.dispersion.lambda_min * 1e3:.0f}–{hi} nm)")
        return out

    def _lib_n(self, name: str, lam_nm: np.ndarray) -> np.ndarray:
        return np.real(self._lib_N(name, lam_nm))

    def N(self, key: str, lam_nm: np.ndarray) -> np.ndarray:
        p = self.pal[key]
        lam_um = np.asarray(lam_nm, dtype=float) * 1e-3
        n = self._lib_N(p.material, lam_nm) if p.material else np.full(np.shape(lam_nm), p.index, dtype=complex)
        return n + p.index_offset + p.index_offset_b / (lam_um * lam_um) - 1j * p.extinction

    def incident(self, lam_nm):
        if self.d.incident_index is not None:
            return np.full(np.shape(lam_nm), float(self.d.incident_index))
        return self._lib_n(self.d.incident, lam_nm)

    def substrate(self, lam_nm):
        if self.d.substrate_index is not None:
            base = np.full(np.shape(lam_nm), complex(self.d.substrate_index, -self.d.substrate_extinction))
        else:
            base = self._lib_N(self.d.substrate, lam_nm)
        return base + self.d.substrate_offset

    def internal_transmittance(self, lam_nm, cos_s) -> np.ndarray:
        """Bulk transmittance exp(-alpha d / cos(theta_s)) of a substrate of thickness substrate_thickness_mm (1 without
        a thickness). alpha from the substrate's k (4 pi k / lambda) or, for a catalogue glass without k data, from its
        internal transmittance (catalogue IT data, else its absorption coefficient)."""
        lam = np.asarray(lam_nm, dtype=float)
        d = self.d.substrate_thickness_mm
        if d is None or self.opaque:
            return np.ones_like(lam)
        if self.d.substrate_index is not None:
            alpha = 4 * np.pi * self.d.substrate_extinction / (lam * 1e-6)
        else:
            key = self.d.substrate.strip().upper()
            if key in ("", "AIR", "VACUUM"):
                return np.ones_like(lam)
            m = self.lib.get(key)
            if m.extinction_table:
                alpha = 4 * np.pi * np.asarray(m.k(lam * 1e-3), dtype=float) / (lam * 1e-6)
            else:
                alpha = np.array([(m.catalog_absorption(float(x) * 1e-3) or (m.absorption_per_mm, False))[0] for x in lam], dtype=float)
        return np.exp(-alpha * d / np.maximum(np.asarray(cos_s, dtype=float), 1e-6))


OPAQUE_K = 1e-3  # k above which a semi-infinite library substrate counts as opaque (a metal)


STENCIL = 3e-5  # relative frequency step of the local GD / GDD stencil (independent of the target's grid)


def stencil_grids(lam_nm: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Wavelengths at omega (1 + STENCIL) and omega (1 - STENCIL), and the step h (rad/fs), for each wavelength."""
    lam = np.asarray(lam_nm, dtype=float)
    w = 2 * np.pi * C_NM_PER_FS / lam
    h = STENCIL * w
    return 2 * np.pi * C_NM_PER_FS / (w + h), 2 * np.pi * C_NM_PER_FS / (w - h), h


def substrate_phase_terms(res: "Resolver", lam_nm: np.ndarray, sin0: float) -> tuple[np.ndarray, np.ndarray]:
    """Group delay (fs) and GDD (fs^2) of one pass through the substrate: d dk_z/domega and d d^2k_z/domega^2 with
    k_z = (omega / c) sqrt(n_s^2 - (n0 sin theta0)^2), by the local stencil at each wavelength (the phase itself,
    millions of radians, is not unwrapped)."""
    lam = np.asarray(lam_nm, dtype=float)
    d_nm = (res.d.substrate_thickness_mm or 0.0) * 1e6
    lp, lm, h = stencil_grids(lam)

    def kz(x):
        n0 = res.incident(x)
        ns = np.real(res.substrate(x))
        return 2 * np.pi / x * np.sqrt(np.clip(ns * ns - (n0 * sin0) ** 2, 0.0, None))  # rad / nm

    k0, kp, km = kz(lam), kz(lp), kz(lm)
    return d_nm * (kp - km) / (2 * h), d_nm * (kp - 2 * k0 + km) / (h * h)


def phase_derivative(a0: dict, ap: dict, am: dict, h: np.ndarray, quantity: str, of: str, polarization: str) -> np.ndarray:
    """GD = -dphi/domega (fs) or GDD = dGD/domega (fs^2) from amplitudes at omega and omega +- h (central differences of
    phase differences arg(a(omega + h) / a(omega - h)), no unwrapping)."""
    pols = ("s", "p") if polarization == "avg" else (polarization,)
    vals = []
    for pol in pols:
        k = ("r" if of == "R" else "t") + pol
        if quantity == "GD":
            vals.append(-np.angle(ap[k] / am[k]) / (2 * h))
        else:
            vals.append(-(np.angle(ap[k] / a0[k]) - np.angle(a0[k] / am[k])) / (h * h))
    return np.mean(vals, axis=0)


def plate(n0, ns, front_from_air, back_from_substrate, lam_nm, sin0, Ti, back: bool, amplitudes: bool = False) -> dict:
    """R, T (s, p) of a coated plate: the front stack coherent; with `back`, the back face (bare or coated) and the bulk
    transmittance Ti of the substrate added incoherently,
        T = Tf Ti Tb / (1 - Rf' Rb Ti^2),   R = Rf + Tf^2 Rb Ti^2 / (1 - Rf' Rb Ti^2),
    Rf' the front film seen from the substrate (Tf' = Tf by reciprocity). With amplitudes, r and t of the front face
    and t of the back face (from the substrate) are also returned (keys r*, t*, tb*)."""
    f = stack_spectral(n0, ns, front_from_air, lam_nm, sin0, amplitudes=amplitudes)
    if not back:
        return f
    nsr = np.real(ns)
    sin_s = n0 * sin0 / nsr  # Snell into the substrate
    fb = stack_spectral(nsr, n0 + 0j, list(reversed(front_from_air)), lam_nm, sin_s)
    b = stack_spectral(nsr, n0 + 0j, back_from_substrate, lam_nm, sin_s, amplitudes=amplitudes)
    out = dict(f)
    Ti2 = Ti * Ti
    for pol in ("s", "p"):
        den = 1.0 - fb["R" + pol] * b["R" + pol] * Ti2
        out["T" + pol] = f["T" + pol] * Ti * b["T" + pol] / den
        out["R" + pol] = f["R" + pol] + f["T" + pol] ** 2 * b["R" + pol] * Ti2 / den
        if amplitudes:
            out["tb" + pol] = b["t" + pol]
    return out


def _y(N, s0):
    y = np.sqrt(np.asarray(N, dtype=complex) ** 2 - s0**2)
    y = np.where(np.imag(y) > 0, -y, y)
    return np.where(np.abs(y) < 1e-300, 1e-300 + 0j, y)


def stack_spectral(n0: np.ndarray, ns: np.ndarray, layers: list[tuple[np.ndarray, float]], lam_nm: np.ndarray, sin0, amplitudes: bool = False) -> dict:
    """R, T (s, p) of a stack vs wavelength; `layers` from the incident side, each (N(lambda), d_nm).
    sin0: sine of the angle in the incident medium (scalar or per wavelength). amplitudes: also the complex r and
    t (s, p; Macleod's convention, t up to a real positive factor)."""
    n0 = np.asarray(n0, dtype=float)
    s0 = n0 * np.asarray(sin0, dtype=float)
    y0 = np.sqrt(np.clip(n0 * n0 - s0 * s0, 0.0, None)) + 0j
    Ns = np.asarray(ns, dtype=complex)
    ys = _y(Ns, s0)
    lay = [(np.asarray(N, dtype=complex), _y(N, s0), d) for N, d in layers]
    out = {}
    normal = not np.any(s0)
    for pol in ("s",) if normal else ("s", "p"):

        def eta(N, y):
            return y if pol == "s" else N * N / y

        e0 = eta(n0 + 0j, y0)
        es = eta(Ns, ys)
        m11 = np.ones_like(y0)
        m12 = np.zeros_like(y0)
        m21 = np.zeros_like(y0)
        m22 = np.ones_like(y0)
        for N, yj, dn in lay:
            ej = eta(N, yj)
            dl = 2 * np.pi * yj * dn / lam_nm
            c, sn = np.cos(dl), np.sin(dl)
            a12, a21 = 1j * sn / ej, 1j * ej * sn
            m11, m12, m21, m22 = m11 * c + m12 * a21, m11 * a12 + m12 * c, m21 * c + m22 * a21, m21 * a12 + m22 * c
        B = m11 + m12 * es
        C = m21 + m22 * es
        den = e0 * B + C
        r = (e0 * B - C) / den
        out["R" + pol] = np.abs(r) ** 2
        out["T" + pol] = np.maximum(4 * np.real(e0) * np.real(es) / np.abs(den) ** 2, 0.0)
        if amplitudes:
            out["r" + pol] = r
            out["t" + pol] = 2 * e0 / den
    if normal:  # s and p are identical at normal incidence
        out["Rp"], out["Tp"] = out["Rs"], out["Ts"]
        if amplitudes:
            out["rp"], out["tp"] = out["rs"], out["ts"]
    return out


def _cos_s(n0, ns, sin0):
    s = np.asarray(n0, dtype=float) * sin0 / np.real(ns)
    return np.sqrt(np.clip(1.0 - s * s, 0.0, None))


def spectrum(design: CoatingDesign, res: Resolver, lam_nm: np.ndarray, angle_deg: float = 0.0, layers: list[DesignLayer] | None = None, back_side: str | None = None) -> dict:
    """R, T, A (avg, s, p) of the coated part vs wavelength (light from the incident medium)."""
    lam_nm = np.asarray(lam_nm, dtype=float)
    layers = design.layers if layers is None else layers
    back_side = design.back_side if back_side is None else back_side
    sin0 = math.sin(math.radians(angle_deg))
    n0 = res.incident(lam_nm)
    ns = res.substrate(lam_nm)
    Ns_cache: dict[str, np.ndarray] = {}

    def N(key):
        if key not in Ns_cache:
            Ns_cache[key] = res.N(key, lam_nm)
        return Ns_cache[key]

    from_air = [(N(L.material), L.thickness_nm) for L in reversed(layers)]
    back = back_side in ("uncoated", "coated") and not res.opaque
    back_src = layers if design.back_same_as_front else design.back_layers
    back_layers = [(N(L.material), L.thickness_nm) for L in back_src] if back_side == "coated" else []
    Ti = res.internal_transmittance(lam_nm, _cos_s(n0, ns, sin0)) if back else 1.0
    f = plate(n0, ns, from_air, back_layers, lam_nm, sin0, Ti, back)
    out: dict[str, np.ndarray] = {k: f[k] for k in ("Rs", "Rp", "Ts", "Tp")}
    if res.opaque:  # power entering an absorbing substrate is absorbed
        out["Ts"], out["Tp"] = np.zeros_like(out["Rs"]), np.zeros_like(out["Rp"])
    for q in ("R", "T"):
        out[q] = 0.5 * (out[q + "s"] + out[q + "p"])
    for pol in ("", "s", "p"):
        out["A" + pol] = np.clip(1.0 - out["R" + pol] - out["T" + pol], 0.0, None)
    return out


# ----------------------------------------------------------------------
# Merit
# ----------------------------------------------------------------------
def _target_grid(t: Target) -> tuple[np.ndarray, np.ndarray]:
    if t.table:
        a = np.asarray(t.table, dtype=float)
        return a[:, 0], a[:, 1]
    lam = np.array([t.lambda_min_nm]) if t.points == 1 or t.lambda_max_nm == t.lambda_min_nm else np.linspace(t.lambda_min_nm, t.lambda_max_nm, t.points)
    v1 = t.value if t.value_end is None else t.value_end
    if len(lam) == 1:
        return lam, np.array([t.value])
    return lam, t.value + (v1 - t.value) * (lam - lam[0]) / (lam[-1] - lam[0])


def _key(t: Target) -> str:
    return t.quantity + ("" if t.polarization == "avg" else t.polarization)


def _colour_quantity(values, quantity: str, illuminant: str, observer: str) -> np.ndarray:
    """Rv/Tv (Y) or L*, a*, b* of spectra on coatanalysis.VIS (last axis), vectorised over leading axes."""
    from . import photometry as ph
    from .coatanalysis import VIS

    cm = ph.cmf(VIS, observer)
    E = ph.illuminant(illuminant, VIS)
    W = cm * E[:, None]
    white = W.sum(0)
    XYZ = np.asarray(values, dtype=float) @ W
    if quantity in ("Rv", "Tv"):
        return XYZ[..., 1:2] / white[1]
    d = 6 / 29
    f = np.where(XYZ / white > d**3, np.cbrt(XYZ / white), XYZ / white / (3 * d * d) + 4 / 29)
    if quantity == "L*":
        return 116 * f[..., 1:2] - 16
    if quantity == "a*":
        return 500 * (f[..., 0:1] - f[..., 1:2])
    return 200 * (f[..., 1:2] - f[..., 2:3])


def _wrap180(x):
    return (np.asarray(x) + 180.0) % 360.0 - 180.0


C_NM_PER_FS = 299.792458


def phase_quantity(amp: dict, lam_nm: np.ndarray, quantity: str, of: str, polarization: str) -> np.ndarray:
    """GD (fs), GDD (fs²), phase (°) or retardance (°) from the complex amplitudes r_s, r_p, t_s, t_p on a grid
    (Macleod's convention: GD = -dphi/domega > 0 for a delay)."""
    lam = np.asarray(lam_nm, dtype=float)
    if quantity == "retardance":
        a = "r" if of == "R" else "t"
        return np.degrees(np.angle(amp[a + "p"] / np.where(np.abs(amp[a + "s"]) > 0, amp[a + "s"], 1e-300)))
    pols = ("s", "p") if polarization == "avg" else (polarization,)
    w = 2 * np.pi * C_NM_PER_FS / lam
    order = np.argsort(w)
    vals = []
    for pol in pols:
        a = amp[("r" if of == "R" else "t") + pol]
        if quantity == "phase":
            vals.append(np.degrees(np.angle(a)))
            continue
        phi = np.empty_like(w)
        phi[order] = np.unwrap(np.angle(a[order]))
        gd = np.empty_like(w)
        gd[order] = -np.gradient(phi[order], w[order], edge_order=2)
        if quantity == "GD":
            vals.append(gd)
        else:
            gdd = np.empty_like(w)
            gdd[order] = np.gradient(gd[order], w[order], edge_order=2)
            vals.append(gdd)
    if quantity == "phase" and len(vals) == 2:  # mean of two angles
        return np.degrees(np.angle(np.exp(1j * np.radians(vals[0])) + np.exp(1j * np.radians(vals[1]))))
    return np.mean(vals, axis=0)


SATISFIED = 1e-6  # RMS merit below which the needle loop stops
MET_TOL = 1e-5  # a target is met when no sample violates it by more than 0.001 % (absolute)


SEP = "|"  # separates the front layers from the back-face layers in an optimiser's thickness list


def two_sided(d: CoatingDesign) -> bool:
    """A back face with its own coating, optimised with the front."""
    return d.back_side == "coated" and not d.back_same_as_front


def _pairs_all(d: CoatingDesign) -> tuple[list[tuple[str, float]], list[bool]]:
    """The optimiser's layer list: the front layers (deposition order) and, for a two-sided design, SEP and the back
    layers (deposition order on the back face). SEP is locked and never merged."""
    p = [(L.material, float(L.thickness_nm)) for L in d.layers]
    lk = [L.locked for L in d.layers]
    if two_sided(d):
        p += [(SEP, 0.0)] + [(L.material, float(L.thickness_nm)) for L in d.back_layers]
        lk += [True] + [L.locked for L in d.back_layers]
    return p, lk


def _with_pairs(d: CoatingDesign, pairs, locked) -> CoatingDesign:
    keys = [k for k, _ in pairs]
    if SEP in keys:
        i = keys.index(SEP)
        return d.model_copy(update={"layers": _to_layers(pairs[:i], locked[:i]), "back_layers": _to_layers(pairs[i + 1:], locked[i + 1:])})
    return d.model_copy(update={"layers": _to_layers(pairs, locked)})


class Merit:
    def __init__(self, design: CoatingDesign, res: Resolver):
        if not design.targets:
            raise DesignError("The design has no targets")
        self.d = design
        self.res = res
        from .coatanalysis import VIS

        for t in design.targets:
            if t.quantity in PHASE_Q and t.of == "T" and res.opaque:
                raise DesignError(f"{t.quantity} of the transmitted light: an opaque substrate transmits nothing")
        self.grids = [(np.array([t.lambda_min_nm]), np.array([t.value])) if t.quantity in COLOUR_Q else _target_grid(t) for t in design.targets]
        wsum = sum(t.weight for t in design.targets)
        if wsum <= 0:
            raise DesignError("All target weights are zero")
        self.w = [math.sqrt(t.weight / wsum / len(g[0])) for t, g in zip(design.targets, self.grids)]
        self.wvec = np.concatenate([np.full(len(g[0]), w) for w, g in zip(self.w, self.grids)])
        self.scale = np.concatenate([np.full(len(g[0]), SCALE[t.quantity]) for t, g in zip(design.targets, self.grids)])
        # angle groups: one spectral evaluation per angle over the union of wavelengths (colour targets: 380-780 nm)
        self.groups: dict[float, np.ndarray] = {}
        for t, (lam, _) in zip(design.targets, self.grids):
            if t.quantity in PHASE_Q:
                continue
            need = VIS if t.quantity in COLOUR_Q else lam
            self.groups[t.angle_deg] = np.unique(np.concatenate([self.groups.get(t.angle_deg, np.zeros(0)), need]))
        # phase targets: complex amplitudes on their own grid
        def mats(lam):
            return (lam, res.incident(lam), res.substrate(lam), {p.key: res.N(p.key, lam) for p in design.palette})

        self._phase = {}
        for i, (t, g) in enumerate(zip(design.targets, self.grids)):
            if t.quantity in ("GD", "GDD"):
                lp, lm, h = stencil_grids(g[0])
                self._phase[i] = (mats(g[0]), mats(lp), mats(lm), h)
            elif t.quantity in PHASE_Q:
                self._phase[i] = (mats(g[0]),)
        # cached materials per angle group
        self._N = {a: {p.key: res.N(p.key, lam) for p in design.palette} for a, lam in self.groups.items()}
        self._n0 = {a: res.incident(lam) for a, lam in self.groups.items()}
        self._ns = {a: res.substrate(lam) for a, lam in self.groups.items()}
        self._Ti = {a: res.internal_transmittance(lam, _cos_s(self._n0[a], self._ns[a], math.sin(math.radians(a)))) for a, lam in self.groups.items()}
        # transmitted phase through the plate: substrate group delay and GDD per phase target (fixed while optimising)
        self._sub_phase = {i: substrate_phase_terms(res, self.grids[i][0], math.sin(math.radians(t.angle_deg)))
                           for i, t in enumerate(design.targets) if t.quantity in ("GD", "GDD") and t.of == "T" and design.back_side != "none" and design.substrate_thickness_mm}
        self.evaluations = 0

    @staticmethod
    def _split(layers):
        """(front, back) of an optimiser layer list; back None when the list has no SEP."""
        keys = [k for k, _ in layers]
        if SEP in keys:
            i = keys.index(SEP)
            return layers[:i], layers[i + 1:]
        return layers, None

    def _back(self, layers: list[tuple[str, float]], Nk: dict) -> list:
        """The back-face stack (from the substrate outwards): the layers after SEP, the design's back layers, or the
        front layers when linked."""
        if self.d.back_side != "coated":
            return []
        front, back = self._split(layers)
        if self.d.back_same_as_front:
            return [(Nk[k], d) for k, d in front]
        if back is not None:
            return [(Nk[k], d) for k, d in back]
        return [(Nk[L.material], L.thickness_nm) for L in self.d.back_layers]

    def _spec(self, layers: list[tuple[str, float]], angle: float) -> dict:
        lam = self.groups[angle]
        Nk = self._N[angle]
        sin0 = math.sin(math.radians(angle))
        n0, ns = self._n0[angle], self._ns[angle]
        back = self.d.back_side in ("uncoated", "coated") and not self.res.opaque
        back_layers = self._back(layers, Nk)
        front = self._split(layers)[0]
        f = plate(n0, ns, [(Nk[k], d) for k, d in reversed(front)], back_layers, lam, sin0, self._Ti[angle] if back else 1.0, back)
        out = {k: f[k] for k in ("Rs", "Rp", "Ts", "Tp")}
        if self.res.opaque:
            out["Ts"], out["Tp"] = np.zeros_like(out["Rs"]), np.zeros_like(out["Rp"])
        for q in ("R", "T"):
            out[q] = 0.5 * (out[q + "s"] + out[q + "p"])
        for pol in ("", "s", "p"):
            out["A" + pol] = np.clip(1.0 - out["R" + pol] - out["T" + pol], 0.0, None)
        return out

    def _values(self, layers: list[tuple[str, float]]) -> list[np.ndarray]:
        """Each target's quantity on its grid. Thicknesses may be floats or (B, 1) arrays (a batch of designs, e.g. the
        finite-difference Jacobian): every array then has a leading batch axis."""
        from .coatanalysis import VIS

        specs = {a: self._spec(layers, a) for a in self.groups}
        if not hasattr(self, "_idx"):
            self._idx = {}
            for i, (t, (lam, _)) in enumerate(zip(self.d.targets, self.grids)):
                if t.quantity in PHASE_Q:
                    continue
                g = self.groups[t.angle_deg]
                pts = VIS if t.quantity in COLOUR_Q else lam
                idx = np.searchsorted(g, pts)
                assert np.allclose(g[np.clip(idx, 0, len(g) - 1)], pts), "target wavelengths are on the angle group's grid"
                self._idx[i] = idx
        out = []
        for i, (t, (lam, _)) in enumerate(zip(self.d.targets, self.grids)):
            if t.quantity in PHASE_Q:
                through = t.of == "T" and self.d.back_side != "none" and not self.res.opaque
                sin0 = math.sin(math.radians(t.angle_deg))

                def amp_at(m):
                    lam_g, n0, ns, Nk = m
                    back_layers = self._back(layers, Nk)
                    front = self._split(layers)[0]
                    a = plate(n0, ns, [(Nk[k], d) for k, d in reversed(front)], back_layers, lam_g, sin0, 1.0, through, amplitudes=True)
                    if through:  # the directly transmitted wave: front face, then back face (one pass through the plate)
                        a = dict(a, ts=a["ts"] * a["tbs"], tp=a["tp"] * a["tbp"])
                    return a

                st = self._phase[i]
                if t.quantity in ("GD", "GDD"):
                    v = phase_derivative(amp_at(st[0]), amp_at(st[1]), amp_at(st[2]), st[3], t.quantity, t.of, t.polarization)
                    if i in self._sub_phase:
                        v = v + self._sub_phase[i][0 if t.quantity == "GD" else 1]
                else:
                    v = phase_quantity(amp_at(st[0]), lam, t.quantity, t.of, t.polarization)
                out.append(v)
            elif t.quantity in COLOUR_Q:
                src = "R" if t.quantity == "Rv" else "T" if t.quantity == "Tv" else t.of
                key = src + ("" if t.polarization == "avg" else t.polarization)
                out.append(_colour_quantity(specs[t.angle_deg][key][..., self._idx[i]], t.quantity, t.illuminant, t.observer))
            else:
                out.append(specs[t.angle_deg][_key(t)][..., self._idx[i]])
        return out

    def residuals_batch(self, X: np.ndarray, pairs: list[tuple[str, float]], free: list[int]) -> np.ndarray:
        """Residual vectors of a batch of designs: row b sets the free layers' thicknesses to X[b] (B x len(free))."""
        X = np.asarray(X, dtype=float)
        layers = [(k, X[:, free.index(j)][:, None] if j in free else d) for j, (k, d) in enumerate(pairs)]
        parts = []
        for t, (lam, tv), w, v in zip(self.d.targets, self.grids, self.w, self._values(layers)):
            v = np.broadcast_to(v, (len(X),) + np.shape(v)[-1:])
            parts.append(w * self._error(t, v, tv) / SCALE[t.quantity])
        self.evaluations += len(X)
        return np.concatenate(parts, axis=-1)

    @staticmethod
    def _error(t: Target, v: np.ndarray, tv: np.ndarray) -> np.ndarray:
        """Signed violation beyond the tolerance band (0 where the target is satisfied), in the quantity's units."""
        e = v - tv
        if t.quantity in ("phase", "retardance"):
            e = _wrap180(e)
        if t.kind == "=":
            return np.sign(e) * np.maximum(np.abs(e) - t.tolerance, 0.0)
        if t.kind == "<=":
            return np.maximum(e - t.tolerance, 0.0)
        return np.minimum(e + t.tolerance, 0.0)

    def residuals(self, layers: list[tuple[str, float]]) -> np.ndarray:
        self.evaluations += 1
        parts = []
        for t, (lam, tv), w, v in zip(self.d.targets, self.grids, self.w, self._values(layers)):
            parts.append(w * self._error(t, v, tv) / SCALE[t.quantity])
        return np.concatenate(parts)

    def value(self, layers) -> float:
        r = self.residuals(layers)
        return float(math.sqrt(np.sum(r * r)))

    def breakdown(self, layers) -> list[dict]:
        out = []
        for t, (lam, tv), v in zip(self.d.targets, self.grids, self._values(layers)):
            viol = np.abs(self._error(t, v, tv))
            out.append(
                {
                    "quantity": t.quantity,
                    "units": UNITS[t.quantity],
                    "lambda_nm": lam.tolist(),
                    "target": tv.tolist(),
                    "value": v.tolist(),
                    "rms_violation": float(np.sqrt(np.mean(viol**2))),
                    "max_violation": float(viol.max()),
                    "met": bool(viol.max() <= MET_TOL * SCALE[t.quantity]),
                    "mean": float(v.mean()),
                    "min": float(v.min()),
                    "max": float(v.max()),
                }
            )
        return out


def _pairs(layers: list[DesignLayer]) -> list[tuple[str, float]]:
    return [(L.material, float(L.thickness_nm)) for L in layers]


def _to_layers(pairs: list[tuple[str, float]], locked: list[bool] | None = None) -> list[DesignLayer]:
    locked = locked or [False] * len(pairs)
    return [DesignLayer(material=k, thickness_nm=float(d), locked=bool(lk)) for (k, d), lk in zip(pairs, locked)]


def merge_and_clean(pairs: list[tuple[str, float]], locked: list[bool], min_nm: float, drop_nm: float = 1e-3):
    """Remove layers thinner than max(min_nm, drop_nm) (unless locked) and merge equal neighbours."""
    lim = max(min_nm, drop_nm)
    keep = [(k, d, lk) for (k, d), lk in zip(pairs, locked) if lk or d >= lim]
    out: list[list] = []
    for k, d, lk in keep:
        if out and out[-1][0] == k and not lk and not out[-1][2]:
            out[-1][1] += d
        else:
            out.append([k, d, lk])
    return [(k, d) for k, d, _ in out], [lk for _, _, lk in out]


# ----------------------------------------------------------------------
# Optimisation
# ----------------------------------------------------------------------


class _Satisfied(Exception):
    pass


def refine(design: CoatingDesign, res: Resolver, max_evaluations: int = 4000, deadline: float | None = None) -> tuple[list[tuple[str, float]], list[bool], dict]:
    """Bounded least squares on the unlocked thicknesses (both faces of a two-sided design); returns the optimiser
    layer list (front, SEP, back), its locks and a summary."""
    pairs, locked = _pairs_all(design)
    mf = Merit(design, res)
    m0 = mf.value(pairs)
    free = [i for i, lk in enumerate(locked) if not lk]
    if not free:
        return pairs, locked, {"initial": m0, "final": m0, "evaluations": mf.evaluations, "status": "no free layers"}
    lo, hi = design.min_thickness_nm, design.max_thickness_nm
    x0 = np.clip(np.array([pairs[i][1] for i in free]), lo, hi)

    def build(x):
        p = list(pairs)
        for j, i in enumerate(free):
            p[i] = (p[i][0], float(x[j]))
        return p

    best = {"m": m0 * m0, "x": x0.copy()}

    def fun(x):
        if deadline is not None and time.time() > deadline:
            raise TimeoutError
        r = mf.residuals(build(x))
        m = float(r @ r)
        if m < best["m"]:  # keep the best point seen (a time limit must not lose progress)
            best["m"], best["x"] = m, np.array(x, dtype=float)
        live = mf.wvec > 0
        if not np.any(np.abs(r[live]) / mf.wvec[live] > MET_TOL):  # every sample within MET_TOL (x SCALE in its units)
            raise _Satisfied
        return r

    def jac(x):
        # forward differences of all free thicknesses in one batched evaluation (the stack is computed for every
        # perturbed design at once), steps of 1e-4 max(|x|, 1)
        h = 1e-4 * np.maximum(np.abs(x), 1.0)
        X = np.vstack([x[None, :], x[None, :] + np.diag(h)])
        R = mf.residuals_batch(X, pairs, free)
        return ((R[1:] - R[0]) / h[:, None]).T

    status = "converged"
    try:
        r = least_squares(fun, x0, jac=jac, bounds=(np.full(len(x0), lo), np.full(len(x0), hi)), method="trf", x_scale=np.maximum(x0, 10.0), max_nfev=max(50, max_evaluations // max(1, len(free))))
        x = r.x if float(r.fun @ r.fun) <= best["m"] else best["x"]
        status = r.message
    except _Satisfied:
        x = best["x"]
        status = "targets met"
    except TimeoutError:
        x = best["x"]
        status = "time limit reached (best design so far kept)"
    best = build(x)
    m1 = mf.value(best)
    if m1 > m0:  # never return a worse design
        best, m1 = pairs, m0
    return best, locked, {"initial": m0, "final": m1, "evaluations": mf.evaluations, "status": status}


def needle_candidates(design: CoatingDesign, res: Resolver, pairs, locked, delta_nm: float = 0.2, positions: int = 15, keep: int = 5) -> list:
    """Needle insertions that lower the merit, best first: [(new pairs, new locked, gain)]. A 0.2 nm layer of every other
    palette material at `positions` places inside every unlocked layer and at both outer interfaces probes the needle
    function (the merit derivative for an infinitesimal new layer); one candidate per layer and outer interface."""
    mf = Merit(design, res)
    m0 = mf.value(pairs)
    keys = [p.key for p in design.palette]
    found: dict = {}
    for j, (k, d) in enumerate(pairs):
        if locked[j]:
            continue
        for f in np.linspace(0.0, 1.0, positions + 2)[1:-1] if d > 2 * delta_nm else [0.5]:
            for km in keys:
                if km == k:
                    continue
                cand = pairs[:j] + [(k, d * f), (km, delta_nm), (k, d * (1 - f))] + pairs[j + 1 :]
                m = mf.value(cand)
                if m < m0 and (j not in found or m < found[j][0]):
                    found[j] = (m, cand, locked[:j] + [False, False, False] + locked[j + 1 :])
    # needles at the outer interfaces: towards the medium and towards the substrate (on both faces of a two-sided design)
    slots = [0, len(pairs)]
    if SEP in [k for k, _ in pairs]:
        i = [k for k, _ in pairs].index(SEP)
        slots += [i, i + 1]
    for at, km in [(a, km) for a in slots for km in keys]:
        cand, lk = pairs[:at] + [(km, delta_nm)] + pairs[at:], locked[:at] + [False] + locked[at:]
        m = mf.value(cand)
        if m < m0 and (("slot", at) not in found or m < found[("slot", at)][0]):
            found[("slot", at)] = (m, cand, lk)
    ranked = sorted(found.values(), key=lambda c: c[0])[:keep]
    return [(c[1], c[2], m0 - c[0]) for c in ranked]


def needle_step(design: CoatingDesign, res: Resolver, pairs, locked, delta_nm: float = 0.2, positions: int = 15):
    """Best single needle insertion: (new pairs, new locked, gain) or None."""
    c = needle_candidates(design, res, pairs, locked, delta_nm, positions, keep=1)
    return c[0] if c else None


def evolution_candidates(design: CoatingDesign, res: Resolver, pairs, locked) -> list:
    """Gradual evolution: quarter waves at the design wavelength of two different palette materials added at the incident
    side and at the substrate side (new layers the refinement can then shape)."""
    keys = [p.key for p in design.palette]
    lam0 = np.array([design.design_wavelength_nm])
    qw = {k: design.design_wavelength_nm / (4.0 * max(float(np.real(res.N(k, lam0))[0]), 0.05)) for k in keys}
    qw[SEP] = 0.0
    out = []
    ks = [k for k, _ in pairs]
    sep = ks.index(SEP) if SEP in ks else None
    for a in keys:
        for b in keys:
            if a == b:
                continue
            out.append(([(a, qw[a]), (b, qw[b])] + pairs, [False, False] + locked))  # front, incident side
            if sep is None:
                out.append((pairs + [(a, qw[a]), (b, qw[b])], locked + [False, False]))  # front, substrate side
            else:
                out.append((pairs[:sep] + [(a, qw[a]), (b, qw[b])] + pairs[sep:], locked[:sep] + [False, False] + locked[sep:]))  # front, substrate side
                out.append((pairs + [(b, qw[b]), (a, qw[a])], locked + [False, False]))  # back face, outer side
    return out


def optimize_design(design: CoatingDesign, custom_materials=(), method: Literal["refine", "needle"] = "refine", max_needles: int = 40, time_limit_s: float = 30.0) -> dict:
    t0 = time.time()
    deadline = t0 + time_limit_s
    res = Resolver(design, custom_materials)
    mf = Merit(design, res)
    pa, la = _pairs_all(design)
    m_initial = mf.value(pa)
    history = [{"step": "start", "merit": m_initial, "layers": len(pa) - (1 if SEP in [k for k, _ in pa] else 0)}]
    # merge equal neighbours first (identical optics, fewer variables)
    p0, l0 = merge_and_clean(pa, la, 0.0, drop_nm=0.0)
    start = _with_pairs(design, p0, l0)
    pairs, locked, info = refine(start, res, deadline=deadline)
    pairs, locked = merge_and_clean(pairs, locked, design.min_thickness_nm)
    cur = _with_pairs(start, pairs, locked)
    history.append({"step": "refine", "merit": Merit(cur, res).value(pairs), "layers": len(pairs)})
    status = info["status"]
    if method == "needle":
        for _ in range(max_needles):
            if history[-1]["merit"] < SATISFIED:
                status = "all targets met"
                break
            if time.time() > deadline:
                status = "time limit reached"
                break
            # the best needles first; when none of them grows, gradual evolution (new quarter-wave pairs at either side)
            improved = False
            for step, cands in (("needle", needle_candidates(cur, res, pairs, locked)), ("evolution", None)):
                if cands is None:
                    cands = [(p2, l2, 0.0) for p2, l2 in evolution_candidates(cur, res, pairs, locked)]
                for p2, l2, _gain in cands:
                    if time.time() > deadline:
                        break
                    trial = _with_pairs(cur, p2, l2)
                    p3, l3, info = refine(trial, res, deadline=deadline)
                    p3, l3 = merge_and_clean(p3, l3, design.min_thickness_nm)
                    m3 = Merit(trial, res).value(p3)
                    if m3 < history[-1]["merit"] * (1 - 1e-9) and len(p3) <= 400:
                        pairs, locked = p3, l3
                        cur = _with_pairs(trial, pairs, locked)
                        history.append({"step": step, "merit": m3, "layers": len(pairs)})
                        improved = True
                        break
                if improved:
                    break
            if not improved:
                status = "time limit reached" if time.time() > deadline else "no needle or new layer pair improves the merit"
                break
        # needle seeds that did not grow (< 1 nm) are not depositable: drop them and refine once more
        if any(d < max(1.0, design.min_thickness_nm) and not lk for (_, d), lk in zip(pairs, locked)):
            pc, lc = merge_and_clean(pairs, locked, design.min_thickness_nm, drop_nm=1.0)
            trial = _with_pairs(cur, pc, lc)
            pc, lc, _ = refine(trial, res, deadline=deadline + 5.0)
            pc, lc = merge_and_clean(pc, lc, design.min_thickness_nm, drop_nm=1.0)
            mc = Merit(trial, res).value(pc)
            prev = history[-1]["merit"]
            met_before = all(b["met"] for b in Merit(cur, res).breakdown(pairs))
            met_after = all(b["met"] for b in Merit(trial, res).breakdown(pc))
            if met_before and not met_after:  # one more, longer refinement of the depositable design
                t2 = _with_pairs(trial, pc, lc)
                pc2, lc2, _ = refine(t2, res, max_evaluations=40000, deadline=time.time() + 15.0)
                pc2, lc2 = merge_and_clean(pc2, lc2, design.min_thickness_nm, drop_nm=1.0)
                if all(b["met"] for b in Merit(trial, res).breakdown(pc2)):
                    pc, lc, mc, met_after = pc2, lc2, Merit(trial, res).value(pc2), True
            # depositable layers are worth a little merit, but never the loss of targets that were met
            if mc <= max(prev * 1.5, prev + 1e-4) and (met_after or not met_before):
                pairs, locked = pc, lc
                cur = _with_pairs(trial, pairs, locked)
                history.append({"step": "remove < 1 nm", "merit": mc, "layers": len(pairs)})
    final = Merit(cur, res).value(pairs)
    if final > m_initial:  # never return a worse design than the one given
        cur, final, status = design, m_initial, status + " (original design kept: no improvement)"
    return {
        "design": cur.model_dump(),
        "initial_merit": m_initial,
        "final_merit": final,
        "history": history,
        "status": status,
        "elapsed_s": time.time() - t0,
        "warnings": sorted(res.warnings),
        "method": "Bounded least squares (SciPy trust-region reflective) on the target residuals" + (", with needle insertion (the five most negative needle-function positions, probed with a 0.2 nm layer of another palette material at 15 positions per layer and at both outer interfaces, each refined until one improves) and gradual evolution (quarter-wave pairs added at either side) when no needle helps" if method == "needle" else ""),
    }


# ----------------------------------------------------------------------
# Evaluation summary
# ----------------------------------------------------------------------
def evaluate_design(design: CoatingDesign, custom_materials=(), lambda_min_nm: float | None = None, lambda_max_nm: float | None = None, samples: int = 401, angle_deg: float = 0.0) -> dict:
    res = Resolver(design, custom_materials)
    lams = [t.lambda_min_nm for t in design.targets] + [t.lambda_max_nm for t in design.targets]
    lo = lambda_min_nm or (min(lams) * 0.85 if lams else design.design_wavelength_nm * 0.6)
    hi = lambda_max_nm or (max(lams) * 1.15 if lams else design.design_wavelength_nm * 1.6)
    lam = np.linspace(lo, hi, samples)
    sp = spectrum(design, res, lam, angle_deg)
    lam0 = np.array([design.design_wavelength_nm])
    layers = []
    z = 0.0
    for i, L in enumerate(design.layers):
        n0 = complex(res.N(L.material, lam0)[0])
        z += L.thickness_nm
        layers.append({"index": i + 1, "material": L.material, "thickness_nm": L.thickness_nm, "n_design": n0.real, "k_design": -n0.imag, "qwot": 4 * n0.real * L.thickness_nm / design.design_wavelength_nm, "cumulative_nm": z, "locked": L.locked})
    out = {
        "lambda_nm": lam.tolist(),
        "angle_deg": angle_deg,
        "spectrum": {k: sp[k].tolist() for k in ("R", "T", "A", "Rs", "Rp", "Ts", "Tp")},
        "layers": layers,
        "total_thickness_nm": z,
        "layer_count": len(design.layers),
        "substrate_n_design": float(np.real(res.substrate(lam0))[0]),
        "incident_n_design": float(np.real(res.incident(lam0))[0]),
        "merit": None,
        "targets": [],
        "warnings": [],
    }
    if design.targets:
        mf = Merit(design, res)
        pairs = _pairs(design.layers)
        out["merit"] = mf.value(pairs)
        out["targets"] = mf.breakdown(pairs)
    out["formula"] = to_formula(design, custom_materials) if design.layers else ""
    thin = [i + 1 for i, L in enumerate(design.layers) if 0 < L.thickness_nm < 5.0]
    if thin:
        out["warnings"].append(f"Layers {', '.join(map(str, thin))} are thinner than 5 nm: hard to deposit reproducibly")
    out["warnings"] += sorted(res.warnings)
    out["method"] = ("Characteristic-matrix thin-film calculation vs wavelength (coherent stack, isotropic layers, N = n - ik)"
                     + ({"uncoated": "; uncoated back surface added incoherently", "coated": "; back-side coating added incoherently"}.get(design.back_side, ""))
                     + (f"; bulk absorption of a {design.substrate_thickness_mm:g} mm substrate" if design.substrate_thickness_mm and design.back_side != "none" else ""))
    out["back_formula"] = to_formula(design.model_copy(update={"layers": design.back_layers}), custom_materials) if design.back_layers else ""
    out["opaque_substrate"] = bool(res.opaque)
    return out


# ----------------------------------------------------------------------
# Starting designs
# ----------------------------------------------------------------------
TemplateKind = Literal["ar_broadband", "v_coat", "hr", "longpass", "shortpass", "bandpass", "notch", "beamsplitter", "enhanced_mirror", "protected_mirror"]


def stopband_halfwidth(nH: float, nL: float) -> float:
    """Half width of the first-order stop band of a quarter-wave stack in g = lambda0 / lambda units."""
    return (2 / math.pi) * math.asin((nH - nL) / (nH + nL))


def template(design: CoatingDesign, kind: TemplateKind, custom_materials=(), high: str = "H", low: str = "L", pairs: int = 8, lambda0_nm: float | None = None, edge_nm: float | None = None, band_min_nm: float | None = None, band_max_nm: float | None = None, cavities: int = 1) -> dict:
    """Classical starting design and matching targets (returned as a new design; layers in deposition order)."""
    res = Resolver(design, custom_materials)
    keys = [p.key for p in design.palette]
    for k in (high, low):
        if k not in keys:
            raise DesignError(f"Palette has no material '{k}'")

    def n(k, lam):
        return float(np.real(res.N(k, np.array([lam]))[0]))

    def qw(k, lam):
        return lam / (4 * n(k, lam))

    lam0 = lambda0_nm or design.design_wavelength_nm
    nH, nL = n(high, lam0), n(low, lam0)
    if nH <= nL:
        raise DesignError(f"'{high}' must have a higher index than '{low}' at {lam0:g} nm")
    L: list[tuple[str, float]] = []  # deposition order
    T: list[dict] = []
    if kind == "ar_broadband":
        a, b = band_min_nm or lam0 * 0.8, band_max_nm or lam0 * 1.2
        lam0 = math.sqrt(a * b)
        L = [(high, qw(high, lam0) * 0.5), (low, qw(low, lam0) * 0.5), (high, qw(high, lam0)), (low, qw(low, lam0))]
        T = [{"quantity": "R", "lambda_min_nm": a, "lambda_max_nm": b, "value": 0.0, "kind": "<=", "tolerance": 0.002, "points": 61}]
    elif kind == "v_coat":
        L = [(high, qw(high, lam0) * 0.6), (low, qw(low, lam0))]
        T = [{"quantity": "R", "lambda_min_nm": lam0, "lambda_max_nm": lam0, "value": 0.0, "points": 1}]
    elif kind == "hr":
        L = [(high, qw(high, lam0)), (low, qw(low, lam0))] * pairs + [(high, qw(high, lam0))]
        dg = stopband_halfwidth(nH, nL)
        a, b = band_min_nm or lam0 / (1 + 0.6 * dg), band_max_nm or lam0 / (1 - 0.6 * dg)
        T = [{"quantity": "R", "lambda_min_nm": a, "lambda_max_nm": b, "value": 0.995, "kind": ">=", "points": 41}]
    elif kind in ("longpass", "shortpass"):
        edge = edge_nm or lam0
        dg = stopband_halfwidth(nH, nL)
        if kind == "longpass":  # reflect short, transmit long: long edge of the stop band at the edge
            lc = edge * (1 - dg)
            unit = [(low, qw(low, lc) / 2), (high, qw(high, lc)), (low, qw(low, lc) / 2)]
            T = [
                {"quantity": "T", "lambda_min_nm": lc / (1 + 0.8 * dg), "lambda_max_nm": edge * 0.97, "value": 0.01, "kind": "<=", "points": 41},
                {"quantity": "T", "lambda_min_nm": edge * 1.04, "lambda_max_nm": min(edge * 1.5, lc / (1 - dg) * 1.9), "value": 0.95, "kind": ">=", "points": 61},
            ]
        else:  # transmit short, reflect long
            lc = edge * (1 + dg)
            unit = [(high, qw(high, lc) / 2), (low, qw(low, lc)), (high, qw(high, lc) / 2)]
            T = [
                {"quantity": "T", "lambda_min_nm": edge * 1.03, "lambda_max_nm": lc / (1 - 0.8 * dg), "value": 0.01, "kind": "<=", "points": 41},
                {"quantity": "T", "lambda_min_nm": max(edge * 0.7, lc / (1 + dg) / 1.6), "lambda_max_nm": edge * 0.96, "value": 0.95, "kind": ">=", "points": 61},
            ]
        L = unit * pairs
    elif kind == "bandpass":
        mirror = [(high, qw(high, lam0)), (low, qw(low, lam0))] * pairs + [(high, qw(high, lam0))]
        cav = mirror + [(low, 2 * qw(low, lam0))] + list(reversed(mirror))
        L = list(cav)
        for _ in range(max(1, cavities) - 1):
            L = L + [(low, qw(low, lam0))] + cav
        dg = stopband_halfwidth(nH, nL)
        hw = band_max_nm - band_min_nm if (band_min_nm and band_max_nm) else lam0 * 0.01
        T = [
            {"quantity": "T", "lambda_min_nm": lam0 - hw / 4, "lambda_max_nm": lam0 + hw / 4, "value": 0.9, "kind": ">=", "points": 11},
            {"quantity": "T", "lambda_min_nm": lam0 / (1 + 0.7 * dg), "lambda_max_nm": lam0 - 3 * hw, "value": 0.01, "kind": "<=", "points": 31},
            {"quantity": "T", "lambda_min_nm": lam0 + 3 * hw, "lambda_max_nm": lam0 / (1 - 0.7 * dg), "value": 0.01, "kind": "<=", "points": 31},
        ]
    elif kind == "notch":
        L = [(high, qw(high, lam0)), (low, qw(low, lam0))] * pairs + [(high, qw(high, lam0))]
        dg = stopband_halfwidth(nH, nL)
        a, b = band_min_nm or lam0 / (1 + 0.5 * dg), band_max_nm or lam0 / (1 - 0.5 * dg)
        T = [
            {"quantity": "T", "lambda_min_nm": a, "lambda_max_nm": b, "value": 0.01, "kind": "<=", "points": 31},
            {"quantity": "T", "lambda_min_nm": lam0 / (1 + 2.2 * dg), "lambda_max_nm": lam0 / (1 + 1.6 * dg), "value": 0.9, "kind": ">=", "points": 21},
            {"quantity": "T", "lambda_min_nm": lam0 / (1 - 1.6 * dg), "lambda_max_nm": min(lam0 / (1 - 2.2 * dg), lam0 * 1.9), "value": 0.9, "kind": ">=", "points": 21},
        ]
    elif kind in ("enhanced_mirror", "protected_mirror"):
        if not res.opaque:
            raise DesignError("Metal-mirror designs need a fixed substrate with extinction k > 0 (the metal)")
        a, b = band_min_nm or lam0 * 0.8, band_max_nm or lam0 * 1.25
        if kind == "protected_mirror":  # half-wave low-index overcoat: absentee at lambda0
            L = [(low, 2 * qw(low, lam0))]
        else:  # (L H)^N quarter waves on the metal, low index first
            L = [(low, qw(low, lam0)), (high, qw(high, lam0))] * max(1, pairs)
        trial = design.model_copy(update={"layers": _to_layers(L)})
        lam_b = np.linspace(a, b, 41)
        Rb = spectrum(trial, res, lam_b)["R"]
        T = [{"quantity": "R", "lambda_min_nm": a, "lambda_max_nm": b, "value": round(float(min(0.999, Rb.min())), 3), "kind": ">=", "points": 41}]
    elif kind == "beamsplitter":
        a, b = band_min_nm or lam0 * 0.85, band_max_nm or lam0 * 1.15
        L = [(high, qw(high, lam0)), (low, qw(low, lam0)), (high, qw(high, lam0))]
        T = [{"quantity": "R", "angle_deg": 45.0, "lambda_min_nm": a, "lambda_max_nm": b, "value": 0.5, "tolerance": 0.02, "points": 41}]
    else:
        raise DesignError(f"Unknown template '{kind}'")
    new = design.model_copy(update={"layers": _to_layers(L), "targets": [Target(**t) for t in T], "design_wavelength_nm": lam0})
    return {"design": new.model_dump(), "notes": [f"Indices at {lam0:g} nm: {high} = {nH:.4f}, {low} = {nL:.4f}"]}


# ----------------------------------------------------------------------
# Monte Carlo thickness errors
# ----------------------------------------------------------------------
def monte_carlo(design: CoatingDesign, custom_materials=(), sigma_rel: float = 0.01, sigma_abs_nm: float = 0.0, runs: int = 200, seed: int = 1, samples: int = 201) -> dict:
    if not (0 <= sigma_rel <= 0.5 and 0 <= sigma_abs_nm <= 100 and 1 <= runs <= 5000):
        raise DesignError("sigma_rel 0…0.5, sigma_abs_nm 0…100 and runs 1…5000 required")
    res = Resolver(design, custom_materials)
    rng = np.random.default_rng(seed)
    pairs = _pairs(design.layers)
    mf = Merit(design, res) if design.targets else None
    lams = [t.lambda_min_nm for t in design.targets] + [t.lambda_max_nm for t in design.targets]
    lo = min(lams) * 0.85 if lams else design.design_wavelength_nm * 0.6
    hi = max(lams) * 1.15 if lams else design.design_wavelength_nm * 1.6
    lam = np.linspace(lo, hi, samples)
    qty = design.targets[0].quantity if design.targets else "T"
    curves = []
    merits = []
    met = 0
    for _ in range(runs):
        pert = [(k, max(0.0, d * (1 + sigma_rel * rng.standard_normal()) + sigma_abs_nm * rng.standard_normal())) for k, d in pairs]
        sp = spectrum(design, res, lam, 0.0, _to_layers(pert))
        curves.append(sp[qty])
        if mf is not None:
            merits.append(mf.value(pert))
            met += all(b["met"] for b in mf.breakdown(pert))
    C = np.array(curves)
    nominal = spectrum(design, res, lam, 0.0)[qty]
    return {
        "lambda_nm": lam.tolist(),
        "quantity": qty,
        "nominal": nominal.tolist(),
        "p05": np.percentile(C, 5, axis=0).tolist(),
        "p50": np.percentile(C, 50, axis=0).tolist(),
        "p95": np.percentile(C, 95, axis=0).tolist(),
        "merit": None if mf is None else {"nominal": mf.value(pairs), "mean": float(np.mean(merits)), "p95": float(np.percentile(merits, 95))},
        "yield": None if mf is None else met / runs,
        "settings": {"sigma_rel": sigma_rel, "sigma_abs_nm": sigma_abs_nm, "runs": runs, "seed": seed},
        "method": "Independent Gaussian thickness errors per layer (relative and absolute), normal incidence spectra; yield = fraction of runs meeting every target",
    }


# ----------------------------------------------------------------------
# Deposition recipe
# ----------------------------------------------------------------------
def recipe(design: CoatingDesign, custom_materials=(), monitor_wavelength_nm: float | None = None, monitor: Literal["T", "R"] = "T", samples_per_layer: int = 60, monitor_back_side: Literal["none", "uncoated"] = "uncoated") -> dict:
    """Layer-by-layer recipe in deposition order with optical-monitor and crystal data.

    Optical monitor: direct monitoring on the part (substrate as witness), at
    normal incidence and the monitor wavelength, through the plate (uncoated
    back surface added incoherently unless monitor_back_side = "none"); for each layer the signal
    while it grows on the previous layers, its value at the start and end
    (termination level), the turning points inside the layer and whether the
    layer ends on a turning point (QWOT a multiple of one at the monitor
    wavelength). Crystal: thickness on the crystal = film thickness / tooling
    factor. Time = thickness / rate.
    """
    if not design.layers:
        raise DesignError("The design has no layers")
    res = Resolver(design, custom_materials)
    pre_warn = []
    if res.opaque:
        if monitor == "T":
            pre_warn.append("Opaque (metal) substrate: transmission cannot be monitored; the recipe uses reflectance monitoring")
            monitor = "R"
        monitor_back_side = "none"
    lm = float(monitor_wavelength_nm or design.design_wavelength_nm)
    lam = np.array([lm])
    pal = {p.key: p for p in design.palette}
    rows = []
    curves = []
    z0 = 0.0
    total_time = 0.0
    for i, L in enumerate(design.layers):
        below = design.layers[:i]
        ds = np.linspace(0.0, L.thickness_nm, max(2, samples_per_layer))
        sig = np.array([float(spectrum(design, res, lam, 0.0, below + [DesignLayer(material=L.material, thickness_nm=float(d))], back_side=monitor_back_side)[monitor][0]) for d in ds])
        inner = sig[1:-1]
        tp = int(np.sum((inner > sig[:-2]) & (inner > sig[2:])) + np.sum((inner < sig[:-2]) & (inner < sig[2:])))
        Nn = complex(res.N(L.material, lam)[0])
        qwot_m = 4 * Nn.real * L.thickness_nm / lm
        n0d = complex(res.N(L.material, np.array([design.design_wavelength_nm]))[0]).real
        p = pal[L.material]
        t_s = L.thickness_nm / p.rate_nm_s
        total_time += t_s
        on_tp = abs(qwot_m - round(qwot_m)) < 0.02 and round(qwot_m) >= 1
        rows.append(
            {
                "layer": i + 1,
                "material": L.material,
                "material_name": p.label or p.material or f"n = {p.index:g}",
                "thickness_nm": L.thickness_nm,
                "qwot_design": 4 * n0d * L.thickness_nm / design.design_wavelength_nm,
                "qwot_monitor": qwot_m,
                "n_monitor": Nn.real,
                "cumulative_nm": z0 + L.thickness_nm,
                "monitor_start": float(sig[0]),
                "monitor_end": float(sig[-1]),
                "turning_points": tp,
                "termination": "turning point" if on_tp else "level",
                "crystal_nm": L.thickness_nm / p.tooling,
                "crystal_kA": L.thickness_nm / p.tooling / 100.0,
                "rate_nm_s": p.rate_nm_s,
                "time_s": t_s,
            }
        )
        curves.append({"layer": i + 1, "thickness_nm": (z0 + ds).tolist(), "signal": sig.tolist()})
        z0 += L.thickness_nm
    warnings = []
    flat = [r["layer"] for r in rows if r["termination"] == "level" and abs(r["monitor_end"] - r["monitor_start"]) < 0.005]
    if flat:
        warnings.append(f"Layers {', '.join(map(str, flat))} change the monitor signal by < 0.5 %: hard to terminate optically at {lm:g} nm (use the crystal or another monitor wavelength)")
    return {
        "name": design.name,
        "substrate": design.substrate,
        "incident": incident_label(design),
        "monitor_wavelength_nm": lm,
        "monitor": monitor,
        "monitor_back_side": monitor_back_side,
        "layers": rows,
        "curves": curves,
        "total_thickness_nm": z0,
        "total_time_s": total_time,
        "palette": [p.model_dump() for p in design.palette],
        "warnings": pre_warn + warnings + sorted(res.warnings),
        "notes": [
            "Deposition order: layer 1 is deposited first, on the substrate.",
            "Optical monitoring simulated directly on the part at normal incidence; witness-chip strategies, chip changes and process drift are not modelled.",
            "Crystal thickness = film thickness / tooling factor; set density and Z-ratio of each material on the crystal controller.",
        ],
    }


# ----------------------------------------------------------------------
# Stack formula (Macleod's notation)
# ----------------------------------------------------------------------
MAX_FORMULA_LAYERS = 400


def _qw_thickness(design: CoatingDesign, res: Resolver, key: str) -> float:
    """Physical thickness of one quarter-wave optical thickness of a palette material at the design wavelength."""
    n = float(np.real(res.N(key, np.array([design.design_wavelength_nm]))[0]))
    return design.design_wavelength_nm / (4.0 * n)


def parse_formula(formula: str, design: CoatingDesign, custom_materials=()) -> list[DesignLayer]:
    """Layers from a stack formula written from the incident medium towards the substrate, as on paper
    ("Air | (HL)^7 H | Glass"). Letters are palette keys (longest match first); a number multiplies the quarter-wave
    optical thickness at the design wavelength (normal incidence) of the key or group after it, an optional "*"
    between them; "(...)^n" repeats a group. Examples: "H L H", "(HL)^7 H", "0.5H L 0.5H", "1.1(0.5L H 0.5L)^8",
    "2L". "|" and the words Air, Sub, Substrate, Glass at either end are ignored. Returns layers in deposition order."""
    res = Resolver(design, custom_materials)
    keys = sorted((p.key for p in design.palette), key=len, reverse=True)
    s = formula.replace("|", " ").strip()
    for w in ("AIR", "SUBSTRATE", "SUB", "GLASS"):
        u = s.upper()
        if u.startswith(w + " ") or u == w:
            s = s[len(w):].strip()
        u = s.upper()
        if u.endswith(" " + w):
            s = s[: -len(w)].strip()
    pos = 0

    def err(msg: str):
        raise DesignError(f"Formula: {msg} at position {pos + 1}")

    def ws():
        nonlocal pos
        while pos < len(s) and s[pos] in " \t,":
            pos += 1

    def number() -> float | None:
        nonlocal pos
        ws()
        j = pos
        while j < len(s) and (s[j].isdigit() or s[j] == "."):
            j += 1
        if j == pos:
            return None
        try:
            v = float(s[pos:j])
        except ValueError:
            err(f"bad number '{s[pos:j]}'")
        pos = j
        return v

    def seq(depth: int) -> list[tuple[str, float]]:
        nonlocal pos
        out: list[tuple[str, float]] = []
        while True:
            ws()
            if pos >= len(s):
                if depth:
                    err("missing ')'")
                return out
            if s[pos] == ")":
                if not depth:
                    err("unmatched ')'")
                pos += 1
                return out
            m = number()
            ws()
            if m is not None and pos < len(s) and s[pos] == "*":
                pos += 1
                ws()
            if pos >= len(s):
                err("a number without a layer")
            if s[pos] == "(":
                pos += 1
                item = seq(depth + 1)
            else:
                k = next((k for k in keys if s.startswith(k, pos)), None)
                if k is None:
                    k = next((k for k in keys if s[pos:pos + len(k)].upper() == k.upper()), None)
                if k is None:
                    err(f"'{s[pos]}' is not a palette key ({', '.join(sorted(keys))})")
                pos += len(k)
                item = [(k, 1.0)]
            ws()
            rep = 1
            if pos < len(s) and s[pos] == "^":
                pos += 1
                r = number()
                if r is None or r != int(r) or r < 1:
                    err("'^' needs a whole number of repeats")
                rep = int(r)
            mult = 1.0 if m is None else m
            if mult <= 0:
                err("a multiplier must be positive")
            out.extend([(k, q * mult) for k, q in item] * rep)
            if len(out) > MAX_FORMULA_LAYERS:
                raise DesignError(f"Formula: more than {MAX_FORMULA_LAYERS} layers")

    items = seq(0)
    if not items:
        raise DesignError("Formula: no layers")
    qw = {k: _qw_thickness(design, res, k) for k in {k for k, _ in items}}
    return [DesignLayer(material=k, thickness_nm=q * qw[k]) for k, q in reversed(items)]


def to_formula(design: CoatingDesign, custom_materials=(), digits: int = 4) -> str:
    """The design as a stack formula (incident side first), quarter-wave multiples at the design wavelength rounded to
    `digits` significant figures; repeated runs are written as (...)^n."""
    if not design.layers:
        return ""
    res = Resolver(design, custom_materials)
    qw = {p.key: _qw_thickness(design, res, p.key) for p in design.palette}
    toks = []
    for L in reversed(design.layers):
        m = float(f"{L.thickness_nm / qw[L.material]:.{digits}g}")
        toks.append(L.material if abs(m - 1.0) < 1e-12 else f"{m:g}{L.material}")
    out: list[str] = []
    i = 0
    while i < len(toks):
        best = (1, 1)  # (period, count)
        for p in range(1, 5):
            c = 1
            while i + (c + 1) * p <= len(toks) and toks[i + c * p : i + (c + 1) * p] == toks[i : i + p]:
                c += 1
            if c >= 2 and p * c > best[0] * best[1] and (p > 1 or c >= 3):
                best = (p, c)
        p, c = best
        if c >= 2:
            body = " ".join(toks[i : i + p]) if p > 1 else toks[i]
            out.append(f"({body.replace(' ', '') if all(len(t) == 1 for t in toks[i:i + p]) else body})^{c}")
            i += p * c
        else:
            out.append(toks[i])
            i += 1
    return " ".join(out)


# ----------------------------------------------------------------------
# Reverse engineering: fit a measured spectrum
# ----------------------------------------------------------------------
class Measurement(_M):
    quantity: Literal["R", "T"] = "T"
    polarization: Literal["avg", "s", "p"] = "avg"
    angle_deg: float = Field(0.0, ge=0.0, lt=90.0)
    lambda_nm: list[float] = Field(min_length=3, max_length=5000)
    value: list[float] = Field(min_length=3, max_length=5000)  # fractions 0...1
    weight: float = Field(1.0, gt=0.0)

    @model_validator(mode="after")
    def _check(self):
        if len(self.lambda_nm) != len(self.value):
            raise ValueError("Measurement: as many values as wavelengths")
        if any(not 50.0 < w <= 50000.0 for w in self.lambda_nm):
            raise ValueError("Measurement wavelengths must be within 50...50000 nm")
        if any(not -0.05 <= v <= 1.05 for v in self.value):
            raise ValueError("Measured values are fractions (0...1); divide percentages by 100")
        return self


FitMode = Literal["scale", "layers", "scale_layers", "none"]


def fit_measurement(design: CoatingDesign, measurements: list[Measurement], custom_materials=(), mode: FitMode = "layers", max_error: float = 0.3, time_limit_s: float = 30.0,
                    fit_index: bool = False, fit_dispersion: bool = False, fit_absorption: bool = False, fit_substrate: bool = False,
                    search: Literal["local", "global"] = "local", index_range: float = 0.1) -> dict:
    """Reverse engineering: the thickness and index errors that make the design reproduce measured R or T spectra
    (bounded nonlinear least squares).

    Thicknesses (mode): "scale" one relative error for all layers (a rate or tooling error); "layers" one relative error
    per unlocked layer; "scale_layers" both (the per-layer errors then describe the deviation from the common scale);
    "none" no thickness variable.
    Indices, per palette material used by the layers: fit_index an offset dA (n + dA), fit_dispersion a Cauchy term
    dB / lambda_um^2, fit_absorption an extinction k >= 0 (added to the material's), fit_substrate an offset of the
    substrate index. The fitted design carries them (PaletteMaterial.index_offset, index_offset_b, extinction;
    CoatingDesign.substrate_offset), so the design keeps reproducing the measurement.

    search "local": least squares from zero (with a scan of the thickness scale and multistart from its best minima);
    "global": quasi-random (Sobol) sampling of the box (thickness +-max_error, index terms within +-index_range, k within
    0...index_range / 2), then least squares from the six best distinct samples and from the local starts, keeping the
    best (multistart).

    Uncertainties from the Jacobian at the solution, s^2 (J^T J)^-1 with s^2 = SSR / (m - n); they are meaningful only
    when the measurement constrains every variable (check the correlations: thickness and index trade against each
    other at one angle; R and T, several angles and a wide band separate them)."""
    if not design.layers:
        raise DesignError("The design has no layers to fit")
    if not measurements:
        raise DesignError("No measurement given")
    if not 0.0 < max_error < 0.9:
        raise DesignError("max_error must be within 0...0.9")
    res = Resolver(design, custom_materials)
    if any(m.quantity == "T" for m in measurements) and res.opaque:
        raise DesignError("An opaque substrate transmits nothing: fit a reflectance measurement")
    d0 = np.array([L.thickness_nm for L in design.layers])
    free = [i for i, L in enumerate(design.layers) if not L.locked]
    use_scale = mode in ("scale", "scale_layers")
    use_layers = mode in ("layers", "scale_layers")
    if use_layers and not free:
        raise DesignError("All layers are locked: nothing to fit per layer")
    keys = [p.key for p in design.palette if any(L.material == p.key for L in design.layers)]
    # variables: (name, kind, target, lower, upper, typical size, units)
    var: list[tuple[str, str, object, float, float, float, str]] = []
    if use_scale:
        var.append(("scale", "scale", None, -max_error, max_error, 0.01, "rel"))
    if use_layers:
        var += [(f"layer {i + 1}", "layer", i, -max_error, max_error, 0.01, "rel") for i in free]
    if fit_index:
        var += [(f"{k}: Δn", "dA", k, -0.3, 0.3, 0.01, "") for k in keys]
    if fit_dispersion:
        var += [(f"{k}: ΔB", "dB", k, -0.1, 0.1, 0.002, "µm²") for k in keys]
    if fit_absorption:
        var += [(f"{k}: k", "k", k, 0.0, 0.2, 1e-3, "") for k in keys]
    if fit_substrate:
        if res.opaque:
            raise DesignError("The substrate index of an opaque substrate is not fitted")
        var.append(("substrate: Δn", "dns", None, -0.2, 0.2, 0.01, ""))
    nvar = len(var)
    if not nvar:
        raise DesignError("Nothing to fit: choose thickness and/or index variables")
    lams = [np.asarray(m.lambda_nm, dtype=float) for m in measurements]
    meas = [np.asarray(m.value, dtype=float) for m in measurements]
    wts = [math.sqrt(m.weight / len(m.value)) for m in measurements]
    nres = sum(len(v) for v in meas)
    if nres <= nvar:
        raise DesignError(f"{nres} measured points cannot determine {nvar} unknowns")

    def apply(x) -> CoatingDesign:
        d = d0.copy()
        pal = {p.key: p.model_copy() for p in design.palette}
        dns = 0.0
        for (name, kind, tgt, *_), v in zip(var, x):
            if kind == "scale":
                d = d * (1.0 + v)
        for (name, kind, tgt, *_), v in zip(var, x):
            if kind == "layer":
                d[tgt] = d[tgt] * (1.0 + v)
            elif kind == "dA":
                pal[tgt].index_offset = float(np.clip(design.palette[[p.key for p in design.palette].index(tgt)].index_offset + v, -1.0, 1.0))
            elif kind == "dB":
                pal[tgt].index_offset_b = float(np.clip(design.palette[[p.key for p in design.palette].index(tgt)].index_offset_b + v, -1.0, 1.0))
            elif kind == "k":
                pal[tgt].extinction = float(design.palette[[p.key for p in design.palette].index(tgt)].extinction + v)
            elif kind == "dns":
                dns = v
        return design.model_copy(update={
            "layers": [L.model_copy(update={"thickness_nm": float(t)}) for L, t in zip(design.layers, d)],
            "palette": [pal[p.key] for p in design.palette],
            "substrate_offset": float(np.clip(design.substrate_offset + dns, -1.0, 1.0)),
        })

    def model(x):
        dx = apply(x)
        res.d, res.pal = dx, {p.key: p for p in dx.palette}
        out = []
        for m, lam in zip(measurements, lams):
            sp = spectrum(dx, res, lam, m.angle_deg)
            out.append(sp[m.quantity + ("" if m.polarization == "avg" else m.polarization)])
        return out

    def resid(x):
        if time.time() > deadline:
            raise TimeoutError
        return np.concatenate([w * (v - y) for w, v, y in zip(wts, model(x), meas)])

    t0 = time.time()
    deadline = t0 + time_limit_s
    lo = np.array([v[3] for v in var])
    hi = np.array([v[4] for v in var])
    x0 = np.clip(np.zeros(nvar), lo, hi)
    x0 = np.where(lo == 0.0, 1e-6, x0)  # a k starts just inside its bound
    resid(x0)  # validates the model before the fit
    starts = [x0.copy()]
    if use_scale:
        # a thickness scale moves spectral features by many fringes, and index errors trade against it: scan the scale
        # and start the least squares from the three best local minima of the scan (multistart)
        grid = np.linspace(-max_error, max_error, 241)
        costs = []
        for v in grid:
            x0[0] = v
            rv = resid(x0)
            costs.append(float(rv @ rv))
        costs_a = np.array(costs)
        minima = [i for i in range(len(grid)) if (i == 0 or costs_a[i] <= costs_a[i - 1]) and (i == len(grid) - 1 or costs_a[i] <= costs_a[i + 1])]
        starts = []
        for i in sorted(minima, key=lambda i: costs_a[i])[:3]:
            st = x0.copy()
            st[0] = grid[i]
            starts.append(st)
    if search == "global":
        # quasi-random (Sobol) sampling of the box, then least squares from the best distinct samples (multistart)
        from scipy.stats import qmc

        span = {"scale": max_error, "layer": max_error, "dA": index_range, "dB": index_range / 2, "k": index_range / 2, "dns": index_range}
        blo = np.array([0.0 if v[3] == 0.0 else max(v[3], -span[v[1]]) for v in var])
        bhi = np.array([min(v[4], span[v[1]]) for v in var])
        m = int(min(10, max(6, np.ceil(np.log2(32 * nvar)))))
        pts = qmc.scale(qmc.Sobol(nvar, scramble=True, seed=1).random_base2(m), blo, bhi)
        stop_at = t0 + 0.4 * time_limit_s
        scored = []
        for x in pts:
            if time.time() > stop_at:
                break
            r = resid(x)
            scored.append((float(r @ r), x))
        scored.sort(key=lambda c: c[0])
        picked: list[np.ndarray] = []
        for _, x in scored:
            if all(np.max(np.abs(x - y) / np.maximum(bhi - blo, 1e-12)) > 0.05 for y in picked):
                picked.append(x)
            if len(picked) == 6:
                break
        starts = [np.clip(x, lo, hi) for x in picked] + starts
    status = "converged"
    sol = None
    for st in starts:
        try:
            cand = least_squares(resid, st, bounds=(lo, hi), method="trf", jac="3-point", x_scale=np.array([v[5] for v in var]), diff_step=1e-5, xtol=1e-12, ftol=1e-12, gtol=1e-12, max_nfev=200 * (nvar + 1))
        except TimeoutError:
            if sol is None:
                raise DesignError(f"The fit did not finish within {time_limit_s:g} s") from None
            status = "time limit reached (best start kept)"
            break
        if sol is None or cand.cost < sol.cost:
            sol = cand
    x, r, J = sol.x, sol.fun, sol.jac
    if not status.startswith("time"):
        status = sol.message + (f" (best of {len(starts)} starts)" if len(starts) > 1 else "")
    ssr = float(r @ r)
    dof = max(1, nres - nvar)
    s2 = ssr / dof
    try:
        cov = s2 * np.linalg.inv(J.T @ J)
        sig = np.sqrt(np.clip(np.diag(cov), 0.0, None))
        dn = np.sqrt(np.clip(np.diag(cov), 1e-300, None))
        corr = cov / np.outer(dn, dn)
        ill = bool(np.linalg.cond(J.T @ J) > 1e12)
    except np.linalg.LinAlgError:
        sig = np.full(nvar, np.nan)
        corr = np.full((nvar, nvar), np.nan)
        ill = True
    fitted = apply(x).model_copy(update={"name": design.name + " (as built)"})
    d1 = np.array([L.thickness_nm for L in fitted.layers])
    curves = []
    mfit = model(x)
    mdes = model(np.where(lo == 0.0, 0.0, np.zeros(nvar)))
    for m, lam, y, a, b in zip(measurements, lams, meas, mdes, mfit):
        curves.append({"quantity": m.quantity, "polarization": m.polarization, "angle_deg": m.angle_deg, "lambda_nm": lam.tolist(), "measured": y.tolist(), "design": a.tolist(), "fitted": b.tolist()})
    at_bound = [v[0] for j, v in enumerate(var) if (abs(x[j] - v[3]) < 1e-9 and v[3] != 0.0) or abs(x[j] - v[4]) < 1e-9]
    warnings = []
    if ill:
        warnings.append("The measurement does not determine every variable independently (ill-conditioned fit): use fewer variables or more spectra (R and T, several angles, a wider band)")
    strong = sorted({(var[a][0], var[b][0]) for a in range(nvar) for b in range(a + 1, nvar) if np.isfinite(corr[a, b]) and abs(corr[a, b]) > 0.98})
    if strong and not ill:
        warnings.append("Strongly correlated (|r| > 0.98): " + "; ".join(f"{a} ~ {b}" for a, b in strong[:6]))
    if at_bound:
        warnings.append(f"At a bound: {', '.join(at_bound)}")
    return {
        "mode": mode,
        "variables": [{"name": v[0], "kind": v[1], "units": v[6], "error": float(x[j]), "sigma": float(sig[j])} for j, v in enumerate(var)],
        "layer_errors": [float(t / t0_ - 1.0) if t0_ > 0 else 0.0 for t, t0_ in zip(d1, d0)],
        "correlation": [[float(v) for v in row] for row in corr],
        "rms_before": float(np.sqrt(np.mean(np.concatenate([a - y for a, y in zip(mdes, meas)]) ** 2))),
        "rms_after": float(np.sqrt(np.mean(np.concatenate([b - y for b, y in zip(mfit, meas)]) ** 2))),
        "fitted_design": fitted.model_dump(),
        "curves": curves,
        "status": status,
        "elapsed_s": time.time() - t0,
        "warnings": warnings + sorted(res.warnings),
        "method": ("Sobol sampling of the parameter box, then bounded nonlinear least squares from the best samples" if search == "global" else "Bounded nonlinear least squares (SciPy trust-region reflective)")
                  + " of the measured R/T against the characteristic-matrix model; relative thickness errors and index corrections n + Δn + ΔB/λ² − ik; uncertainties s²(JᵀJ)⁻¹ at the solution",
    }


def incident_label(design: CoatingDesign) -> str:
    return f"n {design.incident_index:g}" if design.incident_index is not None else design.incident


def design_from_builtin(c, base: CoatingDesign | None = None) -> CoatingDesign:
    """Designer view of a built-in library coating (thinfilm.Coating) under the conditions it was
    designed for: its design wavelength, incident and substrate indices, layer materials and its
    specification as the targets. Not tied to a project coating (saving makes a new one)."""
    labels = list(c.layer_labels) if len(c.layer_labels) == len(c.layers) else [""] * len(c.layers)
    sigs: list[tuple] = []
    lab: dict[tuple, str] = {}
    for L, name in zip(c.layers, labels):
        sig = (L.material or "", float(L.index), float(L.extinction or 0.0))
        if sig not in sigs:
            sigs.append(sig)
            lab[sig] = name
    if len(sigs) > 8:
        raise DesignError(f"{c.name}: more than 8 distinct layer materials")
    # keys by index: H(igh), M(edium), L(ow); further ones by letter
    order = sorted(sigs, key=lambda s: -s[1])
    keys = {1: ["H" if order[0][1] >= 1.8 else "L"], 2: ["H", "L"], 3: ["H", "M", "L"]}.get(len(order), list("HMLNPQXYZW"[: len(order)]))
    keyof = dict(zip(order, keys))
    pal = [{"key": keyof[s], "label": lab[s], "material": s[0], "index": s[1] if not s[0] else 1.46, "extinction": s[2]} for s in order]
    layers = [{"material": keyof[(L.material or "", float(L.index), float(L.extinction or 0.0))], "thickness_nm": float(L.thickness_nm)} for L in reversed(c.layers)]
    b = base.model_dump() if base else {}
    b.update({
        "name": c.name,
        "palette": pal,
        "layers": layers,
        "targets": [dict(t) for t in c.spec],
        "source_coating": "",
        "incident": "AIR",
        "incident_index": None if abs(float(c.incident_index) - 1.0) < 1e-12 else float(c.incident_index),
        "back_side": "none",
    })
    if c.design_nm:
        b["design_wavelength_nm"] = float(c.design_nm)
    if getattr(c, "substrate_material", ""):  # the library glass it is designed on (a metal mirror: the glass blank)
        b["substrate"], b["substrate_index"], b["substrate_extinction"] = c.substrate_material, None, 0.0
    elif c.substrate is not None:  # a mirror with a fixed metal substrate
        b["substrate_index"], b["substrate_extinction"] = float(np.real(c.substrate)), float(-np.imag(c.substrate))
    elif c.substrate_index is not None:  # the glass index it is designed on
        b["substrate_index"], b["substrate_extinction"] = float(c.substrate_index), 0.0
    d = CoatingDesign.model_validate(b)
    if d.min_thickness_nm >= d.max_thickness_nm or any(L.thickness_nm > d.max_thickness_nm for L in d.layers):
        d = d.model_copy(update={"min_thickness_nm": 0.0, "max_thickness_nm": max(2000.0, max((L.thickness_nm for L in d.layers), default=0.0) * 1.5)})
    return d


def to_coating_definition(design: CoatingDesign, name: str | None = None) -> dict:
    """Project coating (air side first, as thinfilm.Coating expects on lenses)."""
    pal = {p.key: p for p in design.palette}
    layers = []
    for L in reversed(design.layers):
        p = pal[L.material]
        layers.append({"material": p.material, "index": p.index, "extinction": p.extinction, "thickness_nm": L.thickness_nm})
    nm = (name or design.name).strip().upper()[:40]
    sub = f"N = {design.substrate_index:g} - {design.substrate_extinction:g}i" if design.substrate_index is not None else design.substrate
    src = design.model_copy(update={"source_coating": nm}).model_dump()
    return {
        "name": nm,
        "description": f"Designed in OptiCore ({len(design.layers)} layers on {sub})",
        "layers": layers,
        "substrate_index": design.substrate_index,
        "substrate_extinction": design.substrate_extinction if design.substrate_index is not None else 0.0,
        "design": src,
    }


def design_from_coating(cd: dict, base: CoatingDesign | None = None) -> CoatingDesign:
    """Designer view of a project coating: its stored design, or a design rebuilt from the layers
    (palette from the distinct layer materials, deposition order = reversed air-side-first list)."""
    if cd.get("design"):
        d = CoatingDesign.model_validate(cd["design"])
        return d.model_copy(update={"source_coating": cd["name"]})
    pal: list[dict] = []
    keyof: dict[tuple, str] = {}
    letters = iter("HLMNPQXYZW")
    for L in cd.get("layers") or []:
        sig = (L.get("material") or "", float(L.get("index", 1.0)), float(L.get("extinction", 0.0) or 0.0))
        if sig not in keyof and len(pal) < 8:
            k = next(letters)
            keyof[sig] = k
            pal.append({"key": k, "material": sig[0], "index": sig[1] if not sig[0] else 1.46, "extinction": sig[2]})
    if not pal:
        pal = [{"key": "H", "index": 2.35}, {"key": "L", "index": 1.46}]
    layers = []
    for L in reversed(cd.get("layers") or []):
        sig = (L.get("material") or "", float(L.get("index", 1.0)), float(L.get("extinction", 0.0) or 0.0))
        layers.append({"material": keyof.get(sig, pal[0]["key"]), "thickness_nm": float(L.get("thickness_nm", 0.0))})
    b = (base.model_dump() if base else {})
    b.update({"name": cd["name"], "palette": pal, "layers": layers, "targets": b.get("targets", []), "source_coating": cd["name"]})
    if cd.get("substrate_index") is not None:
        b["substrate_index"] = cd["substrate_index"]
        b["substrate_extinction"] = cd.get("substrate_extinction", 0.0)
    return CoatingDesign.model_validate(b)


# ----------------------------------------------------------------------
# Angular performance
# ----------------------------------------------------------------------
def angular(design: CoatingDesign, custom_materials=(), wavelengths_nm: list[float] | None = None, angle_max_deg: float = 85.0, angles: int = 86, map_wavelengths: int = 81, map_angles: int = 46, lambda_min_nm: float | None = None, lambda_max_nm: float | None = None) -> dict:
    """R, T, A (avg, s, p) versus angle of incidence at chosen wavelengths, and R/T maps over
    wavelength x angle."""
    if not 1.0 <= angle_max_deg < 90.0:
        raise DesignError("angle_max_deg must be within 1…89.9")
    res = Resolver(design, custom_materials)
    lams = [float(w) for w in (wavelengths_nm or [design.design_wavelength_nm])][:8]
    ang = np.linspace(0.0, angle_max_deg, max(2, angles))
    curves = []
    for lam in lams:
        rows = {k: [] for k in ("R", "T", "A", "Rs", "Rp", "Ts", "Tp")}
        for a in ang:
            sp = spectrum(design, res, np.array([lam]), float(a))
            for k in rows:
                rows[k].append(float(sp[k][0]))
        curves.append({"wavelength_nm": lam, **rows})
    tl = [t.lambda_min_nm for t in design.targets] + [t.lambda_max_nm for t in design.targets]
    lo = lambda_min_nm or (min(tl) * 0.85 if tl else design.design_wavelength_nm * 0.6)
    hi = lambda_max_nm or (max(tl) * 1.15 if tl else design.design_wavelength_nm * 1.6)
    mlam = np.linspace(lo, hi, max(2, map_wavelengths))
    mang = np.linspace(0.0, angle_max_deg, max(2, map_angles))
    Rm = np.zeros((len(mang), len(mlam)))
    Tm = np.zeros_like(Rm)
    for i, a in enumerate(mang):
        sp = spectrum(design, res, mlam, float(a))
        Rm[i], Tm[i] = sp["R"], sp["T"]
    return {
        "angles_deg": ang.tolist(),
        "curves": curves,
        "map": {"lambda_nm": mlam.tolist(), "angles_deg": mang.tolist(), "R": Rm.tolist(), "T": Tm.tolist()},
        "opaque_substrate": bool(res.opaque),
        "warnings": sorted(res.warnings),
        "method": "Characteristic-matrix calculation versus angle of incidence in the incident medium (s, p and their mean)",
    }
