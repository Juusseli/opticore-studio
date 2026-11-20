"""Temperature and pressure (docs/OPTICAL_ENGINE.md §9a).

The environment model is off by default (`OpticalSystem.environment_enabled`): then catalogue indices are
used as they are and the prescription is taken as given. When it is on:

* Indices are relative to the air of the system at its temperature T and pressure P, and wavelengths are
  wavelengths in that air (the convention of glass catalogues and of the established design programs).
  AIR has index 1; VACUUM has 1 / n_air(T, P).
* A glass index is built in absolute terms: the catalogue index (relative to air at the glass's reference
  temperature T0 and 1 atm) times that air's index gives n_abs(λ, T0); the absolute Schott model adds
  Δn_abs(λ, T); dividing by the system air's index gives the index relative to the system air. A lens
  element can have its own temperature (Surface.element_temperature_c); the air keeps the system's.
* The prescription is the design at the reference temperature T_REF = 20 °C. Each glass element expands
  homothetically with its glass's CTE (radii, aspheric and Zernike terms, centre thickness, apertures); an
  air gap expands with its spacer (Surface.mount_cte, else the housing CTE); a mirror with its substrate
  (Surface.mount_cte, else the housing). The object distance is not scaled (it is outside the lens).
* Mount tree: mechanical parts (OpticalSystem.mounts) attach to their parent at a datum and expand
  with their own CTE at their own temperature; a surface seated on a part (Surface.seat_part) moves with
  it, and its element follows; the gaps between elements are whatever the mounts leave.

Air index: Edlén's 1953 dispersion formula for standard air (15 °C, 1 atm) scaled to T and P by the
Kohlrausch (ideal gas) relation, as given in SCHOTT TIE-19 "Temperature Coefficient of the Refractive
Index" (2016). Glass dn/dT: the absolute Schott model of the same document (coefficients D0, D1, D2, E0, E1,
λTK from the glass data sheet).
"""

from __future__ import annotations

from dataclasses import dataclass

from .materials import MaterialError
from .materials.catalog import AIR_NAMES, MIRROR_NAME, VACUUM_NAMES, Material, MaterialLibrary
from .model import OpticalSystem

T_REF = 20.0  # degC: temperature at which the prescription and the CTEs are defined
P_REF = 1.0  # atm: pressure of the catalogue air
EXPANSION_RANGE = (-30.0, 70.0)  # degC: range of the catalogue CTE (TCE -30..+70)


@dataclass(frozen=True)
class Environment:
    temperature_c: float
    pressure_atm: float
    housing_cte: float  # 1e-6 / K

    @property
    def delta_t(self) -> float:
        return self.temperature_c - T_REF


def environment_of(system: OpticalSystem) -> Environment | None:
    """The system's environment, or None when the model is off."""
    if not system.environment_enabled:
        return None
    return Environment(float(system.temperature_c), float(system.pressure_atm), float(system.housing_cte))


def air_index(wavelength_um: float, temperature_c: float, pressure_atm: float) -> float:
    """Refractive index of dry air (Edlén 1953 at 15 °C, 1 atm; Kohlrausch T, P scaling; SCHOTT TIE-19).

    n_ref − 1 = [6432.8 + 2949810 λ²/(146 λ² − 1) + 25540 λ²/(41 λ² − 1)] · 1e-8   (λ in µm)
    n(T, P) − 1 = (n_ref − 1) · P / (1 + 3.4785e-3 (T − 15))                        (T in °C, P in atm)
    """
    L2 = wavelength_um * wavelength_um
    n_ref_1 = (6432.8 + 2949810.0 * L2 / (146.0 * L2 - 1.0) + 25540.0 * L2 / (41.0 * L2 - 1.0)) * 1e-8
    return 1.0 + n_ref_1 * pressure_atm / (1.0 + 3.4785e-3 * (temperature_c - 15.0))


def glass_cte(mat: Material) -> float | None:
    """Linear expansion coefficient (1/K) from the catalogue (TCE −30..+70 °C, stored in 1e-6/K)."""
    v = mat.extra.get("tce_m30_70")
    return None if v is None else float(v) * 1e-6


