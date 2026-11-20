"""Optimisation variables, operands and the merit function.

Merit function definition (weighted RMS of operand errors):

    MF^2 = sum_k w_k (v_k - t_k)^2 / sum_k w_k

For least-squares solvers each operand contributes a residual vector whose
sum of squares equals (v_k - t_k)^2 (e.g. the RMS-spot operand contributes
one residual per ray coordinate), scaled by sqrt(w_k / sum w). Every operand
keeps the same number of residuals in every evaluation (operand_sizes): when it
cannot be evaluated (rays or an image-height field fail at a trial point) its
residuals carry the failure penalty spread over that many entries, so the
finite-difference Jacobian of the least-squares solver stays well defined.

The image-quality operands rms_spot and rms_wavefront minimise (one residual per
ray) when their target is 0; with a target > 0 (a spot or wavefront of a given
size) they contribute the single error RMS - target, padded with zeros to their
fixed size. rms_wavefront with wavelength None is polychromatic: every
wavelength's OPD is taken against the reference sphere of the primary
wavelength's chief ray (so lateral colour is a relative tilt and axial colour a
relative defocus), each wavelength's piston is removed, and with the centroid
reference also the best common tilt; the RMS is in waves of the primary
wavelength, weighted by the wavelength and field weights.

Exact constraints (spec.constraints = "exact", the default; MeritFunction(split=True) in the optimiser): operands
whose role is "constraint" leave the merit function and become constraints the optimiser meets to a tolerance
(optimize/engine.py, an augmented Lagrangian). By default (role "auto") these are the bound operands (min_*, max_*)
and the first-order targets (efl, bfl, fnum, working_fnum, magnification, total_track); every operand's role can be
set. In split mode the residual vector is [objective residuals (weights among the objectives only), one normalised
signed constraint value per constraint (g/s <= 0 met for a bound, = 0 for a target; s = CONSTRAINT_SCALE, the
tolerance)]. With spec.constraints = "penalty" every operand is a weighted residual as described above.

Active operands (is_active): enabled, and a weight above 0 unless the role is "constraint" (a limit's weight is not
used, so a weight-0 limit is still met exactly; with weighted limits it stays in the breakdown with no contribution).
Their order numbers every result. A field or wavelength index an operand names must exist (ValueError), and the
RMS operands weigh a field or wavelength they name with 1, whatever its system weight.

Bound-type operands (min_* / max_*) only contribute when violated. max_lateral_color (|lateral colour|, um),
max_cra (chief-ray angle on the image, degrees) and min_relative_illumination (fraction of the axis) act at the
operand's field or the largest field, with the numbers of analysis/summary.py.

Detector operands (detector_size, detector_power) evaluate the project's light sources and
analytic detectors by the direct-path trace (nsdirect.py, seeded, so the merit function is
deterministic): detector_size is the second-moment beam diameter D4sigma = 2 x (2 sigma) in
the detector plane (mm; the 1/e^2 diameter of a Gaussian beam, the diameter of a uniform disc),
detector_power the fraction of the emitted power the detector accepts (piecewise constant in
steps of about 1/rays).
"""

from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ..model import OpticalSystem
from ..paraxial import compute_pupil, paraxial_data
from ..raytrace import gauss_pupil, trace_fields, trace_pupil
from ..system import NotApplicable, SystemError_, compile_system

VariableParam = Literal[
    "curvature",
    "thickness",
    "conic",
    "asph_4",
    "asph_6",
    "asph_8",
    "asph_10",
    "asph_12",
    "decenter_x",
    "decenter_y",
    "tilt_x",
    "tilt_y",
    "tilt_z",
    "material",
    "curvature_x",
    "conic_x",
    "phase_1",
    "phase_2",
    "phase_3",
    "phase_4",
    "grating_frequency",
    "ideal_power",  # ideal lens: 1 / focal length (1/mm)
    "mount_cte",  # expansion (1e-6/K) of the spacer after an air gap or of a mirror substrate (environment model)
    "zern_1", "zern_2", "zern_3", "zern_4", "zern_5", "zern_6", "zern_7", "zern_8", "zern_9", "zern_10", "zern_11", "zern_12", "zern_13", "zern_14", "zern_15", "zern_16", "zern_17", "zern_18", "zern_19", "zern_20", "zern_21", "zern_22", "zern_23", "zern_24", "zern_25", "zern_26", "zern_27", "zern_28", "zern_29", "zern_30", "zern_31", "zern_32", "zern_33", "zern_34", "zern_35", "zern_36", "zern_37",
    "coating_scale",
    "coat_layer_1", "coat_layer_2", "coat_layer_3", "coat_layer_4", "coat_layer_5", "coat_layer_6", "coat_layer_7", "coat_layer_8", "coat_layer_9", "coat_layer_10", "coat_layer_11", "coat_layer_12", "coat_layer_13", "coat_layer_14", "coat_layer_15", "coat_layer_16", "coat_layer_17", "coat_layer_18", "coat_layer_19", "coat_layer_20", "coat_layer_21", "coat_layer_22", "coat_layer_23", "coat_layer_24", "coat_layer_25", "coat_layer_26", "coat_layer_27", "coat_layer_28", "coat_layer_29", "coat_layer_30", "coat_layer_31", "coat_layer_32", "coat_layer_33", "coat_layer_34", "coat_layer_35", "coat_layer_36", "coat_layer_37", "coat_layer_38", "coat_layer_39", "coat_layer_40", "coat_layer_41", "coat_layer_42", "coat_layer_43", "coat_layer_44", "coat_layer_45", "coat_layer_46", "coat_layer_47", "coat_layer_48", "coat_layer_49", "coat_layer_50", "coat_layer_51", "coat_layer_52", "coat_layer_53", "coat_layer_54", "coat_layer_55", "coat_layer_56", "coat_layer_57", "coat_layer_58", "coat_layer_59", "coat_layer_60",
]
# Q-type and XY-polynomial coefficients (q_1 = a_0, ...; xy_1 = A_1, ...)
VariableParam = Literal[(*VariableParam.__args__, *[f"q_{k}" for k in range(1, 31)], *[f"xy_{k}" for k in range(1, 66)], *[f"odd_{k}" for k in range(1, 17)])]  # type: ignore[valid-type]

OperandType = Literal[
    "rms_spot",
    "throughput",
    "rms_wavefront",
    "mtf",
    "efl",
    "bfl",
    "fnum",
    "working_fnum",
    "total_track",
    "magnification",
    "axial_color",
    "distortion",
    "max_distortion",
    "max_lateral_color",
    "min_relative_illumination",
    "max_cra",
    "min_thickness",
    "max_thickness",
    "min_edge_thickness",
    "max_total_track",
    "surface_reflectance",
    "detector_size",
    "detector_power",
]

