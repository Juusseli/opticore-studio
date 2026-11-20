"""Key numbers of a design and before/after comparisons (optimisation results, the optimisation wizard).

The merit function only sees what its operands ask for; everything else may change while the merit
improves (distortion, lateral colour, the field of view of image-height fields, the corner illumination,
the chief-ray angle on the sensor, the length). design_summary collects those numbers from the normal
analyses, and compare_designs puts two designs side by side and flags what got worse:

    rms_spot_um            polychromatic centroid RMS spot radius per field (spot.py, hexapolar 6)
    mtf                    polychromatic diffraction MTF per field, tangential and sagittal (diffraction.py),
                           at the sensor's half-Nyquist frequency, else at a quarter of the incoherent cutoff
                           1 / (lambda F#w) of the longest wavelength (rounded); both designs at the same one
    efl_mm, total_track_mm, working_fnum   paraxial (primary wavelength)
    field                  object-space field of the largest field: the true field angle in degrees (angle fields,
                           also with a finite object; fields.field_size) or the object height in mm; for
                           image-height fields it moves with distortion and focal length (field of view)
    image_height_mm        real chief-ray height of the largest field (primary wavelength)
    distortion_pct         at the largest field (aberrations.field_curvature_distortion)
    lateral_colour_um      chief-ray landing of the shortest minus the longest wavelength at the largest
                           field, along the field direction
    axial_colour_um        paraxial image distance of the longest minus the shortest wavelength
    relative_illumination  at the largest field (imaging.relative_illumination, with transmission)
    cra_deg                angle of the primary chief ray to the image-surface normal where it lands (the local
                           normal of a curved image surface), at the largest field
    min_glass_edge_mm, min_air_edge_mm   thinnest edges (evaluate.edge_thickness at the larger semi-diameter;
                           plane-parallel plates are left out: their edge is their centre thickness)
    field_profile          the RMS spot between the fields (field_profile): an optimiser only sees the fields it is
                           given, and the image can fall apart between them

A number that does not apply (no off-axis field, an afocal system) or cannot be computed is None, with
the reason in `missing`.

Regression rules (compare_designs, `flags`; kind 'worse' or 'changed'):
    RMS spot of a field  worse if it grows by > 10 % and by > 0.1 Airy radius
    MTF of a field       worse if the mean of T and S drops by > 0.05
    distortion           worse if |D| grows by > 0.5 percentage points
    lateral colour       worse if |LC| grows by > 20 % and by > 0.25 Airy radius
    axial colour         worse if |AC| grows by > 20 % and by > 2 lambda F#w^2 (the quarter-wave
                         depth of focus, longest wavelength)
    relative illum.      worse if it drops by > 0.03
    chief-ray angle      worse if it grows by > 1 degree
    total track          worse if it grows by > 1 %
    thinnest edges       worse if they shrink by > 20 %
    field (FOV)          changed if it moves by > 1 % (image-height fields: the field of view changed)
    EFL                  changed if it moves by > 0.5 %
    sampling gap         worse if the design after has a gap between its fields that the design before did not have
                         (or a gap that grew by > 10 %)

Field profile (field_profile): the polychromatic centroid RMS spot (spot.py, hexapolar 6) at PROFILE_POINTS field
points from the axis to the largest field, along its direction. Vignetting factors are interpolated linearly from
the defined fields by their radial fraction. A sampling gap is a profile point away from every defined field (more
than 0.05 of the field) whose RMS spot exceeds the largest RMS spot of the defined fields by more than GAP_RATIO
and by more than 0.25 Airy radius, or whose rays fail where the defined fields trace.
"""

from __future__ import annotations

import math

import numpy as np

from ..model import OpticalSystem
from ..paraxial import compute_pupil, paraxial_data
from ..raytrace import trace_pupil
from ..system import CompiledSystem, SystemError_, compile_system

FAILED = (SystemError_, ValueError, ArithmeticError, ZeroDivisionError)
PROFILE_POINTS = 11
GAP_RATIO = 1.25
GLASSLESS = ("AIR", "VACUUM", "MIRROR")


