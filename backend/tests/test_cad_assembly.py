"""CAD assemblies: product structure, per-part optics, exact measurements, sections."""

import base64
import math
import os
import tempfile

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.io.cad import _occ, import_cad
from opticore.io.cad_assembly import asset_parts, clearance, read_tree, section, snap_points
from opticore.nonseq import build_scene, trace_nonsequential
from opticore.system import compile_system

from .test_nonseq import _empty


def _assembly_step(parts, groups=()):
    """STEP with an XCAF assembly. parts: {name: (shape, [(dx, dy, dz)...] instances, color or None)} placed in
    a top assembly 'top'; groups: [(group name, part name, [(dx, dy, dz)...])] sub-assemblies of instances."""
    _occ()
    from OCP.gp import gp_Trsf, gp_Vec
    from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_StepModelType
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

    def loc(d):
        t = gp_Trsf()
        t.SetTranslation(gp_Vec(*d))
        return TopLoc_Location(t)

    doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    labels = {}
    for nm, (shape, _inst, color) in parts.items():
        lab = st.AddShape(shape, False)
        TDataStd_Name.Set_s(lab, TCollection_ExtendedString(nm))
        if color:
            ct.SetColor(lab, Quantity_Color(*color, Quantity_TypeOfColor.Quantity_TOC_RGB), XCAFDoc_ColorType.XCAFDoc_ColorSurf)
        labels[nm] = lab
    top = st.NewShape()
    TDataStd_Name.Set_s(top, TCollection_ExtendedString("top"))
    for nm, (_s, inst, _c) in parts.items():
        for d in inst:
            st.AddComponent(top, labels[nm], loc(d))
    for gname, pname, inst in groups:
        g = st.NewShape()
        TDataStd_Name.Set_s(g, TCollection_ExtendedString(gname))
        for d in inst:
            st.AddComponent(g, labels[pname], loc(d))
        st.AddComponent(top, g, loc((0, 0, 0)))
    st.UpdateAssemblies()
    w = STEPCAFControl_Writer()
    w.SetNameMode(True)
    w.SetColorMode(True)
    w.Transfer(doc, STEPControl_StepModelType.STEPControl_AsIs)
    path = os.path.join(tempfile.mkdtemp(), "asm.step")
    w.Write(path)
    data = open(path, "rb").read()
    os.remove(path)
    return data


def _box(dx, dy, dz, x0=0.0, y0=0.0, z0=0.0):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), dx, dy, dz).Shape()


def _cyl(r, h):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    return BRepPrimAPI_MakeCylinder(r, h).Shape()


def _mount():
    """plate 10 x 10 x 2 (red) and a sub-assembly 'posts' with two cylinder instances (r 3, h 5) at z 12."""
    return _assembly_step({"plate": (_box(10, 10, 2), [(0, 0, 0)], (1, 0, 0)), "post": (_cyl(3, 5), [], None)}, [("posts", "post", [(2, 2, 12), (8, 8, 12)])])


def _asset(data, name="mount", **kw):
    imp = import_cad(data, name + ".step")
    a = {
        "id": "a1",
        "name": name,
        "format": "step",
        "source_b64": imp["source_b64"],
        "visible": True,
        "transform": {"translate": [0, 0, 0], "rotate_deg": [0, 0, 0]},
        "optical": {"role": "none"},
        "tree": imp["tree"],
        "mesh": {"positions_b64": imp["positions_b64"], "indices_b64": imp["indices_b64"], "vertices": imp["vertices"], "triangles": imp["triangles"]},
        "bbox_min": imp["bbox_min"],
        "bbox_max": imp["bbox_max"],
    }
    a.update(kw)
    return a, imp