FAILED_RAY_PENALTY = 1.0  # mm, per failed ray coordinate
FAILED_SYSTEM_PENALTY = 1e3
FAILED_CONSTRAINT = 1e6  # normalised violation (in tolerances) of a constraint that cannot be evaluated

# constraints: sign of g = sigma (value - target), "abs" for |value| - target; equality targets have g = 0
CONSTRAINT_SIGN: dict[str, float | str] = {
    "min_thickness": -1.0, "min_edge_thickness": -1.0, "min_relative_illumination": -1.0, "mtf": -1.0, "throughput": -1.0, "detector_power": -1.0,
    "max_thickness": 1.0, "max_total_track": 1.0, "max_cra": 1.0, "max_lateral_color": 1.0, "rms_spot": 1.0, "rms_wavefront": 1.0, "surface_reflectance": 1.0,
    "max_distortion": "abs",
    "efl": 1.0, "bfl": 1.0, "fnum": 1.0, "working_fnum": 1.0, "magnification": 1.0, "total_track": 1.0, "distortion": 1.0, "axial_color": 1.0, "detector_size": 1.0,
}
EQUALITY = {"efl", "bfl", "fnum", "working_fnum", "magnification", "total_track", "distortion", "axial_color", "detector_size"}
# operands that are constraints unless their role says otherwise
DEFAULT_CONSTRAINTS = {"min_thickness", "max_thickness", "min_edge_thickness", "max_total_track", "max_distortion", "max_lateral_color", "min_relative_illumination", "max_cra", "efl", "bfl", "fnum", "working_fnum", "magnification", "total_track"}
# the tolerance to which a constraint is met (its own units); relative ones scale with |target|
CONSTRAINT_SCALE: dict[str, tuple[float, float]] = {  # (absolute, relative to |target|): s = max(absolute, relative |target|)
    "min_thickness": (1e-3, 0.0), "max_thickness": (1e-3, 0.0), "min_edge_thickness": (1e-3, 0.0), "max_total_track": (1e-3, 0.0), "total_track": (1e-3, 0.0),
    "efl": (1e-5, 1e-4), "bfl": (1e-4, 1e-4), "fnum": (1e-3, 0.0), "working_fnum": (1e-3, 0.0), "magnification": (1e-6, 1e-4),
    "max_distortion": (1e-3, 0.0), "distortion": (1e-3, 0.0), "max_lateral_color": (1e-2, 0.0), "min_relative_illumination": (1e-3, 0.0), "max_cra": (1e-2, 0.0),
    "axial_color": (1e-4, 0.0), "rms_spot": (1e-5, 0.0), "rms_wavefront": (1e-3, 0.0), "mtf": (1e-3, 0.0), "throughput": (1e-4, 0.0),
    "detector_size": (1e-4, 0.0), "detector_power": (1e-3, 0.0), "surface_reflectance": (1e-5, 0.0),
}
# the step by which a constraint is relaxed in the price report (own units; relative ones scale with |target|)
RELAX_STEP: dict[str, tuple[float, float]] = {
    "min_thickness": (0.005, 0.02), "max_thickness": (0.005, 0.02), "min_edge_thickness": (0.005, 0.02), "max_total_track": (0.01, 0.01), "total_track": (0.01, 0.01),
    "efl": (0.0, 0.005), "bfl": (0.0, 0.01), "fnum": (0.05, 0.0), "working_fnum": (0.05, 0.0), "magnification": (0.001, 0.01),
    "max_distortion": (0.1, 0.0), "distortion": (0.1, 0.0), "max_lateral_color": (0.1, 0.0), "min_relative_illumination": (0.01, 0.0), "max_cra": (1.0, 0.0),
    "axial_color": (0.001, 0.0), "rms_spot": (0.0005, 0.0), "rms_wavefront": (0.01, 0.0), "mtf": (0.02, 0.0), "throughput": (0.01, 0.0),
    "detector_size": (0.005, 0.02), "detector_power": (0.01, 0.0), "surface_reflectance": (0.001, 0.0),
}


def operand_role(o) -> str:
    """'constraint' or 'objective' (module notes)."""
    if o.role != "auto":
        return o.role
    return "constraint" if o.type in DEFAULT_CONSTRAINTS else "objective"


def is_active(o) -> bool:
    """An operand the merit function uses: enabled, and a weight above 0 unless its role is 'constraint' (a limit's
    weight is not used, so a limit with weight 0 still counts). The same in both constraint modes: with weighted
    limits a weight-0 limit stays in the breakdown and contributes nothing. The active operands, in order, number
    every result's operands (MeritFunction.operands, the breakdowns, the constraint rows' 'index', the trade-off's
    operand, the tolerancing limits)."""
    return bool(o.enabled and (o.weight > 0 or operand_role(o) == "constraint"))


def exact_constraints(spec) -> bool:
    """True when the optimiser meets limits exactly: constraints "exact" and at least one active limit."""
    return spec.constraints == "exact" and any(operand_role(o) == "constraint" for o in spec.operands if is_active(o))


# the breakdown and the constraint rows report the RMS spot in um; its target and tolerance are in mm
REPORT_SCALE = {"rms_spot": 1e3}


def report_scale(o) -> float:
    """Reported unit of an operand's value per unit of its target (1e3 for the RMS spot: um per mm)."""
    return REPORT_SCALE.get(o.type, 1.0)


# operands that read their field / wavelength index (MeritFunction validates these indices)
FIELD_OPERANDS = {"rms_spot", "rms_wavefront", "throughput", "mtf", "surface_reflectance", "max_lateral_color", "min_relative_illumination", "max_cra"}
WAVELENGTH_OPERANDS = {"rms_spot", "rms_wavefront", "throughput", "surface_reflectance", "efl", "bfl", "fnum", "working_fnum", "magnification"}


def constraint_scale(o) -> float:
    a, r = CONSTRAINT_SCALE.get(o.type, (1e-3, 0.0))
    return max(a, r * abs(o.target))


def relax_step(o) -> float:
    a, r = RELAX_STEP.get(o.type, (0.0, 0.01))
    return max(a, r * abs(o.target))


def constraint_value(o, value: float | None) -> float:
    """Normalised signed constraint value g/s (<= 0 met for a bound; 0 for a target) of an operand's value (in the
    units of its target)."""
    if value is None or not math.isfinite(value):
        return FAILED_CONSTRAINT
    sg = CONSTRAINT_SIGN.get(o.type, 1.0)
    g = abs(value) - o.target if sg == "abs" else float(sg) * (value - o.target)
    return g / constraint_scale(o)


