"""Temperature (or pressure) analysis: focus, focal length and spot size across a range (docs/OPTICAL_ENGINE.md §9a).

Each point compiles the system with the environment model on (environment.py) at that temperature or
pressure and evaluates:
* the paraxial EFL and back focal distance at the primary wavelength;
* the best polychromatic RMS focus relative to the image surface (focus.py, exact for a plane image
  surface): the image surface sits on the housing, so this is the defocus the user would have to correct;
* the RMS spot radius on the image surface and at that best focus.

The depth of focus used for comparison is the diffraction-limited ±2 λ N_w² (λ the primary wavelength,
N_w the working F-number at the system's own temperature): a focus shift within it costs little.
"""

from __future__ import annotations

import math

import numpy as np

from ..configs import apply_configuration
from ..environment import T_REF
from ..model import OpticalSystem
from ..paraxial import paraxial_data
from ..system import SystemError_, compile_system
from .focus import focus_status

VARIABLES = ("temperature", "pressure")


def thermal_analysis(system: OpticalSystem, custom_materials=(), variable: str = "temperature", start: float = -20.0, stop: float = 60.0, steps: int = 9, density: int = 6) -> dict:
    if variable not in VARIABLES:
        raise ValueError(f"variable must be one of {VARIABLES}")
    if steps < 2:
        raise ValueError("steps must be at least 2")
    # the active configuration, without configuration values for temperature and pressure (they would
    # override the swept value); the environment model is turned on for the analysis
    base = apply_configuration(system)
    notes = []
    if not system.environment_enabled:
        notes.append("The system has the environment model off; this analysis turns it on (its other analyses use the catalogue indices and the nominal prescription).")
    d = base.model_dump()
    d["multi_config"] = None
    d["environment_enabled"] = True
    base = OpticalSystem.model_validate(d)
    key = "temperature_c" if variable == "temperature" else "pressure_atm"
    values = [float(v) for v in np.linspace(start, stop, steps)]
    w = base.primary_wavelength
    rows = []
    for v in values:
        s = base.model_copy(update={key: v})
        row: dict = {"value": v}
        try:
            cs = compile_system(s, custom_materials)
            pd = paraxial_data(cs, w)
            fs = focus_status(cs, density)
            row.update(
                efl_mm=pd.efl,
                bfl_mm=pd.bfl,
                paraxial_defocus_mm=pd.image_surface_defocus,
                best_focus_mm=fs["best_defocus_mm"],
                rms_um=fs["rms_um"],
                rms_best_um=fs["rms_best_um"],
                rms_field_um=[f["rms_um"] for f in fs["per_field"]],
            )
        except (SystemError_, ValueError, ArithmeticError) as exc:
            row["error"] = str(exc)
        rows.append(row)

    # reference: the system's own environment
    ref_value = float(getattr(base, key))
    ref = None
    try:
        cs = compile_system(base, custom_materials)
        pd = paraxial_data(cs, w)
        lam_mm = float(cs.wavelengths[w]) * 1e-3
        n_w = pd.working_fnum
        dof = 2.0 * lam_mm * n_w * n_w if n_w and math.isfinite(n_w) else None
        ref = {"value": ref_value, "efl_mm": pd.efl, "working_fnum": n_w, "depth_of_focus_mm": dof, "best_focus_mm": focus_status(cs, density)["best_defocus_mm"]}
    except (SystemError_, ValueError, ArithmeticError) as exc:
        notes.append(f"Reference point failed: {exc}")

    ok = [r for r in rows if "error" not in r and r.get("best_focus_mm") is not None]
    slopes = {}
    if len(ok) >= 2:
        x = np.array([r["value"] for r in ok])
        for k in ("best_focus_mm", "efl_mm", "paraxial_defocus_mm"):
            y = np.array([r[k] for r in ok if r.get(k) is not None])
            if len(y) == len(x):
                slopes[k] = float(np.polyfit(x, y, 1)[0])
    spread = None
    if ok:
        bf = [r["best_focus_mm"] for r in ok]
        spread = float(max(bf) - min(bf))
    unit = "°C" if variable == "temperature" else "atm"
    return {
        "variable": variable,
        "unit": unit,
        "values": values,
        "rows": rows,
        "reference": ref,
        "slopes_per_unit": slopes,
        "focus_spread_mm": spread,
        "reference_temperature_c": T_REF,
        "method": (
            f"Environment model at each {variable} (air index: Edlén/Kohlrausch; glass dn/dT: absolute Schott model; "
            f"thermal expansion from {T_REF:g} °C with glass and housing CTEs). Best focus: polychromatic centroid RMS, closed form; "
            f"depth of focus ±2 λ N_w² (diffraction limit) about the best focus at the system's own {variable}."
        ),
        "notes": notes,
    }
