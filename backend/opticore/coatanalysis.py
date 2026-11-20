"""Analyses of a thin-film coating between an incident medium and a substrate.

One engine for the coating editor and the coating designer:

* spectra: R, T, A (s, p, unpolarised mean) and the optical density -log10 T, optionally with the bare back surface of
  the substrate added incoherently (a plate);
* angle curves R, T(theta) at chosen wavelengths;
* phase: the phases of r and t (s, p), the group delay GD = -d(phi)/d(omega) and the group-delay dispersion
  GDD = d(GD)/d(omega) on the wavelength grid, and the ellipsometric angles psi = atan(|rp| / |rs|),
  Delta = arg(rp) - arg(rs);
* colour: the reflected and transmitted colour under CIE illuminant D65 for the CIE 1931 2 degree observer (x, y and
  CIE 1976 L*a*b* against the perfect diffuser), and the luminous reflectance and transmittance Rv, Tv;
* field: the standing-wave intensity |E|^2 / |E_incident|^2 through the stack and the absorptance of each layer;
* profile: the refractive index against depth.

Conventions. Layers are given from the incident side. The spectra and phases use the characteristic matrix of
thinfilm.py (Macleod; N = n - ik, fields ~ exp(i(omega t - k z))): a phase delay makes the phase of t more negative, so
GD = -d(phi)/d(omega) is positive (a vacuum gap d gives d / c). The field uses plane-wave amplitudes in each medium
instead (physics convention exp(i(k z - omega t)), n + i kappa): forward and backward waves matched by the continuity of
the tangential fields. It is an independent route to R and T, and the absorptance of layer j,

    A_j = k0 Im(eps_j) Integral |E|^2 dz / (n0 cos(theta0) |E_inc|^2),

sums to 1 - R - T. Validated in tests/test_coatanalysis.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import photometry as ph
from .thinfilm import _y

C_NM_PER_FS = 299.792458  # speed of light (nm / fs)
VIS = np.arange(380.0, 781.0, 5.0)  # colour integration grid (nm)

NFunc = Callable[[np.ndarray], np.ndarray]


class CoatingAnalysisError(ValueError):
    pass


@dataclass
class Stack:
    """A coating: layers from the incident side as (N(lambda_nm) -> n - ik, thickness nm, label), the incident medium
    n0(lambda) (lossless) and the substrate Ns(lambda) (n - ik). opaque: an absorbing semi-infinite substrate (a
    mirror; nothing is transmitted). back: the bare back surface of a transparent substrate, added incoherently."""

    layers: list[tuple[NFunc, float, str]]
    n0: NFunc
    ns: NFunc
    opaque: bool = False
    back: bool = False
    incident_label: str = "incident medium"
    substrate_label: str = "substrate"
    # the back face (with `back`): its coating, layers listed from the substrate outwards (empty: bare)
    back_layers: list[tuple[NFunc, float, str]] = field(default_factory=list)
    # substrate thickness (mm) and bulk absorption coefficient alpha(lambda_nm) (1/mm): absorption in R and T, and the
    # group delay of the transmitted light through the plate (None: neither)
    substrate_mm: float | None = None
    alpha_mm: NFunc | None = None
    notes: list[str] = field(default_factory=list)


def _const(v: complex) -> NFunc:
    return lambda lam: np.full(np.shape(lam), v, dtype=complex)


# ---------------------------------------------------------------------------------------------------------------- spectra
def _matrix(n0: np.ndarray, ns: np.ndarray, layers: list[tuple[np.ndarray, float]], lam: np.ndarray, sin0: float) -> dict:
    """Complex r, t and power R, T (s, p) by the characteristic matrix, vectorised over wavelength.
    t is power-normalised (|t|^2 = T for a transparent substrate)."""
    n0 = np.asarray(n0, dtype=float)
    s0 = n0 * sin0
    y0 = np.sqrt(np.clip(n0 * n0 - s0 * s0, 0.0, None)) + 0j
    Ns = np.asarray(ns, dtype=complex)
    ys = _y(Ns, s0)
    lay = [(np.asarray(N, dtype=complex), _y(N, s0), d) for N, d in layers]
    out = {}
    for pol in ("s", "p"):

        def eta(N, y):
            return y if pol == "s" else N * N / y

        e0, es = eta(n0 + 0j, y0), eta(Ns, ys)
        m11, m12, m21, m22 = np.ones_like(y0), np.zeros_like(y0), np.zeros_like(y0), np.ones_like(y0)
        for N, yj, d in lay:
            ej = eta(N, yj)
            dl = 2 * np.pi * yj * d / lam
            c, sn = np.cos(dl), np.sin(dl)
            a12, a21 = 1j * sn / ej, 1j * ej * sn
            m11, m12, m21, m22 = m11 * c + m12 * a21, m11 * a12 + m12 * c, m21 * c + m22 * a21, m21 * a12 + m22 * c
        B, C = m11 + m12 * es, m21 + m22 * es
        den = e0 * B + C
        out["r" + pol] = (e0 * B - C) / den
        out["t" + pol] = (2 * e0 / den) * np.sqrt(np.maximum(np.real(es), 0.0) / np.real(e0))
        out["R" + pol] = np.abs(out["r" + pol]) ** 2
        out["T" + pol] = np.maximum(4 * np.real(e0) * np.real(es) / np.abs(den) ** 2, 0.0)
    return out


def _resolve(stack: Stack, lam: np.ndarray):
    return np.real(stack.n0(lam)).astype(float), stack.ns(lam), [(np.asarray(f(lam), dtype=complex), d) for f, d, _ in stack.layers]


def _internal_T(stack: Stack, lam: np.ndarray, ns, n0, sin0) -> np.ndarray:
    """exp(-alpha d / cos(theta_s)) of the substrate; 1 without a thickness. alpha from `alpha_mm`, else from k of ns."""
    if not stack.substrate_mm:
        return np.ones_like(lam)
    alpha = np.asarray(stack.alpha_mm(lam), dtype=float) if stack.alpha_mm is not None else 4 * np.pi * np.maximum(-np.imag(ns), 0.0) / (lam * 1e-6)
    s = n0 * sin0 / np.real(ns)
    cos_s = np.sqrt(np.clip(1.0 - s * s, 1e-12, None))
    return np.exp(-alpha * stack.substrate_mm / cos_s)


def _back(stack: Stack, lam: np.ndarray):
    return [(np.asarray(f(lam), dtype=complex), d) for f, d, _ in stack.back_layers]


def spectrum(stack: Stack, lam_nm, angle_deg: float = 0.0) -> dict:
    """R, T, A (unpolarised, s, p) and OD = -log10(T) of the coated part, light from the incident medium."""
    lam = np.asarray(lam_nm, dtype=float)
    sin0 = math.sin(math.radians(angle_deg))
    n0, ns, layers = _resolve(stack, lam)
    f = _matrix(n0, ns, layers, lam, sin0)
    out = {}
    if stack.back and not stack.opaque:
        # the film seen from the substrate (Snell's invariant n sin(theta) kept), the back face (bare or coated) into
        # the incident medium and the bulk transmittance Ti, combined incoherently:
        #   T = Tf Ti Tb / (1 - Rf' Rb Ti^2),   R = Rf + Tf^2 Rb Ti^2 / (1 - Rf' Rb Ti^2)
        nsr = np.real(ns)
        sin_s = n0 * sin0 / nsr
        fb = _matrix(nsr, n0 + 0j, list(reversed(layers)), lam, sin_s)
        b = _matrix(nsr, n0 + 0j, _back(stack, lam), lam, sin_s)
        Ti = _internal_T(stack, lam, ns, n0, sin0)
        for pol in ("s", "p"):
            Rf, Tf = f["R" + pol], f["T" + pol]
            den = 1.0 - fb["R" + pol] * b["R" + pol] * Ti * Ti
            out["T" + pol] = Tf * Ti * b["T" + pol] / den
            out["R" + pol] = Rf + Tf * Tf * b["R" + pol] * Ti * Ti / den
    else:
        out = {k: f[k] for k in ("Rs", "Rp", "Ts", "Tp")}
    if stack.opaque:
        out["Ts"], out["Tp"] = np.zeros_like(lam), np.zeros_like(lam)
    for q in ("R", "T"):
        out[q] = 0.5 * (out[q + "s"] + out[q + "p"])
    for p in ("", "s", "p"):
        out["A" + p] = np.clip(1.0 - out["R" + p] - out["T" + p], 0.0, None)
    with np.errstate(divide="ignore"):
        out["OD"] = np.where(out["T"] > 0, -np.log10(np.maximum(out["T"], 1e-300)), np.inf)
    return out


def angle_curves(stack: Stack, wavelengths_nm, angles_deg) -> list[dict]:
    """R, T (s, p, mean) against the angle of incidence at each wavelength."""
    out = []
    for w in wavelengths_nm:
        rows = [spectrum(stack, np.array([float(w)]), float(a)) for a in angles_deg]
        out.append({"wavelength_nm": float(w), **{k: [float(r[k][0]) for r in rows] for k in ("R", "Rs", "Rp", "T", "Ts", "Tp", "A")}})
    return out


# ------------------------------------------------------------------------------------------------------------------ phase
# Below this power (|r|^2, or T) the phase of an amplitude is not drawn: near a zero of r or t it jumps by up to
# pi over a vanishing interval and its derivatives (GD, GDD) are dominated by the jump, not by the dispersion
PHASE_MIN_POWER = 1e-3


# relative frequency step of the local derivative stencil of GD and GDD (independent of the wavelength grid)
STENCIL = 3e-5


def _amplitudes(stack: Stack, lam: np.ndarray, sin0: float) -> dict:
    """r, t (s, p) and R, T of the coated face; through a plate (`back`) t and T of the directly transmitted wave,
    t_front t_back, and k_z of the substrate (for its group delay)."""
    n0, ns, layers = _resolve(stack, lam)
    f = _matrix(n0, ns, layers, lam, sin0)
    if stack.back and not stack.opaque:
        nsr = np.real(ns)
        sin_s = n0 * sin0 / nsr
        b = _matrix(nsr, n0 + 0j, _back(stack, lam), lam, sin_s)
        f = dict(f, ts=f["ts"] * b["ts"], tp=f["tp"] * b["tp"], Ts=f["Ts"] * b["Ts"], Tp=f["Tp"] * b["Tp"])
        w = 2 * np.pi * C_NM_PER_FS / lam
        f["kz"] = w / C_NM_PER_FS * np.sqrt(np.clip(nsr * nsr - (n0 * sin0) ** 2, 0.0, None))  # rad / nm
    return f


def phase(stack: Stack, lam_nm, angle_deg: float = 0.0) -> dict:
    """Phases (degrees, unwrapped along the grid for display) of r and t for s and p, the group delay GD = -dphi/domega
    (fs) and the group-delay dispersion GDD = dGD/domega (fs^2), and the ellipsometric psi, Delta (degrees).

    GD and GDD come from a local central-difference stencil at each wavelength (omega (1 +- STENCIL)), of the phase
    differences arg(a(omega + h) / a(omega - h)) etc., so they do not depend on the wavelength grid. Reflection: the
    coated face (the light reflected by the back face of a thick plate is incoherent with it). Transmission through a
    plate (`back`): the directly transmitted wave, t = t_front t_back, plus one pass through the substrate, whose
    group delay and GDD (d dk_z/domega, d d^2k_z/domega^2) are added by the same stencil; the phase shown excludes the
    substrate's propagation phase. Where the power of an amplitude is below PHASE_MIN_POWER its phase, GD and GDD are
    NaN (undefined, not drawn)."""
    lam = np.asarray(lam_nm, dtype=float)
    if len(lam) < 1:
        raise CoatingAnalysisError("No wavelengths")
    sin0 = math.sin(math.radians(angle_deg))
    w = 2 * np.pi * C_NM_PER_FS / lam  # rad / fs
    h = STENCIL * w
    f = _amplitudes(stack, lam, sin0)
    fp = _amplitudes(stack, 2 * np.pi * C_NM_PER_FS / (w + h), sin0)
    fm = _amplitudes(stack, 2 * np.pi * C_NM_PER_FS / (w - h), sin0)
    order = np.argsort(w)
    out: dict = {}
    through = stack.back and not stack.opaque
    sub_gd = sub_gdd = 0.0
    if through and stack.substrate_mm:
        d = stack.substrate_mm * 1e6
        sub_gd = d * (fp["kz"] - fm["kz"]) / (2 * h)
        sub_gdd = d * (fp["kz"] - 2 * f["kz"] + fm["kz"]) / (h * h)
    for key in ("rs", "rp", "ts", "tp"):
        amp = f[key]
        if key[0] == "t" and stack.opaque:
            continue
        phi = np.empty_like(w)
        phi[order] = np.unwrap(np.angle(amp[order])) if len(w) > 1 else np.angle(amp[order])
        gd = -np.angle(fp[key] / fm[key]) / (2 * h)
        gdd = -(np.angle(fp[key] / amp) - np.angle(amp / fm[key])) / (h * h)
        if key[0] == "t":
            gd, gdd = gd + sub_gd, gdd + sub_gdd
        weak = f[key[0].upper() + key[1]] < PHASE_MIN_POWER
        out["phase_" + key] = np.where(weak, np.nan, np.degrees(phi))
        out["gd_" + key] = np.where(weak, np.nan, gd)
        out["gdd_" + key] = np.where(weak, np.nan, gdd)
    rs, rp = f["rs"], f["rp"]
    with np.errstate(divide="ignore", invalid="ignore"):
        out["psi"] = np.degrees(np.arctan2(np.abs(rp), np.abs(rs)))
    out["delta"] = np.degrees(np.angle(rp / np.where(np.abs(rs) > 0, rs, 1e-300)))
    return out


# ----------------------------------------------------------------------------------------------------------------- colour
def _lab(XYZ: np.ndarray, white: np.ndarray) -> dict:
    def fn(t):
        d = 6 / 29
        return np.where(t > d**3, np.cbrt(t), t / (3 * d * d) + 4 / 29)

    fx, fy, fz = (fn(XYZ[i] / white[i]) for i in range(3))
    return {"L": float(116 * fy - 16), "a": float(500 * (fx - fy)), "b": float(200 * (fy - fz))}


def colour_values(values: np.ndarray, illuminant: str = "D65", observer: str = "2") -> dict:
    """Luminous fraction Y and CIE L*a*b* of reflected or transmitted light from its spectrum on VIS (a CIE illuminant,
    the 2 or 10 degree observer, the perfect diffuser under the same illuminant as white). Used by the analyses and by
    the designer's colour targets."""
    cm = ph.cmf(VIS, observer)
    E = ph.illuminant(illuminant, VIS)
    white = (cm * E[:, None]).sum(0)
    XYZ = (cm * (E * np.asarray(values, dtype=float))[:, None]).sum(0)
    return {"Y": float(XYZ[1] / white[1]), **_lab(XYZ, white)}


