"""Validation of wavefront, PSF and MTF against analytic diffraction theory."""

import math

import numpy as np
import pytest

from opticore.analysis.diffraction import diffraction_limited_mtf, geometric_encircled_energy, mtf, psf
from opticore.analysis.wavefront import fit_zernike, fringe_nm, opd_fan, pupil_grid, wavefront_map, wavefront_samples, zernike
from opticore.paraxial import paraxial_data, seidel_coefficients
from opticore.raytrace import trace_pupil
from opticore.samples import achromat, singlet
from opticore.system import compile_system

from .conftest import make_system

ND = 0.5875618


def paraboloid(epd=20.0, defocus=0.0):
    return make_system(
        [
            {"thickness": None},
            {"radius": None, "thickness": 50.0, "is_stop": True},
            {"radius": -200.0, "conic": -1.0, "thickness": -100.0 - defocus, "material": "MIRROR"},
            {},
        ],
        wavelengths=[{"value": ND}],
        aperture={"type": "epd", "value": epd},
    )


def test_perfect_system_has_zero_wavefront_error():
    m = wavefront_map(compile_system(paraboloid(60.0)), 0, 0, grid=32)
    assert m["valid_fraction"] == 1.0
    assert m["rms_waves"] < 1e-9 and m["pv_waves"] < 1e-9
    assert m["strehl_marechal"] == pytest.approx(1.0, abs=1e-12)


def test_spherical_aberration_matches_seidel_W040():
    """Edge OPD at the paraxial focus equals W040 = S_I / 8 (third order, small aperture)."""
    sys = make_system(
        [{"thickness": None}, {"radius": 60.0, "thickness": 4.0, "material": "N-BK7", "is_stop": True}, {"radius": None, "thickness": 100.0}, {}],
        wavelengths=[{"value": ND}],
        aperture={"type": "epd", "value": 4.0},
    )
    pd = paraxial_data(compile_system(sys))
    sys.surfaces[2].thickness = pd.paraxial_image_distance
    cs = compile_system(sys)
    sd = seidel_coefficients(cs)
    W, _, _ = wavefront_samples(cs, 0, 0, np.array([0.0, 0.0]), np.array([1.0, 0.5]))
    w040 = sd["total"]["SI"] / 8 / (ND * 1e-3)
    assert W[0] == pytest.approx(w040, rel=0.005)
    assert W[1] == pytest.approx(w040 / 16, rel=0.01)  # rho^4 dependence


def test_defocus_wavefront_and_sign():
    """Moving the image surface by dz beyond focus gives W = W020 rho^2, W020 = dz / (8 F#^2) > 0."""
    dz = 0.05
    cs = compile_system(paraboloid(20.0, defocus=dz))
    fn = 5.0
    W, _, _ = wavefront_samples(cs, 0, 0, np.array([0.0, 0.0]), np.array([1.0, 0.5]))
    w020 = dz / (8 * fn**2) / (ND * 1e-3)
    assert W[0] == pytest.approx(w020, rel=0.01)
    assert W[1] == pytest.approx(w020 / 4, rel=0.01)
    m = wavefront_map(cs, 0, 0, grid=48)
    z4 = next(t for t in m["zernike"]["terms"] if t["index"] == 4)
    assert z4["value"] == pytest.approx(w020 / 2, rel=0.02)  # Fringe Z4 = 2 rho^2 - 1


def test_perfect_psf_strehl_airy_and_encircled_energy():
    cs = compile_system(paraboloid(20.0))
    p = psf(cs, 0, 0, grid=64, pad=4)
    assert p["strehl"] == pytest.approx(1.0, abs=1e-9)
    assert p["working_fnum"] == pytest.approx(5.0, rel=1e-9)
    r = np.array(p["encircled_energy"]["radius_um"])
    f = np.array(p["encircled_energy"]["fraction"])
    # Airy pattern: 83.8 % of the energy inside the first dark ring
    assert np.interp(p["airy_radius_um"], r, f) == pytest.approx(0.838, abs=0.01)


def test_diffraction_mtf_matches_analytic_circular_pupil():
    cs = compile_system(paraboloid(20.0))
    m = mtf(cs, samples=21, grid=64, pad=4)
    nu = np.array(m["frequency_cyc_per_mm"])
    cut = 1.0 / (ND * 1e-3 * 5.0)
    assert m["cutoff_cyc_per_mm"][0] == pytest.approx(cut, rel=1e-9)
    ref = diffraction_limited_mtf(nu, cut)
    for k in ("tangential", "sagittal"):
        assert np.max(np.abs(np.array(m["fields"][0][k]) - ref)) < 0.005


