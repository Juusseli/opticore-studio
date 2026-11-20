"""Optical system schema (API contract, schema version 1).

Surface list convention (sequential mode):
  surfaces[0]   object surface (thickness = object distance; null = infinity)
  surfaces[1..N-2] optical surfaces
  surfaces[N-1] image surface

Sign conventions (see docs/OPTICAL_ENGINE.md):
  * radius > 0: centre of curvature on the +z side of the vertex; null = plane
  * thickness: signed distance along the local z axis to the next vertex.
    After a mirror light travels towards -z, so following thicknesses are
    normally negative (same convention as most sequential design programs).
  * tilts are in degrees, right-handed about the local axes.
"""

from __future__ import annotations

import math
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1

SurfaceType = Literal["standard", "even_asphere", "odd_asphere", "biconic", "zernike", "qcon", "qbfs", "xy_polynomial", "coordinate_break", "ideal"]
# image_height: real chief-ray height on the image surface; paraxial_image_height: paraxial chief-ray
# height at the paraxial image plane (both resolved to object-space fields by fields.py)
FieldType = Literal["angle", "object_height", "image_height", "paraxial_image_height"]
ApertureType = Literal["epd", "image_fnum", "object_na"]
RayAiming = Literal["paraxial", "real"]
SemiDiameterMode = Literal["auto", "fixed"]


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


SolveType = Literal["marginal_height", "chief_height", "pickup", "marginal_angle", "chief_angle", "f_number"]
THICKNESS_SOLVES = ("marginal_height", "chief_height", "pickup")
CURVATURE_SOLVES = ("marginal_angle", "chief_angle", "f_number", "pickup")


class Solve(StrictModel):
    """Paraxial solve or pickup controlling a thickness or a curvature.

    thickness: marginal_height / chief_height (paraxial ray height `target` mm
               at the next surface; `zone` scales the marginal ray), pickup
               (t = scale * t_source + offset)
    curvature: marginal_angle / chief_angle (paraxial slope `target` after the
               surface), f_number (marginal slope for image-space F/# `target`),
               pickup (R = scale * R_source; plane stays plane)
    """

    type: SolveType
    target: float = 0.0
    surface_id: str | None = None
    scale: float = 1.0
    offset: float = 0.0
    zone: float = Field(default=1.0, gt=0.0, le=1.0)


class JonesElement(StrictModel):
    """Ideal polarising element at a surface (applied after the interface, in the plane normal to the ray;
    polarisation analyses only). Angles from local x towards local y."""

    kind: Literal["polarizer", "retarder"] = "polarizer"
    angle_deg: float = Field(default=0.0, ge=-360.0, le=360.0, description="polariser: transmission axis; retarder: fast axis")
    retardance_waves: float = Field(default=0.25, ge=-10.0, le=10.0, description="retarder: phase delay of the slow axis (waves)")


