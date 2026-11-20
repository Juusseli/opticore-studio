"""Non-sequential ray tracing against exact CAD solids (OpenCascade B-rep).

Scene
-----
* The lens system (optional): every glass element as its exact revolved
  solid (the same solids as the STEP export) with its catalogue glass, every
  mirror as a reflecting solid. Thin-film coatings assigned to the
  sequential surfaces are applied to the matching lens/mirror faces (the
  hit point is matched to the surface sag); rims are uncoated.
* Imported CAD models with an optical role:
    absorber    rays end there (mounts, baffles, housings), unless the body
                scatters: then the diffuse reflectance rho is re-emitted
    mirror      every face reflects (R = 1, or the coating's R on its
                substrate)
    refractive  homogeneous medium with a catalogue/custom material
  Each body may carry a coating (all faces) and a surface scatter model.
  STEP/IGES models are traced against their exact B-rep. STL models are
  traced against their triangles (faceted normals): flagged approximate.
* A detector: a disc (or the image surface) in the image-surface frame.
  Rays that reach it are recorded and end.

Physics per intersection (nearest hit along the ray, exact line/face
intersection with IntCurvesFace; outward normals from BRepGProp_Face, so a
face's orientation decides inside/outside):
* entering / leaving a refractive solid: vector Snell law with the indices
  of the two media; touching faces of two solids (cemented interface) hand
  the ray directly from one glass to the other. Unpolarised power split from
  the bare Fresnel equations or, for a coated face, the thin-film R, T and
  absorptance A (absorbed in the coating); total internal reflection
  reflects all power (R from the stack for coated faces).
* splitting (optional): the reflected part continues as a separate ray when
  its power exceeds `min_power` and the event depth is below `max_events`;
  without splitting only the transmitted part is followed (and the
  reflected power is booked as "discarded reflections").
* surface scattering (Monte Carlo, one scattered ray per event carrying the
  scattered power; seeded and reproducible) with a BSDF (bsdf.py):
    lambertian  cosine-weighted directions about the surface normal
    gaussian    polar angle from the specular direction with a 2D Gaussian
                of per-axis width sigma (truncated at the surface)
    abg, harvey fitted BSDF models normalised to their TIS at normal
                incidence; the TIS at the actual incidence decides the power
  The scattered fraction: absorber -> diffuse reflectance (rest absorbed);
  mirror -> part of the reflected power (TIS); refractive -> part of the
  transmitted power that scatters forward.
* importance sampling (optional): at every scatter event `rays` extra rays
  aim at uniformly sampled points of a target disc or rectangle (a detector,
  or a surface's clear aperture) and carry the BSDF-weighted power of the
  target's cone, P_in f cos(theta_s) A cos(theta_t) / (r^2 rays); they are
  traced like any ray. The regular scattered ray is dropped when its
  direction points into that cone, so the two together cover every
  direction once (unbiased); the energy budget then balances only in
  expectation (`importance_added` vs `importance_dropped`).
* bulk absorption exp(-alpha L) inside refractive media, alpha at each ray's
  wavelength (the catalogue internal transmittance with catalog_absorption,
  else the material's constant), and indices of lens glass at its element's
  temperature, both as in the sequential trace; absorbers and the detector
  end the ray.
"Direct" light has followed only refractions, mirror reflections and TIR;
light that took a partial (Fresnel or coating) reflection at a refractive
face is counted as "after reflections" (ghosts), light that scattered at
least once as "after scattering".
Energy budget: detected (direct, after ghost reflections, after
scattering) + absorbed per object + coating absorption + escaped +
discarded + truncated + bulk = source power (checked).

Source: the sequential system's field and wavelength; rays launched through
an entrance-pupil disc overfilled by `overfill` (so mounts can clip the
beam), uniformly sampled; total source power 1.
Statistics: every ray inherits the index of its source ray; a detector's
power is a sum over independent source rays, so its standard error is
sqrt(N/(N-1) sum_i (X_i - mean X)^2) with X_i the power reaching it from source
ray i (also for its stray part and for each path of the path table, which
groups detected power by the sequence of scatter (S) and partial-reflection (R)
events and the objects where they happened).
This is geometric optics: no diffraction or polarisation; the scatter
models are fitted distributions, not BSDF measurements of the user's parts.
"""

from __future__ import annotations

import base64
import math
import time
from dataclasses import dataclass, field

import numpy as np

from .io.cad import _asset_trsf, _occ, _place, _read_shape, _solidify, _stl_shell
from .physics import reflect, refract, unpolarized_transmittance
from .environment import element_temperatures, medium_index
from .materials.catalog import MaterialError
from .system import CompiledSystem, NotApplicable, SystemError_, medium_absorption
from .thinfilm import get_coating, stack_rt

EPS = 1e-7  # mm: self-intersection guard
SAG_TOL = 1e-5  # mm: hit point on a coated sequential surface


@dataclass
class NsObject:
    name: str
    shape: object
    role: str  # absorber | mirror | refractive | detector
    material: str | None = None
    exact: bool = True
    absorbed: float = 0.0
    coating: object = None  # thinfilm.Coating on every face (CAD bodies)
    surface_coatings: list = field(default_factory=list)  # [(frame, shape, Coating)] faces of the lens system
    scatter: object = None  # bsdf.Bsdf (a legacy dict {"model", "fraction", "sigma"} is accepted)
    owner: str | None = None  # lens solids: id of the surface that starts their glass (element temperature); CAD bodies None


@dataclass
class Scene:
    objects: list[NsObject]
    intersector: object
    face_map: dict
    detector_frame: object
    detector_radius: float | None  # legacy detector face (role "detector"); None without one
    bbox_min: np.ndarray = None
    bbox_max: np.ndarray = None
    notes: list[str] = field(default_factory=list)
    detectors: list = field(default_factory=list)  # nssources.DetectorRT (analytic planes)


def _faces(shape):
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        yield TopoDS.Face(ex.Current())
        ex.Next()


