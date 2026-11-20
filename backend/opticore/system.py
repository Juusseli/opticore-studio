"""Compilation of an OpticalSystem into numerical data used by the tracers."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .geometry import Frame
from .materials import MaterialError, MaterialLibrary
from .model import OpticalSystem
from .surfaces import BiconicShape, OddShape, QShape, Shape, XYPolyShape, ZernikeShape
from .diffractive import Doe
from .thinfilm import COATINGS, coating_from_definition, get_coating, normalize_name


@dataclass
class Diagnostic:
    level: str  # "info" | "warning" | "error"
    code: str
    message: str
    surface: int | None = None

    def as_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message, "surface": self.surface}


class SystemError_(ValueError):
    """Raised when a system cannot be evaluated at all."""

    def __init__(self, message: str, diagnostics: list[Diagnostic] | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or []


class NotApplicable(SystemError_):
    """The analysis does not apply to this kind of system (a documented limitation, e.g. ghosts of mirror systems or
    a diffraction PSF of an afocal system), not an error in the design: the API reports it as NOT_APPLICABLE and the
    UI says so instead of showing a failure."""


@dataclass(frozen=True)
class IdealLens:
    """Ideal (paraxial) lens: tangent-space mapping t' = t - h/f in a uniform medium (raytrace._ideal_lens)."""

    focal_length: float | None  # mm in the surrounding medium; None = no power
    object_distance: float | None  # conjugate for which the OPD is exact (mm along the light); None = infinity

    @property
    def inv_f(self) -> float:
        return 0.0 if self.focal_length is None else 1.0 / self.focal_length


@dataclass
class CompiledSystem:
    model: OpticalSystem
    library: MaterialLibrary
    shapes: list[Shape]
    frames: list[Frame]  # vertex frame of each surface (for CB: frame *before* the break)
    frames_after: list[Frame]  # frame in which the following thickness is measured
    is_cb: np.ndarray
    is_mirror: np.ndarray
    fixed_sd: np.ndarray  # semi-diameter or inf where not clipping
    wavelengths: np.ndarray
    n_after: np.ndarray  # (n_wl, n_surf) physical index of the medium after each surface
    n_signed: np.ndarray  # same with sign flipped after each reflection (paraxial use)
    absorption: np.ndarray  # (n_wl, n_surf) alpha (1/mm) of the medium after each surface
    coatings: list = field(default_factory=list)  # (n_surf,) thinfilm.Coating or None
    does: list = field(default_factory=list)  # (n_surf,) diffractive.Doe or None
    ideal: list = field(default_factory=list)  # (n_surf,) IdealLens or None
    crystal: list = field(default_factory=list)  # (n_surf,) CrystalMedium of the medium after each surface, or None
    jones: list = field(default_factory=list)  # (n_surf,) model.JonesElement or None (polarisation analyses)
    obscuration: np.ndarray | None = None  # (n_surf,) central obscuration radius (mm), 0 = none
    field_cache: dict = field(default_factory=dict)  # fields.py: resolved image-height fields
    coating_library: dict = field(default_factory=dict)  # custom coatings by name (thinfilm.Coating)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def n_surfaces(self) -> int:
        return len(self.shapes)

    @property
    def stop(self) -> int:
        return self.model.stop_index

    @property
    def axial(self) -> bool:
        """True when no coordinate break changes the geometry."""
        return all(f.is_axial() for f in self.frames[1:]) and all(f.is_axial() for f in self.frames_after[1:])

    def wl_index(self, wl: int | None) -> int:
        return self.model.primary_wavelength if wl is None else wl


