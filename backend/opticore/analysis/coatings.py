"""Coatings in the optical system: real incidence angles per surface, the
context a coating is designed for, per-surface coating performance versus
wavelength, and the ray-averaged reflectance of a surface (merit operand).

Angles are measured from the surface normal in the medium in front of the
surface (the side the light comes from). For the coating designer they are
converted into the equivalent angle in the LOW-INDEX medium of the
interface (n sin(theta) is invariant through the stack), because designs
describe light incident from the low-index side; by reciprocity the
transmittance is the same in both directions (reflectance too for lossless
films). Rays that would be totally internally reflected have no
low-index-side equivalent and are reported separately.

The system transmission spectrum is an estimate: the product of the
unpolarised per-surface transmittance at each surface's ray-averaged angle,
the mirror reflectances and the on-axis bulk transmittance exp(-alpha t) with
alpha at each wavelength as in the trace (catalogue internal transmittance
when catalog_absorption is set; incoherent, no multiple reflections). The
throughput analysis gives the exact ray-traced value at the system
wavelengths.
"""

from __future__ import annotations

import math

import numpy as np

from ..paraxial import compute_pupil
from ..raytrace import gauss_pupil, launch, trace
from ..materials.catalog import MaterialError
from ..system import CompiledSystem, SystemError_, medium_absorption
from ..thinfilm import stack_rt, unpolarized_R


def medium_names(cs: CompiledSystem) -> list[str]:
    """Name of the medium after each surface (mirrors and coordinate breaks keep the medium)."""
    out = []
    name = cs.model.surfaces[0].material
    for i, s in enumerate(cs.model.surfaces):
        if i == 0 or not (s.is_mirror or s.type == "coordinate_break"):
            name = s.material
        out.append(name)
    return out


def _check_surface(cs: CompiledSystem, j: int):
    if not 0 < j < cs.n_surfaces - 1 or cs.is_cb[j]:
        raise SystemError_(f"Surface {j} is not an optical surface (object, image or coordinate break)")


def incidence(cs: CompiledSystem, j: int, wavelength: int | None = None, rings: int = 6, fields: list[int] | None = None) -> dict:
    """cos(theta) of the rays at surface j (all fields; quadrature pupil), in the medium before j."""
    _check_surface(cs, j)
    wl = cs.wl_index(wavelength)
    pupil = compute_pupil(cs, wl)
    px, py, w = gauss_pupil(rings)
    cosv, wts = [], []
    for f in fields if fields is not None else range(len(cs.model.fields)):
        P0, D0, opl = launch(cs, wl, f, px, py, pupil)
        r = trace(cs, wl, P0, D0, opl, end=j, record=True)
        ok = r.ok
        if not ok.any():
            continue
        d_in = r.dirs_after[ok, j - 1, :]
        N = r.normals[ok, j, :]
        cosv.append(np.abs(np.einsum("ij,ij->i", d_in, N)))
        wts.append(w[ok])
    if not cosv:
        raise SystemError_(f"No rays reach surface {j}")
    return {"cos": np.concatenate(cosv), "weights": np.concatenate(wts), "wavelength": wl}


def _stats(theta_deg: np.ndarray, w: np.ndarray) -> dict:
    o = np.argsort(theta_deg)
    cw = np.cumsum(w[o]) / w.sum()
    return {
        "min": float(theta_deg.min()),
        "max": float(theta_deg.max()),
        "mean": float((theta_deg * w).sum() / w.sum()),
        "p95": float(theta_deg[o][np.searchsorted(cw, 0.95).clip(0, len(o) - 1)]),
    }


