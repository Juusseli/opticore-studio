"""Tolerancing of surface form (power, irregularity, Zernike terms),
Abbe-number tolerances, the MTF criterion, yield with its confidence interval and inverse allocation."""

import math

import numpy as np
import pytest
from scipy.stats import norm

from opticore.analysis.diffraction import mtf as mtf_analysis
from opticore.materials import MaterialLibrary
from opticore.materials.dispersion import LAMBDA_C, LAMBDA_D, LAMBDA_F
from opticore.optimize.merit import Operand
from opticore.samples import achromat, get_sample
from opticore.system import compile_system
from opticore.tolerance import (
    Compensator,
    Evaluator,
    Tolerance,
    ToleranceError,
    ToleranceSpec,
    abbe_number,
    analyze,
    clear_apertures,
    default_spec,
    perturb,
    solve_factor,
    wilson_interval,
)

from .conftest import make_system

LAM_T = 0.54607  # um, ISO 10110-5 test wavelength
FRINGE = LAM_T * 1e-3 / 2  # mm of surface height per fringe


def _window(material="N-BK7"):
    """Collimated beam through a plane window (stop on its front face) and an ideal lens. The ideal lens is
    exact for its design conjugate only; rays deviated by an aberration see O(NA²) residuals (0.19 % of the
    RMS at F/10), so a long focal length (F/1000) keeps the benchmark at normal incidence."""
    return make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "w1", "thickness": 5.0, "material": material, "is_stop": True},
            {"id": "w2", "thickness": 10.0},
            {"id": "L", "type": "ideal", "focal_length": 10000.0, "thickness": 10000.0},
            {"id": "img"},
        ],
        wavelengths=[{"value": 0.5875618}],
        fields=[{"y": 0.0}],
        aperture={"type": "epd", "value": 10.0},
    )


def _mirror():
    return make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "m1", "radius": -200.0, "thickness": -100.0, "material": "MIRROR", "is_stop": True},
            {"id": "img"},
        ],
        wavelengths=[{"value": 0.5875618}],
        fields=[{"y": 0.0}],
        aperture={"type": "epd", "value": 20.0},
    )


def _wfe(system, tols, values, rings=6):
    ev = Evaluator(system, ToleranceSpec(tolerances=tols, criterion="rms_wavefront", rings=rings), [])
    return ev.evaluate(np.array(values, dtype=float))["value"]


def _sag_delta(system, tol, value, angle=0.0, n=181):
    """Sag change of the toleranced surface on a polar grid over its clear aperture."""
    ap = clear_apertures(system)
    pt = perturb(system, [tol], [value], {0: angle}, ap, LAM_T)
    i = next(k for k, s in enumerate(system.surfaces) if s.id == tol.surface_id)
    a = compile_system(system).shapes[i]
    b = compile_system(pt.system).shapes[i]
    r = np.union1d(np.linspace(0.0, ap[tol.surface_id], n), [ap[tol.surface_id] / math.sqrt(2.0)])  # Z9 extremum
    th = np.radians(np.arange(0.0, 360.0, 0.5))  # contains the extremes of the 30° orientation
    R, T = np.meshgrid(r, th)
    x, y = R * np.cos(T), R * np.sin(T)
    return np.asarray(b.sag_xy(x, y)) - np.asarray(a.sag_xy(x, y)), x, y, ap[tol.surface_id]


# ----------------------------------------------------------------------------- surface form
def test_power_changes_the_edge_sag_by_the_fringes():
    sysm = get_sample("singlet").system
    for sid, v in (("s1", 3.0), ("s1", -2.0), ("s2", 1.5)):  # curved and plane surfaces
        d, x, y, r = _sag_delta(sysm, Tolerance(type="power", surface_id=sid, min=-5, max=5), v)
        edge = np.isclose(np.hypot(x, y), r)
        assert d[edge] == pytest.approx(v * FRINGE, rel=1e-9)
        assert abs(d).max() == pytest.approx(abs(v) * FRINGE, rel=1e-9)  # monotone: PV = edge value