def test_assembly_tree_structure_locations_and_ranges():
    imp = import_cad(_mount(), "mount.step")
    (top,) = imp["tree"]
    assert top["kind"] == "assembly" and top["name"] == "top"
    plate, posts = top["children"]
    assert plate["name"] == "plate" and plate["kind"] == "part" and plate["color"] == "#ff0000"
    assert plate["volume_mm3"] == pytest.approx(200.0, rel=1e-9)
    assert posts["name"] == "posts" and [c["name"] for c in posts["children"]] == ["post", "post"]
    v_post = math.pi * 9 * 5
    assert posts["volume_mm3"] == pytest.approx(2 * v_post, rel=1e-6)
    assert top["volume_mm3"] == pytest.approx(200 + 2 * v_post, rel=1e-6)
    p1, p2 = posts["children"]
    assert p1["bbox_min"][2] == pytest.approx(12.0, abs=1e-6) and p1["bbox_max"][2] == pytest.approx(17.0, abs=1e-6)
    assert np.mean([p1["bbox_min"][0], p1["bbox_max"][0]]) == pytest.approx(2.0, abs=1e-6)
    assert np.mean([p2["bbox_min"][0], p2["bbox_max"][0]]) == pytest.approx(8.0, abs=1e-6)  # second instance moved
    # contiguous triangle ranges covering the mesh, nested in the parent's range
    assert plate["tri_start"] == 0 and posts["tri_start"] == plate["tri_count"]
    assert p2["tri_start"] == p1["tri_start"] + p1["tri_count"]
    assert top["tri_count"] == imp["triangles"] == plate["tri_count"] + posts["tri_count"]
    assert imp["parts"] == 3 and any(d["code"] == "ASSEMBLY" for d in imp["diagnostics"])
    data = _mount()
    assert read_tree(data, "step") is read_tree(data, "step")  # parsed once per file content


def test_hidden_parts_and_inherited_roles():
    a, _ = _asset(_mount(), optical={"role": "absorber"}, hidden_parts=["1.2.2"], part_roles={"1.2": {"role": "mirror"}})
    parts = asset_parts(a)
    assert [p.node_id for p in parts] == ["1.1", "1.2.1"]  # second post hidden
    assert parts[0].optical["role"] == "absorber" and parts[1].optical["role"] == "mirror"  # inherited from 'posts'
    assert len(asset_parts(a, include_hidden=True)) == 3


def test_nonsequential_uses_per_part_roles():
    """Two plates across the beam (y < 0 and y > 0): only the part with an absorber role absorbs."""
    data = _assembly_step({"low": (_box(40, 20, 3, -20, -20, 0), [(0, 0, 30)], None), "high": (_box(40, 20, 3, -20, 1e-3, 0), [(0, 0, 30)], None)})
    cs = compile_system(_empty())
    a, _ = _asset(data, part_roles={"1.1": {"role": "absorber"}})
    r = trace_nonsequential(cs, build_scene(cs, [a], False), rays=300, overfill=1.0, split=False)
    absorbed = r["energy"]["absorbed"]
    assert list(absorbed) == ["mount / low"]
    assert absorbed["mount / low"] == pytest.approx(0.5, abs=0.06)  # half the pupil
    # hide the absorbing part and make the other one absorb
    a2, _ = _asset(data, hidden_parts=["1.1"], part_roles={"1.2": {"role": "absorber"}})
    r2 = trace_nonsequential(cs, build_scene(cs, [a2], False), rays=300, overfill=1.0, split=False)
    assert list(r2["energy"]["absorbed"]) == ["mount / high"]
    assert r2["energy"]["absorbed"]["mount / high"] + r2["energy"]["detected"] == pytest.approx(1.0, abs=1e-12)


def test_exact_point_snapping_with_placement():
    a, _ = _asset(_mount(), transform={"translate": [100.0, 0.0, 0.0], "rotate_deg": [0, 0, 0]})
    (s,) = snap_points({"a1": a}, [{"asset_id": "a1", "part_id": "1.1", "point": [105.0, 5.0, 2.04]}])
    assert s["point"] == pytest.approx([105.0, 5.0, 2.0], abs=1e-9)  # on the exact top face, placement applied
    assert s["offset_mm"] == pytest.approx(0.04, abs=1e-9) and s["exact"]
    (s,) = snap_points({"a1": a}, [{"asset_id": "a1", "part_id": "1.1", "point": [105.0, 5.0, 1.0]}])  # inside the solid
    assert s["offset_mm"] == pytest.approx(1.0, abs=1e-9)


