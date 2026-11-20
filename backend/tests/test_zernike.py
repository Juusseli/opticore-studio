"""Zernike sag surfaces: polynomial expansion, exact equivalences, intersection,
paraxial vertex curvature, checks, variables and file round trip."""

import math

import numpy as np
import pytest

from opticore.analysis.evaluate import edge_thickness, evaluate_system
from opticore.analysis.wavefront import fringe_nm, zernike
from opticore.io.cad import export_system_cad
from opticore.model import OpticalSystem
from opticore.optimize import OptimizationSpec, optimize
from opticore.optimize.merit import MeritFunction
from opticore.paraxial import compute_pupil, paraxial_data
from opticore.project import Project, dump_project, load_project
from opticore.raytrace import launch, trace
from opticore.surfaces import OK, BiconicShape, Shape, ZernikeShape, fringe_monomials
from opticore.system import compile_system

from .conftest import make_system

LAM = 0.5875618


def _rays(n=300, seed=5, half=5.0, tilt=0.12):
    rng = np.random.default_rng(seed)
    P = np.column_stack([rng.uniform(-half, half, n), rng.uniform(-half, half, n), np.full(n, -4.0)])
    D = np.column_stack([rng.uniform(-tilt, tilt, n), rng.uniform(-tilt, tilt, n), np.ones(n)])
    return P, D / np.linalg.norm(D, axis=1, keepdims=True)


def _lens(front: dict, back: dict | None = None, length: float = 95.0, epd: float = 10.0):
    return make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "f", "thickness": 5.0, "material": "N-BK7", "is_stop": True, **front},
            {"id": "b", "thickness": length, **(back or {})},
            {"id": "img"},
        ],
        wavelengths=[{"value": LAM}],
        fields=[{"y": 0.0}, {"y": 3.0}],
        aperture={"type": "epd", "value": epd},
    )


def test_monomial_expansion_equals_the_polar_definition():
    rng = np.random.default_rng(0)
    u, v = rng.uniform(-1, 1, 400), rng.uniform(-1, 1, 400)
    rho, th = np.hypot(u, v), np.arctan2(v, u)
    for i in range(1, 38):
        n, m = fringe_nm(i)[i - 1]
        assert np.allclose(np.polynomial.polynomial.polyval2d(u, v, fringe_monomials(i)), zernike(n, m, rho, th), atol=1e-11)


def test_defocus_term_is_an_exact_paraboloid():
    R, a4 = 8.0, 0.05
    z = ZernikeShape(0.0, 0.0, (), (0, 0, 0, a4), R)  # Z4 = 2 rho^2 - 1 -> 2 a4 r^2 / R^2
    c = 4 * a4 / R**2
    para = Shape(c, -1.0, ())
    P, D = _rays()
    s1, st1 = z.intersect(P, D)
    s2, st2 = para.intersect(P, D)
    assert np.all(st1 == OK) and np.all(st2 == OK)
    assert np.allclose(s1, s2, atol=1e-12)
    q = P + s1[:, None] * D
    assert np.allclose(z.normals(q), para.normals(q), atol=1e-12)
    assert z.curvature == pytest.approx(c, rel=1e-14) and z.curvature_x == pytest.approx(c, rel=1e-14)


def test_astigmatism_term_equals_a_parabolic_biconic():
    R, a5 = 6.0, 0.03
    z = ZernikeShape(0.0, 0.0, (), (0, 0, 0, 0, a5), R)  # Z5 = rho^2 cos 2theta = u^2 - v^2
    bic = BiconicShape(-2 * a5 / R**2, -1.0, 2 * a5 / R**2, -1.0)  # (cx x^2 + cy y^2) / 2
    P, D = _rays(seed=9)
    s1, _ = z.intersect(P, D)
    s2, _ = bic.intersect(P, D)
    assert np.allclose(s1, s2, atol=1e-12)
    q = P + s1[:, None] * D
    assert np.allclose(z.normals(q), bic.normals(q), atol=1e-12)
    assert z.curvature_x == pytest.approx(2 * a5 / R**2) and z.curvature == pytest.approx(-2 * a5 / R**2)