@dataclass
class CrystalMedium:
    """A uniaxial crystal medium (birefringence.py): ordinary and extraordinary indices per wavelength, the
    optic axis (global unit vector) and the wave the sequential trace follows."""

    owner: int  # surface index that starts the medium (its crystal_axis / crystal_mode)
    no: np.ndarray  # (n_wl,)
    ne: np.ndarray  # (n_wl,)
    axis: np.ndarray  # (3,) global
    mode: str  # ordinary | extraordinary
    material: str = ""

    def at(self, wl: int, frame=None, mode: str | None = None):
        """birefringence.Uniaxial at wavelength index wl, the axis in `frame`'s local coordinates (global without)."""
        from .birefringence import Uniaxial

        ax = self.axis if frame is None else frame.to_local_dirs(self.axis[None, :])[0]
        return Uniaxial(float(self.no[wl]), float(self.ne[wl]), ax, mode or self.mode)


def _fmt_r(c: float) -> str:
    return "inf" if abs(c) < 1e-15 else f"{1.0 / c:.6g} mm"


def compile_system(system: OpticalSystem, custom_materials=(), index_offsets: dict | None = None) -> CompiledSystem:
    """Compile a system: apply the active configuration (configs.py), the environment's thermal expansion
    (environment.py), then resolve paraxial solves and pickups (solves.py). Solves therefore act on the
    system as it is at its temperature."""
    if system.multi_config is not None and system.multi_config.operands:
        from .configs import apply_configuration

        system = apply_configuration(system)
    env_diags: list[Diagnostic] = []
    if system.environment_enabled:
        from .environment import apply_environment

        try:
            system, env_diags = apply_environment(system, MaterialLibrary(custom_materials))
        except MaterialError as exc:
            raise SystemError_(str(exc)) from exc
    if any(s.thickness_solve is not None or s.curvature_solve is not None for s in system.surfaces):
        from .solves import resolve_solves

        cs = resolve_solves(system, custom_materials, index_offsets)
    else:
        cs = compile_raw(system, custom_materials, index_offsets)
    cs.diagnostics[:0] = env_diags
    return cs


def _media(surfs) -> list[tuple[str, str, float]]:
    """(material name, id of the surface that starts the medium, sign of n) after each surface:
    mirrors and coordinate breaks keep the medium, each reflection flips the sign."""
    out = []
    sign = 1.0
    name, owner = surfs[0].material, surfs[0].id
    for i, s in enumerate(surfs):
        if i > 0 and s.is_mirror:
            sign = -sign
        if i == 0 or not (s.is_mirror or s.type == "coordinate_break"):
            name, owner = s.material, s.id
        out.append((name, owner, sign))
    return out


def index_offset(offsets: dict, owner: str, library, name: str, wavelength_um: float, temperature_c: float | None, n: float) -> float:
    """Index offset of a medium (tolerancing): a constant dn, or (dn, dVd), an Abbe-number change at constant
    nd: dn + kappa (n(lambda) - nd), kappa = -dVd / (Vd + dVd), so that nd, nF - nC and Vd change exactly."""
    o = offsets.get(owner)
    if o is None:
        return 0.0
    if not isinstance(o, tuple):
        return float(o)
    dn, dv = o
    if dv == 0.0:
        return float(dn)
    from .environment import medium_index
    from .materials.dispersion import LAMBDA_C, LAMBDA_D, LAMBDA_F

    nd, nf, nc = (medium_index(library, name, lam, temperature_c) for lam in (LAMBDA_D, LAMBDA_F, LAMBDA_C))
    vd = (nd - 1.0) / (nf - nc)
    return float(dn) - dv / (vd + dv) * (n - nd)


def medium_absorption(library, name: str, wavelength_um: float, use_catalog: bool) -> tuple[float, bool]:
    """Absorption coefficient alpha (1/mm) of a medium: the catalogue internal transmittance when
    `use_catalog` and the material has it (second item: outside its tabulated range), else the
    material's constant absorption coefficient. Gases absorb nothing."""
    if (name or "").strip().upper() in ("AIR", "VACUUM", "MIRROR", ""):
        return 0.0, False
    mat = library.get(name)
    if use_catalog:
        c = mat.catalog_absorption(wavelength_um)
        if c is not None:
            return c
    return mat.absorption_per_mm, False


