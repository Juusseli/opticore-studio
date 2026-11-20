"""Lens elements as manufactured parts: mechanical geometry, mass and the data of an ISO 10110 drawing.

Every glass between two consecutive refracting surfaces is one element (a cemented doublet has two).
The prescription is the design at 20 degC: the active configuration with the environment model off and
the solves resolved.

Geometry (local frame of the element: front vertex at z = 0, axis z, meridional radius r):

* Clear apertures: the effective semi-diameters of the two surfaces (automatic or fixed).
* Rim: the element's outer radius R is the largest of its surfaces' mechanical semi-diameters, a surface
  without one counting with its clear semi-diameter (plus an optional margin, used by the CAD export).
* A surface with a mechanical semi-diameter ends there and a flat (perpendicular to the axis) continues
  to the rim; a surface without one continues to the rim.
* Profiles z_f(r), t + z_b(r) are the exact sags (meridional y-z section for surfaces that are not
  rotationally symmetric); the thickness is T(r) = t + z_b(r) - z_f(r); the edge thickness is T(R).
* Chamfers: 45 deg protective chamfers of leg c at the rim on each side: inside r > R - c the face is
  replaced by the chord from the face at R - c to the rim c from the face (as in the CAD solid).
* Volume: 2 pi int_0^R r T(r) dr with these boundaries (Gauss-Legendre, 48 nodes per smooth piece,
  breaks at the flats and chamfers).
* Mass: volume x density (catalogue, g/cm^3) where the material gives one.

ISO 10110 data: radii, centre thickness, clear and outer diameters, chamfers, material (nd, Vd, the
glass code), coatings and the project's tolerances that apply to the element: radius and centre
thickness, 3/A(B/C) from the power and irregularity tolerances (fringes at the test wavelength),
4/sigma from the surface and element tilts (arc minutes), decenters, index (nd) and Abbe number (Vd).
"""

from __future__ import annotations

import math

import numpy as np

from ..model import OpticalSystem
from ..system import CompiledSystem, compile_system

GASES = ("AIR", "VACUUM", "MIRROR", "")
_GL_X, _GL_W = np.polynomial.legendre.leggauss(48)


def nominal_system(system: OpticalSystem) -> OpticalSystem:
    """The design at 20 degC: active configuration applied, environment model off."""
    from ..configs import apply_configuration

    d = apply_configuration(system).model_dump()
    d["multi_config"] = None
    d["environment_enabled"] = False
    return OpticalSystem.model_validate(d)


def glass_code(nd: float, vd: float) -> str:
    """Six-digit glass code: 1000 (nd - 1) and 10 Vd, each rounded (e.g. 517642)."""
    return f"{round((nd - 1.0) * 1000):03d}{round(vd * 10):03d}"


def _sag(shape, r: np.ndarray) -> np.ndarray:
    r = np.asarray(r, dtype=float)
    if hasattr(shape, "sag_xy") and (hasattr(shape, "curvature_x") or hasattr(shape, "poly")):
        return np.asarray(shape.sag_xy(np.zeros_like(r), r), dtype=float)  # meridional (y-z) section
    return np.asarray(shape.sag(r * r), dtype=float)


def _profile(shape, end: float):
    """z(r) of a surface that ends at `end` and continues as a flat."""

    def z(r):
        r = np.asarray(r, dtype=float)
        return _sag(shape, np.minimum(r, end))

    return z


def _integrate(f, a: float, b: float) -> float:
    if b <= a:
        return 0.0
    x = 0.5 * (b - a) * _GL_X + 0.5 * (a + b)
    return float(0.5 * (b - a) * np.sum(_GL_W * f(x)))


