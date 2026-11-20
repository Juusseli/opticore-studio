"""Uniaxial crystals, ideal polarising elements and Mueller matrices."""

import math

import numpy as np
import pytest
from scipy.optimize import brentq

from opticore.birefringence import Side, Uniaxial, crystal_mode_field, interface_amplitudes, iso_fields, refract_aniso, s_vector
from opticore.materials.catalog import MaterialLibrary
from opticore.polarization import depolarization_index, mueller, polarization_pupil
from opticore.raytrace import trace
from opticore.system import SystemError_, compile_system

from .conftest import make_system

LAM = 0.5893
LIB = MaterialLibrary()


def _plate(material="CALCITE", t=10.0, axis=None, mode=None, jones_after=None, extra=None, lam=LAM, epd=2.0):
    plate = {"id": "f", "thickness": t, "material": material, "crystal_axis": axis, "crystal_mode": mode}
    back = {"id": "b", "thickness": 20.0}
    if jones_after:
        back["jones"] = jones_after
    surfs = [{"id": "obj", "thickness": None}, {"id": "a", "thickness": 5.0, "is_stop": True}, plate, back, *(extra or []), {"id": "img"}]
    return make_system(surfs, wavelengths=[{"value": lam}], aperture={"type": "epd", "value": epd})


# ---- materials --------------------------------------------------------------------------


@pytest.mark.parametrize("name,no,ne", [("CALCITE", 1.6584, 1.4864), ("QUARTZ", 1.5442, 1.5533)])
def test_crystal_indices_match_handbook_values(name, no, ne):
    """Ghosh (1999) dispersion against handbook indices at the sodium D line (589.3 nm). The fit is within
    1e-4 of them except calcite's extraordinary index (1.48613 against 1.4864, -2.7e-4)."""
    m = LIB.get(name)
    assert m.birefringent
    assert m.index(0.5893) == pytest.approx(no, abs=1e-4)
    assert m.index_e(0.5893) == pytest.approx(ne, abs=3e-4)
    assert not LIB.get("N-BK7").birefringent


# ---- wave solver ------------------------------------------------------------------------


def test_interface_amplitudes_reduce_to_fresnel_and_conserve_energy():
    N = np.array([[0.0, 0.0, 1.0]])
    rng = np.random.default_rng(4)
    no, ne = LIB.get("CALCITE").index(LAM), LIB.get("CALCITE").index_e(LAM)
    for th in (0.0, 30.0, 60.0):
        t = math.radians(th)
        d = np.array([[math.sin(t), 0.0, math.cos(t)]])
        s = s_vector(d, N, np.array([[0.0, 1.0, 0.0]]))
        Es, Ep = iso_fields(d, s)
        ct = math.sqrt(1 - (math.sin(t) / 1.5) ** 2)
        Ts = 4 * math.cos(t) * 1.5 * ct / (math.cos(t) + 1.5 * ct) ** 2
        Tp = 4 * math.cos(t) * 1.5 * ct / (1.5 * math.cos(t) + ct) ** 2
        for E, T_ref, k in ((Es, Ts, 0), (Ep, Tp, 1)):
            r, tr = interface_amplitudes(d, E, d, N, Side(n=1.0), Side(n=1.5), s)
            assert abs(tr[k][0][0]) ** 2 == pytest.approx(T_ref, rel=1e-12)
            assert sum(abs(a[0][0]) ** 2 for a in r + tr) == pytest.approx(1.0, abs=1e-12)
    # lossless crystal faces: random incidences and axes, entering and leaving
    for _ in range(20):
        c = rng.normal(size=3)
        med = Uniaxial(no, ne, c / np.linalg.norm(c))
        d = rng.normal(size=3)
        d[2] = abs(d[2]) + 0.3
        d = (d / np.linalg.norm(d))[None, :]
        s = s_vector(d, N, np.array([[0.0, 1.0, 0.0]]))
        for E in iso_fields(d, s):
            r, tr = interface_amplitudes(d, E, d, N, Side(n=1.0), Side(med=med), s)
            assert sum(abs(a[0][0]) ** 2 for a in r + tr) == pytest.approx(1.0, abs=1e-12)
        for mode in ("ordinary", "extraordinary"):
            med.mode = mode
            ray, K, tir = refract_aniso(d.copy(), d, N, 0.0, med)
            assert not tir[0]
            E = crystal_mode_field(K, med, mode, s)
            r, tr = interface_amplitudes(K, E, ray, N, Side(med=med), Side(n=1.0), s)
            assert sum(abs(a[0][0]) ** 2 for a in r + tr) == pytest.approx(1.0, abs=1e-12)
            assert np.allclose(tr[0][3], d, atol=1e-12)  # leaves parallel to the incident ray


