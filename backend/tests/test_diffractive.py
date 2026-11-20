import math

import numpy as np
import pytest

from opticore.analysis.wavefront import wavefront_map
from opticore.paraxial import compute_pupil, paraxial_data
from opticore.raytrace import launch, trace
from opticore.surfaces import EVANESCENT, OK
from opticore.system import compile_system

from .conftest import make_system

LAM = 0.55  # um


def _grating_system(freq, order=1, material="AIR", tilt=0.0, mirror=False, wl=LAM):
    surfs = [{"id": "obj", "thickness": None}, {"id": "ap", "thickness": 10.0, "is_stop": True}]
    if tilt:
        surfs.append({"id": "cb", "type": "coordinate_break", "tilt_x": tilt})
    surfs.append({"id": "g", "thickness": -20.0 if mirror else 20.0, "material": "MIRROR" if mirror else material, "grating_frequency": freq, "diffraction_order": order})
    surfs.append({"id": "img"})
    return make_system(surfs, wavelengths=[{"value": wl}], aperture={"type": "epd", "value": 2.0})


def _chief_dir(cs):
    pupil = compute_pupil(cs)
    P0, D0, opl = launch(cs, 0, 0, np.array([0.0]), np.array([0.0]), pupil)
    r = trace(cs, 0, P0, D0, opl, record=True)
    return r, r.dirs_after[0, 3 if cs.is_cb[2] else 2]


@pytest.mark.parametrize("freq,order", [(300.0, 1), (600.0, -1), (1200.0, 1), (500.0, 2)])
def test_transmission_grating_at_normal_incidence(freq, order):
    cs = compile_system(_grating_system(freq, order))
    r, d = _chief_dir(cs)
    assert r.ok[0]
    s = order * LAM * 1e-3 * freq
    assert d[1] == pytest.approx(s, abs=1e-13)  # sin(theta_m) = m lambda f (grating vector along local y)
    assert d[0] == pytest.approx(0.0, abs=1e-15)


def test_grating_equation_at_oblique_incidence_into_glass():
    tilt = 20.0
    cs = compile_system(_grating_system(400.0, 1, "N-BK7", tilt=tilt))
    r, d = _chief_dir(cs)
    n = cs.n_after[0, 3]
    frame = cs.frames[3]
    dl = frame.to_local_dirs(d[None, :])[0]  # direction in the grating's local frame
    din = frame.to_local_dirs(np.array([[0.0, 0.0, 1.0]]))[0]
    # n sin(theta_m) - sin(theta_i) = m lambda f  (tangential y components)
    assert n * dl[1] - din[1] == pytest.approx(1 * LAM * 1e-3 * 400.0, abs=1e-13)


def test_reflection_grating_littrow_retroreflects():
    f, m = 1200.0, 1
    theta = math.degrees(math.asin(m * LAM * 1e-3 * f / 2))  # Littrow: 2 sin(theta) = m lambda f
    cs = compile_system(_grating_system(f, -m, tilt=theta, mirror=True))
    r, d = _chief_dir(cs)
    assert r.ok[0]
    assert np.allclose(d, [0.0, 0.0, -1.0], atol=1e-12)  # diffracted straight back towards the source


def test_order_zero_equals_no_grating_and_evanescent_orders_fail():
    a = compile_system(_grating_system(800.0, 0, "N-BK7"))
    b = compile_system(_grating_system(0.0, 1, "N-BK7"))
    _, da = _chief_dir(a)
    _, db = _chief_dir(b)
    assert np.allclose(da, db, atol=1e-15)
    cs = compile_system(_grating_system(2500.0, 1))  # lambda f = 1.375 > 1 in air: evanescent
    r, _ = _chief_dir(cs)
    assert r.status[0] == EVANESCENT


def _doe_lens(A, R=5.0, m=1, wl=LAM, length=100.0, epd=10.0):
    return make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "doe", "thickness": length, "is_stop": True, "phase_coefficients": A, "phase_norm_radius": R, "diffraction_order": m},
            {"id": "img"},
        ],
        wavelengths=[{"value": wl}],
        aperture={"type": "epd", "value": epd},
    )


def test_diffractive_lens_paraxial_power_and_dispersion():
    R, A1 = 5.0, -300.0
    f0 = -math.pi * R * R / (1 * LAM * 1e-3 * A1)
    pd = paraxial_data(compile_system(_doe_lens([A1], R)))
    assert pd.efl == pytest.approx(f0, rel=1e-12)
    # diffractive power scales with the wavelength: f(lambda) = f0 lambda0 / lambda
    pd2 = paraxial_data(compile_system(_doe_lens([A1], R, wl=0.65)))
    assert pd2.efl == pytest.approx(f0 * LAM / 0.65, rel=1e-12)
    # second order doubles the power
    assert paraxial_data(compile_system(_doe_lens([A1], R, m=2))).efl == pytest.approx(f0 / 2, rel=1e-12)