def _scatter_spec(opt: dict, name: str):
    from .bsdf import MODELS, Bsdf

    sc = opt.get("scatter") or {}
    model = sc.get("model", "none")
    if model in (None, "none"):
        return None
    f = float(sc.get("fraction", 0.0))
    if not 0.0 <= f <= 1.0:
        raise SystemError_(f"CAD model '{name}': scatter fraction must be within 0…1")
    if f == 0.0:
        return None
    sig = math.radians(float(sc.get("sigma_deg", 5.0)))
    if model == "gaussian" and not 0.0 < sig <= math.pi / 2:
        raise SystemError_(f"CAD model '{name}': Gaussian scatter width must be within 0…90°")
    if model not in MODELS:
        raise SystemError_(f"CAD model '{name}': unknown scatter model '{model}'")
    try:
        def num(key, default):
            v = sc.get(key)
            return default if v is None else float(v)

        return Bsdf(model, f, sig, B=num("abg_b", 1e-3), g=num("abg_g", 2.0), l=num("harvey_l", 0.01), s=num("harvey_s", -2.0))
    except ValueError as exc:
        raise SystemError_(f"CAD model '{name}': {exc}") from exc


def _as_bsdf(sc):
    """A Bsdf from a scatter spec (Bsdf, or the legacy dict {model, fraction, sigma})."""
    from .bsdf import Bsdf

    if sc is None or isinstance(sc, Bsdf):
        return sc
    return Bsdf(sc["model"], float(sc["fraction"]), float(sc.get("sigma", 0.0)))


@dataclass
class ImportanceTarget:
    """A disc or rectangle that importance-sampled scatter rays aim at (centre, axes R with normal R[:, 2])."""

    name: str
    center: np.ndarray
    R: np.ndarray
    shape: str  # circle | rectangle
    hx: float  # circle: radius; rectangle: half width
    hy: float

    @property
    def area(self) -> float:
        return math.pi * self.hx * self.hx if self.shape == "circle" else 4.0 * self.hx * self.hy

    def sample(self, rng) -> np.ndarray:
        if self.shape == "circle":
            r, ph = self.hx * math.sqrt(rng.random()), 2 * math.pi * rng.random()
            loc = np.array([r * math.cos(ph), r * math.sin(ph), 0.0])
        else:
            loc = np.array([(2 * rng.random() - 1) * self.hx, (2 * rng.random() - 1) * self.hy, 0.0])
        return self.center + self.R @ loc

    def hit(self, Q: np.ndarray, d: np.ndarray) -> bool:
        p = self.R.T @ (Q - self.center)
        v = self.R.T @ d
        if abs(v[2]) < 1e-15:
            return False
        w = -p[2] / v[2]
        if w <= EPS:
            return False
        x, y = p[0] + w * v[0], p[1] + w * v[1]
        return (x * x + y * y <= self.hx * self.hx) if self.shape == "circle" else (abs(x) <= self.hx and abs(y) <= self.hy)


def importance_target(cs: CompiledSystem, scene: "Scene", spec: dict | None) -> ImportanceTarget | None:
    """The target of importance sampling: {"kind": "detector", "id": ...} (an enabled analytic detector of
    the scene), {"kind": "legacy"} (the detector disc on the image surface) or {"kind": "surface",
    "index": i} (the clear aperture of surface i, a disc at its vertex)."""
    if not spec or spec.get("kind") in (None, "none"):
        return None
    kind = spec["kind"]
    if kind == "detector":
        found = [d for d in scene.detectors if d.spec.id == spec.get("id")]
        if not found:
            raise SystemError_("Importance target: the detector is not in the scene (removed or disabled)")
        d = found[0]
        hx, hy = d.extent()
        return ImportanceTarget(d.spec.name, np.asarray(d.t, float), np.asarray(d.R, float), d.spec.shape, hx, hy)
    if kind == "legacy":
        if not scene.detector_radius:
            raise SystemError_("Importance target: the scene has no image-surface detector")
        fr = scene.detector_frame
        return ImportanceTarget("Detector", np.asarray(fr.origin, float), np.asarray(fr.matrix, float), "circle", scene.detector_radius, scene.detector_radius)
    if kind == "surface":
        from .analysis.evaluate import auto_semi_diameters, effective_semi_diameters
        from .paraxial import compute_pupil

        i = int(spec.get("index", 1))
        if not 0 < i < cs.n_surfaces:
            raise SystemError_(f"Importance target: there is no surface {i}")
        sd = effective_semi_diameters(cs, auto_semi_diameters(cs, compute_pupil(cs)))
        fr = cs.frames[i]
        return ImportanceTarget(f"Surface {i} aperture", np.asarray(fr.origin, float), np.asarray(fr.matrix, float), "circle", float(sd[i]), float(sd[i]))
    raise SystemError_(f"Importance target: unknown kind '{kind}'")


def standard_error(rids: np.ndarray, powers: np.ndarray, n: int) -> float:
    """Standard error of a power summed over n independent source rays (rids: the source ray of each hit)."""
    if n < 2 or len(powers) == 0:
        return 0.0
    X = np.bincount(np.asarray(rids, dtype=int), weights=np.asarray(powers, dtype=float), minlength=n)
    return float(math.sqrt(n / (n - 1) * float(((X - X.mean()) ** 2).sum())))


def path_table(hits_keys: list, rids: np.ndarray, powers: np.ndarray, n: int, total: float, top: int = 15) -> list[dict]:
    """Detected power grouped by event path (scatter S / partial reflection R events), largest first."""
    groups: dict[str, list[int]] = {}
    for k, key in enumerate(hits_keys):
        groups.setdefault(" → ".join(key) if key else "direct", []).append(k)
    rows = []
    for name, idx in groups.items():
        ii = np.array(idx)
        pw = float(powers[ii].sum())
        rows.append({"path": name, "power_w": pw, "fraction": pw / total if total > 0 else 0.0, "hits": len(idx), "sigma_w": standard_error(rids[ii], powers[ii], n)})
    rows.sort(key=lambda r: -r["power_w"])
    return rows[:top]


