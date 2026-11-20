"""AGF glass catalogue import (materials/agf.py) and the catalogue dispersion formulas.

The catalogue file below is written by the test from data with independent
references: the built-in N-BK7 / F2 records (SCHOTT datasheet Sellmeier
coefficients, nd/Vd from the datasheets) and formula equivalences that hold
exactly (e.g. Extended with A6 = A7 = 0 is the Schott formula).
"""

from __future__ import annotations

import base64
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.materials import MaterialLibrary, builtin_materials
from opticore.materials.agf import AGF_FORMULAS, catalog_name_from_filename, decode_agf, parse_agf
from opticore.materials.dispersion import LAMBDA_D, Dispersion

client = TestClient(app)
L = np.array([0.40, 0.4861327, 0.5875618, 0.6562725, 0.85, 1.55])


def _bk7():
    return builtin_materials()["N-BK7"]


def _agf_line(name, formula, nd, vd, coefs, status=0, lmin=0.3, lmax=2.5, extra=""):
    c = " ".join(f"{x:.10g}" for x in (list(coefs) + [0.0] * 10)[:10])
    return f"NM {name} {formula} 000000 {nd} {vd} 0 {status} 0\nED 7.1 8.3 2.51 -0.0009 0\nCD {c}\nLD {lmin} {lmax}\n{extra}"


def _catalog_text() -> str:
    bk7 = _bk7()
    f2 = builtin_materials()["F2"]
    bc = list(bk7.dispersion.coefficients)
    fc = list(f2.dispersion.coefficients)
    return (
        "CC Test catalogue written by test_agf.py\n"
        + _agf_line("TEST-BK7", 2, 1.5168, 64.17, bc, status=1, extra="TD 1.86e-06 1.31e-08 -1.37e-11 4.34e-07 6.27e-10 0.17 20\nOD 1 1 1 1 1 1\nIT 0.4 0.997 10\nIT 0.35 0.993 25\n")
        + _agf_line("TEST-F2", 2, f2.nd_ref or 1.62004, f2.vd_ref or 36.37, fc, status=2)
        # wrong catalogue Nd: imported but flagged
        + _agf_line("TEST-BAD", 2, 1.6000, 64.17, bc)
        + _agf_line("TEST-UNK", 99, 1.5, 60, [1.0])
        + "NM TEST-NOCD 2 0 1.5 60 0 0\nLD 0.4 0.8\n"
        + _agf_line("TEST-BK7", 2, 1.5168, 64.17, bc)  # duplicate
    )


def test_formula_table_covers_documented_formulas():
    assert sorted(AGF_FORMULAS) == list(range(1, 14))


def test_sellmeier1_import_reproduces_builtin_and_datasheet():
    cat = parse_agf(_catalog_text(), "TESTCAT", "test.agf")
    recs = {r["name"]: r for r in cat.records}
    assert set(recs) == {"TEST-BK7", "TEST-F2", "TEST-BAD"}
    lib = MaterialLibrary(cat.records)
    m = lib.get("TEST-BK7")
    np.testing.assert_allclose([m.index(x) for x in L], [_bk7().index(x) for x in L], rtol=0, atol=1e-15)
    assert abs(m.nd - 1.5168) < 2e-5
    assert recs["TEST-BK7"]["verified"] and recs["TEST-F2"]["verified"]
    assert recs["TEST-BK7"]["status"] == "preferred" and recs["TEST-F2"]["status"] == "obsolete"
    assert recs["TEST-BK7"]["lambda_min"] == 0.3 and recs["TEST-BK7"]["lambda_max"] == 2.5
    assert recs["TEST-BK7"]["catalog"] == "TESTCAT" and recs["TEST-BK7"]["family"] == "TESTCAT"
    assert recs["TEST-BK7"]["density"] == pytest.approx(2.51)
    assert recs["TEST-BK7"]["internal_transmission"] == [[0.4, 0.997, 10.0], [0.35, 0.993, 25.0]]


