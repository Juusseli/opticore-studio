import numpy as np
import pytest

from opticore.io.cad import export_system_cad
from opticore.optimize.merit import MeritFunction, Operand, OptimizationSpec, Variable, apply_values, get_variable_value
from opticore.paraxial import compute_pupil, paraxial_data
from opticore.raytrace import launch, trace
from opticore.surfaces import OK, BiconicShape, Shape
from opticore.system import compile_system

from .conftest import make_system

LAM = 0.5875618


def _lens(front: dict, back: dict | None = None, length: float = 150.0, fields=None):
    return make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "f", "thickness": 5.0, "material": "N-BK7", "is_stop": True, **front},
            {"id": "b", "thickness": length, **(back or {})},
            {"id": "img"},
        ],
        wavelengths=[{"value": LAM}],
        fields=fields or [{"y": 0.0}],
        aperture={"type": "epd", "value": 10.0},
    )


def test_equal_sections_reproduce_the_standard_conic_exactly():
    rng = np.random.default_rng(3)
    bic = BiconicShape(1 / 40.0, -0.4, 1 / 40.0, -0.4)
    std = Shape(1 / 40.0, -0.4, ())
    P = np.column_stack([rng.uniform(-6, 6, 200), rng.uniform(-6, 6, 200), np.full(200, -5.0)])
    D = np.column_stack([rng.uniform(-0.1, 0.1, 200), rng.uniform(-0.1, 0.1, 200), np.ones(200)])
    D /= np.linalg.norm(D, axis=1, keepdims=True)
    s1, st1 = bic.intersect(P, D)
    s2, st2 = std.intersect(P, D)
    assert np.all(st1 == OK) and np.all(st2 == OK)
    assert np.allclose(s1, s2, atol=1e-12)
    q = P + s1[:, None] * D
    assert np.allclose(bic.normals(q), std.normals(q), atol=1e-12)


def test_intersection_lies_on_the_surface_and_normals_match_the_gradient():
    rng = np.random.default_rng(7)
    bic = BiconicShape(1 / 35.0, 0.3, -1 / 60.0, -1.2)
    P = np.column_stack([rng.uniform(-5, 5, 300), rng.uniform(-5, 5, 300), np.full(300, -3.0)])
    D = np.column_stack([rng.uniform(-0.15, 0.15, 300), rng.uniform(-0.15, 0.15, 300), np.ones(300)])
    D /= np.linalg.norm(D, axis=1, keepdims=True)
    s, st = bic.intersect(P, D)
    assert np.all(st == OK)
    q = P + s[:, None] * D
    assert np.max(np.abs(q[:, 2] - bic.sag_xy(q[:, 0], q[:, 1]))) < 1e-11
    h = 1e-6
    gx = (bic.sag_xy(q[:, 0] + h, q[:, 1]) - bic.sag_xy(q[:, 0] - h, q[:, 1])) / (2 * h)
    gy = (bic.sag_xy(q[:, 0], q[:, 1] + h) - bic.sag_xy(q[:, 0], q[:, 1] - h)) / (2 * h)
    n_fd = np.column_stack([-gx, -gy, np.ones_like(gx)])
    n_fd /= np.linalg.norm(n_fd, axis=1, keepdims=True)
    assert np.allclose(bic.normals(q), n_fd, atol=1e-8)


def _fan(cs, axis: str, rho=np.linspace(-1, 1, 9)):
    pupil = compute_pupil(cs)
    px = rho if axis == "x" else 0 * rho
    py = rho if axis == "y" else 0 * rho
    P0, D0, opl = launch(cs, 0, 0, px, py, pupil)
    r = trace(cs, 0, P0, D0, opl)
    assert r.ok.all()
    return r.image_xy()


