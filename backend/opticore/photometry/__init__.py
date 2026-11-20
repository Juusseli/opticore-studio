"""Photometry and colorimetry with the CIE 1931 standard colorimetric observer.

Data (``photometry/data``: CIE datasets under CC BY-SA 4.0, sources and checksums in its README.md):

* x̄, ȳ, z̄ of the CIE 1931 2° observer, 360–830 nm at 1 nm (CIE 018:2019, Table 6); the photopic spectral luminous
  efficiency is V(λ) = ȳ(λ);
* the scotopic V′(λ), 380–780 nm at 1 nm (CIE 018:2019, Table 2);
* CIE standard illuminant D65, 300–830 nm at 1 nm (ISO/CIE 11664-2:2022, Table B.1);
* for colour under other illuminants: the CIE 1964 10° observer (360–830 nm at 1 nm), illuminant C, the daylight
  components S0, S1, S2 and the fluorescent illuminants (5 nm tables, CIE 015).

Between tabulated wavelengths the values are interpolated linearly; outside the tables they are zero (the CIE's
metadata). CIE standard illuminant A comes from its defining formula (ISO/CIE 11664-2), λ in nm:

    S_A(λ) = 100 (560/λ)^5 [exp(1.435e7 / (2848 · 560)) − 1] / [exp(1.435e7 / (2848 λ)) − 1]

A spectrum is either a set of lines (wavelength, power in W), such as a light source's wavelength samples or the rays
that reach a detector, or a spectral distribution tabulated at 1 nm and summed (continuous spectra):

* luminous flux Φv = K_m Σ P V(λ), K_m = 683.002 lm/W, and the scotopic Φv′ = K′_m Σ P V′(λ), K′_m = 1700.13 lm/W
  (CIE 018:2019). Both give 683 lm/W at 540 THz (555.016 nm in standard air), the definition of the candela.
* tristimulus values (X, Y, Z) = Σ P (x̄, ȳ, z̄) in W, so that Φv = K_m Y.
* chromaticity x = X/(X + Y + Z), y = Y/(X + Y + Z); CIE 1976 u′ = 4X/(X + 15Y + 3Z), v′ = 9Y/(X + 15Y + 3Z); CIE 1960
  u = u′, v = 2v′/3.
* correlated colour temperature (CCT): the temperature of the Planckian radiator nearest in the CIE 1960 (u, v)
  diagram. The radiator's chromaticity is computed with the same 1 nm tables and the second radiation constant
  c₂ = 1.4388e-2 m K (CIE 015:2018). Duv is the signed distance, positive above the locus (towards larger v). The CCT
  is reported for |Duv| ≤ 0.05 only (CIE 015:2018) and within 1000–100 000 K.
* sRGB (IEC 61966-2-1): linear RGB = M (X, Y, Z), with M from the sRGB primaries R (0.64, 0.33), G (0.30, 0.60),
  B (0.15, 0.06) and the white D65 (0.3127, 0.3290); colours outside the gamut are clipped and counted.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar

DATA = Path(__file__).resolve().parent / "data"
KM = 683.002  # lm/W, photopic maximum luminous efficacy (CIE 018:2019)
KM_SCOTOPIC = 1700.13  # lm/W, scotopic (CIE 018:2019)
C2 = 1.4388e-2  # m K, second radiation constant for colorimetry (CIE 015:2018)
CCT_RANGE_K = (1000.0, 100000.0)
DUV_LIMIT = 0.05
FILES = {
    "cmf": ("CIE_xyz_1931_2deg.csv", "17cca777db64b17170f06f67ce9d3ab7"),
    "d65": ("CIE_std_illum_D65.csv", "03d4eb9b837c60671627c946fb534deb"),
    "scotopic": ("CIE_sle_scotopic.csv", "3e45714a429d02e5d1f2a752226d7698"),
    "cmf10": ("CIE_xyz_1964_10deg.csv", "6140e032f9326d88c5a0959b29b4d8f3"),
    "fl": ("CIE_illum_FLs.csv", "441613e501ab0a58e62f2669ff005db7"),
    "daylight": ("CIE_illum_Dxx_comp.csv", "3068737bc5e8561bd8b3ef9639578d18"),
    "c": ("CIE_illum_C.csv", "bb325f040bab332d91f8d9447aa47b78"),
}
# illuminants for colour: CIE standard illuminants A and D65, illuminant C, the daylight illuminants D50, D55, D75 (from the
# daylight components at their CCT, CIE 015:2018 §4.1) and the fluorescent illuminants F2, F7, F11 (CIE FL table)
ILLUMINANTS = ("D65", "D50", "D55", "D75", "A", "C", "F2", "F7", "F11")
OBSERVERS = ("2", "10")
_FL_COLUMN = {"F2": 2, "F7": 7, "F11": 11}
_DAYLIGHT_CCT = {"D50": 5000.0, "D55": 5500.0, "D65": 6500.0, "D75": 7500.0}
SRGB_PRIMARIES = ((0.64, 0.33), (0.30, 0.60), (0.15, 0.06))
SRGB_WHITE = (0.3127, 0.3290)


@lru_cache(maxsize=None)
def table(name: str) -> np.ndarray:
    """The CIE table as an array: first column λ (nm), then the values. Empty entries ("NaN", e.g. z̄₁₀ above 560 nm
    in the 1964 observer table, where the CIE gives no value because it is negligible) are zero."""
    return np.nan_to_num(np.loadtxt(DATA / FILES[name][0], delimiter=",", ndmin=2), nan=0.0)


def _interp(name: str, lam_nm, col: int) -> np.ndarray:
    t = table(name)
    return np.interp(np.asarray(lam_nm, dtype=float), t[:, 0], t[:, col], left=0.0, right=0.0)


def cmf(lam_nm, observer: str = "2") -> np.ndarray:
    """(…, 3) x̄, ȳ, z̄ at the wavelengths (nm): the CIE 1931 2° or CIE 1964 10° observer."""
    lam = np.asarray(lam_nm, dtype=float)
    if observer not in OBSERVERS:
        raise ValueError(f"Unknown observer '{observer}' (2 or 10)")
    name = "cmf" if observer == "2" else "cmf10"
    return np.stack([_interp(name, lam, k) for k in (1, 2, 3)], axis=-1)


def daylight(lam_nm, cct_nominal: float) -> np.ndarray:
    """CIE daylight illuminant D of a nominal CCT (e.g. 5000 for D50) from the daylight components S0, S1, S2 (CIE
    015:2018 §4.1): T = cct_nominal * 1.4388 / 1.4380, x_D from T, y_D = -3 x_D^2 + 2.87 x_D - 0.275, M1 and M2 rounded to
    three decimals, S = S0 + M1 S1 + M2 S2 on the 5 nm table, linear between (relative, not normalised)."""
    T = cct_nominal * 1.4388 / 1.4380
    if 4000.0 <= T <= 7000.0:
        x = -4.6070e9 / T**3 + 2.9678e6 / T**2 + 0.09911e3 / T + 0.244063
    elif 7000.0 < T <= 25000.0:
        x = -2.0064e9 / T**3 + 1.9018e6 / T**2 + 0.24748e3 / T + 0.237040
    else:
        raise ValueError("Daylight CCT must be within 4000...25000 K")
    y = -3.000 * x * x + 2.870 * x - 0.275
    den = 0.0241 + 0.2562 * x - 0.7341 * y
    M1 = round((-1.3515 - 1.7703 * x + 5.9114 * y) / den, 3)
    M2 = round((0.0300 - 31.4424 * x + 30.0717 * y) / den, 3)
    t = table("daylight")
    S = t[:, 1] + M1 * t[:, 2] + M2 * t[:, 3]
    return np.interp(np.asarray(lam_nm, dtype=float), t[:, 0], S, left=0.0, right=0.0)


def illuminant(name: str, lam_nm) -> np.ndarray:
    """Relative spectral power of a CIE illuminant (ILLUMINANTS) at the wavelengths (nm)."""
    lam = np.asarray(lam_nm, dtype=float)
    if name == "D65":
        return d65(lam)
    if name in _DAYLIGHT_CCT:
        return daylight(lam, _DAYLIGHT_CCT[name])
    if name == "A":
        return illuminant_a(lam)
    if name == "C":
        return _interp("c", lam, 1)
    if name in _FL_COLUMN:
        return _interp("fl", lam, _FL_COLUMN[name])
    raise ValueError(f"Unknown illuminant '{name}' ({', '.join(ILLUMINANTS)})")


def v_photopic(lam_nm) -> np.ndarray:
    return _interp("cmf", lam_nm, 2)


def v_scotopic(lam_nm) -> np.ndarray:
    return _interp("scotopic", lam_nm, 1)


def d65(lam_nm) -> np.ndarray:
    """Relative spectral power of CIE standard illuminant D65 (100 at 560 nm)."""
    return _interp("d65", lam_nm, 1)


def illuminant_a(lam_nm) -> np.ndarray:
    """Relative spectral power of CIE standard illuminant A (100 at 560 nm), its defining formula."""
    lam = np.asarray(lam_nm, dtype=float)
    return 100.0 * (560.0 / lam) ** 5 * math.expm1(1.435e7 / (2848.0 * 560.0)) / np.expm1(1.435e7 / (2848.0 * lam))


def planck_relative(lam_nm, T: float) -> np.ndarray:
    """Planck's spectral exitance up to a constant factor, λ^-5 / (exp(c₂ / (λ T)) − 1)."""
    lam = np.asarray(lam_nm, dtype=float) * 1e-9
    with np.errstate(over="ignore"):
        return lam**-5 / np.expm1(np.minimum(C2 / (lam * T), 700.0))


