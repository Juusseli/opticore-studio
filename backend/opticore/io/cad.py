"""STEP / IGES import and export with the OpenCascade kernel (OCP bindings).

Export: the optical system as CAD solids in the optical global frame (mm)
--------------------------------------------------------------------------
* Lens elements (each glass between consecutive surfaces, cemented groups as
  separate solids) are revolved from their exact meridional profile:
  spherical surfaces as true circular arcs (exact spheres), planes as
  lines, conic and even-aspheric surfaces as interpolating B-splines. The
  maximum deviation of every spline from the exact sag is measured by
  projection at the midpoints between nodes and reported.
* Without mechanical data the rim radius is the larger of the two effective
  semi-diameters plus an optional margin; the edge is a cylinder. Elements with non-positive edge
  thickness or a rim beyond a sphere's radius are skipped with a diagnostic.
* Mirrors become a substrate solid behind the reflecting surface (on the
  side away from the incoming light).
* Element rims follow the mechanical data (analysis/elements.py): the rim is
  the largest mechanical (else clear) semi-diameter, a surface with a smaller
  mechanical semi-diameter continues as a flat, 45 deg chamfers cut the rim
  corners.
* Optional: the aperture stop (circle), the image plane (disc), the
  meridional layout rays of every field (polylines), and spacers between the
  elements, cells for elements smaller than the bore and a simple barrel
  around them (mechanics_layout).
* Imported CAD models are included with their placement: STEP/IGES models
  from their original B-rep, STL models as a sewn triangle shell.
* Every item is named (e.g. "L1 N-BK7 (S1-S2)") and coloured through the
  XDE document, so CAD programs show a readable tree.

Import: STEP / IGES files become CAD assets
-------------------------------------------
* The file is read with the XDE readers (names kept where present), units
  converted to mm, bodies (solids, or shells/faces when there are no solids)
  listed with exact B-rep volume, area and bounding box.
* A display mesh is tessellated with a linear deflection of 0.1 % of the
  model's bounding-box diagonal (min 0.005 mm) and an angular deflection of
  0.35 rad. The mesh is for display only.
* The original file is stored with the asset so the exact geometry can be
  re-exported unchanged.

CAD geometry is never part of the optical prescription and is not ray
traced.
"""

from __future__ import annotations

import base64
import math
import os
import tempfile

import numpy as np

MAX_SOURCE_BYTES = 40 * 1024 * 1024
MAX_STL_EXPORT_TRIANGLES = 60_000


class CadError(ValueError):
    pass


_QUIET = False


def _occ():
    """Import the kernel lazily (≈0.6 s) so the engine starts without it, and silence its console statistics."""
    global _QUIET
    try:
        import OCP  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise CadError("The OpenCascade kernel (cadquery-ocp) is not installed in the engine environment") from exc
    if not _QUIET:
        try:
            from OCP.Message import Message, Message_Gravity

            printers = Message.DefaultMessenger_s().Printers()
            for k in range(1, printers.Length() + 1):
                printers.Value(k).SetTraceLevel(Message_Gravity.Message_Fail)
        except Exception:  # noqa: BLE001 - cosmetic only
            pass
        _QUIET = True


# ----------------------------------------------------------------------
# geometry helpers
# ----------------------------------------------------------------------
def _pnt(x, y, z):
    from OCP.gp import gp_Pnt

    return gp_Pnt(float(x), float(y), float(z))


