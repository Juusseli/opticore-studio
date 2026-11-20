"""Design space map: many optimised designs of one specification over several lens topologies.

From a specification (focal length, F/#, half field, wavelengths, maximum length, number of elements) the
job plans candidates over the topologies

    singlet, cemented doublet, air-spaced doublet, Cooke triplet, Petzval (with field flattener), double Gauss

and glass choices from a pool (the built-in glasses unless the user gives a list). Each candidate is a
starting prescription, optimised by the normal optimiser (optimize/engine.py, local trust-region least
squares) to the specification, and measured with the normal analyses. The map is a seeded multistart over
topologies, glasses and perturbed starts; every number on it comes from the engine.

Starting prescriptions (all scaled to the focal length, EPD = f / F#):

* Singlet: Coddington best form (design.py).
* Doublets: thin-lens achromat powers phi1 = phi V1/(V1 - V2), phi2 = -phi V2/(V1 - V2) at the
  specification's wavelengths, equiconvex crown, crown in front; the air-spaced doublet opens the cemented
  interface by a small gap.
* Triplet, Petzval and double Gauss: published prescriptions normalised to f = 1 (the Geiser triplet, Kidger's
  Petzval with field flattener and the double Gauss of US 2,784,643, as in samples.py), with every crown (C) and
  flint (F) replaced by the candidate's pair.
* Variant v > 0 of a candidate perturbs the curvatures (x(1 + 0.2 u)) and air gaps (x(1 + 0.3 u)), u uniform in
  [-1, 1] from the candidate's seed.
* Then, in rounds: one common curvature factor makes the paraxial EFL exact (secant), glass centre thicknesses
  grow until every edge is at least e_min at the full-field clear aperture, air gaps until every edge clearance
  is a_min, and the image goes to the paraxial back focus.

Glass pairs: from the pool, Abbe numbers V = (n_primary - 1)/(n_shortest - n_longest) at the specification's
wavelengths; a pair (crown a, flint b) qualifies when V_b <= 0.8 V_a. Pairs are drawn without replacement with
probability proportional to 1 / s^2, s = (V_a + V_b)/(V_a - V_b) = (|phi1| + |phi2|)/phi of the thin achromat
(weaker element powers first). A singlet takes one glass of the pool, drawn uniformly.

Metrics of a finished candidate (each from the normal analysis at the UI's default settings, so an opened design
shows the same numbers):

* RMS spot radius per field: spot diagram, hexapolar density 6, centroid reference (um); the map uses the
  mean over fields and the worst field.
* MTF at the specification's frequency: diffraction MTF, 64 x 64 pupil, padding 4, (T + S)/2 per field.
* Length: paraxial total track, first surface to image (mm).
* Mass: lens elements (elements.py) from catalogue densities (g); glass cost: the sum of mass x catalogue relative
  cost over the elements (only where every glass has a relative cost).
* Distortion at the full field (primary wavelength, %).
* Tolerance sensitivity: the RSS change of the RMS spot (um) under the default precision tolerances with the
  back-focus compensator (tolerance.py, Monte Carlo off).

A candidate is feasible when its EFL is within 1 % of the target, its length is within the maximum, every glass
edge is at least 0.9 e_min, no air edge is negative and every ray of the spot diagram reaches the image.
"""

from __future__ import annotations

import math
import threading
import time
import traceback
import uuid
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .design import achromat_powers, best_form_shape_factor
from .materials import MaterialError, MaterialLibrary, builtin_materials
from .model import OpticalSystem
from .optimize.merit import OptimizationSpec
from .paraxial import paraxial_data
from .system import SystemError_, compile_system

Topology = Literal["singlet", "cemented_doublet", "air_spaced_doublet", "triplet", "petzval", "double_gauss"]
TOPOLOGIES: tuple[str, ...] = ("singlet", "cemented_doublet", "air_spaced_doublet", "triplet", "petzval", "double_gauss")
ELEMENTS = {"singlet": 1, "cemented_doublet": 2, "air_spaced_doublet": 2, "triplet": 3, "petzval": 5, "double_gauss": 6}
TITLES = {
    "singlet": "Singlet",
    "cemented_doublet": "Cemented doublet",
    "air_spaced_doublet": "Air-spaced doublet",
    "triplet": "Cooke triplet",
    "petzval": "Petzval",
    "double_gauss": "Double Gauss",
}
# optimiser evaluations per candidate
BUDGET = {"singlet": 300, "cemented_doublet": 500, "air_spaced_doublet": 700, "triplet": 1500, "petzval": 2000, "double_gauss": 2500}
FDC = [0.4861327, 0.5875618, 0.6562725]