def build_scene(cs: CompiledSystem, cad_assets: list[dict], include_system: bool = True, detector_radius: float | None = None, custom_materials=(), detectors: list | None = None) -> Scene:
    """Scene of the lens system (as solids) and the CAD bodies with an optical role. With `detectors`
    (nssources.Detector list) the analytic detectors replace the default disc on the image surface."""
    _occ()
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt

    from .analysis.evaluate import auto_semi_diameters, effective_semi_diameters, lens_elements
    from .io.cad import _frame_trsf, build_optics
    from .io.stl import decode_mesh
    from .paraxial import compute_pupil

    pupil = compute_pupil(cs)
    sd = effective_semi_diameters(cs, auto_semi_diameters(cs, pupil))
    objects: list[NsObject] = []
    notes: list[str] = []
    coats = cs.coatings or [None] * cs.n_surfaces
    if include_system and cs.ideal and any(x is not None for x in cs.ideal):
        bad = [i for i, x in enumerate(cs.ideal) if x is not None]
        raise NotApplicable(f"Ideal lens surfaces ({', '.join(map(str, bad))}) have no physical geometry and cannot be traced non-sequentially; replace them with real lenses")
    if include_system:
        items, rep = build_optics(cs, sd, 0.0, False, False, False, pupil)
        els = {f"L{k + 1}": e for k, e in enumerate(lens_elements(cs))}
        mirrors = [i for i in range(1, cs.n_surfaces - 1) if cs.is_mirror[i]]
        built_mirrors = iter(i for i in mirrors)
        for it in items:
            if it["kind"] == "lens":
                key = it["name"].split(" ")[0]
                el = els.get(key)
                sc = []
                if el:
                    for j in (el["front"], el["back"]):
                        if coats[j] is not None:
                            sc.append((cs.frames[j], cs.shapes[j], coats[j]))
                owner = cs.model.surfaces[el["front"]].id if el else None
                objects.append(NsObject(it["name"], it["shape"], "refractive", el["material"] if el else None, surface_coatings=sc, owner=owner))
            elif it["kind"] == "mirror":
                j = _mirror_surface(it["name"], built_mirrors)
                sc = [(cs.frames[j], cs.shapes[j], coats[j])] if j is not None and coats[j] is not None else []
                objects.append(NsObject(it["name"], it["shape"], "mirror", surface_coatings=sc))
        for s in rep["skipped"]:
            notes.append(f"Lens system: surfaces {s['surfaces']} not built ({s['reason']})")
    if include_system and cs.does and any(d is not None for d in cs.does):
        notes.append("Diffractive phases of the lens system are not applied in non-sequential tracing (geometry only)")
    lib = cs.library
    for a in cad_assets:
        if not a.get("visible", True):
            continue
        if a.get("tree") and a.get("format") in ("step", "iges") and a.get("source_b64"):
            # assembly: one object per visible part, each with its own (inherited) optical role
            from .io.cad_assembly import asset_parts

            for part in asset_parts(a):
                po = part.optical
                prole = po.get("role", "none")
                if prole == "none":
                    continue
                objects.append(_cad_object(cs, part.name, part.shape, po, True, notes))
            continue
        optd = a.get("optical") or {}
        opt = optd.get("role", "none")
        if opt == "none":
            continue
        trsf = _asset_trsf(a.get("transform") or {})
        fmt = a.get("format", "stl")
        if fmt in ("step", "iges") and a.get("source_b64"):
            comp, bodies = _read_shape(base64.b64decode(a["source_b64"]), fmt)
            shape, _ = _solidify(comp)
            exact = True
        elif fmt == "stl":
            p, i = decode_mesh(a["mesh"]["positions_b64"], a["mesh"]["indices_b64"])
            shape = _stl_shell(p.astype(float), i)
            shape, _ = _solidify(shape)
            exact = False
            notes.append(f"'{a['name']}' is an STL mesh: traced against its triangles (faceted normals, approximate)")
        else:
            continue
        objects.append(_cad_object(cs, a["name"], _place(shape, trsf), optd, exact, notes))
    if any(o.scatter for o in objects):
        notes.append("Surface scattering is sampled by Monte Carlo (one scattered ray per event); increase the ray count to reduce noise")
    if detectors is not None:
        from .nssources import DetectorRT, surface_frames

        frames = surface_frames(cs)
        try:
            dets = [DetectorRT.build(d, frames) for d in detectors if d.enabled]
        except ValueError as exc:
            raise SystemError_(str(exc)) from exc
        if not dets:
            notes.append("No enabled detector: only the energy budget is computed")
        return assemble_scene(objects, None, None, notes, dets)
    # detector disc on the image surface
    n = cs.n_surfaces
    rd = float(detector_radius) if detector_radius else float(max(sd[n - 1] * 1.5, 1.0))
    circ = gp_Circ(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), rd)
    det = BRepBuilderAPI_MakeFace(BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(circ).Edge()).Wire(), True).Face()
    objects.append(NsObject("Detector", _place(det, _frame_trsf(cs.frames[n - 1])), "detector"))
    return assemble_scene(objects, cs.frames[n - 1], rd, notes)


def _cad_object(cs: CompiledSystem, name: str, shape, optd: dict, exact: bool, notes: list[str]) -> NsObject:
    """Non-sequential object of a placed CAD body (or assembly part) with its optical role."""
    lib = cs.library
    opt = optd.get("role", "none")
    mat = optd.get("material")
    if opt == "refractive":
        if not mat or not lib.has(mat):
            raise SystemError_(f"CAD model '{name}': refractive role needs a known material (got '{mat}')")
    coat = None
    cname = (optd.get("coating") or "").strip()
    if cname and opt in ("mirror", "refractive"):
        try:
            coat = get_coating(cname, cs.coating_library)
        except ValueError as exc:
            raise SystemError_(f"CAD model '{name}': {exc}") from exc
        if opt == "mirror" and coat is not None and coat.substrate is None:
            notes.append(f"'{name}': coating {coat.name} has no mirror substrate (n, k); the mirror stays ideal")
            coat = None
    elif cname:
        notes.append(f"'{name}': coatings apply to mirror and refractive bodies only; ignored")
    return NsObject(name, shape, opt, mat, exact, coating=coat, scatter=_scatter_spec(optd, name))


def _mirror_surface(name: str, it) -> int | None:
    """Surface index of a mirror solid from its export name ('M1 (S4)' -> 4), else the next mirror."""
    import re

    m = re.search(r"\(S(\d+)\)", name)
    if m:
        return int(m.group(1))
    return next(it, None)


