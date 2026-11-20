"""Published reference designs reproduced from public prescriptions, against the values their sources state.

Double Gauss f/1.7 (Lautebacher & Brendel, US 2,784,643), as tabulated in W. J. Smith, Modern Lens Design
(2005), p. 323, with the glasses of COMSOL's Ray Optics tutorial of the same lens (HOYA LAF3, HOYA BAF11,
SCHOTT N-SF5). Stated there: f = 100.2 mm, f/1.7, back focus 61.418 mm (the image distance of the table),
and, at 550 nm on axis with 1027 hexapolar rays, the plane of minimum RMS spot 187 um before the nominal
image surface.
"""

import math

import numpy as np
import pytest

from opticore.model import OpticalSystem
from opticore.paraxial import compute_pupil, paraxial_data
from opticore.raytrace import hexapolar, trace_pupil
from opticore.samples import HOYA_BAF11, HOYA_LAF3, get_sample
from opticore.system import compile_system


@pytest.fixture(scope="module")
def dg():
    p = get_sample("double-gauss")
    return p, compile_system(p.system, p.custom_materials)


def test_double_gauss_glasses_reproduce_the_catalogue():
    from opticore.materials.catalog import MaterialLibrary

    lib = MaterialLibrary([HOYA_LAF3, HOYA_BAF11])
    for rec in (HOYA_LAF3, HOYA_BAF11):
        m = lib.get(rec["name"])
        assert m.nd == pytest.approx(rec["nd_ref"], abs=1e-5)
        assert m.vd == pytest.approx(rec["vd_ref"], abs=0.01)
    assert lib.get("N-SF5").nd == pytest.approx(1.67271, abs=1e-5)


def test_double_gauss_first_order_data_match_the_source(dg):
    p, cs = dg
    pd = paraxial_data(cs)
    assert pd.efl == pytest.approx(100.2, abs=0.05)  # stated to 0.1 mm
    assert pd.efl / p.system.aperture.value == pytest.approx(1.70, abs=0.005)
    assert pd.bfl == pytest.approx(61.418, abs=0.005)  # the table's image distance is the paraxial focus at d
    assert not [d for d in cs.diagnostics if d.level in ("warning", "error")]


def test_double_gauss_best_focus_at_550nm_matches_comsol():
    """Minimum-RMS plane on axis at 550 nm with 1027 hexapolar rays (18 rings, as in the tutorial): 186 um
    before the nominal image surface, against 187 um from COMSOL (meshed solids, Edlen air)."""
    p = get_sample("double-gauss")
    sysd = p.system.model_dump()
    sysd.update(wavelengths=[{"value": 0.55, "weight": 1.0}], primary_wavelength=0, fields=[{"y": 0.0}])
    cs = compile_system(OpticalSystem.model_validate(sysd), p.custom_materials)
    px, py = hexapolar(18)
    r = trace_pupil(cs, 0, 0, px, py, compute_pupil(cs), clip=True)
    assert int(r.ok.sum()) == 1027
    P = r.local[:, -1, :][r.ok]
    D = cs.frames[-1].to_local_dirs(r.dirs)[r.ok]
    # mean square radius about the centroid is quadratic in the defocus dz: minimise it exactly
    u = P[:, :2] - P[:, :2].mean(0)
    v = D[:, :2] / D[:, 2:3]
    v = v - v.mean(0)
    dz = -float((u * v).sum() / (v * v).sum())
    assert dz * 1e3 == pytest.approx(-187.0, abs=3.0)
    rms = math.sqrt(float(((u + dz * v) ** 2).sum(1).mean()))
    assert rms < 0.035  # mm; the residual is spherical aberration


def test_double_gauss_vignetting_of_the_published_apertures(dg):
    """The fixed clear apertures of the table vignette the full field, as published (regression baseline)."""
    p, cs = dg
    px, py = hexapolar(12)
    passed = []
    for f in range(len(p.system.fields)):
        r = trace_pupil(cs, cs.model.primary_wavelength, f, px, py, compute_pupil(cs), clip=True)
        passed.append(float(r.ok.mean()))
    assert passed[0] == 1.0
    assert all(a >= b for a, b in zip(passed, passed[1:]))
    assert passed[-1] == pytest.approx(0.397, abs=0.01)
    assert np.isfinite(passed).all()


