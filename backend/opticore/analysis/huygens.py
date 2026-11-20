"""Huygens point-spread function (scalar wavelet summation).

Every traced ray k defines a secondary source Q_k on the exit-pupil
reference sphere (centre C = chief-ray image point, through the exit pupil;
see wavefront.py) with optical path L_k from the object to Q_k. The scalar
field at a point r of the image surface is the sum of spherical wavelets

    U(r) = sum_k a_k exp(i k0 [L_k + n |r - Q_k|]) / |r - Q_k|,   k0 = 2 pi / lambda0

(obliquity factor ~ 1 for the small angles subtended at the image point).
The rays sample the entrance pupil uniformly, so each carries the same
power; the area dS_k = R^2 dOmega_k it represents on the reference sphere
follows from the Jacobian of the sphere points over the pupil grid (the
source density on the sphere, not the ray directions, which aberrations
bunch into caustics). Power conservation then gives a_k = sqrt(dS_k) (times
the ray's amplitude transmission when `transmission` is on); the common R
factor cancels in the normalisation.

Unlike the FFT PSF this evaluates the field on the actual (possibly tilted)
image surface or a plane displaced from it, with the true ray directions:
off-axis anamorphism, image-plane tilt, defocus and pupil distortion are
included. Normalisation: the same samples with all phases equal (L_k + n R
constant) give the diffraction-limited reference peak U0 = sum a_k / R, so
the reported PSF is |U|^2 / |U0|^2 and its maximum is the Strehl ratio.

Limits: scalar theory (no polarisation / vector high-NA effects); the
wavelets start on the reference sphere (Fresnel number >> 1 assumed);
sampling checks are reported (pupil phase step between neighbouring rays,
and the image window against the alias period lambda / (n dalpha) of the
discrete direction sampling). Validated in tests/test_huygens.py against
the Airy pattern, the analytic on-axis defocus law and a tilted image plane.
"""

from __future__ import annotations

import math

import numpy as np

from ..paraxial import compute_pupil, paraxial_data
from ..raytrace import trace_pupil
from ..system import CompiledSystem, NotApplicable, SystemError_
from .wavefront import _image_space, pupil_grid, reference_geometry

CHUNK = 1 << 21  # complex evaluations per block (memory bound)


def _sphere_points(P: np.ndarray, D: np.ndarray, C: np.ndarray, E: np.ndarray, R: float):
    """Signed distance s along each ray from its image-surface point to the reference sphere, and the point."""
    w = P - C
    b = np.einsum("ij,ij->i", D, w)
    c = np.einsum("ij,ij->i", w, w) - R * R
    disc = b * b - c
    good = disc >= 0
    sq = np.sqrt(np.where(good, disc, 0.0))
    s1, s2 = -b - sq, -b + sq
    X1 = P + s1[:, None] * D
    X2 = P + s2[:, None] * D
    pick1 = np.linalg.norm(X1 - E, axis=1) <= np.linalg.norm(X2 - E, axis=1)
    s = np.where(pick1, s1, s2)
    Q = np.where(pick1[:, None], X1, X2)
    return s, Q, good


