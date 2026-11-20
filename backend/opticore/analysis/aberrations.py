"""Ray fans, field curvature, distortion, longitudinal and chromatic aberration."""

from __future__ import annotations

import math

import numpy as np

from ..paraxial import chief_ray, compute_pupil, trace_paraxial
from ..raytrace import trace_pupil
from ..surfaces import OK
from ..system import CompiledSystem, NotApplicable, SystemError_


def ray_fan(cs: CompiledSystem, samples: int = 41, fields: list[int] | None = None) -> dict:
    """Transverse ray aberration fans on the image surface.

    The fans follow each field's own azimuth u = (ux, uy) (fields.tangential_direction: (tan x, tan y) normalised for
    angle fields; on the axis the largest field's, +y when all fields are on the axis), with the sagittal azimuth
    s = (uy, -ux). Tangential fan: the error along u for pupil points p u; sagittal fan: the error along s for p s.
    For fields along +y this is e_y(py) at px = 0 and e_x(px) at py = 0 (the keys keep those names).
    Errors are relative to the primary-wavelength chief ray of each field, in
    micrometres; failed rays are reported as null."""
    from ..fields import tangential_direction

    pupil = compute_pupil(cs)
    p = np.linspace(-1.0, 1.0, samples)
    prim = cs.model.primary_wavelength
    fields = list(range(len(cs.model.fields))) if fields is None else fields
    out = []
    for f in fields:
        ux, uy = tangential_direction(cs.model, f)
        sx, sy = uy, -ux
        ch = trace_pupil(cs, prim, f, np.array([0.0]), np.array([0.0]), pupil, obscure=False)
        ref = ch.image_xy()[0] if ch.ok[0] else np.array([np.nan, np.nan])
        per_wl = []
        for w in range(len(cs.wavelengths)):
            # + 0.0: no negative zeros in the pupil coordinates
            rt = trace_pupil(cs, w, f, p * ux + 0.0, p * uy + 0.0, pupil, vignetting=True)
            rs = trace_pupil(cs, w, f, p * sx + 0.0, p * sy + 0.0, pupil, vignetting=True)
            et = np.where(rt.ok, (rt.image_xy() - ref) @ np.array([ux, uy]), np.nan) * 1e3
            es = np.where(rs.ok, (rs.image_xy() - ref) @ np.array([sx, sy]), np.nan) * 1e3
            per_wl.append({"wavelength": w, "tangential_ey_um": et.tolist(), "sagittal_ex_um": es.tolist()})
        out.append({"field": f, "field_value": [cs.model.fields[f].x, cs.model.fields[f].y], "direction": [ux, uy], "per_wavelength": per_wl})
    return {
        "pupil": p.tolist(),
        "fields": out,
        "units": {"pupil": "normalised", "error": "um"},
        "method": "Real-ray transverse aberration relative to the primary-wavelength chief ray, tangential along the field's azimuth and sagittal across it",
    }


def _closest_point_param(P1, D1, P2, D2):
    """Parameter t on ray 1 of the point closest to ray 2."""
    w = P1 - P2
    a = D1 @ D1
    b = D1 @ D2
    c = D2 @ D2
    d = D1 @ w
    e = D2 @ w
    den = a * c - b * b
    if abs(den) < 1e-20:
        return None
    return (b * e - c * d) / den


