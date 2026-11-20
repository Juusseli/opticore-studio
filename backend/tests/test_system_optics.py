"""System-level validation against analytical optics."""

import math

import numpy as np
import pytest

from opticore.analysis.aberrations import chromatic_focal_shift, field_curvature_distortion, longitudinal_aberration, ray_fan
from opticore.analysis.evaluate import evaluate_system
from opticore.analysis.spot import spot_diagram
from opticore.materials import builtin_materials
from opticore.paraxial import compute_pupil, paraxial_data, seidel_coefficients
from opticore.raytrace import trace, trace_pupil
from opticore.samples import achromat, fold_mirror, singlet, spherical_mirror
from opticore.surfaces import MISS, OK, VIGNETTED
from opticore.system import SystemError_, compile_system

from .conftest import make_system

ND = 0.5875618


def lens(R1, R2, d, glass="N-BK7", back=100.0, epd=10.0, **kw):
    return make_system(
        [
            {"thickness": None},
            {"radius": R1, "thickness": d, "material": glass, "is_stop": True},
            {"radius": R2, "thickness": back},
            {},
        ],
        wavelengths=[{"value": ND}],
        aperture={"type": "epd", "value": epd},
        **kw,
    )


def test_lensmaker_thick_lens_efl():
    R1, R2, d = 80.0, -120.0, 8.0
    n = builtin_materials()["N-BK7"].index(ND)
    inv_f = (n - 1) * (1 / R1 - 1 / R2 + (n - 1) * d / (n * R1 * R2))
    pd = paraxial_data(compile_system(lens(R1, R2, d)))
    assert pd.efl == pytest.approx(1 / inv_f, rel=1e-12)
    # back focal length of a thick lens: f (1 - (n-1) d / (n R1))
    assert pd.bfl == pytest.approx((1 / inv_f) * (1 - (n - 1) * d / (n * R1)), rel=1e-12)


def test_thin_lens_limit():
    R1, R2 = 60.0, -60.0
    n = builtin_materials()["N-BK7"].index(ND)
    f_thin = 1 / ((n - 1) * (1 / R1 - 1 / R2))
    pd = paraxial_data(compile_system(lens(R1, R2, 1e-6)))
    assert pd.efl == pytest.approx(f_thin, rel=1e-7)


def test_symmetric_lens_principal_planes():
    pd = paraxial_data(compile_system(lens(50.0, -50.0, 10.0)))
    # symmetric biconvex: principal planes symmetric about the centre
    assert pd.front_principal_plane == pytest.approx(-pd.rear_principal_plane, rel=1e-12)
    assert pd.front_principal_plane > 0  # inside the lens, behind surface 1
    # front focal point lies one focal length in front of the front principal plane
    assert pd.ffl == pytest.approx(pd.front_principal_plane - pd.efl, rel=1e-12)
    # and the rear focal point one focal length behind the rear principal plane
    assert pd.bfl == pytest.approx(pd.rear_principal_plane + pd.efl, rel=1e-12)


def test_singlet_real_focus_close_to_paraxial():
    p = singlet()
    cs = compile_system(p.system)
    pd = paraxial_data(cs, 1)
    assert pd.efl == pytest.approx(100.0, abs=0.01)
    # near-axis real rays (tiny aperture) converge at the paraxial focus
    pupil = compute_pupil(cs)
    r = trace_pupil(cs, 1, 0, np.array([0.0]), np.array([1e-4]), pupil)
    Pl = r.local[0, -1]
    Dl = cs.frames[-1].to_local_dirs(r.dirs)[0]
    z_cross = Pl[2] - Pl[1] / Dl[1] * Dl[2]
    assert z_cross == pytest.approx(pd.image_surface_defocus * -1, abs=1e-6)


def test_parallel_plate_lateral_displacement():
    t, n_glass = 10.0, None
    sys = make_system(
        [{"thickness": None}, {"thickness": t, "material": "N-BK7", "is_stop": True}, {"thickness": 5.0}, {}],
        wavelengths=[{"value": ND}],
        fields=[{"y": 20.0}],
        aperture={"type": "epd", "value": 2.0},
    )
    cs = compile_system(sys)
    n = builtin_materials()["N-BK7"].index(ND)
    th = math.radians(20.0)
    expected = t * math.sin(th) * (1 - math.cos(th) / math.sqrt(n * n - math.sin(th) ** 2))
    P = np.array([[0.0, 0.0, -1.0]])
    D = np.array([[0.0, math.sin(th), math.cos(th)]])
    r = trace(cs, 0, P, D)
    out = r.points[0, 2]
    # displacement = perpendicular distance between incident line and exit ray
    inc_line_at = P[0] + (out[2] - P[0, 2]) / D[0, 2] * D[0]
    delta = out - inc_line_at
    perp = np.linalg.norm(delta - np.dot(delta, D[0]) * D[0])
    assert perp == pytest.approx(expected, rel=1e-10)
    assert np.allclose(r.dirs[0], D[0], atol=1e-14)  # exit direction parallel