def huygens_psf(
    cs: CompiledSystem,
    field: int = 0,
    wavelength: int | None = None,
    pupil_samples: int = 64,
    image_samples: int = 65,
    image_delta_um: float | None = None,
    defocus_mm: float = 0.0,
    transmission: bool = False,
) -> dict:
    if not 16 <= pupil_samples <= 256:
        raise ValueError("pupil_samples must be within 16…256")
    if not 16 <= image_samples <= 256:
        raise ValueError("image_samples must be within 16…256")
    wl = cs.wl_index(wavelength)
    lam_um = float(cs.wavelengths[wl])
    lam_mm = lam_um * 1e-3
    pupil = compute_pupil(cs, cs.model.primary_wavelength)  # the aperture at the primary wavelength, as every launch uses
    C, E, R, chief_ref, n_img = reference_geometry(cs, wl, field, pupil)
    if E is None:
        raise NotApplicable("Exit pupil at infinity (image-space telecentric): the spherical Huygens reference is undefined")

    X, Y, inside = pupil_grid(pupil_samples)
    res = trace_pupil(cs, wl, field, X[inside], Y[inside], pupil, clip=True, fresnel=transmission)
    P, D = _image_space(cs, res)
    ok = res.ok.copy()
    s, Q, good = _sphere_points(np.nan_to_num(P), np.nan_to_num(D), C, E, R)
    ok &= good
    L = res.opl + n_img * s  # optical path to the reference sphere

    # area element on the reference sphere per ray: the wavelet sources are the ray
    # points Q_k, so their density (not the ray directions, which aberrations
    # bunch into caustics) sets the amplitude. Q = C + R qhat; dS = R^2 dOmega(qhat).
    N = pupil_samples
    alpha = np.full((N, N), np.nan)
    beta = np.full((N, N), np.nan)
    gam = np.full((N, N), np.nan)
    qh = np.where(ok[:, None], (Q - C) / R, np.nan)
    alpha[inside], beta[inside], gam[inside] = qh[:, 0], qh[:, 1], qh[:, 2]
    h = 2.0 / N

    def grad(a):
        gx = np.full_like(a, np.nan)
        gy = np.full_like(a, np.nan)
        c = (a[:, 2:] - a[:, :-2]) / (2 * h)
        gx[:, 1:-1] = c
        fwd = (a[:, 1:] - a[:, :-1]) / h  # one-sided at the rim
        gx[:, :-1] = np.where(np.isnan(gx[:, :-1]), fwd, gx[:, :-1])
        gx[:, 1:] = np.where(np.isnan(gx[:, 1:]), fwd, gx[:, 1:])
        c = (a[2:, :] - a[:-2, :]) / (2 * h)
        gy[1:-1, :] = c
        fwd = (a[1:, :] - a[:-1, :]) / h
        gy[:-1, :] = np.where(np.isnan(gy[:-1, :]), fwd, gy[:-1, :])
        gy[1:, :] = np.where(np.isnan(gy[1:, :]), fwd, gy[1:, :])
        return gx, gy

    ax, ay = grad(alpha)
    bx, by = grad(beta)
    with np.errstate(invalid="ignore", divide="ignore"):
        dOm = np.abs(ax * by - ay * bx) / np.abs(gam) * h * h  # dOmega = d(qx) d(qy) / |qz| on the unit sphere
    dOm_i = dOm[inside]
    ok &= np.isfinite(dOm_i) & (dOm_i > 0)
    if ok.sum() < 16:
        raise SystemError_("Too few valid rays for a Huygens PSF")
    amp = np.sqrt(dOm_i[ok])
    if transmission:
        amp = amp * np.sqrt(np.clip(res.intensity[ok], 0.0, None))
    Lk = L[ok]
    Qk = Q[ok]
    k0 = 2 * math.pi / lam_mm

    # image window: default covers the geometric spot and a few Airy rings
    try:
        fn = float(paraxial_data(cs, wl).working_fnum)
    except Exception:  # noqa: BLE001
        fn = float("nan")
    xy = P[res.ok][:, :2] if res.ok.any() else np.zeros((1, 2))
    geo = float(np.max(np.hypot(xy[:, 0] - C[0], xy[:, 1] - C[1]))) * 1e3 if len(xy) else 0.0
    airy = 1.22 * lam_um * fn if math.isfinite(fn) and fn > 0 else 0.0
    if image_delta_um is None:
        half = max(4.0 * airy, 1.25 * geo, 4.0 * lam_um)
        image_delta_um = 2 * half / (image_samples - 1)
    dx_mm = image_delta_um * 1e-3
    u = (np.arange(image_samples) - (image_samples - 1) / 2) * dx_mm
    GX, GY = np.meshgrid(u, u)
    Rpts = np.column_stack([C[0] + GX.ravel(), C[1] + GY.ravel(), np.full(GX.size, C[2] + defocus_mm)])

    def field_at(points, phase_path):
        out = np.zeros(len(points), dtype=complex)
        step = max(1, CHUNK // max(1, len(Qk)))
        for a0 in range(0, len(points), step):
            pts = points[a0 : a0 + step]
            d = np.linalg.norm(pts[:, None, :] - Qk[None, :, :], axis=2)
            ph = k0 * (phase_path[None, :] + n_img * (d - R))
            out[a0 : a0 + step] = (amp[None, :] * np.exp(1j * ph) / d).sum(axis=1)
        return out

    Lrel = Lk - chief_ref  # remove the large common path (phase reference only)
    U = field_at(Rpts, Lrel)
    I = np.abs(U) ** 2
    U0 = float(amp.sum() / R)  # unaberrated reference peak (all wavelets in phase at C)
    psf_n = (I / U0**2).reshape(GX.shape)
    # Strehl ratio: refine the peak continuously (it rarely falls on a grid sample)
    kmax = int(np.argmax(psf_n))
    best = np.array([GX.ravel()[kmax], GY.ravel()[kmax]])
    best_I = float(psf_n.ravel()[kmax])
    step = dx_mm
    offs = np.array([(i, j) for i in (-1, 0, 1) for j in (-1, 0, 1)], dtype=float)
    for _ in range(12):
        cand = best[None, :] + step * offs
        pts = np.column_stack([C[0] + cand[:, 0], C[1] + cand[:, 1], np.full(len(cand), C[2] + defocus_mm)])
        Ic = np.abs(field_at(pts, Lrel)) ** 2 / U0**2
        j = int(np.argmax(Ic))
        if Ic[j] > best_I:
            best, best_I = cand[j], float(Ic[j])
        else:
            step *= 0.5
    strehl = best_I

    # centroid and encircled energy on the grid
    tot = psf_n.sum()
    cx = float((psf_n * GX).sum() / tot) * 1e3
    cy = float((psf_n * GY).sum() / tot) * 1e3
    r = np.hypot(GX * 1e3 - cx, GY * 1e3 - cy).ravel()
    order = np.argsort(r)
    cum = np.cumsum(psf_n.ravel()[order]) / tot
    radii = np.linspace(0, float(r.max()) / math.sqrt(2), 101)
    ee = np.interp(radii, r[order], cum)

    # sampling checks
    warnings: list[str] = []
    Wgrid = np.full((N, N), np.nan)
    Wi = np.full(inside.sum(), np.nan)
    Wi[ok] = (chief_ref - Lk) / lam_mm
    Wgrid[inside] = Wi
    dWx = np.nanmax(np.abs(np.diff(Wgrid, axis=1))) if np.isfinite(Wgrid).sum() > 1 else 0.0
    dWy = np.nanmax(np.abs(np.diff(Wgrid, axis=0))) if np.isfinite(Wgrid).sum() > 1 else 0.0
    max_step = float(np.nanmax([dWx, dWy]))
    if max_step > 0.5:
        warnings.append(f"Pupil under-sampled: the wavefront changes by up to {max_step:.2f} waves between neighbouring rays (> 0.5); increase the pupil samples")
    dal = np.nanmedian(np.abs(np.concatenate([np.diff(alpha, axis=1).ravel(), np.diff(beta, axis=0).ravel()])))
    alias_um = lam_um / (n_img * dal) if dal > 0 else float("inf")
    width_um = image_delta_um * (image_samples - 1)
    if width_um > 0.9 * alias_um:
        warnings.append(f"Image window {width_um:.4g} µm exceeds ~90 % of the alias period {alias_um:.4g} µm of the pupil sampling; increase the pupil samples or reduce the window")
    if geo > 0.5 * width_um:
        warnings.append("The geometric spot extends beyond the image window; energy outside it is not shown")
    return {
        "field": field,
        "wavelength": wl,
        "wavelength_um": lam_um,
        "strehl": strehl,
        "peak_um": (best * 1e3).tolist(),
        "x_um": (u * 1e3).tolist(),
        "y_um": (u * 1e3).tolist(),
        "psf": psf_n.tolist(),
        "centroid_um": [cx, cy],
        "chief_image_mm": C[:2].tolist(),
        "encircled_energy": {"radius_um": radii.tolist(), "fraction": ee.tolist()},
        "airy_radius_um": airy if airy else None,
        "working_fnum": fn if math.isfinite(fn) else None,
        "reference_radius_mm": R,
        "defocus_mm": defocus_mm,
        "sampling": {"pupil_samples": pupil_samples, "rays": int(ok.sum()), "image_samples": image_samples, "image_delta_um": image_delta_um, "max_pupil_phase_step_waves": max_step, "alias_period_um": alias_um},
        "warnings": warnings,
        "units": {"psf": "relative to the diffraction-limited peak", "coordinates": "µm on the image surface, about the chief-ray image point"},
        "method": "Huygens PSF: scalar summation of spherical wavelets from the real-ray exit-pupil reference sphere to the image surface (exact distances, solid-angle ray weights); normalised to the unaberrated sum of the same samples; Strehl at the continuously refined peak",
    }
