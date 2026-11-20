"""Analyses that assumed the field lies along +y, or took the degree components of an angle field as a Euclidean
vector (fields.field_size / field_direction / field_along). Each test compares a system with its fields along y to the
same system rotated about the axis (fields along x, -y or the diagonal); the old values are quoted in the docstrings."""

import math

import numpy as np
import pytest

from opticore.analysis.aberrations import _linear_reference, _paraxial_reference, field_curvature_distortion, ray_fan
from opticore.analysis.advisor import diagnose
from opticore.analysis.imaging import _distortion_table, _along, relative_illumination, with_object_space_fields
from opticore.analysis.liveimage import chief_height
from opticore.analysis.summary import design_summary, field_profile, largest_field, relative_illumination_at
from opticore.analysis.vignetting import vignetting_factors
from opticore.analysis.wavefront import opd_fan
from opticore.designspace import metrics
from opticore.fields import field_along, field_direction, field_size, object_field
from opticore.model import Aperture, FieldPoint, OpticalSystem, Surface, Wavelength
from opticore.paraxial import compute_pupil
from opticore.raytrace import trace_pupil
from opticore.samples import get_sample
from opticore.system import compile_system


def _sample(sid):
    p = get_sample(sid)
    return p.system, list(p.custom_materials)


def _rotate(system: OpticalSystem, mode: str) -> OpticalSystem:
    """The fields (all along y) rotated about the axis: 'x' (x = old y), '-y', 'd45' (exactly: an angle field keeps its
    true angle, a height its length). Vignetting factors are swapped for 'x'; 'd45' needs a system without them."""
    d = system.model_dump()
    angle = system.field_type == "angle"
    for f in d["fields"]:
        assert f["x"] == 0.0
        y = f["y"]
        if mode == "x":
            f["x"], f["y"] = y, 0.0
            f["vdx"], f["vdy"], f["vcx"], f["vcy"] = f["vdy"], f["vdx"], f["vcy"], f["vcx"]
        elif mode == "-y":
            f["y"], f["vdy"] = -y, -f["vdy"]
        elif mode == "d45":
            assert not (f["vdx"] or f["vdy"] or f["vcx"] or f["vcy"])
            a = math.degrees(math.atan(math.tan(math.radians(y)) / math.sqrt(2.0))) if angle else y / math.sqrt(2.0)
            f["x"], f["y"] = a, a
    return OpticalSystem.model_validate(d)


def _without_vignetting(system: OpticalSystem) -> OpticalSystem:
    d = system.model_dump()
    for f in d["fields"]:
        f.update(vdx=0.0, vdy=0.0, vcx=0.0, vcy=0.0)
    return OpticalSystem.model_validate(d)


def _biconic_lens(cy: float, cx: float, along: str) -> OpticalSystem:
    """A stop 10 mm in front of a biconic N-BK7 lens, fields 0 / 17.5 / 25 deg along x or y."""
    fields = [{"x": 0.0, "y": 0.0}] + [{"x": 0.0, "y": v} if along == "y" else {"x": v, "y": 0.0} for v in (17.5, 25.0)]
    return OpticalSystem.model_validate(
        {
            "surfaces": [
                {"thickness": None},
                {"radius": None, "thickness": 10.0, "is_stop": True},
                {"type": "biconic", "radius": 1 / cy, "radius_x": 1 / cx, "thickness": 6.0, "material": "N-BK7"},
                {"radius": -60.0, "thickness": 60.0},
                {},
            ],
            "fields": fields,
            "aperture": {"type": "epd", "value": 4.0},
            "wavelengths": [{"value": 0.4861327}, {"value": 0.5875618}, {"value": 0.6562725}],
            "primary_wavelength": 1,
        }
    )