def element_geometry(cs: CompiledSystem, sd: np.ndarray, i: int, margin: float = 0.0) -> dict:
    """Mechanical geometry of the element between surfaces i and i + 1 (see the module docstring)."""
    surfs = cs.model.surfaces
    a, b = surfs[i], surfs[i + 1]
    fs, bs = cs.shapes[i], cs.shapes[i + 1]
    t = float(a.thickness or 0.0)
    if t <= 0.0:
        raise ValueError("an element traversed against the axis (after a mirror) is not supported")
    ca = (float(sd[i]), float(sd[i + 1]))
    mech = (a.mech_semi_diameter, b.mech_semi_diameter)
    base = [m if m is not None else c + margin for m, c in zip(mech, ca)]
    R = max(base)
    ends = [m if m is not None else R for m in mech]
    notes: list[str] = []
    for k, (m, c, s) in enumerate(zip(mech, ca, (i, i + 1))):
        if m is not None and m < c - 1e-9:
            notes.append(f"Surface {s}: the mechanical semi-diameter {m:.4g} mm is smaller than the clear semi-diameter {c:.4g} mm")
    zf, zb_ = _profile(fs, ends[0]), _profile(bs, ends[1])

    def zb(r):
        return t + zb_(r)

    for shape, end, s in ((fs, ends[0], i), (bs, ends[1], i + 1)):
        v = _sag(shape, np.array([end]))
        if not np.all(np.isfinite(v)):
            raise ValueError(f"surface {s} is not defined out to {end:.4g} mm (beyond its sphere or conic)")
    chamfers = (float(a.chamfer), float(b.chamfer))
    zr_f, zr_b = float(zf(np.array([R]))[0]), float(zb(np.array([R]))[0])
    T_rim = zr_b - zr_f
    cf, cb = chamfers
    if (cf > 0.0 or cb > 0.0) and (max(cf, cb) >= R or cf + cb >= T_rim):
        raise ValueError(f"the chamfers ({cf:.4g} and {cb:.4g} mm) do not fit the rim (edge thickness {T_rim:.4g} mm, rim radius {R:.4g} mm)")

    def front(r):
        """Front boundary: the face, and inside the chamfer the chord to the rim (45 deg leg cf)."""
        r = np.asarray(r, dtype=float)
        z = zf(r)
        if cf > 0.0:
            z0_ = float(zf(np.array([R - cf]))[0])
            chord = z0_ + (r - (R - cf)) / cf * (zr_f + cf - z0_)
            z = np.where(r > R - cf, chord, z)
        return z

    def backb(r):
        r = np.asarray(r, dtype=float)
        z = zb(r)
        if cb > 0.0:
            z0_ = float(zb(np.array([R - cb]))[0])
            chord = z0_ + (r - (R - cb)) / cb * (zr_b - cb - z0_)
            z = np.where(r > R - cb, chord, z)
        return z

    thick = lambda r: backb(r) - front(r)  # noqa: E731
    rs = np.linspace(0.0, R, 401)
    T = thick(rs)
    if np.min(T) <= 0.0:
        notes.append(f"The surfaces meet inside the element (thickness {np.min(T):.4g} mm at r = {rs[int(np.argmin(T))]:.4g} mm)")
    breaks = sorted({0.0, *[e for e in (*ends, R - cf if cf else R, R - cb if cb else R) if 0.0 < e < R], R})
    vol = sum(_integrate(lambda r: 2.0 * math.pi * r * thick(r), lo, hi) for lo, hi in zip(breaks[:-1], breaks[1:]))
    edge = T_rim
    for c, side in ((cf, 0), (cb, 1)):
        if c > 0.0 and R - c < ca[side] - 1e-9:
            notes.append(f"Surface {i + side}: the chamfer reaches into the clear aperture")
    # outline of the meridional half section (r >= 0) for drawings: front boundary out, rim, back boundary in
    def samples(end, c):
        r = np.concatenate([np.linspace(0.0, min(end, R - c if c else R), 61), [min(end, R)], [R - c] if c else [], [R]])
        return np.unique(np.clip(r, 0.0, R))

    rf = samples(ends[0], cf)
    rb = samples(ends[1], cb)
    outline = [[float(r), float(z)] for r, z in zip(rf, front(rf))] + [[float(r), float(z)] for r, z in zip(rb[::-1], backb(rb[::-1]))]
    return {
        "surfaces": [i, i + 1],
        "center_thickness_mm": t,
        "clear_semi_diameters_mm": list(ca),
        "mech_semi_diameters_mm": [None if m is None else float(m) for m in mech],
        "profile_ends_mm": [float(e) for e in ends],
        "rim_radius_mm": float(R),
        "edge_thickness_mm": edge,
        "min_thickness_mm": float(np.min(T)),
        "sag_clear_mm": [float(zf(np.array([ca[0]]))[0]), float(zb_(np.array([ca[1]]))[0])],
        "sag_rim_mm": [zr_f, zr_b - t],
        "chamfers_mm": list(chamfers),
        "volume_mm3": float(vol),
        "outline": outline,
        "notes": notes,
    }


