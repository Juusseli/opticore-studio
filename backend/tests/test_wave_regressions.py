"""Regression tests for audited defects in the wave, polarisation, non-sequential, coating and
Gaussian-beam analyses.

References (independent of the code under test):
  * MTF cuts: rotating the field of a rotationally symmetric lens about the axis rotates its image;
    the tangential (along the field) and sagittal MTF must not change. A square pixel's transfer
    function along a cut by direct numerical Fourier integration of the box.
  * FFT sampling: the converged FFT PSF (fine grid) and the Huygens PSF.
  * Bulk absorption: (1 - R)^2 exp(-alpha L) of a window, alpha from the catalogue internal
    transmittance at the ray's wavelength, R the normal-incidence Fresnel reflectance.
  * Element temperature: the sequential trace of the same rays (glass index at its element's
    temperature).
  * Mirror retardance: an ideal mirror retards nothing; a metal mirror retards by the s-p phase
    arg(r_p / -r_s) of the textbook (Born & Wolf) Fresnel amplitudes.
  * POP / BPM: the paraxial Gaussian beam w(z) = w0 sqrt(1 + (z / z_R)^2) and the ABCD law.
  * Gaussian beam through an ideal lens: Self's thin-lens waist transformation (Appl. Opt. 22, 658,
    1983).
"""

from __future__ import annotations

import cmath
import math

import numpy as np
import pytest

from opticore.analysis import diffraction, huygens
from opticore.analysis.coatings import coating_performance
from opticore.analysis.gaussian import gaussian_beam
from opticore.analysis.throughput import transmission
from opticore.materials import MaterialLibrary
from opticore.model import OpticalSystem
from opticore.nonseq import build_scene, trace_nonsequential
from opticore.nssources import Detector, LightSource
from opticore.paraxial import compute_pupil
from opticore.polarization import jones_properties, jones_pupil, polarization_pupil
from opticore.raytrace import launch, trace
from opticore.samples import get_sample
from opticore.system import compile_system
from opticore.wave.bpm import bpm
from opticore.wave.pop import gaussian_q, physical_optics

LAM_POP = 1.55e-3


# ----------------------------------------------------------------------------- MTF cuts
def _cooke(mode: str):
    """Cooke triplet with its y fields turned about the axis: 'x' (90 deg), 'd45' (45 deg), '-y'.
    Angle fields rotate exactly as their tangents: tan(theta_x) = tan(theta) u_x, tan(theta_y) = tan(theta) u_y."""
    d = get_sample("cooke-triplet").system.model_dump()
    for f in d["fields"]:
        th = f["y"]
        if mode == "x":
            f["x"], f["y"] = th, 0.0
        elif mode == "d45":
            a = math.degrees(math.atan(math.tan(math.radians(th)) / math.sqrt(2.0)))
            f["x"], f["y"] = a, a
        elif mode == "-y":
            f["y"] = -th
    return compile_system(OpticalSystem.model_validate(d))


@pytest.mark.parametrize("kind", ["diffraction", "geometric"])
def test_mtf_tangential_and_sagittal_follow_the_field_direction(kind):
    """Before the fix T and S were the y and x frequency cuts: for the x field they were swapped
    (field 3 at 20 c/mm: y field T 0.4623 S 0.5127, x field T 0.5127 S 0.4623) and for the 45 deg field
    both were wrong (0.4195 / 0.4195)."""
    ref = diffraction.mtf(_cooke("y"), kind=kind, max_frequency=20.0, samples=5, grid=32)
    for mode in ("x", "d45", "-y"):
        m = diffraction.mtf(_cooke(mode), kind=kind, max_frequency=20.0, samples=5, grid=32)
        for fy, fm in zip(ref["fields"], m["fields"]):
            assert fm["tangential"] == pytest.approx(fy["tangential"], abs=1e-8)
            assert fm["sagittal"] == pytest.approx(fy["sagittal"], abs=1e-8)
    f3 = ref["fields"][2]
    assert abs(f3["tangential"][-1] - f3["sagittal"][-1]) > 0.03  # astigmatic field: the cut matters
    if kind == "diffraction":
        assert f3["tangential"][-1] == pytest.approx(0.4624, abs=2e-4)
        assert f3["sagittal"][-1] == pytest.approx(0.5126, abs=2e-4)
    d45 = diffraction.mtf(_cooke("d45"), kind=kind, max_frequency=20.0, samples=2, grid=32)
    r = 1 / math.sqrt(2.0)
    assert d45["fields"][2]["tangential_direction"] == pytest.approx([r, r], abs=1e-12)
    assert d45["fields"][2]["sagittal_direction"] == pytest.approx([r, -r], abs=1e-12)
    assert ref["fields"][0]["tangential_direction"] == [0.0, 1.0]  # on axis: T is the y cut, as before