def with_wavelengths(cs: "CompiledSystem", lams, index_offsets: dict | None = None) -> "CompiledSystem":
    """The compiled system (same geometry, solves already resolved) with further wavelengths appended
    (indices of the media at those wavelengths); used for light sources with their own spectrum."""
    import dataclasses

    extra = [float(x) for x in lams if not np.any(np.isclose(cs.wavelengths, x, rtol=0, atol=1e-12))]
    if not extra:
        return cs
    from .environment import element_temperatures, medium_index

    offsets = index_offsets or {}
    media = _media(cs.model.surfaces)
    temps = element_temperatures(cs.model) if cs.model.environment_enabled else {}
    na = np.ones((len(extra), cs.n_surfaces))
    ns = np.ones((len(extra), cs.n_surfaces))
    ab = np.zeros((len(extra), cs.n_surfaces))
    for i, (name, owner, sign) in enumerate(media):
        for w, lam in enumerate(extra):
            try:
                n0 = medium_index(cs.library, name, lam, temps.get(owner))
                na[w, i] = n0 + index_offset(offsets, owner, cs.library, name, lam, temps.get(owner), n0)
                ab[w, i] = medium_absorption(cs.library, name, lam, cs.model.catalog_absorption)[0]
            except Exception as exc:  # DispersionError
                raise SystemError_(f"Surface {i}: {exc}") from exc
            ns[w, i] = sign * na[w, i]
    return dataclasses.replace(cs, wavelengths=np.concatenate([cs.wavelengths, extra]), n_after=np.vstack([cs.n_after, na]), n_signed=np.vstack([cs.n_signed, ns]), absorption=np.vstack([cs.absorption, ab]), field_cache={})


