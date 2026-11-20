"""Forbes Q-type aspheres and XY-polynomial freeforms: polynomial identities and
orthogonality, closed forms, sag/derivative/intersection consistency, even-asphere conversion, Seidel terms,
tracing and optimisation."""

import math

import numpy as np
import pytest
from scipy.special import eval_jacobi

from opticore.model import OpticalSystem
from opticore.optimize.engine import optimize
from opticore.optimize.merit import OptimizationSpec
from opticore.paraxial import compute_pupil, paraxial_data
from opticore.paraxial import seidel_coefficients as seidel
from opticore.qpoly import convert_surface, monomial_coefficients, qbfs, qcon, series, xy_exponents, xy_poly
from opticore.raytrace import gauss_pupil, trace_pupil
from opticore.samples import singlet
from opticore.surfaces import OK, QShape, Shape, XYPolyShape
from opticore.system import compile_system

GL_X, GL_W = np.polynomial.legendre.leggauss(80)
X01, W01 = 0.5 * (GL_X + 1.0), 0.5 * GL_W  # Gauss-Legendre on [0, 1]


# ----------------------------------------------------------------------------- polynomial identities
def test_qcon_closed_forms_and_orthogonality():
    x = np.linspace(0.0, 1.0, 11)
    Q, _ = qcon(x, 3)
    assert Q[0] == pytest.approx(np.ones_like(x))
    assert Q[1] == pytest.approx(6 * x - 5, abs=1e-14)  # P_1^(0,4)(2x - 1)
    assert Q[2] == pytest.approx(eval_jacobi(2, 0, 4, 2 * x - 1), abs=1e-14)
    assert qcon(np.array([1.0]), 12)[0][:, 0] == pytest.approx(np.ones(12))  # Q_m(1) = 1
    # int_0^1 x^4 Q_m Q_n dx = delta_mn / (2n + 5)
    Q, _ = qcon(X01, 16)
    G = (Q * (W01 * X01**4)) @ Q.T
    assert G == pytest.approx(np.diag(1.0 / (2 * np.arange(16) + 5)), abs=1e-13)


def test_qbfs_closed_forms_and_slope_orthonormality():
    x = np.linspace(0.0, 1.0, 11)
    Q, _ = qbfs(x, 4)
    assert Q[0] == pytest.approx(np.ones_like(x))
    assert Q[1] == pytest.approx((13 - 16 * x) / math.sqrt(19), abs=1e-14)
    assert Q[2] == pytest.approx(math.sqrt(2 / 95) * (29 - 4 * x * (25 - 19 * x)), abs=1e-13)
    # orthonormal in the slope norm (2/pi) int_0^1 D[Q_m] D[Q_n] du / sqrt(1 - u^2),
    # D[p](u) = d/du [u^2 (1 - u^2) p(u^2)]; Gauss-Chebyshev quadrature is exact for these polynomials
    N = 200
    u = np.cos((2 * np.arange(1, N + 1) - 1) * np.pi / (2 * N))
    u = u[u > 0]
    M = 14
    Q, dQ = qbfs(u * u, M)
    D = (2 * u - 4 * u**3) * Q + u**2 * (1 - u**2) * 2 * u * dQ
    G = (D @ D.T) / N * 2  # (2/pi) * (pi/N) * sum over the positive half (even integrand)
    assert G == pytest.approx(np.eye(M), abs=1e-11)
    assert np.all(qbfs(np.array([0.0]), M)[0][:, 0] > 0)  # sign convention Q_m(0) > 0


@pytest.mark.parametrize("kind", ["qcon", "qbfs"])
def test_derivatives_and_power_series(kind):
    a = [0.3, -0.2, 0.15, 0.08, -0.05, 0.02, 0.01]
    x = np.linspace(0.01, 0.99, 25)
    S, dS = series(kind, a, x)
    h = 1e-6
    Sp, _ = series(kind, a, x + h)
    Sm, _ = series(kind, a, x - h)
    assert dS == pytest.approx((Sp - Sm) / (2 * h), rel=1e-7, abs=1e-8)
    b = monomial_coefficients(kind, a)
    assert np.polynomial.Polynomial(b)(x) == pytest.approx(S, abs=1e-12)


