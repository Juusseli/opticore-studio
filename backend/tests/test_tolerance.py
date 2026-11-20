import math
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.paraxial import compute_pupil
from opticore.raytrace import gauss_pupil, trace_pupil
from opticore.samples import get_sample
from opticore.system import compile_system
from opticore.tolerance import (
    Compensator,
    Tolerance,
    ToleranceError,
    ToleranceSpec,
    _draw,
    analyze,
    default_spec,
    element_groups,
    perturb,
)

from .conftest import make_system


def _plate_system():
    return make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "stop", "thickness": 10.0, "is_stop": True},
            {"id": "p1", "thickness": 10.0, "material": "N-BK7"},
            {"id": "p2", "thickness": 20.0},
            {"id": "img"},
        ],
        wavelengths=[{"value": 0.5875618}],
        fields=[{"y": 0.0}],
        aperture={"type": "epd", "value": 4.0},
    )


def _chief_y(system, offsets=None):
    cs = compile_system(system, (), offsets)
    pupil = compute_pupil(cs)
    r = trace_pupil(cs, 0, 0, np.array([0.0]), np.array([0.0]), pupil)
    return r.image_xy()[0]


def test_tilted_plate_lateral_displacement():
    sysm = _plate_system()
    th = 10.0
    pt = perturb(sysm, [Tolerance(type="element_tilt_x", surface_id="p1", surface_id_end="p2", min=-th, max=th)], [th])
    n = compile_system(sysm).n_after[0, 2]
    t = 10.0
    a = math.radians(th)
    d = t * math.sin(a) * (1 - math.cos(a) / math.sqrt(n * n - math.sin(a) ** 2))
    y = _chief_y(pt.system)
    assert abs(y[1]) == pytest.approx(d, rel=1e-10)
    assert y[0] == pytest.approx(0.0, abs=1e-12)


def test_return_break_restores_downstream_frames_exactly():
    sysm = get_sample("cooke-triplet").system
    tols = [
        Tolerance(type="element_tilt_x", surface_id="t3", surface_id_end="t4", min=-1, max=1),
        Tolerance(type="element_decenter_y", surface_id="t3", surface_id_end="t4", min=-1, max=1),
        Tolerance(type="surface_tilt_y", surface_id="t4", min=-1, max=1),
        Tolerance(type="surface_decenter_x", surface_id="t1", min=-1, max=1),
    ]
    pt = perturb(sysm, tols, [0.7, 0.3, -0.4, 0.2])
    nom = compile_system(sysm)
    per = compile_system(pt.system)
    idx_n = {s.id: i for i, s in enumerate(sysm.surfaces)}
    idx_p = {s.id: i for i, s in enumerate(pt.system.surfaces)}
    for sid in ("t2", "stp", "t5", "t6", "img"):
        a, b = nom.frames[idx_n[sid]], per.frames[idx_p[sid]]
        assert np.allclose(a.origin, b.origin, atol=1e-12), sid
        assert np.allclose(a.matrix, b.matrix, atol=1e-12), sid
    # the toleranced surfaces did move
    assert not np.allclose(nom.frames[idx_n["t3"]].origin, per.frames[idx_p["t3"]].origin)


def test_decentered_singlet_images_on_its_shifted_axis():
    from opticore.model import OpticalSystem

    d = get_sample("singlet").system.model_dump()
    d.update(fields=d["fields"][:1], wavelengths=[d["wavelengths"][d["primary_wavelength"]]], primary_wavelength=0, ray_aiming="real")
    sysm = OpticalSystem.model_validate(d)
    delta = 0.1
    pt = perturb(sysm, [Tolerance(type="element_decenter_y", surface_id="s1", surface_id_end="s2", min=-delta, max=delta)], [delta])
    cs = compile_system(pt.system)
    pupil = compute_pupil(cs)
    px, py, pw = gauss_pupil(6)
    r = trace_pupil(cs, 0, 0, px, py, pupil)
    xy = r.image_xy()
    assert r.ok.all()
    cy = float((pw * xy[:, 1]).sum() / pw.sum())
    assert cy == pytest.approx(delta, abs=1e-9)


def test_index_offset_applies_to_one_medium_only():
    sysm = get_sample("achromat").system
    base = compile_system(sysm).n_after
    off = compile_system(sysm, (), {"d1": 1e-3}).n_after
    i = [s.id for s in sysm.surfaces].index("d1")
    assert np.allclose(off[:, i] - base[:, i], 1e-3, atol=1e-15)
    mask = np.ones(base.shape[1], bool)
    mask[i] = False
    assert np.array_equal(off[:, mask], base[:, mask])


