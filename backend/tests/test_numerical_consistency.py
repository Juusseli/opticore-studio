"""Finite-difference steps, PMMA data, the chief-ray angle and Gaussian sources in a medium (ADR-044).

* The serial Jacobian of the weighted-limits solve uses the pool's steps (parallel.fd_steps), so a run gives the same
  design with and without the pool. Independent check: the steps equal 1e-7 * max(1, |x|) away from the bounds, and
  a serial run equals a forced-pool run evaluation for evaluation.
* PMMA data (test_materials.py).
* The chief-ray angle is measured against the local normal of the image surface where the chief ray lands.
  Analytic: an ideal lens at the stop sends the chief ray undeviated from its centre; on an image sphere centred on
  the lens the ray meets the surface along its normal (0 degrees), on a plane at the field angle, and on a sphere
  centred elsewhere at the angle between the ray and the radius to its landing point.
* A Gaussian beam source in a medium diverges by M^2 lambda / (pi n w0) (test below).
"""

import math

import numpy as np
import pytest

from opticore.analysis.summary import chief_ray_angle_deg
from opticore.paraxial import compute_pupil
from opticore.system import compile_system

from .conftest import make_system


def _ideal(image: dict, fy: float, fx: float = 0.0):
    return make_system(
        [{"thickness": None}, {"type": "ideal", "focal_length": 100.0, "thickness": 100.0, "is_stop": True}, image],
        wavelengths=[{"value": 0.55}],
        fields=[{"y": 0.0}, {"x": fx, "y": fy}],
        aperture={"type": "epd", "value": 10.0},
    )


def _cra(sys) -> float:
    cs = compile_system(sys)
    return chief_ray_angle_deg(cs, compute_pupil(cs, sys.primary_wavelength), 1)


@pytest.mark.parametrize("fx,fy", [(0.0, 10.0), (7.0, 7.0), (-12.0, 0.0)])
def test_chief_ray_angle_is_taken_to_the_local_normal_of_the_image_surface(fx, fy):
    theta = math.degrees(math.atan(math.hypot(math.tan(math.radians(fx)), math.tan(math.radians(fy)))))
    assert _cra(_ideal({}, fy, fx)) == pytest.approx(theta, abs=1e-9)  # plane: the field angle
    assert _cra(_ideal({"radius": -100.0}, fy, fx)) == pytest.approx(0.0, abs=1e-6)  # centred on the lens: along the normal
    # a sphere of radius 100 with its centre 200 mm behind the lens: the angle between the ray and the radius
    t = math.radians(theta)
    u = np.array([0.0, math.sin(t), math.cos(t)])
    c = np.array([0.0, 0.0, 200.0])
    s = 200.0 * math.cos(t) - math.sqrt((200.0 * math.cos(t)) ** 2 - (200.0**2 - 100.0**2))
    n = (s * u - c) / 100.0
    expected = math.degrees(math.acos(abs(float(u @ n))))
    assert expected > theta + 5.0  # differs clearly from the angle to the axis
    assert _cra(_ideal({"radius": 100.0}, fy, fx)) == pytest.approx(expected, abs=1e-6)


def _plate(object_medium: str | None = None):
    s0 = {"id": "obj", "thickness": 100.0}
    if object_medium:
        s0["material"] = object_medium
    return make_system(
        [
            s0,
            {"id": "a", "thickness": 60.0, "material": "N-BK7", "semi_diameter": 10.0, "semi_diameter_mode": "fixed", "is_stop": True},
            {"id": "b", "thickness": 20.0, "semi_diameter": 10.0, "semi_diameter_mode": "fixed"},
            {"id": "img"},
        ],
        wavelengths=[{"value": 1.0}],
        field_type="object_height",
        fields=[{"y": 0.0}],
        aperture={"type": "object_na", "value": 0.01},
    )