# ----------------------------------------------------------------------------- shapes
def test_qcon_sag_against_the_definition_and_normals():
    c, k, rn, a = 1 / 35.0, -0.6, 9.0, (2e-3, -5e-4, 1e-4, 3e-5)
    q = QShape(c, k, "qcon", a, rn)
    r = np.linspace(0, rn, 300)
    base = c * r * r / (1 + np.sqrt(1 - (1 + k) * c * c * r * r))
    u2 = (r / rn) ** 2
    direct = base + u2**2 * sum(am * eval_jacobi(m, 0, 4, 2 * u2 - 1) for m, am in enumerate(a))
    assert q.sag(r * r) == pytest.approx(direct, abs=1e-15)
    # paraxial curvature and the Seidel fourth-order term of an even asphere with the same r^4 coefficient
    assert q.curvature == c
    a4 = sum(am * eval_jacobi(m, 0, 4, -1.0) for m, am in enumerate(a)) / rn**4
    assert q.seidel_b4 == pytest.approx(k * c**3 + 8 * a4, rel=1e-13)


def test_qbfs_sag_against_the_definition():
    c, rn, a = 1 / 28.0, 8.0, (4e-3, -1e-3, 2e-4)
    q = QShape(c, 0.0, "qbfs", a, rn)
    r = np.linspace(0, rn, 300)
    root = np.sqrt(1 - c * c * r * r)
    u2 = (r / rn) ** 2
    S = a[0] + a[1] * (13 - 16 * u2) / math.sqrt(19) + a[2] * math.sqrt(2 / 95) * (29 - 4 * u2 * (25 - 19 * u2))
    assert q.sag(r * r) == pytest.approx(c * r * r / (1 + root) + u2 * (1 - u2) * S / root, abs=1e-15)
    # paraxial vertex curvature c + 2 S(0) / r_n^2, from the sag's r^2 coefficient
    s0 = a[0] + a[1] * 13 / math.sqrt(19) + a[2] * 29 * math.sqrt(2 / 95)
    assert q.curvature == pytest.approx(c + 2 * s0 / rn**2, rel=1e-14)
    rr = np.array([1e-3])
    assert 2 * q.sag(rr * rr)[0] / 1e-6 == pytest.approx(q.curvature, rel=1e-6)


@pytest.mark.parametrize("shape", [QShape(1 / 30.0, -0.8, "qcon", (3e-3, -6e-4, 2e-4), 7.0), QShape(-1 / 45.0, 0.0, "qbfs", (-2e-3, 5e-4, 1e-4), 7.0), XYPolyShape(1 / 40.0, 0.0, (), (1e-3, -5e-4, 2e-3, 1e-3, -1e-3, 3e-4, 0, 2e-4, -1e-4), 7.0)])
def test_intersections_lie_on_the_surface_with_consistent_normals(shape):
    rng = np.random.default_rng(4)
    n = 300
    P = np.column_stack([rng.uniform(-6, 6, n), rng.uniform(-6, 6, n), np.full(n, -10.0)])
    D = np.column_stack([rng.uniform(-0.05, 0.05, n), rng.uniform(-0.05, 0.05, n), np.ones(n)])
    D /= np.linalg.norm(D, axis=1, keepdims=True)
    s, st = shape.intersect(P, D)
    ok = st == OK
    assert ok.mean() > 0.9
    q = P[ok] + s[ok, None] * D[ok]
    assert q[:, 2] == pytest.approx(shape.sag_xy(q[:, 0], q[:, 1]), abs=1e-11)
    nrm = shape.normals(q)
    h = 1e-6
    zx = (shape.sag_xy(q[:, 0] + h, q[:, 1]) - shape.sag_xy(q[:, 0] - h, q[:, 1])) / (2 * h)
    zy = (shape.sag_xy(q[:, 0], q[:, 1] + h) - shape.sag_xy(q[:, 0], q[:, 1] - h)) / (2 * h)
    ref = np.column_stack([-zx, -zy, np.ones_like(zx)])
    ref /= np.linalg.norm(ref, axis=1, keepdims=True)
    assert nrm == pytest.approx(ref, abs=1e-8)