@pytest.mark.parametrize("kind, pv_shape", [("irregularity", 2.0), ("irregularity_rotational", 1.5)])
def test_irregularity_has_the_stated_peak_to_valley(kind, pv_shape):
    sysm = get_sample("singlet").system
    tol = Tolerance(type=kind, surface_id="s1", min=-1, max=1)
    d, x, y, r = _sag_delta(sysm, tol, 0.8, angle=math.radians(30.0))
    assert d.max() - d.min() == pytest.approx(0.8 * FRINGE, rel=1e-6)
    if kind == "irregularity":
        # astigmatic: the highest point lies on the rim at the drawn orientation (or opposite)
        k = np.argmax(d)
        assert math.degrees(math.atan2(y.flat[k], x.flat[k])) % 180.0 == pytest.approx(30.0, abs=1.0)
    else:
        # rotationally symmetric, vertex fixed
        assert d.std(axis=0).max() < 1e-15
        assert np.allclose(d[:, 0], 0.0, atol=1e-18)


def test_zernike_form_wavefront_at_normal_incidence():
    """Acceptance benchmark: a sag error dz on the window face changes the transmitted wavefront by
    (n - 1) dz. Fringe Z5, Z9 and Z10 have RMS 1/sqrt(6), 1/sqrt(5) and 1/sqrt(8) over the pupil."""
    sysm = _window()
    n = MaterialLibrary().index("N-BK7", 0.5875618)
    lam = 0.5875618e-3
    assert _wfe(sysm, [Tolerance(type="zernike_form", surface_id="w1", term=5, min=-1, max=1)], [0.0]) < 1e-9
    for term, rms in ((5, 1 / math.sqrt(6)), (9, 1 / math.sqrt(5)), (10, 1 / math.sqrt(8))):
        a_um = 0.2
        w = _wfe(sysm, [Tolerance(type="zernike_form", surface_id="w1", term=term, min=-1, max=1)], [a_um])
        assert w == pytest.approx((n - 1) * a_um * 1e-3 * rms / lam, rel=1e-5)


def test_mirror_form_error_doubles_in_reflection():
    sysm = _mirror()
    lam = 0.5875618e-3
    w0 = _wfe(sysm, [Tolerance(type="irregularity", surface_id="m1", min=-1, max=1)], [0.0])
    w = _wfe(sysm, [Tolerance(type="irregularity", surface_id="m1", min=-1, max=1)], [1.0])
    a = FRINGE / 2.0  # Z5 coefficient of one fringe PV
    # astigmatism is orthogonal to the mirror's spherical aberration: the RMS add in quadrature;
    # 2 dz cos(i) with i <= 0.05 rad at F/5
    assert math.sqrt(w * w - w0 * w0) == pytest.approx(2 * a / math.sqrt(6) / lam, rel=2e-3)


def test_form_tolerances_on_unsupported_surfaces_are_refused():
    p = get_sample("singlet").system
    d = p.model_dump()
    d["surfaces"][1].update(type="biconic", radius_x=60.0)
    from opticore.model import OpticalSystem

    with pytest.raises(ToleranceError):
        analyze(OpticalSystem.model_validate(d), ToleranceSpec(tolerances=[Tolerance(type="power", surface_id="s1", min=-1, max=1)], monte_carlo_trials=0))
    with pytest.raises(ValueError):
        Tolerance(type="zernike_form", surface_id="s1", min=-1, max=1)  # needs its term


def test_zernike_surface_keeps_its_normalisation():
    d = get_sample("singlet").system.model_dump()
    d["surfaces"][1].update(type="zernike", zernike_coefficients=[0, 0, 0, 0, 1e-4], zernike_norm_radius=8.0)
    from opticore.model import OpticalSystem

    sysm = OpticalSystem.model_validate(d)
    ap = clear_apertures(sysm)
    assert ap["s1"] == 8.0
    pt = perturb(sysm, [Tolerance(type="zernike_form", surface_id="s1", term=5, min=-1, max=1)], [0.5], None, ap, LAM_T)
    s1 = next(s for s in pt.system.surfaces if s.id == "s1")
    assert s1.zernike_norm_radius == 8.0 and s1.zernike_coefficients[4] == pytest.approx(1e-4 + 0.5e-3)