def compile_raw(system: OpticalSystem, custom_materials=(), index_offsets: dict | None = None) -> CompiledSystem:
    """Compile a system for tracing.

    index_offsets maps the id of a surface that *starts* a medium to a
    refractive-index offset added to that medium at all wavelengths, or to
    (dn, dVd) with an Abbe-number change (index_offset; used by tolerancing;
    the offset follows the medium through mirrors and coordinate breaks until
    the next refracting surface changes it).
    """
    diags: list[Diagnostic] = []
    try:
        lib = MaterialLibrary(custom_materials)
    except MaterialError as exc:
        raise SystemError_(str(exc)) from exc
    if system.environment_enabled:
        from .environment import EnvironmentLibrary, T_REF, environment_of

        env = environment_of(system)
        lib = EnvironmentLibrary(lib, env)
        diags.append(
            Diagnostic(
                "info",
                "ENVIRONMENT",
                f"Environment {env.temperature_c:g} °C, {env.pressure_atm:g} atm: indices relative to the air at these conditions (wavelengths in that air), "
                f"glass dn/dT applied{'' if env.temperature_c == T_REF else f', prescription expanded from {T_REF:g} °C'}",
            )
        )

    surfs = system.surfaces
    n = len(surfs)
    shapes: list[Shape] = []
    for s in surfs:
        if s.type in ("coordinate_break", "ideal"):
            shapes.append(Shape())
            if s.type == "ideal" and (s.radius is not None or s.conic or any(s.aspheric) or s.radius_x is not None):
                diags.append(Diagnostic("info", "IDEAL_SHAPE_IGNORED", "Ideal lens: radius, conic and aspheric terms are ignored (the lens is a plane with a perfect focusing function)", surfs.index(s)))
        elif s.type == "even_asphere":
            shapes.append(Shape(s.curvature, s.conic, tuple(s.aspheric)))
        elif s.type == "odd_asphere":
            k = surfs.index(s)
            shapes.append(OddShape(s.curvature, s.conic, tuple(s.odd_coefficients)))
            if s.aspheric and any(s.aspheric):
                diags.append(Diagnostic("warning", "ASPHERE_IGNORED", "Even-asphere terms are ignored on an odd-asphere surface (enter them as its even-power coefficients)", k))
            if any(b != 0.0 for i, b in enumerate(s.odd_coefficients, start=1) if i in (1, 3)):
                diags.append(Diagnostic("info", "ODD_ASPHERE_PARAXIAL", "Odd asphere: the r and r^3 terms have no paraxial or third-order equivalent; they appear only in real-ray analyses (paraxial data use c + 2 beta_2, the Seidel sums the r^4 term)", k))
            if s.odd_coefficients and s.odd_coefficients[0] != 0.0:
                diags.append(Diagnostic("warning", "ODD_ASPHERE_CONE", "Odd asphere: a non-zero r^1 term makes a cone tip at the vertex (its normal is undefined there)", k))
        elif s.type == "biconic":
            shapes.append(BiconicShape(s.curvature, s.conic, s.curvature_x, s.conic_x))
            if s.curvature != s.curvature_x or s.conic != s.conic_x:
                diags.append(
                    Diagnostic(
                        "info",
                        "BICONIC_PARAXIAL",
                        "Biconic surface: paraxial data (EFL, pupils, solves, Seidel sums) use the y-z section; the x-z section focuses differently (use real-ray analyses)",
                        surfs.index(s),
                    )
                )
        elif s.type in ("qcon", "qbfs"):
            k = surfs.index(s)
            shapes.append(QShape(s.curvature, s.conic, s.type, tuple(s.q_coefficients), s.q_norm_radius))
            if s.type == "qbfs" and s.conic != 0.0:
                diags.append(Diagnostic("warning", "QBFS_CONIC_IGNORED", "A Qbfs surface is a best-fit sphere plus Q terms: its conic constant is ignored (use Qcon for a conic base)", k))
            if s.aspheric and any(s.aspheric):
                diags.append(Diagnostic("warning", "ASPHERE_IGNORED", "Even-asphere terms are ignored on a Q-type surface (convert them to Q coefficients)", k))
        elif s.type == "xy_polynomial":
            k = surfs.index(s)
            xs = XYPolyShape(s.curvature, s.conic, tuple(s.aspheric), tuple(s.xy_coefficients), s.xy_norm_radius)
            shapes.append(xs)
            if any(a != 0.0 for a in s.xy_coefficients):
                diags.append(
                    Diagnostic(
                        "info",
                        "XY_PARAXIAL",
                        f"XY-polynomial surface: paraxial data use the y-z vertex curvature (R_y = {_fmt_r(xs.curvature)}, R_x = {_fmt_r(xs.curvature_x)}); the xy and higher terms appear only in real-ray analyses; Seidel sums omit the polynomial",
                        k,
                    )
                )
            sx, sy = xs.vertex_slope
            if abs(sx) > 1e-12 or abs(sy) > 1e-12:
                diags.append(Diagnostic("warning", "XY_TILT", f"The x and y terms tilt the surface at its vertex (slope {sx:.3g}, {sy:.3g}); paraxial data assume an untilted vertex", k))
        elif s.type == "zernike":
            k = surfs.index(s)
            zs = ZernikeShape(s.curvature, s.conic, tuple(s.aspheric), tuple(s.zernike_coefficients), s.zernike_norm_radius)
            shapes.append(zs)
            if any(a != 0.0 for a in s.zernike_coefficients):
                diags.append(
                    Diagnostic(
                        "info",
                        "ZERNIKE_PARAXIAL",
                        f"Zernike surface: paraxial data use the y-z vertex curvature (R_y = {_fmt_r(zs.curvature)}, R_x = {_fmt_r(zs.curvature_x)}); higher-order and non-symmetric terms appear only in real-ray analyses; Seidel sums omit the Zernike terms",
                        k,
                    )
                )
            sx, sy = zs.vertex_slope
            if abs(sx) > 1e-12 or abs(sy) > 1e-12:
                diags.append(Diagnostic("warning", "ZERNIKE_TILT", f"Zernike tilt terms tilt the surface at its vertex (slope {sx:.3g}, {sy:.3g}); paraxial data assume an untilted vertex", k))
        else:
            if s.aspheric and any(s.aspheric):
                diags.append(
                    Diagnostic("warning", "ASPHERE_IGNORED", "Aspheric terms are ignored on a standard surface", surfs.index(s))
                )
            shapes.append(Shape(s.curvature, s.conic, ()))
        if s.type not in ("zernike", "coordinate_break") and any(a != 0.0 for a in s.zernike_coefficients):
            diags.append(Diagnostic("warning", "ZERNIKE_IGNORED", "Zernike terms are ignored unless the surface type is Zernike", surfs.index(s)))

    # ---- frames: surface 1 vertex at the global origin -------------------
    frames: list[Frame] = [Frame.identity()] * n
    after: list[Frame] = [Frame.identity()] * n
    obj_t = surfs[0].thickness
    frames[0] = Frame(np.array([0.0, 0.0, -(obj_t if obj_t is not None else 0.0)]), np.eye(3))
    after[0] = frames[0]
    current = Frame.identity()
    for i in range(1, n):
        s = surfs[i]
        frames[i] = current
        if s.type == "coordinate_break":
            current = current.coordinate_break(
                s.decenter_x, s.decenter_y, s.tilt_x, s.tilt_y, s.tilt_z, s.cb_order
            )
        after[i] = current
        current = current.translated_local(s.thickness or 0.0)

    # ---- media ----------------------------------------------------------
    wls = np.array([w.value for w in system.wavelengths], dtype=float)
    n_after = np.ones((len(wls), n))
    n_signed = np.ones((len(wls), n))
    absorption = np.zeros((len(wls), n))
    absorption_reported: set = set()
    is_cb = np.array([s.type == "coordinate_break" for s in surfs])
    is_mirror = np.array([s.is_mirror for s in surfs])
    offsets = index_offsets or {}
    from .environment import element_temperatures, medium_index

    temps = element_temperatures(system) if system.environment_enabled else {}
    for i, (s, (medium_name, medium_owner, sign)) in enumerate(zip(surfs, _media(surfs))):
        if not lib.has(medium_name):
            raise SystemError_(
                f"Surface {i}: unknown material '{medium_name}'",
                [Diagnostic("error", "UNKNOWN_MATERIAL", f"Unknown material '{medium_name}'", i)],
            )
        for w, lam in enumerate(wls):
            try:
                n0 = medium_index(lib, medium_name, lam, temps.get(medium_owner))
                n_after[w, i] = n0 + index_offset(offsets, medium_owner, lib, medium_name, lam, temps.get(medium_owner), n0)
            except Exception as exc:  # DispersionError
                raise SystemError_(f"Surface {i}: {exc}") from exc
            n_signed[w, i] = sign * n_after[w, i]
        if medium_name not in ("AIR", "VACUUM", "MIRROR", ""):
            mat = lib.get(medium_name)
            if mat.category == "metal":
                raise SystemError_(f"Surface {i}: {mat.name} is a metal (n, k for coatings and mirror substrates), not a medium light can traverse; use it as a coating layer or a mirror substrate")
            for w, lam in enumerate(wls):
                absorption[w, i], outside = medium_absorption(lib, medium_name, lam, system.catalog_absorption)
                if outside and (mat.name, lam) not in absorption_reported:
                    absorption_reported.add((mat.name, lam))
                    diags.append(Diagnostic("warning", "TRANSMITTANCE_EXTRAPOLATED", f"{mat.name}: {lam:.4f} um is outside the catalogue internal transmittance data; the nearest tabulated value is used", i))
            for lam in wls:
                if not mat.in_range(lam):
                    diags.append(
                        Diagnostic(
                            "warning",
                            "WAVELENGTH_EXTRAPOLATED",
                            f"{mat.name}: {lam:.4f} um is outside the data range "
                            f"{mat.dispersion.lambda_min:.3f}-{mat.dispersion.lambda_max:.3f} um (extrapolated)",
                            i,
                        )
                    )
        if s.type == "coordinate_break" and s.material not in ("AIR", medium_name):
            diags.append(
                Diagnostic("info", "CB_MATERIAL_IGNORED", "Coordinate breaks do not change the medium; material ignored", i)
            )

    custom: dict = {}
    for cd in system.custom_coatings:
        key = normalize_name(cd.name)
        if key in COATINGS or key in ("NONE", "UNCOATED"):
            msg = f"Custom coating '{cd.name}' uses a reserved (built-in) name"
            raise SystemError_(msg, [Diagnostic("error", "COATING_NAME", msg)])
        try:
            custom[key] = coating_from_definition(cd, lib)
        except (MaterialError, ValueError) as exc:
            msg = f"Coating '{cd.name}': {exc}"
            raise SystemError_(msg, [Diagnostic("error", "COATING_MATERIAL", msg)]) from exc

    coatings: list = [None] * n
    for i, s in enumerate(surfs):
        if not s.coating.strip():
            continue
        try:
            c = get_coating(s.coating, custom)
        except ValueError as exc:
            raise SystemError_(
                f"Surface {i}: {exc}", [Diagnostic("error", "UNKNOWN_COATING", str(exc), i)]
            ) from exc
        if c is None:
            continue
        if i in (0, n - 1) or is_cb[i]:
            diags.append(Diagnostic("info", "COATING_IGNORED", "Coatings apply only to refracting surfaces and mirrors; ignored", i))
            continue
        if is_mirror[i] and c.substrate is None:
            diags.append(Diagnostic("warning", "COATING_IGNORED", f"Coating '{c.name}' has no substrate index, so it cannot be used on a mirror; the mirror stays an ideal reflector", i))
            continue
        if not is_mirror[i] and c.substrate is not None:
            diags.append(Diagnostic("info", "COATING_SUBSTRATE_IGNORED", f"Coating '{c.name}': the substrate index applies on mirrors only; here the lens material is the substrate", i))
        for m in c.materials():
            mat = lib.get(m)
            bad = [float(w.value) for w in system.wavelengths if not mat.in_range(float(w.value))]
            if bad:
                diags.append(Diagnostic("warning", "COATING_RANGE", f"Coating '{c.name}': layer material {m} is extrapolated outside its data range at {', '.join(f'{b:g}' for b in bad)} um", i))
        if is_mirror[i]:
            diags.append(Diagnostic("info", "MIRROR_COATING", f"Mirror reflectance from coating '{c.name}' (thin-film calculation) is applied in throughput and polarisation analyses", i))
        coatings[i] = c

    does: list = [None] * n
    for i, s in enumerate(surfs):
        if not s.is_diffractive:
            continue
        if i in (0, n - 1) or is_cb[i]:
            diags.append(Diagnostic("info", "DOE_IGNORED", "Diffractive phase on the object/image surface or a coordinate break is ignored", i))
            continue
        does[i] = Doe(s.diffraction_order, s.grating_frequency, tuple(s.phase_coefficients), s.phase_norm_radius)
        diags.append(Diagnostic("info", "DOE_ACTIVE", f"Diffractive surface (order {s.diffraction_order}): traced with the exact grating equation; Seidel sums, CAD export and the non-sequential trace do not include its phase", i))
        if s.grating_frequency != 0.0:
            diags.append(Diagnostic("info", "GRATING_PARAXIAL", "Linear grating: its deviation is not part of the paraxial data (use real-ray analyses)", i))

    ideal: list = [None] * n
    for i, s in enumerate(surfs):
        if s.type != "ideal":
            continue
        if not np.allclose(n_after[:, i], n_after[:, i - 1], rtol=0, atol=1e-12):
            msg = f"Surface {i}: an ideal lens needs the same medium on both sides (it has no refracting interface)"
            raise SystemError_(msg, [Diagnostic("error", "IDEAL_MEDIA", msg, i)])
        if s.is_diffractive:
            diags.append(Diagnostic("warning", "IDEAL_DOE_IGNORED", "Ideal lens: the diffractive phase is ignored", i))
            does[i] = None
        if s.coating.strip():
            diags.append(Diagnostic("info", "COATING_IGNORED", "Ideal lens: coatings are ignored (no interface)", i))
            coatings[i] = None
        ideal[i] = IdealLens(s.focal_length, s.ideal_object_distance)
        diags.append(
            Diagnostic(
                "info",
                "IDEAL_LENS",
                f"Ideal lens f = {'inf' if s.focal_length is None else f'{s.focal_length:.6g} mm'}: aberration-free imaging (tangent mapping); "
                f"OPD exact for an object at {'infinity' if s.ideal_object_distance is None else f'{s.ideal_object_distance:.6g} mm'}. "
                "No thickness, no Fresnel losses, no reflections; not traced in non-sequential mode or exported to CAD",
                i,
            )
        )

    crystal, jones = _crystals(system, lib, frames, n_after, n_signed, is_mirror, is_cb, does, ideal, coatings, wls, diags)
    obscuration = np.zeros(n)
    for i, s in enumerate(surfs):
        if not s.obscuration:
            continue
        if i in (0, n - 1) or is_cb[i]:
            diags.append(Diagnostic("info", "OBSCURATION_IGNORED", "A central obscuration on the object or image surface or a coordinate break is ignored", i))
            continue
        obscuration[i] = float(s.obscuration)
        diags.append(Diagnostic("info", "OBSCURATION", f"Central obscuration of radius {s.obscuration:.6g} mm: rays inside it are blocked; chief rays (references) are traced through it", i))

    fixed_sd = np.array(
        [s.semi_diameter if (s.semi_diameter_mode == "fixed" and i not in (0,) and not is_cb[i]) else np.inf for i, s in enumerate(surfs)]
    )

    cs = CompiledSystem(
        model=system,
        library=lib,
        shapes=shapes,
        frames=frames,
        frames_after=after,
        is_cb=is_cb,
        is_mirror=is_mirror,
        fixed_sd=fixed_sd,
        wavelengths=wls,
        n_after=n_after,
        n_signed=n_signed,
        absorption=absorption,
        coatings=coatings,
        coating_library=custom,
        does=does,
        ideal=ideal,
        crystal=crystal,
        jones=jones,
        obscuration=obscuration if np.any(obscuration > 0) else None,
        diagnostics=diags,
    )
    if not cs.axial:
        diags.append(
            Diagnostic(
                "info",
                "NON_AXIAL",
                "Coordinate breaks present: paraxial data are computed on the unfolded axis and are approximate",
            )
        )
    stop = system.stop_index
    if any(cs.is_cb[1:stop]) and not cs.axial:
        diags.append(
            Diagnostic(
                "warning",
                "CB_BEFORE_STOP",
                "A coordinate break precedes the stop; use real ray aiming for accurate pupil sampling",
                stop,
            )
        )
    return cs


