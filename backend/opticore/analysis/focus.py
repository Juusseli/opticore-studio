"""Focus status: how far the image surface is from the best polychromatic RMS focus.

After the last refracting or reflecting surface every ray is a straight line, so on a
plane displaced by delta along the image surface normal its intersection is
    p(delta) = p0 + delta * t,   t = (dx/dz, dy/dz) in the image surface frame.
The field's polychromatic centroid moves linearly as well, so the centroid-referenced
squared RMS radius of field f is an exact quadratic in delta:
    RMS_f^2(delta) = A_f + 2 B_f delta + C_f delta^2,
with A, B, C weighted sums over the traced rays (wavelength weights). The field-weighted
mean of RMS_f^2 is quadratic too, and its minimum is at delta* = -B/C.

The model is exact for a plane image surface displaced along its own normal (the usual
case: the last thickness runs along the image normal). For a curved image surface the
displacement is evaluated on the tangent plane at each hit, which is a first-order
estimate; the result says so (`exact = False`).
"""

from __future__ import annotations

import math

import numpy as np

from ..paraxial import compute_pupil
from ..raytrace import pupil_pattern, trace_pupil
from ..system import CompiledSystem

# "At best focus": the RMS at the current position is within 5 % (or 0.1 um) of the best RMS
FOCUS_REL_TOL = 0.05
FOCUS_ABS_TOL_MM = 1e-4


def focus_status(cs: CompiledSystem, density: int = 6) -> dict:
    pupil = compute_pupil(cs)
    px, py = pupil_pattern("hexapolar", density)
    end = cs.n_surfaces - 1
    M = cs.frames[end].matrix  # columns: local axes of the image surface in global coordinates
    nf = len(cs.model.fields)
    per_field = []
    tot = np.zeros(3)  # field-weighted A, B, C
    wsum = 0.0
    n_rays = 0
    for f in range(nf):
        P, T, W = [], [], []
        for w in range(len(cs.wavelengths)):
            r = trace_pupil(cs, w, f, px, py, pupil, vignetting=True)
            ok = r.ok
            if not np.any(ok):
                continue
            d_local = r.dirs[ok] @ M  # direction cosines in the image surface frame
            dz = d_local[:, 2]
            good = np.abs(dz) > 1e-12
            P.append(r.local[ok, end, :2][good])
            T.append(d_local[good, :2] / dz[good, None])
            W.append(np.full(int(np.count_nonzero(good)), cs.model.wavelengths[w].weight))
        if not P or sum(len(x) for x in P) == 0:
            per_field.append({"field": f, "rms_um": None, "rms_best_um": None, "n_rays": 0})
            continue
        p = np.concatenate(P)
        t = np.concatenate(T)
        wt = np.concatenate(W)
        if wt.sum() <= 0:
            wt = np.ones_like(wt)
        wn = wt / wt.sum()
        a = p - (wn[:, None] * p).sum(0)
        b = t - (wn[:, None] * t).sum(0)
        A = float((wn * (a * a).sum(1)).sum())
        B = float((wn * (a * b).sum(1)).sum())
        C = float((wn * (b * b).sum(1)).sum())
        d_f = -B / C if C > 0 else 0.0
        per_field.append({"field": f, "rms_um": math.sqrt(max(A, 0.0)) * 1e3, "rms_best_um": math.sqrt(max(A + 2 * B * d_f + C * d_f * d_f, 0.0)) * 1e3, "n_rays": int(len(p))})
        fw = cs.model.fields[f].weight
        tot += fw * np.array([A, B, C])
        wsum += fw
        n_rays += int(len(p))
    method = "Polychromatic centroid-referenced RMS spot on planes along the image surface normal (exact quadratic in the defocus for straight rays after the last surface); field and wavelength weights"
    if wsum <= 0 or tot[2] <= 0:
        return {"best_defocus_mm": None, "rms_um": None, "rms_best_um": None, "at_best_focus": None, "max_field_rms_um": None, "per_field": per_field, "n_rays": n_rays, "exact": True, "method": method}
    A, B, C = tot / wsum
    delta = -B / C
    rms = math.sqrt(max(A, 0.0))
    rms_best = math.sqrt(max(A + 2 * B * delta + C * delta * delta, 0.0))
    vals = [x["rms_um"] for x in per_field if x["rms_um"] is not None]
    image = cs.model.surfaces[end]
    # exact for a plane image surface whose fields do not move with it: real image-height fields are re-solved on the
    # moved surface (fields.py), so the prediction with the rays held fixed is then a first-order estimate
    exact = bool(cs.shapes[end].curvature == 0 and not getattr(cs.shapes[end], "aspheric", ()) and image.type == "standard" and cs.model.field_type != "image_height")
    return {
        "best_defocus_mm": float(delta),
        "rms_um": rms * 1e3,
        "rms_best_um": rms_best * 1e3,
        "at_best_focus": bool(rms <= rms_best * (1 + FOCUS_REL_TOL) + FOCUS_ABS_TOL_MM),
        "max_field_rms_um": max(vals) if vals else None,
        "per_field": per_field,
        "n_rays": n_rays,
        "exact": exact,
        "method": method,
    }