def test_normal_incidence_on_a_crystal_splits_into_o_and_e_with_their_own_fresnel_loss():
    no, ne = LIB.get("CALCITE").index(LAM), LIB.get("CALCITE").index_e(LAM)
    med = Uniaxial(no, ne, np.array([1.0, 0.0, 0.0]))  # axis in the face: e polarised along x
    N = np.array([[0.0, 0.0, 1.0]])
    d = np.array([[0.0, 0.0, 1.0]])
    s = np.array([[0.0, 1.0, 0.0]])
    for E, mode_power in ((np.array([[1.0, 0.0, 0.0]], complex), (0.0, 4 * ne / (1 + ne) ** 2)), (np.array([[0.0, 1.0, 0.0]], complex), (4 * no / (1 + no) ** 2, 0.0))):
        _, tr = interface_amplitudes(d, E, d, N, Side(n=1.0), Side(med=med), s)
        assert abs(tr[0][0][0]) ** 2 == pytest.approx(mode_power[0], abs=1e-12)
        assert abs(tr[1][0][0]) ** 2 == pytest.approx(mode_power[1], abs=1e-12)


# ---- the sequential trace ----------------------------------------------------------------


def test_calcite_plate_walk_off_and_displacement():
    """Optic axis at 45° to the face, normal incidence: the ordinary ray goes straight, the extraordinary
    ray walks off by tan(rho) = (no^2 - ne^2)/(no^2 + ne^2) (6.23° for calcite at 589.3 nm) and leaves
    displaced by t tan(rho), parallel to the incident ray; its optical path is n_e(45°) t."""
    no, ne = LIB.get("CALCITE").index(LAM), LIB.get("CALCITE").index_e(LAM)
    rho = math.atan((no**2 - ne**2) / (no**2 + ne**2))
    assert math.degrees(rho) == pytest.approx(6.2324, abs=1e-3)
    t = 10.0
    P0 = np.array([[0.0, 0.0, -1.0], [0.3, 0.2, -1.0]])
    D0 = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]])
    res = {}
    for mode in ("ordinary", "extraordinary"):
        cs = compile_system(_plate(axis=[1.0, 0.0, 1.0], mode=mode, t=t))
        r = trace(cs, 0, P0, D0, record=True)
        assert np.all(r.ok)
        res[mode] = r
        assert np.allclose(r.dirs, D0, atol=1e-12)
    dx = res["extraordinary"].points[:, 3, 0] - P0[:, 0]
    assert np.allclose(res["ordinary"].points[:, 3, :2], P0[:, :2], atol=1e-12)
    assert np.allclose(np.abs(dx), t * math.tan(rho), rtol=1e-10)
    assert np.allclose(res["extraordinary"].points[:, 3, 1], P0[:, 1], atol=1e-12)
    n45 = 1 / math.sqrt(0.5 / no**2 + 0.5 / ne**2)
    assert res["ordinary"].opl[0] - res["extraordinary"].opl[0] == pytest.approx((no - n45) * t, rel=1e-10)
    # inside: the ray direction leaves the wave normal (along z) by rho
    w = res["extraordinary"].dirs_after[0, 2, :]
    assert math.degrees(math.acos(w[2])) == pytest.approx(math.degrees(rho), abs=1e-9)


@pytest.mark.parametrize("alpha,theta_i", [(30.0, 20.0), (60.0, -35.0), (90.0, 45.0)])
def test_oblique_extraordinary_refraction_matches_an_independent_solution(alpha, theta_i):
    """Axis in the plane of incidence at alpha from the normal. Independent solution: the wave-normal angle
    theta_t solves n_e(theta_t - alpha) sin(theta_t) = sin(theta_i) (root finding); the ray then makes
    tan(psi_S) = (no^2 / ne^2) tan(psi_k) with the optic axis (psi angles from the axis)."""
    no, ne = LIB.get("CALCITE").index(LAM), LIB.get("CALCITE").index_e(LAM)
    a, ti = math.radians(alpha), math.radians(theta_i)

    def ne_of(psi):
        return 1 / math.sqrt(math.cos(psi) ** 2 / no**2 + math.sin(psi) ** 2 / ne**2)

    tt = brentq(lambda x: ne_of(x - a) * math.sin(x) - math.sin(ti), -math.pi / 2 + 1e-9, math.pi / 2 - 1e-9)
    psi_k = tt - a
    psi_s = math.atan2((no**2 / ne**2) * math.sin(psi_k), math.cos(psi_k))
    ts = a + psi_s
    cs = compile_system(_plate(axis=[math.sin(a), 0.0, math.cos(a)], mode="extraordinary", t=5.0))
    P0 = np.array([[0.0, 0.0, -1.0]])
    D0 = np.array([[math.sin(ti), 0.0, math.cos(ti)]])
    r = trace(cs, 0, P0, D0, record=True)
    assert r.ok[0]
    K = r.waves_after[0, 2, :]
    S = r.dirs_after[0, 2, :]
    assert math.atan2(K[0], K[2]) == pytest.approx(tt, abs=1e-10)
    assert np.linalg.norm(K) == pytest.approx(ne_of(psi_k), rel=1e-12)
    assert math.atan2(S[0], S[2]) == pytest.approx(ts, abs=1e-10)
    assert np.allclose(r.dirs[0], D0[0], atol=1e-12)


