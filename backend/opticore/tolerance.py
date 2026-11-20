"""Tolerance analysis: sensitivities, RSS estimate, Monte Carlo, yield and allocation.

Each tolerance perturbs the nominal system by a signed amount within
[min, max]:

  radius            R -> R + d (mm; curved surfaces only)
  thickness         t -> t + d (mm)
  conic             k -> k + d
  index             n(lambda) -> n(lambda) + d for the medium that starts at
                    the surface (all wavelengths; dispersion unchanged)
  abbe              Vd -> Vd + d at constant nd for the medium that starts at
                    the surface: n(lambda) -> n(lambda) + kappa (n(lambda) - nd),
                    kappa = -d / (Vd + d) (exact for nd, nF - nC and Vd)
  power             sagitta (power) error in fringes over the clear aperture
                    (ISO 10110-5 A): the base curvature changes so that the sag
                    at the clear-aperture radius changes by d * lambda_t / 2
  irregularity      astigmatic irregularity in fringes peak-to-valley (ISO
                    10110-5 B): Fringe Zernike Z5/Z6 sag, orientation 0 deg in
                    the sensitivity run and uniformly random in Monte Carlo
  irregularity_rotational
                    rotationally symmetric irregularity in fringes PV (ISO
                    10110-5 C): Fringe Z9 sag referenced to the vertex
  zernike_form      one Fringe Zernike sag term (Z5..Z37), coefficient in um
  surface_*         decenter (mm) / tilt (deg) of one surface about its vertex
  element_*         decenter (mm) / tilt (deg) of a group of surfaces (lens
                    or cemented group) about the front vertex

Form errors are normalised to the clear aperture (the nominal effective
semi-diameter; a Zernike surface uses its own normalisation radius) and are
added to the surface as Zernike sag terms (a standard or even-asphere surface
becomes a Zernike surface with the same base); one fringe is half the test
wavelength lambda_t (ISO 10110-5: 546.07 nm unless stated).

Decenters and tilts are modelled exactly with coordinate-break pairs, the
same geometry as user-defined breaks. For a group a..b with internal axial
length D and following thickness t_b:

  CB(dx, dy, tx, ty; order 0, thickness 0), a, ..., b (thickness -D),
  CB(-dx, -dy, -tx, -ty; order 1, thickness D + t_b)

The return break restores the nominal axis at the nominal vertex position of
the next surface (order 1 with negated values is the exact inverse of order
0), so downstream surfaces stay where they were.

For every perturbed system the compensators (e.g. back focus) are re-solved
with bounded trust-region least squares on the same criterion, within
+-range of the value they have in the perturbed system. Automatic semi-
diameters are recomputed for every trial (no clipping change); fixed
apertures vignette as usual.

Criteria: RMS spot radius (um, centroid reference, all fields and
wavelengths, Gaussian pupil quadrature), RMS wavefront error (waves of the
primary wavelength, all fields; polychromatic like the rms_wavefront operand
without a wavelength (ADR-039): every wavelength against the primary
chief ray's reference sphere, weighted), the project merit function (lower is
better) or the diffraction MTF at one frequency (mean over the fields of the
tangential and sagittal average, polychromatic; higher is better).

Criterion "merit": the optimiser's active operands (merit.is_active) of the
active configuration (operands pinned to other configurations are left out,
with a note; the active configuration is baked into the prescription). With
exact limits (merit_constraints "exact", the optimisation's mode) the
criterion is the merit function of the goals, as in the optimiser; the
compensators minimise the goals, and the limits are reported apart (`limits`:
their nominal values, values per sensitivity side and trial, and how many
trials meet them to the optimiser's tolerance). Limits do not enter the yield.
With weighted limits ("penalty") every operand is in the criterion.

Monte Carlo draws every enabled tolerance independently: "uniform" on
[min, max], or "normal" with the mean at the centre and the limits at +-2
sigma (truncated at the limits). The RSS estimate is
nominal + sqrt(sum_i max(|D_min,i|, |D_max,i|)^2) with D the sensitivity
changes (minus for MTF); it assumes independent, linear, one-sided
degradations and is only an estimate (compare it with the Monte Carlo
statistics).

Yield: with a specification limit, the fraction of Monte Carlo trials that
meet it (failed trials count as failing), with a 95 % Wilson score interval.

Allocation (inverse sensitivity): the criterion is mapped to a quantity that
adds over independent small perturbations, Q = c^2 for the RMS criteria
(variances add) and Q = -c for MTF (losses add). The budget Q(limit) - Q(c0)
less the share of locked tolerances is split equally over the free ones, and
each free tolerance's limits are scaled (both by the same factor, 1e-3 .. 10)
until its worst-side increase of Q at the limits equals its share (secant
iteration on the real, compensated criterion, aimed 2.5 % under the share);
the new limits are rounded toward zero to 3 significant digits. With every tolerance at its
limit the quadrature sum then meets the specification; the Monte Carlo run
that follows uses the allocated limits and confirms the yield.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scipy.optimize import least_squares
from scipy.stats import truncnorm

from .model import OpticalSystem, new_id
from .optimize.engine import _scale_for
from .optimize.merit import EQUALITY, MeritFunction, Operand, OptimizationSpec, Variable, VariableParam, constraint_scale, exact_constraints, is_active, operand_role, report_scale

ToleranceType = Literal[
    "radius",
    "thickness",
    "conic",
    "index",
    "abbe",
    "power",
    "irregularity",
    "irregularity_rotational",
    "zernike_form",
    "surface_decenter_x",
    "surface_decenter_y",
    "surface_tilt_x",
    "surface_tilt_y",
    "element_decenter_x",
    "element_decenter_y",
    "element_tilt_x",
    "element_tilt_y",
]

TOLERANCE_UNITS: dict[str, str] = {
    "radius": "mm",
    "thickness": "mm",
    "conic": "",
    "index": "",
    "abbe": "",
    "power": "fringes",
    "irregularity": "fringes",
    "irregularity_rotational": "fringes",
    "zernike_form": "um",
    "surface_decenter_x": "mm",
    "surface_decenter_y": "mm",
    "surface_tilt_x": "deg",
    "surface_tilt_y": "deg",
    "element_decenter_x": "mm",
    "element_decenter_y": "mm",
    "element_tilt_x": "deg",
    "element_tilt_y": "deg",
}

_CB_KEY = {"decenter_x": "decenter_x", "decenter_y": "decenter_y", "tilt_x": "tilt_x", "tilt_y": "tilt_y"}

FORM_TYPES = ("power", "irregularity", "irregularity_rotational", "zernike_form")
FORM_SURFACES = ("standard", "even_asphere", "zernike")
GLASS_TYPES = ("index", "abbe")
GASES = ("AIR", "VACUUM", "MIRROR", "")


class Tolerance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=new_id)
    type: ToleranceType
    surface_id: str
    surface_id_end: str | None = Field(default=None, description="last surface of the group (element_* only)")
    min: float
    max: float
    enabled: bool = True
    term: int | None = Field(default=None, ge=5, le=37, description="Fringe Zernike term (zernike_form only)")
    locked: bool = Field(default=False, description="kept as it is when tolerances are allocated to the specification")

    @model_validator(mode="after")
    def _check(self):
        if not (math.isfinite(self.min) and math.isfinite(self.max)) or self.min > self.max:
            raise ValueError("tolerance needs finite min <= max")
        if self.type.startswith("element_") and not self.surface_id_end:
            raise ValueError("element tolerances need surface_id_end")
        if self.type == "zernike_form" and self.term is None:
            raise ValueError("a Zernike form tolerance needs its term (Z5..Z37)")
        return self


class Compensator(BaseModel):
    model_config = ConfigDict(extra="forbid")
    surface_id: str
    parameter: VariableParam = "thickness"
    range: float = Field(default=2.0, gt=0, description="allowed change around the perturbed value")
    enabled: bool = True


class ToleranceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tolerances: list[Tolerance] = Field(default_factory=list)
    compensators: list[Compensator] = Field(default_factory=list)
    criterion: Literal["rms_spot", "rms_wavefront", "merit", "mtf"] = "rms_spot"
    rings: int = Field(default=3, ge=1, le=12)
    monte_carlo_trials: int = Field(default=50, ge=0, le=5000)
    distribution: Literal["normal", "uniform"] = "normal"
    seed: int = 1
    compensator_evaluations: int = Field(default=40, ge=4, le=1000)
    mtf_frequency: float = Field(default=30.0, gt=0.0, description="cycles/mm (criterion mtf)")
    limit: float | None = Field(default=None, description="specification: criterion <= limit (>= for MTF); yield and allocation")
    test_wavelength_um: float = Field(default=0.54607, gt=0.1, lt=20.0, description="test wavelength of the fringe tolerances (ISO 10110-5: 546.07 nm)")


CRITERION_UNITS = {"rms_spot": "um", "rms_wavefront": "waves", "merit": "", "mtf": ""}
# +1: lower is better; -1: higher is better
CRITERION_SENSE = {"rms_spot": 1, "rms_wavefront": 1, "merit": 1, "mtf": -1}
ALLOCATION_FACTORS = (1e-3, 10.0)


class ToleranceError(ValueError):
    pass


# ----------------------------------------------------------------------
# Perturbation of the prescription
# ----------------------------------------------------------------------
def _cb(**kw) -> dict:
    base = {
        "id": new_id(),
        "type": "coordinate_break",
        "label": "tol",
        "comment": "tolerance perturbation",
        "radius": None,
        "thickness": 0.0,
        "material": "AIR",
        "semi_diameter": 0.0,
        "semi_diameter_mode": "auto",
        "conic": 0.0,
        "aspheric": [],
        "is_stop": False,
        "coating": "",
        "decenter_x": 0.0,
        "decenter_y": 0.0,
        "tilt_x": 0.0,
        "tilt_y": 0.0,
        "tilt_z": 0.0,
        "cb_order": 0,
    }
    base.update(kw)
    return base


def validate_tolerances(system: OpticalSystem, tols: list[Tolerance]) -> None:
    pos = {s.id: i for i, s in enumerate(system.surfaces)}
    n = len(system.surfaces)
    for t in tols:
        if t.surface_id not in pos:
            raise ToleranceError(f"Tolerance refers to unknown surface id '{t.surface_id}'")
        i = pos[t.surface_id]
        s = system.surfaces[i]
        if i == 0 and t.type != "thickness":
            raise ToleranceError("Only the object distance can be toleranced on the object surface")
        if i == n - 1:
            raise ToleranceError("The image surface cannot be toleranced (use a back-focus compensator)")
        if s.type == "coordinate_break":
            raise ToleranceError(f"Surface {i}: coordinate breaks cannot be toleranced directly")
        if s.type == "ideal" and t.type in ("radius", "conic"):
            raise ToleranceError(f"Surface {i}: an ideal lens has no {t.type} to tolerance")
        if t.type == "radius" and s.radius is None:
            raise ToleranceError(f"Surface {i}: radius tolerance on a plane surface (no finite radius)")
        if t.type == "thickness" and s.thickness is None:
            raise ToleranceError(f"Surface {i}: infinite thickness cannot be toleranced")
        if t.type in GLASS_TYPES and s.material.upper() in GASES:
            raise ToleranceError(f"Surface {i}: {'index' if t.type == 'index' else 'Abbe number'} tolerance needs a glass medium after the surface")
        if t.type in FORM_TYPES and s.type not in FORM_SURFACES:
            raise ToleranceError(f"Surface {i}: form tolerances need a standard, even-asphere or Zernike surface (not {s.type})")
        if t.type.startswith("element_"):
            if t.surface_id_end not in pos:
                raise ToleranceError(f"Tolerance refers to unknown surface id '{t.surface_id_end}'")
            j = pos[t.surface_id_end]
            if j < i or j >= n - 1:
                raise ToleranceError(f"Element tolerance: last surface {j} must follow first surface {i} and precede the image")
            if any(system.surfaces[k].type == "coordinate_break" for k in range(i, j + 1)):
                raise ToleranceError("Element tolerance groups cannot contain coordinate breaks")
            if any(system.surfaces[k].thickness is None for k in range(i, j + 1)):
                raise ToleranceError("Element tolerance groups need finite thicknesses")


@dataclass
class Perturbed:
    system: OpticalSystem
    # index offset of each medium (by the id of the surface that starts it): dn, or (dn, dVd) with an Abbe change
    index_offsets: dict[str, float | tuple[float, float]]
    thickness_carrier: dict[str, str]  # original surface id -> id whose thickness now holds its thickness


def _base_sag(c: float, k: float, r: float) -> float:
    a = 1.0 - (1.0 + k) * c * c * r * r
    if a <= 0.0:
        raise ToleranceError("power perturbation makes the surface steeper than its clear aperture allows")
    return c * r * r / (1.0 + math.sqrt(a))


def power_curvature_change(c: float, k: float, r: float, h: float) -> float:
    """Curvature change dc of a conic base with sag(c + dc, r) - sag(c, r) = h (Newton, exact).
    d sag / dc = r^2 / (s (1 + s)), s = sqrt(1 - (1 + k) c^2 r^2)."""
    target = _base_sag(c, k, r) + h
    dc = 2.0 * h / (r * r)
    for _ in range(40):
        cc = c + dc
        s = math.sqrt(max(1e-300, 1.0 - (1.0 + k) * cc * cc * r * r))
        f = _base_sag(cc, k, r) - target
        step = f * s * (1.0 + s) / (r * r)
        dc -= step
        if abs(step) <= 1e-15 * max(abs(cc), 1.0 / r):
            break
    return dc


# PV of each irregularity shape over the unit disk: Z5 = rho^2 cos 2theta (2), Z9 - Z9(0) = 6 rho^4 - 6 rho^2 (1.5)
_PV_ASTIG = 2.0
_PV_ROT = 1.5


def perturb(system: OpticalSystem, tols: list[Tolerance], values, angles: dict[int, float] | None = None, apertures: dict[str, float] | None = None, test_wavelength_um: float = 0.54607) -> Perturbed:
    """Apply signed perturbations (one value per tolerance) to a copy of the system.

    angles: orientation (rad) of each astigmatic irregularity, by tolerance position (default 0);
    apertures: clear-aperture radius (mm) of each surface with a form tolerance."""
    d = system.model_dump()
    surfs = [dict(s) for s in d["surfaces"]]
    pos0 = {s["id"]: i for i, s in enumerate(surfs)}
    offsets: dict[str, float] = {}
    abbe: dict[str, float] = {}
    forms: dict[str, dict] = {}
    fringe = test_wavelength_um * 1e-3 / 2.0  # surface height of one fringe (mm)
    groups: dict[tuple[str, str], dict[str, float]] = {}
    for k, (t, v) in enumerate(zip(tols, values)):
        v = float(v)
        s = surfs[pos0[t.surface_id]]
        if t.type == "radius":
            r = s["radius"] + v
            if r == 0.0:
                raise ToleranceError("radius perturbation produced R = 0")
            s["radius"] = r
        elif t.type == "thickness":
            s["thickness"] = s["thickness"] + v
        elif t.type == "conic":
            s["conic"] = s["conic"] + v
        elif t.type == "index":
            offsets[t.surface_id] = offsets.get(t.surface_id, 0.0) + v
        elif t.type == "abbe":
            abbe[t.surface_id] = abbe.get(t.surface_id, 0.0) + v
        elif t.type in FORM_TYPES:
            f = forms.setdefault(t.surface_id, {"h": 0.0, "z": {}})
            z = f["z"]
            if t.type == "power":
                f["h"] += v * fringe
            elif t.type == "irregularity":
                a = v * fringe / _PV_ASTIG
                phi = (angles or {}).get(k, 0.0)
                z[5] = z.get(5, 0.0) + a * math.cos(2.0 * phi)
                z[6] = z.get(6, 0.0) + a * math.sin(2.0 * phi)
            elif t.type == "irregularity_rotational":
                z[9] = z.get(9, 0.0) + v * fringe / _PV_ROT
            else:
                z[t.term] = z.get(t.term, 0.0) + v * 1e-3
        else:
            kind, _, key = t.type.partition("_")
            end = t.surface_id if kind == "surface" else t.surface_id_end
            g = groups.setdefault((t.surface_id, end), {k: 0.0 for k in _CB_KEY})
            g[key] += v

    carrier: dict[str, str] = {}
    # groups first (outermost), then single surfaces; nested pairs compose exactly
    order = sorted(groups.items(), key=lambda kv: kv[0][0] == kv[0][1])
    for (a, b), g in order:
        if all(abs(x) == 0.0 for x in g.values()):
            continue
        pos = {s["id"]: i for i, s in enumerate(surfs)}
        ia, ib = pos[a], pos[b]
        D = float(sum(surfs[k]["thickness"] for k in range(ia, ib)))
        tb = float(surfs[ib]["thickness"])
        pre = _cb(cb_order=0, **{k: g[k] for k in _CB_KEY})
        ret = _cb(cb_order=1, thickness=D + tb, **{k: -g[k] for k in _CB_KEY})
        surfs[ib]["thickness"] = -D
        surfs.insert(ib + 1, ret)
        surfs.insert(ia, pre)
        carrier.setdefault(b, ret["id"])

    for sid, f in forms.items():
        s = next(x for x in surfs if x["id"] == sid)
        r_ap = (apertures or {}).get(sid)
        if not r_ap or r_ap <= 0.0:
            raise ToleranceError("form tolerances need the clear aperture of their surface")
        if f["h"] != 0.0:
            c = 0.0 if s["radius"] is None else 1.0 / s["radius"]
            c2 = c + power_curvature_change(c, s["conic"], r_ap, f["h"])
            s["radius"] = None if c2 == 0.0 else 1.0 / c2
        if any(a != 0.0 for a in f["z"].values()):
            if s["type"] != "zernike":
                if s["type"] == "standard":
                    s["aspheric"] = []  # a standard surface ignores leftover aspheric terms
                s["type"] = "zernike"
                s["zernike_norm_radius"] = r_ap
                s["zernike_coefficients"] = []
            co = list(s["zernike_coefficients"])
            co += [0.0] * (max(f["z"]) - len(co))
            for j, a in f["z"].items():
                co[j - 1] += a
            s["zernike_coefficients"] = co
    d["surfaces"] = surfs
    merged: dict[str, float | tuple[float, float]] = dict(offsets)
    for sid, dv in abbe.items():
        if dv != 0.0:
            merged[sid] = (offsets.get(sid, 0.0), dv)
    return Perturbed(OpticalSystem.model_validate(d), merged, carrier)


def clear_apertures(system: OpticalSystem, custom_materials=()) -> dict[str, float]:
    """Clear-aperture radius of every surface (mm): the nominal effective semi-diameter, or the
    normalisation radius of a Zernike surface. The reference of the form tolerances."""
    from .analysis.evaluate import auto_semi_diameters, effective_semi_diameters
    from .paraxial import compute_pupil
    from .system import compile_system

    cs = compile_system(system, custom_materials)
    sd = effective_semi_diameters(cs, auto_semi_diameters(cs, compute_pupil(cs), {}))
    return {s.id: (float(s.zernike_norm_radius) if s.type == "zernike" else float(sd[i])) for i, s in enumerate(system.surfaces)}


# ----------------------------------------------------------------------
# Criterion evaluation with compensation
# ----------------------------------------------------------------------
def _criterion_operands(spec: ToleranceSpec, merit_operands: list[Operand], n_fields: int = 1) -> list[Operand]:
    if spec.criterion == "rms_spot":
        return [Operand(type="rms_spot", rings=spec.rings, reference="centroid")]
    if spec.criterion == "rms_wavefront":
        # no wavelength: polychromatic in waves of the primary wavelength (ADR-039), as the operand
        return [Operand(type="rms_wavefront", rings=spec.rings)]
    if spec.criterion == "mtf":
        # one per field, target 1: the compensators maximise the MTF; the criterion is the mean value
        return [Operand(type="mtf", target=1.0, field=f, frequency=spec.mtf_frequency, direction="average") for f in range(n_fields)]
    raise ValueError("criterion 'merit' takes the merit function's operands (_merit_criterion)")


def _merit_criterion(merit_operands: list[Operand], active: int, n_configs: int, constraints: str) -> tuple[list[Operand], list[int], bool, list[str]]:
    """Criterion "merit" (module notes): (operands of the active configuration with no configuration of their own,
    their numbers among the optimiser's active operands, split into goals and limits, notes)."""
    act = [o for o in merit_operands if is_active(o)]
    if not act:
        raise ToleranceError("Criterion 'merit' needs an active merit function (Merit Function Editor)")
    keep: list[tuple[int, Operand]] = []
    for k, o in enumerate(act):
        if o.configuration is not None and o.configuration >= n_configs:
            raise ToleranceError(f"Operand {o.type} refers to configuration {o.configuration + 1}, which does not exist")
        if o.configuration is None or o.configuration == active:
            keep.append((k, o.model_copy(update={"configuration": None})))
    notes = []
    if len(keep) < len(act):
        notes.append(f"{len(act) - len(keep)} merit operand(s) of other configurations are left out: the tolerances are evaluated in the active configuration ({active + 1}).")
    if not keep:
        raise ToleranceError(f"Criterion 'merit': no operand of the merit function evaluates the active configuration ({active + 1})")
    ops = [o for _, o in keep]
    split = exact_constraints(OptimizationSpec(operands=ops, constraints=constraints))
    if split and not any(operand_role(o) == "objective" for o in ops):
        raise ToleranceError("Criterion 'merit' with exact limits needs a goal (an operand with the objective role): the limits are reported apart from the criterion")
    if not split and not any(o.weight > 0 for o in ops):
        raise ToleranceError("Criterion 'merit' with weighted limits needs an operand with a weight above 0")
    return ops, [k for k, _ in keep], split, notes


@dataclass
class Evaluator:
    system: OpticalSystem
    spec: ToleranceSpec
    custom_materials: list
    merit_operands: list[Operand] = field(default_factory=list)
    evaluations: int = 0
    ns: tuple | None = None  # (sources, detectors) for detector operands
    merit_constraints: str = "penalty"  # criterion merit: the optimisation's constraint mode ("exact": limits apart)

    def __post_init__(self):
        from .configs import apply_configuration
        from .solves import freeze_solves

        self.notes: list[str] = []
        mc = self.system.multi_config
        active, n_configs = (mc.active, len(mc.names)) if mc is not None else (0, 1)
        # tolerance the active configuration: bake its values into the
        # prescription so perturbations are not overwritten on compile
        if self.system.multi_config is not None:
            d = apply_configuration(self.system).model_dump()
            d["multi_config"] = None
            self.system = OpticalSystem.model_validate(d)
        # solves are frozen at their nominal values: a perturbation must not be
        # silently re-solved (use compensators for that)
        self.system = freeze_solves(self.system, self.custom_materials)
        self.split = False  # exact limits: the criterion is the goals' merit function, the limits apart
        self.limit_numbers: list[int] = []  # their numbers among the optimiser's active operands
        if self.spec.criterion == "merit":
            self.operands, numbers, self.split, notes = _merit_criterion(self.merit_operands, active, n_configs, self.merit_constraints)
            self.notes += notes
            if self.split:
                self.limit_numbers = [n for n, o in zip(numbers, self.operands) if operand_role(o) == "constraint"]
        else:
            self.operands = _criterion_operands(self.spec, self.merit_operands, len(self.system.fields))
        self.limit_ops = [o for o in self.operands if operand_role(o) == "constraint"] if self.split else []
        self.sense = CRITERION_SENSE[self.spec.criterion]
        self.tols = [t for t in self.spec.tolerances if t.enabled]
        self.comps = [c for c in self.spec.compensators if c.enabled]
        validate_tolerances(self.system, self.tols)
        self.apertures: dict[str, float] = {}
        if any(t.type in FORM_TYPES for t in self.tols):
            from .system import SystemError_

            try:
                self.apertures = clear_apertures(self.system, self.custom_materials)
            except (SystemError_, ValueError, ArithmeticError) as exc:
                raise ToleranceError(f"The clear apertures for the form tolerances cannot be computed: {exc}") from exc
            pos = {s.id: i for i, s in enumerate(self.system.surfaces)}
            for t in self.tols:
                if t.type in FORM_TYPES and not self.apertures.get(t.surface_id, 0.0) > 0.0:
                    raise ToleranceError(f"Surface {pos[t.surface_id]}: no clear aperture for its form tolerance")
        pos = {s.id: i for i, s in enumerate(self.system.surfaces)}
        for c in self.comps:
            if c.surface_id not in pos:
                raise ToleranceError(f"Compensator refers to unknown surface id '{c.surface_id}'")
            if c.parameter != "thickness" and c.parameter != "curvature":
                raise ToleranceError("Compensators can be thickness or curvature")
            if c.parameter == "thickness" and self.system.surfaces[pos[c.surface_id]].thickness is None:
                raise ToleranceError("An infinite thickness cannot be a compensator")

    def _value(self, mf: MeritFunction, r: np.ndarray, bd: list[dict]) -> float:
        if self.spec.criterion == "mtf":
            return float(np.mean([b["value"] for b in bd]))
        m = mf.merit_from_residuals(r)
        return m * 1e3 if self.spec.criterion == "rms_spot" else m

    def evaluate(self, values=None, angles: dict[int, float] | None = None) -> dict:
        """Criterion for the perturbation `values` (None = nominal), compensated."""
        if values is None:
            values = np.zeros(len(self.tols))
        pt = perturb(self.system, self.tols, values, angles, self.apertures, self.spec.test_wavelength_um)
        variables = []
        for c in self.comps:
            sid = pt.thickness_carrier.get(c.surface_id, c.surface_id) if c.parameter == "thickness" else c.surface_id
            variables.append(Variable(surface_id=sid, parameter=c.parameter))
        mf = MeritFunction(pt.system, OptimizationSpec(variables=variables, operands=self.operands), self.custom_materials, pt.index_offsets, ns=self.ns, split=self.split)
        r0, bd0 = mf.evaluate(mf.x0)
        # with exact limits a limit that fails is reported (value None, not met); only the goals make the criterion fail
        failed = any("error" in b for b in bd0 if b.get("role") != "constraint")
        uncompensated = None if failed else self._value(mf, r0, bd0)
        comp_delta: list[float] = []
        value = uncompensated
        bd = bd0
        if variables and not failed:
            rng = np.array([c.range for c in self.comps])
            lo, hi = mf.x0 - rng, mf.x0 + rng
            # the compensators minimise the criterion: with exact limits the goals only
            mask = mf.layout()[0] if self.split else slice(None)
            try:
                sol = least_squares(lambda x: mf.evaluate(x)[0][mask], mf.x0, bounds=(lo, hi), method="trf", x_scale=_scale_for(mf), max_nfev=self.spec.compensator_evaluations)
                r1, bd1 = mf.evaluate(sol.x)
                if not any("error" in b for b in bd1 if b.get("role") != "constraint") and self.sense * (self._value(mf, r1, bd1) - value) <= 0:
                    value = self._value(mf, r1, bd1)
                    comp_delta = (sol.x - mf.x0).tolist()
                    bd = bd1
                else:
                    comp_delta = [0.0] * len(variables)
            except (ValueError, ArithmeticError):
                comp_delta = [0.0] * len(variables)
        elif variables:
            comp_delta = [0.0] * len(variables)
        self.evaluations += mf.evaluations
        out = {"value": value, "uncompensated": uncompensated, "compensators": comp_delta, "failed": value is None}
        if self.split:
            # the limits at the (compensated) design: value in the breakdown's unit, met to the optimiser's tolerance
            out["limits"] = [{"value": None if bd[k].get("error") else bd[k].get("value"), "met": bool(bd[k].get("met")), "unit": bd[k].get("unit", "")} for k in mf.constraint_ops]
        return out

    def limit_rows(self) -> list[dict]:
        """The limits' definitions (exact mode), in the unit of their values (merit.report_scale)."""
        rows = []
        for n, o in zip(self.limit_numbers, self.limit_ops):
            u = report_scale(o)
            rows.append({"index": n, "type": o.type, "kind": "target" if o.type in EQUALITY else "bound", "surface_id": o.surface_id, "field": o.field, "target": o.target * u, "tolerance": constraint_scale(o) * u})
        return rows


# ----------------------------------------------------------------------
# Analysis driver
# ----------------------------------------------------------------------
@dataclass
class TolProgress:
    phase: str = "starting"
    done: int = 0
    total: int = 0
    nominal: float | None = None
    trials: list[float | None] = field(default_factory=list)
    started: float = field(default_factory=time.time)


@dataclass
class TolControl:
    cancel: threading.Event = field(default_factory=threading.Event)


class Cancelled(Exception):
    pass


def _draw(tols: list[Tolerance], n: int, distribution: str, rng: np.random.Generator) -> np.ndarray:
    lo = np.array([t.min for t in tols])
    hi = np.array([t.max for t in tols])
    if distribution == "uniform":
        return lo + (hi - lo) * rng.random((n, len(tols)))
    c = 0.5 * (lo + hi)
    sig = (hi - lo) / 4.0  # limits at +-2 sigma
    z = truncnorm.rvs(-2.0, 2.0, size=(n, len(tols)), random_state=rng)
    return c + sig * z


def _stats(vals: np.ndarray) -> dict:
    if vals.size == 0:
        return {}
    p = np.percentile(vals, [2, 10, 50, 90, 98])
    return {
        "mean": float(vals.mean()),
        "std": float(vals.std(ddof=1)) if vals.size > 1 else 0.0,
        "min": float(vals.min()),
        "max": float(vals.max()),
        "p2": float(p[0]),
        "p10": float(p[1]),
        "p50": float(p[2]),
        "p90": float(p[3]),
        "p98": float(p[4]),
    }


def wilson_interval(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """95 % Wilson score interval of a binomial proportion k/n."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4 * n * n)) / d
    return (0.0 if k == 0 else max(0.0, centre - half)), (1.0 if k == n else min(1.0, centre + half))


def solve_factor(g: Callable[[float], float], g1: float, share: float, bounds: tuple[float, float] = ALLOCATION_FACTORS, rtol: float = 0.05, iters: int = 8) -> tuple[float, float, str | None]:
    """Scale factor f of a tolerance's limits with g(f) = share (g: increase of the additive quantity Q
    with the tolerance at f times its limits; g(1) = g1 is known). Steps assume a local power law
    g ~ f^p (p from the two nearest points, else 2) aimed slightly below the share, interpolated inside a
    bracket; returns (f, g(f), capped) with g(f) <= share where possible (capped: 'max' or 'min')."""
    lo_f, hi_f = bounds
    aim = share * (1.0 - rtol / 2.0)
    pts = [(1.0, g1)]

    def nxt() -> float | None:
        below = [p for p in pts if p[1] <= share]
        above = [p for p in pts if p[1] > share]
        if below and above:
            (fl, gl), (fh, gh) = max(below), min(above)
            fn = math.sqrt(fl * fh)
            if gl > 0 and math.isfinite(gh) and gh > gl:
                pw = math.log(gh / gl) / math.log(fh / fl)
                cand = fl * (aim / gl) ** (1.0 / pw)
                if fl < cand < fh:
                    fn = cand
            return fn
        if not above and max(below)[0] >= hi_f:
            return None
        if not below and min(above)[0] <= lo_f:
            return None
        finite = sorted((p for p in pts if p[1] > 0 and math.isfinite(p[1])), key=lambda p: abs(math.log(p[1] / aim)))
        if not finite:  # nothing measurable: jump to the bound on the side of the share
            return hi_f if not above else max(lo_f, min(above)[0] * 0.25)
        f0, g0 = finite[0]
        pw = 2.0
        if len(finite) >= 2 and finite[1][0] != f0:
            f1, g1_ = finite[1]
            est = math.log(g1_ / g0) / math.log(f1 / f0)
            if math.isfinite(est):
                pw = min(4.0, max(0.5, est))
        return min(hi_f, max(lo_f, f0 * (aim / g0) ** (1.0 / pw)))

    for _ in range(iters):
        below = [p for p in pts if p[1] <= share]
        if below and max(below)[1] >= share * (1.0 - rtol):
            break
        f = nxt()
        if f is None or any(abs(f - p[0]) <= 1e-9 * p[0] for p in pts):
            break
        pts.append((f, g(f)))
    below = [p for p in pts if p[1] <= share]
    f, gv = max(below) if below else min(pts)
    capped = "max" if f >= hi_f * (1 - 1e-12) else ("min" if not below else None)
    return f, gv, capped


def analyze(
    system: OpticalSystem,
    spec: ToleranceSpec,
    custom_materials=(),
    merit_operands: list[Operand] | None = None,
    progress: TolProgress | None = None,
    control: TolControl | None = None,
    on_update: Callable[[TolProgress], None] | None = None,
    ns=None,
    allocate: bool = False,
    merit_constraints: str = "penalty",
) -> dict:
    """Tolerance analysis (module notes). `merit_constraints`: the optimisation's constraint mode for the criterion
    "merit" ("exact": the goals' merit function, the limits reported apart under `limits`)."""
    progress = progress or TolProgress()
    control = control or TolControl()
    ev = Evaluator(system, spec, list(custom_materials), list(merit_operands or []), ns=ns, merit_constraints=merit_constraints)
    tols = ev.tols
    sense = ev.sense
    if not tols:
        raise ToleranceError("No enabled tolerances")
    if allocate and spec.limit is None:
        raise ToleranceError("Allocation needs a specification limit")
    active = [k for k, t in enumerate(tols) if not (t.min == 0.0 and t.max == 0.0)]
    progress.total = 1 + 2 * len(active) + spec.monte_carlo_trials
    t0 = time.time()
    status = "finished"

    def tick():
        progress.done += 1
        if on_update:
            on_update(progress)
        if control.cancel.is_set():
            raise Cancelled()

    sens: list[dict] = []
    trial_rows: list[dict] = []
    allocation: dict | None = None
    mc_tols = tols
    nominal = None
    nominal_unc = None
    nom_limits = None
    try:
        progress.phase = "nominal"
        nom = ev.evaluate()
        if nom["failed"]:
            raise ToleranceError("The nominal system cannot be evaluated with this criterion")
        nominal = nom["value"]
        nominal_unc = nom["uncompensated"]
        nom_limits = nom.get("limits")
        progress.nominal = nominal
        if allocate and sense * (nominal - spec.limit) >= 0:
            raise ToleranceError(f"The nominal system ({nominal:.6g}) does not meet the specification ({spec.limit:.6g}); nothing to allocate")
        tick()

        progress.phase = "sensitivity"
        for k in active:
            t = tols[k]
            row = {"tolerance": k, "id": t.id, "type": t.type, "surface_id": t.surface_id, "surface_id_end": t.surface_id_end, "term": t.term, "min": t.min, "max": t.max, "unit": TOLERANCE_UNITS[t.type]}
            for side, val in (("at_min", t.min), ("at_max", t.max)):
                x = np.zeros(len(tols))
                x[k] = val
                r = ev.evaluate(x)
                row[side] = r["value"]
                row[side + "_uncompensated"] = r["uncompensated"]
                row[side + "_compensators"] = r["compensators"]
                if "limits" in r:  # exact limits: their values at this side (the order of the result's `limits`)
                    row[side + "_limits"] = [q["value"] for q in r["limits"]]
                tick()
            deltas = [abs(row[s] - nominal) if row[s] is not None else math.inf for s in ("at_min", "at_max")]
            row["worst_change"] = max(deltas)
            sens.append(row)

        if allocate:
            progress.phase = "allocation"
            allocation = _allocate(ev, tols, active, sens, nominal, spec.limit, tick, progress)
            new = {r["tolerance"]: r for r in allocation["rows"]}
            mc_tols = [t.model_copy(update={"min": new[k]["new_min"], "max": new[k]["new_max"]}) if k in new else t for k, t in enumerate(tols)]

        progress.phase = "monte_carlo"
        rng = np.random.default_rng(spec.seed)
        draws = _draw(mc_tols, spec.monte_carlo_trials, spec.distribution, rng)
        irr = [k for k, t in enumerate(tols) if t.type == "irregularity"]
        phis = rng.random((spec.monte_carlo_trials, len(irr))) * math.pi if irr else None
        for n in range(spec.monte_carlo_trials):
            angles = {k: float(phis[n, j]) for j, k in enumerate(irr)} if irr else None
            r = ev.evaluate(draws[n], angles)
            row = {"values": draws[n].tolist(), "value": r["value"], "compensators": r["compensators"]}
            if "limits" in r:
                row["limits"] = [q["value"] for q in r["limits"]]
                row["limits_met"] = [q["met"] for q in r["limits"]]
            if angles:
                row["angles_deg"] = [math.degrees(angles[k]) for k in irr]
            trial_rows.append(row)
            progress.trials.append(r["value"])
            tick()
    except Cancelled:
        status = "cancelled"

    finite = [r["worst_change"] for r in sens if math.isfinite(r["worst_change"])]
    rss = math.sqrt(sum(c * c for c in finite)) if finite else 0.0
    vals = np.array([r["value"] for r in trial_rows if r["value"] is not None], dtype=float)
    failures = sum(1 for r in trial_rows if r["value"] is None)
    scored = [sense * r["value"] if r["value"] is not None else math.inf for r in trial_rows]
    best = int(np.argmin(scored)) if vals.size else None
    worst = int(np.argmax([s if math.isfinite(s) else -math.inf for s in scored])) if vals.size else None
    notes = []
    if any(not math.isfinite(r["worst_change"]) for r in sens):
        notes.append("Some sensitivity evaluations failed (ray failures or invalid geometry at a tolerance limit).")
    if failures:
        notes.append(f"{failures} Monte Carlo trial(s) could not be evaluated and are excluded from the statistics (they count as failing the specification).")
    if 0 < vals.size < 20:
        notes.append("Fewer than 20 Monte Carlo trials: percentiles are statistically unreliable.")
    if spec.criterion == "rms_spot" and nominal is not None and nominal < 1e-3:
        notes.append("Nominal RMS spot is below 1 nm; relative changes may be dominated by numerical noise.")
    if allocation:
        notes.extend(allocation.pop("notes"))
    notes.extend(ev.notes)

    limits = None
    if ev.split:
        # exact limits, apart from the criterion: nominal value, and how often the Monte Carlo trials meet them
        limits = []
        mc = [t for t in trial_rows if "limits" in t]
        for j, row in enumerate(ev.limit_rows()):
            lim = nom_limits[j] if nom_limits else None
            vals_j = np.array([t["limits"][j] for t in mc if t["limits"][j] is not None], dtype=float)
            row.update(
                unit=lim["unit"] if lim else "",
                nominal=lim["value"] if lim else None,
                met_nominal=bool(lim["met"]) if lim else False,
                monte_carlo={"trials": len(mc), "met": sum(1 for t in mc if t["limits_met"][j]), "statistics": _stats(vals_j)},
            )
            limits.append(row)
        notes.append(
            f"With exact limits the criterion is the merit function of the goals; the {len(limits)} limit(s) are reported apart (limits), "
            "met to the optimiser's tolerance, and do not enter the yield."
        )

    yld = None
    if spec.limit is not None and trial_rows:
        passed = sum(1 for r in trial_rows if r["value"] is not None and sense * (r["value"] - spec.limit) <= 0)
        lo, hi = wilson_interval(passed, len(trial_rows))
        yld = {"limit": spec.limit, "passed": passed, "trials": len(trial_rows), "fraction": passed / len(trial_rows), "ci95": [lo, hi]}

    rss_est = None
    if nominal is not None:
        rss_est = nominal + rss if sense > 0 else max(0.0, nominal - rss)
    kinds = {t.type for t in tols}
    extra = []
    if kinds & set(FORM_TYPES):
        extra.append(f"form errors as Zernike sag over the clear aperture, 1 fringe = {spec.test_wavelength_um * 1e3:.6g} nm / 2")
    if "abbe" in kinds:
        extra.append("Abbe changes at constant nd (dispersion scaled about nd)")
    if spec.criterion == "mtf":
        extra.append(f"MTF at {spec.mtf_frequency:g} cycles/mm: mean over fields of (T + S)/2, polychromatic FFT (32×32 pupil, padding 4)")
    if yld:
        extra.append("yield: trials meeting the limit, 95 % Wilson interval")
    return {
        "status": status,
        "criterion": spec.criterion,
        "unit": CRITERION_UNITS[spec.criterion],
        "sense": sense,
        "nominal": nominal,
        "nominal_uncompensated": nominal_unc,
        "sensitivity": sorted(sens, key=lambda r: -r["worst_change"] if math.isfinite(r["worst_change"]) else -math.inf),
        "rss_change": rss,
        "rss_estimate": rss_est,
        "monte_carlo": {
            "trials": len(trial_rows),
            "requested": spec.monte_carlo_trials,
            "failures": failures,
            "distribution": spec.distribution,
            "seed": spec.seed,
            "statistics": _stats(vals),
            "values": [r["value"] for r in trial_rows],
            "best_trial": trial_rows[best] if best is not None else None,
            "worst_trial": trial_rows[worst] if worst is not None else None,
            "allocated_limits": allocation is not None,
        },
        "yield": yld,
        "allocation": allocation,
        # criterion merit with exact limits (None otherwise): one row per limit (index: its number among the
        # optimiser's active operands)
        "limits": limits,
        "tolerances": [t.model_dump() for t in tols],
        "compensators": [c.model_dump() for c in ev.comps],
        "evaluations": ev.evaluations,
        "elapsed_s": time.time() - t0,
        "notes": notes,
        "method": (
            f"Exact real-ray criterion ({spec.criterion}, Gaussian pupil quadrature, {spec.rings} rings); "
            f"decenters/tilts as coordinate-break pairs; compensators re-solved per trial (trust-region least squares, <= {spec.compensator_evaluations} evaluations); "
            f"Monte Carlo {spec.distribution}{' (limits = ±2σ, truncated)' if spec.distribution == 'normal' else ''}, seed {spec.seed}; RSS = nominal {'+' if sense > 0 else '−'} sqrt(Σ worst change²)"
            + "".join(f"; {e}" for e in extra)
        ),
    }


def round_toward_zero(x: float, digits: int = 3) -> float:
    """x rounded toward zero to `digits` significant digits (an allocated limit never grows by rounding)."""
    if x == 0.0 or not math.isfinite(x):
        return x
    e = math.floor(math.log10(abs(x))) - digits + 1
    q = math.trunc(round(x / 10.0**e, 9))
    return q * 10.0**e if e >= 0 else q / 10.0 ** (-e)


def _allocate(ev: Evaluator, tols: list[Tolerance], active: list[int], sens: list[dict], nominal: float, limit: float, tick: Callable[[], None], progress: TolProgress) -> dict:
    """Inverse sensitivity: scale the free tolerances so that each uses an equal share of the budget in the
    additive quantity Q (module docstring)."""
    sense = ev.sense

    def Q(c: float) -> float:
        return c * c if sense > 0 else -c

    q0 = Q(nominal)
    budget = Q(limit) - q0
    by_k = {r["tolerance"]: r for r in sens}

    def g1(k: int) -> float:
        r = by_k[k]
        vs = [r[s] for s in ("at_min", "at_max") if (tols[k].min if s == "at_min" else tols[k].max) != 0.0]
        if any(v is None for v in vs):
            return math.inf
        return max([Q(v) - q0 for v in vs] + [0.0])

    def g(k: int, f: float) -> float:
        worst = 0.0
        for side in (tols[k].min, tols[k].max):
            if side == 0.0:
                continue
            x = np.zeros(len(tols))
            x[k] = side * f
            r = ev.evaluate(x)
            tick()
            if r["value"] is None:
                return math.inf
            worst = max(worst, Q(r["value"]) - q0)
        return worst

    locked = [k for k in active if tols[k].locked]
    free = [k for k in active if not tols[k].locked]
    if not free:
        raise ToleranceError("Every tolerance is locked: nothing to allocate")
    used = sum(g1(k) for k in locked)
    if not math.isfinite(used) or used >= budget:
        raise ToleranceError("The locked tolerances alone use the whole budget of the specification")
    share = (budget - used) / len(free)
    progress.total += 16 * len(free)  # at most 8 iterations of two sides each
    rows = []
    for k in active:
        t = tols[k]
        if t.locked:
            f, q, capped = 1.0, g1(k), None
        else:
            f, q, capped = solve_factor(lambda ff, k=k: g(k, ff), g1(k), share)
        rows.append({"tolerance": k, "id": t.id, "type": t.type, "surface_id": t.surface_id, "surface_id_end": t.surface_id_end, "term": t.term, "unit": TOLERANCE_UNITS[t.type], "locked": t.locked, "min": t.min, "max": t.max, "factor": f, "new_min": t.min if t.locked else round_toward_zero(t.min * f), "new_max": t.max if t.locked else round_toward_zero(t.max * f), "q": q, "share": q / budget if budget > 0 else None, "capped": capped})
    progress.total = progress.done + ev.spec.monte_carlo_trials
    total_q = q0 + sum(r["q"] for r in rows if math.isfinite(r["q"]))
    predicted = math.sqrt(max(0.0, total_q)) if sense > 0 else -total_q
    notes = []
    n_max = sum(1 for r in rows if r["capped"] == "max")
    n_min = sum(1 for r in rows if r["capped"] == "min")
    if n_max:
        notes.append(f"{n_max} tolerance(s) reached the largest allocation factor ({ALLOCATION_FACTORS[1]:g}×): the criterion is insensitive to them.")
    if n_min:
        notes.append(f"{n_min} tolerance(s) could not be tightened enough (smallest factor {ALLOCATION_FACTORS[0]:g}×).")
    return {
        "limit": limit,
        "nominal": nominal,
        "quantity": "c²" if sense > 0 else "−c",
        "budget": budget,
        "share": share,
        "predicted": predicted,
        "rows": rows,
        "notes": notes,
    }


# ----------------------------------------------------------------------
# Default tolerance sets (generic, illustrative manufacturing grades)
# ----------------------------------------------------------------------
GRADES: dict[str, dict[str, float]] = {
    # radius as a fraction of |R|; thickness mm; index; Abbe number as a fraction of Vd; power and
    # irregularity in fringes; decenter mm; tilt deg
    "commercial": {"radius": 0.005, "thickness": 0.1, "index": 0.001, "abbe": 0.008, "power": 5.0, "irregularity": 2.0, "decenter": 0.05, "tilt": 0.05},
    "precision": {"radius": 0.001, "thickness": 0.05, "index": 0.0005, "abbe": 0.005, "power": 3.0, "irregularity": 1.0, "decenter": 0.02, "tilt": 1.0 / 60},
    "high_precision": {"radius": 0.0005, "thickness": 0.02, "index": 0.0002, "abbe": 0.002, "power": 1.0, "irregularity": 0.25, "decenter": 0.01, "tilt": 0.5 / 60},
}


def abbe_number(library, name: str) -> float:
    """Vd = (nd - 1) / (nF - nC) of a material at catalogue conditions."""
    from .materials.dispersion import LAMBDA_C, LAMBDA_D, LAMBDA_F

    nd, nf, nc = (library.index(name, lam) for lam in (LAMBDA_D, LAMBDA_F, LAMBDA_C))
    return (nd - 1.0) / (nf - nc)


def element_groups(system: OpticalSystem) -> list[tuple[int, int]]:
    """(first, last) surface indices of lenses and cemented groups: maximal runs
    of surfaces followed by glass, closed by the surface where the glass ends."""
    s = system.surfaces
    n = len(s)

    def glass(i: int) -> bool:
        return s[i].type != "coordinate_break" and s[i].material.upper() not in ("AIR", "VACUUM", "MIRROR", "")

    out = []
    i = 1
    while i < n - 1:
        if not glass(i):
            i += 1
            continue
        j = i
        while j + 1 < n - 1 and glass(j + 1):
            j += 1
        back = j + 1
        if back <= n - 2 and s[back].type != "coordinate_break" and not s[back].is_mirror:
            out.append((i, back))
        i = back + 1
    return out


def default_spec(system: OpticalSystem, grade: str = "precision", custom_materials=()) -> ToleranceSpec:
    from .materials import MaterialError, MaterialLibrary

    if grade not in GRADES:
        raise ToleranceError(f"Unknown grade '{grade}'")
    g = GRADES[grade]
    s = system.surfaces
    n = len(s)
    lib = MaterialLibrary(custom_materials)
    tols: list[Tolerance] = []
    for i in range(1, n - 1):
        sf = s[i]
        if sf.type == "coordinate_break":
            continue
        if sf.radius is not None and sf.type != "ideal":
            dr = abs(sf.radius) * g["radius"]
            tols.append(Tolerance(type="radius", surface_id=sf.id, min=-dr, max=dr))
        if sf.type in FORM_SURFACES:
            tols.append(Tolerance(type="power", surface_id=sf.id, min=-g["power"], max=g["power"]))
            tols.append(Tolerance(type="irregularity", surface_id=sf.id, min=-g["irregularity"], max=g["irregularity"]))
        if sf.material.upper() not in GASES:
            if i < n - 2:
                tols.append(Tolerance(type="thickness", surface_id=sf.id, min=-g["thickness"], max=g["thickness"]))
            tols.append(Tolerance(type="index", surface_id=sf.id, min=-g["index"], max=g["index"]))
            try:
                dv = abs(abbe_number(lib, sf.material)) * g["abbe"]
            except (MaterialError, ValueError, ArithmeticError, ZeroDivisionError):
                dv = 0.0  # no dispersion data in the visible: no Abbe tolerance
            if dv > 0.0 and math.isfinite(dv):
                tols.append(Tolerance(type="abbe", surface_id=sf.id, min=-dv, max=dv))
        elif i < n - 2 and sf.thickness is not None and sf.thickness != 0 and i != _back_focus_surface(system):
            tols.append(Tolerance(type="thickness", surface_id=sf.id, min=-g["thickness"], max=g["thickness"]))
    for a, b in element_groups(system):
        for kind, lim in (("decenter_x", g["decenter"]), ("decenter_y", g["decenter"]), ("tilt_x", g["tilt"]), ("tilt_y", g["tilt"])):
            tols.append(Tolerance(type=f"element_{kind}", surface_id=s[a].id, surface_id_end=s[b].id, min=-lim, max=lim))
    comps = []
    bf = _back_focus_surface(system)
    if bf is not None:
        comps.append(Compensator(surface_id=s[bf].id, parameter="thickness", range=2.0))
    return ToleranceSpec(tolerances=tols, compensators=comps)


def _back_focus_surface(system: OpticalSystem) -> int | None:
    n = len(system.surfaces)
    for i in range(n - 2, 0, -1):
        if system.surfaces[i].type != "coordinate_break":
            return i if system.surfaces[i].thickness is not None else None
    return None


# ----------------------------------------------------------------------
# Background jobs
# ----------------------------------------------------------------------
@dataclass
class TolJob:
    id: str
    state: str = "queued"  # queued | running | finished | cancelled | failed
    progress: TolProgress = field(default_factory=TolProgress)
    control: TolControl = field(default_factory=TolControl)
    result: dict | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)


class ToleranceJobs:
    def __init__(self, max_jobs: int = 16):
        self._jobs: dict[str, TolJob] = {}
        self._lock = threading.Lock()
        self.max_jobs = max_jobs

    def start(self, system: OpticalSystem, spec: ToleranceSpec, custom_materials=(), merit_operands=(), ns=None, allocate: bool = False, merit_constraints: str = "penalty") -> TolJob:
        # configuration errors are raised synchronously (ToleranceError)
        Evaluator(system, spec, list(custom_materials), list(merit_operands), ns=ns, merit_constraints=merit_constraints)
        if allocate and spec.limit is None:
            raise ToleranceError("Allocation needs a specification limit")
        import uuid

        job = TolJob(id=uuid.uuid4().hex[:16])

        def run():
            job.state = "running"
            try:
                job.result = analyze(system, spec, custom_materials, list(merit_operands), job.progress, job.control, ns=ns, allocate=allocate, merit_constraints=merit_constraints)
                job.state = "cancelled" if job.result["status"] == "cancelled" else "finished"
            except Exception as exc:  # reported to the client
                job.error = f"{type(exc).__name__}: {exc}"
                job.state = "failed"

        with self._lock:
            done = sorted((j for j in self._jobs.values() if j.state in ("finished", "cancelled", "failed")), key=lambda j: j.created)
            for j in done[: max(0, len(self._jobs) - self.max_jobs + 1)]:
                self._jobs.pop(j.id, None)
            self._jobs[job.id] = job
        threading.Thread(target=run, daemon=True, name=f"tol-{job.id}").start()
        return job

    def get(self, job_id: str) -> TolJob | None:
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job:
            return False
        job.control.cancel.set()
        return True

    def snapshot(self, job: TolJob) -> dict:
        p = job.progress
        return {
            "id": job.id,
            "state": job.state,
            "phase": p.phase,
            "done": p.done,
            "total": p.total,
            "nominal": p.nominal,
            "trials": list(p.trials),
            "elapsed_s": time.time() - p.started,
            "error": job.error,
            "result": job.result if job.state in ("finished", "cancelled") else None,
        }