# metric key -> (sense, unit): +1 smaller is better, -1 larger is better
METRICS = {
    "rms_spot_um": (1, "um"),
    "rms_spot_max_um": (1, "um"),
    "mtf": (-1, ""),
    "length_mm": (1, "mm"),
    "mass_g": (1, "g"),
    "glass_cost": (1, ""),
    "abs_distortion_pct": (1, "%"),
    "tolerance_rss_um": (1, "um"),
    "elements": (1, ""),
    # stock lens systems (stockdesign.py)
    "parts": (1, ""),
    "price": (1, ""),
    "merit": (1, ""),
}

# Published prescriptions as (radius, thickness, role, stop) in the units of their own focal length f_t;
# role C = crown, F = flint, A = air; radius None = flat. The last row's thickness is the image distance.
_GEISER = (  # f/4, f = 50 mm, +-20 deg (samples.geiser_triplet)
    50.0,
    [(23.713, 4.831, "C", False), (7331.288, 5.86, "A", False), (-24.456, 0.975, "F", True), (21.896, 4.822, "A", False), (86.759, 3.127, "C", False), (-20.4942, 41.2365, "A", False)],
)
_PETZVAL = (  # f/2.4, f = 100.8 mm, +-9 deg (samples.petzval_kidger)
    100.8,
    [
        (98.45049, 13.0, "C", False),
        (-83.29386, 4.0, "F", False),
        (-1421.38828, 40.0, "A", False),
        (None, 40.0, "A", True),
        (59.00613, 12.0, "C", False),
        (-54.3647, 3.0, "F", False),
        (-549.36547, 46.8221, "A", False),
        (-39.80076, 2.0, "F", False),
        (None, 1.9548, "A", False),
    ],
)
_DOUBLE_GAUSS = (  # f/1.7, f = 100.2 mm, +-19 deg (samples.double_gauss)
    100.2,
    [
        (75.05, 9.0, "C", False),
        (270.7, 0.1, "A", False),
        (39.27, 16.51, "C", False),
        (None, 2.0, "F", False),
        (25.65, 10.99, "A", False),
        (None, 13.0, "A", True),
        (-31.87, 7.03, "F", False),
        (None, 8.98, "C", False),
        (-43.51, 0.1, "A", False),
        (221.14, 7.98, "C", False),
        (-88.79, 61.418, "A", False),
    ],
)
TEMPLATES = {"triplet": _GEISER, "petzval": _PETZVAL, "double_gauss": _DOUBLE_GAUSS}


class DesignSpaceError(ValueError):
    pass


class DesignSpaceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    focal_length: float = Field(default=100.0, gt=0.0, le=10000.0, description="mm")
    f_number: float = Field(default=5.0, ge=0.7, le=100.0)
    half_field_deg: float = Field(default=2.0, ge=0.0, le=40.0)
    wavelengths: list[float] = Field(default_factory=lambda: list(FDC), min_length=1, max_length=12, description="um")
    primary: int = Field(default=1, ge=0)
    max_length: float | None = Field(default=None, gt=0.0, description="mm, first surface to image (None = no limit)")
    max_elements: int = Field(default=6, ge=1, le=6)
    topologies: list[Topology] = Field(default_factory=lambda: list(TOPOLOGIES), min_length=1)
    candidates: int = Field(default=120, ge=1, le=600)
    glasses: list[str] | None = Field(default=None, description="glass pool (None = the built-in glasses)")
    mtf_frequency: float = Field(default=30.0, gt=0.0, description="cycles/mm")
    tolerances: bool = Field(default=True, description="compute the tolerance sensitivity (RSS) of every candidate")
    seed: int = 1

    @model_validator(mode="after")
    def _check(self):
        if not self.primary < len(self.wavelengths):
            raise ValueError("primary must index a wavelength")
        if any(not (0.2 <= w <= 20.0) for w in self.wavelengths):
            raise ValueError("wavelengths must be 0.2 ... 20 um")
        return self


# ---------------------------------------------------------------------------------------------- glasses
def glass_table(spec: DesignSpaceSpec, custom_materials=()) -> list[dict]:
    """The glass pool with each glass's index at the primary wavelength, Abbe number at the specification's
    wavelengths (catalogue nd/Vd for a single wavelength), density and relative cost."""
    lib = MaterialLibrary(list(custom_materials))
    if spec.glasses is None:
        names = [m.name for m in builtin_materials().values() if m.category == "glass"]
    else:
        names = list(dict.fromkeys(g.strip().upper() for g in spec.glasses if g.strip()))
    lp = spec.wavelengths[spec.primary]
    ls, ll = min(spec.wavelengths), max(spec.wavelengths)
    out, missing, outside = [], [], []
    for nm in names:
        try:
            m = lib.get(nm)
        except MaterialError:
            missing.append(nm)
            continue
        d = m.dispersion
        if ls < d.lambda_min - 1e-9 or ll > d.lambda_max + 1e-9:
            outside.append(nm)
            continue
        try:
            n = m.index(lp)
            v = (n - 1.0) / (m.index(ls) - m.index(ll)) if ll > ls else m.vd_ref
        except (MaterialError, ValueError, ArithmeticError, ZeroDivisionError):
            outside.append(nm)
            continue
        if v is None or not (math.isfinite(n) and math.isfinite(v)) or n <= 1.0 or v <= 0.0:
            outside.append(nm)
            continue
        out.append({"name": m.name, "n": float(n), "V": float(v), "density": m.extra.get("density"), "relative_cost": m.extra.get("relative_cost")})
    if missing:
        raise DesignSpaceError(f"Unknown glasses: {', '.join(missing)}")
    if not out:
        raise DesignSpaceError("No glass of the pool covers the wavelengths" + (f" ({', '.join(outside)} do not)" if outside else ""))
    return out