def constraint_met(o, g: float) -> bool:
    return abs(g) <= 1.0 if o.type in EQUALITY else g <= 1.0


def target_sign(o) -> float:
    """d g / d target = -target_sign / s: +1 for an upper bound (and |value| <= target) or a target, -1 for a lower
    bound. Relaxing a bound moves its target by +target_sign * step."""
    sg = CONSTRAINT_SIGN.get(o.type, 1.0)
    return 1.0 if sg == "abs" else float(sg)


class Variable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    surface_id: str
    parameter: VariableParam
    min: float | None = None
    max: float | None = None
    enabled: bool = True
    configuration: int | None = Field(default=None, ge=0, description="per-configuration value in the configuration editor (None = base prescription)")
    candidates: list[str] | None = Field(default=None, description="material variables: allowed glasses (None = all catalogue glasses)")


class Operand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: OperandType
    target: float = 0.0
    weight: float = Field(default=1.0, ge=0.0)
    field: int | None = None  # None = all fields
    wavelength: int | None = None  # None = all wavelengths
    surface_id: str | None = None
    rings: int = Field(default=4, ge=1, le=20)
    reference: Literal["centroid", "chief"] = "centroid"
    frequency: float | None = Field(default=None, gt=0, description="cycles/mm (mtf operand)")
    direction: Literal["tangential", "sagittal", "average"] = "average"
    configuration: int | None = Field(default=None, ge=0, description="configuration to evaluate (None = active)")
    detector_id: str | None = Field(default=None, description="detector operands: the project detector")
    role: Literal["auto", "objective", "constraint"] = Field(default="auto", description="exact constraints: a goal of the merit function or a constraint met to tolerance; auto by type (module notes)")
    enabled: bool = True


class OptimizationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variables: list[Variable] = Field(default_factory=list)
    operands: list[Operand] = Field(default_factory=list)
    algorithm: Literal["local", "global", "multistart"] = "local"
    max_evaluations: int = Field(default=2000, ge=10, le=200000)
    multistart_runs: int = Field(default=6, ge=2, le=64)
    seed: int = 1
    constraints: Literal["exact", "penalty"] = Field(default="exact", description="constraint operands met to tolerance (augmented Lagrangian) or weighted penalties")


# ----------------------------------------------------------------------
def _surface_index(system: OpticalSystem, sid: str) -> int:
    for i, s in enumerate(system.surfaces):
        if s.id == sid:
            return i
    raise ValueError(f"Unknown surface id '{sid}'")


CONFIG_PARAM = {"curvature": "radius", "thickness": "thickness", "conic": "conic", "decenter_x": "decenter_x", "decenter_y": "decenter_y", "tilt_x": "tilt_x", "tilt_y": "tilt_y", "tilt_z": "tilt_z"}


def config_operand_index(system_or_dict, surface_id: str, parameter: str) -> int | None:
    """Index of the configuration operand controlling (surface, variable parameter), if any."""
    mc = system_or_dict["multi_config"] if isinstance(system_or_dict, dict) else (system_or_dict.multi_config.model_dump() if system_or_dict.multi_config else None)
    if not mc:
        return None
    cp = CONFIG_PARAM.get(parameter)
    for k, op in enumerate(mc["operands"]):
        if op["parameter"] == cp and op["surface_id"] == surface_id:
            return k
    return None


def get_variable_value(system: OpticalSystem, v: Variable) -> float:
    if v.configuration is not None:
        k = config_operand_index(system, v.surface_id, v.parameter)
        val = system.multi_config.operands[k].values[v.configuration]
        if v.parameter == "curvature":
            return 0.0 if val is None else 1.0 / float(val)
        return float(val)
    s = system.surfaces[_surface_index(system, v.surface_id)]
    p = v.parameter
    if p == "curvature":
        return s.curvature
    if p == "curvature_x":
        return s.curvature_x
    if p == "ideal_power":
        return 0.0 if s.focal_length is None else 1.0 / s.focal_length
    if p == "thickness":
        return float(s.thickness or 0.0)
    if p == "conic":
        return s.conic
    if p.startswith("asph_"):
        k = (int(p[5:]) - 4) // 2
        return s.aspheric[k] if k < len(s.aspheric) else 0.0
    if p.startswith("phase_"):
        k = int(p[6:]) - 1
        return s.phase_coefficients[k] if k < len(s.phase_coefficients) else 0.0
    if p.startswith("zern_"):
        k = int(p[5:]) - 1
        return s.zernike_coefficients[k] if k < len(s.zernike_coefficients) else 0.0
    if p.startswith("q_"):
        k = int(p[2:]) - 1
        return s.q_coefficients[k] if k < len(s.q_coefficients) else 0.0
    if p.startswith("xy_"):
        k = int(p[3:]) - 1
        return s.xy_coefficients[k] if k < len(s.xy_coefficients) else 0.0
    if p.startswith("odd_"):
        k = int(p[4:]) - 1
        return s.odd_coefficients[k] if k < len(s.odd_coefficients) else 0.0
    if p == "mount_cte":
        return float(system.housing_cte if s.mount_cte is None else s.mount_cte)
    if p == "coating_scale":
        return 1.0  # multiplier of the coating's current layer thicknesses
    if p.startswith("coat_layer_"):
        cd = _coating_of(system.model_dump(), s.coating)
        return float(cd["layers"][int(p[11:]) - 1]["thickness_nm"])
    return float(getattr(s, p))


def _coating_of(system_dict: dict, name: str) -> dict:
    key = (name or "").strip().upper()
    for c in system_dict.get("custom_coatings") or []:
        if c["name"].strip().upper() == key:
            return c
    raise ValueError(f"Coating '{name}' is not a project coating (built-in coatings cannot be optimised; duplicate it into the project first)")