# ----------------------------------------------------------------------------- field geometry
def test_field_geometry_of_angle_fields():
    """(23.82, 23.82) deg is a 31.98 deg field (tan components), not hypot = 33.69; heights are vectors."""
    a = math.degrees(math.atan(math.tan(math.radians(31.9838)) / math.sqrt(2.0)))
    assert field_size("angle", a, a) == pytest.approx(31.9838, abs=1e-9)
    assert field_size("angle", 0.0, -20.0) == 20.0 and field_size("height", 3.0, 4.0) == 5.0
    fx, fy = field_along("angle", 20.0, *field_direction("angle", 10.0, 15.0))
    assert math.tan(math.radians(fx)) / math.tan(math.radians(fy)) == pytest.approx(math.tan(math.radians(10.0)) / math.tan(math.radians(15.0)), rel=1e-12)
    assert field_size("angle", fx, fy) == pytest.approx(20.0, rel=1e-12)
    assert field_along("angle", 7.5, 0.0, -1.0) == (0.0, -7.5) and field_direction("height", 0.0, 0.0) is None
    # the largest field by its true angle: (0, 33) deg is larger than the 31.98 deg diagonal
    s = OpticalSystem.model_validate({"surfaces": [{"thickness": None}, {"radius": 50.0, "thickness": 5.0, "material": "N-BK7", "is_stop": True}, {"thickness": 95.0}, {}], "fields": [{"x": a, "y": a}, {"y": 33.0}]})
    assert largest_field(s) == 1


# ----------------------------------------------------------------------------- 1. relative illumination direction
def test_relative_illumination_follows_the_field_direction():
    """Biconic lens A (field along x) and B = A rotated by 90 degrees (field along y): the same relative illumination.
    Traced along +y whatever the field, A gave 1.111576 at field 2 (B: 0.886904); the operand saw the same."""
    a, b = compile_system(_biconic_lens(1 / 30, 1 / 60, "x")), compile_system(_biconic_lens(1 / 60, 1 / 30, "y"))
    ra, rb = relative_illumination_at(a, 2), relative_illumination_at(b, 2)
    assert ra == pytest.approx(rb, rel=1e-9)
    assert rb == pytest.approx(0.886904, abs=1e-6)
    fa, fb = relative_illumination(a, points=5), relative_illumination(b, points=5)
    assert fa["direction"] == [1.0, 0.0] and fb["direction"] == [0.0, 1.0]
    assert fa["relative_illumination"] == pytest.approx(fb["relative_illumination"], rel=1e-9)
    assert fa["image_heights_mm"] == pytest.approx(fb["image_heights_mm"], rel=1e-9, abs=1e-12)
    # the image-simulation distortion table and the live image's chief-ray heights follow the same direction
    ta = _distortion_table(a, 1, 1e9, compute_pupil(a))
    tb = _distortion_table(b, 1, 1e9, compute_pupil(b))
    assert ta["r_real"] == pytest.approx(tb["r_real"], rel=1e-9, abs=1e-12)
    assert chief_height(a, 1, 20.0, compute_pupil(a)) == pytest.approx(chief_height(b, 1, 20.0, compute_pupil(b)), rel=1e-12)
    # the min_relative_illumination operand (merit.py calls relative_illumination_at)
    from opticore.optimize.merit import MeritFunction, Operand, OptimizationSpec

    vals = []
    for s in (_biconic_lens(1 / 30, 1 / 60, "x"), _biconic_lens(1 / 60, 1 / 30, "y")):
        mf = MeritFunction(s, OptimizationSpec(operands=[Operand(type="min_relative_illumination", target=1.0)]), split=True)
        vals.append(mf.evaluate(mf.x0)[1][0]["value"])
    assert vals[0] == pytest.approx(vals[1], rel=1e-9) and vals[1] == pytest.approx(0.886904, abs=1e-6)


# ----------------------------------------------------------------------------- 2. finite object with angle fields
def _ideal_finite(field_type: str, fy: float, d0: float = 300.0) -> OpticalSystem:
    return OpticalSystem(
        surfaces=[Surface(thickness=d0), Surface(type="ideal", focal_length=100.0, ideal_object_distance=d0, thickness=150.0, is_stop=True), Surface()],
        wavelengths=[Wavelength(value=0.55)],
        aperture=Aperture(type="object_na", value=0.05),
        field_type=field_type,
        fields=[FieldPoint(y=0.0), FieldPoint(y=fy)],
    )


