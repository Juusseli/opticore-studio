"""Scalar diffraction: FFT point-spread function, Strehl ratio, MTF, encircled energy.

Model and assumptions (stated in every result):
  * Scalar Fraunhofer diffraction from the exit pupil; uniform pupil amplitude
    inside the traced aperture (vignetted / failed rays are opaque).
  * Pupil function P = A exp(-i 2 pi W) sampled on an N x N grid over the
    normalised entrance pupil (pupil aberrations neglected).
  * Image-plane sampling dx = lambda * F#_w / Q with F#_w the paraxial working
    F-number and Q = padded size / N. Off-axis anamorphic pupil scaling is not
    modelled.
  * Strehl ratio = PSF peak / peak of the unaberrated PSF of the same aperture.
  * Sampling (reported as warnings, as in the Huygens PSF): the pupil phase must
    change by less than 0.5 wave between neighbouring samples, else the pupil
    function aliases; and the PSF must fit the periodic FFT window of width
    N lambda F#_w about the chief ray (geometric extent + one Airy radius),
    else it wraps around. Both mean: raise the grid.

Tangential / sagittal MTF: the tangential (meridional) cut runs along the field
direction u, the unit vector of the field components as the trace uses them
((tan x, tan y) for angle fields, the heights otherwise; on axis u = +y), the
sagittal cut along s = (u_y, -u_x). The pupil is sampled on a grid rotated into
(s, u), so the OTF axes are the two cuts and a field rotated about the axis of a
rotationally symmetric system gives the same T and S. Lateral colour and the
geometric spot are projected on u and s. Pupil and image axes are taken as
parallel (as in the FFT PSF). A square pixel of width w along a cut at angle phi
to x has the MTF sinc(nu w cos phi) sinc(nu w sin phi) (pixel_mtf_along).

Validated against the analytic diffraction-limited MTF of a circular pupil
(2/pi)(phi - cos phi sin phi) and the Airy pattern (tests/test_diffraction.py);
field rotation and sampling warnings in tests/test_wave_regressions.py.
"""

from __future__ import annotations

import math

import numpy as np

from ..paraxial import compute_pupil, paraxial_data
from ..raytrace import pupil_pattern, trace_pupil
from ..system import CompiledSystem, NotApplicable, SystemError_
from .wavefront import pupil_grid, wavefront_samples


def _working_fnum(cs: CompiledSystem, wl: int) -> float:
    pd = paraxial_data(cs, wl)
    if not pd.working_fnum or not math.isfinite(pd.working_fnum):
        raise NotApplicable("Working F/# undefined (afocal or collimated image space); diffraction analysis needs a focused image")
    return float(pd.working_fnum)


def field_directions(cs: CompiledSystem, field) -> tuple[np.ndarray, np.ndarray]:
    """(u, s): unit vectors of the tangential (along the field) and sagittal directions in the pupil and
    image plane. u follows the field components as the trace uses them ((tan x, tan y) for angle fields,
    heights otherwise); on axis u = +y. u and -u give the same cuts; u is taken with u_y >= 0 (u = +y
    for any field on the y axis) and s = (u_y, -u_x), so (s, u) is a proper rotation of (x, y)."""
    hx, hy = (cs.model.fields[field].x, cs.model.fields[field].y) if isinstance(field, (int, np.integer)) else field
    if cs.model.field_type == "angle":
        vx, vy = math.tan(math.radians(float(hx))), math.tan(math.radians(float(hy)))
    else:
        vx, vy = float(hx), float(hy)
    r = math.hypot(vx, vy)
    if not math.isfinite(r) or r <= 1e-12:
        u = np.array([0.0, 1.0])
    else:
        u = np.array([vx / r, vy / r])
        if u[1] < 0.0 or (u[1] == 0.0 and u[0] < 0.0):
            u = -u
    return u, np.array([u[1], -u[0]])


def _rotated(X: np.ndarray, Y: np.ndarray, frame) -> tuple[np.ndarray, np.ndarray]:
    """Global pupil coordinates of points given in the (s, u) frame (X along s, Y along u)."""
    if frame is None:
        return X, Y
    u, s_ = frame
    return X * s_[0] + Y * u[0], X * s_[1] + Y * u[1]