class Surface(StrictModel):
    id: str = Field(default_factory=new_id)
    type: SurfaceType = "standard"
    label: str = ""
    comment: str = ""
    radius: float | None = Field(default=None, description="mm; null = infinite (plane)")
    thickness: float | None = Field(default=0.0, description="mm; null = infinity (object only)")
    material: str = Field(default="AIR", description="Material after this surface; MIRROR reflects")
    semi_diameter: float = Field(default=10.0, ge=0.0)
    semi_diameter_mode: SemiDiameterMode = "auto"
    conic: float = 0.0
    radius_x: float | None = Field(default=None, description="biconic: radius of the x-z section (mm); null = flat in x")
    conic_x: float = Field(default=0.0, description="biconic: conic constant of the x-z section")
    aspheric: list[float] = Field(
        default_factory=list,
        description="Even asphere coefficients A4, A6, A8, ... (mm^-3, mm^-5, ...)",
        max_length=8,
    )
    is_stop: bool = False
    obscuration: float | None = Field(default=None, ge=0.0, description="radius (mm) of a central circular obscuration on this surface: rays that meet it inside this radius are blocked (chief rays pass); null = none")
    # mechanics of the lens element (elements.py, CAD export, drawings); no effect on the trace
    mech_semi_diameter: float | None = Field(default=None, ge=0.0, description="where the optical surface ends (mm); null = the clear semi-diameter; a flat continues to the element's rim")
    chamfer: float = Field(default=0.0, ge=0.0, le=50.0, description="45 deg protective chamfer at the element's rim on this surface (mm, leg length)")
    coating: str = Field(default="", description="Thin-film coating name (built-in or custom_coatings); empty = uncoated")
    # Zernike sag surface (type "zernike"): base conic/asphere + Fringe Zernike terms; see surfaces.ZernikeShape
    zernike_coefficients: list[float] = Field(default_factory=list, max_length=37, description="Fringe Zernike sag coefficients Z1.. (mm)")
    zernike_norm_radius: float = Field(default=10.0, gt=0.0, description="normalisation radius of the Zernike terms (mm)")
    # odd asphere (type "odd_asphere"): base conic + sum beta_i r^i, i = 1.. (odd and even powers); surfaces.OddShape
    odd_coefficients: list[float] = Field(default_factory=list, max_length=16, description="odd-asphere coefficients beta_1.. on r^1, r^2, ... (mm^(1-i))")
    # Forbes Q-type aspheres (types "qcon", "qbfs"); see qpoly.py and surfaces.QShape
    q_coefficients: list[float] = Field(default_factory=list, max_length=30, description="Q-polynomial coefficients a_0.. (mm)")
    q_norm_radius: float = Field(default=10.0, gt=0.0, description="normalisation radius of the Q polynomials (mm)")
    # XY-polynomial freeform (type "xy_polynomial"): base conic/asphere + sum A_k (x/R)^i (y/R)^j; see qpoly.xy_exponents
    xy_coefficients: list[float] = Field(default_factory=list, max_length=65, description="XY-polynomial coefficients A_1.. (mm): x, y, x^2, xy, y^2, ...")
    xy_norm_radius: float = Field(default=10.0, gt=0.0, description="normalisation radius of the XY polynomial (mm)")
    # diffractive phase (any refracting surface or mirror); see diffractive.py
    grating_frequency: float = Field(default=0.0, description="linear grating, lines/mm (lines parallel to local x)")
    phase_coefficients: list[float] = Field(default_factory=list, max_length=8, description="radial phase A1.. (radians at phase_norm_radius)")
    phase_norm_radius: float = Field(default=1.0, gt=0.0, description="normalisation radius of the radial phase (mm)")
    diffraction_order: int = Field(default=1, ge=-50, le=50)
    # ideal (paraxial) lens (type "ideal"): perfect imaging in tangent space, see raytrace._ideal_lens
    focal_length: float | None = Field(default=100.0, description="ideal lens: focal length in the surrounding medium (mm); null = no power")
    ideal_object_distance: float | None = Field(default=None, description="ideal lens: object distance (mm, along the light) for which the OPD is exact; null = infinity")
    thickness_solve: Solve | None = None
    curvature_solve: Solve | None = None
    # Coordinate break parameters (only used when type == coordinate_break)
    decenter_x: float = 0.0
    decenter_y: float = 0.0
    tilt_x: float = 0.0
    tilt_y: float = 0.0
    tilt_z: float = 0.0
    cb_order: Literal[0, 1] = Field(
        default=0, description="0: decenter then tilt X,Y,Z; 1: tilt Z,Y,X then decenter"
    )
    # environment model (environment.py): expansion of what sets the gap after this surface (its spacer)
    # or, on a mirror, of its substrate; None = the housing CTE. Glass elements use their glass's CTE.
    mount_cte: float | None = Field(default=None, ge=-50.0, le=500.0, description="thermal expansion coefficient (1e-6/K) of the spacer after this surface or of a mirror substrate; null = housing")
    # mount tree (environment.py): the vertex of this surface is held by this mount part (its seat)
    seat_part: str | None = Field(default=None, description="id of the MountPart that holds this surface's vertex; null = positioned by the gap before it")
    element_temperature_c: float | None = Field(default=None, ge=-273.0, le=1000.0, description="temperature of the glass after this surface (its element) when it differs from the system; null = system")
    # uniaxial crystal after this surface (a material with an extraordinary index; birefringence.py)
    crystal_axis: list[float] | None = Field(default=None, min_length=3, max_length=3, description="optic axis of the crystal after this surface in this surface's local frame (any length); null = local z")
    crystal_mode: Literal["ordinary", "extraordinary"] | None = Field(default=None, description="wave the sequential trace follows in the crystal after this surface; null = ordinary")
    # ideal polariser or retarder at this surface (polarisation analyses)
    jones: JonesElement | None = None

    @field_validator("radius")
    @classmethod
    def _radius(cls, v: float | None) -> float | None:
        if v is None:
            return None
        if not math.isfinite(v):
            return None
        if v == 0.0:
            raise ValueError("radius 0 is undefined; use null (infinity) for a plane")
        return v

    @field_validator("radius_x")
    @classmethod
    def _radius_x(cls, v: float | None) -> float | None:
        if v is None or not math.isfinite(v):
            return None
        if v == 0.0:
            raise ValueError("radius_x 0 is undefined; use null (infinity) for a flat x section")
        return v

    @field_validator("focal_length", "ideal_object_distance")
    @classmethod
    def _focal(cls, v: float | None) -> float | None:
        if v is None or not math.isfinite(v):
            return None
        if v == 0.0:
            raise ValueError("0 is undefined; use null (infinity)")
        return v

    @field_validator("crystal_axis")
    @classmethod
    def _crystal_axis(cls, v: list[float] | None) -> list[float] | None:
        if v is not None and (not all(math.isfinite(x) for x in v) or math.hypot(*v) < 1e-12):
            raise ValueError("the crystal axis needs a non-zero direction")
        return v

    @field_validator("thickness")
    @classmethod
    def _thickness(cls, v: float | None) -> float | None:
        if v is not None and not math.isfinite(v):
            return None
        return v

    @field_validator("material")
    @classmethod
    def _material(cls, v: str) -> str:
        v = (v or "").strip().upper()
        return v or "AIR"

    @property
    def curvature(self) -> float:
        return 0.0 if self.radius is None else 1.0 / self.radius

    @property
    def is_diffractive(self) -> bool:
        return self.grating_frequency != 0.0 or any(a != 0.0 for a in self.phase_coefficients)

    @property
    def curvature_x(self) -> float:
        return 0.0 if self.radius_x is None else 1.0 / self.radius_x

    @property
    def is_mirror(self) -> bool:
        return self.material == "MIRROR"


