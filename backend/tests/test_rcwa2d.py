"""Crossed gratings and metasurfaces by RCWA (wave/rcwa2d.py, wave/rcwaapi.py) and their library examples.

Benchmarks:
* a structure invariant in y (stripes spanning the period) equals the 1D solver (wave/rcwa.py) exactly, for TE, TM,
  conical incidence, an absorbing sliced sawtooth and a metal; lines along x equal the 1D solver turned by 90 degrees;
* uniform layers: the thin-film transfer matrix;
* lossless structures conserve energy; turning the structure and the plane of incidence by 90 degrees turns the
  order map; a C4-symmetric structure at normal incidence is polarisation independent;
* reciprocity: the unpolarised efficiency of order (m, q) at incidence k equals that at incidence -k_mq, for an
  absorbing rotated ellipse (no symmetry);
* translating the whole pattern (here across the cell edge) leaves every efficiency unchanged;
* scalar theory: a thin checkerboard pi-phase grating is the product of two binary gratings, 16/pi^4 in each of the
  orders (+-1, +-1); orders with m + q odd vanish exactly (the pattern is invariant under the half-diagonal shift);
* Dykhne's theorem: a checkerboard of eps1 and eps2 far below the wavelength is a film of permittivity sqrt(eps1 eps2);
  of fused silica and air on fused silica that is the index sqrt(n), the ideal single-layer antireflection coating;
* the guided resonance of a lossless, up-down symmetric membrane with only the zeroth order propagating passes through
  complete reflection and complete transmission (its two eigen-channels change phase by 2 pi against each other).
"""

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.optimize import minimize_scalar

from opticore.api.main import app
from opticore.materials import MaterialLibrary
from opticore.samples import AR_PERIOD_UM, GRATING_LAMBDA_UM, checkerboard_ar_depth_um, get_sample
from opticore.thinfilm import Layer, stack_rt
from opticore.wave.rcwa import GratingLayer, RcwaError, solve
from opticore.wave.rcwa2d import PatternLayer, Shape, from_1d, solve2d
from opticore.wave.rcwaapi import analyse, run

client = TestClient(app)
LIB = MaterialLibrary()
IX = lambda n, l: LIB.index(n, l)  # noqa: E731
LAM = 0.633
K = 12
SAW = [GratingLayer(0.5 / K, 1.0, [(1 - (k + 0.5) / K, 1.0, (2.0 + 0.1j) ** 2)]) for k in range(K)]
CASES = {"lamellar": ([GratingLayer(0.5, 1.0, [(0.25, 0.75, 1.5**2)])], 2.25),
         "sawtooth": (SAW, 2.25),
         "metal": ([GratingLayer(0.1, 1.0, [(0.0, 0.5, (0.2 + 3.5j) ** 2)])], (0.2 + 3.5j) ** 2)}


@pytest.mark.parametrize("case", list(CASES))
@pytest.mark.parametrize("inc", [(10.0, 0.0, "TE"), (10.0, 0.0, "TM"), (20.0, 30.0, (0.6, 0.8))])
def test_a_structure_invariant_in_y_equals_the_1d_solver(case, inc):
    lay, eo = CASES[case]
    th, ph, pol = inc
    a = solve(1.2, lay, 1.0, eo, LAM, th, ph, pol, 10)
    b = solve2d(1.2, 0.9, [from_1d(L, 1.2, 0.9) for L in lay], 1.0, eo, LAM, th, ph, pol, 10, 2)
    assert np.abs(a["R"] - b["R"][:, 2]).max() < 1e-12 and np.abs(a["T"] - b["T"][:, 2]).max() < 1e-12
    assert np.abs(np.delete(b["R"], 2, axis=1)).max() < 1e-20 and np.abs(np.delete(b["T"], 2, axis=1)).max() < 1e-20


def test_lines_along_x_equal_the_1d_solver_turned():
    Ly = 1.1
    g1 = [GratingLayer(0.4, 1.0, [(0.2, 0.65, 4.0)])]
    pl = [PatternLayer(0.4, 1.0, [Shape("rectangle", 0.5, 0.425 * Ly, 1.0, 0.45 * Ly, 4.0)])]
    for th, ph, pol in ((15.0, 90.0, "TE"), (15.0, 90.0, "TM"), (25.0, 120.0, (0.6, 0.8))):
        a = solve(Ly, g1, 1.0, 2.25, LAM, th, ph - 90.0, pol, 10)
        b = solve2d(1.0, Ly, pl, 1.0, 2.25, LAM, th, ph, pol, 2, 10)
        assert np.abs(a["R"] - b["R"][2, :]).max() < 1e-12 and np.abs(a["T"] - b["T"][2, :]).max() < 1e-12


