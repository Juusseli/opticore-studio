"""Design advisor (docs/OPTICAL_ENGINE.md §8n).

Diagnosis -- what limits the image:
* per field, the real wavefront at the primary wavelength (wavefront.py) is decomposed into aberration
  classes by an orthonormalised Fringe Zernike basis on the actual samples (QR in Fringe order), so the class
  variances add up exactly to the variance of the fit; piston and tilt (image position, not blur) are left
  out: defocus (n = 2, m = 0), spherical aberration (m = 0, n >= 4), coma (|m| = 1), astigmatism (|m| = 2),
  trefoil (|m| = 3) and higher (|m| >= 4); the part the 37 terms do not fit is "residual";
* the geometric RMS spot of every field (all wavelengths) against the Airy radius;
* axial colour (paraxial focus spread over the system wavelengths against the depth of focus +-2 lambda N^2),
  lateral colour (real chief-ray height spread at the largest field against the Airy radius) and distortion;
* the surfaces that cause each class: the surface-by-surface Seidel and colour sums (third order).

Suggestions -- what to do about it: candidate design moves, each a one-parameter change of a copy of the
design, are tried with the merit function (the project's, or RMS spot over all fields and wavelengths plus
the current focal length when it has none). Along each move the squared merit is modelled by a parabola
through t = 0 and +-h, its vertex is evaluated and the fit repeated on the three best points (up to six
times), and the best evaluated point is kept, so
every reported value is a real evaluation of the merit function. Moves: refocus, bend a lens or cemented
group (the same change of every curvature, with the last one solved so that the element's paraxial power at
the primary wavelength stays the same), change one curvature (the power), move the stop (a dummy
surface between air gaps), change an air gap or a centre thickness, a conic on the surfaces with the largest
spherical-aberration contributions, and catalogue neighbours of each glass (with refocus; not for plates).
Moves with the same outcome (merit equal to 1e-6) are reported once, as the simplest.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..model import OpticalSystem
from ..optimize.merit import MeritFunction, OptimizationSpec
from ..paraxial import compute_pupil, paraxial_data, seidel_coefficients
from ..system import CompiledSystem, compile_system
from .wavefront import fringe_nm, pupil_grid, wavefront_samples, zernike

CLASSES = ("defocus", "spherical", "coma", "astigmatism", "trefoil", "higher")
SEIDEL_OF = {"spherical": "SI", "coma": "SII", "astigmatism": "SIII", "field_curvature": "SIV", "distortion": "SV", "axial_colour": "CL", "lateral_colour": "CT"}
GASES = ("AIR", "VACUUM", "", "MIRROR")
CURVED = ("standard", "even_asphere", "odd_asphere")  # surface types whose radius the moves change


def _class_of(n: int, m: int) -> str | None:
    am = abs(m)
    if n <= 1:
        return None  # piston, tilt
    if am == 0:
        return "defocus" if n == 2 else "spherical"
    return {1: "coma", 2: "astigmatism", 3: "trefoil"}.get(am, "higher")


def zernike_classes(px: np.ndarray, py: np.ndarray, W: np.ndarray, count: int = 37) -> dict:
    """Variance of each aberration class (waves^2) by an orthonormal basis on the samples (module notes)."""
    ok = np.isfinite(W)
    x, y, w = px[ok], py[ok], W[ok]
    rho, th = np.hypot(x, y), np.arctan2(y, x)
    nm = fringe_nm(count)
    A = np.stack([zernike(n, m, rho, th) for n, m in nm], axis=1)
    Q, R = np.linalg.qr(A)
    keep = np.abs(np.diag(R)) > 1e-9 * np.abs(np.diag(R)).max()
    coef = Q.T @ w
    N = len(w)
    var = {c: 0.0 for c in CLASSES}
    defocus = 0.0
    for j, (n, m) in enumerate(nm):
        cl = _class_of(n, m)
        if cl is None or not keep[j]:
            continue
        var[cl] += coef[j] ** 2 / N
        if (n, m) == (2, 0):
            defocus = float(coef[j] * np.sign(R[j, j]) / math.sqrt(N))  # signed: the sign of +Z4 (2 rho^2 - 1)
    fit = Q @ coef
    resid = w - fit
    total_fit = sum(var.values())
    return {"variance": var, "residual": float(np.mean(resid**2)), "total": total_fit + float(np.mean(resid**2)), "defocus": defocus}


def diagnose(cs: CompiledSystem, grid: int = 48) -> dict:
    """What limits the image (module notes)."""
    from .spot import spot_diagram

    prim = cs.model.primary_wavelength
    pupil = compute_pupil(cs, prim)
    X, Y, inside = pupil_grid(grid)
    px, py = X[inside], Y[inside]
    spot = spot_diagram(cs, density=6)
    airy = spot.get("airy_radius_um")
    fields = []
    for f in range(len(cs.model.fields)):
        entry = {"field": f, "field_value": [cs.model.fields[f].x, cs.model.fields[f].y]}
        try:
            W, _, _ = wavefront_samples(cs, prim, f, px, py, pupil)
            zc = zernike_classes(px, py, W)
            tot = zc["total"]
            entry["rms_waves"] = math.sqrt(tot)
            entry["classes"] = {c: {"rms_waves": math.sqrt(v), "share": v / tot if tot > 0 else 0.0} for c, v in zc["variance"].items()}
            entry["classes"]["residual"] = {"rms_waves": math.sqrt(zc["residual"]), "share": zc["residual"] / tot if tot > 0 else 0.0}
            entry["valid_fraction"] = float(np.isfinite(W).mean())
        except Exception as exc:  # e.g. telecentric image space: no spherical reference
            entry["rms_waves"] = None
            entry["classes"] = None
            entry["note"] = str(exc)
        sf = spot["fields"][f]
        entry["rms_spot_um"] = sf["rms_radius_um"]
        if entry["classes"]:
            # defocus is a focus error (refocusing removes it; pure spherical aberration at the paraxial focus
            # shows mostly as defocus): the blur classes are those left at the best focus
            foc = entry["classes"]["defocus"]["rms_waves"]
            blur = math.sqrt(max(0.0, entry["rms_waves"] ** 2 - foc**2))
            entry["focus_rms_waves"] = foc
            entry["focus_signed_waves"] = zc["defocus"]
            entry["blur_rms_waves"] = blur
            rest = [c for c in CLASSES if c != "defocus"]
            entry["dominant"] = max(rest, key=lambda c: entry["classes"][c]["share"]) if blur > 0 else None
            entry["diffraction_limited"] = blur <= 0.0707  # Marechal 0.8 at the best focus
        fields.append(entry)
    # colour and distortion
    colour = {}
    wls = cs.wavelengths
    if len(wls) > 1:
        bfl = []
        for w in range(len(wls)):
            try:
                bfl.append(paraxial_data(cs, w).bfl)
            except Exception:
                bfl.append(None)
        if all(b is not None for b in bfl):
            pd = paraxial_data(cs, prim)
            nwork = pd.working_fnum or (pd.efl / pd.entrance_pupil_diameter if pd.efl else None)
            lam = float(wls[prim]) * 1e-3
            dof = 2.0 * lam * nwork * nwork if nwork else None
            colour["axial_colour_um"] = (max(bfl) - min(bfl)) * 1e3
            colour["depth_of_focus_um"] = dof * 1e3 if dof else None
        # lateral colour at the largest field: real chief rays per wavelength, their landings measured along the
        # field's azimuth (not along y: a field along x has its colour spread along x)
        from ..fields import field_direction, system_field_kind
        from ..raytrace import trace_pupil
        from .summary import largest_field

        fmax = largest_field(cs.model)
        fmax = 0 if fmax is None else fmax
        fd = cs.model.fields[fmax]
        u = np.array(field_direction(system_field_kind(cs.model), fd.x, fd.y) or (0.0, 1.0))
        hs = []
        for w in range(len(wls)):
            r = trace_pupil(cs, w, fmax, np.array([0.0]), np.array([0.0]), pupil, obscure=False)
            hs.append(float(r.image_xy()[0] @ u) if r.ok[0] else float("nan"))
        if np.all(np.isfinite(hs)):
            colour["lateral_colour_um"] = (max(hs) - min(hs)) * 1e3
            colour["field"] = fmax
    distortion = None
    try:
        from .aberrations import field_curvature_distortion

        fcd = field_curvature_distortion(cs, samples=5, wavelengths=[prim])
        d = fcd["per_wavelength"][0]["distortion_percent"]
        distortion = float(d[-1]) if d and d[-1] is not None else None
    except Exception:
        distortion = None
    # attribution by the surface-by-surface third-order sums
    attribution = {}
    try:
        sc = seidel_coefficients(cs, prim)
        for cls, key in SEIDEL_OF.items():
            vals = [(r["surface"], float(r[key])) for r in sc["surfaces"]]
            s_abs = sum(abs(v) for _, v in vals)
            if s_abs <= 0:
                continue
            top = sorted(vals, key=lambda t: -abs(t[1]))[:3]
            attribution[cls] = {"total": float(sc["total"][key]), "surfaces": [{"surface": i, "value": v, "share": abs(v) / s_abs} for i, v in top]}
        attribution_note = "third-order (Seidel) sums" + (" — approximate: the system is not rotationally symmetric" if sc.get("approximate") else "")
    except Exception as exc:
        attribution_note = f"not available: {exc}"
    # focus: the same criterion as the System card (focus.py: polychromatic RMS spot against its best plane)
    try:
        from .focus import focus_status

        fs = focus_status(cs)
        focus = {k: fs[k] for k in ("best_defocus_mm", "rms_um", "rms_best_um", "at_best_focus")}
    except Exception:
        focus = None
    findings = _findings(fields, colour, distortion, airy, focus)
    return {
        "wavelength_um": float(wls[prim]),
        "airy_radius_um": airy,
        "findings": findings,
        "fields": fields,
        "focus": focus,
        "colour": colour,
        "distortion_percent": distortion,
        "attribution": attribution,
        "attribution_note": attribution_note,
        "method": "Real-ray wavefront at the primary wavelength decomposed into aberration classes with an orthonormalised Fringe Zernike basis "
        f"({grid}×{grid} pupil samples; piston and tilt excluded); geometric RMS spot over all wavelengths (hexapolar, density 6, as the spot diagram); colour from paraxial foci and real chief rays; "
        "causes from the surface Seidel and colour sums",
    }


QUARTER_WAVE = 0.25 / math.sqrt(12.0)  # RMS of a quarter wave of defocus (Rayleigh)


def _findings(fields: list, colour: dict, distortion: float | None, airy: float | None, focus: dict | None = None) -> list[dict]:
    """Structured statements, most important first (the UI words them): focus, field curvature, the dominant
    aberration per field, colour, distortion, or 'diffraction limited'."""
    out = []
    ok = [f for f in fields if f.get("classes")]
    # focus: the image surface is not at the best polychromatic RMS focus (the System card's criterion), so a
    # design balanced over field and wavelength is in focus even where one field's wavefront shows defocus
    if focus and focus.get("at_best_focus") is False:
        share = float(np.mean([f["classes"]["defocus"]["share"] for f in ok])) if ok else None
        out.append({"kind": "focus", "defocus_mm": focus["best_defocus_mm"], "rms_um": focus["rms_um"], "rms_best_um": focus["rms_best_um"], "share": share})
    if ok:
        # signed wavefront defocus per field: its spread over the field is field curvature
        foc = np.array([f["focus_signed_waves"] for f in ok])
        common = float(foc.mean())
        if len(ok) > 1 and float(foc.max() - foc.min()) > QUARTER_WAVE:
            worst = ok[int(np.argmax(np.abs(foc - common)))]
            out.append({"kind": "field_curvature", "field": worst["field"], "rms_waves": float(foc.max() - foc.min())})
        for f in ok:
            if f["dominant"] and f["blur_rms_waves"] > 0.0707:
                share = f["classes"][f["dominant"]]["share"] / max(1e-12, 1.0 - f["classes"]["defocus"]["share"])
                out.append({"kind": "aberration", "field": f["field"], "class": f["dominant"], "rms_waves": f["classes"][f["dominant"]]["rms_waves"], "share": share, "blur_rms_waves": f["blur_rms_waves"]})
    ax, dof = colour.get("axial_colour_um"), colour.get("depth_of_focus_um")
    if ax is not None and dof and ax > dof:
        out.append({"kind": "axial_colour", "value_um": ax, "ratio": ax / dof})
    lat = colour.get("lateral_colour_um")
    if lat is not None and airy and lat > airy:
        out.append({"kind": "lateral_colour", "value_um": lat, "ratio": lat / airy, "field": colour.get("field")})
    if distortion is not None and abs(distortion) > 1.0:
        out.append({"kind": "distortion", "percent": distortion})
    if not out and ok and all(f["diffraction_limited"] for f in ok):
        out.append({"kind": "diffraction_limited"})
    return out


# ---------------------------------------------------------------------------------------------- suggestions
@dataclass
class Move:
    kind: str  # refocus | bend | curvature | stop | gap | thickness | conic | glass
    label: dict  # structured description for the UI (surfaces, element, glass, ...)
    apply: Callable[[dict, float], dict]  # (system dict, t) -> system dict
    h: float  # first step
    lo: float
    hi: float
    patch: Callable[[dict], list]  # system dict after the move -> [{surface_id, key, value}]


def _curv(s: dict) -> float:
    return 0.0 if s.get("radius") is None else 1.0 / s["radius"]


def _set_curv(s: dict, c: float):
    s["radius"] = None if abs(c) < 1e-15 else 1.0 / c


def _group_power(d: dict, g: list[int], n: np.ndarray, last: float | None = None) -> tuple[float, float, float]:
    """Paraxial power of the surfaces g (a lens or cemented group) at one wavelength (n: signed indices after each
    surface), by a y-nu trace of a ray parallel to the axis at unit height. The power is linear in the last
    curvature: returns (power, y at the last surface, index step at the last surface), with the last curvature
    replaced by `last` when given."""
    y, nu = 1.0, 0.0
    for j, k in enumerate(g):
        sk = d["surfaces"][k]
        c = last if (j == len(g) - 1 and last is not None) else _curv(sk)
        dn = float(n[k] - n[k - 1])
        nu -= y * dn * c
        if j < len(g) - 1:
            y += (sk.get("thickness") or 0.0) * nu / float(n[k])
    return -nu, y, float(n[g[-1]] - n[g[-1] - 1])


def _groups(system: OpticalSystem) -> list[list[int]]:
    """Lens elements and cemented groups as lists of surface indices, front to back (glass between them)."""
    surfs = system.surfaces
    n = len(surfs)
    out = []
    i = 1
    while i < n - 1:
        s = surfs[i]
        if s.material.upper() not in GASES and s.type not in ("coordinate_break", "ideal"):
            g = [i]
            j = i
            while j + 1 < n - 1 and surfs[j].material.upper() not in GASES:
                j += 1
                g.append(j)
            if surfs[j].material.upper() in GASES and all(surfs[k].type in ("standard", "even_asphere", "odd_asphere", "biconic") for k in g):
                out.append(g)
            i = j + 1
        else:
            i += 1
    return out


def _patch(d: dict, idx: list[int], keys: list[str]) -> list:
    return [{"surface_id": d["surfaces"][i]["id"], "key": k, "value": d["surfaces"][i][k]} for i in idx for k in keys]


def build_moves(system: OpticalSystem, cs: CompiledSystem, custom_materials=(), glass_candidates: int = 3) -> list[Move]:
    surfs = system.surfaces
    n = len(surfs)
    moves: list[Move] = []
    img_gap = n - 2
    sd = [float(x) for x in cs.fixed_sd]
    try:
        from .evaluate import auto_semi_diameters, effective_semi_diameters

        sd = list(effective_semi_diameters(cs, auto_semi_diameters(cs, compute_pupil(cs))))
    except Exception:
        pass
    # refocus
    s = surfs[img_gap]
    if s.thickness is not None and s.thickness_solve is None and s.type != "coordinate_break":
        pd = paraxial_data(cs)
        nw = pd.working_fnum or 5.0
        lam = float(cs.wavelengths[cs.model.primary_wavelength]) * 1e-3
        h = max(4.0 * lam * nw * nw, 1e-4 * max(abs(s.thickness), 1.0))
        span = max(0.05 * abs(s.thickness), 50 * h)

        def refocus(d, t, k=img_gap):
            d["surfaces"][k]["thickness"] += t
            return d

        moves.append(Move("refocus", {"surface": img_gap}, refocus, h, -span, span, lambda d, k=img_gap: _patch(d, [k], ["thickness"])))
    # bend lenses / cemented groups: the same change of every curvature but the last, which is solved so that
    # the paraxial power of the element (thick lens) at the primary wavelength stays the same
    n_prim = cs.n_signed[cs.model.primary_wavelength]
    base = system.model_dump()
    for g in _groups(system):
        if any(surfs[k].curvature_solve is not None or surfs[k].type not in CURVED for k in g):
            continue
        r = max(sd[g[0]], sd[g[-1]], 1e-3)
        h = 0.02 / r
        phi0 = _group_power(base, g, n_prim)[0]

        def bend(d, t, g=g, phi0=phi0):
            for k in g[:-1]:
                _set_curv(d["surfaces"][k], _curv(d["surfaces"][k]) + t)
            p0, y, dn = _group_power(d, g, n_prim, last=0.0)
            if abs(y * dn) > 1e-12:
                _set_curv(d["surfaces"][g[-1]], (phi0 - p0) / (y * dn))  # power = p0 + y dn c_last
            else:
                _set_curv(d["surfaces"][g[-1]], _curv(d["surfaces"][g[-1]]) + t)
            return d

        moves.append(Move("bend", {"surfaces": g}, bend, h, -0.5 / r, 0.5 / r, lambda d, g=g: _patch(d, g, ["radius"])))
    # single curvatures: the elementary change of power (bending holds it)
    n_phys = cs.n_after[cs.model.primary_wavelength]
    for i in range(1, n - 1):
        si = surfs[i]
        if si.type not in CURVED or si.curvature_solve is not None:
            continue
        if si.material != "MIRROR" and abs(float(n_phys[i] - n_phys[i - 1])) < 1e-9:
            continue  # a dummy surface: no power
        r = max(sd[i], 1e-3)

        def curvature(d, t, i=i):
            _set_curv(d["surfaces"][i], _curv(d["surfaces"][i]) + t)
            return d

        moves.append(Move("curvature", {"surface": i}, curvature, 0.01 / r, -0.5 / r, 0.5 / r, lambda d, i=i: _patch(d, [i], ["radius"])))
    # move a dummy stop between air gaps
    st = system.stop_index
    if 0 < st < n - 1:
        sst = surfs[st]
        before = surfs[st - 1]
        if sst.radius is None and sst.material.upper() in GASES and before.material.upper() in GASES and st - 1 >= 1 and before.thickness is not None and sst.thickness is not None and before.thickness_solve is None and sst.thickness_solve is None:
            a, b = before.thickness, sst.thickness
            lo, hi = -max(0.0, a - 0.05), max(0.0, b - 0.05)
            if hi - lo > 1e-6:

                def move_stop(d, t, st=st):
                    d["surfaces"][st - 1]["thickness"] += t
                    d["surfaces"][st]["thickness"] -= t
                    return d

                moves.append(Move("stop", {"surface": st}, move_stop, max(0.02 * (a + b), 1e-3), lo, hi, lambda d, st=st: _patch(d, [st - 1, st], ["thickness"])))
    # air gaps and centre thicknesses
    for i in range(1, n - 2):
        si = surfs[i]
        if si.thickness is None or si.thickness_solve is not None or si.type == "coordinate_break" or si.material == "MIRROR":
            continue
        if i in (st - 1, st):
            continue  # covered by the stop move
        t0 = si.thickness
        if t0 <= 0:
            continue
        glass = si.material.upper() not in GASES
        kind = "thickness" if glass else "gap"
        lo = -(0.3 if glass else 0.6) * t0
        hi = (0.5 if glass else 1.0) * t0 + (0.0 if glass else 0.5)

        def thick(d, t, i=i):
            d["surfaces"][i]["thickness"] += t
            return d

        moves.append(Move(kind, {"surface": i}, thick, max(0.05 * t0, 1e-3), lo, hi, lambda d, i=i: _patch(d, [i], ["thickness"])))
    # conic on the surfaces with the largest spherical-aberration contributions
    try:
        sc = seidel_coefficients(cs)
        cand = [r for r in sc["surfaces"] if surfs[r["surface"]].type in ("standard", "even_asphere") and surfs[r["surface"]].radius is not None and surfs[r["surface"]].material != "MIRROR"]
        for r in sorted(cand, key=lambda r: -abs(r["SI"]))[:2]:
            i = r["surface"]

            def conic(d, t, i=i):
                d["surfaces"][i]["conic"] = d["surfaces"][i].get("conic", 0.0) + t
                return d

            moves.append(Move("conic", {"surface": i}, conic, 0.1, -3.0, 3.0, lambda d, i=i: _patch(d, [i], ["conic"])))
    except Exception:
        pass
    # catalogue neighbours of each glass (refocused)
    lib = cs.library
    pool = [m for m in lib.all() if m.category in ("glass",) and m.extraordinary is None and m.nd and m.vd]
    free_image = img_gap >= 1 and surfs[img_gap].thickness is not None and surfs[img_gap].thickness_solve is None
    for g in _groups(system):
        if all(surfs[k].radius is None for k in g):
            continue  # a plate (filter, window): its glass only shifts the focus
        for k in g[:-1]:
            name = surfs[k].material
            try:
                m0 = lib.get(name)
            except Exception:
                continue
            if not (m0.nd and m0.vd):
                continue
            dist = sorted(((abs(m.nd - m0.nd) / 0.05) ** 2 + (abs(m.vd - m0.vd) / 5.0) ** 2, m.name) for m in pool if m.name != m0.name)
            for _, cand_name in dist[:glass_candidates]:
                if not free_image:
                    # the image distance is solved: one evaluation of the swapped glass (t = 1)

                    def swap(d, t, k=k, cand=cand_name):
                        if t != 0:
                            d["surfaces"][k]["material"] = cand
                        return d

                    moves.append(Move("glass", {"surface": k, "from": name, "to": cand_name}, swap, 1.0, 1.0, 1.0, lambda d, k=k: _patch(d, [k], ["material"])))
                else:

                    def glass_move(d, t, k=k, cand=cand_name):
                        d["surfaces"][k]["material"] = cand
                        d["surfaces"][img_gap]["thickness"] += t
                        return d

                    pd = paraxial_data(cs)
                    nw = pd.working_fnum or 5.0
                    lam = float(cs.wavelengths[cs.model.primary_wavelength]) * 1e-3
                    hh = max(4.0 * lam * nw * nw, 1e-3)
                    span = max(0.05 * abs(surfs[img_gap].thickness), 50 * hh)
                    moves.append(Move("glass", {"surface": k, "from": name, "to": cand_name}, glass_move, hh, -span, span, lambda d, k=k: _patch(d, [k, img_gap], ["material", "thickness"])))
    return moves


class _MoveMerit(MeritFunction):
    """The merit function along one move (system_for builds the moved design)."""

    def __init__(self, system, spec, custom, move: Move, ns=None):
        super().__init__(system, spec, custom, ns=ns)
        self.move = move

    def system_for(self, x):
        t = float(x[0]) if len(x) else 0.0
        return OpticalSystem.model_validate(self.move.apply(copy.deepcopy(self.base_dict), t))


def default_spec(system: OpticalSystem, custom_materials=()) -> OptimizationSpec:
    """RMS spot over all fields and wavelengths, holding the current focal length."""
    efl = paraxial_data(compile_system(system, custom_materials)).efl
    ops = [{"type": "rms_spot", "rings": 4}]
    if efl is not None and math.isfinite(efl):
        ops.append({"type": "efl", "target": float(efl), "weight": 1.0})
    return OptimizationSpec.model_validate({"operands": ops})


def _line(mm: _MoveMerit, f0: float, move: Move) -> tuple[float, float, int]:
    """Best evaluated point along a move: a parabola of merit^2 through the three best points (0 and +-h to start),
    its vertex evaluated, repeated up to six times or until the vertex stops moving."""
    pts = {0.0: f0}

    def f(t):
        t = float(min(max(t, move.lo), move.hi))
        if t not in pts:
            pts[t] = mm.merit(np.array([t]))
        return pts[t]

    h = min(move.h, max(abs(move.lo), abs(move.hi)))
    for t in (-h, h):
        f(t)
    for _ in range(6):
        best = sorted(pts.items(), key=lambda kv: kv[1])[:3]
        ts = np.array([b[0] for b in best])
        ys = np.array([b[1] ** 2 for b in best])
        if len(set(ts)) < 3:
            break
        A = np.vstack([ts * ts, ts, np.ones(3)]).T
        try:
            a, b, _c = np.linalg.solve(A, ys)
        except np.linalg.LinAlgError:
            break
        if a <= 0:
            # concave: step further downhill from the best point
            tb = best[0][0]
            step = (move.hi - tb) if b < 0 else (move.lo - tb)
            f(tb + 0.5 * step)
            continue
        tv = float(min(max(-b / (2 * a), move.lo), move.hi))
        if abs(tv - best[0][0]) < 1e-3 * h or tv in pts:
            break  # converged
        f(tv)
    t_best, f_best = min(pts.items(), key=lambda kv: kv[1])
    return t_best, f_best, len(pts) - 1


def suggest(system: OpticalSystem, custom_materials=(), spec: OptimizationSpec | None = None, ns=None, progress=None, control=None, top: int = 8) -> dict:
    """Try every move (module notes); return the moves that improve the merit, best first."""
    custom_materials = list(custom_materials)
    cs = compile_system(system, custom_materials)
    own = spec is not None and any(o.enabled and o.weight > 0 for o in spec.operands)
    spec = OptimizationSpec.model_validate({"operands": [o.model_dump() for o in spec.operands]}) if own else default_spec(system, custom_materials)
    moves = build_moves(system, cs, custom_materials)
    base = MeritFunction(system, spec, custom_materials, ns=ns)
    f0 = base.merit(np.array([]))
    out = []
    evals = 0
    if progress is not None:
        progress.update(total=len(moves), done=0)
    for k, mv in enumerate(moves):
        if control is not None and control.cancel.is_set():
            break
        try:
            mm = _MoveMerit(system, spec, custom_materials, mv, ns=ns)
            t, fb, ne = _line(mm, f0, mv)
            evals += ne
            if fb < f0 * (1 - 1e-9) and t != 0.0:
                d = mv.apply(copy.deepcopy(system.model_dump()), t)
                out.append({"kind": mv.kind, **mv.label, "t": t, "merit_before": f0, "merit_after": fb, "gain": (f0 - fb) / f0, "patch": mv.patch(d), "_order": k})
        except Exception:  # a move that breaks the design (e.g. rays fail everywhere) is simply not suggested
            pass
        if progress is not None:
            progress.update(done=k + 1)
    # moves with the same outcome (a gap in front of a plate and refocusing) are one suggestion: the simplest
    kept: list[dict] = []
    for sg in sorted(out, key=lambda s: s["_order"]):
        if not any(abs(sg["merit_after"] - o["merit_after"]) <= 1e-6 * max(abs(o["merit_after"]), 1e-300) for o in kept):
            kept.append(sg)
    out = sorted(kept, key=lambda s: -s["gain"])[:top]
    for sg in out:
        del sg["_order"]
    # field RMS spots before and after for the shown suggestions
    from .spot import spot_diagram

    before = [f["rms_radius_um"] for f in spot_diagram(cs, density=6)["fields"]]
    for s in out:
        d = system.model_dump()
        for p in s["patch"]:
            for sd in d["surfaces"]:
                if sd["id"] == p["surface_id"]:
                    sd[p["key"]] = p["value"]
        try:
            after = [f["rms_radius_um"] for f in spot_diagram(compile_system(OpticalSystem.model_validate(d), custom_materials), density=6)["fields"]]
        except Exception:
            after = None
        s["rms_spot_before_um"] = before
        s["rms_spot_after_um"] = after
    return {
        "merit": f0,
        "merit_kind": "project" if own else "default",
        "moves_tried": len(moves),
        "evaluations": evals,
        "suggestions": out,
        "status": "cancelled" if (control is not None and control.cancel.is_set()) else "finished",
        "method": "Each move is a one-parameter change of a copy of the design; the squared merit along it is modelled by a parabola through 0 and ±h, "
        "its vertex evaluated and the fit repeated on the three best points (up to six times); the best evaluated point is reported (every number is a real merit evaluation)",
    }


# ---------------------------------------------------------------------------------------------- background jobs
@dataclass
class AdvisorProgress:
    total: int = 0
    done: int = 0

    def update(self, total: int | None = None, done: int | None = None):
        if total is not None:
            self.total = total
        if done is not None:
            self.done = done


class AdvisorJobs:
    """Suggestion runs in a background thread with progress and cancel (like the optimiser's jobs)."""

    def __init__(self, max_jobs: int = 16):
        import threading

        self._jobs: dict = {}
        self._lock = threading.Lock()
        self.max_jobs = max_jobs

    def start(self, system: OpticalSystem, custom_materials=(), spec: OptimizationSpec | None = None, ns=None):
        import threading
        import time
        import uuid

        from ..optimize.engine import Control

        job = {"id": uuid.uuid4().hex[:16], "state": "running", "progress": AdvisorProgress(), "control": Control(), "result": None, "error": None, "created": time.time()}

        def run():
            try:
                job["result"] = suggest(system, custom_materials, spec, ns, job["progress"], job["control"])
                job["state"] = job["result"]["status"]
            except Exception as exc:  # reported to the client
                job["error"] = f"{type(exc).__name__}: {exc}"
                job["state"] = "failed"

        with self._lock:
            done = sorted((j for j in self._jobs.values() if j["state"] != "running"), key=lambda j: j["created"])
            for j in done[: max(0, len(self._jobs) - self.max_jobs + 1)]:
                self._jobs.pop(j["id"], None)
            self._jobs[job["id"]] = job
        threading.Thread(target=run, daemon=True, name=f"adv-{job['id']}").start()
        return job

    def get(self, job_id: str):
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job:
            return False
        job["control"].cancel.set()
        return True