def colour(stack: Stack, angle_deg: float = 0.0, illuminant: str = "D65", observer: str = "2") -> dict:
    """Colour of the reflected and transmitted light under a CIE illuminant (D65, D50, D55, D75, A, C, F2, F7, F11) for
    the CIE 1931 2 degree or CIE 1964 10 degree observer, the perfect diffuser under the same illuminant as white. The
    swatch is the sRGB rendering (D65 display white) of the colour without chromatic adaptation."""
    s = spectrum(stack, VIS, angle_deg)
    cm = ph.cmf(VIS, observer)
    E = ph.illuminant(illuminant, VIS)
    white = (cm * E[:, None]).sum(0)
    out = {"illuminant": illuminant, "observer": "CIE 1931 2°" if observer == "2" else "CIE 1964 10°"}
    for q in ("R", "T"):
        XYZ = (cm * (E * s[q])[:, None]).sum(0)
        xy = ph.chromaticity(XYZ)
        # display swatch: the hue at full brightness (a 0.1 % residual reflection is otherwise black)
        lin = np.clip(ph.srgb_matrix() @ (XYZ / white[1]), 0.0, None)
        rgb = ph.srgb_encode(lin / float(lin.max()) if lin.max() > 0 else lin)
        out[q] = {"Y": float(XYZ[1] / white[1]), "x": xy["x"] if xy else None, "y": xy["y"] if xy else None, **_lab(XYZ, white), "srgb": [float(v) for v in rgb]}
    out["Rv"] = out["R"]["Y"]
    out["Tv"] = out["T"]["Y"]
    return out