def test_relative_illumination_of_angle_fields_with_a_finite_object():
    """An ideal lens f = 100 mm, object at 300 mm: the 20 deg angle field and the same object point given by its height
    h = tan(20 deg)(d0 + z_EP) = 109.19 mm have the same relative illumination 0.78056. The angle (degrees) used to be
    taken as an object height in mm, which gave 0.661028, and the unit was reported as 'mm'."""
    ca = compile_system(_ideal_finite("angle", 20.0))
    h = math.tan(math.radians(20.0)) * (300.0 + compute_pupil(ca).z_ep)
    ch = compile_system(_ideal_finite("object_height", h))
    ra = relative_illumination(ca, points=3, transmission=False)
    rh = relative_illumination(ch, points=3, transmission=False)
    assert ra["field_unit"] == "deg" and rh["field_unit"] == "mm"
    assert ra["relative_illumination"][-1] == pytest.approx(rh["relative_illumination"][-1], rel=1e-6)
    assert ra["relative_illumination"][-1] == pytest.approx(0.78056, abs=2e-5)
    assert ra["area_ratio_relative"][-1] == pytest.approx(rh["area_ratio_relative"][-1], rel=1e-6)


# ----------------------------------------------------------------------------- 3. diagonal angle fields
def test_diagonal_angle_fields_use_the_true_field_angle():
    """Cell phone lens with its 3.5 mm image-height field on the diagonal: the object field (23.82, 23.82) deg is a
    31.98 deg field. hypot of the degrees (33.69) gave the relative illumination 0.461655 instead of 0.519286 (the same
    height on y), and the image simulation's PSF node at the sensor corner (2.8, 2.1) mm got the field
    (25.59, 19.19) deg, whose chief ray lands at r = 3.32 mm instead of 3.50."""
    phone, cm = _sample("cell-phone-lens")
    c0, c45 = compile_system(phone, cm), compile_system(_rotate(phone, "d45"), cm)
    assert relative_illumination_at(c45, 2) == pytest.approx(relative_illumination_at(c0, 2), rel=1e-6)
    assert relative_illumination_at(c0, 2) == pytest.approx(0.519286, abs=1e-6)
    s0, s45 = design_summary(phone, cm), design_summary(_rotate(phone, "d45"), cm)
    assert s45["field"] == pytest.approx(31.98376, abs=1e-5) and s45["field"] == pytest.approx(s0["field"], rel=1e-9)
    assert s45["relative_illumination"] == pytest.approx(s0["relative_illumination"], rel=1e-6)
    assert s45["distortion_pct"] == pytest.approx(s0["distortion_pct"], rel=1e-6)
    # a PSF node of the simulations: the field of size v along the node's azimuth lands on the node
    cs = compile_system(with_object_space_fields(phone, cm), cm)
    pu = compute_pupil(cs)
    dist = _distortion_table(cs, cs.model.primary_wavelength, 4.0, pu)
    x, y = 2.8, 2.1
    r = math.hypot(x, y)
    field = _along(cs, dist["sign"] * float(np.interp(r, dist["r_real"], dist["v"])), (x / r, y / r))
    ch = trace_pupil(cs, cs.model.primary_wavelength, field, np.array([0.0]), np.array([0.0]), pu, clip=False, obscure=False)
    assert ch.image_xy()[0] == pytest.approx([x, y], abs=2e-4)
    # the field profile runs along the diagonal at the true angle
    fp = field_profile(_rotate(phone, "d45"), cm)
    assert fp["defined"] == pytest.approx(field_profile(phone, cm)["defined"], abs=1e-9)


def test_diagonal_object_space_angle_field_in_the_summary():
    """An angle field (atan(tan 20 / sqrt 2), same) on the Cooke triplet is a 20 deg field: the summary's field is 20,
    not hypot = 20.41 deg, and its relative illumination is that of the 20 deg field along y."""
    cooke, cm = _sample("cooke-triplet")
    c0, c45 = compile_system(cooke, cm), compile_system(_rotate(cooke, "d45"), cm)
    big = largest_field(cooke)
    assert design_summary(_rotate(cooke, "d45"), cm)["field"] == pytest.approx(abs(cooke.fields[big].y), rel=1e-12)
    assert relative_illumination_at(c45, big) == pytest.approx(relative_illumination_at(c0, big), rel=1e-6)