def _nice(x: float) -> float:
    """x rounded to two significant digits."""
    if not (x > 0 and math.isfinite(x)):
        return x
    e = math.floor(math.log10(x)) - 1
    return float(round(x / 10**e) * 10**e)


def reference_frequency(cs: CompiledSystem) -> float:
    """MTF frequency of the comparison (module notes), cycles/mm."""
    from .diffraction import _working_fnum
    from .imaging import nyquist

    if cs.model.sensor is not None:
        return _nice(0.5 * nyquist(cs.model.sensor))
    w = int(np.argmax(cs.wavelengths))
    return _nice(0.25 / (float(cs.wavelengths[w]) * 1e-3 * _working_fnum(cs, w)))


def _field_size(system: OpticalSystem, f) -> float:
    """Distance of a field from the axis in the system's field units (fields.field_size: the true angle of an angle
    field, not hypot of its degree components)."""
    from ..fields import field_size, system_field_kind

    return field_size(system_field_kind(system), f.x, f.y)


def largest_field(system: OpticalSystem) -> int | None:
    """Index of the field farthest from the axis, or None if every field is on axis."""
    r = [_field_size(system, f) for f in system.fields]
    k = int(np.argmax(r))
    return k if r[k] > 0 else None


_max_field = largest_field


def _chief(cs: CompiledSystem, pupil, w: int, field: int):
    r = trace_pupil(cs, w, field, np.array([0.0]), np.array([0.0]), pupil, obscure=False, clip=False)
    if not r.ok[0]:
        raise SystemError_(f"The chief ray of field {field + 1} fails")
    return r


def lateral_colour_mm(cs: CompiledSystem, pupil, field: int) -> float:
    """Lateral colour of a field (mm): the chief-ray landing of the shortest minus the longest wavelength, along the
    field's direction on the image surface. Shared by the summary and the max_lateral_color operand."""
    from ..fields import field_direction, system_field_kind

    wl = cs.wavelengths
    ws, wlong = int(np.argmin(wl)), int(np.argmax(wl))
    if ws == wlong:
        raise ValueError("Lateral colour needs two or more wavelengths")
    fd = cs.model.fields[field]
    u = field_direction(system_field_kind(cs.model), fd.x, fd.y)  # the azimuth of (tan x, tan y) for angle fields
    if u is None:
        raise ValueError("Lateral colour needs an off-axis field")
    d = _chief(cs, pupil, ws, field).image_xy()[0] - _chief(cs, pupil, wlong, field).image_xy()[0]
    return float(d @ np.array(u))


def chief_ray_angle_deg(cs: CompiledSystem, pupil, field: int) -> float:
    """Angle (degrees) of the primary chief ray of a field to the image-surface normal where it lands: the local normal
    of a curved (or tilted) image surface, which is the sensor's acceptance direction there. Shared by the summary and
    the max_cra operand. (Not the angle to the surface's axis, which on a curved image surface differs by the surface
    slope at the landing point.)"""
    r = _chief(cs, pupil, cs.model.primary_wavelength, field)
    j = cs.n_surfaces - 1
    d = cs.frames[j].to_local_dirs(r.dirs)[0]
    n = cs.shapes[j].normals(r.local[:, j, :])[0]
    c = abs(float(d @ n)) / (float(np.linalg.norm(d)) * float(np.linalg.norm(n)))
    return math.degrees(math.acos(min(1.0, c)))


def relative_illumination_at(cs: CompiledSystem, field: int) -> float:
    """Relative illumination (imaging.relative_illumination, with transmission) at a field's object-space value, traced
    along that field's own azimuth (a field along x is traced along x). Shared by the summary and the
    min_relative_illumination operand."""
    from ..fields import field_direction, field_size, object_field, object_kind
    from .imaging import _object_measure, relative_illumination

    _, umax = _object_measure(cs)
    kind = object_kind(cs)
    fd = cs.model.fields[field]
    obj = object_field(cs, fd.x, fd.y)
    u = field_size(kind, *obj)  # the true field angle, not hypot of the degree components
    if not (umax > 0 and u > 0):
        raise ValueError("Relative illumination needs an off-axis field")
    return float(relative_illumination(cs, points=2, rings=6, extent=u / umax, direction=field_direction(kind, *obj))["relative_illumination"][-1])