def _pupil_samples(cs: CompiledSystem, field, wl: int, grid: int, pupil=None, frame=None):
    """Pupil function on the grid (in the (s, u) frame when given) and its sampling diagnostics: the largest
    wavefront change between neighbouring samples (waves) and the largest x / y distance (mm, image-local)
    of a traced ray from the chief-ray image point, the centre of the FFT PSF."""
    X, Y, inside = pupil_grid(grid)
    W = np.full(X.shape, np.nan)
    px, py = _rotated(X[inside], Y[inside], frame)
    Wi, res, info = wavefront_samples(cs, wl, field, px, py, pupil)
    W[inside] = Wi
    A = np.isfinite(W).astype(float)
    # With W > 0 meaning "wavefront ahead of the reference sphere" (Welford) and
    # numpy's forward FFT kernel exp(-i 2 pi k n / M), the pupil phase is
    # -2 pi W; this places the PSF centroid at the mean real-ray position
    # (validated in tests/test_diffraction.py).
    P = A * np.exp(-1j * 2 * math.pi * np.nan_to_num(W))
    d0 = np.abs(np.diff(W, axis=0))
    d1 = np.abs(np.diff(W, axis=1))
    step = float(max(np.nanmax(d0, initial=0.0), np.nanmax(d1, initial=0.0))) if np.isfinite(W).sum() > 1 else 0.0
    ok = res.ok & np.isfinite(Wi)
    C = np.asarray(info["reference_center_mm"])[:2]
    extent = float(np.max(np.abs(res.image_xy()[ok] - C))) if ok.any() else 0.0
    return P, A, W, step, extent


def pupil_function(cs: CompiledSystem, field: int, wl: int, grid: int, pupil=None):
    P, A, W, _, _ = _pupil_samples(cs, field, wl, grid, pupil)
    return P, A, W


def _sampling_warnings(step: float, extent_um: float | None, window_um: float, airy_um: float, label: str = "") -> list[str]:
    """FFT sampling checks: pupil phase step (> 0.5 wave aliases the pupil function) and PSF wrap-around."""
    out = []
    if step > 0.5:
        out.append(f"{label}Pupil under-sampled: the wavefront changes by up to {step:.2f} waves between neighbouring samples (> 0.5); increase the grid")
    if extent_um is not None and extent_um + airy_um > 0.5 * window_um:
        out.append(f"{label}The PSF ({extent_um:.4g} µm geometric extent + Airy radius from the chief ray) exceeds the FFT window (±{0.5 * window_um:.4g} µm) and wraps around; increase the grid")
    return out


def pixel_mtf_along(nu, width_mm: float, direction) -> np.ndarray:
    """MTF |sinc(nu w cos phi) sinc(nu w sin phi)| of a square pixel of sensitive width w (sides along x
    and y; sinc x = sin(pi x) / (pi x)) along a cut in the direction (cos phi, sin phi), nu in cycles/mm."""
    nu = np.asarray(nu, dtype=float)
    return np.abs(np.sinc(nu * width_mm * float(direction[0])) * np.sinc(nu * width_mm * float(direction[1])))