# ---- Geiser triplet against the ray-optics documentation example (independent software) ----------------------
# ray-optics "Triplet example" (Sasian's OPTI 517 triplet): first_order_data(), list_model() and Seidel sums as
# printed there; heights to 6 significant digits, Seidel sums to 6 decimals (mm, Welford's definitions).
RO_AX_HT = [6.25, 5.72969, 4.66559, 4.63455, 5.06436, 5.1546]
RO_PR_HT = [-4.25088, -2.85718, 3.53405e-07, 0.2842, 2.67738, 3.55571, 18.1985]
RO_SEIDEL = [
    [0.027654, 0.019379, 0.013581, 0.089174, 0.072010],
    [0.022082, -0.059501, 0.160327, -0.000288, -0.431229],
    [-0.105156, 0.137692, -0.180295, -0.085097, 0.347506],
    [-0.045358, -0.076796, -0.130024, -0.095046, -0.381069],
    [0.007942, 0.028382, 0.101431, 0.024373, 0.449596],
    [0.103810, -0.050068, 0.024148, 0.103180, -0.061411],
]
RO_SUM = [0.010973, -0.000912, -0.010832, 0.036297, -0.004597]


def test_geiser_triplet_matches_ray_optics():
    from opticore.paraxial import chief_ray, marginal_ray, max_field_value, seidel_coefficients

    p = get_sample("geiser-triplet")
    cs = compile_system(p.system, p.custom_materials)
    pd = paraxial_data(cs)
    assert pd.efl == pytest.approx(50.0, abs=0.005)
    assert pd.bfl == pytest.approx(41.24, abs=0.005)
    assert pd.ffl == pytest.approx(-37.1, abs=0.05)
    assert pd.front_principal_plane == pytest.approx(12.9, abs=0.05)
    assert pd.rear_principal_plane == pytest.approx(-8.763, abs=5e-4)
    assert pd.entrance_pupil_position == pytest.approx(11.68, abs=0.005)
    assert pd.exit_pupil_position + p.system.surfaces[-2].thickness == pytest.approx(-10.01, abs=0.005)  # from the last surface
    assert pd.exit_pupil_diameter / 2 == pytest.approx(6.406, abs=5e-4)
    assert pd.efl / p.system.aperture.value == pytest.approx(4.0, abs=1e-3)
    pu = compute_pupil(cs, 1)
    m = marginal_ray(cs, 1, pu)
    c = chief_ray(cs, 1, pu, max_field_value(cs))
    assert np.allclose(m.y[1:7], RO_AX_HT, atol=1e-5)
    assert np.allclose(c.y[1:8], RO_PR_HT, atol=1e-4)
    sc = seidel_coefficients(cs, 1)
    assert sc["lagrange_invariant"] == pytest.approx(2.275, abs=5e-4)  # optical invariant
    got = [[r[k] for k in ("SI", "SII", "SIII", "SIV", "SV")] for r in sc["surfaces"]]
    assert np.allclose(got, RO_SEIDEL, atol=1.5e-6)
    assert np.allclose([sc["total"][k] for k in ("SI", "SII", "SIII", "SIV", "SV")], RO_SUM, atol=1.5e-6)


# ---- Petzval (Kidger, COMSOL tutorial) --------------------------------------------------------------------------


def test_petzval_matches_its_source():
    """f = 100 mm nominally (COMSOL substituted glasses: 100.8 mm here), f/2.4, and the table's image plane is the
    polychromatic best (minimum-RMS) focus on axis, as the tutorial's adjusted back focus."""
    p = get_sample("petzval")
    cs = compile_system(p.system, p.custom_materials)
    pd = paraxial_data(cs)
    assert pd.efl == pytest.approx(100.0, rel=0.01)
    assert pd.efl / p.system.aperture.value == pytest.approx(2.4, abs=0.05)
    Ps, Ds = [], []
    for w in range(3):
        r = trace_pupil(cs, w, 0, *hexapolar(12), compute_pupil(cs), clip=True)
        assert r.ok.all()
        Ps.append(r.local[:, -1, :2][r.ok])
        Ds.append(cs.frames[-1].to_local_dirs(r.dirs)[r.ok])
    P, D = np.vstack(Ps), np.vstack(Ds)
    u = P - P.mean(0)
    v = D[:, :2] / D[:, 2:3]
    v = v - v.mean(0)
    dz = -float((u * v).sum() / (v * v).sum())
    assert abs(dz) < 0.005  # mm