def design_summary(system: OpticalSystem, custom_materials=(), mtf_frequency: float | None = None) -> dict:
    """Key numbers of one design (module notes)."""
    from ..fields import field_size, object_field, object_kind
    from .aberrations import chromatic_focal_shift, field_curvature_distortion
    from .diffraction import mtf
    from .evaluate import auto_semi_diameters, edge_thickness, effective_semi_diameters
    from .spot import spot_diagram

    custom = list(custom_materials)
    cs = compile_system(system, custom)
    pupil = compute_pupil(cs)
    prim = system.primary_wavelength
    out: dict = {}
    missing: dict = {}

    def attempt(name: str, fn):
        try:
            out[name] = fn()
        except FAILED as exc:
            out[name] = None
            missing[name] = str(exc)

    def paraxial():
        pd = paraxial_data(cs, prim)
        out["efl_mm"] = pd.efl
        out["working_fnum"] = pd.working_fnum
        return pd.total_track

    attempt("total_track_mm", paraxial)
    out.setdefault("efl_mm", None)
    out.setdefault("working_fnum", None)

    def spots():
        sp = spot_diagram(cs)
        out["airy_radius_um"] = sp["airy_radius_um"]
        return [f["rms_radius_um"] for f in sp["fields"]]

    attempt("rms_spot_um", spots)
    out.setdefault("airy_radius_um", None)
    try:
        freq = float(mtf_frequency) if mtf_frequency else reference_frequency(cs)
    except FAILED as exc:
        freq = None
        missing["mtf"] = str(exc)
    out["mtf_frequency"] = freq
    if freq:

        def mtfs():
            m = mtf(cs, max_frequency=freq, samples=2, grid=64, pad=4)
            return [[float(fr["tangential"][-1]), float(fr["sagittal"][-1])] for fr in m["fields"]]

        attempt("mtf", mtfs)
    else:
        out["mtf"] = None
    wl = cs.wavelengths
    w_short, w_long = int(np.argmin(wl)), int(np.argmax(wl))

    def axial():
        if w_short == w_long:
            raise ValueError("one wavelength")
        r = chromatic_focal_shift(cs, float(wl[w_short]), float(wl[w_long]), samples=2)
        return float(r["focal_shift_um"][-1] - r["focal_shift_um"][0])

    attempt("axial_colour_um", axial)
    fmax = _max_field(cs.model)
    off = ["field", "image_height_mm", "distortion_pct", "lateral_colour_um", "relative_illumination", "cra_deg"]
    if fmax is None:
        for k in off:
            out[k] = None
            missing[k] = "no off-axis field"
    else:
        fd = cs.model.fields[fmax]

        def field_value():
            # the true field angle (or object height): not hypot of the degree components of a diagonal angle field
            return float(field_size(object_kind(cs), *object_field(cs, fd.x, fd.y)))

        attempt("field", field_value)
        attempt("image_height_mm", lambda: float(np.linalg.norm(_chief(cs, pupil, prim, fmax).image_xy()[0])))

        def distortion():
            v = field_curvature_distortion(cs, samples=2, wavelengths=[prim])["per_wavelength"][0]["distortion_percent"][-1]
            if v is None:
                raise ValueError("distortion undefined")
            return float(v)

        attempt("distortion_pct", distortion)

        attempt("lateral_colour_um", lambda: lateral_colour_mm(cs, pupil, fmax) * 1e3)
        attempt("relative_illumination", lambda: relative_illumination_at(cs, fmax))
        attempt("cra_deg", lambda: chief_ray_angle_deg(cs, pupil, fmax))

    def edges():
        sd = effective_semi_diameters(cs, auto_semi_diameters(cs, pupil))
        glass, air = [], []
        n = cs.n_surfaces
        for i in range(1, n - 2):
            s = system.surfaces[i]
            if cs.is_cb[i] or cs.is_cb[i + 1] or s.type == "ideal" or system.surfaces[i + 1].type == "ideal":
                continue
            s2 = system.surfaces[i + 1]
            if s.material.upper() not in GLASSLESS and all(x.type == "standard" and x.radius is None for x in (s, s2)):
                continue  # a plane-parallel plate (filter, window): its edge is its centre thickness
            e = edge_thickness(cs, i, max(sd[i], sd[i + 1]))
            (air if s.material.upper() in GLASSLESS else glass).append((e, s.id))
        out["min_air_edge_mm"] = min(air)[0] if air else None
        out["min_air_edge_surface"] = min(air)[1] if air else None
        out["min_glass_edge_surface"] = min(glass)[1] if glass else None
        return min(glass)[0] if glass else None

    attempt("min_glass_edge_mm", edges)
    attempt("field_profile", lambda: field_profile(system, custom, out.get("rms_spot_um"), out.get("airy_radius_um")))
    for k in ("min_air_edge_mm", "min_air_edge_surface", "min_glass_edge_surface"):
        out.setdefault(k, None)
    out["max_field_index"] = fmax
    # the unit of `field` (an object-space field): angles also with a finite object; the compiled system is the active
    # configuration (whose object distance may differ from the base prescription's)
    out["field_unit"] = "deg" if object_kind(cs) == "angle" else "mm"
    out["missing"] = missing
    return out


