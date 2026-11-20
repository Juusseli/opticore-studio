"""Regression tests for issues found in an independent code review: conic and sphere root selection, angle fields
with a finite object, virtual objects, the optimiser drivers, ZMX wavelength slots, glass after a mirror and a stop
on a coordinate break."""

import numpy as np
import pytest

from opticore.analysis.evaluate import evaluate_system
from opticore.analysis.spot import spot_diagram
from opticore.io.zmx import parse_zmx
from opticore.optimize import OptimizationSpec, optimize
from opticore.paraxial import chief_ray, compute_pupil, paraxial_data
from opticore.raytrace import trace_pupil
from opticore.samples import singlet
from opticore.system import compile_system

from .conftest import make_system

ND = 0.5875618


def focus(sys):
    pd = paraxial_data(compile_system(sys))
    sys.surfaces[-2].thickness = pd.paraxial_image_distance
    return compile_system(sys)


# conic root selection when the ray starts beyond the centre of curvature
def test_concave_mirror_with_object_beyond_centre_of_curvature():
    sys = make_system(
        [{"thickness": 300.0}, {"radius": -200.0, "thickness": -150.0, "material": "MIRROR", "is_stop": True}, {}],
        wavelengths=[{"value": ND}],
        field_type="object_height",
        fields=[{"y": 0.0}],
        aperture={"type": "object_na", "value": 0.01},
    )
    cs = focus(sys)
    r = trace_pupil(cs, 0, 0, np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 0.0]))
    assert np.all(r.ok)
    assert paraxial_data(cs).paraxial_image_distance == pytest.approx(-150.0, rel=1e-9)


def test_cassegrain_with_hyperbolic_secondary_traces():
    # classical Cassegrain: paraboloid primary, hyperboloid secondary
    sys = make_system(
        [
            {"thickness": None},
            {"radius": -1000.0, "conic": -1.0, "thickness": -400.0, "material": "MIRROR", "is_stop": True},
            {"radius": -266.667, "conic": -2.778, "thickness": 500.0, "material": "MIRROR"},
            {},
        ],
        wavelengths=[{"value": ND}],
        aperture={"type": "epd", "value": 100.0},
    )
    cs = focus(sys)
    sp = spot_diagram(cs)
    f0 = sp["fields"][0]
    assert sum(w["n_ok"] for w in f0["per_wavelength"]) == sum(w["n_rays"] for w in f0["per_wavelength"])


def test_rear_stop_beyond_centre_of_curvature():
    sys = make_system(
        [
            {"thickness": None},
            {"radius": 20.0, "thickness": 3.0, "material": "N-BK7"},
            {"radius": None, "thickness": 15.0},
            {"radius": None, "thickness": 20.0, "is_stop": True},
            {},
        ],
        wavelengths=[{"value": ND}],
        aperture={"type": "epd", "value": 4.0},
    )
    cs = compile_system(sys)
    assert compute_pupil(cs).z_ep > 20.0  # launch plane beyond the centre of curvature
    r = trace_pupil(cs, 0, 0, np.array([0.0, 0.0]), np.array([0.0, 1.0]))
    assert np.all(r.ok)


def test_both_roots_pick_vertex_sheet_for_ray_from_inside_sphere():
    from opticore.surfaces import OK, Shape

    sh = Shape(curvature=1 / 10.0)
    # ray starting inside the sphere near its centre, travelling backwards
    s, st = sh.intersect(np.array([[0.0, 1.0, 12.0]]), np.array([[0.0, 0.0, -1.0]]))
    assert st[0] == OK
    q = np.array([0.0, 1.0, 12.0]) + s[0] * np.array([0.0, 0.0, -1.0])
    assert q[2] == pytest.approx(10.0 - np.sqrt(100.0 - 1.0), abs=1e-12)


# angle fields with a finite object
def test_angle_field_with_finite_object_matches_paraxial():
    sys = make_system(
        [{"thickness": 200.0}, {"radius": 51.68, "thickness": 5.0, "material": "N-BK7", "is_stop": True}, {"radius": None, "thickness": 150.0}, {}],
        wavelengths=[{"value": ND}],
        field_type="angle",
        fields=[{"y": 0.0}, {"y": 2.0}],
        aperture={"type": "epd", "value": 2.0},
    )
    cs = focus(sys)
    r = trace_pupil(cs, 0, 1, np.array([0.0]), np.array([0.0]))
    c = chief_ray(cs, 0, compute_pupil(cs), 2.0)
    assert r.image_xy()[0, 1] == pytest.approx(c.y[-1], rel=1e-3)