# ---------------------------------------------------------------- chromaticity
def chromaticity(XYZ) -> dict | None:
    X, Y, Z = (float(v) for v in XYZ)
    s = X + Y + Z
    d = X + 15.0 * Y + 3.0 * Z
    if not (s > 0 and d > 0):
        return None
    up, vp = 4.0 * X / d, 9.0 * Y / d
    return {"x": X / s, "y": Y / s, "u_prime": up, "v_prime": vp}


@lru_cache(maxsize=1)
def _locus_grid() -> tuple[np.ndarray, np.ndarray]:
    lam = table("cmf")[:, 0]
    return lam, table("cmf")[:, 1:4]


def planck_uv(T) -> np.ndarray:
    """CIE 1960 (u, v) of Planckian radiators at the temperatures T (1 nm summation over 360–830 nm)."""
    lam, xyz = _locus_grid()
    Ts = np.atleast_1d(np.asarray(T, dtype=float))
    M = np.stack([planck_relative(lam, t) for t in Ts])  # (nT, nλ)
    X, Y, Z = (M @ xyz).T
    d = X + 15.0 * Y + 3.0 * Z
    return np.stack([4.0 * X / d, 6.0 * Y / d], axis=-1)


def cct(XYZ) -> dict:
    """{'cct_k', 'duv'}: the nearest Planckian radiator in CIE 1960 (u, v) (module notes); cct_k is None when the
    colour is farther than 0.05 from the locus or the nearest point lies outside 1000–100 000 K."""
    c = chromaticity(XYZ)
    if c is None:
        return {"cct_k": None, "duv": None}
    u, v = c["u_prime"], 2.0 * c["v_prime"] / 3.0
    lo, hi = CCT_RANGE_K
    grid = np.geomspace(lo, hi, 400)
    uv = planck_uv(grid)
    d2 = (uv[:, 0] - u) ** 2 + (uv[:, 1] - v) ** 2
    i = int(np.argmin(d2))
    if i in (0, len(grid) - 1):
        return {"cct_k": None, "duv": None}

    def dist2(m):  # in mireds, where the locus is smoother
        p = planck_uv(1e6 / m)[0]
        return (p[0] - u) ** 2 + (p[1] - v) ** 2

    m_lo, m_hi = 1e6 / grid[i + 1], 1e6 / grid[i - 1]
    r = minimize_scalar(dist2, bounds=(m_lo, m_hi), method="bounded", options={"xatol": 1e-9})
    T = 1e6 / float(r.x)
    p = planck_uv(T)[0]
    duv = math.copysign(math.sqrt(dist2(float(r.x))), v - p[1])
    return {"cct_k": T if abs(duv) <= DUV_LIMIT else None, "duv": duv}