# ------------------------------------------------------------------------------------------------------------------ field
def field_profile(stack: Stack, lam_nm: float, angle_deg: float = 0.0, pol: str = "s", points_per_layer: int = 120, outside_nm: float | None = None) -> dict:
    """Standing-wave |E|^2 / |E_inc|^2 against depth z (nm; 0 at the incident face, positive into the stack) and the
    absorptance of each layer, by plane-wave amplitudes in each medium (independent of the characteristic matrix)."""
    if pol not in ("s", "p"):
        raise CoatingAnalysisError("Polarisation s or p")
    lam = np.array([float(lam_nm)])
    k0 = 2 * np.pi / lam_nm
    n0 = float(np.real(stack.n0(lam)[0]))
    sin0 = math.sin(math.radians(angle_deg))
    s0 = n0 * sin0
    # physics convention: n + i kappa
    media = [complex(n0)] + [complex(np.conj(f(lam)[0])) for f, _, _ in stack.layers] + [complex(np.conj(stack.ns(lam)[0]))]
    d = [0.0] + [float(dd) for _, dd, _ in stack.layers] + [0.0]
    eps = [m * m for m in media]
    q = []
    for e in eps:
        v = np.sqrt(e - s0 * s0 + 0j)
        q.append(v if v.imag > 0 or (v.imag == 0 and v.real >= 0) else -v)
    g = [qi if pol == "s" else qi / e for qi, e in zip(q, eps)]
    # backward from the substrate: only the transmitted wave there (amplitude 1, rescaled at the end)
    m = len(media) - 1
    A = [0j] * (m + 1)
    B = [0j] * (m + 1)
    A[m], B[m] = 1.0 + 0j, 0j
    F, G = A[m], g[m] * A[m]
    for j in range(m - 1, 0, -1):  # layers: (F, G) at the layer's far side
        phi = k0 * q[j] * d[j]
        ae, be = (F + G / g[j]) / 2, (F - G / g[j]) / 2  # A e^{i phi}, B e^{-i phi}
        A[j], B[j] = ae * np.exp(-1j * phi), be * np.exp(1j * phi)
        F, G = A[j] + B[j], g[j] * (A[j] - B[j])
    A[0], B[0] = (F + G / g[0]) / 2, (F - G / g[0]) / 2
    scale = 1.0 / A[0]
    A = [a * scale for a in A]
    B = [b * scale for b in B]
    e_inc2 = 1.0 if pol == "s" else 1.0 / (n0 * n0)  # |E_inc|^2 for a unit tangential amplitude (H for p)

    def e2(j, u):
        fwd, bwd = A[j] * np.exp(1j * k0 * q[j] * u), B[j] * np.exp(-1j * k0 * q[j] * u)
        if pol == "s":
            return np.abs(fwd + bwd) ** 2
        return (np.abs(q[j] / eps[j] * (fwd - bwd)) ** 2 + np.abs(s0 / eps[j] * (fwd + bwd)) ** 2)

    outside = outside_nm if outside_nm is not None else 0.25 * lam_nm
    zs, Es, boundaries, absorb = [], [], [0.0], []
    u = np.linspace(-outside, 0.0, 60)
    zs.append(u)
    Es.append(e2(0, u) / e_inc2)
    z = 0.0
    for j in range(1, m):
        n = max(8, points_per_layer)
        u = np.linspace(0.0, d[j], n + 1 if n % 2 == 0 else n)
        E = e2(j, u) / e_inc2
        zs.append(z + u)
        Es.append(E)
        integ = float(np.trapezoid(E, u)) if len(u) < 3 else _simpson(E, u)
        absorb.append(float(k0 * eps[j].imag * integ / (n0 * math.cos(math.radians(angle_deg)))))
        z += d[j]
        boundaries.append(z)
    u = np.linspace(0.0, outside, 60)
    zs.append(z + u)
    Es.append(e2(m, u) / e_inc2)
    R = float(abs(B[0]) ** 2)
    T = 0.0 if stack.opaque else float((g[m].real / g[0].real) * abs(A[m]) ** 2)
    if stack.opaque:  # power entering the substrate is absorbed there
        T_sub = float((g[m].real / g[0].real) * abs(A[m]) ** 2)
    else:
        T_sub = T
    return {
        "wavelength_nm": float(lam_nm), "angle_deg": angle_deg, "polarization": pol,
        "z_nm": np.concatenate(zs).tolist(), "e2": np.concatenate(Es).tolist(), "boundaries_nm": boundaries,
        "layer_absorptance": absorb, "R": R, "T": T, "substrate_absorptance": T_sub if stack.opaque else 0.0,
        "labels": [lab for _, _, lab in stack.layers],
    }


