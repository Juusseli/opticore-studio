import threading
import time

import numpy as np
import pytest

from opticore.model import OpticalSystem
from opticore.optimize import OptimizationSpec, optimize
from opticore.optimize.engine import Control, Progress
from opticore.optimize.jobs import JobManager
from opticore.optimize.merit import MeritFunction
from opticore.paraxial import paraxial_data
from opticore.samples import achromat, singlet
from opticore.system import compile_system


def focus_spec(lo=80.0, hi=110.0, algorithm="local"):
    return OptimizationSpec.model_validate(
        {
            "variables": [{"surface_id": "s2", "parameter": "thickness", "min": lo, "max": hi}],
            "operands": [{"type": "rms_spot", "field": 0, "wavelength": 1, "rings": 6}],
            "algorithm": algorithm,
            "max_evaluations": 400,
        }
    )


def test_merit_definition_matches_weighted_spot_rms():
    """The RMS-spot merit equals the Gaussian-quadrature area-weighted RMS
    computed independently from traced rays."""
    from opticore.raytrace import gauss_pupil, trace_pupil

    p = singlet()
    mf = MeritFunction(p.system, focus_spec())
    r, br = mf.evaluate(mf.x0)
    cs = compile_system(p.system)
    px, py, w = gauss_pupil(6)
    xy = trace_pupil(cs, 1, 0, px, py).image_xy()
    c = (w[:, None] * xy).sum(0)
    rms = float(np.sqrt((w * ((xy - c) ** 2).sum(1)).sum()))
    assert br[0]["value"] == pytest.approx(rms * 1e3, rel=1e-9)
    assert mf.merit_from_residuals(r) == pytest.approx(rms, rel=1e-9)


def test_gauss_pupil_quadrature_is_exact_for_polynomials():
    from opticore.raytrace import gauss_pupil

    px, py, w = gauss_pupil(4)
    rho2 = px**2 + py**2
    assert w.sum() == pytest.approx(1.0, abs=1e-14)
    for k in range(1, 8):  # mean of rho^(2k) over the unit disc = 1/(k+1)
        assert (w * rho2**k).sum() == pytest.approx(1.0 / (k + 1), rel=1e-12)
    assert abs((w * px).sum()) < 1e-15 and abs((w * px * py).sum()) < 1e-15


def test_focus_optimisation_improves_and_respects_bounds():
    p = singlet()
    before = p.system.model_dump()
    res = optimize(p.system, focus_spec())
    assert res["final_merit"] < res["initial_merit"]
    t = res["variables"][0]["final"]
    assert 80.0 <= t <= 110.0
    # best focus of an undercorrected singlet is slightly inside the paraxial focus
    pd = paraxial_data(compile_system(p.system), 1)
    assert t < pd.bfl
    assert p.system.model_dump() == before  # original never modified


def test_bounds_clamp_solution():
    res = optimize(singlet().system, focus_spec(lo=99.0, hi=110.0))
    assert res["variables"][0]["final"] == pytest.approx(99.0, abs=1e-9)
    assert res["variables"][0]["at_bound"]


def test_achromat_optimisation_large_improvement():
    p = achromat(False)
    res = optimize(p.system, p.optimization)
    assert res["final_merit"] < 0.1 * res["initial_merit"]
    opt = OpticalSystem.model_validate(res["system"])
    efl = paraxial_data(compile_system(opt), 1).efl
    assert efl == pytest.approx(100.0, abs=0.01)


def test_global_and_multistart_find_focus():
    for alg in ("global", "multistart"):
        spec = focus_spec(algorithm=alg)
        spec.max_evaluations = 600
        res = optimize(singlet().system, spec)
        local = optimize(singlet().system, focus_spec())
        assert res["final_merit"] <= local["final_merit"] * 1.05, alg


def test_cancel_returns_best_so_far():
    p = achromat(False)
    spec = p.optimization.model_copy(update={"max_evaluations": 100000})
    control = Control()
    progress = Progress()
    out = {}

    def run():
        out["r"] = optimize(p.system, spec, progress=progress, control=control)

    th = threading.Thread(target=run)
    th.start()
    while progress.evaluations < 5 and th.is_alive():
        time.sleep(0.01)
    control.cancel.set()
    th.join(timeout=60)
    r = out["r"]
    assert r["status"] == "cancelled"
    assert r["final_merit"] <= r["initial_merit"]