@lru_cache(maxsize=1)
def srgb_matrix() -> np.ndarray:
    """XYZ → linear sRGB (IEC 61966-2-1), from the primaries and the D65 white with Y = 1."""
    P = np.array([[x / y, 1.0, (1.0 - x - y) / y] for x, y in SRGB_PRIMARIES]).T  # columns: XYZ of R, G, B (Y = 1)
    xw, yw = SRGB_WHITE
    W = np.array([xw / yw, 1.0, (1.0 - xw - yw) / yw])
    S = np.linalg.solve(P, W)
    return np.linalg.inv(P * S[None, :])


def srgb_encode(linear: np.ndarray) -> np.ndarray:
    """IEC 61966-2-1 transfer function of linear values in 0…1."""
    a = np.clip(linear, 0.0, 1.0)
    return np.where(a <= 0.0031308, 12.92 * a, 1.055 * np.power(a, 1.0 / 2.4) - 0.055)


# ---------------------------------------------------------------- spectra
def line_spectrum(lam_um, power_w) -> dict:
    """Photometric and colorimetric quantities of lines (wavelength µm, power W)."""
    lam_nm = np.asarray(lam_um, dtype=float) * 1000.0
    P = np.asarray(power_w, dtype=float)
    XYZ = (P[:, None] * cmf(lam_nm)).sum(0) if len(P) else np.zeros(3)
    return quantities(XYZ, float(P.sum()), float(KM_SCOTOPIC * (P * v_scotopic(lam_nm)).sum()), float(np.min(lam_nm)) if len(P) else None, float(np.max(lam_nm)) if len(P) else None)