# ---- Hubble Space Telescope (nominal design) --------------------------------------------------------------------


def test_hubble_first_order_and_ritchey_chretien_conditions():
    """f = 57.6 m and f/24 (Lallo 2012), focus 1500 mm behind the primary (COMSOL table), and the Ritchey-Chretien
    property: third-order spherical aberration and coma vanish up to the rounding of the published conics
    (W040 = S_I / 8 lambda, W131 = S_II / 2 lambda below 0.1 and 0.05 waves), while astigmatism and field curvature
    remain. The Petzval curvature from the Seidel sum equals the two-mirror formula 2 (1/R_s - 1/R_p)."""
    from opticore.paraxial import seidel_coefficients

    p = get_sample("hubble")
    cs = compile_system(p.system)
    pd = paraxial_data(cs)
    assert pd.efl == pytest.approx(57600.0, rel=1e-4)
    assert pd.efl / p.system.aperture.value == pytest.approx(24.0, abs=1e-3)
    assert pd.bfl - 4906.071 == pytest.approx(1500.0, abs=0.2)  # paraxial focus behind the primary vertex
    sc = seidel_coefficients(cs, 0)
    lam = 0.55e-3
    t = sc["total"]
    assert abs(t["SI"]) / (8 * lam) < 0.1
    assert abs(t["SII"]) / (2 * lam) < 0.05
    assert abs(t["SIII"]) / (2 * lam) > 1.0  # astigmatism remains (waves at 10')
    petzval = t["SIV"] / sc["lagrange_invariant"] ** 2
    assert petzval == pytest.approx(2 * (1 / 1358.0 - 1 / 11040.0), rel=1e-9)
    # the curved focal surface of the source flattens the field: RMS at 10' far below a flat image surface
    def rms(system, f):
        c2 = compile_system(system)
        r = trace_pupil(c2, 0, f, *hexapolar(10), compute_pupil(c2), clip=True)
        xy = r.local[:, -1, :2][r.ok]
        return math.sqrt(float(((xy - xy.mean(0)) ** 2).sum(1).mean()))

    flat = p.system.model_copy(deep=True)
    flat.surfaces[-1].radius = None
    assert rms(p.system, 2) < rms(flat, 2) / 8
    assert rms(p.system, 0) < 0.006  # mm on axis, outside the obscuration (diffraction-limited geometry: Airy radius 16 um)


# ---- Cell phone lens (US 7,535,658): the patent's Example 1, and ray-optics' transcription against ray-optics ------


def test_cell_phone_lens_matches_the_patent():
    """US 7,535,658 Example 1 as printed (FIGS. 10, 11, 28, 29), read from the patent's drawings.

    * FIG. 28: f1/f = 0.78, |f2/f| = 1.06, f3/f = 5.07, bf/TL = 0.24, TL/(2 Ih) = 0.92 (two decimals). f3/f also tells the
      patent's R5 = 5.794 from ray-optics' 5.694 (4.86).
    * FIG. 10 margin: f = 5.57, F/2.8, bf = 1.53, TL = 6.41 (air basis), Ih = 3.5. The model's f = 5.587 and paraxial
      bf = 1.546 lie 0.3 % above: within the rounding of the printed indices (3 decimals).
    * FIG. 29 (read from the curves): distortion about -1.7 % near 15 % of the image height and +0.5 % at the edge;
      astigmatism within about +-0.03 mm (checked to +-0.05 mm)."""
    from opticore.analysis.aberrations import field_curvature_distortion

    p = get_sample("cell-phone-lens")
    s = p.system
    cs = compile_system(s, p.custom_materials)
    assert not [d for d in cs.diagnostics if d.level in ("warning", "error")]
    pd = paraxial_data(cs)
    f = pd.efl
    w = s.primary_wavelength

    def element(i):  # thick lens in air between surfaces i and i + 1
        n = float(cs.n_after[w, i])
        c1, c2 = s.surfaces[i].curvature, s.surfaces[i + 1].curvature
        p1, p2 = (n - 1) * c1, (1 - n) * c2
        return 1.0 / (p1 + p2 - p1 * p2 * s.surfaces[i].thickness / n)

    idx = {x.id: k for k, x in enumerate(s.surfaces)}
    n_cg = float(cs.n_after[w, idx["ir1"]])
    tl = sum(s.surfaces[idx[k]].thickness for k in ("c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8")) + s.surfaces[idx["ir1"]].thickness / n_cg + s.surfaces[idx["ir2"]].thickness
    bf = s.surfaces[idx["c8"]].thickness + s.surfaces[idx["ir1"]].thickness / n_cg + s.surfaces[idx["ir2"]].thickness
    assert element(idx["c1"]) / f == pytest.approx(0.78, abs=0.006)
    assert abs(element(idx["c3"]) / f) == pytest.approx(1.06, abs=0.006)
    assert element(idx["c5"]) / f == pytest.approx(5.07, abs=0.03)
    assert bf / tl == pytest.approx(0.24, abs=0.006)
    assert tl / (2 * 3.5) == pytest.approx(0.92, abs=0.006)
    assert tl == pytest.approx(6.41, abs=0.005)
    assert pd.image_space_fnum == pytest.approx(2.8, abs=1e-9)
    assert f == pytest.approx(5.57, rel=0.004)
    assert bf == pytest.approx(1.53, abs=0.01)  # S8 to the image surface, air basis (1.538)
    fc = field_curvature_distortion(cs, samples=8, wavelengths=[w])["per_wavelength"][0]
    dist = fc["distortion_percent"]
    assert -2.0 < dist[1] < -1.3  # 0.5 mm
    assert 0.0 < dist[-1] < 1.0  # 3.5 mm
    assert max(abs(x) for x in fc["tangential_mm"] + fc["sagittal_mm"]) < 0.05