def test_nd_self_check_flags_but_keeps_mismatching_glass():
    cat = parse_agf(_catalog_text(), "TESTCAT")
    bad = next(r for r in cat.records if r["name"] == "TEST-BAD")
    assert bad["verified"] is False
    msgs = {(d.glass, d.level): d.message for d in cat.diagnostics}
    assert "differs from the catalogue Nd" in msgs[("TEST-BAD", "warning")]
    assert "unsupported dispersion formula 99" in msgs[("TEST-UNK", "error")]
    assert "no dispersion coefficients" in msgs[("TEST-NOCD", "error")]
    assert "duplicate" in msgs[("TEST-BK7", "warning")]
    assert cat.diagnostics[0].level == "info" and "3 of 6 glasses imported" in cat.diagnostics[0].message


def test_thermal_coefficients_feed_the_schott_dn_dt_model():
    cat = parse_agf(_catalog_text(), "TESTCAT")
    rec = next(r for r in cat.records if r["name"] == "TEST-BK7")
    assert rec["thermal"]["lambda_tk"] == 0.17 and rec["thermal"]["T0"] == 20
    m = MaterialLibrary([rec]).get("TEST-BK7")
    n0 = m.index(LAMBDA_D)
    n40 = m.dispersion.index_at_temperature(LAMBDA_D, 40.0)
    th = rec["thermal"]
    dT = 20.0
    expect = (n0 * n0 - 1) / (2 * n0) * (th["D0"] * dT + th["D1"] * dT**2 + th["D2"] * dT**3 + (th["E0"] * dT + th["E1"] * dT**2) / (LAMBDA_D**2 - th["lambda_tk"] ** 2))
    assert n40 - n0 == pytest.approx(expect, rel=1e-12)
    # N-BK7 datasheet order of magnitude: dn/dT ~ 2-3e-6 /K in the visible
    assert 1e-6 < (n40 - n0) / dT < 5e-6


def _same(f1, c1, f2, c2):
    a = Dispersion(f1, c1).index(L)
    b = Dispersion(f2, c2).index(L)
    np.testing.assert_allclose(a, b, rtol=0, atol=1e-14)


SCHOTT_BK7 = [2.2718929, -1.0108077e-2, 1.0592509e-2, 2.0816965e-4, -7.6472538e-6, 4.9240991e-7]


def test_catalogue_formulas_reduce_to_known_forms():
    s = SCHOTT_BK7
    _same("extended", s + [0, 0], "schott", s)
    _same("extended2", s + [0, 0], "schott", s)
    _same("extended3", [s[0], s[1], 0.0, s[2], s[3], s[4], s[5], 0, 0], "schott", s)
    B1, C1, B2, C2 = 1.03961212, 0.00600069867, 0.231792344, 0.0200179144
    _same("sellmeier4", [1.0, B1, C1, B2, C2], "sellmeier", [B1, C1, B2, C2])
    _same("handbook2", [1.0, B1, C1, 0.0], "sellmeier", [B1, C1])
    _same("sellmeier2", [0.0, B1, math.sqrt(C1), 0.0, 0.1], "sellmeier_sq", [B1, math.sqrt(C1)])
    # Sellmeier 3 / 5 are plain Sellmeier sums
    _same("sellmeier", [B1, C1, B2, C2, 0.0, 1.0, 0.0, 2.0], "sellmeier", [B1, C1, B2, C2])


def test_catalogue_formulas_at_a_point():
    lam = 0.5
    L2 = lam * lam
    # handbook 1
    assert Dispersion("handbook1", [2.0, 0.01, 0.02, 0.01]).index(lam) == pytest.approx(math.sqrt(2.0 + 0.01 / (L2 - 0.02) - 0.01 * L2), abs=1e-15)
    # Conrady
    assert Dispersion("conrady", [1.5, 0.005, 0.0002]).index(lam) == pytest.approx(1.5 + 0.005 / lam + 0.0002 / lam**3.5, abs=1e-15)
    # Herzberger
    a = [1.5, 0.004, 0.0001, -0.002, 1e-5, -1e-7]
    Lh = 1 / (L2 - 0.028)
    assert Dispersion("herzberger", a).index(lam) == pytest.approx(a[0] + a[1] * Lh + a[2] * Lh**2 + a[3] * L2 + a[4] * L2**2 + a[5] * L2**3, abs=1e-15)
    # Schott formula coefficients of BK7 reproduce its nd
    assert Dispersion("schott", SCHOTT_BK7).index(LAMBDA_D) == pytest.approx(1.5168, abs=1e-4)


