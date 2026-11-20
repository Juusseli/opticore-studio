"""Rigorous coupled-wave analysis (wave/rcwa.py, wave/rcwaapi.py) and the grating examples of the library.

Benchmarks:
* uniform layers: the thin-film transfer matrix (thinfilm.py) for s and p, oblique incidence, an absorbing layer;
* lossless gratings: R + T = 1 (TE, TM, conical, sliced profiles); a symmetric profile at normal incidence diffracts
  +m and -m equally;
* reciprocity (Rayleigh): R_m at incidence k_x equals R_m at incidence -k_x,m, for an absorbing blazed grating;
* the blaze direction: a sawtooth thick at +x (a prism with its base there) sends the light into the +1 order, and
  its mirror image at the mirrored angle gives the mirrored orders;
* scalar diffraction: a thin binary pi-phase grating (period >> wavelength) sends 4/pi^2 and 4/(9 pi^2) of the
  transmitted light into orders +-1 and +-3 and nothing into the zeroth;
* zeroth-order effective-medium theory: a lamellar grating much finer than the wavelength reflects like a film of
  index sqrt(f e1 + (1-f) e2) (TE) or 1/sqrt(f/e1 + (1-f)/e2) (TM), and its retardance approaches that film's as the
  period shrinks; the error halves with the period (first order in period/wavelength: the evanescent orders at the
  grating's two interfaces; the index correction inside the grating is of second order);
* Li's factorisation: TM efficiencies converge as the harmonics grow;
* a guided-mode resonance: complete reflection (a transmission zero) of a lossless grating with one propagating order,
  near the wavelength period x n_eff of the slab waveguide's TE0 mode (transfer-matrix mode solver here).
"""

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.optimize import brentq, minimize_scalar

from opticore.api.main import app
from opticore.materials import MaterialLibrary
from opticore.samples import GMR_PERIOD_UM, get_sample
from opticore.thinfilm import Layer, stack_amplitudes, stack_rt
from opticore.wave.rcwa import GratingLayer, solve
from opticore.wave.rcwaapi import analyse, run

client = TestClient(app)
LIB = MaterialLibrary()
IX = lambda n, l: LIB.index(n, l)  # noqa: E731
LAM = 0.633


@pytest.mark.parametrize("theta", [0.0, 35.0, 70.0])
@pytest.mark.parametrize("pol", ["TE", "TM"])
def test_uniform_layers_equal_the_thin_film_matrix(theta, pol):
    lay = [GratingLayer(0.12, 2.1**2), GratingLayer(0.2, (1.38 + 0.05j) ** 2)]
    r = solve(1.0, lay, 1.0, 1.52**2, LAM, theta, 0.0, pol, harmonics=3)
    tf = stack_rt(1.0, 1.52, (Layer(2.1, 120.0, 0.0, ""), Layer(1.38, 200.0, 0.05, "")), LAM, np.array([math.cos(math.radians(theta))]))
    key = "s" if pol == "TE" else "p"
    assert r["R"].sum() == pytest.approx(tf["R" + key][0], abs=1e-12) and r["T"].sum() == pytest.approx(tf["T" + key][0], abs=1e-12)


def test_energy_symmetry_and_conical_incidence():
    g = [GratingLayer(0.5, 1.0, [(0.25, 0.75, 1.5**2)])]
    for pol in ("TE", "TM"):
        r = solve(1.2, g, 1.0, 1.5**2, LAM, 10.0, 0.0, pol, harmonics=20)
        assert abs(r["R"].sum() + r["T"].sum() - 1) < 1e-12
    assert abs(sum(x.sum() for x in (solve(1.2, g, 1.0, 2.25, LAM, 20.0, 30.0, (0.6, 0.8), harmonics=20)[k] for k in ("R", "T"))) - 1) < 1e-12
    s = {"wavelength_um": LAM, "period_um": 1.0, "harmonics": 25, "polarisation": "TM", "substrate": {"n": 1.5},
         "layers": [{"kind": "sinusoidal", "thickness_um": 0.4, "slices": 20, "ridge": {"n": 1.5}, "groove": {"n": 1.0}}]}
    r = analyse(s, IX)
    assert abs(r["absorbed"]) < 1e-12
    by = {o["m"]: o for o in r["orders"]}
    assert all(abs(by[m]["T"] - by[-m]["T"]) < 1e-12 for m in by if m > 0)


