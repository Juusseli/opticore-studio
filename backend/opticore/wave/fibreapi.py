"""Fibre analyses behind the API: modes of radial profiles, dispersion curves and cross-section (2D) modes.

The physics is in fibermodes.py (exact step-index modes), fibreprofile.py (radial profiles, dispersion, cut-off)
and fibre2d.py (full-vector modes of an arbitrary cross-section)."""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np

from .fibermodes import FibreError, fibre_modes
from .fibreprofile import Profile, cutoff_wavelength, dispersion, lp01_properties, lp_modes, mode_field
from .fibre2d import CrossSection, Shape, hexagonal_holes, solve_modes

IndexFn = Callable[[str, float], float]
RangeFn = Callable[[str], tuple[float, float]]


def _range_notes(spec: dict, range_of: RangeFn | None, what: list[tuple[str, float]]) -> list[str]:
    """A note for each wavelength outside the cladding material's data range (its index there is extrapolated)."""
    mat = spec.get("clad_material")
    if not mat or range_of is None:
        return []
    lo, hi = range_of(mat)
    if not (hi > lo > 0):
        return []
    return [f"{label} {lam:.4g} um is outside the data range of {mat} ({lo:g} to {hi:g} um): its index there is extrapolated" for label, lam in what if lam is not None and not (lo <= lam <= hi)]


def clad_fn(spec: dict, index_of: IndexFn):
    """Cladding index as a function of the wavelength: a library material, else a constant."""
    mat = spec.get("clad_material")
    if mat:
        return lambda lam: float(index_of(mat, lam))
    n = spec.get("n_clad")
    if n is None:
        raise FibreError("Give the cladding index or a cladding material")
    return float(n)


def profile_of(spec: dict, n_clad_ref: float) -> Profile:
    """The radial profile of a request; the core contrast from dn, or from n_core or NA at the reference wavelength,
    as an index offset that is kept at every wavelength."""
    kind = spec.get("profile_kind") or "step"
    if kind == "layers":
        rings = tuple((float(r), float(d)) for r, d in spec.get("layers") or [])
        return Profile("layers", 0.0, layers=rings)
    if spec.get("dn") is not None:
        n1 = n_clad_ref + float(spec["dn"])
    elif spec.get("n_core") is not None:
        n1 = float(spec["n_core"])
    elif spec.get("na") is not None:
        n1 = math.sqrt(n_clad_ref**2 + float(spec["na"]) ** 2)
    else:
        raise FibreError("Give the core index or the numerical aperture")
    return Profile(kind, float(spec["core_radius_um"]), dn_core=n1 - n_clad_ref, alpha=float(spec.get("alpha") or 2.0))


