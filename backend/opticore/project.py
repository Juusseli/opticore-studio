"""Native project format (.opticore), schema version 1.

The checksum is SHA-256 over the canonical JSON of the project without its
`checksum` member. Canonical JSON = keys sorted, no whitespace, numbers in
ECMAScript Number-to-String form, so that the browser (JSON.stringify) and
the backend produce byte-identical output (see docs/FILE_FORMATS.md).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import ENGINE_VERSION
from .model import OpticalSystem, new_id
from .nssources import Detector, LightSource
from .optimize.merit import OptimizationSpec
from .tolerance import ToleranceSpec

PROJECT_FORMAT = "opticore-project"
PROJECT_SCHEMA_VERSION = 1


class ProjectError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Metadata(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = "Untitled project"
    description: str = ""
    author: str = ""
    created: str = Field(default_factory=now_iso)
    modified: str = Field(default_factory=now_iso)
    tags: list[str] = Field(default_factory=list)


class Revision(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(default_factory=new_id)
    timestamp: str = Field(default_factory=now_iso)
    label: str = ""
    system: OpticalSystem
    merit: float | None = None


class Provenance(BaseModel):
    model_config = ConfigDict(extra="allow")
    created_with: str = f"OptiCore Studio engine {ENGINE_VERSION}"
    imports: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Checksum(BaseModel):
    algorithm: Literal["sha256"] = "sha256"
    value: str


class CadMesh(BaseModel):
    model_config = ConfigDict(extra="forbid")
    positions_b64: str  # little-endian float32 xyz (mm, asset coordinates)
    indices_b64: str  # little-endian uint32 triangle indices
    vertices: int = Field(ge=0)
    triangles: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self):
        from .io.stl import StlError, decode_mesh

        try:
            p, i = decode_mesh(self.positions_b64, self.indices_b64)
        except (StlError, ValueError) as exc:
            raise ValueError(f"Invalid CAD mesh: {exc}") from exc
        if len(p) != self.vertices or len(i) != self.triangles:
            raise ValueError("CAD mesh vertex/triangle counts do not match the encoded data")
        return self


class CadTransform(BaseModel):
    """Placement in the optical global frame: p_global = R(rx, ry, rz) p + t.

    R = Rx(rx) Ry(ry) Rz(rz) (degrees; intrinsic X-Y-Z, the Three.js "XYZ" order)."""

    model_config = ConfigDict(extra="forbid")
    translate: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    rotate_deg: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)


class CadScatter(BaseModel):
    """Surface scatter model (BSDF) of a CAD body (non-sequential mode; bsdf.py)."""

    model_config = ConfigDict(extra="forbid")
    model: Literal["none", "lambertian", "gaussian", "abg", "harvey"] = "none"
    fraction: float = Field(default=0.0, ge=0.0, le=1.0, description="absorber: diffuse reflectance; mirror: scattered part of the reflected power; refractive: scattered part of the transmitted power (ABg / Harvey: TIS at normal incidence)")
    sigma_deg: float = Field(default=5.0, gt=0.0, le=90.0, description="Gaussian model: per-axis angular width about the specular direction")
    abg_b: float | None = Field(default=None, gt=0.0, description="ABg: B (direction-cosine units to the power g); None = 1e-3")
    abg_g: float | None = Field(default=None, ge=0.0, le=4.0, description="ABg: slope g; None = 2")
    harvey_l: float | None = Field(default=None, gt=0.0, le=1.0, description="Harvey-Shack: shoulder l (direction cosines); None = 0.01")
    harvey_s: float | None = Field(default=None, ge=-6.0, lt=0.0, description="Harvey-Shack: slope s (< 0); None = -2")


class CadOptical(BaseModel):
    """Optical role of a CAD model in non-sequential tracing."""

    model_config = ConfigDict(extra="forbid")
    role: Literal["none", "absorber", "mirror", "refractive"] = "none"
    material: str | None = None
    coating: str = ""  # thin-film coating on every face (mirror / refractive)
    scatter: CadScatter = Field(default_factory=CadScatter)


class CadAsset(BaseModel):
    """Imported CAD geometry (display, placement and measurement; traced only in non-sequential mode, and only
    where it has an optical role)."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=new_id)
    name: str
    source_filename: str = ""
    format: Literal["stl", "step", "iges"] = "stl"
    units: str = "mm"
    imported: str = ""
    mesh: CadMesh
    bbox_min: list[float]
    bbox_max: list[float]
    surface_area_mm2: float
    volume_mm3: float | None = None
    closed: bool = False
    diagnostics: list[dict] = Field(default_factory=list)
    bodies: list[dict] = Field(default_factory=list, description="STEP/IGES: top-level bodies with exact B-rep volume, area and bounding box")
    source_b64: str | None = Field(default=None, description="STEP/IGES: original file (base64) so the exact geometry can be re-exported")
    mesh_deflection_mm: float | None = Field(default=None, description="STEP/IGES: linear deflection of the display mesh")
    transform: CadTransform = Field(default_factory=CadTransform)
    optical: CadOptical = Field(default_factory=CadOptical)
    tree: list[dict] = Field(default_factory=list, description="STEP/IGES assembly structure with per-node triangle ranges (io/cad_assembly.py)")
    hidden_parts: list[str] = Field(default_factory=list, description="tree node ids hidden in the views and left out of non-sequential tracing")
    part_roles: dict[str, CadOptical] = Field(default_factory=dict, description="optical role overrides per tree node (inherited by the subtree)")
    visible: bool = True
    color: str = "#9aa7b4"
    opacity: float = Field(default=0.55, ge=0.05, le=1.0)


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["opticore-project"] = PROJECT_FORMAT
    schema_version: int = PROJECT_SCHEMA_VERSION
    id: str = Field(default_factory=new_id)
    metadata: Metadata = Field(default_factory=Metadata)
    system: OpticalSystem
    custom_materials: list[dict] = Field(default_factory=list)
    optimization: OptimizationSpec = Field(default_factory=OptimizationSpec)
    tolerancing: ToleranceSpec = Field(default_factory=ToleranceSpec)
    cad_assets: list[CadAsset] = Field(default_factory=list)
    # non-sequential light sources and detectors (nssources.py); optional, older files have none
    sources: list[LightSource] = Field(default_factory=list, max_length=64)
    detectors: list[Detector] = Field(default_factory=list, max_length=64)
    analysis_settings: dict[str, Any] = Field(default_factory=dict)
    ui: dict[str, Any] = Field(default_factory=dict)
    revisions: list[Revision] = Field(default_factory=list)
    saved_optimizations: list[dict] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)
    checksum: Checksum | None = None


