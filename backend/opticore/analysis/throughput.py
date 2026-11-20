"""Energy throughput: vignetting, Fresnel surface losses and bulk absorption.

Model: unpolarised Fresnel power transmission at bare dielectric surfaces, or
the thin-film transfer-matrix transmittance where a coating is assigned
(validated R + T = 1 in tests), internal absorption exp(-alpha * path) from
material data (the catalogue internal transmittance per wavelength when the
system's catalog_absorption is on, alpha = -ln(tau) / d, else the material's
constant coefficient), ideal mirrors (R = 1), and no multiple reflections or ghosts
(sequential, single pass). Pupil integrals use Gaussian quadrature, so the values are
pupil-area-weighted fractions of the power entering the entrance pupil.
"""

from __future__ import annotations

import numpy as np

from ..paraxial import compute_pupil
from ..raytrace import gauss_pupil, launch, trace
from ..system import CompiledSystem, _media, medium_absorption


def transmission(cs: CompiledSystem, rings: int = 8) -> dict:
    pupil = compute_pupil(cs)
    px, py, pw = gauss_pupil(rings)
    model = cs.model
    rows = []
    for f in range(len(model.fields)):
        per = []
        for w in range(len(cs.wavelengths)):
            P, D, opl = launch(cs, w, f, px, py, pupil)
            geo = trace(cs, w, P, D, opl, clip=True, fresnel=False)
            ful = trace(cs, w, P, D, opl, clip=True, fresnel=True)
            vig = float((pw * geo.ok).sum())
            tot = float((pw * np.where(ful.ok, ful.intensity, 0.0)).sum())
            per.append(
                {
                    "wavelength": w,
                    "geometric": vig,  # fraction not vignetted / failed
                    "total": tot,  # including Fresnel and absorption
                    "surface_losses": tot / vig if vig > 0 else None,  # transmission of the passing rays
                }
            )
        rows.append({"field": f, "field_value": [model.fields[f].x, model.fields[f].y], "per_wavelength": per})

    # per-surface breakdown for the primary-wavelength on-axis chief ray
    prim = model.primary_wavelength
    P, D, opl = launch(cs, prim, 0, np.array([0.0]), np.array([0.0]), pupil)
    breakdown = []
    prev = 1.0
    for j in range(1, cs.n_surfaces):
        if cs.is_cb[j]:
            continue
        r = trace(cs, prim, P, D, opl, end=j, clip=False, fresnel=True)
        cur = float(r.intensity[0]) if r.ok[0] else 0.0
        if j < cs.n_surfaces - 1:
            breakdown.append({"surface": j, "transmission": cur / prev if prev > 0 else 0.0, "cumulative": cur, "mirror": bool(cs.is_mirror[j]), "coating": cs.coatings[j].name if cs.coatings[j] else None})
        prev = cur if cur > 0 else prev
    wts = np.array([w.weight for w in model.wavelengths])
    fws = np.array([fl.weight for fl in model.fields])
    T = np.array([[x["total"] for x in r["per_wavelength"]] for r in rows])
    mean = float((fws[:, None] * wts[None, :] * T).sum() / (fws.sum() * wts.sum())) if fws.sum() > 0 and wts.sum() > 0 else 0.0
    # absorption of each glass: where it comes from and its coefficient per wavelength
    mats = []
    for name in sorted({m for m, _o, _s in _media(model.surfaces) if m.strip().upper() not in ("AIR", "VACUUM", "MIRROR", "")}):
        mat = cs.library.get(name)
        has = mat.transmittance_table is not None
        alphas = [medium_absorption(cs.library, name, float(lam), model.catalog_absorption)[0] for lam in cs.wavelengths]
        source = "catalogue" if model.catalog_absorption and has else ("constant" if mat.absorption_per_mm > 0 else "none")
        mats.append({"name": mat.name, "source": source, "catalog_data": has, "alpha_per_mm": alphas})
    notes = []
    off = [m["name"] for m in mats if m["catalog_data"] and m["source"] != "catalogue"]
    if off:
        notes.append(f"Catalogue internal transmittance is available for {', '.join(off)} but not used (catalogue absorption is off).")
    return {
        "fields": rows,
        "absorption": {"catalog": model.catalog_absorption, "materials": mats},
        "notes": notes,
        "weighted_mean_total": mean,
        "chief_ray_surfaces": breakdown,
        "settings": {"rings": rings, "rays": int(len(px))},
        "units": {"transmission": "fraction of power entering the entrance pupil"},
        "method": f"Gaussian-quadrature pupil integral; unpolarised Fresnel transmission (bare surfaces) or thin-film transfer matrix (coated surfaces); bulk absorption exp(-alpha L) ({'catalogue internal transmittance per wavelength where available' if model.catalog_absorption else 'material absorption coefficients'}); ideal mirrors; single pass (no ghosts)",
    }
