"""Spectrometer analysis: where each wavelength images, the dispersion and the spectral resolution.

The system is traced at a sweep of wavelengths (not only its own list): for each one a hexapolar bundle of the chosen
field point (the slit point) goes to the image surface.

* Calibration: the bundle's centroid (x, y) at each wavelength. The dispersion direction u is that of the centroid
  track (first to last wavelength); the position along it is s(lambda).
* Linear dispersion D = ds/dlambda (central differences, second order at the ends too; mm/nm) and the reciprocal dispersion 1/D (nm/mm).
* Geometric spectral resolution: the spot's rms width along u, sigma, as a Gaussian-equivalent FWHM in wavelength,
  dlambda = 2.355 sigma / |D|, and the resolving power lambda / dlambda. A spot below 1 nm has no geometric
  resolution (it is set by diffraction).
* Diffraction-limited resolving power of the first linear grating (Rayleigh): R = |m| N with N = G w the lines
  across the illuminated width w (the extent of the traced rays on the grating, across its lines).

Every number comes from real rays; nothing assumes a spectrometer layout. A system whose image does not move with
wavelength raises NotApplicable. Validated in tests/test_spectrometer.py.
"""

from __future__ import annotations

import math

import numpy as np

from ..model import OpticalSystem, Wavelength
from ..paraxial import compute_pupil
from ..raytrace import pupil_pattern, trace_pupil
from ..system import NotApplicable, compile_system


FWHM_PER_SIGMA = 2.0 * math.sqrt(2.0 * math.log(2.0))
CHUNK = 23  # sweep wavelengths per compiled copy (the model allows 24; index 0 keeps the primary wavelength)


def spectrometer(system: OpticalSystem, custom_materials: list, field: int = 0, wl_min: float | None = None, wl_max: float | None = None,
                 points: int = 41, density: int = 6) -> dict:
    lam0 = float(system.wavelengths[system.primary_wavelength].value)
    values = [float(w.value) for w in system.wavelengths]
    if wl_min is None or wl_max is None:
        lo, hi = (min(values), max(values)) if max(values) > min(values) else (0.95 * lam0, 1.05 * lam0)
        wl_min = lo if wl_min is None else wl_min
        wl_max = hi if wl_max is None else wl_max
    if not (0 < wl_min < wl_max):
        raise ValueError("The wavelength range needs 0 < start < stop")
    if not 3 <= points <= 201:
        raise ValueError("3 to 201 wavelengths")
    xs = np.linspace(wl_min, wl_max, points)
    px, py = pupil_pattern("hexapolar", density)
    cen, sig_all, n_ok, chief, hits = [], [], [], [], []
    grating = None
    for k0 in range(0, points, CHUNK):
        chunk = xs[k0 : k0 + CHUNK]
        model = system.model_copy(update={"wavelengths": [Wavelength(value=lam0)] + [Wavelength(value=float(x)) for x in chunk], "primary_wavelength": 0})
        cs = compile_system(model, custom_materials)
        if grating is None:
            for j, s in enumerate(model.surfaces):
                if s.grating_frequency:
                    grating = (j, int(s.diffraction_order), float(s.grating_frequency), s.label or f"Surface {j}")
                    break
            if grating is None:
                grating = False
        pupil = compute_pupil(cs)
        for i in range(len(chunk)):
            r = trace_pupil(cs, i + 1, field, px, py, pupil, vignetting=True)
            ok = r.ok
            xy = r.image_xy()[ok]
            n_ok.append(int(ok.sum()))
            cen.append(xy.mean(0) if len(xy) else np.array([np.nan, np.nan]))
            sig_all.append(xy)
            c = trace_pupil(cs, i + 1, field, np.array([0.0]), np.array([0.0]), pupil)
            chief.append(c.image_xy()[0] if c.ok[0] else np.array([np.nan, np.nan]))
            if grating:
                loc = r.local[ok, grating[0], :2]
                hits.append(float(loc[:, 1].max() - loc[:, 1].min()) if len(loc) else float("nan"))
    C = np.array(cen)
    good = np.isfinite(C).all(axis=1)
    if good.sum() < 3:
        raise NotApplicable("Too few wavelengths reach the image for a spectrometer analysis")
    track = C[good][-1] - C[good][0]
    length = float(np.hypot(*track))
    if length < 1e-6:
        raise NotApplicable("The image does not move with wavelength (no dispersion): not a spectrometer")
    u = track / length
    s = (C - C[good][0]) @ u
    D = np.gradient(s, xs * 1000.0, edge_order=2)  # mm per nm
    sig = np.array([float(np.sqrt(np.mean(((xy - c) @ u) ** 2))) if len(xy) else np.nan for xy, c in zip(sig_all, C)])
    cross = np.array([float(np.sqrt(np.mean(((xy - c) @ np.array([-u[1], u[0]])) ** 2))) if len(xy) else np.nan for xy, c in zip(sig_all, C)])
    res_nm = [float(FWHM_PER_SIGMA * sg / abs(d)) if (np.isfinite(sg) and sg >= 1e-6 and abs(d) > 0) else None for sg, d in zip(sig, D)]
    out = {
        "field": field,
        "wavelength_um": xs.tolist(),
        "centroid_mm": [[float(a), float(b)] if np.isfinite(a) else None for a, b in C],
        "chief_mm": [[float(a), float(b)] if np.isfinite(a) else None for a, b in np.array(chief)],
        "direction": [float(u[0]), float(u[1])],
        "position_mm": [float(v) if np.isfinite(v) else None for v in s],
        "dispersion_mm_per_nm": [float(v) if np.isfinite(v) else None for v in D],
        "reciprocal_nm_per_mm": [float(1.0 / v) if (np.isfinite(v) and abs(v) > 0) else None for v in D],
        "rms_along_um": [float(v * 1e3) if np.isfinite(v) else None for v in sig],
        "rms_across_um": [float(v * 1e3) if np.isfinite(v) else None for v in cross],
        "resolution_nm": res_nm,
        "resolving_power": [float(x * 1000.0 / r) if r else None for x, r in zip(xs, res_nm)],
        "rays": int(len(px)),
        "rays_ok": n_ok,
        "span_mm": length,
    }
    notes = []
    if any(r is None for r in res_nm):
        notes.append("Where the geometric spot is below 1 nm the resolution is set by diffraction: see the grating's resolving power")
    if min(n_ok) < len(px):
        notes.append(f"Some rays are vignetted (as few as {min(n_ok)} of {len(px)} reach the image)")
    if grating:
        j, m, G, label = grating
        w = np.array(hits)
        Rg = np.abs(m) * G * w
        out["grating"] = {"surface": j, "label": label, "order": m, "lines_per_mm": G, "illuminated_mm": [float(v) if np.isfinite(v) else None for v in w],
                          "resolving_power": [float(v) if np.isfinite(v) else None for v in Rg],
                          "resolution_nm": [float(x * 1000.0 / v) if (np.isfinite(v) and v > 0) else None for x, v in zip(xs, Rg)]}
    out["notes"] = notes
    out["method"] = (f"Real rays of field {field} ({len(px)}-ray hexapolar bundle) at {points} wavelengths; centroid track, D = ds/dλ by central differences, "
                     "geometric resolution 2.355 σ / |D| (σ the rms spot width along the dispersion)"
                     + ("; grating resolving power |m| G w (Rayleigh) over the illuminated width w" if grating else ""))
    return out