# ----------------------------------------------------------------------
# Canonical JSON identical to the frontend implementation
# ----------------------------------------------------------------------
_REPR_RE = re.compile(r"^(-?)(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$")


def js_number(x: float | int) -> str:
    """Format a number exactly like ECMAScript Number.prototype.toString."""
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, int):
        return str(x)
    if not math.isfinite(x):
        return "null"
    if x == 0:
        return "0"
    m = _REPR_RE.match(repr(float(x)))
    if not m:  # pragma: no cover
        raise ValueError(f"Cannot format number {x!r}")
    sign, ip, fp, ex = m.group(1), m.group(2), m.group(3) or "", int(m.group(4) or 0)
    digits = (ip + fp).lstrip("0")
    # exponent n such that value = 0.d1d2... * 10^n
    lead_zeros = len(ip + fp) - len((ip + fp).lstrip("0"))
    n = len(ip) + ex - lead_zeros
    digits = digits.rstrip("0") or "0"
    k = len(digits)
    if k <= n <= 21:
        s = digits + "0" * (n - k)
    elif 0 < n <= 21:
        s = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        s = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        es = ("+" if e >= 0 else "-") + str(abs(e))
        s = digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + es
    return sign + s


def canonical_json(obj: Any) -> str:
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, (int, float)):
        return js_number(obj)
    if isinstance(obj, str):
        return json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(canonical_json(v) for v in obj) + "]"
    if isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: kv[0])
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + canonical_json(v) for k, v in items) + "}"
    raise TypeError(f"Not JSON-serialisable: {type(obj).__name__}")


def compute_checksum(project_dict: dict) -> str:
    body = {k: v for k, v in project_dict.items() if k != "checksum"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
def migrate(raw: dict) -> tuple[dict, list[str]]:
    """Upgrade an older project dict to the current schema. Returns (dict, notes)."""
    notes: list[str] = []
    if raw.get("format") != PROJECT_FORMAT:
        raise ProjectError("Not an OptiCore project file (missing format 'opticore-project')")
    v = raw.get("schema_version")
    if not isinstance(v, int):
        raise ProjectError("Project schema_version missing or invalid")
    if v > PROJECT_SCHEMA_VERSION:
        raise ProjectError(
            f"Project schema version {v} is newer than this application supports ({PROJECT_SCHEMA_VERSION}); please update OptiCore Studio"
        )
    # (no older versions exist yet; migrations will be chained here)
    return raw, notes


def load_project(raw: dict, verify_checksum: bool = True) -> tuple[Project, list[str]]:
    raw, notes = migrate(raw)
    cs = raw.get("checksum")
    if verify_checksum and cs:
        expected = cs.get("value") if isinstance(cs, dict) else None
        actual = compute_checksum(raw)
        if expected != actual:
            notes.append("Checksum mismatch: the file was modified outside OptiCore Studio or is corrupted")
    try:
        proj = Project.model_validate(raw)
    except Exception as exc:
        raise ProjectError(f"Invalid project: {exc}") from exc
    return proj, notes


def dump_project(project: Project) -> dict:
    d = project.model_dump(mode="json")
    d["checksum"] = None
    d.pop("checksum")
    d["checksum"] = {"algorithm": "sha256", "value": compute_checksum(d)}
    return d