def test_reciprocity_of_an_absorbing_blazed_grating():
    s = {"wavelength_um": LAM, "period_um": 1.5, "harmonics": 40, "polarisation": "TE", "substrate": {"n": 1.5},
         "layers": [{"kind": "sawtooth", "thickness_um": 0.5, "slices": 30, "ridge": {"n": 2.0, "k": 0.1}, "groove": {"n": 1.0}}]}
    th = 15.0
    a = run(dict(s, theta_deg=th), IX)
    checked = 0
    for o in a["orders"]:
        if o["R"] is None:
            continue
        kxm = math.sin(math.radians(th)) + o["m"] * LAM / 1.5
        b = run(dict(s, theta_deg=math.degrees(math.asin(-kxm))), IX)
        ob = next(q for q in b["orders"] if q["m"] == o["m"])
        assert ob["R"] == pytest.approx(o["R"], abs=2e-6)
        checked += 1
    assert checked >= 3


def test_a_blazed_grating_diffracts_towards_its_thick_side():
    # scalar theory: a sawtooth whose thickness grows with x (a prism with its base at +x) adds the phase 2 pi x / L
    # (physics sign: the thicker glass delays more) and sends the light into the +1 order, k_x + 2 pi / L; its mirror
    # image sends it into -1 with the same efficiency
    n = 1.457
    H = LAM / (n - 1)  # a 2 pi phase step
    s = {"wavelength_um": LAM, "period_um": 10.0, "harmonics": 40, "polarisation": "TE", "substrate": {"n": n},
         "layers": [{"kind": "sawtooth", "thickness_um": H, "slices": 40, "ridge": {"n": n}, "groove": {"n": 1.0}}]}
    r = run(s, IX)
    by = {o["m"]: o["T"] / r["total_T"] for o in r["orders"]}
    assert by[1] > 0.9 and by[1] > 100 * by[-1]
    K = 40
    lay = [GratingLayer(H / K, 1.0, [(1 - (k + 0.5) / K, 1.0, n * n)]) for k in range(K)]
    mir = [GratingLayer(L.thickness, L.eps_bg, [(1 - b, 1 - a, e) for a, b, e in L.segments]) for L in lay]
    for th in (0.0, 12.0):
        a = solve(10.0, lay, 1.0, n * n, LAM, th, 0.0, "TM", 30)
        b = solve(10.0, mir, 1.0, n * n, LAM, -th, 0.0, "TM", 30)
        assert np.allclose(a["T"], b["T"][::-1], atol=1e-10) and np.allclose(a["R"], b["R"][::-1], atol=1e-10)


def test_order_angles_follow_the_grating_equation():
    r = run({"wavelength_um": LAM, "period_um": 1.0, "theta_deg": 10.0, "harmonics": 8, "substrate": {"n": 1.5},
             "layers": [{"kind": "sawtooth", "thickness_um": 0.3, "slices": 5, "ridge": {"n": 1.5}, "groove": {"n": 1.0}}]}, IX)
    for o in r["orders"]:
        s = math.sin(math.radians(10.0)) + o["m"] * LAM
        if o.get("angle_r_deg") is not None:
            assert math.sin(math.radians(o["angle_r_deg"])) == pytest.approx(s, abs=1e-12)
        if o.get("angle_t_deg") is not None:
            assert 1.5 * math.sin(math.radians(o["angle_t_deg"])) == pytest.approx(s, abs=1e-12)


