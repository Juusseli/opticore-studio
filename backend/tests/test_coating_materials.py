"""Coating materials with n and k (materials/data/coating_materials.json, tools/coating_materials.py).

Independent references:
* the converter against hand-written refractiveindex.info pages: Sellmeier formulas 1 and 2, the Cauchy formula 5,
  tabulated n, k and nk evaluated at their own nodes;
* the thinned tables reproduce every original point (checked when the file is generated; here on a synthetic table);
* bare metals: normal-incidence R = ((n - 1)^2 + k^2) / ((n + 1)^2 + k^2) gives the well-known reflectances (Ag and Al
  above 90 % in the visible, Au above 95 % in the near infrared, Au below 50 % at 450 nm);
* a metal cannot be a lens medium; a library metal substrate makes a coating design opaque and reflects like the bare
  metal.
"""

from __future__ import annotations

import json
from importlib import resources

import numpy as np
import pytest

from opticore.coatdesign import CoatingDesign, DesignError, Resolver, spectrum
from opticore.materials import MaterialError, MaterialLibrary
from opticore.materials.catalog import _material_from_record
from opticore.tools.coating_materials import TOL_N, convert, thin_table

LIB = MaterialLibrary()


def _R(N):
    return ((N.real - 1) ** 2 + N.imag**2) / ((N.real + 1) ** 2 + N.imag**2)


def test_converter_formulas_and_tables():
    f1 = "DATA:\n  - type: formula 1\n    wavelength_range: 0.31 5.5\n    coefficients: 0 3.0249 0.1353406 40314 1239.842\n"
    r = convert(f1, "x")
    m = _material_from_record({"name": "A", **r}, builtin=False)
    L = 0.6
    assert m.index(L) == pytest.approx(np.sqrt(1 + 3.0249 * L**2 / (L**2 - 0.1353406**2) + 40314 * L**2 / (L**2 - 1239.842**2)), rel=1e-14)
    f2 = "DATA:\n  - type: formula 2\n    wavelength_range: 0.4 14\n    coefficients: 0.01 3.6 0.0234 2.2 1148\n  - type: tabulated k\n    data: |\n        0.4 0.002\n        1.0 0.0001\n"
    m = _material_from_record({"name": "B", **convert(f2, "x")}, builtin=False)
    assert m.index(L) == pytest.approx(np.sqrt(1 + 0.01 + 3.6 * L**2 / (L**2 - 0.0234) + 2.2 * L**2 / (L**2 - 1148)), rel=1e-14)
    assert m.k(0.4) == pytest.approx(0.002) and m.k(1.0) == pytest.approx(0.0001) and m.k(5.0) == pytest.approx(0.0001)  # end value held
    f5 = "DATA:\n  - type: formula 5\n    wavelength_range: 0.2 2.0\n    coefficients: 1.875 6.28e-3 -2 5.80e-4 -4\n"
    m = _material_from_record({"name": "C", **convert(f5, "x")}, builtin=False)
    assert m.index(0.5) == pytest.approx(1.875 + 6.28e-3 / 0.25 + 5.8e-4 / 0.0625, rel=1e-14)
    tab = "DATA:\n  - type: tabulated nk\n    data: |\n        0.4 0.05 2.0\n        0.5 0.05 3.0\n        0.6 0.06 4.0\n"
    m = _material_from_record({"name": "D", **convert(tab, "x")}, builtin=False)
    for w, n, k in ((0.4, 0.05, 2.0), (0.5, 0.05, 3.0), (0.6, 0.06, 4.0)):
        assert m.complex_index(w) == pytest.approx(complex(n, -k), abs=1e-14)
    with pytest.raises(ValueError, match="not a Cauchy"):
        convert("DATA:\n  - type: formula 5\n    wavelength_range: 0.2 2\n    coefficients: 1.8 0.01 -1\n", "x")