def test_clearance_and_interference():
    a, _ = _asset(_mount())
    c = clearance({"a1": a}, {"asset_id": "a1", "part_id": "1.1"}, {"asset_id": "a1", "part_id": "1.2.1"})
    assert c["distance_mm"] == pytest.approx(10.0, abs=1e-9)  # plate top z = 2, post bottom z = 12
    assert c["point_a"][2] == pytest.approx(2.0, abs=1e-9) and c["point_b"][2] == pytest.approx(12.0, abs=1e-9)
    c = clearance({"a1": a}, {"asset_id": "a1", "part_id": "1.1"}, {"asset_id": "a1", "part_id": "1.2"})  # a whole sub-assembly
    assert c["distance_mm"] == pytest.approx(10.0, abs=1e-9)
    # a post sunk 1 mm into the plate interferes: common volume = pi r^2 * 1 mm
    data = _assembly_step({"plate": (_box(10, 10, 2), [(0, 0, 0)], None), "post": (_cyl(3, 5), [(5, 5, 1)], None)})
    b, _ = _asset(data)
    c = clearance({"a1": b}, {"asset_id": "a1", "part_id": "1.1"}, {"asset_id": "a1", "part_id": "1.2"})
    assert c["touching"] and c["distance_mm"] == pytest.approx(0.0, abs=1e-9)
    assert c["interference_volume_mm3"] == pytest.approx(math.pi * 9, rel=1e-6)


def _length(polys):
    return sum(float(np.sum(np.linalg.norm(np.diff(np.array(p), axis=0), axis=1))) for p in polys)


def test_plane_sections_of_parts_and_meshes():
    a, _ = _asset(_mount())
    secs = {s["part_id"]: s["polylines"] for s in section(a, origin=(4.0, 0, 0), normal=(1, 0, 0))}
    assert _length(secs["1.1"]) == pytest.approx(2 * (10 + 2), rel=1e-6)  # plate cut: 10 x 2 rectangle
    chord = 2 * math.sqrt(9 - 4)  # post at x = 2, r = 3, plane x = 4
    assert _length(secs["1.2.1"]) == pytest.approx(2 * (chord + 5), rel=1e-6)
    assert "1.2.2" not in secs  # second post spans x = 5...11: the plane x = 4 misses it
    for p in secs["1.1"]:
        assert np.allclose(np.array(p)[:, 0], 4.0, atol=1e-9)
    # hidden parts are not sectioned
    a2, _ = _asset(_mount(), hidden_parts=["1.2"])
    assert [s["part_id"] for s in section(a2, origin=(4.0, 0, 0))] == ["1.1"]
    # STL: triangle slicing of a cube
    from opticore.io.stl import parse_stl

    from .test_stl import _tris, binary_stl

    cube = parse_stl(binary_stl(_tris(a=5.0)))
    stl = {"id": "s", "name": "cube", "format": "stl", "visible": True, "transform": {"translate": [-2.5, -2.5, 0.0], "rotate_deg": [0, 0, 0]}, "mesh": {"positions_b64": cube["positions_b64"], "indices_b64": cube["indices_b64"]}}
    (row,) = section(stl, origin=(0.3, 0, 0))
    assert _length(row["polylines"]) == pytest.approx(4 * 5.0, rel=1e-9)


def test_cad_assembly_api():
    c = TestClient(app)
    a, _ = _asset(_mount())
    r = c.post("/api/v1/cad/measure", json={"assets": [a], "picks": [{"asset_id": "a1", "part_id": "1.1", "point": [2, 2, 2.1]}, {"asset_id": "a1", "part_id": "1.2.1", "point": [2, 2, 11.9]}]}).json()
    assert r["distance"]["distance_mm"] == pytest.approx(10.0, abs=1e-9)
    r = c.post("/api/v1/cad/clearance", json={"assets": [a], "a": {"asset_id": "a1", "part_id": "1.1"}, "b": {"asset_id": "a1", "part_id": "1.2"}}).json()
    assert r["distance_mm"] == pytest.approx(10.0, abs=1e-9)
    r = c.post("/api/v1/cad/section", json={"assets": [a]}).json()
    assert r["assets"][0]["asset_id"] == "a1" and r["assets"][0]["parts"]
    bad = c.post("/api/v1/cad/clearance", json={"assets": [a], "a": {"asset_id": "a1", "part_id": "9"}, "b": {"asset_id": "a1"}})
    assert bad.status_code == 422
    imp = c.post("/api/v1/import/cad", json={"filename": "m.step", "data_base64": base64.b64encode(_mount()).decode()}).json()
    assert imp["tree"][0]["children"][1]["name"] == "posts"