@pytest.mark.parametrize("pol", ["TE", "TM"])
def test_subwavelength_grating_reflects_like_its_effective_medium(pol):
    s = {"wavelength_um": LAM, "period_um": LAM / 40, "harmonics": 15, "polarisation": pol, "substrate": {"n": 1.5},
         "layers": [{"kind": "lamellar", "thickness_um": 0.3, "fill": 0.5, "ridge": {"n": 1.5}, "groove": {"n": 1.0}}]}
    e1, e2, f = 2.25, 1.0, 0.5
    ne = math.sqrt(f * e1 + (1 - f) * e2) if pol == "TE" else 1 / math.sqrt(f / e1 + (1 - f) / e2)
    tf = stack_rt(1.0, 1.5, (Layer(ne, 300.0, 0.0, ""),), LAM, np.array([1.0]))
    assert run(s, IX)["total_R"] == pytest.approx(tf["Rs"][0], abs=1e-4)


def test_li_factorisation_converges_for_tm():
    g = [GratingLayer(0.5, 1.0, [(0.25, 0.75, 1.5**2)])]
    t = [solve(1.2, g, 1.0, 2.25, LAM, 10.0, 0.0, "TM", harmonics=M)["T"] for M in (40, 80)]
    assert abs(t[0][40] - t[1][80]) < 2e-5  # the zeroth order (index M)
    metal = [GratingLayer(0.1, 1.0, [(0.0, 0.5, (0.2 + 3.5j) ** 2)])]
    R = [solve(0.5, metal, 1.0, (0.2 + 3.5j) ** 2, LAM, 0.0, 0.0, "TM", harmonics=M)["R"].sum() for M in (20, 40, 80)]
    assert abs(R[2] - R[1]) < abs(R[1] - R[0])  # monotone convergence (the inverse rule; Laurent's rule wanders)


def test_rcwa_endpoint():
    r = client.post("/api/v1/wave/rcwa", json={"wavelength_um": LAM, "period_um": 1.0, "polarisation": "unpolarised", "substrate": {"n": 1.5},
                                               "layers": [{"kind": "trapezoid", "thickness_um": 0.3, "fill_top": 0.3, "fill_bottom": 0.7, "slices": 6, "ridge": {"n": 1.5}, "groove": {"n": 1}}],
                                               "sweep": {"kind": "angle", "start": 0, "stop": 30, "points": 4}})
    j = r.json()
    assert r.status_code == 200 and abs(j["absorbed"]) < 1e-12 and len(j["sweep"]["x"]) == 4 and len(j["structure"]["slices"]) == 6
    assert "retardance_deg" in j and j["convergence"]["harmonics_low"] == 12
    bad = client.post("/api/v1/wave/rcwa", json={"wavelength_um": LAM, "period_um": 1.0, "incident": {"n": 1.5, "k": 0.1}, "substrate": {"n": 1.5}, "layers": []})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "RCWA"
    # the library examples' stored settings are valid requests as the view sends them
    for sid in ("binary-grating", "waveplate-grating", "gmr-filter"):
        req = dict(get_sample(sid).analysis_settings["rcwa"], sweep=None)
        assert client.post("/api/v1/wave/rcwa", json=req).status_code == 200, sid


# ---------------------------------------------------------------- the library examples
def test_binary_phase_grating_example_matches_scalar_theory():
    p = get_sample("binary-grating")
    assert p.ui["open_view"] == "rcwa"
    r = analyse(p.analysis_settings["rcwa"], IX)
    by = {o["m"]: o["T"] / r["total_T"] for o in r["orders"]}
    assert abs(r["absorbed"]) < 1e-12 and r["convergence"]["max_change"] < 1e-3
    assert by[0] < 2e-3
    for m, want in ((1, 4 / math.pi**2), (3, 4 / (9 * math.pi**2))):
        assert by[m] == pytest.approx(want, rel=0.01) and by[-m] == pytest.approx(by[m], abs=1e-12)


