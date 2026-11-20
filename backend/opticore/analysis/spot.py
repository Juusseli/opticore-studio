"""Spot diagrams and RMS spot radius (geometric, real rays)."""

from __future__ import annotations

import numpy as np

from ..paraxial import compute_pupil, paraxial_data
from ..raytrace import pupil_pattern, status_summary, trace_pupil
from ..system import CompiledSystem


def spot_diagram(
    cs: CompiledSystem,
    pattern: str = "hexapolar",
    density: int = 6,
    reference: str = "centroid",
    fields: list[int] | None = None,
    wavelengths: list[int] | None = None,
) -> dict:
    """Geometric spot diagram on the image surface.

    reference: 'centroid' (polychromatic weighted centroid) or 'chief'
    (primary-wavelength chief ray). Radii are reported in micrometres.
    """
    pupil = compute_pupil(cs)
    px, py = pupil_pattern(pattern, density)
    fields = list(range(len(cs.model.fields))) if fields is None else fields
    wavelengths = list(range(len(cs.wavelengths))) if wavelengths is None else wavelengths
    prim = cs.model.primary_wavelength
    try:
        pd = paraxial_data(cs, prim)
        wf = pd.working_fnum
    except Exception:
        wf = None
    lam_prim = float(cs.wavelengths[prim])
    airy_um = 1.22 * lam_prim * wf if wf else None
    out_fields = []
    for f in fields:
        per_wl = []
        all_xy = []
        all_w = []
        chief = trace_pupil(cs, prim, f, np.array([0.0]), np.array([0.0]), pupil, obscure=False)
        chief_xy = chief.image_xy()[0] if chief.ok[0] else np.array([np.nan, np.nan])
        for w in wavelengths:
            r = trace_pupil(cs, w, f, px, py, pupil, vignetting=True)
            xy = r.image_xy()[r.ok]
            weight = cs.model.wavelengths[w].weight
            all_xy.append(xy)
            all_w.append(np.full(len(xy), weight))
            per_wl.append({"wavelength": w, "xy": xy, "summary": status_summary(r), "n_rays": int(len(px)), "n_ok": int(len(xy))})
        XY = np.concatenate(all_xy) if all_xy else np.zeros((0, 2))
        W = np.concatenate(all_w) if all_w else np.zeros(0)
        if len(XY) and W.sum() > 0:
            centroid = (XY * W[:, None]).sum(0) / W.sum()
        else:
            centroid = np.array([np.nan, np.nan])
        ref = centroid if reference == "centroid" else chief_xy
        if len(XY) and W.sum() > 0 and np.all(np.isfinite(ref)):
            d2 = ((XY - ref) ** 2).sum(1)
            rms = float(np.sqrt((d2 * W).sum() / W.sum()))
            geo = float(np.sqrt(d2.max()))
        else:
            rms = geo = float("nan")
        wl_stats = []
        for item in per_wl:
            xy = item["xy"]
            if len(xy) and np.all(np.isfinite(ref)):
                d2 = ((xy - ref) ** 2).sum(1)
                wl_stats.append({"rms_um": float(np.sqrt(d2.mean())) * 1e3, "geo_um": float(np.sqrt(d2.max())) * 1e3})
            else:
                wl_stats.append({"rms_um": None, "geo_um": None})
        out_fields.append(
            {
                "field": f,
                "field_value": [cs.model.fields[f].x, cs.model.fields[f].y],
                "reference_xy": ref.tolist(),
                "chief_xy": chief_xy.tolist(),
                "centroid_xy": centroid.tolist(),
                "rms_radius_um": rms * 1e3,
                "geo_radius_um": geo * 1e3,
                "per_wavelength": [
                    {
                        "wavelength": it["wavelength"],
                        "points_um": ((it["xy"] - ref) * 1e3).tolist() if np.all(np.isfinite(ref)) else [],
                        "n_rays": it["n_rays"],
                        "n_ok": it["n_ok"],
                        "status": it["summary"],
                        **st,
                    }
                    for it, st in zip(per_wl, wl_stats)
                ],
            }
        )
    return {
        "fields": out_fields,
        "airy_radius_um": airy_um,
        "settings": {"pattern": pattern, "density": density, "reference": reference, "rays_per_wavelength": int(len(px))},
        "units": {"points": "um, relative to reference", "radius": "um"},
        "method": "Real-ray geometric spot on the image surface; weighted by wavelength weights",
    }


def rms_spot_radius(cs: CompiledSystem, field: int, pattern="hexapolar", density=6, reference="centroid") -> float:
    """Polychromatic RMS spot radius in mm (helper for optimisation and tests)."""
    res = spot_diagram(cs, pattern, density, reference, fields=[field])
    return res["fields"][0]["rms_radius_um"] / 1e3
