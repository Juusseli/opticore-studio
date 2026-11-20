"""General non-sequential sources and detectors (nssources.py, nonseq.trace_nonsequential).

Benchmarks are analytic radiometry and Gaussian-beam second moments:
* point Lambertian source -> coaxial disc of radius a at distance d: F = sin^2(theta), tan(theta) = a/d
* isotropic point source -> disc: F = (1 - cos(theta)) / 2
* cone source (uniform within theta_m) -> disc: F = (1 - cos(theta)) / (1 - cos(theta_m))
* acceptance angle alpha on a large detector next to a Lambertian point: accepted = sin^2(alpha)
* cos^n source: fraction within theta = 1 - cos^(n+1)(theta)
* Gaussian beam ensemble (waist w0, divergence lambda/(pi w0)): 1/e^2 width 2 sigma = w0 sqrt(1 + (z/zR)^2)
Monte Carlo results are compared within 4 binomial standard deviations.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.nonseq import build_scene, trace_nonsequential
from opticore.nssources import Detector, LightSource, _split_counts
from opticore.system import SystemError_, compile_system

from .conftest import make_system

client = TestClient(app)


def empty_system(lam=0.55):
    return make_system([{"thickness": None}, {"thickness": 10.0, "is_stop": True, "semi_diameter": 5.0}, {"thickness": 0.0}], wavelengths=[{"value": lam}])


def run(sources, detectors, system=None, cad=(), include_system=False, **kw):
    cs = compile_system(system or empty_system())
    scene = build_scene(cs, list(cad), include_system, None, (), detectors)
    return trace_nonsequential(cs, scene, sources=sources, split=False, **kw)


def det(z, r, **kw):
    return Detector(placement={"position": [0, 0, z]}, size_x=r, **kw)


def binom(F, N):
    return 4 * math.sqrt(max(F * (1 - F), 1e-12) / N)


@pytest.mark.parametrize(
    "angular,kw,F",
    [
        ("lambertian", {}, lambda th: math.sin(th) ** 2),
        ("isotropic", {}, lambda th: (1 - math.cos(th)) / 2),
        ("cone", {"half_angle_deg": 40.0}, lambda th: (1 - math.cos(th)) / (1 - math.cos(math.radians(40.0)))),
        ("cosine_power", {"cos_power": 3.0}, lambda th: 1 - math.cos(th) ** 4),
    ],
)
def test_point_source_on_a_coaxial_disc_matches_the_radiometric_fraction(angular, kw, F):
    N = 20000
    a, d = 6.0, 10.0
    src = LightSource(angular=angular, rays=N, power_w=2.0, **kw)
    r = run([src], [det(d, a)], seed=3)
    th = math.atan(a / d)
    expect = F(th)
    got = r["detectors"][0]
    assert got["fraction"] == pytest.approx(expect, abs=binom(expect, N))
    assert got["power_w"] == pytest.approx(2.0 * got["fraction"], rel=1e-12)
    assert r["total_power_w"] == pytest.approx(2.0)
    assert r["energy"]["total"] == pytest.approx(1.0, abs=1e-12)


def test_acceptance_angle_rejects_light_outside_the_cone():
    N = 20000
    src = LightSource(angular="lambertian", rays=N)
    alpha = 20.0
    r = run([src], [det(1.0, 1000.0, acceptance_deg=alpha)], seed=5)
    d = r["detectors"][0]
    expect = math.sin(math.radians(alpha)) ** 2
    assert d["fraction"] == pytest.approx(expect, abs=binom(expect, N))
    assert d["rejected_angle_w"] == pytest.approx(1.0 - d["power_w"], abs=1e-9)
    assert r["energy"]["detector_rejected"] == pytest.approx(1.0 - d["fraction"], abs=1e-9)
    assert r["energy"]["total"] == pytest.approx(1.0, abs=1e-12)
    # incidence angles never exceed the acceptance angle
    h = d["angle_hist"]
    assert sum(p for b, p in zip(h["bin_deg"], h["power_w"]) if b >= alpha) == pytest.approx(0.0, abs=1e-12)


def test_gaussian_beam_ensemble_follows_the_gaussian_beam_width():
    lam_um = 1.55
    w0 = 0.0052  # mm (SMF-28-like mode field radius)
    theta = lam_um * 1e-3 / (math.pi * w0)
    zR = w0 / theta
    N = 40000
    src = LightSource(shape="disk", size_x=10 * w0, spatial="gaussian", gaussian_wx=w0, gaussian_wy=w0, angular="gaussian", gaussian_x_deg=math.degrees(math.atan(theta)), gaussian_y_deg=math.degrees(math.atan(theta)), rays=N, wavelengths=[{"value": lam_um}])
    zs = [0.0, 0.5 * zR, 2.0 * zR, 20.0 * zR]
    zs = [z + 1e-5 for z in zs]  # in front of the source plane (self-intersection guard 1e-7 mm)
    dets = [det(z, 5.0, mode="monitor", name=f"z{k}") for k, z in enumerate(zs)]
    r = run([src], dets, seed=7)
    for z, d in zip(zs, r["detectors"]):
        w = w0 * math.sqrt(1 + (z / zR) ** 2)
        wx, wy = d["width_2sigma_mm"]
        assert wx == pytest.approx(w, rel=0.025) and wy == pytest.approx(w, rel=0.025)
        assert d["fraction"] == pytest.approx(1.0, abs=1e-12)  # monitors see every ray
    assert r["energy"]["escaped"] == pytest.approx(1.0, abs=1e-9)  # monitors do not stop rays


def test_gaussian_beam_through_a_lens_matches_the_abcd_waist():
    """A Gaussian waist at the object plane imaged 2f-2f by a slow lens: at the paraxial image plane the
    ABCD law gives w' = sqrt(A^2 w0^2 + B^2 theta^2) with A = m, B = 0, i.e. w' = |m| w0, and the ray
    ensemble's second moments propagate with the same ABCD matrix (aberrations negligible at F/40)."""
    lam_um = 1.0
    w0 = 0.050
    theta = lam_um * 1e-3 / (math.pi * w0)  # 0.0318 rad
    f_obj = 60.0
    sysm = make_system(
        [
            {"thickness": 120.0},  # object 2f before the lens: image 2f behind, magnification -1
            {"radius": 62.0, "thickness": 4.0, "material": "N-BK7", "is_stop": True, "semi_diameter": 10.0},
            {"radius": -62.0, "thickness": 0.0},
            {"thickness": 0.0},
        ],
        wavelengths=[{"value": lam_um}],
    )
    from opticore.paraxial import paraxial_data

    cs = compile_system(sysm)
    pd = paraxial_data(cs)
    img = pd.paraxial_image_distance
    lens_z = 4.0
    # waist at the object plane (-120 mm); detector at the paraxial image plane of the second surface
    N = 30000
    src = LightSource(placement={"position": [0, 0, -120.0]}, shape="disk", size_x=10 * w0, spatial="gaussian", gaussian_wx=w0, gaussian_wy=w0, angular="gaussian", gaussian_x_deg=math.degrees(math.atan(theta)), gaussian_y_deg=math.degrees(math.atan(theta)), rays=N, wavelengths=[{"value": lam_um}])
    r = run([src], [det(lens_z + img, 3.0, mode="monitor")], system=sysm, include_system=True, seed=9)
    d = r["detectors"][0]
    m = abs(pd.paraxial_magnification)
    # image of a waist at the object plane through a slow lens: w' ~ |m| w0 (zR >> defocus at both planes)
    w_expect = m * w0
    assert f_obj  # documentation of the set-up
    assert d["width_2sigma_mm"][0] == pytest.approx(w_expect, rel=0.03)
    assert d["width_2sigma_mm"][1] == pytest.approx(w_expect, rel=0.03)


