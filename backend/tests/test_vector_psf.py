"""Vector (Debye–Wolf) PSF: Richards–Wolf integrals, published high-NA spot size, low-NA limits."""

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.integrate import quad
from scipy.special import jv

from opticore.analysis.diffraction import psf
from opticore.analysis.vectorpsf import debye_focus, vector_psf
from opticore.api.main import app
from opticore.raytrace import gauss_pupil
from opticore.samples import get_sample
from opticore.system import compile_system

from .conftest import make_system

LAM = 0.55
LAM_MM = LAM * 1e-3
K = 2 * math.pi / LAM_MM


def rw_integrals(na: float, r: float, apod) -> tuple[float, float, float]:
    """Richards–Wolf I0, I1, I2 at radius r in the focal plane for the apodisation apod(theta) (1D quadrature)."""
    al = math.asin(na)

    def I(n, f):
        return quad(lambda t: apod(t) * f(t) * jv(n, K * r * math.sin(t)), 0.0, al, limit=200, epsabs=1e-13)[0]

    return (
        I(0, lambda t: math.sin(t) * (1 + math.cos(t))),
        I(1, lambda t: math.sin(t) ** 2),
        I(2, lambda t: math.sin(t) * (1 - math.cos(t))),
    )


def aplanatic_pupil(na: float, rings: int = 48):
    """Plane waves of an aplanatic lens (sin theta = NA rho) for x-polarised uniform illumination: the
    Richards–Wolf field on the reference sphere, with the quadrature weight and sqrt(|J| / s_z)."""
    px, py, w = gauss_pupil(rings, 2 * rings + 8)
    rho, ph = np.hypot(px, py), np.arctan2(py, px)
    st = na * rho
    ct = np.sqrt(1 - st**2)
    s = np.stack([-st * np.cos(ph), -st * np.sin(ph), ct], axis=1)
    E = np.stack([ct * np.cos(ph) ** 2 + np.sin(ph) ** 2, (ct - 1) * np.cos(ph) * np.sin(ph), st * np.cos(ph)], axis=1)
    return s, ((w * na / np.sqrt(ct))[:, None] * E).astype(complex)


def test_debye_sum_reproduces_the_richards_wolf_integrals_at_na_09():
    na = 0.9
    s, a = aplanatic_pupil(na)
    xs = np.linspace(0.0, 1.2 * LAM_MM / na, 25)
    Ex = debye_focus(s, a, K, xs, np.array([0.0]))[:, 0, :]  # along x (phi = 0)
    Ey = debye_focus(s, a, K, np.array([0.0]), xs)[:, :, 0]  # along y (phi = 90°)
    apod = lambda t: math.sqrt(math.cos(t))  # noqa: E731
    I00 = rw_integrals(na, 0.0, apod)[0] ** 2
    c0 = float((np.abs(Ex[:, 0]) ** 2).sum())
    for i, r in enumerate(xs):
        I0, I1, I2 = rw_integrals(na, r, apod)
        # phi = 0: |Ex|^2 = (I0 + I2)^2, Ey = 0, |Ez|^2 = 4 I1^2; phi = 90°: |Ex|^2 = (I0 - I2)^2, Ey = Ez = 0
        assert np.allclose(np.abs(Ex[:, i]) ** 2 / c0, np.array([(I0 + I2) ** 2, 0.0, 4 * I1**2]) / I00, atol=1e-10)
        assert np.allclose(np.abs(Ey[:, i]) ** 2 / c0, np.array([(I0 - I2) ** 2, 0.0, 0.0]) / I00, atol=1e-10)


def test_na_09_focal_spot_area_matches_the_published_value():
    """Uniform, linearly polarised illumination of an aplanatic NA 0.9 lens: the area inside the
    half-maximum contour of |E|^2 is 0.31 lambda^2 (Dorn, Quabis, Leuchs, PRL 91, 233901, 2003), against
    0.26 lambda^2 for the scalar Airy spot, because the longitudinal field widens it along the polarisation."""
    na = 0.9
    s, a = aplanatic_pupil(na)
    xf = np.linspace(-0.8 * LAM_MM / na, 0.8 * LAM_MM / na, 321)
    E = debye_focus(s, a, K, xf, xf)
    I = (np.abs(E) ** 2).sum(axis=0)
    area = (I >= 0.5 * I.max()).sum() * (xf[1] - xf[0]) ** 2 / LAM_MM**2
    assert area == pytest.approx(0.31, abs=0.006)
    airy = math.pi / 4 * (0.514497 / na) ** 2
    assert airy == pytest.approx(0.256, abs=1e-3)
    c = len(xf) // 2
    fx = np.interp(0.5, I[c, c:][::-1] / I.max(), xf[c:][::-1])
    fy = np.interp(0.5, I[c:, c][::-1] / I.max(), xf[c:][::-1])
    assert 2 * fx > 2 * fy  # wider along the polarisation (x)