def apply_values(system_dict: dict, variables: list[Variable], x: np.ndarray, index_of: dict[str, int]) -> dict:
    d = {**system_dict, "surfaces": [dict(s) for s in system_dict["surfaces"]]}
    if any(v.parameter == "coating_scale" or v.parameter.startswith("coat_layer_") for v in variables):
        d["custom_coatings"] = [{**c, "layers": [dict(L) for L in c["layers"]]} for c in system_dict.get("custom_coatings") or []]
    if system_dict.get("multi_config"):
        mc = system_dict["multi_config"]
        d["multi_config"] = {**mc, "operands": [{**op, "values": list(op["values"])} for op in mc["operands"]]}
    for v, val in zip(variables, x):
        p = v.parameter
        val = float(val)
        if v.configuration is not None:
            k = config_operand_index(d, v.surface_id, p)
            vals = d["multi_config"]["operands"][k]["values"]
            vals[v.configuration] = (None if abs(val) < 1e-15 else 1.0 / val) if p == "curvature" else val
            continue
        s = d["surfaces"][index_of[v.surface_id]]
        if p == "coating_scale" or p.startswith("coat_layer_"):
            cd = _coating_of(d, s.get("coating", ""))
            if p == "coating_scale":
                base = _coating_of(system_dict, s.get("coating", ""))
                for L, L0 in zip(cd["layers"], base["layers"]):
                    L["thickness_nm"] = max(0.0, float(L0["thickness_nm"]) * val)
            else:
                cd["layers"][int(p[11:]) - 1]["thickness_nm"] = max(0.0, val)
            continue
        if p == "curvature":
            s["radius"] = None if abs(val) < 1e-15 else 1.0 / val
        elif p == "curvature_x":
            s["radius_x"] = None if abs(val) < 1e-15 else 1.0 / val
        elif p == "ideal_power":
            s["focal_length"] = None if abs(val) < 1e-15 else 1.0 / val
        elif p.startswith("asph_"):
            k = (int(p[5:]) - 4) // 2
            a = list(s.get("aspheric") or [])
            while len(a) <= k:
                a.append(0.0)
            a[k] = val
            s["aspheric"] = a
        elif p.startswith("phase_"):
            k = int(p[6:]) - 1
            a = list(s.get("phase_coefficients") or [])
            while len(a) <= k:
                a.append(0.0)
            a[k] = val
            s["phase_coefficients"] = a
        elif p.startswith("zern_") or p.startswith("q_") or p.startswith("xy_") or p.startswith("odd_"):
            key, k = (
                ("zernike_coefficients", int(p[5:]) - 1) if p.startswith("zern_")
                else ("q_coefficients", int(p[2:]) - 1) if p.startswith("q_")
                else ("odd_coefficients", int(p[4:]) - 1) if p.startswith("odd_")
                else ("xy_coefficients", int(p[3:]) - 1)
            )
            a = list(s.get(key) or [])
            while len(a) <= k:
                a.append(0.0)
            a[k] = val
            s[key] = a
        else:
            s[p] = val
    return d


