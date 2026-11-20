"""The optimiser's parallel Jacobian (optimize/parallel.py) and the colour, illumination and chief-ray-angle operands.

* The parallel finite-difference Jacobian equals the serial one with the same steps (SciPy's '2-point' scheme)
  to the warm-start tolerances.
* An optimisation with it reaches the serial run's merit, and a cancel stops it and frees the pool.
* max_lateral_color, min_relative_illumination and max_cra report the numbers of the design summary
  (analysis/summary.py) and are one-sided.
"""

from __future__ import annotations

import numpy as np
import pytest

from opticore import workers
from opticore.analysis.summary import design_summary
from opticore.optimize import parallel
from opticore.optimize.engine import Control, optimize
from opticore.optimize.merit import MeritFunction, Operand, OptimizationSpec, Variable
from opticore.samples import cell_phone_lens, geiser_triplet

IDS = ["g1", "g2", "g3", "g4", "g5", "g6"]


def _triplet_spec(max_evaluations=200) -> OptimizationSpec:
    return OptimizationSpec(
        variables=[Variable(surface_id=i, parameter="curvature") for i in IDS] + [Variable(surface_id="g6", parameter="thickness", min=30, max=50)],
        operands=[Operand(type="rms_spot"), Operand(type="efl", target=50.0)],
        max_evaluations=max_evaluations,
    )


def test_parallel_jacobian_equals_the_serial_one():
    p = geiser_triplet()
    spec = _triplet_spec()
    mf = MeritFunction(p.system, spec, p.custom_materials)
    lo, hi = mf.bounds()
    x = mf.x0.copy()
    pj = parallel.ParallelJacobian(p.system, spec, p.custom_materials, None, None, lo, hi, 1e-7, lambda z: mf.evaluate(z)[0], lambda z, r: None, lambda: None, lambda: False)
    try:
        J = pj(x)
    finally:
        pj.close()
    f0 = mf.evaluate(x)[0]
    dx = pj.steps(x)
    Js = np.empty_like(J)
    for i in range(len(x)):
        xi = x.copy()
        xi[i] += dx[i]
        Js[:, i] = (mf.evaluate(xi)[0] - f0) / dx[i]
    # scipy's own '2-point' steps: h = 1e-7 sign(x) max(1, |x|), reversed at an upper bound
    assert np.allclose(dx, 1e-7 * np.where(x >= 0, 1, -1) * np.maximum(1, np.abs(x)), rtol=1e-6)
    scale = np.abs(Js).max(axis=0)
    assert np.all(np.abs(J - Js) <= 1e-6 * scale + 1e-12)
    assert pj.columns == len(x)


def test_optimisation_with_the_parallel_jacobian_reaches_the_serial_merit(monkeypatch):
    p = geiser_triplet()
    spec = _triplet_spec()
    monkeypatch.setenv("OPTICORE_PARALLEL_JACOBIAN", "0")
    serial = optimize(p.system, spec, p.custom_materials)
    monkeypatch.setenv("OPTICORE_PARALLEL_JACOBIAN", "force")
    par = optimize(p.system, spec, p.custom_materials)
    assert serial["parallel"] is None
    assert par["parallel"] is not None and par["parallel"]["columns"] >= len(spec.variables)
    assert par["final_merit"] == pytest.approx(serial["final_merit"], rel=1e-4)
    assert workers.idle()
    # the sensitivities at the solution, on the pool and in the main process, agree
    from opticore.optimize.engine import sensitivity

    mf = MeritFunction(p.system, spec, p.custom_materials)
    xb = np.array([v["final"] for v in par["variables"]])
    m = mf.merit(xb)
    lo, hi = mf.bounds()
    pj = parallel.ParallelJacobian(p.system, spec, p.custom_materials, None, None, lo, hi, 1e-7, lambda z: mf.evaluate(z)[0], lambda z, r: None, lambda: None, lambda: False)
    try:
        s_par = sensitivity(mf, xb, m, pj.run)
    finally:
        pj.close()
    s_ser = sensitivity(mf, xb, m)
    assert np.allclose(np.array(s_par, dtype=float), np.array(s_ser, dtype=float), rtol=1e-5, atol=1e-9)


def test_a_cancel_stops_a_parallel_run_and_frees_the_pool(monkeypatch):
    monkeypatch.setenv("OPTICORE_PARALLEL_JACOBIAN", "force")
    p = geiser_triplet()
    ctl = Control()

    def on_update(progress):
        if progress.evaluations >= 12:
            ctl.cancel.set()

    r = optimize(p.system, _triplet_spec(2000), p.custom_materials, control=ctl, on_update=on_update)
    assert r["status"] == "cancelled" and r["evaluations"] < 60
    assert workers.idle()


def test_colour_illumination_and_chief_ray_angle_operands_match_the_summary():
    p = cell_phone_lens()
    s = design_summary(p.system, p.custom_materials)
    lat, ri, cra = abs(s["lateral_colour_um"]), s["relative_illumination"], s["cra_deg"]
    spec = OptimizationSpec(
        variables=[Variable(surface_id="c1", parameter="curvature")],
        operands=[
            Operand(type="max_lateral_color", target=lat + 0.1),
            Operand(type="max_lateral_color", target=lat - 0.5),
            Operand(type="min_relative_illumination", target=ri - 0.01),
            Operand(type="min_relative_illumination", target=ri + 0.05),
            Operand(type="max_cra", target=cra + 1.0),
            Operand(type="max_cra", target=cra - 2.0),
        ],
    )
    mf = MeritFunction(p.system, spec, p.custom_materials)
    _, b = mf.evaluate(mf.x0)
    assert [o["value"] for o in b[::2]] == pytest.approx([lat, ri, cra], rel=1e-12)
    w = 1 / 6
    assert [o["contribution"] for o in b] == pytest.approx([0.0, w * 0.5**2, 0.0, w * 0.05**2, 0.0, w * 2.0**2], rel=1e-9, abs=1e-15)
    # an explicit field: on the axis the chief ray meets the image along its normal
    bad = spec.model_copy(update={"operands": [Operand(type="max_cra", target=10.0, field=0)]})
    _, b0 = MeritFunction(p.system, bad, p.custom_materials).evaluate(mf.x0)
    assert b0[0]["value"] == pytest.approx(0.0, abs=1e-9)


def test_never_parallel_inside_a_pool_worker(monkeypatch):
    """The design-space map and the stock-lens build optimise their candidates inside pool workers; a pool per
    worker there would start workers x workers processes."""
    monkeypatch.setenv("OPTICORE_PARALLEL_JACOBIAN", "1")
    monkeypatch.setattr(workers, "worker_count", lambda: 8)
    assert parallel.maybe(14, 0.2) == workers.idle()
    monkeypatch.setattr(workers, "_worker_flags", bytearray(4))  # as set by the worker initialiser
    assert workers.in_worker()
    assert not parallel.maybe(14, 0.2)
    monkeypatch.setenv("OPTICORE_PARALLEL_JACOBIAN", "force")
    assert not parallel.maybe(14, 0.2)
