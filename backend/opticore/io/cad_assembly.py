"""CAD assemblies: the STEP/IGES product structure, per-part geometry,
exact measurements and plane sections.

Assembly tree
-------------
The XCAF document of a STEP/IGES file is walked from its free shapes:
an assembly label lists components (instances) that refer to a part or a
sub-assembly with a location; locations accumulate down the tree. Node ids
are 1-based index paths ("1", "1.2", "1.2.3"), stable for a given file. Each
part instance is a leaf with its located shape; the display mesh is built
leaf by leaf in depth-first order, so every node owns one contiguous range
of triangles (tri_start, tri_count) and the UI can hide or highlight parts
without re-tessellating.

Per-part optics
---------------
An asset may override the optical role (and material, coating, scatter) of
any node in `part_roles`; a leaf uses the nearest override on its path,
otherwise the asset role. Hidden nodes (`hidden_parts`) and their subtrees
are left out of non-sequential tracing and measurements.

Measurements (exact B-rep, global optical frame including the asset
placement): nearest points of picked display-mesh points on the exact
part surfaces (BRepExtrema), distances between them, and the minimum
distance (clearance) between two parts; touching or interfering parts give
0 and the volume of their common part is reported.

Sections: BRepAlgoAPI_Section of each visible part with a plane (default
the global y-z plane x = 0 of the 2D layout), discretised with a chordal
deflection; STL meshes are sliced triangle by triangle.
"""

from __future__ import annotations

import base64
import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np

from .cad import CadError, _asset_trsf, _occ, _place, _solidify, _stl_shell, _tessellate, shape_properties


@dataclass
class TreeNode:
    id: str
    name: str
    kind: str  # "assembly" | "part"
    children: list["TreeNode"] = field(default_factory=list)
    shape: object = None  # located shape (parts only)
    color: str | None = None


_CACHE: "OrderedDict[str, list[TreeNode]]" = OrderedDict()
_CACHE_MAX = 8


def _label_name(lab) -> str:
    from OCP.TDataStd import TDataStd_Name

    a = TDataStd_Name()
    if lab.FindAttribute(TDataStd_Name.GetID_s(), a):
        txt = str(a.Get().ToExtString())
        if txt and not txt.startswith("=>"):  # "=>[0:1:1:2]" are automatic reference names
            return txt
    return ""


def _label_color(lab) -> str | None:
    from OCP.Quantity import Quantity_Color
    from OCP.XCAFDoc import XCAFDoc_ColorTool, XCAFDoc_ColorType

    col = Quantity_Color()
    for kind in (XCAFDoc_ColorType.XCAFDoc_ColorSurf, XCAFDoc_ColorType.XCAFDoc_ColorGen):
        try:
            if XCAFDoc_ColorTool.GetColor_s(lab, kind, col):
                return "#" + "".join(f"{int(round(max(0.0, min(1.0, v)) * 255)):02x}" for v in (col.Red(), col.Green(), col.Blue()))
        except Exception:  # noqa: BLE001
            return None
    return None


