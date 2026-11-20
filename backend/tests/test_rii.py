"""refractiveindex.info glass data (materials/rii.py) and the general polynomial dispersion formula.

The YAML pages below are written by the test from data with independent references: the
built-in N-BK7 record (SCHOTT datasheet Sellmeier and dn/dT coefficients, nd/Vd from the
datasheet) and formula identities that hold exactly (formula 3 with the Schott exponents is the
Schott formula; a Sellmeier term with C = 0 is a constant)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.materials import MaterialLibrary, builtin_materials
from opticore.materials.dispersion import Dispersion, DispersionError
from opticore.materials.rii import glass_name, parse_rii_catalog

client = TestClient(app)
L = np.array([0.40, 0.4861327, 0.5875618, 0.6562725, 0.85, 1.55])
BK7_SELLMEIER = "0 1.03961212 0.00600069867 0.231792344 0.0200179144 1.01046945 103.560653"


def _page(data: str, props: str = "    nd: 1.5168\n    Vd: 64.17\n", cond: str = "CONDITIONS:\n    temperature: 293\n") -> str:
    return f"""# test page
REFERENCES: |
    <a href="https://example.org/x.agf">TEST Zemax catalog</a> (see <a href="https://example.org">example</a>)
DATA:
{data}{cond}PROPERTIES:
{props}"""


def _one(text: str, path: str = "specs/test/optical/G1.yml"):
    cat = parse_rii_catalog([(path, text)], "TEST")
    return cat, (cat.records[0] if cat.records else None)


def test_polynomial_formula_matches_schott_form():
    # Schott: n^2 = A0 + A1 L^2 + A2 L^-2 + A3 L^-4 + A4 L^-6 + A5 L^-8
    A = [2.2718929, -1.0108077e-2, 1.0592509e-2, 2.0816965e-4, -7.6472538e-6, 4.9240991e-7]
    poly = Dispersion("polynomial", [A[0], A[1], 2, A[2], -2, A[3], -4, A[4], -6, A[5], -8])
    np.testing.assert_allclose(poly.index(L), Dispersion("schott", A).index(L), rtol=0, atol=1e-14)
    assert Dispersion("polynomial", [2.25]).index(0.5) == pytest.approx(1.5, abs=1e-15)
    with pytest.raises(DispersionError):
        Dispersion("polynomial", [2.0, 0.01])  # coefficient without its exponent


def test_formula2_page_reproduces_builtin_bk7_and_properties():
    props = """    thermal_dispersion:
      - type: formula A
        coefficients: 1.86e-06 1.31e-08 -1.37e-11 4.34e-07 6.27e-10 0.17
    nd: 1.5168
    Vd: 64.17
    glass_code: 517642.251
    glass_status: preferred
    density:
      - value: 2510
    thermal_expansion:
      - temperature_range: 243 343
        value: 7.1e-06
      - temperature_range: 293 573
        value: 8.3e-06
    dPgF: -0.0009
"""
    data = f"""  - type: formula 2
    wavelength_range: 0.3 2.5
    coefficients: {BK7_SELLMEIER}
  - type: tabulated k
    data: |
        0.500 9.5781E-09
        1.530 9.8390E-08