def test_waveplate_example_and_the_effective_medium_limit():
    p = get_sample("waveplate-grating")
    req = p.analysis_settings["rcwa"]
    r = analyse(req, IX)
    assert r["retardance_deg"] == pytest.approx(90.0, abs=1.0) and abs(r["absorbed"]) < 1e-12
    assert [o["m"] for o in r["orders"]] == [0]  # only the zeroth order propagates
    # the retardance approaches the effective-medium film's as the period shrinks, the error ~ period/wavelength
    n_fs = LIB.index("FUSED_SILICA", LAM)
    e1, f, d = n_fs**2, 0.5, req["layers"][0]["thickness_um"]
    n_te, n_tm = math.sqrt(f * e1 + (1 - f)), 1 / math.sqrt(f / e1 + (1 - f))
    amp = {k: stack_amplitudes(1.0, n_fs, (Layer(n, d * 1000.0, 0.0, ""),), LAM, np.array([1.0])) for k, n in (("te", n_te), ("tm", n_tm))}
    emt = math.degrees(-np.angle(amp["te"]["ts"][0]) + np.angle(amp["tm"]["tp"][0]))
    emt = (emt + 180) % 360 - 180
    errs = []
    for div in (16, 32, 64):
        rr = analyse(dict(req, period_um=LAM / div, harmonics=12, sweep=None), IX)
        errs.append(abs(rr["retardance_deg"] - emt))
    assert errs[2] < 0.07 and 1.6 < errs[0] / errs[1] < 2.2 and 1.6 < errs[1] / errs[2] < 2.2


def _te0_neff(lam, layers, n_top, n_sub):
    """TE0 effective index of a planar waveguide (layers top to bottom: (n, d)) by transfer of (E, dE/dz)."""
    k = 2 * math.pi / lam

    def mismatch(ne):
        b = k * ne
        E, dE = 1.0, math.sqrt(b * b - (k * n_top) ** 2)
        for n, d in layers:
            q2 = (k * n) ** 2 - b * b
            q = math.sqrt(abs(q2))
            if q2 > 0:
                E, dE = E * math.cos(q * d) + dE / q * math.sin(q * d), -E * q * math.sin(q * d) + dE * math.cos(q * d)
            else:
                E, dE = E * math.cosh(q * d) + dE / q * math.sinh(q * d), E * q * math.sinh(q * d) + dE * math.cosh(q * d)
        return dE + math.sqrt(b * b - (k * n_sub) ** 2) * E

    grid = np.linspace(max(n for n, _ in layers) - 1e-9, max(n_top, n_sub) + 1e-9, 2000)
    v = [mismatch(x) for x in grid]
    a = next(i for i in range(len(v) - 1) if v[i] * v[i + 1] < 0)
    return brentq(mismatch, grid[a + 1], grid[a])


def test_guided_mode_resonance_filter_example():
    p = get_sample("gmr-filter")
    req = dict(p.analysis_settings["rcwa"], sweep=None)
    r = analyse(p.analysis_settings["rcwa"], IX)
    T = r["sweep"]["curves"]["T"]
    i = int(np.argmin(T))
    xs = r["sweep"]["x"]
    best = minimize_scalar(lambda x: run(req, IX, wavelength_um=x)["total_T"], bounds=(xs[max(0, i - 1)], xs[min(len(xs) - 1, i + 1)]), method="bounded", options={"xatol": 1e-10})
    assert best.fun < 1e-8  # complete reflection of a lossless grating with only the zeroth order propagating
    lam = best.x
    for _ in range(5):  # resonance estimate: period x n_eff of the TE0 mode (grating layer as its TE effective medium)
        ne = _te0_neff(lam, [(math.sqrt(0.5 * 4.0 + 0.5), 0.05), (2.0, 0.12)], 1.0, LIB.index("FUSED_SILICA", lam))
        lam = GMR_PERIOD_UM * ne
    assert best.x == pytest.approx(lam, rel=2e-3)
    assert r["wavelength_um"] == pytest.approx(best.x, abs=5e-4)
