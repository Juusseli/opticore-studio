"""Ideal (paraxial) lens surfaces, image-height fields and object-space telecentric systems.

Benchmarks are analytic: an ideal lens images in tangent space exactly
(t' = t - h/f), so heights follow the paraxial ABCD formulas for every field
and aperture (h' = f tan(theta), 1/s' = 1/f - 1/s, two-lens EFL
f1 f2 / (f1 + f2 - d)); a 4f relay with the stop in the common focal plane is
doubly telecentric with magnification -1.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from opticore.analysis.spot import spot_diagram
from opticore.analysis.wavefront import wavefront_map
from opticore.fields import object_field
from opticore.paraxial import compute_pupil, paraxial_data, seidel_coefficients
from opticore.raytrace import trace_pupil, hexapolar
from opticore.surfaces import OK
from opticore.system import SystemError_, compile_system

from .conftest import make_system

LAM = [{"value": 0.55}]


def ideal_singlet(f=100.0, obj=None, fields=(0.0, 10.0, 20.0), field_type="angle", img=None, **kw):
    surfaces = [
        {"thickness": obj},
        {"type": "ideal", "focal_length": f, "thickness": img if img is not None else (f if obj is None else 1.0 / (1.0 / f - 1.0 / obj)), "is_stop": True, "semi_diameter": 15.0},
        {"thickness": 0.0},
    ]
    surfaces[1].update(kw)
    return make_system(surfaces, wavelengths=LAM, fields=[{"y": v} for v in fields], field_type=field_type, aperture={"type": "epd", "value": 20.0})


def _landing(cs, field, px, py):
    r = trace_pupil(cs, 0, field, np.asarray(px, float), np.asarray(py, float), clip=False)
    assert np.all(r.status == OK)
    return r.local[:, cs.n_surfaces - 1, :2], r


def test_ideal_lens_images_infinity_perfectly_at_every_field():
    cs = compile_system(ideal_singlet())
    px, py = hexapolar(6)
    for k, theta in enumerate((0.0, 10.0, 20.0)):
        xy, _ = _landing(cs, k, px, py)
        assert np.max(np.abs(xy[:, 1] - 100.0 * math.tan(math.radians(theta)))) < 1e-10
        assert np.max(np.abs(xy[:, 0])) < 1e-10
    pd = paraxial_data(cs)
    assert pd.efl == pytest.approx(100.0, abs=1e-12)
    assert pd.bfl == pytest.approx(100.0, abs=1e-12)
    s = seidel_coefficients(cs)
    assert all(abs(v) < 1e-15 for v in s["total"].values())


def test_ideal_lens_wavefront_is_flat_for_its_design_conjugate():
    cs = compile_system(ideal_singlet())
    for f in range(3):
        w = wavefront_map(cs, f, grid=24)
        assert w["rms_waves"] < 1e-7 and w["pv_waves"] < 1e-6


def test_ideal_lens_finite_conjugate_and_opd_conjugate_setting():
    # s = 300 mm, f = 100 mm -> s' = 150 mm, m = -0.5 (object heights in mm)
    sys_inf = ideal_singlet(obj=300.0, fields=(0.0, 5.0, 10.0), field_type="object_height")
    cs = compile_system(sys_inf)
    px, py = hexapolar(5)
    for k, h in enumerate((0.0, 5.0, 10.0)):
        xy, _ = _landing(cs, k, px, py)
        assert np.max(np.abs(xy[:, 1] + 0.5 * h)) < 1e-10
    assert paraxial_data(cs).paraxial_magnification == pytest.approx(-0.5, abs=1e-12)
    # OPD designed for infinity: rays still image perfectly but the OPD shows the conjugate residual
    w_inf = wavefront_map(cs, 2, grid=20)["rms_waves"]
    assert w_inf > 1e-3
    cs2 = compile_system(ideal_singlet(obj=300.0, fields=(0.0, 5.0, 10.0), field_type="object_height", ideal_object_distance=300.0))
    for f in range(3):
        assert wavefront_map(cs2, f, grid=20)["rms_waves"] < 1e-7


def test_two_ideal_lenses_follow_the_thick_system_formulas():
    f1, f2, d = 100.0, 50.0, 30.0
    efl = f1 * f2 / (f1 + f2 - d)
    bfl = f2 * (f1 - d) / (f1 + f2 - d)
    sysm = make_system(
        [
            {"thickness": None},
            {"type": "ideal", "focal_length": f1, "thickness": d, "is_stop": True, "semi_diameter": 15.0},
            {"type": "ideal", "focal_length": f2, "thickness": bfl},
            {"thickness": 0.0},
        ],
        wavelengths=LAM,
        fields=[{"y": 0.0}, {"y": 5.0}],
        aperture={"type": "epd", "value": 20.0},
    )
    cs = compile_system(sysm)
    pd = paraxial_data(cs)
    assert pd.efl == pytest.approx(efl, abs=1e-10) and pd.bfl == pytest.approx(bfl, abs=1e-10)
    px, py = hexapolar(5)
    xy, _ = _landing(cs, 1, px, py)
    assert np.max(np.abs(xy[:, 1] - efl * math.tan(math.radians(5.0)))) < 1e-9


def test_ideal_lens_after_a_fold_mirror_focuses_along_the_reversed_axis():
    """Light travelling towards -z after a mirror: the lens still converges, focus at -f."""
    sysm = make_system(
        [
            {"thickness": None},
            {"thickness": 20.0, "is_stop": True, "semi_diameter": 15.0},
            {"material": "MIRROR", "thickness": -10.0, "semi_diameter": 20.0},
            {"type": "ideal", "focal_length": 80.0, "thickness": -80.0, "semi_diameter": 20.0},
            {"thickness": 0.0},
        ],
        wavelengths=LAM,
        fields=[{"y": 0.0}, {"y": 3.0}],
        aperture={"type": "epd", "value": 16.0},
    )
    cs = compile_system(sysm)
    assert paraxial_data(cs).efl == pytest.approx(80.0, abs=1e-10)
    px, py = hexapolar(4)
    for k in range(2):
        xy, _ = _landing(cs, k, px, py)
        assert np.ptp(xy[:, 0]) < 1e-9 and np.ptp(xy[:, 1]) < 1e-9


def test_ideal_lens_validation():
    with pytest.raises(ValueError, match="mirror"):
        make_system([{"thickness": None}, {"type": "ideal", "material": "MIRROR", "is_stop": True}, {}], wavelengths=LAM)
    sysm = make_system([{"thickness": None}, {"type": "ideal", "material": "N-BK7", "thickness": 5, "is_stop": True}, {"thickness": 10}, {}], wavelengths=LAM)
    with pytest.raises(SystemError_, match="same medium"):
        compile_system(sysm)


# ---------------------------------------------------------------- image-height fields
def singlet(field_type: str, fields):
    return make_system(
        [
            {"thickness": None},
            {"radius": 51.68, "thickness": 6.0, "material": "N-BK7", "is_stop": True, "semi_diameter": 13.0},
            {"radius": None, "thickness": 96.0},
            {"thickness": 0.0},
        ],
        wavelengths=[{"value": 0.5875618}],
        fields=[{"y": v} for v in fields],
        field_type=field_type,
        aperture={"type": "epd", "value": 20.0},
    )


def test_real_image_height_fields_land_the_chief_ray_on_target():
    cs = compile_system(singlet("image_height", (0.0, 3.0, 6.0, -4.0)))
    for k, h in enumerate((0.0, 3.0, 6.0, -4.0)):
        xy, _ = _landing(cs, k, [0.0], [0.0])
        assert xy[0, 1] == pytest.approx(h, abs=1e-8)
        assert abs(xy[0, 0]) < 1e-12
    # an x component works independently
    xy, _ = _landing(cs, (2.0, 1.5), [0.0], [0.0])
    assert xy[0] == pytest.approx([2.0, 1.5], abs=1e-8)


def test_image_height_of_an_ideal_lens_is_f_tan_theta():
    cs = compile_system(ideal_singlet(fields=(0.0, 10.0, 25.0), field_type="image_height"))
    for h in (10.0, 25.0):
        assert object_field(cs, 0.0, h)[1] == pytest.approx(math.degrees(math.atan(h / 100.0)), abs=1e-9)
    cs_p = compile_system(ideal_singlet(fields=(0.0, 10.0), field_type="paraxial_image_height"))
    assert object_field(cs_p, 0.0, 10.0)[1] == pytest.approx(math.degrees(math.atan(0.1)), abs=1e-12)


def test_paraxial_image_height_fields_match_the_paraxial_chief_ray():
    cs = compile_system(singlet("paraxial_image_height", (0.0, 5.0)))
    pd = paraxial_data(cs)
    assert pd.paraxial_image_height == pytest.approx(5.0, abs=1e-10)


def test_unreachable_image_height_is_reported():
    """A strongly curved exit surface of a high-index lens: larger chief rays are totally reflected,
    so image heights beyond ~4 mm cannot be reached; smaller ones are found."""
    sysm = make_system(
        [
            {"thickness": None},
            {"radius": None, "thickness": 3.0, "material": "N-SF57", "is_stop": True, "semi_diameter": 2.0},
            {"radius": -4.0, "thickness": 8.0, "semi_diameter": 3.0},
            {"thickness": 0.0},
        ],
        wavelengths=[{"value": 0.5875618}],
        fields=[{"y": 0.0}, {"y": 3.0}, {"y": 50.0}],
        field_type="image_height",
        aperture={"type": "epd", "value": 2.0},
    )
    cs = compile_system(sysm)
    xy, _ = _landing(cs, 1, [0.0], [0.0])
    assert xy[0, 1] == pytest.approx(3.0, abs=1e-8)
    with pytest.raises(SystemError_, match="cannot be reached"):
        object_field(cs, 0.0, 50.0)


def test_spot_diagram_runs_with_image_height_fields():
    cs = compile_system(singlet("image_height", (0.0, 4.0)))
    sd = spot_diagram(cs, density=4)
    assert sd["fields"][1]["chief_xy"][1] == pytest.approx(4.0, abs=1e-7)


# ---------------------------------------------------------------- object-space telecentric
def relay(**kw):
    """4f relay of ideal lenses with the stop in the common focal plane: doubly telecentric, m = -1."""
    d = dict(
        wavelengths=LAM,
        fields=[{"y": 0.0}, {"y": 5.0}],
        field_type="object_height",
        aperture={"type": "object_na", "value": 0.05},
        object_space_telecentric=True,
    )
    d.update(kw)
    return make_system(
        [
            {"thickness": 100.0},
            {"type": "ideal", "focal_length": 100.0, "thickness": 100.0, "semi_diameter": 20.0},
            {"thickness": 100.0, "is_stop": True, "semi_diameter": 10.0},
            {"type": "ideal", "focal_length": 100.0, "thickness": 100.0, "semi_diameter": 20.0},
            {"thickness": 0.0},
        ],
        **d,
    )


def test_telecentric_chief_rays_leave_parallel_and_cross_the_stop_centre():
    cs = compile_system(relay())
    pupil = compute_pupil(cs)
    assert pupil.telecentric and math.isinf(pupil.z_ep)
    xy, r = _landing(cs, 1, [0.0], [0.0])
    assert np.allclose(r.start_dirs[0], [0.0, 0.0, 1.0])
    assert abs(r.local[0, 2, 1]) < 1e-12  # stop centre
    assert xy[0, 1] == pytest.approx(-5.0, abs=1e-10)
    px, py = hexapolar(5)
    xy, r = _landing(cs, 1, px, py)
    assert np.ptp(xy[:, 1]) < 1e-10
    # marginal rays fill NA 0.05: direction cosine of the edge ray
    edge = r.start_dirs[np.argmax(py)]
    assert math.hypot(edge[0], edge[1]) == pytest.approx(0.05, abs=1e-12)
    pd = paraxial_data(cs)
    assert pd.object_space_na == pytest.approx(0.05, abs=1e-12)
    assert pd.paraxial_magnification == pytest.approx(-1.0, abs=1e-12)
    assert pd.entrance_pupil_position == math.inf
    assert pd.as_dict()["entrance_pupil_position"] is None
    assert pd.stop_semi_diameter == pytest.approx(100.0 * math.tan(math.asin(0.05)), rel=1e-12)


def test_telecentric_validation_and_unflagged_system_error():
    with pytest.raises(ValueError, match="object-space NA"):
        relay(aperture={"type": "epd", "value": 10.0})
    with pytest.raises(ValueError, match="object-height or image-height"):
        relay(field_type="angle")
    # without the flag the entrance pupil is at infinity: a clear error instead of wrong numbers
    cs = compile_system(relay(object_space_telecentric=False))
    with pytest.raises(SystemError_, match="telecentric"):
        compute_pupil(cs)


def test_telecentric_image_height_fields():
    cs = compile_system(relay(field_type="image_height", fields=[{"y": 0.0}, {"y": -3.0}]))
    xy, _ = _landing(cs, 1, [0.0], [0.0])
    assert xy[0, 1] == pytest.approx(-3.0, abs=1e-9)
    assert object_field(cs, 0.0, -3.0)[1] == pytest.approx(3.0, abs=1e-9)


# ---------------------------------------------------------------- integration
def test_ideal_power_variable_reaches_a_target_focal_length():
    from opticore.optimize.engine import optimize
    from opticore.optimize.merit import Operand, OptimizationSpec, Variable

    sysm = ideal_singlet(f=80.0, img=100.0, fields=(0.0,))
    spec = OptimizationSpec(variables=[Variable(surface_id=sysm.surfaces[1].id, parameter="ideal_power")], operands=[Operand(type="efl", target=125.0)], max_evaluations=200)
    res = optimize(sysm, spec)
    out = res["system"]["surfaces"][1]
    assert out["focal_length"] == pytest.approx(125.0, rel=1e-6)
    with pytest.raises(ValueError, match="ideal lens has no curvature"):
        optimize(sysm, OptimizationSpec(variables=[Variable(surface_id=sysm.surfaces[1].id, parameter="curvature")], operands=[Operand(type="efl", target=125.0)]))


def test_ideal_lens_is_refused_by_the_non_sequential_trace():
    from opticore.nonseq import build_scene

    cs = compile_system(ideal_singlet())
    with pytest.raises(SystemError_, match="non-sequentially"):
        build_scene(cs, [])


def test_evaluate_reports_ideal_surfaces_and_telecentric_stop_position():
    from opticore.analysis.evaluate import evaluate_system

    ev = evaluate_system(compile_system(ideal_singlet()))
    assert ev["surfaces"][1]["is_ideal"] and ev["surfaces"][1]["focal_length"] == 100.0
    good = evaluate_system(compile_system(relay()))
    assert any(d["code"] == "TELECENTRIC" for d in good["diagnostics"])
    assert good["pupil"]["entrance_pupil_z"] == math.inf  # serialised as null by the API
    # move the stop away from the common focal plane: warned
    bad = relay()
    bad.surfaces[1].thickness = 60.0
    bad.surfaces[2].thickness = 140.0
    ev = evaluate_system(compile_system(bad))
    assert any(d["code"] == "TELECENTRIC_STOP" for d in ev["diagnostics"])


def test_zmx_paraxial_surface_becomes_an_ideal_lens():
    from opticore.io.zmx import parse_zmx

    zmx = "VERS 1\nMODE SEQ\nUNIT MM X W X CM MR CPMM\nENPD 10\nWAVM 1 0.55 1\nSURF 0\n  DISZ INFINITY\nSURF 1\n  STOP\n  TYPE PARAXIAL\n  PARM 1 50\n  PARM 2 1\n  DISZ 50\nSURF 2\n"
    proj, diags = parse_zmx(zmx)
    s1 = proj.system.surfaces[1]
    assert s1.type == "ideal" and s1.focal_length == 50.0
    assert any("OPD mode 1" in d.message for d in diags)
    assert paraxial_data(compile_system(proj.system)).efl == pytest.approx(50.0, abs=1e-12)


def test_zmx_image_height_fields_are_imported():
    from opticore.io.zmx import parse_zmx

    zmx = (
        "VERS 1\nMODE SEQ\nUNIT MM X W X CM MR CPMM\nENPD 20\nFTYP 3 0 2 1 0 0 0\nXFLN 0 0\nYFLN 0 4\nWAVM 1 0.5875618 1\n"
        "SURF 0\n  DISZ INFINITY\nSURF 1\n  STOP\n  CURV 0.01934984520123839\n  DISZ 6\n  GLAS N-BK7 0 0 1.5168 64.17\n  DIAM 13\nSURF 2\n  DISZ 96\nSURF 3\n"
    )
    proj, diags = parse_zmx(zmx)
    assert proj.system.field_type == "image_height"
    assert [f.y for f in proj.system.fields] == [0.0, 4.0]
    cs = compile_system(proj.system)
    xy, _ = _landing(cs, 1, [0.0], [0.0])
    assert xy[0, 1] == pytest.approx(4.0, abs=1e-8)
