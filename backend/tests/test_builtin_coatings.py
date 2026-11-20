"""The built-in coating library (materials/data/builtin_coatings.json, thinfilm.COATINGS).

The coatings are made of dispersive film and metal materials with measured n and k (materials/data/
coating_materials.json) on N-BK7 unless stated. Every coating meets the specification stored with it (the coating
designer's targets), evaluated on its design substrate and incident medium by the analysis module (and, below, by
the designer: two implementations). Analytic references for the exact designs, at the design wavelength:
* quarter-wave MgF2 on n_s: R = ((n_s - n^2) / (n_s + n^2))^2 (the film's k there is below 1e-15);
* (HL)^N H quarter waves on n_s: R = ((1 - Y) / (1 + Y))^2 with Y = (nH / nL)^(2N) nH^2 / n_s for the lossless stack of
  the films' real indices, and the absorbing stack's R within its absorptance of it;
* the two-layer V-coats: zero reflectance at the design wavelength with the complex film indices;
* the MacNeille cube: its glass index n_g^2 = 2 nH^2 nL^2 / (nH^2 + nL^2) puts every H/L interface at Brewster's angle;
* metal mirrors: opaque (T < 1e-4) and R of the bare metal ((n - 1)^2 + k^2) / ((n + 1)^2 + k^2) reproduced without
  overcoats.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from opticore.coatanalysis import Stack, _const, phase, spectrum, stack_from_coating
from opticore.materials import MaterialLibrary
from opticore.thinfilm import COATINGS

c = _const
NAMES = sorted(COATINGS)
LIB = MaterialLibrary()


def _stack(co) -> Stack:
    sub = {"material": co.substrate_material} if co.substrate_material else {"index": co.substrate_index}
    return stack_from_coating(co, LIB, co.incident_index, sub)


def _N(name, lam_nm):
    return LIB.complex_index(name, lam_nm * 1e-3)


def test_the_library_is_broad():
    cats = {co.category for co in COATINGS.values()}
    assert {"Antireflection", "Mirrors", "Filters", "Beam splitters"} <= cats and len(COATINGS) >= 29
    assert all(co.spec and co.description and co.design_nm for co in COATINGS.values())
    # made of measured, dispersive film and metal materials
    mats = {L.material for co in COATINGS.values() for L in co.layers}
    assert {"TIO2_FILM", "SIO2_FILM", "TA2O5_FILM", "MGF2_FILM", "AL2O3_FILM", "AL", "AG", "AU"} <= mats
    assert all(L.material for co in COATINGS.values() for L in co.layers)


@pytest.mark.parametrize("name", NAMES)
def test_every_built_in_meets_its_specification(name):
    co = COATINGS[name]
    st = _stack(co)
    for t in co.spec:
        lo, hi = t["lambda_min_nm"], t["lambda_max_nm"]
        lam = np.linspace(lo, hi, t.get("points", 41)) if hi > lo else np.array([lo])
        pol = t.get("polarization", "avg")
        if t["quantity"] in ("GD", "GDD"):  # group delay (dispersion) by the analysis module's own phase code
            p = phase(st, lam, t.get("angle_deg", co.angle_deg))
            key = t["quantity"].lower() + "_" + t.get("of", "R").lower()
            v = 0.5 * (p[key + "s"] + p[key + "p"]) if pol == "avg" else p[key + pol]
        else:
            s = spectrum(st, lam, t.get("angle_deg", co.angle_deg))
            v = s[t["quantity"] + ("" if pol == "avg" else pol)]
        k, tol = t.get("kind", "="), t.get("tolerance", 0.0)
        if k == "<=":
            assert v.max() <= t["value"] + tol + 1e-12, (name, t)
        elif k == ">=":
            assert v.min() >= t["value"] - tol - 1e-12, (name, t)
        else:
            assert np.abs(v - t["value"]).max() <= tol + 1e-12, (name, t)


def test_analytic_quarter_wave_designs():
    co = COATINGS["MGF2_QW550"]
    n, ns = _N("MGF2_FILM", 550.0), _N("N-BK7", 550.0)
    assert abs(n.imag) < 1e-15 and co.layers[0].thickness_nm == pytest.approx(550 / (4 * n.real), rel=1e-12)
    R = spectrum(_stack(co), np.array([550.0]))["R"][0]
    assert R == pytest.approx(((ns.real - n.real**2) / (ns.real + n.real**2)) ** 2, abs=1e-14)
    for name in ("HR_532", "HR_633", "HR_1064", "HR_1550"):
        co = COATINGS[name]
        lam0 = co.design_nm
        nH, nL, ns = _N("TIO2_FILM", lam0), _N("SIO2_FILM", lam0), _N("N-BK7", lam0).real
        N = (len(co.layers) - 1) // 2
        lossless = Stack([(c(complex(_N(L.material, lam0).real)), L.thickness_nm, "") for L in co.layers], c(1.0), c(ns))
        for L in co.layers:  # exact quarter waves of the real index
            assert 4 * _N(L.material, lam0).real * L.thickness_nm / lam0 == pytest.approx(1.0, rel=1e-12)
        Y = (nH.real / nL.real) ** (2 * N) * nH.real**2 / ns
        assert spectrum(lossless, np.array([lam0]))["R"][0] == pytest.approx(((1 - Y) / (1 + Y)) ** 2, abs=1e-13), name
        s = spectrum(_stack(co), np.array([lam0]))
        assert ((1 - Y) / (1 + Y)) ** 2 - s["A"][0] - 1e-12 <= s["R"][0] <= ((1 - Y) / (1 + Y)) ** 2 + 1e-12, name
    for name in [n for n in NAMES if n.startswith("VCOAT_")]:
        co = COATINGS[name]
        assert spectrum(_stack(co), np.array([co.design_nm]))["R"][0] < 1e-18, name
        assert co.layers[0].thickness_nm * co.layers[0].index != pytest.approx(co.design_nm / 4, rel=0.05)  # not a quarter wave


def test_macneille_cube_is_at_brewster_inside():
    co = COATINGS["PBS_MACNEILLE"]
    nH, nL, ng = _N("TIO2_FILM", 550.0).real, _N("SIO2_FILM", 550.0).real, co.incident_index
    assert ng**2 == pytest.approx(2 * nH**2 * nL**2 / (nH**2 + nL**2), rel=1e-6)
    s0 = ng * math.sin(math.radians(45.0))
    tH = math.asin(s0 / nH)
    assert math.degrees(math.atan(nL / nH)) == pytest.approx(math.degrees(tH), abs=1e-4)  # Brewster at H -> L
    lam = np.linspace(460, 680, 45)
    s = spectrum(_stack(co), lam, 45.0)
    assert s["Rs"][lam.searchsorted(550)] > 0.999 and s["Tp"].min() > 0.97


def test_metal_mirrors_are_opaque_and_reduce_to_the_bare_metal():
    for name in ("AL_PROTECTED", "AL_ENHANCED", "AL_UV", "AG_PROTECTED", "AU_PROTECTED"):
        co = COATINGS[name]
        assert co.substrate is not None  # usable on mirror surfaces
        lam = np.linspace(co.spec[0]["lambda_min_nm"], co.spec[0]["lambda_max_nm"], 21)
        s = spectrum(_stack(co), lam)
        assert s["T"].max() < 1e-4, name
        metal = co.layers[-1]
        bare = Stack([(lambda x, m=metal.material: np.array([_N(m, float(w)) for w in np.atleast_1d(x)]), metal.thickness_nm, "")], c(1.0), c(1.52))
        N = np.array([_N(metal.material, float(w)) for w in lam])
        Rm = ((N.real - 1) ** 2 + N.imag**2) / ((N.real + 1) ** 2 + N.imag**2)
        assert np.allclose(spectrum(bare, lam)["R"], Rm, atol=2e-4), name  # opaque film = semi-infinite metal


@pytest.mark.parametrize("name", NAMES)
def test_built_ins_open_in_the_designer_under_their_design_conditions(name):
    """The coating designer gets the built-in with its design wavelength, incident and substrate and its
    specification as targets: the designer's own spectrum code (coatdesign) meets every target, and agrees with the
    analysis code (coatanalysis) to rounding."""
    from opticore.coatanalysis import stack_from_design
    from opticore.coatdesign import Resolver, design_from_builtin, evaluate_design

    co = COATINGS[name]
    d = design_from_builtin(co)
    assert d.design_wavelength_nm == co.design_nm and len(d.layers) == len(co.layers) and len(d.targets) == len(co.spec)
    assert (d.incident_index or 1.0) == pytest.approx(co.incident_index, abs=0)
    if co.substrate_material:
        assert d.substrate == co.substrate_material and d.substrate_index is None
    else:
        assert d.substrate_index == pytest.approx(co.substrate_index, abs=0)
    assert all(p.material for p in d.palette)
    ev = evaluate_design(d)
    assert all(t["met"] for t in ev["targets"]), [(t["max_violation"]) for t in ev["targets"]]
    lam = np.linspace(min(t["lambda_min_nm"] for t in co.spec), max(t["lambda_max_nm"] for t in co.spec), 7)
    a = spectrum(stack_from_design(d, Resolver(d)), lam, co.angle_deg)
    b = spectrum(_stack(co), lam, co.angle_deg)
    for k in ("R", "T", "Rs", "Rp"):
        assert np.abs(a[k] - b[k]).max() < 1e-12, k


def test_fixed_incident_index_of_a_design():
    """incident_index replaces the incident material: a bare glass-to-glass interface reflects ((n0 - ns) / (n0 + ns))^2
    at normal incidence and totally beyond the critical angle asin(ns / n0)."""
    from opticore.coatdesign import CoatingDesign, Resolver, spectrum as dspec

    n0, ns = 1.753835, 1.52
    d = CoatingDesign(palette=[{"key": "L", "index": 1.46}], layers=[], incident="NO_SUCH_GLASS", incident_index=n0, substrate_index=ns)
    res = Resolver(d)
    s = dspec(d, res, np.array([550.0]), 0.0)
    assert s["R"][0] == pytest.approx(((n0 - ns) / (n0 + ns)) ** 2, rel=1e-13)
    crit = math.degrees(math.asin(ns / n0))
    s = dspec(d, res, np.array([550.0]), crit + 2.0)
    assert s["R"][0] == pytest.approx(1.0, abs=1e-12) and s["T"][0] == pytest.approx(0.0, abs=1e-12)