def test_isotropic_limit_of_a_crystal_equals_the_glass():
    """A 'crystal' with no = ne (the N-BK7 formula twice) traces and polarises exactly like N-BK7."""
    bk7 = LIB.get("N-BK7").dispersion
    rec = {"name": "ISOCRYST", "formula": "sellmeier", "coefficients": list(bk7.coefficients), "lambda_min": 0.3, "lambda_max": 2.5,
           "extraordinary": {"formula": "sellmeier", "coefficients": list(bk7.coefficients), "lambda_min": 0.3, "lambda_max": 2.5}}
    glass = compile_system(_plate("N-BK7"))
    cry = compile_system(_plate("ISOCRYST", axis=[1, 0.4, 0.7], mode="extraordinary"), custom_materials=[rec])
    P0 = np.array([[0.0, 0.0, -1.0], [0.5, 0.1, -1.0]])
    D0 = np.array([[0.1, 0.05, 1.0], [0.0, -0.2, 1.0]])
    D0 /= np.linalg.norm(D0, axis=1, keepdims=True)
    a, b = trace(glass, 0, P0, D0, fresnel=True), trace(cry, 0, P0, D0, fresnel=True)
    assert np.allclose(a.points[:, -1], b.points[:, -1], atol=1e-12)
    assert np.allclose(a.opl, b.opl, rtol=1e-13)
    assert np.allclose(a.intensity, b.intensity, rtol=1e-12)
    pa = polarization_pupil(glass, input_state="45", grid=5)
    pb = polarization_pupil(cry, input_state="45", grid=5, crystal_modes="sum")
    assert pb["summary"]["unpolarized_transmission"] == pytest.approx(pa["summary"]["unpolarized_transmission"], rel=1e-12)
    assert np.allclose(pa["retardance_waves"], pb["retardance_waves"], atol=1e-9)
    assert np.allclose(pa["summary"]["mueller"], pb["summary"]["mueller"], atol=1e-9)


def test_paraxial_index_of_the_extraordinary_wave_is_its_index_along_the_axis():
    no, ne = LIB.get("CALCITE").index(LAM), LIB.get("CALCITE").index_e(LAM)
    assert compile_system(_plate(axis=[0, 0, 1], mode="extraordinary")).n_after[0, 2] == pytest.approx(no, rel=1e-14)
    assert compile_system(_plate(axis=[1, 0, 0], mode="extraordinary")).n_after[0, 2] == pytest.approx(ne, rel=1e-14)
    assert compile_system(_plate(axis=[1, 0, 0], mode=None)).n_after[0, 2] == pytest.approx(no, rel=1e-14)
    codes = [d.code for d in compile_system(_plate(axis=[1, 0, 0])).diagnostics]
    assert "BIREFRINGENT" in codes


def test_invalid_crystal_layouts_are_refused():
    with pytest.raises(SystemError_, match="object or image space"):
        compile_system(make_system([{"thickness": 10.0, "material": "CALCITE"}, {"thickness": 5.0, "is_stop": True}, {}], wavelengths=[{"value": LAM}], aperture={"type": "epd", "value": 1.0}))
    with pytest.raises(SystemError_, match="cannot border"):
        compile_system(make_system([{"thickness": None}, {"thickness": 5.0, "is_stop": True, "material": "CALCITE"}, {"thickness": -5.0, "material": "MIRROR"}, {"thickness": -10.0}, {}], wavelengths=[{"value": LAM}], aperture={"type": "epd", "value": 1.0}))
    with pytest.raises(SystemError_, match="polarising element"):
        compile_system(make_system([{"thickness": None}, {"thickness": 5.0, "is_stop": True}, {"thickness": 2.0, "material": "CALCITE", "jones": {"kind": "polarizer"}}, {"thickness": 10.0}, {}], wavelengths=[{"value": LAM}], aperture={"type": "epd", "value": 1.0}))


