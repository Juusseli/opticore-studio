"""Spectrometer analysis (analysis/spectrometer.py) and its library example.

References (independent of the analysis):
* the grating equation and the ideal camera: a collimated beam diffracted by G lines/mm into order m leaves at
  sin(beta) = m lambda G and images at y = f2 tan(beta); the linear dispersion is dy/dlambda = f2 m G / cos^3(beta);
* the Rayleigh resolving power of a grating, R = |m| N, with N = G w the lines across the illuminated width w (here the
  collimated beam's diameter, the entrance pupil);
* a real camera lens: the resolution is the rms spot width along the dispersion as a Gaussian FWHM over |D|.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.analysis.spectrometer import spectrometer
from opticore.api.main import app
from opticore.samples import SPECTRO_F_MM, SPECTRO_LINES, get_sample
from opticore.system import NotApplicable

client = TestClient(app)


def test_grating_spectrograph_example_follows_the_grating_equation():
    p = get_sample("grating-spectrograph")
    assert p.ui["open_view"] == "spectrometer"
    st = p.analysis_settings["spectrometer"]
    r = spectrometer(p.system, [], st["field"], st["wl_min_um"], st["wl_max_um"], st["points"], st["density"])
    lam = np.array(r["wavelength_um"])
    beta = np.arcsin(lam * 1e-3 * SPECTRO_LINES)
    y = np.array([c[1] for c in r["centroid_mm"]])
    assert np.abs(y - SPECTRO_F_MM * np.tan(beta)).max() < 1e-9
    assert np.abs(np.array([c[1] for c in r["chief_mm"]]) - y).max() < 1e-9
    D = np.array(r["dispersion_mm_per_nm"])
    Dan = SPECTRO_F_MM * SPECTRO_LINES * 1e-6 / np.cos(beta) ** 3
    assert np.abs(D / Dan - 1).max() < 5e-5  # second-order differences over 5 nm steps
    assert r["direction"] == pytest.approx([0.0, 1.0], abs=1e-12)
    g = r["grating"]
    EPD = p.system.aperture.value
    assert g["order"] == 1 and g["lines_per_mm"] == SPECTRO_LINES
    assert np.allclose(g["illuminated_mm"], EPD, atol=1e-9) and np.allclose(g["resolving_power"], SPECTRO_LINES * EPD, rtol=1e-12)
    assert g["resolution_nm"][20] == pytest.approx(0.55e3 / (SPECTRO_LINES * EPD), rel=1e-9)
    assert all(v is None for v in r["resolution_nm"]) and r["notes"]  # ideal optics: no geometric spot


def test_real_camera_gives_a_geometric_resolution():
    p = get_sample("grating-spectrograph")
    sysd = p.system.model_dump(mode="json")
    # the camera as a plano-convex N-BK7 singlet of about the same focal length
    sysd["surfaces"][3:4] = [
        {"id": "c1", "label": "Camera front", "radius": 51.68, "thickness": 5.0, "material": "N-BK7"},
        {"id": "c2", "label": "Camera back", "radius": None, "thickness": 96.6},
    ]
    from opticore.model import OpticalSystem

    sys2 = OpticalSystem.model_validate(sysd)
    r = spectrometer(sys2, [], 0, 0.45, 0.65, 21)
    res = np.array(r["resolution_nm"], float)
    sig = np.array(r["rms_along_um"], float) * 1e-3
    D = np.abs(np.array(r["dispersion_mm_per_nm"], float))
    assert np.all(np.isfinite(res)) and np.allclose(res, 2 * math.sqrt(2 * math.log(2)) * sig / D, rtol=1e-12)
    assert np.allclose(np.array(r["resolving_power"]), np.array(r["wavelength_um"]) * 1000 / res, rtol=1e-12)
    assert res.min() > 0.0 and np.all(D > 0.05)


def test_no_dispersion_is_not_a_spectrometer():
    with pytest.raises(NotApplicable, match="dispersion"):
        spectrometer(get_sample("spherical-mirror").system, [], 0, 0.45, 0.65, 5)


def test_spectrometer_endpoint():
    p = get_sample("grating-spectrograph")
    body = {"system": p.system.model_dump(mode="json"), "wl_min_um": 0.5, "wl_max_um": 0.6, "points": 5}
    j = client.post("/api/v1/analysis/spectrometer", json=body)
    assert j.status_code == 200, j.text
    assert len(j.json()["position_mm"]) == 5 and j.json()["grating"]["resolving_power"][0] == pytest.approx(12000.0)
    bad = client.post("/api/v1/analysis/spectrometer", json={**body, "wl_min_um": 0.7})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "SPECTROMETER"
    na = client.post("/api/v1/analysis/spectrometer", json={"system": get_sample("singlet").system.model_dump(mode="json")})
    assert na.status_code == 422 and na.json()["error"]["code"] == "NOT_APPLICABLE"
