"""Sequential real-ray tracing (vectorised over rays).

Rays are launched in object space, aimed at the entrance pupil (paraxial
aiming) or iteratively aimed so they cross the stop at the requested
normalised coordinates (real aiming), then traced surface by surface with
exact intersections, vector Snell refraction and reflection.

Ray failures are never silently discarded: every ray carries a status code and
the index of the surface where it terminated (see surfaces.STATUS_TEXT).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .paraxial import Pupil, compute_pupil
from .physics import reflect, refract, unpolarized_transmittance
from .thinfilm import unpolarized_R, unpolarized_T
from .diffractive import diffract
from .surfaces import EVANESCENT, OBSCURED, OK, STATUS_TEXT, TIR, VIGNETTED
from .fields import object_field, object_kind
from .system import CompiledSystem, SystemError_

AIM_TOL = 1e-11  # mm at the stop (tight: optimiser finite differences must not see aiming noise)
AIM_MAX_ITER = 25


@dataclass
class TraceResult:
    points: np.ndarray  # (nr, ns, 3) global intersection points (NaN where not reached / CB)
    local: np.ndarray  # (nr, ns, 3) local intersection points
    dirs: np.ndarray  # (nr, 3) final global directions (after the last traced surface)
    status: np.ndarray  # (nr,) int8
    fail_surface: np.ndarray  # (nr,) surface index of termination, -1 if ok
    opl: np.ndarray  # (nr,) optical path length to the last traced surface (mm)
    intensity: np.ndarray  # (nr,) relative transmitted intensity
    start_points: np.ndarray  # (nr, 3)
    start_dirs: np.ndarray  # (nr, 3)
    end_surface: int
    dirs_after: np.ndarray | None = None  # (nr, ns, 3) global direction after each surface (record=True)
    waves_after: np.ndarray | None = None  # (nr, ns, 3) global wave vector K (|K| = phase index) after each surface (record=True, crystals)
    normals: np.ndarray | None = None  # (nr, ns, 3) global unit surface normal at each hit (record=True)
    intensity_after: np.ndarray | None = None  # (nr, ns) relative intensity after each surface (record=True)

    @property
    def ok(self) -> np.ndarray:
        return self.status == OK

    def image_xy(self) -> np.ndarray:
        return self.local[:, self.end_surface, :2]


def _mirror_R(cs, wl: int, j: int, d: np.ndarray, normals: np.ndarray) -> np.ndarray:
    """Unpolarised reflectance of the coated mirror j (layers from the incident medium to the substrate)."""
    coat = cs.coatings[j]
    lam_um = float(cs.wavelengths[wl])
    n0 = abs(float(cs.n_after[wl, j - 1]))
    cos_i = np.abs(np.einsum("ij,ij->i", d, normals))
    return unpolarized_R(n0, coat.substrate, coat.layers_at(lam_um), lam_um, cos_i)


IDEAL_INF = 1e9  # |distance| (mm) treated as infinite in the ideal-lens path correction


def _ideal_lens(lens, q: np.ndarray, d: np.ndarray, n: float) -> tuple[np.ndarray, np.ndarray]:
    """Ideal lens at the local plane z = 0 in a medium of index n.

    Directions are written as tangents along the direction of travel,
    t = (dx, dy) / |dz|. The lens maps t' = t - h / f (h = (x, y) at the lens):
    every ray from an object point at distance s converges to the point at
    s' with 1/s' = 1/f - 1/s, for any field (perfect, distortion-free imaging).

    The optical path added at the lens makes the path from the design object
    point Q (s = lens.object_distance, infinity by default) to its image Q'
    the same for every ray:
        dOPL = n (sgn(s) |Q| - s sqrt(1 + t^2)) + n (sgn(s') |Q'| - s' sqrt(1 + t'^2))
    with Q = h - s (t, 1) and Q' = h + s' (t', 1) in travel coordinates; for
    s -> infinity the first term becomes -n (d . h), for s' -> infinity the
    second becomes +n (d' . h). Rays from other conjugates image perfectly but
    their OPD contains the residual of a lens corrected for the design conjugate.
    Returns (new local directions, OPL increments)."""
    sz = np.where(d[:, 2] < 0, -1.0, 1.0)
    az = np.abs(d[:, 2])
    tx, ty = d[:, 0] / az, d[:, 1] / az
    hx, hy = q[:, 0], q[:, 1]
    k = lens.inv_f
    tx2, ty2 = tx - hx * k, ty - hy * k
    nn = np.sqrt(1.0 + tx2 * tx2 + ty2 * ty2)
    dn = np.stack([tx2 / nn, ty2 / nn, sz / nn], axis=1)
    s_obj = lens.object_distance
    if s_obj is None or abs(s_obj) > IDEAL_INF:
        a = -(d[:, 0] * hx + d[:, 1] * hy)
        inv_si = k
    else:
        qx, qy = hx - s_obj * tx, hy - s_obj * ty
        a = math.copysign(1.0, s_obj) * np.sqrt(qx * qx + qy * qy + s_obj * s_obj) - s_obj * np.sqrt(1.0 + tx * tx + ty * ty)
        inv_si = k - 1.0 / s_obj
    if abs(inv_si) < 1.0 / IDEAL_INF:
        b = dn[:, 0] * hx + dn[:, 1] * hy
    else:
        si = 1.0 / inv_si
        px, py = hx + si * tx2, hy + si * ty2
        b = math.copysign(1.0, si) * np.sqrt(px * px + py * py + si * si) - si * nn
    return dn, n * (a + b)


def trace(
    cs: CompiledSystem,
    wl: int,
    P0: np.ndarray,
    D0: np.ndarray,
    opl0: np.ndarray | None = None,
    end: int | None = None,
    clip: bool = True,
    fresnel: bool = False,
    record: bool = False,
    obscure: bool | None = None,
) -> TraceResult:
    """Trace rays starting at global points P0 with unit directions D0 (object space).

    clip applies the fixed semi-diameters; obscure (default: clip) also blocks rays inside a
    surface's central obscuration (chief-ray references are traced with obscure=False).

    record=True also stores the global direction after every surface, the
    global surface normal at every hit (used by the polarisation ray trace) and
    the relative intensity after every surface (direct-path detector trace).

    Uniaxial crystals (cs.crystal, birefringence.py): rays travel along the
    ray (Poynting) direction and carry their wave vector K; the optical path
    over a segment of length s is (K·d) s, and refraction conserves the
    tangential part of K. Fresnel losses at crystal faces use the phase indices
    of the incident and the traced wave (unpolarised, isotropic formula)."""
    n_s = cs.n_surfaces
    end = n_s - 1 if end is None else end
    nr = P0.shape[0]
    P = P0.astype(float).copy()
    D = D0.astype(float).copy()
    D /= np.linalg.norm(D, axis=1, keepdims=True)
    opl = np.zeros(nr) if opl0 is None else opl0.astype(float).copy()
    intensity = np.ones(nr)
    status = np.zeros(nr, dtype=np.int8)
    fail = np.full(nr, -1, dtype=np.int32)
    pts = np.full((nr, n_s, 3), np.nan)
    loc = np.full((nr, n_s, 3), np.nan)
    pts[:, 0, :] = P0
    loc[:, 0, :] = cs.frames[0].to_local_points(P0)
    dirs_after = np.full((nr, n_s, 3), np.nan) if record else None
    nrm = np.full((nr, n_s, 3), np.nan) if record else None
    inten = np.full((nr, n_s), np.nan) if record else None
    if record:
        dirs_after[:, 0, :] = D
        inten[:, 0] = 1.0
    cry = cs.crystal if cs.crystal and any(c is not None for c in cs.crystal) else None
    K = D * cs.n_after[wl, 0] if cry is not None else None  # global wave vectors (crystal media in the path)
    waves = np.full((nr, n_s, 3), np.nan) if (record and cry is not None) else None
    if waves is not None:
        waves[:, 0, :] = K

    for j in range(1, end + 1):
        if cs.is_cb[j]:
            continue
        alive = np.nonzero(status == OK)[0]
        if alive.size == 0:
            break
        fr = cs.frames[j]
        p = fr.to_local_points(P[alive])
        d = fr.to_local_dirs(D[alive])
        s, st = cs.shapes[j].intersect(p, d)
        bad = st != OK
        if np.any(bad):
            status[alive[bad]] = st[bad]
            fail[alive[bad]] = j
        good = ~bad
        idx = alive[good]
        if idx.size == 0:
            continue
        s = s[good]
        p = p[good]
        d = d[good]
        q = p + s[:, None] * d
        n1 = cs.n_after[wl, j - 1]
        n2 = cs.n_after[wl, j]
        in_cry = cry is not None and cry[j - 1] is not None
        out_cry = cry is not None and cry[j] is not None
        if in_cry:
            k_loc = fr.to_local_dirs(K[idx])
            opl[idx] += np.einsum("ij,ij->i", k_loc, d) * s  # ray index n cos(walk-off)
        else:
            opl[idx] += n1 * s
        if cs.absorption[wl, j - 1] > 0.0:
            intensity[idx] *= np.exp(-cs.absorption[wl, j - 1] * np.abs(s))
        loc[idx, j, :] = q
        pts[idx, j, :] = fr.to_global_points(q)
        if clip and np.isfinite(cs.fixed_sd[j]):
            r = np.hypot(q[:, 0], q[:, 1])
            v = r > cs.fixed_sd[j] * (1.0 + 1e-12) + 1e-12
            if np.any(v):
                status[idx[v]] = VIGNETTED
                fail[idx[v]] = j
                keep = ~v
                idx, q, d = idx[keep], q[keep], d[keep]
                if in_cry:
                    k_loc = k_loc[keep]
                if idx.size == 0:
                    continue
        if (clip if obscure is None else obscure) and cs.obscuration is not None and cs.obscuration[j] > 0.0:
            v = np.hypot(q[:, 0], q[:, 1]) < cs.obscuration[j]
            if np.any(v):
                status[idx[v]] = OBSCURED
                fail[idx[v]] = j
                keep = ~v
                idx, q, d = idx[keep], q[keep], d[keep]
                if in_cry:
                    k_loc = k_loc[keep]
                if idx.size == 0:
                    continue
        if j == n_s - 1:  # image surface: no change of direction
            P[idx] = fr.to_global_points(q)
            if record:
                dirs_after[idx, j, :] = D[idx]
                nrm[idx, j, :] = fr.to_global_dirs(cs.shapes[j].normals(q))
                inten[idx, j] = intensity[idx]
            continue
        normals = cs.shapes[j].normals(q)
        doe = cs.does[j] if cs.does else None
        lens = cs.ideal[j] if cs.ideal else None
        if lens is not None:
            dn, dopl = _ideal_lens(lens, q, d, float(n1))
            opl[idx] += dopl
        elif doe is not None:
            lam_mm = float(cs.wavelengths[wl]) * 1e-3
            G = doe.grating_vector(q[:, 0], q[:, 1])
            refl = bool(cs.is_mirror[j])
            dn, evan = diffract(d, normals, n1, n2, G, doe.order, lam_mm, refl)
            opl[idx] += doe.order * lam_mm * doe.phase(q[:, 0], q[:, 1]) / (2 * math.pi)
            if np.any(evan):
                status[idx[evan]] = EVANESCENT
                fail[idx[evan]] = j
            if fresnel and refl and cs.coatings and cs.coatings[j] is not None:
                intensity[idx] *= np.where(evan, 0.0, _mirror_R(cs, wl, j, d, normals))
            if fresnel and not refl and n1 != n2:
                # zero-thickness phase element on a refracting interface: Fresnel loss of the interface
                cos_i = np.abs(np.einsum("ij,ij->i", d, normals))
                cos_t = np.abs(np.einsum("ij,ij->i", dn, normals))
                intensity[idx] *= np.where(evan, 0.0, unpolarized_transmittance(n1, n2, cos_i, cos_t))
        elif cs.is_mirror[j]:
            dn, _ = reflect(d, normals)
            if fresnel and cs.coatings and cs.coatings[j] is not None:
                intensity[idx] *= _mirror_R(cs, wl, j, d, normals)
        elif in_cry or out_cry:
            from .birefringence import refract_aniso

            kin = k_loc if in_cry else float(n1) * d
            med = cry[j].at(wl, fr) if out_cry else None
            dn, kn, tir = refract_aniso(kin, d, normals, float(n2), med)
            if np.any(tir):
                status[idx[tir]] = TIR
                fail[idx[tir]] = j
            if fresnel:
                na, nb = np.linalg.norm(kin, axis=1), np.linalg.norm(kn, axis=1)
                cos_i = np.abs(np.einsum("ij,ij->i", kin, normals)) / na
                cos_t = np.abs(np.einsum("ij,ij->i", kn, normals)) / np.where(nb > 0, nb, 1.0)
                T = unpolarized_transmittance(na, nb, cos_i, cos_t)
                intensity[idx] *= np.where(tir, 0.0, T)
            K[idx] = fr.to_global_dirs(kn)
        else:
            if n1 == n2:
                dn = d
            else:
                dn, tir, cos_i, cos_t = refract(d, normals, n1, n2)
                if np.any(tir):
                    status[idx[tir]] = TIR
                    fail[idx[tir]] = j
                if fresnel:
                    coat = cs.coatings[j] if cs.coatings else None
                    if coat is None:
                        T = unpolarized_transmittance(n1, n2, cos_i, cos_t)
                    else:
                        lam_um = float(cs.wavelengths[wl])
                        T = unpolarized_T(n1, n2, coat.oriented(lam_um, n1, n2), lam_um, cos_i)
                    intensity[idx] *= np.where(tir, 0.0, T)
        P[idx] = fr.to_global_points(q)
        D[idx] = fr.to_global_dirs(dn)
        if cry is not None and not (in_cry or out_cry):
            K[idx] = float(n2) * D[idx]
        if record:
            dirs_after[idx, j, :] = D[idx]
            nrm[idx, j, :] = fr.to_global_dirs(normals)
            inten[idx, j] = intensity[idx]
            if waves is not None:
                waves[idx, j, :] = K[idx]
    return TraceResult(
        points=pts,
        local=loc,
        dirs=D,
        status=status,
        fail_surface=fail,
        opl=opl,
        intensity=intensity,
        start_points=P0,
        start_dirs=D0,
        end_surface=end,
        dirs_after=dirs_after,
        normals=nrm,
        intensity_after=inten,
        waves_after=waves,
    )


# ----------------------------------------------------------------------
# Ray launching
# ----------------------------------------------------------------------


def _field_xy(cs: CompiledSystem, field: int) -> tuple[float, float]:
    f = cs.model.fields[field]
    return f.x, f.y


def launch(
    cs: CompiledSystem,
    wl: int,
    field: int | tuple[float, float],
    px: np.ndarray,
    py: np.ndarray,
    pupil: Pupil | None = None,
    aiming: str | None = None,
    aim_cache: dict | None = None,
    object_units: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Starting points, directions and reference OPL for normalised pupil
    coordinates (px, py) in the unit circle and a field index (or explicit
    (hx, hy) field value in field units; with object_units=True an explicit
    value is already an object-space field, see fields.py).

    Object-space telecentric systems launch every ray from the object point
    with direction cosines (L, M) = NA/n0 * (px, py) about the axis (chief
    ray parallel to the axis; no pupil aiming).

    aim_cache (optional): dict reused across calls to warm-start real ray
    aiming from the previous solution of the same field/wavelength/pattern
    (used by the optimiser, where successive systems differ slightly)."""
    pupil = pupil or compute_pupil(cs, cs.model.primary_wavelength)
    aiming = aiming or cs.model.ray_aiming
    hx, hy = _field_xy(cs, field) if isinstance(field, (int, np.integer)) else field
    if not object_units:
        hx, hy = object_field(cs, hx, hy, aim_cache)
    px = np.atleast_1d(np.asarray(px, dtype=float))
    py = np.atleast_1d(np.asarray(py, dtype=float))
    if cs.model.object_space_telecentric:
        return _launch_telecentric(cs, wl, hx, hy, px, py)
    qx = px * pupil.r_ep
    qy = py * pupil.r_ep
    if aiming != "real":
        return _launch_from_pupil_points(cs, wl, hx, hy, qx, qy, pupil)
    key = None
    if aim_cache is not None:
        key = (wl, float(hx), float(hy), px.tobytes(), py.tobytes())
        prev = aim_cache.get(key)
        if prev is not None:
            qx, qy = prev[0].copy(), prev[1].copy()
    P, D, opl, qx, qy = _real_aim(cs, wl, hx, hy, px, py, pupil, qx, qy)
    if key is not None:
        if len(aim_cache) > 512:
            aim_cache.clear()
        aim_cache[key] = (qx, qy)
    return P, D, opl


def _launch_telecentric(cs, wl, hx, hy, px, py):
    n0 = float(cs.n_after[wl, 0])
    na = cs.model.aperture.value / n0
    if na >= 1.0:
        raise SystemError_("Object-space NA must be smaller than the object-space index")
    L = na * px
    M = na * py
    N = np.sqrt(np.clip(1.0 - L * L - M * M, 0.0, None))
    D = np.stack([L, M, N], axis=1)
    O = np.array([hx, hy, -cs.model.surfaces[0].thickness])
    return np.tile(O, (px.shape[0], 1)), D, np.zeros(px.shape[0])


def _launch_from_pupil_points(cs, wl, hx, hy, qx, qy, pupil: Pupil):
    n0 = cs.n_after[wl, 0]
    z_ep = pupil.z_ep
    nr = qx.shape[0]
    Q = np.stack([qx, qy, np.full(nr, z_ep)], axis=1)
    if cs.model.object_at_infinity:
        tx, ty = math.tan(math.radians(hx)), math.tan(math.radians(hy))
        d = np.array([tx, ty, 1.0])
        d /= np.linalg.norm(d)
        D = np.tile(d, (nr, 1))
        # start on the plane through the EP centre perpendicular to D (reference wavefront)
        epc = np.array([0.0, 0.0, z_ep])
        along = (Q - epc) @ d
        P = Q - along[:, None] * D
        opl = np.zeros(nr)
        return P, D, opl
    d0 = cs.model.surfaces[0].thickness
    if object_kind(cs) == "angle":
        # angle fields with a finite object: the object point is where a chief
        # ray at that angle through the EP centre meets the object plane
        # (consistent with paraxial.chief_ray: h = -tan(theta) (d0 + z_EP))
        ox = -math.tan(math.radians(hx)) * (d0 + z_ep)
        oy = -math.tan(math.radians(hy)) * (d0 + z_ep)
    else:
        ox, oy = hx, hy
    O = np.array([ox, oy, -d0])
    if d0 >= 0:
        D = Q - O
        nrm = np.linalg.norm(D, axis=1, keepdims=True)
        D /= np.where(nrm > 0, nrm, 1.0)
        P = np.tile(O, (nr, 1))
        return P, D, np.zeros(nr)
    # virtual object (behind surface 1): light converges towards O; rays start
    # on the EP plane and the OPL is referenced to the (virtual) object point
    D = O - Q
    nrm = np.linalg.norm(D, axis=1, keepdims=True)
    D /= np.where(nrm > 0, nrm, 1.0)
    return Q, D, -n0 * nrm[:, 0]


def _stop_hit(cs, wl, hx, hy, qx, qy, pupil):
    P, D, _ = _launch_from_pupil_points(cs, wl, hx, hy, qx, qy, pupil)
    r = trace(cs, wl, P, D, end=cs.stop, clip=False)
    return r.local[:, cs.stop, 0], r.local[:, cs.stop, 1], r.status == OK


def _real_aim(cs, wl, hx, hy, px, py, pupil: Pupil, qx, qy):
    """Adjust entrance-pupil intercepts so rays cross the stop at
    (px, py) * r_stop (tolerance AIM_TOL). Chord-Newton iteration: the 2x2
    finite-difference Jacobian per ray is reused while the error keeps
    shrinking and recomputed otherwise. Rays that cannot be aimed keep their
    last estimate and fail later in the trace (status reported).
    Returns (P, D, opl, qx, qy)."""
    tx = px * pupil.r_stop
    ty = py * pupil.r_stop
    qx = qx.copy()
    qy = qy.copy()
    h = max(1e-6, 1e-7 * pupil.r_ep)
    J = None
    prev_err = None
    for _ in range(AIM_MAX_ITER):
        sx, sy, ok = _stop_hit(cs, wl, hx, hy, qx, qy, pupil)
        ex = sx - tx
        ey = sy - ty
        err = np.hypot(ex, ey)
        active = ok & (err >= AIM_TOL)
        if not np.any(active):
            break
        stalled = prev_err is not None and np.any(err[active] > 0.25 * prev_err[active])
        if J is None or stalled:
            s1x, s1y, ok1 = _stop_hit(cs, wl, hx, hy, qx + h, qy, pupil)
            s2x, s2y, ok2 = _stop_hit(cs, wl, hx, hy, qx, qy + h, pupil)
            J = ((s1x - sx) / h, (s1y - sy) / h, (s2x - sx) / h, (s2y - sy) / h, ok1 & ok2)
        J11, J21, J12, J22, okJ = J
        det = J11 * J22 - J12 * J21
        upd = active & okJ & (np.abs(det) > 1e-18)
        if not np.any(upd):
            break
        dx = np.where(upd, (J22 * ex - J12 * ey) / np.where(upd, det, 1.0), 0.0)
        dy = np.where(upd, (-J21 * ex + J11 * ey) / np.where(upd, det, 1.0), 0.0)
        qx = qx - dx
        qy = qy - dy
        prev_err = err
    P, D, opl = _launch_from_pupil_points(cs, wl, hx, hy, qx, qy, pupil)
    return P, D, opl, qx, qy


def has_vignetting(cs: CompiledSystem, field) -> bool:
    if not isinstance(field, (int, np.integer)):
        return False
    f = cs.model.fields[field]
    return bool(f.vdx or f.vdy or f.vcx or f.vcy)


def vignetted_pupil(cs: CompiledSystem, field, px, py):
    """Normalised pupil coordinates after the field's vignetting factors:
    px' = vdx + px (1 - vcx), py' = vdy + py (1 - vcy) (the unit circle maps onto the
    part of the pupil that the apertures pass). Geometric pupil sampling (spot diagrams,
    ray and OPD fans, layout rays, automatic semi-diameters, best focus, geometric MTF and
    encircled energy, the merit function) uses it; chief rays and the diffraction,
    wavefront, throughput and polarisation analyses use the real, clipped pupil."""
    if not has_vignetting(cs, field):
        return px, py
    f = cs.model.fields[field]
    return f.vdx + np.asarray(px, float) * (1.0 - f.vcx), f.vdy + np.asarray(py, float) * (1.0 - f.vcy)


def trace_pupil(
    cs: CompiledSystem,
    wl: int,
    field: int | tuple[float, float],
    px: np.ndarray,
    py: np.ndarray,
    pupil: Pupil | None = None,
    clip: bool = True,
    fresnel: bool = False,
    end: int | None = None,
    aim_cache: dict | None = None,
    vignetting: bool = False,
    obscure: bool | None = None,
) -> TraceResult:
    """Trace normalised pupil coordinates of a field; vignetting=True applies the field's
    vignetting factors (vignetted_pupil) to the sampled coordinates; obscure as in trace."""
    if vignetting:
        px, py = vignetted_pupil(cs, field, px, py)
    P, D, opl = launch(cs, wl, field, px, py, pupil, aim_cache=aim_cache)
    return trace(cs, wl, P, D, opl, clip=clip, fresnel=fresnel, end=end, obscure=obscure)


def trace_fields(
    cs: CompiledSystem,
    wl: int,
    fields,
    px: np.ndarray,
    py: np.ndarray,
    pupil: Pupil | None = None,
    clip: bool = True,
    aim_cache: dict | None = None,
    vignetting: bool = False,
    obscure: bool | None = None,
) -> list[TraceResult]:
    """trace_pupil of several fields in one trace. Every ray is traced on its own (the surface steps and the
    Newton intersections act ray by ray), so each field's result equals its own trace_pupil to the last bit;
    the per-surface work is done once for all fields instead of once per field."""
    fields = list(fields)
    Ps, Ds, Os, counts = [], [], [], []
    for f in fields:
        qx, qy = vignetted_pupil(cs, f, px, py) if vignetting else (px, py)
        P, D, opl = launch(cs, wl, f, qx, qy, pupil, aim_cache=aim_cache)
        Ps.append(P)
        Ds.append(D)
        Os.append(np.asarray(opl, dtype=float))
        counts.append(len(P))
    r = trace(cs, wl, np.concatenate(Ps), np.concatenate(Ds), np.concatenate(Os), clip=clip, obscure=obscure)
    out, a = [], 0
    for c in counts:
        s = slice(a, a + c)
        out.append(
            TraceResult(
                points=r.points[s],
                local=r.local[s],
                dirs=r.dirs[s],
                status=r.status[s],
                fail_surface=r.fail_surface[s],
                opl=r.opl[s],
                intensity=r.intensity[s],
                start_points=r.start_points[s],
                start_dirs=r.start_dirs[s],
                end_surface=r.end_surface,
            )
        )
        a += c
    return out


def status_summary(res: TraceResult) -> dict:
    out: dict[str, int] = {}
    for code, txt in STATUS_TEXT.items():
        c = int(np.count_nonzero(res.status == code))
        if c:
            out[txt] = c
    return out


# ----------------------------------------------------------------------
# Pupil sampling patterns
# ----------------------------------------------------------------------


def hexapolar(rings: int) -> tuple[np.ndarray, np.ndarray]:
    """Hexapolar pattern: centre + ring k with 6k points (k = 1..rings)."""
    xs = [0.0]
    ys = [0.0]
    for k in range(1, rings + 1):
        r = k / rings
        m = 6 * k
        a = 2 * np.pi * np.arange(m) / m
        xs.extend(r * np.cos(a))
        ys.extend(r * np.sin(a))
    return np.array(xs), np.array(ys)


def square_grid(n: int) -> tuple[np.ndarray, np.ndarray]:
    """n x n grid over the unit square, keeping points inside the unit circle."""
    v = (np.arange(n) + 0.5) / n * 2 - 1
    X, Y = np.meshgrid(v, v)
    m = X**2 + Y**2 <= 1.0
    return X[m], Y[m]


def dithered(n: int, seed: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic quasi-random (Fibonacci / golden angle) disc sampling."""
    i = np.arange(n) + 0.5
    r = np.sqrt(i / n)
    a = i * math.pi * (3 - math.sqrt(5)) + seed
    return r * np.cos(a), r * np.sin(a)


def gauss_pupil(rings: int, arms: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Gaussian quadrature over the unit pupil (rings and arms).

    Radial nodes are Gauss-Legendre points in u = rho^2 on [0, 1] (the disc
    area element is proportional to du dtheta); arms are equally spaced and
    offset by half a step. Returns (px, py, weights) with weights summing to 1,
    so sum(w f) is the pupil-area mean of f. Exact for f = rho^(2k) with
    k <= 2*rings - 1 and for angular orders below the arm count. The default
    arm count (at least 2 rings + 2) is a multiple of 4, so the pattern maps onto
    itself under 90-degree rotations and both mirror axes: a field along x is
    sampled exactly like one along y (10 arms would give the cell-phone lens an
    RMS spot of 7.183 um along y and 7.157 um along x)."""
    rings = max(1, int(rings))
    arms = arms or 4 * math.ceil(max(8, 2 * rings + 2) / 4)
    x, w = np.polynomial.legendre.leggauss(rings)
    u = (x + 1.0) / 2.0
    wr = w / 2.0  # sums to 1 over [0, 1]
    th = (np.arange(arms) + 0.5) * 2 * np.pi / arms
    rho = np.sqrt(u)
    px = (rho[:, None] * np.cos(th)[None, :]).ravel()
    py = (rho[:, None] * np.sin(th)[None, :]).ravel()
    wt = (wr[:, None] * np.full(arms, 1.0 / arms)[None, :]).ravel()
    return px, py, wt


def pupil_pattern(name: str, density: int) -> tuple[np.ndarray, np.ndarray]:
    if name == "hexapolar":
        return hexapolar(max(1, density))
    if name == "square":
        return square_grid(max(2, density))
    if name == "dithered":
        return dithered(max(8, density))
    raise ValueError(f"Unknown pupil pattern '{name}'")
