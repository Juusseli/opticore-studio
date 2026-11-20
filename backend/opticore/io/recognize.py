"""Recognise lenses and mirrors in imported STEP/IGES solids and insert them as optical surfaces.

Recognition (per solid, exact B-rep through OpenCascade)
--------------------------------------------------------
1. Symmetry axis: the common axis of the solid's surfaces of revolution,
   cylinders, cones and tori, or the line through the centres of its
   spherical faces, or (for flat windows) the normal of its largest plane.
   Spherical centres and optical planes must be consistent with the axis.
2. The axis line is intersected with the solid: a lens or mirror substrate
   has exactly two crossings, the front (first along the axis) and back
   optical faces. The axis is oriented along +z of the optical frame when it
   is roughly aligned with it, otherwise along the part's own direction.
3. Each optical face is classified exactly where possible:
     plane                  R = infinity
     sphere                 R = (centre - vertex) . axis
     surface of revolution  plane / sphere when the meridian is a line / a
                            circle centred on the axis; otherwise fitted
     anything else          sampled along a meridian by exact line-face
                            intersections and fitted with an even asphere
                            (curvature, conic, A4-A10) by least squares;
                            RMS and maximum residuals are reported
4. Clear semi-diameter of each optical face: the largest distance of its
   boundary from the axis; centre thickness: distance between the vertices.

Insertion into the sequential system
------------------------------------
* placement "axis": the element's front vertex is put `gap` mm after
  surface k on the current axis; downstream surfaces keep their positions
  (the element must fit into the existing space).
* placement "cad": the element is placed where the CAD model is (after its
  CAD transform) relative to the frame after surface k: on-axis parts are
  inserted directly, decentred or tilted parts with an exact
  coordinate-break pair (the same construction as element tolerances), so
  downstream surfaces are unchanged.
* Several elements are inserted in axis order; elements that touch
  (gap < 1 um) become cemented groups (one shared surface).
* A mirror (role "mirror") uses one optical face as the reflecting surface
  and must be inserted directly before the image; the image distance gets a
  paraxial focus solve (marginal height 0) that the user can remove.
The user assigns the glass; geometry alone is not an optical prescription.
"""

from __future__ import annotations

import base64
import math

import numpy as np
from scipy.optimize import least_squares

from .cad import CadError, _asset_trsf, _occ, _place, _read_shape, _solidify, shape_properties

AXIS_TOL = 1e-6  # mm
ANG_TOL = 1e-7  # rad


# ----------------------------------------------------------------------
# OpenCascade helpers
# ----------------------------------------------------------------------
def _faces(shape):
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        yield TopoDS.Face(ex.Current())
        ex.Next()


def _solids(shape):
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        yield TopoDS.Solid(ex.Current())
        ex.Next()


def _v(p) -> np.ndarray:
    return np.array([p.X(), p.Y(), p.Z()], dtype=float)


def _surface_info(face) -> dict:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_CurveType, GeomAbs_SurfaceType as T

    s = BRepAdaptor_Surface(face, True)
    t = s.GetType()
    if t == T.GeomAbs_Plane:
        pl = s.Plane()
        return {"kind": "plane", "point": _v(pl.Location()), "normal": _v(pl.Axis().Direction())}
    if t == T.GeomAbs_Sphere:
        sp = s.Sphere()
        return {"kind": "sphere", "center": _v(sp.Location()), "radius": sp.Radius()}
    if t == T.GeomAbs_Cylinder:
        ax = s.Cylinder().Axis()
        return {"kind": "cylinder", "axis_point": _v(ax.Location()), "axis_dir": _v(ax.Direction())}
    if t == T.GeomAbs_Cone:
        ax = s.Cone().Axis()
        return {"kind": "cone", "axis_point": _v(ax.Location()), "axis_dir": _v(ax.Direction())}
    if t == T.GeomAbs_Torus:
        ax = s.Torus().Axis()
        return {"kind": "torus", "axis_point": _v(ax.Location()), "axis_dir": _v(ax.Direction())}
    if t == T.GeomAbs_SurfaceOfRevolution:
        ax = s.AxeOfRevolution()
        info = {"kind": "revolution", "axis_point": _v(ax.Location()), "axis_dir": _v(ax.Direction())}
        bc = s.BasisCurve()
        ct = bc.GetType()
        if ct == GeomAbs_CurveType.GeomAbs_Circle:
            c = bc.Circle()
            info["meridian"] = {"kind": "circle", "center": _v(c.Location()), "radius": c.Radius()}
        elif ct == GeomAbs_CurveType.GeomAbs_Line:
            ln = bc.Line()
            info["meridian"] = {"kind": "line", "point": _v(ln.Location()), "dir": _v(ln.Direction())}
        return info
    return {"kind": "other"}