def test_cell_phone_lens_matches_ray_optics():
    """ray-optics' transcription of the patent (CELL_PHONE_RAY_OPTICS: R5, one coefficient, the stop, the cover glass
    and the aperture differ from Example 1) against ray-optics' output. First-order data (printed to 4 significant digits) and real-ray intercepts (5-6 decimals) of ray-optics'
    "Cell Phone lens" example: eight odd aspheres with r^3 .. r^10 terms. ray-optics converts its image-height field
    to an object angle with the paraxial chief ray on the image surface (31.76 deg for 3.5 mm) and scales the angle for
    relative fields; its axial "marginal ray" is a ray parallel to the axis 1.0 mm high."""
    from scipy.optimize import brentq

    from opticore.paraxial import chief_ray
    from opticore.raytrace import launch, trace

    from opticore.samples import cell_phone_lens

    p = cell_phone_lens("ray-optics")
    cs = compile_system(p.system, p.custom_materials)
    assert not [d for d in cs.diagnostics if d.level in ("warning", "error")]
    pd = paraxial_data(cs)
    assert pd.efl == pytest.approx(5.555, abs=5e-4)
    assert pd.ffl == pytest.approx(-7.531, abs=5e-4)
    assert pd.front_principal_plane == pytest.approx(-1.976, abs=5e-4)
    assert pd.bfl == pytest.approx(0.5678, abs=5e-5)
    assert pd.rear_principal_plane == pytest.approx(-4.987, abs=5e-4)
    assert pd.entrance_pupil_position == pytest.approx(0.0, abs=1e-12)
    assert pd.entrance_pupil_diameter / 2 == pytest.approx(0.7936, abs=5e-5)
    assert pd.exit_pupil_diameter / 2 == pytest.approx(0.5854, abs=5e-5)
    # ray-optics' field convention: angle fields
    d = p.system.model_dump()
    d.update(field_type="angle", fields=[{"y": 0.0}, {"y": 20.0}])
    csa = compile_system(OpticalSystem.model_validate(d), p.custom_materials)
    pu = compute_pupil(csa, 1)
    theta = brentq(lambda t: float(chief_ray(csa, 1, pu, t).y[-1]) - 3.5, 1.0, 45.0)
    assert theta == pytest.approx(31.76, abs=5e-3)
    P0, D0, o = launch(csa, 1, (0.0, 0.7071 * theta), np.array([0.0, 0.0, 0.0]), np.array([0.0, 1.0, -1.0]), pu, object_units=True)
    r = trace(csa, 1, P0, D0, o)
    assert np.allclose(r.image_xy()[:, 1], [2.37370, 2.41684, 2.34160], atol=1e-5)
    r = trace(csa, 1, np.array([[0.0, 1.0, -1.0]]), np.array([[0.0, 0.0, 1.0]]), clip=False)
    assert r.image_xy()[0, 1] == pytest.approx(-0.02573, abs=5e-6)
    assert r.dirs[0, 1] == pytest.approx(-0.185004, abs=1e-6)
    assert r.dirs[0, 2] == pytest.approx(0.982738, abs=1e-6)