def absolute_index(mat: Material, wavelength_um: float, n_air_system: float, temperature_c: float) -> float:
    """Absolute index of a material at temperature T for a wavelength given in the system air (whose
    index is n_air_system). The air formula takes the same wavelength argument throughout (its vacuum/air
    distinction is far below its accuracy), so at the reference conditions the result divided by
    n_air_system is exactly the catalogue index."""
    th = mat.dispersion.thermal
    t0 = th.T0 if th is not None else T_REF
    vacuum = wavelength_um * n_air_system
    n_air0 = air_index(wavelength_um, t0, P_REF)
    n_abs0 = mat.index(vacuum / n_air0) * n_air0  # catalogue: relative to air at T0, 1 atm
    if th is None or temperature_c == t0:
        return n_abs0
    dT = temperature_c - t0
    L = vacuum
    dn = (n_abs0 * n_abs0 - 1.0) / (2.0 * n_abs0) * (
        th.D0 * dT + th.D1 * dT**2 + th.D2 * dT**3 + (th.E0 * dT + th.E1 * dT**2) / (L * L - th.lambda_tk**2)
    )
    return n_abs0 + dn


class EnvironmentLibrary:
    """A MaterialLibrary view whose index() is relative to the system air at (T, P) for wavelengths in
    that air. Everything else is delegated to the wrapped library."""

    def __init__(self, library: MaterialLibrary, env: Environment):
        self._lib = library
        self.env = env
        self._cache: dict[tuple[str, float, float], float] = {}

    def __getattr__(self, name):
        return getattr(self._lib, name)

    def index(self, name: str, wavelength_um: float) -> float:
        return self.index_at(name, wavelength_um, None)

    def index_at(self, name: str, wavelength_um: float, temperature_c: float | None) -> float:
        """Index relative to the system air; a glass at `temperature_c` (its element's own temperature)
        or, when None, at the system temperature. Gases are always at the system condition."""
        key = (name or "").strip().upper()
        if key in AIR_NAMES:
            return 1.0
        env = self.env
        t = env.temperature_c if temperature_c is None else float(temperature_c)
        ck = (key, float(wavelength_um), t)
        if ck in self._cache:
            return self._cache[ck]
        n_air = air_index(wavelength_um, env.temperature_c, env.pressure_atm)
        if key in VACUUM_NAMES:
            n = 1.0 / n_air
        else:
            n = absolute_index(self._lib.get(key), wavelength_um, n_air, t) / n_air
        self._cache[ck] = n
        return n


def medium_index(library, name: str, wavelength_um: float, owner_temperature_c: float | None) -> float:
    """Index of a medium: through the element temperature when the library models the environment."""
    if isinstance(library, EnvironmentLibrary):
        return library.index_at(name, wavelength_um, owner_temperature_c)
    return library.index(name, wavelength_um)


def _glass(name: str) -> bool:
    key = (name or "").strip().upper()
    return key not in AIR_NAMES and key not in VACUUM_NAMES and key not in (MIRROR_NAME, "")


def element_temperatures(system: OpticalSystem) -> dict[str, float]:
    """Temperature of each glass medium, keyed by the id of the surface that starts it (its element):
    the element's own temperature where set, else the system temperature."""
    from .system import _media

    out: dict[str, float] = {}
    by_id = {s.id: s for s in system.surfaces}
    for name, owner, _sign in _media(system.surfaces):
        if _glass(name) and owner not in out:
            t = by_id[owner].element_temperature_c
            out[owner] = float(system.temperature_c if t is None else t)
    return out


def thermal_scales(system: OpticalSystem, library: MaterialLibrary, env: Environment, diags: list | None = None) -> tuple[list[float], list[float]]:
    """(shape scale, thickness scale) per surface: 1 + α ΔT with the CTE that governs each.

    Shape: a refracting surface follows the glass after it, else the glass before it (the rear face of an
    element); a mirror its substrate (mount_cte, else the housing); surfaces between two gases do not
    scale. Thickness after a surface: the glass of the medium, else the spacer (mount_cte, else housing;
    after a mirror always the housing, since a mirror's mount_cte is its substrate). Glass uses its
    element's temperature (Surface.element_temperature_c), everything else the system temperature.
    """
    from .system import Diagnostic, _media

    surfs = system.surfaces
    n = len(surfs)
    dT = env.delta_t
    housing = env.housing_cte * 1e-6
    media = _media(surfs)
    temps = element_temperatures(system)
    missing: set[str] = set()

    def cte_of(name: str) -> float | None:
        try:
            a = glass_cte(library.get(name))
        except MaterialError:
            return None
        if a is None:
            missing.add(name.strip().upper())
        return a

    def glass_dt(k: int) -> float:
        return temps.get(media[k][1], env.temperature_c) - T_REF

    shape = [1.0] * n
    thick = [1.0] * n
    for i, s in enumerate(surfs):
        a_shape, dt_shape = None, dT
        if i == 0 or s.type in ("coordinate_break", "ideal"):
            pass
        elif s.is_mirror:
            a_shape = s.mount_cte * 1e-6 if s.mount_cte is not None else housing
        elif _glass(media[i][0]):
            a_shape, dt_shape = cte_of(media[i][0]), glass_dt(i)
        elif _glass(media[i - 1][0]):
            a_shape, dt_shape = cte_of(media[i - 1][0]), glass_dt(i - 1)
        if a_shape is not None and i < n - 1:
            shape[i] = 1.0 + a_shape * dt_shape
        if 0 < i < n - 1:
            dt_t = dT
            if _glass(media[i][0]):
                a_t, dt_t = cte_of(media[i][0]), glass_dt(i)
            elif s.is_mirror:
                a_t = housing  # a mirror's mount_cte is its substrate; the gap behind it is housing
            else:
                a_t = s.mount_cte * 1e-6 if s.mount_cte is not None else housing
            if a_t is not None:
                thick[i] = 1.0 + a_t * dt_t
    if diags is not None and (dT != 0.0 or any(t != T_REF for t in temps.values())):
        for m in sorted(missing):
            diags.append(Diagnostic("warning", "THERMAL_NO_CTE", f"{m}: no thermal expansion data; the element keeps its nominal shape and thickness"))
    return shape, thick