def test_spherical_mirror_paraxial_focus():
    p = spherical_mirror()
    cs = compile_system(p.system)
    pd = paraxial_data(cs)
    assert pd.efl == pytest.approx(100.0, rel=1e-12)  # f = |R|/2
    assert pd.bfl == pytest.approx(-100.0, rel=1e-12)  # focus 100 mm in front (signed thickness)


@pytest.mark.parametrize("h", [1.0, 5.0, 10.0])
def test_spherical_mirror_exact_spherical_aberration(h):
    """Ray at height h on a concave sphere of radius R crosses the axis at
    R - R / (2 cos(theta)) from the vertex, sin(theta) = h / R."""
    R = 200.0
    p = spherical_mirror()
    cs = compile_system(p.system)
    P = np.array([[0.0, h, -10.0]])
    D = np.array([[0.0, 0.0, 1.0]])
    r = trace(cs, 0, P, D)
    m = r.points[0, 2]
    d = r.dirs[0]
    t = -m[1] / d[1]
    z_cross = m[2] + t * d[2]
    vertex_z = cs.frames[2].origin[2]
    th = math.asin(h / R)
    expected = R - R / (2 * math.cos(th))
    assert vertex_z - z_cross == pytest.approx(expected, abs=1e-9)


def test_paraboloid_perfect_focus_and_equal_opl():
    sys = make_system(
        [
            {"thickness": None},
            {"radius": None, "thickness": 50.0, "is_stop": True},
            {"radius": -200.0, "conic": -1.0, "thickness": -100.0, "material": "MIRROR"},
            {},
        ],
        wavelengths=[{"value": ND}],
        aperture={"type": "epd", "value": 60.0},
    )
    cs = compile_system(sys)
    pupil = compute_pupil(cs)
    px, py = np.meshgrid(np.linspace(-1, 1, 11), np.linspace(-1, 1, 11))
    m = px**2 + py**2 <= 1
    r = trace_pupil(cs, 0, 0, px[m], py[m], pupil)
    assert np.all(r.ok)
    xy = r.image_xy()
    assert np.max(np.hypot(xy[:, 0], xy[:, 1])) < 1e-10
    assert np.ptp(r.opl) < 1e-9  # aberration-free: all optical paths equal


def test_fold_mirror_matches_unfolded():
    folded = compile_system(fold_mirror().system)
    unfolded = compile_system(singlet().system.model_copy(update={"wavelengths": fold_mirror().system.wavelengths, "primary_wavelength": 0, "fields": fold_mirror().system.fields}))
    a = spot_diagram(folded)["fields"]
    b = spot_diagram(unfolded)["fields"]
    for fa, fb in zip(a, b):
        assert fa["rms_radius_um"] == pytest.approx(fb["rms_radius_um"], rel=1e-9, abs=1e-9)
    # image plane lies on +y after the fold, 56.7036 mm from the mirror
    img = folded.frames[-1]
    assert img.origin[1] == pytest.approx(56.7036, abs=1e-9)
    assert img.origin[2] == pytest.approx(45.0, abs=1e-9)


def test_chromatic_focal_shift_sign_singlet():
    cs = compile_system(singlet().system)
    res = chromatic_focal_shift(cs, 0.48, 0.66, samples=5)
    # positive (normal) dispersion: blue focuses closer to the lens
    assert res["focal_shift_um"][0] < 0 < res["focal_shift_um"][-1]


def test_achromat_corrects_axial_color():
    a = compile_system(achromat(True).system)
    s = compile_system(singlet().system)
    da = chromatic_focal_shift(a, 0.4861327, 0.6562725, 2)["focal_shift_um"]
    ds = chromatic_focal_shift(s, 0.4861327, 0.6562725, 2)["focal_shift_um"]
    assert abs(da[1] - da[0]) < 0.05 * abs(ds[1] - ds[0])