class MeritFunction:
    """Evaluates the merit function and residual vectors for given variable values."""

    def __init__(self, system: OpticalSystem, spec: OptimizationSpec, custom_materials=(), index_offsets: dict[str, float] | None = None, ns=None, split: bool = False):
        self.base = system
        # (sources, detectors) of the project for the detector operands
        self.sources, self.detectors = (list(ns[0]), list(ns[1])) if ns else ([], [])
        self.index_offsets = dict(index_offsets or {})
        self.base_dict = system.model_dump()
        self.custom_materials = list(custom_materials)
        self.variables = [v for v in spec.variables if v.enabled]
        self.operands = [o for o in spec.operands if is_active(o)]  # numbering of every result (is_active)
        if not self.operands:
            raise ValueError("The merit function has no active operands")
        if not split and not any(o.weight > 0 for o in self.operands):
            raise ValueError("The merit function has no operand with a weight above 0 (a limit's weight counts with weighted limits)")
        self.index_of = {s.id: i for i, s in enumerate(system.surfaces)}
        seen_coat: set = set()
        for v in self.variables:
            if v.parameter == "material":
                raise ValueError("Material variables are handled by glass substitution (optimize), not by the merit function")
            if v.surface_id not in self.index_of:
                raise ValueError(f"Variable refers to unknown surface id '{v.surface_id}'")
            i = self.index_of[v.surface_id]
            if v.parameter == "thickness" and i == 0 and system.surfaces[0].thickness is None:
                raise ValueError("Infinite object distance cannot be a variable")
            if v.parameter in ("decenter_x", "decenter_y", "tilt_x", "tilt_y", "tilt_z") and system.surfaces[i].type != "coordinate_break":
                raise ValueError("Tilt/decenter variables require a coordinate-break surface")
            nconf = len(system.multi_config.names) if system.multi_config else 1
            ck = config_operand_index(system, v.surface_id, v.parameter)
            if v.configuration is not None:
                if system.multi_config is None or v.configuration >= nconf:
                    raise ValueError(f"Variable refers to configuration {v.configuration + 1}, which does not exist")
                if ck is None:
                    raise ValueError(f"Surface {i}: per-configuration {v.parameter} variable needs a matching row in the configuration editor")
                if v.parameter == "curvature" and system.multi_config.operands[ck].values[v.configuration] is None:
                    pass  # plane in this configuration: curvature 0 is a valid start
                continue
            if ck is not None:
                raise ValueError(f"Surface {i}: {v.parameter} is set per configuration; make the variable per-configuration instead")
            if v.parameter == "thickness" and system.surfaces[i].thickness_solve is not None:
                raise ValueError(f"Surface {i}: the thickness is controlled by a solve and cannot be a variable")
            if v.parameter == "curvature" and system.surfaces[i].curvature_solve is not None:
                raise ValueError(f"Surface {i}: the curvature is controlled by a solve and cannot be a variable")
            if v.parameter in ("curvature_x", "conic_x") and system.surfaces[i].type != "biconic":
                raise ValueError(f"Surface {i}: {v.parameter} needs a biconic surface")
            if (v.parameter == "ideal_power") != (system.surfaces[i].type == "ideal") and v.parameter in ("ideal_power", "curvature", "conic"):
                raise ValueError(f"Surface {i}: " + ("ideal_power needs an ideal lens" if v.parameter == "ideal_power" else f"an ideal lens has no {v.parameter}; vary ideal_power instead"))
            if v.parameter == "coating_scale" or v.parameter.startswith("coat_layer_"):
                cd = _coating_of(system.model_dump(), system.surfaces[i].coating)
                if v.parameter.startswith("coat_layer_") and int(v.parameter[11:]) > len(cd["layers"]):
                    raise ValueError(f"Coating {cd['name']} has only {len(cd['layers'])} layers")
                ck = (cd["name"].strip().upper(), v.parameter)
                if ck in seen_coat:
                    raise ValueError(f"Coating {cd['name']}: {v.parameter} is already a variable (on another surface that uses the same coating)")
                seen_coat.add(ck)
            if v.parameter.startswith("zern_") and system.surfaces[i].type != "zernike":
                raise ValueError(f"Surface {i}: Zernike variables need a Zernike surface")
            if v.parameter.startswith("q_") and system.surfaces[i].type not in ("qcon", "qbfs"):
                raise ValueError(f"Surface {i}: Q-coefficient variables need a Qcon or Qbfs surface")
            if v.parameter.startswith("xy_") and system.surfaces[i].type != "xy_polynomial":
                raise ValueError(f"Surface {i}: XY-coefficient variables need an XY-polynomial surface")
            if v.parameter.startswith("odd_") and system.surfaces[i].type != "odd_asphere":
                raise ValueError(f"Surface {i}: odd-asphere variables need an odd-asphere surface")
            if v.parameter.startswith("asph_") and system.surfaces[i].type not in ("even_asphere", "zernike", "xy_polynomial"):
                raise ValueError("Aspheric variables require an even-asphere surface")
            if (v.parameter.startswith("phase_") or v.parameter == "grating_frequency") and (i in (0, len(system.surfaces) - 1) or system.surfaces[i].type == "coordinate_break"):
                raise ValueError(f"Surface {i}: diffractive variables need an optical surface (not object, image or coordinate break)")
            if v.parameter == "mount_cte":
                if not system.environment_enabled:
                    raise ValueError("Spacer/substrate expansion variables need the environment model (temperature and pressure) to be on")
                if i in (0, len(system.surfaces) - 1):
                    raise ValueError(f"Surface {i}: the object and image surfaces have no spacer or substrate")
        nconf = len(system.multi_config.names) if system.multi_config else 1
        nf, nw = len(system.fields), len(system.wavelengths)  # the same in every configuration
        for o in self.operands:
            if o.configuration is not None and o.configuration >= nconf:
                raise ValueError(f"Operand {o.type} refers to configuration {o.configuration + 1}, which does not exist")
            if o.field is not None and o.type in FIELD_OPERANDS and not 0 <= o.field < nf:
                raise ValueError(f"Operand {o.type} refers to field {o.field + 1}, which does not exist (the system has {nf})")
            if o.wavelength is not None and o.type in WAVELENGTH_OPERANDS and not 0 <= o.wavelength < nw:
                raise ValueError(f"Operand {o.type} refers to wavelength {o.wavelength + 1}, which does not exist (the system has {nw})")
            if o.type in ("detector_size", "detector_power"):
                if not any(s.enabled for s in self.sources):
                    raise ValueError(f"Operand {o.type} needs an enabled light source (Sources and detectors)")
                if not any(d.id == o.detector_id and d.enabled for d in self.detectors):
                    raise ValueError(f"Operand {o.type} needs an enabled detector of the project")
        self.wsum = sum(o.weight for o in self.operands)  # 0 only in split mode with weight-0 limits alone
        # exact constraints (module notes): the objective's weights are its own; constraints are separate entries
        self.split = bool(split)
        self.roles = [operand_role(o) if self.split else "objective" for o in self.operands]
        self.wsum_obj = sum(o.weight for o, r in zip(self.operands, self.roles) if r == "objective") or 1.0
        self.constraint_ops = [k for k, r in enumerate(self.roles) if r == "constraint"]
        self.fixed = set(self.fixed_operands())
        self.x0 = np.array([get_variable_value(system, v) for v in self.variables], dtype=float)
        self._sizes: list[int] | None = None
        self._layout: tuple[np.ndarray, np.ndarray] | None = None
        self.evaluations = 0
        self._pattern_cache: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        self._aim_cache: dict = {}  # warm starts for real ray aiming between evaluations
        self._aim_caches: dict[int, dict] = {}
        self._failed = 0  # one warm-start cache per configuration

    # ------------------------------------------------------------------
    def fixed_operands(self) -> list[int]:
        """Indices (into self.operands) of thickness and edge operands that no variable can change: their
        surface's thickness is not a variable, a solve or a pickup, and for an edge both surfaces are plain
        planes without shape variables (a plane-parallel plate: its edge is its fixed centre thickness).
        A violated one adds a constant to the merit function. Conservative: multi-configuration systems,
        per-configuration operands and spacer-expansion variables are never reported."""
        s = self.base.surfaces
        if self.base.multi_config is not None or any(v.parameter == "mount_cte" for v in self.variables):
            return []
        thick = {v.surface_id for v in self.variables if v.parameter == "thickness"}
        shape = {v.surface_id for v in self.variables if v.parameter != "thickness"}

        def plane(sf) -> bool:
            return sf.type == "standard" and sf.radius is None and sf.curvature_solve is None and sf.id not in shape

        out = []
        for k, o in enumerate(self.operands):
            if o.type not in ("min_thickness", "max_thickness", "min_edge_thickness") or o.configuration is not None:
                continue
            i = self.index_of.get(o.surface_id or "")
            if i is None or i + 1 >= len(s) or s[i].id in thick or s[i].thickness_solve is not None or s[i].thickness is None:
                continue
            if o.type == "min_edge_thickness" and not (plane(s[i]) and plane(s[i + 1])):
                continue
            out.append(k)
        return out

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        lo = np.array([-np.inf if v.min is None else v.min for v in self.variables])
        hi = np.array([np.inf if v.max is None else v.max for v in self.variables])
        return lo, hi

    def system_for(self, x: np.ndarray) -> OpticalSystem:
        d = apply_values(self.base_dict, self.variables, x, self.index_of)
        return OpticalSystem.model_validate(d)

    def _pattern(self, rings: int):
        """Gaussian-quadrature pupil samples (px, py, area weights summing to 1)."""
        if rings not in self._pattern_cache:
            self._pattern_cache[rings] = gauss_pupil(rings)
        return self._pattern_cache[rings]

    def operand_sizes(self, system: OpticalSystem) -> list[int]:
        sizes = []
        nf = len(system.fields)
        nw = len(system.wavelengths)
        for k_op, o in enumerate(self.operands):
            if self.roles[k_op] == "constraint":
                sizes.append(1)
            elif o.type == "rms_spot":
                px, _, _ = self._pattern(o.rings)
                fcount = nf if o.field is None else 1
                wcount = nw if o.wavelength is None else 1
                sizes.append(2 * len(px) * fcount * wcount)
            elif o.type == "rms_wavefront":
                px, _, _ = self._pattern(o.rings)
                fcount = nf if o.field is None else 1
                wcount = nw if o.wavelength is None else 1
                sizes.append(len(px) * fcount * wcount)
            else:
                sizes.append(1)
        return sizes

    def evaluate(self, x: np.ndarray) -> tuple[np.ndarray, list[dict]]:
        """Return (residual vector, operand breakdown)."""
        self.evaluations += 1
        if self._sizes is None:
            self._sizes = self.operand_sizes(self.base)
        sizes = self._sizes
        res_parts: list[np.ndarray] = []
        breakdown: list[dict] = []
        try:
            base_system = self.system_for(x)
        except (ValueError, ArithmeticError) as exc:
            for o, n in zip(self.operands, sizes):
                res_parts.append(np.full(n, FAILED_SYSTEM_PENALTY * self._weight_scale(o) / math.sqrt(n)))
                breakdown.append({"type": o.type, "value": None, "target": o.target, "weight": o.weight, "error": str(exc)})
            return self._finish(res_parts, breakdown)
        active = base_system.multi_config.active if base_system.multi_config else 0
        contexts: dict[int, Any] = {}

        def context(k: int):
            """Compiled system, pupil and per-evaluation caches for configuration k."""
            if k not in contexts:
                try:
                    from ..configs import with_active

                    system_k = with_active(base_system, k)
                    cs_k = compile_system(system_k, self.custom_materials, self.index_offsets)
                    contexts[k] = {"cs": cs_k, "pupil": compute_pupil(cs_k), "system": cs_k.model, "pcache": {}, "sd": []}
                except (SystemError_, ValueError, ArithmeticError) as exc:
                    contexts[k] = {"error": str(exc)}
            return contexts[k]

        for k_op, (o, n) in enumerate(zip(self.operands, sizes)):
            scale = self._weight_scale(o)
            value: float | None = None
            err = None
            kc = active if o.configuration is None else o.configuration
            ctx = context(kc)
            if "error" in ctx:
                res_parts.append(np.full(n, FAILED_SYSTEM_PENALTY * scale / math.sqrt(n)))
                breakdown.append({"type": o.type, "value": None, "target": o.target, "weight": o.weight, "configuration": kc, "error": ctx["error"]})
                continue
            cs, pupil, system = ctx["cs"], ctx["pupil"], ctx["system"]
            self._aim_cache = self._aim_caches.setdefault(kc, {})
            prim = system.primary_wavelength

            def pdata(w: int, ctx=ctx):
                if w not in ctx["pcache"]:
                    ctx["pcache"][w] = paraxial_data(ctx["cs"], w)
                return ctx["pcache"][w]

            def semi_diameters(ctx=ctx):
                """Effective semi-diameters, computed once per evaluation and configuration."""
                if not ctx["sd"]:
                    from ..analysis.evaluate import auto_semi_diameters, effective_semi_diameters

                    ctx["sd"].append(effective_semi_diameters(ctx["cs"], auto_semi_diameters(ctx["cs"], ctx["pupil"], self._aim_cache)))
                return ctx["sd"][0]

            try:
                if o.type in ("rms_spot", "rms_wavefront"):
                    spot = o.type == "rms_spot"
                    r, value = self._rms_spot_residuals(cs, pupil, o) if spot else self._rms_wavefront_residuals(cs, pupil, o)
                    if o.target:
                        # a spot / wavefront of a given size: the single error RMS - target (fixed size: zero-padded)
                        r = np.zeros(n)
                        r[0] = value - o.target
                    res_parts.append(scale * r)
                    breakdown.append({"type": o.type, "value": value * 1e3 if spot else value, "unit": "um" if spot else "waves", "target": o.target, "weight": o.weight, "configuration": kc, "contribution": float((scale * r) @ (scale * r)), "failed_rays": self._failed})
                    continue
                w = prim if o.wavelength is None else o.wavelength
                if o.type in ("detector_size", "detector_power"):
                    from ..nsdirect import trace_direct

                    if "direct" not in ctx:
                        ctx["direct"] = trace_direct(cs, self.sources, self.detectors, seed=1, index_offsets=self.index_offsets)
                    enabled = [d for d in self.detectors if d.enabled]
                    det = ctx["direct"]["detectors"][next(k for k, d in enumerate(enabled) if d.id == o.detector_id)]
                    if o.type == "detector_power":
                        value = float(det["fraction"])
                        unit = ""
                    else:
                        wxy = det["plane"]["width_2sigma_mm"]
                        if wxy is None:
                            raise ValueError("no light reaches the detector plane")
                        value = 2.0 * {"sagittal": wxy[0], "tangential": wxy[1]}.get(o.direction, 0.5 * (wxy[0] + wxy[1]))
                        unit = "mm"
                    e = value - o.target
                    res_parts.append(np.array([scale * e]))
                    breakdown.append({"type": o.type, "value": value, "unit": unit, "target": o.target, "weight": o.weight, "configuration": kc, "contribution": float((scale * e) ** 2), "detector": det["name"], "power_fraction": det["fraction"], "rays": det["plane"]["rays"]})
                    continue
                if o.type == "surface_reflectance":
                    from ..analysis.coatings import surface_reflectance

                    if not o.surface_id or o.surface_id not in self.index_of:
                        raise ValueError("Surface reflectance operand needs a surface")
                    value = surface_reflectance(cs, self.index_of[o.surface_id], o.wavelength, o.field, max(3, o.rings))
                    e = value - o.target
                    res_parts.append(np.array([scale * e]))
                    breakdown.append({"type": o.type, "value": value, "target": o.target, "weight": o.weight, "configuration": kc, "contribution": float((scale * e) ** 2)})
                    continue
                if o.type == "throughput":
                    from ..analysis.throughput import transmission

                    tr = transmission(cs, rings=max(4, o.rings))
                    if o.field is None and o.wavelength is None:
                        value = tr["weighted_mean_total"]
                    else:
                        fsel = range(len(system.fields)) if o.field is None else [o.field]
                        wsel = range(len(system.wavelengths)) if o.wavelength is None else [o.wavelength]
                        vals = [tr["fields"][fi]["per_wavelength"][wi]["total"] for fi in fsel for wi in wsel]
                        value = float(np.mean(vals))
                    e = value - o.target
                    res_parts.append(np.array([scale * e]))
                    breakdown.append({"type": o.type, "value": value, "target": o.target, "weight": o.weight, "configuration": kc, "contribution": float((scale * e) ** 2)})
                    continue
                if o.type == "mtf":
                    from ..analysis.diffraction import mtf as mtf_analysis

                    if not o.frequency:
                        raise ValueError("MTF operand needs a frequency (cycles/mm)")
                    # one field, or (field None) the field-weighted mean over all fields
                    fields_sel = list(range(len(system.fields))) if o.field is None else [o.field]
                    m = mtf_analysis(cs, fields_sel, max_frequency=o.frequency, samples=2, grid=32, pad=4)
                    vals, fws = [], []
                    for fi, fr in zip(fields_sel, m["fields"]):
                        tv, sv = fr["tangential"][-1], fr["sagittal"][-1]
                        vals.append(tv if o.direction == "tangential" else sv if o.direction == "sagittal" else 0.5 * (tv + sv))
                        fws.append(system.fields[fi].weight)
                    value = float(np.average(vals, weights=fws)) if sum(fws) > 0 else float(np.mean(vals))
                    e = value - o.target
                    res_parts.append(np.array([scale * e]))
                    breakdown.append({"type": o.type, "value": value, "target": o.target, "weight": o.weight, "configuration": kc, "contribution": float((scale * e) ** 2)})
                    continue
                if o.type in ("efl", "bfl", "fnum", "working_fnum", "magnification"):
                    pd = pdata(w)
                    value = {
                        "efl": pd.efl,
                        "bfl": pd.bfl,
                        "fnum": pd.image_space_fnum,
                        "working_fnum": pd.working_fnum,
                        "magnification": pd.paraxial_magnification,
                    }[o.type]
                    if value is None:
                        raise ValueError(f"{o.type} undefined for this system")
                    e = value - o.target
                elif o.type in ("total_track", "max_total_track"):
                    value = pdata(prim).total_track
                    e = value - o.target if o.type == "total_track" else max(0.0, value - o.target)
                elif o.type == "axial_color":
                    from ..materials import LAMBDA_C, LAMBDA_F

                    value = self._axial_color(cs, pupil, LAMBDA_F, LAMBDA_C)
                    e = value - o.target
                elif o.type in ("distortion", "max_distortion"):
                    from ..analysis.aberrations import field_curvature_distortion

                    fc = field_curvature_distortion(cs, samples=2, wavelengths=[prim])
                    dv = fc["per_wavelength"][0]["distortion_percent"][-1]
                    if dv is None:
                        raise ValueError("distortion undefined")
                    value = dv
                    # max_distortion: |distortion| at the largest field at most the target (one-sided, %)
                    e = value - o.target if o.type == "distortion" else max(0.0, abs(value) - o.target)
                elif o.type in ("max_lateral_color", "min_relative_illumination", "max_cra"):
                    # at the operand's field, or the largest field (analysis/summary.py computes the same numbers)
                    from ..analysis.summary import chief_ray_angle_deg, largest_field, lateral_colour_mm, relative_illumination_at

                    f = largest_field(system) if o.field is None else o.field
                    if f is None:
                        raise ValueError(f"{o.type} needs an off-axis field")
                    if o.type == "max_lateral_color":
                        value = abs(lateral_colour_mm(cs, pupil, f)) * 1e3  # um: a 0.1 um excess weighs like 0.1 % of distortion
                        e = max(0.0, value - o.target)
                    elif o.type == "max_cra":
                        value = chief_ray_angle_deg(cs, pupil, f)  # degrees
                        e = max(0.0, value - o.target)
                    else:
                        value = relative_illumination_at(cs, f)  # fraction of the axis
                        e = max(0.0, o.target - value)
                elif o.type in ("min_thickness", "max_thickness"):
                    i = self.index_of[o.surface_id or ""]
                    value = float(system.surfaces[i].thickness or 0.0)
                    e = max(0.0, o.target - value) if o.type == "min_thickness" else max(0.0, value - o.target)
                elif o.type == "min_edge_thickness":
                    from ..analysis.evaluate import edge_thickness

                    i = self.index_of[o.surface_id or ""]
                    sd = semi_diameters()
                    h = max(sd[i], sd[i + 1])
                    value = edge_thickness(cs, i, h)
                    e = max(0.0, o.target - value)
                else:  # pragma: no cover
                    raise ValueError(f"Unsupported operand {o.type}")
            except (ValueError, ArithmeticError, SystemError_, KeyError) as exc:
                e = FAILED_SYSTEM_PENALTY
                err = str(exc)
            # n residuals in every evaluation (n > 1 only for a failed rms_spot / rms_wavefront here)
            res_parts.append(np.full(n, scale * e / math.sqrt(n)))
            extra = {"error": err} if err else {}
            if k_op in self.fixed:
                extra["fixed"] = True  # no variable can change it (fixed_operands)
            breakdown.append({"type": o.type, "value": value, "target": o.target, "weight": o.weight, "configuration": kc, "contribution": float((scale * e) ** 2), **extra})
        return self._finish(res_parts, breakdown)

    def _weight_scale(self, o: Operand) -> float:
        """sqrt(w / sum w): an operand's residual scale (0 for the weight-0 limits, which split mode replaces)."""
        return math.sqrt(o.weight / self.wsum) if self.wsum > 0 else 0.0

    def _finish(self, parts: list[np.ndarray], breakdown: list[dict]) -> tuple[np.ndarray, list[dict]]:
        """The residual vector. In split mode the objective blocks are rescaled to the objective weights and each
        constraint becomes its normalised signed value (module notes); the breakdown says which is which."""
        if not self.split:
            return np.concatenate(parts), breakdown
        f = math.sqrt(self.wsum / self.wsum_obj)
        out = []
        for k, (o, b, block) in enumerate(zip(self.operands, breakdown, parts)):
            if self.roles[k] == "objective":
                blk = np.asarray(block, dtype=float) * f
                b["role"] = "objective"
                if "contribution" in b:
                    b["contribution"] = float(blk @ blk)
                out.append(blk)
                continue
            v = None if b.get("error") else b.get("value")
            if v is not None:
                v = v / report_scale(o)  # the breakdown reports the spot in um; its target is in mm
            g = constraint_value(o, v)
            b.update(role="constraint", g=g, met=constraint_met(o, g), contribution=0.0)
            out.append(np.array([g]))
        return np.concatenate(out), breakdown

    def layout(self) -> tuple[np.ndarray, np.ndarray]:
        """Split mode: (mask of the objective entries in the residual vector, indices of the constraint entries)."""
        if self._layout is not None:
            return self._layout
        if self._sizes is None:
            self._sizes = self.operand_sizes(self.base)
        sizes = self._sizes
        mask = np.zeros(sum(sizes), dtype=bool)
        cidx = []
        i = 0
        for k, n in enumerate(sizes):
            if self.roles[k] == "objective":
                mask[i : i + n] = True
            else:
                cidx.append(i)
            i += n
        self._layout = (mask, np.array(cidx, dtype=int))
        return self._layout

    def objective_merit(self, r: np.ndarray) -> float:
        """The merit function of the objective operands only (split mode); the whole merit otherwise."""
        if not self.split:
            return float(math.sqrt(float(r @ r)))
        mask, _ = self.layout()
        ro = r[mask]
        return float(math.sqrt(float(ro @ ro)))

    def _rms_spot_residuals(self, cs, pupil, o: Operand) -> tuple[np.ndarray, float]:
        """Residuals sqrt(w_ray w_lambda / W) (x - ref) with Gaussian-quadrature
        ray weights: their sum of squares is the pupil-area-weighted,
        wavelength-weighted RMS^2 per field (then averaged with field weights).
        A field or wavelength the operand selects has weight 1 (its system weight
        may be 0: the operand then measures it anyway, it does not read 0)."""
        self._failed = 0  # rays that received the failure penalty (reported in the breakdown)
        px, py, pw = self._pattern(o.rings)
        system = cs.model
        fields = range(len(system.fields)) if o.field is None else [o.field]
        wls = range(len(system.wavelengths)) if o.wavelength is None else [o.wavelength]
        parts = []
        total_sq = 0.0
        groups = 0.0
        prim = system.primary_wavelength
        traced = {w: trace_fields(cs, w, fields, px, py, pupil, aim_cache=self._aim_cache, vignetting=True) for w in wls}  # all fields at once
        for fi, f in enumerate(fields):
            fw = 1.0 if o.field is not None else system.fields[f].weight
            blocks = []
            weights = []
            for w in wls:
                r = traced[w][fi]
                blocks.append((r.image_xy(), r.ok))
                weights.append(1.0 if o.wavelength is not None else system.wavelengths[w].weight)
            W = float(sum(weights))
            if o.reference == "chief":
                ch = trace_pupil(cs, prim, f, np.array([0.0]), np.array([0.0]), pupil, obscure=False)
                ref = ch.image_xy()[0] if ch.ok[0] else None
            else:
                num = np.zeros(2)
                den = 0.0
                for (xy, ok), ww in zip(blocks, weights):
                    if np.any(ok):
                        num += ww * (pw[ok, None] * xy[ok]).sum(0)
                        den += ww * pw[ok].sum()
                ref = num / den if den > 0 else None
            for (xy, ok), ww in zip(blocks, weights):
                self._failed += int((~ok).sum())
                if ref is None:
                    d = np.full((len(px), 2), FAILED_RAY_PENALTY)
                else:
                    d = np.where(ok[:, None], xy - ref, FAILED_RAY_PENALTY)
                sc = np.sqrt(pw * ww / W) if W > 0 else np.zeros_like(pw)
                block = (d * sc[:, None]).ravel()
                parts.append(block * math.sqrt(fw))
                total_sq += float(block @ block) * fw
            groups += fw
        g = groups if groups > 0 else 1.0
        r = np.concatenate(parts) / math.sqrt(g)
        return r, math.sqrt(total_sq / g)

    def _rms_wavefront_residuals(self, cs, pupil, o: Operand) -> tuple[np.ndarray, float]:
        """Residuals sqrt(a) (OPD - fit) / lambda with Gaussian-quadrature area weights a (times the
        wavelength weight / their sum): the sum of squares is the pupil-area RMS^2, wavelength- and
        field-weighted (module notes). All wavelengths of a field share the reference sphere of the chief
        ray at the reference wavelength (the primary one, or the operand's own wavelength), so lateral colour
        shows as a relative tilt and axial colour as a relative defocus; the fit removes each wavelength's
        piston and, with the centroid reference, the best common tilt (linear in the pupil coordinates).
        The result is in waves of the reference wavelength. The pupil is sampled through the fields'
        vignetting factors; failed rays contribute a one-wave penalty. A selected field or wavelength has
        weight 1 (as for the spot)."""
        from ..analysis.wavefront import opl_to_reference, reference_geometry

        self._failed = 0
        px, py, pw = self._pattern(o.rings)
        npx = len(px)
        system = cs.model
        fields = list(range(len(system.fields))) if o.field is None else [o.field]
        wls = list(range(len(system.wavelengths))) if o.wavelength is None else [o.wavelength]
        ref_w = system.primary_wavelength if o.wavelength is None else o.wavelength
        lam_mm = float(cs.wavelengths[ref_w]) * 1e-3
        ww = np.array([system.wavelengths[w].weight for w in wls], dtype=float) if len(wls) > 1 else np.ones(1)
        a = np.concatenate([pw * (x / ww.sum()) for x in ww]) if ww.sum() > 0 else np.tile(pw / len(wls), len(wls))
        # least-squares model: one piston per wavelength (+ a common tilt for the centroid reference)
        X = np.zeros((npx * len(wls), len(wls) + (2 if o.reference == "centroid" else 0)))
        for k in range(len(wls)):
            X[k * npx : (k + 1) * npx, k] = 1.0
        if o.reference == "centroid":
            X[:, -2] = np.tile(px, len(wls))
            X[:, -1] = np.tile(py, len(wls))
        traced = {w: trace_fields(cs, w, fields, px, py, pupil, aim_cache=self._aim_cache, vignetting=True) for w in wls}
        img = cs.n_surfaces - 1
        parts = []
        tot = 0.0
        fw_sum = 0.0
        for fi, f in enumerate(fields):
            fw = 1.0 if o.field is not None else system.fields[f].weight
            try:
                C, E, R, _, _ = reference_geometry(cs, ref_w, f, pupil)
            except SystemError_:  # the chief ray fails: no reference, every ray of the field gets the penalty
                C = E = None
                R = 0.0
            if C is not None and E is None:
                raise NotApplicable("Exit pupil at infinity (image-space telecentric): the spherical wavefront reference is undefined; use the RMS spot")
            O = np.full(npx * len(wls), np.nan)
            if E is not None:
                for k, w in enumerate(wls):
                    O[k * npx : (k + 1) * npx] = -opl_to_reference(cs, traced[w][fi], C, E, R, float(cs.n_after[w, img - 1]))
            ok = np.isfinite(O)
            fit = np.zeros_like(O)
            if ok.any():
                cols = [j for j in range(X.shape[1]) if np.any(ok & (X[:, j] != 0.0))]
                sw = np.sqrt(a[ok])
                coef, *_ = np.linalg.lstsq(X[ok][:, cols] * sw[:, None], O[ok] * sw, rcond=None)
                fit = X[:, cols] @ coef
            self._failed += int((~ok).sum())
            r = np.where(ok, (O - fit) / lam_mm, 1.0) * np.sqrt(a)
            parts.append(r * math.sqrt(fw))
            tot += float(r @ r) * fw
            fw_sum += fw
        g = fw_sum if fw_sum > 0 else 1.0
        return np.concatenate(parts) / math.sqrt(g), math.sqrt(tot / g)

    def _axial_color(self, cs, pupil, l1: float, l2: float) -> float:
        """Difference of paraxial image distances at two wavelengths (mm)."""
        from ..analysis.aberrations import chromatic_focal_shift

        res = chromatic_focal_shift(cs, l1 if l1 < l2 else l2, l2 if l2 > l1 else l1, samples=2)
        s = res["focal_shift_um"]
        return (s[-1] - s[0]) / 1e3 * (1 if l2 > l1 else -1)

    # ------------------------------------------------------------------
    def merit_from_residuals(self, r: np.ndarray) -> float:
        """The merit function: sqrt(sum r^2); in split mode that of the objective operands only."""
        return self.objective_merit(r)

    def merit(self, x: np.ndarray) -> float:
        r, _ = self.evaluate(x)
        return self.merit_from_residuals(r)