def quantities(XYZ, power_w: float, scotopic_lm: float, lam_min_nm: float | None = None, lam_max_nm: float | None = None) -> dict:
    flux = KM * float(XYZ[1])
    out = {
        "power_w": power_w,
        "luminous_flux_lm": flux,
        "scotopic_flux_lm": scotopic_lm,
        "luminous_efficacy_lm_per_w": flux / power_w if power_w > 0 else None,
        "XYZ_w": [float(v) for v in XYZ],
        "chromaticity": chromaticity(XYZ),
        **cct(XYZ),
        "srgb": None,
        "notes": [],
    }
    if out["chromaticity"] is None:
        out["notes"].append("No visible light (360–830 nm): no luminous flux and no colour")
    else:
        rgb = srgb_matrix() @ np.asarray(XYZ, dtype=float)
        out["srgb_out_of_gamut"] = bool(np.any(rgb < -1e-12))
        rgb = np.clip(rgb, 0.0, None)
        if rgb.max() > 0:
            out["srgb"] = [int(round(255 * float(v))) for v in srgb_encode(rgb / rgb.max())]
        if out["cct_k"] is None and out["duv"] is not None:
            out["notes"].append(f"The colour lies {abs(out['duv']):.3f} from the Planckian locus (more than {DUV_LIMIT}): no correlated colour temperature")
    if out["chromaticity"] is not None and lam_min_nm is not None and (lam_min_nm < 360.0 or lam_max_nm > 830.0):
        out["notes"].append("Wavelengths outside 360–830 nm carry no luminous flux or colour")
    return out


def tabulated(lam_nm, spd) -> dict:
    """Quantities of a spectral distribution tabulated at 1 nm (relative units; summed over 360–830 nm)."""
    lam = np.asarray(lam_nm, dtype=float)
    S = np.asarray(spd, dtype=float)
    XYZ = (S[:, None] * cmf(lam)).sum(0)
    return quantities(XYZ, float(S.sum()), float(KM_SCOTOPIC * (S * v_scotopic(lam)).sum()))


# ---------------------------------------------------------------- detector maps
def _xy_to_XYZ(x: float, y: float) -> np.ndarray:
    return np.array([x / y, 1.0, (1.0 - x - y) / y])