def test_uniform_layers_equal_the_thin_film_matrix():
    u = [PatternLayer(0.12, 2.1**2), PatternLayer(0.2, (1.38 + 0.05j) ** 2)]
    tf = stack_rt(1.0, 1.52, (Layer(2.1, 120.0, 0.0, ""), Layer(1.38, 200.0, 0.05, "")), LAM, np.array([math.cos(math.radians(35))]))
    for pol, key in (("TE", "Rs"), ("TM", "Rp")):
        r = solve2d(0.7, 0.5, u, 1.0, 1.52**2, LAM, 35.0, 40.0, pol, 2, 2)
        assert r["R"].sum() == pytest.approx(tf[key][0], abs=1e-12) and r["T"].sum() == pytest.approx(tf["T" + key[1]][0], abs=1e-12)


def test_energy_rotation_and_c4_symmetry():
    L = 0.8
    lay = [PatternLayer(0.3, 2.1**2, [Shape("ellipse", 0.3, 0.45, 0.35, 0.22, 1.0, 25.0), Shape("rectangle", 0.62, 0.15, 0.2, 0.12, 1.45**2, -10.0)])]
    a = solve2d(L, L, lay, 1.0, 1.5**2, LAM, 20.0, 10.0, "TM", 6, 6)
    assert abs(a["R"].sum() + a["T"].sum() - 1) < 1e-12
    # the structure turned by +90 degrees about the cell's corner ((x, y) -> (L - y, x)) with the plane of incidence
    turned = [PatternLayer(0.3, 2.1**2, [Shape(s.kind, L - s.cy, s.cx, s.a, s.b, s.eps, s.angle_deg + 90.0) for s in lay[0].shapes])]
    b = solve2d(L, L, turned, 1.0, 1.5**2, LAM, 20.0, 100.0, "TM", 6, 6)
    assert np.abs(np.rot90(b["R"], 3) - a["R"]).max() < 1e-12 and np.abs(np.rot90(b["T"], 3) - a["T"]).max() < 1e-12
    c4 = [PatternLayer(0.25, 2.0**2, [Shape("ellipse", 0.4, 0.4, 0.4, 0.4, 1.0)])]
    te, tm = (solve2d(0.8, 0.8, c4, 1.0, 1.0, 1.3, 0.0, 0.0, p, 7, 7)["T"] for p in ("TE", "TM"))
    assert np.abs(te - tm.T).max() < 1e-12  # TE (E along y) and TM (E along x) are each other turned by 90 degrees


def test_reciprocity_of_an_absorbing_asymmetric_pattern():
    lay = [PatternLayer(0.2, 1.0, [Shape("ellipse", 0.35, 0.5, 0.42, 0.2, (2.0 + 0.2j) ** 2, 30.0)])]
    M = 6

    def unpol(th, ph):
        r = [solve2d(0.9, 0.9, lay, 1.0, 2.25, LAM, th, ph, p, M, M) for p in ("TE", "TM")]
        return 0.5 * (r[0]["R"] + r[1]["R"]), r[0]

    R, r0 = unpol(18.0, 25.0)
    checked = 0
    for i, j in np.ndindex(R.shape):
        if not r0["propagating_r"][i, j] or (i, j) == (M, M):
            continue
        kx, ky = r0["kx"][i, j], r0["ky"][i, j]
        R2, _ = unpol(math.degrees(math.asin(math.hypot(kx, ky))), math.degrees(math.atan2(-ky, -kx)))
        assert R2[i, j] == pytest.approx(R[i, j], abs=2e-5)
        checked += 1
    assert checked >= 5


def test_translating_the_pattern_across_the_cell_edge_changes_nothing():
    base = [Shape("ellipse", 0.3, 0.4, 0.3, 0.2, 2.0**2, 15.0), Shape("rectangle", 0.7, 0.75, 0.25, 0.3, 1.5**2, 0.0)]
    moved = [Shape(s.kind, (s.cx + 0.55) % 1.0 - 0.1, (s.cy + 0.37) % 1.0, s.a, s.b, s.eps, s.angle_deg) for s in base]
    a = solve2d(1.0, 1.0, [PatternLayer(0.3, 1.0, base)], 1.0, 2.25, LAM, 12.0, 40.0, "TE", 5, 5)
    b = solve2d(1.0, 1.0, [PatternLayer(0.3, 1.0, moved)], 1.0, 2.25, LAM, 12.0, 40.0, "TE", 5, 5)
    assert np.abs(a["T"] - b["T"]).max() < 1e-12 and np.abs(a["R"] - b["R"]).max() < 1e-12