def _simpson(y: np.ndarray, x: np.ndarray) -> float:
    from scipy.integrate import simpson

    return float(simpson(y, x=x))


# ---------------------------------------------------------------------------------------------------------------- profile
def profile(stack: Stack, lam_nm: float) -> dict:
    """The layers' real index and extinction at lam_nm against depth from the incident face."""
    lam = np.array([float(lam_nm)])
    z = 0.0
    rows = []
    for f, d, lab in stack.layers:
        N = complex(f(lam)[0])
        rows.append({"label": lab, "z0": z, "z1": z + d, "n": N.real, "k": -N.imag, "thickness_nm": d, "qwot": 4 * N.real * d / lam_nm})
        z += d
    return {"wavelength_nm": float(lam_nm), "layers": rows, "total_nm": z, "incident_n": float(np.real(stack.n0(lam)[0])),
            "substrate_n": float(np.real(stack.ns(lam)[0])), "substrate_k": float(-np.imag(stack.ns(lam)[0]))}


# --------------------------------------------------------------------------------------------------------------- analyses
def band_stats(lam: np.ndarray, s: dict, lo: float, hi: float) -> dict:
    m = (lam >= lo) & (lam <= hi)
    if not m.any():
        return {}
    out = {"lambda_min_nm": lo, "lambda_max_nm": hi}
    for q in ("R", "T", "A"):
        v = s[q][m]
        out[q] = {"mean": float(np.trapezoid(v, lam[m]) / (lam[m][-1] - lam[m][0])) if m.sum() > 1 else float(v[0]), "min": float(v.min()), "max": float(v.max())}
    return out


