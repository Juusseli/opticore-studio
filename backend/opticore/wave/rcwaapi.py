"""Gratings behind the API: profiles, materials, order tables, phases, convergence and sweeps (RCWA, wave/rcwa.py).

A grating is a stack of layers between an incident medium and a substrate, periodic in x with period L. A layer is

* uniform: one medium;
* lamellar: a ridge of width fill · L centred in the period, the groove medium beside it;
* sinusoidal, sawtooth (blazed) or trapezoid surface relief of the layer's thickness h: the ridge medium lies below the
  surface y(x) (measured from the layer's substrate side), y = h (1 + cos 2πx)/2, y = h x, or a centred trapezoid
  whose width changes linearly from fill_bottom to fill_top. The layer is cut into `slices` lamellar slices, each with
  the profile's width at its mid-height (a staircase that converges to the profile).

Media are an index n + iκ (κ ≥ 0 absorbing) or a library material (its index at the wavelength).

Per order m: the angles of the propagating reflected and transmitted waves (sin θ = k_x,m / n in the plane of
incidence for φ = 0), the efficiencies R_m and T_m, and for the zeroth orders the complex amplitudes projected on the
TE and TM unit vectors of the outgoing wave. The phase delay is reported (physics convention: the delay k · OPL is
positive); the retardance of the zeroth transmitted order is the TE delay minus the TM delay. The convergence estimate
is the largest change of any efficiency between the requested harmonics and 60 % of them.

Crossed gratings and metasurfaces (period_y_um given; wave/rcwa2d.py): the cell is period_um × period_y_um and a
layer may also be a pattern: a background (the groove medium) with shapes on it, rectangles or ellipses with a centre,
two sizes, a rotation and a medium (the layer's ridge medium when none is given). The 1D profiles become stripes along
y (lines periodic in x). Orders are (m, q) with the directions (polar angle θ and azimuth φ) of the propagating ones;
the zeroth orders also give the power converted into the orthogonal polarisation.

From the API the runs (the point, the convergence check, the sweep in chunks) go to the shared process pool
(workers.py): its workers use one BLAS thread, which suits these small dense matrices (OpenBLAS's default threading
makes them up to hundreds of times slower when other work is running), and the sweep runs in parallel.
"""

from __future__ import annotations

import math
from typing import Callable

import numpy as np

from .rcwa import GratingLayer, RcwaError, solve
from .rcwa2d import MAX_ORDERS, PatternLayer, Shape, check_shapes, from_1d, solve2d

IndexFn = Callable[[str, float], float]


def medium(spec: dict | None, lam: float, index_of: IndexFn, what: str) -> complex:
    """(n + iκ) of a medium spec {n, k, material}."""
    if not spec:
        raise RcwaError(f"{what}: give an index or a material")
    if spec.get("material"):
        n = float(index_of(spec["material"], lam))
    elif spec.get("n") is not None:
        n = float(spec["n"])
    else:
        raise RcwaError(f"{what}: give an index or a material")
    k = float(spec.get("k") or 0.0)
    if not n > 0 or k < 0:
        raise RcwaError(f"{what}: the index must be positive and the extinction not negative")
    return complex(n, k)


def _width_at(kind: str, eta: float, layer: dict) -> tuple[float, float]:
    """(x0, x1) of the ridge at height fraction eta (0 at the substrate side, 1 at the top) of a relief layer."""
    if kind == "sinusoidal":
        w = math.acos(max(-1.0, min(1.0, 2.0 * eta - 1.0))) / math.pi
        return 0.5 - w / 2, 0.5 + w / 2
    if kind == "sawtooth":
        return eta, 1.0
    if kind == "trapezoid":
        fb, ft = float(layer.get("fill_bottom", 0.5)), float(layer.get("fill_top", 0.5))
        w = fb + (ft - fb) * eta
        return 0.5 - w / 2, 0.5 + w / 2
    raise RcwaError(f"Unknown profile '{kind}'")


