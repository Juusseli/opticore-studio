"""Field definitions: conversion of image-space fields to object-space fields.

Rays are always launched from an object-space field: an angle (degrees, as
tan components: the chief ray direction is (tan x, tan y, 1)) for an object
at infinity, an object height (mm) for a finite object. Image-space field
types are resolved to that object field at the primary wavelength, so all
wavelengths of one field share the object point (as in a real instrument):

  paraxial_image_height  linear: the paraxial chief ray of a unit object field
                         gives the paraxial image height per unit (tan) field
                         at the paraxial image plane; components independently.
  image_height           real: the object field whose real chief ray (pupil
                         centre, the system's ray aiming) meets the image
                         surface at (hx, hy) in its local frame. Solved by
                         Newton iteration with a finite-difference Jacobian,
                         starting from the paraxial estimate; tolerance
                         FIELD_TOL. Fails with an error when the height cannot
                         be reached (e.g. beyond the field the system accepts).

Results are cached on the compiled system.

Field geometry (field_size, field_direction, field_along). Angle components are tan components, not a
Euclidean vector: the field (ax, ay) deg has the true field angle atan(hypot(tan ax, tan ay)) and the
azimuth of (tan ax, tan ay); (23.82, 23.82) deg is a 31.98 deg field, not hypot = 33.69. Analyses that
rank fields, follow a field direction or build new fields along one use these helpers; heights (mm,
object or image) combine as plain vectors.
"""

from __future__ import annotations

import math

import numpy as np

from .system import CompiledSystem, Diagnostic, SystemError_

FIELD_TOL = 1e-12  # mm on the image surface (finite-difference Jacobians need the field consistent far below their steps)
FIELD_MAX_ITER = 40

IMAGE_FIELDS = ("image_height", "paraxial_image_height")


def object_kind(cs: CompiledSystem) -> str:
    """'angle' or 'object_height': the object-space field used to launch rays."""
    m = cs.model
    if m.object_at_infinity:
        return "angle"
    return "angle" if m.field_type == "angle" else "object_height"


def system_field_kind(model) -> str:
    """'angle' when the system's own field values are angles (field_type 'angle'), else 'height' (object or image
    heights, mm): how field_size, field_direction and field_along combine the model's field components."""
    return "angle" if model.field_type == "angle" else "height"


def field_size(kind: str, fx: float, fy: float) -> float:
    """Distance of a field from the axis (module notes): the true field angle atan(hypot(tan x, tan y)) in degrees for
    kind 'angle', hypot(x, y) otherwise. Fields on an axis give |component| exactly."""
    if kind != "angle" or fx == 0.0 or fy == 0.0:
        return math.hypot(fx, fy)
    return math.degrees(math.atan(math.hypot(math.tan(math.radians(fx)), math.tan(math.radians(fy)))))


def field_direction(kind: str, fx: float, fy: float) -> tuple[float, float] | None:
    """Unit azimuth of a field in the x-y plane, (tan x, tan y) normalised for kind 'angle' and (x, y) otherwise;
    None on the axis. Fields on an axis give exact unit components."""
    if fx == 0.0 and fy == 0.0:
        return None
    if fx == 0.0:
        return 0.0, math.copysign(1.0, fy)
    if fy == 0.0:
        return math.copysign(1.0, fx), 0.0
    a, b = (math.tan(math.radians(fx)), math.tan(math.radians(fy))) if kind == "angle" else (fx, fy)
    n = math.hypot(a, b)
    return a / n, b / n


def field_along(kind: str, v: float, ux: float, uy: float) -> tuple[float, float]:
    """The field of size v (field_size; negative v points the other way) along the unit azimuth (ux, uy):
    (atan(tan v ux), atan(tan v uy)) for kind 'angle', (v ux, v uy) otherwise. Components along the axes are exact."""

    def comp(c: float) -> float:
        if c == 0.0:
            return 0.0
        if abs(c) == 1.0 or kind != "angle":
            return v * c
        return math.degrees(math.atan(math.tan(math.radians(v)) * c))

    return comp(ux), comp(uy)


def tangential_direction(model, index: int) -> tuple[float, float]:
    """Unit azimuth of the tangential (meridional) plane of field `index` of a model: the field's own azimuth
    (field_direction in the model's field units); for a field on the axis the largest field's, and +y when every field
    is on the axis. The sagittal azimuth is (uy, -ux), so fields along +y keep tangential = y and sagittal = x."""
    kind = system_field_kind(model)
    f = model.fields[index]
    u = field_direction(kind, f.x, f.y)
    if u is None and model.fields:
        big = max(model.fields, key=lambda g: field_size(kind, g.x, g.y))
        u = field_direction(kind, big.x, big.y)
    return u or (0.0, 1.0)


