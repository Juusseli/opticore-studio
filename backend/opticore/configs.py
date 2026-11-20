"""Multiple configurations (zoom positions, conjugates, alternative glasses, ...).

`OpticalSystem.multi_config` holds a table of operands (parameter, surface)
with one value per configuration. The surfaces store the base prescription;
the active configuration's values override the base wherever an operand
exists. System parameters (aperture value, temperature, pressure) have no
surface; a field's vignetting factors (vdx, vdy, vcx, vcy) name the field
instead, since a zoom lens vignettes differently at each position. Every compile applies the active configuration first (then solves),
so all analyses describe the active configuration. Applying a configuration
is idempotent (values are absolute, not offsets).

Merit operands and optimisation variables can name a configuration
explicitly; see optimize/merit.py.
"""

from __future__ import annotations

from .model import OpticalSystem
from .system import Diagnostic, SystemError_


def n_configs(system: OpticalSystem) -> int:
    return len(system.multi_config.names) if system.multi_config else 1


def with_active(system: OpticalSystem, k: int) -> OpticalSystem:
    """Copy of the system with configuration k marked active (not yet applied)."""
    mc = system.multi_config
    if mc is None:
        if k != 0:
            raise SystemError_(f"Configuration {k + 1} does not exist (single configuration)")
        return system
    if not 0 <= k < len(mc.names):
        raise SystemError_(f"Configuration {k + 1} does not exist ({len(mc.names)} configurations)")
    if mc.active == k:
        return system
    d = system.model_dump()
    d["multi_config"]["active"] = k
    return OpticalSystem.model_validate(d)


def apply_configuration(system: OpticalSystem) -> OpticalSystem:
    """The system with the active configuration's values written into the prescription."""
    mc = system.multi_config
    if mc is None or not mc.operands:
        return system
    k = mc.active
    d = system.model_dump()
    pos = {s["id"]: i for i, s in enumerate(d["surfaces"])}
    for op in mc.operands:
        v = op.values[k]
        if op.surface_id is not None:
            src = system.surfaces[pos[op.surface_id]]
            if (op.parameter == "thickness" and src.thickness_solve is not None) or (op.parameter == "radius" and src.curvature_solve is not None):
                raise SystemError_(
                    f"Surface {pos[op.surface_id]}: {op.parameter} is controlled by both a solve and the configuration editor",
                    [Diagnostic("error", "CONFIG_INVALID", f"{op.parameter} is controlled by both a solve and a configuration operand", pos[op.surface_id])],
                )
        if op.parameter == "aperture_value":
            d["aperture"]["value"] = float(v)
            continue
        if op.parameter == "temperature":
            d["temperature_c"] = float(v)
            continue
        if op.parameter == "pressure":
            d["pressure_atm"] = float(v)
            continue
        if op.field is not None:  # a field's vignetting factor (CONFIG_FIELD_PARAMS)
            d["fields"][op.field][op.parameter] = float(v)
            continue
        s = d["surfaces"][pos[op.surface_id]]
        if op.parameter == "semi_diameter":
            s["semi_diameter"] = float(v)
            s["semi_diameter_mode"] = "fixed"
        else:
            s[op.parameter] = v
    try:
        return OpticalSystem.model_validate(d)
    except ValueError as exc:
        name = mc.names[k]
        raise SystemError_(
            f"Configuration '{name}' is invalid: {exc}",
            [Diagnostic("error", "CONFIG_INVALID", f"Configuration '{name}': {exc}")],
        ) from exc