def glass_pairs(table: list[dict], rng: np.random.Generator) -> list[tuple[str, str]]:
    """Crown/flint pairs (V_flint <= 0.8 V_crown) drawn without replacement, weight 1/s^2 (module docstring)."""
    pairs, w = [], []
    for a in table:
        for b in table:
            if a["name"] != b["name"] and b["V"] <= 0.8 * a["V"]:
                s = (a["V"] + b["V"]) / (a["V"] - b["V"])
                pairs.append((a["name"], b["name"]))
                w.append(1.0 / (s * s))
    if not pairs:
        return []
    p = np.array(w) / np.sum(w)
    order = rng.choice(len(pairs), size=len(pairs), replace=False, p=p)
    return [pairs[k] for k in order]


# ---------------------------------------------------------------------------------------------- planning
def plan(spec: DesignSpaceSpec, custom_materials=()) -> list[dict]:
    """Candidate list: topologies share the count evenly; each cycles through its glass choices, then repeats
    them as perturbed variants. Deterministic for a seed."""
    topos = [t for t in TOPOLOGIES if t in spec.topologies and ELEMENTS[t] <= spec.max_elements]
    if not topos:
        raise DesignSpaceError("No topology has at most the given number of elements")
    table = glass_table(spec, custom_materials)
    choices: dict[str, list[tuple[str, ...]]] = {}
    for t in topos:
        rng = np.random.default_rng([spec.seed, TOPOLOGIES.index(t)])
        if t == "singlet":
            choices[t] = [(table[k]["name"],) for k in rng.permutation(len(table))]
        else:
            choices[t] = glass_pairs(table, rng)
    topos = [t for t in topos if choices[t]]
    if not topos:
        raise DesignSpaceError("The glass pool has no crown/flint pair (a flint needs at most 0.8 times the crown's Abbe number)")
    base, extra = divmod(spec.candidates, len(topos))
    tasks = []
    for ti, t in enumerate(topos):
        combos = choices[t]
        for k in range(base + (1 if ti < extra else 0)):
            tasks.append({"index": len(tasks), "topology": t, "glasses": list(combos[k % len(combos)]), "variant": k // len(combos), "seed": [spec.seed, TOPOLOGIES.index(t), k]})
    return tasks


def submission_order(tasks: list[dict]) -> list[dict]:
    """Round robin over the topologies (the plan lists them one after the other)."""
    by: dict[str, list[dict]] = {}
    for t in tasks:
        by.setdefault(t["topology"], []).append(t)
    out, k = [], 0
    while len(out) < len(tasks):
        for lst in by.values():
            if k < len(lst):
                out.append(lst[k])
        k += 1
    return out


# ---------------------------------------------------------------------------------------------- starting designs
def _limits(spec: DesignSpaceSpec) -> tuple[float, float, float]:
    """Minimum glass edge e_min, minimum centre thickness t_min and minimum air edge a_min (mm)."""
    f, epd = spec.focal_length, spec.focal_length / spec.f_number
    e_min = max(0.3, 0.04 * epd, 0.01 * f)
    return e_min, e_min, max(0.05, 0.002 * f)


def _rows(topology: str, glasses: list[str], spec: DesignSpaceSpec, lib: MaterialLibrary) -> list[list]:
    """Starting rows [curvature (1/mm), thickness (mm), material, stop] before thickening and EFL scaling."""
    f = spec.focal_length
    phi = 1.0 / f
    lp = spec.wavelengths[spec.primary]
    ls, ll = min(spec.wavelengths), max(spec.wavelengths)
    e_min, t_min, a_min = _limits(spec)
    if topology == "singlet":
        g = glasses[0]
        n = lib.index(g, lp)
        q = best_form_shape_factor(n)
        return [[phi * (q + 1.0) / (2.0 * (n - 1.0)), t_min, g, True], [phi * (q - 1.0) / (2.0 * (n - 1.0)), f, "AIR", False]]
    if topology in ("cemented_doublet", "air_spaced_doublet"):
        a, b = glasses
        na, nb = lib.index(a, lp), lib.index(b, lp)
        if ll > ls:
            va = (na - 1.0) / (lib.index(a, ls) - lib.index(a, ll))
            vb = (nb - 1.0) / (lib.index(b, ls) - lib.index(b, ll))
        else:
            va, vb = lib.get(a).vd_ref or 60.0, lib.get(b).vd_ref or 35.0
        p1, p2 = achromat_powers(phi, va, vb)
        c1 = p1 / (2.0 * (na - 1.0))
        c2 = -c1
        c3 = c2 - p2 / (nb - 1.0)
        if topology == "cemented_doublet":
            return [[c1, t_min, a, True], [c2, t_min, b, False], [c3, f, "AIR", False]]
        return [[c1, t_min, a, True], [c2, max(a_min, 0.005 * f), "AIR", False], [c2, t_min, b, False], [c3, f, "AIR", False]]
    ft, rows = TEMPLATES[topology]
    role = {"C": glasses[0], "F": glasses[1], "A": "AIR"}
    k = f / ft
    return [[(1.0 / (r * k)) if r is not None else 0.0, t * k, role[m], stop] for r, t, m, stop in rows]


def _system(rows: list[list], spec: DesignSpaceSpec, name: str) -> OpticalSystem:
    hf = spec.half_field_deg
    fields = [0.0] if hf == 0 else [0.0, round(0.7 * hf, 6), hf]
    surfaces = [{"id": "obj", "label": "Object", "thickness": None}]
    lens = 0
    for k, (c, t, m, stop) in enumerate(rows):
        glass_before = k > 0 and rows[k - 1][2] != "AIR"
        if m != "AIR" and not glass_before:
            lens += 1
            label = f"L{lens} front"
        elif m != "AIR":
            label = f"L{lens} | L{lens + 1}"
            lens += 1
        elif glass_before:
            label = f"L{lens} back"
        else:
            label = "Stop" if stop else "Surface"
        surfaces.append({"id": f"s{k + 1}", "label": label, "radius": (1.0 / c) if c != 0.0 else None, "thickness": t, "material": m, "is_stop": bool(stop)})
    surfaces.append({"id": "img", "label": "Image"})
    return OpticalSystem.model_validate(
        {
            "name": name,
            "surfaces": surfaces,
            "wavelengths": [{"value": w, "weight": 1.0} for w in spec.wavelengths],
            "primary_wavelength": spec.primary,
            "fields": [{"y": y} for y in fields],
            "field_type": "angle",
            "aperture": {"type": "epd", "value": spec.focal_length / spec.f_number},
        }
    )


def _is_lens_surface(rows: list[list], k: int) -> bool:
    return rows[k][2] != "AIR" or (k > 0 and rows[k - 1][2] != "AIR")


def start_design(topology: str, glasses: list[str], variant: int, seed, spec: DesignSpaceSpec, custom_materials=(), name: str = "Candidate") -> OpticalSystem:
    """Starting prescription of one candidate: thin-lens or template rows, perturbed for variant > 0, then
    thickened and scaled to the focal length (module docstring)."""
    from .analysis.evaluate import auto_semi_diameters, edge_thickness, effective_semi_diameters
    from .paraxial import compute_pupil

    custom = list(custom_materials)
    lib = MaterialLibrary(custom)
    rows = _rows(topology, glasses, spec, lib)
    if variant > 0:
        rng = np.random.default_rng(seed)
        for k, r in enumerate(rows):
            r[0] *= 1.0 + 0.2 * rng.uniform(-1.0, 1.0)
            if r[2] == "AIR" and k < len(rows) - 1:
                r[1] *= 1.0 + 0.3 * rng.uniform(-1.0, 1.0)
    f = spec.focal_length
    e_min, t_min, a_min = _limits(spec)
    prim = spec.primary

    def efl(scale: float) -> float:
        rr = [[c * scale, t, m, s] for c, t, m, s in rows]
        pd = paraxial_data(compile_system(_system(rr, spec, name), custom), prim)
        if pd.efl is None or not math.isfinite(pd.efl) or pd.efl == 0.0:
            raise DesignSpaceError("afocal start")
        return pd.efl

    def solve_scale(s: float) -> float:
        s0, s1 = s, s * 1.001
        g0 = 1.0 / efl(s0) - 1.0 / f
        for _ in range(40):
            g1 = 1.0 / efl(s1) - 1.0 / f
            if abs(g1) <= 1e-13 / f or g1 == g0:
                break
            s0, s1, g0 = s1, s1 - g1 * (s1 - s0) / (g1 - g0), g1
        return s1

    for _ in range(8):
        s = solve_scale(1.0)
        for r in rows:
            r[0] *= s
        sys_ = _system(rows, spec, name)
        cs = compile_system(sys_, custom)
        pd = paraxial_data(cs, prim)
        if pd.bfl is not None and math.isfinite(pd.bfl) and pd.bfl > 0:
            rows[-1][1] = pd.bfl
            cs = compile_system(_system(rows, spec, name), custom)
        sd = effective_semi_diameters(cs, auto_semi_diameters(cs, compute_pupil(cs)))
        if not np.all(np.isfinite(sd)):
            raise DesignSpaceError("rays fail in the starting design")
        changed = False
        for k in range(len(rows) - 1):
            i = k + 1  # surface index
            h = float(max(sd[i], sd[i + 1]))
            if rows[k][2] != "AIR":
                e = edge_thickness(cs, i, h)
                need = max(e_min - e, t_min - rows[k][1])
                if need > 1e-6:
                    rows[k][1] += need
                    changed = True
            elif _is_lens_surface(rows, k + 1) or _is_lens_surface(rows, k):
                e = edge_thickness(cs, i, h)
                need = max(a_min - e, -rows[k][1])
                if need > 1e-6:
                    rows[k][1] += need
                    changed = True
        if not changed:
            break
    return _system(rows, spec, name)


def optimisation_spec(system: OpticalSystem, topology: str, spec: DesignSpaceSpec) -> OptimizationSpec:
    """Variables (lens curvatures, glass and air thicknesses, image distance) and operands (RMS spot, EFL, edge
    thicknesses, maximum length) of one candidate."""
    f = spec.focal_length
    e_min, t_min, a_min = _limits(spec)
    surfs = system.surfaces[1:-1]
    rows = [[0.0 if s.radius is None else 1.0 / s.radius, s.thickness, s.material.upper(), s.is_stop] for s in surfs]
    variables, operands = [], [{"type": "rms_spot", "target": 0.0, "weight": 1.0, "rings": 4}, {"type": "efl", "target": f, "weight": 1.0}]
    n = len(rows)
    for k, s in enumerate(surfs):
        c, t = rows[k][0], float(s.thickness or 0.0)
        if _is_lens_surface(rows, k):
            cmax = max(10.0 / f, 2.0 * abs(c))
            variables.append({"surface_id": s.id, "parameter": "curvature", "min": -cmax, "max": cmax})
        if k == n - 1:
            variables.append({"surface_id": s.id, "parameter": "thickness", "min": max(0.01 * t, 0.02), "max": max(3.0 * t, 0.5 * f)})
        elif rows[k][2] != "AIR":
            variables.append({"surface_id": s.id, "parameter": "thickness", "min": t_min, "max": max(3.0 * t, t + 0.1 * f)})
            operands.append({"type": "min_edge_thickness", "surface_id": s.id, "target": e_min, "weight": 1.0})
        else:
            variables.append({"surface_id": s.id, "parameter": "thickness", "min": 0.0, "max": max(3.0 * t, 0.3 * f)})
            operands.append({"type": "min_edge_thickness", "surface_id": s.id, "target": a_min, "weight": 1.0})
    if spec.max_length is not None:
        operands.append({"type": "max_total_track", "target": spec.max_length, "weight": 1.0})
    return OptimizationSpec.model_validate({"variables": variables, "operands": operands, "algorithm": "local", "max_evaluations": BUDGET[topology]})


# ---------------------------------------------------------------------------------------------- metrics
def metrics(system: OpticalSystem, custom_materials=(), spec: DesignSpaceSpec | None = None, cancel=None) -> dict:
    """The map's numbers for one design, each from the normal analysis (module docstring)."""
    from .analysis.aberrations import field_curvature_distortion
    from .analysis.diffraction import mtf
    from .analysis.elements import elements
    from .analysis.spot import spot_diagram

    spec = spec or DesignSpaceSpec()
    custom = list(custom_materials)
    cs = compile_system(system, custom)
    prim = system.primary_wavelength
    pd = paraxial_data(cs, prim)
    sp = spot_diagram(cs)
    rms = [float(fl["rms_radius_um"]) for fl in sp["fields"]]
    ray_ok = all(w["n_ok"] == w["n_rays"] for fl in sp["fields"] for w in fl["per_wavelength"])
    failed = (SystemError_, ValueError, ArithmeticError)
    try:
        m = mtf(cs, max_frequency=spec.mtf_frequency, samples=2, grid=64, pad=4)
        mtf_f = [0.5 * (fl["tangential"][-1] + fl["sagittal"][-1]) for fl in m["fields"]]
    except failed:  # e.g. a chief ray that fails: no wavefront reference
        mtf_f = None
    dist = None
    if max(math.hypot(fl.x, fl.y) for fl in cs.model.fields) > 0:  # any off-axis field, along x as well as y
        fc = field_curvature_distortion(cs, samples=2, wavelengths=[prim])
        dist = fc["per_wavelength"][0]["distortion_percent"][-1]
    el = elements(system, custom)
    mass = el["total_mass_g"]
    cost = el["relative_cost"] * mass if (el["relative_cost"] is not None and mass is not None) else None
    rss = None
    if spec.tolerances:
        from .tolerance import TolControl, ToleranceError, analyze, default_spec

        ctl = TolControl()
        if cancel is not None:
            ctl.cancel = cancel
        tspec = default_spec(system, "precision", custom).model_copy(update={"monte_carlo_trials": 0})
        try:
            tr = analyze(system, tspec, custom, control=ctl)
        except (ToleranceError, *failed):
            tr = {"status": "failed"}
        if tr["status"] == "cancelled":
            raise _Stopped()
        rss = float(tr["rss_change"]) if tr["status"] == "finished" else None
    return {
        "rms_spot_um": float(np.mean(rms)),
        "rms_spot_max_um": float(np.max(rms)),
        "rms_spot_fields_um": rms,
        "mtf": float(np.mean(mtf_f)) if mtf_f is not None else None,
        "mtf_fields": [float(v) for v in mtf_f] if mtf_f is not None else None,
        "length_mm": float(pd.total_track),
        "mass_g": mass,
        "glass_cost": cost,
        "distortion_pct": dist,
        "abs_distortion_pct": abs(dist) if dist is not None else None,
        "tolerance_rss_um": rss,
        "elements": len(el["elements"]),
        "efl_mm": pd.efl,
        "fnum": pd.image_space_fnum,
        "airy_radius_um": sp["airy_radius_um"],
        "rays_ok": ray_ok,
    }


def violations(system: OpticalSystem, m: dict, spec: DesignSpaceSpec, custom_materials=()) -> list[dict]:
    """Specification checks of a finished candidate (module docstring); empty = feasible."""
    from .analysis.evaluate import auto_semi_diameters, edge_thickness, effective_semi_diameters
    from .paraxial import compute_pupil

    out = []
    f = spec.focal_length
    if m["efl_mm"] is None or abs(m["efl_mm"] - f) > 0.01 * f:
        out.append({"kind": "efl", "value": m["efl_mm"], "limit": f})
    if spec.max_length is not None and m["length_mm"] > spec.max_length * (1 + 1e-3):
        out.append({"kind": "length", "value": m["length_mm"], "limit": spec.max_length})
    if not m["rays_ok"]:
        out.append({"kind": "rays", "value": None, "limit": None})
    e_min, _, _ = _limits(spec)
    cs = compile_system(system, list(custom_materials))
    sd = effective_semi_diameters(cs, auto_semi_diameters(cs, compute_pupil(cs)))
    surfs = system.surfaces
    worst_glass, worst_air = math.inf, math.inf
    for i in range(1, len(surfs) - 2):
        glass = surfs[i].material.upper() not in ("AIR", "")
        e = edge_thickness(cs, i, float(max(sd[i], sd[i + 1])))
        if glass:
            worst_glass = min(worst_glass, e)
        else:
            worst_air = min(worst_air, e)
    if worst_glass < 0.9 * e_min:
        out.append({"kind": "edge", "value": worst_glass, "limit": e_min})
    if worst_air < -1e-6:
        out.append({"kind": "collision", "value": worst_air, "limit": 0.0})
    return out


# ---------------------------------------------------------------------------------------------- one candidate
class _Stopped(Exception):
    pass


def title(task: dict) -> str:
    g = "/".join(task["glasses"])
    return f"{TITLES[task['topology']]} {g}" + (f" (start {task['variant'] + 1})" if task["variant"] else "")


def run_candidate(task: dict, spec_json: dict, custom_materials: list, slot: int | None = None) -> dict:
    """Build, optimise and measure one candidate (runs in a worker process; also callable directly)."""
    from .analysis.outline import system_outline
    from .jsonutil import jsonable
    from .optimize.engine import Control, optimize

    t0 = time.time()
    spec = DesignSpaceSpec.model_validate(spec_json)
    cancel = None
    if slot is not None:
        from .workers import flag

        cancel = flag(slot)
    base = {"index": task["index"], "topology": task["topology"], "glasses": task["glasses"], "variant": task["variant"], "title": title(task)}
    if cancel is not None and cancel.is_set():
        return {**base, "status": "cancelled"}
    try:
        start = start_design(task["topology"], task["glasses"], task["variant"], task["seed"], spec, custom_materials, name=title(task))
        ospec = optimisation_spec(start, task["topology"], spec)
        ctl = Control()
        if cancel is not None:
            ctl.cancel = cancel
        res = optimize(start, ospec, custom_materials, control=ctl)
        if res["status"] == "cancelled":
            return {**base, "status": "cancelled"}
        system = OpticalSystem.model_validate(res["system"])
        m = metrics(system, custom_materials, spec, cancel)
        v = violations(system, m, spec, custom_materials)
        outline = system_outline(compile_system(system, list(custom_materials)))
    except _Stopped:
        return {**base, "status": "cancelled"}
    except (DesignSpaceError, SystemError_, MaterialError, ValueError, ArithmeticError) as exc:
        return {**base, "status": "failed", "error": f"{type(exc).__name__}: {exc}", "elapsed_s": time.time() - t0}
    return jsonable(
        {
            **base,
            "status": "finished",
            "feasible": not v,
            "violations": v,
            "metrics": m,
            "merit": res["final_merit"],
            "initial_merit": res["initial_merit"],
            "evaluations": res["evaluations"],
            "optimiser_status": res["status"],
            "system": system.model_dump(mode="json"),
            "optimization": ospec.model_dump(mode="json"),
            "outline": outline,
            "elapsed_s": time.time() - t0,
        }
    )


# ---------------------------------------------------------------------------------------------- Pareto front
def pareto_front(points: list[dict | None], objectives: list[str]) -> list[int]:
    """Indices of the exact non-dominated set: a point is dominated when another is at least as good in every
    objective and better in one (senses from METRICS). Points without a finite value of every objective are
    left out."""
    for o in objectives:
        if o not in METRICS:
            raise DesignSpaceError(f"Unknown objective '{o}'")
    idx, vals = [], []
    for k, p in enumerate(points):
        if p is None:
            continue
        v = [p.get(o) for o in objectives]
        if any(x is None or not math.isfinite(float(x)) for x in v):
            continue
        idx.append(k)
        vals.append([METRICS[o][0] * float(x) for o, x in zip(objectives, v)])
    if not idx:
        return []
    a = np.array(vals)
    front = []
    for i in range(len(idx)):
        le = np.all(a <= a[i], axis=1)
        lt = np.any(a < a[i], axis=1)
        if not np.any(le & lt):
            front.append(idx[i])
    return front


def default_objectives(candidates: list[dict]) -> list[str]:
    """Performance, length and cost. Lens forms: the glass cost when every feasible candidate has one, else the
    mass. Stock lenses: the summed part price when every feasible candidate has one, else the number of parts."""
    done = [c for c in candidates if c.get("status") == "finished" and c.get("feasible")]
    if done and all("parts" in c["metrics"] for c in done):
        cost = "price" if all(c["metrics"].get("price") is not None for c in done) else "parts"
        return ["rms_spot_um", "length_mm", cost]
    cost = "glass_cost" if done and all(c["metrics"].get("glass_cost") is not None for c in done) else "mass_g"
    return ["rms_spot_um", "length_mm", cost]


# ---------------------------------------------------------------------------------------------- jobs
class DesignSpaceJobs:
    """Design space runs: candidates go to the shared process pool (workers.py); results arrive as they finish,
    are kept by plan index, and survive a cancel. A run that nobody polls for `abandon_s` seconds (the page was
    closed) is cancelled.

    A job is the lens-form map (the default runner) or any runner(job, pool, flag) that submits work with
    `gather` and stores candidates with `store` (the stock lens builds of stockdesign.py run a prescreen phase
    first)."""

    ABANDON_S = 60.0  # a running job nobody has polled for this long is cancelled

    def __init__(self, max_jobs: int = 8, abandon_s: float = ABANDON_S):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.max_jobs = max_jobs
        self.abandon_s = abandon_s

    def start(self, spec, custom_materials=(), runner=None, total: int = 0, topologies: list[str] | None = None, describe=None) -> dict:
        custom = list(custom_materials)
        if runner is None:  # the lens-form map
            tasks = plan(spec, custom)  # configuration errors are raised here (synchronously)
            total = len(tasks)
            topologies = sorted({t["topology"] for t in tasks}, key=TOPOLOGIES.index)

            def runner(job, pool, fl):
                sj = spec.model_dump(mode="json")
                # topologies interleaved: early results of every kind, and the long ones do not all queue at the end
                futures = {pool.submit(run_candidate, t, sj, custom, fl.slot): t["index"] for t in submission_order(tasks)}
                self.gather(job, futures, lambda k, r: self.store(job, k, r))

        job = {
            "id": uuid.uuid4().hex[:16],
            "state": "running",
            "spec": spec,
            "custom": custom,
            "total": total,
            "topologies": topologies or [],
            "describe": describe,
            "results": {},  # plan index -> candidate
            "order": [],  # plan indices in completion order
            "failed": 0,
            "phase": None,  # a runner's phase before its candidates (e.g. "prescreen")
            "phase_done": 0,
            "phase_total": 0,
            "notes": [],
            "error": None,
            "created": time.time(),
            "polled": time.time(),
            "abandoned": False,
            "broken": False,
            "finished": None,
            "flag": None,
            "futures": {},
            "cancel": threading.Event(),
        }

        def run():
            from . import workers

            try:
                pool, fl = workers.acquire()
                job["flag"] = fl
                if job["cancel"].is_set():
                    fl.set()
                runner(job, pool, fl)
                job["state"] = "cancelled" if job["cancel"].is_set() else "finished"
            except Exception as exc:  # reported to the client
                job["error"] = f"{type(exc).__name__}: {exc}"
                job["state"] = "failed"
                traceback.print_exc()
            finally:
                job["phase"] = None
                job["finished"] = time.time()
                if job["flag"] is not None:
                    workers.release(job["flag"], broken=job["broken"])

        with self._lock:
            done = sorted((j for j in self._jobs.values() if j["state"] != "running"), key=lambda j: j["created"])
            for j in done[: max(0, len(self._jobs) - self.max_jobs + 1)]:
                self._jobs.pop(j["id"], None)
            self._jobs[job["id"]] = job
        threading.Thread(target=run, daemon=True, name=f"ds-{job['id']}").start()
        return job

    def gather(self, job: dict, futures: dict, handle) -> None:
        """Wait for the futures ({future: key}) and pass each result (or failure record) to handle(key, result);
        cancel an abandoned job. A broken pool is raised (the job fails, the pool is replaced)."""
        import concurrent.futures as cf

        job["futures"] = futures
        pending = set(futures)
        while pending:
            done, pending = cf.wait(pending, timeout=1.0, return_when=cf.FIRST_COMPLETED)
            for fut in done:
                k = futures[fut]
                try:
                    r = fut.result()
                except cf.CancelledError:
                    continue
                except cf.process.BrokenProcessPool:
                    job["broken"] = True
                    raise
                except Exception as exc:  # a worker error is that task's failure
                    r = {"index": k, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                handle(k, r)
            # nobody is watching (the page was closed or reloaded): stop instead of occupying every core
            if not job["cancel"].is_set() and time.time() - job["polled"] > self.abandon_s:
                job["abandoned"] = True
                self.cancel(job["id"])

    @staticmethod
    def store(job: dict, k: int, r: dict) -> None:
        """Keep a finished (or failed) candidate; a cancelled one is dropped."""
        if r.get("status") == "cancelled":
            return
        if r.get("status") == "failed":
            job["failed"] += 1
        job["results"][k] = r
        job["order"].append(k)

    def get(self, job_id: str) -> dict | None:
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job:
            return False
        job["cancel"].set()
        if job["flag"] is not None:
            job["flag"].set()
        for fut in list(job.get("futures", {})):
            fut.cancel()
        return True

    def snapshot(self, job: dict, since: int = 0, objectives: list[str] | None = None) -> dict:
        """Progress, the candidates finished after the first `since` (completion order, without their full
        prescriptions) and the Pareto front of all finished feasible candidates."""
        job["polled"] = time.time()
        order = list(job["order"])
        results = dict(job["results"])
        finished = [results[k] for k in order if results[k].get("status") == "finished"]
        objectives = objectives or default_objectives(finished)
        n = max([job["total"], *[k + 1 for k in results]])
        pts: list[dict | None] = [None] * n
        for k, c in results.items():
            if c.get("status") == "finished" and c.get("feasible"):
                pts[k] = c["metrics"]
        light = [{key: v for key, v in results[k].items() if key not in ("system", "optimization")} for k in order[since:]]
        end = job["finished"] or time.time()
        return {
            "id": job["id"],
            "state": job["state"],
            "total": job["total"],
            "done": len(order),
            "failed": job["failed"],
            "phase": job["phase"],
            "phase_done": job["phase_done"],
            "phase_total": job["phase_total"],
            "notes": list(job["notes"]),
            "elapsed_s": end - job["created"],
            "error": job["error"],
            "abandoned": job["abandoned"],
            "since": since,
            "candidates": light,
            "objectives": objectives,
            "pareto": pareto_front(pts, objectives),
            "topologies": list(job["topologies"]),
            "metrics": {k: {"sense": s, "unit": u} for k, (s, u) in METRICS.items()},
        }

    def candidate(self, job: dict, index: int) -> dict | None:
        """One finished candidate as a project to open (prescription, its optimisation set-up, used custom glasses)."""
        c = job["results"].get(index)
        if not c or c.get("status") != "finished":
            return None
        used = {s["material"].upper() for s in c["system"]["surfaces"] if s.get("material")}
        if job["describe"] is not None:
            desc = job["describe"](job, index, c)
        elif not isinstance(job["spec"], DesignSpaceSpec):
            desc = f"Candidate {index + 1} of {job['total']}: {c['title']}."
        else:
            spec: DesignSpaceSpec = job["spec"]
            desc = (
                f"Design space candidate {index + 1} of {job['total']}: {c['title']}, optimised for f = {spec.focal_length:g} mm, F/{spec.f_number:g}, "
                f"half field {spec.half_field_deg:g} deg (seed {spec.seed})."
            )
        project = {
            "metadata": {"name": c["title"], "description": desc},
            "system": c["system"],
            "optimization": c["optimization"],
            "custom_materials": [r for r in job["custom"] if str(r.get("name", "")).upper() in used],
        }
        return {"index": index, "title": c["title"], "metrics": c["metrics"], "project": project}