def test_seidel_SI_matches_real_transverse_aberration():
    """Third-order: transverse marginal aberration at the paraxial focus.

    OptiCore's slope convention gives u' < 0 for a converging ray above the
    axis, so delta_y = +S_I / (2 n' u') (Welford's text uses the opposite slope
    sign and writes -S_I / (2 n' u')). An undercorrected positive lens has S_I > 0."""
    sys = lens(60.0, None, 4.0, back=100.0, epd=2.0)
    cs = compile_system(sys)
    pd = paraxial_data(cs)
    sys2 = sys.model_copy(deep=True)
    sys2.surfaces[2].thickness = pd.paraxial_image_distance
    cs = compile_system(sys2)
    sd = seidel_coefficients(cs)
    pupil = compute_pupil(cs)
    r = trace_pupil(cs, 0, 0, np.array([0.0]), np.array([1.0]), pupil)
    ey = r.image_xy()[0, 1]
    assert sd["total"]["SI"] > 0
    expected = sd["total"]["SI"] / (2 * sd["image_marginal_nu"])
    assert ey == pytest.approx(expected, rel=0.01)


def test_real_ray_aiming_hits_stop_centre():
    sys = make_system(
        [
            {"thickness": None},
            {"radius": 40.0, "thickness": 5.0, "material": "N-BK7"},
            {"radius": -200.0, "thickness": 10.0},
            {"radius": None, "thickness": 60.0, "is_stop": True},
            {},
        ],
        wavelengths=[{"value": ND}],
        fields=[{"y": 0.0}, {"y": 15.0}],
        aperture={"type": "epd", "value": 12.0},
        ray_aiming="real",
    )
    cs = compile_system(sys)
    pupil = compute_pupil(cs)
    r = trace_pupil(cs, 0, 1, np.array([0.0, 0.0]), np.array([0.0, 1.0]), pupil)
    assert np.allclose(r.local[0, 3, :2], 0.0, atol=1e-8)
    assert r.local[1, 3, 1] == pytest.approx(pupil.r_stop, abs=1e-8)


def test_vignetting_by_fixed_aperture():
    sys = make_system(
        [
            {"thickness": None},
            {"radius": 50.0, "thickness": 5.0, "material": "N-BK7", "is_stop": True},
            {"radius": None, "thickness": 20.0},
            {"radius": None, "thickness": 50.0, "semi_diameter": 2.0, "semi_diameter_mode": "fixed"},
            {},
        ],
        wavelengths=[{"value": ND}],
        aperture={"type": "epd", "value": 10.0},
    )
    cs = compile_system(sys)
    r = trace_pupil(cs, 0, 0, np.array([0.0, 0.0]), np.array([0.0, 1.0]))
    assert r.status[0] == OK
    assert r.status[1] == VIGNETTED and r.fail_surface[1] == 3


def test_ray_miss_reported():
    sys = make_system(
        [{"thickness": None}, {"radius": 3.0, "thickness": 2.0, "material": "N-BK7", "is_stop": True}, {"thickness": 10.0}, {}],
        wavelengths=[{"value": ND}],
        aperture={"type": "epd", "value": 10.0},
    )
    cs = compile_system(sys)
    r = trace_pupil(cs, 0, 0, np.array([0.0, 0.0]), np.array([0.0, 1.0]))
    assert r.status[0] == OK
    assert r.status[1] == MISS


def test_spot_reproducible_and_evaluate_runs():
    cs = compile_system(achromat(True).system)
    a = spot_diagram(cs)
    b = spot_diagram(cs)
    assert a == b
    ev = evaluate_system(cs)
    assert not [d for d in ev["diagnostics"] if d["level"] == "error"]
    assert len(ev["surfaces"]) == 5


def test_achromat_baseline_values():
    """Regression baseline for the frozen optimised sample (expected outputs)."""
    cs = compile_system(achromat(True).system)
    pd = paraxial_data(cs, 1)
    assert pd.efl == pytest.approx(100.0, abs=0.01)
    assert pd.image_space_fnum == pytest.approx(5.0, abs=0.01)
    sp = spot_diagram(cs)
    rms = [f["rms_radius_um"] for f in sp["fields"]]
    assert all(r < 20.0 for r in rms), rms
    assert rms == pytest.approx([12.99, 12.98, 16.07], abs=0.05)


def test_ray_fan_zero_at_chief_and_field_curves():
    cs = compile_system(achromat(True).system)
    fan = ray_fan(cs, samples=11)
    mid = 5
    for f in fan["fields"]:
        prim = f["per_wavelength"][1]
        assert prim["tangential_ey_um"][mid] == pytest.approx(0.0, abs=1e-9)
    fc = field_curvature_distortion(cs, samples=5)
    d = fc["per_wavelength"][1]["distortion_percent"]
    assert d[0] == 0.0 and all(abs(x) < 1.0 for x in d[1:])
    la = longitudinal_aberration(cs, samples=5)
    assert len(la["per_wavelength"]) == 3