def _dist_to_axis(p: np.ndarray, o: np.ndarray, a: np.ndarray) -> float:
    d = p - o
    return float(np.linalg.norm(d - (d @ a) * a))


def _face_points(face, n: int = 48) -> np.ndarray:
    """Points sampled on the boundary edges of a face."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    pts = []
    ex = TopExp_Explorer(face, TopAbs_EDGE)
    while ex.More():
        c = BRepAdaptor_Curve(TopoDS.Edge(ex.Current()))
        u0, u1 = c.FirstParameter(), c.LastParameter()
        for u in np.linspace(u0, u1, n):
            pts.append(_v(c.Value(float(u))))
        ex.Next()
    return np.array(pts) if pts else np.zeros((0, 3))


def _line_hits(shape, o: np.ndarray, d: np.ndarray, tol: float = 1e-7) -> list[tuple[float, object, np.ndarray]]:
    """(w, face, point) of all intersections of the infinite line o + w d with the shape, sorted by w."""
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector

    it = IntCurvesFace_ShapeIntersector()
    it.Load(shape, tol)
    it.Perform(gp_Lin(gp_Pnt(*o), gp_Dir(*d)), -1e7, 1e7)
    out = []
    for k in range(1, it.NbPnt() + 1):
        out.append((it.WParameter(k), it.Face(k), _v(it.Pnt(k))))
    out.sort(key=lambda x: x[0])
    # merge duplicates (edges shared by two faces)
    merged = []
    for h in out:
        if merged and abs(h[0] - merged[-1][0]) < 1e-6:
            continue
        merged.append(h)
    return merged


def _face_line_hit(face, o, d) -> np.ndarray | None:
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    from OCP.IntCurvesFace import IntCurvesFace_Intersector

    it = IntCurvesFace_Intersector(face, 1e-8)
    it.Perform(gp_Lin(gp_Pnt(*o), gp_Dir(*d)), -1e7, 1e7)
    if it.NbPnt() == 0:
        return None
    k = min(range(1, it.NbPnt() + 1), key=lambda i: abs(it.WParameter(i)))
    return _v(it.Pnt(k))


# ----------------------------------------------------------------------
# recognition
# ----------------------------------------------------------------------
def _axis_of(solid) -> tuple[np.ndarray, np.ndarray]:
    infos = [(f, _surface_info(f)) for f in _faces(solid)]
    axes = [(i["axis_point"], i["axis_dir"] / np.linalg.norm(i["axis_dir"])) for _, i in infos if "axis_dir" in i]
    spheres = [i for _, i in infos if i["kind"] == "sphere"]
    if axes:
        o, a = axes[0]
        for p, b in axes[1:]:
            if abs(abs(a @ b) - 1) > ANG_TOL * 10 or _dist_to_axis(p, o, a) > AXIS_TOL * 10:
                raise CadError("surfaces of revolution do not share one axis (not rotationally symmetric)")
    elif len(spheres) >= 2:
        cs = sorted(spheres, key=lambda s: -s["radius"])
        o = cs[0]["center"]
        d = cs[1]["center"] - o
        if np.linalg.norm(d) < AXIS_TOL:
            raise CadError("concentric spherical faces: the optical axis is undefined")
        a = d / np.linalg.norm(d)
    else:
        planes = [(f, i) for f, i in infos if i["kind"] == "plane"]
        if not planes:
            raise CadError("no rotational symmetry axis found")
        from OCP.BRepGProp import BRepGProp
        from OCP.GProp import GProp_GProps

        best = max(planes, key=lambda fi: _face_area(fi[0]))
        a = best[1]["normal"] / np.linalg.norm(best[1]["normal"])
        g = GProp_GProps()
        BRepGProp.VolumeProperties_s(solid, g)
        o = _v(g.CentreOfMass())
        if spheres:
            o = spheres[0]["center"]
    for s in spheres:
        if _dist_to_axis(s["center"], o, a) > max(AXIS_TOL * 10, 1e-9 * s["radius"]):
            raise CadError("spherical faces are not centred on a common axis")
    return o, a


def _face_area(face) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    g = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, g)
    return float(g.Mass())


def _sag_model(r: np.ndarray, c: float, k: float, a: np.ndarray) -> np.ndarray:
    r2 = r * r
    root = np.sqrt(np.clip(1 - (1 + k) * c * c * r2, 0, None))
    z = c * r2 / (1 + root)
    p = r2 * r2
    for ai in a:
        z = z + ai * p
        p = p * r2
    return z


def _classify_face(face, vertex: np.ndarray, axis: np.ndarray, o_axis: np.ndarray, sd: float) -> dict:
    info = _surface_info(face)
    if info["kind"] == "plane":
        if abs(abs(info["normal"] @ axis) - 1) > 1e-6:
            raise CadError("a planar optical face is tilted against the axis")
        return {"type": "plane", "radius": None, "conic": 0.0, "aspheric": [], "fit_rms_mm": 0.0, "fit_max_mm": 0.0, "exact": True}
    if info["kind"] == "sphere":
        R = float((info["center"] - vertex) @ axis)
        return {"type": "sphere", "radius": R, "conic": 0.0, "aspheric": [], "fit_rms_mm": 0.0, "fit_max_mm": 0.0, "exact": True}
    mer = info.get("meridian")
    if info["kind"] == "revolution" and mer:
        if mer["kind"] == "line" and abs(mer["dir"] @ axis) < 1e-9:
            return {"type": "plane", "radius": None, "conic": 0.0, "aspheric": [], "fit_rms_mm": 0.0, "fit_max_mm": 0.0, "exact": True}
        if mer["kind"] == "circle" and _dist_to_axis(mer["center"], o_axis, axis) < max(AXIS_TOL, 1e-9 * mer["radius"]):
            R = float((mer["center"] - vertex) @ axis)
            if abs(abs(R) - mer["radius"]) < 1e-6 * max(1.0, mer["radius"]):
                return {"type": "sphere", "radius": R, "conic": 0.0, "aspheric": [], "fit_rms_mm": 0.0, "fit_max_mm": 0.0, "exact": True}
    # general surface: sample a meridian with exact line-face intersections and fit an even asphere
    u = np.cross(axis, [1.0, 0.0, 0.0])
    if np.linalg.norm(u) < 0.1:
        u = np.cross(axis, [0.0, 1.0, 0.0])
    u /= np.linalg.norm(u)
    rs, zs = [], []
    for r in np.linspace(0.0, 0.985 * sd, 41):
        p = _face_line_hit(face, vertex + r * u - 1.0 * axis, axis)
        if p is not None:
            rs.append(r)
            zs.append(float((p - vertex) @ axis))
    rs, zs = np.array(rs), np.array(zs)
    if len(rs) < 8:
        raise CadError("could not sample the optical face along its meridian")

    def fit(n_asph: int, with_k: bool):
        def res(x):
            c = x[0]
            k = x[1] if with_k else 0.0
            a = x[2:] if with_k else x[1:]
            return _sag_model(rs, c, k, a) - zs

        # initial curvature from the paraxial sag
        c0 = 2 * zs[-1] / rs[-1] ** 2 if rs[-1] > 0 else 0.0
        x0 = [c0] + ([0.0] if with_k else []) + [0.0] * n_asph
        sol = least_squares(res, x0, x_scale="jac", xtol=1e-15, ftol=1e-15, gtol=1e-15, max_nfev=4000)
        return sol.x, res(sol.x)

    best = None
    for n_a, wk in ((0, True), (1, True), (2, True), (3, True), (4, True)):
        x, r = fit(n_a, wk)
        rms = float(np.sqrt(np.mean(r * r)))
        best = (x, r, rms, n_a, wk)
        if rms < 1e-8:
            break
    x, r, rms, n_a, wk = best
    c = float(x[0])
    k = float(x[1]) if wk else 0.0
    a = [float(v) for v in (x[2:] if wk else x[1:])]
    kind = "conic" if not any(abs(v) > 0 for v in a) and abs(k) > 1e-12 else ("asphere" if a else "sphere")
    return {
        "type": kind if kind != "sphere" else "sphere",
        "radius": None if abs(c) < 1e-15 else 1.0 / c,
        "conic": k,
        "aspheric": a,
        "fit_rms_mm": rms,
        "fit_max_mm": float(np.max(np.abs(r))),
        "exact": False,
        "samples": int(len(rs)),
    }


def analyse_solid(solid, name: str) -> dict:
    o, a = _axis_of(solid)
    if a[2] < -1e-9 or (abs(a[2]) < 1e-9 and (a[0] < 0 or (abs(a[0]) < 1e-9 and a[1] < 0))):
        a = -a  # orient along +z of the optical frame when possible
    hits = _line_hits(solid, o, a)
    if len(hits) != 2:
        raise CadError(f"the optical axis crosses the part {len(hits)} times (a lens or mirror substrate needs exactly 2)")
    (w0, f0, v0), (w1, f1, v1) = hits
    sd0 = max(_dist_to_axis(p, o, a) for p in _face_points(f0))
    sd1 = max(_dist_to_axis(p, o, a) for p in _face_points(f1))
    front = _classify_face(f0, v0, a, o, sd0)
    back = _classify_face(f1, v1, a, o, sd1)
    front["semi_diameter"] = float(sd0)
    back["semi_diameter"] = float(sd1)
    pr = shape_properties(solid)
    rim = 0.0
    for f in _faces(solid):
        pts = _face_points(f, 24)
        if len(pts):
            rim = max(rim, max(_dist_to_axis(p, o, a) for p in pts))
    return {
        "name": name,
        "front": front,
        "back": back,
        "thickness": float(w1 - w0),
        "vertex": v0.tolist(),
        "axis": a.tolist(),
        "rim_radius": float(rim),
        "volume_mm3": pr["volume_mm3"],
    }


def recognize_asset(asset: dict) -> dict:
    """Recognised lens/mirror elements of a STEP/IGES CAD asset (in the optical global frame)."""
    _occ()
    fmt = asset.get("format")
    if fmt not in ("step", "iges") or not asset.get("source_b64"):
        raise CadError("Optical recognition needs a STEP or IGES model (exact B-rep); STL meshes cannot be converted exactly")
    comp, bodies = _read_shape(base64.b64decode(asset["source_b64"]), fmt)
    trsf = _asset_trsf(asset.get("transform") or {})
    elements, skipped = [], []
    for name, shp in bodies:
        shp, _ = _solidify(shp)
        solids = list(_solids(shp))
        if not solids:
            skipped.append({"name": name, "reason": "not a solid (curves or open surfaces)"})
            continue
        for k, so in enumerate(solids):
            nm = name if len(solids) == 1 else f"{name} #{k + 1}"
            try:
                elements.append(analyse_solid(_place(so, trsf), nm))
            except CadError as exc:
                skipped.append({"name": nm, "reason": str(exc)})
            except Exception as exc:  # noqa: BLE001 - kernel failures are reported per body
                skipped.append({"name": nm, "reason": f"geometry could not be analysed ({exc})"})
    a0 = np.array(elements[0]["axis"]) if elements else None
    for e in elements:
        e["axial_order"] = float(np.array(e["vertex"]) @ a0)
    elements.sort(key=lambda e: e["axial_order"])
    return {"elements": elements, "skipped": skipped}


# ----------------------------------------------------------------------
# insertion
# ----------------------------------------------------------------------
def _tilts_for(a_local: np.ndarray) -> tuple[float, float]:
    """tilt_x, tilt_y (deg) of an order-0 coordinate break that turns local z into a_local."""
    from ..geometry import Frame

    a = a_local / np.linalg.norm(a_local)
    beta = math.asin(max(-1.0, min(1.0, a[0])))
    for alpha in (math.atan2(-a[1], a[2]), math.atan2(a[1], a[2])):
        f = Frame.identity().coordinate_break(0, 0, math.degrees(alpha), math.degrees(beta), 0, 0)
        if np.allclose(f.matrix[:, 2], a, atol=1e-12):
            return math.degrees(alpha), math.degrees(beta)
    raise CadError("could not express the part's axis as a coordinate break")


def _surface_dict(id_: str, label: str, face: dict, thickness: float, material: str, sd: float) -> dict:
    asph = [a for a in face["aspheric"]]
    return {
        "id": id_,
        "type": "even_asphere" if asph else "standard",
        "label": label,
        "comment": "from CAD" + ("" if face.get("exact", True) else f" (fit rms {face['fit_rms_mm']:.1e} mm)"),
        "radius": face["radius"],
        "thickness": thickness,
        "material": material,
        "semi_diameter": float(sd),
        "semi_diameter_mode": "fixed",
        "conic": float(face["conic"]),
        "aspheric": asph,
    }


def insert_elements(system, elements: list[dict], role: str, materials: list[str], after: int, placement: str, gap: float, reflect_face: str, library) -> tuple[object, dict]:
    """Return (new OpticalSystem, report)."""
    from ..model import OpticalSystem, new_id
    from ..system import compile_system

    if not elements:
        raise CadError("No recognised element selected")
    d = system.model_dump()
    surfs = d["surfaces"]
    n = len(surfs)
    if not 0 <= after < n - 1:
        raise CadError("insertion point must be the object or an optical surface before the image")
    for m in materials:
        if role == "lens" and not library.has(m):
            raise CadError(f"Unknown material '{m}'")
    cs = compile_system(system)
    F = cs.frames_after[after]
    t_after = surfs[after]["thickness"]
    if t_after is None:
        if placement == "cad":
            raise CadError("CAD placement after an object at infinity is undefined; insert after surface 1 or use axis placement")
        t_after = 0.0
    medium_after = surfs[after]["material"] if not cs.is_mirror[after] else cs.model.surfaces[after].material
    notes: list[str] = []

    # local coordinates of each element's front vertex and axis in the frame after surface `after`
    loc = []
    for e in elements:
        p = F.to_local_points(np.array([e["vertex"]]))[0] if placement == "cad" else None
        a = F.to_local_dirs(np.array([e["axis"]]))[0] if placement == "cad" else np.array([0.0, 0.0, 1.0])
        loc.append((p, a))
    if placement == "axis":
        # keep the elements' mutual CAD spacing along their own axis; the first front vertex goes `gap` mm after surface `after`
        a_cad = np.array(elements[0]["axis"])
        base = np.array(elements[0]["vertex"]) @ a_cad
        for k, e in enumerate(elements):
            loc[k] = (np.array([0.0, 0.0, gap + float(np.array(e["vertex"]) @ a_cad - base)]), np.array([0.0, 0.0, 1.0]))
    a0 = loc[0][1]
    for p, a in loc[1:]:
        if abs(abs(a @ a0) - 1) > 1e-9:
            raise CadError("the selected elements do not share one axis; insert them separately")

    new: list[dict] = []
    first_z = float(loc[0][0][2])
    off_axis = np.linalg.norm(loc[0][0][:2]) > 1e-9 or abs(a0[2] - 1) > 1e-12
    if role == "mirror":
        if len(elements) != 1:
            raise CadError("insert one mirror at a time")
        if after != n - 2:
            raise CadError("a mirror must be inserted directly before the image surface")
        e = elements[0]
        face = e["front"] if reflect_face == "front" else e["back"]
        if reflect_face == "back":
            raise CadError("reflection from the back face needs the light to pass through the substrate; place the part so the reflecting face is first along the axis")
        surfs[after]["thickness"] = first_z
        if off_axis:
            ta, tb = _tilts_for(a0)
            new.append({"id": new_id(), "type": "coordinate_break", "label": f"{e['name']} placement", "thickness": 0.0, "decenter_x": float(loc[0][0][0]), "decenter_y": float(loc[0][0][1]), "tilt_x": ta, "tilt_y": tb, "cb_order": 0})
        rest = t_after - first_z
        mir = _surface_dict(new_id(), e["name"], face, -abs(rest) if abs(rest) > 1e-6 else -10.0, "MIRROR", face["semi_diameter"])
        mir["thickness_solve"] = {"type": "marginal_height", "target": 0.0}
        new.append(mir)
        notes.append("Image distance after the mirror is a paraxial focus solve (marginal-ray height 0); remove it in the inspector to set it manually")
    else:
        surfs[after]["thickness"] = first_z
        if off_axis:
            ta, tb = _tilts_for(a0)
            new.append({"id": new_id(), "type": "coordinate_break", "label": "CAD placement", "thickness": 0.0, "decenter_x": float(loc[0][0][0]), "decenter_y": float(loc[0][0][1]), "tilt_x": ta, "tilt_y": tb, "cb_order": 0})
        # axial position of every element's front vertex relative to the first one (along the common axis)
        p0 = loc[0][0]
        zf = []
        for k, (p, _a) in enumerate(loc):
            dp = p - p0
            if np.linalg.norm(dp - (dp @ a0) * a0) > 1e-6:
                raise CadError(f"{elements[k]['name']} is not on the axis of {elements[0]['name']}; insert it separately")
            zf.append(float(dp @ a0))
        for k, e in enumerate(elements):
            mat = materials[k] if k < len(materials) else materials[-1]
            front, back = e["front"], e["back"]
            sd_front = front["semi_diameter"]
            if k > 0 and zf[k] - (zf[k - 1] + elements[k - 1]["thickness"]) < 1e-3:
                prev_back = elements[k - 1]["back"]
                if (prev_back["radius"] is None) != (front["radius"] is None) or (front["radius"] is not None and abs(prev_back["radius"] - front["radius"]) > 1e-6 * abs(front["radius"])):
                    notes.append(f"{e['name']}: cemented faces differ (R {prev_back['radius']} vs {front['radius']}); the front face of {e['name']} is used")
                sd_front = max(sd_front, prev_back["semi_diameter"])
            new.append(_surface_dict(new_id(), f"{e['name']} front", front, e["thickness"], mat, sd_front))
            z_back = zf[k] + e["thickness"]
            if k + 1 < len(elements):
                g = zf[k + 1] - z_back
                if g < -1e-6:
                    raise CadError(f"{elements[k + 1]['name']} overlaps {e['name']} along the axis")
                if g < 1e-3:
                    continue  # cemented: the next element's front face is the shared surface
                new.append(_surface_dict(new_id(), f"{e['name']} back", back, g, medium_after, back["semi_diameter"]))
            else:
                new.append(_surface_dict(new_id(), f"{e['name']} back", back, 0.0, medium_after, back["semi_diameter"]))
        length = zf[-1] + elements[-1]["thickness"]
        if off_axis:
            new[-1]["thickness"] = -length
            new.append({"id": new_id(), "type": "coordinate_break", "label": "CAD placement (return)", "thickness": t_after - first_z, "decenter_x": -float(loc[0][0][0]), "decenter_y": -float(loc[0][0][1]), "tilt_x": -new[0]["tilt_x"], "tilt_y": -new[0]["tilt_y"], "cb_order": 1})
        else:
            rest = t_after - first_z - length
            if rest < -1e-6:
                raise CadError(f"the element(s) end {first_z + length:.4g} mm after surface {after} but only {t_after:.4g} mm are available; reduce the gap or make room first")
            new[-1]["thickness"] = max(rest, 0.0)
    surfs[after + 1 : after + 1] = new
    d["surfaces"] = surfs
    out = OpticalSystem.model_validate(d)
    compile_system(out)  # validates materials and geometry
    return out, {"inserted": [s["label"] for s in new], "notes": notes, "first_index": after + 1, "count": len(new)}