def field_curvature_distortion(cs: CompiledSystem, samples: int = 21, wavelengths: list[int] | None = None, eps: float = 1e-3) -> dict:
    """Tangential/sagittal focus shift and distortion versus field, along the direction of the largest field.

    Foci are located from pairs of real rays symmetric about the chief ray
    (normalised pupil +-eps) in the tangential plane (containing the field
    direction) and the sagittal plane; values are longitudinal distances (mm)
    from the image surface along its local z.
    Distortion = (h_real - h_ref) / h_ref, both measured on the image surface
    along the reference direction, with h_real the real chief-ray landing and
    h_ref the reference landing (equals F-tan(theta) distortion when the image
    surface is at focus):
    * fields along y only: the paraxial chief-ray height (y-nu trace);
    * a field with an x component in a rotationally symmetric system
      (_rotationally_symmetric): the same paraxial reference in the field's
      azimuth (_paraxial_reference), so a field along x or a diagonal gives
      the number of the same field along y;
    * otherwise (biconic, XY polynomial, Zernike, tilts and decentres): the
      linear limit of the real chief ray (_linear_reference), which follows
      the x-z section of an anamorphic system where the paraxial trace knows
      only the y-z section.
    The field runs from the axis to the largest field along its azimuth, as a
    field size (fields.field_size: the true angle of an angle field, built
    along the azimuth by fields.field_along)."""
    from ..fields import field_along, field_direction, field_size, system_field_kind

    pupil = compute_pupil(cs)
    model = cs.model
    kind = system_field_kind(model)
    hmax = max(field_size(kind, f.x, f.y) for f in model.fields)
    vals = np.linspace(0.0, hmax, samples) if hmax > 0 else np.array([0.0])
    wavelengths = list(range(len(cs.wavelengths))) if wavelengths is None else wavelengths
    img = cs.n_surfaces - 1
    fr = cs.frames[img]
    # direction of the largest field (+y when every field lies on the y axis)
    along_y = all(f.x == 0.0 for f in model.fields) or hmax == 0.0
    ux, uy = (0.0, 1.0)
    if not along_y:
        big = max(model.fields, key=lambda f: field_size(kind, f.x, f.y))
        ux, uy = field_direction(kind, big.x, big.y)
    sx, sy = uy, -ux  # sagittal direction
    paraxial_ref = _rotationally_symmetric(cs)
    per_wl = []
    for w in wavelengths:
        tan_f, sag_f, dist, yreal, yref = [], [], [], [], []
        ref = None if along_y else (_paraxial_reference(cs, w, pupil, img) if paraxial_ref else _linear_reference(cs, w, pupil, img, hmax))
        for h in vals:
            field = field_along(kind, float(h), ux, uy) if not along_y else (0.0, float(h))
            px = np.array([0.0, eps * ux, -eps * ux, eps * sx, -eps * sx])
            py = np.array([0.0, eps * uy, -eps * uy, eps * sy, -eps * sy])
            r = trace_pupil(cs, w, field, px, py, pupil, clip=False)
            if not np.all(r.status == OK):
                tan_f.append(None)
                sag_f.append(None)
                dist.append(None)
                yreal.append(None)
                yref.append(None)
                continue
            Pl = r.local[:, img, :]
            Dl = fr.to_local_dirs(r.dirs)
            # tangential: rays 1 & 2; sagittal: rays 3 & 4
            def focus(a, b):
                t = _closest_point_param(Pl[a], Dl[a], Pl[b], Dl[b])
                if t is None:
                    return None
                q = Pl[a] + t * Dl[a]
                return float(q[2])

            tan_f.append(focus(1, 2))
            sag_f.append(focus(3, 4))
            if along_y:
                y_chief = float(Pl[0, 1])
                yreal.append(y_chief)
                # paraxial chief-ray height at the (actual) image surface
                c = chief_ray(cs, w, pupil, float(h))
                y_par = float(c.y[img]) if np.isfinite(c.y[img]) else float("nan")
                yref.append(y_par)
                if h > 0 and abs(y_par) > 1e-15:
                    dist.append((y_chief - y_par) / y_par * 100.0)
                else:
                    dist.append(0.0 if h == 0 else None)
                continue
            # along the reference direction: the reference landing's offset from the axis landing
            P = Pl[0, :2]
            q = None if ref is None or h == 0 else ref(field)
            if q is None:
                yreal.append(float(P[0] * ux + P[1] * uy))
                yref.append(None if h > 0 else 0.0)
                dist.append(0.0 if h == 0 else None)
                continue
            L0, R = q
            d = R - L0
            nd = float(np.hypot(d[0], d[1]))
            if nd <= 1e-15:
                yreal.append(float(P[0] * ux + P[1] * uy))
                yref.append(None)
                dist.append(None)
                continue
            rhat = d / nd
            # heights signed along the field direction, as the y heights of fields along y (an inverted image < 0)
            sgn = -1.0 if float(rhat[0] * ux + rhat[1] * uy) < 0.0 else 1.0
            yreal.append(sgn * float((P - L0) @ rhat))
            yref.append(sgn * nd)
            dist.append(float((P - R) @ rhat / nd * 100.0))
        per_wl.append(
            {
                "wavelength": w,
                "tangential_mm": tan_f,
                "sagittal_mm": sag_f,
                "distortion_percent": dist,
                "real_chief_height_mm": yreal,
                "paraxial_height_mm": yref,
            }
        )
    return {
        "field_values": vals.tolist(),
        "field_type": model.field_type,
        "per_wavelength": per_wl,
        "units": {"focus": "mm from image surface", "distortion": "%", "field": "deg" if model.field_type == "angle" else "mm"},
        "direction": [ux, uy],
        "method": "Real differential rays about the chief ray along the largest field's direction; distortion vs the paraxial chief-ray height (fields along y, and any azimuth of a rotationally symmetric system) or the linear limit of the real chief ray (other systems with fields off the y axis)",
    }


