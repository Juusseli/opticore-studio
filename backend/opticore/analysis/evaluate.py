"""System evaluation: auto semi-diameters, validation, layout geometry, rays."""

from __future__ import annotations

import warnings

import numpy as np

from ..paraxial import Pupil, compute_pupil, paraxial_data
from ..qpoly import monomial_coefficients
from ..raytrace import status_summary, trace_fields, trace_pupil, vignetted_pupil
from ..surfaces import OK, STATUS_TEXT
from ..system import CompiledSystem, Diagnostic
from ..solves import solved_values

EDGE_SAMPLES = 16


def auto_semi_diameters(cs: CompiledSystem, pupil: Pupil, aim_cache: dict | None = None) -> np.ndarray:
    """Semi-diameter needed to pass the full pupil for every field and wavelength.

    Uses the chief ray plus EDGE_SAMPLES rays on the pupil rim (unclipped).
    The object surface gets the object height (or 0 at infinity)."""
    n = cs.n_surfaces
    a = 2 * np.pi * np.arange(EDGE_SAMPLES) / EDGE_SAMPLES
    px = np.concatenate([[0.0], np.cos(a)])
    py = np.concatenate([[0.0], np.sin(a)])
    sd = np.zeros(n)
    for w in range(len(cs.wavelengths)):
        for r in trace_fields(cs, w, range(len(cs.model.fields)), px, py, pupil, clip=False, aim_cache=aim_cache, vignetting=True):
            rr = np.hypot(r.local[:, :, 0], r.local[:, :, 1])
            with np.errstate(invalid="ignore"), warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)  # surfaces no ray reaches: NaN, set to 0 below
                mx = np.nanmax(np.where(np.isfinite(rr), rr, np.nan), axis=0) if rr.size else np.zeros(n)
            mx = np.where(np.isfinite(mx), mx, 0.0)
            sd = np.maximum(sd, mx)
    if cs.model.object_at_infinity:
        sd[0] = 0.0
    return sd


def effective_semi_diameters(cs: CompiledSystem, auto_sd: np.ndarray) -> np.ndarray:
    out = auto_sd.copy()
    for i, s in enumerate(cs.model.surfaces):
        if s.semi_diameter_mode == "fixed":
            out[i] = s.semi_diameter
    return out


def validate_geometry(cs: CompiledSystem, sd: np.ndarray) -> list[Diagnostic]:
    """Manufacturability / physical-consistency checks."""
    diags: list[Diagnostic] = []
    surfs = cs.model.surfaces
    n = len(surfs)
    for i in range(1, n - 1):
        s = surfs[i]
        if cs.is_cb[i]:
            continue
        sh = cs.shapes[i]
        if hasattr(sh, "poly") and sd[i] > sh.norm_radius * (1 + 1e-9) and np.any(sh.poly):
            what = "XY-polynomial" if cs.model.surfaces[i].type == "xy_polynomial" else "Zernike"
            diags.append(Diagnostic("warning", "ZERNIKE_EXTRAPOLATED", f"Semi-diameter {sd[i]:.4g} mm exceeds the {what} normalisation radius {sh.norm_radius:.4g} mm: the polynomial is extrapolated", i))
        if getattr(sh, "kind", None) in ("qcon", "qbfs") and sd[i] > sh.norm_radius * (1 + 1e-9) and any(sh.coefficients):
            diags.append(Diagnostic("warning", "Q_EXTRAPOLATED", f"Semi-diameter {sd[i]:.4g} mm exceeds the Q-polynomial normalisation radius {sh.norm_radius:.4g} mm: the polynomials are used outside the unit aperture", i))
        if not sh.is_plane and sd[i] > 0:
            if not bool(sh.domain_ok(np.array([sd[i] ** 2]))[0]):
                diags.append(
                    Diagnostic("error", "SD_EXCEEDS_SURFACE", f"Semi-diameter {sd[i]:.4g} mm exceeds the surface definition domain", i)
                )
        # glass element thickness checks
        medium_glass = cs.n_after[0, i] != 1.0 and not cs.is_mirror[i]
        if medium_glass and i + 1 < n - 1 and not cs.is_cb[i + 1]:
            # thickness is signed along local z; after an odd number of mirrors light
            # travels towards -z, so judge it along the propagation direction
            prop = 1.0 if cs.n_signed[0, i] > 0 else -1.0
            t = (s.thickness or 0.0) * prop
            if t <= 0:
                diags.append(Diagnostic("error", "NONPOSITIVE_GLASS_THICKNESS", f"Glass thickness {t:g} mm must be positive", i))
            h = max(sd[i], sd[i + 1])
            try:
                e = edge_thickness(cs, i, h)
                if np.isfinite(e) and e < 0:
                    diags.append(
                        Diagnostic(
                            "warning",
                            "NEGATIVE_EDGE_THICKNESS",
                            f"Edge thickness {e:.3f} mm at h = {h:.3f} mm is negative (element not manufacturable)",
                            i,
                        )
                    )
            except Exception:
                pass
        if s.semi_diameter_mode == "fixed" and s.semi_diameter == 0:
            diags.append(Diagnostic("warning", "ZERO_APERTURE", "Fixed semi-diameter is zero: all rays will be clipped", i))
    return diags


