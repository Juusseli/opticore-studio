"""Relative illumination, sensor model and image simulation."""

import base64
import math

import numpy as np
import pytest

from opticore.analysis.aberrations import field_curvature_distortion
from opticore.analysis.diffraction import mtf
from opticore.analysis.imaging import _distortion_table, pixel_aperture, pixel_mtf, relative_illumination, sensor_mtf_terms, sensor_signal, simulate_image
from opticore.model import OpticalSystem, Sensor
from opticore.paraxial import compute_pupil
from opticore.raytrace import gauss_pupil, launch, trace
from opticore.samples import achromat, cooke_triplet
from opticore.system import compile_system

from .conftest import make_system


def _ideal(epd, field_deg=40.0):
    return make_system(
        [{"id": "obj", "thickness": None}, {"id": "L", "type": "ideal", "focal_length": 100.0, "thickness": 100.0, "is_stop": True}, {"id": "img"}],
        wavelengths=[{"value": 0.55}],
        fields=[{"y": 0.0}, {"y": field_deg}],
        aperture={"type": "epd", "value": epd},
    )


def _with_sensor(system, **kw):
    d = system.model_dump()
    d["sensor"] = {"pixel_pitch_um": 3.45, "fill_factor": 0.8, "width_px": 1024, "height_px": 768, **kw}
    return OpticalSystem.model_validate(d)


# ----------------------------------------------------------------------------- relative illumination
@pytest.mark.parametrize("epd", [2.0, 20.0])
def test_cos4_law_of_an_ideal_lens(epd):
    """Benchmark: an ideal lens with the stop at the lens images a flat field with relative illumination
    cos^4(theta), at any aperture (the energy form is exact for it)."""
    r = relative_illumination(compile_system(_ideal(epd)), points=5, transmission=False)
    th = np.radians(r["field_values"])
    assert r["relative_illumination"] == pytest.approx(np.cos(th) ** 4, abs=1e-7)
    assert r["unvignetted_fraction"] == pytest.approx([1.0] * 5)


def test_doublet_relative_illumination_against_flat_field_ray_binning():
    """Acceptance benchmark: the doublet's relative illumination equals an independent flat-field estimate
    that bins the power of rays from a dense set of object directions into image annuli (aberration blur
    included), within 1e-3."""
    s = achromat(True).system
    cs = compile_system(s)
    ri = relative_illumination(cs, points=3, transmission=False)
    pupil = compute_pupil(cs)
    px, py, pw = gauss_pupil(6)

    def annulus_irradiance(theta_c, half_width_deg=0.15):
        # power ~ sum over object angles theta (weight sin theta d theta) of pupil-quadrature rays landing in
        # the image annulus of the chief rays of theta_c +- half_width (rotational symmetry: one meridian)
        ths = np.linspace(theta_c - 2 * half_width_deg, theta_c + 2 * half_width_deg, 801)
        ths = ths[ths >= 0]
        dth = ths[1] - ths[0]

        def chief(t):
            P, D, o = launch(cs, 1, (0.0, t), np.array([0.0]), np.array([0.0]), pupil, object_units=True)
            return abs(trace(cs, 1, P, D, o).image_xy()[0, 1])

        r1, r2 = chief(max(theta_c - half_width_deg, 0.0)), chief(theta_c + half_width_deg)
        power = 0.0
        for t in ths:
            P, D, o = launch(cs, 1, (0.0, float(t)), px, py, pupil, object_units=True)
            res = trace(cs, 1, P, D, o)
            rr = np.hypot(*res.image_xy().T)
            inside = res.ok & (rr >= r1) & (rr < r2)
            area_perp = math.pi * pupil.r_ep**2 * math.cos(math.radians(t))
            power += area_perp * np.sum(pw[inside]) * math.sin(math.radians(t)) * math.radians(dth)
        return power / (math.pi * (r2 * r2 - r1 * r1))

    e_mid = annulus_irradiance(1.0)
    e_edge = annulus_irradiance(2.0 - 0.15)
    th_edge = 2.0 - 0.15
    ri_edge = float(np.interp(th_edge, ri["field_values"], ri["relative_illumination"]))
    ri_mid = float(np.interp(1.0, ri["field_values"], ri["relative_illumination"]))
    assert e_edge / e_mid == pytest.approx(ri_edge / ri_mid, abs=1e-3)


def test_vignetting_lowers_the_relative_illumination():
    d = cooke_triplet(True).system.model_dump()
    d["surfaces"][1].update(semi_diameter_mode="fixed", semi_diameter=8.0)  # clip the front lens
    vig = relative_illumination(compile_system(OpticalSystem.model_validate(d)), points=5, transmission=False)
    free = relative_illumination(compile_system(cooke_triplet(True).system), points=5, transmission=False)
    assert vig["unvignetted_fraction"][-1] < 0.95 and free["unvignetted_fraction"][-1] == pytest.approx(1.0)
    assert vig["relative_illumination"][-1] < free["relative_illumination"][-1]