def test_pixel_mtf_along_a_cut_matches_the_box_fourier_integral():
    w = 0.004  # mm
    n = 801
    x = (np.arange(n) + 0.5) / n * w - w / 2
    X, Y = np.meshgrid(x, x)
    for phi in (0.0, math.pi / 6, math.pi / 4, math.pi / 2):
        e = (math.cos(phi), math.sin(phi))
        for nu in (50.0, 120.0, 200.0):
            ref = abs(np.exp(-2j * math.pi * nu * (X * e[0] + Y * e[1])).mean())
            assert diffraction.pixel_mtf_along(nu, w, e) == pytest.approx(ref, abs=2e-6)


# ----------------------------------------------------------------------------- FFT sampling
def _defocused_singlet():
    d = get_sample("singlet").system.model_dump()
    d["surfaces"][2]["thickness"] += 4.0
    return compile_system(OpticalSystem.model_validate(d))


def test_fft_psf_and_mtf_warn_when_the_pupil_is_undersampled():
    """Singlet defocused by 4 mm, on axis: at grid 32 the wavefront changes by ~1 wave per sample and
    the PSF wraps around its FFT window (Strehl 0.0079 against 0.0014 converged, MTF 0.07 against
    0.0004), which was reported without any warning."""
    cs = _defocused_singlet()
    coarse = diffraction.psf(cs, 0, grid=32, pad=4)
    assert coarse["sampling"]["max_pupil_phase_step_waves"] == pytest.approx(1.02, abs=0.02)
    assert any("Pupil under-sampled" in w for w in coarse["warnings"])
    assert any("wraps around" in w for w in coarse["warnings"])
    assert coarse["sampling"]["geometric_extent_um"] > 0.5 * coarse["sampling"]["window_um"]
    m = diffraction.mtf(cs, fields=[0], samples=4, grid=32)
    assert any("Pupil under-sampled" in w for w in m["warnings"])
    fine = diffraction.psf(cs, 0, grid=256, pad=4)
    assert fine["warnings"] == []
    assert diffraction.mtf(cs, fields=[0], samples=4, grid=256)["warnings"] == []
    # the converged FFT result agrees with the independent Huygens summation, the coarse one does not
    h = huygens.huygens_psf(cs, 0, pupil_samples=128, image_samples=65)
    assert h["warnings"] == []
    assert fine["strehl"] == pytest.approx(h["strehl"], rel=0.05)
    assert coarse["strehl"] > 3 * h["strehl"]