# ----------------------------------------------------------------------------- 4. ray and OPD fans
def test_ray_and_opd_fans_follow_the_field_direction():
    """Cooke triplet, field 1 along y and along x: the tangential fan is the fan along the field. It used to be the py
    fan whatever the field: the x field got the sagittal numbers [28.088, 0, -28.088] as 'tangential' and
    [-8.227, 0, 59.263] as 'sagittal'."""
    cooke, cm = _sample("cooke-triplet")
    for mode in ("x", "-y", "d45"):
        base = _without_vignetting(cooke) if mode == "d45" else cooke
        sy, sm = compile_system(base, cm), compile_system(_rotate(base, mode), cm)
        ry, rm = ray_fan(sy, samples=5), ray_fan(sm, samples=5)
        oy, om = opd_fan(sy, samples=5), opd_fan(sm, samples=5)
        for f in range(len(cooke.fields)):
            for wy, wm in zip(ry["fields"][f]["per_wavelength"], rm["fields"][f]["per_wavelength"]):
                assert wm["tangential_ey_um"] == pytest.approx(wy["tangential_ey_um"], rel=1e-6, abs=1e-6)
                assert wm["sagittal_ex_um"] == pytest.approx(wy["sagittal_ex_um"], rel=1e-6, abs=1e-6)
            for wy, wm in zip(oy["fields"][f]["per_wavelength"], om["fields"][f]["per_wavelength"]):
                assert wm["tangential_waves"] == pytest.approx(wy["tangential_waves"], rel=1e-6, abs=1e-7)
                assert wm["sagittal_waves"] == pytest.approx(wy["sagittal_waves"], rel=1e-6, abs=1e-7)
    rx = ray_fan(compile_system(_rotate(cooke, "x"), cm), samples=3)["fields"][1]
    assert rx["direction"] == [1.0, 0.0]
    assert rx["per_wavelength"][1]["tangential_ey_um"] == pytest.approx([-8.227, 0.0, 59.263], abs=1e-3)
    assert rx["per_wavelength"][1]["sagittal_ex_um"] == pytest.approx([28.088, 0.0, -28.088], abs=1e-3)
    # an anamorphic lens: the on-axis fans of A (fields along x) are those of its rotation B (fields along y)
    a, b = ray_fan(compile_system(_biconic_lens(1 / 30, 1 / 60, "x")), samples=5), ray_fan(compile_system(_biconic_lens(1 / 60, 1 / 30, "y")), samples=5)
    for fa, fb in zip(a["fields"], b["fields"]):
        for wa, wb in zip(fa["per_wavelength"], fb["per_wavelength"]):
            assert wa["tangential_ey_um"] == pytest.approx(wb["tangential_ey_um"], rel=1e-6, abs=1e-6)
            assert wa["sagittal_ex_um"] == pytest.approx(wb["sagittal_ex_um"], rel=1e-6, abs=1e-6)


# ----------------------------------------------------------------------------- 5. advisor lateral colour
def test_advisor_lateral_colour_follows_the_field_direction():
    """Cooke triplet: 0.857658 um of lateral colour whatever the field direction. The y heights alone gave 0 for x
    fields and 0.606455 (1/sqrt 2 of it) on the diagonal."""
    cooke, cm = _sample("cooke-triplet")
    ref = diagnose(compile_system(cooke, cm), grid=16)["colour"]["lateral_colour_um"]
    assert ref == pytest.approx(0.857658, abs=1e-6)
    for mode in ("x", "-y"):
        assert diagnose(compile_system(_rotate(cooke, mode), cm), grid=16)["colour"]["lateral_colour_um"] == pytest.approx(ref, rel=1e-8)
    d45 = _rotate(_without_vignetting(cooke), "d45")
    assert diagnose(compile_system(d45, cm), grid=16)["colour"]["lateral_colour_um"] == pytest.approx(ref, rel=1e-8)


# ----------------------------------------------------------------------------- 6. vignetting factors
def test_automatic_vignetting_factors_of_x_fields():
    """Double Gauss field 3 without the sample's factors: the factors of the x field are those of the y field with x and
    y swapped. The y extent of the x field was measured at px = 0, not through the centre of the passed region
    (VCY 0.156564 instead of 0.071155)."""
    dg, cm = _sample("double-gauss")
    base = _without_vignetting(dg)
    vy = vignetting_factors(compile_system(base, cm))["fields"]
    vx = vignetting_factors(compile_system(_rotate(base, "x"), cm))["fields"]
    for fy, fx in zip(vy, vx):
        assert fx["ok"] and fy["ok"]
        assert (fx["vdx"], fx["vcx"], fx["vdy"], fx["vcy"]) == pytest.approx((fy["vdy"], fy["vcy"], fy["vdx"], fy["vcx"]), abs=1e-6)
    assert vx[3]["vcy"] == pytest.approx(0.071155, abs=1e-6) and vx[3]["vdx"] == pytest.approx(-0.152449, abs=1e-6)