# ---- wave plates, polarisers, Mueller ---------------------------------------------------


def _quartz_dn(lam=LAM):
    q = LIB.get("QUARTZ")
    return q.index_e(lam) - q.index(lam)


def test_quartz_quarter_wave_plate():
    """Zero-order quartz plate of thickness lambda / (4 (ne - no)) with the axis in the face: retardance 0.25
    waves over the whole pupil; 45° linear light leaves circular (S3 = -1, the slow e wave delayed by
    exp(+i pi/2)); x light stays x. The same as an ideal retarder of 0.25 waves with the fast axis along y."""
    t = LAM * 1e-3 / (4 * _quartz_dn())
    cs = compile_system(_plate("QUARTZ", t=t, axis=[1, 0, 0]))
    r45 = polarization_pupil(cs, input_state="45", grid=7)
    sm = r45["summary"]
    assert sm["max_retardance_waves"] == pytest.approx(0.25, abs=1e-8)
    assert sm["rms_retardance_waves"] == pytest.approx(0.25, abs=1e-8)
    assert sm["output_stokes"][3] == pytest.approx(-1.0, abs=2e-6)
    assert sm["wave_separation_mm"] == pytest.approx(0.0, abs=1e-12)
    assert sm["wave_combinations"] == 2
    rx = polarization_pupil(cs, input_state="x", grid=5)["summary"]
    assert rx["output_stokes"][1] == pytest.approx(1.0, abs=1e-12)
    # an ideal retarder in air does the same (without the plate's Fresnel diattenuation)
    ideal = compile_system(make_system([{"thickness": None}, {"thickness": 5.0, "is_stop": True, "jones": {"kind": "retarder", "angle_deg": 90.0, "retardance_waves": 0.25}}, {"thickness": 20.0}, {}], wavelengths=[{"value": LAM}], aperture={"type": "epd", "value": 2.0}))
    si = polarization_pupil(ideal, input_state="45", grid=5)["summary"]
    assert np.allclose(si["output_stokes"], [1, 0, 0, -1], atol=1e-12)
    assert np.allclose(si["output_stokes"], sm["output_stokes"], atol=2e-3)
    # the prescription mode follows one wave only: no retardance, half the power for 45° light
    one = polarization_pupil(cs, input_state="45", grid=5, crystal_modes="prescription")["summary"]
    assert one["max_retardance_waves"] == pytest.approx(0.0, abs=1e-9)
    assert one["input_transmission"] == pytest.approx(0.5 * rx["input_transmission"] * (4 * LIB.get("QUARTZ").index(LAM) / (1 + LIB.get("QUARTZ").index(LAM)) ** 2) ** 2 / (4 * LIB.get("QUARTZ").index_e(LAM) / (1 + LIB.get("QUARTZ").index_e(LAM)) ** 2) ** 2, rel=1e-9)


def test_half_wave_plate_rotates_linear_light_by_twice_its_axis_angle():
    t = LAM * 1e-3 / (2 * _quartz_dn())
    c = math.radians(22.5)
    cs = compile_system(_plate("QUARTZ", t=t, axis=[math.cos(c), math.sin(c), 0.0]))
    S = polarization_pupil(cs, input_state="x", grid=5)["summary"]["output_stokes"]
    assert S[2] == pytest.approx(1.0, abs=2e-3)  # linear at 45°
    assert abs(S[3]) < 1e-9


@pytest.mark.parametrize("angle", [0.0, 30.0, 60.0, 90.0, 135.0])
def test_malus_law(angle):
    cs = compile_system(make_system([{"thickness": None}, {"thickness": 5.0, "is_stop": True, "jones": {"kind": "polarizer", "angle_deg": angle}}, {"thickness": 20.0}, {}], wavelengths=[{"value": LAM}], aperture={"type": "epd", "value": 2.0}))
    sm = polarization_pupil(cs, input_state="x", grid=5)["summary"]
    assert sm["input_transmission"] == pytest.approx(math.cos(math.radians(angle)) ** 2, abs=1e-12)
    assert sm["unpolarized_transmission"] == pytest.approx(0.5, abs=1e-12)
    assert sm["max_diattenuation"] == pytest.approx(1.0, abs=1e-12)


