import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.physics import fresnel
from opticore.polarization import jones_pupil, jones_properties, polarization_matrices, polarization_pupil
from opticore.samples import get_sample
from opticore.system import compile_system
from opticore.thinfilm import COATINGS, stack_amplitudes, stack_rt

from .conftest import make_system

LAM = 0.5875618


def _tilted_interface(theta_deg: float, n_glass="N-BK7", plate: bool = False, coating: str = ""):
    """Collimated axial beam onto a plane interface tilted about x by theta (exit face parallel if plate)."""
    surfs = [
        {"id": "obj", "thickness": None},
        {"id": "stop", "thickness": 5.0, "is_stop": True},
        {"id": "cb", "type": "coordinate_break", "tilt_x": theta_deg},
        {"id": "f1", "thickness": 10.0, "material": n_glass, "coating": coating},
    ]
    if plate:
        surfs += [{"id": "f2", "thickness": 0.0}, {"id": "cb2", "type": "coordinate_break", "tilt_x": -theta_deg, "thickness": 20.0}]
    else:
        surfs[-1]["thickness"] = 10.0
    surfs += [{"id": "img"}]
    return make_system(surfs, wavelengths=[{"value": LAM}], aperture={"type": "epd", "value": 1.0})


def _axial_ray(cs):
    P0 = np.array([[0.0, 0.0, -1.0]])
    D0 = np.array([[0.0, 0.0, 1.0]])
    return P0, D0


def _angles(cs, theta):
    n1, n2 = 1.0, cs.n_after[0, 3]
    ci = math.cos(math.radians(theta))
    ct = math.sqrt(1 - (n1 / n2 * math.sin(math.radians(theta))) ** 2)
    return n1, n2, ci, ct


@pytest.mark.parametrize("theta", [0.0, 20.0, 45.0, 56.0, 75.0])
def test_single_interface_jones_matches_fresnel(theta):
    cs = compile_system(_tilted_interface(theta))
    P0, D0 = _axial_ray(cs)
    jp = jones_pupil(cs, 0, P0, D0)
    J = jp["J"][0]
    n1, n2, ci, ct = _angles(cs, theta)
    f = fresnel(n1, n2, ci, ct)
    # tilt about x: the plane of incidence is y-z, so x is s-polarised and y is p-polarised
    assert abs(J[0, 0]) ** 2 == pytest.approx(float(f["Ts"]), rel=1e-12)
    assert abs(J[1, 1]) ** 2 == pytest.approx(float(f["Tp"]), rel=1e-12)
    assert abs(J[0, 1]) < 1e-12 and abs(J[1, 0]) < 1e-12
    props = jones_properties(jp["J"])
    assert props["transmission"][0] == pytest.approx(0.5 * float(f["Ts"] + f["Tp"]), rel=1e-12)
    assert props["retardance"][0] == pytest.approx(0.0, abs=1e-12)  # dielectric transmission: real coefficients


def test_brewster_angle_transmits_p_completely():
    cs = compile_system(_tilted_interface(0.0))
    n2 = cs.n_after[0, 3]
    theta_b = math.degrees(math.atan(n2))
    cs = compile_system(_tilted_interface(theta_b))
    jp = jones_pupil(cs, 0, *_axial_ray(cs))
    J = jp["J"][0]
    assert abs(J[1, 1]) ** 2 == pytest.approx(1.0, abs=1e-12)
    n1, n2, ci, ct = _angles(cs, theta_b)
    Ts = float(fresnel(n1, n2, ci, ct)["Ts"])
    D = jones_properties(jp["J"])["diattenuation"][0]
    assert D == pytest.approx((1 - Ts) / (1 + Ts), rel=1e-12)


def test_tilted_plate_transmits_square_of_single_surface():
    theta = 50.0
    cs = compile_system(_tilted_interface(theta, plate=True))
    jp = jones_pupil(cs, 0, *_axial_ray(cs))
    J = jp["J"][0]
    n1, n2, ci, ct = _angles(cs, theta)
    f = fresnel(n1, n2, ci, ct)
    assert abs(J[0, 0]) ** 2 == pytest.approx(float(f["Ts"]) ** 2, rel=1e-12)
    assert abs(J[1, 1]) ** 2 == pytest.approx(float(f["Tp"]) ** 2, rel=1e-12)


def test_normal_incidence_mirror_reverses_the_field():
    sysm = get_sample("spherical-mirror").system
    cs = compile_system(sysm)
    m = polarization_matrices(cs, 0, np.array([[0.0, 0.0, -1.0]]), np.array([[0.0, 0.0, 1.0]]))
    P = m["P"][0]
    E = np.array([0.3, 0.7, 0.0])
    assert np.allclose(P @ E, -E, atol=1e-12)
    # an ideal mirror is lossless and non-diattenuating
    jp = jones_pupil(cs, 0, np.array([[0.0, 3.0, -1.0]]), np.array([[0.0, 0.0, 1.0]]))
    pr = jones_properties(jp["J"])
    assert pr["transmission"][0] == pytest.approx(1.0, abs=1e-12)
    assert pr["diattenuation"][0] == pytest.approx(0.0, abs=1e-12)


def test_coated_interface_amplitudes_match_thin_film_power_and_phase():
    theta = 40.0
    cs = compile_system(_tilted_interface(theta, coating="VCOAT_550"))
    jp = jones_pupil(cs, 0, *_axial_ray(cs))
    J = jp["J"][0]
    n2 = cs.n_after[0, 3]
    ci = np.array([math.cos(math.radians(theta))])
    layers = COATINGS["VCOAT_550"].layers_at(LAM)  # dispersive films at the trace wavelength
    rt = stack_rt(1.0, n2, layers, LAM, ci)
    amp = stack_amplitudes(1.0, n2, layers, LAM, ci)
    assert abs(J[0, 0]) ** 2 == pytest.approx(rt["Ts"][0], rel=1e-12)
    assert abs(J[1, 1]) ** 2 == pytest.approx(rt["Tp"][0], rel=1e-12)
    # retardance of the coated interface = phase difference of t_p and t_s
    expected = abs(np.angle(amp["tp"][0] / amp["ts"][0]))
    assert jones_properties(jp["J"])["retardance"][0] == pytest.approx(expected, abs=1e-12)
    assert expected > 1e-4  # the coating does introduce retardance