# ----------------------------------------------------------------------------- sensor
def test_pixel_mtf_is_the_analytic_sinc_and_the_aperture_filter_reproduces_it():
    s = Sensor(pixel_pitch_um=5.0, fill_factor=0.64)
    w = 5e-3 * 0.8
    nu = np.array([0.0, 25.0, 50.0, 100.0, 125.0])
    expected = np.where(nu > 0, np.abs(np.sin(np.pi * nu * w) / np.where(nu > 0, np.pi * nu * w, 1.0)), 1.0)
    assert pixel_mtf(nu, s) == pytest.approx(expected, abs=1e-15)
    # a sinusoid of an integer number of periods on the grid: the box filter scales its modulation by sinc
    dx = 0.25e-3
    n = 400
    x = np.arange(n) * dx
    for cycles in (5, 12, 33):
        nu_c = cycles / (n * dx)
        img = np.tile(1.0 + 0.5 * np.cos(2 * np.pi * nu_c * x), (8, 1))
        out = pixel_aperture(img, dx, w) / (w / dx) ** 2
        mod = (out.max() - out.min()) / (out.max() + out.min())
        assert mod == pytest.approx(0.5 * abs(np.sinc(nu_c * w)), rel=1e-9)


def test_system_mtf_is_lens_times_pixel_and_nyquist():
    s = _with_sensor(achromat(True).system)
    cs = compile_system(s)
    m = mtf(cs, None, 150.0, 16)
    t = sensor_mtf_terms(m, s.sensor)
    assert t["nyquist_cyc_per_mm"] == pytest.approx(1 / (2 * 3.45e-3))
    pm = pixel_mtf(m["frequency_cyc_per_mm"], s.sensor)
    assert t["fields"][1]["tangential"] == pytest.approx(np.array(m["fields"][1]["tangential"]) * pm, abs=1e-15)


def test_shot_and_read_noise_statistics():
    s = Sensor(full_well_e=20000.0, read_noise_e=8.0, bit_depth=16)
    e = np.full((400, 400), 5000.0)
    dn = sensor_signal(e, s, True, 3)
    elec = dn / (2**16 - 1) * 20000.0
    assert elec.mean() == pytest.approx(5000.0, abs=1.0)
    assert elec.var() == pytest.approx(5000.0 + 64.0 + (20000.0 / 65535) ** 2 / 12, rel=0.02)
    assert np.array_equal(sensor_signal(e, s, False), np.round(e / 20000.0 * 65535))


# ----------------------------------------------------------------------------- simulation
def test_distortion_map_against_the_distortion_analysis():
    """Benchmark: the image simulation's chief-ray map (real height / first-order height - 1) equals the
    distortion analysis of the triplet."""
    cs = compile_system(cooke_triplet(True).system)
    tab = _distortion_table(cs, 1, 1e9, compute_pupil(cs))
    fc = field_curvature_distortion(cs, samples=9)
    prim = next(p for p in fc["per_wavelength"] if p["wavelength"] == 1)
    vals = np.array(fc["field_values"])
    ours = np.interp(vals[1:], tab["v"], tab["r_real"] / np.where(tab["r_ideal"] > 0, tab["r_ideal"], 1)) - 1
    assert ours * 100 == pytest.approx(np.array(prim["distortion_percent"][1:]), abs=1e-4)


def test_doublet_image_simulation_conserves_energy_and_returns_images():
    """Acceptance criterion: a test pattern imaged through the doublet onto a defined sensor; the blur conserves the
    signal exactly and the images decode to the sensor size."""
    s = _with_sensor(achromat(True).system)
    r = simulate_image(s, (), "siemens", crop_px=96, noise=False, grid=3)
    assert r["energy"]["blurred_total"] == pytest.approx(r["energy"]["in_scene_x_ri"], rel=1e-12)
    for k in ("ideal", "optics", "sensor"):
        a = np.frombuffer(base64.b64decode(r["images"][k]), dtype="<u2")
        assert a.size == 96 * 96
    assert r["sensor_defined"] and r["nyquist_cyc_per_mm"] == pytest.approx(1 / (2 * 3.45e-3))
    # the brightest noiseless pixel sits at the exposure level
    opt = np.frombuffer(base64.b64decode(r["images"]["optics"]), dtype="<u2")
    assert opt.max() == pytest.approx(0.7 * 65535, abs=1)
    with pytest.raises(ValueError):
        simulate_image(s, (), "nope")


def test_image_simulation_api():
    from fastapi.testclient import TestClient

    from opticore.api.main import app

    c = TestClient(app)
    s = _with_sensor(achromat(True).system)
    r = c.post("/api/v1/analysis/image-simulation", json={"system": s.model_dump(mode="json"), "scene": "grid", "crop_px": 48, "grid": 2})
    assert r.status_code == 200 and r.json()["width_px"] == 48
    ri = c.post("/api/v1/analysis/relative-illumination", json={"system": s.model_dump(mode="json"), "points": 3})
    assert ri.status_code == 200 and len(ri.json()["relative_illumination"]) == 3
    m = c.post("/api/v1/analysis/mtf", json={"system": s.model_dump(mode="json"), "samples": 8})
    assert "sensor" in m.json()