def read_tree(data: bytes, fmt: str) -> list[TreeNode]:
    """Product structure of a STEP/IGES file (cached by content)."""
    key = hashlib.sha1(data).hexdigest() + fmt
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    _occ()
    import os
    import tempfile

    from OCP.IGESCAFControl import IGESCAFControl_Reader
    from OCP.Interface import Interface_Static
    from OCP.OCP.collections import Sequence_TDF_Label
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDF import TDF_Label
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    tmp = tempfile.mkdtemp(prefix="opticore_asm_")
    path = os.path.join(tmp, "in." + ("step" if fmt == "step" else "igs"))
    with open(path, "wb") as f:
        f.write(data)
    try:
        Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
        doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
        rd = STEPCAFControl_Reader() if fmt == "step" else IGESCAFControl_Reader()
        rd.SetNameMode(True)
        rd.SetColorMode(True)
        if int(rd.ReadFile(path)) != 1:
            raise CadError(f"The file could not be read as {fmt.upper()}")
        if not rd.Transfer(doc):
            raise CadError(f"No geometry could be transferred from the {fmt.upper()} file")
        st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

        def walk(lab, loc, nid: str, name: str, color: str | None, depth: int) -> TreeNode:
            col = _label_color(lab) or color
            if XCAFDoc_ShapeTool.IsAssembly_s(lab) and depth < 64:
                comps = Sequence_TDF_Label()
                XCAFDoc_ShapeTool.GetComponents_s(lab, comps, False)
                node = TreeNode(nid, name or _label_name(lab) or f"Assembly {nid}", "assembly", color=col)
                for k in range(1, comps.Length() + 1):
                    c = comps.Value(k)
                    ref = TDF_Label()
                    if not XCAFDoc_ShapeTool.GetReferredShape_s(c, ref):
                        continue
                    cl = loc.Multiplied(XCAFDoc_ShapeTool.GetLocation_s(c))
                    node.children.append(walk(ref, cl, f"{nid}.{k}", _label_name(c) or _label_name(ref), _label_color(c) or col, depth + 1))
                return node
            shp = XCAFDoc_ShapeTool.GetShape_s(lab)
            shp = shp.Moved(loc) if not loc.IsIdentity() else shp
            shp, _ = _solidify(shp)
            return TreeNode(nid, name or _label_name(lab) or f"Part {nid}", "part", shape=shp, color=col)

        labels = Sequence_TDF_Label()
        st.GetFreeShapes(labels)
        roots = [walk(labels.Value(k), TopLoc_Location(), str(k), _label_name(labels.Value(k)), None, 0) for k in range(1, labels.Length() + 1)]
        if not roots:
            raise CadError("The file contains no shapes")
    finally:
        try:
            os.remove(path)
            os.rmdir(tmp)
        except OSError:
            pass
    _CACHE[key] = roots
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return roots


def leaves(nodes: list[TreeNode], path: tuple[str, ...] = ()):
    """Depth-first (node, ancestor-id path including itself) of every part."""
    for n in nodes:
        p = path + (n.id,)
        if n.kind == "part":
            yield n, p
        else:
            yield from leaves(n.children, p)


def _count_solids(shape) -> int:
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    k = 0
    while ex.More():
        k += 1
        ex.Next()
    return k