def test_distortion_zero_for_thin_lens_stop_at_lens_paraxially():
    """A thin lens with the stop in contact has no third-order distortion: the
    chief ray passes undeviated through the centre. Real distortion must be tiny."""
    sys = lens(1000.0, -1000.0, 1e-3, back=1000.0, epd=1.0, fields=[{"y": 0.0}, {"y": 1.0}])
    fc = field_curvature_distortion(compile_system(sys), samples=3)
    d = fc["per_wavelength"][0]["distortion_percent"]
    assert all(abs(v) < 1e-3 for v in d[1:])


def _biconic_lens(cy: float, cx: float, along: str):
    """A stop 10 mm in front of a biconic N-BK7 lens, fields 0 / 17.5 / 25 deg along x or y."""
    fields = [{"x": 0.0, "y": 0.0}] + [{"x": 0.0, "y": v} if along == "y" else {"x": v, "y": 0.0} for v in (17.5, 25.0)]
    return make_system(
        [
            {"thickness": None},
            {"radius": None, "thickness": 10.0, "is_stop": True},
            {"type": "biconic", "radius": 1 / cy, "radius_x": 1 / cx, "thickness": 6.0, "material": "N-BK7"},
            {"radius": -60.0, "thickness": 60.0},
            {},
        ],
        fields=fields,
        aperture={"type": "epd", "value": 4.0},
    )


def test_distortion_and_field_curvature_follow_the_field_direction():
    """A biconic lens with its field along x is the 90-degree rotation of the lens with the sections swapped and the
    field along y: distortion and foci must agree. Taken along y whatever the field, they would read the y section of
    the x-field lens (-10.7 % instead of -6.36 %), and a distortion limit could pass a lens that misses it."""
    a = field_curvature_distortion(compile_system(_biconic_lens(1 / 30, 1 / 60, "x")), samples=3)
    b = field_curvature_distortion(compile_system(_biconic_lens(1 / 60, 1 / 30, "y")), samples=3)
    assert a["direction"] == [1.0, 0.0] and b["direction"] == [0.0, 1.0]
    for wa, wb in zip(a["per_wavelength"], b["per_wavelength"]):
        assert wa["distortion_percent"] == pytest.approx(wb["distortion_percent"], rel=1e-6, abs=1e-9)
        assert wa["tangential_mm"] == pytest.approx(wb["tangential_mm"], rel=1e-9)
        assert wa["sagittal_mm"] == pytest.approx(wb["sagittal_mm"], rel=1e-9)
    assert a["per_wavelength"][0]["distortion_percent"][-1] == pytest.approx(-6.357, abs=1e-3)
    # the distortion limit sees the same value in both orientations: a 6 % limit is missed by both
    from opticore.optimize.merit import MeritFunction, Operand, OptimizationSpec

    for s in (_biconic_lens(1 / 30, 1 / 60, "x"), _biconic_lens(1 / 60, 1 / 30, "y")):
        mf = MeritFunction(s, OptimizationSpec(operands=[Operand(type="max_distortion", target=6.0)]), split=True)
        _, b = mf.evaluate(mf.x0)
        assert b[0]["value"] == pytest.approx(-6.357, abs=1e-3) and not b[0]["met"]
    # rotationally symmetric: the linear limit of the real chief ray (x) equals the paraxial reference (y)
    c = field_curvature_distortion(compile_system(_biconic_lens(1 / 30, 1 / 30, "x")), samples=3)
    d = field_curvature_distortion(compile_system(_biconic_lens(1 / 30, 1 / 30, "y")), samples=3)
    assert c["per_wavelength"][0]["distortion_percent"] == pytest.approx(d["per_wavelength"][0]["distortion_percent"], rel=1e-6, abs=1e-9)


def test_invalid_system_errors():
    with pytest.raises(ValueError):
        make_system([{"thickness": None}, {}])
    with pytest.raises(ValueError):
        make_system([{"thickness": None}, {"radius": 0.0}, {}])
    with pytest.raises(ValueError):
        make_system([{"thickness": None}, {"is_stop": True}, {"is_stop": True}, {}])
    with pytest.raises(SystemError_):
        compile_system(make_system([{"thickness": None}, {"material": "UNOBTAINIUM", "thickness": 1}, {}]))


