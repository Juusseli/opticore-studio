"""Thin-film coating design: spectral solver, back surface, starting designs,
optimisation, Monte Carlo, deposition recipe, project coating export, API."""

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.coatdesign import (
    CoatingDesign,
    DesignError,
    Resolver,
    evaluate_design,
    monte_carlo,
    optimize_design,
    recipe,
    spectrum,
    stack_spectral,
    stopband_halfwidth,
    template,
    to_coating_definition,
)
from opticore.materials import MaterialLibrary
from opticore.thinfilm import Layer, coating_from_definition, stack_rt

NH, NL = 2.35, 1.46


def _design(**kw):
    d = {"palette": [{"key": "H", "index": NH, "tooling": 1.2, "rate_nm_s": 0.25}, {"key": "L", "index": NL, "tooling": 0.9, "rate_nm_s": 0.8}], "substrate": "N-BK7"}
    d.update(kw)
    return CoatingDesign.model_validate(d)


def _ns(lam_nm):
    return MaterialLibrary().index("N-BK7", lam_nm * 1e-3)


def test_spectral_solver_matches_the_thin_film_module():
    lam = np.linspace(400, 800, 9)
    layers = [(np.full(9, 2.1 - 0.01j), 80.0), (np.full(9, 1.38 + 0j), 120.0), (np.full(9, 2.3 + 0j), 35.0)]
    for ang in (0.0, 30.0, 60.0):
        o = stack_spectral(np.ones(9), np.full(9, 1.52 + 0j), layers, lam, math.sin(math.radians(ang)))
        for i, l in enumerate(lam):
            ref = stack_rt(1.0, 1.52, tuple(Layer(N.real, d, -N.imag) for N, d in [(L[0][i], L[1]) for L in layers]), l * 1e-3, np.array([math.cos(math.radians(ang))]))
            for k in ("Rs", "Rp", "Ts", "Tp"):
                assert o[k][i] == pytest.approx(ref[k][0], abs=1e-13)


def test_quarter_wave_stack_peak_and_stop_band_width():
    lam0, N = 600.0, 20
    d = _design(substrate="N-BK7")
    res = Resolver(d)
    layers = template(d, "hr", pairs=N, lambda0_nm=lam0)["design"]["layers"]
    D = _design(layers=layers)
    lam = np.linspace(400, 900, 5001)
    R = spectrum(D, res, lam)["R"]
    ns = _ns(lam0)
    Y = (NH / NL) ** (2 * N) * NH**2 / ns
    i0 = int(np.argmin(np.abs(lam - lam0)))
    assert R[i0] == pytest.approx(((1 - Y) / (1 + Y)) ** 2, abs=1e-6)
    # stop band edges (R falls to half its plateau) in g = lambda0 / lambda
    lo = hi = i0  # contiguous high-reflection band around lambda0
    while R[lo - 1] > 0.5:
        lo -= 1
    while R[hi + 1] > 0.5:
        hi += 1
    g_lo, g_hi = lam0 / lam[hi], lam0 / lam[lo]
    dg = stopband_halfwidth(NH, NL)
    assert (g_hi - g_lo) / 2 == pytest.approx(dg, rel=0.04)
    assert (g_hi + g_lo) / 2 == pytest.approx(1.0, abs=0.01)


def test_incoherent_back_surface_of_a_bare_plate():
    lam = np.array([550.0])
    n = _ns(550.0)
    sp = spectrum(_design(back_side="uncoated"), Resolver(_design()), lam)
    assert sp["T"][0] == pytest.approx(2 * n / (n * n + 1), rel=1e-12)
    assert sp["R"][0] + sp["T"][0] == pytest.approx(1.0, abs=1e-14)
    # oblique: per polarisation T = (1 - R) / (1 + R) of a single face
    sp = spectrum(_design(back_side="uncoated"), Resolver(_design()), lam, 50.0)
    one = stack_rt(1.0, n, (), 0.55, np.array([math.cos(math.radians(50))]))
    for pol in ("s", "p"):
        R1 = one["R" + pol][0]
        assert sp["T" + pol][0] == pytest.approx((1 - R1) / (1 + R1), rel=1e-12)