def assemble_scene(objects: list[NsObject], detector_frame, detector_radius: float | None, notes: list[str] | None = None, detectors: list | None = None) -> Scene:
    """Build the intersector and face map for a list of placed objects (optionally a legacy detector face)
    plus analytic detectors."""
    dets = list(detectors or [])
    if not objects:
        pts = [d.t for d in dets] or [np.zeros(3)]
        lo = np.min(pts, axis=0) - 1.0
        hi = np.max(pts, axis=0) + 1.0
        return Scene([], None, {}, detector_frame, detector_radius, lo, hi, list(notes or []), dets)
    from OCP.BRep import BRep_Builder
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.TopoDS import TopoDS_Compound

    from .io.cad import shape_properties

    comp = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(comp)
    face_map: dict = {}
    for k, o in enumerate(objects):
        b.Add(comp, o.shape)
        for f in _faces(o.shape):
            face_map.setdefault(hash(f), []).append((k, f))
    it = IntCurvesFace_ShapeIntersector()
    it.Load(comp, 1e-8)
    pr = shape_properties(comp)
    lo, hi = np.array(pr["bbox_min"], dtype=float), np.array(pr["bbox_max"], dtype=float)
    for d in dets:
        lo, hi = np.minimum(lo, d.t), np.maximum(hi, d.t)
    return Scene(objects, it, face_map, detector_frame, None if detector_radius is None else float(detector_radius), lo, hi, list(notes or []), dets)


def _which(scene: Scene, face) -> int:
    for k, f in scene.face_map.get(hash(face), []):
        if f.IsSame(face):
            return k
    raise RuntimeError("hit face not found in the scene")


def _normal(face, u: float, v: float) -> np.ndarray:
    from OCP.BRepGProp import BRepGProp_Face
    from OCP.gp import gp_Pnt, gp_Vec

    p, n = gp_Pnt(), gp_Vec()
    BRepGProp_Face(face).Normal(u, v, p, n)
    a = np.array([n.X(), n.Y(), n.Z()])
    return a / np.linalg.norm(a)


def _hits(scene: Scene, P: np.ndarray, D: np.ndarray):
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt

    it = scene.intersector
    it.Perform(gp_Lin(gp_Pnt(*P), gp_Dir(*D)), EPS, 1e9)
    out = []
    for k in range(1, it.NbPnt() + 1):
        out.append((it.WParameter(k), it.Face(k), it.UParameter(k), it.VParameter(k)))
    out.sort(key=lambda h: h[0])
    return out


# ---- scattering ----------------------------------------------------------