def _paraboloid(na: float = 0.9, f: float = 10.0):
    h = 2 * f * math.tan(math.asin(na) / 2)  # h = 2 f tan(theta / 2)
    return make_system(
        [{"thickness": None}, {"radius": -2 * f, "conic": -1.0, "material": "MIRROR", "thickness": -f, "is_stop": True, "semi_diameter": 2 * h}, {"thickness": 0.0}],
        wavelengths=[{"value": LAM}],
        fields=[{"y": 0.0}],
        aperture={"type": "epd", "value": 2 * h},
    )


def test_paraboloid_mirror_focus_through_the_whole_chain_matches_richards_wolf():
    """A paraboloid focusing collimated x-polarised light at NA 0.9, traced as a real system (mirror
    polarisation, pupil-to-direction Jacobian, optical paths): its focal field equals the Richards–Wolf
    integrals with the paraboloid's apodisation 2f / (1 + cos theta) (energy conservation for h = 2f tan(theta/2))."""
    cs = compile_system(_paraboloid())
    r = vector_psf(cs, input_state="x", rings=48, grid=41, half_width_um=0.6, section=False)
    assert r["na"] == pytest.approx(0.9, rel=1e-9)
    assert r["strehl"] == pytest.approx(1.0, abs=1e-9)
    apod = lambda t: 1.0 / (1.0 + math.cos(t))  # noqa: E731
    I00 = rw_integrals(0.9, 0.0, apod)[0] ** 2
    for prof, sign in (("profile_x", 1), ("profile_y", -1)):
        p = r[prof]
        for i, x in enumerate(p["x_um"]):
            I0, I1, I2 = rw_integrals(0.9, abs(x) * 1e-3, apod)
            assert p["x"][i] == pytest.approx((I0 + sign * I2) ** 2 / I00, abs=1e-8)
            assert p["z"][i] == pytest.approx((4 * I1**2 if sign > 0 else 0.0) / I00, abs=1e-8)


def test_radial_and_azimuthal_polarisation_at_high_na():
    cs = compile_system(_paraboloid())
    rad = vector_psf(cs, input_state="radial", rings=40, grid=41, half_width_um=0.6, section=False)
    azi = vector_psf(cs, input_state="azimuthal", rings=40, grid=41, half_width_um=0.6, section=False)
    c = 20
    # radial: a longitudinal field peaks on the axis; azimuthal: a dark centre (doughnut), no Ez anywhere
    assert rad["components"]["z"][c][c] == pytest.approx(1.0, abs=1e-6)
    assert rad["energy_fraction"]["z"] > 0.4
    assert azi["intensity"][c][c] < 1e-10
    assert azi["energy_fraction"]["z"] < 1e-12


def test_low_na_limit_is_the_airy_pattern():
    """An ideal lens at NA 0.01: FWHM 0.5145 lambda / NA in x and y, a negligible longitudinal field and a
    Strehl ratio of 1."""
    sysd = make_system(
        [{"thickness": None}, {"type": "ideal", "focal_length": 100.0, "thickness": 100.0, "is_stop": True, "semi_diameter": 60.0}, {"thickness": 0.0}],
        wavelengths=[{"value": LAM}],
        fields=[{"y": 0.0}],
        aperture={"type": "epd", "value": 2.0},
    )
    r = vector_psf(compile_system(sysd), input_state="x", rings=40, grid=81, section=True)
    na = r["na"]
    assert na == pytest.approx(1 / math.sqrt(1 + 100**2), rel=1e-9)
    airy = 0.514497 * LAM / na
    assert r["fwhm_x_um"] == pytest.approx(airy, rel=2e-4)
    assert r["fwhm_y_um"] == pytest.approx(airy, rel=2e-4)
    assert r["energy_fraction"]["z"] < 1e-4
    assert r["strehl"] == pytest.approx(1.0, abs=1e-9)
    assert len(r["section"]["intensity"]) == 81


@pytest.mark.parametrize("sample", ["singlet", "achromat"])
def test_aberrated_low_na_systems_match_the_scalar_strehl_ratio(sample):
    cs = compile_system(get_sample(sample).system)
    v = vector_psf(cs, rings=48, grid=81, section=False)
    p = psf(cs, 0, grid=128, pad=4)
    assert v["strehl"] == pytest.approx(p["strehl"], abs=0.005)


def test_vector_psf_api():
    client = TestClient(app)
    body = {"system": get_sample("achromat").system.model_dump(mode="json"), "input": "rcp", "rings": 24, "grid": 41}
    r = client.post("/api/v1/analysis/vector-psf", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert len(j["intensity"]) == 41 and j["fwhm_x_um"] > 0 and j["half_max_area_um2"] > 0
    assert abs(sum(j["energy_fraction"].values()) - 1.0) < 1e-12
    assert client.post("/api/v1/analysis/vector-psf", json={**body, "input": "elliptic"}).status_code == 422