def test_index_offset_follows_medium_through_coordinate_breaks():
    sysm = make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "g", "thickness": 1.0, "material": "N-BK7", "is_stop": True},
            {"id": "cb", "type": "coordinate_break", "thickness": 1.0},
            {"id": "o", "thickness": 5.0},
            {"id": "img"},
        ],
        wavelengths=[{"value": 0.55}],
    )
    base = compile_system(sysm).n_after[0]
    off = compile_system(sysm, (), {"g": 0.01}).n_after[0]
    assert off[1] - base[1] == pytest.approx(0.01) and off[2] - base[2] == pytest.approx(0.01)
    assert off[3] == base[3]


def test_lensmaker_power_change_from_index_tolerance():
    # thin-ish singlet: d(phi)/dn = phi/(n-1) to first order (plano-convex: phi = (n-1)/R)
    from opticore.paraxial import paraxial_data

    sysm = get_sample("singlet").system
    dn = 1e-4
    cs0 = compile_system(sysm)
    cs1 = compile_system(sysm, (), {"s1": dn})
    w = sysm.primary_wavelength
    phi0 = 1 / paraxial_data(cs0, w).efl
    phi1 = 1 / paraxial_data(cs1, w).efl
    n = cs0.n_after[w, 1]
    # exact thick-lens plano-convex power is (n-1)/R independent of thickness
    assert phi1 - phi0 == pytest.approx(dn / 51.68, rel=1e-6)
    assert phi0 == pytest.approx((n - 1) / 51.68, rel=1e-10)


def _small_spec(**kw):
    sysm = get_sample("singlet").system
    spec = ToleranceSpec(
        tolerances=[
            Tolerance(type="thickness", surface_id="s1", min=-0.1, max=0.1),
            Tolerance(type="element_decenter_x", surface_id="s1", surface_id_end="s2", min=-0.05, max=0.05),
            Tolerance(type="radius", surface_id="s1", min=0.0, max=0.0),  # zero range: skipped in sensitivity
        ],
        compensators=[Compensator(surface_id="s2", parameter="thickness", range=2.0)],
        monte_carlo_trials=6,
        rings=2,
        **kw,
    )
    return sysm, spec


def test_compensator_cancels_pure_defocus_tolerance():
    sysm = get_sample("singlet").system
    spec = ToleranceSpec(
        tolerances=[Tolerance(type="thickness", surface_id="s2", min=-0.3, max=0.3)],
        compensators=[Compensator(surface_id="s2", range=2.0)],
        monte_carlo_trials=0,
        rings=2,
    )
    r = analyze(sysm, spec)
    row = r["sensitivity"][0]
    assert row["at_max"] == pytest.approx(r["nominal"], abs=1e-4)
    assert row["at_min"] == pytest.approx(r["nominal"], abs=1e-4)
    assert row["at_max_uncompensated"] > r["nominal"] + 1.0  # defocus visibly hurts uncompensated
    # the compensator takes up exactly the +-0.3 mm defocus (difference of the two solutions)
    assert row["at_min_compensators"][0] - row["at_max_compensators"][0] == pytest.approx(0.6, abs=1e-3)


def test_decenter_x_sensitivity_symmetric_for_y_fields():
    sysm, spec = _small_spec()
    r = analyze(sysm, spec)
    dec = next(s for s in r["sensitivity"] if s["type"] == "element_decenter_x")
    assert dec["at_min"] == pytest.approx(dec["at_max"], rel=1e-9)


def test_analysis_structure_rss_and_reproducibility():
    sysm, spec = _small_spec()
    a = analyze(sysm, spec)
    b = analyze(sysm, spec)
    assert len(a["sensitivity"]) == 2  # zero-range tolerance skipped
    worst = [s["worst_change"] for s in a["sensitivity"]]
    assert a["rss_change"] == pytest.approx(math.sqrt(sum(w * w for w in worst)), rel=1e-12)
    assert a["rss_estimate"] == pytest.approx(a["nominal"] + a["rss_change"])
    assert a["monte_carlo"]["values"] == b["monte_carlo"]["values"]
    st = a["monte_carlo"]["statistics"]
    assert st["min"] <= st["p50"] <= st["max"]
    assert a["monte_carlo"]["trials"] == 6
    assert any("Fewer than 20" in n for n in a["notes"])
    assert a["unit"] == "um"


