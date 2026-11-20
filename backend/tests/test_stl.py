import base64
import struct

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.io.stl import StlError, decode_mesh, parse_stl
from opticore.project import CadAsset, dump_project, load_project
from opticore.samples import get_sample

# unit cube, outward-facing (counter-clockwise seen from outside)
CUBE_V = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], dtype=float)
CUBE_F = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]


def _tris(v=CUBE_V, faces=CUBE_F, a=1.0):
    return [tuple(v[i] * a for i in f) for f in faces]


def binary_stl(tris, normals=None) -> bytes:
    out = bytearray(b"OptiCore test".ljust(80, b" "))
    out += struct.pack("<I", len(tris))
    for k, t in enumerate(tris):
        n = normals[k] if normals is not None else np.cross(t[1] - t[0], t[2] - t[0])
        out += struct.pack("<3f", *n) + b"".join(struct.pack("<3f", *p) for p in t) + b"\0\0"
    return bytes(out)


def ascii_stl(tris, name="cube") -> bytes:
    lines = [f"solid {name}"]
    for t in tris:
        n = np.cross(t[1] - t[0], t[2] - t[0])
        lines.append(f"  facet normal {n[0]:e} {n[1]:e} {n[2]:e}\n    outer loop")
        for p in t:
            lines.append(f"      vertex {p[0]:.9e} {p[1]:.9e} {p[2]:.9e}")
        lines.append("    endloop\n  endfacet")
    lines.append(f"endsolid {name}")
    return "\n".join(lines).encode("ascii")


@pytest.mark.parametrize("kind", ["binary", "ascii"])
def test_cube_statistics(kind):
    a = 12.5
    data = binary_stl(_tris(a=a)) if kind == "binary" else ascii_stl(_tris(a=a))
    r = parse_stl(data, "mm", "cube")
    assert r["format"] == kind
    assert r["triangles"] == 12 and r["vertices"] == 8
    assert r["closed"]
    assert r["surface_area_mm2"] == pytest.approx(6 * a * a, rel=1e-6)
    assert r["volume_mm3"] == pytest.approx(a**3, rel=1e-6)
    assert r["size"] == pytest.approx([a, a, a])
    codes = {d["code"] for d in r["diagnostics"]}
    assert "NOT_AN_OPTICAL_SURFACE" in codes and "OPEN_MESH" not in codes and "INWARD_NORMALS" not in codes


def test_units_scale_to_mm():
    r = parse_stl(binary_stl(_tris(a=2.0)), "in")
    assert r["size"] == pytest.approx([50.8, 50.8, 50.8])
    assert r["volume_mm3"] == pytest.approx((2 * 25.4) ** 3, rel=1e-6)
    with pytest.raises(StlError):
        parse_stl(binary_stl(_tris()), "furlong")


def test_inward_normals_and_open_mesh_and_degenerate_are_reported():
    inward = [(t[0], t[2], t[1]) for t in _tris()]
    r = parse_stl(binary_stl(inward))
    assert r["volume_mm3"] == pytest.approx(-1.0, rel=1e-6)
    assert any(d["code"] == "INWARD_NORMALS" for d in r["diagnostics"])
    open_mesh = _tris()[:-2]
    r = parse_stl(binary_stl(open_mesh))
    assert not r["closed"] and r["volume_mm3"] is None
    assert any(d["code"] == "OPEN_MESH" for d in r["diagnostics"])
    deg = _tris() + [(CUBE_V[0], CUBE_V[0], CUBE_V[1])]
    r = parse_stl(binary_stl(deg))
    assert any(d["code"] == "DEGENERATE_TRIANGLES" and d["message"].startswith("1 ") for d in r["diagnostics"])
    # stored facet normals that contradict the winding are reported (winding wins)
    wrong = [-np.cross(t[1] - t[0], t[2] - t[0]) for t in _tris()]
    r = parse_stl(binary_stl(_tris(), normals=wrong))
    assert any(d["code"] == "NORMALS_DISAGREE" for d in r["diagnostics"])
    assert r["volume_mm3"] == pytest.approx(1.0, rel=1e-6)


def test_mesh_round_trip_and_corrupt_files():
    r = parse_stl(binary_stl(_tris(a=3.0)))
    p, i = decode_mesh(r["positions_b64"], r["indices_b64"])
    assert p.shape == (8, 3) and i.shape == (12, 3)
    tri = p[i]
    assert float(0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1).sum()) == pytest.approx(6 * 9.0, rel=1e-6)
    good = binary_stl(_tris())
    with pytest.raises(StlError):
        parse_stl(good[:-10])  # truncated binary (size mismatch, not ASCII)
    with pytest.raises(StlError):
        parse_stl(b"solid x\n facet normal 0 0 1\n outer loop\n vertex 0 0 0\n vertex 1 0 0\n endloop\n endfacet\nendsolid")  # two-vertex facet
    with pytest.raises(StlError):
        parse_stl(b"hello world, definitely not an stl")


def test_binary_file_starting_with_solid_is_detected_by_size():
    data = bytearray(binary_stl(_tris()))
    data[:5] = b"solid"  # many exporters write 'solid' into the binary header
    r = parse_stl(bytes(data))
    assert r["format"] == "binary" and r["closed"]


def _asset(r) -> dict:
    return {
        "name": "cube",
        "source_filename": "cube.stl",
        "units": r["units"],
        "mesh": {"positions_b64": r["positions_b64"], "indices_b64": r["indices_b64"], "vertices": r["vertices"], "triangles": r["triangles"]},
        "bbox_min": r["bbox_min"],
        "bbox_max": r["bbox_max"],
        "surface_area_mm2": r["surface_area_mm2"],
        "volume_mm3": r["volume_mm3"],
        "closed": r["closed"],
        "diagnostics": r["diagnostics"],
        "transform": {"translate": [0, 0, 50], "rotate_deg": [0, 90, 0]},
    }


def test_cad_asset_in_project_round_trip_and_validation():
    r = parse_stl(binary_stl(_tris(a=5.0)))
    p = get_sample("singlet")
    d = p.model_dump()
    d["cad_assets"] = [_asset(r)]
    raw = dump_project(type(p).model_validate(d))
    proj, _ = load_project(raw)
    assert proj.cad_assets[0].mesh.triangles == 12
    assert proj.cad_assets[0].transform.rotate_deg == [0, 90, 0]
    bad = _asset(r)
    bad["mesh"]["triangles"] = 13
    with pytest.raises(ValueError):
        CadAsset.model_validate(bad)
    bad = _asset(r)
    bad["mesh"]["indices_b64"] = base64.b64encode(np.array([[0, 1, 99]], dtype="<u4").tobytes()).decode()
    bad["mesh"]["triangles"] = 1
    with pytest.raises(ValueError):
        CadAsset.model_validate(bad)


def test_stl_api():
    c = TestClient(app)
    data = base64.b64encode(ascii_stl(_tris(a=2.0))).decode()
    r = c.post("/api/v1/import/stl", json={"filename": "cube.stl", "data_base64": data, "units": "cm"})
    assert r.status_code == 200
    assert r.json()["size"] == pytest.approx([20.0, 20.0, 20.0])
    bad = c.post("/api/v1/import/stl", json={"data_base64": base64.b64encode(b"nope nope nope").decode()})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "STL_INVALID"