def edge_thickness(cs: CompiledSystem, i: int, h: float) -> float:
    """Edge thickness at height h, measured along the propagation direction."""
    prop = 1.0 if cs.n_signed[0, i] > 0 else -1.0
    t = cs.model.surfaces[i].thickness or 0.0
    a, b = cs.shapes[i], cs.shapes[i + 1]
    if hasattr(a, "poly") or hasattr(b, "poly"):
        # Zernike surfaces: thinnest edge around the whole rim
        ph = np.linspace(0.0, 2 * np.pi, 145)[:-1]
        x, y = h * np.cos(ph), h * np.sin(ph)
        return float(np.min(prop * (t + b.sag_xy(x, y) - a.sag_xy(x, y))))
    # both meridians (they differ only for biconic surfaces); the thinner edge counts
    ey = prop * (t + float(b.sag(h * h)) - float(a.sag(h * h)))
    ex = prop * (t + float(b.sag_x(h * h)) - float(a.sag_x(h * h)))
    return min(ey, ex)


def surface_profiles(cs: CompiledSystem, sd: np.ndarray, samples: int = 41) -> list[dict]:
    """Meridional (y-z) profile of each surface in local coordinates plus its frame."""
    out = []
    for i, s in enumerate(cs.model.surfaces):
        fr = cs.frames[i]
        h = float(sd[i])
        if cs.is_cb[i]:
            prof = []
        else:
            ys = np.linspace(-h, h, samples) if h > 0 else np.array([0.0])
            r2 = ys * ys
            ok = cs.shapes[i].domain_ok(r2)
            zs = cs.shapes[i].sag(np.where(ok, r2, np.nan))
            prof = [[float(y), float(z)] for y, z, k in zip(ys, zs, ok) if k and np.isfinite(z)]
        out.append(
            {
                "index": i,
                "id": s.id,
                "type": s.type,
                "semi_diameter": h,
                "origin": fr.origin.tolist(),
                "matrix": fr.matrix.tolist(),
                "profile": prof,  # [[y_local, z_local], ...]
                "curvature": cs.shapes[i].curvature,
                "conic": cs.shapes[i].conic,
                "curvature_x": float(getattr(cs.shapes[i], "curvature_x", cs.shapes[i].curvature)),
                "conic_x": float(getattr(cs.shapes[i], "conic_x", cs.shapes[i].conic)),
                "aspheric": list(cs.shapes[i].aspheric),
                # Zernike surfaces: base surface and the exact monomial polynomial (normalised coordinates), for drawing
                "zernike": (
                    {
                        "base_curvature": cs.shapes[i].base_curvature,
                        "norm_radius": cs.shapes[i].norm_radius,
                        "poly": cs.shapes[i].poly.tolist(),
                    }
                    if hasattr(cs.shapes[i], "poly")
                    else None
                ),
                # Q-type aspheres: base and the departure series S(x) as a power series in x = (r / r_n)^2, for drawing
                "qpoly": (
                    {
                        "kind": cs.shapes[i].kind,
                        "base_curvature": cs.shapes[i].base_curvature,
                        "conic": cs.shapes[i].base.conic,
                        "norm_radius": cs.shapes[i].norm_radius,
                        "series": monomial_coefficients(cs.shapes[i].kind, cs.shapes[i].coefficients),
                    }
                    if getattr(cs.shapes[i], "kind", None) in ("qcon", "qbfs")
                    else None
                ),
                # odd aspheres: base conic and the coefficients beta_1.. on r^1.. (for drawing)
                "odd": (
                    {"base_curvature": cs.shapes[i].base_curvature, "conic": cs.shapes[i].conic, "coefficients": list(cs.shapes[i].coefficients)}
                    if getattr(cs.shapes[i], "kind", None) == "odd"
                    else None
                ),
                "is_mirror": bool(cs.is_mirror[i]),
                "is_stop": i == cs.stop,
                "is_ideal": bool(cs.ideal and cs.ideal[i] is not None),
                "focal_length": (cs.ideal[i].focal_length if cs.ideal and cs.ideal[i] is not None else None),
            }
        )
    return out


