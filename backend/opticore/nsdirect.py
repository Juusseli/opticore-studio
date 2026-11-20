"""Direct-path trace of non-sequential sources to analytic detectors (fast, for optimisation).

The source rays (nssources.sample_source, same seeded sampling as the non-sequential trace) are
traced through the *sequential* surfaces with the vectorised exact ray trace (raytrace.trace:
Snell refraction, mirrors, unpolarised Fresnel or thin-film transmission, bulk absorption). The
ray path is the polyline source -> surface hits -> straight on after the last surface; each
detector plane is intersected with the path segments.

This is the direct (transmitted) path of the non-sequential trace with splitting off, against
the lens surfaces only:
* a ray outside the clear aperture (effective semi-diameter) of a refracting or reflecting
  surface is lost; the non-sequential trace would let it pass beside the lens;
* lens edges (cylinders), ghost reflections, scattering and CAD bodies are not modelled;
* TIR ends the ray.
For a source whose rays all pass through the clear apertures the results equal the
non-sequential trace without splitting (validated in tests/test_nsdirect.py). Results report
the same quantities as nssources.DetectorRT.result plus the beam in the detector *plane* (all
rays crossing the plane, power-weighted: centroid and 2-sigma widths), which is a smooth
function of the design and therefore the quantity the optimiser targets.
"""

from __future__ import annotations

import math
import time

import numpy as np

from .nssources import Detector, DetectorRT, LightSource, sample_source, surface_frames
from .system import CompiledSystem, SystemError_, with_wavelengths

EPS = 1e-9


def _source_rays(cs: CompiledSystem, sources: list[LightSource], seed: int, frames, index_offsets: dict[str, float] | None = None):
    from .paraxial import compute_pupil
    from .raytrace import launch

    rng = np.random.default_rng(seed)
    wl = cs.model.primary_wavelength
    lam0 = float(cs.wavelengths[wl])
    sys_wls = [(float(w.value), float(w.weight)) for w in cs.model.wavelengths]
    out = []
    info = []
    for k, s in enumerate(sources):
        if s.kind == "system_field":
            if s.field >= len(cs.model.fields):
                raise SystemError_(f"Source '{s.name}': field {s.field + 1} does not exist")
            pupil = compute_pupil(cs, cs.model.primary_wavelength)  # the aperture at the primary wavelength, as every launch uses
            m = max(3, int(math.sqrt(s.rays * 4 / math.pi)))
            u = np.linspace(-s.overfill, s.overfill, m)
            gx, gy = np.meshgrid(u, u)
            inside = gx**2 + gy**2 <= s.overfill**2 + 1e-12
            P0, D0, _ = launch(cs, wl, s.field, gx[inside], gy[inside], pupil)
            n0 = len(P0)
            out.append((P0, D0 / np.linalg.norm(D0, axis=1, keepdims=True), np.full(n0, s.power_w / n0), np.full(n0, lam0), k))
        else:
            def object_index(lam: float) -> float:  # the rays start in the object space (a Gaussian beam's divergence)
                c = with_wavelengths(cs, [lam], index_offsets)
                return float(c.n_after[int(np.argmin(np.abs(c.wavelengths - lam))), 0])

            try:
                sr = sample_source(s, k, sys_wls, rng, frames, medium_index=object_index)
            except ValueError as exc:
                raise SystemError_(str(exc)) from exc
            out.append((sr.P, sr.D, sr.power, sr.lam, k))
        info.append({"name": s.name, "kind": s.kind, "rays": int(len(out[-1][0])), "power_w": s.power_w})
    return out, info


