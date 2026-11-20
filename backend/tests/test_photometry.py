"""Photometry and colorimetry (opticore/photometry).

References:
* the CIE datasets themselves: their MD5 sums from the CIE's metadata;
* the definition of the candela: 683 lm/W at 540 THz (555.016 nm in standard air) for photopic and scotopic vision
  with K_m = 683.002 and K'_m = 1700.13 lm/W (CIE 018:2019);
* CIE standard illuminant A from its defining formula: chromaticity (0.44757, 0.40745) (CIE 015) and the Planckian
  radiator at 2848 K x 1.4388/1.435 (its CCT, exactly on the locus);
* D65: chromaticity (0.31271, 0.32902) (CIE 015), and the CCT of that chromaticity, about 6504 K;
* the equal-energy spectrum at x = y = 1/3 (the normalisation of the colour-matching functions);
* the sRGB matrix of IEC 61966-2-1 and its white D65 -> (1, 1, 1).
"""

import hashlib

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore import photometry as ph
from opticore.api.main import app

client = TestClient(app)
LAM = np.arange(360, 831)


def test_cie_tables_are_the_published_datasets():
    for name, (fname, md5) in ph.FILES.items():
        assert hashlib.md5((ph.DATA / fname).read_bytes()).hexdigest() == md5, fname
    assert ph.table("cmf").shape == (471, 4) and ph.table("cmf")[0, 0] == 360 and ph.table("cmf")[-1, 0] == 830
    assert ph.table("d65").shape == (531, 2) and ph.table("scotopic").shape == (401, 2)


def test_maximum_luminous_efficacies_reproduce_the_candela():
    assert ph.KM * float(ph.v_photopic(555.016)) == pytest.approx(683.0, abs=2e-3)
    assert ph.KM_SCOTOPIC * float(ph.v_scotopic(555.016)) == pytest.approx(683.0, abs=0.05)
    assert float(ph.v_photopic(555.0)) == 1.0 and float(ph.v_scotopic(507.0)) == 1.0
    one = ph.line_spectrum([0.555], [1.0])
    assert one["luminous_flux_lm"] == pytest.approx(683.002, abs=1e-9) and one["luminous_efficacy_lm_per_w"] == pytest.approx(683.002, abs=1e-9)
    assert ph.line_spectrum([0.507], [2.0])["scotopic_flux_lm"] == pytest.approx(2 * 1700.13, abs=1e-6)
    ir = ph.line_spectrum([1.55], [1.0])
    assert ir["luminous_flux_lm"] == 0.0 and ir["chromaticity"] is None and ir["notes"]


def test_illuminant_a_and_d65():
    assert float(ph.illuminant_a(560.0)) == pytest.approx(100.0, abs=1e-12)
    A = ph.tabulated(LAM, ph.illuminant_a(LAM))
    assert A["chromaticity"]["x"] == pytest.approx(0.44757, abs=2e-5) and A["chromaticity"]["y"] == pytest.approx(0.40745, abs=2e-5)
    assert A["cct_k"] == pytest.approx(2848.0 * 1.4388 / 1.435, abs=1e-4) and abs(A["duv"]) < 1e-9
    assert float(ph.d65(560.0)) == pytest.approx(100.0, abs=1e-9)
    D = ph.tabulated(LAM, ph.d65(LAM))
    assert D["chromaticity"]["x"] == pytest.approx(0.31271, abs=2e-5) and D["chromaticity"]["y"] == pytest.approx(0.32902, abs=2e-5)
    published = ph.cct(np.array([0.31271 / 0.32902, 1.0, (1 - 0.31271 - 0.32902) / 0.32902]))
    assert published["cct_k"] == pytest.approx(6504.0, abs=1.0) and published["duv"] == pytest.approx(0.0032, abs=2e-4)
    E = ph.tabulated(LAM, np.ones(len(LAM)))
    assert E["chromaticity"]["x"] == pytest.approx(1 / 3, abs=5e-5) and E["chromaticity"]["y"] == pytest.approx(1 / 3, abs=5e-5)