@pytest.mark.parametrize("kind,edge", [("longpass", 600.0), ("shortpass", 600.0)])
def test_edge_filters_meet_their_targets_after_refinement(kind, edge):
    D = CoatingDesign.model_validate(template(_design(), kind, pairs=12, edge_nm=edge)["design"])
    o = optimize_design(D, time_limit_s=30)
    E = evaluate_design(CoatingDesign.model_validate(o["design"]))
    assert o["final_merit"] <= o["initial_merit"]
    assert all(t["met"] for t in E["targets"])
    blocking = next(t for t in E["targets"] if t["target"][0] == 0.01)
    assert blocking["max"] <= 0.01 + 1e-5


def test_hr_and_notch_templates_work_without_optimisation():
    for kind in ("hr", "notch"):
        D = CoatingDesign.model_validate(template(_design(), kind, pairs=10, lambda0_nm=633.0)["design"])
        E = evaluate_design(D)
        assert E["targets"][0]["met"], kind


def test_fabry_perot_bandpass_peaks_at_the_design_wavelength():
    D = CoatingDesign.model_validate(template(_design(), "bandpass", pairs=5, lambda0_nm=550.0)["design"])
    lam = np.linspace(540, 560, 4001)
    T = spectrum(D, Resolver(D), lam)["T"]
    assert lam[int(np.argmax(T))] == pytest.approx(550.0, abs=0.05)
    assert T.max() > 0.85
    assert T[0] < 0.05 and T[-1] < 0.05  # narrow pass band


def test_needle_optimisation_builds_a_broadband_ar():
    d = _design(palette=[{"key": "H", "index": 2.35}, {"key": "L", "index": 1.38}])
    D = CoatingDesign.model_validate(template(d, "ar_broadband", band_min_nm=420, band_max_nm=680)["design"])
    start = evaluate_design(D)["targets"][0]["max"]
    o = optimize_design(D, method="needle", time_limit_s=60)
    out = CoatingDesign.model_validate(o["design"])
    E = evaluate_design(out)
    assert E["targets"][0]["max"] <= 0.002 + 1e-5  # R <= 0.2 % over 420-680 nm (met within 0.001 %)
    assert E["targets"][0]["met"]
    assert start > 0.01
    assert len(out.layers) > len(D.layers)
    assert min(L.thickness_nm for L in out.layers) >= 1.0
    assert any(h["step"] == "needle" for h in o["history"])
    merits = [h["merit"] for h in o["history"]]
    assert merits[-1] <= merits[0]


def test_bounds_and_locked_layers_are_respected():
    D = CoatingDesign.model_validate(template(_design(), "longpass", pairs=6, edge_nm=600)["design"])
    lay = [dict(L) for L in D.model_dump()["layers"]]
    lay[0]["locked"] = True
    lay[0]["thickness_nm"] = 33.3
    D = _design(layers=lay, targets=D.model_dump()["targets"], min_thickness_nm=20.0, max_thickness_nm=150.0)
    o = optimize_design(D, time_limit_s=20)
    out = CoatingDesign.model_validate(o["design"])
    assert out.layers[0].thickness_nm == 33.3 and out.layers[0].locked
    assert all(20.0 - 1e-9 <= L.thickness_nm <= 150.0 + 1e-9 for L in out.layers if not L.locked)


def test_monte_carlo_spread_and_yield():
    D = CoatingDesign.model_validate(template(_design(), "hr", pairs=10, lambda0_nm=633.0)["design"])
    z = monte_carlo(D, sigma_rel=0.0, runs=5)
    assert np.allclose(z["p05"], z["nominal"]) and np.allclose(z["p95"], z["nominal"])
    assert z["yield"] == 1.0
    m = monte_carlo(D, sigma_rel=0.03, runs=60, seed=3)
    spread = np.array(m["p95"]) - np.array(m["p05"])
    assert spread.max() > 0.05
    assert m == monte_carlo(D, sigma_rel=0.03, runs=60, seed=3)  # reproducible
    with pytest.raises(DesignError):
        monte_carlo(D, sigma_rel=0.9)


