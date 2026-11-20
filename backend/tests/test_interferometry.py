"""Interferometric testing (analysis/interferometry.py) and its library example.

References (independent of the analysis):
* the N-step phase-shifting formula recovers any phase for N = 3 ... 8 and any visibility;
* the flood-fill unwrapping restores a smooth phase sampled below pi per pixel;
* tilt fringes: t fringes across the pupil diameter cross the pupil's x axis 2t times;
* a sphere tested at its centre of curvature is a null test (no fringes); a lens tested in double pass shows twice
  the fringes of a single pass;
* the paraboloid tested at its centre of curvature: the exact double-pass optical path of the ray that leaves the
  focus through the pupil point (u, v), reflects on z = R - h^2/(2R) and returns to the reference sphere through the
  vertex, computed here in closed form; at the mirror height h it is r^4/(4R^3) to fourth order.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.analysis.interferometry import interferogram, phase_shift, unwrap_flood
from opticore.api.main import app
from opticore.samples import HENE_UM, PARA_D_MM, PARA_R_MM, get_sample
from opticore.system import compile_system

client = TestClient(app)


@pytest.mark.parametrize("n", [3, 4, 5, 8])
def test_phase_shifting_recovers_any_phase(n):
    rng = np.random.default_rng(n)
    phi = rng.uniform(-math.pi, math.pi, (20, 30))
    for V in (1.0, 0.35):
        frames = np.stack([0.5 * (1 + V * np.cos(phi + 2 * math.pi * k / n)) for k in range(n)])
        got = phase_shift(frames)
        assert np.abs((got - phi + math.pi) % (2 * math.pi) - math.pi).max() < 1e-12


def test_flood_fill_unwrapping():
    y, x = np.mgrid[-1:1:101j, -1:1:101j]
    valid = x * x + y * y <= 1
    true = 2 * math.pi * (3.0 * (x * x + y * y) + 4.0 * x - 2.5 * y)  # < pi per pixel
    wrapped = (true + math.pi) % (2 * math.pi) - math.pi
    un = unwrap_flood(wrapped, valid)
    d = (un - true)[valid]
    assert np.abs(d - d[0]).max() < 1e-10 and np.all(np.isnan(un[~valid]))
    island = valid & (x > 0.9)  # a region not connected to the centre stays NaN
    assert np.all(np.isnan(unwrap_flood(wrapped, island & (np.abs(y) < 0.1))[~(island & (np.abs(y) < 0.1))]))


def _sphere_at_coc():
    p = get_sample("paraboloid-test")
    sysd = p.system.model_dump(mode="json")
    sysd["surfaces"][1]["conic"] = 0.0
    from opticore.model import OpticalSystem

    return compile_system(OpticalSystem.model_validate(sysd), [])


def test_null_test_tilt_fringes_and_double_pass():
    r = interferogram(_sphere_at_coc(), grid=64, tilt_x=10.0, phase_steps=4)
    assert r["pv_waves"] < 1e-6  # a sphere at its centre of curvature: no aberration fringes
    I = np.array(r["intensity"], float)
    row = I[I.shape[0] // 2]
    row = row[np.isfinite(row)] - 0.5
    crossings = int(np.sum(np.sign(row[1:]) != np.sign(row[:-1])))
    assert crossings == 20  # 10 tilt fringes: 20 crossings of the mean level across the diameter
    cs = compile_system(get_sample("cooke-triplet").system, [])
    one, two = interferogram(cs, grid=96, passes=1, phase_steps=0), interferogram(cs, grid=96, passes=2, phase_steps=0)
    assert two["fringes_pv"] == pytest.approx(2 * one["fringes_pv"], rel=1e-12) and one["pv_waves"] == pytest.approx(two["pv_waves"], rel=1e-12)
    rec = interferogram(cs, grid=96, passes=2, tilt_y=6.0, phase_steps=5)
    assert rec["recovery_rms_error_waves"] < 1e-9 and rec["recovered_fraction"] == 1.0 and rec["notes"] == []
    In = np.array(rec["intensity"], float)
    assert np.nanmin(In) >= 0 and np.nanmax(In) <= 1


def _exact_paraboloid_opd(u: float) -> float:
    """Double-pass OPD (waves) of the paraboloid at its centre of curvature for the ray through the pupil-plane radius u
    (the plane of the vertex), against the reference sphere through the vertex centred on the focus."""
    R, lam = PARA_R_MM, HENE_UM * 1e-3
    if u == 0:
        return 0.0
    a = u * u / (2 * R)  # the ray (s u, s R) meets z = R - x^2 / (2R) where a s^2 + R s - R = 0
    s = 2 * R / (R + math.sqrt(R * R + 4 * a * R))  # the stable root of a s^2 + R s - R = 0
    P = np.array([s * u, s * R])
    L1 = float(np.linalg.norm(P))
    d = P / L1
    nrm = np.array([P[0] / R, 1.0]) / math.hypot(P[0] / R, 1.0)
    rd = d - 2 * np.dot(d, nrm) * nrm
    b, c = float(np.dot(P, rd)), float(np.dot(P, P) - R * R)
    t = min((-b - math.sqrt(b * b - c), -b + math.sqrt(b * b - c)), key=abs)
    return (L1 + t - R) / lam


def test_paraboloid_example_matches_the_exact_double_pass_path():
    p = get_sample("paraboloid-test")
    assert p.ui["open_view"] == "interferogram"
    cs = compile_system(p.system, [])
    st = p.analysis_settings["interferogram"]
    r = interferogram(cs, st["field"], st["wavelength"], st["grid"], st["passes"], st["tilt_x"], st["tilt_y"], st["visibility"], st["phase_steps"])
    W = np.array(r["wavefront_waves"], float)
    X, Y = np.meshgrid(r["x"], r["y"])
    ok = np.isfinite(W)
    ex = np.array([_exact_paraboloid_opd(math.hypot(a, b) * PARA_D_MM / 2) for a, b in zip(X[ok], Y[ok])])
    d = -W[ok] - ex  # the analysis reports the wavefront error, the opposite sign of the path excess
    assert np.abs(d - d.mean()).max() < 1e-6
    # fourth order at the mirror height: r^4 / (4 R^3) (the edge ray meets the mirror 2.3 mm before the vertex plane)
    h_edge = 75.0 * (1 - 0.0019)  # about the edge's height on the mirror
    assert _exact_paraboloid_opd(75.0) == pytest.approx(h_edge**4 / (4 * PARA_R_MM**3) / (HENE_UM * 1e-3), rel=2e-3)
    assert 7.0 < r["fringes_pv"] < 7.3 and r["max_step_rad"] < 0.9 * math.pi
    assert r["recovery_rms_error_waves"] < 1e-9 and r["recovered_fraction"] == 1.0 and r["notes"] == []


def test_interferogram_endpoint():
    p = get_sample("paraboloid-test")
    body = {"system": p.system.model_dump(mode="json"), "grid": 64, "tilt_x": 3.0}
    j = client.post("/api/v1/analysis/interferogram", json=body)
    assert j.status_code == 200, j.text
    r = j.json()
    assert len(r["intensity"]) == 64 and r["phase_steps"] == 4 and "recovered_waves" in r
    assert client.post("/api/v1/analysis/interferogram", json={**body, "phase_steps": 2}).json()["error"]["code"] == "INTERFEROGRAM"
    assert client.post("/api/v1/analysis/interferogram", json={**body, "passes": 3}).status_code == 422