def surface_context(cs: CompiledSystem, j: int) -> dict:
    """What a coating on surface j sees: media on both sides, angle range, system band."""
    _check_surface(cs, j)
    names = medium_names(cs)
    before, after = names[j - 1], names[j]
    wl = cs.model.primary_wavelength
    inc = incidence(cs, j, wl)
    n1 = float(cs.n_after[wl, j - 1])
    lam = [float(w) * 1e3 for w in cs.wavelengths]
    out = {
        "surface": j,
        "is_mirror": bool(cs.is_mirror[j]),
        "coating": cs.model.surfaces[j].coating,
        "wavelength_band_nm": [min(lam), max(lam)],
        "primary_nm": float(cs.wavelengths[wl]) * 1e3,
        "rays": int(len(inc["cos"])),
    }
    th1 = np.degrees(np.arccos(np.clip(inc["cos"], -1, 1)))
    if cs.is_mirror[j]:
        out.update({"incident": before, "substrate": None, "light_from": "incident", "angles_deg": _stats(th1, inc["weights"]), "angles_in_medium": before})
        return out
    n2 = float(cs.n_after[wl, j])
    low, high = (before, after) if n1 <= n2 else (after, before)
    n_low = min(n1, n2)
    s = n1 * np.sqrt(np.clip(1 - inc["cos"] ** 2, 0, None)) / n_low  # sin(theta) in the low-index medium
    tir = s >= 1.0
    th_low = np.degrees(np.arcsin(np.clip(s, 0, 1)))
    keep = ~tir
    out.update(
        {
            "incident": low,
            "substrate": high,
            "light_from": "incident" if n1 <= n2 else "substrate",
            "angles_deg": _stats(th_low[keep], inc["weights"][keep]) if keep.any() else None,
            "angles_in_medium": low,
            "angles_actual_deg": _stats(th1, inc["weights"]),
            "tir_fraction": float(inc["weights"][tir].sum() / inc["weights"].sum()),
        }
    )
    return out


def _layers_for(coat, lam_um, n1, n2):
    return () if coat is None else coat.oriented(lam_um, n1, n2)