# ---------------------------------------------------------------- mount tree
def part_shift(system: OpticalSystem, env: Environment, part_id: str, z: float) -> float:
    """Axial displacement (mm) of the point at nominal axial position z of a mount part: its own expansion
    from its datum plus the displacement of its datum on the parent (the fixed reference does not move)."""
    parts = {m.id: m for m in system.mounts}
    m = parts[part_id]
    t = env.temperature_c if m.temperature_c is None else m.temperature_c
    own = m.cte * 1e-6 * (t - T_REF) * (z - m.datum_z)
    return own + (0.0 if m.parent is None else part_shift(system, env, m.parent, m.datum_z))


def mount_layout(system: OpticalSystem, env: Environment, thick: list[float], diags: list | None = None) -> tuple[list[float | None] | None, dict]:
    """Thicknesses with the seated surfaces placed by the mount tree, or None when no surface is seated.

    Surfaces joined by glass form a block (a lens or a cemented group) that keeps its expanded internal
    thicknesses; a seated block sits where its seat has moved; an unseated block follows the gap before it
    (expanded by the rules in `thick`). Positions run along the axis from the surface 1 vertex, so systems
    with mirrors or coordinate breaks are not supported. Also returns a report: each part's datum
    displacement and each seat's displacement (mm)."""
    from .system import Diagnostic, _media

    surfs = system.surfaces
    n = len(surfs)
    report: dict = {"parts": [], "seats": []}
    seats = {i: s.seat_part for i, s in enumerate(surfs) if s.seat_part is not None and 0 < i}
    for m in system.mounts:
        report["parts"].append({"id": m.id, "datum_shift_mm": 0.0 if m.parent is None else part_shift(system, env, m.parent, m.datum_z)})
    if not seats:
        return None, report
    if any(s.is_mirror or s.type == "coordinate_break" for s in surfs):
        if diags is not None:
            diags.append(Diagnostic("warning", "MOUNT_UNSUPPORTED", "Mounts place surfaces along a straight axis; with mirrors or coordinate breaks the seats are ignored (gaps follow their spacers)"))
        return None, report
    media = _media(surfs)
    t_nom = [s.thickness for s in surfs]
    s_nom = [0.0] * n
    for i in range(1, n - 1):
        s_nom[i + 1] = s_nom[i] + (t_nom[i] or 0.0)
    t_exp = [None if t_nom[i] is None else t_nom[i] * thick[i] for i in range(n)]
    # blocks: a new one starts after every gas
    blocks: list[list[int]] = []
    for i in range(1, n):
        if i == 1 or not _glass(media[i - 1][0]):
            blocks.append([i])
        else:
            blocks[-1].append(i)
    s_new = [0.0] * n
    t_new = list(t_exp)
    prev_last: int | None = None
    for b in blocks:
        off = {b[0]: 0.0}
        for k in b[1:]:
            off[k] = off[k - 1] + (t_exp[k - 1] or 0.0)
        seated = [j for j in b if j in seats]
        if len(seated) > 1 and diags is not None:
            diags.append(Diagnostic("warning", "MOUNT_OVERCONSTRAINED", f"Surfaces {', '.join(map(str, seated))} of one element are all seated; the first one places it", seated[1]))
        if seated:
            j = seated[0]
            first = s_nom[j] + part_shift(system, env, seats[j], s_nom[j]) - off[j]
        elif prev_last is None:
            first = 0.0
        else:
            first = s_new[prev_last] + (t_exp[prev_last] or 0.0)
        for k in b:
            s_new[k] = first + off[k]
        if prev_last is not None:
            gap = first - s_new[prev_last]
            t_new[prev_last] = gap
            if gap <= 0 and diags is not None:
                diags.append(Diagnostic("warning", "MOUNT_COLLISION", f"The mounts close the gap after surface {prev_last} ({gap:.4g} mm)", prev_last))
        prev_last = b[-1]
    # surface 1 stays the origin of the frame: a seat that moves it moves the object distance instead
    if s_new[1] != 0.0 and t_nom[0] is not None:
        t_new[0] = t_nom[0] + s_new[1]
    for i, j in seats.items():
        report["seats"].append({"surface": i, "part": j, "z_nominal_mm": s_nom[i], "shift_mm": s_new[i] - s_nom[i]})
    return t_new, report