def test_shapes_are_validated():
    with pytest.raises(RcwaError, match="overlap"):
        solve2d(1.0, 1.0, [PatternLayer(0.1, 1.0, [Shape("ellipse", 0.5, 0.5, 0.5, 0.5, 4.0), Shape("rectangle", 0.7, 0.5, 0.3, 0.3, 4.0)])], 1.0, 1.0, LAM)
    with pytest.raises(RcwaError, match="overlap"):  # larger than the period: overlaps its copy in the next cell
        solve2d(1.0, 1.0, [PatternLayer(0.1, 1.0, [Shape("ellipse", 0.5, 0.5, 1.2, 0.4, 4.0)])], 1.0, 1.0, LAM)
    with pytest.raises(RcwaError, match="orders"):
        solve2d(1.0, 1.0, [], 1.0, 1.0, LAM, Mx=20, My=20)
    # touching shapes (a checkerboard) are accepted
    solve2d(1.0, 1.0, [PatternLayer(0.1, 1.0, [Shape("rectangle", 0.25, 0.25, 0.5, 0.5, 4.0), Shape("rectangle", 0.75, 0.75, 0.5, 0.5, 4.0)])], 1.0, 1.0, LAM, Mx=2, My=2)


def test_crossed_grating_endpoint():
    req = {"wavelength_um": 1.55, "period_um": 1.1, "period_y_um": 1.1, "harmonics": 4, "harmonics_y": 4, "polarisation": "unpolarised",
           "incident": {"n": 1}, "substrate": {"n": 1},
           "layers": [{"kind": "pattern", "thickness_um": 0.344, "groove": {"n": 2.0}, "ridge": {"n": 1.0},
                       "shapes": [{"kind": "ellipse", "cx_um": 0.55, "cy_um": 0.55, "a_um": 0.55, "b_um": 0.55}]}],
           "sweep": {"kind": "wavelength", "start": 1.5, "stop": 1.6, "points": 3, "orders_2d": [[0, 0], [1, 0]]}}
    r = client.post("/api/v1/wave/rcwa", json=req)
    j = r.json()
    assert r.status_code == 200 and abs(j["absorbed"]) < 1e-12 and j["harmonics_y"] == 4
    assert j["orders"][0]["q"] == 0 and "azimuth_t_deg" in j["orders"][0]
    assert j["convergence"]["harmonics_y_low"] == 2 and j["sweep"]["orders"] == ["(0,0)", "(1,0)"] and len(j["sweep"]["curves"]["T(0,0)"]) == 3
    assert j["structure"]["period_y_um"] == 1.1 and j["structure"]["slices"][0]["shapes"][0]["kind"] == "ellipse"
    assert j["zeroth"]["TE"]["t"]["cross_power"] < 1e-20  # a centred circle converts no polarisation at normal incidence
    # 1D profiles in a crossed grating become stripes along y
    j2 = client.post("/api/v1/wave/rcwa", json=dict(req, sweep=None, layers=[{"kind": "sawtooth", "thickness_um": 0.3, "slices": 4, "ridge": {"n": 1.5}, "groove": {"n": 1.0}}])).json()
    assert len(j2["structure"]["slices"]) == 4 and j2["structure"]["slices"][0]["shapes"][0]["b"] == pytest.approx(1.1)
    for bad, word in ((dict(req, period_y_um=None, sweep=None), "crossed"),
                      (dict(req, sweep=None, harmonics=20, harmonics_y=20), "orders"),
                      (dict(req, sweep=None, layers=[dict(req["layers"][0], shapes=[{"kind": "ellipse", "cx_um": 0.55, "cy_um": 0.55, "a_um": 1.3, "b_um": 0.5}])]), "overlap")):
        e = client.post("/api/v1/wave/rcwa", json=bad)
        assert e.status_code == 422 and e.json()["error"]["code"] == "RCWA" and word in e.json()["error"]["message"]
    for sid in ("fanout-grating", "checkerboard-ar", "phc-mirror"):  # the examples' stored settings are valid requests
        q = dict(get_sample(sid).analysis_settings["rcwa"], sweep=None, harmonics=2, harmonics_y=2)
        assert client.post("/api/v1/wave/rcwa", json=q).status_code == 200, sid