def _to_object(kind: str, ux: float, uy: float) -> tuple[float, float]:
    """Internal unknowns (tan components for angles, mm for heights) -> object field units."""
    if kind == "angle":
        return math.degrees(math.atan(ux)), math.degrees(math.atan(uy))
    return ux, uy


def object_field(cs: CompiledSystem, hx: float, hy: float, warm: dict | None = None) -> tuple[float, float]:
    """Object-space field (degrees or mm) for a field value given in the system's field units. `warm`
    (optional, e.g. the optimiser's aim cache) keeps real image-height solutions across systems as starts."""
    ft = cs.model.field_type
    if ft not in IMAGE_FIELDS:
        return float(hx), float(hy)
    key = (ft, float(hx), float(hy))
    hit = cs.field_cache.get(key)
    if hit is not None:
        return hit
    if ft == "paraxial_image_height":
        k = paraxial_image_scale(cs)
        out = _to_object(object_kind(cs), hx / k, hy / k)
    else:
        out = _solve_real_image_height(cs, float(hx), float(hy), warm)
    cs.field_cache[key] = out
    return out


def paraxial_image_scale(cs: CompiledSystem) -> float:
    """Paraxial chief-ray height at the paraxial image plane per unit object field (tan or mm), primary wavelength."""
    k = cs.field_cache.get("_pscale")
    if k is not None:
        return k
    from .paraxial import chief_ray_object, compute_pupil, marginal_ray

    wl = cs.model.primary_wavelength
    pupil = compute_pupil(cs, wl)
    last = cs.n_surfaces - 2
    m = marginal_ray(cs, wl, pupil)
    if abs(m.u[last]) < 1e-15:
        raise SystemError_("Paraxial image-height fields need a focal system (the paraxial image is at infinity)", [Diagnostic("error", "FIELD_AFOCAL", "Afocal system: use angle or object-height fields")])
    img_dist = -m.y[last] / m.u[last]
    unit = 45.0 if object_kind(cs) == "angle" else 1.0  # tan(45 deg) = 1
    c = chief_ray_object(cs, wl, pupil, unit)
    k = float(c.y[last] + img_dist * c.u[last])
    if not math.isfinite(k) or abs(k) < 1e-15:
        raise SystemError_("The paraxial chief ray does not reach a finite image height", [Diagnostic("error", "FIELD_SCALE", "Paraxial image height cannot be converted to an object field")])
    cs.field_cache["_pscale"] = k
    return k


def _chief_landing(cs: CompiledSystem, kind: str, ux: float, uy: float) -> tuple[float, float] | None:
    from .paraxial import compute_pupil
    from .raytrace import launch, trace
    from .surfaces import OK

    wl = cs.model.primary_wavelength
    pupil = compute_pupil(cs, wl)
    ox, oy = _to_object(kind, ux, uy)
    P, D, opl = launch(cs, wl, (ox, oy), np.array([0.0]), np.array([0.0]), pupil, object_units=True)
    r = trace(cs, wl, P, D, opl, clip=False)
    if r.status[0] != OK:
        return None
    x, y = r.local[0, cs.n_surfaces - 1, :2]
    return float(x), float(y)


def _jacobian(cs: CompiledSystem, kind: str, u: np.ndarray, f0) -> np.ndarray | None:
    """d(landing)/d(u) by forward differences (backward ones where the forward chief ray fails, at the edge
    of the accepted field)."""
    h = 1e-7 * max(1.0, float(np.max(np.abs(u))))
    cols = []
    for d in (np.array([h, 0.0]), np.array([0.0, h])):
        fp = _chief_landing(cs, kind, *(u + d))
        if fp is not None:
            cols.append((np.array(fp) - np.array(f0)) / h)
            continue
        fm = _chief_landing(cs, kind, *(u - d))
        if fm is None:
            return None
        cols.append((np.array(f0) - np.array(fm)) / h)
    return np.array(cols).T


