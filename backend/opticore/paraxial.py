"""First-order (paraxial) optics using the y-nu method on the unfolded axis.

Reflections are handled with signed indices (n' = -n at a mirror) and the
signed thickness convention, so reduced quantities stay consistent.
All paraxial results are flagged "paraxial" in the API; they are first-order
approximations, not real-ray results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np

from .system import CompiledSystem, Diagnostic, SystemError_


@dataclass
class ParaxialRay:
    y: np.ndarray  # height at each surface vertex plane (index 0 unused for infinite objects)
    nu: np.ndarray  # reduced slope n*u after each surface
    u: np.ndarray  # slope after each surface


def trace_paraxial(cs: CompiledSystem, wl: int, y1: float, u0: float, start: int = 1, end: int | None = None) -> ParaxialRay:
    """Trace a paraxial ray that arrives at surface `start` with height y1 and
    slope u0 (in the medium before `start`). Returns per-surface data; entries
    before `start` are NaN. `end` is inclusive (default: image surface)."""
    n = cs.n_surfaces
    end = n - 1 if end is None else end
    surfs = cs.model.surfaces
    ns = cs.n_signed[wl]
    y = np.full(n, np.nan)
    nu = np.full(n, np.nan)
    u = np.full(n, np.nan)
    y_cur = y1
    nu_cur = ns[start - 1] * u0
    # entry start-1 holds the incoming ray (slope before surface `start`)
    nu[start - 1] = nu_cur
    u[start - 1] = u0
    for j in range(start, end + 1):
        c = cs.shapes[j].curvature if not cs.is_cb[j] else 0.0
        n1 = ns[j - 1]
        n2 = ns[j]
        y[j] = y_cur
        phi = (n2 - n1) * c
        doe = cs.does[j] if cs.does else None
        if doe is not None:
            phi += doe.paraxial_power(float(cs.wavelengths[wl]) * 1e-3)
        lens = cs.ideal[j] if cs.ideal else None
        if lens is not None:
            # ideal lens: u' = u - y/f along the light in a medium n; with signed indices phi = |n| / f
            phi += abs(n1) * lens.inv_f
        nu_cur = nu_cur - y_cur * phi
        nu[j] = nu_cur
        u[j] = nu_cur / n2
        t = surfs[j].thickness or 0.0
        if j < end:
            y_cur = y_cur + t * u[j]
    return ParaxialRay(y=y, nu=nu, u=u)


@dataclass
class ParaxialData:
    wavelength_um: float
    efl: float | None
    bfl: float | None
    ffl: float | None
    front_principal_plane: float | None  # relative to surface 1 vertex
    rear_principal_plane: float | None  # relative to last optical surface vertex
    power: float
    entrance_pupil_position: float | None  # relative to surface 1 vertex (+z to the right)
    entrance_pupil_diameter: float
    exit_pupil_position: float | None  # relative to image surface
    exit_pupil_diameter: float | None
    stop_semi_diameter: float
    image_space_fnum: float | None
    working_fnum: float | None
    image_space_na: float | None
    object_space_na: float | None
    paraxial_magnification: float | None
    paraxial_image_distance: float | None  # from last optical surface (signed thickness units)
    paraxial_image_height: float | None  # chief ray height at the paraxial image plane
    image_surface_defocus: float | None  # last thickness minus paraxial image distance
    lagrange_invariant: float | None
    total_track: float
    max_field: float
    approximate: bool

    def as_dict(self) -> dict:
        d = asdict(self)
        return {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in d.items()}


def _finite(x: float) -> float | None:
    return x if (x is not None and math.isfinite(x)) else None


class Pupil:
    """Paraxial entrance pupil description used for ray launching."""

    def __init__(self, z_ep: float, r_ep: float, r_stop: float, telecentric: bool, u_marginal: float | None = None):
        self.z_ep = z_ep  # global z of the entrance pupil plane (inf for object-space telecentric)
        self.r_ep = r_ep  # entrance pupil radius (inf for object-space telecentric)
        self.r_stop = r_stop
        self.telecentric = telecentric
        self.u_marginal = u_marginal  # object-space telecentric: paraxial marginal slope tan(asin(NA/n0))


def system_matrix_to(cs: CompiledSystem, wl: int, end: int):
    """Heights at surface `end` for the unit rays A (y=1,u=0) and B (y=0,u=1)
    launched at surface 1 in object space (end inclusive, before refraction at end)."""
    A = trace_paraxial(cs, wl, 1.0, 0.0, 1, end)
    B = trace_paraxial(cs, wl, 0.0, 1.0, 1, end)
    return A, B


def compute_pupil(cs: CompiledSystem, wl: int | None = None) -> Pupil:
    wl = cs.wl_index(wl)
    model = cs.model
    stop = cs.stop
    A, B = system_matrix_to(cs, wl, stop)
    yA, yB = A.y[stop], B.y[stop]
    n0 = cs.n_after[wl, 0]
    d0 = model.surfaces[0].thickness
    if model.object_space_telecentric:
        s = model.aperture.value / n0
        if s >= 1.0:
            raise SystemError_("Object-space NA must be smaller than the object-space index")
        u0 = math.tan(math.asin(s))
        m = trace_paraxial(cs, wl, u0 * d0, u0, 1, stop)
        return Pupil(z_ep=math.inf, r_ep=math.inf, r_stop=abs(float(m.y[stop])), telecentric=True, u_marginal=u0)
    telecentric = abs(yA) < 1e-14
    if telecentric:
        raise SystemError_(
            "The aperture stop is imaged to infinity in object space (telecentric entrance pupil); switch on 'object-space telecentric' with an object-space NA",
            [Diagnostic("error", "TELECENTRIC_EP", "The entrance pupil is at infinity: enable object-space telecentric mode (system settings)", stop)],
        )
    z_ep = yB / yA  # relative to surface 1 (global origin)
    ap = model.aperture
    if ap.type == "epd":
        r_ep = ap.value / 2.0
    elif ap.type == "image_fnum":
        efl = effective_focal_length(cs, wl)
        if efl is None:
            raise SystemError_("Image-space F/# needs a finite focal length (afocal system)")
        r_ep = abs(efl) / ap.value / 2.0
    else:  # object_na
        if d0 is None:
            raise SystemError_("Object-space NA requires a finite object distance")
        s = ap.value / n0
        if s >= 1.0:
            raise SystemError_("Object-space NA must be smaller than the object-space index")
        r_ep = abs((z_ep + d0) * math.tan(math.asin(s)))
    r_stop = abs(r_ep * yA)
    return Pupil(z_ep=z_ep, r_ep=r_ep, r_stop=r_stop, telecentric=telecentric)


def effective_focal_length(cs: CompiledSystem, wl: int) -> float | None:
    last = cs.n_surfaces - 2
    A = trace_paraxial(cs, wl, 1.0, 0.0, 1, last)
    nu_k = A.nu[last]
    if abs(nu_k) < 1e-15:
        return None
    return -1.0 / nu_k  # = 1/power, power = -(n'u')/y1


def max_field_value(cs: CompiledSystem) -> float:
    """The largest field's distance from the axis in the system's field units: for angle fields the true field angle
    atan(hypot(tan x, tan y)) (fields.field_size), not the hypotenuse of the degree components."""
    from .fields import field_size, system_field_kind

    kind = system_field_kind(cs.model)
    vals = [field_size(kind, f.x, f.y) for f in cs.model.fields]
    return max(vals) if vals else 0.0


def marginal_ray(cs: CompiledSystem, wl: int, pupil: Pupil) -> ParaxialRay:
    d0 = cs.model.surfaces[0].thickness
    if pupil.telecentric:
        return trace_paraxial(cs, wl, pupil.u_marginal * d0, pupil.u_marginal)
    if d0 is None:
        return trace_paraxial(cs, wl, pupil.r_ep, 0.0)
    u = pupil.r_ep / (pupil.z_ep + d0) if abs(pupil.z_ep + d0) > 1e-15 else 0.0
    return trace_paraxial(cs, wl, u * d0, u)


def chief_ray(cs: CompiledSystem, wl: int, pupil: Pupil, field_value: float) -> ParaxialRay:
    """Paraxial chief ray for a (y) field value in the system's field units (image-height fields are
    converted to the object-space field first, fields.py)."""
    from .fields import object_field

    return chief_ray_object(cs, wl, pupil, object_field(cs, 0.0, field_value)[1])


def chief_ray_object(cs: CompiledSystem, wl: int, pupil: Pupil, field_value: float) -> ParaxialRay:
    """Paraxial chief ray for an object-space field (degrees at infinity or for angle fields, else mm)."""
    from .fields import object_kind

    d0 = cs.model.surfaces[0].thickness
    if pupil.telecentric:
        return trace_paraxial(cs, wl, field_value, 0.0)
    if object_kind(cs) == "angle":
        u = math.tan(math.radians(field_value))
        return trace_paraxial(cs, wl, -u * pupil.z_ep, u)
    h = field_value
    u = -h / (pupil.z_ep + d0)
    return trace_paraxial(cs, wl, h + u * d0, u)


def paraxial_data(cs: CompiledSystem, wl: int | None = None) -> ParaxialData:
    wl = cs.wl_index(wl)
    model = cs.model
    n = cs.n_surfaces
    last = n - 2
    img = n - 1
    # the pupil the rays are launched through: the aperture is defined at the primary wavelength (raytrace.launch);
    # a pupil recomputed at `wl` would resize the stop with the wavelength (EFL(wl) / F#, or n0(wl) for an object NA)
    pupil = compute_pupil(cs, model.primary_wavelength)
    n0 = cs.n_after[wl, 0]
    nk = cs.n_signed[wl, last]
    d0 = model.surfaces[0].thickness

    # system matrix: rays A (y=1, nu=0) and Bn (y=0, nu=1) in reduced coordinates
    A = trace_paraxial(cs, wl, 1.0, 0.0, 1, last)
    Bn = trace_paraxial(cs, wl, 0.0, 1.0 / cs.n_signed[wl, 0], 1, last)
    Am, Cm = A.y[last], A.nu[last]
    Dm = Bn.nu[last]
    power = -Cm
    afocal = abs(Cm) < 1e-15
    if afocal:
        efl = bfl = ffl = fpp = rpp = None
    else:
        efl = 1.0 / power
        # A.y[last] is height at last surface; after refraction slope = A.u[last]
        bfl = -A.y[last] / A.u[last]
        ffl_pos = Dm * cs.n_signed[wl, 0] / Cm  # front focal point relative to surface 1
        ffl = ffl_pos
        fpp = cs.n_signed[wl, 0] * (Dm - 1.0) / Cm
        rpp = nk * (1.0 - Am) / Cm

    m = marginal_ray(cs, wl, pupil)
    hmax = max_field_value(cs)
    c = chief_ray(cs, wl, pupil, hmax)

    t_last = model.surfaces[last].thickness or 0.0
    u_m = m.u[last]
    if abs(u_m) > 1e-15:
        img_dist = -m.y[last] / u_m
        working_fnum = 1.0 / (2.0 * abs(nk) * abs(u_m))
        image_na = abs(nk) * math.sin(math.atan(abs(u_m)))
    else:
        img_dist = None
        working_fnum = None
        image_na = None
    image_fnum = (abs(efl) / (2 * pupil.r_ep)) if efl is not None and not pupil.telecentric else None
    obj_na = None
    mag = None
    if d0 is not None:
        if pupil.telecentric:
            u0 = pupil.u_marginal
        else:
            u0 = pupil.r_ep / (pupil.z_ep + d0) if abs(pupil.z_ep + d0) > 1e-15 else 0.0
        obj_na = abs(n0) * math.sin(math.atan(abs(u0)))
        if abs(m.nu[last]) > 1e-15:
            mag = (cs.n_signed[wl, 0] * u0) / m.nu[last]
    para_img_h = None
    if img_dist is not None:
        para_img_h = float(c.y[last] + img_dist * c.u[last])
    # exit pupil: where the image-space chief ray crosses the axis, relative to image surface
    xp_pos = xp_d = None
    if abs(c.u[last]) > 1e-15 and hmax > 0:
        z_from_last = -c.y[last] / c.u[last]
        xp_pos = z_from_last - t_last
        xp_d = 2.0 * abs(m.y[last] + z_from_last * m.u[last])
    elif hmax == 0:
        # use a small virtual field to locate the exit pupil
        cc = chief_ray_object(cs, wl, pupil, 1e-6)
        if abs(cc.u[last]) > 1e-20:
            z_from_last = -cc.y[last] / cc.u[last]
            xp_pos = z_from_last - t_last
            xp_d = 2.0 * abs(m.y[last] + z_from_last * m.u[last])
    lag = None
    if hmax > 0:
        lag = float(cs.n_signed[wl, 1] * (c.u[1] * m.y[1] - m.u[1] * c.y[1]))
    total_track = float(sum((s.thickness or 0.0) for s in model.surfaces[1:img]))

    return ParaxialData(
        wavelength_um=float(cs.wavelengths[wl]),
        efl=_finite(efl) if efl is not None else None,
        bfl=_finite(bfl) if bfl is not None else None,
        ffl=_finite(ffl) if ffl is not None else None,
        front_principal_plane=fpp,
        rear_principal_plane=rpp,
        power=float(power),
        entrance_pupil_position=pupil.z_ep,
        entrance_pupil_diameter=2.0 * pupil.r_ep,
        exit_pupil_position=xp_pos,
        exit_pupil_diameter=xp_d,
        stop_semi_diameter=pupil.r_stop,
        image_space_fnum=image_fnum,
        working_fnum=working_fnum,
        image_space_na=image_na,
        object_space_na=obj_na,
        paraxial_magnification=mag,
        paraxial_image_distance=img_dist,
        paraxial_image_height=para_img_h,
        image_surface_defocus=(t_last - img_dist) if img_dist is not None else None,
        lagrange_invariant=lag,
        total_track=total_track,
        max_field=hmax,
        approximate=not cs.axial,
    )




def seidel_coefficients(cs: CompiledSystem, wl: int | None = None) -> dict:
    """Third-order Seidel surface contributions and first-order colour.

    Standard formulation (W. T. Welford, *Aberrations of Optical Systems*,
    ch. 8) with refraction invariants A = n(y c + u), A_bar = n(y_bar c + u_bar):

        S_I   = -A^2 y d(u/n)          S_II  = -A A_bar y d(u/n)
        S_III = -A_bar^2 y d(u/n)      S_IV  = -H^2 c d(1/n)
        S_V   = (A_bar/A)(S_III + S_IV)
        C_L   = A y d(dn/n)            C_T   = A_bar y d(dn/n)

    with dn = n_F - n_C. Conic and A4 terms add d S_I = (k c^3 + 8 A4) dn' y^4
    (scaled by y_bar/y powers for S_II, S_III, S_V). Valid only for axial,
    rotationally symmetric systems; wavefront coefficient W040 = S_I / 8.
    """
    from .materials import LAMBDA_C, LAMBDA_F

    wl = cs.wl_index(wl)
    last = cs.n_surfaces - 2
    pupil = compute_pupil(cs, cs.model.primary_wavelength)  # the launched pupil (paraxial_data)
    m = marginal_ray(cs, wl, pupil)
    hmax = max_field_value(cs)
    c = chief_ray(cs, wl, pupil, hmax)
    ns = cs.n_signed[wl]
    H = float(ns[0] * (c.u[0] * m.y[1] - m.u[0] * c.y[1])) if hmax > 0 else 0.0

    def delta_n(i: int) -> float:
        name = _medium_name(cs, i)
        if name in ("AIR", "VACUUM", ""):
            return 0.0
        mat = cs.library.get(name)
        sgn = 1.0 if ns[i] > 0 else -1.0
        return sgn * (mat.index(LAMBDA_F) - mat.index(LAMBDA_C))

    rows = []
    keys = ("SI", "SII", "SIII", "SIV", "SV", "CL", "CT")
    tot = {k: 0.0 for k in keys}
    for j in range(1, last + 1):
        if cs.is_cb[j]:
            continue
        if cs.ideal and cs.ideal[j] is not None:
            # an ideal lens is free of aberrations (tangent mapping: no Seidel or colour contribution)
            row = {"surface": j, **{k: 0.0 for k in keys}, "ideal": True}
            rows.append(row)
            continue
        sh = cs.shapes[j]
        cv = sh.curvature
        n1, n2 = ns[j - 1], ns[j]
        y, yb = m.y[j], c.y[j]
        u_in, ub_in = m.nu[j - 1] / n1, c.nu[j - 1] / n1
        u_out = m.u[j]
        A = n1 * (y * cv + u_in)
        Ab = n1 * (yb * cv + ub_in)
        d_u_n = u_out / n2 - u_in / n1
        SI = -A * A * y * d_u_n
        SII = -A * Ab * y * d_u_n
        SIII = -Ab * Ab * y * d_u_n
        SIV = -H * H * cv * (1.0 / n2 - 1.0 / n1)
        SV = (Ab / A) * (SIII + SIV) if abs(A) > 1e-15 else 0.0
        b4 = getattr(sh, "seidel_b4", None)
        if b4 is None:
            b4 = sh.conic * cv**3 + (8.0 * sh.aspheric[0] if sh.aspheric else 0.0)
        if b4 != 0.0 and abs(y) > 1e-15:
            dS = b4 * (n2 - n1) * y**4
            r = yb / y
            SI += dS
            SII += dS * r
            SIII += dS * r * r
            SV += dS * r**3
        d_dn_n = delta_n(j) / n2 - delta_n(j - 1) / n1
        CL = A * y * d_dn_n
        CT = Ab * y * d_dn_n
        row = {"surface": j, "SI": SI, "SII": SII, "SIII": SIII, "SIV": SIV, "SV": SV, "CL": CL, "CT": CT}
        rows.append(row)
        for k in keys:
            tot[k] += row[k]
    nk = ns[last]
    uk = m.u[last]
    return {
        "surfaces": rows,
        "total": tot,
        "lagrange_invariant": H,
        "wavelength_um": float(cs.wavelengths[wl]),
        "image_marginal_nu": float(nk * uk),
        "approximate": not cs.axial,
    }


def _medium_name(cs: CompiledSystem, i: int) -> str:
    """Name of the physical medium after surface i (mirrors/CBs keep the medium)."""
    surfs = cs.model.surfaces
    name = surfs[0].material
    for k in range(0, i + 1):
        s = surfs[k]
        if k == 0 or not (s.is_mirror or s.type == "coordinate_break"):
            name = s.material
    return name