def field_profile(system: OpticalSystem, custom_materials=(), sampled_um: list[float] | None = None, airy_um: float | None = None) -> dict | None:
    """RMS spot (um) from the axis to the largest field, and the sampling gap if there is one (module notes). None
    without an off-axis field."""
    from ..fields import field_along, field_direction, system_field_kind
    from .spot import spot_diagram

    fmax = largest_field(system)
    if fmax is None:
        return None
    fd = system.fields[fmax]
    kind = system_field_kind(system)
    r_max = _field_size(system, fd)
    ux, uy = field_direction(kind, fd.x, fd.y)
    fracs = np.linspace(0.0, 1.0, PROFILE_POINTS)
    defined = sorted({round(_field_size(system, f) / r_max, 12) for f in system.fields})
    order = sorted(system.fields, key=lambda f: _field_size(system, f))
    rr = [_field_size(system, f) / r_max for f in order]
    d = system.model_dump()
    # profile points along the largest field's azimuth at fractions of its size (field_along: angle fields keep the
    # azimuth of (tan x, tan y), a diagonal angle field is not scaled component by component)
    d["fields"] = [
        dict(zip(("x", "y"), field_along(kind, float(t) * r_max, ux, uy)), weight=1.0, **{k: float(np.interp(t, rr, [getattr(f, k) for f in order])) for k in ("vdx", "vdy", "vcx", "vcy")})
        for t in fracs
    ]
    cs = compile_system(OpticalSystem.model_validate(d), list(custom_materials))
    sp = spot_diagram(cs)
    rms = [None if f.get("rms_radius_um") is None or not math.isfinite(f["rms_radius_um"]) else float(f["rms_radius_um"]) for f in sp["fields"]]
    if sampled_um is None:
        sampled_um = [x for x in (spot_diagram(compile_system(system, list(custom_materials)))["fields"]) for x in [x["rms_radius_um"]]]
    airy = airy_um if airy_um is not None else sp.get("airy_radius_um") or 0.0
    gap = sampling_gap([float(t) for t in fracs], rms, defined, sampled_um, airy)
    return {"fractions": [float(t) for t in fracs], "rms_um": rms, "defined": [float(r) for r in defined], "gap": gap}


def sampling_gap(fracs: list[float], rms: list[float | None], defined: list[float], sampled_um: list[float | None], airy_um: float) -> dict | None:
    """The worst profile point between the defined fields that is a sampling gap (module notes), or None."""
    ok = [x for x in sampled_um if x is not None and math.isfinite(x)]
    if not ok:
        return None
    s_max = max(ok)
    gap = None
    for t, v in zip(fracs, rms):
        if min(abs(t - r) for r in defined) <= 0.05:
            continue
        if v is None:  # rays fail between fields that trace
            return {"fraction": t, "rms_um": None, "sampled_max_um": s_max, "ratio": None}
        if v > GAP_RATIO * s_max and v - s_max > 0.25 * airy_um and (gap is None or v / s_max > gap["ratio"]):
            gap = {"fraction": t, "rms_um": v, "sampled_max_um": s_max, "ratio": v / s_max}
    return gap