def build(spec: dict, lam: float, index_of: IndexFn) -> tuple[list[GratingLayer], list[dict]]:
    """Grating layers (sliced) and a description of the slices for drawing: [{z0, z1, groove, segments: [[x0, x1, n]]}]."""
    out: list[GratingLayer] = []
    draw: list[dict] = []
    z = 0.0
    for k, L in enumerate(spec.get("layers") or []):
        kind = L.get("kind", "uniform")
        if kind == "pattern":
            raise RcwaError(f"Layer {k + 1}: a pattern of shapes needs a crossed grating (give the period in y)")
        h = float(L.get("thickness_um") or 0.0)
        if h < 0:
            raise RcwaError(f"Layer {k + 1}: the thickness must not be negative")
        if kind == "uniform":
            n = medium(L.get("ridge"), lam, index_of, f"Layer {k + 1}")
            out.append(GratingLayer(h, n * n))
            draw.append({"z0": z, "z1": z + h, "groove": [n.real, n.imag], "segments": [], "layer": k})
            z += h
            continue
        nr = medium(L.get("ridge"), lam, index_of, f"Layer {k + 1} ridge")
        ng = medium(L.get("groove"), lam, index_of, f"Layer {k + 1} groove")
        if kind == "lamellar":
            f = float(L.get("fill", 0.5))
            if not 0.0 <= f <= 1.0:
                raise RcwaError(f"Layer {k + 1}: the fill factor must lie in 0…1")
            segs = [(0.5 - f / 2, 0.5 + f / 2)] if f > 0 else []
            out.append(GratingLayer(h, ng * ng, [(a, b, nr * nr) for a, b in segs]))
            draw.append({"z0": z, "z1": z + h, "groove": [ng.real, ng.imag], "segments": [[a, b, nr.real, nr.imag] for a, b in segs], "layer": k})
            z += h
            continue
        S = int(L.get("slices") or 10)
        if not 1 <= S <= 200:
            raise RcwaError(f"Layer {k + 1}: 1 to 200 slices")
        dz = h / S
        for j in range(S):
            eta = 1.0 - (j + 0.5) / S  # from the top (incident side) down to the substrate side
            a, b = _width_at(kind, eta, L)
            a, b = max(0.0, a), min(1.0, b)
            segs = [(a, b)] if b - a > 1e-12 else []
            out.append(GratingLayer(dz, ng * ng, [(x0, x1, nr * nr) for x0, x1 in segs]))
            draw.append({"z0": z, "z1": z + dz, "groove": [ng.real, ng.imag], "segments": [[x0, x1, nr.real, nr.imag] for x0, x1 in segs], "layer": k})
            z += dz
    return out, draw


def build2d(spec: dict, lam: float, index_of: IndexFn) -> tuple[list[PatternLayer], list[dict]]:
    """Layers of a crossed grating and their drawing: [{z0, z1, groove, shapes: [{kind, cx, cy, a, b, angle, n, k}]}]."""
    Lx, Ly = float(spec["period_um"]), float(spec["period_y_um"])
    out: list[PatternLayer] = []
    draw: list[dict] = []
    z = 0.0
    for k, L in enumerate(spec.get("layers") or []):
        if L.get("kind") != "pattern":
            sub, sdraw = build(dict(spec, layers=[L]), lam, index_of)
            for g, d in zip(sub, sdraw):
                pl = from_1d(g, Lx, Ly)
                out.append(pl)
                shapes = [{"kind": "rectangle", "cx": sh.cx, "cy": sh.cy, "a": sh.a, "b": sh.b, "angle": 0.0,
                           "n": complex(np.sqrt(sh.eps)).real, "k": complex(np.sqrt(sh.eps)).imag} for sh in pl.shapes]
                draw.append({"z0": z + d["z0"], "z1": z + d["z1"], "groove": d["groove"], "shapes": shapes, "layer": k})
            z += float(L.get("thickness_um") or 0.0)
            continue
        h = float(L.get("thickness_um") or 0.0)
        if h < 0:
            raise RcwaError(f"Layer {k + 1}: the thickness must not be negative")
        ng = medium(L.get("groove"), lam, index_of, f"Layer {k + 1} background")
        ridge = L.get("ridge")
        shapes, sdraw = [], []
        for j, sh in enumerate(L.get("shapes") or []):
            nm = medium(sh.get("medium") or ridge, lam, index_of, f"Layer {k + 1} shape {j + 1}")
            S = Shape(sh.get("kind", "rectangle"), float(sh["cx_um"]), float(sh["cy_um"]), float(sh["a_um"]), float(sh["b_um"]), nm * nm, float(sh.get("angle_deg", 0.0)))
            shapes.append(S)
            sdraw.append({"kind": S.kind, "cx": S.cx, "cy": S.cy, "a": S.a, "b": S.b, "angle": S.angle_deg, "n": nm.real, "k": nm.imag})
        out.append(PatternLayer(h, ng * ng, shapes))
        draw.append({"z0": z, "z1": z + h, "groove": [ng.real, ng.imag], "shapes": sdraw, "layer": k})
        z += h
    return out, draw