class Wavelength(StrictModel):
    value: float = Field(gt=0.0, description="Vacuum wavelength in micrometres")
    weight: float = Field(default=1.0, ge=0.0)


class FieldPoint(StrictModel):
    x: float = 0.0
    y: float = 0.0
    weight: float = Field(default=1.0, ge=0.0)
    # vignetting factors (raytrace.vignetted_pupil): the sampled pupil of this field is
    # px' = vdx + px (1 - vcx), py' = vdy + py (1 - vcy) in normalised pupil coordinates
    vdx: float = Field(default=0.0, ge=-1.0, le=1.0, description="vignetting decenter x (normalised pupil)")
    vdy: float = Field(default=0.0, ge=-1.0, le=1.0, description="vignetting decenter y (normalised pupil)")
    vcx: float = Field(default=0.0, ge=0.0, le=0.999, description="vignetting compression x")
    vcy: float = Field(default=0.0, ge=0.0, le=0.999, description="vignetting compression y")


class Aperture(StrictModel):
    type: ApertureType = "epd"
    value: float = Field(default=10.0, gt=0.0)


ConfigParameter = Literal[
    "thickness",
    "radius",
    "conic",
    "material",
    "semi_diameter",
    "decenter_x",
    "decenter_y",
    "tilt_x",
    "tilt_y",
    "tilt_z",
    "aperture_value",
    "temperature",
    "pressure",
    "vdx",
    "vdy",
    "vcx",
    "vcy",
]
CONFIG_SYSTEM_PARAMS = ("aperture_value", "temperature", "pressure")
# a field's vignetting factors per configuration (a zoom lens vignettes differently at each position)
CONFIG_FIELD_PARAMS = ("vdx", "vdy", "vcx", "vcy")
CONFIG_SURFACE_PARAMS = ("thickness", "radius", "conic", "material", "semi_diameter", "decenter_x", "decenter_y", "tilt_x", "tilt_y", "tilt_z")