def trace_direct(cs: CompiledSystem, sources: list[LightSource], detectors: list[Detector], seed: int = 1, index_offsets: dict[str, float] | None = None) -> dict:
    """Detector results of the direct path (see the module docstring)."""
    from .analysis.evaluate import auto_semi_diameters, effective_semi_diameters
    from .paraxial import compute_pupil
    from .raytrace import trace

    t0 = time.time()
    frames = surface_frames(cs)
    srcs = [s for s in sources if s.enabled]
    if not srcs:
        raise SystemError_("No enabled light source")
    try:
        dets = [DetectorRT.build(d, frames) for d in detectors if d.enabled]
    except ValueError as exc:
        raise SystemError_(str(exc)) from exc
    starts, info = _source_rays(cs, srcs, seed, frames, index_offsets)
    total_power = float(sum(float(st[2].sum()) for st in starts))
    if total_power <= 0:
        raise SystemError_("The sources emit no power")
    P0 = np.concatenate([st[0] for st in starts])
    D0 = np.concatenate([st[1] for st in starts])
    pw0 = np.concatenate([st[2] for st in starts])
    lam = np.concatenate([st[3] for st in starts])
    ksrc = np.concatenate([np.full(len(st[0]), st[4]) for st in starts])
    nr = len(P0)
    n = cs.n_surfaces

    # clear apertures of the physical surfaces (as the solids of the non-sequential scene)
    sd = effective_semi_diameters(cs, auto_semi_diameters(cs, compute_pupil(cs)))
    physical = [j for j in range(1, n - 1) if not cs.is_cb[j] and (cs.is_mirror[j] or np.any(cs.n_after[:, j] != cs.n_after[:, j - 1]))]
    hit_j = [j for j in range(1, n) if not cs.is_cb[j]]  # path vertices after the start

    csx = with_wavelengths(cs, np.unique(lam), index_offsets)
    pts = np.full((nr, len(hit_j) + 1, 3), np.nan)
    inten = np.full((nr, len(hit_j) + 1), np.nan)
    dir_end = np.full((nr, 3), np.nan)
    alive_end = np.zeros(nr, bool)
    lost = {"outside_aperture": 0.0, "tir_or_failed": 0.0}
    pts[:, 0] = P0
    inten[:, 0] = 1.0
    for value in np.unique(lam):
        sel = np.nonzero(lam == value)[0]
        wi = int(np.argmin(np.abs(csx.wavelengths - value)))
        tr = trace(csx, wi, P0[sel], D0[sel], clip=True, fresnel=True, record=True)
        alive = np.ones(len(sel), bool)  # still on its path (a ray ends at its last reached vertex)
        out_ap = np.zeros(len(sel), bool)
        for c, j in enumerate(hit_j, start=1):
            q = tr.local[:, j]
            reached = alive & np.all(np.isfinite(q), axis=1)
            if j in physical:
                clip = reached & (np.hypot(q[:, 0], q[:, 1]) > sd[j] * (1 + 1e-9) + 1e-12)
                out_ap |= clip
                reached &= ~clip
            pts[sel[reached], c] = tr.points[reached, j]
            inten[sel[reached], c] = tr.intensity_after[reached, j]
            alive = reached
        good = tr.ok & alive
        dir_end[sel[good]] = tr.dirs[good]
        alive_end[sel[good]] = True
        pw = pw0[sel]
        lost["outside_aperture"] += float(pw[out_ap].sum())
        lost["tir_or_failed"] += float(pw[~good & ~out_ap].sum())

    # ---- detector crossings along the path ------------------------------------------------
    nseg = len(hit_j) + 1  # finite segments 0..nseg-2, semi-infinite segment nseg-1
    events = []  # (ray, key, det, x, y, dz, inside, power)
    for di, det in enumerate(dets):
        R, t = det.R, det.t
        loc = (pts - t) @ R  # (nr, nv, 3) local coordinates
        for k in range(nseg):
            a = loc[:, k]
            if k < nseg - 1:
                b = loc[:, k + 1]
                d = b - a
                valid = np.all(np.isfinite(a), axis=1) & np.all(np.isfinite(b), axis=1)
            else:
                d = dir_end @ R
                valid = alive_end & np.all(np.isfinite(a), axis=1)
            dz = d[:, 2]
            with np.errstate(divide="ignore", invalid="ignore"):
                u = -a[:, 2] / dz
            seglen = np.linalg.norm(d, axis=1)
            umin = EPS / np.maximum(seglen, 1e-300)
            # a crossing at the vertex shared with the next segment (a detector on a surface's vertex
            # plane, e.g. anchored to the image surface) belongs to this segment: u up to 1 + umin here,
            # u > umin on the next one, so rounding cannot drop it between the two (or count it twice)
            cross = valid & (np.abs(dz) > 1e-15) & (u > umin) & ((u <= 1.0 + umin) if k < nseg - 1 else True)
            idx = np.nonzero(cross)[0]
            if idx.size == 0:
                continue
            x = a[idx, 0] + u[idx] * d[idx, 0]
            y = a[idx, 1] + u[idx] * d[idx, 1]
            if det.spec.shape == "circle":
                inside = x * x + y * y <= det.spec.size_x**2
            else:
                inside = (np.abs(x) <= det.spec.size_x / 2) & (np.abs(y) <= det.spec.size_y / 2)
            dzn = dz[idx] / seglen[idx]
            power = pw0[idx] * inten[idx, k]
            for r_, key, x_, y_, z_, in_, p_ in zip(idx, k + np.minimum(u[idx], 1.0 - 1e-12), x, y, dzn, inside, power):
                events.append((int(r_), float(key), di, float(x_), float(y_), float(z_), bool(in_), float(p_)))
    events.sort(key=lambda e: (e[0], e[1]))
    plane: list[list[tuple]] = [[] for _ in dets]  # (x, y, power) of every unblocked plane crossing
    blocked_ray = -1
    for r_, key, di, x, y, dz, inside, p in events:
        if r_ == blocked_ray:
            continue
        det = dets[di]
        s = det.spec
        front = dz > 0.0
        if not plane[di] or plane[di][-1][3] != r_:
            plane[di].append((x, y, p, r_))
        if not inside:
            continue
        if not front and not s.two_sided:
            if s.mode == "absorb":
                det.back_w += p
                blocked_ray = r_
            continue
        if math.degrees(math.acos(min(1.0, abs(dz)))) <= s.acceptance_deg + 1e-9:
            det.hits.append((x, y, p, abs(dz), float(lam[r_]), int(ksrc[r_]), 0, 0))
        else:
            det.rejected_w += p
        if s.mode == "absorb":
            blocked_ray = r_

    names = [i["name"] for i in info]
    results = []
    for di, det in enumerate(dets):
        res = det.result(total_power, names)
        pl = np.array([(x, y, p) for x, y, p, _ in plane[di]]) if plane[di] else np.zeros((0, 3))
        pp = float(pl[:, 2].sum()) if len(pl) else 0.0
        if pp > 0:
            w = pl[:, 2] / pp
            c = (pl[:, :2] * w[:, None]).sum(0)
            dx, dy = pl[:, 0] - c[0], pl[:, 1] - c[1]
            res["plane"] = {"power_w": pp, "rays": int(len(pl)), "centroid_mm": c.tolist(), "width_2sigma_mm": [2 * math.sqrt(float((w * dx * dx).sum())), 2 * math.sqrt(float((w * dy * dy).sum()))]}
        else:
            res["plane"] = {"power_w": 0.0, "rays": 0, "centroid_mm": None, "width_2sigma_mm": None}
        results.append(res)
    return {
        "detectors": results,
        "sources": info,
        "total_power_w": total_power,
        "lost_w": lost,
        "rays": nr,
        "seed": seed,
        "time_s": time.time() - t0,
        "method": "Direct path: seeded source rays traced through the sequential surfaces (exact refraction, Fresnel or thin-film transmission, absorption), clipped at the clear apertures, intersected with the analytic detector planes; no ghosts, edges, scattering or CAD bodies",
    }