def test_negative_edge_thickness_warning():
    sys = make_system(
        [{"thickness": None}, {"radius": 12.0, "thickness": 1.0, "material": "N-BK7", "is_stop": True}, {"radius": -12.0, "thickness": 10.0}, {}],
        wavelengths=[{"value": ND}],
        aperture={"type": "epd", "value": 18.0},
    )
    ev = evaluate_system(compile_system(sys))
    assert any(d["code"] == "NEGATIVE_EDGE_THICKNESS" for d in ev["diagnostics"])


def test_wavelength_extrapolation_warning():
    sys = lens(50.0, -50.0, 5.0, glass="PMMA")
    sys = sys.model_copy(update={"wavelengths": [type(sys.wavelengths[0])(value=0.3)]})
    cs = compile_system(sys)
    assert any(d.code == "WAVELENGTH_EXTRAPOLATED" for d in cs.diagnostics)


def test_finite_conjugate_imaging_magnification_and_na():
    """Object at distance s from a thick lens: image distance and magnification
    from the system matrix (Gaussian optics), real chief ray height ~ m*h,
    and object-space NA aperture definition."""
    R1, R2, d = 80.0, -80.0, 5.0
    n = builtin_materials()["N-BK7"].index(ND)
    s_obj = 250.0
    sys = make_system(
        [
            {"thickness": s_obj},
            {"radius": R1, "thickness": d, "material": "N-BK7", "is_stop": True},
            {"radius": R2, "thickness": 100.0},
            {},
        ],
        wavelengths=[{"value": ND}],
        field_type="object_height",
        fields=[{"y": 0.0}, {"y": 1.0}],
        aperture={"type": "object_na", "value": 0.01},
    )
    cs = compile_system(sys)
    pd = paraxial_data(cs)
    # independent ABCD (reduced) matrix: refraction P = -(n2-n1)c, translation T = t/n
    def refr(n1, n2, c):
        return np.array([[1.0, 0.0], [-(n2 - n1) * c, 1.0]])

    def tr(t, nn):
        return np.array([[1.0, t / nn], [0.0, 1.0]])

    M = refr(n, 1.0, 1 / R2) @ tr(d, n) @ refr(1.0, n, 1 / R1) @ tr(s_obj, 1.0)
    # image distance s' makes the B element vanish: (tr(s') @ M)[0,1] = 0
    s_img = -M[0, 1] / M[1, 1]
    mag = M[0, 0] + s_img * M[1, 0]
    assert pd.paraxial_image_distance == pytest.approx(s_img, rel=1e-10)
    assert pd.paraxial_magnification == pytest.approx(mag, rel=1e-10)
    assert pd.object_space_na == pytest.approx(0.01, rel=1e-9)
    # put the image at focus and check the real chief-ray height of a small field
    sys.surfaces[2].thickness = s_img
    cs = compile_system(sys)
    r = trace_pupil(cs, 0, 1, np.array([0.0]), np.array([0.0]))
    assert r.image_xy()[0, 1] == pytest.approx(mag * 1.0, rel=2e-3)  # third-order distortion only


def test_object_height_spot_is_sharp_near_axis():
    """A slow lens imaging a point near the axis at its conjugate gives a small spot."""
    sys = make_system(
        [
            {"thickness": 200.0},
            {"radius": 100.0, "thickness": 4.0, "material": "N-BK7", "is_stop": True},
            {"radius": -100.0, "thickness": 200.0},
            {},
        ],
        wavelengths=[{"value": ND}],
        field_type="object_height",
        fields=[{"y": 0.0}],
        aperture={"type": "object_na", "value": 0.005},
    )
    cs = compile_system(sys)
    pd = paraxial_data(cs)
    sys.surfaces[2].thickness = pd.paraxial_image_distance
    sp = spot_diagram(compile_system(sys))
    assert sp["fields"][0]["rms_radius_um"] < 1.0


def test_cooke_triplet_baseline():
    """Frozen optimised Cooke triplet (expected outputs)."""
    from opticore.samples import cooke_triplet

    cs = compile_system(cooke_triplet(True).system)
    pd = paraxial_data(cs, 1)
    assert pd.efl == pytest.approx(50.0, abs=0.001)
    assert pd.image_space_fnum == pytest.approx(4.5, abs=1e-3)
    rms = [f["rms_radius_um"] for f in spot_diagram(cs)["fields"]]
    assert rms == pytest.approx([7.86, 19.74, 18.28], abs=0.05)
    assert not [d for d in evaluate_system(cs)["diagnostics"] if d["level"] != "info"]