def coating_performance(cs: CompiledSystem, lambda_min_nm: float | None = None, lambda_max_nm: float | None = None, samples: int = 121, include_uncoated: bool = True) -> dict:
    lib = cs.library
    names = medium_names(cs)
    lw = [float(w) * 1e3 for w in cs.wavelengths]
    lo = lambda_min_nm or min(lw) * 0.9
    hi = lambda_max_nm or max(lw) * 1.1
    if hi <= lo:
        raise SystemError_("lambda_max must exceed lambda_min")
    lam = np.linspace(lo, hi, samples)
    n_of = {nm: np.array([lib.index(nm, float(x) * 1e-3) for x in lam]) for nm in set(names) if lib.has(nm)}
    rows = []
    T_sys = np.ones_like(lam)
    for j in range(1, cs.n_surfaces - 1):
        if cs.is_cb[j]:
            continue
        coat = cs.coatings[j] if cs.coatings else None
        mirror = bool(cs.is_mirror[j])
        n1, n2 = n_of[names[j - 1]], n_of[names[j]]
        if not mirror and coat is None and (not include_uncoated or np.allclose(n1, n2)):
            continue
        try:
            inc = incidence(cs, j, None, rings=4)
            th = np.degrees(np.arccos(np.clip(inc["cos"], -1, 1)))
            st = _stats(th, inc["weights"])
        except SystemError_:
            st = {"min": 0.0, "max": 0.0, "mean": 0.0, "p95": 0.0}
        R = {k: np.zeros_like(lam) for k in ("mean", "max", "normal")}
        T = {k: np.zeros_like(lam) for k in ("mean", "max", "normal")}
        for key, ang in (("normal", 0.0), ("mean", st["mean"]), ("max", st["max"])):
            c = math.cos(math.radians(ang))
            for i, l in enumerate(lam):
                lu = float(l) * 1e-3
                if mirror:
                    if coat is None:
                        R[key][i] = 1.0
                    else:
                        R[key][i] = float(unpolarized_R(float(n1[i]), coat.substrate, coat.layers_at(lu), lu, np.array([c]))[0])
                    T[key][i] = 0.0
                else:
                    o = stack_rt(float(n1[i]), float(n2[i]), _layers_for(coat, lu, float(n1[i]), float(n2[i])), lu, np.array([c]))
                    R[key][i] = 0.5 * (o["Rs"][0] + o["Rp"][0])
                    T[key][i] = 0.5 * (o["Ts"][0] + o["Tp"][0])
        T_sys *= R["mean"] if mirror else T["mean"]
        rows.append(
            {
                "surface": j,
                "label": cs.model.surfaces[j].label,
                "coating": coat.name if coat is not None else None,
                "mirror": mirror,
                "media": [names[j - 1], names[j]],
                "angles_deg": st,
                "R": {k: v.tolist() for k, v in R.items()},
                "T": {k: v.tolist() for k, v in T.items()},
            }
        )
    # on-axis bulk transmittance exp(-alpha(lambda) t) per medium, alpha as in the trace (system.medium_absorption:
    # the catalogue internal transmittance at each wavelength when catalog_absorption is set, else the constant)
    bulk = np.ones_like(lam)
    use_cat = bool(cs.model.catalog_absorption)
    absorb_outside: set[str] = set()
    for j in range(1, cs.n_surfaces - 1):
        nm = names[j]
        if cs.is_cb[j] or not lib.has(nm) or nm.strip().upper() in ("", "AIR", "VACUUM"):
            continue
        t = abs(cs.model.surfaces[j].thickness or 0.0)
        for i, x in enumerate(lam):
            try:
                a, outside = medium_absorption(lib, nm, float(x) * 1e-3, use_cat)
            except MaterialError:
                a, outside = 0.0, False
            if outside:
                absorb_outside.add(nm)
            bulk[i] *= math.exp(-a * t)
    notes = []
    if absorb_outside:
        notes.append(f"Catalogue absorption of {', '.join(sorted(absorb_outside))} is used beyond its tabulated wavelengths (nearest end value)")
    return {
        "lambda_nm": lam.tolist(),
        "surfaces": rows,
        "system_transmission_estimate": (T_sys * bulk).tolist(),
        "system_wavelengths_nm": lw,
        "notes": notes,
        "method": "Per-surface thin-film / Fresnel R and T (unpolarised) at normal incidence and at the ray-averaged and maximum angle of the traced pupil (all fields, primary wavelength); system transmission estimated as the product of the per-surface values at the mean angle, mirror reflectances and on-axis bulk transmittance (incoherent, no multiple reflections"
        + ("; catalogue internal transmittance" if use_cat else "")
        + ")",
    }


def surface_reflectance(cs: CompiledSystem, j: int, wavelength: int | None = None, field: int | None = None, rings: int = 4) -> float:
    """Ray-averaged (pupil quadrature) unpolarised reflectance of surface j for the light that reaches it."""
    _check_surface(cs, j)
    wls = range(len(cs.wavelengths)) if wavelength is None else [wavelength]
    fields = None if field is None else [field]
    tot = wsum = 0.0
    for wl in wls:
        inc = incidence(cs, j, wl, rings, fields)
        c, w = inc["cos"], inc["weights"]
        lam_um = float(cs.wavelengths[wl])
        n1, n2 = float(cs.n_after[wl, j - 1]), float(cs.n_after[wl, j])
        coat = cs.coatings[j] if cs.coatings else None
        if cs.is_mirror[j]:
            if coat is None:
                R = np.ones_like(c)
            else:
                R = unpolarized_R(n1, coat.substrate, coat.layers_at(lam_um), lam_um, c)
        else:
            tir = (n1 / n2) ** 2 * (1 - c**2) >= 1.0
            R = np.ones_like(c)
            if np.any(~tir):
                o = stack_rt(n1, n2, _layers_for(coat, lam_um, n1, n2), lam_um, c[~tir])
                R[~tir] = 0.5 * (o["Rs"] + o["Rp"])
        tot += float((R * w).sum())
        wsum += float(w.sum())
    return tot / wsum


__all__ = ["coating_performance", "incidence", "medium_names", "surface_context", "surface_reflectance"]