def test_zernike_combination_reproduces_an_even_asphere_lens():
    """A4 r^4 = A4 R^4 rho^4 = (A4 R^4 / 6) Z9 + (A4 R^4 / 2) Z4 + const."""
    A4, R = -2e-5, 6.0
    coeffs = [0.0] * 9
    coeffs[3] = A4 * R**4 / 2
    coeffs[8] = A4 * R**4 / 6
    zern = compile_system(_lens({"type": "zernike", "radius": 60.0, "conic": -0.5, "zernike_coefficients": coeffs, "zernike_norm_radius": R}, {"radius": -150.0}))
    asph = compile_system(_lens({"type": "even_asphere", "radius": 60.0, "conic": -0.5, "aspheric": [A4]}, {"radius": -150.0}))
    pupil = compute_pupil(asph)
    rng = np.random.default_rng(2)
    px, py = rng.uniform(-0.7, 0.7, 200), rng.uniform(-0.7, 0.7, 200)
    for f in (0, 1):
        a = trace(asph, 0, *launch(asph, 0, f, px, py, pupil))
        b = trace(zern, 0, *launch(zern, 0, f, px, py, compute_pupil(zern)))
        assert np.all(a.ok) and np.all(b.ok)
        assert np.allclose(a.image_xy(), b.image_xy(), atol=1e-11)
        assert np.allclose(a.opl, b.opl, atol=1e-10)
    assert paraxial_data(zern).efl == pytest.approx(paraxial_data(asph).efl, rel=1e-13)


def test_random_freeform_intersection_and_normals():
    rng = np.random.default_rng(11)
    coeffs = tuple(rng.normal(0, 0.02, 37))
    z = ZernikeShape(1 / 50.0, -0.3, (1e-6,), coeffs, 7.0)
    P, D = _rays(seed=4)
    s, st = z.intersect(P, D)
    assert np.all(st == OK)
    q = P + s[:, None] * D
    assert np.max(np.abs(q[:, 2] - z.sag_xy(q[:, 0], q[:, 1]))) < 1e-11
    h = 1e-6
    gx = (z.sag_xy(q[:, 0] + h, q[:, 1]) - z.sag_xy(q[:, 0] - h, q[:, 1])) / (2 * h)
    gy = (z.sag_xy(q[:, 0], q[:, 1] + h) - z.sag_xy(q[:, 0], q[:, 1] - h)) / (2 * h)
    n_fd = np.column_stack([-gx, -gy, np.ones_like(gx)])
    n_fd /= np.linalg.norm(n_fd, axis=1, keepdims=True)
    assert np.allclose(z.normals(q), n_fd, atol=1e-7)
    assert abs(float(z.sag_xy(0.0, 0.0))) < 1e-15  # vertex reference


def test_vertex_curvature_and_tilt():
    R = 5.0
    c = [0.0] * 9
    c[3], c[8] = 0.01, 0.002  # Z4 (2 rho^2 - 1), Z9 (6 rho^4 - 6 rho^2 + 1)
    z = ZernikeShape(1 / 80.0, 0.0, (), tuple(c), R)
    assert z.curvature == pytest.approx(1 / 80.0 + 2 * (2 * 0.01 - 6 * 0.002) / R**2, rel=1e-14)
    tilt = ZernikeShape(0.0, 0.0, (), (0.0, 0.0, 0.05), R)  # Z3 = rho sin(theta) = v: plane z = 0.05 y / R
    sx, sy = tilt.vertex_slope
    assert sx == 0.0 and sy == pytest.approx(0.05 / R)
    q = np.array([[0.0, 2.0, 0.1]])
    n = tilt.normals(q)[0]
    assert np.allclose(n, np.array([0.0, -0.01, 1.0]) / math.hypot(0.01, 1.0), atol=1e-15)
    cs = compile_system(_lens({"type": "zernike", "radius": 60.0, "zernike_coefficients": [0, 0, 0.05], "zernike_norm_radius": R}))
    codes = {d.code for d in cs.diagnostics}
    assert {"ZERNIKE_PARAXIAL", "ZERNIKE_TILT"} <= codes