class ConfigOperand(StrictModel):
    """One row of the configuration editor: a parameter and its value in every configuration."""

    parameter: ConfigParameter
    surface_id: str | None = None  # None for system and field parameters
    field: int | None = Field(None, ge=0)  # the field (index) of a field parameter (CONFIG_FIELD_PARAMS)
    values: list[float | str | None]


class MultiConfig(StrictModel):
    names: list[str] = Field(min_length=1, max_length=64)
    operands: list[ConfigOperand] = Field(default_factory=list)
    active: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check(self) -> "MultiConfig":
        n = len(self.names)
        if self.active >= n:
            raise ValueError("active configuration index out of range")
        seen = set()
        for k, op in enumerate(self.operands):
            if len(op.values) != n:
                raise ValueError(f"Configuration operand {k + 1}: expected {n} values, got {len(op.values)}")
            key = (op.parameter, op.surface_id, op.field)
            if key in seen:
                raise ValueError(f"Configuration operand {k + 1}: duplicate {op.parameter} for the same {'field' if op.field is not None else 'surface'}")
            seen.add(key)
            if op.parameter in CONFIG_FIELD_PARAMS:
                if op.field is None or op.surface_id is not None:
                    raise ValueError(f"Configuration operand {k + 1}: {op.parameter} is a field parameter (a field, no surface)")
            elif op.field is not None:
                raise ValueError(f"Configuration operand {k + 1}: {op.parameter} is not a field parameter")
            elif op.parameter in CONFIG_SYSTEM_PARAMS:
                if op.surface_id is not None:
                    raise ValueError(f"{op.parameter} is a system parameter (no surface)")
            elif op.surface_id is None:
                raise ValueError(f"Configuration operand {k + 1}: {op.parameter} needs a surface")
            for v in op.values:
                if op.parameter == "material":
                    if not isinstance(v, str) or not v.strip():
                        raise ValueError(f"Configuration operand {k + 1}: material values must be names")
                elif op.parameter in ("radius", "thickness"):
                    if v is not None and (isinstance(v, str) or not math.isfinite(v) or (op.parameter == "radius" and v == 0)):
                        raise ValueError(f"Configuration operand {k + 1}: invalid {op.parameter} value {v!r}")
                elif op.parameter in CONFIG_FIELD_PARAMS:
                    lo, hi = (-1.0, 1.0) if op.parameter in ("vdx", "vdy") else (0.0, 0.999)
                    if v is None or isinstance(v, str) or not (lo <= v <= hi):
                        raise ValueError(f"Configuration operand {k + 1}: {op.parameter} must lie in [{lo:g}, {hi:g}]")
                elif v is None or isinstance(v, str) or not math.isfinite(v):
                    raise ValueError(f"Configuration operand {k + 1}: {op.parameter} needs finite numbers")
        return self


class CoatingLayer(StrictModel):
    material: str = Field(default="", description="library material giving n(lambda); empty = fixed index")
    index: float = Field(default=1.38, gt=0.0, le=10.0, description="fixed real index n (when no material)")
    extinction: float = Field(default=0.0, ge=0.0, le=100.0, description="extinction coefficient k (N = n - i k)")
    thickness_nm: float = Field(ge=0.0, le=1e6, description="physical thickness (nm)")


class CoatingDefinition(StrictModel):
    """User-defined thin-film stack. Layers run from the low-index (air) side
    towards the substrate; on a mirror, from the incident medium towards the
    substrate given by substrate_index / substrate_extinction."""

    name: str = Field(min_length=1, max_length=40)
    description: str = ""
    layers: list[CoatingLayer] = Field(default_factory=list, max_length=200)
    substrate_index: float | None = Field(default=None, gt=0.0, le=100.0, description="mirror substrate n (None: not for mirrors)")
    substrate_extinction: float = Field(default=0.0, ge=0.0, le=100.0, description="mirror substrate k")
    design: dict | None = Field(default=None, description="coating designer source (palette, targets, deposition order); not used by the trace")