def test_xy_terms_and_closed_form_paraboloid():
    assert xy_exponents(10) == [(1, 0), (0, 1), (2, 0), (1, 1), (0, 2), (3, 0), (2, 1), (1, 2), (0, 3), (4, 0)]
    c = xy_poly([0.0, 0.0, 2.0, 0.0, 2.0])
    assert c[2, 0] == 2.0 and c[0, 2] == 2.0 and c.sum() == 4.0
    # x^2 and y^2 terms a (x^2 + y^2)/R^2 on a plane are the paraboloid c = 2a/R^2, k = -1
    a, R = 0.05, 6.0
    xy = XYPolyShape(0.0, 0.0, (), (0.0, 0.0, a, 0.0, a), R)
    para = Shape(2 * a / R**2, -1.0)
    rng = np.random.default_rng(1)
    P = np.column_stack([rng.uniform(-4, 4, 50), rng.uniform(-4, 4, 50), np.full(50, -5.0)])
    D = np.column_stack([rng.uniform(-0.1, 0.1, 50), rng.uniform(-0.1, 0.1, 50), np.ones(50)])
    D /= np.linalg.norm(D, axis=1, keepdims=True)
    s1, _ = xy.intersect(P, D)
    s2, _ = para.intersect(P, D)
    assert s1 == pytest.approx(s2, abs=1e-12)
    assert xy.curvature == pytest.approx(2 * a / R**2) and xy.curvature_x == pytest.approx(2 * a / R**2)


# ----------------------------------------------------------------------------- conversion and systems
def _with_surface(system, i, **patch):
    d = system.model_dump()
    d["surfaces"][i].update(patch)
    return OpticalSystem.model_validate(d)


def _rms(cs, rings=6):
    pupil = compute_pupil(cs)
    px, py, w = gauss_pupil(rings)
    r = trace_pupil(cs, cs.model.primary_wavelength, 0, px, py, pupil)
    xy = r.image_xy()
    c = (w[:, None] * xy).sum(0) / w.sum()
    return math.sqrt((w * ((xy - c) ** 2).sum(1)).sum() / w.sum())


def test_even_asphere_conversion_traces_identically():
    """Benchmark: an even asphere rewritten as Qcon reproduces its sag exactly and its trace to 1e-12 mm;
    as Qbfs (best-fit sphere + 6 terms) to the fit residual."""
    base = singlet().system
    asp = _with_surface(base, 1, type="even_asphere", conic=-0.6, aspheric=[-2e-6, 1e-9])
    cs0 = compile_system(asp)
    for to, tol in (("qcon", 1e-12), ("qbfs", 1e-9)):
        conv = convert_surface(asp.surfaces[1].model_dump(), to, 6.0)
        assert conv["residual_max_mm"] < tol
        qs = _with_surface(asp, 1, **conv["surface"])
        cs1 = compile_system(qs)
        assert _rms(cs1) == pytest.approx(_rms(cs0), abs=tol * 10)
        # Seidel spherical aberration from the equivalent fourth-order term
        assert seidel(cs1)["total"]["SI"] == pytest.approx(seidel(cs0)["total"]["SI"], rel=1e-6)
        assert paraxial_data(cs1).efl == pytest.approx(paraxial_data(cs0).efl, rel=1e-9)
    with pytest.raises(ValueError):
        convert_surface({"type": "biconic", "radius": 10.0}, "qcon", 5.0)


def test_qcon_singlet_optimises():
    """Acceptance criterion: a Qcon front surface of the plano-convex singlet, with its first two Q coefficients and the
    image distance as variables, corrects the on-axis spherical aberration."""
    p = singlet()
    s = _with_surface(p.system, 1, type="qcon", q_coefficients=[0.0, 0.0], q_norm_radius=5.0)
    d = s.model_dump()
    d["fields"] = [{"y": 0.0}]
    s = OpticalSystem.model_validate(d)
    before = _rms(compile_system(s))
    spec = OptimizationSpec.model_validate(
        {
            "variables": [{"surface_id": "s1", "parameter": "q_1"}, {"surface_id": "s1", "parameter": "q_2"}, {"surface_id": "s2", "parameter": "thickness", "min": 80, "max": 120}],
            "operands": [{"type": "rms_spot", "target": 0.0, "weight": 1.0, "rings": 6, "wavelength": 1}],
            "algorithm": "local",
            "max_evaluations": 400,
        }
    )
    res = optimize(s, spec)
    after = _rms(compile_system(OpticalSystem.model_validate(res["system"])))
    assert after < before / 20