def test_fft_sampling_warnings_only_where_the_result_is_off():
    """Singlet: at grid 64 every field and wavelength is sampled (no warnings, the MTF agrees with grid 128);
    at grid 32 the blue wavefront of the outer field changes by 0.72 waves per sample and its MTF at the
    highest frequency is 0.020 against 0.0009 converged: only that field is flagged."""
    cs = compile_system(get_sample("singlet").system)
    for f in range(3):
        p = diffraction.psf(cs, f, grid=32)
        assert p["warnings"] == [] and p["sampling"]["max_pupil_phase_step_waves"] < 0.5
    m64 = diffraction.mtf(cs, grid=64, samples=6)
    m128 = diffraction.mtf(cs, grid=128, samples=6)
    assert m64["warnings"] == [] and m128["warnings"] == []
    for a, b in zip(m64["fields"], m128["fields"]):
        assert a["tangential"] == pytest.approx(b["tangential"], abs=2e-3)
    m32 = diffraction.mtf(cs, grid=32, samples=6)
    assert len(m32["warnings"]) == 1 and m32["warnings"][0].startswith("Field 3:")
    assert abs(m32["fields"][2]["tangential"][-1] - m128["fields"][2]["tangential"][-1]) > 0.01


# ----------------------------------------------------------------------------- non-sequential media
def _window(lam_sys: float, catalog: bool):
    return OpticalSystem.model_validate(
        {
            "surfaces": [
                {"id": "o", "thickness": None},
                {"id": "a", "thickness": 50.0, "material": "N-BK7", "is_stop": True, "semi_diameter": 5.0},
                {"id": "b", "thickness": 10.0, "semi_diameter": 5.0},
                {"id": "img", "thickness": 0.0},
            ],
            "wavelengths": [{"value": lam_sys}],
            "aperture": {"type": "epd", "value": 4.0},
            "catalog_absorption": catalog,
        }
    )


@pytest.mark.parametrize("lam_sys, lam_src", [(0.40, None), (0.55, 0.40), (0.40, 0.70)])
def test_nonseq_bulk_absorption_from_the_catalogue_at_the_ray_wavelength(lam_sys, lam_src):
    """50 mm N-BK7 window: transmitted (1 - R)^2 exp(-alpha L), alpha(0.40 um) = 3.21e-4 / mm from the
    catalogue; the trace used the constant alpha = 0 (0.913944 instead of 0.899379 at 0.40 um)."""
    cs = compile_system(_window(lam_sys, True))
    lam = lam_src or lam_sys
    mat = MaterialLibrary().get("N-BK7")
    alpha, outside = mat.catalog_absorption(lam)
    assert not outside and alpha > 0
    n = cs.library.index("N-BK7", lam)
    R = ((n - 1) / (n + 1)) ** 2
    expected = (1 - R) ** 2 * math.exp(-alpha * 50.0)
    det = Detector(placement={"position": [0, 0, 0], "anchor": "img"}, size_x=20.0)
    src = LightSource(kind="emitter", angular="collimated", shape="disk", size_x=1.0, rays=100, placement={"position": [0, 0, -5]}, wavelengths=[{"value": lam}] if lam_src else [])
    r = trace_nonsequential(cs, build_scene(cs, [], True, None, (), [det]), sources=[src], split=False)
    assert r["detectors"][0]["fraction"] == pytest.approx(expected, rel=1e-9)
    assert r["energy"]["bulk_absorption"] == pytest.approx((1 - R) * (1 - math.exp(-alpha * 50.0)), rel=1e-9)
    if lam_src is None:
        assert expected == pytest.approx(0.899379, abs=1e-6)


def _rms_seq_and_ns(cs, rays=300):
    r = trace_nonsequential(cs, build_scene(cs, [], True), rays=rays, overfill=1.0, split=False)
    m = max(3, int(math.sqrt(rays * 4 / math.pi)))
    g = np.linspace(-1.0, 1.0, m)
    gx, gy = np.meshgrid(g, g)
    inside = gx**2 + gy**2 <= 1.0 + 1e-12
    w = cs.model.primary_wavelength
    P0, D0, opl = launch(cs, w, 0, gx[inside], gy[inside], compute_pupil(cs))
    s = trace(cs, w, P0, D0, opl, fresnel=True)
    xy, I = s.image_xy()[s.ok], s.intensity[s.ok]
    c = (xy * I[:, None]).sum(0) / I.sum()
    rms = math.sqrt(float((((xy - c) ** 2).sum(1) * I).sum() / I.sum()))
    return r["detector"]["direct_rms_mm"], rms