def lens_elements(cs: CompiledSystem) -> list[dict]:
    """Groups of consecutive surfaces bounding glass (for drawing solids)."""
    els = []
    surfs = cs.model.surfaces
    n = len(surfs)
    for i in range(1, n - 2):
        if cs.is_cb[i] or cs.is_mirror[i]:
            continue
        mat = surfs[i].material
        if mat in ("AIR", "VACUUM"):
            continue
        j = i + 1
        if cs.is_cb[j]:
            continue
        els.append({"front": i, "back": j, "material": mat})
    return els


def layout_rays(cs: CompiledSystem, pupil: Pupil, n_rays: int = 7, mode: str = "meridional") -> list[dict]:
    """Ray paths for the layout views (all fields, all wavelengths)."""
    if mode == "meridional":
        py = np.linspace(-1.0, 1.0, max(n_rays, 1)) if n_rays > 1 else np.array([0.0])
        px = np.zeros_like(py)
    else:  # ring for 3D
        a = 2 * np.pi * np.arange(n_rays) / n_rays
        px = np.concatenate([[0.0], np.cos(a)])
        py = np.concatenate([[0.0], np.sin(a)])
    rays = []
    for f in range(len(cs.model.fields)):
        for w in range(len(cs.wavelengths)):
            r = trace_pupil(cs, w, f, px, py, pupil, clip=True, vignetting=True)
            for k in range(len(px)):
                pts = r.points[k]
                valid = np.all(np.isfinite(pts), axis=1)
                poly = pts[valid].tolist()
                # include the start point for infinite objects so the ray enters the drawing
                rays.append(
                    {
                        "field": f,
                        "wavelength": w,
                        "px": float(px[k]),
                        "py": float(py[k]),
                        "status": STATUS_TEXT[int(r.status[k])],
                        "fail_surface": int(r.fail_surface[k]),
                        "points": poly,
                        "start": r.start_points[k].tolist(),
                        "start_dir": r.start_dirs[k].tolist(),
                    }
                )
    return rays


def telecentric_check(cs: CompiledSystem, pupil) -> list[Diagnostic]:
    """Object-space telecentric mode: the chief rays leave parallel to the axis. They cross the stop centre
    only when the stop sits in the rear focal plane of the optics in front of it."""
    from ..paraxial import chief_ray, max_field_value

    hmax = max_field_value(cs)
    if hmax <= 0:
        return []
    c = chief_ray(cs, cs.model.primary_wavelength, pupil, hmax)
    off = abs(float(c.y[cs.stop]))
    if off > 0.02 * max(pupil.r_stop, 1e-12):
        return [
            Diagnostic(
                "warning",
                "TELECENTRIC_STOP",
                f"Object-space telecentric mode, but the stop is not in the rear focal plane of the optics before it: the edge-field chief ray misses the stop centre by {off:.4g} mm ({100 * off / pupil.r_stop:.1f} % of the stop radius), so the beam is vignetted asymmetrically by the stop",
                cs.stop,
            )
        ]
    return [Diagnostic("info", "TELECENTRIC", "Object-space telecentric: chief rays leave the object parallel to the axis and cross the stop centre", cs.stop)]


AIM_WARN = 0.05  # aiming error (fraction of the stop radius) above which pupil-dependent results are noticeably off
AIM_INFO = 0.01
_AIM_RAYS = ("chief", "marginal +y", "marginal -y", "marginal +x", "marginal -x")


def aiming_check(cs: CompiledSystem, pupil) -> list[Diagnostic]:
    """Paraxial ray aiming launches the rays through the paraxial entrance pupil. Where the pupil is aberrated they
    miss the stop points they stand for ((px, py) * r_stop): the chief ray the centre, the marginal rays the rim.
    The largest miss over the fields (primary wavelength), as a fraction of the stop radius, decides: above
    AIM_WARN a warning, above AIM_INFO a note. (Measured on the samples: a 5-9 % miss changed edge RMS spots,
    relative illumination or distortion by 6-26 %, a 1.8 % miss by 0.3 %.)"""
    from ..raytrace import launch, trace

    if cs.model.ray_aiming == "real" or cs.stop is None or cs.model.object_space_telecentric or not (pupil.r_stop > 0):
        return []
    wl = cs.model.primary_wavelength
    px = np.array([0.0, 0.0, 0.0, 1.0, -1.0])
    py = np.array([0.0, 1.0, -1.0, 0.0, 0.0])
    worst = (0.0, 0, 0)
    for f in range(len(cs.model.fields)):
        try:
            P, D, opl = launch(cs, wl, f, px, py, pupil, aiming="paraxial")
            r = trace(cs, wl, P, D, opl, end=cs.stop, clip=False)
        except Exception:  # noqa: BLE001 - a field that cannot be launched is reported by the ray checks
            continue
        q = r.local[:, cs.stop, :2]
        miss = np.hypot(q[:, 0] - px * pupil.r_stop, q[:, 1] - py * pupil.r_stop) / pupil.r_stop
        miss = np.where(np.all(np.isfinite(q), axis=1) & r.ok, miss, 0.0)  # failed rays: RAY_FAILED
        k = int(np.argmax(miss))
        if miss[k] > worst[0]:
            worst = (float(miss[k]), f, k)
    e, f, k = worst
    if e <= AIM_INFO:
        return []
    text = (
        f"Paraxial ray aiming: the {_AIM_RAYS[k]} ray of field {f + 1} crosses the stop {e * pupil.r_stop:.3g} mm from the point it "
        f"stands for ({100 * e:.1f} % of the stop radius). Spots, MTF, wavefront, relative illumination, vignetting and "
        f"chief-ray results refer to the paraxial entrance pupil, not to the stop; real ray aiming fills the stop"
    )
    if e > AIM_WARN:
        return [Diagnostic("warning", "PARAXIAL_AIMING", text, cs.stop)]
    return [Diagnostic("info", "PARAXIAL_AIMING", text, cs.stop)]