def _newton(cs: CompiledSystem, kind: str, target: np.ndarray, u0: np.ndarray, scale: float):
    """Damped Newton iteration for the object field u whose real chief ray lands on `target`, with a
    backtracking line search (a trial point whose chief ray fails, or that does not reduce the error, is
    halved towards the last point). Returns (u, J) at convergence or None."""
    u = np.array(u0, dtype=float)
    f0 = _chief_landing(cs, kind, *u)
    if f0 is None:
        return None
    for _ in range(FIELD_MAX_ITER):
        e = np.array(f0) - target
        err = float(np.max(np.abs(e)))
        J = _jacobian(cs, kind, u, f0)
        if J is None:
            return None
        if err < FIELD_TOL * scale:
            return u, J
        try:
            step = np.linalg.solve(J, e)
        except np.linalg.LinAlgError:
            return None
        lim = 0.5 * max(1.0, float(np.max(np.abs(u))))  # damp large steps (strongly non-linear fields)
        if np.max(np.abs(step)) > lim:
            step *= lim / np.max(np.abs(step))
        for _ in range(12):
            un = u - step
            fn = _chief_landing(cs, kind, *un)
            if fn is not None and float(np.max(np.abs(np.array(fn) - target))) < err:
                u, f0 = un, fn
                break
            step = 0.5 * step
        else:
            return None
    return None


def _axis(cs: CompiledSystem, kind: str):
    """Landing point of the on-axis object field's chief ray and the orientation (sign of det J) of the
    chief-ray map there; cached on the compiled system."""
    hit = cs.field_cache.get("_axis")
    if hit is None:
        f0 = _chief_landing(cs, kind, 0.0, 0.0)
        J = _jacobian(cs, kind, np.zeros(2), f0) if f0 is not None else None
        hit = (np.array(f0), float(np.sign(np.linalg.det(J)))) if J is not None else (None, 0.0)
        cs.field_cache["_axis"] = hit
    return hit


def _solve_real_image_height(cs: CompiledSystem, hx: float, hy: float, warm: dict | None = None) -> tuple[float, float]:
    """Object field of the real chief ray that meets (hx, hy) on the image surface. Newton from the warm start
    (the previous solution of the same field, e.g. of the optimiser's last design) or the paraxial estimate;
    the solution must lie on the first branch from the axis, where the chief-ray map keeps the orientation it
    has on the axis (beyond a fold of the field several object fields meet the same height and det J changes
    sign). Otherwise the field is followed out from the axis in steps (continuation), which also finds
    solutions that a Newton start beyond the fold misses."""
    kind = object_kind(cs)
    if hx == 0.0 and hy == 0.0 and cs.axial:
        return 0.0, 0.0
    from .paraxial import chief_ray_object, compute_pupil

    wl = cs.model.primary_wavelength
    pupil = compute_pupil(cs, wl)
    img = cs.n_surfaces - 1
    unit = 45.0 if kind == "angle" else 1.0
    k = float(chief_ray_object(cs, wl, pupil, unit).y[img])
    if not math.isfinite(k) or abs(k) < 1e-12:
        k = paraxial_image_scale(cs)
    target = np.array([hx, hy])
    scale = max(1.0, abs(hx), abs(hy))
    base, orient = _axis(cs, kind)
    if base is None or orient == 0.0:
        raise _unreachable(hx, hy)

    def first_branch(res) -> bool:
        return res is not None and float(np.sign(np.linalg.det(res[1]))) == orient

    key = ("image_field", float(hx), float(hy))
    starts = [np.array(warm[key])] if warm is not None and key in warm else []
    starts.append(target / k)
    for u0 in starts:
        res = _newton(cs, kind, target, u0, scale)
        if first_branch(res):
            return _store(warm, key, kind, res[0])
    # continuation from the axis: targets base + t (target - base), each Newton from the last solution;
    # a step that fails is halved
    u, t, dt = np.zeros(2), 0.0, 0.25
    while t < 1.0:
        tn = min(1.0, t + dt)
        res = _newton(cs, kind, base + tn * (target - base), u + (tn - t) * (target - base) / k, scale)
        if not first_branch(res):
            dt *= 0.5
            if dt < 1.0 / 512:
                raise _unreachable(hx, hy)
            continue
        u, t = res[0], tn
        dt = min(0.25, 2.0 * dt)
    return _store(warm, key, kind, u)


def _store(warm: dict | None, key, kind: str, u: np.ndarray) -> tuple[float, float]:
    if warm is not None:
        warm[key] = (float(u[0]), float(u[1]))
    return _to_object(kind, *u)


def _unreachable(hx: float, hy: float) -> SystemError_:
    msg = f"Image height ({hx:g}, {hy:g}) mm cannot be reached by a real chief ray (the field is outside what the system accepts, or rays fail)"
    return SystemError_(msg, [Diagnostic("error", "FIELD_UNREACHABLE", msg)])