def tessellate_tree(roots: list[TreeNode], deflection: float) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Display mesh (leaf by leaf) and the JSON tree with triangle ranges and exact properties."""
    pos: list[np.ndarray] = []
    idx: list[np.ndarray] = []
    state = {"v": 0, "t": 0}

    def build(n: TreeNode) -> dict:
        t0 = state["t"]
        if n.kind == "part":
            p, t = _tessellate(n.shape, deflection)
            if len(t):
                pos.append(p)
                idx.append(t + state["v"])
                state["v"] += len(p)
                state["t"] += len(t)
            pr = shape_properties(n.shape)
            return {
                "id": n.id,
                "name": n.name,
                "kind": "part",
                "solids": _count_solids(n.shape),
                "volume_mm3": pr["volume_mm3"],
                "area_mm2": pr["area_mm2"],
                "bbox_min": pr["bbox_min"],
                "bbox_max": pr["bbox_max"],
                "tri_start": t0,
                "tri_count": state["t"] - t0,
                "color": n.color,
                "children": [],
            }
        kids = [build(c) for c in n.children]
        vols = [k["volume_mm3"] for k in kids]
        bmin = np.min([k["bbox_min"] for k in kids], axis=0).tolist() if kids else [0.0, 0.0, 0.0]
        bmax = np.max([k["bbox_max"] for k in kids], axis=0).tolist() if kids else [0.0, 0.0, 0.0]
        return {
            "id": n.id,
            "name": n.name,
            "kind": "assembly",
            "solids": int(sum(k["solids"] for k in kids)),
            "volume_mm3": None if any(v is None for v in vols) or not kids else float(sum(vols)),
            "area_mm2": float(sum(k["area_mm2"] for k in kids)),
            "bbox_min": bmin,
            "bbox_max": bmax,
            "tri_start": t0,
            "tri_count": state["t"] - t0,
            "color": n.color,
            "children": kids,
        }

    tree = [build(r) for r in roots]
    if not pos:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64), tree
    return np.vstack(pos), np.vstack(idx), tree


def count_parts(tree: list[dict]) -> int:
    return sum(1 if n["kind"] == "part" else count_parts(n["children"]) for n in tree)


# ----------------------------------------------------------------------
# Parts of an asset in the global frame
# ----------------------------------------------------------------------
@dataclass
class AssetPart:
    asset: dict
    node_id: str | None  # None: the whole asset (STL or no tree)
    name: str
    shape: object  # global (asset placement applied)
    optical: dict
    exact: bool


def _effective_optical(asset: dict, path: tuple[str, ...]) -> dict:
    roles = asset.get("part_roles") or {}
    for nid in reversed(path):
        if nid in roles:
            return {**(asset.get("optical") or {}), **roles[nid]}
    return asset.get("optical") or {}


def asset_parts(asset: dict, include_hidden: bool = False) -> list[AssetPart]:
    """Located shapes of an asset: one per part for STEP/IGES, the triangle shell for STL."""
    trsf = _asset_trsf(asset.get("transform") or {})
    fmt = asset.get("format", "stl")
    hidden = set(asset.get("hidden_parts") or [])
    if fmt in ("step", "iges") and asset.get("source_b64"):
        roots = read_tree(base64.b64decode(asset["source_b64"]), fmt)
        out = []
        for leaf, path in leaves(roots):
            if not include_hidden and hidden.intersection(path):
                continue
            out.append(AssetPart(asset, leaf.id, f"{asset['name']} / {leaf.name}", _place(leaf.shape, trsf), _effective_optical(asset, path), True))
        return out
    if fmt == "stl":
        from .stl import decode_mesh

        p, i = decode_mesh(asset["mesh"]["positions_b64"], asset["mesh"]["indices_b64"])
        shape, _ = _solidify(_stl_shell(p.astype(float), i))
        return [AssetPart(asset, None, asset["name"], _place(shape, trsf), asset.get("optical") or {}, False)]
    return []


def find_part(asset: dict, node_id: str | None) -> AssetPart:
    parts = asset_parts(asset, include_hidden=True)
    if node_id is None:
        if len(parts) == 1:
            return parts[0]
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Compound

        comp = TopoDS_Compound()
        b = BRep_Builder()
        b.MakeCompound(comp)
        for p in parts:
            b.Add(comp, p.shape)
        return AssetPart(asset, None, asset["name"], comp, asset.get("optical") or {}, all(p.exact for p in parts))
    # a node id selects that part, or all parts below an assembly node
    sel = [p for p in parts if p.node_id == node_id or (p.node_id or "").startswith(node_id + ".")]
    if not sel:
        raise CadError(f"Part '{node_id}' not found in '{asset['name']}'")
    if len(sel) == 1:
        return sel[0]
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    comp = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(comp)
    for p in sel:
        b.Add(comp, p.shape)
    return AssetPart(asset, node_id, f"{asset['name']} / {node_id}", comp, asset.get("optical") or {}, True)


# ----------------------------------------------------------------------
# Measurements
# ----------------------------------------------------------------------
def _vertex(p):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.gp import gp_Pnt

    return BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, p))).Vertex()


def _dist(a, b):
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    d = BRepExtrema_DistShapeShape(a, b)
    d.Perform()
    if not d.IsDone() or d.NbSolution() < 1:
        raise CadError("Distance computation failed")
    pa, pb = d.PointOnShape1(1), d.PointOnShape2(1)
    return float(d.Value()), [pa.X(), pa.Y(), pa.Z()], [pb.X(), pb.Y(), pb.Z()]


def snap_points(assets: dict[str, dict], picks: list[dict]) -> list[dict]:
    """Nearest points on the exact part surfaces for picked (display-mesh) points."""
    out = []
    for pk in picks:
        a = assets.get(pk["asset_id"])
        if a is None:
            raise CadError(f"Unknown CAD model '{pk['asset_id']}'")
        part = find_part(a, pk.get("part_id"))
        d, pv, ps = _dist(_vertex(pk["point"]), _boundary(part.shape))
        out.append({"point": ps, "picked": list(map(float, pk["point"])), "offset_mm": d, "exact": part.exact, "part": part.name})
    return out


def _boundary(shape):
    """Faces only (so a point inside a solid snaps to its surface, not to itself)."""
    from OCP.BRep import BRep_Builder
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS_Compound

    comp = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(comp)
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    n = 0
    while ex.More():
        b.Add(comp, ex.Current())
        n += 1
        ex.Next()
    return comp if n else shape


def clearance(assets: dict[str, dict], a_ref: dict, b_ref: dict) -> dict:
    """Minimum distance between two parts (exact); 0 with the common volume when they touch or interfere."""
    pa = find_part(assets[a_ref["asset_id"]], a_ref.get("part_id"))
    pb = find_part(assets[b_ref["asset_id"]], b_ref.get("part_id"))
    d, p1, p2 = _dist(pa.shape, pb.shape)
    common = 0.0
    if d < 1e-9:
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Common

        try:
            cm = BRepAlgoAPI_Common(pa.shape, pb.shape)
            if cm.IsDone():
                common = float(shape_properties(cm.Shape()).get("volume_mm3") or 0.0)
        except Exception:  # noqa: BLE001
            common = 0.0
    return {
        "distance_mm": d,
        "point_a": p1,
        "point_b": p2,
        "a": pa.name,
        "b": pb.name,
        "touching": d < 1e-9,
        "interference_volume_mm3": common,
        "exact": pa.exact and pb.exact,
        "method": "BRepExtrema_DistShapeShape on the exact B-rep (STL: triangle shells); common volume by BRepAlgoAPI_Common",
    }


# ----------------------------------------------------------------------
# Sections
# ----------------------------------------------------------------------
def section(asset: dict, origin=(0.0, 0.0, 0.0), normal=(1.0, 0.0, 0.0), deflection: float | None = None) -> list[dict]:
    """Polylines (global coordinates) where the visible parts of an asset cut a plane."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    out = []
    if asset.get("format") == "stl":
        return [{"part_id": None, "polylines": _slice_mesh(asset, np.asarray(origin, float), np.asarray(normal, float))}]
    diag = float(np.linalg.norm(np.subtract(asset.get("bbox_max", [1, 1, 1]), asset.get("bbox_min", [0, 0, 0]))))
    defl = deflection or max(1e-3, 2e-3 * diag)
    pln = gp_Pln(gp_Pnt(*map(float, origin)), gp_Dir(*map(float, normal)))
    for part in asset_parts(asset):
        polys = []
        try:
            sec = BRepAlgoAPI_Section(part.shape, pln, False)
            sec.ComputePCurveOn1(False)
            sec.Approximation(False)
            sec.Build()
            if not sec.IsDone():
                continue
            ex = TopExp_Explorer(sec.Shape(), TopAbs_EDGE)
            while ex.More():
                c = BRepAdaptor_Curve(TopoDS.Edge(ex.Current()))
                g = GCPnts_QuasiUniformDeflection(c, defl)
                if g.IsDone() and g.NbPoints() >= 2:
                    pts = [g.Value(k) for k in range(1, g.NbPoints() + 1)]
                    polys.append([[p.X(), p.Y(), p.Z()] for p in pts])
                ex.Next()
        except Exception:  # noqa: BLE001 - a failing part must not hide the others
            continue
        if polys:
            out.append({"part_id": part.node_id, "polylines": polys})
    return out


def _slice_mesh(asset: dict, o: np.ndarray, n: np.ndarray) -> list[list[list[float]]]:
    from .stl import decode_mesh

    p, i = decode_mesh(asset["mesh"]["positions_b64"], asset["mesh"]["indices_b64"])
    t = asset.get("transform") or {}
    from scipy.spatial.transform import Rotation

    R = Rotation.from_euler("XYZ", t.get("rotate_deg", [0, 0, 0]), degrees=True).as_matrix()  # intrinsic: Rx Ry Rz, as _asset_trsf
    P = p.astype(float) @ R.T + np.asarray(t.get("translate", [0, 0, 0]), float)
    d = (P - o) @ (n / np.linalg.norm(n))
    segs = []
    for tri in i.reshape(-1, 3):
        dd = d[tri]
        if dd.min() > 0 or dd.max() < 0:
            continue
        pts = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            da, db = dd[a], dd[b]
            if (da > 0) != (db > 0) and da != db:
                s = da / (da - db)
                pts.append((P[tri[a]] + s * (P[tri[b]] - P[tri[a]])).tolist())
        if len(pts) == 2:
            segs.append(pts)
    return segs