def test_each_section_behaves_like_the_standard_surface_of_that_section():
    # rays in the x-z plane only see the x section, rays in the y-z plane only the y section
    Rx, kx, Ry, ky = 45.0, -0.5, 80.0, 0.0
    bic = compile_system(_lens({"type": "biconic", "radius": Ry, "conic": ky, "radius_x": Rx, "conic_x": kx}))
    as_x = compile_system(_lens({"radius": Rx, "conic": kx}))
    as_y = compile_system(_lens({"radius": Ry, "conic": ky}))
    xb, xs = _fan(bic, "x"), _fan(as_x, "y")  # x fan of the biconic == meridional fan of the x-section lens
    assert np.allclose(xb[:, 0], xs[:, 1], atol=1e-12) and np.allclose(xb[:, 1], 0, atol=1e-12)
    yb, ys = _fan(bic, "y"), _fan(as_y, "y")
    assert np.allclose(yb[:, 1], ys[:, 1], atol=1e-12)
    # paraxial data follow the y section
    assert paraxial_data(bic).efl == pytest.approx(paraxial_data(as_y).efl, rel=1e-13)
    assert any(d.code == "BICONIC_PARAXIAL" for d in bic.diagnostics)


def test_cylinder_lens_has_no_power_in_x():
    cyl = compile_system(_lens({"type": "biconic", "radius": 60.0, "radius_x": None}))
    x = _fan(cyl, "x")
    pupil = compute_pupil(cyl)
    assert np.allclose(x[:, 0], np.linspace(-1, 1, 9) * pupil.r_ep, atol=1e-12)  # collimated x fan passes undeviated
    n = cyl.n_after[0, 1]
    assert paraxial_data(cyl).efl == pytest.approx(60.0 / (n - 1), rel=1e-12)  # plano-convex in y


def test_edge_thickness_and_domain_use_both_sections():
    from opticore.analysis.evaluate import edge_thickness, validate_geometry

    sysm = _lens({"type": "biconic", "radius": 200.0, "radius_x": 12.0})
    cs = compile_system(sysm)
    h = 5.0
    zx = float(cs.shapes[1].sag_x(h * h))
    assert edge_thickness(cs, 1, h) == pytest.approx(5.0 - zx, rel=1e-12)  # the x section is the thicker sag
    tight = make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "f", "type": "biconic", "radius": 200.0, "radius_x": 6.0, "thickness": 5.0, "material": "N-BK7", "is_stop": True, "semi_diameter": 8.0, "semi_diameter_mode": "fixed"},
            {"id": "b", "thickness": 100.0},
            {"id": "img"},
        ],
        wavelengths=[{"value": LAM}],
        aperture={"type": "epd", "value": 4.0},
    )
    cs2 = compile_system(tight)
    sd = np.array([0.0, 8.0, 8.0, 8.0])
    assert any(d.code == "SD_EXCEEDS_SURFACE" for d in validate_geometry(cs2, sd))


def test_biconic_variables_and_cad_export_skip():
    sysm = _lens({"type": "biconic", "radius": 80.0, "radius_x": 45.0, "conic_x": -0.2}, fields=[{"y": 0.0}, {"x": 1.0, "y": 0.0}])
    v1 = Variable(surface_id="f", parameter="curvature_x")
    v2 = Variable(surface_id="f", parameter="conic_x")
    assert get_variable_value(sysm, v1) == pytest.approx(1 / 45.0) and get_variable_value(sysm, v2) == pytest.approx(-0.2)
    d = apply_values(sysm.model_dump(), [v1, v2], np.array([1 / 50.0, -0.3]), {s.id: i for i, s in enumerate(sysm.surfaces)})
    assert d["surfaces"][1]["radius_x"] == pytest.approx(50.0) and d["surfaces"][1]["conic_x"] == -0.3
    MeritFunction(sysm, OptimizationSpec(variables=[v1], operands=[Operand(type="rms_spot", rings=2)]))
    with pytest.raises(ValueError):
        MeritFunction(_lens({"radius": 80.0}), OptimizationSpec(variables=[v1], operands=[Operand(type="rms_spot", rings=2)]))
    cs = compile_system(sysm)
    rep = export_system_cad(cs, "step", include_rays=False, include_stop=True, include_image=False)["report"]
    assert rep["skipped"] and "biconic" in rep["skipped"][0]["reason"]