# ----------------------------------------------------------------------------- 7. design-space metrics
def test_design_space_metrics_keep_distortion_of_x_fields():
    """designspace.metrics took the distortion only when a field had a y component: x fields gave None."""
    from opticore.designspace import DesignSpaceSpec

    cooke, cm = _sample("cooke-triplet")
    spec = DesignSpaceSpec(tolerances=False)
    my, mx = metrics(cooke, cm, spec), metrics(_rotate(cooke, "x"), cm, spec)
    assert mx["distortion_pct"] is not None
    assert mx["distortion_pct"] == pytest.approx(my["distortion_pct"], rel=1e-6)


# ----------------------------------------------------------------------------- 8. distortion reference
def test_distortion_reference_of_rotated_fields_and_odd_aspheres():
    """Cell phone lens (r^3 odd-asphere terms): x fields gave 0.529361 % against 0.525830 % along y, because the linear
    limit of the real chief ray was taken with a one-sided step of 1e-4 of the field (the h|h| term of the chief-ray map
    biases it linearly in the step: 3.4815699 mm instead of the paraxial 3.4816922). A rotationally symmetric system
    uses the paraxial reference in every azimuth; the linear limit (for anamorphic systems) is Richardson-extrapolated."""
    phone, cm = _sample("cell-phone-lens")
    dy = field_curvature_distortion(compile_system(phone, cm), samples=2, wavelengths=[1])["per_wavelength"][0]
    for mode in ("x", "-y", "d45"):
        dm = field_curvature_distortion(compile_system(_rotate(phone, mode), cm), samples=2, wavelengths=[1])["per_wavelength"][0]
        assert dm["distortion_percent"][-1] == pytest.approx(dy["distortion_percent"][-1], rel=1e-7)
        assert dm["paraxial_height_mm"][-1] == pytest.approx(dy["paraxial_height_mm"][-1], rel=1e-9)
    assert dy["distortion_percent"][-1] == pytest.approx(0.525830, abs=1e-6)
    # the linear limit itself now agrees with the paraxial reference (it was 3.5e-5 off)
    cs = compile_system(_rotate(phone, "x"), cm)
    pu, img = compute_pupil(cs), cs.n_surfaces - 1
    lin = _linear_reference(cs, 1, pu, img, 3.5)((3.5, 0.0))[1]
    par = _paraxial_reference(cs, 1, pu, img)((3.5, 0.0))[1]
    assert par[0] == pytest.approx(3.4816922, abs=1e-6)
    assert lin == pytest.approx(par, rel=1e-8, abs=1e-9)


# ----------------------------------------------------------------------------- 9. summary field unit
def test_summary_field_unit_follows_the_object_kind_of_the_active_configuration():
    """The summary's field unit came from system.object_at_infinity of the base prescription: angle fields with a
    finite object were labelled 'mm', and a configuration that moves the object used the base's unit."""
    ach, cm = _sample("achromat")
    d = ach.model_dump()
    d["surfaces"][0]["thickness"] = 500.0  # angle fields with a finite object
    s = design_summary(OpticalSystem.model_validate(d), cm)
    assert s["field_unit"] == "deg" and s["field"] == pytest.approx(2.0, rel=1e-12)
    two, cm2 = _sample("achromat-two-conjugates")
    d = two.model_dump()
    d["field_type"] = "image_height"
    d["fields"] = [{"y": 0.0}, {"y": 2.0}, {"y": 3.0}]
    for active, unit in ((0, "deg"), (1, "mm")):
        d["multi_config"]["active"] = active
        sys_k = OpticalSystem.model_validate(d)
        out = design_summary(sys_k, cm2)
        cs = compile_system(sys_k, cm2)
        assert out["field_unit"] == unit
        obj = object_field(cs, 0.0, 3.0)
        assert out["field"] == pytest.approx(field_size("angle" if unit == "deg" else "height", *obj), rel=1e-12)