def _pol(p: str) -> list[tuple[str, tuple[float, float]]]:
    if p == "unpolarised":
        return [("TE", (1.0, 0.0)), ("TM", (0.0, 1.0))]
    return [(p, (1.0, 0.0) if p == "TE" else (0.0, 1.0))]


def _te_tm(kvec: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    k = kvec / np.linalg.norm(kvec)
    a = np.cross([0.0, 0.0, 1.0], k)
    a = np.array([0.0, 1.0, 0.0]) if np.linalg.norm(a) < 1e-12 else a / np.linalg.norm(a)
    b = np.cross(k, a)
    return a, b / np.linalg.norm(b)


def _zeroth(res: dict, kz_in: float, idx=None) -> dict:
    """Complex zeroth-order amplitudes on the outgoing TE/TM vectors: |amplitude|², the phase delay (degrees, physics
    sign) and the power fraction. idx: the zeroth order's index (default the middle of a 1D result)."""
    M = len(res["orders"]) // 2 if idx is None else idx
    out = {}
    for side, vec, kz in (("r", res["r"], -res["kz_ref"][M]), ("t", res["t"], res["kz_trn"][M])):
        if abs(np.imag(kz)) > 1e-12 or abs(np.real(kz)) < 1e-12:
            continue
        kv = np.array([res["kx"][M], res["ky"][M], float(np.real(kz))])
        a_te, a_tm = _te_tm(kv)
        e = np.array([vec[0][M], vec[1][M], vec[2][M]])
        for name, a in (("TE", a_te), ("TM", a_tm)):
            amp = complex(np.dot(e, a))
            out[f"{side}_{name}"] = {"abs2": abs(amp) ** 2, "delay_deg": float(-math.degrees(math.atan2(amp.imag, amp.real))),
                                     "power": abs(float(np.real(kz))) / kz_in * abs(amp) ** 2}
    return out


def _wrap(d: float) -> float:
    return (d + 180.0) % 360.0 - 180.0


def _direction(kx: float, ky: float, n: float) -> tuple[float, float]:
    """Polar angle and azimuth (degrees) of a propagating order with in-plane wave vector (kx, ky) in a medium n."""
    s = math.hypot(kx, ky)
    return math.degrees(math.asin(max(-1.0, min(1.0, s / n)))), (math.degrees(math.atan2(ky, kx)) if s > 1e-12 else 0.0)


def _run2d(spec: dict, index_of: IndexFn, lam: float, th: float, ph: float, M: int, My: int, n_in: complex, n_out: complex) -> dict:
    Lx, Ly = float(spec["period_um"]), float(spec["period_y_um"])
    layers, _ = build2d(spec, lam, index_of)
    pol = spec.get("polarisation", "TE")
    parts = [(name, solve2d(Lx, Ly, layers, n_in.real**2, n_out * n_out, lam, th, ph, p, M, My)) for name, p in _pol(pol)]
    R = sum(r["R"] for _, r in parts) / len(parts)
    T = sum(r["T"] for _, r in parts) / len(parts)
    r0 = parts[0][1]
    orders = []
    for i, j in np.ndindex(R.shape):
        pr, pt = bool(r0["propagating_r"][i, j]), bool(r0["propagating_t"][i, j])
        if not (pr or pt):
            continue
        kx, ky = float(r0["kx"][i, j]), float(r0["ky"][i, j])
        row = {"m": int(r0["p"][i, j]), "q": int(r0["q"][i, j]), "R": float(R[i, j]) if pr else None, "T": float(T[i, j]) if pt else None}
        if pr:
            row["angle_r_deg"], row["azimuth_r_deg"] = _direction(kx, ky, n_in.real)
        if pt:
            row["angle_t_deg"], row["azimuth_t_deg"] = _direction(kx, ky, n_out.real)
        orders.append(row)
    out = {"wavelength_um": lam, "theta_deg": th, "phi_deg": ph, "polarisation": pol, "harmonics": M, "harmonics_y": My, "orders": orders,
           "total_R": float(R.sum()), "total_T": float(T.sum()), "absorbed": float(1.0 - R.sum() - T.sum())}
    kz_in = n_in.real * math.cos(math.radians(th))
    zeroth = {}
    for name, r in parts:
        z = _zeroth(r, kz_in, (M, My))
        other = "TM" if name == "TE" else "TE"
        t, rr = z.get(f"t_{name}"), z.get(f"r_{name}")
        if t is not None and z.get(f"t_{other}") is not None:
            t = dict(t, cross_power=z[f"t_{other}"]["power"])
        if rr is not None and z.get(f"r_{other}") is not None:
            rr = dict(rr, cross_power=z[f"r_{other}"]["power"])
        zeroth[name] = {"t": t, "r": rr}
    out["zeroth"] = zeroth
    return out


def run(spec: dict, index_of: IndexFn, harmonics: int | None = None, wavelength_um: float | None = None, theta_deg: float | None = None,
        harmonics_y: int | None = None) -> dict:
    lam = float(wavelength_um if wavelength_um is not None else spec["wavelength_um"])
    th = float(theta_deg if theta_deg is not None else spec.get("theta_deg", 0.0))
    ph = float(spec.get("phi_deg", 0.0))
    period = float(spec["period_um"])
    M = int(harmonics if harmonics is not None else spec.get("harmonics", 20))
    n_in = medium(spec.get("incident") or {"n": 1.0}, lam, index_of, "Incident medium")
    if n_in.imag != 0:
        raise RcwaError("The incident medium must be lossless")
    n_out = medium(spec.get("substrate"), lam, index_of, "Substrate")
    if spec.get("period_y_um"):
        My = int(harmonics_y if harmonics_y is not None else spec.get("harmonics_y", 5))
        return _run2d(spec, index_of, lam, th, ph, M, My, n_in, n_out)
    layers, _ = build(spec, lam, index_of)
    pol = spec.get("polarisation", "TE")
    parts = []
    for name, p in _pol(pol):
        r = solve(period, layers, n_in.real**2, n_out * n_out, lam, th, ph, p, M)
        parts.append((name, r))
    R = sum(r["R"] for _, r in parts) / len(parts)
    T = sum(r["T"] for _, r in parts) / len(parts)
    r0 = parts[0][1]
    orders = []
    for i, m in enumerate(r0["orders"]):
        pr, pt = bool(r0["propagating_r"][i]), bool(r0["propagating_t"][i])
        if not (pr or pt):
            continue
        kx = float(r0["kx"][i])
        row = {"m": int(m), "R": float(R[i]) if pr else None, "T": float(T[i]) if pt else None}
        if pr:
            row["angle_r_deg"] = math.degrees(math.asin(max(-1.0, min(1.0, kx / n_in.real))))
        if pt:
            row["angle_t_deg"] = math.degrees(math.asin(max(-1.0, min(1.0, kx / n_out.real))))
        orders.append(row)
    out = {"wavelength_um": lam, "theta_deg": th, "phi_deg": ph, "polarisation": pol, "harmonics": M, "orders": orders,
           "total_R": float(R.sum()), "total_T": float(T.sum()), "absorbed": float(1.0 - R.sum() - T.sum())}
    zeroth = {}
    kz_in = n_in.real * math.cos(math.radians(th))
    for name, r in parts:
        z = _zeroth(r, kz_in)
        zeroth[name] = z.get(f"t_{name}"), z.get(f"r_{name}")
    out["zeroth"] = {name: {"t": t, "r": rr} for name, (t, rr) in zeroth.items()}
    return out


def _chunk(spec: dict, custom: list, jobs: list[dict]) -> list[dict]:
    """Runs of one pool task (top level, so that it pickles)."""
    from ..materials import MaterialLibrary

    lib = MaterialLibrary(custom)
    ix = lambda name, lam: lib.index(name, lam)  # noqa: E731
    return [run(spec, ix, **kw) for kw in jobs]


def _runs(spec: dict, index_of: IndexFn, custom: list | None, jobs: list[dict]) -> list[dict]:
    """The runs, on the process pool when the request's materials are given (API), else here (tests, workers)."""
    from .. import workers

    if custom is None or workers.in_worker() or len(jobs) == 0:
        return [run(spec, index_of, **kw) for kw in jobs]
    n = max(1, min(len(jobs), 2 * workers.worker_count()))
    parts = [jobs[i::n] for i in range(n)]
    pool, flag = workers.acquire()
    broken = False
    try:
        futs = [pool.submit(_chunk, spec, custom, part) for part in parts]
        got = [f.result() for f in futs]
    except Exception as exc:  # noqa: BLE001 - a broken pool is replaced; the error is re-raised
        from concurrent.futures.process import BrokenProcessPool

        broken = isinstance(exc, BrokenProcessPool)
        for f in futs:  # the other runs are not wanted any more
            f.cancel()
        raise
    finally:
        workers.release(flag, broken=broken)
    out: list[dict | None] = [None] * len(jobs)
    for i, part in enumerate(got):
        for j, r in enumerate(part):
            out[i + j * n] = r
    return out  # type: ignore[return-value]


def analyse(spec: dict, index_of: IndexFn, custom_materials: list | None = None) -> dict:
    """One wavelength and angle: the order table, zeroth-order phases (and the TE−TM retardance when both are
    computed), the convergence estimate, the structure for drawing; optionally a sweep. With custom_materials (the
    API) the runs go to the process pool."""
    lam = float(spec["wavelength_um"])
    crossed = bool(spec.get("period_y_um"))
    M = int(spec.get("harmonics", 20))
    M2 = max(1, int(round(0.6 * M)))
    My = int(spec.get("harmonics_y", 5)) if crossed else 0
    My2 = max(1, int(round(0.6 * My))) if crossed else 0
    lower = M2 < M or (crossed and My2 < My)
    low_job = {"harmonics": min(M2, M)} | ({"harmonics_y": min(My2, My)} if crossed else {})
    # validate here, before any run is sent to the pool (a refused request must not leave its other runs computing)
    if crossed:
        if (2 * M + 1) * (2 * My + 1) > MAX_ORDERS:
            raise RcwaError(f"{(2 * M + 1) * (2 * My + 1)} orders: at most {MAX_ORDERS} ((2Mx+1)(2My+1)); lower the harmonics")
        check_shapes(build2d(spec, lam, index_of)[0], float(spec["period_um"]), float(spec["period_y_um"]))
    else:
        build(spec, lam, index_of)
    sw = spec.get("sweep")
    xs = np.linspace(float(sw["start"]), float(sw["stop"]), int(sw.get("points", 51))) if sw and sw.get("kind") in ("wavelength", "angle") else None
    jobs: list[dict] = [{}] + ([low_job] if lower else [])
    if xs is not None:
        key = "wavelength_um" if sw["kind"] == "wavelength" else "theta_deg"
        jobs += [{key: float(x)} for x in xs]
    done = _runs(spec, index_of, custom_materials, jobs)
    res = done[0]
    k = 1
    if lower:
        low = done[k]
        k += 1
        by = {(o["m"], o.get("q", 0)): o for o in low["orders"]}
        diff = 0.0
        for o in res["orders"]:
            q = by.get((o["m"], o.get("q", 0)), {})
            for key in ("R", "T"):
                if o.get(key) is not None:
                    diff = max(diff, abs(o[key] - (q.get(key) or 0.0)))
        res["convergence"] = {"harmonics_low": low_job["harmonics"], "max_change": diff} | ({"harmonics_y_low": low_job["harmonics_y"]} if crossed else {})
    if spec.get("polarisation") == "unpolarised":
        te, tm = res["zeroth"].get("TE", {}).get("t"), res["zeroth"].get("TM", {}).get("t")
        if te and tm:
            res["retardance_deg"] = _wrap(te["delay_deg"] - tm["delay_deg"])
    if crossed:
        _, draw = build2d(spec, lam, index_of)
        res["structure"] = {"period_um": float(spec["period_um"]), "period_y_um": float(spec["period_y_um"]), "slices": draw}
    else:
        _, draw = build(spec, lam, index_of)
        res["structure"] = {"period_um": float(spec["period_um"]), "slices": draw}
    notes = []
    if res["absorbed"] < -1e-9:
        notes.append(f"Reflected plus transmitted power exceeds the incident by {-res['absorbed']:.2e}: raise the harmonics")
    if res.get("convergence") and res["convergence"]["max_change"] > 1e-3:
        lo = f"{low_job['harmonics']} × {low_job['harmonics_y']}" if crossed else f"{M2}"
        hi = f"{M} × {My}" if crossed else f"{M}"
        notes.append(f"Efficiencies change by up to {res['convergence']['max_change']:.2g} between {lo} and {hi} harmonics: raise the harmonics")
    res["notes"] = notes
    if xs is not None:
        if crossed:
            want2 = sorted({(int(a), int(b)) for a, b in (sw.get("orders_2d") or [[0, 0]])})
            keys = [(f"({a},{b})", (a, b)) for a, b in want2]
        else:
            want = sorted({int(m) for m in (sw.get("orders") or [-1, 0, 1])})
            keys = [(f"{m}", (m, 0)) for m in want]
        curves = {f"R{n}": [] for n, _ in keys} | {f"T{n}": [] for n, _ in keys}
        curves["R"] = []
        curves["T"] = []
        for r in done[k:]:
            by = {(o["m"], o.get("q", 0)): o for o in r["orders"]}
            for n, key in keys:
                o = by.get(key, {})
                curves[f"R{n}"].append(o.get("R"))
                curves[f"T{n}"].append(o.get("T"))
            curves["R"].append(r["total_R"])
            curves["T"].append(r["total_T"])
        res["sweep"] = {"kind": sw["kind"], "x": xs.tolist(), "orders": [n for n, _ in keys], "curves": curves}
    if crossed:
        res["method"] = (f"Rigorous coupled-wave analysis of a crossed grating, S-matrix formulation, {2 * M + 1} × {2 * My + 1} orders, Li's fast Fourier "
                         "factorisation (inverse rule along x for Ex and along y for Ey, line by line; curved and rotated boundaries as fine "
                         "staircases in that rule); relief profiles as lamellar slices")
    else:
        res["method"] = (f"Rigorous coupled-wave analysis, S-matrix formulation, {2 * M + 1} orders, Li's Fourier factorisation (inverse rule for the field "
                         "normal to the grating lines); relief profiles as lamellar slices")
    return res