# ----------------------------------------------------------------------------- glass
def test_abbe_tolerance_changes_vd_at_constant_nd():
    base = get_sample("singlet").system
    d = base.model_dump()
    d["wavelengths"] = [{"value": LAMBDA_F}, {"value": LAMBDA_D}, {"value": LAMBDA_C}]
    d["primary_wavelength"] = 1
    from opticore.model import OpticalSystem

    sysm = OpticalSystem.model_validate(d)
    vd0 = abbe_number(MaterialLibrary(), "N-BK7")

    def indices(offsets, s=sysm):
        cs = compile_system(s, (), offsets)
        return cs.n_after[:, 1]

    nf, nd, nc = indices({})
    assert (nd - 1) / (nf - nc) == pytest.approx(vd0, rel=1e-14)
    nf2, nd2, nc2 = indices({"s1": (0.0, -0.4)})
    assert nd2 == nd
    assert (nd2 - 1) / (nf2 - nc2) == pytest.approx(vd0 - 0.4, rel=1e-12)
    nf3, nd3, nc3 = indices({"s1": (2e-4, 0.3)})  # with an index tolerance as well
    assert nd3 == pytest.approx(nd + 2e-4, abs=1e-15)
    assert nf3 - nc3 == pytest.approx((nf - nc) * vd0 / (vd0 + 0.3), rel=1e-12)
    # in an environment (40 °C): exact against that environment's indices
    env = OpticalSystem.model_validate({**d, "environment_enabled": True, "temperature_c": 40.0})
    ef, ed, ec = indices({}, env)
    ef2, ed2, ec2 = indices({"s1": (0.0, 0.5)}, env)
    assert (ed2 - 1) / (ef2 - ec2) == pytest.approx((ed - 1) / (ef - ec) + 0.5, rel=1e-12)


def test_default_spec_has_form_and_glass_tolerances():
    sysm = achromat(True).system
    spec = default_spec(sysm, "precision")
    kinds = {}
    for t in spec.tolerances:
        kinds.setdefault(t.type, []).append(t)
    assert len(kinds["power"]) == 3 and kinds["power"][0].max == 3.0
    assert len(kinds["irregularity"]) == 3 and kinds["irregularity"][0].max == 1.0
    assert [t.surface_id for t in kinds["abbe"]] == ["d1", "d2"]
    assert kinds["abbe"][0].max == pytest.approx(0.005 * abbe_number(MaterialLibrary(), "N-BK7"))


# ----------------------------------------------------------------------------- statistics
def test_wilson_interval_textbook_values():
    lo, hi = wilson_interval(5, 10)
    assert (lo, hi) == pytest.approx((0.2366, 0.7634), abs=1e-4)
    lo, hi = wilson_interval(0, 10)
    assert lo == 0.0 and hi == pytest.approx(3.8415 / 13.8415, abs=1e-4)
    assert wilson_interval(10, 10)[1] == 1.0


def test_yield_of_a_monotonic_criterion_matches_the_truncated_normal():
    """Benchmark: a criterion monotonic in one tolerance (the EFL against a radius error). Its limit at the
    value for +1 sigma (limits = ±2 sigma) is met with probability (Phi(1) - Phi(-2)) / (Phi(2) - Phi(-2))."""
    sysm = get_sample("singlet").system
    tol = Tolerance(type="radius", surface_id="s1", min=-0.2, max=0.2)
    ops = [Operand(type="efl", target=0.0)]
    ev = Evaluator(sysm, ToleranceSpec(tolerances=[tol], criterion="merit"), [], ops)
    sigma = 0.1
    limit = max(ev.evaluate(np.array([sigma]))["value"], ev.evaluate(np.array([-sigma]))["value"])
    spec = ToleranceSpec(tolerances=[tol], criterion="merit", monte_carlo_trials=400, seed=7, limit=limit)
    r = analyze(sysm, spec, (), ops)
    expected = (norm.cdf(1.0) - norm.cdf(-2.0)) / (norm.cdf(2.0) - norm.cdf(-2.0))
    y = r["yield"]
    assert y["trials"] == 400 and y["limit"] == limit
    assert y["ci95"][0] <= expected <= y["ci95"][1]
    assert y["fraction"] == pytest.approx(expected, abs=0.05)