@pytest.mark.parametrize("T", [1500.0, 2856.0, 4000.0, 6500.0, 10000.0, 25000.0])
def test_cct_of_planckian_radiators(T):
    r = ph.cct(ph.planck_relative(LAM, T) @ ph.cmf(LAM))
    assert r["cct_k"] == pytest.approx(T, rel=1e-7) and abs(r["duv"]) < 1e-9


def test_duv_is_the_signed_distance_across_the_locus():
    """A point moved 0.01 along the locus normal (towards larger v) keeps the temperature and has Duv = +0.01."""
    T = 4000.0
    p = ph.planck_uv(T)[0]
    t = (ph.planck_uv(T * 1.0001)[0] - ph.planck_uv(T / 1.0001)[0]) / (2e-4 * T)
    n = np.array([-t[1], t[0]]) / np.hypot(*t)
    n = n if n[1] > 0 else -n
    for d in (0.01, -0.01, 0.06):
        u, v = p + d * n
        vp = 1.5 * v
        # XYZ with Y = 1 from (u', v')
        X, Z = 9 * u / (4 * vp), (12 - 3 * u - 20 * vp) / (4 * vp)
        r = ph.cct(np.array([X, 1.0, Z]))
        assert r["duv"] == pytest.approx(d, abs=1e-7)
        if abs(d) <= 0.05:
            assert r["cct_k"] == pytest.approx(T, abs=1e-3)
        else:
            assert r["cct_k"] is None


def test_srgb_matrix_and_transfer_function():
    M = ph.srgb_matrix()
    iec = np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]])
    assert np.abs(M - iec).max() < 1e-3
    xw, yw = ph.SRGB_WHITE
    assert np.allclose(M @ np.array([xw / yw, 1.0, (1 - xw - yw) / yw]), 1.0, atol=1e-12)
    assert float(ph.srgb_encode(np.array(0.0031308))) == pytest.approx(0.04045, abs=1e-5)
    assert float(ph.srgb_encode(np.array(1.0))) == pytest.approx(1.0, abs=1e-12)


def test_photometry_endpoint_and_source_light():
    r = client.post("/api/v1/photometry/spectrum", json={"wavelengths": [{"value": 0.555, "weight": 1.0}, {"value": 0.6, "weight": 0.0}], "power_w": 2.0}).json()
    assert r["luminous_flux_lm"] == pytest.approx(2 * 683.002, abs=1e-9)
    bad = client.post("/api/v1/photometry/spectrum", json={"wavelengths": [{"value": 0.555, "weight": 0.0}], "power_w": 1.0})
    assert bad.status_code == 422


@pytest.mark.parametrize("name,observer,xy", [
    ("D65", "2", (0.31272, 0.32903)), ("D50", "2", (0.34567, 0.35851)), ("D55", "2", (0.33242, 0.34743)), ("D75", "2", (0.29902, 0.31485)),
    ("A", "2", (0.44757, 0.40745)), ("C", "2", (0.31006, 0.31616)), ("F2", "2", (0.37208, 0.37529)), ("F7", "2", (0.31292, 0.32933)),
    ("F11", "2", (0.38052, 0.37713)), ("D65", "10", (0.31382, 0.33100)), ("D50", "10", (0.34773, 0.35952)), ("A", "10", (0.45117, 0.40594)),
])
def test_white_points_of_the_cie_illuminants(name, observer, xy):
    """Chromaticities of the illuminants (CIE 015 tables of white points) from their spectra and the observers."""
    lam = np.arange(360.0, 831.0, 1.0)
    XYZ = (ph.cmf(lam, observer) * ph.illuminant(name, lam)[:, None]).sum(0)
    c = ph.chromaticity(XYZ)
    assert c["x"] == pytest.approx(xy[0], abs=4e-4) and c["y"] == pytest.approx(xy[1], abs=4e-4)


def test_daylight_formula_reproduces_the_d65_table():
    """D65 is defined by the daylight formula at 6504 K: the components reproduce the tabulated D65 on its 5 nm points."""
    lam = np.arange(300.0, 831.0, 5.0)
    d = ph.daylight(lam, 6500.0)
    t = ph.d65(lam)
    assert np.abs(d / d[lam == 560][0] * 100 - t).max() < 0.05  # the table's own rounding