def test_config_errors():
    p = singlet()
    with pytest.raises(ValueError):
        MeritFunction(p.system, OptimizationSpec(variables=[], operands=[]))
    with pytest.raises(ValueError):
        MeritFunction(p.system, OptimizationSpec.model_validate({"variables": [{"surface_id": "nope", "parameter": "thickness"}], "operands": [{"type": "efl", "target": 50}]}))
    with pytest.raises(ValueError):
        MeritFunction(p.system, OptimizationSpec.model_validate({"variables": [{"surface_id": "s1", "parameter": "tilt_x"}], "operands": [{"type": "efl", "target": 50}]}))
    # global search: a curvature gets bounds from its clear aperture (ADR-039); other unbounded variables are refused
    with pytest.raises(ValueError, match="S1 conic"):
        optimize(p.system, OptimizationSpec.model_validate({"variables": [{"surface_id": "s1", "parameter": "conic", "min": None, "max": None}], "operands": [{"type": "efl", "target": 50}], "algorithm": "global"}))


def test_efl_target_curvature():
    p = singlet()
    spec = OptimizationSpec.model_validate({"variables": [{"surface_id": "s1", "parameter": "curvature"}], "operands": [{"type": "efl", "target": 80.0}]})
    res = optimize(p.system, spec)
    opt = OpticalSystem.model_validate(res["system"])
    assert paraxial_data(compile_system(opt), 1).efl == pytest.approx(80.0, rel=1e-6)


def test_job_manager_lifecycle():
    jm = JobManager()
    job = jm.start(singlet().system, focus_spec())
    job.thread.join(timeout=60)
    snap = jm.snapshot(job)
    assert snap["state"] == "finished"
    assert snap["result"]["final_merit"] < snap["result"]["initial_merit"]
    assert jm.get("missing") is None
    assert jm.cancel("missing") is False


def test_sensitivity_reported():
    res = optimize(singlet().system, focus_spec())
    assert res["variables"][0]["sensitivity"] is not None


def test_rms_wavefront_operand_matches_analysis_and_optimises():
    from opticore.analysis.wavefront import wavefront_samples
    from opticore.raytrace import gauss_pupil

    p = singlet()
    spec = OptimizationSpec.model_validate(
        {
            "variables": [{"surface_id": "s2", "parameter": "thickness", "min": 90.0, "max": 100.0}],
            "operands": [{"type": "rms_wavefront", "field": 0, "wavelength": 1, "rings": 6}],
            "max_evaluations": 300,
        }
    )
    mf = MeritFunction(p.system, spec)
    r, br = mf.evaluate(mf.x0)
    cs = compile_system(p.system)
    px, py, pw = gauss_pupil(6)
    W, _, _ = wavefront_samples(cs, 1, 0, px, py)
    mean = (pw * W).sum()
    assert br[0]["value"] == pytest.approx(float(np.sqrt((pw * (W - mean) ** 2).sum())), rel=1e-9)
    res = optimize(p.system, spec)
    assert res["final_merit"] < res["initial_merit"]
    # Minimum-RMS focus makes the residual orthogonal to defocus: a weighted
    # least-squares fit of {1, rho^2} to W at the optimum has a ~zero rho^2 term.
    from opticore.model import OpticalSystem

    opt = compile_system(OpticalSystem.model_validate(res["system"]))
    gx, gy, gw = gauss_pupil(6)
    A = np.stack([np.ones_like(gx), gx**2 + gy**2], axis=1) * np.sqrt(gw)[:, None]
    W1, _, _ = wavefront_samples(opt, 1, 0, gx, gy)
    W0, _, _ = wavefront_samples(cs, 1, 0, gx, gy)
    c1, *_ = np.linalg.lstsq(A, W1 * np.sqrt(gw), rcond=None)
    c0, *_ = np.linalg.lstsq(A, W0 * np.sqrt(gw), rcond=None)
    assert abs(c1[1]) < 1e-3 * abs(c0[1])


def test_mtf_operand_value_and_improvement():
    p = singlet()
    spec = OptimizationSpec.model_validate(
        {
            "variables": [{"surface_id": "s2", "parameter": "thickness", "min": 90.0, "max": 100.0}],
            "operands": [{"type": "mtf", "field": 0, "frequency": 30.0, "target": 1.0}],
            "max_evaluations": 200,
        }
    )
    mf = MeritFunction(p.system, spec)
    _, br = mf.evaluate(mf.x0)
    assert 0.0 <= br[0]["value"] <= 1.0
    res = optimize(p.system, spec)
    assert res["operands_after"][0]["value"] > br[0]["value"]