def psf(cs: CompiledSystem, field: int, wl: int | None = None, grid: int = 64, pad: int = 4) -> dict:
    wl = cs.model.primary_wavelength if wl is None else wl
    if grid < 16 or pad < 2:
        raise ValueError("grid >= 16 and pad >= 2 required")
    pupil = compute_pupil(cs)
    P, A, W, step, extent = _pupil_samples(cs, field, wl, grid, pupil)
    if A.sum() == 0:
        raise SystemError_("No valid rays in the pupil")
    M = grid * pad
    big = np.zeros((M, M), dtype=complex)
    big[:grid, :grid] = P
    ref = np.zeros((M, M))
    ref[:grid, :grid] = A
    F = np.fft.fftshift(np.fft.fft2(big))
    I = np.abs(F) ** 2
    I0 = np.abs(np.fft.fftshift(np.fft.fft2(ref))) ** 2
    peak0 = I0.max()
    strehl = float(I.max() / peak0)
    fn = _working_fnum(cs, wl)
    lam_um = float(cs.wavelengths[wl])
    dx_um = lam_um * fn / pad
    coords = (np.arange(M) - M // 2) * dx_um
    norm = I / peak0  # relative to the diffraction-limited peak (Strehl at the maximum)
    # encircled energy about the PSF centroid
    tot = I.sum()
    Xc, Yc = np.meshgrid(coords, coords)
    cx = float((I * Xc).sum() / tot)
    cy = float((I * Yc).sum() / tot)
    r = np.hypot(Xc - cx, Yc - cy).ravel()
    order = np.argsort(r)
    cum = np.cumsum(I.ravel()[order]) / tot
    radii = np.linspace(0, 6 * 1.22 * lam_um * fn, 121)
    ee = np.interp(radii, r[order], cum)
    # crop the displayed window to +-6 Airy radii
    half = min(M // 2, int(math.ceil(6 * 1.22 * lam_um * fn / dx_um)))
    sl = slice(M // 2 - half, M // 2 + half + 1)
    window_um = M * dx_um  # period of the FFT PSF: grid * lambda * F#_w
    warnings = _sampling_warnings(step, extent * 1e3, window_um, 1.22 * lam_um * fn)
    return {
        "field": field,
        "wavelength": wl,
        "wavelength_um": lam_um,
        "strehl": strehl,
        "working_fnum": fn,
        "airy_radius_um": 1.22 * lam_um * fn,
        "dx_um": dx_um,
        "x_um": coords[sl].tolist(),
        "y_um": coords[sl].tolist(),
        "psf": norm[sl, sl].tolist(),
        "centroid_um": [cx, cy],
        "encircled_energy": {"radius_um": radii.tolist(), "fraction": ee.tolist()},
        "settings": {"grid": grid, "pad": pad},
        "sampling": {"max_pupil_phase_step_waves": step, "window_um": window_um, "geometric_extent_um": extent * 1e3},
        "warnings": warnings,
        "units": {"psf": "relative to diffraction-limited peak", "coordinates": "µm on the image surface"},
        "method": "FFT PSF: scalar Fraunhofer diffraction of the real-ray pupil function; uniform amplitude; paraxial working-F/# scaling; pupil aberrations and off-axis anamorphism neglected",
    }


def _otf_cuts(cs: CompiledSystem, field: int, wl: int, grid: int, pad: int, pupil, frame=None):
    """OTF along the two cuts of the (s, u) frame (field_directions; None: the x / y axes) and the largest
    pupil phase step (waves per sample)."""
    P, A, _, step, _ = _pupil_samples(cs, field, wl, grid, pupil, frame)
    M = grid * pad
    big = np.zeros((M, M), dtype=complex)
    big[:grid, :grid] = P
    I = np.abs(np.fft.fft2(big)) ** 2
    otf = np.fft.fft2(I)
    otf = otf / otf[0, 0]
    fn = _working_fnum(cs, wl)
    lam_mm = float(cs.wavelengths[wl]) * 1e-3
    dx_mm = lam_mm * fn / pad
    dnu = 1.0 / (M * dx_mm)  # cycles/mm per bin
    nmax = grid  # cutoff bin = N
    k = np.arange(nmax + 1)
    # numpy fft2 axis 0 = rows = u (the field direction), axis 1 = columns = s
    tan = otf[k % M, 0]  # frequency along u -> tangential (meridional) structure
    sag = otf[0, k % M]
    return k * dnu, tan, sag, 1.0 / (lam_mm * fn), step


def diffraction_limited_mtf(nu: np.ndarray, cutoff: float) -> np.ndarray:
    x = np.clip(nu / cutoff, 0.0, 1.0)
    phi = np.arccos(x)
    return (2 / math.pi) * (phi - np.cos(phi) * np.sin(phi))


def mtf(cs: CompiledSystem, fields: list[int] | None = None, max_frequency: float | None = None, samples: int = 64, grid: int = 64, pad: int = 4, kind: str = "diffraction") -> dict:
    """Polychromatic MTF (tangential & sagittal) per field.

    diffraction: weighted average of the complex OTF of each wavelength,
    interpolated onto a common frequency axis. geometric: Fourier transform of
    the weighted spot distribution (no diffraction). Tangential = the cut along
    the field direction u, sagittal = along s (field_directions; module notes)."""
    pupil = compute_pupil(cs)
    fields = list(range(len(cs.model.fields))) if fields is None else fields
    wls = list(range(len(cs.wavelengths)))
    weights = np.array([cs.model.wavelengths[w].weight for w in wls], dtype=float)
    if weights.sum() <= 0:
        raise ValueError("All wavelength weights are zero")
    cutoffs = []
    for w in wls:
        fn = _working_fnum(cs, w)
        cutoffs.append(1.0 / (float(cs.wavelengths[w]) * 1e-3 * fn))
    fmax = max_frequency or min(cutoffs)
    nu = np.linspace(0.0, fmax, samples)
    out = []
    warnings: list[str] = []
    for f in fields:
        u, s_ = field_directions(cs, f)
        dirs = {"tangential_direction": u.tolist(), "sagittal_direction": s_.tolist()}
        if kind == "geometric":
            # the pupil pattern turns with the field, so a rotated field samples the same rays
            px, py = _rotated(*pupil_pattern("hexapolar", 16), (u, s_))
            ts, ss, ws = [], [], []
            for w in wls:
                r = trace_pupil(cs, w, f, px, py, pupil, vignetting=True)
                xy = r.image_xy()[r.ok]
                ts.append(xy @ u)  # spot coordinate along the field (tangential)
                ss.append(xy @ s_)
                ws.append(np.full(len(xy), weights[w]))
            t = np.concatenate(ts)
            sc = np.concatenate(ss)
            wt = np.concatenate(ws)
            if wt.sum() == 0:
                raise SystemError_("No valid rays for the geometric MTF")
            wt = wt / wt.sum()
            T = np.abs(np.exp(-2j * math.pi * np.outer(nu, t)) @ wt)
            S = np.abs(np.exp(-2j * math.pi * np.outer(nu, sc)) @ wt)
            out.append({"field": f, "tangential": T.tolist(), "sagittal": S.tolist(), **dirs})
            continue
        T = np.zeros(len(nu), dtype=complex)
        S = np.zeros(len(nu), dtype=complex)
        # Each wavelength's PSF is computed about its own chief-ray image point;
        # lateral colour shifts those points, which is a linear phase on the OTF:
        # OTF_shifted(nu) = OTF(nu) exp(-2 pi i nu delta).
        prim = cs.model.primary_wavelength
        chief = {}
        for w in wls:
            ch = trace_pupil(cs, w, f, np.array([0.0]), np.array([0.0]), pupil, clip=False)
            chief[w] = ch.image_xy()[0] if ch.ok[0] else np.array([np.nan, np.nan])
        ref = chief[prim] if np.all(np.isfinite(chief[prim])) else np.zeros(2)
        step_f = 0.0
        for w in wls:
            k_nu, tan, sag, _, step = _otf_cuts(cs, f, w, grid, pad, pupil, (u, s_))
            step_f = max(step_f, step)
            Ti = np.interp(nu, k_nu, tan.real, right=0.0) + 1j * np.interp(nu, k_nu, tan.imag, right=0.0)
            Si = np.interp(nu, k_nu, sag.real, right=0.0) + 1j * np.interp(nu, k_nu, sag.imag, right=0.0)
            d = (chief[w] - ref) if np.all(np.isfinite(chief[w])) else np.zeros(2)
            T += weights[w] * Ti * np.exp(-2j * math.pi * nu * float(d @ u))
            S += weights[w] * Si * np.exp(-2j * math.pi * nu * float(d @ s_))
        T /= weights.sum()
        S /= weights.sum()
        warnings += _sampling_warnings(step_f, None, 0.0, 0.0, f"Field {f + 1}: ")
        out.append({"field": f, "tangential": np.abs(T).tolist(), "sagittal": np.abs(S).tolist(), **dirs, "max_pupil_phase_step_waves": step_f})
    # diffraction limit (polychromatic, weighted)
    dl = np.zeros_like(nu)
    for w, c in zip(wls, cutoffs):
        dl += weights[w] * diffraction_limited_mtf(nu, c)
    dl /= weights.sum()
    return {
        "frequency_cyc_per_mm": nu.tolist(),
        "fields": out,
        "diffraction_limit": dl.tolist(),
        "cutoff_cyc_per_mm": cutoffs,
        "kind": kind,
        "settings": {"grid": grid, "pad": pad, "samples": samples},
        "warnings": warnings,
        "units": {"frequency": "cycles/mm", "mtf": "modulation (0-1)"},
        "method": (
            "Diffraction MTF = |OTF|, OTF = FFT of the FFT-PSF (pupil autocorrelation) on a pupil grid turned into the field direction; tangential = cut along the field, sagittal = across it; polychromatic complex average including lateral colour (chief-ray image shifts as OTF phase); same assumptions as the FFT PSF"
            if kind == "diffraction"
            else "Geometric MTF: Fourier transform of the real-ray spot distribution (hexapolar 16 rings turned into the field direction) projected along the field (tangential) and across it (sagittal), no diffraction"
        ),
    }


def geometric_encircled_energy(cs: CompiledSystem, field: int, samples: int = 101) -> dict:
    pupil = compute_pupil(cs)
    px, py = pupil_pattern("hexapolar", 16)
    pts, wts = [], []
    for w in range(len(cs.wavelengths)):
        r = trace_pupil(cs, w, field, px, py, pupil, vignetting=True)
        xy = r.image_xy()[r.ok]
        pts.append(xy)
        wts.append(np.full(len(xy), cs.model.wavelengths[w].weight))
    P = np.concatenate(pts)
    Wt = np.concatenate(wts)
    if Wt.sum() == 0:
        raise SystemError_("No valid rays")
    c = (P * Wt[:, None]).sum(0) / Wt.sum()
    r = np.hypot(P[:, 0] - c[0], P[:, 1] - c[1]) * 1e3
    order = np.argsort(r)
    cum = np.cumsum(Wt[order]) / Wt.sum()
    radii = np.linspace(0, r.max() * 1.05 if r.max() > 0 else 1.0, samples)
    return {"radius_um": radii.tolist(), "fraction": np.interp(radii, r[order], cum).tolist(), "method": "Geometric (real-ray) encircled energy about the centroid"}