def test_thinning_keeps_every_point_within_tolerance():
    lam = np.geomspace(0.2, 20.0, 2000)
    n = 1.5 + 0.004 / lam**2 + 0.02 * np.exp(-((lam - 9.0) / 0.4) ** 2)
    k = 1e-3 * np.exp(-((lam - 9.0) / 0.3) ** 2)
    rec = {"formula": "tabulated", "table": np.column_stack([lam, n]).tolist(), "extinction_table": np.column_stack([lam, k]).tolist()}
    dev = thin_table(rec)
    assert len(rec["table"]) < 600 and dev < 5 * TOL_N
    m = _material_from_record({"name": "T", **rec}, builtin=False)
    assert np.abs(m.dispersion.index(lam) - n).max() < 5 * TOL_N and np.abs(m.k(lam) - k).max() < 5 * TOL_N


def test_shipped_coating_materials():
    data = json.loads(resources.files("opticore.materials").joinpath("data/coating_materials.json").read_text("utf-8"))
    assert "CC0" in data["notes"]
    names = {m["name"] for m in data["materials"]}
    assert {"SIO2_FILM", "TIO2_FILM", "TA2O5_FILM", "NB2O5_FILM", "HFO2_FILM", "AL2O3_FILM", "MGF2_FILM", "ZNS_FILM", "SI3N4_FILM", "AG", "AG_LD", "AU", "CU", "CR", "AL"} <= names
    for m in data["materials"]:
        assert "refractiveindex.info" in m["source"] and m["category"] in ("film", "metal")
    # typical film indices at 550 nm
    for name, lo, hi in (("SIO2_FILM", 1.44, 1.49), ("TIO2_FILM", 2.2, 2.5), ("TA2O5_FILM", 2.05, 2.2), ("MGF2_FILM", 1.37, 1.40), ("AL2O3_FILM", 1.6, 1.7), ("HFO2_FILM", 1.9, 2.15), ("NB2O5_FILM", 2.2, 2.4)):
        N = LIB.complex_index(name, 0.55)
        assert lo < N.real < hi and -N.imag < 1e-4, name
    # bare metals at normal incidence
    assert _R(LIB.complex_index("AG", 0.55)) > 0.95 and _R(LIB.complex_index("AL", 0.55)) > 0.9
    assert _R(LIB.complex_index("AU", 1.0)) > 0.95 and _R(LIB.complex_index("AU", 0.45)) < 0.5
    assert _R(LIB.complex_index("CU", 0.45)) < 0.7 < _R(LIB.complex_index("CU", 0.8))
    assert LIB.get("AG").category == "metal" and LIB.get("TIO2_FILM").absorbing


def test_metals_are_not_lens_media():
    from opticore.samples import singlet
    from opticore.system import SystemError_, compile_system

    sysm = singlet().system
    sysm.surfaces[1].material = "AG"
    with pytest.raises(SystemError_, match="metal"):
        compile_system(sysm)


def test_a_library_metal_substrate_is_an_opaque_mirror():
    d = CoatingDesign(palette=[{"key": "L", "material": "SIO2_FILM"}], layers=[], substrate="AG")
    res = Resolver(d)
    assert res.opaque
    lam = np.array([450.0, 550.0, 700.0])
    s = spectrum(d, res, lam)
    N = np.array([LIB.complex_index("AG", w * 1e-3) for w in lam])
    assert np.allclose(s["R"], _R(N), rtol=1e-12) and np.all(s["T"] == 0.0) and np.allclose(s["A"], 1 - _R(N), rtol=1e-12)
    with pytest.raises(DesignError, match="metal"):
        Resolver(CoatingDesign(palette=[{"key": "L", "index": 1.46}], incident="AG"))


def test_record_validation():
    with pytest.raises(MaterialError):
        _material_from_record({"name": "X", "formula": "constant", "coefficients": [1.5], "extinction_table": [[0.5, -1.0]]}, builtin=False)
    m = _material_from_record({"name": "Y", "formula": "constant", "coefficients": [1.5], "extinction_table": [[0.5, 0.01]]}, builtin=False)
    assert m.k(0.3) == pytest.approx(0.01) and m.complex_index(0.7) == pytest.approx(1.5 - 0.01j)