def _colour_sigma(q: dict, w3: np.ndarray, rays, n_rays: int, standard_error) -> dict:
    """Standard errors of x, y, CCT and Duv of light collected from n independent source rays: each hit's linearised
    contribution, (X_i − x S_i)/S for x (S = X + Y + Z), and through the numerical gradient of CCT and Duv in (x, y)."""
    c = q["chromaticity"]
    out = {"chromaticity_sigma": None, "cct_sigma_k": None, "duv_sigma": None}
    if c is None or not len(w3) or n_rays < 2:
        return out
    S = float(w3.sum())
    si = w3.sum(1)
    cx = (w3[:, 0] - c["x"] * si) / S
    cy = (w3[:, 1] - c["y"] * si) / S
    out["chromaticity_sigma"] = {"x": standard_error(rays, cx, n_rays), "y": standard_error(rays, cy, n_rays)}
    if q["duv"] is None:
        return out
    h = 1e-5
    grads = {}
    for key in ("cct_k", "duv"):
        def f(dx, dy, key=key):
            r = cct(_xy_to_XYZ(c["x"] + dx, c["y"] + dy))
            return r[key] if key == "duv" else (1e6 / r["cct_k"] if r["cct_k"] else None)  # CCT through mireds

        vals = [f(h, 0), f(-h, 0), f(0, h), f(0, -h)]
        if any(v is None for v in vals):
            continue
        grads[key] = ((vals[0] - vals[1]) / (2 * h), (vals[2] - vals[3]) / (2 * h))
    if "duv" in grads:
        gx, gy = grads["duv"]
        out["duv_sigma"] = standard_error(rays, gx * cx + gy * cy, n_rays)
    if "cct_k" in grads and q["cct_k"]:
        gx, gy = grads["cct_k"]
        s_mired = standard_error(rays, gx * cx + gy * cy, n_rays)
        out["cct_sigma_k"] = q["cct_k"] ** 2 / 1e6 * s_mired
    return out


def detector_maps(x, y, power_w, lam_um, rays, n_rays, ex, ey, area_mm2: float, standard_error) -> dict:
    """Illuminance (lux), luminous flux and the colour of the light on a detector from its hits: the maps of X, Y, Z
    per pixel area (W/mm², rows along y like the irradiance), the illuminance K_m Y in lux and a true-colour image
    (linear sRGB of every pixel with one exposure for the map, its brightest channel 1, clipped to the gamut and
    encoded; rows along y)."""
    lam_nm = np.asarray(lam_um, dtype=float) * 1000.0
    P = np.asarray(power_w, dtype=float)
    w3 = P[:, None] * cmf(lam_nm) if len(P) else np.zeros((0, 3))
    lm = KM * w3[:, 1] if len(P) else np.zeros(0)
    px_area_m2 = (ex[1] - ex[0]) * (ey[1] - ey[0]) * 1e-6
    maps = [np.histogram2d(y, x, bins=[ey, ex], weights=w3[:, k])[0] if len(P) else np.zeros((len(ey) - 1, len(ex) - 1)) for k in range(3)]
    lux = KM * maps[1] / px_area_m2
    XYZ = w3.sum(0) if len(P) else np.zeros(3)
    q = quantities(XYZ, float(P.sum()), float(KM_SCOTOPIC * (P * v_scotopic(lam_nm)).sum()) if len(P) else 0.0, float(lam_nm.min()) if len(P) else None, float(lam_nm.max()) if len(P) else None)
    flux = q["luminous_flux_lm"]
    out = {
        **q,
        **_colour_sigma(q, w3, rays, n_rays, standard_error),
        "luminous_flux_sigma_lm": standard_error(rays, lm, n_rays) if len(P) else 0.0,
        "average_illuminance_lux": flux / (area_mm2 * 1e-6) if area_mm2 > 0 else None,
        "peak_illuminance_lux": float(lux.max()) if lux.size else 0.0,
        "illuminance_lux": lux.tolist(),
        "xyz_w_mm2": [(m / (px_area_m2 * 1e6)).tolist() for m in maps],
    }
    # true colour: linear sRGB per pixel, one exposure for the map (its brightest channel is 1), clipped to the gamut
    rgb = np.einsum("ij,jyx->yxi", srgb_matrix(), np.stack(maps))
    out_of_gamut = float(((rgb < -1e-12).any(-1) & (maps[1] > 0)).sum()) / max(1, int((maps[1] > 0).sum()))
    rgb = np.clip(rgb, 0.0, None)
    top = float(rgb.max())
    out["colour_image"] = np.round(255 * srgb_encode(rgb / top)).astype(int).tolist() if top > 0 else None
    out["colour_image_out_of_gamut"] = out_of_gamut
    return out