def field_map(stack: Stack, lam_min_nm: float, lam_max_nm: float, angle_deg: float = 0.0, pol: str = "s", wavelengths: int = 61, depth_points: int = 400) -> dict:
    """|E|^2 / |E_inc|^2 against wavelength and depth (a map of field_profile over the band) on a common depth grid
    from 15 % of the stack thickness in the incident medium to 15 % into the substrate."""
    total = sum(d for _, d, _ in stack.layers)
    out_nm = max(20.0, 0.15 * total)
    z = np.linspace(-out_nm, total + out_nm, depth_points)
    lams = np.linspace(lam_min_nm, lam_max_nm, wavelengths)
    rows = []
    for lam in lams:
        f = field_profile(stack, float(lam), angle_deg, pol, points_per_layer=60, outside_nm=out_nm)
        zf, ef = np.asarray(f["z_nm"]), np.asarray(f["e2"])
        rows.append(np.interp(z, zf, ef))
    bounds = np.concatenate([[0.0], np.cumsum([d for _, d, _ in stack.layers])])
    return {"wavelength_nm": lams.tolist(), "z_nm": z.tolist(), "e2": [r.tolist() for r in rows], "boundaries_nm": bounds.tolist(), "polarization": pol, "angle_deg": angle_deg}


def analyze(stack: Stack, lam_min_nm: float, lam_max_nm: float, samples: int = 241, angle_deg: float = 0.0, angles_deg: list[float] | None = None,
            reference_nm: float | None = None, band: tuple[float, float] | None = None, field_pol: str = "s", illuminant: str = "D65", observer: str = "2") -> dict:
    """Everything the coating views show, for one setting."""
    if not (0 < lam_min_nm < lam_max_nm):
        raise CoatingAnalysisError("The wavelength range needs 0 < minimum < maximum")
    lam = np.linspace(lam_min_nm, lam_max_nm, samples)
    s = spectrum(stack, lam, angle_deg)
    ref = reference_nm if reference_nm is not None else 0.5 * (lam_min_nm + lam_max_nm)
    out: dict = {"lambda_nm": lam.tolist(), "angle_deg": angle_deg, "reference_nm": ref,
                 "spectrum": {k: [float(x) if np.isfinite(x) else None for x in v] for k, v in s.items()}}
    angs = sorted({a for a in (angles_deg or []) if 0 <= a < 90 and a != angle_deg})
    out["angles"] = [{"angle_deg": a, **{k: spectrum(stack, lam, a)[k].tolist() for k in ("R", "T")}} for a in angs[:6]]
    grid = np.linspace(0.0, 89.0, 90)
    out["angle_curve"] = angle_curves(stack, [ref], grid)[0] | {"angles_deg": grid.tolist()}
    out["phase"] = {k: [float(x) if np.isfinite(x) else None for x in v] for k, v in phase(stack, lam, angle_deg).items()}
    out["phase_min_power"] = PHASE_MIN_POWER
    out["colour"] = colour(stack, angle_deg, illuminant, observer)
    out["field"] = field_profile(stack, ref, angle_deg, field_pol)
    out["field_map"] = field_map(stack, lam_min_nm, lam_max_nm, angle_deg, field_pol)
    out["profile"] = profile(stack, ref)
    out["admittance"] = {p: admittance_locus(stack, ref, angle_deg, p) for p in ("s", "p")}
    if band:
        out["band"] = band_stats(lam, s, *band)
    i = int(np.argmin(np.abs(lam - ref)))
    out["at_reference"] = {k: float(s[k][i]) for k in ("R", "T", "A", "Rs", "Rp", "Ts", "Tp")}
    out["notes"] = list(stack.notes)
    if stack.back and not stack.opaque:
        out["notes"].append(("R, T and A include the back face" + (" (coated)" if stack.back_layers else " (bare)") + " added incoherently"
                             + (f" and the bulk absorption of {stack.substrate_mm:g} mm of substrate" if stack.substrate_mm else "")
                             + "; the transmitted phase is through the plate (front face, back face" + (", substrate group delay" if stack.substrate_mm else "")
                             + "); reflection phase and field are of the coated face"))
    out["method"] = ("Characteristic-matrix thin-film calculation (coherent, isotropic layers, N = n − ik), unpolarised = mean of s and p; "
                     f"GD = −dφ/dω and GDD = dGD/dω by a local stencil (Δω/ω = {STENCIL:g}) at each wavelength; colour under CIE {illuminant} ({'1931 2°' if observer == '2' else '1964 10°'} observer) with L*a*b* against the perfect diffuser; "
                     "field |E|² by plane-wave amplitudes per medium; admittance diagram Y = C/B from the substrate outwards (tilted admittances)")
    return out


