import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.analysis.sweep import sweep
from opticore.api.main import app
from opticore.optimize.merit import MeritFunction, Operand, OptimizationSpec, Variable
from opticore.samples import get_sample
from opticore.system import compile_system


def test_radius_sweep_of_plano_convex_lens_follows_lensmaker():
    sysm = get_sample("singlet").system
    n = compile_system(sysm).n_after[sysm.primary_wavelength, 1]
    r = sweep(sysm, [{"surface_id": "s1", "parameter": "curvature", "start": 40.0, "stop": 80.0, "steps": 9}], [Operand(type="efl")])
    R = np.array(r["axes"][0])
    efl = np.array(r["metrics"][0]["values"], dtype=float)
    # thick plano-convex lens (plane back): f = R / (n - 1) exactly, independent of thickness
    assert np.allclose(efl, R / (n - 1), rtol=1e-12)
    assert r["parameters"][0]["current"] == pytest.approx(51.68)
    assert r["metrics"][0]["nominal"] == pytest.approx(51.68 / (n - 1), rel=1e-12)


def test_back_focus_sweep_leaves_efl_unchanged_and_finds_best_focus():
    sysm = get_sample("singlet").system
    r = sweep(sysm, [{"surface_id": "s2", "parameter": "thickness", "start": 94.0, "stop": 98.0, "steps": 41}], [Operand(type="efl"), Operand(type="rms_spot", rings=3, field=0)])
    efl = np.array(r["metrics"][0]["values"], dtype=float)
    assert np.ptp(efl) < 1e-12
    rms = np.array(r["metrics"][1]["values"], dtype=float)
    assert r["metrics"][1]["unit"] == "um"
    k = int(np.argmin(rms))
    assert 0 < k < 40  # interior minimum: best focus inside the swept range
    # the sweep value equals a direct merit evaluation at that point
    mf = MeritFunction(sysm, OptimizationSpec(variables=[Variable(surface_id="s2", parameter="thickness")], operands=[Operand(type="rms_spot", rings=3, field=0)]))
    _, bd = mf.evaluate(np.array([r["axes"][0][k]]))
    assert rms[k] == pytest.approx(bd[0]["value"], rel=1e-12)


def test_two_dimensional_sweep_matches_one_dimensional_slices():
    sysm = get_sample("achromat").system
    p1 = {"surface_id": "d1", "parameter": "curvature", "start": 45.0, "stop": 55.0, "steps": 5}
    p2 = {"surface_id": "d3", "parameter": "thickness", "start": 93.0, "stop": 97.0, "steps": 4}
    ops = [Operand(type="rms_spot", rings=2, field=0), Operand(type="efl")]
    r2 = sweep(sysm, [p1, p2], ops)
    v2 = np.array(r2["metrics"][0]["values"], dtype=float)
    assert v2.shape == (5, 4)
    j = 2
    r1 = sweep(sysm.model_copy(update={"surfaces": [s.model_copy(update={"thickness": r2["axes"][1][j]}) if s.id == "d3" else s for s in sysm.surfaces]}), [p1], ops)
    assert np.allclose(v2[:, j], np.array(r1["metrics"][0]["values"], dtype=float), rtol=1e-12)
    # EFL depends only on the radius, not on the back focus
    e2 = np.array(r2["metrics"][1]["values"], dtype=float)
    assert np.allclose(e2, e2[:, :1], rtol=1e-12)


def test_points_with_failed_rays_are_omitted_not_penalised():
    sysm = get_sample("singlet").system.model_dump()
    sysm["surfaces"][2]["semi_diameter"] = 4.7  # marginal height ~4.57 mm at R = 20, ~4.86 mm at R = 60
    sysm["surfaces"][2]["semi_diameter_mode"] = "fixed"
    from opticore.model import OpticalSystem

    s = OpticalSystem.model_validate(sysm)
    # weakly curved fronts leave the beam wider than the fixed back aperture: those points vignette
    r = sweep(s, [{"surface_id": "s1", "parameter": "curvature", "start": 20.0, "stop": 60.0, "steps": 9}], [Operand(type="rms_spot", rings=3)])
    vals = r["metrics"][0]["values"]
    assert any(v is None for v in vals)
    assert any("ray(s) failed" in e for e in r["errors"])
    assert vals[0] is not None and vals[-1] is None


@pytest.mark.parametrize(
    "params,metrics",
    [
        ([], [Operand(type="efl")]),
        ([{"surface_id": "s1", "parameter": "curvature", "start": 50, "stop": 50, "steps": 5}], [Operand(type="efl")]),
        ([{"surface_id": "s1", "parameter": "curvature", "start": -10, "stop": 10, "steps": 5}], [Operand(type="efl")]),  # passes R = 0
        ([{"surface_id": "s1", "parameter": "curvature", "start": 40, "stop": 60, "steps": 5}], []),
        ([{"surface_id": "s1", "parameter": "curvature", "start": 40, "stop": 60, "steps": 60}, {"surface_id": "s2", "parameter": "thickness", "start": 90, "stop": 100, "steps": 60}], [Operand(type="efl")]),
    ],
)
def test_invalid_sweeps(params, metrics):
    with pytest.raises(ValueError):
        sweep(get_sample("singlet").system, params, metrics)


def test_sweep_api():
    c = TestClient(app)
    body = {
        "system": get_sample("singlet").system.model_dump(),
        "parameters": [{"surface_id": "s2", "parameter": "thickness", "start": 95, "stop": 97, "steps": 5}],
        "metrics": [{"type": "rms_spot", "rings": 2}, {"type": "bfl"}],
    }
    r = c.post("/api/v1/analysis/sweep", json=body)
    assert r.status_code == 200
    assert len(r.json()["metrics"][1]["values"]) == 5
    bad = c.post("/api/v1/analysis/sweep", json={**body, "parameters": [{**body["parameters"][0], "surface_id": "nope"}]})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "SWEEP_CONFIG"