def test_recipe_monitor_crystal_and_time():
    lam0 = 633.0
    D = CoatingDesign.model_validate(template(_design(), "hr", pairs=4, lambda0_nm=lam0)["design"])
    r = recipe(D, monitor_wavelength_nm=lam0)
    res = Resolver(D)
    for row in r["layers"]:
        j = row["layer"]
        T = spectrum(D, res, np.array([lam0]), 0.0, D.layers[:j], back_side="uncoated")["T"][0]
        assert row["monitor_end"] == pytest.approx(T, abs=1e-12)
        assert row["qwot_monitor"] == pytest.approx(1.0, rel=1e-12)  # quarter waves at the monitor wavelength
        assert row["termination"] == "turning point" and row["turning_points"] == 0  # the extremum is the layer end
        p = next(x for x in D.palette if x.key == row["material"])
        assert row["crystal_nm"] == pytest.approx(row["thickness_nm"] / p.tooling)
        assert row["time_s"] == pytest.approx(row["thickness_nm"] / p.rate_nm_s)
    # quarter-wave layers end on a turning point of the monitor signal (zero slope)
    for c in r["curves"]:
        s = np.array(c["signal"])
        assert abs(s[-1] - s[-2]) < 0.01 * abs(s[-1] - s[0])
    assert r["total_time_s"] == pytest.approx(sum(x["time_s"] for x in r["layers"]))
    assert r["layers"][0]["cumulative_nm"] == pytest.approx(D.layers[0].thickness_nm)


def test_saved_project_coating_reproduces_the_design():
    D = CoatingDesign.model_validate(template(_design(), "longpass", pairs=6, edge_nm=600)["design"])
    cd = to_coating_definition(D, "my lp")
    assert cd["name"] == "MY LP"
    c = coating_from_definition(cd, MaterialLibrary())
    lam = 610.0
    n = _ns(lam)
    o = stack_rt(1.0, n, c.oriented(lam * 1e-3, 1.0, n), lam * 1e-3, np.array([1.0]))
    sp = spectrum(D, Resolver(D), np.array([lam]))
    assert 0.5 * (o["Rs"][0] + o["Rp"][0]) == pytest.approx(sp["R"][0], abs=1e-12)


def test_dispersive_palette_material():
    d = _design(palette=[{"key": "H", "index": 2.35}, {"key": "L", "material": "FUSED_SILICA"}], layers=[{"material": "L", "thickness_nm": 100.0}])
    res = Resolver(d)
    lam = np.array([450.0, 650.0])
    sp = spectrum(d, res, lam)
    lib = MaterialLibrary()
    for i, l in enumerate(lam):
        ref = stack_rt(1.0, _ns(l), (Layer(lib.index("FUSED_SILICA", l * 1e-3), 100.0),), l * 1e-3, np.array([1.0]))
        assert sp["R"][i] == pytest.approx(0.5 * (ref["Rs"][0] + ref["Rp"][0]), abs=1e-13)


def test_validation_errors():
    with pytest.raises(ValueError):
        _design(layers=[{"material": "X", "thickness_nm": 10}])
    with pytest.raises(ValueError):
        _design(targets=[{"lambda_min_nm": 600, "lambda_max_nm": 500, "value": 0}])
    with pytest.raises(DesignError):
        Resolver(_design(palette=[{"key": "H", "material": "NOPE"}]))
    with pytest.raises(DesignError):
        optimize_design(_design(layers=[{"material": "H", "thickness_nm": 10}]))


def test_coating_design_api():
    c = TestClient(app)
    d = _design().model_dump()
    t = c.post("/api/v1/coating-design/template", json={"design": d, "kind": "longpass", "edge_nm": 600, "pairs": 8}).json()
    D = t["design"]
    e = c.post("/api/v1/coating-design/evaluate", json={"design": D}).json()
    assert len(e["spectrum"]["T"]) == len(e["lambda_nm"]) and e["layer_count"] == len(D["layers"])
    o = c.post("/api/v1/coating-design/optimize", json={"design": D, "method": "refine", "time_limit_s": 10}).json()
    assert o["final_merit"] <= o["initial_merit"]
    r = c.post("/api/v1/coating-design/recipe", json={"design": o["design"], "monitor_wavelength_nm": 700}).json()
    assert len(r["layers"]) == len(o["design"]["layers"])
    m = c.post("/api/v1/coating-design/montecarlo", json={"design": o["design"], "sigma_rel": 0.01, "runs": 10}).json()
    assert 0 <= m["yield"] <= 1
    cd = c.post("/api/v1/coating-design/export-coating", json={"design": o["design"], "name": "lp600"}).json()
    assert cd["name"] == "LP600" and len(cd["layers"]) == len(o["design"]["layers"])
    assert c.post("/api/v1/coating-design/evaluate", json={"design": {**D, "substrate": "NOPE"}}).status_code == 422