def _grew(a, b, rel: float, absolute: float) -> bool:
    return a is not None and b is not None and abs(b) > abs(a) * (1 + rel) and abs(b) - abs(a) > absolute


def compare_designs(before: OpticalSystem, after: OpticalSystem, custom_materials=()) -> dict:
    """Both designs' summaries at the same MTF frequency and the flags of the regression rules (module notes)."""
    b = design_summary(before, custom_materials)
    a = design_summary(after, custom_materials, b["mtf_frequency"])
    flags: list[dict] = []

    def flag(key: str, kind: str = "worse", field: int | None = None, x0=None, x1=None):
        flags.append({"key": key, "kind": kind, "field": field, "before": x0, "after": x1})

    airy = b["airy_radius_um"] or a["airy_radius_um"] or 0.0
    for k, (x0, x1) in enumerate(zip(b["rms_spot_um"] or [], a["rms_spot_um"] or [])):
        if x1 > x0 * 1.10 and x1 - x0 > 0.1 * airy:
            flag("rms_spot_um", field=k, x0=x0, x1=x1)
    for k, (m0, m1) in enumerate(zip(b["mtf"] or [], a["mtf"] or [])):
        if sum(m1) / 2 < sum(m0) / 2 - 0.05:
            flag("mtf", field=k, x0=sum(m0) / 2, x1=sum(m1) / 2)
    d0, d1 = b["distortion_pct"], a["distortion_pct"]
    if d0 is not None and d1 is not None and abs(d1) > abs(d0) + 0.5:
        flag("distortion_pct", x0=d0, x1=d1)
    if _grew(b["lateral_colour_um"], a["lateral_colour_um"], 0.2, 0.25 * airy):
        flag("lateral_colour_um", x0=b["lateral_colour_um"], x1=a["lateral_colour_um"])
    if b["working_fnum"]:
        lam_um = float(max(w.value for w in before.wavelengths))
        if _grew(b["axial_colour_um"], a["axial_colour_um"], 0.2, 2.0 * lam_um * b["working_fnum"] ** 2):
            flag("axial_colour_um", x0=b["axial_colour_um"], x1=a["axial_colour_um"])
    r0, r1 = b["relative_illumination"], a["relative_illumination"]
    if r0 is not None and r1 is not None and r1 < r0 - 0.03:
        flag("relative_illumination", x0=r0, x1=r1)
    c0, c1 = b["cra_deg"], a["cra_deg"]
    if c0 is not None and c1 is not None and c1 > c0 + 1.0:
        flag("cra_deg", x0=c0, x1=c1)
    t0, t1 = b["total_track_mm"], a["total_track_mm"]
    if t0 is not None and t1 is not None and abs(t1) > abs(t0) * 1.01:
        flag("total_track_mm", x0=t0, x1=t1)
    for key in ("min_glass_edge_mm", "min_air_edge_mm"):
        e0, e1 = b[key], a[key]
        if e0 is not None and e1 is not None and e0 > 0 and e1 < 0.8 * e0:
            flag(key, x0=e0, x1=e1)
    f0, f1 = b["field"], a["field"]
    if f0 and f1 is not None and abs(f1 - f0) > 0.01 * abs(f0):
        flag("field", "changed", x0=f0, x1=f1)
    e0, e1 = b["efl_mm"], a["efl_mm"]
    if e0 and e1 is not None and math.isfinite(e0) and math.isfinite(e1) and abs(e1 - e0) > 0.005 * abs(e0):
        flag("efl_mm", "changed", x0=e0, x1=e1)
    g0 = (b.get("field_profile") or {}).get("gap")
    g1 = (a.get("field_profile") or {}).get("gap")
    if g1 is not None:
        r0 = g0["ratio"] if g0 is not None and g0["ratio"] is not None else None
        r1 = g1["ratio"]
        if g0 is None or (r1 is None and r0 is not None) or (r1 is not None and r0 is not None and r1 > 1.1 * r0):
            flag("field_gap", x0=g0["rms_um"] if g0 else None, x1=g1["rms_um"])
    return {
        "before": b,
        "after": a,
        "flags": flags,
        "method": "Normal analyses of both designs (analysis/summary.py); regression thresholds in the module notes",
    }