# virtual objects
def test_virtual_object_traces_and_matches_magnification():
    sys = make_system(
        [{"thickness": -200.0}, {"radius": 51.68, "thickness": 5.0, "material": "N-BK7", "is_stop": True}, {"radius": None, "thickness": 50.0}, {}],
        wavelengths=[{"value": ND}],
        field_type="object_height",
        fields=[{"y": 0.0}, {"y": 1.0}],
        aperture={"type": "epd", "value": 2.0},
    )
    cs = focus(sys)
    m = paraxial_data(cs).paraxial_magnification
    r = trace_pupil(cs, 0, 1, np.array([0.0]), np.array([0.0]))
    assert r.ok[0]
    assert r.image_xy()[0, 1] == pytest.approx(m * 1.0, rel=1e-3)
    sp = spot_diagram(cs)
    assert sp["fields"][0]["rms_radius_um"] < 5.0


# optimiser drivers
def test_out_of_bounds_start_is_reported_not_hidden():
    p = singlet()
    spec = OptimizationSpec.model_validate(
        {"variables": [{"surface_id": "s2", "parameter": "thickness", "min": 50.0, "max": 60.0}], "operands": [{"type": "rms_spot", "field": 0, "wavelength": 1}], "max_evaluations": 200}
    )
    r = optimize(p.system, spec)
    assert r["variables"][0]["initial"] == pytest.approx(96.7036)  # true start, not the clamped value
    assert r["notes"] and "outside their bounds" in r["notes"][0]
    assert any("worse than the original" in n for n in r["notes"])
    assert r["final_merit"] > r["initial_merit"]  # honestly reported as worse


def test_global_reaches_polish_with_normal_budget():
    p = singlet()
    spec = OptimizationSpec.model_validate(
        {
            "variables": [{"surface_id": "s2", "parameter": "thickness", "min": 90.0, "max": 100.0}],
            "operands": [{"type": "rms_spot", "field": 0, "wavelength": 1}],
            "algorithm": "global",
            "max_evaluations": 300,
        }
    )
    r = optimize(p.system, spec)
    assert "polish" in r["message"]
    assert r["evaluations"] <= 300 + 5


def test_multistart_runs_all_starts_within_budget():
    p = singlet()
    spec = OptimizationSpec.model_validate(
        {
            "variables": [{"surface_id": "s2", "parameter": "thickness", "min": 90.0, "max": 100.0}],
            "operands": [{"type": "rms_spot", "field": 0, "wavelength": 1}],
            "algorithm": "multistart",
            "multistart_runs": 6,
            "max_evaluations": 120,
        }
    )
    r = optimize(p.system, spec)
    assert r["message"].startswith("6 of 6")


# ZMX wavelength slots
def test_zmx_uses_active_wavelength_count():
    lines = ["VERS 1", "MODE SUDO", "ENPD 10", "FTYP 0 0 1 3 0 0 0", "PWAV 2", "XFLN 0", "YFLN 0"]
    lines += [f"WAVM {i} {w} 1" for i, w in enumerate([0.486, 0.588, 0.656] + [0.55] * 21, start=1)]
    lines += ["SURF 0", "  DISZ INFINITY", "SURF 1", "  STOP", "  CURV 0.02", "  DISZ 5", "  GLAS N-BK7", "SURF 2", "  DISZ 90", "SURF 3"]
    proj, _ = parse_zmx("\n".join(lines))
    assert [w.value for w in proj.system.wavelengths] == [0.486, 0.588, 0.656]


# glass after an odd number of mirrors
def test_glass_after_mirror_negative_thickness_is_valid():
    sys = make_system(
        [
            {"thickness": None},
            {"radius": None, "thickness": 50.0, "is_stop": True},
            {"radius": -400.0, "thickness": -50.0, "material": "MIRROR"},
            {"radius": 100.0, "thickness": -5.0, "material": "N-BK7"},
            {"radius": None, "thickness": -100.0},
            {},
        ],
        wavelengths=[{"value": ND}],
        aperture={"type": "epd", "value": 10.0},
    )
    ev = evaluate_system(compile_system(sys))
    codes = {d["code"] for d in ev["diagnostics"]}
    assert "NONPOSITIVE_GLASS_THICKNESS" not in codes
    et = ev["edge_thickness"][3]
    assert et is not None and et > 0


# stop on a coordinate break
def test_stop_on_coordinate_break_rejected():
    with pytest.raises(ValueError):
        make_system([{"thickness": None}, {"type": "coordinate_break", "is_stop": True, "thickness": 1.0}, {"radius": 50.0, "thickness": 5.0, "material": "N-BK7"}, {}])