# ----------------------------------------------------------------------------- MTF criterion
def test_mtf_criterion_matches_the_mtf_analysis_and_degrades_with_defocus():
    p = achromat(True)
    # ±0.2 mm is several depths of focus (±29 µm at F/5) either way of the best focus
    spec = ToleranceSpec(tolerances=[Tolerance(type="thickness", surface_id="d3", min=-0.2, max=0.2)], criterion="mtf", mtf_frequency=40.0, monte_carlo_trials=8, limit=0.3)
    r = analyze(p.system, spec, p.custom_materials)
    cs = compile_system(p.system, p.custom_materials)
    vals = []
    for f in range(len(p.system.fields)):
        m = mtf_analysis(cs, [f], max_frequency=40.0, samples=2, grid=32, pad=4)
        vals.append(0.5 * (m["fields"][0]["tangential"][-1] + m["fields"][0]["sagittal"][-1]))
    assert r["nominal"] == pytest.approx(float(np.mean(vals)), rel=1e-12)
    assert r["sense"] == -1 and r["unit"] == ""
    row = r["sensitivity"][0]
    assert row["at_min"] < r["nominal"] and row["at_max"] < r["nominal"]  # defocus lowers the MTF either way
    assert r["rss_estimate"] == pytest.approx(r["nominal"] - row["worst_change"])
    # higher is better: trials at or above the limit pass
    vals = [v for v in r["monte_carlo"]["values"] if v is not None]
    assert r["yield"]["passed"] == sum(1 for v in vals if v >= 0.3)


# ----------------------------------------------------------------------------- allocation
def test_allocated_limits_round_toward_zero():
    from opticore.tolerance import round_toward_zero

    assert round_toward_zero(0.22930011749779977) == 0.229
    assert round_toward_zero(-17.762003698016546) == -17.7
    assert round_toward_zero(0.0009240908) == pytest.approx(0.000924, rel=1e-12)
    assert round_toward_zero(123456.0) == 123000.0
    assert round_toward_zero(0.0) == 0.0


def test_solve_factor_on_quadratic_and_saturating_models():
    # steps aim 2.5 % under the share (never over it): one step for an exact quadratic
    f, g, cap = solve_factor(lambda f: 3.0 * f * f, 3.0, 12.0)
    assert f == pytest.approx(2.0 * math.sqrt(0.975), rel=1e-12) and g <= 12.0 and cap is None
    f, g, cap = solve_factor(lambda f: 2.0 * f + 5.0 * f * f, 7.0, 1.0)
    assert 0.95 <= g <= 1.0 and cap is None
    assert f == pytest.approx((-2 + math.sqrt(4 + 20 * g)) / 10, rel=1e-12)
    f, g, cap = solve_factor(lambda f: 0.0, 0.0, 1.0)
    assert f == 10.0 and cap == "max"


