"""Parameter sweeps: evaluate metrics over a 1D or 2D grid of parameter values.

Each swept parameter is an optimisation-variable definition (surface,
parameter, optional configuration) with start, stop and step count. The
metrics are merit-function operands; their values (not their residuals)
are reported, computed with exactly the same code as the merit function and
the optimiser (Gaussian pupil quadrature for RMS spot / wavefront, paraxial
data for first-order quantities, ...). Points where the system cannot be
evaluated (invalid geometry, failed rays) are reported as null with the
error message of the first failure. Curvature sweeps are specified as
radius in mm for readability and converted internally.
"""

from __future__ import annotations

import time

import numpy as np

from ..model import OpticalSystem
from ..optimize.merit import MeritFunction, Operand, OptimizationSpec, Variable

MAX_POINTS = 2601  # e.g. 51 x 51


def sweep(system: OpticalSystem, params: list[dict], metrics: list[Operand], custom_materials=(), ns=None) -> dict:
    if not 1 <= len(params) <= 2:
        raise ValueError("A sweep needs one or two parameters")
    if not metrics:
        raise ValueError("Choose at least one metric")
    axes = []
    variables = []
    for p in params:
        steps = int(p.get("steps", 21))
        if steps < 2:
            raise ValueError("Each swept parameter needs at least 2 steps")
        start, stop = float(p["start"]), float(p["stop"])
        if start == stop:
            raise ValueError("Sweep start and stop must differ")
        param = p["parameter"]
        if param == "material":
            raise ValueError("Materials cannot be swept continuously")
        vals = np.linspace(start, stop, steps)
        if param == "curvature" and np.any(vals == 0):
            raise ValueError("A radius sweep cannot pass through R = 0")
        axes.append(vals)
        variables.append(Variable(surface_id=p["surface_id"], parameter=param, configuration=p.get("configuration")))
    n_points = int(np.prod([len(a) for a in axes]))
    if n_points > MAX_POINTS:
        raise ValueError(f"Too many sweep points ({n_points}); the limit is {MAX_POINTS}")
    ops = [m.model_copy(update={"enabled": True, "weight": 1.0}) for m in metrics]
    mf = MeritFunction(system, OptimizationSpec(variables=variables, operands=ops), custom_materials, ns=ns)

    def to_x(v, var):  # radius (mm) -> curvature
        return 1.0 / v if var.parameter == "curvature" else v

    t0 = time.time()
    shape = tuple(len(a) for a in axes)
    values = [np.full(shape, np.nan) for _ in ops]
    errors: list[str] = []
    units: list[str | None] = [None] * len(ops)
    for index in np.ndindex(*shape):
        x = np.array([to_x(axes[k][index[k]], variables[k]) for k in range(len(axes))])
        _, bd = mf.evaluate(x)
        for m, b in enumerate(bd):
            if b.get("error"):
                if len(errors) < 5 and b["error"] not in errors:
                    errors.append(b["error"])
                continue
            if b.get("failed_rays"):
                msg = f"{b['type']}: {b['failed_rays']} ray(s) failed (vignetted, missed or TIR) — point omitted"
                if len(errors) < 5 and msg not in errors:
                    errors.append(msg)
                continue
            v = b.get("value")
            if v is not None:
                values[m][index] = float(v)
            if b.get("unit"):
                units[m] = b["unit"]
    nominal = [None] * len(ops)
    _, bd0 = MeritFunction(system, OptimizationSpec(operands=ops), custom_materials, ns=ns).evaluate(np.array([]))
    for m, b in enumerate(bd0):
        nominal[m] = None if b.get("error") or b.get("value") is None else float(b["value"])
    current = [float(1.0 / v if var.parameter == "curvature" and v != 0 else v) for var, v in zip(variables, mf.x0)]

    def lst(a):
        return [None if not np.isfinite(v) else float(v) for v in a] if a.ndim == 1 else [lst(r) for r in a]

    return {
        "axes": [a.tolist() for a in axes],
        "parameters": [{**p, "unit": _unit(p["parameter"]), "current": c} for p, c in zip(params, current)],
        "metrics": [
            {"type": o.type, "field": o.field, "wavelength": o.wavelength, "configuration": o.configuration, "frequency": o.frequency, "unit": units[m] or _metric_unit(o.type), "nominal": nominal[m], "values": lst(values[m])}
            for m, o in enumerate(ops)
        ],
        "points": n_points,
        "errors": errors,
        "elapsed_s": time.time() - t0,
        "method": "Merit-function operand values at every grid point (same code path as optimisation); radius sweeps in mm",
    }


def _unit(param: str) -> str:
    if param in ("thickness", "decenter_x", "decenter_y", "curvature"):
        return "mm"
    if param.startswith("tilt"):
        return "deg"
    return ""


def _metric_unit(t: str) -> str:
    return {
        "efl": "mm",
        "bfl": "mm",
        "total_track": "mm",
        "axial_color": "mm",
        "distortion": "%",
        "rms_spot": "um",
        "rms_wavefront": "waves",
        "mtf": "",
        "throughput": "",
        "fnum": "",
        "working_fnum": "",
        "magnification": "",
    }.get(t, "")