def test_edge_thickness_uses_the_whole_rim():
    coma = [0.0] * 8
    coma[6] = 2.0  # Z7: (3 rho^3 - 2 rho) cos(theta): thicker on one side
    cs = compile_system(_lens({"radius": 60.0}, {"type": "zernike", "radius": -60.0, "zernike_coefficients": coma, "zernike_norm_radius": 6.0}))
    h = 5.0
    ph = np.linspace(0, 2 * np.pi, 3601)
    a, b = cs.shapes[1], cs.shapes[2]
    brute = np.min(5.0 + b.sag_xy(h * np.cos(ph), h * np.sin(ph)) - a.sag_xy(h * np.cos(ph), h * np.sin(ph)))
    e = edge_thickness(cs, 1, h)
    assert e == pytest.approx(brute, abs=2e-4)
    assert e < 5.0 + float(b.sag(h * h)) - float(a.sag(h * h)) - 0.1  # thinner than the y-section suggests


def test_checks_and_diagnostics():
    with pytest.raises(ValueError, match="curvature solves"):
        _lens({"type": "zernike", "radius": 60.0, "curvature_solve": {"type": "f_number", "target": 4}})
    with pytest.raises(ValueError):
        _lens({"type": "zernike", "zernike_coefficients": [0.0] * 38})
    cs = compile_system(_lens({"radius": 60.0, "zernike_coefficients": [0, 0, 0, 0.1]}))
    assert any(d.code == "ZERNIKE_IGNORED" for d in cs.diagnostics)
    ev = evaluate_system(compile_system(_lens({"type": "zernike", "radius": 60.0, "zernike_coefficients": [0, 0, 0, 0.01], "zernike_norm_radius": 2.0}, {"radius": -150.0})))
    assert any(d["code"] == "ZERNIKE_EXTRAPOLATED" for d in ev["diagnostics"])
    zs = ev["surfaces"][1]["zernike"]
    assert zs["norm_radius"] == 2.0 and zs["poly"][2][0] == pytest.approx(0.02) and zs["poly"][0][2] == pytest.approx(0.02)
    assert ev["surfaces"][2]["zernike"] is None


def test_cad_export_skips_zernike_elements():
    cs = compile_system(_lens({"type": "zernike", "radius": 60.0, "zernike_coefficients": [0, 0, 0, 0.01]}, {"radius": -150.0}))
    rep = export_system_cad(cs, "step", include_rays=False, include_stop=True, include_image=False)["report"]
    assert rep["skipped"] and "Zernike" in rep["skipped"][0]["reason"]


def test_zernike_variables_optimise_spherical_aberration():
    sysm = _lens({"type": "zernike", "radius": 50.0, "zernike_coefficients": [0.0] * 9, "zernike_norm_radius": 6.0}, {"radius": -200.0}, length=90.0, epd=12.0)
    spec = OptimizationSpec.model_validate(
        {
            "variables": [{"surface_id": "f", "parameter": "zern_9"}, {"surface_id": "b", "parameter": "thickness", "min": 60, "max": 120}],
            "operands": [{"type": "rms_spot", "field": 0, "wavelength": 0, "rings": 6}],
            "algorithm": "local",
            "max_evaluations": 300,
        }
    )
    res = optimize(sysm, spec)
    assert res["final_merit"] < 0.2 * res["initial_merit"]
    out = OpticalSystem.model_validate(res["system"])
    assert out.surfaces[1].zernike_coefficients[8] == pytest.approx(res["variables"][0]["final"])
    assert sysm.surfaces[1].zernike_coefficients[8] == 0.0
    bad = OptimizationSpec.model_validate({"variables": [{"surface_id": "b", "parameter": "zern_4"}], "operands": [{"type": "efl", "target": 100}]})
    with pytest.raises(ValueError, match="Zernike"):
        MeritFunction(sysm, bad)


def test_project_round_trip_keeps_zernike_terms():
    from opticore.samples import get_sample

    p = get_sample("singlet")
    d = p.model_dump()
    d["system"]["surfaces"][1].update({"type": "zernike", "zernike_coefficients": [0, 0, 0, 0, 0.003, 0, -0.001], "zernike_norm_radius": 12.5})
    proj = Project.model_validate(d)
    q, notes = load_project(dump_project(proj))
    assert q.system.surfaces[1].zernike_coefficients == [0, 0, 0, 0, 0.003, 0, -0.001]
    assert q.system.surfaces[1].zernike_norm_radius == 12.5
    assert not [n for n in notes if "Checksum" in n]