def test_allocation_of_a_quadratic_merit_is_analytic():
    """Benchmark: three orthogonal Zernike errors on a window behind which a perfect lens focuses. The RMS
    wavefront is sqrt(sum (k_j a_j)^2) with k_j = (n - 1) RMS_j / lambda, so equal shares of the budget L^2
    give a_j = L / (sqrt(3) k_j) exactly."""
    sysm = _window()
    n = MaterialLibrary().index("N-BK7", 0.5875618)
    lam = 0.5875618e-3
    terms = {5: 1 / math.sqrt(6), 9: 1 / math.sqrt(5), 10: 1 / math.sqrt(8)}
    tols = [Tolerance(type="zernike_form", surface_id="w1", term=j, min=-0.1, max=0.1) for j in terms]
    limit = 0.05  # waves RMS
    spec = ToleranceSpec(tolerances=tols, criterion="rms_wavefront", rings=6, monte_carlo_trials=40, limit=limit)
    r = analyze(sysm, spec, allocate=True)
    al = r["allocation"]
    for row, (j, rms) in zip(sorted(al["rows"], key=lambda x: x["term"]), sorted(terms.items())):
        k = (n - 1) * 1e-3 * rms / lam  # waves per um
        assert row["new_max"] == pytest.approx(limit / (math.sqrt(3) * k), rel=0.05)
        assert row["new_max"] <= limit / (math.sqrt(3) * k) * (1 + 1e-6)  # never over the share
    assert al["predicted"] == pytest.approx(limit, rel=0.05) and al["predicted"] <= limit * (1 + 1e-9)
    # all three at their allocated limits together meet the specification
    ev = Evaluator(sysm, ToleranceSpec(tolerances=tols, criterion="rms_wavefront", rings=6), [])
    at = ev.evaluate(np.array([row["new_max"] for row in sorted(al["rows"], key=lambda x: x["tolerance"])]))["value"]
    assert at == pytest.approx(al["predicted"], rel=1e-3)
    # the confirming Monte Carlo used the allocated limits
    assert r["monte_carlo"]["allocated_limits"] and r["yield"]["fraction"] == 1.0
    # a locked tolerance keeps its limits and its use of the budget is taken first
    tols[0].locked = True
    r2 = analyze(sysm, ToleranceSpec(tolerances=tols, criterion="rms_wavefront", rings=6, monte_carlo_trials=0, limit=limit), allocate=True)
    locked = next(x for x in r2["allocation"]["rows"] if x["locked"])
    assert locked["factor"] == 1.0 and locked["new_max"] == 0.1


def test_allocation_refusals():
    sysm = _window()
    tol = Tolerance(type="zernike_form", surface_id="w1", term=5, min=-0.1, max=0.1)
    with pytest.raises(ToleranceError):
        analyze(sysm, ToleranceSpec(tolerances=[tol], criterion="rms_wavefront"), allocate=True)  # no limit
    with pytest.raises(ToleranceError):  # the nominal system already fails a negative budget
        analyze(sysm, ToleranceSpec(tolerances=[tol], criterion="rms_wavefront", limit=-1.0), allocate=True)


def test_doublet_yield_and_allocation():
    """Acceptance criterion: the sample doublet toleranced with irregularity and glass tolerances to a yield figure, and
    an inverse allocation that meets an RMS-spot budget in the confirming Monte Carlo run."""
    p = achromat(True)
    pick = {("radius", "d1"), ("power", "d2"), ("irregularity", "d1"), ("irregularity", "d3"), ("index", "d2"), ("abbe", "d1"), ("abbe", "d2"), ("element_tilt_x", "d1")}
    full = default_spec(p.system, "precision")
    tols = [t for t in full.tolerances if (t.type, t.surface_id) in pick]
    assert len(tols) == len(pick)
    comps = [Compensator(surface_id="d3", parameter="thickness", range=1.0)]
    nominal = analyze(p.system, ToleranceSpec(tolerances=tols[:1], compensators=comps, monte_carlo_trials=0, compensator_evaluations=20))["nominal"]
    limit = 1.25 * nominal
    spec = ToleranceSpec(tolerances=tols, compensators=comps, monte_carlo_trials=30, seed=3, limit=limit, compensator_evaluations=20)
    r = analyze(p.system, spec)
    y = r["yield"]
    assert y["trials"] == 30 and 0.0 <= y["ci95"][0] <= y["fraction"] <= y["ci95"][1] <= 1.0
    a = analyze(p.system, spec, allocate=True)
    al = a["allocation"]
    assert al["predicted"] <= limit * (1 + 1e-9)
    assert any(abs(row["factor"] - 1.0) > 0.05 for row in al["rows"])
    vals = [v for v in a["monte_carlo"]["values"] if v is not None]
    assert len(vals) == 30 and max(vals) <= limit
    assert a["yield"]["fraction"] == 1.0
