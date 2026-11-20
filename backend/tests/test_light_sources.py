"""Light sources: aiming a placement at a point, the Gaussian beam source (M^2, waist position) and generated
spectra (blackbody, Gaussian line, flat band)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.integrate import quad

from opticore.api.main import app
from opticore.nonseq import build_scene, trace_nonsequential
from opticore.nssources import Detector, LightSource, Placement, aim_angles, describe_beam, placement_matrix, sample_source, surface_frames
from opticore.samples import get_sample
from opticore.spectra import SIGMA, WIEN_UM_K, SpectrumSpec, generate, planck
from opticore.system import compile_system

from .conftest import make_system

client = TestClient(app)


# ---------------------------------------------------------------------------------------------- aim
@pytest.mark.parametrize("roll", [0.0, 30.0, -125.0])
@pytest.mark.parametrize("pos,aim", [([0, 0, 0], [0, 0, 5]), ([1, 2, 3], [4, -1, 13]), ([0, 0, 0], [10, 0, 0.0]), ([0, 0, 0], [0, -3, -4]), ([5, 5, 5], [5, 5, -20])])
def test_aim_points_the_axis_at_the_point(pos, aim, roll):
    p = Placement(position=pos, aim=aim, rotation_deg=[77.0, -12.0, roll])  # the first two angles are ignored
    R, t = placement_matrix(p)
    d = np.subtract(aim, pos) / np.linalg.norm(np.subtract(aim, pos))
    assert R[:, 2] == pytest.approx(d, abs=1e-12)
    assert np.allclose(R.T @ R, np.eye(3), atol=1e-12) and np.linalg.det(R) == pytest.approx(1.0)
    # the roll turns the local x axis about the aimed axis
    R0, _ = placement_matrix(Placement(position=pos, aim=aim, rotation_deg=[0, 0, 0]))
    assert float(R0[:, 0] @ R[:, 0]) == pytest.approx(math.cos(math.radians(roll)), abs=1e-12)
    a, b = aim_angles(d)
    Re, _ = placement_matrix(Placement(position=pos, rotation_deg=[a, b, roll]))
    assert Re == pytest.approx(R, abs=1e-12)  # aim = these explicit angles


def test_aim_relative_to_an_anchor_surface_and_refusals():
    p = get_sample("cooke-triplet")
    cs = compile_system(p.system, p.custom_materials)
    frames = surface_frames(cs)
    sid = p.system.surfaces[3].id
    M, O = frames[sid]
    pl = Placement(anchor=sid, position=[0, 1, -5], aim=[0, -2, 10])
    R, t = placement_matrix(pl, frames)
    d_local = np.array([0, -3, 15.0]) / np.linalg.norm([0, -3, 15.0])
    assert R[:, 2] == pytest.approx(M @ d_local, abs=1e-12)
    assert t == pytest.approx(M @ np.array([0, 1, -5.0]) + O, abs=1e-12)
    with pytest.raises(ValueError):
        placement_matrix(Placement(position=[1, 1, 1], aim=[1, 1, 1]))
    # a source aimed off axis emits along the aimed direction
    src = LightSource(angular="collimated", shape="point", rays=10, placement={"position": [0, 0, 0], "aim": [0, 3, 4]})
    sr = sample_source(src, 0, [(0.55, 1.0)], np.random.default_rng(0))
    assert sr.D == pytest.approx(np.tile([0, 0.6, 0.8], (10, 1)), abs=1e-12)


# ---------------------------------------------------------------------------------------------- Gaussian beam
def _width(sr, z, axis=0):
    s = sr.P[:, axis] + sr.D[:, axis] / sr.D[:, 2] * (z - sr.P[:, 2])
    return 2.0 * float(np.std(s))


@pytest.mark.parametrize("zw", [0.0, 20.0, -15.0])
def test_gaussian_beam_widths_follow_the_beam_law(zw):
    """w(z)^2 = w0^2 + theta^2 (z - z_w)^2 with theta = M^2 lambda / (pi w0), separately in x and y."""
    lam = 0.6328
    src = LightSource(kind="gaussian_beam", beam_waist_x=0.05, beam_waist_y=0.08, beam_m2=2.0, beam_waist_z=zw, rays=200000, wavelengths=[{"value": lam}])
    sr = sample_source(src, 0, [(lam, 1.0)], np.random.default_rng(4))
    for axis, w0 in ((0, 0.05), (1, 0.08)):
        th = 2.0 * lam * 1e-3 / (math.pi * w0)
        for z in (zw - 30.0, zw - 10.0, zw, zw + 25.0, 0.0):
            assert _width(sr, z, axis) == pytest.approx(math.sqrt(w0**2 + th**2 * (z - zw) ** 2), rel=0.01), (axis, z)
    d = describe_beam(src, lam)
    assert d["x"]["rayleigh_mm"] == pytest.approx(math.pi * 0.05**2 / (2.0 * lam * 1e-3))
    assert d["x"]["radius_at_source_mm"] == pytest.approx(math.sqrt(0.05**2 + (2.0 * lam * 1e-3 / (math.pi * 0.05)) ** 2 * zw**2))
    if zw:
        zr = d["x"]["rayleigh_mm"]
        assert d["x"]["wavefront_radius_mm"] == pytest.approx(-zw * (1 + (zr / zw) ** 2))  # < 0: converging
    else:
        assert d["x"]["wavefront_radius_mm"] is None


def test_gaussian_beam_source_through_a_lens_forms_the_abcd_waist():
    """A converging beam (waist 120 mm ahead of the source, at the object plane of a 2f-2f lens) through the real
    lens: at the paraxial image plane the width is |m| w0, as for the hand-built Gaussian source (test_ns_sources)."""
    lam_um, w0 = 1.0, 0.050
    sysm = make_system(
        [
            {"thickness": 120.0},
            {"radius": 62.0, "thickness": 4.0, "material": "N-BK7", "is_stop": True, "semi_diameter": 10.0},
            {"radius": -62.0, "thickness": 0.0},
            {"thickness": 0.0},
        ],
        wavelengths=[{"value": lam_um}],
    )
    from opticore.paraxial import paraxial_data

    cs = compile_system(sysm)
    pd = paraxial_data(cs)
    # the source plane sits 30 mm before the object plane and the waist is set 30 mm ahead of it
    src = LightSource(kind="gaussian_beam", placement={"position": [0, 0, -150.0]}, beam_waist_x=w0, beam_waist_y=w0, beam_waist_z=30.0, rays=30000, wavelengths=[{"value": lam_um}])
    scene = build_scene(cs, [], True, None, (), [Detector(placement={"position": [0, 0, 4.0 + pd.paraxial_image_distance]}, size_x=3.0, mode="monitor")])
    r = trace_nonsequential(cs, scene, sources=[src], split=False, seed=9)
    d = r["detectors"][0]
    w_expect = abs(pd.paraxial_magnification) * w0
    assert d["width_2sigma_mm"][0] == pytest.approx(w_expect, rel=0.03)
    assert d["width_2sigma_mm"][1] == pytest.approx(w_expect, rel=0.03)


def test_sources_describe_endpoint():
    sysm = make_system([{"thickness": None}, {"thickness": 10.0, "is_stop": True, "semi_diameter": 5.0}, {"thickness": 0.0}], wavelengths=[{"value": 0.55}])
    body = {
        "system": sysm.model_dump(mode="json"),
        "custom_materials": [],
        "sources": [
            LightSource(kind="gaussian_beam", beam_waist_x=0.1, beam_waist_z=5, placement={"position": [0, 0, -10], "aim": [0, 10, 0]}).model_dump(mode="json"),
            LightSource(kind="system_field").model_dump(mode="json"),
        ],
        "detectors": [Detector(placement={"position": [0, 0, 20], "rotation_deg": [-90, 0, 0]}).model_dump(mode="json")],
    }
    r = client.post("/api/v1/sources/describe", json=body).json()
    s0 = r["sources"][0]
    assert s0["direction"] == pytest.approx([0, math.sqrt(0.5), math.sqrt(0.5)]) and s0["axis_angle_deg"] == pytest.approx(45.0)
    assert s0["beam"]["x"]["divergence_mrad"] == pytest.approx(0.55e-3 / (math.pi * 0.1) * 1e3)
    assert "direction" not in r["sources"][1]
    assert r["detectors"][0]["direction"] == pytest.approx([0, 1, 0], abs=1e-12)


# ---------------------------------------------------------------------------------------------- spectra
def test_blackbody_spectrum():
    T = 3000.0
    g = generate(SpectrumSpec(kind="blackbody", temperature_k=T, lambda_min_um=0.3, lambda_max_um=3.0, samples=27))
    w = np.array([x["weight"] for x in g["wavelengths"]])
    c = np.array([x["value"] for x in g["wavelengths"]])
    assert w.sum() == pytest.approx(1.0) and len(w) == 27
    # Wien: the heaviest bin holds lambda_max = b / T (bins of equal width)
    bin_ = g["info"]["bin_um"]
    assert abs(c[np.argmax(w)] - WIEN_UM_K / T) <= bin_ / 2 + 1e-12
    # the band fraction equals an independent quadrature of Planck's law over sigma T^4 / pi
    band = quad(lambda l: float(planck(l, T)), 0.3, 3.0, limit=200)[0]
    assert g["info"]["band_fraction"] == pytest.approx(band / (SIGMA * T**4 / math.pi), rel=1e-6)
    # and the whole spectrum integrates to sigma T^4 / pi
    total = quad(lambda l: float(planck(l, T)), 0.05, 200.0, limit=400)[0]
    assert total == pytest.approx(SIGMA * T**4 / math.pi, rel=1e-4)
    # each bin's weight is its share of the band integral
    k = 5
    lo = 0.3 + k * bin_
    assert w[k] == pytest.approx(quad(lambda l: float(planck(l, T)), lo, lo + bin_)[0] / band, rel=1e-8)


def test_gaussian_line_and_flat_band():
    g = generate(SpectrumSpec(kind="gaussian", center_um=0.63, fwhm_um=0.02, samples=21))
    w = np.array([x["weight"] for x in g["wavelengths"]])
    c = np.array([x["value"] for x in g["wavelengths"]])
    mean = float((w * c).sum())
    sd = float(math.sqrt((w * (c - mean) ** 2).sum()))
    assert mean == pytest.approx(0.63, abs=1e-12)
    assert sd == pytest.approx(0.02 / (2 * math.sqrt(2 * math.log(2))), rel=0.01)
    f = generate(SpectrumSpec(kind="flat", lambda_min_um=0.4, lambda_max_um=0.7, samples=3))
    assert [x["value"] for x in f["wavelengths"]] == pytest.approx([0.45, 0.55, 0.65]) and all(x["weight"] == pytest.approx(1 / 3) for x in f["wavelengths"])
    r = client.post("/api/v1/sources/spectrum", json={"kind": "blackbody", "temperature_k": 5778, "lambda_min_um": 0.4, "lambda_max_um": 0.7, "samples": 7})
    assert r.status_code == 200 and len(r.json()["wavelengths"]) == 7
    assert client.post("/api/v1/sources/spectrum", json={"kind": "flat", "samples": 3}).status_code == 422
    # a generated spectrum is a valid source spectrum
    LightSource(wavelengths=r.json()["wavelengths"])