def test_marechal_agrees_with_fft_strehl_for_small_aberration():
    cs = compile_system(paraboloid(20.0, defocus=0.012))
    wm = wavefront_map(cs, 0, 0, grid=64)
    assert 0.02 < wm["rms_waves"] < 0.08
    p = psf(cs, 0, 0, grid=64, pad=4)
    assert p["strehl"] == pytest.approx(wm["strehl_marechal"], rel=0.02)


def test_psf_centroid_equals_mean_ray_position():
    """Fraunhofer theory: the PSF centroid equals the mean transverse ray error
    (pupil-area weighted). Agreement is limited by the linear entrance-to-exit
    pupil mapping assumed by the FFT method (pupil aberration)."""
    cs = compile_system(singlet().system)
    p = psf(cs, 1, 1, grid=64, pad=4)
    X, Y, ins = pupil_grid(64)
    r = trace_pupil(cs, 1, 1, X[ins], Y[ins])
    ch = trace_pupil(cs, 1, 1, np.array([0.0]), np.array([0.0]))
    g = (r.image_xy()[r.ok].mean(0) - ch.image_xy()[0]) * 1e3
    assert abs(g[1]) > 0.5  # non-trivial coma
    assert p["centroid_um"][1] == pytest.approx(g[1], rel=0.03)
    assert abs(p["centroid_um"][0]) < 1e-6


def test_zernike_fit_recovers_synthetic_coefficients():
    X, Y, ins = pupil_grid(48)
    rho = np.hypot(X[ins], Y[ins])
    th = np.arctan2(Y[ins], X[ins])
    truth = {4: 0.3, 7: -0.12, 9: 0.05, 12: 0.02}
    nm = fringe_nm(37)
    W = sum(c * zernike(*nm[j - 1], rho, th) for j, c in truth.items())
    fit = fit_zernike(X[ins], Y[ins], W, 37)
    for t in fit["terms"]:
        assert t["value"] == pytest.approx(truth.get(t["index"], 0.0), abs=1e-10)
    assert fit["fit_residual_rms_waves"] < 1e-12


def test_fringe_ordering():
    nm = fringe_nm(37)
    assert nm[:9] == [(0, 0), (1, 1), (1, -1), (2, 0), (2, 2), (2, -2), (3, 1), (3, -1), (4, 0)]
    assert nm[15] == (6, 0) and nm[24] == (8, 0) and nm[35] == (10, 0) and nm[36] == (12, 0)


def test_opd_fan_and_geometric_quantities_run():
    cs = compile_system(achromat(True).system)
    fan = opd_fan(cs, samples=9)
    assert fan["fields"][0]["per_wavelength"][1]["tangential_waves"][4] == pytest.approx(0.0, abs=1e-9)
    g = mtf(cs, kind="geometric", samples=9)
    assert g["fields"][0]["tangential"][0] == pytest.approx(1.0)
    ee = geometric_encircled_energy(cs, 0)
    assert ee["fraction"][-1] == pytest.approx(1.0)
    d = mtf(cs, samples=9)
    dl = np.array(d["diffraction_limit"])
    for f in d["fields"]:
        assert np.all(np.array(f["tangential"]) <= dl + 0.02)  # never better than the diffraction limit


def test_polychromatic_mtf_includes_lateral_colour():
    """A rear-stop singlet off axis has strong lateral colour: the polychromatic
    MTF cannot exceed the lateral-colour bound |sum w exp(-2 pi i nu dy)| / sum w."""
    sys = make_system(
        [
            {"thickness": None},
            {"radius": 51.68, "thickness": 5.0, "material": "N-BK7"},
            {"radius": None, "thickness": 10.0},
            {"radius": None, "thickness": 86.7, "is_stop": True},
            {},
        ],
        wavelengths=[{"value": 0.4861327}, {"value": ND}, {"value": 0.6562725}],
        primary_wavelength=1,
        fields=[{"y": 5.0}],
        aperture={"type": "epd", "value": 2.0},
    )
    cs = compile_system(sys)
    ys = [trace_pupil(cs, w, 0, np.array([0.0]), np.array([0.0])).image_xy()[0, 1] for w in range(3)]
    assert abs(ys[2] - ys[0]) > 0.005  # > 5 um of lateral colour
    m = mtf(cs, samples=11, max_frequency=20.0)  # cutoff ~34 cyc/mm at F/50
    nu = np.array(m["frequency_cyc_per_mm"])
    bound = np.abs(np.mean([np.exp(-2j * math.pi * nu * (y - ys[1])) for y in ys], axis=0))
    assert bound[-1] < 0.9  # lateral colour matters at 20 cyc/mm
    assert np.all(np.array(m["fields"][0]["tangential"]) <= bound + 1e-9)