class Sensor(StrictModel):
    """An image sensor centred on the image surface (analysis/imaging.py): square pixels of `pixel_pitch_um`
    whose light-sensitive area is a centred square of fill_factor x the pixel area."""

    pixel_pitch_um: float = Field(default=3.45, gt=0.0, le=100.0)
    fill_factor: float = Field(default=1.0, gt=0.0, le=1.0)
    width_px: int = Field(default=640, ge=8, le=16384)
    height_px: int = Field(default=480, ge=8, le=16384)
    full_well_e: float = Field(default=10000.0, gt=0.0, le=1e7)
    read_noise_e: float = Field(default=5.0, ge=0.0, le=1e4)
    bit_depth: int = Field(default=12, ge=1, le=16)


class MountPart(StrictModel):
    """A mechanical part of the mount tree (environment.py): it attaches to its parent (or to the fixed
    reference) at datum_z and expands with its own CTE at its own temperature."""

    id: str = Field(default_factory=new_id)
    name: str = ""
    cte: float = Field(default=23.6, ge=-50.0, le=500.0, description="linear expansion (1e-6/K)")
    temperature_c: float | None = Field(default=None, ge=-273.0, le=1000.0, description="null = system temperature")
    parent: str | None = Field(default=None, description="id of the part it attaches to; null = the fixed reference")
    datum_z: float = Field(default=0.0, description="axial position (mm, along the unfolded axis from surface 1) where it attaches to its parent")
    cad_asset_id: str | None = None
    cad_node_id: str | None = None


