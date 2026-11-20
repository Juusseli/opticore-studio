import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.analysis.gaussian import gaussian_beam
from opticore.api.main import app
from opticore.paraxial import paraxial_data
from opticore.samples import get_sample
from opticore.system import SystemError_, compile_system

from .conftest import make_system

LAM = 0.6328  # um (He-Ne)


def _free_space(length=500.0, n_mat="AIR"):
    return make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "a", "thickness": length, "is_stop": True, "material": n_mat},
            {"id": "img"},
        ],
        wavelengths=[{"value": LAM}],
    )


def _w(z, w0, zr):
    return w0 * math.sqrt(1 + (z / zr) ** 2)


def test_free_space_propagation_matches_analytic_beam():
    cs = compile_system(_free_space())
    w0 = 0.25
    r = gaussian_beam(cs, w0, 100.0)
    lam = LAM * 1e-3
    zr = math.pi * w0**2 / lam
    assert r["object"]["rayleigh_range"] == pytest.approx(zr, rel=1e-14)
    z = np.array(r["curve"]["z"])
    w = np.array(r["curve"]["w"])
    ok = np.isfinite(z)
    # waist at z = -100 (100 mm before surface 1)
    expected = [_w(zz + 100.0, w0, zr) for zz in z[ok]]
    assert np.allclose(w[ok], expected, rtol=1e-12)
    img = r["image"]
    assert img["waist_radius"] == pytest.approx(w0, rel=1e-12)
    assert img["waist_from_last_surface"] == pytest.approx(-100.0, abs=1e-9)
    assert img["w_at_image_surface"] == pytest.approx(_w(600.0, w0, zr), rel=1e-12)
    # far-field divergence lambda / (pi w0) and R(z) = z (1 + (zr/z)^2)
    assert img["divergence_half_angle_mrad"] == pytest.approx(lam / (math.pi * w0) * 1e3, rel=1e-12)
    assert img["R_at_image_surface"] == pytest.approx(600.0 * (1 + (zr / 600.0) ** 2), rel=1e-10)


def test_rayleigh_range_scales_with_index_in_glass():
    sysm = _free_space(200.0, "N-BK7")
    cs = compile_system(sysm)
    n = cs.n_after[0, 1]
    w0 = 0.2
    r = gaussian_beam(cs, w0, 0.0)  # waist on the entrance face
    seg = r["segments"][0]
    assert seg["waist_radius"] == pytest.approx(w0, rel=1e-12)  # waist size unchanged by a plane interface
    assert seg["rayleigh_range"] == pytest.approx(math.pi * n * w0**2 / (LAM * 1e-3), rel=1e-12)
    assert r["image"]["w_at_image_surface"] == pytest.approx(_w(200.0, w0, seg["rayleigh_range"]), rel=1e-12)


def _self_formula(s, f, zr):
    """S. A. Self, Appl. Opt. 22, 658 (1983): waist distance after H' and magnification."""
    sp = 1.0 / (1.0 / f - 1.0 / (s + zr * zr / (s - f)))
    m = 1.0 / math.sqrt((1 - s / f) ** 2 + (zr / f) ** 2)
    return sp, m


@pytest.mark.parametrize("w0,d", [(0.5, 150.0), (0.2, 80.0), (1.0, 0.0), (0.05, 300.0)])
def test_thick_singlet_matches_self_waist_transformation(w0, d):
    sysm = get_sample("singlet").system
    cs = compile_system(sysm)
    wl = sysm.primary_wavelength
    pd = paraxial_data(cs, wl)
    f = pd.efl
    lam = cs.wavelengths[wl] * 1e-3
    zr = math.pi * w0**2 / lam
    s = d + pd.front_principal_plane  # waist distance in front of H
    sp, m = _self_formula(s, f, zr)
    r = gaussian_beam(cs, w0, d, wavelength=wl)
    img = r["image"]
    assert img["waist_from_last_surface"] == pytest.approx(sp + pd.rear_principal_plane, rel=1e-9, abs=1e-9)
    assert img["waist_radius"] == pytest.approx(m * w0, rel=1e-10)