def test_gaussian_beam_source_in_a_solid_diverges_by_one_over_its_index():
    """A Gaussian beam (w0 = 20 um, M^2 = 1.5, lambda = 1 um) whose source lies 10 mm inside a 60 mm N-BK7 plate (its
    faces at z = 0 and 60 in the global frame, which starts at the first surface): in
    the glass w(z)^2 = w0^2 + theta^2 z^2 with theta = M^2 lambda / (pi n w0) (the wavelength in the glass is
    lambda / n). Behind the plate the far-field angle in air is n theta = M^2 lambda / (pi w0) (paraxial Snell), and
    the beam continues from the virtual waist at the reduced distance d / n. Diverging as in air inside the glass
    would be n = 1.507 times too fast."""
    from opticore.nonseq import build_scene, trace_nonsequential
    from opticore.nssources import Detector, LightSource

    sysm = _plate()
    cs = compile_system(sysm)
    n = float(cs.library.index("N-BK7", 1.0))
    lam, w0, m2 = 1.0e-3, 0.020, 1.5
    th_glass = m2 * lam / (math.pi * n * w0)
    src = LightSource(kind="gaussian_beam", placement={"position": [0, 0, 10.0]}, beam_waist_x=w0, beam_waist_y=w0, beam_m2=m2, rays=40000, wavelengths=[{"value": 1.0}])
    z_in, z_out = 50.0, 75.0  # 40 mm after the source in the glass; 15 mm behind the plate (the image is at 80)
    dets = [Detector(name="in", placement={"position": [0, 0, z_in]}, size_x=5.0, mode="monitor"), Detector(name="out", placement={"position": [0, 0, z_out]}, size_x=8.0, mode="monitor")]
    scene = build_scene(cs, [], True, None, (), dets)
    r = trace_nonsequential(cs, scene, sources=[src], split=False, seed=5, keep_paths=0)
    assert any("inside" in s and "n = " in s for s in r["notes"])
    w_in = math.hypot(w0, th_glass * (z_in - 10.0))
    w_out = math.hypot(w0, n * th_glass * ((z_out - 60.0) + (60.0 - 10.0) / n))  # in air from the virtual waist
    d_in, d_out = r["detectors"]
    assert d_in["width_2sigma_mm"] == pytest.approx([w_in, w_in], rel=0.02)
    assert d_out["width_2sigma_mm"] == pytest.approx([w_out, w_out], rel=0.02)
    assert abs(d_in["width_2sigma_mm"][0] / w_in - 1.0) < 0.02 < abs(math.hypot(w0, n * th_glass * 40.0) / w_in - 1.0)


def test_gaussian_beam_source_of_the_direct_path_diverges_in_the_object_space():
    """The direct path starts its rays in the object space: in an object space of index 1.4 (a custom immersion
    medium) the beam diverges by M^2 lambda / (pi 1.4 w0); the beam description is in air."""
    from fastapi.testclient import TestClient

    from opticore.api.main import app
    from opticore.nsdirect import trace_direct
    from opticore.nssources import Detector, LightSource

    custom = [{"name": "IMM14", "formula": "constant", "coefficients": [1.4]}]
    sysm = _plate("IMM14")
    cs = compile_system(sysm, custom)
    w0 = 0.020
    src = LightSource(kind="gaussian_beam", placement={"position": [0, 0, -80.0]}, beam_waist_x=w0, beam_waist_y=w0, rays=20000, wavelengths=[{"value": 1.0}])
    det = Detector(placement={"position": [0, 0, -20.0]}, size_x=5.0, mode="monitor")  # 60 mm on, before the plate (z = 0)
    d = trace_direct(cs, [src], [det], seed=2)["detectors"][0]
    w = math.hypot(w0, 1.0e-3 / (math.pi * 1.4 * w0) * 60.0)
    assert d["width_2sigma_mm"] == pytest.approx([w, w], rel=0.02)
    body = {"system": sysm.model_dump(mode="json"), "custom_materials": custom, "sources": [src.model_dump(mode="json")], "detectors": []}
    b = TestClient(app).post("/api/v1/sources/describe", json=body).json()["sources"][0]["beam"]
    assert b["medium_index"] == 1.0 and b["x"]["divergence_mrad"] == pytest.approx(1.0 / (math.pi * w0))