# ---- Zoom 17-119 mm F2.8-3.4 (Canon JP2015094867A, Numerical Example 1) ----------------------------------------------
# The patent's various data per zoom position (wide, middle, tele) and group data (focal length, length, front
# principal point from the group's first surface, rear principal point from its last surface).
CANON_EFL = (17.00, 51.00, 119.00)
CANON_EP = (49.30, 88.38, 135.35)  # entrance pupil from S1
CANON_XP = -130.84  # exit pupil from S50
CANON_FPP = (64.67, 124.67, 174.28)  # front principal point from S1
CANON_RPP = (29.02, -4.98, -72.98)  # rear principal point from S50
CANON_GROUPS = [(1, 18, 55.00, 103.59, 62.54, 42.93), (19, 26, -32.20, 20.22, 1.79, -13.90), (27, 29, -79.64, 3.71, -0.33, -2.31), (30, 50, 52.82, 84.24, 24.67, -84.56)]
# Spread (standard deviation) of each value caused by the table's own rounding (r to 0.001 mm, d to 0.01 mm), from
# 150 uniform draws within the rounding at the e line: EFL, EP, FPP, RPP per zoom position, XP; group f, FPP, RPP.
CANON_SIGMA = {"efl": (0.004, 0.014, 0.029), "ep": (0.004, 0.012, 0.041), "fpp": (0.005, 0.015, 0.048), "rpp": (0.018, 0.023, 0.070), "xp": 0.095,
               "groups": [(0.0087, 0.0033, 0.0036), (0.0026, 0.0033, 0.0064), (0.0008, 0.0004, 0.0027), (0.0104, 0.0211, 0.0232)]}


def _canon(k: int, wavelength: float | None = None):
    from opticore.samples import canon_zoom

    p = canon_zoom()
    d = p.system.model_dump()
    d["multi_config"]["active"] = k
    if wavelength is not None:
        d["wavelengths"], d["primary_wavelength"] = [{"value": wavelength}], 0
    return p, compile_system(OpticalSystem.model_validate(d), p.custom_materials)


def _agrees(value, printed, sigma):
    """Within the printed digit (0.005) plus 2.5 standard deviations of the table's rounding."""
    return abs(value - printed) <= 0.005 + 2.5 * sigma


def test_canon_zoom_glasses_are_catalogue_glasses_with_the_patents_nd_vd():
    from opticore.materials.catalog import MaterialLibrary
    from opticore.samples import CANON_ZOOM_GLASSES, CANON_ZOOM_TABLE

    lib = MaterialLibrary(list(CANON_ZOOM_GLASSES.values()))
    for (nd, vd), rec in CANON_ZOOM_GLASSES.items():
        m = lib.get(rec["name"])
        assert m.nd == pytest.approx(rec["nd_ref"], abs=4e-6) and m.vd == pytest.approx(rec["vd_ref"], abs=0.01)
        assert round(m.nd, 5) == pytest.approx(nd, abs=1e-5) and round(m.vd, 1) == pytest.approx(vd, abs=0.051)
    used = {(nd, vd) for _, _, nd, vd, _ in CANON_ZOOM_TABLE if nd}
    assert used - set(CANON_ZOOM_GLASSES) == {(1.43387, 95.1)}  # the fluorite (model glass)


def test_canon_zoom_lengths_are_the_patents():
    from opticore.samples import CANON_ZOOM_GAPS, CANON_ZOOM_TABLE

    for k in range(3):
        t = [CANON_ZOOM_GAPS[i][k] if d is None else d for i, (_, d, _, _, _) in enumerate(CANON_ZOOM_TABLE, start=1)]
        assert sum(t) == pytest.approx(325.03, abs=0.011)  # lens total length (each printed d rounded to 0.01)
    for a, b, _, length, _, _ in CANON_GROUPS:
        assert sum(CANON_ZOOM_TABLE[j][1] for j in range(a - 1, b - 1)) == pytest.approx(length, abs=0.011)


