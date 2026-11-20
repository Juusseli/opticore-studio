"""PARAXIAL_AIMING (analysis/evaluate.aiming_check): with paraxial ray aiming, how far the chief and marginal rays
land on the stop from the points they stand for ((px, py) * r_stop), as a fraction of the stop radius.

* Exact case (analytic): with the stop as the first surface and the object at infinity the paraxial entrance pupil
  is the stop, so the miss is 0 and nothing is reported.
* Independent check: a retrofocus front (a strong negative meniscus before the stop, 40 deg field). The rays that
  OptiCore launches are traced to the stop with a trace written here (spheres, constant index, vector Snell); the
  largest miss equals the reported one.
* Levels: above 5 % a warning, 1-5 % a note (measured effects in the module notes).
"""

import math

import numpy as np
import pytest

from opticore.analysis.evaluate import AIM_INFO, AIM_WARN, aiming_check, evaluate_system
from opticore.paraxial import compute_pupil
from opticore.raytrace import launch
from opticore.samples import get_sample
from opticore.system import compile_system

from .conftest import make_system

N = 1.6
CUSTOM = [{"name": "N16", "formula": "constant", "coefficients": [N]}]
# (radius, thickness after, index after); the stop is the plane after the meniscus
FRONT = [(40.0, 2.0, N), (12.0, 20.0, 1.0)]


def _retrofocus(aiming="paraxial"):
    return make_system(
        [
            {"thickness": None},
            {"radius": 40.0, "thickness": 2.0, "material": "N16"},
            {"radius": 12.0, "thickness": 20.0},
            {"thickness": 5.0, "is_stop": True},
            {"radius": 30.0, "thickness": 5.0, "material": "N16"},
            {"radius": -30.0, "thickness": 40.0},
            {},
        ],
        wavelengths=[{"value": 0.55}],
        fields=[{"y": 0.0}, {"y": 20.0}, {"y": 40.0}],
        aperture={"type": "epd", "value": 4.0},
        ray_aiming=aiming,
    )


def _to_stop(P, D):
    """Independent trace through the front spheres (vertex of the first at z = 0) to the stop plane."""
    P, D = np.array(P, float), np.array(D, float) / np.linalg.norm(D)
    z0, n1 = 0.0, 1.0
    for R, t, n2 in FRONT:
        c = 1.0 / R
        q = P - np.array([0.0, 0.0, z0])
        B, C = D[2] - c * float(q @ D), c * float(q @ q) - 2.0 * q[2]
        P = P + C / (B + math.sqrt(B * B - c * C)) * D
        Nrm = np.array([-c * P[0], -c * P[1], 1.0 - c * (P[2] - z0)])
        Nrm /= np.linalg.norm(Nrm)
        mu, ci = n1 / n2, float(D @ Nrm)
        D = mu * D + (math.sqrt(1.0 - mu * mu * (1.0 - ci * ci)) - mu * ci) * Nrm
        n1, z0 = n2, z0 + t
    return P + (z0 - P[2]) / D[2] * D


def _aim(system, custom=()):
    cs = compile_system(system, custom)
    return cs, aiming_check(cs, compute_pupil(cs))


def test_no_report_when_the_stop_is_the_entrance_pupil():
    s = make_system(
        [{"thickness": None}, {"radius": 50.0, "thickness": 5.0, "material": "N-BK7", "is_stop": True}, {"radius": -50.0, "thickness": 48.0}, {}],
        fields=[{"y": 0.0}, {"y": 10.0}],
        aperture={"type": "epd", "value": 10.0},
    )
    assert _aim(s)[1] == []


def test_the_reported_miss_equals_an_independent_trace():
    cs, d = _aim(_retrofocus(), CUSTOM)
    pu = compute_pupil(cs)
    px, py = np.array([0.0, 0.0, 0.0, 1.0, -1.0]), np.array([0.0, 1.0, -1.0, 0.0, 0.0])
    worst = 0.0
    for f in range(3):
        P0, D0, _ = launch(cs, 0, f, px, py, pu, aiming="paraxial")
        for k in range(5):
            q = _to_stop(P0[k], D0[k])
            worst = max(worst, math.hypot(q[0] - px[k] * pu.r_stop, q[1] - py[k] * pu.r_stop) / pu.r_stop)
    assert worst > AIM_WARN
    assert len(d) == 1 and d[0].level == "warning" and d[0].code == "PARAXIAL_AIMING" and d[0].surface == cs.stop
    assert f"({100 * worst:.1f} % of the stop radius)" in d[0].message
    # with real ray aiming the rays fill the stop: nothing to report
    assert _aim(_retrofocus("real"), CUSTOM)[1] == []


@pytest.mark.parametrize("sid,level", [("geiser-triplet", "warning"), ("double-gauss", "warning"), ("petzval", "info"), ("live-eiffel", "info"), ("achromat", None), ("hubble", None)])
def test_levels_on_the_samples(sid, level):
    """Paraxial aiming misses (measured): Geiser 8.9 %, double Gauss 6.0 %, Petzval 4.4 %, Eiffel 1.8 %, achromat
    0.4 %, Hubble 0.02 %. With real aiming the Geiser triplet's relative illumination is 0.869 against 0.773."""
    p = get_sample(sid)
    _, d = _aim(p.system.model_copy(update={"ray_aiming": "paraxial"}), p.custom_materials)
    assert [x.level for x in d] == ([level] if level else [])


def test_evaluate_reports_it():
    p = get_sample("geiser-triplet")
    ev = evaluate_system(compile_system(p.system, p.custom_materials))
    assert [x["code"] for x in ev["diagnostics"] if x["code"] == "PARAXIAL_AIMING"] == ["PARAXIAL_AIMING"]
    assert 0 < AIM_INFO < AIM_WARN < 1
