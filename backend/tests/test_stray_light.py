"""Stray light: ABg / Harvey-Shack BSDFs, importance sampling, error bars and the path table."""

import math
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.integrate import quad
from scipy.stats import kstest

from opticore.api.main import app
from opticore.bsdf import Bsdf, _basis
from opticore.nonseq import NsObject, assemble_scene, build_scene, standard_error, trace_nonsequential
from opticore.nssources import Detector, DetectorRT, Placement
from opticore.system import compile_system

from .test_nonseq import _box, _empty, _step_asset

# ---- BSDF models ------------------------------------------------------------------------


def _tis_reference(bs: Bsdf, b: float) -> float:
    """TIS by an independent formulation: polar coordinates about beta_0, each ray integrated out to
    the unit circle, r_max(phi) = -b cos(phi) + sqrt(1 - b^2 sin^2(phi))."""
    knee = bs.B ** (1.0 / bs.g) if bs.model == "abg" and bs.g > 0 else bs.l

    def ring(phi):
        rmax = -b * math.cos(phi) + math.sqrt(1.0 - (b * math.sin(phi)) ** 2)
        pts = [p for p in (knee, 10 * knee) if p < rmax]
        return quad(lambda r: float(bs.value(r)) * r, 0.0, rmax, points=pts or None, limit=200, epsabs=1e-14, epsrel=1e-12)[0]

    return 2.0 * quad(ring, 0.0, math.pi, limit=200, epsabs=1e-13, epsrel=1e-11)[0]  # symmetric in phi


MODELS = [
    Bsdf("abg", 0.05, B=1e-3, g=2.0),
    Bsdf("abg", 0.2, B=1e-2, g=1.5),
    Bsdf("harvey", 0.01, l=0.01, s=-2.0),
    Bsdf("harvey", 0.1, l=0.05, s=-3.0),
]


@pytest.mark.parametrize("bs", MODELS, ids=lambda b: f"{b.model}-{b.fraction}")
def test_tis_is_normalised_and_matches_an_independent_integral(bs):
    assert bs.tis(0.0) == pytest.approx(bs.fraction, rel=1e-9)  # energy-normalised at normal incidence
    prev = bs.tis(0.0)
    for b in (0.3, 0.7, 0.95):
        t = bs.tis(b)
        assert t == pytest.approx(_tis_reference(bs, b), rel=1e-6)
        assert t <= prev + 1e-12  # the lobe is clipped by the horizon: TIS falls towards grazing
        prev = t


@pytest.mark.parametrize("b", [0.0, 0.6, 0.95])
def test_abg_with_zero_slope_is_lambertian(b):
    """ABg with g = 0 is a constant BSDF: rho = pi A/(B + 1) at every incidence, cosine-weighted directions."""
    bs = Bsdf("abg", 0.3, B=0.5, g=0.0)
    assert bs.amplitude / (bs.B + 1.0) == pytest.approx(0.3 / math.pi, rel=1e-9)
    assert bs.tis(b) == pytest.approx(0.3, rel=1e-9)
    n = np.array([0.0, 0.0, 1.0])
    spec = np.array([b, 0.0, math.sqrt(1 - b * b)])
    rng = np.random.default_rng(5)
    d = np.array([bs.sample(spec, n, rng) for _ in range(6000)])
    assert np.all(d[:, 2] > 0)
    # Lambertian: sin^2(theta) = |beta|^2 is uniform on [0, 1] and the azimuth is uniform
    assert kstest(1.0 - d[:, 2] ** 2, "uniform").pvalue > 1e-3
    assert kstest((np.arctan2(d[:, 1], d[:, 0]) + math.pi) / (2 * math.pi), "uniform").pvalue > 1e-3


def test_sampled_directions_follow_the_bsdf():
    bs = Bsdf("abg", 0.1, B=1e-2, g=1.5)
    n = np.array([0.2, -0.1, 1.0])
    n /= np.linalg.norm(n)
    e1, e2 = _basis(n)
    b0 = 0.5
    spec = b0 * e1 + math.sqrt(1 - b0 * b0) * n
    rng = np.random.default_rng(9)
    N = 40000
    d = np.array([bs.sample(spec, n, rng) for _ in range(N)])
    assert np.allclose(np.linalg.norm(d, axis=1), 1.0, atol=1e-12) and np.all(d @ n > 0)
    x = np.hypot(d @ e1 - b0, d @ e2)
    from opticore.bsdf import theta_in

    for x0 in (0.05, 0.2, 0.6, 1.2):
        pts = [q for q in (0.5, 0.0464) if q < x0]
        p = bs.amplitude * quad(lambda t: float(bs.shape(t)) * t * theta_in(t, b0), 0.0, x0, points=pts or None, limit=200)[0] / bs.tis(b0)
        assert np.mean(x < x0) == pytest.approx(p, abs=4 * math.sqrt(p * (1 - p) / N) + 1e-9)


