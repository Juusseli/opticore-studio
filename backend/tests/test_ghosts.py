import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.analysis.ghosts import ghost_analysis, ghost_system
from opticore.api.main import app
from opticore.paraxial import compute_pupil, paraxial_data
from opticore.raytrace import gauss_pupil, launch, trace
from opticore.samples import get_sample
from opticore.system import SystemError_, compile_system
from opticore.thinfilm import stack_rt

from .conftest import make_system

LAM = 0.5875618


def _window_and_lens(coating: str = ""):
    """Plane-parallel N-BK7 window in a collimated axial beam, followed by a plano-convex singlet."""
    return make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "w1", "thickness": 4.0, "material": "N-BK7", "is_stop": True, "coating": coating},
            {"id": "w2", "thickness": 10.0, "coating": coating},
            {"id": "l1", "radius": 51.68, "thickness": 5.0, "material": "N-BK7"},
            {"id": "l2", "thickness": 96.7},
            {"id": "img"},
        ],
        wavelengths=[{"value": LAM}],
        fields=[{"y": 0.0}],
        aperture={"type": "epd", "value": 10.0},
    )


def _ghost(r, i, j):
    return next(g for g in r["ghosts"] if g["reflect_first"] == i and g["reflect_second"] == j)


def test_window_ghost_energy_is_R_squared_of_the_main_image():
    # normal incidence on both window faces: the ghost rays leave the window parallel to the
    # main rays, so E_ghost / E_main = R(window)^2 exactly
    cs = compile_system(_window_and_lens())
    r = ghost_analysis(cs)
    n = cs.n_after[0, 1]
    R = ((n - 1) / (n + 1)) ** 2
    g = _ghost(r, 2, 1)
    assert g["energy_fraction"] / r["main"]["energy_fraction"] == pytest.approx(R * R, rel=1e-10)
    assert g["mean_R_first"] == pytest.approx(R, rel=1e-12) and g["mean_R_second"] == pytest.approx(R, rel=1e-12)
    # a window ghost in collimated light focuses where the main image does
    pd = paraxial_data(cs)
    assert g["focus_from_image_mm"] == pytest.approx(-pd.image_surface_defocus, abs=1e-9)


def test_window_ghost_spot_equals_main_spot():
    cs = compile_system(_window_and_lens())
    r = ghost_analysis(cs)
    g = _ghost(r, 2, 1)
    pupil = compute_pupil(cs)
    px, py, pw = gauss_pupil(6)
    P0, D0, opl = launch(cs, 0, 0, px, py, pupil)
    m = trace(cs, 0, P0, D0, opl, fresnel=True)
    w = pw * m.intensity
    xy = m.image_xy()
    c = (w[:, None] * xy).sum(0) / w.sum()
    rms = np.sqrt((w * ((xy - c) ** 2).sum(1)).sum() / w.sum())
    assert g["rms_radius_mm"] == pytest.approx(rms, rel=1e-9)


def test_coated_window_reduces_ghost_by_coating_reflectance_squared():
    bare = ghost_analysis(compile_system(_window_and_lens()))
    coated_cs = compile_system(_window_and_lens("MGF2_QW550"))
    coated = ghost_analysis(coated_cs)
    n = coated_cs.n_after[0, 1]
    from opticore.thinfilm import COATINGS

    Rc = stack_rt(1.0, n, COATINGS["MGF2_QW550"].layers_at(LAM), LAM, np.array([1.0]))["Rs"][0]  # the MgF2 film
    # main image also gains transmission through the coated faces; compare ghost/main ratios
    rb = _ghost(bare, 2, 1)["energy_fraction"] / bare["main"]["energy_fraction"]
    rc = _ghost(coated, 2, 1)["energy_fraction"] / coated["main"]["energy_fraction"]
    nn = ((n - 1) / (n + 1)) ** 2
    assert rb == pytest.approx(nn * nn, rel=1e-10)
    assert rc == pytest.approx(Rc * Rc, rel=1e-10)
    assert rc < 0.15 * rb


def test_singlet_ghost_focus_matches_independent_abcd():
    sysm = get_sample("singlet").system
    cs = compile_system(sysm)
    w = sysm.primary_wavelength
    n = cs.n_after[w, 1]
    c1, c2 = 1 / 51.68, 0.0
    t, d = 5.0, sysm.surfaces[2].thickness
    # reduced (y, nu) matrices with signed indices; mirror: n' = -n
    T = lambda tau: np.array([[1.0, tau], [0.0, 1.0]])  # noqa: E731
    Rf = lambda phi: np.array([[1.0, 0.0], [-phi, 1.0]])  # noqa: E731
    M = Rf((n - 1) * c1)  # refract at S1
    M = T(t / n) @ M
    M = Rf((-n - n) * c2) @ M  # reflect at S2 (inside the glass)
    M = T((-t) / (-n)) @ M
    M = Rf((n - (-n)) * c1) @ M  # reflect at S1 from inside
    M = T(t / n) @ M
    M = Rf((1 - n) * c2) @ M  # out through S2
    y, nu = M @ np.array([5.0, 0.0])  # collimated marginal ray, EP radius 5
    z_focus = -y / nu  # behind S2 (n = 1 after the last refraction)
    r = ghost_analysis(cs, wavelength=w)
    g = _ghost(r, 2, 1)
    assert g["focus_from_image_mm"] == pytest.approx(z_focus - d, rel=1e-10)


def test_ghost_system_geometry_and_pair_counting():
    tri = get_sample("cooke-triplet").system
    cs = compile_system(tri)
    r = ghost_analysis(cs)
    # of the 7 surfaces, the 6 with an index step (not the stop in air) form 6 * 5 / 2 = 15 ghost pairs
    steps = [k for k in range(1, cs.n_surfaces - 1) if cs.n_after[1, k - 1] != cs.n_after[1, k]]
    expected = sum(1 for i in steps for j in steps if j < i)
    assert len(r["ghosts"]) == expected == 15
    g = ghost_system(tri, 4, 2)
    mats = [s.material for s in g.surfaces]
    assert mats[4] == "MIRROR" and mats[4 + (4 - 1 - 2) + 1] == "MIRROR"
    # thickness signs: negative while travelling backwards, positive again after the second mirror
    assert g.surfaces[4].thickness < 0 and g.surfaces[6].thickness > 0
    # ranking by relative irradiance, energies bounded by the product of the two reflectances
    rel = [x["relative_irradiance"] for x in r["ghosts"]]
    assert rel == sorted(rel, reverse=True)
    assert all(x["energy_fraction"] <= x["mean_R_first"] * x["mean_R_second"] + 1e-15 for x in r["ghosts"] if x.get("mean_R_first") is not None)


def test_mirror_systems_are_rejected():
    with pytest.raises(SystemError_):
        ghost_analysis(compile_system(get_sample("spherical-mirror").system))


def test_ghost_api():
    c = TestClient(app)
    r = c.post("/api/v1/analysis/ghosts", json={"system": get_sample("achromat").system.model_dump()})
    assert r.status_code == 200
    b = r.json()
    assert len(b["ghosts"]) == 3 and all(len(g["paths_zy"]) > 0 for g in b["ghosts"])
    bad = c.post("/api/v1/analysis/ghosts", json={"system": get_sample("spherical-mirror").system.model_dump()})
    assert bad.status_code in (400, 422)