def _tolerances_for(spec, system: OpticalSystem, i: int) -> dict:
    """The enabled tolerances of the project that apply to the element i..i+1, in ISO 10110 terms."""
    if spec is None:
        return {}
    pos = {s.id: k for k, s in enumerate(system.surfaces)}
    out: dict = {"surfaces": [{}, {}], "notes": []}

    def mag(t):
        return max(abs(t.min), abs(t.max))

    for t in spec.tolerances:
        if not t.enabled or t.surface_id not in pos:
            continue
        k = pos[t.surface_id]
        side = k - i
        if t.type.startswith("element_"):
            k2 = pos.get(t.surface_id_end, k)
            if not (k <= i and i + 1 <= k2):
                continue
            if "tilt" in t.type:
                for sd_ in out["surfaces"]:
                    sd_["tilt_arcmin"] = max(sd_.get("tilt_arcmin", 0.0), mag(t) * 60.0)
            else:
                out["decenter_mm"] = max(out.get("decenter_mm", 0.0), mag(t))
            continue
        if side not in (0, 1):
            continue
        s = out["surfaces"][side]
        if t.type == "radius":
            s["radius"] = [t.min, t.max]
        elif t.type == "power":
            s["power_fringes"] = max(s.get("power_fringes", 0.0), mag(t))
        elif t.type == "irregularity":
            s["irregularity_fringes"] = max(s.get("irregularity_fringes", 0.0), mag(t))
        elif t.type == "irregularity_rotational":
            s["rotational_fringes"] = max(s.get("rotational_fringes", 0.0), mag(t))
        elif t.type == "zernike_form":
            s.setdefault("zernike_um", []).append({"term": t.term, "max": mag(t)})
        elif t.type in ("surface_tilt_x", "surface_tilt_y"):
            s["tilt_arcmin"] = max(s.get("tilt_arcmin", 0.0), mag(t) * 60.0)
        elif t.type in ("surface_decenter_x", "surface_decenter_y"):
            s["decenter_mm"] = max(s.get("decenter_mm", 0.0), mag(t))
        elif side == 0 and t.type == "thickness":
            out["center_thickness"] = [t.min, t.max]
        elif side == 0 and t.type == "index":
            out["nd"] = mag(t)
        elif side == 0 and t.type == "abbe":
            out["vd"] = mag(t)
    for s in out["surfaces"]:
        if "power_fringes" in s or "irregularity_fringes" in s or "rotational_fringes" in s:
            a = s.get("power_fringes")
            b = s.get("irregularity_fringes")
            c = s.get("rotational_fringes")
            fa = "-" if a is None else f"{a:g}"
            fb = "-" if b is None else f"{b:g}"
            s["iso_3"] = f"3/{fa}({fb}{'' if c is None else f'/{c:g}'})"
        if "tilt_arcmin" in s:
            s["iso_4"] = f"4/{s['tilt_arcmin']:.3g}'"
    out["test_wavelength_nm"] = spec.test_wavelength_um * 1e3
    return out


