"""Wavefront (OPD) analysis against the reference sphere, and Zernike fitting.

Reference sphere
----------------
For each field and wavelength the reference sphere is centred on the chief
ray's intersection C with the image surface and passes through the point E
where the chief ray crosses the (paraxial) exit-pupil plane. Each ray's optical
path is extended from the image surface along the ray to that sphere (virtual
propagation in image space), giving OPL_ref(ray).

Sign convention (Welford): W = OPL_ref(chief) - OPL_ref(ray), so a wavefront
that is *ahead* of the reference sphere is positive and an undercorrected
positive lens has W(edge) = +S_I/8 > 0 at the paraxial focus (validated).

Values are reported in waves of the analysis wavelength. Rays that fail or are
vignetted are excluded (masked), never extrapolated.
"""

from __future__ import annotations

import math

import numpy as np

from ..paraxial import compute_pupil, paraxial_data
from ..raytrace import trace_pupil
from ..system import CompiledSystem, NotApplicable, SystemError_

PLANE_REFERENCE_RADIUS = 1e9  # mm; beyond this the reference is treated as a plane


def _image_space(cs: CompiledSystem, res):
    img = cs.n_surfaces - 1
    fr = cs.frames[img]
    P = res.local[:, img, :]
    D = fr.to_local_dirs(res.dirs)
    return P, D


def reference_geometry(cs: CompiledSystem, wl: int, field, pupil=None):
    """Return (C, E, R, chief_opl_ref, n_img) for one field/wavelength in image-local coordinates."""
    pupil = pupil or compute_pupil(cs)
    ch = trace_pupil(cs, wl, field, np.array([0.0]), np.array([0.0]), pupil, clip=False)
    if not ch.ok[0]:
        raise SystemError_("The chief ray fails for this field; no wavefront reference can be defined")
    P, D = _image_space(cs, ch)
    C = P[0]
    d = D[0]
    try:
        pd = paraxial_data(cs, wl)
        z_xp = pd.exit_pupil_position
    except Exception:
        z_xp = None
    n_img = float(cs.n_after[wl, cs.n_surfaces - 2])
    if z_xp is None or not math.isfinite(z_xp) or abs(z_xp) > PLANE_REFERENCE_RADIUS or abs(d[2]) < 1e-12:
        return C, None, math.inf, float(ch.opl[0]), n_img
    t = (z_xp - C[2]) / d[2]
    E = C + t * d
    R = float(np.linalg.norm(E - C))
    # optical path from the image point back to E along the chief ray (t is signed)
    chief_ref = float(ch.opl[0]) + n_img * t
    return C, E, R, chief_ref, n_img


def opl_to_reference(cs: CompiledSystem, res, C, E, R, n_img):
    """OPL of each ray up to the reference sphere (NaN for failed rays)."""
    P, D = _image_space(cs, res)
    opl = res.opl.copy()
    out = np.full(len(opl), np.nan)
    ok = res.ok
    if E is None:  # plane reference perpendicular to the chief ray direction through C
        return out
    w = P - C
    b = np.einsum("ij,ij->i", D, w)
    c = np.einsum("ij,ij->i", w, w) - R * R
    disc = b * b - c
    good = ok & (disc >= 0)
    sq = np.sqrt(np.where(good, disc, 0.0))
    s1 = -b - sq
    s2 = -b + sq
    X1 = P + s1[:, None] * D
    X2 = P + s2[:, None] * D
    pick1 = np.linalg.norm(X1 - E, axis=1) <= np.linalg.norm(X2 - E, axis=1)
    s = np.where(pick1, s1, s2)
    out[good] = opl[good] + n_img * s[good]
    return out


def wavefront_samples(cs: CompiledSystem, wl: int, field, px: np.ndarray, py: np.ndarray, pupil=None, vignetting: bool = False):
    """W in waves at normalised pupil points (NaN where rays fail/vignette); vignetting=True samples the
    pupil through the field's vignetting factors (OPD fans)."""
    pupil = pupil or compute_pupil(cs)
    C, E, R, chief_ref, n_img = reference_geometry(cs, wl, field, pupil)
    if E is None:
        raise NotApplicable("Exit pupil at infinity (image-space telecentric): spherical OPD reference undefined")
    res = trace_pupil(cs, wl, field, px, py, pupil, clip=True, vignetting=vignetting)
    oplr = opl_to_reference(cs, res, C, E, R, n_img)
    lam_mm = float(cs.wavelengths[wl]) * 1e-3
    W = (chief_ref - oplr) / lam_mm
    return W, res, {"reference_center_mm": C.tolist(), "reference_radius_mm": R, "exit_pupil_point_mm": E.tolist()}


# ----------------------------------------------------------------------
# Zernike polynomials (Fringe / University of Arizona ordering, peak-normalised)
# ----------------------------------------------------------------------


def fringe_nm(count: int = 37) -> list[tuple[int, int]]:
    """(n, m) for Fringe indices 1..count; m > 0 cos term, m < 0 sin term."""
    out: list[tuple[int, int]] = []
    s = 0
    while len(out) < 36:
        for m in range(s, -1, -1):
            n = 2 * s - m
            if m == 0:
                out.append((n, 0))
            else:
                out.append((n, m))
                out.append((n, -m))
        s += 1
    out = out[:36]
    out.append((12, 0))
    return out[:count]