def profile_modes(spec: dict, index_of: IndexFn, range_of: RangeFn | None = None) -> dict:
    """LP modes, LP01 properties and the LP11 cut-off of a step, graded or layered profile."""
    lam = float(spec["wavelength_um"])
    clad = clad_fn(spec, index_of)
    n_clad = clad(lam) if callable(clad) else clad
    prof = profile_of(spec, n_clad)
    out: dict[str, Any] = {}
    if prof.kind == "step":
        # the exact vector solution (Snitzer) plus the profile solver's LP01 properties; the LP11 cut-off
        # of the profile model (the core keeps its index offset over the dispersive cladding)
        out = fibre_modes(lam, prof.a, n_clad + prof.dn_core, n_clad, vector=bool(spec.get("vector", True)))
        if callable(clad):
            out["cutoff_wavelength_um"] = cutoff_wavelength(prof, clad, 1, (0.05, 50.0))
    else:
        modes = lp_modes(prof, lam, clad, fields=False)
        nmax = prof.n_max(n_clad)
        na = math.sqrt(nmax**2 - n_clad**2)
        V = 2 * math.pi / lam * prof.core_radius * na
        profiles = []
        for m in modes[:8]:
            r, psi = mode_field(prof, m, lam, clad)
            sel = r <= max(3.0 * prof.core_radius, 1.2 * prof.a)
            step = max(1, int(sel.sum() // 300))
            profiles.append({"name": m["name"], "l": m["l"], "r_um": r[sel][::step].tolist(), "field": psi[sel][::step].tolist()})
        notes = ["Weakly guiding (scalar LP) modes of the profile; the full-vector splitting is not computed for graded and layered profiles"]
        out = {"wavelength_um": lam, "core_radius_um": prof.core_radius, "outer_radius_um": prof.a, "n_core": nmax, "n_clad": n_clad, "na": na, "v_number": V,
               "single_mode": len(modes) == 1, "lp_modes": modes, "mode_count": int(sum(m["degeneracy"] for m in modes)), "vector_modes": [],
               "profiles": profiles, "notes": notes,
               "method": ("Exact transfer of (psi, psi') through the layers with Bessel functions; " if prof.piecewise_constant else "Finite differences on a cell-centred radial grid with Richardson extrapolation; ")
               + "LP01 mode field diameter by Petermann II"}
        lc = cutoff_wavelength(prof, clad, 1, (0.05, 50.0))
        out["cutoff_wavelength_um"] = lc
        out["single_mode"] = lc is None or lam > lc
    p = lp01_properties(prof, lam, clad)
    lp01 = dict(out.get("lp01") or {})
    lp01.update({"neff": p["neff"], "mfd_petermann2": p["mfd_petermann2_um"], "effective_area_um2": p["effective_area_um2"], "core_power_fraction": p["core_power_fraction"]})
    out["lp01"] = lp01
    out["profile_kind"] = prof.kind
    out["notes"] = list(out.get("notes") or []) + _range_notes(spec, range_of, [("The wavelength", lam), ("The LP11 cut-off", out.get("cutoff_wavelength_um"))])
    r = np.linspace(0.0, max(2.0 * prof.core_radius, 1.25 * prof.a), 401)
    out["index_profile"] = {"r_um": r.tolist(), "n": prof.n(r, n_clad).tolist()}
    return out


def dispersion_curve(spec: dict, index_of: IndexFn, wl_min: float, wl_max: float, points: int, l: int = 0, m: int = 1, range_of: RangeFn | None = None) -> dict:
    if not (0 < wl_min < wl_max) or not (3 <= points <= 201):
        raise FibreError("Give 0 < wavelength min < max and 3 to 201 points")
    clad = clad_fn(spec, index_of)
    lam_ref = float(spec.get("wavelength_um") or wl_min)
    n_ref = clad(lam_ref) if callable(clad) else clad
    prof = profile_of(spec, n_ref)
    lams = np.linspace(wl_min, wl_max, points)
    rows, skipped = [], []
    guess = None
    for lam in lams:
        try:
            rows.append(dispersion(prof, [lam], clad, l, m, guess=guess)["rows"][0])
            guess = rows[-1]["neff"]
        except FibreError:
            skipped.append(float(lam))
            guess = None
    zero = None
    for a, b in zip(rows[:-1], rows[1:]):
        if a["D_ps_nm_km"] * b["D_ps_nm_km"] <= 0:
            from scipy.optimize import brentq

            zero = float(brentq(lambda x: dispersion(prof, [x], clad, l, m, guess=a["neff"])["rows"][0]["D_ps_nm_km"], a["wavelength_um"], b["wavelength_um"], xtol=1e-7))
            break
    notes = []
    if skipped:
        notes.append(f"LP{l}{m} is not guided at {len(skipped)} of the wavelengths (beyond its cut-off)")
    notes += _range_notes(spec, range_of, [("The band edge", wl_min), ("The band edge", wl_max)])
    lc = cutoff_wavelength(prof, clad, 1, (0.05, 50.0))
    return {"mode": f"LP{l}{m}", "rows": rows, "zero_dispersion_um": zero, "cutoff_lp11_um": lc, "notes": notes,
            "method": "n_eff on a five-point stencil in wavelength (h = 2e-3 lambda): group index n - lambda dn/dlambda and D = -(lambda/c) d2n/dlambda2; "
            "material part from the cladding glass alone (the core keeps its index offset), waveguide part = total - material"}


# ---------------------------------------------------------------- cross-sections
def cross_section(spec: dict, lam: float, index_of: IndexFn) -> CrossSection:
    def n_of(item: dict, key_n: str = "n", key_mat: str = "material") -> float:
        if item.get(key_mat):
            return float(index_of(item[key_mat], lam))
        if item.get(key_n) is None:
            raise FibreError("Every region needs an index or a material")
        return float(item[key_n])

    bg = n_of(spec, "n_background", "background_material")
    shapes: list[Shape] = []
    lat = spec.get("lattice")
    if lat:
        n_hole = n_of(lat, "n_hole", "hole_material") if (lat.get("hole_material") or lat.get("n_hole") is not None) else 1.0
        shapes += hexagonal_holes(float(lat["pitch_um"]), float(lat["d_um"]), int(lat["rings"]), n_hole=n_hole, missing_centre=bool(lat.get("missing_centre", True)))
    for s in spec.get("shapes") or []:
        shapes.append(Shape(s.get("kind", "circle"), float(s.get("x", 0.0)), float(s.get("y", 0.0)), n_of(s), r=float(s.get("r", 0.0)),
                            rx=float(s.get("rx", 0.0)), ry=float(s.get("ry", 0.0)), w=float(s.get("w", 0.0)), hgt=float(s.get("h", 0.0)), angle_deg=float(s.get("angle_deg", 0.0))))
    return CrossSection(bg, shapes)


def _mirror_symmetric(cs: CrossSection) -> bool:
    """True when the structure is symmetric about both axes (the quadrant with walls is then exact)."""
    rng = np.random.default_rng(3)
    ext = max(cs.extent(), 1.0) * 1.2
    X, Y = rng.uniform(-ext, ext, 4000), rng.uniform(-ext, ext, 4000)
    n = cs.index(X, Y)
    return bool(np.array_equal(n, cs.index(-X, Y)) and np.array_equal(n, cs.index(X, -Y)))


def _guess(cs: CrossSection, lam: float) -> float:
    """A first guess of the fundamental mode index: a step-index core of the radius of the high-index region around
    the centre (the distance to the nearest lower-index shape), u = 2."""
    nc = float(cs.index(np.array([0.0]), np.array([0.0]))[0])
    rho = math.inf
    for s in cs.shapes:
        if s.n < nc:
            rho = min(rho, math.hypot(s.x, s.y) - s.extent())
        elif s.n >= nc and s.inside(np.array([0.0]), np.array([0.0]))[0]:
            rho = min(rho, s.extent())
    if not math.isfinite(rho) or rho <= 0:
        rho = 2.0 * lam
    k = 2 * math.pi / lam
    return nc - 4.0 / (2 * nc * k * k * rho * rho)


MAX_CELLS_2D = 700  # mesh cells along one side of the solved square


def mesh_of(spec: dict, cs: CrossSection, lam: float) -> tuple[float, float, float, int]:
    """(half window, mesh step, absorbing layer, cells along one side of the solved square): the quadrant of a
    structure symmetric about both axes, else the full window."""
    half = float(spec.get("window_um") or max(3.0 * cs.extent(), 4.0 * lam))
    h = float(spec.get("mesh_um") or half / 100.0)
    pml = float(spec.get("pml_um") or 0.0)
    cells = math.ceil((half + pml) / h - 1e-9) * (1 if _mirror_symmetric(cs) else 2)
    return half, h, pml, cells


def modes_2d(spec: dict, index_of: IndexFn, progress=lambda f: None, control: dict | None = None) -> dict:
    lam = float(spec["wavelength_um"])
    cs = cross_section(spec, lam, index_of)
    half, h, pml, _ = mesh_of(spec, cs, lam)
    pol = spec.get("polarisation", "x")
    count = int(spec.get("count") or 6)
    refine = bool(spec.get("refine", False))
    symmetric = _mirror_symmetric(cs)
    sym = (("pec", "pmc") if pol == "x" else ("pmc", "pec")) if symmetric else None
    n_guess = float(spec["n_guess"]) if spec.get("n_guess") else _guess(cs, lam)
    meshes = [h, h / 2] if refine else [h]
    found = []
    for j, hh in enumerate(meshes):
        if control and control.get("cancel"):
            from .fdtd import Cancelled

            raise Cancelled()
        progress(0.05 + 0.9 * j / len(meshes))
        ms, mesh = solve_modes(cs, lam, half, hh, n_guess=n_guess, count=count, symmetry=sym, pml_um=pml)
        found.append((ms, mesh))
    progress(0.97)
    ms, mesh = found[-1]
    X, Y = np.meshgrid(mesh["x"], mesh["x"], indexing="ij")
    inner = (np.abs(X) <= half) & (np.abs(Y) <= half)
    core_r = max(_core_radius(cs, lam), mesh["h"])
    out_modes = []
    for k, m in enumerate(ms):
        I = np.abs(m["_Ex"]) ** 2 + np.abs(m["_Ey"]) ** 2
        tot = float(I[inner].sum())
        frac = float(I[inner & (np.hypot(X, Y) <= core_r)].sum() / tot) if tot > 0 else 0.0
        # effective area of |E_t|^2 over the plane (the quadrant's sums scale by 4)
        q = 4.0 if sym else 1.0
        a_eff = (q * I[inner].sum() * mesh["h"] ** 2) ** 2 / (q * (I[inner] ** 2).sum() * mesh["h"] ** 2) if tot > 0 else 0.0
        row = {"index": k, "neff": m["neff"].real, "kappa": m["neff"].imag, "loss_db_per_m": m["loss_db_per_m"], "core_fraction": frac, "effective_area_um2": float(a_eff)}
        if refine:
            coarse = min(found[0][0], key=lambda c: abs(c["neff"] - m["neff"]))
            ext = (4.0 * m["neff"] - coarse["neff"]) / 3.0
            row.update({"neff_coarse": coarse["neff"].real, "neff": ext.real, "kappa": ext.imag, "loss_db_per_m": float(20 / math.log(10) * 2 * math.pi / lam * ext.imag * 1e6)})
        out_modes.append(row)
    best = max(range(len(out_modes)), key=lambda i: out_modes[i]["core_fraction"]) if out_modes else None
    # field of the most core-localised mode and the index map, on the full plane (mirrored), at most 161 x 161
    fields = None
    if best is not None:
        I = np.abs(ms[best]["_Ex"]) ** 2 + np.abs(ms[best]["_Ey"]) ** 2
        n_map = np.sqrt(np.abs(mesh["eps_z"]))
        xs = mesh["x"]
        if sym:
            I = np.concatenate([I[:0:-1], I], axis=0)
            I = np.concatenate([I[:, :0:-1], I], axis=1)
            n_map = np.concatenate([n_map[:0:-1], n_map], axis=0)
            n_map = np.concatenate([n_map[:, :0:-1], n_map], axis=1)
            xs = np.concatenate([-xs[:0:-1], xs])
        keep = np.abs(xs) <= half
        I, n_map, xs = I[np.ix_(keep, keep)], n_map[np.ix_(keep, keep)], xs[keep]
        step = max(1, int(math.ceil(len(xs) / 161)))
        I, n_map, xs = I[::step, ::step], n_map[::step, ::step], xs[::step]
        fields = {"x_um": xs.tolist(), "intensity": (I / I.max()).T.tolist(), "index": n_map.T.tolist()}
    notes = []
    if not symmetric:
        notes.append("The structure is not symmetric about both axes: the full window was solved (slower)")
    if pml <= 0:
        notes.append("No absorbing layer: leaky modes appear lossless and the window edge reflects")
    progress(1.0)
    return {"wavelength_um": lam, "polarisation": pol if symmetric else "all", "n_guess": n_guess, "modes": out_modes, "best": best, "fields": fields,
            "mesh": {"h_um": mesh["h"], "cells": mesh["cells"], "unknowns": mesh["unknowns"], "refined": refine, "symmetry": list(sym) if sym else None},
            "notes": notes,
            "method": "Full-vector finite differences on a Yee mesh (Et eigenproblem beta^2 = P Q), averaged permittivity tensor at interfaces, "
            + ("quadrant with electric/magnetic walls, " if sym else "")
            + ("perfectly matched layer, " if pml > 0 else "")
            + ("Richardson extrapolation from meshes h and h/2" if refine else "one mesh")}


def _core_radius(cs: CrossSection, lam: float) -> float:
    nc = float(cs.index(np.array([0.0]), np.array([0.0]))[0])
    rho = math.inf
    for s in cs.shapes:
        if s.n < nc:
            rho = min(rho, math.hypot(s.x, s.y) - s.extent())
        elif s.inside(np.array([0.0]), np.array([0.0]))[0]:
            rho = min(rho, s.extent())
    return rho if math.isfinite(rho) and rho > 0 else 2.0 * lam