def test_nonseq_glass_at_its_element_temperature():
    """Singlet at 20 C with its lens at 70 C: the non-sequential trace used the glass index at the
    system temperature (RMS 5.66 um against the sequential 6.19 um)."""
    d = get_sample("singlet").system.model_dump()
    d["environment_enabled"] = True
    d["temperature_c"] = 20.0
    d["surfaces"][1]["element_temperature_c"] = 70.0
    ns, seq = _rms_seq_and_ns(compile_system(OpticalSystem.model_validate(d)))
    assert ns == pytest.approx(seq, rel=1e-6)
    d["surfaces"][1]["element_temperature_c"] = None
    ns20, seq20 = _rms_seq_and_ns(compile_system(OpticalSystem.model_validate(d)))
    assert ns20 == pytest.approx(seq20, rel=1e-6)
    assert abs(seq20 - seq) > 0.05 * seq  # the element temperature matters at this level


# ----------------------------------------------------------------------------- polarisation
@pytest.mark.parametrize("sid", ["fold-mirror", "spherical-mirror"])
def test_ideal_mirrors_have_no_retardance(sid):
    """With right-handed bases an odd number of reflections gives J = diag(-1, 1), which was read as
    half a wave of retardance (max_retardance_waves 0.5)."""
    cs = compile_system(get_sample(sid).system)
    for f in range(len(cs.model.fields)):
        s = polarization_pupil(cs, f, grid=9, input_state="45")["summary"]
        assert s["max_retardance_waves"] < 1e-9
        assert s["max_rotation_deg"] < 5.0
    # the Jones pupil and Mueller matrix stay in right-handed bases: an ideal mirror is diag(1, 1, -1, -1)
    if sid == "fold-mirror":
        M = np.array(polarization_pupil(cs, 0, grid=5, input_state="x")["summary"]["mueller"])
        assert np.diag(M) / M[0, 0] == pytest.approx([1.0, 1.0, -1.0, -1.0], abs=2e-3)  # (its lens loses ~8 %)


def test_coated_metal_fold_mirror_retardance_is_its_s_p_phase():
    """Bare aluminium-like substrate N = 0.96 - 6.69i at 45 deg: retardance |arg(r_p / -r_s)| = 0.2054
    rad (Born & Wolf signs, where an ideal conductor has r_p = -r_s); reported 2.9362 = pi - 0.2054."""
    p = get_sample("fold-mirror")
    d = p.system.model_dump()
    j = next(i for i, s in enumerate(p.system.surfaces) if s.is_mirror)
    d["surfaces"][j]["coating"] = "AL TEST"
    d["custom_coatings"] = [{"name": "al test", "layers": [], "substrate_index": 0.96, "substrate_extinction": 6.69}]
    cs = compile_system(OpticalSystem.model_validate(d))
    N = complex(0.96, -6.69)
    c0 = math.cos(math.radians(45.0))
    ct = cmath.sqrt(1 - (math.sin(math.radians(45.0)) / N) ** 2)
    rs = (c0 - N * ct) / (c0 + N * ct)
    rp = (N * c0 - ct) / (N * c0 + ct)
    expected = abs(cmath.phase(rp / -rs))
    assert expected == pytest.approx(0.2054, abs=1e-4)
    wl = cs.model.primary_wavelength
    P0, D0, _ = launch(cs, wl, 0, np.array([0.0]), np.array([0.0]), compute_pupil(cs, wl))
    jp = jones_pupil(cs, wl, P0, D0)
    assert jp["reflections"] == 1
    assert jones_properties(jp["J"], jp["reflections"])["retardance"][0] == pytest.approx(expected, abs=1e-9)
    # the pupil map: the metal's retardance grows with the angle of incidence across the pupil (no pi offset)
    s = polarization_pupil(cs, 0, grid=5, input_state="x")["summary"]
    assert expected < s["max_retardance_waves"] * 2 * math.pi < 1.3 * expected