def test_detector_modes_sides_and_spectrum():
    N = 6000
    src = LightSource(angular="collimated", shape="disk", size_x=1.0, rays=N, power_w=1.0, wavelengths=[{"value": 0.5, "weight": 1.0}, {"value": 0.6, "weight": 3.0}])
    assert list(_split_counts(N, np.array([1.0, 3.0]))) == [1500, 4500]
    # a monitor in front of an absorbing detector: both see all the light
    r = run([src], [det(5.0, 2.0, mode="monitor", name="mon"), det(10.0, 2.0, name="end")], seed=1)
    mon, end = r["detectors"]
    assert mon["fraction"] == pytest.approx(1.0) and end["fraction"] == pytest.approx(1.0)
    assert end["by_wavelength_w"] == pytest.approx({"0.5": 0.25, "0.6": 0.75})
    assert r["energy"]["detected"] == pytest.approx(1.0) and r["energy"]["total"] == pytest.approx(1.0)
    # a detector facing the other way blocks the light from its back (one-sided)
    flipped = Detector(placement={"position": [0, 0, 5.0], "rotation_deg": [180.0, 0, 0]}, size_x=2.0)
    r = run([src], [flipped, det(10.0, 2.0, name="end")], seed=1)
    assert r["detectors"][0]["blocked_back_w"] == pytest.approx(1.0) and r["detectors"][1]["power_w"] == 0.0
    flipped2 = flipped.model_copy(update={"two_sided": True})
    r = run([src], [flipped2], seed=1)
    assert r["detectors"][0]["fraction"] == pytest.approx(1.0)


