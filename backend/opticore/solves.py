"""Paraxial solves and pickups.

A solve replaces a stored thickness or curvature by a value computed from the
first-order (paraxial, primary-wavelength) trace of the system itself:

  thickness  marginal_height  t_j = (h - y_j) / u_j for the marginal ray
                              (scaled by `zone`), i.e. the marginal ray has
                              height h at surface j+1 (h = 0: paraxial focus)
             chief_height     same for the chief ray at the maximum field
             pickup           t_j = scale * t_source + offset
  curvature  marginal_angle   slope after surface j equals `target`:
                              c = (nu_j-1 - n'_j u') / (y_j (n'_j - n_j))
             chief_angle      same for the chief ray
             f_number         marginal slope giving |n' u'| = 1 / (2 F#), with
                              the ray converging (opposite sign to y_j)
             pickup           R_j = scale * R_source (plane stays plane)

Because a solve can change the entrance pupil or the rays that later solves
use, all solves are updated together and the system is recompiled until the
values no longer change (relative 1e-13, at most 40 iterations). Solves
after the stop converge in one update. The resolved values are what every
analysis, the optimiser and the tolerance analysis see. Paraxial solves are
first-order and are labelled as such in the UI.
"""

from __future__ import annotations

import math

from .model import CURVATURE_SOLVES, THICKNESS_SOLVES, OpticalSystem
from .system import CompiledSystem, Diagnostic, SystemError_, compile_raw

MAX_ITER = 40
REL_TOL = 1e-13


def _check(system: OpticalSystem) -> None:
    surfs = system.surfaces
    n = len(surfs)
    ids = {s.id: i for i, s in enumerate(surfs)}
    for i, s in enumerate(surfs):
        for kind, sv in (("thickness", s.thickness_solve), ("curvature", s.curvature_solve)):
            if sv is None:
                continue
            allowed = THICKNESS_SOLVES if kind == "thickness" else CURVATURE_SOLVES
            if sv.type not in allowed:
                raise SystemError_(f"Surface {i}: '{sv.type}' is not a {kind} solve", [Diagnostic("error", "SOLVE_INVALID", f"'{sv.type}' is not a {kind} solve", i)])
            if i == 0 or i == n - 1:
                raise SystemError_(f"Surface {i}: solves are not allowed on the object or image surface", [Diagnostic("error", "SOLVE_INVALID", "Solves are not allowed on the object or image surface", i)])
            if s.type == "coordinate_break" and not (kind == "thickness" and sv.type == "pickup"):
                raise SystemError_(f"Surface {i}: coordinate breaks only support thickness pickups", [Diagnostic("error", "SOLVE_INVALID", "Coordinate breaks only support thickness pickups", i)])
            if sv.type == "pickup":
                if sv.surface_id not in ids or ids[sv.surface_id] == i:
                    raise SystemError_(f"Surface {i}: pickup source must be another existing surface", [Diagnostic("error", "SOLVE_INVALID", "Pickup source must be another existing surface", i)])
                src = surfs[ids[sv.surface_id]]
                if kind == "thickness" and src.thickness is None:
                    raise SystemError_(f"Surface {i}: cannot pick up an infinite thickness", [Diagnostic("error", "SOLVE_INVALID", "Cannot pick up an infinite thickness", i)])
            if sv.type == "f_number" and not (sv.target > 0 and math.isfinite(sv.target)):
                raise SystemError_(f"Surface {i}: F-number solve needs a positive target", [Diagnostic("error", "SOLVE_INVALID", "F-number solve needs a positive target", i)])


def _new_values(cs: CompiledSystem, diags: list[Diagnostic]) -> dict[tuple[int, str], float | None]:
    """Values requested by every solve for the current compiled system."""
    from .paraxial import chief_ray, compute_pupil, marginal_ray, max_field_value

    model = cs.model
    surfs = model.surfaces
    ids = {s.id: i for i, s in enumerate(surfs)}
    wl = model.primary_wavelength
    ns = cs.n_signed[wl]
    pupil = None
    mray = cray = None
    out: dict[tuple[int, str], float | None] = {}

    def rays():
        nonlocal pupil, mray, cray
        if pupil is None:
            pupil = compute_pupil(cs, wl)
            mray = marginal_ray(cs, wl, pupil)
            h = max_field_value(cs)
            cray = chief_ray(cs, wl, pupil, h) if h > 0 else None
        return mray, cray

    for i, s in enumerate(surfs):
        sv = s.thickness_solve
        if sv is not None:
            if sv.type == "pickup":
                src = surfs[ids[sv.surface_id]]
                out[(i, "thickness")] = sv.scale * float(src.thickness) + sv.offset
            else:
                m, c = rays()
                ray = m if sv.type == "marginal_height" else c
                zone = sv.zone if sv.type == "marginal_height" else 1.0
                if ray is None:
                    diags.append(Diagnostic("warning", "SOLVE_FAILED", "Chief-ray solve needs a non-zero field", i))
                    continue
                y, u = zone * ray.y[i], zone * ray.u[i]
                if not (math.isfinite(y) and math.isfinite(u)) or abs(u) < 1e-15:
                    diags.append(Diagnostic("warning", "SOLVE_FAILED", f"{sv.type} solve undefined: the ray is parallel to the axis after surface {i}", i))
                    continue
                out[(i, "thickness")] = (sv.target - y) / u
        sv = s.curvature_solve
        if sv is not None:
            if sv.type == "pickup":
                src = surfs[ids[sv.surface_id]]
                out[(i, "curvature")] = None if src.radius is None else 1.0 / (sv.scale * src.radius) if sv.scale != 0 else None
                continue
            m, c = rays()
            ray = c if sv.type == "chief_angle" else m
            if ray is None:
                diags.append(Diagnostic("warning", "SOLVE_FAILED", "Chief-ray solve needs a non-zero field", i))
                continue
            y = ray.y[i]
            nu_in = ray.nu[i - 1]
            dn = ns[i] - ns[i - 1]
            if abs(y) < 1e-15 or abs(dn) < 1e-15:
                diags.append(Diagnostic("warning", "SOLVE_FAILED", f"{sv.type} solve undefined at surface {i} (ray height zero or no index change)", i))
                continue
            if sv.type == "f_number":
                nu_out = -math.copysign(1.0, y) / (2.0 * sv.target)
            else:
                nu_out = ns[i] * sv.target
            out[(i, "curvature")] = (nu_in - nu_out) / (y * dn)
    return out


