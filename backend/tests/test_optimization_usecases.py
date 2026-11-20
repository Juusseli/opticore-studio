"""Optimisation in everyday use: the cases an optical engineer runs first, with analytic answers, and the
failures found when optimising the cell-phone lens (ADR-039).

Benchmarks
* a spot of a given RMS radius behind an ideal lens: defocus dz = sqrt(2) r f / R (uniform pupil of radius R:
  RMS = R dz / (sqrt 2 f), exact for the ideal lens's straight converging rays);
* best-form singlet: minimum spherical aberration at shape factor X = 2 (n^2 - 1) / (n + 2) (thin lens, object
  at infinity, third order; checked at F/10 where third order dominates);
* a Gaussian beam focused by one and by two thick lenses onto a detector: the second-moment diameter D4sigma of
  the ray ensemble equals 2 w(z) of q-parameter propagation through the lenses' paraxial ABCD matrices
  (w0' = M^2 lambda f / (pi w0), z_R' = pi w0'^2 / lambda), so a target diameter puts the detector where the
  Gaussian beam has that size;
* the polychromatic RMS wavefront: on axis it equals the weighted per-wavelength RMS (concentric reference
  spheres); off axis lateral colour appears as a tilt n' delta sin(U') of the other wavelengths.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from opticore.analysis import summary
from opticore.analysis.summary import compare_designs, design_summary, sampling_gap
from opticore.analysis.wavefront import opl_to_reference, reference_geometry, wavefront_samples
from opticore.fields import _chief_landing, object_field
from opticore.materials import MaterialLibrary
from opticore.model import OpticalSystem
from opticore.nsdirect import trace_direct
from opticore.nssources import Detector, LightSource
from opticore.optimize import merit as M
from opticore.optimize.engine import optimize
from opticore.optimize.merit import MeritFunction, Operand, OptimizationSpec, Variable
from opticore.paraxial import compute_pupil
from opticore.raytrace import gauss_pupil, trace_pupil
from opticore.samples import cell_phone_lens, geiser_triplet, singlet
from opticore.system import SystemError_, compile_system

from .conftest import make_system

LAM_D = 0.5875618


def _spec(variables, operands, **kw) -> OptimizationSpec:
    return OptimizationSpec(variables=[Variable(**v) for v in variables], operands=[Operand(**o) for o in operands], **kw)


# ----------------------------------------------------------------------------- robustness
def test_a_failed_operand_keeps_its_residual_count(monkeypatch):
    """A failing RMS operand keeps one residual per ray: a single residual breaks SciPy's finite-difference Jacobian
    ('shapes (12,) (731,)' in a cell-phone lens optimisation)."""
    p = singlet()
    spec = _spec([{"surface_id": "s2", "parameter": "thickness", "min": 80, "max": 120}], [{"type": "rms_spot"}, {"type": "rms_wavefront"}, {"type": "efl", "target": 100}])
    mf = MeritFunction(p.system, spec)
    r0, _ = mf.evaluate(mf.x0)
    sizes = mf.operand_sizes(p.system)
    assert len(r0) == sum(sizes)

    def boom(*a, **k):
        raise SystemError_("Image height (0, 3.5) mm cannot be reached by a real chief ray")

    monkeypatch.setattr(MeritFunction, "_rms_spot_residuals", boom)
    monkeypatch.setattr(MeritFunction, "_rms_wavefront_residuals", boom)
    r1, b = mf.evaluate(mf.x0)
    assert len(r1) == len(r0)
    # the failure penalty: each failed operand contributes (scale * penalty)^2 in total
    k = sizes[0]
    assert float(r1[:k] @ r1[:k]) == pytest.approx((M.FAILED_SYSTEM_PENALTY * math.sqrt(1 / 3)) ** 2, rel=1e-12)
    assert b[0]["error"] and b[1]["error"] and "error" not in b[2]


def test_an_error_inside_the_search_returns_the_best_design_so_far(monkeypatch):
    p = singlet()
    spec = _spec([{"surface_id": "s2", "parameter": "thickness", "min": 80, "max": 120}], [{"type": "rms_spot", "field": 0}], max_evaluations=200)
    d = p.system.model_dump()
    d["surfaces"][2]["thickness"] = 99.0
    start = OpticalSystem.model_validate(d)
    orig = MeritFunction.evaluate
    calls = {"n": 0}

    def flaky_once(self, x):
        calls["n"] += 1
        if calls["n"] == 5:  # after the first trial step of the search
            raise RuntimeError("numerical trouble")
        return orig(self, x)

    monkeypatch.setattr(MeritFunction, "evaluate", flaky_once)
    r = optimize(start, spec)
    assert r["status"] == "error" and "RuntimeError" in r["message"]
    assert r["final_merit"] < r["initial_merit"]


def test_image_height_field_on_the_first_branch_where_newton_from_the_paraxial_start_failed():
    """A trial design of the cell-phone optimisation: the real chief-ray height rises to 3.93 mm at ~27 deg and
    folds back. Newton from the paraxial start lands beyond the fold and fails; the 3.5 mm field is at ~22.5 deg."""
    p = cell_phone_lens("ray-optics")  # ray-optics' transcription of the cell-phone lens
    d = p.system.model_dump()
    vals = {"stop": (None, 0.000157), "c1": (1.99412, 1.19), "c2": (27.33716, 1.221412), "c3": (-1.915951, 0.75), "c4": (-8.406973, 0.221212), "c5": (4.973780, 0.89), "c6": (7.303828, 0.747197), "c7": (1.404768, 0.85), "c8": (1.758548, 0.770295), "ir2": (None, 0.799978)}
    for s in d["surfaces"]:
        if s["id"] in vals:
            r, t = vals[s["id"]]
            if r is not None:
                s["radius"] = r
            s["thickness"] = t
    cs = compile_system(OpticalSystem.model_validate(d), p.custom_materials)
    heights = [(_chief_landing(cs, "angle", 0.0, math.tan(math.radians(a))) or (0, float("nan")))[1] for a in (22.0, 27.0, 29.5)]
    assert heights[1] > 3.9 and heights[0] < 3.5 and heights[2] < heights[1]  # the fold
    ang = object_field(cs, 0.0, 3.5)[1]
    assert 22.0 < ang < 23.0
    y = _chief_landing(cs, "angle", 0.0, math.tan(math.radians(ang)))[1]
    assert y == pytest.approx(3.5, abs=1e-8)
    # the warm start of the optimiser reproduces it
    warm: dict = {}
    cs2 = compile_system(OpticalSystem.model_validate(d), p.custom_materials)
    assert object_field(cs2, 0.0, 3.5, warm)[1] == pytest.approx(ang, abs=1e-9)
    assert ("image_field", 0.0, 3.5) in warm


def test_global_search_takes_curvature_bounds_from_the_clear_apertures():
    p = singlet()
    spec = _spec(
        [{"surface_id": "s1", "parameter": "curvature"}, {"surface_id": "s2", "parameter": "thickness", "min": 80, "max": 120}],
        [{"type": "rms_spot", "field": 0}, {"type": "efl", "target": 100}],
        algorithm="global",
        max_evaluations=150,
    )
    r = optimize(p.system, spec)
    assert r["status"] in ("converged", "max_evaluations")
    assert any("Search bounds of the curvatures" in n for n in r["notes"])
    with pytest.raises(ValueError, match="S1 conic"):
        optimize(p.system, spec.model_copy(update={"variables": [*spec.variables, Variable(surface_id="s1", parameter="conic", min=None, max=None)]}))


# ----------------------------------------------------------------------------- targets and operands
def _ideal(f=100.0, epd=5.0, t=None):
    return make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "L", "type": "ideal", "focal_length": f, "thickness": f if t is None else t, "is_stop": True},
            {"id": "img"},
        ],
        wavelengths=[{"value": LAM_D}],
        fields=[{"y": 0.0}],
        aperture={"type": "epd", "value": epd},
    )


@pytest.mark.parametrize("start", [101.0, 99.0])
def test_a_spot_of_a_given_rms_radius_behind_an_ideal_lens(start):
    """rms_spot with a target > 0 is met, not minimised. Behind an ideal lens the
    spot of a uniform pupil of radius R at defocus dz has RMS radius R dz / (sqrt 2 f)."""
    f, R, r = 100.0, 2.5, 0.05
    spec = _spec([{"surface_id": "L", "parameter": "thickness", "min": 80, "max": 120}], [{"type": "rms_spot", "target": r, "rings": 6}])
    res = optimize(_ideal(f, 2 * R, start), spec)
    dz = math.sqrt(2) * r * f / R
    t = OpticalSystem.model_validate(res["system"]).surfaces[1].thickness
    assert t == pytest.approx(f + math.copysign(dz, start - f), abs=1e-5)
    assert res["operands_after"][0]["value"] == pytest.approx(r * 1e3, rel=1e-6)


def test_best_form_singlet_from_curvatures_and_focus():
    """Minimum spherical aberration of a singlet for an object at infinity: X = (c1 + c2) / (c1 - c2) =
    2 (n^2 - 1) / (n + 2) (third order, thin lens). F/10 and a 1.5 mm lens on f = 100 mm."""
    n = MaterialLibrary().index("N-BK7", LAM_D)
    x_best = 2 * (n * n - 1) / (n + 2)
    sysm = make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "a", "radius": 51.7, "thickness": 1.5, "material": "N-BK7", "is_stop": True},
            {"id": "b", "radius": None, "thickness": 99.0},
            {"id": "img"},
        ],
        wavelengths=[{"value": LAM_D}],
        fields=[{"y": 0.0}],
        aperture={"type": "epd", "value": 10.0},
    )
    spec = _spec(
        [{"surface_id": "a", "parameter": "curvature"}, {"surface_id": "b", "parameter": "curvature"}, {"surface_id": "b", "parameter": "thickness", "min": 80, "max": 120}],
        [{"type": "rms_spot", "rings": 6}, {"type": "efl", "target": 100.0}],
        max_evaluations=600,
    )
    res = optimize(sysm, spec)
    s = OpticalSystem.model_validate(res["system"]).surfaces
    c1, c2 = s[1].curvature, s[2].curvature
    assert (c1 + c2) / (c1 - c2) == pytest.approx(x_best, abs=0.03)


def test_max_distortion_and_all_field_mtf_operands():
    p = geiser_triplet()
    cm = p.custom_materials
    cs = compile_system(p.system, cm)
    from opticore.analysis.aberrations import field_curvature_distortion
    from opticore.analysis.diffraction import mtf

    dist = field_curvature_distortion(cs, samples=2, wavelengths=[1])["per_wavelength"][0]["distortion_percent"][-1]
    spec = _spec(
        [{"surface_id": "g2", "parameter": "thickness", "min": 1, "max": 10}],
        [
            {"type": "max_distortion", "target": abs(dist) + 0.1},
            {"type": "max_distortion", "target": abs(dist) - 0.2},
            {"type": "mtf", "frequency": 40.0, "target": 1.0},
        ],
    )
    mf = MeritFunction(p.system, spec, cm)
    _, b = mf.evaluate(mf.x0)
    assert b[0]["value"] == pytest.approx(dist, rel=1e-12) and b[0]["contribution"] == 0.0
    assert b[1]["contribution"] == pytest.approx(0.2**2 / 3, rel=1e-9)
    m = mtf(cs, max_frequency=40.0, samples=2, grid=32, pad=4)
    per = [0.5 * (f["tangential"][-1] + f["sagittal"][-1]) for f in m["fields"]]
    w = [f.weight for f in p.system.fields]
    assert b[2]["value"] == pytest.approx(float(np.average(per, weights=w)), rel=1e-12)


def test_max_distortion_holds_while_the_triplet_is_sharpened():
    p = geiser_triplet()
    s = p.system
    cm = p.custom_materials
    base = design_summary(s, cm)
    lim = abs(base["distortion_pct"])
    ids = ["g1", "g2", "g3", "g4", "g5", "g6"]
    variables = [{"surface_id": i, "parameter": "curvature"} for i in ids] + [{"surface_id": "g6", "parameter": "thickness", "min": 30, "max": 50}]
    spec = _spec(variables, [{"type": "rms_spot"}, {"type": "efl", "target": 50.0}, {"type": "max_distortion", "target": lim}], max_evaluations=400)
    res = optimize(s, spec, cm)
    after = design_summary(OpticalSystem.model_validate(res["system"]), cm)
    assert sum(after["rms_spot_um"]) < sum(base["rms_spot_um"])
    assert abs(after["distortion_pct"]) <= lim + 0.02


def test_unchangeable_targets_and_image_quality_that_got_worse_are_reported():
    """Two traps of the cell-phone run: a 1 mm edge target on a 0.4 mm filter plate (constant: 94 % of the merit
    function) and a constraint the start misses, which the optimiser serves at the cost of the image."""
    sysm = make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "a", "radius": 51.7, "thickness": 4.0, "material": "N-BK7", "is_stop": True},
            {"id": "b", "radius": None, "thickness": 5.0},
            {"id": "w1", "radius": None, "thickness": 0.4, "material": "N-BK7"},
            {"id": "w2", "radius": None, "thickness": 90.0},
            {"id": "img"},
        ],
        wavelengths=[{"value": LAM_D}],
        fields=[{"y": 0.0}],
        aperture={"type": "epd", "value": 10.0},
    )
    spec = _spec(
        [{"surface_id": "a", "parameter": "curvature"}, {"surface_id": "b", "parameter": "curvature"}, {"surface_id": "w2", "parameter": "thickness", "min": 50, "max": 200}],
        [{"type": "rms_spot"}, {"type": "min_edge_thickness", "target": 1.0, "surface_id": "w1"}, {"type": "min_edge_thickness", "target": 6.0, "surface_id": "a"}],
        max_evaluations=300,
    )
    mf = MeritFunction(sysm, spec)
    assert mf.fixed == {1}
    _, b = mf.evaluate(mf.x0)
    assert b[1].get("fixed") and not b[2].get("fixed")
    # weighted merit function: the constant violation's share of the merit function
    res = optimize(sysm, spec.model_copy(update={"constraints": "penalty"}))
    fixed = res["fixed_operands"]
    assert [f["index"] for f in fixed] == [1] and 0 < fixed[0]["share"] <= 1
    # an edge thicker than the centre makes the positive lens negative: the spot gets far worse
    assert [o["type"] for o in res["objective_worse"]] == ["rms_spot"]
    # exact constraints: the fixed one is reported unmet (the run is infeasible), the other one is met exactly
    res = optimize(sysm, spec.model_copy(update={"max_evaluations": 800}))
    w1, a = res["constraints"]
    assert res["status"] == "infeasible" and w1["fixed"] and not w1["met"]
    assert a["met"] and a["after"] == pytest.approx(6.0, abs=1e-3)
    assert [o["type"] for o in res["objective_worse"]] == ["rms_spot"]


def test_variables_that_change_nothing_are_reported():
    """The focal length does not depend on the image distance: that variable is inert (sensitivity exactly 0), as
    an image distance is for a detector placed in global coordinates."""
    p = singlet()
    spec = _spec([{"surface_id": "s1", "parameter": "curvature"}, {"surface_id": "s2", "parameter": "thickness", "min": 80, "max": 120}], [{"type": "efl", "target": 90.0}])
    res = optimize(p.system, spec)
    assert res["inert_variables"] == [1]
    # the focal length alone is a constraint (exact): no merit function to be sensitive; weighted, the sensitivity is 0
    assert res["variables"][1]["sensitivity"] is None and res["constraints"][0]["met"]
    res = optimize(p.system, spec.model_copy(update={"constraints": "penalty"}))
    assert res["inert_variables"] == [1] and res["variables"][1]["sensitivity"] == 0.0


# ----------------------------------------------------------------------------- polychromatic wavefront
def test_rms_wavefront_one_wavelength_matches_the_wavefront_analysis():
    p = singlet()
    px, py, pw = gauss_pupil(6)
    cs = compile_system(p.system)
    for f in (0, 2):
        W, _, _ = wavefront_samples(cs, 1, f, px, py, vignetting=True)
        spec = _spec([{"surface_id": "s2", "parameter": "thickness", "min": 90, "max": 100}], [{"type": "rms_wavefront", "field": f, "wavelength": 1, "rings": 6, "reference": "chief"}])
        mf = MeritFunction(p.system, spec)
        _, b = mf.evaluate(mf.x0)
        mean = (pw * W).sum()
        assert b[0]["value"] == pytest.approx(float(np.sqrt((pw * (W - mean) ** 2).sum())), rel=1e-9)
        # the centroid reference also removes the tilt (zero on axis by symmetry)
        A = np.stack([np.ones_like(px), px, py], 1) * np.sqrt(pw)[:, None]
        coef = np.linalg.lstsq(A, W * np.sqrt(pw), rcond=None)[0]
        rms_c = float(np.sqrt((pw * (W - coef[0] - coef[1] * px - coef[2] * py) ** 2).sum()))
        spec_c = spec.model_copy(update={"operands": [spec.operands[0].model_copy(update={"reference": "centroid"})]})
        mf = MeritFunction(p.system, spec_c)
        assert mf.evaluate(mf.x0)[1][0]["value"] == pytest.approx(rms_c, rel=1e-9)


def test_polychromatic_rms_wavefront_on_axis_is_the_weighted_per_wavelength_rms():
    p = singlet()
    cs = compile_system(p.system)
    px, py, pw = gauss_pupil(6)
    lam = [w.value for w in p.system.wavelengths]
    wts = [w.weight for w in p.system.wavelengths]
    acc = 0.0
    for k in range(3):
        W, _, _ = wavefront_samples(cs, k, 0, px, py, vignetting=True)
        mean = (pw * W).sum()
        acc += wts[k] * (lam[k] / lam[1]) ** 2 * float((pw * (W - mean) ** 2).sum())
    spec = _spec([{"surface_id": "s2", "parameter": "thickness", "min": 90, "max": 100}], [{"type": "rms_wavefront", "field": 0, "rings": 6, "reference": "chief"}])
    mf = MeritFunction(p.system, spec)
    v = mf.evaluate(mf.x0)[1][0]["value"]
    assert v == pytest.approx(math.sqrt(acc / sum(wts)), rel=1e-4)
    # axial colour counts: far more than the primary wavelength alone
    one = MeritFunction(p.system, spec.model_copy(update={"operands": [spec.operands[0].model_copy(update={"wavelength": 1})]}))
    assert v > 3 * one.evaluate(one.x0)[1][0]["value"]


def test_lateral_colour_is_a_tilt_of_the_common_reference():
    """Off axis, wavelength F against the primary chief ray's reference sphere differs from its own by a tilt of
    n' delta sin(U') at the pupil edge (delta: the chief-ray separation on the image)."""
    p = geiser_triplet()
    cs = compile_system(p.system, p.custom_materials)
    pupil = compute_pupil(cs)
    f, w = 2, 0
    px = np.zeros(9)
    py = np.linspace(-1, 1, 9)
    Cp, Ep, Rp, _, n_img = reference_geometry(cs, 1, f, pupil)
    Cw, Ew, Rw, _, _ = reference_geometry(cs, w, f, pupil)
    res = trace_pupil(cs, w, f, px, py, pupil)
    d = opl_to_reference(cs, res, Cw, Ew, Rw, n_img) - opl_to_reference(cs, res, Cp, Ep, Rp, n_img)
    tilt = np.polyfit(py, d - d.mean(), 1)[0]
    delta = Cw[1] - Cp[1]
    marg = trace_pupil(cs, w, f, np.array([0.0, 0.0]), np.array([1.0, -1.0]), pupil)
    sin_u = 0.5 * abs(marg.dirs[0, 1] - marg.dirs[1, 1])
    assert abs(delta) > 1e-4  # 0.46 um of lateral colour (F - d) at 20 deg
    assert abs(tilt) == pytest.approx(n_img * abs(delta) * sin_u, rel=0.05)


# ----------------------------------------------------------------------------- Gaussian beam onto a detector
def _abcd_lens(R1, R2, t, n):
    """Thick lens in air: refraction, translation, refraction (reduced angles)."""
    def ref(R, n1, n2):
        return np.array([[1.0, 0.0], [-(n2 - n1) / R if R else 0.0, 1.0]])

    return ref(R2, n, 1.0) @ np.array([[1.0, t / n], [0.0, 1.0]]) @ ref(R1, 1.0, n)


def _beam_radius(q):
    lam_mm = 1.064e-3
    return math.sqrt(-lam_mm / (math.pi * (1.0 / q).imag))


def _beam_system(lenses, gap_after, epd=8.0):
    surf = [{"id": "obj", "thickness": None}]
    for k, (R1, R2, t, d) in enumerate(lenses):
        surf.append({"id": f"l{k}a", "radius": R1, "thickness": t, "material": "N-BK7", "is_stop": k == 0})
        surf.append({"id": f"l{k}b", "radius": R2, "thickness": d})
    surf[-1]["thickness"] = gap_after
    surf.append({"id": "img"})
    return make_system(surf, wavelengths=[{"value": 1.064}], fields=[{"y": 0.0}], aperture={"type": "epd", "value": epd})


def _beam_ns(w0=1.0, rays=20000):
    src = LightSource(id="laser", name="laser", kind="gaussian_beam", beam_waist_x=w0, beam_waist_y=w0, beam_m2=1.0, rays=rays, placement={"anchor": "l0a", "position": [0.0, 0.0, -5.0]}, wavelengths=[{"value": 1.064, "weight": 1.0}])
    det = Detector(id="cam", name="sensor", placement={"anchor": "img"}, shape="circle", size_x=5.0, pixels=32)
    return [src], [det]


def _expected_diameter(system: OpticalSystem, w0=1.0):
    """2 w at the image surface by q-parameter propagation: waist at the source plane 5 mm before the first lens."""
    lam_mm = 1.064e-3
    n = MaterialLibrary().index("N-BK7", 1.064)
    q = complex(5.0, math.pi * w0 * w0 / lam_mm)  # 5 mm of free space after the waist
    s = system.surfaces
    k = 1
    while k < len(s) - 1:
        a, b = s[k], s[k + 1]
        m = _abcd_lens(a.radius, b.radius, a.thickness, n)
        q = (m[0, 0] * q + m[0, 1]) / (m[1, 0] * q + m[1, 1])
        q = q + b.thickness
        k += 2
    return 2 * _beam_radius(q)


def test_gaussian_beam_through_a_lens_focuses_to_the_gaussian_waist_and_to_a_target_size():
    lam_mm = 1.064e-3
    sysm = _beam_system([(103.4, None, 3.0, 0.0)], 196.0)
    ns = _beam_ns()
    n = MaterialLibrary().index("N-BK7", 1.064)
    f = 103.4 / (n - 1)
    # focus: the smallest beam on the sensor is the Gaussian waist 2 w0' = 2 lambda f / (pi w0)
    spec = _spec([{"surface_id": "l0b", "parameter": "thickness", "min": 150, "max": 250}], [{"type": "detector_size", "detector_id": "cam", "target": 0.0}], max_evaluations=200)
    res = optimize(sysm, spec, ns=ns)
    d_min = res["operands_after"][0]["value"]
    assert d_min == pytest.approx(2 * lam_mm * f / math.pi, rel=0.03)
    # a 0.30 mm beam: the sensor goes where the Gaussian beam is that wide (two places; this start is behind focus)
    spec = _spec([{"surface_id": "l0b", "parameter": "thickness", "min": 150, "max": 250}], [{"type": "detector_size", "detector_id": "cam", "target": 0.30}], max_evaluations=200)
    res = optimize(_beam_system([(103.4, None, 3.0, 0.0)], 230.0), spec, ns=ns)
    out = OpticalSystem.model_validate(res["system"])
    assert res["operands_after"][0]["value"] == pytest.approx(0.30, rel=1e-6)
    assert _expected_diameter(out) == pytest.approx(0.30, rel=0.02)
    assert out.surfaces[2].thickness > 200


def test_gaussian_beam_through_two_lenses_by_their_spacing():
    """A two-lens focuser (f ~ 100 and ~ 200 mm) with the sensor fixed: the lens spacing sets a 0.2 mm beam."""
    sysm = _beam_system([(51.7, None, 3.0, 40.0), (103.4, None, 3.0, 0.0)], 60.0)
    ns = _beam_ns()
    spec = _spec([{"surface_id": "l0b", "parameter": "thickness", "min": 5, "max": 120}], [{"type": "detector_size", "detector_id": "cam", "target": 0.20}], max_evaluations=300)
    res = optimize(sysm, spec, ns=ns)
    out = OpticalSystem.model_validate(res["system"])
    assert res["operands_after"][0]["value"] == pytest.approx(0.20, rel=1e-5)
    assert _expected_diameter(out) == pytest.approx(0.20, rel=0.03)
    # the ray ensemble and the Gaussian beam agree along the way too (one more check, independent of the optimiser)
    cs = compile_system(out)
    det = trace_direct(cs, *ns, seed=1)["detectors"][0]
    assert 2 * 0.5 * sum(det["plane"]["width_2sigma_mm"]) == pytest.approx(_expected_diameter(out), rel=0.03)


# ----------------------------------------------------------------------------- before/after numbers
def test_design_summary_and_regression_flags_of_quick_focus_on_the_cell_phone_lens():
    """Quick focus of the cell-phone sample (field-weighted mean RMS) moves the image 89 um: the centre blurs
    (RMS 3.9 -> 13.4 um, MTF down) while the edges sharpen; the comparison flags exactly that."""
    p = cell_phone_lens("ray-optics")  # ray-optics' transcription of the cell-phone lens
    s0 = p.system
    d = s0.model_dump()
    d["surfaces"][-2]["thickness"] = 0.728567
    s1 = OpticalSystem.model_validate(d)
    r = compare_designs(s0, s1, p.custom_materials)
    b = r["before"]
    assert b["field"] == pytest.approx(object_field(compile_system(s0, p.custom_materials), 0.0, 3.5)[1], rel=1e-12)
    assert b["distortion_pct"] == pytest.approx(3.936, abs=0.01)
    assert b["lateral_colour_um"] == pytest.approx(-0.995, abs=0.01)
    assert b["mtf_frequency"] == pytest.approx(110.0)
    assert b["min_glass_edge_mm"] == pytest.approx(0.8548, abs=1e-3)  # L1; the 0.4 mm filter plate is left out
    keys = {(f["key"], f["field"]) for f in r["flags"]}
    assert ("rms_spot_um", 0) in keys and ("mtf", 0) in keys
    assert ("rms_spot_um", 1) not in keys and ("rms_spot_um", 2) not in keys
    assert compare_designs(s0, s0, p.custom_materials)["flags"] == []


def test_the_field_profile_is_the_spot_analysis_between_the_fields_and_finds_sampling_gaps(monkeypatch):
    """design_summary's field profile is the spot analysis at intermediate fields. The gap rule flags an image that
    falls apart between the fields the merit function sees: the cell-phone lens optimised on the axis and the full
    field only reached 6.1 / 4.9 um there, and 10.7 um at 40 % of the field (VALIDATION.md)."""
    p = singlet()
    s = design_summary(p.system)
    fp = s["field_profile"]
    assert fp["defined"] == [0.0, 0.5, 1.0] and len(fp["fractions"]) == 11
    for f, k in ((0, 0), (5, 1), (10, 2)):
        assert fp["rms_um"][f] == pytest.approx(s["rms_spot_um"][k], rel=1e-9)
    assert fp["gap"] is None
    fr = [k / 10 for k in range(11)]
    bump = [6.06, 6.82, 8.76, 10.49, 10.73, 9.8, 7.29, 6.86, 7.2, 7.2, 4.91]
    g = sampling_gap(fr, bump, [0.0, 1.0], [6.06, 4.91], 2.0)
    assert g["fraction"] == 0.4 and g["ratio"] == pytest.approx(10.73 / 6.06)
    assert sampling_gap(fr, bump, [0.0, 0.4, 1.0], [6.06, 10.73, 4.91], 2.0) is None  # a field there sees it
    assert sampling_gap(fr, [6.06, None, *bump[2:]], [0.0, 1.0], [6.06, 4.91], 2.0)["rms_um"] is None  # rays fail
    assert sampling_gap(fr, [1.0] * 4 + [1.3] + [1.0] * 6, [0.0, 1.0], [1.0, 1.0], 2.0) is None  # < 0.25 Airy radius
    # compare_designs flags a gap the design after has and the design before had not
    real = summary.field_profile
    calls = []

    def profile(*a, **k):
        out = real(*a, **k)
        calls.append(1)
        if len(calls) == 2:
            out["gap"] = {"fraction": 0.3, "rms_um": 99.0, "sampled_max_um": 48.1, "ratio": 2.06}
        return out

    monkeypatch.setattr(summary, "field_profile", profile)
    flags = compare_designs(p.system, p.system)["flags"]
    assert [(f["key"], f["after"]) for f in flags] == [("field_gap", 99.0)]