def test_empty_stack_amplitudes_are_fresnel():
    ci = np.cos(np.radians(np.linspace(0, 80, 7)))
    n2 = 1.6
    ct = np.sqrt(1 - (np.sin(np.arccos(ci)) / n2) ** 2)
    a = stack_amplitudes(1.0, n2, (), LAM, ci)
    f = fresnel(1.0, n2, ci, ct)
    assert np.allclose(np.abs(a["ts"]) ** 2, f["Ts"], atol=1e-14)
    assert np.allclose(np.abs(a["tp"]) ** 2, f["Tp"], atol=1e-14)
    assert np.allclose(a["rs"].real, f["rs"], atol=1e-14)


def test_axial_chief_ray_matches_scalar_throughput():
    from opticore.paraxial import compute_pupil
    from opticore.raytrace import launch, trace

    cs = compile_system(get_sample("achromat").system)
    pupil = compute_pupil(cs)
    P0, D0, opl = launch(cs, 1, 0, np.array([0.0]), np.array([0.0]), pupil)
    scalar = trace(cs, 1, P0, D0, opl, fresnel=True).intensity[0]
    jp = jones_pupil(cs, 1, P0, D0)
    assert jones_properties(jp["J"])["transmission"][0] == pytest.approx(scalar, rel=1e-12)


def test_rotational_symmetry_of_an_axial_system():
    cs = compile_system(get_sample("singlet").system)
    r = polarization_pupil(cs, 0, None, grid=21, input_state="unpolarized")
    px, py = np.array(r["px"]), np.array(r["py"])
    D = np.array(r["diattenuation"], dtype=float)
    # rotating the pupil by 90 degrees maps the (square, symmetric) grid onto itself:
    # diattenuation and retardance are invariant for a rotationally symmetric system
    key = {(round(x, 9), round(y, 9)): k for k, (x, y) in enumerate(zip(px, py))}
    R = np.array(r["retardance_waves"], dtype=float)
    for k, (x, y) in enumerate(zip(px, py)):
        m = key[(round(-y, 9), round(x, 9))]
        assert D[m] == pytest.approx(D[k], rel=1e-9, abs=1e-15)
        assert R[m] == pytest.approx(R[k], abs=1e-12)
    assert np.nanmax(D) > 1e-4  # the singlet is measurably diattenuating at the rim
    # uncoated dielectric surfaces have real Fresnel coefficients: no linear retardance,
    # only the geometric (skew-ray) rotation between the local bases
    assert np.nanmax(R) < 1e-12
    assert np.nanmax(np.abs(np.array(r["rotation_deg"], dtype=float))) > 1e-6
    # x-input on the x axis behaves like y-input on the y axis
    rx = polarization_pupil(cs, 0, None, grid=21, input_state="x")
    ry = polarization_pupil(cs, 0, None, grid=21, input_state="y")
    i_x = int(np.argmin(np.hypot(px - 0.9, py)))
    i_y = int(np.argmin(np.hypot(px, py - 0.9)))
    assert rx["transmission"][i_x] == pytest.approx(ry["transmission"][i_y], rel=1e-12)
    assert rx["summary"]["x_transmission"] == pytest.approx(rx["summary"]["y_transmission"], rel=1e-10)


def test_jones_property_extraction():
    a, b, d = 0.9, 0.6, 0.7
    J = np.array([[[a, 0], [0, b * np.exp(1j * d)]]], dtype=complex)
    rot = lambda t: np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])  # noqa: E731
    Jr = np.array([rot(0.3) @ J[0] @ rot(-0.3)])
    for M in (J, Jr):
        p = jones_properties(M)
        assert p["transmission"][0] == pytest.approx(0.5 * (a * a + b * b), rel=1e-12)
        assert p["diattenuation"][0] == pytest.approx((a * a - b * b) / (a * a + b * b), rel=1e-12)
        assert p["retardance"][0] == pytest.approx(d, rel=1e-10)
        assert p["rotation"][0] == pytest.approx(0.0, abs=1e-12)
    # a pure rotation is reported as rotation, not as linear retardance
    pr = jones_properties(np.array([rot(0.2)], dtype=complex))
    assert pr["retardance"][0] == pytest.approx(0.0, abs=1e-12)
    assert pr["rotation"][0] == pytest.approx(0.2, rel=1e-12)
    # retarder followed by a rotation: both recovered
    pc = jones_properties(np.array([rot(0.15) @ J[0]]))
    assert pc["retardance"][0] == pytest.approx(d, rel=1e-10)
    assert pc["rotation"][0] == pytest.approx(0.15, rel=1e-10)


def test_polarization_api():
    c = TestClient(app)
    sysm = get_sample("achromat").system
    r = c.post("/api/v1/analysis/polarization", json={"system": sysm.model_dump(), "field": 2, "input": "45", "grid": 9})
    assert r.status_code == 200, r.text
    b = r.json()
    assert 0.8 < b["summary"]["unpolarized_transmission"] < 1.0
    assert len(b["px"]) == len(b["transmission"]) == len(b["ellipse"]["azimuth_rad"])
    assert c.post("/api/v1/analysis/polarization", json={"system": sysm.model_dump(), "input": "nope"}).status_code == 422