def test_every_formula_number_imports_with_a_consistent_nd():
    """Each AGF formula, fed with coefficients equivalent to BK7, is imported, verified and gives BK7 indices."""
    s = SCHOTT_BK7
    sell = list(_bk7().dispersion.coefficients)
    B1, C1, B2, C2, B3, C3 = sell
    variants = {
        1: s,
        2: sell,
        6: sell + [0.0, 1.0],
        10: s + [0.0, 0.0],
        11: sell + [0.0, 1.0, 0.0, 2.0],
        12: s + [0.0, 0.0],
        13: [s[0], s[1], 0.0, s[2], s[3], s[4], s[5], 0.0, 0.0],
    }
    ref = Dispersion("schott", s)
    text = ""
    for fno, c in variants.items():
        nd = float((ref if fno in (1, 10, 12, 13) else _bk7().dispersion).index(LAMBDA_D))
        vd = (nd - 1) / float((ref if fno in (1, 10, 12, 13) else _bk7().dispersion).index(0.4861327) - (ref if fno in (1, 10, 12, 13) else _bk7().dispersion).index(0.6562725))
        text += _agf_line(f"F{fno}", fno, round(nd, 6), round(vd, 3), c)
    cat = parse_agf(text, "X")
    assert {r["name"] for r in cat.records} == {f"F{k}" for k in variants}
    assert all(r["verified"] for r in cat.records), [d.as_dict() for d in cat.diagnostics]


def test_decoding_utf16_and_names():
    text = _catalog_text()
    for data in (text.encode("utf-16"), text.encode("utf-16-le"), ("\ufeff" + text).encode("utf-8"), text.encode("latin-1")):
        assert decode_agf(data).replace("\ufeff", "").startswith("CC Test")
    assert catalog_name_from_filename("C:\\glass\\schott 2026.agf") == "SCHOTT_2026"
    assert catalog_name_from_filename("cdgm.AGF") == "CDGM"


def test_api_agf_and_zmx_with_catalogue_glass():
    b64 = base64.b64encode(_catalog_text().encode("utf-16")).decode()
    r = client.post("/api/v1/materials/agf", json={"filename": "testcat.agf", "content_base64": b64})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["catalog"] == "TESTCAT"
    assert len(d["records"]) == 3 and len(d["summaries"]) == 3
    s = next(x for x in d["summaries"] if x["name"] == "TEST-BK7")
    assert s["nd"] == pytest.approx(1.5168, abs=2e-5) and s["status"] == "preferred" and s["nd_ref"] == 1.5168
    assert client.post("/api/v1/materials/agf", json={"filename": "x.agf", "content_base64": base64.b64encode(b"hello").decode()}).status_code == 422

    zmx = "VERS 1\nMODE SEQ\nUNIT MM X W X CM MR CPMM\nENPD 10\nWAVM 1 0.5876 1\nSURF 0\n  DISZ INFINITY\nSURF 1\n  STOP\n  CURV 0.02\n  DISZ 4\n  GLAS TEST-BK7 0 0 1.5 60\nSURF 2\n  CURV -0.02\n  DISZ 45\nSURF 3\n"
    zb = base64.b64encode(zmx.encode()).decode()
    plain = client.post("/api/v1/import/zmx", json={"filename": "l.zmx", "content_base64": zb}).json()
    assert any(x["status"] == "missing_material" for x in plain["diagnostics"])
    withcat = client.post("/api/v1/import/zmx", json={"filename": "l.zmx", "content_base64": zb, "catalog_materials": d["records"]}).json()
    assert not any(x["status"] == "missing_material" for x in withcat["diagnostics"])
    p = withcat["project"]
    assert p["system"]["surfaces"][1]["material"] == "TEST-BK7"
    assert [m["name"] for m in p["custom_materials"]] == ["TEST-BK7"]
    # the self-contained project evaluates with the catalogue glass
    ev = client.post("/api/v1/system/evaluate", json={"system": p["system"], "custom_materials": p["custom_materials"]})
    assert ev.status_code == 200
    assert ev.json()["indices"][0][1] == pytest.approx(_bk7().index(0.5876), abs=1e-14)