def _apply(system_dict: dict, values: dict[tuple[int, str], float | None]) -> None:
    for (i, kind), v in values.items():
        s = system_dict["surfaces"][i]
        if kind == "thickness":
            s["thickness"] = float(v)
        else:
            s["radius"] = None if v is None or abs(v) < 1e-300 else 1.0 / v


def _close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= REL_TOL * max(1.0, abs(a), abs(b))


def resolve_solves(system: OpticalSystem, custom_materials=(), index_offsets=None) -> CompiledSystem:
    """Compile `system` with all solves resolved (cs.model holds the solved values)."""
    _check(system)
    d = system.model_dump()
    diags: list[Diagnostic] = []
    cs = compile_raw(system, custom_materials, index_offsets)
    converged = False
    for _ in range(MAX_ITER):
        step_diags: list[Diagnostic] = []
        vals = _new_values(cs, step_diags)
        current = {}
        for (i, kind) in vals:
            s = cs.model.surfaces[i]
            current[(i, kind)] = float(s.thickness) if kind == "thickness" else (None if s.radius is None else 1.0 / s.radius)
        if all(_close(vals[k], current[k]) for k in vals):
            converged = True
            diags = step_diags
            break
        _apply(d, vals)
        try:
            cs = compile_raw(OpticalSystem.model_validate(d), custom_materials, index_offsets)
        except ValueError as exc:  # e.g. a solve produced an invalid prescription
            raise SystemError_(f"Solve produced an invalid system: {exc}", [Diagnostic("error", "SOLVE_FAILED", str(exc))]) from exc
        diags = step_diags
    if not converged:
        diags.append(Diagnostic("warning", "SOLVE_NOT_CONVERGED", f"Solves did not converge in {MAX_ITER} iterations; values may be inconsistent"))
    for i, s in enumerate(cs.model.surfaces):
        if s.thickness_solve is not None or s.curvature_solve is not None:
            diags.append(Diagnostic("info", "SOLVE_ACTIVE", f"{'thickness ' + s.thickness_solve.type if s.thickness_solve else ''}{' and ' if s.thickness_solve and s.curvature_solve else ''}{'curvature ' + s.curvature_solve.type if s.curvature_solve else ''} solve (paraxial, primary wavelength)", i))
    cs.diagnostics.extend(diags)
    return cs


def freeze_solves(system: OpticalSystem, custom_materials=()) -> OpticalSystem:
    """The system with solved values written in and the solves removed."""
    if not any(s.thickness_solve is not None or s.curvature_solve is not None for s in system.surfaces):
        return system
    from .system import compile_system

    from .configs import apply_configuration

    cs = compile_system(system, custom_materials)  # active configuration applied, solves resolved
    # cs.model is the system at its temperature (environment.py); write the solved values back into the
    # nominal prescription at the reference temperature, so that compiling the result expands it once
    nominal = apply_configuration(system)
    shape = thick = [1.0] * len(nominal.surfaces)
    if nominal.environment_enabled:
        from .environment import environment_of, thermal_scales
        from .materials import MaterialLibrary

        shape, thick = thermal_scales(nominal, MaterialLibrary(custom_materials), environment_of(nominal))
    d = nominal.model_dump()
    for i, (s, solved) in enumerate(zip(d["surfaces"], cs.model.surfaces)):
        if s["thickness_solve"] is not None and solved.thickness is not None:
            s["thickness"] = solved.thickness / thick[i]
        if s["curvature_solve"] is not None:
            s["radius"] = None if solved.radius is None else solved.radius / shape[i]
        s["thickness_solve"] = None
        s["curvature_solve"] = None
    return OpticalSystem.model_validate(d)


def solved_values(cs: CompiledSystem) -> list[dict]:
    """Per-surface resolved values for surfaces that carry solves (for the UI)."""
    out = []
    for i, s in enumerate(cs.model.surfaces):
        if s.thickness_solve is not None or s.curvature_solve is not None:
            out.append({"surface": i, "thickness": s.thickness, "radius": s.radius, "thickness_solve": s.thickness_solve is not None, "curvature_solve": s.curvature_solve is not None})
    return out