def test_rotation_is_free_of_the_global_phase():
    """U / sqrt(det U) can be -U: J = exp(2i) I was read as a rotation of pi, and a Cooke triplet with
    MgF2 on every surface reported max_rotation_deg 180."""
    rot = lambda t: np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])  # noqa: E731
    for phase in (0.0, 2.0, -2.5, math.pi):
        p = jones_properties(np.array([np.exp(1j * phase) * np.eye(2)]))
        assert p["rotation"][0] == pytest.approx(0.0, abs=1e-12)
        assert p["retardance"][0] == pytest.approx(0.0, abs=1e-12)
        q = jones_properties(np.array([np.exp(1j * phase) * rot(0.3) @ np.diag([1.0, np.exp(0.4j)])]))
        assert q["rotation"][0] == pytest.approx(0.3, abs=1e-12)
        assert q["retardance"][0] == pytest.approx(0.4, abs=1e-12)
    d = get_sample("cooke-triplet").system.model_dump()
    bare = polarization_pupil(compile_system(OpticalSystem.model_validate(d)), 0, grid=11, input_state="x")["summary"]["max_rotation_deg"]
    for s in d["surfaces"][1:-1]:
        s["coating"] = "MGF2_QW550"
    coated = polarization_pupil(compile_system(OpticalSystem.model_validate(d)), 0, grid=11, input_state="x")["summary"]["max_rotation_deg"]
    assert coated < 1.0
    assert coated == pytest.approx(bare, abs=0.05)


# ----------------------------------------------------------------------------- POP / BPM sources
def _free(d0, d1, lam=1.55):
    return compile_system(
        OpticalSystem.model_validate(
            {
                "surfaces": [{"id": "o", "thickness": d0}, {"id": "a", "thickness": d1, "semi_diameter": 5, "semi_diameter_mode": "fixed", "is_stop": True}, {"id": "i"}],
                "wavelengths": [{"value": lam}],
                "field_type": "object_height",
                "fields": [{"y": 0}],
                "aperture": {"type": "object_na", "value": 0.1},
            }
        )
    )


@pytest.mark.parametrize("d0, zw", [(2.0, 0.0), (22.0, 20.0), (1.0, -1.0), (2.0, 4.0), (2.0, 2.0)])
def test_pop_gaussian_source_with_its_waist_off_the_object_surface(d0, zw):
    """20 um waist 2 mm before surface 1 (or 2 mm after it, or at it), given from different object
    planes: the target width is 2 w(7 mm - ...). The source's second-moment radius was taken as the
    waist (d0 = 22, waist_z = 20: +70 %; d0 = 1, waist_z = -1: -1 %)."""
    w0 = 0.02
    r = physical_optics(_free(d0, 5.0), {"kind": "gaussian", "waist_x": w0, "waist_z": zw})
    w = gaussian_q(w0, d0 + 5.0 - zw, LAM_POP)[0]
    assert r["target"]["d4sigma_mm"][0] == pytest.approx(2 * w, rel=1e-3)
    assert r["target"]["d4sigma_mm"][1] == pytest.approx(2 * w, rel=1e-3)
    assert r["target"]["power"] == pytest.approx(1.0, abs=2e-3)
    assert not any("under-sampled" in n for n in r["notes"])


def _plate(d0, t=5.0, d2=3.0):
    a = {"id": "a", "thickness": t, "material": "N-BK7", "semi_diameter": 2, "semi_diameter_mode": "fixed", "is_stop": True}
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