def test_normal_draws_stay_within_limits_and_centre():
    tols = [Tolerance(type="thickness", surface_id="x", min=-0.2, max=0.6)]
    d = _draw(tols, 20000, "normal", np.random.default_rng(3))
    assert d.min() >= -0.2 and d.max() <= 0.6
    assert d.mean() == pytest.approx(0.2, abs=0.005)
    # truncated at +-2 sigma: std = sigma * sqrt(1 - 2*2*phi(2)/(Phi(2)-Phi(-2)))
    sigma = 0.8 / 4
    phi2 = math.exp(-2) / math.sqrt(2 * math.pi)
    PHI = math.erf(2 / math.sqrt(2))
    assert d.std() == pytest.approx(sigma * math.sqrt(1 - 4 * phi2 / PHI), rel=0.02)
    u = _draw(tols, 20000, "uniform", np.random.default_rng(3))
    assert u.min() >= -0.2 and u.max() <= 0.6 and u.std() == pytest.approx(0.8 / math.sqrt(12), rel=0.02)


def test_validation_errors():
    sysm = get_sample("singlet").system
    with pytest.raises(ToleranceError):
        analyze(sysm, ToleranceSpec(tolerances=[Tolerance(type="radius", surface_id="s2", min=-1, max=1)]))  # plane
    with pytest.raises(ToleranceError):
        analyze(sysm, ToleranceSpec(tolerances=[Tolerance(type="index", surface_id="s2", min=-1e-3, max=1e-3)]))  # air
    with pytest.raises(ToleranceError):
        analyze(sysm, ToleranceSpec(tolerances=[Tolerance(type="thickness", surface_id="nope", min=-1, max=1)]))
    with pytest.raises(ToleranceError):
        analyze(sysm, ToleranceSpec(tolerances=[Tolerance(type="thickness", surface_id="s1", min=-1, max=1)], criterion="merit"))
    with pytest.raises(ValueError):
        Tolerance(type="thickness", surface_id="s1", min=1, max=-1)


def test_default_spec_groups_and_compensator():
    tri = get_sample("cooke-triplet").system
    assert element_groups(tri) == [(1, 2), (3, 4), (6, 7)]
    ach = get_sample("achromat").system
    assert element_groups(ach) == [(1, 3)]  # cemented doublet = one group
    spec = default_spec(ach, "precision")
    assert spec.compensators[0].surface_id == "d3"
    kinds = {t.type for t in spec.tolerances}
    assert {"radius", "thickness", "index", "element_tilt_x", "element_decenter_y"} <= kinds
    # back focus is a compensator, not a tolerance
    assert not any(t.type == "thickness" and t.surface_id == "d3" for t in spec.tolerances)


def test_tolerance_api_job_roundtrip():
    c = TestClient(app)
    sysm, spec = _small_spec()
    body = {"system": sysm.model_dump(), "tolerance": spec.model_dump()}
    d = c.post("/api/v1/tolerance/default", json={"system": sysm.model_dump(), "grade": "commercial"})
    assert d.status_code == 200 and d.json()["tolerance"]["tolerances"]
    r = c.post("/api/v1/tolerance/start", json=body)
    assert r.status_code == 200
    jid = r.json()["job_id"]
    t0 = time.time()
    while True:
        s = c.get(f"/api/v1/tolerance/{jid}").json()
        if s["state"] in ("finished", "failed", "cancelled"):
            break
        assert time.time() - t0 < 60
        time.sleep(0.05)
    assert s["state"] == "finished", s["error"]
    assert s["done"] == s["total"] == 1 + 4 + 6
    assert len(s["result"]["monte_carlo"]["values"]) == 6
    bad = c.post("/api/v1/tolerance/start", json={**body, "tolerance": {**spec.model_dump(), "criterion": "merit"}})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "TOLERANCE_CONFIG"
    assert c.get("/api/v1/tolerance/unknown").status_code == 404
    assert c.post("/api/v1/tolerance/unknown/cancel").status_code == 404


def test_cancel_stops_monte_carlo():
    c = TestClient(app)
    sysm, spec = _small_spec()
    spec.monte_carlo_trials = 2000
    jid = c.post("/api/v1/tolerance/start", json={"system": sysm.model_dump(), "tolerance": spec.model_dump()}).json()["job_id"]
    time.sleep(0.3)
    assert c.post(f"/api/v1/tolerance/{jid}/cancel").status_code == 200
    t0 = time.time()
    while (s := c.get(f"/api/v1/tolerance/{jid}").json())["state"] not in ("cancelled", "finished", "failed"):
        assert time.time() - t0 < 30
        time.sleep(0.05)
    assert s["state"] == "cancelled"
    assert s["result"]["monte_carlo"]["trials"] < 2000
