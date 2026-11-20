"""Automatic vignetting factors (docs/OPTICAL_ENGINE.md, "Vignetting factors").

For each field, the part of the entrance pupil that the fixed apertures pass is found along the pupil
axis of the field's dominant direction (y, or x when |field x| > |field y|) and then along the other axis
through the centre found: with the real (aimed) rays of the primary wavelength, bisection finds how far a
ray can move from the centre before an aperture clips it. The factors VDY = (top + bottom) / 2,
VCY = 1 - (top - bottom) / 2 (and VDX, VCX from the x extent at py = VDY; for a field along x the x extent
at py = 0 first and the y extent at px = VDX) map the unit pupil onto that region
(raytrace.vignetted_pupil), so the marginal rays of every field just pass.
The passed region is assumed to be convex along each line through its centre (true for circular
apertures); fields whose centre ray is blocked keep zero factors and are reported.
"""

from __future__ import annotations

import numpy as np

from ..paraxial import compute_pupil
from ..raytrace import trace_pupil
from ..system import CompiledSystem

TOL = 1e-7  # normalised pupil


def _passes(cs: CompiledSystem, wl: int, field: int, px: float, py: float, pupil) -> bool:
    r = trace_pupil(cs, wl, field, np.array([px]), np.array([py]), pupil, clip=True, obscure=False)
    return bool(r.ok[0])


def _edge(cs: CompiledSystem, wl: int, field: int, pupil, ox: float, oy: float, dx: float, dy: float) -> float:
    """Largest t in [0, 1] (to TOL) for which the ray at (ox, oy) + t (dx, dy) passes; the origin passes."""
    if _passes(cs, wl, field, ox + dx, oy + dy, pupil):
        return 1.0
    lo, hi = 0.0, 1.0
    while hi - lo > TOL:
        mid = 0.5 * (lo + hi)
        if _passes(cs, wl, field, ox + mid * dx, oy + mid * dy, pupil):
            lo = mid
        else:
            hi = mid
    return lo


def vignetting_factors(cs: CompiledSystem) -> dict:
    """Vignetting factors of every field at the primary wavelength (see the module notes)."""
    wl = cs.model.primary_wavelength
    pupil = compute_pupil(cs, wl)
    out = []
    for f in range(len(cs.model.fields)):
        if not _passes(cs, wl, f, 0.0, 0.0, pupil):
            out.append({"vdx": 0.0, "vdy": 0.0, "vcx": 0.0, "vcy": 0.0, "ok": False, "note": "the centre ray of the pupil is blocked"})
            continue
        # the dominant field axis first (its extent through the pupil centre sets the decentre), then the other axis
        # through the centre found: a field along x has its pupil decentred along x, and its y extent must be measured
        # through that centre, not at px = 0
        fd = cs.model.fields[f]
        first = "x" if abs(fd.x) > abs(fd.y) else "y"
        a, b = (1.0, 0.0) if first == "x" else (0.0, 1.0)
        hi = _edge(cs, wl, f, pupil, 0.0, 0.0, a, b)
        lo = -_edge(cs, wl, f, pupil, 0.0, 0.0, -a, -b)
        vd1, vc1 = 0.5 * (hi + lo), 1.0 - 0.5 * (hi - lo)
        cx, cy = (vd1, 0.0) if first == "x" else (0.0, vd1)
        if not _passes(cs, wl, f, cx, cy, pupil):
            out.append({"vdx": 0.0, "vdy": 0.0, "vcx": 0.0, "vcy": 0.0, "ok": False, "note": f"the vignetted pupil is not convex along {first}"})
            continue
        hi = _edge(cs, wl, f, pupil, cx, cy, b, a)
        lo = -_edge(cs, wl, f, pupil, cx, cy, -b, -a)
        vd2, vc2 = 0.5 * (hi + lo), 1.0 - 0.5 * (hi - lo)
        (vdx, vcx), (vdy, vcy) = ((vd1, vc1), (vd2, vc2)) if first == "x" else ((vd2, vc2), (vd1, vc1))
        clean = lambda v: 0.0 if abs(v) < 2 * TOL else float(v)  # noqa: E731
        out.append({"vdx": clean(vdx), "vdy": clean(vdy), "vcx": min(0.999, clean(vcx)), "vcy": min(0.999, clean(vcy)), "ok": True, "note": None})
    return {
        "fields": out,
        "wavelength_um": float(cs.wavelengths[wl]),
        "method": "Bisection of real (aimed) rays against the fixed apertures along the pupil axis of the field's dominant direction and then along the other axis through the centre of the passed region (tolerance 1e-7 of the pupil radius)",
    }