# ------------------------------------------------------------------------------------------------------------- admittance
ISO_R = (0.001, 0.01, 0.04, 0.1, 0.25, 0.5, 0.75, 0.9)


def admittance_locus(stack: Stack, lam_nm: float, angle_deg: float = 0.0, pol: str = "s", points_per_layer: int = 64) -> dict:
    """Admittance diagram (Macleod, ch. 2): the running optical admittance Y = C / B of the stack built up from the
    substrate towards the incident medium, in units of the free-space admittance. Tilted admittances: eta = N cos(theta)
    for s and N / cos(theta) for p (N = n - ik). Each layer traces an arc; the end point Y gives
    r = (eta0 - Y) / (eta0 + Y). Iso-reflectance circles for a real eta0: centre eta0 (1 + rho^2) / (1 - rho^2), radius
    2 rho eta0 / (1 - rho^2)."""
    if pol not in ("s", "p"):
        raise CoatingAnalysisError("Polarisation s or p")
    lam = np.array([float(lam_nm)])
    n0 = float(np.real(stack.n0(lam)[0]))
    s0 = n0 * math.sin(math.radians(angle_deg))

    def eta(N: complex) -> complex:
        y = complex(_y(np.array([N], dtype=complex), s0)[0])
        return y if pol == "s" else N * N / y

    e0 = eta(complex(n0))
    Y = eta(complex(stack.ns(lam)[0]))
    start = Y
    arcs = []
    for f, d, label in reversed(stack.layers):  # from the substrate outwards
        N = complex(f(lam)[0])
        ej = eta(N)
        yj = complex(_y(np.array([N], dtype=complex), s0)[0])
        dl = 2 * np.pi * yj * np.linspace(0.0, float(d), max(2, points_per_layer)) / lam_nm
        c, sn = np.cos(dl), np.sin(dl)
        Ys = (1j * ej * sn + c * Y) / (c + 1j * sn * Y / ej)
        arcs.append({"label": label, "n": N.real, "k": -N.imag, "thickness_nm": float(d), "re": Ys.real.tolist(), "im": Ys.imag.tolist()})
        Y = complex(Ys[-1])
    r = (e0 - Y) / (e0 + Y)
    circles = []
    if abs(e0.imag) < 1e-12 and e0.real > 0:
        for R in ISO_R:
            rho = math.sqrt(R)
            circles.append({"R": R, "centre": e0.real * (1 + rho * rho) / (1 - rho * rho), "radius": 2 * rho * e0.real / (1 - rho * rho)})
    return {
        "wavelength_nm": float(lam_nm), "angle_deg": angle_deg, "polarization": pol,
        "eta0": [e0.real, e0.imag], "substrate": [start.real, start.imag], "arcs": arcs, "end": [Y.real, Y.imag],
        "R": float(abs(r) ** 2), "phase_r_deg": float(np.degrees(np.angle(r))), "iso_R": circles,
    }