def test_canon_zoom_first_order_data_match_the_patent_at_the_e_line():
    """At the e line (546.07 nm) every published value is reproduced within the printed digit plus 2.5 standard
    deviations of the spread that the table's own rounding causes (at most 1.4 here). At the d line the exit pupil
    misses by 1.19 mm (12 standard deviations): the patent's data refer to the e line."""
    for k in range(3):
        p, cs = _canon(k)
        pd = paraxial_data(cs)
        assert _agrees(pd.efl, CANON_EFL[k], CANON_SIGMA["efl"][k])
        assert _agrees(pd.entrance_pupil_position, CANON_EP[k], CANON_SIGMA["ep"][k])
        assert _agrees(pd.front_principal_plane, CANON_FPP[k], CANON_SIGMA["fpp"][k])
        assert _agrees(pd.rear_principal_plane, CANON_RPP[k], CANON_SIGMA["rpp"][k])
        assert _agrees(pd.exit_pupil_position + p.system.surfaces[-2].thickness, CANON_XP, CANON_SIGMA["xp"])
        assert pd.image_space_fnum == pytest.approx((2.8, 2.8, 3.4)[k], abs=1e-9)
    _, cs = _canon(0, 0.5875618)
    xp_d = paraxial_data(cs).exit_pupil_position + 46.02
    assert xp_d - CANON_XP == pytest.approx(-1.19, abs=0.01) and abs(xp_d - CANON_XP) > 10 * CANON_SIGMA["xp"]


def test_canon_zoom_group_data_match_the_patent_at_the_e_line():
    from opticore.paraxial import trace_paraxial

    _, cs = _canon(0)
    w = cs.model.primary_wavelength
    for (a, b, f, _, fpp, rpp), sig in zip(CANON_GROUPS, CANON_SIGMA["groups"]):
        r1 = trace_paraxial(cs, w, 1.0, 0.0, start=a, end=b)  # reduced (y, n u) matrix of surfaces a..b in air
        r2 = trace_paraxial(cs, w, 0.0, 1.0, start=a, end=b)
        A, C, D = r1.y[b], r1.nu[b], r2.nu[b]
        assert _agrees(-1.0 / C, f, sig[0])
        assert _agrees((D - 1.0) / C, fpp, sig[1])
        assert _agrees((1.0 - A) / C, rpp, sig[2])


def test_canon_zoom_axial_beam_fits_the_published_effective_diameters():
    """Real rays (real aiming, e line): at every zoom position the full F2.8 / F3.4 axial beam passes every surface
    inside the patent's effective diameter, using up to 98 % of it."""
    from opticore.raytrace import hexapolar, trace_pupil
    from opticore.samples import CANON_ZOOM_TABLE

    eff = np.array([row[4] / 2 for row in CANON_ZOOM_TABLE])
    used = []
    for k in range(3):
        _, cs = _canon(k)
        r = trace_pupil(cs, 1, 0, *hexapolar(8), compute_pupil(cs, 1), clip=False)
        assert r.ok.all()
        h = np.hypot(r.local[:, 1:51, 0], r.local[:, 1:51, 1]).max(axis=0)
        used.append(float((h / eff).max()))
    assert max(used) < 1.0 and max(used) > 0.95


