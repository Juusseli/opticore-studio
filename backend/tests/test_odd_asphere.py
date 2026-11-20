"""Odd aspheres (z = conic + sum beta_i r^i): sag, normals, intersection, paraxial and Seidel equivalents, ZMX ODDASPH."""

import numpy as np
import pytest

from opticore.io.zmx import parse_zmx
from opticore.model import OpticalSystem
from opticore.paraxial import compute_pupil, paraxial_data, seidel_coefficients
from opticore.raytrace import hexapolar, trace_pupil
from opticore.surfaces import OK, OddShape, Shape
from opticore.system import compile_system

from .conftest import make_system


def test_sag_slope_and_normals_against_finite_differences():
    sh = OddShape(0.05, -0.7, (0.0, 0.002, -3e-4, 1e-4, 2e-6, -1e-7))
    r = np.linspace(0.05, 6.0, 40)
    z = sh.sag(r * r)
    ref = Shape(0.05, -0.7, ()).sag(r * r) + 0.002 * r**2 - 3e-4 * r**3 + 1e-4 * r**4 + 2e-6 * r**5 - 1e-7 * r**6
    assert np.allclose(z, ref, rtol=0, atol=1e-15)
    h = 1e-6
    dz = (sh.sag((r + h) ** 2) - sh.sag((r - h) ** 2)) / (2 * h)
    assert np.allclose(sh.slope_over_r(r * r) * r, dz, rtol=1e-7, atol=1e-10)
    p = np.stack([r * 0.6, r * 0.8, z], axis=1)
    n = sh.normals(p)
    t = np.stack([0.6 * np.ones_like(r), 0.8 * np.ones_like(r), dz], axis=1)  # radial tangent
    assert np.allclose(np.einsum("ij,ij->i", n, t), 0.0, atol=1e-9)
    assert sh.curvature == pytest.approx(0.05 + 2 * 0.002)


def test_intersection_lies_on_the_surface():
    sh = OddShape(-0.03, 1.2, (0.0, 0.0, 5e-4, -2e-4, 1e-5))
    rng = np.random.default_rng(2)
    P = np.c_[rng.uniform(-3, 3, 200), rng.uniform(-3, 3, 200), np.full(200, -5.0)]
    D = np.c_[rng.normal(0, 0.1, 200), rng.normal(0, 0.1, 200), np.ones(200)]
    D /= np.linalg.norm(D, axis=1, keepdims=True)
    s, st = sh.intersect(P, D)
    assert np.all(st == OK)
    q = P + s[:, None] * D
    assert np.allclose(q[:, 2], sh.sag(q[:, 0] ** 2 + q[:, 1] ** 2), atol=1e-11)


def _singlet(front: dict):
    return make_system(
        [{"thickness": None}, {"thickness": 5.0, "material": "N-BK7", "is_stop": True, **front}, {"radius": -60.0, "thickness": 90.0}, {}],
        wavelengths=[{"value": 0.5875618}],
        fields=[{"y": 0.0}, {"y": 5.0}],
        aperture={"type": "epd", "value": 16.0},
    )


def test_even_terms_reproduce_the_even_asphere_exactly():
    """beta_4, beta_6 on r^4, r^6 are the even asphere's A4, A6: identical traces, paraxial data and Seidel sums."""
    even = compile_system(_singlet({"type": "even_asphere", "radius": 50.0, "conic": -0.4, "aspheric": [2e-6, -3e-9]}))
    odd = compile_system(_singlet({"type": "odd_asphere", "radius": 50.0, "conic": -0.4, "odd_coefficients": [0, 0, 0, 2e-6, 0, -3e-9]}))
    px, py = hexapolar(6)
    for f in (0, 1):
        a = trace_pupil(even, 0, f, px, py, compute_pupil(even))
        b = trace_pupil(odd, 0, f, px, py, compute_pupil(odd))
        assert np.allclose(a.image_xy(), b.image_xy(), atol=1e-11)
        assert np.allclose(a.opl, b.opl, atol=1e-10)
    assert paraxial_data(odd).efl == pytest.approx(paraxial_data(even).efl, rel=1e-14)
    se, so = seidel_coefficients(even), seidel_coefficients(odd)
    for k in ("SI", "SII", "SIII", "SIV", "SV"):
        assert so["total"][k] == pytest.approx(se["total"][k], rel=1e-12, abs=1e-15)