# ---------------------------------------------------------------- the library examples
def test_checkerboard_fanout_example_matches_scalar_theory():
    p = get_sample("fanout-grating")
    assert p.ui["open_view"] == "rcwa"
    req = p.analysis_settings["rcwa"]
    r = analyse(req, IX, [])
    by = {(o["m"], o["q"]): o["T"] / r["total_T"] for o in r["orders"] if o["T"] is not None}
    want = (4 / math.pi**2) ** 2  # the product of two binary pi gratings: (2/pi)^2 in each of +-1, squared
    assert abs(r["absorbed"]) < 1e-12
    for o in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        assert by[o] == pytest.approx(want, rel=3e-3) and by[o] == pytest.approx(by[(1, 1)], abs=1e-12)
    # (1, 3) and (3, 1): scalar 16/(9 pi^4); not equal to each other, since TE (E along y) breaks the diagonal mirror
    assert by[(1, 3)] == pytest.approx(want / 9, rel=0.02) and by[(3, 1)] == pytest.approx(want / 9, rel=0.02)
    assert max(v for (m, q), v in by.items() if (m + q) % 2) < 1e-20  # m + q odd: dark by the half-diagonal shift
    # the zeroth order (scalar: dark) converges slowly at the touching corners and falls as the harmonics grow
    low = run(req, IX, harmonics=6, harmonics_y=6)
    t00_low = next(o["T"] for o in low["orders"] if (o["m"], o["q"]) == (0, 0)) / low["total_T"]
    assert by[(0, 0)] < 0.01 and by[(0, 0)] < 0.5 * t00_low


def test_checkerboard_antireflection_example_follows_dykhne():
    p = get_sample("checkerboard-ar")
    req = p.analysis_settings["rcwa"]
    r = analyse(req, IX, [])
    n0 = LIB.index("FUSED_SILICA", GRATING_LAMBDA_UM)
    assert ((n0 - 1) / (n0 + 1)) ** 2 > 0.034 and r["total_R"] < 1e-4 and r["notes"] == []
    d = req["layers"][0]["thickness_um"]
    assert d == pytest.approx(checkerboard_ar_depth_um(), abs=1e-5)
    for x, R in zip(r["sweep"]["x"], r["sweep"]["curves"]["R"]):  # the film of index sqrt(n) over the whole band
        n = LIB.index("FUSED_SILICA", x)
        film = stack_rt(1.0, n, (Layer(math.sqrt(n), d * 1000.0, 0.0, ""),), x, np.array([1.0]))["Rs"][0]
        assert R == pytest.approx(film, abs=5e-4)
    tm = run(dict(req, polarisation="TM", sweep=None), IX)
    assert tm["total_R"] == pytest.approx(r["total_R"], abs=1e-12)  # the checkerboard is C4 symmetric
    # a finer checkerboard is closer to the effective film: halving the period cuts the residual reflectance at 633 nm
    # by more than 20 (at these harmonics; much finer cells meet the corners' truncation floor near 3e-8)
    Rs = [run(dict(req, sweep=None, period_um=AR_PERIOD_UM / f, period_y_um=AR_PERIOD_UM / f,
                   layers=[dict(req["layers"][0], shapes=[dict(s, cx_um=s["cx_um"] / f, cy_um=s["cy_um"] / f, a_um=s["a_um"] / f, b_um=s["b_um"] / f) for s in req["layers"][0]["shapes"]])]),
              IX)["total_R"] for f in (1, 2)]
    assert Rs[1] < Rs[0] / 20


def test_photonic_crystal_membrane_example_reflects_and_transmits_completely():
    p = get_sample("phc-mirror")
    req = p.analysis_settings["rcwa"]
    r = analyse(req, IX, [])
    assert abs(r["absorbed"]) < 1e-12 and [(o["m"], o["q"]) for o in r["orders"]] == [(0, 0)]  # only the zeroth order
    assert r["total_T"] < 1e-4 and r["notes"] == []  # at its resonance, converged
    tm = run(dict(req, polarisation="TM", sweep=None), IX)
    assert tm["total_T"] == pytest.approx(r["total_T"], abs=1e-12)  # C4: either polarisation
    T = r["sweep"]["curves"]["T"]
    assert min(T) < 0.01 and max(T) > 0.99
    # the theorem holds for the truncated (lossless, symmetric) system itself: complete reflection and transmission
    point = dict(req, sweep=None)
    t = lambda x: run(point, IX, wavelength_um=x, harmonics=5, harmonics_y=5)  # noqa: E731
    dip = minimize_scalar(lambda x: t(x)["total_T"], bounds=(1.53, 1.57), method="bounded", options={"xatol": 1e-9})
    peak = minimize_scalar(lambda x: t(x)["total_R"], bounds=(1.49, 1.535), method="bounded", options={"xatol": 1e-9})
    assert dip.fun < 1e-10 and peak.fun < 1e-10
