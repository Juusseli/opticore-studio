"""Rotationally symmetric beam propagation (wave/bpm.py) against analytic Gaussian beams and the
physical-optics propagation."""

import math

import numpy as np
import pytest

from opticore.model import OpticalSystem
from opticore.system import SystemError_, compile_system
from opticore.wave.bpm import Hankel, bpm
from opticore.wave.pop import gaussian_q, physical_optics

from .beam_systems import relay, singlet, thick_lens

LAM = 1.55e-3


def _system(d0, R1, t, d2, mat="N-BK7"):
    a = {"id": "a", "thickness": t, "material": mat, "semi_diameter": 2, "semi_diameter_mode": "fixed", "is_stop": True}
    if R1 is not None:
        a["radius"] = R1
    return compile_system(
        OpticalSystem.model_validate(
            {
                "surfaces": [{"id": "o", "thickness": d0}, a, {"id": "b", "thickness": d2, "semi_diameter": 2, "semi_diameter_mode": "fixed"}, {"id": "i"}],
                "wavelengths": [{"value": 1.55}],
                "field_type": "object_height",
                "fields": [{"y": 0}],
                "aperture": {"type": "object_na", "value": 0.05},
            }
        )
    )


def _abcd_w(d0, R1, t, d2, n, w0):
    """Paraxial Gaussian beam (reduced q = q / n): air d0, surface R1, glass t, plane, air d2."""
    q = d0 + 1j * math.pi * w0 * w0 / LAM
    q = 1 / (1 / q - (n - 1) / R1) if R1 else q
    q = q + t / n + d2
    return math.sqrt(-LAM / (math.pi * (1 / q).imag))


def test_hankel_transform_conserves_power_and_propagates_exactly():
    H = Hankel(512, 1.0)
    w0 = 0.03
    u = np.exp(-((H.r / w0) ** 2)).astype(complex)
    assert (np.abs(u) ** 2 * H.weights).sum() == pytest.approx(math.pi * w0 * w0 / 2, rel=1e-12)
    v = H.propagate(u, 2 * math.pi / LAM, 0.0, 2.0)
    assert (np.abs(v) ** 2 * H.weights).sum() == pytest.approx(math.pi * w0 * w0 / 2, rel=1e-12)
    I = np.abs(v) ** 2
    w = math.sqrt(2 * (I * H.r**2 * H.weights).sum() / (I * H.weights).sum())
    assert w == pytest.approx(gaussian_q(w0, 2.0, LAM)[0], rel=2e-4)


@pytest.mark.parametrize("d0", [0.5, 2.0, 20.0])
def test_plate_matches_the_gaussian_beam_also_near_the_waist(d0):
    """5 mm N-BK7 plate, 20 um waist d0 before it: the beam width is that of the free beam over the
    reduced length d0 + t / n + d2, the power T^2. POP's ray transfer misses the diffraction inside
    the glass when the plate sits within the Rayleigh range (0.81 mm)."""
    cs = _system(d0, None, 5.0, 3.0)
    n = float(cs.n_after[0, 1])
    w = gaussian_q(0.02, d0 + 5.0 / n + 3.0, LAM)[0]
    r = bpm(cs, {"kind": "gaussian", "waist_x": 0.02})
    assert r["target"]["d4sigma_mm"][0] == pytest.approx(2 * w, rel=1e-3)
    T = 1 - ((n - 1) / (n + 1)) ** 2
    assert r["target"]["power"] + r["target"]["power_outside_window"] == pytest.approx(T * T, rel=1e-4)
    if d0 == 0.5:
        assert abs(physical_optics(cs, {"kind": "gaussian", "waist_x": 0.02})["target"]["d4sigma_mm"][0] / (2 * w) - 1) > 0.2


@pytest.mark.parametrize("d0, R1, t, d2, w0", [(0.5, 20.0, 3.0, 20.0, 0.03), (0.3, 10.0, 2.0, 30.0, 0.02), (1.0, -15.0, 2.0, 10.0, 0.025)])
def test_singlet_near_the_waist_matches_the_abcd_beam(d0, R1, t, d2, w0):
    """Curved entrance face inside the Rayleigh range of the source (paraxial: the beam is ~1 %
    of the radius of curvature, so aberrations are negligible): the BPM width follows the ABCD
    law to 1e-3."""
    cs = _system(d0, R1, t, d2)
    n = float(cs.n_after[0, 1])
    r = bpm(cs, {"kind": "gaussian", "waist_x": w0})
    assert r["target"]["d4sigma_mm"][0] == pytest.approx(2 * _abcd_w(d0, R1, t, d2, n, w0), rel=1e-3)
    assert "face zones" in r["exit"]["propagation"]


@pytest.mark.parametrize("make", [thick_lens, singlet], ids=["thick-lens", "singlet"])
def test_agrees_with_pop_where_the_ray_transfer_holds(make):
    """Strongly curved faces with the beam far from its waist at the lens (tests/beam_systems.py), so
    POP's ray transfer is accurate: D4sigma within 1 %, power on the 0.4 mm detector within 0.2 %."""
    p = make()
    cs = compile_system(p.system, p.custom_materials)
    src = {"kind": "gaussian", "waist_x": 0.0052}
    rb = bpm(cs, src, detector_radius=0.2)
    rp = physical_optics(cs, src, detector_radius=0.2)
    assert rb["target"]["d4sigma_mm"][0] == pytest.approx(rp["target"]["d4sigma_mm"][0], rel=0.01)
    assert rb["target"]["power_in_radius"] == pytest.approx(rp["target"]["power_in_radius"], abs=2e-3)
    assert rb["side"]["irradiance"] and len(rb["side"]["z"]) == len(rb["side"]["irradiance"][0])


def test_refuses_off_axis_sources_and_too_wide_beams():
    cs = _system(2.0, 20.0, 3.0, 20.0)
    with pytest.raises(SystemError_, match="on-axis"):
        bpm(cs, {"kind": "gaussian", "waist_x": 0.02, "decenter": [0.1, 0.0]})
    p = relay()  # a 4 mm collimated beam over R 12.7 mm faces: POP's job
    with pytest.raises(SystemError_, match="Use POP"):
        bpm(compile_system(p.system, p.custom_materials), {"kind": "gaussian", "waist_x": 0.004})


def test_api_method_bpm():
    from fastapi.testclient import TestClient

    from opticore.api.main import app

    c = TestClient(app)
    p = thick_lens()
    body = {"system": p.system.model_dump(mode="json"), "custom_materials": p.custom_materials, "source": {"kind": "gaussian", "waist_x": 0.0052}, "detector_radius": 0.2}
    r = c.post("/api/v1/analysis/pop", json={**body, "method": "bpm", "side_view": True})
    assert r.status_code == 200, r.text
    js = r.json()
    assert js["method"].startswith("Rotationally symmetric beam propagation") and "side" in js
    assert c.post("/api/v1/analysis/pop", json={**body, "method": "bpm"}).json().get("side") is None
    assert c.post("/api/v1/analysis/pop", json={**body, "method": "maxwell"}).status_code == 422