def radial(n: int, m: int, rho: np.ndarray) -> np.ndarray:
    m = abs(m)
    R = np.zeros_like(rho)
    for k in range((n - m) // 2 + 1):
        c = (-1) ** k * math.factorial(n - k) / (math.factorial(k) * math.factorial((n + m) // 2 - k) * math.factorial((n - m) // 2 - k))
        R = R + c * rho ** (n - 2 * k)
    return R


def zernike(n: int, m: int, rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    R = radial(n, m, rho)
    if m > 0:
        return R * np.cos(m * theta)
    if m < 0:
        return R * np.sin(-m * theta)
    return R


ZERNIKE_NAMES = {
    (0, 0): "piston",
    (1, 1): "tilt x",
    (1, -1): "tilt y",
    (2, 0): "defocus",
    (2, 2): "astigmatism 0°",
    (2, -2): "astigmatism 45°",
    (3, 1): "coma x",
    (3, -1): "coma y",
    (4, 0): "spherical",
    (3, 3): "trefoil x",
    (3, -3): "trefoil y",
}


def fit_zernike(px: np.ndarray, py: np.ndarray, W: np.ndarray, count: int = 37) -> dict:
    """Least-squares Fringe Zernike fit over valid samples (unit pupil)."""
    ok = np.isfinite(W)
    rho = np.hypot(px[ok], py[ok])
    th = np.arctan2(py[ok], px[ok])
    nm = fringe_nm(count)
    A = np.stack([zernike(n, m, rho, th) for n, m in nm], axis=1)
    coef, *_ = np.linalg.lstsq(A, W[ok], rcond=None)
    fit = A @ coef
    resid = W[ok] - fit
    return {
        "convention": "Fringe (peak-normalised), waves",
        "terms": [{"index": j + 1, "n": n, "m": m, "name": ZERNIKE_NAMES.get((n, m), ""), "value": float(c)} for j, ((n, m), c) in enumerate(zip(nm, coef))],
        "fit_residual_rms_waves": float(np.sqrt(np.mean(resid**2))) if resid.size else None,
    }


def pupil_grid(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """n x n sample centres over [-1, 1]^2 and the in-circle mask."""
    v = -1.0 + (np.arange(n) + 0.5) * 2.0 / n
    X, Y = np.meshgrid(v, v)
    inside = X**2 + Y**2 <= 1.0
    return X, Y, inside


def wavefront_map(cs: CompiledSystem, field: int, wl: int | None = None, grid: int = 64, zernike_terms: int = 37) -> dict:
    wl = cs.model.primary_wavelength if wl is None else wl
    pupil = compute_pupil(cs)
    X, Y, inside = pupil_grid(grid)
    W = np.full(X.shape, np.nan)
    Wi, res, ref = wavefront_samples(cs, wl, field, X[inside], Y[inside], pupil)
    W[inside] = Wi
    valid = np.isfinite(W)
    if not np.any(valid):
        raise SystemError_("No valid rays for the wavefront map")
    wv = W[valid]
    wv0 = wv - wv.mean()
    rms = float(np.sqrt(np.mean(wv0**2)))
    pv = float(wv.max() - wv.min())
    z = fit_zernike(X[valid], Y[valid], W[valid], zernike_terms)
    marechal = math.exp(-((2 * math.pi * rms) ** 2))
    n_inside = int(inside.sum())
    return {
        "field": field,
        "wavelength": wl,
        "wavelength_um": float(cs.wavelengths[wl]),
        "grid": grid,
        "x": X[0].tolist(),
        "y": Y[:, 0].tolist(),
        "map_waves": np.where(valid, W, np.nan).tolist(),
        "rms_waves": rms,
        "pv_waves": pv,
        "strehl_marechal": marechal,
        "valid_fraction": float(valid.sum() / n_inside),
        "zernike": z,
        "reference": ref,
        "units": {"map": "waves", "pupil": "normalised entrance pupil"},
        "method": "Real-ray OPD to the reference sphere (centred on the chief-ray image point, through the paraxial exit pupil); "
        "Strehl by the Maréchal approximation exp(-(2πσ)²), meaningful for σ ≲ 0.1 waves",
    }


def opd_fan(cs: CompiledSystem, samples: int = 41, fields: list[int] | None = None) -> dict:
    """OPD fans: tangential through pupil points p u along the field's azimuth u (fields.tangential_direction, as the
    ray fans), sagittal through p s with s = (uy, -ux); for fields along +y the py and px fans."""
    from ..fields import tangential_direction

    pupil = compute_pupil(cs)
    p = np.linspace(-1.0, 1.0, samples)
    fields = list(range(len(cs.model.fields))) if fields is None else fields
    out = []
    for f in fields:
        ux, uy = tangential_direction(cs.model, f)
        sx, sy = uy, -ux
        per = []
        for w in range(len(cs.wavelengths)):
            try:
                # + 0.0: no negative zeros in the pupil coordinates
                Wt, _, _ = wavefront_samples(cs, w, f, p * ux + 0.0, p * uy + 0.0, pupil, vignetting=True)
                Ws, _, _ = wavefront_samples(cs, w, f, p * sx + 0.0, p * sy + 0.0, pupil, vignetting=True)
                per.append({"wavelength": w, "tangential_waves": Wt.tolist(), "sagittal_waves": Ws.tolist()})
            except SystemError_ as exc:
                per.append({"wavelength": w, "tangential_waves": [None] * samples, "sagittal_waves": [None] * samples, "error": str(exc)})
        out.append({"field": f, "field_value": [cs.model.fields[f].x, cs.model.fields[f].y], "direction": [ux, uy], "per_wavelength": per})
    return {
        "pupil": p.tolist(),
        "fields": out,
        "units": {"pupil": "normalised", "opd": "waves (of each wavelength)"},
        "method": "Real-ray OPD relative to the reference sphere of each wavelength's chief ray (Welford sign: W>0 = wavefront ahead); tangential fan along the field's azimuth, sagittal across it",
    }
