"""OptiCore Studio HTTP API (version 1).

All endpoints live under /api/v1. Errors are structured:
    {"error": {"code": str, "message": str, "details": [...]}}
"""

from __future__ import annotations

import functools
import logging
import math
from typing import Any, Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import ENGINE_VERSION
from ..analysis.aberrations import chromatic_focal_shift, field_curvature_distortion, longitudinal_aberration, ray_fan
from ..analysis.diffraction import geometric_encircled_energy, mtf, psf
from ..analysis.evaluate import evaluate_system
from ..analysis.outline import system_outline
from ..analysis.focus import focus_status
from ..analysis.summary import compare_designs, design_summary
from ..analysis.thermal import thermal_analysis
from ..design import DesignError as FirstLensError, first_lens
from ..analysis.gaussian import gaussian_beam
from ..analysis.huygens import huygens_psf
from ..analysis.ghosts import ghost_analysis
from ..analysis.sweep import sweep
from ..polarization import polarization_pupil
from ..analysis.throughput import transmission
from ..analysis.wavefront import opd_fan, wavefront_map
from ..analysis.spot import spot_diagram
from ..jsonutil import jsonable
from ..materials import MaterialError, MaterialLibrary
from ..materials.dispersion import DispersionError
from ..materials.agf import catalog_name_from_filename, decode_agf, parse_agf
from ..materials.rii import parse_rii_catalog
from ..wave.fdtd import FdtdError
from ..wave.fdtd import spec_from_dict as fdtd_spec
from ..wave.fibermodes import FibreError
from ..wave.jobs import FdtdJobs
from ..wave.bpm import bpm
from ..wave.pop import physical_optics
from ..model import SCHEMA_VERSION, CoatingDefinition, OpticalSystem, Wavelength
from ..optimize.engine import validate_spec
from ..optimize.glass import split_variables
from ..optimize.jobs import JobManager
from ..optimize.merit import MeritFunction, Operand, OptimizationSpec, exact_constraints
from ..paraxial import paraxial_data, seidel_coefficients
from ..project import ProjectError, dump_project, load_project
from ..io.cad import CadError, export_system_cad, import_cad
from ..io.recognize import insert_elements, recognize_asset
from ..nonseq import build_scene, trace_nonsequential
from ..nssources import Detector, LightSource
from ..io.stl import StlError, parse_stl
from ..io.zmx import ZmxError, decode_zmx, parse_zmx
from ..thinfilm import COATINGS, coating_curve, coating_from_definition
from ..coatdesign import CoatingDesign, DesignError, TemplateKind, FitMode, Measurement, angular, design_from_builtin, design_from_coating, evaluate_design, fit_measurement, parse_formula, monte_carlo, optimize_design, recipe, template, to_coating_definition
from ..analysis.coatings import coating_performance, surface_context
from ..tolerance import GRADES, ToleranceError, ToleranceJobs, ToleranceSpec, default_spec
from ..samples import get_sample, list_samples
from ..system import NotApplicable, SystemError_, compile_system

log = logging.getLogger("opticore.api")

