import copy
import json

import pytest

from opticore.analysis.spot import spot_diagram
from opticore.project import ProjectError, canonical_json, compute_checksum, dump_project, js_number, load_project
from opticore.samples import SAMPLES, achromat
from opticore.system import compile_system


@pytest.mark.parametrize(
    "x,expected",
    [
        (0.0, "0"),
        (-0.0, "0"),
        (1.0, "1"),
        (100.0, "100"),
        (-0.5, "-0.5"),
        (123.456, "123.456"),
        (1e-7, "1e-7"),
        (1e-6, "0.000001"),
        (0.0001234, "0.0001234"),
        (1.5e16, "15000000000000000"),
        (1e21, "1e+21"),
        (1.2345e22, "1.2345e+22"),
        (2.5e-12, "2.5e-12"),
        (0.1 + 0.2, "0.30000000000000004"),
        (5, "5"),
        (float("nan"), "null"),
    ],
)
def test_js_number_formatting(x, expected):
    assert js_number(x) == expected


def test_canonical_json_sorted_and_compact():
    assert canonical_json({"b": [1, 2.5, None], "a": {"y": True, "x": "é"}}) == '{"a":{"x":"é","y":true},"b":[1,2.5,null]}'


@pytest.mark.parametrize("sid", list(SAMPLES))
def test_roundtrip_all_samples(sid):
    proj = SAMPLES[sid][1]()
    d = dump_project(proj)
    text = json.dumps(d)
    loaded, notes = load_project(json.loads(text))
    assert notes == []
    assert dump_project(loaded) == d


def test_reload_gives_identical_engineering_results():
    proj = achromat(True)
    d = json.loads(json.dumps(dump_project(proj)))
    loaded, _ = load_project(d)
    a = spot_diagram(compile_system(proj.system))
    b = spot_diagram(compile_system(loaded.system))
    assert a == b


def test_checksum_detects_modification():
    d = dump_project(achromat(True))
    d2 = copy.deepcopy(d)
    d2["system"]["surfaces"][1]["radius"] = 50.0
    _, notes = load_project(d2)
    assert any("Checksum mismatch" in n for n in notes)
    assert compute_checksum(d) == d["checksum"]["value"]


def test_rejects_foreign_and_future_files():
    with pytest.raises(ProjectError):
        load_project({"format": "something-else", "schema_version": 1})
    d = dump_project(achromat(True))
    d["schema_version"] = 99
    with pytest.raises(ProjectError):
        load_project(d)
    with pytest.raises(ProjectError):
        load_project({"format": "opticore-project", "schema_version": 1, "system": {"surfaces": []}})