def _rotationally_symmetric(cs: CompiledSystem) -> bool:
    """True when the system is rotationally symmetric about its axis, so the paraxial (y-nu) data hold in every azimuth:
    no coordinate breaks or tilted/decentred surfaces (cs.axial), rotationally symmetric shapes (standard, even and odd
    aspheres, Q-type, biconics with equal sections; ideal lenses and coordinate breaks are planes), no linear gratings
    and no crystals."""
    from ..surfaces import BiconicShape, OddShape, QShape, Shape

    def symmetric(s) -> bool:
        if type(s) in (Shape, OddShape, QShape):
            return True
        return type(s) is BiconicShape and s.curvature == s.curvature_x and s.conic == s.conic_x

    return (
        cs.axial
        and all(symmetric(s) for s in cs.shapes)
        and all(d is None or d.frequency == 0 for d in cs.does)
        and all(c is None for c in cs.crystal)
    )


def _internal_field(cs: CompiledSystem, kind: str, fx: float, fy: float) -> np.ndarray:
    """The object-space field of a field value (system units) as launched: tan of the angles, or the object heights."""
    from ..fields import object_field

    ox, oy = object_field(cs, fx, fy)
    if kind == "angle":
        return np.array([math.tan(math.radians(ox)), math.tan(math.radians(oy))])
    return np.array([ox, oy], dtype=float)


def _paraxial_reference(cs: CompiledSystem, w: int, pupil, img: int):
    """The paraxial reference of a rotationally symmetric system in any azimuth: a function field -> (axis landing 0,
    reference landing k t) on the image surface, with t the launched object field (_internal_field) and k the paraxial
    chief-ray height on the image surface per unit t (y-nu trace, linear in the field). For a field along y, k t is
    the paraxial chief-ray height of the fields-along-y branch. None when the paraxial chief ray fails."""
    from ..fields import object_kind
    from ..paraxial import chief_ray_object

    kind = object_kind(cs)
    unit = 45.0 if kind == "angle" else 1.0
    k = float(chief_ray_object(cs, w, pupil, unit).y[img]) / (math.tan(math.radians(unit)) if kind == "angle" else 1.0)
    if not math.isfinite(k):
        return None
    L0 = np.zeros(2)

    def ref(field):
        try:
            t = _internal_field(cs, kind, *field)
        except (ValueError, ArithmeticError, SystemError_):
            return None
        return L0, k * t

    return ref


def _linear_reference(cs: CompiledSystem, w: int, pupil, img: int, hmax: float):
    """The linear limit of the real chief ray: a function field -> (axis landing L0, reference landing R) on the
    image surface (local x, y), or None when the small-field chief rays fail.

    R = L0 + M (t - t0), with t the object-space field as launched (_internal_field) and M the 2x2 map from t to the
    landing. M(d) is measured with chief rays at d along x and y (d = 1e-5 of the largest field) and extrapolated to
    d -> 0 by Richardson, M = 2 M(d) - M(2d): a one-sided difference carries an error linear in d from every even part
    of the chief-ray map (h^2 of a decentred system, and h|h| of an r^3 odd asphere, which a symmetric difference
    would not cancel either: h|h| is odd); the extrapolation leaves O(d^2) (the cell phone lens: 3.5e-10 of M, where
    a plain one-sided step of 1e-4 is 3.5e-5 off). For a rotationally symmetric system M is the paraxial magnification; for
    an anamorphic one each column follows its own section."""
    from ..fields import object_kind

    kind = object_kind(cs)

    def landing(fx: float, fy: float):
        r = trace_pupil(cs, w, (fx, fy), np.array([0.0]), np.array([0.0]), pupil, obscure=False, clip=False)
        return np.array(r.local[0, img, :2], dtype=float) if r.ok[0] else None

    def internal(fx: float, fy: float) -> np.ndarray:
        return _internal_field(cs, kind, fx, fy)

    d = 1e-5 * hmax
    try:
        L0 = landing(0.0, 0.0)
        if L0 is None:
            return None
        t0 = internal(0.0, 0.0)

        def M_at(s: float) -> np.ndarray | None:
            Lx, Ly = landing(s, 0.0), landing(0.0, s)
            if Lx is None or Ly is None:
                return None
            T = np.column_stack([internal(s, 0.0) - t0, internal(0.0, s) - t0])
            return np.column_stack([Lx - L0, Ly - L0]) @ np.linalg.inv(T)

        M1, M2 = M_at(d), M_at(2.0 * d)
        if M1 is None or M2 is None:
            return None
        M = 2.0 * M1 - M2
    except (ValueError, ArithmeticError, np.linalg.LinAlgError, SystemError_):
        return None

    def ref(field):
        try:
            t = internal(*field)
        except (ValueError, ArithmeticError, SystemError_):
            return None
        return L0, L0 + M @ (t - t0)

    return ref