class OpticalSystem(StrictModel):
    name: str = "Untitled system"
    units: Literal["mm"] = "mm"
    surfaces: list[Surface]
    wavelengths: list[Wavelength] = Field(
        default_factory=lambda: [Wavelength(value=0.5875618)], min_length=1, max_length=24
    )
    primary_wavelength: int = Field(default=0, ge=0)
    field_type: FieldType = "angle"
    fields: list[FieldPoint] = Field(default_factory=lambda: [FieldPoint()], min_length=1, max_length=25)
    aperture: Aperture = Field(default_factory=Aperture)
    ray_aiming: RayAiming = "paraxial"
    # object-space telecentric: chief rays leave the object parallel to the axis (entrance pupil at infinity);
    # needs a finite object distance and an object-space NA aperture
    object_space_telecentric: bool = False
    # environment (environment.py): off by default, so catalogue indices and the prescription are used as given
    temperature_c: float = Field(default=20.0, ge=-273.0, le=1000.0, description="system temperature (degC); used when environment_enabled")
    pressure_atm: float = Field(default=1.0, ge=0.0, le=100.0, description="air pressure (atm, 0 = vacuum); used when environment_enabled")
    environment_enabled: bool = Field(default=False, description="model temperature and pressure: air index, glass dn/dT and thermal expansion")
    housing_cte: float = Field(default=23.6, ge=-50.0, le=500.0, description="housing/spacer expansion (1e-6/K) where a surface gives none; default aluminium 6061")
    catalog_absorption: bool = Field(default=False, description="absorb in glass by the catalogue internal transmittance (per wavelength) where a material has it")
    sensor: Sensor | None = Field(default=None, description="image sensor for the sensor-aware analyses (pixel MTF, image simulation)")
    mounts: list[MountPart] = Field(default_factory=list, max_length=100, description="mount tree of the environment model")
    multi_config: MultiConfig | None = None
    custom_coatings: list[CoatingDefinition] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _check(self) -> "OpticalSystem":
        s = self.surfaces
        if len(s) < 3:
            raise ValueError("A sequential system needs an object surface, at least one surface and an image surface")
        for i, surf in enumerate(s):
            if surf.thickness is None and i != 0:
                raise ValueError(f"Surface {i}: only the object surface may have infinite thickness")
        if s[0].type == "coordinate_break" or s[-1].type == "coordinate_break":
            raise ValueError("Object and image surfaces cannot be coordinate breaks")
        for i, surf in enumerate(s):
            if surf.type in ("zernike", "qbfs", "xy_polynomial") and surf.curvature_solve is not None:
                raise ValueError(f"Surface {i}: curvature solves are not supported on {surf.type} surfaces (their polynomial terms change the vertex curvature)")
        if s[0].is_mirror:
            raise ValueError("The object surface cannot be a mirror")
        stops = [i for i, x in enumerate(s) if x.is_stop]
        if len(stops) > 1:
            raise ValueError(f"Only one aperture stop is allowed (found at surfaces {stops})")
        if stops and s[stops[0]].type == "coordinate_break":
            raise ValueError("The aperture stop cannot be a coordinate break")
        if stops and stops[0] in (0, len(s) - 1):
            raise ValueError("The aperture stop cannot be the object or image surface")
        if self.primary_wavelength >= len(self.wavelengths):
            raise ValueError("primary_wavelength index out of range")
        ids = [x.id for x in s]
        if len(set(ids)) != len(ids):
            raise ValueError("Surface ids must be unique")
        parts = {m.id: m for m in self.mounts}
        if len(parts) != len(self.mounts):
            raise ValueError("Mount part ids must be unique")
        for m in self.mounts:
            seen, cur = {m.id}, m.parent
            while cur is not None:
                if cur not in parts:
                    raise ValueError(f"Mount part '{m.name or m.id}' attaches to an unknown part '{cur}'")
                if cur in seen:
                    raise ValueError(f"Mount part '{m.name or m.id}' is part of a cycle")
                seen.add(cur)
                cur = parts[cur].parent
        for i, x in enumerate(s):
            if x.seat_part is not None and x.seat_part not in parts:
                raise ValueError(f"Surface {i} is seated on an unknown mount part '{x.seat_part}'")
        if self.field_type == "object_height" and s[0].thickness is None:
            raise ValueError("Object-height fields require a finite object distance")
        if self.aperture.type == "object_na" and s[0].thickness is None:
            raise ValueError("Object-space NA requires a finite object distance")
        if self.object_space_telecentric:
            if s[0].thickness is None or s[0].thickness <= 0:
                raise ValueError("An object-space telecentric system needs a real object at a finite distance")
            if self.aperture.type != "object_na":
                raise ValueError("An object-space telecentric system needs an object-space NA aperture (the entrance pupil is at infinity)")
            if self.field_type == "angle":
                raise ValueError("An object-space telecentric system needs object-height or image-height fields (chief rays are parallel to the axis)")
        for i, surf in enumerate(s):
            if surf.type != "ideal":
                continue
            if i in (0, len(s) - 1):
                raise ValueError("The object and image surfaces cannot be ideal lenses")
            if surf.is_mirror:
                raise ValueError(f"Surface {i}: an ideal lens cannot be a mirror")
            if surf.curvature_solve is not None:
                raise ValueError(f"Surface {i}: an ideal lens has no curvature to solve")
        cnames = [c.name.strip().upper() for c in self.custom_coatings]
        if len(set(cnames)) != len(cnames):
            raise ValueError("Custom coating names must be unique")
        if self.multi_config is not None:
            for k, op in enumerate(self.multi_config.operands):
                if op.surface_id is not None and op.surface_id not in ids:
                    raise ValueError(f"Configuration operand {k + 1} refers to unknown surface id '{op.surface_id}'")
                if op.field is not None and op.field >= len(self.fields):
                    raise ValueError(f"Configuration operand {k + 1} refers to field {op.field + 1}, which does not exist")
        return self

    @property
    def stop_index(self) -> int:
        for i, x in enumerate(self.surfaces):
            if x.is_stop:
                return i
        return 1

    @property
    def primary_wavelength_um(self) -> float:
        return self.wavelengths[self.primary_wavelength].value

    @property
    def object_at_infinity(self) -> bool:
        return self.surfaces[0].thickness is None