def test_crossed_polarisers_with_a_quarter_wave_plate_between():
    def system(*jones):
        surfs = [{"thickness": None}, {"thickness": 5.0, "is_stop": True}]
        for j in jones:
            surfs.append({"thickness": 2.0, "jones": j})
        surfs += [{"thickness": 20.0}, {}]
        return compile_system(make_system(surfs, wavelengths=[{"value": LAM}], aperture={"type": "epd", "value": 2.0}))

    crossed = polarization_pupil(system({"kind": "polarizer", "angle_deg": 0}, {"kind": "polarizer", "angle_deg": 90}), input_state="unpolarized", grid=5)
    assert crossed["summary"]["unpolarized_transmission"] == pytest.approx(0.0, abs=1e-15)
    qwp = polarization_pupil(system({"kind": "polarizer", "angle_deg": 0}, {"kind": "retarder", "angle_deg": 45, "retardance_waves": 0.25}, {"kind": "polarizer", "angle_deg": 90}), input_state="unpolarized", grid=5)
    assert qwp["summary"]["unpolarized_transmission"] == pytest.approx(0.25, abs=1e-12)  # 1/2 x circular through a polariser


def test_mueller_matrices_of_standard_elements_and_depolarisation():
    assert np.allclose(mueller(np.array([[[1, 0], [0, 0]]], complex))[0], 0.5 * np.array([[1, 1, 0, 0], [1, 1, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]), atol=1e-15)
    # quarter-wave plate, fast axis x (slow y delayed): 45° linear -> S3 = +1
    M = mueller(np.array([[[1, 0], [0, 1j]]]))[0]
    assert np.allclose(M, [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, -1], [0, 0, 1, 0]], atol=1e-15)
    assert depolarization_index(M) == pytest.approx(1.0, abs=1e-12)
    rot = mueller(np.array([[[math.cos(0.3), -math.sin(0.3)], [math.sin(0.3), math.cos(0.3)]]]))[0]
    assert depolarization_index(rot) == pytest.approx(1.0, abs=1e-12)
    # incoherent average of orthogonal polarisers: a partial depolariser with DI = 1/sqrt(3)
    avg = 0.5 * (mueller(np.array([[[1, 0], [0, 0]]], complex))[0] + mueller(np.array([[[0, 0], [0, 1]]], complex))[0])
    assert depolarization_index(avg) == pytest.approx(1 / math.sqrt(3), abs=1e-12)
    # the system's pupil-averaged Mueller matrix of a polariser at 0°
    cs = compile_system(make_system([{"thickness": None}, {"thickness": 5.0, "is_stop": True, "jones": {"kind": "polarizer", "angle_deg": 0}}, {"thickness": 20.0}, {}], wavelengths=[{"value": LAM}], aperture={"type": "epd", "value": 2.0}))
    sm = polarization_pupil(cs, input_state="unpolarized", grid=5)["summary"]
    assert np.allclose(sm["mueller"], 0.5 * np.array([[1, 1, 0, 0], [1, 1, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]), atol=1e-12)
    assert sm["output_dop"] == pytest.approx(1.0, abs=1e-12)


def test_fast_lens_depolarises_slightly_and_stays_near_identity():
    from opticore.samples import get_sample

    cs = compile_system(get_sample("achromat").system)
    sm = polarization_pupil(cs, input_state="x", grid=7)["summary"]
    M = np.array(sm["mueller"]) / sm["mueller"][0][0]
    assert np.allclose(M, np.eye(4), atol=0.02)
    assert 0.98 < sm["depolarization_index"] <= 1.0 + 1e-12


def test_polarization_api_with_crystal_waves():
    from fastapi.testclient import TestClient

    from opticore.api.main import app

    client = TestClient(app)
    t = LAM * 1e-3 / (4 * _quartz_dn())
    body = {"system": _plate("QUARTZ", t=t, axis=[1, 0, 0]).model_dump(mode="json"), "input": "45", "grid": 5}
    both = client.post("/api/v1/analysis/polarization", json=body).json()
    one = client.post("/api/v1/analysis/polarization", json={**body, "crystal_modes": "prescription"}).json()
    assert both["summary"]["max_retardance_waves"] == pytest.approx(0.25, abs=1e-8)
    assert one["summary"]["max_retardance_waves"] == pytest.approx(0.0, abs=1e-9)
    assert both["crystals"][0]["material"] == "QUARTZ" and both["summary"]["wave_combinations"] == 2
    assert client.post("/api/v1/analysis/polarization", json={**body, "crystal_modes": "both"}).status_code == 422
