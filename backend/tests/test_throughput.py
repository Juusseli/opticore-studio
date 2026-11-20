import math

import pytest

from opticore.analysis.throughput import transmission
from opticore.optimize.merit import MeritFunction, OptimizationSpec
from opticore.samples import spherical_mirror
from opticore.system import compile_system

from .conftest import make_system

ND = 0.5875618


def plate(material="N-BK7", t=10.0, custom=(), sd=None):
    s3 = {"thickness": 10.0}
    if sd is not None:
        s3 = {"thickness": 10.0, "semi_diameter": sd, "semi_diameter_mode": "fixed"}
    sys = make_system(
        [{"thickness": None}, {"thickness": t, "material": material, "is_stop": True}, s3, {}],
        wavelengths=[{"value": ND}],
        aperture={"type": "epd", "value": 2.0},
    )
    return compile_system(sys, list(custom))


def test_plate_fresnel_two_surfaces_normal_incidence():
    n = 1.5
    cs = plate("GLASS15", custom=[{"name": "GLASS15", "formula": "constant", "coefficients": [n]}])
    R = ((n - 1) / (n + 1)) ** 2
    res = transmission(cs)
    v = res["fields"][0]["per_wavelength"][0]
    assert v["geometric"] == pytest.approx(1.0, abs=1e-12)
    assert v["total"] == pytest.approx((1 - R) ** 2, rel=1e-9)
    assert [b["transmission"] for b in res["chief_ray_surfaces"]] == pytest.approx([1 - R, 1 - R], rel=1e-12)


def test_bulk_absorption_beer_lambert():
    n, alpha, t = 1.5, 0.1, 10.0
    cs = plate("ABS", t=t, custom=[{"name": "ABS", "formula": "constant", "coefficients": [n], "absorption_per_mm": alpha}])
    R = ((n - 1) / (n + 1)) ** 2
    v = transmission(cs)["fields"][0]["per_wavelength"][0]
    assert v["total"] == pytest.approx((1 - R) ** 2 * math.exp(-alpha * t), rel=1e-9)


def test_vignetting_area_fraction():
    cs = plate(sd=0.5)  # beam radius 1 mm, aperture radius 0.5 mm -> 25 % of the area
    v = transmission(cs, rings=40)["fields"][0]["per_wavelength"][0]
    assert v["geometric"] == pytest.approx(0.25, abs=0.01)


def test_ideal_mirror_is_lossless():
    v = transmission(compile_system(spherical_mirror().system))["fields"][0]["per_wavelength"][0]
    assert v["total"] == pytest.approx(1.0, abs=1e-12)


def test_throughput_operand():
    sys = make_system(
        [{"thickness": None}, {"thickness": 10.0, "material": "N-BK7", "is_stop": True}, {"thickness": 10.0}, {}],
        wavelengths=[{"value": ND}],
        aperture={"type": "epd", "value": 2.0},
    )
    sys.surfaces[1].id = "p1"
    spec = OptimizationSpec.model_validate({"variables": [], "operands": [{"type": "throughput", "target": 1.0}]})
    mf = MeritFunction(sys, spec)
    r, br = mf.evaluate(mf.x0)
    expected = transmission(compile_system(sys))["weighted_mean_total"]
    assert br[0]["value"] == pytest.approx(expected, rel=1e-12)
