"""Professional coating-design tools (coatdesign.py, coatanalysis.py): stack formulas, the admittance diagram, phase and
colour targets, and reverse engineering of measured spectra.

Independent references:
* formula: quarter waves d = lambda0 / (4 n); (HL)^N H reflects R = ((1 - Y) / (1 + Y))^2, Y = (nH / nL)^(2N) nH^2 / ns;
* admittance: a lossless layer traces a circle centred on the real axis (through Y0 and eta^2 / Y0 when Y0 is real);
  a quarter wave ends at n^2 / ns, a half wave where it started; the end point gives the matrix R; a point of an
  iso-reflectance circle reflects exactly that R;
* GD of a vacuum gap in transmission: d / c; designer GD/GDD equal coatanalysis.phase (a separate implementation);
* retardance of a bare interface: 0 below and 180 deg above Brewster's angle; in total internal reflection
  2 atan(cos(theta) sqrt(sin^2(theta) - n^2) / sin^2(theta)) - 180 deg (Macleod's p sign);
* colour of a flat reflectance R: Rv = R, L* = 116 R^(1/3) - 16, a* = b* = 0;
* reverse engineering: synthetic measurements of a design with known thickness errors are fitted back exactly
  (noise-free), and within the reported uncertainty with noise.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.coatanalysis import Stack, _const, admittance_locus, phase, spectrum as aspectrum, stack_from_design
from opticore.coatdesign import (
    CoatingDesign, DesignError, Measurement, Merit, Resolver, design_from_builtin, evaluate_design, fit_measurement,
    optimize_design, parse_formula, spectrum, to_formula,
)
from opticore.thinfilm import COATINGS

c = _const
client = TestClient(app)


def _hl(ns=1.52, lam0=550.0, targets=()):
    return CoatingDesign(palette=[{"key": "H", "index": 2.35}, {"key": "L", "index": 1.46}], substrate_index=ns, design_wavelength_nm=lam0, targets=list(targets))


# ------------------------------------------------------------------------------------------------------------- formula
def test_formula_quarter_waves_and_the_hr_reflectance():
    d = _hl()
    L = parse_formula("Air | (HL)^7 H | Glass", d)
    assert [x.material for x in L] == ["H", "L"] * 7 + ["H"]
    assert L[0].thickness_nm == pytest.approx(550 / (4 * 2.35), rel=1e-15) and L[1].thickness_nm == pytest.approx(550 / (4 * 1.46), rel=1e-15)
    explicit = parse_formula(" ".join(["H", "L"] * 7 + ["H"]), d)
    assert [x.thickness_nm for x in explicit] == [x.thickness_nm for x in L]
    R = spectrum(d.model_copy(update={"layers": L}), Resolver(d), np.array([550.0]))["R"][0]
    Y = (2.35 / 1.46) ** 14 * 2.35**2 / 1.52
    assert R == pytest.approx(((1 - Y) / (1 + Y)) ** 2, abs=1e-14)


def test_formula_multipliers_groups_and_errors():
    d = _hl()
    t = lambda f: [(x.material, round(x.thickness_nm, 9)) for x in parse_formula(f, d)]  # noqa: E731
    assert t("2(HL)") == t("2H 2L") == t("2*H 2 L")
    assert t("((HL)^2 L)^2") == t("H L H L L H L H L L")
    assert t("0.5H L 0.5H") == t("0.5*H L .5H")
    assert t("1.1(0.5L H 0.5L)^3") == t(" ".join(["0.55L 1.1H 0.55L"] * 3))
    for bad, msg in (("(HL", "missing"), ("HL)", "unmatched"), ("H^0", "whole number"), ("X", "palette key"), ("", "no layers"), ("2", "without a layer")):
        with pytest.raises(DesignError, match=msg):
            parse_formula(bad, d)


@pytest.mark.parametrize("name", sorted(COATINGS))
def test_formula_round_trip_of_every_built_in(name):
    """to_formula writes 4 significant figures of the quarter-wave multiples: parsing it back reproduces the layers to
    5e-4 (exactly for quarter-wave designs)."""
    d = design_from_builtin(COATINGS[name])
    f = to_formula(d)
    back = parse_formula(f, d)
    assert [x.material for x in back] == [x.material for x in d.layers]
    rel = max(abs(a.thickness_nm / b.thickness_nm - 1) for a, b in zip(back, d.layers))
    assert rel < 5e-4, (name, f)
    if name.startswith("HR_") and not name.endswith("45"):
        assert f.startswith("(HL)^") and rel < 1e-12


# ----------------------------------------------------------------------------------------------------------- admittance
def test_admittance_of_quarter_and_half_waves():
    ns, n = 1.52, 1.38
    q = Stack([(c(n), 550 / (4 * n), "QW")], c(1.0), c(ns))
    a = admittance_locus(q, 550.0)
    re, im = np.array(a["arcs"][0]["re"]), np.array(a["arcs"][0]["im"])
    assert a["substrate"] == pytest.approx([ns, 0.0]) and a["end"][0] == pytest.approx(n * n / ns, rel=1e-12) and abs(a["end"][1]) < 1e-12
    centre = 0.5 * (ns + n * n / ns)
    assert np.allclose(np.hypot(re - centre, im), 0.5 * abs(ns - n * n / ns), atol=1e-12)  # a circle on the real axis
    assert a["R"] == pytest.approx(((1 - n * n / ns) / (1 + n * n / ns)) ** 2, rel=1e-12)
    h = admittance_locus(Stack([(c(2.1), 550 / (2 * 2.1), "HW")], c(1.0), c(ns)), 550.0)
    assert h["end"] == pytest.approx([ns, 0.0], abs=1e-12)  # an absentee layer


@pytest.mark.parametrize("pol", ["s", "p"])
def test_admittance_end_point_gives_the_matrix_reflectance(pol):
    st = Stack([(c(2.1), 80.0, "a"), (c(complex(3.0, -0.4)), 25.0, "absorbing"), (c(1.46), 140.0, "b")], c(1.0), c(1.52))
    a = admittance_locus(st, 600.0, 35.0, pol)
    s = aspectrum(st, np.array([600.0]), 35.0)
    assert a["R"] == pytest.approx(s["R" + pol][0], abs=1e-12)
    for circ in a["iso_R"]:  # a point on an iso-reflectance circle reflects exactly that R
        Y = circ["centre"] + circ["radius"] * np.exp(1j * 0.7)
        e0 = a["eta0"][0]
        assert abs((e0 - Y) / (e0 + Y)) ** 2 == pytest.approx(circ["R"], rel=1e-12)


# --------------------------------------------------------------------------------------------------------- phase targets
def _merit_value(design, i=0):
    return Merit(design, Resolver(design))._values([(L.material, L.thickness_nm) for L in design.layers])[i]


def _with(design, *targets):
    return CoatingDesign.model_validate({**design.model_dump(), "targets": list(targets)})


def test_group_delay_target_of_a_vacuum_gap_and_against_the_analysis_code():
    gap = CoatingDesign(palette=[{"key": "G", "index": 1.0}], layers=[{"material": "G", "thickness_nm": 3000.0}], substrate_index=1.0,
                        targets=[{"quantity": "GD", "of": "T", "lambda_min_nm": 500, "lambda_max_nm": 600, "value": 0.0, "points": 21}])
    assert np.allclose(_merit_value(gap), 3000.0 / 299.792458, rtol=1e-12)
    d = design_from_builtin(COATINGS["DM_800"])
    lam = np.linspace(770, 830, 31)
    ref = phase(stack_from_design(d, Resolver(d)), lam)
    for q, key in (("GD", "gd_r"), ("GDD", "gdd_r")):
        t = {"quantity": q, "of": "R", "lambda_min_nm": 770, "lambda_max_nm": 830, "value": 0.0, "points": 31}
        v = _merit_value(_with(d, t))
        assert np.allclose(v, 0.5 * (ref[key + "s"] + ref[key + "p"]), rtol=1e-9, atol=1e-5), q  # stencil round-off ~1e-6 fs²


def test_retardance_target_of_a_bare_interface_and_in_total_internal_reflection():
    def ret(design, angle):
        t = {"quantity": "retardance", "of": "R", "angle_deg": angle, "lambda_min_nm": 550, "lambda_max_nm": 550, "value": 0.0, "points": 1}
        return float(_merit_value(_with(design, t))[0])

    glass = CoatingDesign(palette=[{"key": "L", "index": 1.46}], substrate_index=1.5)
    assert abs(ret(glass, 30.0)) < 1e-9 and abs(abs(ret(glass, 60.0)) - 180.0) < 1e-9
    tir = CoatingDesign(palette=[{"key": "L", "index": 1.46}], incident_index=1.5, substrate_index=1.0)
    n = 1 / 1.5
    for th in (50.0, 60.0, 70.0):
        s2 = math.sin(math.radians(th)) ** 2
        want = 2 * math.degrees(math.atan(math.cos(math.radians(th)) * math.sqrt(s2 - n * n) / s2)) - 180.0
        assert ret(tir, th) == pytest.approx(want, abs=1e-9)


def test_colour_targets_of_a_flat_reflectance():
    d = CoatingDesign(palette=[{"key": "L", "index": 1.46}], substrate_index=1.5)
    R = 0.04
    vals = {}
    for q, of in (("Rv", "R"), ("Tv", "R"), ("L*", "R"), ("a*", "R"), ("b*", "R")):
        t = {"quantity": q, "of": of, "lambda_min_nm": 380, "lambda_max_nm": 780, "value": 0.0, "points": 1}
        vals[q] = float(_merit_value(_with(d, t))[0])
    assert vals["Rv"] == pytest.approx(R, abs=1e-12) and vals["Tv"] == pytest.approx(1 - R, abs=1e-12)
    assert vals["L*"] == pytest.approx(116 * R ** (1 / 3) - 16, abs=1e-9) and abs(vals["a*"]) < 1e-6 and abs(vals["b*"]) < 1e-6


def test_target_validation():
    with pytest.raises(ValueError, match="fractions"):
        CoatingDesign(palette=[{"key": "H"}], targets=[{"quantity": "R", "lambda_min_nm": 500, "lambda_max_nm": 600, "value": 1.5}])
    # GD and GDD come from a local stencil: a single wavelength is a valid target
    CoatingDesign(palette=[{"key": "H"}], targets=[{"quantity": "GDD", "lambda_min_nm": 800, "lambda_max_nm": 800, "value": -50, "points": 1}])
    mirror = CoatingDesign(palette=[{"key": "H"}], layers=[{"material": "H", "thickness_nm": 50}], substrate_index=0.1, substrate_extinction=3.0,
                           targets=[{"quantity": "GD", "of": "T", "lambda_min_nm": 500, "lambda_max_nm": 600, "value": 0, "points": 9}])
    with pytest.raises(DesignError, match="opaque"):
        Merit(mirror, Resolver(mirror))


def test_a_dispersive_mirror_is_optimised_to_its_gdd_target():
    """Library example: from a linearly chirped quarter-wave stack the designer meets R >= 99 % and GDD -40 +- 15 fs²
    (the built-in DM_800 is this design, checked in test_builtin_coatings.py)."""
    n, lam0 = 24, 800.0
    layers = [{"material": "H" if i % 2 == 0 else "L", "thickness_nm": (1 + 0.12 * (0.5 - i / (n - 1))) * lam0 / (4 * (2.35 if i % 2 == 0 else 1.46))} for i in range(n)]
    spec = [{"quantity": "R", "lambda_min_nm": 760, "lambda_max_nm": 840, "value": 0.99, "kind": ">=", "points": 41},
            {"quantity": "GDD", "of": "R", "lambda_min_nm": 770, "lambda_max_nm": 830, "value": -40.0, "tolerance": 15.0, "points": 31}]
    d = _hl(lam0=lam0, targets=spec).model_copy(update={"layers": CoatingDesign.model_validate({"palette": [{"key": "H"}, {"key": "L"}], "layers": layers}).layers})
    start = evaluate_design(d)
    assert not start["targets"][1]["met"]
    r = optimize_design(d, method="refine", time_limit_s=60)
    ev = evaluate_design(CoatingDesign.model_validate(r["design"]))
    assert all(t["met"] for t in ev["targets"]) and ev["targets"][1]["units"] == "fs²"
    assert -55.01 <= min(ev["targets"][1]["value"]) and max(ev["targets"][1]["value"]) <= -24.99  # the band, to MET_TOL x 1000 fs²


# ---------------------------------------------------------------------------------------------------- reverse engineering
def _synthetic(design, errors, angle=0.0, quantity="R", noise=0.0, seed=3):
    built = design.model_copy(update={"layers": [L.model_copy(update={"thickness_nm": L.thickness_nm * (1 + e)}) for L, e in zip(design.layers, errors)]})
    lam = np.linspace(400, 800, 161)
    v = spectrum(built, Resolver(built), lam, angle)[quantity]
    if noise:
        v = v + np.random.default_rng(seed).normal(0.0, noise, len(v))
    return Measurement(quantity=quantity, angle_deg=angle, lambda_nm=lam.tolist(), value=v.tolist())


def test_fit_recovers_known_thickness_errors():
    d = design_from_builtin(COATINGS["BBAR_VIS"])
    errors = [0.03, -0.02, 0.015, -0.01, 0.025, -0.005]
    meas = [_synthetic(d, errors, 0.0, "R"), _synthetic(d, errors, 45.0, "R"), _synthetic(d, errors, 0.0, "T")]
    r = fit_measurement(d, meas, mode="layers")
    assert np.allclose(r["layer_errors"], errors, atol=1e-6), r["layer_errors"]
    assert r["rms_after"] < 1e-8 < r["rms_before"]
    fitted = CoatingDesign.model_validate(r["fitted_design"])
    assert fitted.layers[0].thickness_nm == pytest.approx(d.layers[0].thickness_nm * 1.03, rel=1e-6)


def test_fit_of_a_uniform_rate_error_and_its_uncertainty():
    d = design_from_builtin(COATINGS["LP_550"])
    meas = _synthetic(d, [0.025] * len(d.layers), quantity="T")
    r = fit_measurement(d, [meas], mode="scale")
    assert r["variables"][0]["name"] == "scale" and r["variables"][0]["error"] == pytest.approx(0.025, abs=1e-7)
    noisy = _synthetic(d, [0.025] * len(d.layers), quantity="T", noise=2e-3)
    r = fit_measurement(d, [noisy], mode="scale")
    v = r["variables"][0]
    assert 0 < v["sigma"] < 1e-3 and abs(v["error"] - 0.025) < 4 * v["sigma"]
    assert r["rms_after"] == pytest.approx(2e-3, rel=0.2)  # the residual is the noise


def test_fit_validation():
    d = design_from_builtin(COATINGS["MGF2_QW550"])
    with pytest.raises(ValueError, match="fractions"):
        Measurement(quantity="R", lambda_nm=[500, 550, 600], value=[1, 2, 3])
    with pytest.raises(DesignError, match="cannot determine"):
        fit_measurement(d.model_copy(update={"layers": d.layers * 3}), [Measurement(quantity="R", lambda_nm=[500, 550, 600], value=[0.01, 0.01, 0.01])], mode="layers")


# -------------------------------------------------------------------------------------------------------------------- API
def test_formula_fit_and_admittance_endpoints():
    d = design_from_builtin(COATINGS["HR_1064"]).model_dump()
    r = client.post("/api/v1/coating-design/formula", json={"design": d, "formula": "(HL)^5 H"})
    assert r.status_code == 200 and r.json()["layer_count"] == 11 and r.json()["formula"] == "(HL)^5 H"
    r = client.post("/api/v1/coating-design/formula", json={"design": d, "formula": "(HQ)^5"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "COATING_DESIGN_ERROR"
    ev = client.post("/api/v1/coating-design/evaluate", json={"design": d}).json()
    assert ev["formula"] == "(HL)^12 H"
    bb = design_from_builtin(COATINGS["BBAR_VIS"])
    m = _synthetic(bb, [0.02] * 6)
    r = client.post("/api/v1/coating-design/fit", json={"design": bb.model_dump(), "measurements": [m.model_dump()], "mode": "scale"})
    assert r.status_code == 200 and r.json()["variables"][0]["error"] == pytest.approx(0.02, abs=1e-6)
    a = client.post("/api/v1/coating-design/analyze", json={"design": d, "lambda_min_nm": 1000, "lambda_max_nm": 1120, "angle_deg": 0, "angles_deg": [], "reference_nm": 1064, "band_nm": None, "field_pol": "s"}).json()
    assert a["admittance"]["s"]["R"] == pytest.approx(a["at_reference"]["R"], abs=1e-9)


# --------------------------------------------------------------------------------------------- back side and substrate
BK7 = [1.03961212, 0.00600069867, 0.231792344, 0.0200179144, 1.01046945, 103.560653]


def _bk7_n_ng(lam_um):
    """N-BK7 index and group index n - lambda dn/dlambda from its Sellmeier formula, differentiated analytically."""
    L2 = lam_um * lam_um
    n2 = 1 + sum(B * L2 / (L2 - C) for B, C in zip(BK7[0::2], BK7[1::2]))
    n = math.sqrt(n2)
    dn = sum(-B * lam_um * C / (L2 - C) ** 2 for B, C in zip(BK7[0::2], BK7[1::2])) / n  # dn/dlambda
    return n, n - lam_um * dn


def test_absorbing_plate_with_a_bare_back_face():
    """A plate of index n - ik and thickness d at normal incidence: Ti = exp(-4 pi k d / lambda), T = (1 - R)^2 Ti /
    (1 - R^2 Ti^2), R_total = R + (1 - R)^2 R Ti^2 / (1 - R^2 Ti^2) with R = ((n - 1) / (n + 1))^2."""
    n, k, d_mm = 1.5, 2e-6, 3.0
    d = CoatingDesign(palette=[{"key": "L", "index": 1.46}], layers=[], substrate_index=n, substrate_extinction=k, back_side="uncoated", substrate_thickness_mm=d_mm)
    lam = np.array([400.0, 550.0, 800.0])
    sp = spectrum(d, Resolver(d), lam)
    R = ((n - 1) / (n + 1)) ** 2
    Ti = np.exp(-4 * np.pi * k * d_mm * 1e6 / lam)
    assert np.allclose(sp["T"], (1 - R) ** 2 * Ti / (1 - R**2 * Ti**2), rtol=1e-9)
    assert np.allclose(sp["R"], R + (1 - R) ** 2 * R * Ti**2 / (1 - R**2 * Ti**2), rtol=1e-9)
    assert np.all(sp["A"] > 0)


def test_the_same_coating_on_both_faces():
    """A lossless coating of single-face reflectance R1 on both faces of a lossless plate: T = (1 - R1) / (1 + R1)."""
    co = design_from_builtin(COATINGS["VCOAT_1064"])
    lam = np.linspace(900, 1200, 7)
    one = spectrum(co, Resolver(co), lam)
    both = co.model_copy(update={"back_side": "coated", "back_layers": list(co.layers)})
    two = spectrum(both, Resolver(both), lam)
    R1 = one["R"]
    assert np.allclose(two["T"], (1 - R1) / (1 + R1), rtol=1e-6)  # the films' k (< 1e-5) is the only loss


def test_plate_designer_and_analysis_agree_with_a_back_coating_and_absorption():
    from opticore.coatanalysis import phase as aphase

    d = design_from_builtin(COATINGS["BBAR_VIS"]).model_copy(update={"substrate_thickness_mm": 2.0})
    d = d.model_copy(update={"back_side": "coated", "back_layers": list(d.layers)})
    lam = np.linspace(400, 700, 31)
    for angle in (0.0, 30.0):
        a = spectrum(d, Resolver(d), lam, angle)
        b = aspectrum(stack_from_design(d, Resolver(d)), lam, angle)
        for k in ("R", "T", "Rs", "Tp"):
            assert np.abs(a[k] - b[k]).max() < 1e-12, (k, angle)
    t = {"quantity": "GD", "of": "T", "lambda_min_nm": 400, "lambda_max_nm": 700, "value": 0.0, "points": 31}
    gd = _merit_value(_with(d, t))
    ref = aphase(stack_from_design(d, Resolver(d)), lam)
    assert np.allclose(gd, 0.5 * (ref["gd_ts"] + ref["gd_tp"]), rtol=1e-9)


def test_group_delay_through_a_glass_plate():
    """A bare 1 mm N-BK7 plate: the transmitted group delay is d n_g / c (n_g from the Sellmeier derivative), and the
    GDD d lambda^3 / (2 pi c^2) d^2n/dlambda^2 (by differences of the analytic n_g)."""
    d_mm = 1.0
    plate = CoatingDesign(palette=[{"key": "L", "index": 1.46}], layers=[], substrate="N-BK7", back_side="uncoated", substrate_thickness_mm=d_mm)
    lam = np.linspace(700, 900, 41)
    gd = _merit_value(_with(plate, {"quantity": "GD", "of": "T", "lambda_min_nm": 700, "lambda_max_nm": 900, "value": 0.0, "points": 41}))
    c = 299.792458  # nm / fs
    want = np.array([_bk7_n_ng(w * 1e-3)[1] for w in lam]) * d_mm * 1e6 / c
    assert np.allclose(gd, want, rtol=2e-6)
    gdd = _merit_value(_with(plate, {"quantity": "GDD", "of": "T", "lambda_min_nm": 700, "lambda_max_nm": 900, "value": 0.0, "points": 41}))
    i = 20
    h = 1e-3  # um
    ng = lambda x: _bk7_n_ng(x)[1]  # noqa: E731
    lam_um = lam[i] * 1e-3
    # GDD = dGD/domega = -(lambda^2 / (2 pi c)) dGD/dlambda
    dgd_dlam = (ng(lam_um + h) - ng(lam_um - h)) / (2 * h) * d_mm * 1e6 / c / 1e3  # fs per nm
    assert gdd[i] == pytest.approx(-(lam[i] ** 2) / (2 * np.pi * c) * dgd_dlam, rel=1e-4)


# ------------------------------------------------------------------------------------------------- index fitting
def _truth(d, scale=0.0, dA=None, dB=None, k=None, dns=0.0):
    pal = []
    for p in d.palette:
        pal.append(p.model_copy(update={"index_offset": (dA or {}).get(p.key, 0.0), "index_offset_b": (dB or {}).get(p.key, 0.0), "extinction": p.extinction + (k or {}).get(p.key, 0.0)}))
    return d.model_copy(update={"palette": pal, "substrate_offset": dns, "layers": [L.model_copy(update={"thickness_nm": L.thickness_nm * (1 + scale)}) for L in d.layers]})


def _measure(t, specs):
    lam = np.linspace(400, 800, 161)
    return [Measurement(quantity=q, angle_deg=a, lambda_nm=lam.tolist(), value=spectrum(t, Resolver(t), lam, a)[q].tolist()) for q, a in specs]


def test_fit_recovers_film_index_dispersion_and_thickness_together():
    d = design_from_builtin(COATINGS["BBAR_VIS"])
    keys = {p.key for p in d.palette}
    hi = max(d.palette, key=lambda p: Resolver(d).N(p.key, np.array([550.0]))[0].real).key
    lo = (keys - {hi}).pop()
    t = _truth(d, 0.015, {hi: 0.02, lo: -0.01}, {hi: 0.004})
    r = fit_measurement(d, _measure(t, (("R", 0.0), ("T", 0.0), ("R", 45.0), ("T", 45.0))), mode="scale", fit_index=True, fit_dispersion=True)
    v = {x["name"]: x["error"] for x in r["variables"]}
    assert v["scale"] == pytest.approx(0.015, abs=1e-8)
    assert v[f"{hi}: Δn"] == pytest.approx(0.02, abs=1e-8) and v[f"{lo}: Δn"] == pytest.approx(-0.01, abs=1e-8)
    assert v[f"{hi}: ΔB"] == pytest.approx(0.004, abs=1e-8) and abs(v[f"{lo}: ΔB"]) < 1e-8
    fitted = CoatingDesign.model_validate(r["fitted_design"])
    assert {p.key: p.index_offset for p in fitted.palette}[hi] == pytest.approx(0.02, abs=1e-8)
    assert r["rms_after"] < 1e-9


def test_fit_of_absorption_and_of_the_substrate_index():
    d = design_from_builtin(COATINGS["BBAR_VIS"])
    key = d.palette[0].key
    t = _truth(d, k={key: 0.003}, dns=0.012)
    r = fit_measurement(d, _measure(t, (("R", 0.0), ("T", 0.0), ("R", 50.0))), mode="none", fit_absorption=True, fit_substrate=True)
    v = {x["name"]: x["error"] for x in r["variables"]}
    # the k of the two films trade against each other (both only lower R + T): recovered to 1e-5, and reported
    assert v[f"{key}: k"] == pytest.approx(0.003, abs=1e-5) and v["substrate: Δn"] == pytest.approx(0.012, abs=1e-5)
    assert any("correlated" in w for w in r["warnings"]) or all(abs(x["error"]) < 1e-5 for x in r["variables"] if x["kind"] == "k" and not x["name"].startswith(key))


def test_an_edge_filter_fit_of_thickness_index_and_dispersion():
    """33 layers: a 1 % rate error with a TiO2 index and dispersion error is recovered from R and T at two angles. (The
    fit is local: much larger combined errors can end in another minimum, which its RMS shows; fit in steps then.)"""
    d = design_from_builtin(COATINGS["LP_550"])
    t = _truth(d, 0.01, {"H": 0.01}, {"H": 0.002})
    r = fit_measurement(d, _measure(t, (("R", 0.0), ("T", 0.0), ("R", 45.0), ("T", 45.0))), mode="scale", fit_index=True, fit_dispersion=True)
    v = {x["name"]: x["error"] for x in r["variables"]}
    assert v["scale"] == pytest.approx(0.01, abs=1e-7) and v["H: Δn"] == pytest.approx(0.01, abs=1e-7) and v["H: ΔB"] == pytest.approx(0.002, abs=1e-7)
    assert abs(v["L: Δn"]) < 1e-7 and r["rms_after"] < 1e-9


def test_global_search_recovers_a_hard_edge_filter_fit():
    """33 layers with a 1.5 % rate error and TiO2 / SiO2 index and dispersion errors (a case the local fit can miss,
    depending on the data): Sobol sampling with least squares from the best samples recovers every parameter."""
    d = design_from_builtin(COATINGS["LP_550"])
    t = _truth(d, 0.015, {"H": 0.02, "L": -0.01}, {"H": 0.004})
    lam = np.linspace(400, 800, 81)
    meas = [Measurement(quantity=q, angle_deg=a, lambda_nm=lam.tolist(), value=spectrum(t, Resolver(t), lam, a)[q].tolist()) for q, a in (("R", 0.0), ("T", 0.0), ("R", 45.0), ("T", 45.0))]
    r = fit_measurement(d, meas, mode="scale", fit_index=True, fit_dispersion=True, search="global", max_error=0.05, index_range=0.05, time_limit_s=120)
    v = {x["name"]: x["error"] for x in r["variables"]}
    assert r["rms_after"] < 1e-9 and v["scale"] == pytest.approx(0.015, abs=1e-7)
    assert v["H: Δn"] == pytest.approx(0.02, abs=1e-7) and v["L: Δn"] == pytest.approx(-0.01, abs=1e-7) and v["H: ΔB"] == pytest.approx(0.004, abs=1e-7)


@pytest.mark.parametrize("illuminant,observer", [("D65", "2"), ("A", "2"), ("F11", "10"), ("D50", "10")])
def test_colour_targets_under_any_illuminant_and_observer(illuminant, observer):
    """A flat reflectance R has the illuminant's own chromaticity: a* = b* = 0 and L* = 116 R^(1/3) - 16 whatever the
    illuminant and observer; a coloured coating's a*, b* equal the analysis module's for the same setting."""
    from opticore.coatanalysis import colour

    flat = CoatingDesign(palette=[{"key": "L", "index": 1.46}], substrate_index=1.5)
    for q in ("a*", "b*", "L*"):
        t = {"quantity": q, "of": "R", "lambda_min_nm": 380, "lambda_max_nm": 780, "value": 0.0, "points": 1, "illuminant": illuminant, "observer": observer}
        v = float(_merit_value(_with(flat, t))[0])
        assert v == pytest.approx(116 * 0.04 ** (1 / 3) - 16 if q == "L*" else 0.0, abs=1e-9), q
    d = design_from_builtin(COATINGS["BBAR_VIS"])
    ref = colour(stack_from_design(d, Resolver(d)), 0.0, illuminant, observer)["R"]
    for q in ("a*", "b*"):
        t = {"quantity": q, "of": "R", "lambda_min_nm": 380, "lambda_max_nm": 780, "value": 0.0, "points": 1, "illuminant": illuminant, "observer": observer}
        assert float(_merit_value(_with(d, t))[0]) == pytest.approx(ref[q[0]], abs=1e-9)


def test_colour_depends_on_the_illuminant():
    from opticore.coatanalysis import colour

    d = design_from_builtin(COATINGS["BBAR_VIS"])
    st = stack_from_design(d, Resolver(d))
    a, b = colour(st, 0.0, "D65", "2")["R"], colour(st, 0.0, "A", "2")["R"]
    assert abs(a["x"] - b["x"]) > 0.01 and colour(st, 0.0, "A", "2")["illuminant"] == "A"


def test_field_map_rows_are_the_field_profiles():
    from opticore.coatanalysis import field_map, field_profile

    d = design_from_builtin(COATINGS["HR_1064"])
    st = stack_from_design(d, Resolver(d))
    m = field_map(st, 1000.0, 1120.0, 0.0, "s", wavelengths=13, depth_points=300)
    z = np.asarray(m["z_nm"])
    for i in (0, 6, 12):
        lam = m["wavelength_nm"][i]
        f = field_profile(st, lam, 0.0, "s", points_per_layer=60, outside_nm=-z[0])
        assert np.allclose(m["e2"][i], np.interp(z, f["z_nm"], f["e2"]), atol=1e-12)
    assert m["boundaries_nm"][-1] == pytest.approx(sum(L.thickness_nm for L in d.layers), rel=1e-12)


def test_gdd_at_a_single_wavelength():
    """A one-point GDD target (the stencil needs no grid) equals the analysis module at that wavelength."""
    from opticore.coatanalysis import phase as aphase

    d = design_from_builtin(COATINGS["DM_800"])
    t = {"quantity": "GDD", "of": "R", "lambda_min_nm": 800, "lambda_max_nm": 800, "value": 0.0, "points": 1}
    v = float(_merit_value(_with(d, t))[0])
    ref = aphase(stack_from_design(d, Resolver(d)), np.array([800.0]))
    assert v == pytest.approx(0.5 * (ref["gdd_rs"][0] + ref["gdd_rp"][0]), abs=1e-5) and -55 < v < -25


# ------------------------------------------------------------------------------------------------- optimisation engine
def _ar_start(band=(400.0, 700.0)):
    pal = [{"key": "H", "material": "TIO2_FILM"}, {"key": "L", "material": "SIO2_FILM"}, {"key": "M", "material": "MGF2_FILM"}]
    from opticore.coatdesign import template

    t = template(CoatingDesign(palette=pal, substrate="N-BK7", design_wavelength_nm=550), "ar_broadband", high="H", low="L", lambda0_nm=550, band_min_nm=band[0], band_max_nm=band[1])
    return CoatingDesign.model_validate(t["design"])


def test_batched_jacobian_rows_equal_single_evaluations():
    d = _ar_start().model_copy(update={"targets": CoatingDesign.model_validate({"palette": [{"key": "H"}], "targets": [
        {"quantity": "R", "lambda_min_nm": 400, "lambda_max_nm": 700, "value": 0.005, "kind": "<=", "points": 31},
        {"quantity": "a*", "of": "R", "lambda_min_nm": 380, "lambda_max_nm": 780, "value": 0.0, "tolerance": 1.0, "points": 1},
        {"quantity": "GDD", "of": "R", "lambda_min_nm": 500, "lambda_max_nm": 600, "value": 0.0, "points": 5}]}).targets})
    mf = Merit(d, Resolver(d))
    pairs = [(L.material, L.thickness_nm) for L in d.layers]
    free = list(range(len(pairs)))
    X = np.array([[x * f for (_, x) in pairs] for f in (1.0, 1.01, 0.97)])
    batch = mf.residuals_batch(X, pairs, free)
    for row, x in zip(batch, X):
        single = mf.residuals([(k, float(v)) for (k, _), v in zip(pairs, x)])
        assert np.allclose(row, single, rtol=1e-12, atol=1e-15)


def test_needle_optimisation_of_a_broadband_ar_from_measured_films():
    """Library example of the needle method: R <= 0.5 % over 400-700 nm on N-BK7 from the four-layer start, with the
    TiO2, SiO2 and MgF2 films; met within seconds by refinement, needles and (if needed) new layer pairs."""
    d = _ar_start().model_copy(update={"targets": CoatingDesign.model_validate({"palette": [{"key": "H"}], "targets": [
        {"quantity": "R", "lambda_min_nm": 400, "lambda_max_nm": 700, "value": 0.005, "kind": "<=", "points": 61}]}).targets})
    assert not evaluate_design(d)["targets"][0]["met"]
    r = optimize_design(d, method="needle", time_limit_s=60)
    out = CoatingDesign.model_validate(r["design"])
    ev = evaluate_design(out)
    assert ev["targets"][0]["met"] and len(out.layers) > len(d.layers) and r["elapsed_s"] < 30
    assert all(L.thickness_nm >= 1.0 for L in out.layers)


def test_back_face_linked_to_the_front():
    """back_same_as_front: the back face carries the front layers (the same spectrum as an explicit copy), and the
    optimiser shapes both faces together: a plate AR with T >= 99 % over 450-650 nm through 2 mm of N-BK7."""
    d = _ar_start((450.0, 650.0))
    linked = d.model_copy(update={"back_side": "coated", "back_same_as_front": True, "substrate_thickness_mm": 2.0})
    copied = d.model_copy(update={"back_side": "coated", "back_layers": list(d.layers), "substrate_thickness_mm": 2.0})
    lam = np.linspace(450, 650, 21)
    assert np.allclose(spectrum(linked, Resolver(linked), lam)["T"], spectrum(copied, Resolver(copied), lam)["T"], atol=1e-15)
    target = CoatingDesign.model_validate({"palette": [{"key": "H"}], "targets": [{"quantity": "T", "lambda_min_nm": 450, "lambda_max_nm": 650, "value": 0.99, "kind": ">=", "points": 41}]}).targets
    r = optimize_design(linked.model_copy(update={"targets": target}), method="needle", time_limit_s=30)
    out = CoatingDesign.model_validate(r["design"])
    assert out.back_same_as_front and evaluate_design(out)["targets"][0]["met"]