def longitudinal_aberration(cs: CompiledSystem, samples: int = 21) -> dict:
    """Axial intercept of on-axis meridional rays versus pupil height, per
    wavelength, relative to the image surface (mm). Uses the on-axis field."""
    pupil = compute_pupil(cs)
    img = cs.n_surfaces - 1
    fr = cs.frames[img]
    p = np.linspace(0.0, 1.0, samples)
    p[0] = 1e-4  # avoid the axial ray (undefined intercept)
    out = []
    for w in range(len(cs.wavelengths)):
        r = trace_pupil(cs, w, (0.0, 0.0), np.zeros_like(p), p, pupil, clip=True)
        Pl = r.local[:, img, :]
        Dl = fr.to_local_dirs(r.dirs)
        with np.errstate(divide="ignore", invalid="ignore"):
            t = -Pl[:, 1] / Dl[:, 1]
            z = Pl[:, 2] + t * Dl[:, 2]
        z = np.where(r.ok & np.isfinite(z), z, np.nan)
        out.append({"wavelength": w, "focus_mm": z.tolist()})
    return {
        "pupil": p.tolist(),
        "per_wavelength": out,
        "units": {"pupil": "normalised", "focus": "mm from image surface"},
        "method": "Real meridional rays from the axial object point",
    }


def chromatic_focal_shift(cs: CompiledSystem, lam_min: float | None = None, lam_max: float | None = None, samples: int = 41) -> dict:
    """Paraxial back focal distance versus wavelength relative to the primary wavelength."""
    import copy

    wls = cs.wavelengths
    lam_min = lam_min or float(min(wls.min(), 0.4861327))
    lam_max = lam_max or float(max(wls.max(), 0.6562725))
    lams = np.linspace(lam_min, lam_max, samples)
    model = cs.model
    lib = cs.library
    last = cs.n_surfaces - 2
    pupil = compute_pupil(cs)

    def bfd(lam: float) -> float:
        # temporary per-wavelength signed index row
        from ..environment import element_temperatures, medium_index

        temps = element_temperatures(model) if model.environment_enabled else {}
        ns = np.empty(cs.n_surfaces)
        sign = 1.0
        name, owner = model.surfaces[0].material, model.surfaces[0].id
        for i, s in enumerate(model.surfaces):
            if i > 0 and s.is_mirror:
                sign = -sign
            if i == 0 or not (s.is_mirror or s.type == "coordinate_break"):
                name, owner = s.material, s.id
            ns[i] = sign * medium_index(lib, name, lam, temps.get(owner))
        tmp = copy.copy(cs)
        tmp.n_signed = ns[None, :]
        tmp.wavelengths = np.array([lam])  # diffractive power is wavelength dependent
        d0 = model.surfaces[0].thickness
        if d0 is None:
            ray = trace_paraxial(tmp, 0, pupil.r_ep, 0.0, 1, last)
        else:
            u = pupil.u_marginal if pupil.telecentric else pupil.r_ep / (pupil.z_ep + d0)
            ray = trace_paraxial(tmp, 0, u * d0, u, 1, last)
        u_last = float(ray.u[last])
        return -float(ray.y[last]) / u_last if u_last != 0.0 else math.inf

    ref = bfd(float(cs.wavelengths[model.primary_wavelength]))
    if not math.isfinite(ref):
        raise NotApplicable("No paraxial focus (afocal or collimated image space): axial colour is not a focal shift")
    shift = [(bfd(float(l)) - ref) * 1e3 for l in lams]
    return {
        "wavelength_um": lams.tolist(),
        "focal_shift_um": shift,
        "units": {"wavelength": "um", "shift": "um"},
        "method": "Paraxial marginal-ray image distance relative to the primary wavelength",
    }