def test_rectangle_source_and_detector_and_irradiance():
    N = 20000
    src = LightSource(angular="collimated", shape="rectangle", size_x=4.0, size_y=2.0, rays=N, power_w=8.0)
    d = Detector(placement={"position": [0, 0, 3.0]}, shape="rectangle", size_x=2.0, size_y=2.0, pixels=20)
    r = run([src], [d], seed=2)
    res = r["detectors"][0]
    assert res["fraction"] == pytest.approx(0.5, abs=binom(0.5, N))
    # uniform irradiance: 8 W / 8 mm^2 = 1 W/mm^2
    irr = np.array(res["irradiance"])
    assert irr.mean() == pytest.approx(1.0, rel=0.02)


def test_volume_source_and_placement_rotation():
    N = 20000
    # sphere volume source with isotropic emission seen from far away: like a point (F ~ (1 - cos)/2)
    src = LightSource(shape="sphere", size_x=0.5, angular="isotropic", rays=N, placement={"position": [10.0, 0, 0]})
    d = Detector(placement={"position": [10.0, 0, 100.0]}, size_x=30.0)
    r = run([src], [d], seed=4)
    th = math.atan(30.0 / 100.0)
    assert r["detectors"][0]["fraction"] == pytest.approx((1 - math.cos(th)) / 2, abs=binom(0.02, N) + 2e-3)
    # rotating a collimated source by 90 deg about y sends it along +x: hits a detector rotated the same way
    src2 = LightSource(angular="collimated", rays=100, placement={"position": [0, 0, 0], "rotation_deg": [0, 90.0, 0]})
    d2 = Detector(placement={"position": [5.0, 0, 0], "rotation_deg": [0, 90.0, 0]}, size_x=0.1)
    assert run([src2], [d2])["detectors"][0]["fraction"] == pytest.approx(1.0)


def test_table_source_reproduces_a_lambertian_law():
    N = 20000
    tab = [[a, math.cos(math.radians(a))] for a in range(0, 91, 2)]
    src = LightSource(angular="table", table=tab, rays=N)
    r = run([src], [det(10.0, 6.0)], seed=6)
    expect = math.sin(math.atan(0.6)) ** 2
    assert r["detectors"][0]["fraction"] == pytest.approx(expect, abs=binom(expect, N) + 2e-3)


def test_source_validation_and_seed_reproducibility():
    with pytest.raises(ValueError, match="table"):
        LightSource(angular="table", table=[[0, 1]])
    with pytest.raises(ValueError, match="increase"):
        LightSource(angular="table", table=[[10, 1], [5, 1]])
    src = LightSource(angular="lambertian", rays=500)
    a = run([src], [det(10.0, 6.0)], seed=1)["detectors"][0]["power_w"]
    b = run([src], [det(10.0, 6.0)], seed=1)["detectors"][0]["power_w"]
    c = run([src], [det(10.0, 6.0)], seed=2)["detectors"][0]["power_w"]
    assert a == b and a != c


def test_system_field_source_and_lens_with_a_sensor():
    """A system_field source through a real lens onto a small sensor at the focus: nearly all power
    except the Fresnel losses (bare N-BK7, ~4 % per surface) reaches it."""
    from opticore.samples import get_sample

    s = get_sample("singlet").system
    cs = compile_system(s)
    img_z = cs.frames[-1].origin[2]
    src = LightSource(kind="system_field", rays=600, overfill=1.0)
    sensor = Detector(placement={"position": [0, 0, float(img_z)]}, size_x=0.5)
    scene = build_scene(cs, [], True, None, (), [sensor])
    r = trace_nonsequential(cs, scene, sources=[src], split=False)
    f = r["detectors"][0]["fraction"]
    assert 0.88 < f < 0.94
    assert r["energy"]["total"] == pytest.approx(1.0, abs=1e-9)