def mount_report(system: OpticalSystem, custom_materials=()) -> dict:
    """Mount displacements at the system's environment (for the Mounts tab): parts and seats."""
    from .configs import apply_configuration

    system = apply_configuration(system)
    env = environment_of(system)
    if env is None:
        return {"enabled": False, "parts": [], "seats": [], "diagnostics": []}
    diags: list = []
    _shape, thick = thermal_scales(system, MaterialLibrary(custom_materials), env)
    _placed, report = mount_layout(system, env, thick, diags)
    return {"enabled": True, "temperature_c": env.temperature_c, **report, "diagnostics": [d.as_dict() for d in diags]}


def apply_environment(system: OpticalSystem, library: MaterialLibrary) -> tuple[OpticalSystem, list]:
    """The prescription at the system temperature (thermal expansion, mount tree), with diagnostics.

    The result keeps `environment_enabled`; compile_raw then uses an EnvironmentLibrary for the indices."""
    from .system import Diagnostic

    env = environment_of(system)
    diags: list = []
    if env is None:
        return system, diags
    lo, hi = EXPANSION_RANGE
    temps = [env.temperature_c, *element_temperatures(system).values(), *(m.temperature_c for m in system.mounts if m.temperature_c is not None)]
    out = [t for t in temps if not lo <= t <= hi]
    if out:
        diags.append(Diagnostic("warning", "THERMAL_RANGE", f"{out[0]:g} °C is outside the −30…+70 °C range of the catalogue expansion coefficients (extrapolated)"))
    if any(t != T_REF for t in temps):
        seen: set[str] = set()
        for s in system.surfaces:
            if _glass(s.material) and s.material.strip().upper() not in seen:
                seen.add(s.material.strip().upper())
                try:
                    mat = library.get(s.material)
                except MaterialError:
                    continue
                if mat.dispersion.thermal is None:
                    diags.append(Diagnostic("warning", "THERMAL_NO_DNDT", f"{mat.name}: no dn/dT data; its index changes only through the air"))
    shape, thick = thermal_scales(system, library, env, diags)
    placed, _report = mount_layout(system, env, thick, diags)
    if placed is None and all(v == 1.0 for v in shape) and all(v == 1.0 for v in thick):
        return system, diags
    d = system.model_dump()
    for i, s in enumerate(d["surfaces"]):
        k = shape[i]
        if k != 1.0:
            if s["radius"] is not None:
                s["radius"] *= k
            if s["radius_x"] is not None:
                s["radius_x"] *= k
            # sag z_k(r) = k z(r / k): A_{2m} r^{2m} -> A_{2m} k^{1-2m}; coefficients start at r^4
            s["aspheric"] = [a * k ** (-(2 * j + 3)) for j, a in enumerate(s["aspheric"])]
            s["zernike_coefficients"] = [z * k for z in s["zernike_coefficients"]]
            s["zernike_norm_radius"] *= k
            # odd asphere: beta_i r^i -> beta_i k^(1-i); Q and XY polynomials: amplitudes (mm) and normalisation radii x k
            s["odd_coefficients"] = [b * k ** (-i) for i, b in enumerate(s["odd_coefficients"])]
            s["q_coefficients"] = [a * k for a in s["q_coefficients"]]
            s["q_norm_radius"] *= k
            s["xy_coefficients"] = [a * k for a in s["xy_coefficients"]]
            s["xy_norm_radius"] *= k
            if s["obscuration"] is not None:
                s["obscuration"] *= k
            s["semi_diameter"] *= k
            s["phase_norm_radius"] *= k
            s["grating_frequency"] /= k
        if placed is not None:
            s["thickness"] = placed[i]
        else:
            t = thick[i]
            if t != 1.0 and s["thickness"] is not None:
                s["thickness"] *= t
    return OpticalSystem.model_validate(d), diags