def _canon_independent(P, D, lam, k):
    """Sequential trace written here without OptiCore code: indices from the glass coefficients (Sellmeier, HOYA's
    polynomial, the fluorite's Cauchy through nd and vd), conic base and even-asphere sag by Newton, vector Snell.
    Global frame: S1's vertex at z = 0. Returns the image point and direction."""
    from opticore.samples import CANON_ZOOM_ASPHERES, CANON_ZOOM_GAPS, CANON_ZOOM_GLASSES, CANON_ZOOM_TABLE

    def index(nd, vd):
        if nd is None:
            return 1.0
        g = CANON_ZOOM_GLASSES.get((nd, vd))
        L2 = lam * lam
        if g is None:  # Cauchy n = A + B / L^2 through nd and nF - nC = (nd - 1) / vd
            B = (nd - 1.0) / vd / (1.0 / 0.4861327**2 - 1.0 / 0.6562725**2)
            return nd - B / 0.5875618**2 + B / L2
        c = g["coefficients"]
        if g["formula"] == "sellmeier":
            return math.sqrt(1.0 + sum(Bi * L2 / (L2 - Ci) for Bi, Ci in zip(c[0::2], c[1::2])))
        return math.sqrt(c[0] + sum(ci * lam**e for ci, e in zip(c[1::2], c[2::2])))

    def sag(c, kc, A, x, y):
        r2 = x * x + y * y
        root = math.sqrt(1.0 - (1.0 + kc) * c * c * r2)
        z, dz = c * r2 / (1.0 + root), c / (2.0 * root)
        for j, a in enumerate(A):
            z += a * r2 ** (2 + j)
            dz += a * (2 + j) * r2 ** (1 + j)
        return z, 2.0 * x * dz, 2.0 * y * dz

    P, D = np.array(P, float), np.array(D, float) / np.linalg.norm(D)
    z0, n1 = 0.0, 1.0
    for i, (r, d, nd, vd, _) in enumerate(CANON_ZOOM_TABLE, start=1):
        c = 0.0 if r is None else 1.0 / r
        kc, A = CANON_ZOOM_ASPHERES.get(i, (0.0, []))
        q = P - np.array([0.0, 0.0, z0])
        Bq, Cq = D[2] - c * float(q @ D), c * float(q @ q) - 2.0 * q[2]
        s = Cq / (Bq + math.sqrt(Bq * Bq - c * Cq))  # base sphere, then Newton on the full sag
        for _ in range(80):
            Q = P + s * D
            zs, gx, gy = sag(c, kc, A, Q[0], Q[1])
            ds = -(z0 + zs - Q[2]) / (gx * D[0] + gy * D[1] - D[2])
            s += ds
            if abs(ds) < 1e-15:
                break
        P = P + s * D
        _, gx, gy = sag(c, kc, A, P[0], P[1])
        N = np.array([-gx, -gy, 1.0]) / math.hypot(1.0, math.hypot(gx, gy))
        n2 = index(nd, vd)
        mu, ci = n1 / n2, float(D @ N)
        D = mu * D + (math.sqrt(1.0 - mu * mu * (1.0 - ci * ci)) - mu * ci) * N
        D /= np.linalg.norm(D)
        n1, z0 = n2, z0 + (CANON_ZOOM_GAPS[i][k] if d is None else d)
    return P + (z0 - P[2]) / D[2] * D, D


def test_canon_zoom_real_rays_equal_an_independent_trace():
    """Rays launched with real aiming (F, e, C; fields 0, 0.7 and 1.0 of 14.8 mm; chief, rim and inner pupil points)
    at the three zoom positions end at the same image point and direction in OptiCore and in the trace above."""
    from opticore.raytrace import launch, trace

    px = np.array([0.0, 0.0, 0.0, 0.7, -0.7, 0.5])
    py = np.array([0.0, 1.0, -1.0, 0.0, 0.0, 0.5])
    n = 0
    for k in range(3):
        _, cs = _canon(k)
        pu = compute_pupil(cs, 1)
        for w, lam in enumerate(cs.wavelengths):
            for f in range(3):
                P0, D0, o = launch(cs, w, f, px, py, pu)
                r = trace(cs, w, P0, D0, o, clip=False)
                for j in range(len(px)):
                    if not r.ok[j]:
                        continue
                    q, dj = _canon_independent(P0[j], D0[j], float(lam), k)
                    assert r.points[j, -1] == pytest.approx(q, abs=1e-10)
                    assert r.dirs[j] == pytest.approx(dj, abs=1e-12)
                    n += 1
    assert n >= 150


def test_canon_zoom_vignetting_factors_per_zoom_position():
    """Each zoom position carries its own vignetting factors (configuration operands per field): they are the
    vignetting analysis of that position's published apertures (VD rounded to 1e-4, VC rounded up plus 1e-4), and
    with them every marginal ray passes in every zoom position (no messages)."""
    from opticore.analysis.evaluate import evaluate_system
    from opticore.analysis.vignetting import vignetting_factors
    from opticore.samples import CANON_ZOOM_VIGNETTING

    for k in range(3):
        p, cs = _canon(k)
        for (f, key), values in CANON_ZOOM_VIGNETTING.items():
            assert getattr(cs.model.fields[f], key) == values[k]
        assert evaluate_system(cs)["diagnostics"] == []
        d = cs.model.model_dump()
        for fd in d["fields"]:
            fd.update(vdx=0.0, vdy=0.0, vcx=0.0, vcy=0.0)
        d["multi_config"] = None
        raw = vignetting_factors(compile_system(OpticalSystem.model_validate(d), p.custom_materials))["fields"]
        for (f, key), values in CANON_ZOOM_VIGNETTING.items():
            if key.startswith("vc"):
                assert 0.0 < values[k] - raw[f][key] <= 2.0e-4
            else:
                assert abs(values[k] - raw[f][key]) <= 5.0e-5
