"""Huygens PSF: Airy pattern, defocus law, tilted image plane, FFT agreement, checks."""

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.special import j1

from opticore.analysis.diffraction import psf as fft_psf
from opticore.analysis.huygens import huygens_psf
from opticore.api.main import app
from opticore.samples import get_sample
from opticore.system import compile_system

from .conftest import make_system
from .test_diffractive import _ideal_coeffs

LAM = 0.55  # um
F, R_NORM, EPD = 100.0, 5.0, 10.0


def _ideal(tilt_deg: float = 0.0):
    """Aberration-free F/10 focus: a diffractive lens with the exact focusing phase."""
    A = _ideal_coeffs(F, R_NORM, LAM)
    surfs = [
        {"id": "obj", "thickness": None},
        {"id": "doe", "thickness": F, "is_stop": True, "phase_coefficients": A, "phase_norm_radius": R_NORM},
    ]
    if tilt_deg:
        surfs.append({"id": "cb", "type": "coordinate_break", "tilt_x": tilt_deg, "thickness": 0.0})
    surfs.append({"id": "img"})
    return compile_system(make_system(surfs, wavelengths=[{"value": LAM}], aperture={"type": "epd", "value": EPD}))


NA = (EPD / 2) / math.hypot(EPD / 2, F)


def _airy(r_um):
    v = 2 * math.pi * NA * np.asarray(r_um) / LAM
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(v == 0, 1.0, (2 * j1(v) / v) ** 2)
    return a


def test_aberration_free_focus_is_the_airy_pattern():
    r = huygens_psf(_ideal(), 0, None, pupil_samples=64, image_samples=65, image_delta_um=0.4)
    I = np.array(r["psf"])
    x = np.array(r["x_um"])
    mid = 32
    assert x[mid] == 0.0
    assert r["strehl"] == pytest.approx(1.0, abs=2e-3)
    for prof in (I[mid, :], I[:, mid]):
        assert np.max(np.abs(prof - _airy(np.abs(x)))) < 4e-3
    # first dark ring at 0.61 lambda / NA
    k0 = int(np.argmin(I[mid, mid : mid + 30])) + mid
    assert x[k0] == pytest.approx(0.6098 * LAM / NA, abs=0.4)
    assert not r["warnings"]


def test_on_axis_defocus_follows_the_sinc_law():
    """I(dz)/I0 = [sin(u/4)/(u/4)]^2 with u = (2 pi / lambda) NA^2 dz (Born & Wolf 8.8)."""
    cs = _ideal()
    for frac in (0.5, 1.0, 0.25):  # u/4 = frac * pi
        dz = frac * 2 * LAM * 1e-3 / NA**2
        r = huygens_psf(cs, 0, None, pupil_samples=96, image_samples=17, image_delta_um=0.5, defocus_mm=dz)
        I0 = np.array(r["psf"])[8, 8]
        a = frac * math.pi
        assert I0 == pytest.approx((math.sin(a) / a) ** 2, abs=6e-3)


def test_tilted_image_plane_stretches_the_psf():
    beta = 60.0
    r = huygens_psf(_ideal(beta), 0, None, pupil_samples=64, image_samples=81, image_delta_um=0.4)
    I = np.array(r["psf"])
    x = np.array(r["x_um"])
    mid = 40

    def first_zero(prof):
        k = mid + 1
        while prof[k + 1] < prof[k]:  # first local minimum outward from the centre
            k += 1
        # parabolic refinement of the minimum
        a, b, c = prof[k - 1], prof[k], prof[k + 1]
        return x[k] + 0.5 * (a - c) / (a - 2 * b + c) * (x[1] - x[0])

    zx = first_zero(I[mid, :])
    zy = first_zero(I[:, mid])
    assert zy / zx == pytest.approx(1 / math.cos(math.radians(beta)), rel=0.03)  # FFT PSF cannot show this
    assert r["strehl"] == pytest.approx(1.0, abs=5e-3)


def test_agrees_with_the_fft_psf_for_a_real_lens():
    cs = compile_system(get_sample("achromat").system)
    f = fft_psf(cs, 0, None, grid=64, pad=4)
    for n_img in (48, 65):  # the Strehl ratio does not depend on the image grid (peak refined)
        h = huygens_psf(cs, 0, None, pupil_samples=64, image_samples=n_img)
        assert h["strehl"] == pytest.approx(f["strehl"], abs=0.005)
    assert 0 < h["strehl"] <= 1.0 + 1e-9


def test_sampling_warnings_and_errors():
    cs = _ideal()
    r = huygens_psf(cs, 0, None, pupil_samples=16, image_samples=32, image_delta_um=20.0)
    assert any("alias" in w for w in r["warnings"])
    with pytest.raises(ValueError):
        huygens_psf(cs, 0, None, pupil_samples=8)
    big = make_system(
        [{"id": "obj", "thickness": None}, {"id": "s1", "radius": 30.0, "thickness": 6.0, "material": "N-SF11", "is_stop": True}, {"id": "s2", "thickness": 40.0}, {"id": "img"}],
        aperture={"type": "epd", "value": 24.0},
    )
    r = huygens_psf(compile_system(big), 0, None, pupil_samples=16, image_samples=32)
    assert any("under-sampled" in w for w in r["warnings"])


def test_huygens_api():
    c = TestClient(app)
    body = {"system": get_sample("singlet").system.model_dump(), "field": 0, "pupil_samples": 32, "image_samples": 32}
    r = c.post("/api/v1/analysis/huygens", json=body)
    assert r.status_code == 200
    b = r.json()
    assert len(b["psf"]) == 32 and 0 < b["strehl"] <= 1
    assert c.post("/api/v1/analysis/huygens", json={**body, "pupil_samples": 4}).status_code == 422