# --------------------------------------------------------------------------------------------------------------- adapters
def stack_from_coating(coating, library, incident_index: float = 1.0, substrate: dict | None = None, mirror: bool = False, back: bool = False) -> Stack:
    """A project or built-in coating (thinfilm.Coating, layers listed from the incident side) on a substrate:
    substrate = {"material": name} (dispersive glass) or {"index": n, "extinction": k}; mirror uses the coating's own
    metal substrate (n - ik)."""
    layers = []
    labels = getattr(coating, "layer_labels", ()) or ()
    for i, L in enumerate(coating.layers):
        lab = (labels[i] if i < len(labels) and labels[i] else (L.material or f"n {L.index:g}"))
        if L.material:
            mat, k = L.material, L.extinction

            def f(lam, mat=mat, k=k):
                return np.array([library.complex_index(mat, float(x) * 1e-3) for x in np.atleast_1d(lam)], dtype=complex) - 1j * k
        else:
            f = _const(complex(L.index, -L.extinction))
        layers.append((f, float(L.thickness_nm), lab))
    notes = []
    if mirror:
        if coating.substrate is None:
            raise CoatingAnalysisError("This coating has no mirror substrate (n, k)")
        ns, sub_label, opaque = _const(coating.substrate), f"metal N = {coating.substrate.real:g} − {-coating.substrate.imag:g}i", coating.substrate.imag != 0
    else:
        sub = substrate or {"index": 1.52}
        if sub.get("material"):
            name = sub["material"]
            ns = (lambda lam, name=name: np.array([library.complex_index(name, float(x) * 1e-3) for x in np.atleast_1d(lam)], dtype=complex))
            sub_label = name
            opaque = library.get(name).category == "metal"
        else:
            ns = _const(complex(float(sub.get("index", 1.52)), -float(sub.get("extinction", 0.0) or 0.0)))
            sub_label = f"n {float(sub.get('index', 1.52)):g}"
            opaque = float(sub.get("extinction", 0.0) or 0.0) > 1e-3  # a metal (coatdesign.OPAQUE_K); a weakly absorbing glass is not
    if back and opaque:
        notes.append("An absorbing substrate has no back surface to add")
    return Stack(layers, _const(complex(incident_index)), ns, opaque=opaque, back=back and not opaque, incident_label=f"n {incident_index:g}", substrate_label=sub_label, notes=notes)