def test_bsdf_parameter_validation():
    for kw in ({"model": "abg", "fraction": 0.1, "B": 0.0}, {"model": "abg", "fraction": 0.1, "g": -1.0}, {"model": "harvey", "fraction": 0.1, "s": 0.5}, {"model": "harvey", "fraction": 0.1, "l": 0.0}, {"model": "abg", "fraction": 1.5}, {"model": "phong", "fraction": 0.1}):
        with pytest.raises(ValueError):
            Bsdf(**kw)
    with pytest.raises(ValueError):
        Bsdf("gaussian", 0.1, sigma=0.1).value(0.0)


# ---- the trace ---------------------------------------------------------------------------


def _parallel_disc_view_factor(h: float, r: float, a: float) -> float:
    """Differential area to a parallel disc of radius a at height h whose centre is offset by r."""
    return 0.5 * (1.0 - (h * h + r * r - a * a) / math.sqrt((h * h + r * r + a * a) ** 2 - 4.0 * r * r * a * a))


def _plate_scene(bsdf: Bsdf, h=20.0, r=10.0, a=1.0):
    """A narrow beam along +z hits a scattering absorber plate at z = 100; a small one-sided disc
    detector of radius a faces the plate at height h, offset by r from the beam."""
    det = Detector(id="det", name="Small", placement=Placement(position=[r, 0.0, 100.0 - h], rotation_deg=[180.0, 0.0, 0.0]), size_x=a)
    plate = NsObject("plate", _box(-30, -30, 100, 60, 60, 2), "absorber", scatter=bsdf)
    return assemble_scene([plate], None, None, detectors=[DetectorRT.build(det)])


IMP = {"target": {"kind": "detector", "id": "det"}, "rays": 4}


def test_abg_lambertian_limit_matches_the_view_factor_with_importance_sampling():
    """ABg with g = 0 and rho = 1: the detected fraction is the view factor of the small disc; importance
    sampling gets it with a small error from a few hundred source rays."""
    h, r, a = 20.0, 10.0, 1.0
    F = _parallel_disc_view_factor(h, r, a)
    cs = compile_system(_empty(length=200.0, epd=0.2))
    res = trace_nonsequential(cs, _plate_scene(Bsdf("abg", 1.0, B=1.0, g=0.0), h, r, a), rays=400, overfill=1.0, split=False, seed=3, importance=IMP)
    d = res["detectors"][0]
    assert d["power_sigma_w"] > 0 and d["power_sigma_w"] < 0.01 * d["power_w"]
    # the beam's finite width (0.1 mm at 20 mm) changes the view factor by < 1e-4 relative
    assert d["power_w"] == pytest.approx(F, abs=4 * d["power_sigma_w"] + 1e-4 * F)
    e = res["energy"]
    assert e["importance_added"] > 0 and e["importance_dropped"] >= 0
    assert res["settings"]["importance"] == {"target": "Small", "rays": 4}
    # the detector sees only scattered light: one path, S at the plate
    assert [p["path"] for p in d["paths"]] == ["S:plate"]
    assert d["stray_w"] == pytest.approx(d["power_w"], rel=1e-12)


def test_importance_sampling_is_unbiased_against_brute_force_and_converges_with_fewer_rays():
    """Acceptance criterion: a small detector's stray-light power from an ABg scatterer. Brute force with
    40 000 source rays and importance sampling with 2 % of them (800 rays, 4 per scatter event) agree
    within their error bars, and the importance estimate's error is still at most a tenth of the
    brute-force one."""
    bs = Bsdf("abg", 1.0, B=0.1, g=2.0)
    cs = compile_system(_empty(length=200.0, epd=0.2))
    t0 = time.time()
    full = trace_nonsequential(cs, _plate_scene(bs), rays=40000, overfill=1.0, split=False, seed=21)
    brute = full["detectors"][0]
    t_brute = time.time() - t0
    t0 = time.time()
    imp = trace_nonsequential(cs, _plate_scene(bs), rays=800, overfill=1.0, split=False, seed=22, importance=IMP)["detectors"][0]
    t_imp = time.time() - t0
    assert brute["hits"] > 30  # enough hits for a Gaussian error bar
    s = math.hypot(brute["power_sigma_w"], imp["power_sigma_w"])
    assert imp["power_w"] == pytest.approx(brute["power_w"], abs=3 * s)
    assert imp["power_sigma_w"] < 0.1 * brute["power_sigma_w"]
    assert t_imp < t_brute
    # the brute-force error bar is the binomial one (all hits carry the same power)
    N = full["source_rays"]  # the pupil grid's ray count
    p = brute["power_w"] / brute["hits"]  # power per hit
    q = brute["hits"] / N
    assert brute["power_sigma_w"] == pytest.approx(p * math.sqrt(q * (1 - q) * N * N / (N - 1)), rel=1e-9)


