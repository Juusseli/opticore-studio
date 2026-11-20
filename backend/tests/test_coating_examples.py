"""Tabulated targets, two-sided optimisation and the OIC 2019 "Yucca" benchmark example.

References:
* D. Poitras, L. Li, M. R. Jacobson, C. C. Cooksey, "2019 Topical Meeting on Optical Interference Coatings:
  Manufacturing Problem Contest", Appl. Opt. 59(5), A31-A39 (2020): the merit function MF (eq. 1), the target data
  (Figshare doi:10.6084/m9.figshare.9915800, CC BY 4.0) and the contest results (Table 3: design MF 0.439...2.14).
* The contest MF is recomputed here with the analysis module's own spectrum code (coatanalysis), independent of the
  designer's merit.
"""

from __future__ import annotations

import csv
import hashlib
import json
from importlib import resources

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.coatanalysis import spectrum as aspectrum, stack_from_design
from opticore.coatdesign import CoatingDesign, Merit, Resolver, _pairs_all, optimize_design, refine
from opticore.tools.coating_examples import TARGETS, contest_mf, yucca_targets


def _independent_mf(d: CoatingDesign) -> float:
    """sqrt(mean(((Ts - Ts_target) / 0.01)^2)) over both tables, by coatanalysis."""
    st = stack_from_design(d, Resolver(d))
    errs = []
    for t in yucca_targets():
        tab = np.asarray(t["table"])
        Ts = aspectrum(st, tab[:, 0], t["angle_deg"])["Ts"]
        errs.append((Ts - tab[:, 1]) / 0.01)
    e = np.concatenate(errs)
    return float(np.sqrt(np.mean(e * e)))


def test_contest_target_data():
    rows = [r for r in csv.reader(open(TARGETS, encoding="utf-8")) if r and not r[0].startswith("#")][1:]
    n10 = [r for r in rows if r[0] == "10"]
    n50 = [r for r in rows if r[0] == "50"]
    assert len(n10) == 626 and len(n50) == 586 and {r[3] for r in rows} == {"0.01"}
    assert (n10[0][1], n10[-1][1], n50[0][1], n50[-1][1]) == ("450", "1075", "480", "1065")
    assert "CC BY 4.0" in open(TARGETS, encoding="utf-8").read(600)


def test_tabulated_targets_give_the_contest_merit_function():
    """With the two tables, "=" targets, zero tolerance and weights = numbers of points, the designer's merit is the
    contest MF x 0.01 (checked against the independent computation) for an arbitrary two-sided design."""
    d = CoatingDesign(palette=[{"key": "H", "material": "TIO2_FILM"}, {"key": "L", "material": "SIO2_FILM"}], substrate="N-BK7", back_side="coated", substrate_thickness_mm=1.0,
                      layers=[{"material": k, "thickness_nm": x} for k, x in (("H", 80.0), ("L", 120.0), ("H", 60.0), ("L", 95.0))],
                      back_layers=[{"material": k, "thickness_nm": x} for k, x in (("L", 100.0), ("H", 50.0))], targets=yucca_targets())
    p, _ = _pairs_all(d)
    assert Merit(d, Resolver(d)).value(p) / 0.01 == pytest.approx(_independent_mf(d), rel=1e-10)
    assert contest_mf(d) == pytest.approx(_independent_mf(d), rel=1e-10)


def test_table_validation():
    base = {"quantity": "T", "lambda_min_nm": 400, "lambda_max_nm": 500, "value": 0.5}
    with pytest.raises(ValueError, match="increase"):
        CoatingDesign(palette=[{"key": "H"}], targets=[dict(base, table=[(500, 0.5), (400, 0.5)])])
    with pytest.raises(ValueError, match="fractions"):
        CoatingDesign(palette=[{"key": "H"}], targets=[dict(base, table=[(400, 0.5), (500, 1.5)])])
    d = CoatingDesign(palette=[{"key": "H"}], targets=[dict(base, table=[(420, 0.2), (470, 0.3)])])
    assert (d.targets[0].lambda_min_nm, d.targets[0].lambda_max_nm) == (420, 470)