def stack_from_design(design, res) -> Stack:
    """A coating-designer design (coatdesign.CoatingDesign, layers in deposition order) with its Resolver."""
    pal = {p.key: p for p in design.palette}
    layers = []
    for L in reversed(design.layers):
        p = pal[L.material]
        layers.append(((lambda lam, key=L.material: res.N(key, np.asarray(lam, dtype=float))), float(L.thickness_nm), p.label or p.material or p.key))
    back_layers = []
    if design.back_side == "coated":
        for L in (design.layers if design.back_same_as_front else design.back_layers):  # deposition order: from the substrate outwards
            p = pal[L.material]
            back_layers.append(((lambda lam, key=L.material: res.N(key, np.asarray(lam, dtype=float))), float(L.thickness_nm), p.label or p.material or p.key))
    back = design.back_side in ("uncoated", "coated") and not res.opaque

    def alpha(lam):  # bulk absorption (1/mm): exp(-alpha d) at normal incidence from the resolver
        lam = np.asarray(lam, dtype=float)
        T1 = res.internal_transmittance(lam, np.ones_like(lam))
        return -np.log(np.maximum(T1, 1e-300)) / design.substrate_thickness_mm

    return Stack(layers, lambda lam: res.incident(np.asarray(lam, dtype=float)), lambda lam: res.substrate(np.asarray(lam, dtype=float)), opaque=res.opaque,
                 back=back, incident_label=(f"n {design.incident_index:g}" if design.incident_index is not None else design.incident),
                 substrate_label=(f"N = {design.substrate_index:g} − {design.substrate_extinction:g}i" if design.substrate_index is not None else design.substrate),
                 back_layers=back_layers, substrate_mm=design.substrate_thickness_mm if back else None, alpha_mm=alpha if back and design.substrate_thickness_mm else None)