@pytest.mark.parametrize("d0, zw", [(20.5, 20.0), (2.0, 2.5)])
def test_bpm_gaussian_source_with_its_waist_off_the_object_surface(d0, zw):
    """BPM through a 5 mm N-BK7 plate starts from the POP entry field: a waist 0.5 mm before the plate
    (seen from 20.5 mm) and one 0.5 mm beyond its front face (converging onto it) follow the ABCD law
    over the reduced length (d0 - z_w) + t / n + d2."""
    cs = _plate(d0)
    n = float(cs.n_after[0, 1])
    w = gaussian_q(0.02, (d0 - zw) + 5.0 / n + 3.0, LAM_POP)[0]
    r = bpm(cs, {"kind": "gaussian", "waist_x": 0.02, "waist_z": zw})
    assert r["target"]["d4sigma_mm"][0] == pytest.approx(2 * w, rel=1e-3)


def test_pop_flags_an_undersampled_source_field():
    """An imported field converging with R = 5 mm, sampled on 64 points over +-0.5 mm, changes its phase
    by several radians between samples: noted instead of propagated silently."""
    lam = 1.55
    k = 2 * math.pi / (lam * 1e-3)
    r = np.linspace(0.0, 0.5, 400)
    u = np.exp(-((r / 0.2) ** 2)) * np.exp(-1j * k * r * r / (2 * 5.0))
    src = {"kind": "field", "r_um": (r * 1e3).tolist(), "re": u.real.tolist(), "im": u.imag.tolist(), "wavelength_um": lam}
    pre = physical_optics(_free(20.0, 5.0), src, grid=64, _transfer_only=True)
    assert any("under-sampled" in n for n in pre["notes"])
    assert pre["src_info"]["phase_step_rad"] > math.pi / 2


# ----------------------------------------------------------------------------- coatings, Gaussian beam
def test_coating_transmission_estimate_uses_the_catalogue_absorption():
    """50 mm N-BK7 at 380 nm: the estimate used the constant alpha (0.9132) instead of the catalogue
    internal transmittance (0.8824, as the throughput analysis)."""
    cs = compile_system(_window(0.38, True))
    cp = coating_performance(cs, 379.0, 381.0, 3)
    est = cp["system_transmission_estimate"][1]
    alpha = MaterialLibrary().get("N-BK7").catalog_absorption(0.38)[0]
    n = cs.library.index("N-BK7", 0.38)
    R = ((n - 1) / (n + 1)) ** 2
    assert est == pytest.approx((1 - R) ** 2 * math.exp(-alpha * 50.0), rel=1e-9)
    assert est == pytest.approx(transmission(cs)["weighted_mean_total"], rel=1e-9)
    off = coating_performance(compile_system(_window(0.38, False)), 379.0, 381.0, 3)["system_transmission_estimate"][1]
    assert off == pytest.approx((1 - R) ** 2, rel=1e-9)


@pytest.mark.parametrize("s", [0.0, 50.0, 300.0])
def test_gaussian_beam_through_an_ideal_lens(s):
    """Ideal f = 100 mm lens, 1 mm waist s before it, 0.55 um: Self's thin-lens transformation
    s' = f + (s - f) f^2 / ((s - f)^2 + z_R^2), w0' = w0 f / sqrt((s - f)^2 + z_R^2). The ideal lens had no
    power in the beam analysis (image waist 1.0 mm at 0 mm instead of 0.0175 mm at 99.97 mm for s = 0)."""
    f, w0, lam = 100.0, 1.0, 0.55e-3
    sysm = OpticalSystem.model_validate(
        {
            "surfaces": [{"thickness": None}, {"type": "ideal", "focal_length": f, "thickness": 100.0, "is_stop": True}, {}],
            "wavelengths": [{"value": 0.55}],
            "aperture": {"type": "epd", "value": 4.0},
        }
    )
    g = gaussian_beam(compile_system(sysm), w0, s)
    zR = math.pi * w0 * w0 / lam
    den = (s - f) ** 2 + zR**2
    assert g["image"]["waist_from_last_surface"] == pytest.approx(f + (s - f) * f * f / den, rel=1e-9)
    assert g["image"]["waist_radius"] == pytest.approx(w0 * f / math.sqrt(den), rel=1e-9)
    if s == 0.0:
        assert g["image"]["waist_radius"] == pytest.approx(0.017504, abs=1e-6)
