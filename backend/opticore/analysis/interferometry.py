"""Interferometric testing: the interferogram of the system's wavefront and its phase-shifting recovery.

The test arm is the system as traced: a mirror at its centre of curvature (the source and the return focus at the
object and image points), or the transmitted wavefront of a lens in a Mach-Zehnder. With passes = 2 the system is
traversed twice via a perfect return mirror at its focus (a lens tested in a Twyman-Green with a return sphere), which
doubles the wavefront error. The reference arm is a perfect sphere centred on the image point (the reference sphere of
the wavefront map, analysis/wavefront.py), tilted by the requested number of fringes.

On the normalised pupil (x, y in -1 ... 1):

    phi(x, y) = 2 pi (passes W(x, y) + t_x x / 2 + t_y y / 2),    I = (1 + V cos phi) / 2

W the wavefront error in waves at the test wavelength, t_x, t_y the tilt fringes across the pupil diameter, V the
fringe visibility.

Phase shifting: N >= 3 frames with the reference shifted by d_k = 2 pi k / N. Then

    phi = atan2(-sum I_k sin d_k, sum I_k cos d_k)

which is exact for equal steps. The wrapped phase is unwrapped by a flood fill from the pupil centre. This needs less
than pi between neighbouring pixels: the largest step of the true phase is reported, and above 0.9 pi the recovery is
flagged as undersampled. The carrier is then removed and the result divided by the passes, giving the recovered
wavefront, which is compared with W after removing piston. Validated in tests/test_interferometry.py.
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np

from ..system import CompiledSystem
from .wavefront import wavefront_map

STEP_LIMIT = 0.9 * math.pi


def _wrap(a: np.ndarray) -> np.ndarray:
    return (a + math.pi) % (2 * math.pi) - math.pi


def unwrap_flood(wrapped: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Unwrap a 2D phase map over the valid pixels by a breadth-first flood fill from the valid pixel nearest the
    centre (4-neighbours); pixels not connected to it stay NaN."""
    ny, nx = wrapped.shape
    out = np.full(wrapped.shape, np.nan)
    if not valid.any():
        return out
    iy, ix = np.nonzero(valid)
    k = int(np.argmin((iy - (ny - 1) / 2) ** 2 + (ix - (nx - 1) / 2) ** 2))
    start = (int(iy[k]), int(ix[k]))
    out[start] = wrapped[start]
    q = deque([start])
    while q:
        i, j = q.popleft()
        for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if 0 <= a < ny and 0 <= b < nx and valid[a, b] and np.isnan(out[a, b]):
                out[a, b] = out[i, j] + _wrap(wrapped[a, b] - wrapped[i, j])
                q.append((a, b))
    return out


def phase_shift(frames: np.ndarray) -> np.ndarray:
    """Wrapped phase from N equally stepped frames (axis 0), steps 2 pi k / N."""
    n = frames.shape[0]
    d = 2 * math.pi * np.arange(n) / n
    s = np.tensordot(np.sin(d), frames, axes=1)
    c = np.tensordot(np.cos(d), frames, axes=1)
    return np.arctan2(-s, c)


def interferogram(cs: CompiledSystem, field: int = 0, wl: int | None = None, grid: int = 128, passes: int = 1, tilt_x: float = 0.0, tilt_y: float = 0.0,
                  visibility: float = 1.0, phase_steps: int = 4) -> dict:
    """The interferogram of the wavefront and, with phase_steps >= 3, the wavefront recovered by phase shifting."""
    if passes not in (1, 2):
        raise ValueError("passes must be 1 or 2")
    if not 0.0 < visibility <= 1.0:
        raise ValueError("The visibility must lie in (0, 1]")
    if phase_steps and phase_steps < 3:
        raise ValueError("Phase shifting needs at least 3 frames (or 0 for none)")
    w = wavefront_map(cs, field, wl, grid, 15)
    W = np.array(w["map_waves"], float)
    x = np.array(w["x"], float)
    y = np.array(w["y"], float)
    X, Y = np.meshgrid(x, y)
    valid = np.isfinite(W)
    carrier = 2 * math.pi * (tilt_x * X / 2 + tilt_y * Y / 2)
    phi = np.where(valid, 2 * math.pi * passes * np.nan_to_num(W) + carrier, np.nan)
    I = np.where(valid, 0.5 * (1 + visibility * np.cos(phi)), np.nan)
    # the largest phase step between neighbouring valid pixels (sampling of the fringes)
    steps = [np.abs(np.diff(phi, axis=a)) for a in (0, 1)]
    max_step = float(max((np.nanmax(s) if np.isfinite(s).any() else 0.0) for s in steps))
    wv = W[valid]
    out = {
        "field": w["field"], "wavelength": w["wavelength"], "wavelength_um": w["wavelength_um"], "grid": grid, "passes": passes,
        "tilt_x": tilt_x, "tilt_y": tilt_y, "visibility": visibility, "x": x.tolist(), "y": y.tolist(),
        "intensity": I.tolist(), "wavefront_waves": W.tolist(),
        "pv_waves": float(wv.max() - wv.min()), "rms_waves": w["rms_waves"],
        "fringes_pv": float(passes * (wv.max() - wv.min())),  # aberration fringes (no tilt)
        "max_step_rad": max_step, "reference": w["reference"], "zernike": w["zernike"],
    }
    notes = []
    if max_step > STEP_LIMIT:
        notes.append(f"The fringes are undersampled ({max_step / math.pi:.2f} pi between neighbouring pixels): raise the grid or lower the tilt")
    if phase_steps:
        frames = np.stack([0.5 * (1 + visibility * np.cos(np.nan_to_num(phi) + 2 * math.pi * k / phase_steps)) for k in range(phase_steps)])
        wrapped = phase_shift(frames)
        un = unwrap_flood(wrapped, valid)
        rec = (un - carrier) / (2 * math.pi * passes)
        ok = valid & np.isfinite(rec)
        rec0 = rec - np.nanmean(rec[ok])
        W0 = W - wv.mean()
        res = rec0[ok] - W0[ok]
        out["phase_steps"] = phase_steps
        out["recovered_waves"] = np.where(ok, rec0, np.nan).tolist()
        out["recovery_rms_error_waves"] = float(np.sqrt(np.mean((res - res.mean()) ** 2)))
        out["recovered_fraction"] = float(ok.sum() / max(valid.sum(), 1))
        if out["recovery_rms_error_waves"] > 1e-6 and max_step <= STEP_LIMIT:
            notes.append(f"The recovered wavefront differs from the computed one by {out['recovery_rms_error_waves']:.2g} waves rms")
    out["notes"] = notes
    out["method"] = (f"Interferogram of the traced wavefront ({'double pass via a perfect return mirror' if passes == 2 else 'single pass'}) against a "
                     f"perfect reference sphere with {tilt_x:g} × {tilt_y:g} tilt fringes"
                     + (f"; {phase_steps}-step phase shifting (synchronous detection) and flood-fill unwrapping" if phase_steps else ""))
    return out
