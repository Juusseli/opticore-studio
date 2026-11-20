"""STL import (binary and ASCII) for CAD geometry.

STL stores an unindexed triangle soup without units. The importer

  * detects binary vs ASCII (a binary file's size is exactly
    84 + 50 * n_triangles; "solid" at the start alone is not trusted),
  * scales by the user-chosen length unit to mm,
  * merges coincident vertices (exact float32 equality after scaling) into an
    indexed mesh,
  * reports diagnostics: degenerate (zero-area) triangles, facet normals that
    disagree with the vertex winding, boundary and non-manifold edges
    (closed = every edge shared by exactly two triangles), consistent
    orientation, and the enclosed volume by the divergence theorem (only
    meaningful for closed meshes; negative volume = inward-facing normals).

The mesh is CAD geometry only: it is not part of the optical prescription
and is not ray traced. Triangulation is the CAD exporter's approximation of
the true surfaces, so it must not be used as an exact optical surface.
"""

from __future__ import annotations

import base64
import re
import struct
from collections import Counter

import numpy as np

UNIT_TO_MM = {"mm": 1.0, "um": 1e-3, "cm": 10.0, "m": 1000.0, "in": 25.4}
MAX_TRIANGLES = 2_000_000


class StlError(ValueError):
    pass


def _parse_binary(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    n = struct.unpack_from("<I", data, 80)[0]
    rec = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    arr = np.frombuffer(data, dtype=rec, count=n, offset=84)
    return arr["v"].astype(np.float64), arr["n"].astype(np.float64)


_FLOAT = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def _parse_ascii(text: str) -> tuple[np.ndarray, np.ndarray]:
    facets = re.findall(
        rf"facet\s+normal\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s+outer\s+loop\s+"
        rf"vertex\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s+vertex\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s+vertex\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s+endloop\s+endfacet",
        text,
        flags=re.IGNORECASE,
    )
    n_facet_kw = len(re.findall(r"\bfacet\s+normal\b", text, flags=re.IGNORECASE))
    if not facets:
        raise StlError("No facets found in the ASCII STL file")
    if n_facet_kw != len(facets):
        raise StlError(f"Malformed ASCII STL: {n_facet_kw} facets declared but {len(facets)} could be parsed (only triangular facets are allowed)")
    a = np.array(facets, dtype=np.float64)
    return a[:, 3:].reshape(-1, 3, 3), a[:, :3]


def parse_stl(data: bytes, units: str = "mm", name: str = "") -> dict:
    if units not in UNIT_TO_MM:
        raise StlError(f"Unknown unit '{units}'")
    if len(data) < 15:
        raise StlError("File too small to be an STL file")
    diagnostics: list[dict] = []
    is_binary = len(data) >= 84 and 84 + 50 * struct.unpack_from("<I", data, 80)[0] == len(data)
    if is_binary:
        n = struct.unpack_from("<I", data, 80)[0]
        if n > MAX_TRIANGLES:
            raise StlError(f"{n} triangles exceed the import limit of {MAX_TRIANGLES}")
        tri, nrm = _parse_binary(data)
        fmt = "binary"
    else:
        try:
            text = data.decode("ascii")
        except UnicodeDecodeError as exc:
            raise StlError("Not a valid STL file (binary size does not match its triangle count and the content is not ASCII)") from exc
        if not text.lstrip().lower().startswith("solid"):
            raise StlError("Not a valid STL file (ASCII STL must start with 'solid')")
        tri, nrm = _parse_ascii(text)
        if len(tri) > MAX_TRIANGLES:
            raise StlError(f"{len(tri)} triangles exceed the import limit of {MAX_TRIANGLES}")
        fmt = "ascii"
    if not np.all(np.isfinite(tri)):
        raise StlError("The file contains non-finite vertex coordinates")
    s = UNIT_TO_MM[units]
    tri = tri * s

    # indexed mesh (exact float32 matches)
    f32 = tri.reshape(-1, 3).astype(np.float32)
    uniq, inv = np.unique(f32, axis=0, return_inverse=True)
    idx = inv.reshape(-1, 3).astype(np.uint32)

    e1 = tri[:, 1] - tri[:, 0]
    e2 = tri[:, 2] - tri[:, 0]
    cr = np.cross(e1, e2)
    area2 = np.linalg.norm(cr, axis=1)
    scale = max(float(np.ptp(tri.reshape(-1, 3), axis=0).max()), 1e-30)
    degenerate = area2 < 1e-12 * scale * scale
    area = float(0.5 * area2.sum())
    collapsed = (idx[:, 0] == idx[:, 1]) | (idx[:, 1] == idx[:, 2]) | (idx[:, 0] == idx[:, 2])
    n_deg = int(np.sum(degenerate | collapsed))
    if n_deg:
        diagnostics.append({"level": "warning", "code": "DEGENERATE_TRIANGLES", "message": f"{n_deg} degenerate (zero-area or collapsed) triangle(s)"})

    # facet normals vs winding
    nn = np.linalg.norm(nrm, axis=1)
    given = nn > 1e-9
    good = given & ~degenerate
    if np.any(good):
        dots = np.einsum("ij,ij->i", nrm[good] / nn[good, None], cr[good] / area2[good, None])
        flipped = int(np.sum(dots < 0))
        if flipped:
            diagnostics.append({"level": "info", "code": "NORMALS_DISAGREE", "message": f"{flipped} facet normal(s) disagree with the vertex winding (winding is used)"})

    # edges: closed / manifold / consistently oriented
    valid = idx[~collapsed]
    directed = np.concatenate([valid[:, [0, 1]], valid[:, [1, 2]], valid[:, [2, 0]]])
    undirected = np.sort(directed, axis=1)
    cnt = Counter(map(tuple, undirected.tolist()))
    boundary = sum(1 for c in cnt.values() if c == 1)
    nonmanifold = sum(1 for c in cnt.values() if c > 2)
    dcnt = Counter(map(tuple, directed.tolist()))
    misoriented = sum(1 for e, c in dcnt.items() if c > 1)  # same directed edge twice: inconsistent winding
    closed = boundary == 0 and nonmanifold == 0 and len(valid) > 0
    volume = None
    if closed:
        v = valid.astype(np.int64)
        p = uniq.astype(np.float64)
        volume = float(np.einsum("ij,ij->i", p[v[:, 0]], np.cross(p[v[:, 1]], p[v[:, 2]])).sum() / 6.0)
        if misoriented:
            diagnostics.append({"level": "warning", "code": "INCONSISTENT_WINDING", "message": f"{misoriented} edge(s) traversed twice in the same direction: triangle orientation is inconsistent; volume is unreliable"})
        elif volume < 0:
            diagnostics.append({"level": "warning", "code": "INWARD_NORMALS", "message": "Closed mesh with inward-facing triangles (negative enclosed volume)"})
    else:
        diagnostics.append({"level": "info", "code": "OPEN_MESH", "message": f"Mesh is not closed ({boundary} boundary edge(s), {nonmanifold} non-manifold edge(s)); volume not computed"})

    lo = uniq.min(axis=0).astype(float)
    hi = uniq.max(axis=0).astype(float)
    diagnostics.append({"level": "info", "code": "NOT_AN_OPTICAL_SURFACE", "message": "STL triangulation is CAD geometry only; it is not used as an exact optical surface or ray traced"})
    return {
        "name": name,
        "format": fmt,
        "units": units,
        "scale_to_mm": s,
        "triangles": int(len(tri)),
        "vertices": int(len(uniq)),
        "bbox_min": lo.tolist(),
        "bbox_max": hi.tolist(),
        "size": (hi - lo).tolist(),
        "surface_area_mm2": area,
        "volume_mm3": volume,
        "closed": closed,
        "diagnostics": diagnostics,
        "positions_b64": base64.b64encode(uniq.astype("<f4").tobytes()).decode("ascii"),
        "indices_b64": base64.b64encode(idx.astype("<u4").tobytes()).decode("ascii"),
    }


def decode_mesh(positions_b64: str, indices_b64: str) -> tuple[np.ndarray, np.ndarray]:
    p = np.frombuffer(base64.b64decode(positions_b64), dtype="<f4").reshape(-1, 3)
    i = np.frombuffer(base64.b64decode(indices_b64), dtype="<u4").reshape(-1, 3)
    if len(i) and int(i.max()) >= len(p):
        raise StlError("Mesh indices out of range")
    return p, i

