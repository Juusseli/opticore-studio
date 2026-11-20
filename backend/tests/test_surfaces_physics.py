import math

import numpy as np
import pytest

from opticore.physics import fresnel, reflect, refract, unpolarized_reflectance
from opticore.surfaces import MISS, OK, OUT_OF_DOMAIN, Shape


def unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


# ---------------------------------------------------------------- surfaces
def test_sphere_intersection_matches_geometry(rng):
    R = 50.0
    sh = Shape(curvature=1 / R)
    P = np.column_stack([rng.uniform(-10, 10, 50), rng.uniform(-10, 10, 50), np.full(50, -20.0)])
    D = unit(np.column_stack([rng.uniform(-0.1, 0.1, 50), rng.uniform(-0.1, 0.1, 50), np.ones(50)]))
    s, st = sh.intersect(P, D)
    assert np.all(st == OK)
    Q = P + s[:, None] * D
    # point lies on the sphere centred at (0,0,R) on the vertex side (z < R)
    assert np.allclose(np.linalg.norm(Q - [0, 0, R], axis=1), R, atol=1e-10)
    assert np.all(Q[:, 2] < R)


def test_plane_and_parallel_ray_miss():
    sh = Shape()
    s, st = sh.intersect(np.array([[0.0, 0, -5], [0, 0, -5]]), np.array([[0.0, 0, 1], [1.0, 0, 0]]))
    assert st[0] == OK and s[0] == pytest.approx(5.0)
    assert st[1] == MISS


def test_sphere_miss():
    sh = Shape(curvature=1 / 5.0)
    s, st = sh.intersect(np.array([[20.0, 0, -5]]), np.array([[0.0, 0, 1]]))
    assert st[0] == MISS


def test_paraboloid_sag():
    c, k = 1 / 100.0, -1.0
    sh = Shape(curvature=c, conic=k)
    r = np.linspace(0, 40, 9)
    assert np.allclose(sh.sag(r**2), c * r**2 / 2, atol=1e-13)


def test_conic_domain():
    sh = Shape(curvature=1 / 10.0, conic=0.0)
    assert sh.domain_ok(np.array([99.0]))[0]
    assert not sh.domain_ok(np.array([101.0]))[0]


def test_asphere_intersection_vs_bisection(rng):
    sh = Shape(curvature=1 / 40.0, conic=-0.5, aspheric=(1e-5, -2e-8))
    P = np.column_stack([rng.uniform(-8, 8, 30), rng.uniform(-8, 8, 30), np.full(30, -10.0)])
    D = unit(np.column_stack([rng.uniform(-0.05, 0.05, 30), rng.uniform(-0.05, 0.05, 30), np.ones(30)]))
    s, st = sh.intersect(P, D)
    assert np.all(st == OK)
    for i in range(30):
        f = lambda t: (P[i, 2] + t * D[i, 2]) - sh.sag((P[i, 0] + t * D[i, 0]) ** 2 + (P[i, 1] + t * D[i, 1]) ** 2)
        a, b = 0.0, 30.0
        for _ in range(200):
            m = 0.5 * (a + b)
            if f(a) * f(m) <= 0:
                b = m
            else:
                a = m
        assert s[i] == pytest.approx(0.5 * (a + b), abs=1e-9)


def test_normals_match_numerical_gradient(rng):
    sh = Shape(curvature=1 / 30.0, conic=-0.8, aspheric=(2e-6,))
    pts = np.column_stack([rng.uniform(-6, 6, 20), rng.uniform(-6, 6, 20)])
    z = sh.sag(pts[:, 0] ** 2 + pts[:, 1] ** 2)
    n = sh.normals(np.column_stack([pts, z]))
    h = 1e-6
    for (x, y), nn in zip(pts, n):
        dzdx = (sh.sag((x + h) ** 2 + y**2) - sh.sag((x - h) ** 2 + y**2)) / (2 * h)
        dzdy = (sh.sag(x**2 + (y + h) ** 2) - sh.sag(x**2 + (y - h) ** 2)) / (2 * h)
        ref = unit([-dzdx, -dzdy, 1.0])
        assert np.allclose(nn, ref, atol=1e-7)


def test_hyperboloid_far_ray_out_of_domain_or_miss():
    sh = Shape(curvature=1 / 10.0, conic=0.5)  # oblate ellipsoid, finite extent
    s, st = sh.intersect(np.array([[30.0, 0, -5]]), np.array([[0.0, 0, 1]]))
    assert st[0] in (MISS, OUT_OF_DOMAIN)


# ---------------------------------------------------------------- physics
def test_snell_planar_interface():
    theta = math.radians(30)
    d = np.array([[math.sin(theta), 0, math.cos(theta)]])
    t, tir, ci, ct = refract(d, np.array([[0, 0, 1.0]]), 1.0, 1.5)
    assert not tir[0]
    assert math.asin(t[0, 0]) == pytest.approx(math.asin(math.sin(theta) / 1.5), abs=1e-14)
    assert np.linalg.norm(t[0]) == pytest.approx(1.0)


def test_snell_normal_orientation_independent():
    d = unit([[0.3, 0.1, 1.0]])
    a = refract(d, np.array([[0, 0, 1.0]]), 1.2, 1.7)[0]
    b = refract(d, np.array([[0, 0, -1.0]]), 1.2, 1.7)[0]
    assert np.allclose(a, b)


def test_total_internal_reflection():
    crit = math.asin(1 / 1.5)
    for ang, expect in [(crit - 0.01, False), (crit + 0.01, True), (math.radians(45), True)]:
        d = np.array([[math.sin(ang), 0, math.cos(ang)]])
        _, tir, _, _ = refract(d, np.array([[0, 0, 1.0]]), 1.5, 1.0)
        assert bool(tir[0]) is expect


def test_reflection_law():
    d = unit([[0.2, -0.4, 1.0]])
    n = unit([[0.1, 0.3, -1.0]])
    r, _ = reflect(d, n)
    # angle of incidence equals angle of reflection, coplanar
    assert np.dot(r[0], n[0]) == pytest.approx(-np.dot(d[0], n[0]))
    assert np.dot(np.cross(d[0], n[0]), r[0]) == pytest.approx(0.0, abs=1e-15)


def test_fresnel_normal_incidence():
    R = unpolarized_reflectance(1.0, 1.5, 1.0, 1.0)
    assert R == pytest.approx(((1.5 - 1.0) / 2.5) ** 2, rel=1e-14)  # 0.04


@pytest.mark.parametrize("n1,n2", [(1.0, 1.5), (1.5, 1.0), (1.33, 1.8)])
def test_fresnel_energy_conservation(n1, n2):
    th = np.linspace(0, math.asin(min(1.0, n2 / n1)) - 1e-6 if n1 > n2 else math.pi / 2 - 1e-6, 50)
    ci = np.cos(th)
    st = n1 / n2 * np.sin(th)
    ct = np.sqrt(1 - st**2)
    f = fresnel(n1, n2, ci, ct)
    assert np.allclose(f["Rs"] + f["Ts"], 1.0, atol=1e-13)
    assert np.allclose(f["Rp"] + f["Tp"], 1.0, atol=1e-13)


def test_brewster_angle():
    n1, n2 = 1.0, 1.5
    th = math.atan(n2 / n1)
    ci = math.cos(th)
    ct = math.sqrt(1 - (n1 / n2 * math.sin(th)) ** 2)
    assert fresnel(n1, n2, ci, ct)["Rp"] == pytest.approx(0.0, abs=1e-15)
