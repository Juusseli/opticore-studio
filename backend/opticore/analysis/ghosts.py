"""Two-surface ghost analysis (double reflections in a sequential lens).

A two-surface ghost arises when light refracted through surfaces 1..i-1 is
partially reflected at surface i, travels backwards, is partially
reflected again at an earlier surface j < i and then continues forwards to
the image. For every pair (i, j) of interfaces with an index step the
ghost path is built as an ordinary sequential system:

    S0 .. S(i-1)            unchanged
    S(i)    as a mirror     thickness -t(i-1), medium unchanged
    S(i-1) .. S(j+1)        traversed backwards: thickness -t(k-1),
                            medium after = medium before S(k) (forwards)
    S(j)    as a mirror     thickness +t(j)
    S(j+1) .. image         unchanged

Rays are launched with the main system's entrance pupil (Gaussian pupil
quadrature) and traced exactly through the ghost system. Fixed (mechanical)
apertures clip ghost rays; automatic apertures do not.

Energy: every ray carries the product of the unpolarised transmittances at
all refractions (Fresnel or thin-film coating), bulk absorption, and the
unpolarised reflectances R_i, R_j at its actual angles of incidence (Fresnel
or coating, incident from the correct side). The ghost energy is the
pupil-area-weighted sum relative to the power entering the entrance pupil.

Reported per ghost: paraxial ghost focus relative to the image surface,
real-ray RMS/geometric radius of the ghost footprint on the image surface,
energy fraction, and the mean irradiance over the geometric footprint
relative to that of the main image (footprint radius floored at the Airy
radius for both). The relative irradiance is an estimate for ranking
ghosts, not a stray-light irradiance distribution (no diffraction,
scattering or higher-order ghosts; single field and wavelength).

Systems with mirrors or coordinate breaks between the object and the image
are not supported by this module yet (a structured error is returned).
"""

from __future__ import annotations

import math

import numpy as np

from ..model import OpticalSystem
from ..paraxial import compute_pupil, marginal_ray, paraxial_data
from ..raytrace import gauss_pupil, launch, trace
from ..system import compile_raw, CompiledSystem, NotApplicable
from ..thinfilm import stack_rt

NON = {"AIR", "VACUUM", ""}


def ghost_system(model: OpticalSystem, i: int, j: int) -> OpticalSystem:
    """Sequential system that follows the (i, j) double-reflection path."""
    s = [x.model_dump() for x in model.surfaces]
    n = len(s)
    out = []

    def copy(k: int, **kw) -> dict:
        d = dict(s[k])
        d.update(id=f"g{len(out)}_{s[k]['id']}", is_stop=False, thickness_solve=None, curvature_solve=None, **kw)
        return d

    for k in range(0, i):
        out.append(copy(k))
    out.append(copy(i, material="MIRROR", thickness=-(s[i - 1]["thickness"] or 0.0), coating=""))
    for k in range(i - 1, j, -1):
        out.append(copy(k, thickness=-(s[k - 1]["thickness"] or 0.0), material=s[k - 1]["material"]))
    out.append(copy(j, material="MIRROR", thickness=s[j]["thickness"], coating=""))
    for k in range(j + 1, n):
        out.append(copy(k))
    d = model.model_dump()
    d["surfaces"] = out
    d["multi_config"] = None
    # any surface may be the stop for validation; rays are launched with the main pupil
    d["surfaces"][1]["is_stop"] = True
    return OpticalSystem.model_validate(d)


def _reflectance(cs: CompiledSystem, wl: int, surf: int, from_front: bool, cos_i: np.ndarray) -> np.ndarray:
    """Unpolarised reflectance of interface `surf` of the main system for light incident from the front (n_before) or back side."""
    n_front = cs.n_after[wl, surf - 1]
    n_back = cs.n_after[wl, surf]
    n1, n2 = (n_front, n_back) if from_front else (n_back, n_front)
    coat = cs.coatings[surf] if cs.coatings else None
    layers = () if coat is None else coat.oriented(float(cs.wavelengths[wl]), n1, n2)
    cos_i = np.asarray(cos_i, dtype=float)
    # total internal reflection inside the denser medium: R = 1
    tir = (n1 / n2) ** 2 * (1 - cos_i**2) >= 1.0
    R = np.ones_like(cos_i)
    if np.any(~tir):
        o = stack_rt(n1, n2, layers, float(cs.wavelengths[wl]), cos_i[~tir])
        R[~tir] = 0.5 * (o["Rs"] + o["Rp"])
    return R