def test_r2_term_is_paraxial_curvature():
    """A plane base with beta_2 = 1 / (2 R) has the paraxial power of a sphere of radius R."""
    sph = compile_system(_singlet({"radius": 50.0}))
    odd = compile_system(_singlet({"type": "odd_asphere", "radius": None, "odd_coefficients": [0.0, 1.0 / 100.0]}))
    assert paraxial_data(odd).efl == pytest.approx(paraxial_data(sph).efl, rel=1e-12)
    codes = [d.code for d in compile_system(_singlet({"type": "odd_asphere", "radius": 50.0, "odd_coefficients": [1e-3, 0, 1e-4]})).diagnostics]
    assert "ODD_ASPHERE_PARAXIAL" in codes and "ODD_ASPHERE_CONE" in codes


def test_odd_asphere_variables():
    from opticore.optimize.merit import OptimizationSpec, apply_values, get_variable_value

    sysd = _singlet({"type": "odd_asphere", "radius": 50.0, "odd_coefficients": [0, 0, 1e-4]})
    spec = OptimizationSpec.model_validate({"variables": [{"surface_id": sysd.surfaces[1].id, "parameter": "odd_3"}], "operands": [{"type": "efl", "target": 100.0}]})
    assert get_variable_value(sysd, spec.variables[0]) == pytest.approx(1e-4)
    d = apply_values(sysd.model_dump(), spec.variables, np.array([2e-4]), {s.id: i for i, s in enumerate(sysd.surfaces)})
    assert d["surfaces"][1]["odd_coefficients"][2] == pytest.approx(2e-4)
    spec5 = OptimizationSpec.model_validate({"variables": [{"surface_id": sysd.surfaces[1].id, "parameter": "odd_5"}], "operands": [{"type": "efl", "target": 100.0}]})
    d5 = apply_values(sysd.model_dump(), spec5.variables, np.array([3e-6]), {s.id: i for i, s in enumerate(sysd.surfaces)})
    assert d5["surfaces"][1]["odd_coefficients"] == pytest.approx([0, 0, 1e-4, 0, 3e-6])


def test_zmx_odd_asphere_import():
    text = """VERS 140101 1 12345
MODE SUDO
NAME Odd
UNIT MM X W X CM MR CPMM
ENPD 10
WAVM 1 0.55 1
PWAV 1
XFLN 0
YFLN 0
FWGN 1
SURF 0
  TYPE STANDARD
  DISZ INFINITY
SURF 1
  STOP
  TYPE ODDASPH
  CURV 0.02
  CONI -0.5
  PARM 3 1.0E-4
  PARM 4 -2.0E-5
  DISZ 5
  GLAS N-BK7 0 0 1.5168 64.17
SURF 2
  TYPE STANDARD
  DISZ 50
SURF 3
  TYPE STANDARD
"""
    proj, diags = parse_zmx(text)
    s = proj.system.surfaces[1]
    assert s.type == "odd_asphere" and s.odd_coefficients == pytest.approx([0.0, 0.0, 1e-4, -2e-5])
    proj_cm, _ = parse_zmx(text.replace("UNIT MM", "UNIT CM"))
    assert proj_cm.system.surfaces[1].odd_coefficients[2] == pytest.approx(1e-4 * 10.0**-2)  # beta_3 [cm^-2] -> mm^-2
    assert isinstance(OpticalSystem.model_validate(proj.system.model_dump()), OpticalSystem)