def _crystals(system, lib, frames, n_after, n_signed, is_mirror, is_cb, does, ideal, coatings, wls, diags):
    """Uniaxial crystal media and ideal polarising elements (birefringence.py, polarization.py). The paraxial
    index of an extraordinary medium is its phase index along the local z axis of the surface that starts it."""
    surfs = system.surfaces
    n = len(surfs)
    crystal: list = [None] * n
    built: dict = {}
    ids = {s.id: k for k, s in enumerate(surfs)}
    for i, (medium_name, medium_owner, sign) in enumerate(_media(surfs)):
        if medium_name in ("AIR", "VACUUM", "MIRROR", ""):
            continue
        mat = lib.get(medium_name)
        if not mat.birefringent:
            continue
        k = ids[medium_owner]
        if k not in built:
            so = surfs[k]
            ax = np.asarray(so.crystal_axis if so.crystal_axis is not None else [0.0, 0.0, 1.0], dtype=float)
            ax = ax / np.linalg.norm(ax)
            mode = so.crystal_mode or "ordinary"
            try:
                ne = np.array([mat.index_e(float(lam)) for lam in wls])
            except Exception as exc:  # DispersionError
                raise SystemError_(f"Surface {k}: {exc}") from exc
            built[k] = CrystalMedium(k, n_after[:, i].copy(), ne, frames[k].to_global_dirs(ax[None, :])[0], mode, mat.name)
            for lam in wls:
                if not mat.extraordinary.in_range(float(lam)):
                    diags.append(Diagnostic("warning", "WAVELENGTH_EXTRAPOLATED", f"{mat.name} (extraordinary): {lam:.4f} um is outside the data range (extrapolated)", k))
            diags.append(
                Diagnostic(
                    "info",
                    "BIREFRINGENT",
                    f"{mat.name} is uniaxial: the trace follows the {mode} wave (optic axis {ax[0]:.4g}, {ax[1]:.4g}, {ax[2]:.4g} in the surface frame). "
                    "Paraxial data use its index along the local z axis; walk-off and the other wave are in the real-ray and polarisation analyses",
                    k,
                )
            )
        cm = built[k]
        crystal[i] = cm
        if cm.mode == "extraordinary":
            cz = float(np.asarray(surfs[k].crystal_axis or [0.0, 0.0, 1.0], dtype=float)[2] / np.linalg.norm(surfs[k].crystal_axis or [0.0, 0.0, 1.0]))
            n_e = 1.0 / np.sqrt(cz * cz / cm.no**2 + (1.0 - cz * cz) / cm.ne**2)
            n_after[:, i] = n_e
            n_signed[:, i] = sign * n_e
    if crystal[0] is not None or (n > 1 and crystal[n - 2] is not None):
        msg = "A birefringent crystal cannot be the object or image space"
        raise SystemError_(msg, [Diagnostic("error", "BIREFRINGENT_SPACE", msg)])
    for j in range(1, n - 1):
        near = crystal[j - 1] is not None or crystal[j] is not None
        if not near:
            continue
        if is_mirror[j] or ideal[j] is not None or does[j] is not None:
            msg = f"Surface {j}: mirrors, ideal lenses and diffractive surfaces cannot border a birefringent crystal"
            raise SystemError_(msg, [Diagnostic("error", "BIREFRINGENT_SURFACE", msg, j)])
        if coatings[j] is not None:
            diags.append(Diagnostic("warning", "BIREFRINGENT_COATING", f"Coating '{coatings[j].name}' on a crystal face: Fresnel losses use the traced wave's index; the polarisation analysis treats the face as uncoated", j))

    jones: list = [None] * n
    for i, s in enumerate(surfs):
        if s.jones is None:
            continue
        if i in (0, n - 1) or is_cb[i] or is_mirror[i]:
            diags.append(Diagnostic("info", "JONES_IGNORED", "Polarising elements apply on refracting (or plane) surfaces only; ignored", i))
            continue
        if crystal[i] is not None:
            msg = f"Surface {i}: a polarising element cannot face into a birefringent crystal"
            raise SystemError_(msg, [Diagnostic("error", "JONES_CRYSTAL", msg, i)])
        jones[i] = s.jones
        what = f"ideal linear polariser at {s.jones.angle_deg:g} deg" if s.jones.kind == "polarizer" else f"ideal retarder ({s.jones.retardance_waves:g} waves, fast axis {s.jones.angle_deg:g} deg)"
        diags.append(Diagnostic("info", "POLARIZING_ELEMENT", f"{what[0].upper()}{what[1:]}: applied in the polarisation analyses (and the vector PSF); ray, spot and throughput analyses do not include it", i))
    return crystal, jones