def evaluate_system(cs: CompiledSystem, layout_rays_per_field: int = 7, ring_rays: int = 8) -> dict:
    diags = list(cs.diagnostics)
    pupil = compute_pupil(cs)
    auto_sd = auto_semi_diameters(cs, pupil)
    sd = effective_semi_diameters(cs, auto_sd)
    diags.extend(validate_geometry(cs, sd))
    paraxial = {}
    for w in range(len(cs.wavelengths)):
        try:
            paraxial[w] = paraxial_data(cs, w).as_dict()
        except Exception as exc:  # pragma: no cover - defensive
            diags.append(Diagnostic("warning", "PARAXIAL_FAILED", f"Paraxial analysis failed: {exc}"))
    # chief + marginal real-ray check per field (primary wavelength)
    wl = cs.model.primary_wavelength
    ray_checks = []
    for f in range(len(cs.model.fields)):
        # chief ray, then the marginal rays of the (vignetted) pupil
        mx, my = vignetted_pupil(cs, f, np.array([0.0, 0.0, 1.0, -1.0]), np.array([1.0, -1.0, 0.0, 0.0]))
        r = trace_pupil(cs, wl, f, np.concatenate([[0.0], mx]), np.concatenate([[0.0], my]), pupil)
        if cs.obscuration is not None:  # the chief ray is a reference: traced through obscurations
            rc = trace_pupil(cs, wl, f, np.array([0.0]), np.array([0.0]), pupil, obscure=False)
            r.status[0], r.fail_surface[0] = rc.status[0], rc.fail_surface[0]
        summary = status_summary(r)
        if np.any(r.status != OK):
            for k in np.nonzero(r.status != OK)[0]:
                name = ["chief", "marginal +y", "marginal -y", "marginal +x", "marginal -x"][k]
                diags.append(
                    Diagnostic(
                        "warning",
                        "RAY_FAILED",
                        f"Field {f + 1}: {name} ray failed at surface {int(r.fail_surface[k])} ({STATUS_TEXT[int(r.status[k])]})",
                        int(r.fail_surface[k]),
                    )
                )
        ray_checks.append({"field": f, "status": summary})
    if pupil.telecentric:
        diags.extend(telecentric_check(cs, pupil))
    diags.extend(aiming_check(cs, pupil))
    # global surface positions (vertex z) for tables
    rays2d = layout_rays(cs, pupil, layout_rays_per_field, "meridional")
    rays3d = layout_rays(cs, pupil, ring_rays, "ring") if ring_rays > 0 else []
    return {
        "pupil": {"entrance_pupil_z": pupil.z_ep, "entrance_pupil_radius": pupil.r_ep, "stop_radius": pupil.r_stop},
        "paraxial": paraxial,
        "auto_semi_diameters": auto_sd.tolist(),
        "semi_diameters": sd.tolist(),
        "surfaces": surface_profiles(cs, sd),
        "elements": lens_elements(cs),
        "rays": rays2d,
        "rays3d": rays3d,
        "ray_checks": ray_checks,
        "diagnostics": [d.as_dict() for d in diags],
        "axial": cs.axial,
        "global_vertex_z": [float(f.origin[2]) for f in cs.frames],
        "indices": cs.n_after.tolist(),  # [wavelength][surface]: medium after each surface
        "solved": solved_values(cs),  # resolved values of surfaces with solves/pickups
        "configuration": ({"active": cs.model.multi_config.active, "names": list(cs.model.multi_config.names)} if cs.model.multi_config else None),
        "edge_thickness": [
            (edge_thickness(cs, i, max(sd[i], sd[i + 1])) if (i + 1 < cs.n_surfaces and not cs.is_cb[i] and not cs.is_cb[i + 1] and i > 0) else None)
            for i in range(cs.n_surfaces)
        ],
        "method": "Exact real-ray trace (sequential); paraxial data by y-nu trace",
    }