def test_api_sources_and_detectors_and_project_round_trip():
    sysd = empty_system().model_dump()
    body = {"system": sysd, "include_system": False, "sources": [{"angular": "lambertian", "rays": 4000}], "detectors": [{"placement": {"position": [0, 0, 10]}, "size_x": 6.0}]}
    r = client.post("/api/v1/analysis/nonseq", json=body)
    assert r.status_code == 200, r.text
    d = r.json()["detectors"][0]
    assert d["fraction"] == pytest.approx(math.sin(math.atan(0.6)) ** 2, abs=0.03)
    # disabled sources fall back to the system field
    body["sources"][0]["enabled"] = False
    body["include_system"] = True
    r = client.post("/api/v1/analysis/nonseq", json=body)
    assert r.status_code == 200 and r.json()["sources"][0]["kind"] == "system_field"
    # projects store sources and detectors
    from opticore.project import dump_project, load_project
    from opticore.samples import get_sample

    p = get_sample("singlet")
    raw = dump_project(p)
    raw["sources"] = [{"name": "LED", "shape": "disk", "size_x": 0.2, "angular": "lambertian"}]
    raw["detectors"] = [{"name": "PD", "shape": "rectangle", "size_x": 1.0, "size_y": 1.0}]
    raw["checksum"] = None
    proj, _ = load_project(raw)
    assert proj.sources[0].name == "LED" and proj.detectors[0].shape == "rectangle"
    with pytest.raises(SystemError_):
        run([LightSource(kind="system_field", field=5)], [det(10, 1)])


def test_gaussian_relay_through_coated_lenses():
    """1:1 relay of two AR-coated plano-convex N-BK7 lenses (tests/beam_systems.py): paraxially exact
    (m = -1, image on the detector plane); the collimated beam between the lenses has the 1/e^2 radius
    f tan(theta); the detector receives the power left after the four AR-coated faces, (1 - R)^4."""
    from opticore.materials import MaterialLibrary
    from opticore.paraxial import paraxial_data
    from opticore.thinfilm import get_coating, unpolarized_R

    from .beam_systems import RELAY_F, RELAY_LAM, relay

    p = relay()
    cs = compile_system(p.system)
    pd = paraxial_data(cs)
    assert pd.paraxial_magnification == pytest.approx(-1.0, abs=1e-4)
    assert pd.image_surface_defocus == pytest.approx(0.0, abs=1e-3)
    scene = build_scene(cs, [], True, None, (), p.detectors)
    r = trace_nonsequential(cs, scene, sources=p.sources, split=True, seed=1)
    det, mon = r["detectors"]
    theta = math.radians(p.sources[0].gaussian_x_deg)
    assert mon["width_2sigma_mm"][0] == pytest.approx(RELAY_F * math.tan(theta), rel=0.05)
    n = MaterialLibrary().index("N-BK7", RELAY_LAM)
    coat = get_coating("AR_1064", cs.coating_library)
    R = float(unpolarized_R(1.0, n, coat.layers_at(RELAY_LAM), RELAY_LAM, np.array([1.0]))[0])
    assert 0.005 < R < 0.02
    assert det["fraction"] == pytest.approx((1 - R) ** 4, abs=0.02)
    assert det["width_2sigma_mm"][0] < 0.1  # the image of the 4 um waist, well inside the detector


def test_thick_lens_beam_shorter_than_its_conjugates():
    """N-SF11 biconvex lens (R = +-2.5 mm, 2.8 mm thick), source and detector 9 mm apart: the EFL and the
    back focal distance equal the thick-lens formulas; the shortest real conjugate (1:1, Newton
    x = x' = f) needs 2 (f + BFL) of air, more than the 6.2 mm available, so the beam converges past
    the detector; it fits the lens and nearly all of it reaches the detector."""
    from opticore.materials import MaterialLibrary
    from opticore.paraxial import paraxial_data

    from .beam_systems import THICK_LAM, THICK_LENS_LENGTH, THICK_R, THICK_T, thick_lens

    p = thick_lens()
    s = p.system.surfaces
    assert s[0].thickness + s[1].thickness + s[2].thickness == pytest.approx(THICK_LENS_LENGTH, abs=1e-9)
    cs = compile_system(p.system)
    pd = paraxial_data(cs)
    n = MaterialLibrary().index("N-SF11", THICK_LAM)
    R, t = THICK_R, THICK_T
    phi = (n - 1) * 2 / R - (n - 1) ** 2 * t / (n * R * R)  # c1 = 1/R, c2 = -1/R
    assert pd.efl == pytest.approx(1 / phi, rel=1e-9)
    assert pd.bfl == pytest.approx((1 - (n - 1) * t / (n * R)) / phi, rel=1e-9)
    assert 2 * (pd.efl + pd.bfl) > THICK_LENS_LENGTH - t
    assert pd.image_surface_defocus < 0  # the paraxial image lies behind the detector
    scene = build_scene(cs, [], True, None, (), p.detectors)
    r = trace_nonsequential(cs, scene, sources=p.sources, split=True, seed=1)
    det, mon = r["detectors"]
    assert det["fraction"] > 0.99
    assert mon["fraction"] > 0.999