def ghost_analysis(cs: CompiledSystem, custom_materials=(), field: int = 0, wavelength: int | None = None, rings: int = 6, fan_rays: int = 7) -> dict:
    model = cs.model
    n = cs.n_surfaces
    if any(cs.is_cb[1:-1]) or any(cs.is_mirror[1:-1]):
        raise NotApplicable("Ghost analysis currently supports refractive systems without mirrors or coordinate breaks; the non-sequential trace follows ghosts of any system")
    wl = cs.wl_index(wavelength)
    pupil = compute_pupil(cs, cs.model.primary_wavelength)  # the aperture at the primary wavelength, as every launch uses
    lam_mm = float(cs.wavelengths[wl]) * 1e-3
    px, py, pw = gauss_pupil(rings)
    P0, D0, opl0 = launch(cs, wl, field, px, py, pupil)
    # main image for reference
    main = trace(cs, wl, P0, D0, opl0, clip=True, fresnel=True)
    pd = paraxial_data(cs, wl)
    wf = pd.working_fnum or pd.image_space_fnum or 0.0
    airy = 1.22 * lam_mm * wf if wf else 0.0
    ok_m = main.ok
    E_main = float((pw * np.where(ok_m, main.intensity, 0.0)).sum())
    xy_m = main.image_xy()
    w_m = pw * np.where(ok_m, main.intensity, 0.0)
    c_m = (w_m[:, None] * np.nan_to_num(xy_m)).sum(0) / max(w_m.sum(), 1e-300)
    geo_m = float(np.nanmax(np.hypot(*(xy_m[ok_m] - c_m).T))) if ok_m.any() else float("nan")
    r_main = max(geo_m, airy, 1e-9)
    irr_main = E_main / r_main**2 if E_main > 0 else float("nan")

    # meridional fan for drawing ghost paths
    fy = np.linspace(-1.0, 1.0, max(fan_rays, 2))
    F0, FD, Fo = launch(cs, wl, field, np.zeros_like(fy), fy, pupil)

    ghosts = []
    skipped = 0
    for i in range(2, n - 1):
        for j in range(1, i):
            if cs.n_after[wl, i - 1] == cs.n_after[wl, i] or cs.n_after[wl, j - 1] == cs.n_after[wl, j]:
                skipped += 1
                continue  # no index step: no reflection
            gsys = ghost_system(model, i, j)
            g = compile_raw(gsys, custom_materials)
            gi, gj = i, 2 * i - j
            r = trace(g, wl, P0, D0, opl0, clip=True, fresnel=True, record=True)
            ok = r.ok
            row = {"reflect_first": i, "reflect_second": j, "energy_fraction": 0.0, "rms_radius_mm": None, "geo_radius_mm": None, "relative_irradiance": 0.0, "focus_from_image_mm": None, "rays_ok": int(ok.sum()), "rays": int(len(ok))}
            # paraxial ghost focus relative to the image surface
            try:
                m = marginal_ray(g, wl, pupil)
                last = g.n_surfaces - 2
                if abs(m.u[last]) > 1e-15:
                    row["focus_from_image_mm"] = float(-m.y[last] / m.u[last] - (gsys.surfaces[last].thickness or 0.0))
            except Exception:  # noqa: BLE001
                pass
            if ok.any():
                k_i = r.dirs_after[:, gi - 1, :]
                k_j = r.dirs_after[:, gj - 1, :]
                cos_i = np.ones(len(ok))
                cos_j = np.ones(len(ok))
                cos_i[ok] = np.abs(np.einsum("ij,ij->i", k_i[ok], r.normals[ok, gi, :]))
                cos_j[ok] = np.abs(np.einsum("ij,ij->i", k_j[ok], r.normals[ok, gj, :]))
                Ri = np.zeros(len(ok))
                Rj = np.zeros(len(ok))
                Ri[ok] = _reflectance(cs, wl, i, True, np.clip(cos_i[ok], 0, 1))
                Rj[ok] = _reflectance(cs, wl, j, False, np.clip(cos_j[ok], 0, 1))
                I = np.where(ok, r.intensity * Ri * Rj, 0.0)
                w = pw * I
                E = float(w.sum())
                xy = r.image_xy()
                if w.sum() > 0:
                    c = (w[:, None] * np.nan_to_num(xy)).sum(0) / w.sum()
                    d = np.hypot(*(np.nan_to_num(xy) - c).T)
                    rms = float(math.sqrt((w * d * d).sum() / w.sum()))
                    geo = float(np.max(d[ok]))
                    rg = max(geo, airy, 1e-9)
                    row.update(
                        energy_fraction=E,
                        rms_radius_mm=rms,
                        geo_radius_mm=geo,
                        centroid_mm=[float(c[0]), float(c[1])],
                        relative_irradiance=(E / rg**2) / irr_main if irr_main and np.isfinite(irr_main) else None,
                        mean_R_first=float((pw * Ri * ok).sum() / max((pw * ok).sum(), 1e-300)),
                        mean_R_second=float((pw * Rj * ok).sum() / max((pw * ok).sum(), 1e-300)),
                    )
            fr = trace(g, wl, F0, FD, Fo, clip=True)
            paths = []
            for k in range(len(fy)):
                pts = [fr.points[k, s] for s in range(g.n_surfaces) if np.all(np.isfinite(fr.points[k, s]))]
                if len(pts) > 1:
                    paths.append([[float(p[2]), float(p[1])] for p in pts])
            row["paths_zy"] = paths
            ghosts.append(row)
    ghosts.sort(key=lambda r: -(r["relative_irradiance"] or 0.0))
    return {
        "field": field,
        "wavelength_um": float(cs.wavelengths[wl]),
        "main": {"energy_fraction": E_main, "geo_radius_mm": geo_m, "airy_radius_mm": airy, "working_fnum": wf},
        "ghosts": ghosts,
        "pairs_skipped_no_index_step": skipped,
        "settings": {"rings": rings, "rays": int(len(px))},
        "units": {"length": "mm", "energy": "fraction of entrance-pupil power"},
        "method": "Exact sequential trace of each two-surface ghost path (mirror copies of the reflecting surfaces); unpolarised Fresnel/coating reflectance at each ray's angle; transmittances and absorption on all passes; relative irradiance = mean irradiance over the geometric footprint vs the main image (radii floored at the Airy radius)",
    }