app = FastAPI(title="OptiCore Studio API", version=ENGINE_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173", "http://127.0.0.1:4173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

jobs = JobManager()
tol_jobs = ToleranceJobs()
fdtd_jobs = FdtdJobs()


def error(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": jsonable(details) if details is not None else []}})


@app.exception_handler(RequestValidationError)
async def _validation(_: Request, exc: RequestValidationError):
    details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
    return error(422, "VALIDATION_ERROR", "Request validation failed", details)


@app.exception_handler(SystemError_)
async def _system_error(_: Request, exc: SystemError_):
    if isinstance(exc, NotApplicable):
        return error(422, "NOT_APPLICABLE", str(exc))
    return error(422, "SYSTEM_ERROR", str(exc), [d.as_dict() for d in exc.diagnostics])


def refused(exc: Exception, code: str):
    """422 for an endpoint's own ValueError handling; a NotApplicable keeps its code (the UI shows it as such)."""
    return error(422, "NOT_APPLICABLE" if isinstance(exc, NotApplicable) else code, str(exc))


@app.exception_handler(MaterialError)
async def _material_error(_: Request, exc: MaterialError):
    return error(422, "MATERIAL_ERROR", str(exc))


@app.exception_handler(DispersionError)
async def _dispersion_error(_: Request, exc: DispersionError):
    return error(422, "DISPERSION_ERROR", str(exc))


@app.exception_handler(DesignError)
async def _design_error(_: Request, exc: DesignError):
    return error(422, "COATING_DESIGN_ERROR", str(exc))


@app.exception_handler(ProjectError)
async def _project_error(_: Request, exc: ProjectError):
    return error(422, "PROJECT_ERROR", str(exc))


@app.exception_handler(ZmxError)
async def _zmx_error(_: Request, exc: ZmxError):
    return error(422, "IMPORT_ERROR", str(exc))


@app.exception_handler(HTTPException)
async def _http_error(_: Request, exc: HTTPException):
    return error(exc.status_code, "BAD_REQUEST" if exc.status_code < 500 else "INTERNAL_ERROR", str(exc.detail))


@app.exception_handler(Exception)
async def _unexpected(_: Request, exc: Exception):
    log.exception("Unhandled error")
    return error(500, "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")


# ----------------------------------------------------------------------
class SystemRequest(BaseModel):
    system: OpticalSystem
    custom_materials: list[dict] = Field(default_factory=list)


class EvaluateRequest(SystemRequest):
    layout_rays: int = Field(default=7, ge=1, le=41)
    ring_rays: int = Field(default=8, ge=0, le=64)


class SpotRequest(SystemRequest):
    pattern: Literal["hexapolar", "square", "dithered"] = "hexapolar"
    density: int = Field(default=6, ge=1, le=64)
    reference: Literal["centroid", "chief"] = "centroid"


class FanRequest(SystemRequest):
    samples: int = Field(default=41, ge=3, le=401)


class FieldRequest(SystemRequest):
    samples: int = Field(default=21, ge=2, le=201)


class ChromaticRequest(SystemRequest):
    lambda_min: float | None = Field(default=None, gt=0)
    lambda_max: float | None = Field(default=None, gt=0)
    samples: int = Field(default=41, ge=2, le=401)


class WavefrontRequest(SystemRequest):
    field: int = Field(default=0, ge=0)
    wavelength: int | None = Field(default=None, ge=0)
    grid: int = Field(default=64, ge=16, le=256)
    zernike_terms: int = Field(default=37, ge=1, le=37)


class InterferogramRequest(SystemRequest):
    field: int = Field(default=0, ge=0)
    wavelength: int | None = Field(default=None, ge=0)
    grid: int = Field(default=128, ge=16, le=384)
    passes: Literal[1, 2] = 1
    tilt_x: float = Field(default=0.0, ge=-200.0, le=200.0, description="tilt fringes across the pupil diameter, x")
    tilt_y: float = Field(default=0.0, ge=-200.0, le=200.0)
    visibility: float = Field(default=1.0, gt=0.0, le=1.0)
    phase_steps: int = Field(default=4, ge=0, le=8, description="frames of the phase-shifting recovery (0: none, else 3 to 8)")


class SpectrometerRequest(SystemRequest):
    field: int = Field(default=0, ge=0, description="the slit point")
    wl_min_um: float | None = Field(default=None, gt=0.0, le=100.0)
    wl_max_um: float | None = Field(default=None, gt=0.0, le=100.0)
    points: int = Field(default=41, ge=3, le=201)
    density: int = Field(default=6, ge=2, le=12, description="rings of the hexapolar bundle")


class PsfRequest(SystemRequest):
    field: int = Field(default=0, ge=0)
    wavelength: int | None = Field(default=None, ge=0)
    grid: int = Field(default=64, ge=16, le=256)
    pad: int = Field(default=4, ge=2, le=8)


class MtfRequest(SystemRequest):
    kind: Literal["diffraction", "geometric"] = "diffraction"
    max_frequency: float | None = Field(default=None, gt=0)
    samples: int = Field(default=64, ge=4, le=512)
    grid: int = Field(default=64, ge=16, le=256)
    pad: int = Field(default=4, ge=2, le=8)


class EncircledRequest(SystemRequest):
    field: int = Field(default=0, ge=0)


class NsMixin(BaseModel):
    # the project's light sources and detectors, for the detector operands (nsdirect.py)
    sources: list[LightSource] = Field(default_factory=list, max_length=200)
    detectors: list[Detector] = Field(default_factory=list, max_length=200)

    def ns(self):
        return (self.sources, self.detectors) if (self.sources or self.detectors) else None


class MeritRequest(SystemRequest, NsMixin):
    optimization: OptimizationSpec


class IndexRequest(BaseModel):
    materials: list[str]
    wavelengths: list[float] = Field(min_length=1, max_length=2000)
    custom_materials: list[dict] = Field(default_factory=list)


class CurveRequest(BaseModel):
    materials: list[str] = Field(min_length=1, max_length=12)
    lambda_min: float = Field(default=0.4, gt=0)
    lambda_max: float = Field(default=0.8, gt=0)
    samples: int = Field(default=121, ge=2, le=2001)
    custom_materials: list[dict] = Field(default_factory=list)


class PauseRequest(BaseModel):
    paused: bool


class ImportRequest(BaseModel):
    filename: str = "lens.zmx"
    content_base64: str = Field(max_length=20_000_000)
    # ZMX: records of the user's imported glass catalogues, used for glasses that are not built in
    catalog_materials: list[dict] = Field(default_factory=list, max_length=20_000)


# ----------------------------------------------------------------------
@app.get("/api/v1/health")
def health():
    return {"status": "ok", "engine_version": ENGINE_VERSION, "schema_version": SCHEMA_VERSION}


@app.get("/api/v1/materials")
def materials():
    lib = MaterialLibrary()
    return {"materials": jsonable([m.summary() for m in lib.all()])}


@app.get("/api/v1/coating-examples")
def coating_examples():
    """Worked coating-design examples (materials/data/coating_examples.json, tools/coating_examples.py): published
    benchmark problems designed with the coating designer, with their reference results."""
    import json as _json
    from pathlib import Path as _Path

    path = _Path(__file__).resolve().parents[1] / "materials" / "data" / "coating_examples.json"
    if not path.exists():
        return {"examples": []}
    return jsonable(_json.loads(path.read_text(encoding="utf-8")))


@app.get("/api/v1/coatings")
def coatings():
    return {
        "coatings": [
            {
                "name": c.name,
                "description": c.description,
                "layers": [{"material": L.material, "index": L.index, "extinction": L.extinction, "thickness_nm": L.thickness_nm, "label": lab}
                           for L, lab in zip(c.layers, c.layer_labels or [""] * len(c.layers))],
                "substrate_index": None if c.substrate is None else c.substrate.real,
                "substrate_extinction": 0.0 if c.substrate is None else -c.substrate.imag,
                "builtin": True,
                "category": c.category,
                "design_nm": c.design_nm,
                "band_nm": list(c.band_nm) if c.band_nm else None,
                "angle_deg": c.angle_deg,
                "incident_index": c.incident_index,
                "design_substrate_index": c.substrate_index,
                "design_substrate_material": c.substrate_material or None,
                "spec": list(c.spec),
            }
            for c in COATINGS.values()
        ]
    }


class CoatingCurveRequest(BaseModel):
    name: str = ""
    definition: CoatingDefinition | None = None  # custom stack (takes precedence over `name`)
    custom_materials: list[dict] = Field(default_factory=list)
    mirror: bool = False  # use the coating's own substrate (n, k) and report the mirror reflectance
    incident_index: float = Field(1.0, ge=1.0, lt=4.0)  # lossless incident medium (e.g. glass for a rear-surface mirror)
    substrate_index: float = Field(1.52, ge=1.0, lt=4.0)
    lambda_min: float = Field(0.4, gt=0.1)
    lambda_max: float = Field(0.8, lt=20.0)
    angle_deg: float = Field(0.0, ge=0.0, lt=90.0)
    samples: int = Field(81, ge=2, le=1001)


@app.post("/api/v1/coatings/curve")
def coatings_curve(req: CoatingCurveRequest):
    if req.lambda_max <= req.lambda_min:
        raise HTTPException(400, "lambda_max must exceed lambda_min")
    try:
        if req.definition is not None:
            lib = MaterialLibrary(req.custom_materials)
            coat = coating_from_definition(req.definition, lib)
            if coat.name in COATINGS:
                raise ValueError(f"'{coat.name}' is a built-in coating name")
            return coating_curve(coat, req.substrate_index, req.lambda_min, req.lambda_max, req.samples, req.angle_deg, n0=req.incident_index, mirror=req.mirror)
        return coating_curve(req.name, req.substrate_index, req.lambda_min, req.lambda_max, req.samples, req.angle_deg, n0=req.incident_index, mirror=req.mirror)
    except (ValueError, MaterialError, DispersionError) as exc:
        raise HTTPException(400, str(exc)) from exc


class CoatingAnalysisParams(BaseModel):
    lambda_min_nm: float = Field(400.0, gt=50.0, le=50000.0)
    lambda_max_nm: float = Field(800.0, gt=50.0, le=50000.0)
    samples: int = Field(241, ge=5, le=2001)
    angle_deg: float = Field(0.0, ge=0.0, lt=90.0)
    angles_deg: list[float] = Field(default_factory=list, max_length=6, description="extra angles of incidence overlaid on the spectrum")
    reference_nm: float | None = Field(None, gt=50.0, le=50000.0, description="wavelength of the field, angle and profile views")
    band_nm: tuple[float, float] | None = None
    field_pol: Literal["s", "p"] = "s"
    illuminant: Literal["D65", "D50", "D55", "D75", "A", "C", "F2", "F7", "F11"] = "D65"
    observer: Literal["2", "10"] = "2"


class CoatingAnalyzeRequest(CoatingAnalysisParams):
    name: str = ""
    definition: CoatingDefinition | None = None  # custom stack (takes precedence over `name`)
    custom_materials: list[dict] = Field(default_factory=list)
    mirror: bool = False
    incident_index: float = Field(1.0, ge=1.0, lt=4.0)
    substrate_material: str = ""
    substrate_index: float = Field(1.52, gt=0.0, le=10.0)
    substrate_extinction: float = Field(0.0, ge=0.0, le=100.0)
    back_side: bool = False


def _coating_analysis(stack, req: CoatingAnalysisParams):
    from ..coatanalysis import analyze

    return jsonable(analyze(stack, req.lambda_min_nm, req.lambda_max_nm, req.samples, req.angle_deg, req.angles_deg, req.reference_nm, req.band_nm, req.field_pol, req.illuminant, req.observer))


@app.post("/api/v1/coatings/analyze")
def coatings_analyze(req: CoatingAnalyzeRequest):
    """Spectra, angle curves, phase, GD/GDD, colour, field and index profile of a built-in or project coating."""
    from ..coatanalysis import CoatingAnalysisError, stack_from_coating
    from ..thinfilm import get_coating

    lib = MaterialLibrary(req.custom_materials)
    try:
        if req.definition is not None:
            coat = coating_from_definition(req.definition, lib)
        else:
            coat = get_coating(req.name)
            if coat is None:
                raise ValueError("Give a coating name or definition")
        sub = {"material": req.substrate_material} if req.substrate_material else {"index": req.substrate_index, "extinction": req.substrate_extinction}
        stack = stack_from_coating(coat, lib, req.incident_index, sub, req.mirror, req.back_side)
        return _coating_analysis(stack, req)
    except (CoatingAnalysisError, ValueError, MaterialError, DispersionError) as exc:
        return error(422, "COATING", str(exc))


@app.post("/api/v1/materials/resolve")
def materials_resolve(req: IndexRequest):
    lib = MaterialLibrary(req.custom_materials)
    out = {}
    for name in req.materials:
        mat_vals = []
        warnings = []
        for lam in req.wavelengths:
            mat_vals.append(lib.index(name, lam))
            if name.upper() not in ("AIR", "VACUUM", "") and not lib.get(name).in_range(lam):
                warnings.append(f"{lam} um outside data range (extrapolated)")
        out[name] = {"index": mat_vals, "warnings": warnings}
    return jsonable({"wavelengths": req.wavelengths, "materials": out})


@app.post("/api/v1/materials/curves")
def material_curves(req: CurveRequest):
    if req.lambda_max <= req.lambda_min:
        raise HTTPException(422, "lambda_max must exceed lambda_min")
    lib = MaterialLibrary(req.custom_materials)
    lams = np.linspace(req.lambda_min, req.lambda_max, req.samples)
    curves = []
    for name in req.materials:
        if name.upper() in ("AIR", "VACUUM"):
            curves.append({"name": name, "index": [1.0] * len(lams), "in_range": [True] * len(lams)})
            continue
        m = lib.get(name)
        curves.append(
            {
                "name": m.name,
                "index": [m.index(float(l)) for l in lams],
                "k": [float(x) for x in m.k(lams)] if m.extinction_table else None,
                "in_range": [m.in_range(float(l)) for l in lams],
                "summary": m.summary(),
            }
        )
    return jsonable({"wavelength_um": lams, "curves": curves})


@app.post("/api/v1/materials/agf")
def material_agf(req: ImportRequest):
    """Parse a glass catalogue (AGF). Stateless: the browser keeps the catalogue (records and summaries)."""
    import base64
    import binascii

    try:
        data = base64.b64decode(req.content_base64, validate=True)
    except (binascii.Error, ValueError):
        return error(422, "IMPORT_ERROR", "File content is not valid base64")
    text = decode_agf(data)
    if not any(l.lstrip().upper().startswith("NM ") for l in text.splitlines()):
        return error(422, "IMPORT_ERROR", "Not an AGF glass catalogue (no NM records found)")
    cat = parse_agf(text, catalog_name_from_filename(req.filename), req.filename)
    summaries = []
    for rec in cat.records:
        summaries.append(MaterialLibrary([rec]).get(rec["name"]).summary())
    return jsonable({"catalog": cat.name, "filename": req.filename, "comments": cat.comments[:20], "records": cat.records, "summaries": summaries, "diagnostics": [d.as_dict() for d in cat.diagnostics]})


class RiiFile(BaseModel):
    path: str = Field(max_length=300)
    content: str


class RiiRequest(BaseModel):
    catalog: str = Field(min_length=1, max_length=40)
    files: list[RiiFile] = Field(max_length=5000)


@app.post("/api/v1/materials/rii")
def material_rii(req: RiiRequest):
    """Convert one maker's refractiveindex.info YAML pages (downloaded by the browser) into a glass
    catalogue. Stateless, like the AGF import: the browser keeps the result."""
    if not req.files:
        return error(422, "IMPORT_ERROR", "No refractiveindex.info files given")
    name = catalog_name_from_filename(req.catalog)
    cat = parse_rii_catalog([(f.path, f.content) for f in req.files], name)
    summaries = [MaterialLibrary([rec]).get(rec["name"]).summary() for rec in cat.records]
    return jsonable({"catalog": cat.name, "filename": "refractiveindex.info", "comments": cat.comments, "records": cat.records, "summaries": summaries, "diagnostics": [d.as_dict() for d in cat.diagnostics]})


@app.post("/api/v1/materials/validate")
def material_validate(rec: dict):
    lib = MaterialLibrary([rec])
    return jsonable({"material": lib.get(rec.get("name", "")).summary()})


@app.post("/api/v1/system/evaluate")
def system_evaluate(req: EvaluateRequest):
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(evaluate_system(cs, req.layout_rays, req.ring_rays))


class FirstLensRequest(BaseModel):
    focal_length: float = Field(gt=0, le=100000)
    f_number: float = Field(ge=0.5, le=1000)
    half_field_deg: float = Field(default=0.0, ge=0, le=60)
    wavelengths: list[float] = Field(min_length=1, max_length=24)
    primary: int = Field(default=0, ge=0)
    kind: Literal["singlet", "doublet"] = "singlet"
    crown: str = "N-BK7"
    flint: str = "F2"
    name: str | None = None
    custom_materials: list[dict] = Field(default_factory=list)


@app.post("/api/v1/design/first-lens")
def design_first_lens(req: FirstLensRequest):
    """Starting prescription for a first lens: best-form singlet or thin-lens achromat made thick (design.py)."""
    try:
        project, extra = first_lens(req.focal_length, req.f_number, req.half_field_deg, req.wavelengths, req.primary, req.kind, req.crown, req.flint, req.custom_materials, req.name)
    except FirstLensError as exc:
        return error(422, "DESIGN_ERROR", str(exc))
    return {"project": dump_project(project), **jsonable(extra)}


class FocusRequest(SystemRequest):
    density: int = Field(default=6, ge=2, le=20)


@app.post("/api/v1/analysis/focus")
def analysis_focus(req: FocusRequest):
    """Distance of the image surface from the best polychromatic RMS focus (closed form, see analysis/focus.py)."""
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(focus_status(cs, req.density))


class SummaryRequest(SystemRequest):
    mtf_frequency: float | None = Field(default=None, gt=0, description="cycles/mm; default: half the sensor Nyquist, else a quarter of the cutoff")


@app.post("/api/v1/analysis/summary")
def analysis_summary(req: SummaryRequest):
    """Key numbers of a design: spot, MTF, distortion, lateral and axial colour, field of view, relative illumination,
    chief-ray angle, length and thinnest edges, each from the normal analysis (analysis/summary.py)."""
    return jsonable(design_summary(req.system, req.custom_materials, req.mtf_frequency))


class CompareRequest(BaseModel):
    before: OpticalSystem
    after: OpticalSystem
    custom_materials: list[dict] = Field(default_factory=list)


@app.post("/api/v1/optimize/compare")
def optimize_compare(req: CompareRequest):
    """Before/after numbers of an optimisation (or any two designs) and what got worse (analysis/summary.py)."""
    return jsonable(compare_designs(req.before, req.after, req.custom_materials))


class ThermalRequest(SystemRequest):
    variable: Literal["temperature", "pressure"] = "temperature"
    start: float = Field(default=-20.0, ge=-273.0, le=1000.0)
    stop: float = Field(default=60.0, ge=-273.0, le=1000.0)
    steps: int = Field(default=9, ge=2, le=41)
    density: int = Field(default=6, ge=2, le=20)


@app.post("/api/v1/analysis/thermal")
def analysis_thermal(req: ThermalRequest):
    """Focus shift, EFL and RMS spot across a temperature or pressure range (analysis/thermal.py)."""
    if req.variable == "pressure" and (req.start < 0 or req.stop < 0):
        raise SystemError_("Pressure must not be negative")
    return jsonable(thermal_analysis(req.system, req.custom_materials, req.variable, req.start, req.stop, req.steps, req.density))


class ConvertQRequest(SystemRequest):
    surface: int = Field(ge=1)
    to: Literal["qcon", "qbfs"] = "qcon"
    terms: int | None = Field(default=None, ge=1, le=30)
    norm_radius: float | None = Field(default=None, gt=0.0)  # default: the surface's effective semi-diameter


@app.post("/api/v1/surface/convert-q")
def convert_q(req: ConvertQRequest):
    """Rewrite an even-asphere surface as Qcon (exact) or Qbfs (least squares), with the sag residual (qpoly.py)."""
    from ..analysis.evaluate import auto_semi_diameters, effective_semi_diameters
    from ..paraxial import compute_pupil
    from ..qpoly import convert_surface

    if req.surface >= len(req.system.surfaces) - 1:
        return error(422, "CONVERT_Q", "Choose a surface between the object and the image")
    rn = req.norm_radius
    if rn is None:
        cs = compile_system(req.system, req.custom_materials)
        rn = float(effective_semi_diameters(cs, auto_semi_diameters(cs, compute_pupil(cs)))[req.surface])
    try:
        return jsonable(convert_surface(req.system.surfaces[req.surface].model_dump(), req.to, rn, req.terms))
    except ValueError as exc:
        return refused(exc, "CONVERT_Q")


@app.post("/api/v1/system/mounts")
def system_mounts(req: SystemRequest):
    """Mount tree displacements at the system's environment (environment.py)."""
    from ..environment import mount_report

    return jsonable(mount_report(req.system, req.custom_materials))


@app.post("/api/v1/system/outline")
def system_outline_endpoint(req: SystemRequest):
    """Thumbnail outline (drawing data) of a system: glass outlines, mirrors, stop, image and a few real rays."""
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(system_outline(cs))


@app.post("/api/v1/analysis/paraxial")
def analysis_paraxial(req: SystemRequest):
    cs = compile_system(req.system, req.custom_materials)
    data = [paraxial_data(cs, w).as_dict() for w in range(len(cs.wavelengths))]
    try:
        seidel = seidel_coefficients(cs)
    except Exception as exc:  # pragma: no cover
        seidel = {"error": str(exc)}
    return jsonable({"per_wavelength": data, "seidel": seidel, "method": "paraxial (first-order) y-nu trace; Seidel third-order sums"})


@app.post("/api/v1/analysis/spot")
def analysis_spot(req: SpotRequest):
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(spot_diagram(cs, req.pattern, req.density, req.reference))


@app.post("/api/v1/analysis/rayfan")
def analysis_rayfan(req: FanRequest):
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(ray_fan(cs, req.samples))


@app.post("/api/v1/analysis/field")
def analysis_field(req: FieldRequest):
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(field_curvature_distortion(cs, req.samples))


@app.post("/api/v1/analysis/longitudinal")
def analysis_longitudinal(req: FieldRequest):
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(longitudinal_aberration(cs, req.samples))


@app.post("/api/v1/analysis/chromatic")
def analysis_chromatic(req: ChromaticRequest):
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(chromatic_focal_shift(cs, req.lambda_min, req.lambda_max, req.samples))


def _check_field_wl(system: OpticalSystem, field: int, wavelength: int | None):
    if field >= len(system.fields):
        raise HTTPException(422, f"field index {field} out of range")
    if wavelength is not None and wavelength >= len(system.wavelengths):
        raise HTTPException(422, f"wavelength index {wavelength} out of range")


@app.post("/api/v1/analysis/wavefront")
def analysis_wavefront(req: WavefrontRequest):
    _check_field_wl(req.system, req.field, req.wavelength)
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(wavefront_map(cs, req.field, req.wavelength, req.grid, req.zernike_terms))


@app.post("/api/v1/analysis/interferogram")
def analysis_interferogram(req: InterferogramRequest):
    """Interferogram of the wavefront against a tilted reference sphere, and its phase-shifting recovery."""
    from ..analysis.interferometry import interferogram

    _check_field_wl(req.system, req.field, req.wavelength)
    cs = compile_system(req.system, req.custom_materials)
    try:
        return jsonable(interferogram(cs, req.field, req.wavelength, req.grid, req.passes, req.tilt_x, req.tilt_y, req.visibility, req.phase_steps))
    except SystemError_:
        raise  # NOT_APPLICABLE and system errors keep their codes
    except ValueError as exc:
        return error(422, "INTERFEROGRAM", str(exc))


@app.post("/api/v1/analysis/spectrometer")
def analysis_spectrometer(req: SpectrometerRequest):
    """Calibration, linear dispersion and spectral resolution over a wavelength sweep (analysis/spectrometer.py)."""
    from ..analysis.spectrometer import spectrometer

    _check_field_wl(req.system, req.field, None)
    compile_system(req.system, req.custom_materials)  # the system's own errors first
    try:
        return jsonable(spectrometer(req.system, req.custom_materials, req.field, req.wl_min_um, req.wl_max_um, req.points, req.density))
    except SystemError_:
        raise  # NOT_APPLICABLE and system errors keep their codes
    except ValueError as exc:
        return error(422, "SPECTROMETER", str(exc))


@app.post("/api/v1/analysis/opdfan")
def analysis_opdfan(req: FanRequest):
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(opd_fan(cs, req.samples))


@app.post("/api/v1/analysis/psf")
def analysis_psf(req: PsfRequest):
    _check_field_wl(req.system, req.field, req.wavelength)
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(psf(cs, req.field, req.wavelength, req.grid, req.pad))


class HuygensRequest(SystemRequest):
    field: int = Field(0, ge=0)
    wavelength: int | None = None
    pupil_samples: int = Field(64, ge=16, le=256)
    image_samples: int = Field(65, ge=16, le=256)
    image_delta_um: float | None = Field(None, gt=0.0, le=1e4)
    defocus_mm: float = Field(0.0, ge=-1e3, le=1e3)
    transmission: bool = False


@app.post("/api/v1/analysis/huygens")
def analysis_huygens(req: HuygensRequest):
    _check_field_wl(req.system, req.field, req.wavelength)
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(huygens_psf(cs, req.field, req.wavelength, req.pupil_samples, req.image_samples, req.image_delta_um, req.defocus_mm, req.transmission))


@app.post("/api/v1/analysis/mtf")
def analysis_mtf(req: MtfRequest):
    cs = compile_system(req.system, req.custom_materials)
    res = mtf(cs, None, req.max_frequency, req.samples, req.grid, req.pad, req.kind)
    if req.system.sensor is not None:
        from ..analysis.imaging import sensor_mtf_terms

        res["sensor"] = sensor_mtf_terms(res, req.system.sensor)
    return jsonable(res)


class RelativeIlluminationRequest(SystemRequest):
    points: int = Field(11, ge=2, le=101)
    rings: int = Field(8, ge=2, le=20)
    transmission: bool = True
    wavelength: int | None = None


@app.post("/api/v1/analysis/relative-illumination")
def analysis_relative_illumination(req: RelativeIlluminationRequest):
    """Relative illumination from the projected solid angle of real-ray beams (analysis/imaging.py)."""
    from ..analysis.imaging import relative_illumination

    _check_field_wl(req.system, 0, req.wavelength)
    cs = compile_system(req.system, req.custom_materials)
    try:
        return jsonable(relative_illumination(cs, req.points, req.rings, req.transmission, req.wavelength))
    except ValueError as exc:
        return refused(exc, "RELATIVE_ILLUMINATION")


class ImageSimRequest(SystemRequest):
    scene: Literal["siemens", "bars", "grid", "checker", "edge"] = "siemens"
    crop_px: int = Field(256, ge=16, le=512)
    oversample: int = Field(3, ge=1, le=7)
    grid: int = Field(5, ge=1, le=9)
    exposure: float = Field(0.7, gt=0.0, le=1.0)
    noise: bool = True
    seed: int = 1
    psf_grid: int = Field(64, ge=32, le=128)


@app.post("/api/v1/analysis/image-simulation")
def analysis_image_simulation(req: ImageSimRequest):
    """Image of a test scene through the system onto the sensor (analysis/imaging.py)."""
    from ..analysis.imaging import simulate_image

    try:
        return jsonable(simulate_image(req.system, req.custom_materials, req.scene, req.crop_px, req.oversample, req.grid, req.exposure, req.noise, req.seed, req.psf_grid))
    except ValueError as exc:
        return refused(exc, "IMAGE_SIMULATION")


class PhotoData(BaseModel):
    """The user's photo for the live image: sRGB bytes R, G, B per pixel, row-major from the top row (base64)."""

    width: int = Field(ge=2, le=1024)
    height: int = Field(ge=2, le=1024)
    data: str


class LiveImageRequest(SystemRequest):
    scene: Literal["siemens", "bars", "grid", "checker", "edge"] = "siemens"
    photo: PhotoData | None = None
    width: int = Field(192, ge=16, le=1024)
    quality: Literal["preview", "full"] = "preview"
    channels_um: list[float] | None = Field(default=None, min_length=3, max_length=3)
    zoom: float = Field(1.0, ge=1.0, le=256.0)
    center: tuple[float, float] = (0.0, 0.0)
    # the client's view (a random id per browser tab): a newer request on it stops this one
    channel: str | None = Field(default=None, max_length=64)


live_channels = None


@app.post("/api/v1/analysis/live-image")
def analysis_live_image(req: LiveImageRequest):
    """Colour image of a test scene or a photo through the system (analysis/liveimage.py)."""
    global live_channels
    from ..analysis.liveimage import Channels, Superseded, decode_photo, render

    if live_channels is None:
        live_channels = Channels()
    stale = live_channels.begin(req.channel)
    try:
        photo = decode_photo(req.photo.width, req.photo.height, req.photo.data) if req.photo else None
        return jsonable(render(req.system, req.custom_materials, scene_name=req.scene, photo=photo, width=req.width, quality=req.quality, channels_um=req.channels_um, zoom=req.zoom, center=req.center, stale=stale))
    except Superseded as exc:
        return error(409, "SUPERSEDED", str(exc))
    except ValueError as exc:  # also invalid base64 (binascii.Error)
        return refused(exc, "LIVE_IMAGE")


@app.post("/api/v1/analysis/encircled")
def analysis_encircled(req: EncircledRequest):
    _check_field_wl(req.system, req.field, None)
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(geometric_encircled_energy(cs, req.field))


@app.post("/api/v1/analysis/throughput")
def analysis_throughput(req: SystemRequest):
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(transmission(cs))


# ---------------------------------------------------------------------- wave optics
class FibreRequest(BaseModel):
    wavelength_um: float = Field(gt=0.05, le=100.0)
    core_radius_um: float = Field(gt=0.0, le=5000.0)
    n_core: float | None = Field(None, gt=1.0)
    na: float | None = Field(None, gt=0.0, lt=2.0)
    dn: float | None = Field(None, gt=0.0, lt=1.0, description="core index above the cladding, the same at every wavelength")
    n_clad: float | None = Field(None, gt=1.0)
    clad_material: str | None = None
    custom_materials: list[dict] = Field(default_factory=list)
    vector: bool = True
    # radial profile (wave/fibreprofile.py): step (exact vector modes), graded power law, or rings (r_um, dn)
    profile_kind: Literal["step", "graded", "layers"] = "step"
    alpha: float = Field(2.0, gt=0.0, le=100.0)
    layers: list[tuple[float, float]] = Field(default_factory=list, max_length=40)


class FibreDispersionRequest(FibreRequest):
    wl_min_um: float = Field(gt=0.05, le=100.0)
    wl_max_um: float = Field(gt=0.05, le=100.0)
    points: int = Field(41, ge=3, le=201)
    l: int = Field(0, ge=0, le=50)
    m: int = Field(1, ge=1, le=50)


class Fibre2dShape(BaseModel):
    kind: Literal["circle", "ellipse", "rect"] = "circle"
    x: float = 0.0
    y: float = 0.0
    r: float = Field(0.0, ge=0.0)
    rx: float = Field(0.0, ge=0.0)
    ry: float = Field(0.0, ge=0.0)
    w: float = Field(0.0, ge=0.0)
    h: float = Field(0.0, ge=0.0)
    angle_deg: float = 0.0
    n: float | None = Field(None, gt=0.0)
    material: str | None = None


class Fibre2dLattice(BaseModel):
    pitch_um: float = Field(gt=0.0)
    d_um: float = Field(gt=0.0)
    rings: int = Field(1, ge=1, le=8)
    n_hole: float | None = Field(1.0, gt=0.0)
    hole_material: str | None = None
    missing_centre: bool = True


class Fibre2dRequest(BaseModel):
    wavelength_um: float = Field(gt=0.05, le=100.0)
    n_background: float | None = Field(None, gt=0.0)
    background_material: str | None = None
    lattice: Fibre2dLattice | None = None
    shapes: list[Fibre2dShape] = Field(default_factory=list, max_length=200)
    window_um: float | None = Field(None, gt=0.0, le=2000.0)
    mesh_um: float | None = Field(None, gt=0.0)
    pml_um: float = Field(0.0, ge=0.0)
    polarisation: Literal["x", "y"] = "x"
    count: int = Field(6, ge=1, le=30)
    n_guess: float | None = Field(None, gt=0.0)
    refine: bool = False
    custom_materials: list[dict] = Field(default_factory=list)


def _fibre_indices_req(req: FibreRequest) -> tuple[float, float]:
    n2 = req.n_clad
    if req.clad_material:
        n2 = MaterialLibrary(req.custom_materials).index(req.clad_material, req.wavelength_um)
    if n2 is None:
        raise FibreError("Give the cladding index or a cladding material")
    if req.n_core is not None:
        return float(req.n_core), float(n2)
    if req.na is None:
        raise FibreError("Give the core index or the numerical aperture")
    return math.sqrt(n2 * n2 + req.na * req.na), float(n2)


def _material_range(lib: MaterialLibrary, name: str) -> tuple[float, float]:
    d = lib.get(name).dispersion
    return float(d.lambda_min or 0.0), float(d.lambda_max or 0.0)


@app.post("/api/v1/wave/fiber_modes")
def wave_fiber_modes(req: FibreRequest):
    """Modes of a step (exact vector and LP), graded or layered profile, LP01 field diameter, effective area and the
    LP11 cut-off (wave/fibreapi.py)."""
    from ..wave.fibreapi import profile_modes

    lib = MaterialLibrary(req.custom_materials)
    try:
        if req.profile_kind == "step" and req.dn is None:
            _fibre_indices_req(req)  # checks that the core and cladding indices are given
        return jsonable(profile_modes(req.model_dump(), lambda name, lam: lib.index(name, lam), lambda name: _material_range(lib, name)))
    except (FibreError, MaterialError) as exc:
        return error(422, "FIBRE_ERROR", str(exc))


class RcwaMedium(BaseModel):
    n: float | None = Field(None, gt=0.0, le=100.0)
    k: float = Field(0.0, ge=0.0, le=100.0)
    material: str | None = None


class RcwaShape(BaseModel):
    kind: Literal["rectangle", "ellipse"] = "rectangle"
    cx_um: float = Field(ge=-10000.0, le=10000.0)
    cy_um: float = Field(ge=-10000.0, le=10000.0)
    a_um: float = Field(gt=0.0, le=10000.0)
    b_um: float = Field(gt=0.0, le=10000.0)
    angle_deg: float = Field(0.0, ge=-360.0, le=360.0)
    medium: RcwaMedium | None = None


class RcwaLayer(BaseModel):
    kind: Literal["uniform", "lamellar", "sinusoidal", "sawtooth", "trapezoid", "pattern"] = "lamellar"
    thickness_um: float = Field(ge=0.0, le=1000.0)
    fill: float = Field(0.5, ge=0.0, le=1.0)
    fill_top: float = Field(0.5, ge=0.0, le=1.0)
    fill_bottom: float = Field(0.5, ge=0.0, le=1.0)
    slices: int = Field(10, ge=1, le=200)
    ridge: RcwaMedium | None = None
    groove: RcwaMedium | None = None
    shapes: list[RcwaShape] = Field(default_factory=list, max_length=64)


class RcwaSweep(BaseModel):
    kind: Literal["wavelength", "angle"]
    start: float
    stop: float
    points: int = Field(51, ge=2, le=201)
    orders: list[int] = Field(default_factory=lambda: [-1, 0, 1], max_length=9)
    orders_2d: list[tuple[int, int]] = Field(default_factory=lambda: [(0, 0)], max_length=9)


class RcwaRequest(BaseModel):
    wavelength_um: float = Field(gt=0.05, le=100.0)
    period_um: float = Field(gt=0.0, le=10000.0)
    theta_deg: float = Field(0.0, ge=-89.9, le=89.9)
    phi_deg: float = Field(0.0, ge=-180.0, le=180.0)
    polarisation: Literal["TE", "TM", "unpolarised"] = "TE"
    harmonics: int = Field(20, ge=0, le=150)
    period_y_um: float | None = Field(None, gt=0.0, le=10000.0)
    harmonics_y: int = Field(5, ge=0, le=40)
    incident: RcwaMedium = Field(default_factory=lambda: RcwaMedium(n=1.0))
    substrate: RcwaMedium
    layers: list[RcwaLayer] = Field(default_factory=list, max_length=50)
    sweep: RcwaSweep | None = None
    custom_materials: list[dict] = Field(default_factory=list)


@app.post("/api/v1/wave/rcwa")
def wave_rcwa(req: RcwaRequest):
    """Diffraction efficiencies of a grating, or of a crossed grating or metasurface (period_y_um), by rigorous
    coupled-wave analysis (wave/rcwa.py, wave/rcwa2d.py, wave/rcwaapi.py)."""
    from ..wave.rcwa import RcwaError
    from ..wave.rcwaapi import analyse

    lib = MaterialLibrary(req.custom_materials)
    spec = req.model_dump()
    if req.sweep is not None and req.sweep.kind == "angle" and not (-89.9 <= min(req.sweep.start, req.sweep.stop) and max(req.sweep.start, req.sweep.stop) <= 89.9):
        return error(422, "RCWA", "Angles of a sweep must lie within ±89.9°")
    if req.sweep is not None and req.sweep.kind == "wavelength" and not min(req.sweep.start, req.sweep.stop) > 0.05:
        return error(422, "RCWA", "Wavelengths of a sweep must exceed 0.05 µm")
    try:
        return jsonable(analyse(spec, lambda name, lam: lib.index(name, lam), req.custom_materials))
    except (RcwaError, MaterialError) as exc:
        return error(422, "RCWA", str(exc))
    except np.linalg.LinAlgError as exc:
        return error(422, "RCWA", f"The coupled-wave system is singular at this setting ({exc}); change the wavelength or angle slightly")


@app.post("/api/v1/wave/fiber_dispersion")
def wave_fiber_dispersion(req: FibreDispersionRequest):
    """Effective index, group index and chromatic dispersion (material + waveguide) of one LP mode over a band."""
    from ..wave.fibreapi import dispersion_curve

    lib = MaterialLibrary(req.custom_materials)
    try:
        return jsonable(dispersion_curve(req.model_dump(), lambda name, lam: lib.index(name, lam), req.wl_min_um, req.wl_max_um, req.points, req.l, req.m, lambda name: _material_range(lib, name)))
    except (FibreError, MaterialError) as exc:
        return error(422, "FIBRE_ERROR", str(exc))


@app.post("/api/v1/wave/fiber2d/start")
def wave_fiber2d_start(req: Fibre2dRequest):
    """Full-vector modes of an arbitrary fibre cross-section (photonic crystal fibres), in the background."""
    from ..wave.fibreapi import MAX_CELLS_2D, cross_section, mesh_of, modes_2d

    spec = req.model_dump()
    lib = MaterialLibrary(spec.pop("custom_materials", []))
    index_of = lambda name, lam: lib.index(name, lam)  # noqa: E731
    try:
        cs = cross_section(spec, req.wavelength_um, index_of)  # input errors are reported here, before the job starts
        _, _, _, cells = mesh_of(spec, cs, req.wavelength_um)
        if cells > MAX_CELLS_2D:
            raise FibreError(f"The mesh would have {cells} cells along a side (at most {MAX_CELLS_2D}): use a coarser mesh or a smaller window")
    except (FibreError, MaterialError, ValueError) as exc:
        return error(422, "FIBRE_ERROR", str(exc))
    job = fdtd_jobs.start_fn(lambda progress, control: modes_2d(spec, index_of, progress=progress, control=control))
    return {"job_id": job.id}


class PopRequest(SystemRequest):
    source: dict = Field(default_factory=lambda: {"kind": "gaussian", "waist_x": 0.0052})
    wavelength: int | None = None
    target_offset: float = 0.0
    grid: int = Field(128, ge=32, le=512)
    out_grid: int = Field(128, ge=16, le=512)
    out_window: float | None = Field(None, gt=0)
    target_mode: dict | None = None
    detector_radius: float | None = Field(None, gt=0)
    side_view: bool = False  # the field along the system (meridional cut)
    # "pop": ray transfer through the lenses; "bpm": the wave propagated inside the glass
    # (rotationally symmetric beam propagation, wave/bpm.py)
    method: Literal["pop", "bpm"] = "pop"
    bpm_step_um: float | None = Field(None, gt=0.05, le=50.0)


@app.post("/api/v1/analysis/pop")
def analysis_pop(req: PopRequest):
    _check_field_wl(req.system, 0, req.wavelength)
    cs = compile_system(req.system, req.custom_materials)
    if req.source.get("kind") == "pupil":
        # a uniform collimated beam that fills the entrance pupil (object at infinity): the beam an imaging lens sees
        if req.system.surfaces[0].thickness is not None:
            return error(422, "POP_SOURCE", "A beam that fills the entrance pupil needs the object at infinity")
        from ..paraxial import compute_pupil

        req.source = {"kind": "tophat", "radius": float(compute_pupil(cs).r_ep)}
    try:
        if req.method == "bpm":
            res = bpm(cs, req.source, req.wavelength, req.target_offset, req.grid, req.target_mode, req.detector_radius, dz_um=req.bpm_step_um)
            if not req.side_view:
                res.pop("side", None)
            return jsonable(res)
        return jsonable(physical_optics(cs, req.source, req.wavelength, req.target_offset, req.grid, req.out_grid, req.out_window, req.target_mode, req.detector_radius, side_view=req.side_view))
    except (FibreError, KeyError, ValueError) as exc:
        if isinstance(exc, SystemError_):
            raise
        return error(422, "POP_ERROR", f"{type(exc).__name__}: {exc}")


class FdtdRequest(BaseModel):
    model_config = {"extra": "allow"}
    custom_materials: list[dict] = Field(default_factory=list)


@app.post("/api/v1/wave/fdtd/start")
def wave_fdtd_start(req: FdtdRequest):
    d = req.model_dump()
    lib = MaterialLibrary(d.pop("custom_materials", []))
    try:
        spec = fdtd_spec(d, index_of=lambda name, lam: lib.index(name, lam))
        job = fdtd_jobs.start(spec)
    except (FdtdError, KeyError, ValueError, TypeError) as exc:
        return error(422, "FDTD_CONFIG", f"{exc}")
    return {"job_id": job.id}


@app.get("/api/v1/wave/fiber2d/{job_id}")
@app.get("/api/v1/wave/fdtd/{job_id}")
def wave_fdtd_status(job_id: str):
    j = fdtd_jobs.get(job_id)
    if not j:
        return error(404, "JOB_NOT_FOUND", f"No FDTD job '{job_id}'")
    return fdtd_jobs.snapshot(j)


@app.post("/api/v1/wave/fiber2d/{job_id}/cancel")
@app.post("/api/v1/wave/fdtd/{job_id}/cancel")
def wave_fdtd_cancel(job_id: str):
    if not fdtd_jobs.cancel(job_id):
        return error(404, "JOB_NOT_FOUND", f"No running FDTD job '{job_id}'")
    return {"cancelled": True}


class GaussianRequest(SystemRequest):
    waist_radius: float = Field(1.0, gt=0, description="1/e^2 intensity radius (mm)")
    waist_distance: float = Field(0.0, description="waist position before surface 1 (mm); negative = virtual")
    wavelength: int | None = None
    m2: float = Field(1.0, ge=1.0, le=1000.0)
    samples: int = Field(60, ge=2, le=1000)


@app.post("/api/v1/analysis/gaussian")
def analysis_gaussian(req: GaussianRequest):
    _check_field_wl(req.system, 0, req.wavelength)
    cs = compile_system(req.system, req.custom_materials)
    from ..analysis.evaluate import auto_semi_diameters, effective_semi_diameters
    from ..paraxial import compute_pupil

    try:
        sd = [float(x) for x in effective_semi_diameters(cs, auto_semi_diameters(cs, compute_pupil(cs)))]
    except SystemError_:
        sd = None
    return jsonable(gaussian_beam(cs, req.waist_radius, req.waist_distance, req.wavelength, req.m2, req.samples, sd))


class PolarizationRequest(SystemRequest):
    field: int = Field(0, ge=0)
    wavelength: int | None = None
    grid: int = Field(15, ge=3, le=65)
    input: Literal["x", "y", "45", "-45", "rcp", "lcp", "unpolarized"] = "x"
    crystal_modes: Literal["sum", "prescription"] = "sum"


@app.post("/api/v1/analysis/polarization")
def analysis_polarization(req: PolarizationRequest):
    _check_field_wl(req.system, req.field, req.wavelength)
    cs = compile_system(req.system, req.custom_materials)
    try:
        return jsonable(polarization_pupil(cs, req.field, req.wavelength, req.grid, req.input, req.crystal_modes))
    except SystemError_:
        raise
    except ValueError as exc:
        return refused(exc, "POLARIZATION")


@app.post("/api/v1/system/vignetting")
def system_vignetting(req: SystemRequest):
    """Vignetting factors of every field from the fixed apertures (analysis/vignetting.py)."""
    from ..analysis.vignetting import vignetting_factors

    cs = compile_system(req.system, req.custom_materials)
    return jsonable(vignetting_factors(cs))


class VectorPsfRequest(SystemRequest):
    field: int = Field(0, ge=0)
    wavelength: int | None = None
    input: Literal["x", "y", "45", "-45", "rcp", "lcp", "radial", "azimuthal"] = "x"
    rings: int = Field(40, ge=8, le=96)
    grid: int = Field(81, ge=21, le=161)
    half_width_um: float | None = Field(None, gt=0.0, le=1e4)
    defocus_um: float = Field(0.0, ge=-1e4, le=1e4)
    section: bool = True
    crystal_modes: Literal["sum", "prescription"] = "sum"
    gaussian_fill: float | None = Field(None, gt=0.0, le=10.0)  # input field 1/e radius / pupil radius


@app.post("/api/v1/analysis/vector-psf")
def analysis_vector_psf(req: VectorPsfRequest):
    """Debye–Wolf vector PSF from the real rays (analysis/vectorpsf.py)."""
    from ..analysis.vectorpsf import vector_psf

    _check_field_wl(req.system, req.field, req.wavelength)
    cs = compile_system(req.system, req.custom_materials)
    try:
        return jsonable(vector_psf(cs, req.field, req.wavelength, req.input, req.rings, req.grid, req.half_width_um, req.defocus_um, req.section, req.crystal_modes, req.gaussian_fill))
    except SystemError_:
        raise
    except ValueError as exc:
        return refused(exc, "VECTOR_PSF")


class SweepParameter(BaseModel):
    surface_id: str
    parameter: Literal["curvature", "thickness", "conic", "asph_4", "asph_6", "asph_8", "asph_10", "asph_12", "decenter_x", "decenter_y", "tilt_x", "tilt_y", "tilt_z", "phase_1", "phase_2", "phase_3", "phase_4", "grating_frequency", "zern_1", "zern_2", "zern_3", "zern_4", "zern_5", "zern_6", "zern_7", "zern_8", "zern_9", "zern_10", "zern_11", "zern_12", "zern_13", "zern_14", "zern_15", "zern_16", "zern_17", "zern_18", "zern_19", "zern_20", "zern_21", "zern_22", "zern_23", "zern_24", "zern_25", "zern_26", "zern_27", "zern_28", "zern_29", "zern_30", "zern_31", "zern_32", "zern_33", "zern_34", "zern_35", "zern_36", "zern_37"]
    configuration: int | None = None
    start: float
    stop: float
    steps: int = Field(21, ge=2, le=401)


class SweepRequest(SystemRequest, NsMixin):
    parameters: list[SweepParameter] = Field(min_length=1, max_length=2)
    metrics: list[Operand] = Field(min_length=1, max_length=12)


@app.post("/api/v1/analysis/sweep")
def analysis_sweep(req: SweepRequest):
    try:
        return jsonable(sweep(req.system, [p.model_dump() for p in req.parameters], req.metrics, req.custom_materials, ns=req.ns()))
    except ValueError as exc:
        return refused(exc, "SWEEP_CONFIG")


class GhostRequest(SystemRequest):
    field: int = Field(0, ge=0)
    wavelength: int | None = None
    rings: int = Field(6, ge=2, le=16)


@app.post("/api/v1/analysis/ghosts")
def analysis_ghosts(req: GhostRequest):
    _check_field_wl(req.system, req.field, req.wavelength)
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(ghost_analysis(cs, req.custom_materials, req.field, req.wavelength, req.rings))


@app.post("/api/v1/optimize/merit")
def optimize_merit(req: MeritRequest):
    # exact constraints (optimize/constrained.py): the merit is the objective's, each constraint operand reports its
    # role, its normalised value g and whether it is met
    spec = split_variables(req.optimization)[0]
    exact = exact_constraints(spec)  # the optimiser's rule (merit.is_active: a weight-0 limit counts)
    try:
        mf = MeritFunction(req.system, spec, req.custom_materials, ns=req.ns(), split=exact)
    except ValueError as exc:
        return refused(exc, "OPTIMIZATION_CONFIG")
    r, breakdown = mf.evaluate(mf.x0)
    return jsonable(
        {
            "merit": mf.merit_from_residuals(r),
            "constraint_mode": "exact" if exact else "penalty",
            "operands": breakdown,
            "variables": [{"surface_id": v.surface_id, "parameter": v.parameter, "value": x} for v, x in zip(mf.variables, mf.x0)],
        }
    )


@app.post("/api/v1/optimize/start")
def optimize_start(req: MeritRequest):
    # validate eagerly so configuration errors are reported synchronously
    try:
        validate_spec(req.system, req.optimization, req.custom_materials, ns=req.ns())
    except ValueError as exc:
        return refused(exc, "OPTIMIZATION_CONFIG")
    job = jobs.start(req.system, req.optimization, req.custom_materials, ns=req.ns())
    return {"job_id": job.id}


@app.get("/api/v1/optimize/{job_id}")
def optimize_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return error(404, "JOB_NOT_FOUND", f"No optimisation job '{job_id}'")
    return jobs.snapshot(job)


@app.post("/api/v1/optimize/{job_id}/cancel")
def optimize_cancel(job_id: str):
    if not jobs.cancel(job_id):
        return error(404, "JOB_NOT_FOUND", f"No optimisation job '{job_id}'")
    return {"ok": True}


@app.post("/api/v1/optimize/{job_id}/pause")
def optimize_pause(job_id: str, req: PauseRequest):
    if not jobs.pause(job_id, req.paused):
        return error(409, "JOB_NOT_RUNNING", "Job is not running")
    return {"ok": True}


class ToleranceRequest(SystemRequest, NsMixin):
    tolerance: ToleranceSpec
    optimization: OptimizationSpec | None = None  # merit operands for criterion "merit"
    allocate: bool = False  # inverse sensitivity: allocate the tolerances to the specification limit


class ToleranceDefaultRequest(SystemRequest):
    grade: Literal["commercial", "precision", "high_precision"] = "precision"


@app.post("/api/v1/tolerance/default")
def tolerance_default(req: ToleranceDefaultRequest):
    try:
        return {"tolerance": jsonable(default_spec(req.system, req.grade, req.custom_materials).model_dump()), "grades": GRADES}
    except ToleranceError as exc:
        return error(422, "TOLERANCE_CONFIG", str(exc))


@app.post("/api/v1/tolerance/start")
def tolerance_start(req: ToleranceRequest):
    ops = req.optimization.operands if req.optimization else []
    # criterion merit: the optimisation's constraint mode (exact: the goals' merit, the limits reported apart)
    mode = req.optimization.constraints if req.optimization else "penalty"
    try:
        job = tol_jobs.start(req.system, req.tolerance, req.custom_materials, ops, ns=req.ns(), allocate=req.allocate, merit_constraints=mode)
    except (ToleranceError, ValueError) as exc:
        return error(422, "TOLERANCE_CONFIG", str(exc))
    return {"job_id": job.id}


@app.get("/api/v1/tolerance/{job_id}")
def tolerance_status(job_id: str):
    job = tol_jobs.get(job_id)
    if not job:
        return error(404, "JOB_NOT_FOUND", f"No tolerance job '{job_id}'")
    return jsonable(tol_jobs.snapshot(job))


@app.post("/api/v1/tolerance/{job_id}/cancel")
def tolerance_cancel(job_id: str):
    if not tol_jobs.cancel(job_id):
        return error(404, "JOB_NOT_FOUND", f"No tolerance job '{job_id}'")
    return {"ok": True}


# ---------------------------------------------------------------------------------------------- design advisor
from ..analysis.advisor import AdvisorJobs  # noqa: E402

adv_jobs = AdvisorJobs()


@app.post("/api/v1/analysis/advisor")
def analysis_advisor(req: SystemRequest):
    """What limits the image (analysis/advisor.py diagnose)."""
    from ..analysis.advisor import diagnose

    cs = compile_system(req.system, req.custom_materials)
    return jsonable(diagnose(cs))


class AdvisorRequest(SystemRequest, NsMixin):
    optimization: OptimizationSpec | None = None  # the project's merit function (None or no operands: RMS spot + focal length)


@app.post("/api/v1/advisor/start")
def advisor_start(req: AdvisorRequest):
    try:
        compile_system(req.system, req.custom_materials)
    except SystemError_:
        raise
    job = adv_jobs.start(req.system, req.custom_materials, req.optimization, ns=req.ns())
    return {"job_id": job["id"]}


@app.get("/api/v1/advisor/{job_id}")
def advisor_status(job_id: str):
    job = adv_jobs.get(job_id)
    if not job:
        return error(404, "JOB_NOT_FOUND", f"No advisor job '{job_id}'")
    pr = job["progress"]
    return jsonable({"job_id": job["id"], "state": job["state"], "progress": {"done": pr.done, "total": pr.total}, "result": job["result"], "error": job["error"]})


@app.post("/api/v1/advisor/{job_id}/cancel")
def advisor_cancel(job_id: str):
    if not adv_jobs.cancel(job_id):
        return error(404, "JOB_NOT_FOUND", f"No advisor job '{job_id}'")
    return {"ok": True}


# ---------------------------------------------------------------------------------------------- design space map
from ..designspace import DesignSpaceError, DesignSpaceJobs, DesignSpaceSpec  # noqa: E402

ds_jobs = DesignSpaceJobs()


class DesignSpaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: DesignSpaceSpec = Field(default_factory=DesignSpaceSpec)
    custom_materials: list[dict] = Field(default_factory=list)


@app.post("/api/v1/design-space/start")
def design_space_start(req: DesignSpaceRequest):
    """Plan and start a design space run (designspace.py); configuration errors answer 422 at once."""
    try:
        job = ds_jobs.start(req.spec, req.custom_materials)
    except (DesignSpaceError, MaterialError) as exc:
        return error(422, "DESIGN_SPACE", str(exc))
    return {"job_id": job["id"], "total": job["total"]}


@app.get("/api/v1/design-space/{job_id}")
def design_space_status(job_id: str, since: int = 0, objectives: str | None = None):
    """Progress, the candidates finished after the first `since`, and the Pareto front for `objectives`
    (comma-separated metric keys; default: RMS spot, length and glass cost or mass)."""
    job = ds_jobs.get(job_id)
    if not job:
        return error(404, "JOB_NOT_FOUND", f"No design space job '{job_id}'")
    objs = [o.strip() for o in objectives.split(",") if o.strip()] if objectives else None
    try:
        return jsonable(ds_jobs.snapshot(job, max(0, since), objs))
    except DesignSpaceError as exc:
        return error(422, "DESIGN_SPACE", str(exc))


@app.get("/api/v1/design-space/{job_id}/candidates/{index}")
def design_space_candidate(job_id: str, index: int):
    """One finished candidate as a project (prescription, optimisation set-up, the custom glasses it uses)."""
    job = ds_jobs.get(job_id)
    if not job:
        return error(404, "JOB_NOT_FOUND", f"No design space job '{job_id}'")
    c = ds_jobs.candidate(job, index)
    if c is None:
        return error(404, "CANDIDATE_NOT_FOUND", f"Candidate {index} is not a finished design")
    return jsonable(c)


@app.post("/api/v1/design-space/{job_id}/cancel")
def design_space_cancel(job_id: str):
    if not ds_jobs.cancel(job_id):
        return error(404, "JOB_NOT_FOUND", f"No design space job '{job_id}'")
    return {"ok": True}


# ---------------------------------------------------------------------------------------------- trade-off curves (ADR-042)
from ..optimize import tradeoff as tradeoff_mod  # noqa: E402

tradeoff_jobs = DesignSpaceJobs()


class TradeoffRequest(MeritRequest):
    """`system` is the optimised design (each point starts there), `base` the design before optimisation (every
    point is reported against it); `operand` numbers the active operands like an optimisation result."""

    base: OpticalSystem
    operand: int = Field(ge=0)
    targets: list[float] | None = Field(default=None, max_length=41)
    budget: int = Field(default=800, ge=20, le=20000)


@app.post("/api/v1/optimize/tradeoff/start")
def tradeoff_start(req: TradeoffRequest):
    """The best merit as one limit moves: one exact-constraint optimisation per target on the process pool
    (optimize/tradeoff.py)."""
    spec = split_variables(req.optimization)[0]
    try:
        job = tradeoff_mod.start_job(tradeoff_jobs, req.base, req.system, spec, req.operand, req.targets, req.budget, req.custom_materials, req.ns())
    except (ValueError, MaterialError) as exc:
        return refused(exc, "OPTIMIZATION_CONFIG")
    return {"job_id": job["id"], "targets": job["tradeoff"]["targets"]}


@app.get("/api/v1/optimize/tradeoff/{job_id}")
def tradeoff_status(job_id: str):
    job = tradeoff_jobs.get(job_id)
    if not job:
        return error(404, "JOB_NOT_FOUND", f"No trade-off job '{job_id}'")
    return jsonable(tradeoff_mod.snapshot(tradeoff_jobs, job))


@app.get("/api/v1/optimize/tradeoff/{job_id}/points/{index}")
def tradeoff_point(job_id: str, index: int):
    """A finished point's full optimisation result (shown and applied like any optimisation result)."""
    job = tradeoff_jobs.get(job_id)
    if not job:
        return error(404, "JOB_NOT_FOUND", f"No trade-off job '{job_id}'")
    r = tradeoff_mod.point_result(job, index)
    if r is None:
        return error(404, "POINT_NOT_FOUND", f"Point {index} is not a finished design")
    return jsonable(r)


@app.post("/api/v1/optimize/tradeoff/{job_id}/cancel")
def tradeoff_cancel(job_id: str):
    if not tradeoff_jobs.cancel(job_id):
        return error(404, "JOB_NOT_FOUND", f"No trade-off job '{job_id}'")
    return {"ok": True}


# ---------------------------------------------------------------------------------------------- stock lenses
from ..stock import StockError, StockLens, check_glasses, generic_library, lens_from_zmx, lens_surfaces, lenses_from_csv  # noqa: E402
from ..stock import describe as describe_stock  # noqa: E402
from ..stockdesign import StockDesignError, StockMatchSpec, StockSpec, describe_candidate, describe_match, design_elements, lens_pool, match_runner, stock_runner  # noqa: E402


@functools.lru_cache(maxsize=1)
def _generic_described() -> tuple[dict, ...]:
    return tuple(describe_stock(l) for l in generic_library())


@app.get("/api/v1/stock/generic")
def stock_generic():
    """The built-in generic stock lenses with their paraxial data (d line)."""
    return jsonable({"catalog": "Generic", "lenses": list(_generic_described())})


class StockLensesRequest(BaseModel):
    lenses: list[StockLens] = Field(max_length=20000)
    custom_materials: list[dict] = Field(default_factory=list)


@app.post("/api/v1/stock/describe")
def stock_describe(req: StockLensesRequest):
    """Paraxial data of stock lenses (d line) and the glasses that cannot be resolved."""
    return jsonable({"lenses": [describe_stock(l, req.custom_materials) for l in req.lenses], "missing_glasses": check_glasses(req.lenses, req.custom_materials)})


class StockZmxFile(BaseModel):
    filename: str = Field(max_length=300)
    content_base64: str = Field(max_length=5_000_000)


class StockZmxRequest(BaseModel):
    files: list[StockZmxFile] = Field(min_length=1, max_length=2000)
    catalog: str = Field(min_length=1, max_length=80)
    vendor: str = Field(default="", max_length=80)
    catalog_materials: list[dict] = Field(default_factory=list, description="records of the user's glass catalogues")


@app.post("/api/v1/stock/import/zmx")
def stock_import_zmx(req: StockZmxRequest):
    """Stock lenses from vendor ZMX files (one lens per file); files that fail are listed with the reason."""
    import base64

    lenses, custom, files = [], {}, []
    for f in req.files:
        try:
            text = decode_zmx(base64.b64decode(f.content_base64, validate=True))
            lens, used, diags = lens_from_zmx(text, f.filename, req.catalog, req.vendor, req.catalog_materials)
            lenses.append(describe_stock(lens, used))
            for r in used:
                custom[str(r.get("name", "")).upper()] = r
            files.append({"filename": f.filename, "ok": True, "part": lens.part, "diagnostics": [d for d in diags if d["status"] not in ("imported", "info")]})
        except (ZmxError, StockError, MaterialError, ValueError) as exc:
            files.append({"filename": f.filename, "ok": False, "error": str(exc).splitlines()[0] if str(exc) else type(exc).__name__})
    return jsonable({"catalog": req.catalog, "lenses": lenses, "custom_materials": list(custom.values()), "files": files})


class StockCsvRequest(BaseModel):
    content: str = Field(max_length=5_000_000)
    catalog: str = Field(min_length=1, max_length=80)
    custom_materials: list[dict] = Field(default_factory=list)


@app.post("/api/v1/stock/import/csv")
def stock_import_csv(req: StockCsvRequest):
    """Stock lenses from the documented CSV format (docs/FILE_FORMATS.md); malformed rows are reported by line."""
    try:
        lenses, diags = lenses_from_csv(req.content, req.catalog)
    except StockError as exc:
        return error(422, "STOCK_IMPORT", str(exc))
    return jsonable({"catalog": req.catalog, "lenses": [describe_stock(l, req.custom_materials) for l in lenses], "diagnostics": diags, "missing_glasses": check_glasses(lenses, req.custom_materials)})


class StockSurfacesRequest(BaseModel):
    lens: StockLens
    reversed: bool = False
    gap_after: float = Field(default=5.0, ge=0.0)


@app.post("/api/v1/stock/surfaces")
def stock_surfaces(req: StockSurfacesRequest):
    """The lens as design surfaces (fixed clear apertures, mechanical semi-diameter, the part in labels and comments)."""
    return {"surfaces": lens_surfaces(req.lens, req.reversed, req.gap_after, "stk")}


class StockBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: StockSpec = Field(default_factory=StockSpec)
    lenses: list[StockLens] = Field(default_factory=list, max_length=20000)
    custom_materials: list[dict] = Field(default_factory=list)


@app.post("/api/v1/stock/build/start")
def stock_build_start(req: StockBuildRequest):
    """Build systems from stock lenses (stockdesign.py); progress, results and cancel use /design-space/{id}."""
    try:
        lens_pool(req.spec, req.lenses, req.custom_materials)
    except (StockDesignError, MaterialError) as exc:
        return error(422, "STOCK_DESIGN", str(exc))
    job = ds_jobs.start(req.spec, req.custom_materials, runner=stock_runner(ds_jobs, req.spec, req.lenses, req.custom_materials), describe=describe_candidate(req.spec))
    return {"job_id": job["id"], "total": 0}


class StockMatchRequest(SystemRequest):
    spec: StockMatchSpec = Field(default_factory=StockMatchSpec)
    optimization: OptimizationSpec | None = None
    lenses: list[StockLens] = Field(default_factory=list, max_length=20000)


@app.post("/api/v1/stock/match/start")
def stock_match_start(req: StockMatchRequest):
    """Replace the design's lens elements by stock lenses and reoptimise the air gaps (stockdesign.py)."""
    try:
        design_elements(req.system, req.custom_materials)
        lens_pool(StockSpec(wavelengths=[w.value for w in req.system.wavelengths], primary=req.system.primary_wavelength, materials=req.spec.materials, generic=req.spec.generic), req.lenses, req.custom_materials)
    except (StockDesignError, MaterialError) as exc:
        return error(422, "STOCK_DESIGN", str(exc))
    job = ds_jobs.start(
        req.spec, req.custom_materials, runner=match_runner(ds_jobs, req.spec, req.system, req.optimization, req.lenses, req.custom_materials), describe=describe_match(req.spec)
    )
    return {"job_id": job["id"], "total": 0}


# ---------------------------------------------------------------------------------------------- light sources
from ..spectra import SpectrumSpec, generate as generate_spectrum  # noqa: E402


@app.post("/api/v1/sources/spectrum")
def sources_spectrum(spec: SpectrumSpec):
    """A source spectrum as wavelength samples with power weights (spectra.py): blackbody, Gaussian line, flat band."""
    try:
        return jsonable(generate_spectrum(spec))
    except ValueError as exc:
        return error(422, "SPECTRUM", str(exc))


class SourcesDescribeRequest(SystemRequest, NsMixin):
    pass


class PhotometryRequest(BaseModel):
    """Lines of a spectrum: wavelengths (µm) with power weights, and the total power (W)."""

    wavelengths: list[Wavelength] = Field(min_length=1, max_length=2000)
    power_w: float = Field(1.0, gt=0.0, le=1e12)


@app.post("/api/v1/photometry/spectrum")
def photometry_spectrum(req: PhotometryRequest):
    """Luminous flux (photopic, scotopic), efficacy, tristimulus values, chromaticity, CCT and Duv, sRGB (photometry/)."""
    from ..photometry import line_spectrum

    wl = [(w.value, w.weight) for w in req.wavelengths if w.weight > 0]
    tot = sum(x for _, x in wl)
    if not tot > 0:
        return error(422, "PHOTOMETRY", "At least one wavelength needs a positive weight")
    return jsonable(line_spectrum([v for v, _ in wl], [req.power_w * x / tot for _, x in wl]))


@app.post("/api/v1/sources/describe")
def sources_describe(req: SourcesDescribeRequest):
    """Where every source and detector is and points (global frame), and the beam parameters of Gaussian beams."""
    from ..nssources import describe_beam, placement_matrix, surface_frames
    from ..photometry import line_spectrum

    cs = compile_system(req.system, req.custom_materials)
    frames = surface_frames(cs)
    prim = req.system.wavelengths[req.system.primary_wavelength].value

    def pose(pl):
        try:
            R, t = placement_matrix(pl, frames)
        except ValueError as exc:
            return {"error": str(exc)}
        d = R[:, 2]
        return {"position": t.tolist(), "direction": d.tolist(), "axis_angle_deg": math.degrees(math.acos(max(-1.0, min(1.0, float(d[2])))))}

    out_s = []
    for src in req.sources:
        row = {"id": src.id, "kind": src.kind, **(pose(src.placement) if src.kind != "system_field" else {})}
        # luminous flux and colour of the source's spectrum (its wavelength samples, else the system's), photometry/
        wl = [(w.value, w.weight) for w in src.wavelengths if w.weight > 0] or [(w.value, w.weight) for w in req.system.wavelengths if w.weight > 0]
        tot = sum(x for _, x in wl)
        row["light"] = line_spectrum([v for v, _ in wl], [src.power_w * x / tot for _, x in wl]) if tot > 0 else None
        if src.kind == "gaussian_beam":
            lam = next((w.value for w in src.wavelengths if w.weight > 0), prim)
            # in the surrounding air; a source inside a solid diverges by 1/n there (the trace uses that solid's index)
            n_air = float(cs.library.index("AIR", lam)) if cs.library.has("AIR") else 1.0
            row["beam"] = describe_beam(src, lam, n_air)
        out_s.append(row)
    return jsonable({"sources": out_s, "detectors": [{"id": d.id, **pose(d.placement)} for d in req.detectors]})


class StlImportRequest(BaseModel):
    filename: str = ""
    data_base64: str
    units: Literal["mm", "um", "cm", "m", "in"] = "mm"


@app.post("/api/v1/import/stl")
def import_stl(req: StlImportRequest):
    import base64 as _b64

    try:
        raw = _b64.b64decode(req.data_base64, validate=True)
    except (ValueError, TypeError):
        return error(422, "STL_INVALID", "data_base64 is not valid base64")
    try:
        return jsonable(parse_stl(raw, req.units, req.filename))
    except StlError as exc:
        return error(422, "STL_INVALID", str(exc))


class CadImportRequest(BaseModel):
    filename: str
    data_base64: str


@app.post("/api/v1/import/cad")
def import_cad_file(req: CadImportRequest):
    import base64 as _b64

    try:
        raw = _b64.b64decode(req.data_base64, validate=True)
    except (ValueError, TypeError):
        return error(422, "CAD_INVALID", "data_base64 is not valid base64")
    try:
        return jsonable(import_cad(raw, req.filename))
    except CadError as exc:
        return error(422, "CAD_INVALID", str(exc))


class CadExportRequest(SystemRequest):
    format: Literal["step", "iges"] = "step"
    cad_assets: list[dict] = Field(default_factory=list)
    rim_margin: float = Field(0.0, ge=0.0, le=100.0)
    include_stop: bool = True
    include_image: bool = True
    include_rays: bool = True
    include_cad: bool = True
    include_mechanics: bool = False  # spacers between the elements and a simple barrel


@app.post("/api/v1/export/cad")
def export_cad(req: CadExportRequest):
    cs = compile_system(req.system, req.custom_materials)
    try:
        return jsonable(
            export_system_cad(cs, req.format, req.cad_assets, req.rim_margin, req.include_stop, req.include_image, req.include_rays, req.include_cad, req.include_mechanics)
        )
    except CadError as exc:
        return error(422, "CAD_EXPORT", str(exc))


class ElementsRequest(SystemRequest):
    tolerancing: ToleranceSpec | None = None  # the project's tolerances, for the drawings


@app.post("/api/v1/elements")
def elements_endpoint(req: ElementsRequest):
    """Lens elements as parts: mechanical geometry, mass, cost and ISO 10110 drawing data (analysis/elements.py)."""
    from ..analysis.elements import elements as element_list

    try:
        return jsonable(element_list(req.system, req.custom_materials, req.tolerancing))
    except (SystemError_, ValueError) as exc:
        return error(422, "ELEMENTS", str(exc))


class NonSeqImportanceTarget(BaseModel):
    kind: Literal["none", "detector", "legacy", "surface"] = "none"
    id: str | None = None  # detector id
    index: int | None = Field(None, ge=1)  # surface index


class NonSeqImportance(BaseModel):
    """Importance sampling of scattered light towards a target (nonseq.py)."""

    target: NonSeqImportanceTarget = Field(default_factory=NonSeqImportanceTarget)
    rays: int = Field(4, ge=1, le=64)  # extra rays per scatter event


class NonSeqRequest(SystemRequest):
    cad_assets: list[dict] = Field(default_factory=list)
    include_system: bool = True
    field: int = Field(0, ge=0)
    wavelength: int | None = None
    rays: int = Field(400, ge=4, le=20000)
    overfill: float = Field(1.2, gt=0.0, le=10.0)
    split: bool = True
    max_events: int = Field(40, ge=1, le=500)
    min_power: float = Field(1e-6, gt=0.0, lt=1.0)
    pixels: int = Field(64, ge=4, le=512)
    detector_radius: float | None = Field(None, gt=0.0)
    seed: int = Field(1, ge=0, le=2**31 - 1)  # Monte Carlo sources and scattering
    # general sources / detectors (nssources.py); None or empty enabled list: the system field / image-surface disc
    sources: list[LightSource] | None = None
    detectors: list[Detector] | None = None
    importance: NonSeqImportance | None = None
    # stop between source rays after this many seconds (a random subset, scaled to the whole source); None: all rays
    max_seconds: float | None = Field(None, gt=0.0, le=3600.0)


@app.post("/api/v1/analysis/nonseq")
def analysis_nonseq(req: NonSeqRequest):
    _check_field_wl(req.system, req.field, req.wavelength)
    cs = compile_system(req.system, req.custom_materials)
    try:
        srcs = [s for s in (req.sources or []) if s.enabled] or None
        dets = req.detectors if req.detectors else None
        scene = build_scene(cs, req.cad_assets, req.include_system, req.detector_radius, req.custom_materials, dets)
        return jsonable(trace_nonsequential(cs, scene, req.field, req.wavelength, req.rays, req.overfill, req.split, req.max_events, req.min_power, req.pixels, seed=req.seed, sources=srcs, importance=req.importance.model_dump() if req.importance else None, max_seconds=req.max_seconds))
    except CadError as exc:
        return error(422, "NONSEQ", str(exc))


class CadRecognizeRequest(BaseModel):
    asset: dict


@app.post("/api/v1/cad/recognize")
def cad_recognize(req: CadRecognizeRequest):
    try:
        return jsonable(recognize_asset(req.asset))
    except CadError as exc:
        return error(422, "CAD_RECOGNIZE", str(exc))


class CadInsertRequest(SystemRequest):
    asset: dict
    elements: list[int] = Field(min_length=1)
    role: Literal["lens", "mirror"] = "lens"
    materials: list[str] = Field(default_factory=lambda: ["N-BK7"])
    after: int = Field(ge=0)
    placement: Literal["cad", "axis"] = "cad"
    gap: float = 0.0
    reflect_face: Literal["front", "back"] = "front"


@app.post("/api/v1/cad/insert")
def cad_insert(req: CadInsertRequest):
    try:
        rec = recognize_asset(req.asset)
        els = rec["elements"]
        if any(not 0 <= k < len(els) for k in req.elements):
            return error(422, "CAD_INSERT", "element index out of range")
        chosen = [els[k] for k in sorted(set(req.elements))]
        new, report = insert_elements(req.system, chosen, req.role, req.materials, req.after, req.placement, req.gap, req.reflect_face, MaterialLibrary(req.custom_materials))
    except (CadError, SystemError_) as exc:
        return error(422, "CAD_INSERT", str(exc))
    return jsonable({"system": new.model_dump(), "report": report, "elements": chosen})


@app.get("/api/v1/samples")
def samples():
    return {"samples": list_samples()}


@app.get("/api/v1/samples/{sample_id}")
def sample(sample_id: str):
    try:
        return dump_project(get_sample(sample_id))
    except KeyError:
        return error(404, "SAMPLE_NOT_FOUND", f"No sample '{sample_id}'")


@app.post("/api/v1/project/validate")
def project_validate(raw: dict):
    proj, notes = load_project(raw)
    return {"valid": True, "notes": notes, "project": dump_project(proj)}


@app.post("/api/v1/import/zmx")
def import_zmx(req: ImportRequest):
    import base64
    import binascii

    try:
        data = base64.b64decode(req.content_base64, validate=True)
    except (binascii.Error, ValueError):
        return error(422, "IMPORT_ERROR", "File content is not valid base64")
    text = decode_zmx(data)
    project, diags = parse_zmx(text, req.filename, req.catalog_materials)
    return {"project": dump_project(project), "diagnostics": [d.as_dict() for d in diags]}


# ----------------------------------------------------------------------
# Thin-film coating design
# ----------------------------------------------------------------------
class CoatingDesignRequest(BaseModel):
    design: CoatingDesign
    custom_materials: list[dict] = Field(default_factory=list)


class CoatingEvaluateRequest(CoatingDesignRequest):
    lambda_min_nm: float | None = Field(None, gt=50.0)
    lambda_max_nm: float | None = Field(None, gt=50.0)
    samples: int = Field(401, ge=2, le=4001)
    angle_deg: float = Field(0.0, ge=0.0, lt=90.0)


@app.post("/api/v1/coating-design/evaluate")
def coating_design_evaluate(req: CoatingEvaluateRequest):
    return jsonable(evaluate_design(req.design, req.custom_materials, req.lambda_min_nm, req.lambda_max_nm, req.samples, req.angle_deg))


class CoatingTemplateRequest(CoatingDesignRequest):
    kind: TemplateKind
    high: str = "H"
    low: str = "L"
    pairs: int = Field(8, ge=1, le=60)
    lambda0_nm: float | None = Field(None, gt=50.0)
    edge_nm: float | None = Field(None, gt=50.0)
    band_min_nm: float | None = Field(None, gt=50.0)
    band_max_nm: float | None = Field(None, gt=50.0)
    cavities: int = Field(1, ge=1, le=5)


class CoatingDesignAnalyzeRequest(CoatingAnalysisParams):
    design: CoatingDesign
    custom_materials: list[dict] = Field(default_factory=list)


@app.post("/api/v1/coating-design/analyze")
def coating_design_analyze(req: CoatingDesignAnalyzeRequest):
    """The coating views' analyses (phase, GD/GDD, colour, field, profile ...) for a designer design."""
    from ..coatanalysis import CoatingAnalysisError, stack_from_design
    from ..coatdesign import Resolver

    try:
        res = Resolver(req.design, req.custom_materials)
        out = _coating_analysis(stack_from_design(req.design, res), req)
        out["notes"] = list(out.get("notes", [])) + sorted(res.warnings)
        return out
    except (CoatingAnalysisError, DesignError, ValueError, MaterialError, DispersionError) as exc:
        return error(422, "COATING_DESIGN", str(exc))


@app.post("/api/v1/coating-design/template")
def coating_design_template(req: CoatingTemplateRequest):
    return jsonable(template(req.design, req.kind, req.custom_materials, req.high, req.low, req.pairs, req.lambda0_nm, req.edge_nm, req.band_min_nm, req.band_max_nm, req.cavities))


class CoatingOptimizeRequest(CoatingDesignRequest):
    method: Literal["refine", "needle"] = "refine"
    max_needles: int = Field(40, ge=1, le=200)
    time_limit_s: float = Field(30.0, gt=0.0, le=300.0)


@app.post("/api/v1/coating-design/optimize")
def coating_design_optimize(req: CoatingOptimizeRequest):
    return jsonable(optimize_design(req.design, req.custom_materials, req.method, req.max_needles, req.time_limit_s))


class CoatingMonteCarloRequest(CoatingDesignRequest):
    sigma_rel: float = Field(0.01, ge=0.0, le=0.5)
    sigma_abs_nm: float = Field(0.0, ge=0.0, le=100.0)
    runs: int = Field(200, ge=1, le=5000)
    seed: int = Field(1, ge=0, le=2**31 - 1)


@app.post("/api/v1/coating-design/montecarlo")
def coating_design_montecarlo(req: CoatingMonteCarloRequest):
    return jsonable(monte_carlo(req.design, req.custom_materials, req.sigma_rel, req.sigma_abs_nm, req.runs, req.seed))


class CoatingRecipeRequest(CoatingDesignRequest):
    monitor_wavelength_nm: float | None = Field(None, gt=50.0, le=50000.0)
    monitor: Literal["T", "R"] = "T"
    monitor_back_side: Literal["none", "uncoated"] = "uncoated"


@app.post("/api/v1/coating-design/recipe")
def coating_design_recipe(req: CoatingRecipeRequest):
    return jsonable(recipe(req.design, req.custom_materials, req.monitor_wavelength_nm, req.monitor, 60, req.monitor_back_side))


class CoatingExportRequest(CoatingDesignRequest):
    name: str | None = None


@app.post("/api/v1/coating-design/export-coating")
def coating_design_export(req: CoatingExportRequest):
    return jsonable(to_coating_definition(req.design, req.name))


class CoatingAngularRequest(CoatingDesignRequest):
    wavelengths_nm: list[float] = Field(default_factory=list, max_length=8)
    angle_max_deg: float = Field(85.0, ge=1.0, lt=90.0)
    angles: int = Field(86, ge=2, le=361)
    map_wavelengths: int = Field(81, ge=2, le=401)
    map_angles: int = Field(46, ge=2, le=181)
    lambda_min_nm: float | None = Field(None, gt=50.0)
    lambda_max_nm: float | None = Field(None, gt=50.0)


@app.post("/api/v1/coating-design/angular")
def coating_design_angular(req: CoatingAngularRequest):
    return jsonable(angular(req.design, req.custom_materials, req.wavelengths_nm or None, req.angle_max_deg, req.angles, req.map_wavelengths, req.map_angles, req.lambda_min_nm, req.lambda_max_nm))


class CoatingFormulaRequest(CoatingDesignRequest):
    formula: str = Field(min_length=1, max_length=4000)


@app.post("/api/v1/coating-design/formula")
def coating_design_formula(req: CoatingFormulaRequest):
    """Layers from a stack formula ("(HL)^7 H", incident side first, quarter waves at the design wavelength)."""
    from ..coatdesign import to_formula

    layers = parse_formula(req.formula, req.design, req.custom_materials)
    d = req.design.model_copy(update={"layers": layers})
    return jsonable({"design": d.model_dump(), "formula": to_formula(d, req.custom_materials), "layer_count": len(layers)})


class CoatingFitRequest(CoatingDesignRequest):
    measurements: list[Measurement] = Field(min_length=1, max_length=12)
    mode: FitMode = "layers"
    max_error: float = Field(0.3, gt=0.0, lt=0.9)
    time_limit_s: float = Field(30.0, gt=0.0, le=300.0)
    fit_index: bool = False
    fit_dispersion: bool = False
    fit_absorption: bool = False
    fit_substrate: bool = False
    search: Literal["local", "global"] = "local"
    index_range: float = Field(0.1, gt=0.0, le=0.5)


@app.post("/api/v1/coating-design/fit")
def coating_design_fit(req: CoatingFitRequest):
    """Reverse engineering: thickness and index errors that reproduce measured R/T spectra."""
    return jsonable(fit_measurement(req.design, req.measurements, req.custom_materials, req.mode, req.max_error, req.time_limit_s,
                                    req.fit_index, req.fit_dispersion, req.fit_absorption, req.fit_substrate, req.search, req.index_range))


class CoatingFromDefinitionRequest(BaseModel):
    coating: dict | None = None
    builtin: str | None = Field(None, description="a built-in library coating, opened under its design conditions")
    base: CoatingDesign | None = None


@app.post("/api/v1/coating-design/from-coating")
def coating_design_from_coating(req: CoatingFromDefinitionRequest):
    if req.builtin is not None:
        c = COATINGS.get(req.builtin.strip().upper())
        if c is None:
            raise DesignError(f"Unknown built-in coating '{req.builtin}'")
        return jsonable({"design": design_from_builtin(c, req.base).model_dump()})
    if req.coating is None:
        raise DesignError("Give a coating definition or a built-in coating name")
    return jsonable({"design": design_from_coating(req.coating, req.base).model_dump()})


class SurfaceContextRequest(SystemRequest):
    surface: int = Field(ge=1)


@app.post("/api/v1/analysis/surface-context")
def analysis_surface_context(req: SurfaceContextRequest):
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(surface_context(cs, req.surface))


class CoatingPerformanceRequest(SystemRequest):
    lambda_min_nm: float | None = Field(None, gt=50.0)
    lambda_max_nm: float | None = Field(None, gt=50.0)
    samples: int = Field(121, ge=2, le=801)
    include_uncoated: bool = True


@app.post("/api/v1/analysis/coatings")
def analysis_coatings(req: CoatingPerformanceRequest):
    cs = compile_system(req.system, req.custom_materials)
    return jsonable(coating_performance(cs, req.lambda_min_nm, req.lambda_max_nm, req.samples, req.include_uncoated))


# ----------------------------------------------------------------------
# CAD assemblies: exact measurements and sections
# ----------------------------------------------------------------------
from ..io.cad_assembly import clearance as cad_clearance, section as cad_section, snap_points as cad_snap  # noqa: E402


class CadMeasureRequest(BaseModel):
    assets: list[dict] = Field(min_length=1)
    picks: list[dict] = Field(min_length=1, max_length=16)  # {asset_id, part_id?, point: [x, y, z]} (global)


@app.post("/api/v1/cad/measure")
def cad_measure(req: CadMeasureRequest):
    by_id = {a["id"]: a for a in req.assets}
    try:
        pts = cad_snap(by_id, req.picks)
    except CadError as exc:
        return error(422, "CAD_MEASURE", str(exc))
    dist = None
    if len(pts) >= 2:
        a, b = np.array(pts[0]["point"]), np.array(pts[1]["point"])
        dist = {"distance_mm": float(np.linalg.norm(b - a)), "delta_mm": (b - a).tolist()}
    return jsonable({"points": pts, "distance": dist})


class CadClearanceRequest(BaseModel):
    assets: list[dict] = Field(min_length=1)
    a: dict  # {asset_id, part_id?}
    b: dict


@app.post("/api/v1/cad/clearance")
def cad_clearance_endpoint(req: CadClearanceRequest):
    by_id = {x["id"]: x for x in req.assets}
    try:
        return jsonable(cad_clearance(by_id, req.a, req.b))
    except (CadError, KeyError) as exc:
        return error(422, "CAD_CLEARANCE", str(exc))


class CadSectionRequest(BaseModel):
    assets: list[dict] = Field(default_factory=list)
    origin: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    normal: list[float] = Field(default_factory=lambda: [1.0, 0.0, 0.0], min_length=3, max_length=3)


@app.post("/api/v1/cad/section")
def cad_section_endpoint(req: CadSectionRequest):
    out = []
    for a in req.assets:
        if not a.get("visible", True):
            continue
        try:
            out.append({"asset_id": a["id"], "parts": cad_section(a, req.origin, req.normal)})
        except CadError as exc:
            out.append({"asset_id": a["id"], "parts": [], "error": str(exc)})
    return jsonable({"assets": out, "plane": {"origin": req.origin, "normal": req.normal}})