def _profile_edge(shape, h: float, z0: float, sign: float = 1.0):
    """Meridional profile edge of a surface from r = 0 to r = h in the local XZ plane, shifted by z0.

    Returns (edge, max_deviation_mm, kind)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.GC import GC_MakeArcOfCircle
    from OCP.GeomAPI import GeomAPI_Interpolate, GeomAPI_ProjectPointOnCurve
    from OCP.OCP.collections import HArray1_gp_Pnt

    def z(r):
        return z0 + float(shape.sag(np.array(r) ** 2))

    p0, p1 = _pnt(0, 0, z(0.0)), _pnt(h, 0, z(h))
    c, k, asph = shape.curvature, shape.conic, [a for a in shape.aspheric if a != 0.0]
    if hasattr(shape, "kind"):  # Q-type asphere: always the interpolating spline
        asph = [1.0]
    if c == 0.0 and not asph:
        return BRepBuilderAPI_MakeEdge(p0, p1).Edge(), 0.0, "plane"
    if k == 0.0 and not asph:
        arc = GC_MakeArcOfCircle(p0, _pnt(h / 2, 0, z(h / 2)), p1).Value()
        return BRepBuilderAPI_MakeEdge(arc).Edge(), 0.0, "sphere"
    n = 81
    rs = np.linspace(0.0, h, n)
    arr = HArray1_gp_Pnt(1, n)
    for i, r in enumerate(rs):
        arr.SetValue(i + 1, _pnt(r, 0, z(r)))
    it = GeomAPI_Interpolate(arr, False, 1e-9)
    it.Perform()
    if not it.IsDone():
        raise CadError("B-spline interpolation of an aspheric profile failed")
    curve = it.Curve()
    dev = 0.0
    for r in 0.5 * (rs[1:] + rs[:-1]):
        proj = GeomAPI_ProjectPointOnCurve(_pnt(r, 0, z(r)), curve)
        if proj.NbPoints():
            dev = max(dev, proj.LowerDistance())
    return BRepBuilderAPI_MakeEdge(curve).Edge(), float(dev), "conic" if not asph else "asphere"


def _revolve_profile(edges):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt

    w = BRepBuilderAPI_MakeWire()
    for e in edges:
        w.Add(e)
    if not w.IsDone():
        raise CadError("Profile wire is not closed")
    face = BRepBuilderAPI_MakeFace(w.Wire(), True).Face()
    return BRepPrimAPI_MakeRevol(face, gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 2 * math.pi, False).Shape()


def _seg(a, b):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge

    return BRepBuilderAPI_MakeEdge(_pnt(*a), _pnt(*b)).Edge()


def _frame_trsf(frame):
    from OCP.gp import gp_Trsf

    m, o = frame.matrix, frame.origin
    t = gp_Trsf()
    t.SetValues(m[0][0], m[0][1], m[0][2], o[0], m[1][0], m[1][1], m[1][2], o[1], m[2][0], m[2][1], m[2][2], o[2])
    return t


def _place(shape, trsf):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

    return BRepBuilderAPI_Transform(shape, trsf, True).Shape()


def _asset_trsf(transform: dict):
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

    t = gp_Trsf()
    t.SetTranslation(gp_Vec(*[float(v) for v in transform.get("translate", [0, 0, 0])]))
    rx, ry, rz = [math.radians(float(v)) for v in transform.get("rotate_deg", [0, 0, 0])]
    for axis, ang in ((gp_Dir(1, 0, 0), rx), (gp_Dir(0, 1, 0), ry), (gp_Dir(0, 0, 1), rz)):
        r = gp_Trsf()
        r.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), axis), ang)
        t.Multiply(r)  # t = T * Rx * Ry * Rz  (Rz applied first, Three.js 'XYZ')
    return t


def shape_properties(shape) -> dict:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    gs = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, gs)
    has_solid = TopExp_Explorer(shape, TopAbs_SOLID).More()
    vol = None
    if has_solid:
        gv = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, gv)
        vol = float(gv.Mass())
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, b, False, False)
    if b.IsVoid():
        lo = hi = [0.0, 0.0, 0.0]
    else:
        a_, b_ = b.CornerMin(), b.CornerMax()
        lo, hi = [a_.X(), a_.Y(), a_.Z()], [b_.X(), b_.Y(), b_.Z()]
    return {"area_mm2": float(gs.Mass()), "volume_mm3": vol, "bbox_min": lo, "bbox_max": hi, "solid": has_solid}


# ----------------------------------------------------------------------
# export
# ----------------------------------------------------------------------
GLASS_RGB = (0.62, 0.80, 1.0)
MIRROR_RGB = (0.80, 0.82, 0.86)
SPACER_RGB = (0.35, 0.37, 0.40)
FIELD_RGB = [(0.15, 0.39, 0.92), (0.09, 0.64, 0.29), (0.86, 0.15, 0.15), (0.58, 0.2, 0.92), (0.92, 0.35, 0.05)]


def build_optics(cs, sd: np.ndarray, rim_margin: float = 0.0, include_stop: bool = True, include_image: bool = True, include_rays: bool = True, pupil=None) -> tuple[list[dict], dict]:
    """Solids/curves for the optical system: list of {name, shape, rgb, kind} and a report."""
    _occ()
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeWire
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt

    from ..analysis.evaluate import lens_elements, layout_rays

    items: list[dict] = []
    report = {"solids": [], "skipped": [], "max_profile_deviation_mm": 0.0, "notes": []}
    surfs = cs.model.surfaces
    n = cs.n_surfaces
    wl = cs.model.primary_wavelength
    lens_no = 0
    for el in lens_elements(cs):
        i, j = el["front"], el["back"]
        t = float(surfs[i].thickness or 0.0)
        fs, bs = cs.shapes[i], cs.shapes[j]
        try:
            if hasattr(fs, "curvature_x") or hasattr(bs, "curvature_x"):
                raise CadError("biconic and Zernike surfaces are not rotationally symmetric and cannot be exported as revolved solids yet")
            from ..analysis.elements import element_geometry

            try:
                geo = element_geometry(cs, sd, i, rim_margin)
            except ValueError as exc:
                raise CadError(str(exc)) from exc
            h = geo["rim_radius_mm"]
            ends = geo["profile_ends_mm"]
            cf, cb = geo["chamfers_mm"]
            for s_, nm, e in ((fs, i, ends[0]), (bs, j, ends[1])):
                if s_.curvature != 0.0 and s_.conic == 0.0 and not any(s_.aspheric) and e >= abs(1.0 / s_.curvature) * (1 - 1e-9):
                    raise CadError(f"rim radius {e:.4g} mm exceeds the radius of curvature of surface {nm}")
                if float(s_._root_term(e * e)) < 0:
                    raise CadError(f"rim radius {e:.4g} mm is beyond the conic's extent on surface {nm}")
            edge = geo["edge_thickness_mm"]
            if edge * (1 if t >= 0 else -1) <= 1e-6:
                raise CadError(f"edge thickness {edge:.4g} mm at the rim is not positive")

            def side(shape, z0, end, c, direction):
                """Edges of one face from the axis to the rim: profile, flat, chamfer; returns (edges, rim point z, dev, kind)."""
                stop = min(end, h - c) if c > 0 else end
                e_prof, dev, kind = _profile_edge(shape, stop, z0)
                edges = [e_prof]
                z_end = z0 + float(shape.sag(stop * stop))
                r_end = stop
                if r_end < h - c - 1e-12:  # flat out to the rim (or to the chamfer)
                    edges.append(_seg((r_end, 0, z_end), (h - c, 0, z_end)))
                    r_end = h - c
                if c > 0:
                    z_rim = z0 + float(shape.sag(min(end, h) ** 2))
                    edges.append(_seg((r_end, 0, z_end), (h, 0, z_rim + direction * c)))
                    return edges, z_rim + direction * c, dev, kind
                return edges, z_end, dev, kind

            front, zf_rim, d1, k1 = side(fs, 0.0, ends[0], cf, 1.0)
            back, zb_rim, d2, k2 = side(bs, t, ends[1], cb, -1.0)
            z_axis_back = t + float(bs.sag(0.0))
            solid = _revolve_profile([*front, _seg((h, 0, zf_rim), (h, 0, zb_rim)), *back[::-1], _seg((0, 0, z_axis_back), (0, 0, 0.0))])
        except (CadError, Exception) as exc:  # noqa: BLE001 - report every failure as a diagnostic
            report["skipped"].append({"surfaces": [i, j], "reason": str(exc)})
            continue
        lens_no += 1
        name = f"L{lens_no} {el['material']} (S{i}-S{j})"
        shp = _place(solid, _frame_trsf(cs.frames[i]))
        items.append({"name": name, "shape": shp, "rgb": GLASS_RGB, "kind": "lens"})
        report["max_profile_deviation_mm"] = max(report["max_profile_deviation_mm"], d1, d2)
        report["solids"].append({"name": name, "surfaces": [i, j], "rim_radius_mm": h, "front": k1, "back": k2, "element_volume_mm3": geo["volume_mm3"], **shape_properties(shp)})

    mir = 0
    for i in range(1, n - 1):
        if not cs.is_mirror[i]:
            continue
        h = float(sd[i]) + rim_margin
        s_ = cs.shapes[i]
        try:
            direction = 1.0 if cs.n_signed[wl, i - 1] > 0 else -1.0  # light travels +z locally -> substrate at +z
            zf_h = float(s_.sag(h * h))
            d = max(2.0, 0.1 * 2 * h)
            zb = (max(0.0, zf_h) + d) if direction > 0 else (min(0.0, zf_h) - d)
            e_front, dev, kind = _profile_edge(s_, h, 0.0)
            solid = _revolve_profile([e_front, _seg((h, 0, zf_h), (h, 0, zb)), _seg((h, 0, zb), (0, 0, zb)), _seg((0, 0, zb), (0, 0, 0.0))])
        except Exception as exc:  # noqa: BLE001
            report["skipped"].append({"surfaces": [i], "reason": str(exc)})
            continue
        mir += 1
        name = f"M{mir} mirror (S{i})"
        shp = _place(solid, _frame_trsf(cs.frames[i]))
        items.append({"name": name, "shape": shp, "rgb": MIRROR_RGB, "kind": "mirror"})
        report["max_profile_deviation_mm"] = max(report["max_profile_deviation_mm"], dev)
        report["solids"].append({"name": name, "surfaces": [i], "rim_radius_mm": h, "front": kind, "back": "plane", **shape_properties(shp)})

    if include_stop and pupil is not None:
        st = cs.stop
        circ = gp_Circ(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), max(pupil.r_stop, 1e-6))
        wire = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(circ).Edge()).Wire()
        items.append({"name": f"Aperture stop (S{st}, r = {pupil.r_stop:.4f} mm)", "shape": _place(wire, _frame_trsf(cs.frames[st])), "rgb": (0.1, 0.1, 0.1), "kind": "stop"})
    if include_image:
        ri = float(max(sd[n - 1], 1e-3))
        circ = gp_Circ(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), ri)
        face = BRepBuilderAPI_MakeFace(BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(circ).Edge()).Wire(), True).Face()
        items.append({"name": f"Image plane (S{n - 1})", "shape": _place(face, _frame_trsf(cs.frames[n - 1])), "rgb": (0.55, 0.55, 0.55), "kind": "image"})
    if include_rays and pupil is not None:
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Compound

        rays = [r for r in layout_rays(cs, pupil, 7, "meridional") if r["wavelength"] == wl]
        L = max(10.0, 0.15 * (float(cs.frames[n - 1].origin[2]) - float(cs.frames[1].origin[2])))
        for f in sorted({r["field"] for r in rays}):
            comp = TopoDS_Compound()
            bld = BRep_Builder()
            bld.MakeCompound(comp)
            count = 0
            for r in (x for x in rays if x["field"] == f):
                pts = [p for p in r["points"]]
                if surfs[0].thickness is None and pts:
                    p, d = np.array(pts[1] if len(pts) > 1 else pts[0]), np.array(r["start_dir"])
                    pts = [(p - d * L).tolist(), *pts[1:]]
                if len(pts) < 2:
                    continue
                poly = BRepBuilderAPI_MakePolygon()
                last = None
                for p in pts:
                    if last is not None and np.linalg.norm(np.subtract(p, last)) < 1e-9:
                        continue
                    poly.Add(_pnt(*p))
                    last = p
                if poly.IsDone():
                    bld.Add(comp, poly.Wire())
                    count += 1
            if count:
                items.append({"name": f"Rays field {f + 1}", "shape": comp, "rgb": FIELD_RGB[f % len(FIELD_RGB)], "kind": "rays"})
    if report["max_profile_deviation_mm"] > 0:
        report["notes"].append(f"Conic/aspheric profiles are B-spline interpolations; maximum deviation from the exact sag {report['max_profile_deviation_mm']:.2e} mm")
    if not cs.axial:
        report["notes"].append("Folded/decentred system: every element is placed in the global frame of its surface")
    return items, report


def mechanics_layout(cs, sd: np.ndarray, rim_margin: float = 0.0) -> dict:
    """Spacers, cells and a simple barrel for the lens elements (axial systems without mirrors only).

    * Barrel: a tube whose bore is the largest element rim, wall max(1 mm, 10 % of the bore), from the
      front rim of the first element to the back rim of the last.
    * Cells: an element with a smaller rim sits in a ring from its rim to the bore, as long as its edge.
    * Spacers between consecutive elements separated by air: outer radius = the bore; the ends are flat
      and touch each lens where it protrudes most between the spacer's bore and the lens rim (or the
      cell when the bore is outside the rim); the bore is the upper bound of the radius of every ray
      that passes the clear apertures of the surfaces in the gap: a ray's distance from the axis is
      convex along its path, so it lies under the chords through the aperture edges (taken at both ends
      of each surface's sag span), sampled as a polyline on or above that bound."""
    from ..analysis.elements import _profile, element_geometry
    from ..analysis.evaluate import lens_elements

    out = {"spacers": [], "cells": [], "barrel": None, "notes": []}
    if not cs.axial or np.any(cs.is_mirror[1:-1]) or np.any(cs.is_cb):
        out["notes"].append("Spacers and barrel are built only for axial systems without mirrors or coordinate breaks")
        return out
    z0 = [float(f.origin[2]) for f in cs.frames]
    els = []
    for el in lens_elements(cs):
        try:
            els.append(element_geometry(cs, sd, el["front"], rim_margin))
        except ValueError:
            continue
    if not els:
        return out
    Rb = max(g["rim_radius_mm"] for g in els)
    w = max(1.0, 0.1 * Rb)

    def rim_z(g, side):
        return z0[g["surfaces"][side]] + g["sag_rim_mm"][side]

    zmin = min(rim_z(g, 0) for g in els)
    zmax = max(rim_z(g, 1) for g in els)
    out["barrel"] = {"inner_radius_mm": Rb, "outer_radius_mm": Rb + w, "z_start_mm": zmin, "z_end_mm": zmax, "volume_mm3": math.pi * ((Rb + w) ** 2 - Rb**2) * (zmax - zmin)}
    for g in els:
        R = g["rim_radius_mm"]
        if R < Rb - 1e-6:
            za, zb = rim_z(g, 0), rim_z(g, 1)
            out["cells"].append({"element_surfaces": g["surfaces"], "inner_radius_mm": R, "outer_radius_mm": Rb, "z_start_mm": za, "z_end_mm": zb, "volume_mm3": math.pi * (Rb**2 - R**2) * (zb - za)})

    def contact(g, side, k, r_in):
        """z where a spacer end touches the element: its face's extreme between r_in and its rim."""
        R = g["rim_radius_mm"]
        if r_in >= R:
            return rim_z(g, side)
        rr = np.linspace(r_in, R, 64)
        prof = z0[k] + _profile(cs.shapes[k], g["profile_ends_mm"][side])(rr)
        return float(np.max(prof)) if side == 1 else float(np.min(prof))

    for g1, g2 in zip(els[:-1], els[1:]):
        j, i2 = g1["surfaces"][1], g2["surfaces"][0]
        if j >= i2:  # cemented: no spacer
            continue
        ks = list(range(j, i2 + 1))
        rs = np.array([float(sd[k]) for k in ks])
        zsag = np.array([z0[k] + float(cs.shapes[k].sag(sd[k] ** 2)) for k in ks])
        zlo = np.minimum([z0[k] for k in ks], zsag)
        zhi = np.maximum([z0[k] for k in ks], zsag)
        za = contact(g1, 1, j, float(rs[0]))
        zb = contact(g2, 0, i2, float(rs[-1]))
        if zb - za <= 1e-6:
            out["notes"].append(f"No room for a spacer between surfaces {j} and {i2}")
            continue

        def bound(z):
            """Upper bound of a passing ray's radius at z: a ray crosses surface k somewhere in [zlo, zhi]
            within sd, and its radius is convex in z, so it stays under the chords through the aperture
            edges at the low and at the high ends of the sag spans, and under each sd across its span."""
            z = np.asarray(z, dtype=float)
            b = np.maximum(np.interp(z, zlo, rs), np.interp(z, zhi, rs))
            for r_, lo, hi in zip(rs, zlo, zhi):
                b = np.where((z >= lo) & (z <= hi), np.maximum(b, r_), b)
            return b

        # the bound is convex between its breakpoints, so the polyline through these samples lies on or above it
        knots = np.unique(np.concatenate([[za, zb], zlo, zhi]))
        knots = knots[(knots >= za) & (knots <= zb)]
        zz = np.unique(np.concatenate([np.linspace(a_, b_, 9) for a_, b_ in zip(knots[:-1], knots[1:])])) if len(knots) > 1 else np.array([za, zb])
        pts = [(float(r), float(z)) for r, z in zip(bound(zz), zz)]
        if max(r for r, _ in pts) >= Rb - 0.2:
            out["notes"].append(f"No room for a spacer between surfaces {j} and {i2} (its wall would be under 0.2 mm)")
            continue
        vol = math.pi * Rb**2 * (zb - za) - sum(math.pi * (z1 - z0_) * (r0 * r0 + r0 * r1 + r1 * r1) / 3.0 for (r0, z0_), (r1, z1) in zip(pts[:-1], pts[1:]))
        out["spacers"].append({"between": [j, i2], "bore": [[r, z] for r, z in pts], "inner_radius_mm": min(r for r, _ in pts), "outer_radius_mm": Rb, "z_start_mm": za, "z_end_mm": zb, "length_mm": zb - za, "volume_mm3": vol})
    return out


def _revolve_polygon(points: list[tuple[float, float]]):
    """Solid of revolution of a closed polygon given as (r, z) points."""
    pts = [(float(r), 0.0, float(z)) for r, z in points]
    return _revolve_profile([_seg(p, q) for p, q in zip(pts, pts[1:] + pts[:1])])


def build_mechanics(cs, sd: np.ndarray, rim_margin: float = 0.0) -> tuple[list[dict], dict]:
    """Solids of the spacers, cells and the barrel (mechanics_layout)."""
    _occ()
    lay = mechanics_layout(cs, sd, rim_margin)
    items = []
    for k, sp in enumerate(lay["spacers"]):
        Rb = sp["outer_radius_mm"]
        poly = [(r, z) for r, z in sp["bore"]] + [(Rb, sp["z_end_mm"]), (Rb, sp["z_start_mm"])]
        shp = _revolve_polygon(poly)
        sp["solid_volume_mm3"] = shape_properties(shp)["volume_mm3"]
        items.append({"name": f"Spacer {k + 1} (S{sp['between'][0]}-S{sp['between'][1]})", "shape": shp, "rgb": SPACER_RGB, "kind": "spacer"})
    for k, c in enumerate(lay["cells"]):
        shp = _revolve_polygon([(c["inner_radius_mm"], c["z_start_mm"]), (c["outer_radius_mm"], c["z_start_mm"]), (c["outer_radius_mm"], c["z_end_mm"]), (c["inner_radius_mm"], c["z_end_mm"])])
        c["solid_volume_mm3"] = shape_properties(shp)["volume_mm3"]
        items.append({"name": f"Cell {k + 1} (S{c['element_surfaces'][0]}-S{c['element_surfaces'][1]})", "shape": shp, "rgb": SPACER_RGB, "kind": "cell"})
    b = lay["barrel"]
    if b:
        shp = _revolve_polygon([(b["inner_radius_mm"], b["z_start_mm"]), (b["outer_radius_mm"], b["z_start_mm"]), (b["outer_radius_mm"], b["z_end_mm"]), (b["inner_radius_mm"], b["z_end_mm"])])
        b["solid_volume_mm3"] = shape_properties(shp)["volume_mm3"]
        items.append({"name": "Barrel", "shape": shp, "rgb": SPACER_RGB, "kind": "barrel"})
    return items, lay


def _stl_shell(positions: np.ndarray, indices: np.ndarray):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_Sewing

    sew = BRepBuilderAPI_Sewing(1e-6)
    for a, b, c in indices:
        pa, pb, pc = positions[a], positions[b], positions[c]
        if np.linalg.norm(np.cross(pb - pa, pc - pa)) < 1e-14:
            continue
        poly = BRepBuilderAPI_MakePolygon(_pnt(*pa), _pnt(*pb), _pnt(*pc), True)
        sew.Add(BRepBuilderAPI_MakeFace(poly.Wire(), True).Face())
    sew.Perform()
    return sew.SewedShape()


def asset_shapes(assets: list[dict]) -> tuple[list[dict], list[str]]:
    """Shapes of imported CAD assets with their placement (for export)."""
    from ..io.stl import decode_mesh

    items, notes = [], []
    for a in assets:
        if not a.get("visible", True):
            notes.append(f"Hidden CAD model '{a['name']}' not exported")
            continue
        trsf = _asset_trsf(a.get("transform") or {})
        rgb = tuple(int(a.get("color", "#9aa7b4")[k : k + 2], 16) / 255 for k in (1, 3, 5))
        fmt = a.get("format", "stl")
        if fmt in ("step", "iges") and a.get("source_b64"):
            shape, _names = _read_shape(base64.b64decode(a["source_b64"]), fmt)
        elif fmt == "stl":
            if a["mesh"]["triangles"] > MAX_STL_EXPORT_TRIANGLES:
                notes.append(f"STL model '{a['name']}' has {a['mesh']['triangles']} triangles (> {MAX_STL_EXPORT_TRIANGLES}); not exported")
                continue
            p, i = decode_mesh(a["mesh"]["positions_b64"], a["mesh"]["indices_b64"])
            shape = _stl_shell(p.astype(float), i)
        else:
            notes.append(f"CAD model '{a['name']}' has no source geometry; not exported")
            continue
        items.append({"name": a["name"], "shape": _place(shape, trsf), "rgb": rgb, "kind": "cad"})
    return items, notes


def write_cad(items: list[dict], fmt: str) -> bytes:
    """Write named, coloured items to STEP (AP214) or IGES (B-rep) bytes."""
    _occ()
    from OCP.IGESCAFControl import IGESCAFControl_Writer
    from OCP.Interface import Interface_Static
    from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_StepModelType
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

    if fmt not in ("step", "iges"):
        raise CadError(f"Unknown CAD format '{fmt}'")
    doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    for it in items:
        lab = st.AddShape(it["shape"], False)
        TDataStd_Name.Set_s(lab, TCollection_ExtendedString(it["name"]))
        r, g, b = it["rgb"]
        col = Quantity_Color(r, g, b, Quantity_TypeOfColor.Quantity_TOC_RGB)
        ct.SetColor(lab, col, XCAFDoc_ColorType.XCAFDoc_ColorSurf)
        ct.SetColor(lab, col, XCAFDoc_ColorType.XCAFDoc_ColorCurv)
    tmp = tempfile.mkdtemp(prefix="opticore_cad_")
    path = os.path.join(tmp, "out." + ("step" if fmt == "step" else "igs"))
    try:
        if fmt == "step":
            Interface_Static.SetCVal_s("write.step.unit", "MM")
            Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
            w = STEPCAFControl_Writer()
            w.SetNameMode(True)
            w.SetColorMode(True)
            if not w.Transfer(doc, STEPControl_StepModelType.STEPControl_AsIs):
                raise CadError("STEP transfer failed")
            if int(w.Write(path)) != 1:  # IFSelect_RetDone
                raise CadError("Writing the STEP file failed")
        else:
            Interface_Static.SetCVal_s("write.iges.unit", "MM")
            Interface_Static.SetIVal_s("write.iges.brep.mode", 1)
            w = IGESCAFControl_Writer()
            w.SetNameMode(True)
            w.SetColorMode(True)
            if not w.Transfer(doc):
                raise CadError("IGES transfer failed")
            if not w.Write(path):
                raise CadError("Writing the IGES file failed")
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(path)
            os.rmdir(tmp)
        except OSError:
            pass


def export_system_cad(cs, fmt: str, cad_assets: list[dict] | None = None, rim_margin: float = 0.0, include_stop: bool = True, include_image: bool = True, include_rays: bool = True, include_cad: bool = True, include_mechanics: bool = False) -> dict:
    from ..analysis.evaluate import auto_semi_diameters, effective_semi_diameters
    from ..paraxial import compute_pupil

    pupil = compute_pupil(cs)
    sd = effective_semi_diameters(cs, auto_semi_diameters(cs, pupil))
    items, report = build_optics(cs, sd, rim_margin, include_stop, include_image, include_rays, pupil)
    if include_mechanics:
        mech, lay = build_mechanics(cs, sd, rim_margin)
        items += mech
        report["mechanics"] = {"spacers": lay["spacers"], "cells": lay["cells"], "barrel": lay["barrel"]}
        report["notes"] += lay["notes"]
    if include_cad and cad_assets:
        extra, notes = asset_shapes(cad_assets)
        items += extra
        report["notes"] += notes
        report["cad_models"] = [x["name"] for x in extra]
    if not items:
        raise CadError("Nothing to export")
    data = write_cad(items, fmt)
    report["items"] = [{"name": x["name"], "kind": x["kind"]} for x in items]
    report["bytes"] = len(data)
    report["format"] = fmt
    report["units"] = "mm"
    return {"data_base64": base64.b64encode(data).decode("ascii"), "report": report}


# ----------------------------------------------------------------------
# import
# ----------------------------------------------------------------------
def _read_shape(data: bytes, fmt: str):
    """Read STEP/IGES bytes; returns (compound shape, [(name, shape)] of top-level bodies)."""
    _occ()
    from OCP.BRep import BRep_Builder
    from OCP.IGESCAFControl import IGESCAFControl_Reader
    from OCP.Interface import Interface_Static
    from OCP.OCP.collections import Sequence_TDF_Label
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopoDS import TopoDS_Compound
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    if len(data) > MAX_SOURCE_BYTES:
        raise CadError(f"File larger than {MAX_SOURCE_BYTES // (1024 * 1024)} MB")
    tmp = tempfile.mkdtemp(prefix="opticore_cad_")
    path = os.path.join(tmp, "in." + ("step" if fmt == "step" else "igs"))
    with open(path, "wb") as f:
        f.write(data)
    try:
        Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
        doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
        rd = STEPCAFControl_Reader() if fmt == "step" else IGESCAFControl_Reader()
        rd.SetNameMode(True)
        if int(rd.ReadFile(path)) != 1:
            raise CadError(f"The file could not be read as {fmt.upper()}")
        if not rd.Transfer(doc):
            raise CadError(f"No geometry could be transferred from the {fmt.upper()} file")
        st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
        labels = Sequence_TDF_Label()
        st.GetFreeShapes(labels)
        bodies = []
        for k in range(1, labels.Length() + 1):
            lab = labels.Value(k)
            shp = XCAFDoc_ShapeTool.GetShape_s(lab)
            name = f"Body {k}"
            attr = TDataStd_Name()
            if lab.FindAttribute(TDataStd_Name.GetID_s(), attr):
                txt = attr.Get().ToExtString()
                if txt:
                    name = str(txt)
            bodies.append((name, shp))
        if not bodies:
            raise CadError("The file contains no shapes")
        comp = TopoDS_Compound()
        b = BRep_Builder()
        b.MakeCompound(comp)
        for _, s in bodies:
            b.Add(comp, s)
        return comp, bodies
    finally:
        try:
            os.remove(path)
            os.rmdir(tmp)
        except OSError:
            pass


def _solidify(shape, tol: float = 1e-4):
    """Sew loose faces (typical for IGES) and turn closed shells into solids.

    Returns (shape, repaired: bool). Bodies that already contain solids are
    returned unchanged; open surface models stay surfaces."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    if TopExp_Explorer(shape, TopAbs_SOLID).More() or not TopExp_Explorer(shape, TopAbs_FACE).More():
        return shape, False
    sew = BRepBuilderAPI_Sewing(tol)
    sew.Add(shape)
    sew.Perform()
    sewn = sew.SewedShape()
    ex = TopExp_Explorer(sewn, TopAbs_SHELL)
    solids = []
    while ex.More():
        sh = TopoDS.Shell(ex.Current())
        if BRep_Tool.IsClosed_s(sh):
            mk = BRepBuilderAPI_MakeSolid(sh)
            if mk.IsDone():
                so = mk.Solid()
                g = GProp_GProps()
                BRepGProp.VolumeProperties_s(so, g)
                if g.Mass() < 0:
                    so = TopoDS.Solid(so.Reversed())
                solids.append(so)
        ex.Next()
    if not solids:
        return sewn, False
    if len(solids) == 1:
        return solids[0], True
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    comp = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(comp)
    for so in solids:
        b.Add(comp, so)
    return comp, True


def _tessellate(shape, deflection: float) -> tuple[np.ndarray, np.ndarray]:
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_Orientation
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    BRepMesh_IncrementalMesh(shape, deflection, False, 0.35, True)
    pos: list[np.ndarray] = []
    idx: list[np.ndarray] = []
    base = 0
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        face = TopoDS.Face(ex.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None:
            trsf = loc.Transformation()
            nn = tri.NbNodes()
            p = np.empty((nn, 3))
            for k in range(1, nn + 1):
                q = tri.Node(k).Transformed(trsf)
                p[k - 1] = (q.X(), q.Y(), q.Z())
            t = np.empty((tri.NbTriangles(), 3), dtype=np.int64)
            for k in range(1, tri.NbTriangles() + 1):
                a, b_, c = tri.Triangle(k).Get()
                t[k - 1] = (a - 1, b_ - 1, c - 1)
            if face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED:
                t = t[:, [0, 2, 1]]
            pos.append(p)
            idx.append(t + base)
            base += nn
        ex.Next()
    if not pos:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    return np.vstack(pos), np.vstack(idx)


def import_cad(data: bytes, filename: str) -> dict:
    ext = os.path.splitext(filename.lower())[1]
    fmt = {".step": "step", ".stp": "step", ".iges": "iges", ".igs": "iges"}.get(ext)
    if fmt is None:
        raise CadError("Unsupported CAD file type (use .step/.stp or .iges/.igs; STL has its own importer)")
    if len(data) > MAX_SOURCE_BYTES:
        raise CadError(f"File larger than {MAX_SOURCE_BYTES // (1024 * 1024)} MB")
    from .cad_assembly import count_parts, leaves, read_tree, tessellate_tree

    roots = read_tree(data, fmt)
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    comp = TopoDS_Compound()
    bb = BRep_Builder()
    bb.MakeCompound(comp)
    for leaf, _ in leaves(roots):
        bb.Add(comp, leaf.shape)
    props = shape_properties(comp)
    diag = float(np.linalg.norm(np.subtract(props["bbox_max"], props["bbox_min"])))
    deflection = max(0.005, 1e-3 * diag)
    p, t, tree = tessellate_tree(roots, deflection)
    if len(t) == 0:
        raise CadError("The model has no faces to display (curves or points only)")
    diagnostics = []
    # top-level bodies (summary rows kept for lens recognition and the CAD table)
    body_rows = [{"name": n["name"], "solids": n["solids"], "volume_mm3": n["volume_mm3"], "area_mm2": n["area_mm2"], "bbox_min": n["bbox_min"], "bbox_max": n["bbox_max"]} for n in tree]
    n_solids = sum(n["solids"] for n in tree)
    n_parts = count_parts(tree)
    if n_solids == 0:
        diagnostics.append({"level": "info", "code": "NO_SOLIDS", "message": "The file contains no solids (surfaces only)"})
    if any(n["kind"] == "assembly" for n in tree):
        diagnostics.append({"level": "info", "code": "ASSEMBLY", "message": f"Assembly structure read: {n_parts} part instance(s) in {len(tree)} top-level node(s)"})
    diagnostics.append({"level": "info", "code": "DISPLAY_MESH", "message": f"Display mesh: {len(t)} triangles, linear deflection {deflection:.3g} mm (exact B-rep kept for export)"})
    diagnostics.append({"level": "info", "code": "NOT_AN_OPTICAL_SURFACE", "message": "CAD geometry is not part of the optical prescription and is not ray traced"})
    return {
        "name": os.path.splitext(os.path.basename(filename))[0],
        "format": fmt,
        "units": "mm",
        "triangles": int(len(t)),
        "vertices": int(len(p)),
        "bbox_min": props["bbox_min"],
        "bbox_max": props["bbox_max"],
        "size": list(np.subtract(props["bbox_max"], props["bbox_min"])),
        "surface_area_mm2": props["area_mm2"],
        "volume_mm3": props["volume_mm3"],
        "closed": n_solids > 0,
        "bodies": body_rows,
        "tree": tree,
        "parts": n_parts,
        "mesh_deflection_mm": deflection,
        "diagnostics": diagnostics,
        "positions_b64": base64.b64encode(p.astype("<f4").tobytes()).decode("ascii"),
        "indices_b64": base64.b64encode(t.astype("<u4").tobytes()).decode("ascii"),
        "source_b64": base64.b64encode(data).decode("ascii"),
    }