"""
    cat, r = _one(_page(data, props), "specs/test/optical/N-BK7.yml")
    assert r["name"] == "N-BK7" and r["formula"] == "sellmeier" and len(r["coefficients"]) == 6  # c0 = 0 dropped
    assert (r["lambda_min"], r["lambda_max"]) == (0.3, 2.5)
    m = MaterialLibrary([r]).get("N-BK7")
    ref = builtin_materials()["N-BK7"]
    np.testing.assert_allclose([m.index(x) for x in L], [ref.index(x) for x in L], rtol=0, atol=1e-14)
    assert r["verified"] is True and r["status"] == "preferred"
    # dn/dT: the same Schott model as the built-in record, T0 = 293 K = 19.85 C
    assert r["thermal"] == {"D0": 1.86e-06, "D1": 1.31e-08, "D2": -1.37e-11, "E0": 4.34e-07, "E1": 6.27e-10, "lambda_tk": 0.17, "T0": 19.85}
    assert r["density"] == pytest.approx(2.51) and r["tce_m30_70"] == pytest.approx(7.1) and r["dpgf"] == -0.0009
    assert r["comment"] == "glass code 517642.251"
    # internal transmittance of 10 mm from k: tau = exp(-4 pi k d / lambda)
    lam, tau, d = r["internal_transmission"][1]
    assert (lam, d) == (1.53, 10.0)
    assert tau == pytest.approx(math.exp(-4 * math.pi * 9.8390e-08 * 10e3 / 1.53), abs=1e-6)
    assert "TEST Zemax catalog" in r["source"] and "<a" not in r["source"] and "refractiveindex.info" in r["source"]


def test_formula1_with_constant_term():
    # n^2 - 1 = c0 + B L^2/(L^2 - C^2): c0 becomes a Sellmeier term with C = 0
    c0, B, C = 0.4, 0.8, 0.1
    data = f"  - type: formula 1\n    wavelength_range: 0.4 2.0\n    coefficients: {c0} {B} {C}\n"
    cat, r = _one(_page(data, props=""))
    assert r["formula"] == "sellmeier_sq" and r["coefficients"] == [c0, 0.0, B, C]
    n = MaterialLibrary([r]).get("G1").index(0.8)
    assert n == pytest.approx(math.sqrt(1 + c0 + B * 0.64 / (0.64 - C * C)), abs=1e-14)


def test_formula3_page_and_zero_terms():
    data = "  - type: formula 3\n    wavelength_range: 0.36 2.3\n    coefficients: 2.2718929 -1.0108077e-2 2 1.0592509e-2 -2 0 -4 2.0816965e-4 -4\n"
    cat, r = _one(_page(data, props=""))
    assert r["formula"] == "polynomial" and r["coefficients"] == [2.2718929, -1.0108077e-2, 2.0, 1.0592509e-2, -2.0, 2.0816965e-4, -4.0]
    n = MaterialLibrary([r]).get("G1").index(0.6)
    assert n == pytest.approx(math.sqrt(2.2718929 - 1.0108077e-2 * 0.36 + 1.0592509e-2 / 0.36 + 2.0816965e-4 / 0.36**2), abs=1e-14)


def test_tabulated_nk_page():
    data = "  - type: tabulated nk\n    data: |\n        0.4 1.53 1e-7\n        0.6 1.52 2e-8\n        0.8 1.51 1e-8\n        1.0 1.505 1e-8\n"
    cat, r = _one(_page(data, props=""))
    assert r["formula"] == "tabulated" and r["table"][1] == [0.6, 1.52]
    assert r["internal_transmission"][0][1] == pytest.approx(math.exp(-4 * math.pi * 1e-7 * 1e4 / 0.4), abs=1e-6)
    assert MaterialLibrary([r]).get("G1").index(0.6) == pytest.approx(1.52, abs=1e-12)


def test_tabulated_k_keeps_strong_and_weak_absorption():
    """alpha = 4 pi k / lambda must survive the catalogue record: a strongly absorbing line must not floor at 2.76 /mm
    (tau underflowing at 10 mm), nor a very weak one be quantised by rounding tau to 6 decimals."""
    data = "  - type: tabulated nk\n    data: |\n        0.35 1.55 1e-4\n        0.5 1.53 1e-11\n        0.8 1.51 0\n"
    _, r = _one(_page(data, props=""))
    lib = MaterialLibrary([r])
    from opticore.system import medium_absorption

    for lam, k in ((0.35, 1e-4), (0.5, 1e-11), (0.8, 0.0)):
        alpha = medium_absorption(lib, "G1", lam, True)[0]
        assert alpha == pytest.approx(4 * math.pi * k * 1e3 / lam, rel=1e-9, abs=1e-15)


def test_flags_mismatch_skips_bad_pages_and_ir_glasses():
    good = f"  - type: formula 2\n    wavelength_range: 0.3 2.5\n    coefficients: {BK7_SELLMEIER}\n"
    files = [
        ("specs/t/optical/WRONG.yml", _page(good, "    nd: 1.52\n    Vd: 64.17\n")),  # nd off by 3e-3
        ("specs/t/optical/F4.yml", _page("  - type: formula 4\n    coefficients: 1 2 3\n")),
        ("specs/t/optical/BAD.yml", "DATA: [unclosed"),
        ("specs/t/optical/KONLY.yml", _page("  - type: tabulated k\n    data: |\n        0.5 1e-8\n        0.6 1e-8\n")),
        # infrared glass: range 1-12 um, n^2 - 1 = 5.6 L^2/(L^2 - 0.6): no real index at the F line
        ("specs/t/infrared/IRG.yml", _page("  - type: formula 2\n    wavelength_range: 1 12\n    coefficients: 0 5.6 0.6\n", props="")),
        ("specs/t/other/WRONG.yml", _page(good)),  # duplicate name
    ]
    cat = parse_rii_catalog(files, "T")
    names = [r["name"] for r in cat.records]
    assert names == ["WRONG", "IRG"]
    assert cat.records[0]["verified"] is False and cat.records[1]["verified"] is True
    by = {(d.glass, d.level) for d in cat.diagnostics}
    assert {("F4", "error"), ("BAD", "error"), ("KONLY", "error"), ("WRONG", "warning"), ("IRG", "info")} <= by
    assert "1 do not reproduce" in cat.diagnostics[0].message and "1 materials (e.g. infrared glasses)" in cat.diagnostics[0].message
    assert glass_name("specs/sumita/optical/K-CaFK95(M).yml") == "K-CAFK95(M)"


def test_rii_endpoint():
    page = _page(f"  - type: formula 2\n    wavelength_range: 0.3 2.5\n    coefficients: {BK7_SELLMEIER}\n")
    r = client.post("/api/v1/materials/rii", json={"catalog": "schott", "files": [{"path": "specs/schott/optical/N-BK7.yml", "content": page}]})
    assert r.status_code == 200
    d = r.json()
    assert d["catalog"] == "SCHOTT" and d["records"][0]["family"] == "SCHOTT"
    assert d["summaries"][0]["nd"] == pytest.approx(1.5168, abs=1e-4) and d["summaries"][0]["catalog"] == "SCHOTT"
    assert client.post("/api/v1/materials/rii", json={"catalog": "x", "files": []}).status_code == 422