def test_both_faces_are_optimised():
    """A two-sided design: the optimiser's list is front, SEP, back; the batched Jacobian rows equal single
    evaluations, and refinement changes the back layers as well as the front ones."""
    d = CoatingDesign(palette=[{"key": "H", "material": "TIO2_FILM"}, {"key": "L", "material": "SIO2_FILM"}], substrate="N-BK7", back_side="coated", substrate_thickness_mm=1.0,
                      layers=[{"material": k, "thickness_nm": x} for k, x in (("H", 70.0), ("L", 110.0), ("H", 70.0), ("L", 110.0))],
                      back_layers=[{"material": k, "thickness_nm": x} for k, x in (("H", 60.0), ("L", 90.0))], targets=yucca_targets(step=8))
    res = Resolver(d)
    mf = Merit(d, res)
    pairs, locked = _pairs_all(d)
    assert [k for k, _ in pairs][4] == "|" and locked[4]
    free = [i for i, lk in enumerate(locked) if not lk]
    X = np.array([[pairs[i][1] * f for i in free] for f in (1.0, 1.02)])
    for row, x in zip(mf.residuals_batch(X, pairs, free), X):
        p2 = list(pairs)
        for j, i in enumerate(free):
            p2[i] = (p2[i][0], float(x[j]))
        assert np.allclose(row, mf.residuals(p2), rtol=1e-12, atol=1e-15)
    p3, _, info = refine(d, res)
    assert info["final"] < info["initial"]
    keys = [k for k, _ in p3]
    back = p3[keys.index("|") + 1:]
    assert any(abs(a[1] - b.thickness_nm) > 1e-3 for a, b in zip(back, d.back_layers))
    r = optimize_design(d, method="refine", time_limit_s=30)
    out = CoatingDesign.model_validate(r["design"])
    assert len(out.back_layers) == 2 and r["final_merit"] < r["initial_merit"]


def test_the_yucca_example():
    """The library example: designed with the coating designer, its contest MF (recomputed independently) is the stored
    one and lies within the range of the contest's own designs (Table 3: 0.439...2.14)."""
    data = json.loads(resources.files("opticore.materials").joinpath("data/coating_examples.json").read_text("utf-8"))
    ex = next(e for e in data["examples"] if e["id"] == "oic2019_yucca")
    d = CoatingDesign.model_validate(ex["design"])
    assert d.back_side == "coated" and not d.back_same_as_front and d.substrate == "N-BK7" and d.substrate_thickness_mm == 1.0
    assert len(d.targets) == 2 and len(d.targets[0].table) == 626 and len(d.targets[1].table) == 586
    mf = _independent_mf(d)
    assert mf == pytest.approx(ex["contest_mf"], rel=1e-9)
    assert mf <= ex["reference"]["design_mf_range"][1]
    assert all(L.thickness_nm >= 5.0 for L in d.layers + d.back_layers)
    assert ex["layers_front"] == len(d.layers) and ex["layers_back"] == len(d.back_layers)
    assert hashlib.md5(TARGETS.read_bytes()).hexdigest()  # the target file the example was designed against is present


def test_examples_endpoint_and_evaluation():
    """/coating-examples lists the example; /coating-design/evaluate of its design reports both tabulated targets with
    one sample per listed wavelength and the merit that gives the stored MF."""
    client = TestClient(app)
    r = client.get("/api/v1/coating-examples")
    assert r.status_code == 200
    ex = next(e for e in r.json()["examples"] if e["id"] == "oic2019_yucca")
    assert ex["category"] == "Benchmarks" and "Appl. Opt. 59(5)" in ex["reference"]["paper"]
    ev = client.post("/api/v1/coating-design/evaluate", json={"design": ex["design"]})
    assert ev.status_code == 200, ev.text
    b = ev.json()["targets"]
    assert [len(t["lambda_nm"]) for t in b] == [626, 586]
    assert b[0]["lambda_nm"][0] == 450 and b[1]["lambda_nm"][-1] == 1065
    assert ev.json()["merit"] / 0.01 == pytest.approx(ex["contest_mf"], rel=1e-9)