def test_xy_freeform_optimises_astigmatism_away():
    """Acceptance criterion: an XY-polynomial surface with an astigmatic x^2 term; optimising its x^2 and y^2 terms
    restores a sharp on-axis focus (the two terms become equal)."""
    p = singlet()
    s = _with_surface(p.system, 2, type="xy_polynomial", xy_coefficients=[0.0, 0.0, 2e-3, 0.0, 0.0], xy_norm_radius=5.0)
    d = s.model_dump()
    d["fields"] = [{"y": 0.0}]
    s = OpticalSystem.model_validate(d)
    before = _rms(compile_system(s))
    spec = OptimizationSpec.model_validate(
        {
            "variables": [{"surface_id": "s2", "parameter": "xy_3"}, {"surface_id": "s2", "parameter": "xy_5"}],
            "operands": [{"type": "rms_spot", "target": 0.0, "weight": 1.0, "rings": 6, "wavelength": 1}],
            "algorithm": "local",
            "max_evaluations": 400,
        }
    )
    res = optimize(s, spec)
    out = OpticalSystem.model_validate(res["system"])
    after = _rms(compile_system(out))
    xy = out.surfaces[2].xy_coefficients
    assert after < before / 5
    assert xy[2] == pytest.approx(xy[4], abs=2e-5)


def test_validation_and_diagnostics():
    p = singlet()
    with pytest.raises(ValueError):
        _with_surface(p.system, 1, type="xy_polynomial", curvature_solve={"type": "f_number", "target": 5.0})
    cs = compile_system(_with_surface(p.system, 1, type="qbfs", conic=-1.0, q_coefficients=[1e-3]))
    assert "QBFS_CONIC_IGNORED" in [d.code for d in cs.diagnostics]
    spec = OptimizationSpec.model_validate({"variables": [{"surface_id": "s1", "parameter": "q_1"}], "operands": [{"type": "efl", "target": 100}]})
    with pytest.raises(ValueError):
        optimize(p.system, spec)  # q variable on a standard surface


def test_convert_api_and_geometry_for_drawing():
    from fastapi.testclient import TestClient

    from opticore.api.main import app

    c = TestClient(app)
    asp = _with_surface(singlet().system, 1, type="even_asphere", conic=-0.6, aspheric=[-2e-6, 1e-9])
    r = c.post("/api/v1/surface/convert-q", json={"system": asp.model_dump(mode="json"), "surface": 1, "to": "qcon"})
    assert r.status_code == 200 and r.json()["surface"]["type"] == "qcon"
    q = _with_surface(asp, 1, **r.json()["surface"])
    ev = c.post("/api/v1/system/evaluate", json={"system": q.model_dump(mode="json")}).json()
    g = ev["surfaces"][1]["qpoly"]
    assert g["kind"] == "qcon" and len(g["series"]) == 2
    bad = c.post("/api/v1/surface/convert-q", json={"system": asp.model_dump(mode="json"), "surface": 3, "to": "qcon"})
    assert bad.status_code == 422


def test_qcon_element_exports_with_its_volume():
    pytest.importorskip("OCP")
    from opticore.analysis.evaluate import auto_semi_diameters, effective_semi_diameters
    from opticore.io.cad import build_optics

    s = _with_surface(singlet().system, 1, type="qcon", conic=-0.6, q_coefficients=[2e-3, -4e-4], q_norm_radius=5.0)
    cs = compile_system(s)
    sd = effective_semi_diameters(cs, auto_semi_diameters(cs, compute_pupil(cs), {}))
    _items, rep = build_optics(cs, sd, include_stop=False, include_image=False, include_rays=False)
    assert rep["solids"] and rep["solids"][0]["front"] == "asphere"
    assert rep["max_profile_deviation_mm"] < 1e-6
    assert rep["solids"][0]["volume_mm3"] == pytest.approx(rep["solids"][0]["element_volume_mm3"], rel=1e-6)