def test_importance_target_on_the_legacy_detector_and_on_a_surface_aperture():
    cs = compile_system(_empty(length=200.0, epd=0.2))
    scene = _plate_scene(Bsdf("lambertian", 0.5))
    with pytest.raises(Exception, match="not in the scene"):
        trace_nonsequential(cs, scene, rays=20, overfill=1.0, split=False, importance={"target": {"kind": "detector", "id": "nope"}, "rays": 2})
    with pytest.raises(Exception, match="no image-surface detector"):
        trace_nonsequential(cs, scene, rays=20, overfill=1.0, split=False, importance={"target": {"kind": "legacy"}, "rays": 2})
    # surface target: the stop's clear aperture (z = 0, radius 0.1); nothing is in the way of the scattered light
    r = trace_nonsequential(cs, scene, rays=200, overfill=1.0, split=False, importance={"target": {"kind": "surface", "index": 1}, "rays": 2})
    assert r["settings"]["importance"]["target"] == "Surface 1 aperture"
    assert r["energy"]["importance_added"] > 0


def test_gaussian_scatter_is_not_importance_sampled():
    cs = compile_system(_empty(length=200.0, epd=0.2))
    r = trace_nonsequential(cs, _plate_scene(Bsdf("gaussian", 0.5, sigma=0.2)), rays=100, overfill=1.0, split=False, importance=IMP)
    assert r["energy"]["importance_added"] == 0.0
    assert any("Gaussian scatter of plate" in n for n in r["notes"])


def test_standard_error_of_a_sum_over_source_rays():
    rng = np.random.default_rng(1)
    n = 50
    rid = rng.integers(0, n, 400)
    pw = rng.random(400)
    X = np.bincount(rid, weights=pw, minlength=n)
    assert standard_error(rid, pw, n) == pytest.approx(math.sqrt(n * X.var(ddof=1)), rel=1e-12)
    assert standard_error(rid[:0], pw[:0], n) == 0.0


def test_path_table_ranks_stray_paths_of_a_window_and_a_baffle():
    """A beam crosses a window (Fresnel ghosts) onto the image-surface detector; a diffuse baffle beside
    the beam does not see it. The path table separates the direct light and the window's double
    reflection; the paths add up to the detected power."""
    cs = compile_system(_empty(length=100.0, epd=4.0))
    win = _step_asset(_box(-15, -15, 20, 30, 30, 4), "window", "refractive", "N-BK7")
    scene = build_scene(cs, [win], False)
    r = trace_nonsequential(cs, scene, rays=200, overfill=1.0, split=True, min_power=1e-9)
    det = r["detector"]
    rows = det["paths"]
    assert rows[0]["path"] == "direct" and rows[0]["power"] == pytest.approx(r["energy"]["detected_direct"], rel=1e-12)
    ghost = [p for p in rows if p["path"] == "R:window → R:window"]
    n = cs.library.index("N-BK7", 0.5875618)
    R = ((n - 1) / (n + 1)) ** 2
    assert ghost and ghost[0]["power"] == pytest.approx((1 - R) ** 2 * R * R, rel=1e-9)
    assert sum(p["power"] for p in rows) == pytest.approx(r["energy"]["detected"], rel=1e-9)
    assert det["stray"] == pytest.approx(r["energy"]["detected"] - r["energy"]["detected_direct"], rel=1e-9)
    assert det["power_sigma"] == pytest.approx(0.0, abs=1e-12)  # a deterministic (unscattered) ray grid


def test_cad_scatter_models_through_the_api():
    client = TestClient(app)
    sysd = _empty(length=200.0, epd=0.2).model_dump(mode="json")
    plate = _step_asset(_box(-30, -30, 100, 60, 60, 2), "plate", "absorber")
    plate["optical"]["scatter"] = {"model": "harvey", "fraction": 0.2, "harvey_l": 0.05, "harvey_s": -2.5}
    det = {"id": "d1", "name": "Small", "placement": {"position": [10, 0, 80], "rotation_deg": [180, 0, 0]}, "size_x": 1.0}
    body = {"system": sysd, "cad_assets": [plate], "include_system": False, "rays": 200, "overfill": 1.0, "split": False, "detectors": [det], "importance": {"target": {"kind": "detector", "id": "d1"}, "rays": 4}}
    res = client.post("/api/v1/analysis/nonseq", json=body)
    assert res.status_code == 200, res.text
    j = res.json()
    assert j["objects"][0]["scatter"]["model"] == "harvey" and j["objects"][0]["scatter"]["l"] == 0.05
    assert j["detectors"][0]["power_w"] > 0 and j["detectors"][0]["power_sigma_w"] > 0
    plate["optical"]["scatter"] = {"model": "harvey", "fraction": 0.2, "harvey_s": 1.0}
    assert client.post("/api/v1/analysis/nonseq", json=body).status_code == 422
