"""Thin-film multilayer optics (characteristic / transfer-matrix method).

For a stack of homogeneous, isotropic layers between a lossless incident
medium n0 and a substrate Ns, at incidence angle theta0 in n0, each layer j
(complex index N_j = n_j - i k_j) contributes

    y_j = N_j cos(theta_j) = sqrt(N_j^2 - (n0 sin theta0)^2)
    delta_j = 2 pi y_j d_j / lambda
    M_j = [[cos delta_j, i sin delta_j / eta_j], [i eta_j sin delta_j, cos delta_j]]

with tilted admittances eta = y (s) and eta = N^2 / y (p). The layer matrix
does not depend on the sign of y. For the substrate the branch Im y <= 0
(decaying field in Macleod's N = n - ik convention) is chosen, which also
gives the evanescent substrate under total internal reflection.
[B, C]^T = (prod M_j) [1, eta_s]^T gives

    r = (eta0 B - C) / (eta0 B + C),   R = |r|^2,
    T = 4 Re(eta0) Re(eta_s) / |eta0 B + C|^2,   A = 1 - R - T.

Reference: H. A. Macleod, *Thin-Film Optical Filters*, ch. 2. Validated in
tests/test_thinfilm.py: bare interface = Fresnel (dielectric and absorbing),
quarter-wave AR and HR formulas, R + T = 1 for lossless stacks, the Airy
summation and R + T + A = 1 for an absorbing film, half-wave absentee layers.

Layers have a fixed index n and extinction k, or take n(lambda) from a
library material (dispersive layers). Built-in coatings are generic textbook
designs. User-defined coatings live in the optical system
(`OpticalSystem.custom_coatings`).

Use in the sequential trace: a coating on a refracting surface replaces the
bare-interface Fresnel transmittance (unpolarised mean of s and p). The layer
list is ordered from the lower-index medium towards the denser one, so the
same coating applies to front and rear lens faces. A coating on a mirror needs
a substrate index (Ns = n - ik of the metal); its layers are listed from the
incident medium towards the substrate, and the mirror reflects
R = (Rs + Rp) / 2 instead of 1. The coating is assumed thin compared with the
ray geometry (no lateral shift). Absorbed power is lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Layer:
    index: float  # real part n (ignored when `material` is set)
    thickness_nm: float
    extinction: float = 0.0  # k in N = n - i k
    material: str = ""  # library material: n(lambda) from its dispersion formula

    @property
    def N(self) -> complex | float:
        return complex(self.index, -self.extinction) if self.extinction else self.index


@dataclass(frozen=True)
class Coating:
    name: str
    layers: tuple[Layer, ...] = field(default_factory=tuple)  # from the low-index (air) side towards the substrate
    description: str = ""
    substrate: complex | None = None  # mirror substrate N = n - i k (None: not usable on mirrors)
    library: Any = field(default=None, compare=False, hash=False, repr=False)  # MaterialLibrary for material layers
    builtin: bool = True
    # built-in library: what the design is for (shown in the coating editor, checked by tests/test_builtin_coatings.py)
    category: str = ""
    design_nm: float | None = None
    band_nm: tuple[float, float] | None = None
    angle_deg: float = 0.0
    incident_index: float = 1.0
    substrate_index: float | None = None  # the substrate it is designed on (a hint; on lenses the glass is used)
    substrate_material: str = ""  # library material of that substrate (e.g. N-BK7), when not a fixed index
    spec: tuple = ()  # targets (dicts in the coating designer's form) the design meets
    layer_labels: tuple[str, ...] = ()

    def layers_at(self, wavelength_um: float) -> tuple[Layer, ...]:
        """Layers with material indices evaluated at `wavelength_um`."""
        if not any(L.material for L in self.layers):
            return self.layers
        out = []
        for L in self.layers:
            if L.material:
                # n and k of the material (films and metals carry k); a layer's own extinction adds to it
                N = self.library.complex_index(L.material, wavelength_um)
                out.append(Layer(float(N.real), L.thickness_nm, L.extinction - float(N.imag)))
            else:
                out.append(L)
        return tuple(out)

    def oriented(self, wavelength_um: float, n1: float, n2: float) -> tuple[Layer, ...]:
        """Layers in the order met by light going from n1 into n2 (refracting surfaces)."""
        L = self.layers_at(wavelength_um)
        return L if n1 <= n2 else L[::-1]

    def materials(self) -> list[str]:
        return [L.material for L in self.layers if L.material]


def quarter_wave(n: float, design_um: float) -> Layer:
    return Layer(n, design_um * 1000.0 / (4.0 * n))


def _load_builtins() -> dict[str, Coating]:
    """Built-in coatings: generic, vendor-neutral designs of dispersive film and metal materials (materials/data/
    coating_materials.json) or nominal indices (materials/data/builtin_coatings.json, generated by
    opticore.tools.builtin_coatings; each checked against its specification in tests/test_builtin_coatings.py)."""
    import json
    from pathlib import Path

    from .materials import MaterialLibrary

    data = json.loads((Path(__file__).parent / "materials" / "data" / "builtin_coatings.json").read_text(encoding="utf-8"))
    lib = MaterialLibrary()
    out = {}
    for c in data["coatings"]:
        sub = c.get("mirror_substrate")
        out[c["name"]] = Coating(
            c["name"], tuple(Layer(float(L["index"]), float(L["thickness_nm"]), float(L.get("extinction", 0.0)), str(L.get("material", "")).upper()) for L in c["layers"]), c["description"],
            substrate=complex(sub[0], -sub[1]) if sub else None, library=lib,
            category=c["category"], design_nm=c.get("design_nm"), band_nm=tuple(c["band_nm"]) if c.get("band_nm") else None, angle_deg=float(c.get("angle_deg", 0.0)),
            incident_index=float(c.get("incident_index", 1.0)), substrate_index=c.get("substrate_index"), substrate_material=c.get("substrate_material") or "", spec=tuple(c.get("spec", ())),
            layer_labels=tuple(L.get("material_label", "") for L in c["layers"]),
        )
    return out


# Built-in coatings: generic textbook designs (no vendor data).
COATINGS: dict[str, Coating] = _load_builtins()


def _y(N, s0):
    """N cos(theta) = sqrt(N^2 - s0^2) on the branch Im <= 0 (decaying / outgoing wave)."""
    y = np.sqrt(np.asarray(N, dtype=complex) ** 2 - s0**2)
    y = np.where(np.imag(y) > 0, -y, y)
    return np.where(np.abs(y) < 1e-300, 1e-300 + 0j, y)


def _stack(n0: float, ns, layers: tuple[Layer, ...], wavelength_um: float, cos0) -> dict:
    cos0 = np.real(np.asarray(cos0, dtype=complex))
    s0 = n0 * np.sqrt(np.clip(1.0 - cos0**2, 0.0, None))  # invariant n0 sin(theta0)
    lam_nm = wavelength_um * 1000.0
    Ns = complex(ns)
    y0 = n0 * cos0 + 0j
    ys = _y(Ns, s0)
    lay = []
    for L in layers:
        if L.material:
            raise ValueError("Material layers must be resolved with Coating.layers_at first")
        N = complex(L.N)
        lay.append((N, _y(N, s0), L.thickness_nm))
    out = {}
    for pol in ("s", "p"):

        def eta(N, y):
            return y if pol == "s" else N * N / y

        e0 = eta(complex(n0), y0)
        es = eta(Ns, ys)
        m11 = np.ones_like(y0)
        m12 = np.zeros_like(y0)
        m21 = np.zeros_like(y0)
        m22 = np.ones_like(y0)
        for N, yj, d_nm in lay:
            ej = eta(N, yj)
            d = 2 * np.pi * yj * d_nm / lam_nm
            c, sn = np.cos(d), np.sin(d)
            a11, a12, a21, a22 = c, 1j * sn / ej, 1j * ej * sn, c
            m11, m12, m21, m22 = m11 * a11 + m12 * a21, m11 * a12 + m12 * a22, m21 * a11 + m22 * a21, m21 * a12 + m22 * a22
        B = m11 + m12 * es
        C = m21 + m22 * es
        den = e0 * B + C
        r = (e0 * B - C) / den
        out["r" + pol] = r
        out["t" + pol] = (2 * e0 / den) * np.sqrt(np.maximum(np.real(es), 0.0) / np.real(e0))
        out["R" + pol] = np.abs(r) ** 2
        out["T" + pol] = np.maximum(4 * np.real(e0) * np.real(es) / np.abs(den) ** 2, 0.0)
    return out


def stack_rt(n0: float, ns: complex | float, layers: tuple[Layer, ...], wavelength_um: float, cos0: np.ndarray):
    """Power reflectance, transmittance and absorptance (Rs, Rp, Ts, Tp, As, Ap) for incidence cosines cos0 (array)."""
    o = _stack(n0, ns, layers, wavelength_um, cos0)
    res = {k: o[k] for k in ("Rs", "Rp", "Ts", "Tp")}
    res["As"] = np.clip(1.0 - res["Rs"] - res["Ts"], 0.0, None)
    res["Ap"] = np.clip(1.0 - res["Rp"] - res["Tp"], 0.0, None)
    return res


def unpolarized_T(n0, ns, layers, wavelength_um, cos0):
    o = stack_rt(n0, ns, layers, wavelength_um, cos0)
    return 0.5 * (o["Ts"] + o["Tp"])


def unpolarized_R(n0, ns, layers, wavelength_um, cos0):
    o = stack_rt(n0, ns, layers, wavelength_um, cos0)
    return 0.5 * (o["Rs"] + o["Rp"])


def stack_amplitudes(n0: float, ns: complex | float, layers: tuple[Layer, ...], wavelength_um: float, cos0: np.ndarray) -> dict:
    """Complex, power-normalised transmission and reflection amplitudes.

    t~ = tau * sqrt(Re(eta_sub) / Re(eta0)) with tau = 2 eta0 / (eta0 B + C) the
    tangential-field transmission coefficient, so |t~|^2 = T exactly and arg(t~)
    is the phase of the transmitted field (for a non-evanescent substrate).
    r = (eta0 B - C) / (eta0 B + C) in Macleod's convention (for p it is the
    ratio of the tangential fields). An empty stack gives the Fresnel
    coefficients of the bare interface (|t~_s|^2 = Ts, |t~_p|^2 = Tp).
    """
    o = _stack(n0, ns, layers, wavelength_um, cos0)
    return {k: o[k] for k in ("ts", "tp", "rs", "rp")}


def normalize_name(name: str) -> str:
    return (name or "").strip().upper()


def coating_from_definition(d, library=None) -> Coating:
    """Build a Coating from a model.CoatingDefinition (or an equivalent dict)."""

    def g(obj, k, default=None):
        return obj.get(k, default) if isinstance(obj, dict) else getattr(obj, k, default)

    layers = []
    for L in g(d, "layers") or []:
        mat = normalize_name(g(L, "material", "") or "")
        layers.append(Layer(float(g(L, "index", 1.0)), float(g(L, "thickness_nm", 0.0)), float(g(L, "extinction", 0.0) or 0.0), mat))
    sub_n = g(d, "substrate_index")
    sub = None if sub_n is None else complex(float(sub_n), -float(g(d, "substrate_extinction", 0.0) or 0.0))
    c = Coating(normalize_name(g(d, "name", "")), tuple(layers), g(d, "description", "") or "", sub, library, builtin=False)
    if c.materials() and library is None:
        raise ValueError(f"Coating '{c.name}': material layers need a material library")
    for m in c.materials():
        library.get(m)  # raises MaterialError for unknown materials
    return c


def get_coating(name: str, custom: dict[str, Coating] | None = None) -> Coating | None:
    key = normalize_name(name)
    if key in ("", "NONE", "UNCOATED"):
        return None
    if custom and key in custom:
        return custom[key]
    if key not in COATINGS:
        raise ValueError(f"Unknown coating '{name}'")
    return COATINGS[key]


def coating_curve(
    name_or_coating,
    n_substrate: float,
    lam_min: float = 0.4,
    lam_max: float = 0.8,
    samples: int = 81,
    angle_deg: float = 0.0,
    n0: float = 1.0,
    mirror: bool = False,
    custom: dict[str, Coating] | None = None,
) -> dict:
    """Unpolarised R, T, A (and Rs, Rp) versus wavelength.

    mirror=True uses the coating's own substrate (metal) instead of
    `n_substrate`, with the layers in the order listed; otherwise the layers
    run from the lower-index side (as on a refracting surface)."""
    c = name_or_coating if isinstance(name_or_coating, Coating) else get_coating(name_or_coating, custom)
    if mirror and (c is None or c.substrate is None):
        raise ValueError("A mirror coating needs a substrate index (n, k)")
    lams = np.linspace(lam_min, lam_max, samples)
    cos0 = np.array([np.cos(np.radians(angle_deg))])
    sub = c.substrate if mirror else n_substrate
    out: dict[str, list[float]] = {k: [] for k in ("R", "T", "A", "Rs", "Rp")}
    for lam in lams:
        if c is None:
            layers: tuple[Layer, ...] = ()
        elif mirror:
            layers = c.layers_at(float(lam))
        else:
            layers = c.oriented(float(lam), n0, n_substrate)
        o = stack_rt(n0, sub, layers, float(lam), cos0)
        out["R"].append(float(0.5 * (o["Rs"][0] + o["Rp"][0])))
        out["T"].append(float(0.5 * (o["Ts"][0] + o["Tp"][0])))
        out["A"].append(float(0.5 * (o["As"][0] + o["Ap"][0])))
        out["Rs"].append(float(o["Rs"][0]))
        out["Rp"].append(float(o["Rp"][0]))
    sub_c = complex(sub)
    return {
        "wavelength_um": lams.tolist(),
        "reflectance": out["R"],
        "transmittance": out["T"],
        "absorptance": out["A"],
        "rs": out["Rs"],
        "rp": out["Rp"],
        "coating": c.name if c else "",
        "substrate_index": sub_c.real,
        "substrate_extinction": -sub_c.imag,
        "incident_index": n0,
        "angle_deg": angle_deg,
        "mirror": mirror,
        "method": "Characteristic-matrix thin-film calculation (coherent, isotropic layers, N = n - ik); unpolarised = mean of s and p",
    }