def _basis(n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = np.cross(n, a)
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(n, e1)


def sample_lambertian(normal: np.ndarray, rng) -> np.ndarray:
    """Cosine-weighted direction in the hemisphere of `normal` (unit): P(theta < t) = sin^2 t."""
    u1, u2 = rng.random(2)
    s, c, ph = math.sqrt(u1), math.sqrt(1.0 - u1), 2 * math.pi * u2
    e1, e2 = _basis(normal)
    return c * normal + s * (math.cos(ph) * e1 + math.sin(ph) * e2)


def sample_gaussian(specular: np.ndarray, normal: np.ndarray, sigma: float, rng, tries: int = 64) -> np.ndarray:
    """Direction at polar angle theta from `specular` with (theta cos phi, theta sin phi) ~ N(0, sigma^2) per
    axis, restricted to the hemisphere of `normal` (rejected samples are redrawn)."""
    e1, e2 = _basis(specular)
    for _ in range(tries):
        dx, dy = rng.normal(0.0, sigma, 2)
        th = math.hypot(dx, dy)
        if th >= math.pi:
            continue
        d = math.cos(th) * specular + math.sin(th) * (dx / th * e1 + dy / th * e2) if th > 0 else specular.copy()
        if float(d @ normal) > 1e-9:
            return d
    return specular.copy()


def _scatter_dir(sc: dict, specular: np.ndarray, out_normal: np.ndarray, rng) -> np.ndarray:
    if sc["model"] == "lambertian":
        return sample_lambertian(out_normal, rng)
    return sample_gaussian(specular, out_normal, sc["sigma"], rng)


def _face_coating(obj: NsObject, Q: np.ndarray):
    if obj.coating is not None:
        return obj.coating
    for fr, shp, coat in obj.surface_coatings:
        q = fr.to_local_points(Q[None, :])[0]
        if abs(float(q[2]) - float(shp.sag(q[0] * q[0] + q[1] * q[1]))) < SAG_TOL:
            return coat
    return None


def _medium_at(scene: Scene, P: np.ndarray) -> int | None:
    """Index of the refractive solid containing point P (None: surrounding air)."""
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN

    for k, o in enumerate(scene.objects):
        if o.role != "refractive":
            continue
        c = BRepClass3d_SolidClassifier(o.shape, gp_Pnt(*map(float, P)), 1e-7)
        if c.State() == TopAbs_IN:
            return k
    return None


def trace_nonsequential(
    cs: CompiledSystem,
    scene: Scene,
    field: int = 0,
    wavelength: int | None = None,
    rays: int = 400,
    overfill: float = 1.2,
    split: bool = True,
    max_events: int = 40,
    min_power: float = 1e-6,
    pixels: int = 64,
    keep_paths: int = 60,
    seed: int = 1,
    sources: list | None = None,
    importance: dict | None = None,
    max_seconds: float | None = None,
) -> dict:
    """Trace the scene. Without `sources` the light comes from the sequential system's field
    (`field`, `wavelength`, `rays`, `overfill`; power 1); otherwise from the given
    nssources.LightSource list (emitters and/or system_field sources, powers in W).
    Analytic detectors are in scene.detectors; a legacy detector face (role "detector")
    may also be part of the scene objects. `importance` = {"target": {...} (importance_target),
    "rays": per scatter event} turns on importance sampling. With `max_seconds` the source rays are traced in a
    random order (seeded) and the trace stops between source rays once the time is up: the traced rays are a random
    subset, their powers are scaled to the whole source and the statistics are over them (a note says how many)."""
    from .nssources import sample_source, surface_frames
    from .paraxial import compute_pupil
    from .raytrace import launch

    t0 = time.time()
    rng = np.random.default_rng(seed)
    wl = cs.wl_index(wavelength)
    lam0 = float(cs.wavelengths[wl])
    lib = cs.library
    sys_wls = [(float(w.value), float(w.weight)) for w in cs.model.wavelengths]

    def system_field_rays(fld: int, nrays: int, ovf: float):
        pupil = compute_pupil(cs, wl)
        m = max(3, int(math.sqrt(nrays * 4 / math.pi)))
        u = np.linspace(-ovf, ovf, m)
        gx, gy = np.meshgrid(u, u)
        inside = gx**2 + gy**2 <= ovf**2 + 1e-12
        px, py = gx[inside], gy[inside]
        P0, D0, _ = launch(cs, wl, fld, px, py, pupil)
        D0 = D0 / np.linalg.norm(D0, axis=1, keepdims=True)
        if cs.model.surfaces[0].thickness is None:
            # object at infinity: launch() starts rays on the entrance-pupil plane, which may lie
            # inside or behind the optics (the sequential trace can propagate backwards there).
            # Back the starting points off along the (straight) object-space rays to well before
            # every object of the scene.
            c = 0.5 * (scene.bbox_min + scene.bbox_max)
            diag = float(np.linalg.norm(scene.bbox_max - scene.bbox_min))
            L = np.linalg.norm(P0 - c, axis=1) + diag + 1.0
            P0 = P0 - D0 * L[:, None]
        return P0, D0

    n_air: dict[float, float] = {}

    n_of: dict = {}
    a_of: dict = {}
    # Media as in the sequential trace (system.compile_raw / with_wavelengths): a lens solid's glass at its
    # element's temperature (environment.element_temperatures, keyed by the surface that starts the glass),
    # CAD bodies at the system temperature; bulk absorption from the catalogue internal transmittance at the
    # ray's own wavelength when catalog_absorption is set, else the material's constant alpha.
    temps = element_temperatures(cs.model) if cs.model.environment_enabled else {}
    use_cat = bool(cs.model.catalog_absorption)
    absorb_outside: set[str] = set()

    def index_of(o: NsObject | None, lam: float) -> float:
        if o is None:
            if lam not in n_air:
                n_air[lam] = float(lib.index("AIR", lam)) if lib.has("AIR") else 1.0
            return n_air[lam]
        key = (o.material, o.owner, lam)
        if key not in n_of:
            n_of[key] = float(medium_index(lib, o.material, lam, temps.get(o.owner) if o.owner else None))
        return n_of[key]

    # ---- source rays: (P, D, power, lambda, source index, start medium) ----
    starts: list[tuple] = []
    src_info: list[dict] = []
    if sources is None:
        P0, D0 = system_field_rays(field, rays, overfill)
        n0 = len(P0)
        starts.append((P0, D0, np.full(n0, 1.0 / n0), np.full(n0, lam0), 0, None))
        src_info.append({"name": "System field", "kind": "system_field", "rays": n0, "power_w": 1.0, "overfill": overfill, "pupil_fraction": min(1.0, 1.0 / overfill**2)})
    else:
        for k, s in enumerate(sources):
            if s.kind == "system_field":
                if s.field >= len(cs.model.fields):
                    raise SystemError_(f"Source '{s.name}': field {s.field + 1} does not exist")
                P0, D0 = system_field_rays(s.field, s.rays, s.overfill)
                n0 = len(P0)
                starts.append((P0, D0, np.full(n0, s.power_w / n0), np.full(n0, lam0), k, None))
            else:
                frames = surface_frames(cs)
                med = None
                if s.kind == "gaussian_beam" and scene.objects:
                    # a Gaussian beam's divergence depends on the medium it is launched into: the one at its centre
                    from .nssources import placement_matrix

                    try:
                        med = _medium_at(scene, placement_matrix(s.placement, frames)[1])
                    except ValueError as exc:
                        raise SystemError_(str(exc)) from exc
                try:
                    obj = scene.objects[med] if med is not None else None
                    sr = sample_source(s, k, sys_wls, rng, frames, medium_index=lambda lam, o=obj: index_of(o, lam))
                except ValueError as exc:
                    raise SystemError_(str(exc)) from exc
                if s.kind != "gaussian_beam":
                    med = _medium_at(scene, sr.P.mean(axis=0)) if scene.objects else None
                if med is not None:
                    note = f"Source '{s.name}' lies inside '{scene.objects[med].name}': it emits into that medium"
                    if s.kind == "gaussian_beam":
                        lam_s = float(sr.lam[0])
                        note += f" (its divergence is M² λ / (π n w0) with n = {index_of(scene.objects[med], lam_s):.5f} at {lam_s * 1000:.1f} nm)"
                    scene.notes.append(note)
                starts.append((sr.P, sr.D, sr.power, sr.lam, k, med))
            src_info.append({"name": s.name, "kind": s.kind, "rays": int(len(starts[-1][0])), "power_w": s.power_w})
    total_power = float(sum(float(st[2].sum()) for st in starts))
    if total_power <= 0:
        raise SystemError_("The sources emit no power")
    source_names = [si["name"] for si in src_info]

    def alpha_of(o: NsObject | None, lam: float) -> float:
        if o is None or not o.material:
            return 0.0
        key = (o.material, lam)
        if key not in a_of:
            try:
                a, outside = medium_absorption(lib, o.material, lam, use_cat)
            except MaterialError:
                a, outside = 0.0, False
            if outside:
                absorb_outside.add(o.material)
            a_of[key] = float(a)
        return a_of[key]

    det_hits: list[tuple[float, float, float, int, int]] = []  # legacy detector face
    escaped = discarded = truncated = bulk = coat_abs = scattered = 0.0
    det_rejected = det_back = 0.0
    paths: list[dict] = []
    max_paths = keep_paths * 3

    def new_path(Q):
        return [Q.tolist()] if len(paths) < keep_paths * 2 else None

    # stack entry: P, D, power, medium, depth, n_reflections, n_scatter, path, lambda, source, source ray, event key
    # source rays wait in `fresh` (taken from the end); the stack holds the descendants of one source ray at a time
    stack = []
    fresh = []
    per_src_paths = max(1, keep_paths // max(1, len(starts)))
    rid0 = 0
    for P0, D0, pw0, lam_s, k_src, med in starts:
        for i in range(len(P0) - 1, -1, -1):
            fresh.append((P0[i].copy(), D0[i] / np.linalg.norm(D0[i]), float(pw0[i]), med, 0, 0, 0, [P0[i].tolist()] if i < per_src_paths else None, float(lam_s[i]), k_src, rid0 + i, ()))
        rid0 += len(P0)
    if max_seconds is not None:
        # a random order makes any prefix a random subset (own generator: the scatter draws stay those of the seed)
        order = np.random.default_rng(seed + 1_000_003).permutation(len(fresh))
        fresh = [fresh[k] for k in order]
    traced_rids: list[int] = []
    traced_power = 0.0
    nsrc = sum(len(s[0]) for s in starts)
    target = importance_target(cs, scene, (importance or {}).get("target"))
    imp_rays = int((importance or {}).get("rays", 0)) if target is not None else 0
    imp_added = imp_dropped = 0.0
    no_value = set()

    def key_add(key: tuple, ev: str) -> tuple:
        return key + (ev,) if len(key) < 6 else key

    def scatter_event(Q, spec, out_n, p_in, p_scat, medium, depth, nrefl, nsc, lam, k_src, rid, key, obj, bsdf):
        """Push the scattered ray (and importance rays) of a scatter event; returns nothing."""
        nonlocal imp_added, imp_dropped
        k2 = key_add(key, f"S:{obj.name}")
        if target is not None and imp_rays > 0 and bsdf.has_value:
            for _ in range(imp_rays):
                X = target.sample(rng)
                v = X - Q
                r2 = float(v @ v)
                if r2 <= EPS * EPS:
                    continue
                d = v / math.sqrt(r2)
                cs_ = float(d @ out_n)
                if cs_ <= 0.0:
                    continue
                ct = abs(float(d @ target.R[:, 2]))
                w = p_in * bsdf.density(d, spec, out_n) * cs_ * target.area * ct / (r2 * imp_rays)
                if w <= 0.0:
                    continue
                imp_added += w
                stack.append((Q, d, w, medium, depth + 1, nrefl, nsc + 1, None, lam, k_src, rid, k2))
            ds = bsdf.sample(spec, out_n, rng)
            if target.hit(Q, ds):
                imp_dropped += p_scat  # covered by the importance rays
                return
            stack.append((Q, ds, p_scat, medium, depth + 1, nrefl, nsc + 1, new_path(Q), lam, k_src, rid, k2))
            return
        if target is not None and imp_rays > 0 and not bsdf.has_value:
            no_value.add(obj.name)
        stack.append((Q, bsdf.sample(spec, out_n, rng), p_scat, medium, depth + 1, nrefl, nsc + 1, new_path(Q), lam, k_src, rid, k2))
    events = 0
    has_occ = scene.intersector is not None

    def finish(path, nrefl, nsc, end):
        if path is not None and len(paths) < max_paths:
            paths.append({"points": path, "reflections": nrefl, "scatters": nsc, "end": end})

    while stack or fresh:
        if not stack:
            if max_seconds is not None and traced_rids and time.time() - t0 > max_seconds:
                break
            stack.append(fresh.pop())
            traced_rids.append(int(stack[-1][10]))
            traced_power += stack[-1][2]
        P, D, pw, medium, depth, nrefl, nsc, path, lam, k_src, rid, key = stack.pop()
        if pw < min_power * 1e-3 * total_power:
            truncated += pw
            continue
        if depth >= max_events:
            truncated += pw
            finish(path, nrefl, nsc, "truncated")
            continue
        hits = _hits(scene, P, D) if has_occ else []
        # nearest analytic detector in front of the ray
        dbest = None
        for det in scene.detectors:
            r = det.intersect(P, D, EPS)
            if r is not None and (dbest is None or r[0] < dbest[1][0]):
                dbest = (det, r)
        if dbest is not None and (not hits or dbest[1][0] < hits[0][0] - EPS):
            det, (w, x, y, dz) = dbest
            Q = P + w * D
            if medium is not None:
                att = math.exp(-alpha_of(scene.objects[medium], lam) * w)
                bulk += pw * (1.0 - att)
                pw *= att
            if path is not None:
                path.append(Q.tolist())
            s = det.spec
            front = dz > 0.0
            if not front and not s.two_sided:
                if s.mode == "absorb":
                    det.back_w += pw
                    det_back += pw
                    finish(path, nrefl, nsc, f"blocked: {s.name}")
                else:
                    stack.append((Q, D, pw, medium, depth, nrefl, nsc, path, lam, k_src, rid, key))
                continue
            ok = math.degrees(math.acos(min(1.0, abs(dz)))) <= s.acceptance_deg + 1e-9
            if ok:
                det.hits.append((x, y, pw, abs(dz), lam, k_src, nrefl, nsc, rid, key))
            else:
                det.rejected_w += pw
            if s.mode == "absorb":
                if not ok:
                    det_rejected += pw
                finish(path, nrefl, nsc, f"{'detector' if ok else 'rejected'}: {s.name}")
            else:
                stack.append((Q, D, pw, medium, depth, nrefl, nsc, path, lam, k_src, rid, key))
            continue
        if not hits:
            escaped += pw
            if path is not None:
                path.append((P + D * 50.0).tolist())
            finish(path, nrefl, nsc, "escaped")
            continue
        events += 1
        w, face, fu, fv = hits[0]
        k = _which(scene, face)
        obj = scene.objects[k]
        Q = P + w * D
        if medium is not None:
            att = math.exp(-alpha_of(scene.objects[medium], lam) * w)
            bulk += pw * (1.0 - att)
            pw *= att
        if path is not None:
            path.append(Q.tolist())
        if obj.role == "detector":
            loc = scene.detector_frame.to_local_points(Q[None, :])[0]
            det_hits.append((float(loc[0]), float(loc[1]), pw, nrefl, nsc, rid, key))
            finish(path, nrefl, nsc, "detector")
            continue
        nrm = _normal(face, fu, fv)
        back = nrm if float(D @ nrm) < 0.0 else -nrm  # normal on the incidence side
        sc = _as_bsdf(obj.scatter)

        def tis_of(bs, spec, out_n):
            from .bsdf import _basis as _b2

            e1, e2 = _b2(out_n)
            return bs.tis(math.hypot(float(spec @ e1), float(spec @ e2)))

        if obj.role == "absorber":
            if sc is not None:
                Dr = reflect(D[None, :], nrm[None, :])[0][0]
                ps = pw * tis_of(sc, Dr, back)
                obj.absorbed += pw - ps
                scattered += ps
                finish(path, nrefl, nsc, f"scattered: {obj.name}")
                scatter_event(Q, Dr, back, pw, ps, medium, depth, nrefl, nsc, lam, k_src, rid, key, obj, sc)
            else:
                obj.absorbed += pw
                finish(path, nrefl, nsc, f"absorbed: {obj.name}")
            continue
        if obj.role == "mirror":
            Dn = reflect(D[None, :], nrm[None, :])[0][0]
            coat = _face_coating(obj, Q)
            if coat is not None:
                n0 = index_of(scene.objects[medium] if medium is not None else None, lam)
                o = stack_rt(n0, coat.substrate, coat.layers_at(lam), lam, np.array([abs(float(D @ nrm))]))
                R = float(0.5 * (o["Rs"][0] + o["Rp"][0]))
                coat_abs += pw * (1.0 - R)
                pw *= R
            if sc is not None:
                ps = pw * tis_of(sc, Dn, back)
                scattered += ps
                scatter_event(Q, Dn, back, pw, ps, medium, depth, nrefl, nsc, lam, k_src, rid, key, obj, sc)
                pw -= ps
            stack.append((Q, Dn, pw, medium, depth + 1, nrefl, nsc, path, lam, k_src, rid, key))  # nominal (specular) mirror path
            continue
        # refractive
        entering = float(D @ nrm) < 0.0
        cur = scene.objects[medium] if medium is not None else None
        if entering:
            n1, n2, new_medium = index_of(cur, lam), index_of(obj, lam), k
        else:
            # leaving obj: into another solid touching at the same point (cemented) or into air
            nxt = None
            for w2, f2, _, _ in hits[1:]:
                if w2 - w > 1e-6:
                    break
                k2 = _which(scene, f2)
                o2 = scene.objects[k2]
                if k2 != k and o2.role == "refractive":
                    nxt = k2
                    break
            n1, n2, new_medium = index_of(obj, lam), index_of(scene.objects[nxt] if nxt is not None else None, lam), nxt
        t, tir, ci, ct = refract(D[None, :], nrm[None, :], n1, n2)
        coat = _face_coating(obj, Q)
        Dr = reflect(D[None, :], nrm[None, :])[0][0]
        if coat is not None:
            o = stack_rt(n1, n2, coat.oriented(lam, n1, n2), lam, ci)
            R = float(0.5 * (o["Rs"][0] + o["Rp"][0]))
            T = 0.0 if tir[0] else float(0.5 * (o["Ts"][0] + o["Tp"][0]))
            coat_abs += pw * max(0.0, 1.0 - R - T)
        elif tir[0]:
            R, T = 1.0, 0.0
        else:
            T = float(unpolarized_transmittance(n1, n2, ci, ct)[0])
            R = 1.0 - T
        if tir[0]:
            stack.append((Q, Dr, pw * R, medium, depth + 1, nrefl, nsc, path, lam, k_src, rid, key))  # TIR is a nominal path (prisms)
            continue
        if split and pw * R > min_power * total_power:
            stack.append((Q, Dr, pw * R, medium, depth + 1, nrefl + 1, nsc, new_path(Q) if path is not None else None, lam, k_src, rid, key_add(key, f"R:{obj.name}")))
        else:
            discarded += pw * R
        pt = pw * T
        if sc is not None:
            fwd = -back  # transmission side
            ps = pt * tis_of(sc, t[0], fwd)
            scattered += ps
            scatter_event(Q, t[0], fwd, pt, ps, new_medium, depth, nrefl, nsc, lam, k_src, rid, key, obj, sc)
            pt -= ps
        stack.append((Q, t[0], pt, new_medium, depth + 1, nrefl, nsc, path, lam, k_src, rid, key))

    if fresh:
        # stopped by the time budget: scale the traced rays to the whole source, renumber them for the statistics
        f_s = total_power / traced_power
        remap = {r: k for k, r in enumerate(traced_rids)}
        det_hits = [(*h[:2], h[2] * f_s, *h[3:5], remap[h[5]], *h[6:]) for h in det_hits]
        for d in scene.detectors:
            d.hits = [(*h[:2], h[2] * f_s, *h[3:8], remap[h[8]], *h[9:]) if len(h) > 8 else (*h[:2], h[2] * f_s, *h[3:]) for h in d.hits]
        for o in scene.objects:
            o.absorbed *= f_s
        escaped, discarded, truncated, bulk, coat_abs, scattered = (x * f_s for x in (escaped, discarded, truncated, bulk, coat_abs, scattered))
        det_rejected, det_back, imp_added, imp_dropped = (x * f_s for x in (det_rejected, det_back, imp_added, imp_dropped))
        scene.notes.append(
            f"Time limit ({max_seconds:g} s) reached: {len(traced_rids)} of {nsrc} source rays traced (a random subset); the results are scaled to "
            "the whole source and their standard errors cover it. More rays: raise the time limit, or turn ghost splitting off"
        )
        nsrc = len(traced_rids)
    P_tot = total_power
    absorbed = {o.name: o.absorbed / P_tot for o in scene.objects if o.role == "absorber"}
    legacy_keys = [h[6] for h in det_hits]
    hits_arr = np.array([h[:6] for h in det_hits], dtype=float) if det_hits else np.zeros((0, 6))
    legacy = float(hits_arr[:, 2].sum()) if len(hits_arr) else 0.0
    det_results = [d.result(P_tot, source_names, nsrc) for d in scene.detectors]
    det_abs = sum(r["power_w"] for d, r in zip(scene.detectors, det_results) if d.spec.mode == "absorb")
    det_abs_direct = sum(r["direct_w"] for d, r in zip(scene.detectors, det_results) if d.spec.mode == "absorb")
    det_abs_scat = sum(float(sum(h[2] for h in d.hits if h[7] > 0)) for d in scene.detectors if d.spec.mode == "absorb")
    is_direct = (hits_arr[:, 3] == 0) & (hits_arr[:, 4] == 0) if len(hits_arr) else np.zeros(0, bool)
    is_scat = hits_arr[:, 4] > 0 if len(hits_arr) else np.zeros(0, bool)
    direct = (float(hits_arr[is_direct, 2].sum()) if len(hits_arr) else 0.0) + det_abs_direct
    after_scatter = (float(hits_arr[is_scat, 2].sum()) if len(hits_arr) else 0.0) + det_abs_scat
    detected = legacy + det_abs
    budget = detected + sum(o.absorbed for o in scene.objects if o.role == "absorber") + escaped + discarded + truncated + bulk + coat_abs + det_rejected + det_back
    if absorb_outside:
        scene.notes.append(f"Catalogue absorption of {', '.join(sorted(absorb_outside))} is used beyond its tabulated wavelengths (nearest end value)")
    if no_value:
        scene.notes.append(f"Importance sampling skips the Gaussian scatter of {', '.join(sorted(no_value))} (no closed-form BSDF)")
    legacy_block = None
    if scene.detector_radius:
        R_det = scene.detector_radius
        edges = np.linspace(-R_det, R_det, pixels + 1)
        irr = np.zeros((pixels, pixels))
        if len(hits_arr):
            H, _, _ = np.histogram2d(hits_arr[:, 1], hits_arr[:, 0], bins=[edges, edges], weights=hits_arr[:, 2] / P_tot)
            irr = H / ((edges[1] - edges[0]) ** 2)
        d = hits_arr[is_direct] if len(hits_arr) else hits_arr
        centroid = rms = None
        if len(d) and d[:, 2].sum() > 0:
            c = (d[:, :2] * d[:, 2:3]).sum(0) / d[:, 2].sum()
            rr = ((d[:, :2] - c) ** 2).sum(1)
            centroid = c.tolist()
            rms = float(math.sqrt((rr * d[:, 2]).sum() / d[:, 2].sum()))
        stray = (hits_arr[:, 3] > 0) | (hits_arr[:, 4] > 0) if len(hits_arr) else np.zeros(0, bool)
        legacy_block = {
            "power_sigma": standard_error(hits_arr[:, 5], hits_arr[:, 2], nsrc) / P_tot if len(hits_arr) else 0.0,
            "stray": float(hits_arr[stray, 2].sum()) / P_tot if len(hits_arr) else 0.0,
            "stray_sigma": standard_error(hits_arr[stray, 5], hits_arr[stray, 2], nsrc) / P_tot if len(hits_arr) else 0.0,
            "paths": [{**r, "power": r["power_w"] / P_tot, "sigma": r["sigma_w"] / P_tot} for r in path_table(legacy_keys, hits_arr[:, 5], hits_arr[:, 2], nsrc, float(hits_arr[:, 2].sum()))] if len(hits_arr) else [],
            "radius_mm": R_det,
            "pixels": pixels,
            "irradiance": irr.tolist(),
            "units": "source power fraction per mm²",
            "hits": int(len(hits_arr)),
            "scatter_hits": int(is_scat.sum()) if len(hits_arr) else 0,
            "direct_centroid_mm": centroid,
            "direct_rms_mm": rms,
        }
    f = 1.0 / P_tot
    return {
        "field": field,
        "wavelength_um": lam0,
        "source": {"rays": nsrc, "overfill": overfill, "power": 1.0, "pupil_fraction": min(1.0, 1.0 / overfill**2)} if sources is None else {"rays": nsrc, "power": 1.0},
        "sources": src_info,
        "total_power_w": P_tot,
        "energy": {
            "detected": detected * f,
            "detected_direct": direct * f,
            "detected_after_reflections": max(0.0, detected - direct - after_scatter) * f,  # no rounding noise below 0
            "detected_after_scatter": after_scatter * f,
            "absorbed": absorbed,
            "coating_absorption": coat_abs * f,
            "escaped": escaped * f,
            "discarded_reflections": discarded * f,
            "truncated": truncated * f,
            "bulk_absorption": bulk * f,
            "scattered": scattered * f,
            "importance_added": imp_added * f,
            "importance_dropped": imp_dropped * f,
            "detector_rejected": det_rejected * f,
            "detector_back": det_back * f,
            "total": budget * f,
        },
        "detector": legacy_block,
        "detectors": det_results,
        "objects": [
            {"name": o.name, "role": o.role, "material": o.material, "exact": o.exact, "coating": o.coating.name if o.coating is not None else (", ".join(sorted({c.name for _, _, c in o.surface_coatings})) or None), "scatter": None if o.scatter is None else {**_as_bsdf(o.scatter).describe(), "sigma_deg": math.degrees(_as_bsdf(o.scatter).sigma)}}
            for o in scene.objects
        ],
        "paths": paths[:max_paths],
        "settings": {"split": split, "max_events": max_events, "min_power": min_power, "seed": seed, "max_seconds": max_seconds, "importance": None if target is None else {"target": target.name, "rays": imp_rays}},
        "complete": not fresh,
        "source_rays": nsrc,
        "events": events,
        "elapsed_s": time.time() - t0,
        "notes": scene.notes,
        "method": "Non-sequential geometric trace against exact B-rep solids (OpenCascade line/face intersection, outward face normals); Snell refraction with unpolarised Fresnel or thin-film (coated faces) splitting, TIR, mirrors (ideal or coated), absorbers, Monte Carlo surface scattering (Lambertian, Gaussian, ABg, Harvey-Shack BSDF)"
        + (f", importance sampling towards {target.name} ({imp_rays} rays per scatter event)" if target is not None else "")
        + ", bulk absorption; standard errors over source rays; "
        + ("uniform overfilled source through the system pupil; detector disc on the image surface" if sources is None else "Monte Carlo sources (shape, spatial and angular law, spectrum; seeded); analytic plane detectors with acceptance angle"),
    }