def _ideal_coeffs(f_mm, R, lam_um, n_terms=6):
    """Series of phi(r) = -(2 pi / lambda)(sqrt(r^2 + f^2) - f) in (r/R)^2."""
    lam = lam_um * 1e-3
    out = []
    for i in range(1, n_terms + 1):
        # sqrt(f^2 + x) - f = sum_i binom(1/2, i) x^i f^(1-2i), x = r^2
        b = math.comb(2 * i, i) * (-1) ** (i + 1) / ((1 - 2 * i) * 4**i) * -1
        out.append(-(2 * math.pi / lam) * b * f_mm ** (1 - 2 * i) * R ** (2 * i))
    return out


def test_ideal_diffractive_lens_focuses_on_axis_without_aberration():
    f, R = 100.0, 5.0
    A = _ideal_coeffs(f, R, LAM)
    cs = compile_system(_doe_lens(A, R, length=f))
    assert paraxial_data(cs).efl == pytest.approx(f, rel=1e-12)
    pupil = compute_pupil(cs)
    rho = np.linspace(-1, 1, 21)
    P0, D0, opl = launch(cs, 0, 0, 0 * rho, rho, pupil)
    r = trace(cs, 0, P0, D0, opl)
    assert np.all(r.status == OK)
    assert np.max(np.abs(r.image_xy()[:, 1])) < 1e-6  # all zones focus at f (truncated series)
    # OPL includes the diffractive phase: the wavefront at the focus is flat
    wf = wavefront_map(cs, 0, None, 32)
    assert wf["rms_waves"] < 1e-3


def test_fresnel_on_diffractive_refracting_interface_is_counted():
    cs = compile_system(_grating_system(300.0, 1, "N-BK7"))
    pupil = compute_pupil(cs)
    P0, D0, opl = launch(cs, 0, 0, np.array([0.0]), np.array([0.0]), pupil)
    r = trace(cs, 0, P0, D0, opl, fresnel=True)
    n = cs.n_after[0, 2]
    assert r.intensity[0] < 1.0 and r.intensity[0] > 1 - 2 * ((n - 1) / (n + 1)) ** 2


def test_hybrid_achromat_optimisation_matches_thin_lens_condition():
    """Optimising A1 of a DOE on a BK7 singlet for zero F-C axial colour
    reproduces the thin-lens hybrid achromat condition
    (n_F - n_C)(c1 - c2) = (lambda_F - lambda_C) A1 / (pi R^2)."""
    from opticore.materials import LAMBDA_C, LAMBDA_D, LAMBDA_F
    from opticore.optimize import OptimizationSpec, optimize

    R = 10.0
    system = make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "s1", "radius": 100.0, "thickness": 1.0, "material": "N-BK7", "is_stop": True},
            {"id": "s2", "radius": -100.0, "thickness": 95.0, "phase_coefficients": [0.0], "phase_norm_radius": R},
            {"id": "img"},
        ],
        wavelengths=[{"value": LAMBDA_F}, {"value": LAMBDA_D}, {"value": LAMBDA_C}],
        primary_wavelength=1,
        aperture={"type": "epd", "value": 4.0},
    )
    spec = OptimizationSpec.model_validate(
        {"variables": [{"surface_id": "s2", "parameter": "phase_1", "min": -2000, "max": 2000}], "operands": [{"type": "axial_color", "target": 0.0}], "algorithm": "local"}
    )
    res = optimize(system, spec)
    a1 = res["variables"][0]["final"]
    cs = compile_system(system)
    dn = cs.n_after[0, 1] - cs.n_after[2, 1]
    a1_thin = dn * (2 / 100.0) * math.pi * R * R / ((LAMBDA_F - LAMBDA_C) * 1e-3)
    assert res["final_merit"] < 1e-7  # mm of F-C focal shift
    assert a1 == pytest.approx(a1_thin, rel=0.02)  # thin-lens estimate; lens is 1 mm thick
    assert res["system"]["surfaces"][2]["phase_coefficients"] == [a1]  # applied to a copy, original untouched
    assert system.surfaces[2].phase_coefficients == [0.0]


def test_diffractive_variables_are_rejected_on_coordinate_breaks():
    from opticore.optimize import OptimizationSpec
    from opticore.optimize.merit import MeritFunction

    system = _grating_system(300.0, tilt=5.0)
    spec = OptimizationSpec.model_validate({"variables": [{"surface_id": "cb", "parameter": "grating_frequency"}], "operands": [{"type": "efl", "target": 50}]})
    with pytest.raises(ValueError, match="diffractive variables"):
        MeritFunction(system, spec)


def test_chromatic_focal_shift_of_a_diffractive_lens_follows_f_proportional_to_inverse_wavelength():
    from opticore.analysis.aberrations import chromatic_focal_shift

    R, A1, L = 5.0, -300.0, 100.0
    cs = compile_system(_doe_lens([A1], R, length=L))
    f0 = -math.pi * R * R / (LAM * 1e-3 * A1)
    res = chromatic_focal_shift(cs, 0.45, 0.65, samples=5)
    for lam, shift in zip(res["wavelength_um"], res["focal_shift_um"]):
        assert shift == pytest.approx((f0 * LAM / lam - f0) * 1e3, rel=1e-10, abs=1e-9)