def elements(system: OpticalSystem, custom_materials=(), tolerancing=None, margin: float = 0.0) -> dict:
    """Every lens element of the system with its geometry, material, mass and ISO 10110 data."""
    from ..analysis.evaluate import auto_semi_diameters, effective_semi_diameters, lens_elements
    from ..paraxial import compute_pupil

    nom = nominal_system(system)
    cs = compile_system(nom, custom_materials)
    sd = effective_semi_diameters(cs, auto_semi_diameters(cs, compute_pupil(cs), {}))
    model = cs.model
    lib = cs.library
    out = []
    skipped = []
    total_mass = 0.0
    mass_known = True
    cost_weighted = 0.0
    cost_known = True
    from ..materials.dispersion import LAMBDA_C, LAMBDA_D, LAMBDA_F

    for k, el in enumerate(lens_elements(cs)):
        i = el["front"]
        a, b = model.surfaces[i], model.surfaces[i + 1]
        try:
            geo = element_geometry(cs, sd, i, margin)
        except (ValueError, ArithmeticError) as exc:
            skipped.append({"surfaces": [i, i + 1], "reason": str(exc)})
            continue
        mat = lib.get(a.material)
        nd, nf, nc = (mat.index(lam) for lam in (LAMBDA_D, LAMBDA_F, LAMBDA_C))
        vd = (nd - 1.0) / (nf - nc)
        dens = mat.extra.get("density")
        cost = mat.extra.get("relative_cost")
        mass = geo["volume_mm3"] * float(dens) * 1e-3 if dens else None
        if mass is None:
            mass_known = False
        else:
            total_mass += mass
        if mass is not None and cost is not None:
            cost_weighted += mass * float(cost)
        else:
            cost_known = False
        tau10 = mat.catalog_absorption(LAMBDA_D)
        cemented = []
        if i > 1 and model.surfaces[i - 1].material.upper() not in GASES and not cs.is_cb[i - 1] and not cs.is_mirror[i - 1]:
            cemented.append(i)
        if b.material.upper() not in GASES and not cs.is_mirror[i + 1]:
            cemented.append(i + 1)
        out.append(
            {
                "index": len(out) + 1,
                "name": f"L{len(out) + 1}",
                "surfaces": [i, i + 1],
                "surface_ids": [a.id, b.id],
                "labels": [a.label, b.label],
                "radii_mm": [a.radius, b.radius],
                "conics": [a.conic, b.conic],
                "aspheric": [list(a.aspheric) if a.type in ("even_asphere", "zernike") else [], list(b.aspheric) if b.type in ("even_asphere", "zernike") else []],
                "types": [a.type, b.type],
                "coatings": [a.coating or None, b.coating or None],
                "cemented_surfaces": cemented,
                "material": {
                    "name": mat.name,
                    "catalog": mat.extra.get("catalog") or mat.family,
                    "nd": nd,
                    "vd": vd,
                    "code": glass_code(nd, vd),
                    "density_g_cm3": dens,
                    "relative_cost": cost,
                    "internal_transmittance_10mm_d": None if tau10 is None else math.exp(-tau10[0] * 10.0),
                },
                "mass_g": mass,
                **geo,
                "tolerances": _tolerances_for(tolerancing, model, i),
            }
        )
    return {
        "elements": out,
        "skipped": skipped,
        "total_mass_g": total_mass if out and mass_known else None,
        "mass_known_g": total_mass,
        "relative_cost": (cost_weighted / total_mass) if out and cost_known and total_mass > 0 else None,
        "units": {"length": "mm", "mass": "g", "volume": "mm^3"},
        "method": "Design at 20 °C (active configuration, environment off, solves resolved); clear apertures = effective semi-diameters; rim = largest mechanical (else clear) semi-diameter; exact sag profiles (meridional section), flats beyond a mechanical semi-diameter, 45° chamfers; volume by Gauss-Legendre quadrature of 2πr·T(r) minus revolved chamfer triangles; mass from catalogue density; relative cost mass-weighted (catalogue relative cost per unit mass, where every glass has one)",
    }
