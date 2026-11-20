"""Compact meridional outline of a system, for thumbnails (start screen, recent projects).

Drawing data only. The polylines are the exact y-z surface profiles of the layout and the
real-ray paths of the layout trace (primary wavelength), in global (z, y) coordinates and
rounded to five significant digits. Nothing here is an optical result in its own right.
"""

from __future__ import annotations

import math

import numpy as np

from ..system import CompiledSystem
from .evaluate import auto_semi_diameters, compute_pupil, effective_semi_diameters, layout_rays, lens_elements, surface_profiles

PROFILE_SAMPLES = 17


def _r(v: float) -> float:
    return float(f"{v:.5g}")


def _zy(points) -> list[list[float]]:
    return [[_r(p[2]), _r(p[1])] for p in points]


def _global(frame_origin, frame_matrix, y: float, z: float) -> np.ndarray:
    return frame_origin + frame_matrix[:, 1] * y + frame_matrix[:, 2] * z


def _surface_points(s: dict) -> list[np.ndarray]:
    o = np.asarray(s["origin"], float)
    m = np.asarray(s["matrix"], float)
    return [_global(o, m, y, z) for y, z in s["profile"]]


def _element_polygon(front: dict, back: dict) -> list[np.ndarray] | None:
    """Closed outline of a glass element between two surfaces, stepped to the larger semi-diameter."""
    if len(front["profile"]) < 2 or len(back["profile"]) < 2:
        return None
    of, mf = np.asarray(front["origin"], float), np.asarray(front["matrix"], float)
    ob, mb = np.asarray(back["origin"], float), np.asarray(back["matrix"], float)
    hf, hb = front["semi_diameter"], back["semi_diameter"]
    hm = max(hf, hb)
    pf, pb = front["profile"], back["profile"]
    pts = [_global(of, mf, y, z) for y, z in pf]
    if hf < hm:
        pts.append(_global(of, mf, hm, pf[-1][1]))
    if hb < hm:
        pts.append(_global(ob, mb, hm, pb[-1][1]))
    pts += [_global(ob, mb, y, z) for y, z in reversed(pb)]
    if hb < hm:
        pts.append(_global(ob, mb, -hm, pb[0][1]))
    if hf < hm:
        pts.append(_global(of, mf, -hm, pf[0][1]))
    return pts


def system_outline(cs: CompiledSystem, max_fields: int = 3) -> dict:
    """Glass outlines, mirrors, stop, image plane and a few real rays of the active configuration.

    Rays: the marginal and chief rays of up to ``max_fields`` fields (first, middle, last) at the
    primary wavelength. For an object at infinity they are extended backwards along their start
    direction so they enter the drawing, as in the 2D layout.
    """
    pupil = compute_pupil(cs)
    sd = effective_semi_diameters(cs, auto_semi_diameters(cs, pupil))
    surfs = surface_profiles(cs, sd, PROFILE_SAMPLES)
    n = len(surfs)
    infinite = cs.model.surfaces[0].thickness is None
    items: list[dict] = []
    in_element: set[int] = set()
    for el in lens_elements(cs):
        poly = _element_polygon(surfs[el["front"]], surfs[el["back"]])
        if poly:
            items.append({"kind": "glass", "points": _zy(poly)})
            in_element.update((el["front"], el["back"]))
    for i, s in enumerate(surfs):
        if i == 0 or not s["profile"]:
            continue
        pts = _surface_points(s)
        if i == n - 1:
            items.append({"kind": "image", "points": _zy(pts)})
        elif s["is_ideal"]:
            items.append({"kind": "ideal", "points": _zy(pts)})
        elif s["is_mirror"]:
            items.append({"kind": "mirror", "points": _zy(pts)})
        elif s["is_stop"] and i not in in_element:
            # aperture blades: from the stop edge outwards
            o, m = np.asarray(s["origin"], float), np.asarray(s["matrix"], float)
            h = s["semi_diameter"]
            for sign in (1.0, -1.0):
                items.append({"kind": "stop", "points": _zy([_global(o, m, sign * h, 0.0), _global(o, m, sign * h * 1.3, 0.0)])})
        elif i not in in_element and cs.model.surfaces[i].material != cs.model.surfaces[i - 1].material:
            items.append({"kind": "surface", "points": _zy(pts)})
    if not infinite and surfs[0]["profile"]:
        items.append({"kind": "object", "points": _zy(_surface_points(surfs[0]))})

    nf = len(cs.model.fields)
    fields = sorted({0, nf // 2, nf - 1})[:max_fields] if nf else []
    raw = [r for r in layout_rays(cs, pupil, 3, "meridional") if r["wavelength"] == cs.model.primary_wavelength and r["field"] in fields]
    # bounds of the geometry and the traced segments (object at infinity: without the lead-in)
    allpts = [p for it in items for p in it["points"]] + [[p[2], p[1]] for r in raw for p in r["points"]]
    if not allpts:
        return {"bbox": [-1.0, 1.0, -1.0, 1.0], "items": items, "rays": [], "infinite_object": infinite}
    zs = [p[0] for p in allpts]
    ys = [p[1] for p in allpts]
    zmin, zmax = min(zs), max(zs)
    lead = 0.12 * (zmax - zmin) if infinite else 0.0
    rays = []
    for r in raw:
        pts = [np.asarray(p, float) for p in r["points"]]
        if not pts:
            continue
        if infinite:
            p = pts[1] if len(pts) > 1 else pts[0]
            d = np.asarray(r["start_dir"], float)
            length = lead + max(0.0, p[2] - zmin)
            pts = [p - d * (length / max(d[2], 1e-6))] + pts[1:]
            ys.append(float(pts[0][1]))
        rays.append({"field": r["field"], "ok": r["status"] == "ok", "points": _zy(pts)})
    zmin -= lead
    bbox = [_r(zmin), _r(zmax), _r(min(ys)), _r(max(ys))]
    if not all(math.isfinite(v) for v in bbox):
        bbox = [-1.0, 1.0, -1.0, 1.0]
    return {"bbox": bbox, "items": items, "rays": rays, "infinite_object": infinite}