def test_spherical_mirror_focuses_collimated_beam_near_f():
    sysm = get_sample("spherical-mirror").system
    cs = compile_system(sysm)
    f = 100.0
    w0 = 2.0
    lam = cs.wavelengths[0] * 1e-3
    zr = math.pi * w0**2 / lam
    # waist on the mirror: entrance surface 50 mm before it
    r = gaussian_beam(cs, w0, -50.0)
    sp, m = _self_formula(0.0, f, zr)  # waist at the mirror (s = 0)
    img = r["image"]
    assert img["waist_from_last_surface"] == pytest.approx(sp, rel=1e-10)  # = f zr^2 / (zr^2 + f^2)
    assert img["waist_radius"] == pytest.approx(m * w0, rel=1e-10)
    assert img["waist_radius"] == pytest.approx(lam * f / (math.pi * w0), rel=1e-4)  # far-field limit


def test_m2_equals_scaled_wavelength():
    sysm = get_sample("singlet").system
    cs = compile_system(sysm)
    a = gaussian_beam(cs, 0.4, 120.0, m2=2.5)
    # a pure wavelength rescale with the same indices
    cs2 = compile_system(sysm)
    cs2.wavelengths = cs2.wavelengths * 2.5
    b = gaussian_beam(cs2, 0.4, 120.0)
    assert a["image"]["waist_radius"] == pytest.approx(b["image"]["waist_radius"], rel=1e-12)
    assert a["image"]["waist_from_last_surface"] == pytest.approx(b["image"]["waist_from_last_surface"], rel=1e-12)


def test_small_waist_images_like_a_point():
    # z_R -> 0: the image waist lies at the paraxial image of the object waist
    sysm = get_sample("singlet").system
    cs = compile_system(sysm)
    wl = sysm.primary_wavelength
    pd = paraxial_data(cs, wl)
    s = 300.0 + pd.front_principal_plane
    sp = 1 / (1 / pd.efl - 1 / s)
    r = gaussian_beam(cs, 1e-5, 300.0, wavelength=wl)
    assert r["image"]["waist_from_last_surface"] == pytest.approx(sp + pd.rear_principal_plane, rel=1e-6)


def test_clipping_report_and_errors():
    sysm = get_sample("singlet").system
    cs = compile_system(sysm)
    r = gaussian_beam(cs, 12.0, 0.0, semi_diameters=[0, 12.7, 12.7, 1.0])
    s1 = r["surfaces"][0]
    assert s1["clip_transmission"] == pytest.approx(1 - math.exp(-2 * 12.7**2 / s1["w"] ** 2), rel=1e-12)
    assert any("aperture" in n for n in r["notes"])
    with pytest.raises(SystemError_):
        gaussian_beam(cs, 0.0, 0.0)
    with pytest.raises(SystemError_):
        gaussian_beam(cs, 1.0, 0.0, m2=0.5)


def test_folded_system_is_unfolded_with_note():
    sysm = get_sample("fold-mirror").system
    cs = compile_system(sysm)
    r = gaussian_beam(cs, 0.5, 50.0)
    assert any("unfolded" in n for n in r["notes"])
    assert r["image"]["waist_radius"] > 0


def test_gaussian_api():
    c = TestClient(app)
    sysm = get_sample("singlet").system
    r = c.post("/api/v1/analysis/gaussian", json={"system": sysm.model_dump(), "waist_radius": 0.5, "waist_distance": 100})
    assert r.status_code == 200
    body = r.json()
    assert body["image"]["waist_radius"] > 0 and len(body["curve"]["z"]) == len(body["curve"]["w"])
    assert all("clip_transmission" in s for s in body["surfaces"][:2])
    bad = c.post("/api/v1/analysis/gaussian", json={"system": sysm.model_dump(), "waist_radius": -1})
    assert bad.status_code == 422
    bad = c.post("/api/v1/analysis/gaussian", json={"system": sysm.model_dump(), "wavelength": 9})
    assert bad.status_code == 422
