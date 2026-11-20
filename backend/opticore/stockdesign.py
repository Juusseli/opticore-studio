"""Optical systems built from stock lenses: search, prescreen and optimise on the process pool.

**Build.** From a specification, ordered combinations of 1-3 stock lenses (each either way round, a symmetric lens
once; the same part may be used twice) are placed in air:

1. **First order** (vectorised over every combination, reduced 2 x 2 matrices at the primary wavelength, stock.py).
   With lens matrices L_i and air gaps T(d) = [[1, d], [0, 1]] the system matrix from the first to the last vertex is
   M = L_n T(d_{n-1}) ... T(d_1) L_1.
   * Object at infinity, target EFL f: C(M) = -1/f is linear in the last gap, which is solved; the image is at
     -A/C behind the last vertex. One lens must have |EFL - f| <= tolerance f.
   * Object at the distance s, target magnification m: with N = M T(s) the image is at -B(N)/D(N) and the
     magnification is 1/D(N), linear in the last gap, which is solved. One lens must match m within the tolerance.
   * Three lenses: the first gap takes 6 values from the minimum gap to a limit (log-spaced) and the second is
     solved. Triples are a seeded random sample when there are more than `triples` of them.
   Kept are combinations whose gaps are at least the minimum at the vertices and at the smaller lens's rim, whose
   image distance is at least max(minimum gap, 1 mm), whose length fits, and whose paraxial marginal plus chief ray
   heights fit every lens's clear aperture (stop at the first lens; entrance pupil f/N, or the object NA).
2. **Third-order ranking** (vectorised Seidel sums, the formulas of paraxial.seidel_coefficients): an estimate of
   the RMS wavefront over the fields with one common refocus, from the balanced Zernike RMS of each Seidel term
   (spherical W040/(6 sqrt 5), coma W131 H/(6 sqrt 2), astigmatism W222 H^2/(2 sqrt 6), residual field curvature
   /(2 sqrt 3)) and the spread of the axial and lateral colour over the wavelengths. It only chooses which
   combinations get a real-ray check; it is not reported as a result.
3. **Real-ray prescreen** (process pool): the RMS spot at the best common focus (analysis/focus.py, hexapolar
   density 3) of the best `prescreen` combinations, shared by the lens counts.
4. **Optimisation** (process pool): the best `candidates`, shared by the lens counts, optimised in their air gaps
   and image distance (normal optimiser, local least squares): RMS spot (4 rings), the EFL or magnification target,
   edge clearance between the lenses and the maximum length. Then the normal metrics (designspace.metrics), the
   number of parts and their summed price (when every part has one).

A candidate meets the specification when its EFL or magnification is within the tolerance, it fits the length,
no lenses collide (vertex and rim gaps at least 0.9 times the minimum gap) and every ray of the spot diagram
passes the clear apertures.
"""

from __future__ import annotations

import math
import time
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .designspace import FDC, DesignSpaceSpec, metrics
from .materials import LAMBDA_C, LAMBDA_F, MaterialError, MaterialLibrary
from .model import OpticalSystem
from .optimize.merit import OptimizationSpec
from .stock import StockError, StockLens, generic_library, lens_matrix, lens_surfaces, oriented
from .system import SystemError_, compile_system

GRID_FIRST_GAP = 6


class StockSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conjugate: Literal["infinite", "finite"] = "infinite"
    focal_length: float = Field(default=100.0, gt=0.0, le=10000.0, description="infinite: target EFL (mm)")
    f_number: float = Field(default=5.0, ge=0.5, le=200.0, description="infinite: EPD = f / F#")
    half_field_deg: float = Field(default=1.0, ge=0.0, le=30.0, description="infinite")
    object_distance: float = Field(default=100.0, gt=0.0, le=100000.0, description="finite: object to the first lens vertex (mm)")
    magnification: float = Field(default=-1.0, description="finite: target lateral magnification")
    object_na: float = Field(default=0.05, gt=0.0, lt=0.95, description="finite: object-space numerical aperture")
    object_height: float = Field(default=0.0, ge=0.0, description="finite: largest object height (mm)")
    wavelengths: list[float] = Field(default_factory=lambda: list(FDC), min_length=1, max_length=12)
    primary: int = Field(default=1, ge=0)
    max_length: float | None = Field(default=None, gt=0.0, description="infinite: first vertex to image; finite: object to image (mm)")
    lens_counts: list[int] = Field(default_factory=lambda: [1, 2], min_length=1)
    materials: list[str] | None = Field(default=None, description="allowed glasses (a lens qualifies when all its glasses are allowed); null = all")
    generic: bool = Field(default=True, description="include the built-in generic library")
    min_gap: float = Field(default=0.5, ge=0.0, description="minimum air gap at the vertices and the rims (mm)")
    tolerance: float = Field(default=0.01, gt=0.0, le=0.5, description="relative tolerance of the EFL or magnification")
    candidates: int = Field(default=40, ge=1, le=400)
    prescreen: int = Field(default=1500, ge=1, le=20000)
    triples: int = Field(default=200000, ge=1000, le=2000000)
    mtf_frequency: float = Field(default=30.0, gt=0.0)
    tolerances: bool = False
    seed: int = 1

    @model_validator(mode="after")
    def _check(self):
        if not self.primary < len(self.wavelengths):
            raise ValueError("primary must index a wavelength")
        if any(n not in (1, 2, 3) for n in self.lens_counts):
            raise ValueError("lens counts are 1, 2 or 3")
        if self.conjugate == "finite" and self.magnification == 0.0:
            raise ValueError("the magnification cannot be zero")
        return self


class StockDesignError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------- lens table
def lens_pool(spec: StockSpec, lenses: list[StockLens], custom_materials=()) -> list[StockLens]:
    """Generic (when asked) plus the given lenses, without duplicates, restricted to the allowed glasses."""
    pool: dict[str, StockLens] = {}
    for l in (generic_library() if spec.generic else []) + list(lenses):
        pool.setdefault(l.key, l)
    out = list(pool.values())
    if spec.materials is not None:
        allowed = {m.strip().upper() for m in spec.materials}
        out = [l for l in out if all(m.upper() in allowed for m in l.materials)]
    lib = MaterialLibrary(list(custom_materials))
    lo, hi = min(spec.wavelengths), max(spec.wavelengths)
    good = []
    for l in out:
        try:
            if all(lib.get(m).dispersion.lambda_min <= lo + 1e-9 and hi <= lib.get(m).dispersion.lambda_max + 1e-9 for m in l.materials):
                good.append(l)
        except MaterialError:
            continue
    if not good:
        raise StockDesignError("No stock lens is available: choose catalogues, allowed glasses or wavelengths the lenses cover")
    return good


def _symmetric(l: StockLens) -> bool:
    r, t, m = oriented(l, True)
    return t == l.thicknesses and [x.upper() for x in m] == [x.upper() for x in l.materials] and all(
        (a is None and b is None) or (a is not None and b is not None and abs(a - b) <= 1e-9 * abs(a)) for a, b in zip(r, l.radii)
    )


def _sag(c: np.ndarray, r: np.ndarray) -> np.ndarray:
    x = 1.0 - (c * r) ** 2
    with np.errstate(invalid="ignore"):
        return np.where(x >= 0.0, c * r * r / (1.0 + np.sqrt(np.maximum(x, 0.0))), np.nan)


def entry_table(lenses: list[StockLens], spec: StockSpec, custom_materials=()) -> dict:
    """Every lens and orientation as arrays: matrix at the primary wavelength, length, diameters, outer curvatures
    and the padded surface data for the third-order sums (three surfaces per lens)."""
    lib = MaterialLibrary(list(custom_materials))
    lp = spec.wavelengths[spec.primary]
    rows = []
    for li, l in enumerate(lenses):
        for rev in (False, True):
            if rev and _symmetric(l):
                continue
            M = lens_matrix(l, lib, lp, rev)
            if abs(M[1, 0]) < 1e-14:
                continue
            radii, thick, mats = oriented(l, rev)
            curv = [0.0 if r is None else 1.0 / r for r in radii] + [0.0] * (3 - len(radii))
            n_after = [lib.index(m, lp) for m in mats] + [1.0] * (3 - len(mats))
            dn_after = [lib.index(m, LAMBDA_F) - lib.index(m, LAMBDA_C) for m in mats] + [0.0] * (3 - len(mats))
            t_next = list(thick) + [0.0] * (3 - len(thick))
            rows.append((li, rev, M, sum(thick), l.diameter, l.clear, curv, n_after, dn_after, t_next))
    if not rows:
        raise StockDesignError("No usable stock lens (afocal or missing data)")
    E = {
        "lens": np.array([r[0] for r in rows]),
        "rev": np.array([r[1] for r in rows]),
        "A": np.array([r[2][0, 0] for r in rows]),
        "B": np.array([r[2][0, 1] for r in rows]),
        "C": np.array([r[2][1, 0] for r in rows]),
        "D": np.array([r[2][1, 1] for r in rows]),
        "L": np.array([r[3] for r in rows]),
        "dia": np.array([r[4] for r in rows]),
        "clear": np.array([r[5] for r in rows]) / 2.0,
        "curv": np.array([r[6] for r in rows]),
        "n": np.array([r[7] for r in rows]),
        "dn": np.array([r[8] for r in rows]),
        "t": np.array([r[9] for r in rows]),
    }
    # outer surfaces in the light direction: the first one and the last real one
    nsurf = np.array([len(lenses[r[0]].radii) for r in rows])
    E["c_first"] = E["curv"][:, 0]
    E["c_last"] = E["curv"][np.arange(len(rows)), nsurf - 1]
    E["nmean"] = np.array([np.mean(r[7][: len(lenses[r[0]].materials)]) for r in rows])
    return E


# ---------------------------------------------------------------------------------------------- first order
def _mul(a, b):
    """Product of stacked 2 x 2 matrices given as tuples (A, B, C, D) of arrays."""
    A1, B1, C1, D1 = a
    A2, B2, C2, D2 = b
    return (A1 * A2 + B1 * C2, A1 * B2 + B1 * D2, C1 * A2 + D1 * C2, C1 * B2 + D1 * D2)


def _gap(d):
    one = np.ones_like(d)
    return (one, d, np.zeros_like(d), one)


def _entry(E, idx):
    return (E["A"][idx], E["B"][idx], E["C"][idx], E["D"][idx])


def solve_last_gap(P, Lq, spec: StockSpec):
    """The last air gap d that meets the first-order target for the partial system P (first vertex to the last gap)
    followed by the lens Lq: the result is linear in d (module docstring). Returns d (NaN where impossible)."""
    A1, B1, C1, D1 = P
    A2, B2, C2, D2 = Lq
    if spec.conjugate == "infinite":
        # C(M) = C2 (A1 + d C1) + D2 C1 = -1/f
        a = C2 * A1 + D2 * C1
        b = C2 * C1
        target = -1.0 / spec.focal_length
    else:
        s = spec.object_distance
        # D(N) of N = M T(s): C(M) s + D(M); C(M) = a0 + d b0, D(M) = C2 (B1 + d D1) + D2 D1
        a = (C2 * A1 + D2 * C1) * s + C2 * B1 + D2 * D1
        b = C2 * C1 * s + C2 * D1
        target = 1.0 / spec.magnification
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(np.abs(b) > 1e-18, (target - a) / b, np.nan)


def image_distance(M, spec: StockSpec):
    """Image distance behind the last vertex and the first-order value (EFL or magnification) of M."""
    A, B, C, D = M
    with np.errstate(divide="ignore", invalid="ignore"):
        if spec.conjugate == "infinite":
            return -A / C, -1.0 / C
        s = spec.object_distance
        Bn, Dn = A * s + B, C * s + D
        return -Bn / Dn, 1.0 / Dn


def _paraxial_rays(spec: StockSpec) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    """(y, nu) of the marginal and chief rays at the first vertex (stop there) and the Lagrange invariant."""
    if spec.conjugate == "infinite":
        y, nu = spec.focal_length / spec.f_number / 2.0, 0.0
        yb, nub = 0.0, math.tan(math.radians(spec.half_field_deg))
        return np.array(y), np.array(nu), np.array(yb), np.array(nub), float(nub * y)
    u0 = math.tan(math.asin(spec.object_na))
    s, h = spec.object_distance, spec.object_height
    return np.array(s * u0), np.array(u0), np.array(0.0), np.array(-h / s), float(-h * u0)


def _check(combo_entries: list[np.ndarray], gaps: list[np.ndarray], E, spec: StockSpec) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Feasibility of combinations (first-order solved): gaps, rims, image distance, length and the paraxial beam
    in the clear apertures. Returns (ok, image distance, first-order value)."""
    n = len(combo_entries)
    M = _entry(E, combo_entries[0])
    for k in range(1, n):
        M = _mul(_entry(E, combo_entries[k]), _mul(_gap(gaps[k - 1]), M))
    d_img, value = image_distance(M, spec)
    ok = np.isfinite(d_img) & (d_img >= max(spec.min_gap, 1.0))
    target = spec.focal_length if spec.conjugate == "infinite" else spec.magnification
    ok &= np.abs(value - target) <= spec.tolerance * abs(target) + 1e-9
    for k, g in enumerate(gaps):
        ok &= np.isfinite(g) & (g >= spec.min_gap)
        a, b = combo_entries[k], combo_entries[k + 1]
        r = np.minimum(E["dia"][a], E["dia"][b]) / 2.0
        rim = g + _sag(E["c_first"][b], r) - _sag(E["c_last"][a], r)
        ok &= np.isfinite(rim) & (rim >= spec.min_gap)
    length = sum(E["L"][e] for e in combo_entries) + sum(gaps) + d_img
    if spec.conjugate == "finite":
        length = length + spec.object_distance
    if spec.max_length is not None:
        ok &= length <= spec.max_length
    # paraxial marginal + chief heights at every lens (front and back vertex) within the clear aperture
    y, nu, yb, nub, _ = _paraxial_rays(spec)
    y = np.broadcast_to(y, ok.shape).astype(float)
    nu = np.broadcast_to(nu, ok.shape).astype(float)
    yb = np.broadcast_to(yb, ok.shape).astype(float)
    nub = np.broadcast_to(nub, ok.shape).astype(float)
    for k, e in enumerate(combo_entries):
        lim = E["clear"][e] * 0.98
        ok &= np.abs(y) + np.abs(yb) <= lim
        A, B, C, D = _entry(E, e)
        y, nu = A * y + B * nu, C * y + D * nu
        yb, nub = A * yb + B * nub, C * yb + D * nub
        ok &= np.abs(y) + np.abs(yb) <= lim
        if k < n - 1:
            y, yb = y + gaps[k] * nu, yb + gaps[k] * nub
    return ok, d_img, value


def enumerate_first_order(E, spec: StockSpec, chunk: int = 400000) -> list[dict]:
    """Every feasible combination: {'n', 'entries' (k x n), 'gaps' (k x n-1), 'd_img', 'value'} per lens count."""
    ne = len(E["A"])
    out = []
    rng = np.random.default_rng(spec.seed)
    for n in sorted(set(spec.lens_counts)):
        ent, gp, di, va = [], [], [], []
        if n == 1:
            e = np.arange(ne)
            ok, d_img, value = _check([e], [], E, spec)
            ent.append(e[ok][:, None])
            gp.append(np.zeros((int(ok.sum()), 0)))
            di.append(d_img[ok])
            va.append(value[ok])
        elif n == 2:
            idx = np.arange(ne)
            step = max(1, chunk // ne)
            for i0 in range(0, ne, step):
                a = np.repeat(idx[i0 : i0 + step], ne)
                b = np.tile(idx, min(step, ne - i0))
                d = solve_last_gap(_entry(E, a), _entry(E, b), spec)
                ok, d_img, value = _check([a, b], [d], E, spec)
                ent.append(np.stack([a[ok], b[ok]], 1))
                gp.append(d[ok][:, None])
                di.append(d_img[ok])
                va.append(value[ok])
        else:
            total = ne**3
            if total <= spec.triples:
                t = np.stack(np.unravel_index(np.arange(total), (ne, ne, ne)), 1)
            else:
                t = rng.integers(0, ne, size=(spec.triples, 3))
            scale = spec.focal_length if spec.conjugate == "infinite" else spec.object_distance
            g_hi = min(spec.max_length, 2.0 * scale) if spec.max_length is not None else 2.0 * scale
            grid = np.geomspace(max(spec.min_gap, 0.05), max(g_hi, 2 * max(spec.min_gap, 0.05)), GRID_FIRST_GAP)
            for i0 in range(0, len(t), max(1, chunk // GRID_FIRST_GAP)):
                tt = t[i0 : i0 + max(1, chunk // GRID_FIRST_GAP)]
                a = np.repeat(tt[:, 0], GRID_FIRST_GAP)
                b = np.repeat(tt[:, 1], GRID_FIRST_GAP)
                c = np.repeat(tt[:, 2], GRID_FIRST_GAP)
                d1 = np.tile(grid, len(tt))
                P = _mul(_entry(E, b), _mul(_gap(d1), _entry(E, a)))
                d2 = solve_last_gap(P, _entry(E, c), spec)
                ok, d_img, value = _check([a, b, c], [d1, d2], E, spec)
                ent.append(np.stack([a[ok], b[ok], c[ok]], 1))
                gp.append(np.stack([d1[ok], d2[ok]], 1))
                di.append(d_img[ok])
                va.append(value[ok])
        if ent:
            out.append({"n": n, "entries": np.concatenate(ent), "gaps": np.concatenate(gp), "d_img": np.concatenate(di), "value": np.concatenate(va)})
    return out


# ---------------------------------------------------------------------------------------------- third order
def seidel_sums(E, entries: np.ndarray, gaps: np.ndarray, spec: StockSpec) -> dict[str, np.ndarray]:
    """Seidel sums S_I..S_V, C_L, C_T of combinations (rows of entries and gaps), vectorised; the formulas of
    paraxial.seidel_coefficients with the stop at the first vertex (no aspheres in stock lenses)."""
    k = len(entries)
    y0, nu0, yb0, nub0, H = _paraxial_rays(spec)
    y = np.full(k, float(y0))
    nu = np.full(k, float(nu0))
    yb = np.full(k, float(yb0))
    nub = np.full(k, float(nub0))
    S = {key: np.zeros(k) for key in ("SI", "SII", "SIII", "SIV", "SV", "CL", "CT")}
    n_cur = np.ones(k)
    dn_cur = np.zeros(k)
    nl = entries.shape[1]
    for j in range(nl):
        e = entries[:, j]
        for s in range(3):
            c = E["curv"][e, s]
            n2 = E["n"][e, s]
            dn2 = E["dn"][e, s]
            A = n_cur * y * c + nu
            Ab = n_cur * yb * c + nub
            nu2 = nu - y * c * (n2 - n_cur)
            nub2 = nub - yb * c * (n2 - n_cur)
            dun = nu2 / (n2 * n2) - nu / (n_cur * n_cur)
            SI = -A * A * y * dun
            SII = -A * Ab * y * dun
            SIII = -Ab * Ab * y * dun
            SIV = -H * H * c * (1.0 / n2 - 1.0 / n_cur)
            with np.errstate(divide="ignore", invalid="ignore"):
                SV = np.where(np.abs(A) > 1e-15, (Ab / A) * (SIII + SIV), 0.0)
            ddn = dn2 / n2 - dn_cur / n_cur
            S["SI"] += SI
            S["SII"] += SII
            S["SIII"] += SIII
            S["SIV"] += SIV
            S["SV"] += SV
            S["CL"] += A * y * ddn
            S["CT"] += Ab * y * ddn
            t = E["t"][e, s]
            y = y + t * nu2 / n2
            yb = yb + t * nub2 / n2
            nu, nub, n_cur, dn_cur = nu2, nub2, n2, dn2
        if j < nl - 1:
            d = gaps[:, j]
            y = y + d * nu
            yb = yb + d * nub
    return S


def third_order_rms(S: dict[str, np.ndarray], spec: StockSpec) -> np.ndarray:
    """Estimated RMS wavefront (waves) over the fields 0, 0.7, 1 with one common refocus (module docstring)."""
    lam = spec.wavelengths[spec.primary] * 1e-3
    W040, W131, W222, W220 = S["SI"] / 8.0, S["SII"] / 2.0, S["SIII"] / 2.0, (S["SIII"] + S["SIV"]) / 4.0
    hs = [0.0, 0.7, 1.0] if (spec.half_field_deg > 0 if spec.conjugate == "infinite" else spec.object_height > 0) else [0.0]
    chrom = len(spec.wavelengths) > 1
    focus = np.mean([W220 * h * h for h in hs], axis=0)
    tot = np.zeros_like(W040)
    for h in hs:
        v = (W040 / (6.0 * math.sqrt(5.0))) ** 2 + (W131 * h / (6.0 * math.sqrt(2.0))) ** 2 + (W222 * h * h / (2.0 * math.sqrt(6.0))) ** 2
        v = v + ((W220 * h * h - focus) / (2.0 * math.sqrt(3.0))) ** 2
        if chrom:
            v = v + (S["CL"] / 2.0 / math.sqrt(6.0) / (2.0 * math.sqrt(3.0))) ** 2 + (S["CT"] * h / (2.0 * math.sqrt(6.0))) ** 2
        tot = tot + v
    return np.sqrt(tot / len(hs)) / lam


# ---------------------------------------------------------------------------------------------- systems
def build_system(lenses: list[StockLens], combo: list[tuple[int, bool]], gaps: list[float], d_img: float, spec: StockSpec, name: str) -> OpticalSystem:
    surfaces: list[dict] = [{"id": "obj", "label": "Object", "thickness": None if spec.conjugate == "infinite" else spec.object_distance}]
    for k, (li, rev) in enumerate(combo):
        gap = gaps[k] if k < len(gaps) else d_img
        surfaces += lens_surfaces(lenses[li], rev, gap, f"p{k + 1}s", stop_first=(k == 0))
    surfaces.append({"id": "img", "label": "Image"})
    if spec.conjugate == "infinite":
        hf = spec.half_field_deg
        fields = [0.0] if hf == 0 else [0.0, round(0.7 * hf, 6), hf]
        aperture = {"type": "epd", "value": spec.focal_length / spec.f_number}
        ftype = "angle"
    else:
        h = spec.object_height
        fields = [0.0] if h == 0 else [0.0, round(0.7 * h, 6), h]
        aperture = {"type": "object_na", "value": spec.object_na}
        ftype = "object_height"
    return OpticalSystem.model_validate(
        {
            "name": name,
            "surfaces": surfaces,
            "wavelengths": [{"value": w, "weight": 1.0} for w in spec.wavelengths],
            "primary_wavelength": spec.primary,
            "fields": [{"y": y} for y in fields],
            "field_type": ftype,
            "aperture": aperture,
        }
    )


def combo_title(lenses: list[StockLens], combo: list[tuple[int, bool]]) -> str:
    return " + ".join(lenses[li].part + (" (rev.)" if rev else "") for li, rev in combo)


def optimisation_spec(system: OpticalSystem, n: int, spec: StockSpec) -> OptimizationSpec:
    """Air gaps and image distance as variables; RMS spot, the first-order target, rim clearance, length."""
    surfs = system.surfaces
    backs = [i for i, s in enumerate(surfs) if s.label.endswith(" back")]
    scale = spec.focal_length if spec.conjugate == "infinite" else spec.object_distance
    variables, operands = [], [{"type": "rms_spot", "target": 0.0, "weight": 1.0, "rings": 4}]
    for k, i in enumerate(backs):
        t = float(surfs[i].thickness or 0.0)
        if k < n - 1:
            variables.append({"surface_id": surfs[i].id, "parameter": "thickness", "min": spec.min_gap, "max": max(3.0 * t, t + scale, 2.0 * spec.min_gap)})
            operands.append({"type": "min_edge_thickness", "surface_id": surfs[i].id, "target": spec.min_gap, "weight": 1.0})
        else:
            variables.append({"surface_id": surfs[i].id, "parameter": "thickness", "min": max(0.1, spec.min_gap), "max": max(3.0 * t, t + scale)})
    if spec.conjugate == "infinite":
        operands.append({"type": "efl", "target": spec.focal_length, "weight": 1.0})
    else:
        operands.append({"type": "magnification", "target": spec.magnification, "weight": 100.0})
    if spec.max_length is not None:
        operands.append({"type": "max_total_track", "target": spec.max_length - (spec.object_distance if spec.conjugate == "finite" else 0.0), "weight": 1.0})
    return OptimizationSpec.model_validate({"variables": variables, "operands": operands, "algorithm": "local", "max_evaluations": 150 + 150 * n})


def _rms_best(system: OpticalSystem, custom: list) -> tuple[float, float]:
    from .analysis.focus import focus_status

    st = focus_status(compile_system(system, custom), density=3)
    if st["rms_best_um"] is None or st["best_defocus_mm"] is None:
        return math.inf, 0.0
    return float(st["rms_best_um"]), float(st["best_defocus_mm"])


def prescreen_task(items: list[dict], spec_json: dict, lenses_json: list[dict], custom: list, slot: int | None = None) -> list[tuple[int, float, float]]:
    """Real-ray RMS spot at the best focus of each combination: [(id, rms_um, defocus_mm)] (worker)."""
    spec = StockSpec.model_validate(spec_json)
    lenses = [StockLens.model_validate(d) for d in lenses_json]
    flag = None
    if slot is not None:
        from .workers import flag as _flag

        flag = _flag(slot)
    out = []
    for it in items:
        if flag is not None and flag.is_set():
            break
        try:
            sysm = build_system(lenses, it["combo"], it["gaps"], it["d_img"], spec, "prescreen")
            rms, dz = _rms_best(sysm, custom)
        except (SystemError_, ValueError, ArithmeticError, MaterialError):
            rms, dz = math.inf, 0.0
        out.append((it["id"], rms, dz))
    return out


def run_stock_candidate(task: dict, spec_json: dict, lenses_json: list[dict], custom: list, slot: int | None = None) -> dict:
    """Optimise one combination in its air gaps and image distance, then measure it (worker)."""
    from .analysis.evaluate import auto_semi_diameters, edge_thickness, effective_semi_diameters
    from .analysis.outline import system_outline
    from .jsonutil import jsonable
    from .optimize.engine import Control, optimize
    from .paraxial import compute_pupil, paraxial_data

    t0 = time.time()
    spec = StockSpec.model_validate(spec_json)
    lenses = [StockLens.model_validate(d) for d in lenses_json]
    combo = [tuple(c) for c in task["combo"]]
    title = combo_title(lenses, combo)
    n = len(combo)
    base = {"index": task["index"], "topology": f"stock_{n}", "glasses": sorted({m for li, _ in combo for m in lenses[li].materials}), "variant": 0, "title": title, "parts": [lenses[li].key for li, _ in combo]}
    flag = None
    if slot is not None:
        from .workers import flag as _flag

        flag = _flag(slot)
        if flag.is_set():
            return {**base, "status": "cancelled"}
    try:
        start = build_system(lenses, combo, task["gaps"], task["d_img"] + task.get("defocus", 0.0), spec, title)
        ospec = optimisation_spec(start, n, spec)
        ctl = Control()
        if flag is not None:
            ctl.cancel = flag
        res = optimize(start, ospec, custom, control=ctl)
        if res["status"] == "cancelled":
            return {**base, "status": "cancelled"}
        system = OpticalSystem.model_validate(res["system"])
        ds = DesignSpaceSpec(mtf_frequency=spec.mtf_frequency, tolerances=spec.tolerances, wavelengths=spec.wavelengths, primary=spec.primary)
        m = metrics(system, custom, ds, flag)
        cs = compile_system(system, custom)
        pd = paraxial_data(cs, system.primary_wavelength)
        if spec.conjugate == "finite":
            m["length_mm"] = float(pd.total_track + spec.object_distance)
            m["magnification"] = pd.paraxial_magnification
        m["parts"] = n
        prices = [lenses[li].price for li, _ in combo]
        m["price"] = float(sum(prices)) if all(p is not None for p in prices) else None
        # specification checks
        v = []
        if spec.conjugate == "infinite":
            if m["efl_mm"] is None or abs(m["efl_mm"] - spec.focal_length) > spec.tolerance * spec.focal_length:
                v.append({"kind": "efl", "value": m["efl_mm"], "limit": spec.focal_length})
        else:
            mag = m.get("magnification")
            if mag is None or abs(mag - spec.magnification) > spec.tolerance * abs(spec.magnification):
                v.append({"kind": "magnification", "value": mag, "limit": spec.magnification})
        if spec.max_length is not None and m["length_mm"] > spec.max_length * (1 + 1e-3):
            v.append({"kind": "length", "value": m["length_mm"], "limit": spec.max_length})
        if not m["rays_ok"]:
            v.append({"kind": "rays", "value": None, "limit": None})
        sd = effective_semi_diameters(cs, auto_semi_diameters(cs, compute_pupil(cs)))
        backs = [i for i, s in enumerate(system.surfaces) if s.label.endswith(" back")]
        worst = math.inf
        for i in backs[:-1]:
            worst = min(worst, float(system.surfaces[i].thickness or 0.0), edge_thickness(cs, i, float(min(system.surfaces[i].mech_semi_diameter or sd[i], system.surfaces[i + 1].mech_semi_diameter or sd[i + 1]))))
        if worst < 0.9 * spec.min_gap:
            v.append({"kind": "collision", "value": worst, "limit": spec.min_gap})
        outline = system_outline(cs)
    except (StockError, SystemError_, MaterialError, ValueError, ArithmeticError) as exc:
        return {**base, "status": "failed", "error": f"{type(exc).__name__}: {exc}", "elapsed_s": time.time() - t0}
    return jsonable(
        {
            **base,
            "status": "finished",
            "feasible": not v,
            "violations": v,
            "metrics": m,
            "merit": res["final_merit"],
            "initial_merit": res["initial_merit"],
            "evaluations": res["evaluations"],
            "optimiser_status": res["status"],
            "system": system.model_dump(mode="json"),
            "optimization": ospec.model_dump(mode="json"),
            "outline": outline,
            "elapsed_s": time.time() - t0,
        }
    )


# ---------------------------------------------------------------------------------------------- planning and the job
def plan_build(spec: StockSpec, lenses: list[StockLens], custom_materials=()) -> tuple[list[StockLens], list[dict], dict]:
    """Lens pool, the prescreen list (third-order ranked, shared by the lens counts) and statistics."""
    pool = lens_pool(spec, lenses, custom_materials)
    E = entry_table(pool, spec, custom_materials)
    found = enumerate_first_order(E, spec)
    stats = {"lenses": len(pool), "orientations": int(len(E["A"])), "feasible": {g["n"]: int(len(g["entries"])) for g in found}}
    counts = [g for g in found if len(g["entries"])]
    if not counts:
        raise StockDesignError("No combination of the stock lenses meets the first-order target within the length and apertures: widen the tolerance, the length or the lens counts")
    share = max(1, spec.prescreen // len(counts))
    items = []
    for g in counts:
        S = seidel_sums(E, g["entries"], g["gaps"], spec)
        score = third_order_rms(S, spec)
        score = np.where(np.isfinite(score), score, np.inf)
        order = np.argsort(score, kind="stable")[:share]
        for r in order:
            combo = [(int(E["lens"][e]), bool(E["rev"][e])) for e in g["entries"][r]]
            items.append({"id": len(items), "n": g["n"], "combo": combo, "gaps": [float(x) for x in g["gaps"][r]], "d_img": float(g["d_img"][r]), "third_order_waves": float(score[r])})
    return pool, items, stats


def stock_runner(jobs, spec: StockSpec, lenses: list[StockLens], custom: list):
    """The job runner: plan (in the job thread), prescreen and optimise (process pool)."""

    def runner(job, pool, fl):
        job["phase"] = "search"
        lens_pool_, items, stats = plan_build(spec, lenses, custom)
        job["notes"].append(
            f"{stats['lenses']} stock lenses ({stats['orientations']} orientations); first-order solutions: "
            + ", ".join(f"{n} lens{'es' if n > 1 else ''}: {k}" for n, k in sorted(stats["feasible"].items()))
        )
        sj = spec.model_dump(mode="json")
        lj = [l.model_dump(mode="json") for l in lens_pool_]
        # real-ray prescreen in chunks
        job["phase"] = "prescreen"
        job["phase_total"] = len(items)
        scores: dict[int, tuple[float, float]] = {}
        chunk = 40
        futures = {pool.submit(prescreen_task, items[i : i + chunk], sj, lj, custom, fl.slot): i for i in range(0, len(items), chunk)}

        def take(k, r):
            if isinstance(r, list):
                for cid, rms, dz in r:
                    scores[cid] = (rms, dz)
            job["phase_done"] = len(scores)

        jobs.gather(job, futures, take)
        if job["cancel"].is_set():
            return
        # the best of each lens count share the optimisation budget
        by_n: dict[int, list[dict]] = {}
        for it in items:
            rms, dz = scores.get(it["id"], (math.inf, 0.0))
            if math.isfinite(rms):
                by_n.setdefault(it["n"], []).append({**it, "rms_prescreen_um": rms, "defocus": dz})
        if not by_n:
            raise StockDesignError("Every prescreened combination failed the real-ray trace")
        share = max(1, spec.candidates // len(by_n))
        finalists = []
        for n in sorted(by_n):
            finalists += sorted(by_n[n], key=lambda x: x["rms_prescreen_um"])[:share]
        rest = sorted([x for n in by_n for x in sorted(by_n[n], key=lambda x: x["rms_prescreen_um"])[share:]], key=lambda x: x["rms_prescreen_um"])
        finalists += rest[: max(0, spec.candidates - len(finalists))]
        for k, f in enumerate(finalists):
            f["index"] = k
        job["total"] = len(finalists)
        job["topologies"] = [f"stock_{n}" for n in sorted(by_n)]
        job["phase"] = "optimise"
        job["phase_total"] = len(finalists)
        job["phase_done"] = 0
        futures = {pool.submit(run_stock_candidate, f, sj, lj, custom, fl.slot): f["index"] for f in finalists}

        def keep(k, r):
            jobs.store(job, k, r)
            job["phase_done"] = len(job["order"])

        jobs.gather(job, futures, keep)

    return runner


def describe_candidate(spec: StockSpec):
    def describe(job, index, c) -> str:
        target = f"f = {spec.focal_length:g} mm, F/{spec.f_number:g}, half field {spec.half_field_deg:g} deg" if spec.conjugate == "infinite" else (
            f"magnification {spec.magnification:g} at {spec.object_distance:g} mm, NA {spec.object_na:g}, object height {spec.object_height:g} mm"
        )
        return f"Built from stock lenses ({', '.join(c.get('parts', []))}) for {target}; air gaps and image distance optimised (candidate {index + 1} of {job['total']}, seed {spec.seed})."

    return describe


# ---------------------------------------------------------------------------------------------- match an existing design
class StockMatchSpec(BaseModel):
    """Replace each lens element of a design by stock lenses (see `plan_match`)."""

    model_config = ConfigDict(extra="forbid")
    materials: list[str] | None = None
    generic: bool = True
    per_element: int = Field(default=4, ge=1, le=12, description="nearest stock lenses (with orientation) tried per element")
    min_gap: float = Field(default=0.2, ge=0.0)
    candidates: int = Field(default=30, ge=1, le=400)
    prescreen: int = Field(default=600, ge=1, le=20000)
    mtf_frequency: float = Field(default=30.0, gt=0.0)
    tolerances: bool = False
    seed: int = 1


def _element_matrix(system: OpticalSystem, cs, a: int, b: int, wl: int) -> np.ndarray:
    """Reduced matrix of the element from surface a to surface b (vertices), at wavelength index wl."""
    M = np.eye(2)
    for j in range(a, b + 1):
        n1, n2 = float(cs.n_after[wl, j - 1]), float(cs.n_after[wl, j])
        c = float(cs.shapes[j].curvature)
        M = np.array([[1.0, 0.0], [-(n2 - n1) * c, 1.0]]) @ M
        if j < b:
            M = np.array([[1.0, float(system.surfaces[j].thickness or 0.0) / n2], [0.0, 1.0]]) @ M
    return M


def design_elements(system: OpticalSystem, custom_materials=()) -> list[dict]:
    """The design's lens elements (singlets and cemented groups in air) with their paraxial data and clear aperture."""
    from .analysis.evaluate import auto_semi_diameters, effective_semi_diameters
    from .paraxial import compute_pupil
    from .tolerance import element_groups

    if any(s.type == "coordinate_break" for s in system.surfaces):
        raise StockDesignError("Stock matching needs an axial design without coordinate breaks")
    cs = compile_system(system, list(custom_materials))
    sd = effective_semi_diameters(cs, auto_semi_diameters(cs, compute_pupil(cs)))
    wl = system.primary_wavelength
    out = []
    for a, b in element_groups(system):
        if any(system.surfaces[j].type != "standard" or system.surfaces[j].conic != 0.0 for j in range(a, b + 1)):
            continue
        before = system.surfaces[a - 1].material.upper()
        after = system.surfaces[b].material.upper()
        if before not in ("AIR", "") or after not in ("AIR", ""):
            continue
        M = _element_matrix(system, cs, a, b, wl)
        (A, B), (C, D) = M
        if abs(C) < 1e-14:
            continue
        out.append(
            {
                "first": a,
                "last": b,
                "glasses": b - a,
                "efl": -1.0 / C,
                "front_principal": (D - 1.0) / C,
                "rear_principal": (1.0 - A) / C,
                "length": float(sum(system.surfaces[j].thickness or 0.0 for j in range(a, b))),
                "clear": float(2.0 * max(sd[a : b + 1])),
                "c_first": float(cs.shapes[a].curvature),
                "nmean": float(np.mean([cs.n_after[wl, j] for j in range(a, b)])),
            }
        )
    if not out:
        raise StockDesignError("The design has no spherical lens element in air to replace")
    return out


MATCH_WEIGHTS = {"shape": 0.25, "index": 0.5, "size": 0.05}


def match_candidates(E, lenses: list[StockLens], el: dict, k: int) -> list[int]:
    """Entry indices of the k stock lenses (with orientation) nearest to the element: the same number of glasses,
    a clear aperture at least the element's, and the smallest score

        |phi_stock f - 1| + 0.25 |c1_stock - c1| |f| + 0.5 |n_stock - n| + 0.05 max(0, clear_stock / clear - 1)

    (relative power, first curvature, mean index at the primary wavelength, oversize)."""
    ng = np.array([len(lenses[i].materials) for i in E["lens"]])
    ok = (ng == el["glasses"]) & (2.0 * E["clear"] >= 0.98 * el["clear"])
    idx = np.nonzero(ok)[0]
    if not len(idx):
        return []
    w = MATCH_WEIGHTS
    score = (
        np.abs(-E["C"][idx] * el["efl"] - 1.0)
        + w["shape"] * np.abs(E["c_first"][idx] - el["c_first"]) * abs(el["efl"])
        + w["index"] * np.abs(E["nmean"][idx] - el["nmean"])
        + w["size"] * np.maximum(0.0, 2.0 * E["clear"][idx] / el["clear"] - 1.0)
    )
    order = np.argsort(score, kind="stable")
    return [int(i) for i in idx[order[:k]]]


def substitute(system: OpticalSystem, elements: list[dict], picks: list[tuple[StockLens, bool, dict]], min_gap: float, name: str) -> OpticalSystem:
    """The design with each element replaced by a stock lens whose principal-plane midpoint sits where the
    element's was (first order kept as far as one lens allows); gaps below the minimum are raised to it."""
    surfs = [s.model_dump() for s in system.surfaces]
    out: list[dict] = []
    i = 0
    ei = {el["first"]: (el, pk) for el, pk in zip(elements, picks)}
    k = 0
    while i < len(surfs):
        if i in ei:
            el, (lens, rev, par) = ei[i]
            k += 1
            mid_orig = (el["front_principal"] + el["length"] + el["rear_principal"]) / 2.0
            mid_new = (par["front_principal"] + par["length"] + par["rear_principal"]) / 2.0
            delta = mid_orig - mid_new  # new front vertex relative to the old one
            prev = out[-1]
            if prev.get("thickness") is not None and i > 1:
                prev["thickness"] = max(min_gap, float(prev["thickness"]) + delta)
            gap_after = float(surfs[el["last"]]["thickness"] or 0.0) - (delta + par["length"] - el["length"])
            stop = any(surfs[j].get("is_stop") for j in range(el["first"], el["last"] + 1))
            out += lens_surfaces(lens, rev, max(min_gap, gap_after), f"m{k}s", stop_first=stop)
            i = el["last"] + 1
            continue
        out.append(surfs[i])
        i += 1
    d = system.model_dump()
    d["surfaces"] = out
    d["name"] = name
    return OpticalSystem.model_validate(d)


def match_merit(system: OpticalSystem, original: OpticalSystem, optimization: OptimizationSpec | None, min_gap: float, custom: list) -> OptimizationSpec:
    """The project's operands that still apply (operands on replaced surfaces are dropped), or RMS spot and the
    original EFL; the air gaps around the stock lenses and the image distance as variables; rim clearance."""
    from .optimize.merit import is_active
    from .paraxial import paraxial_data

    ids = {s.id for s in system.surfaces}
    ops = []
    if optimization is not None:
        ops = [o.model_dump() for o in optimization.operands if is_active(o) and (o.surface_id is None or o.surface_id in ids) and o.type != "min_edge_thickness"]
    if not ops:
        efl = paraxial_data(compile_system(original, custom), original.primary_wavelength).efl
        ops = [{"type": "rms_spot", "rings": 4}] + ([{"type": "efl", "target": efl, "weight": 1.0}] if efl and math.isfinite(efl) else [])
    surfs = system.surfaces
    gaps = set()
    for i, s in enumerate(surfs):
        if not s.comment.startswith("Stock lens"):
            continue
        if s.label.endswith(" back"):
            gaps.add(i)
        if s.label.endswith(" front") and i - 1 >= 1 and surfs[i - 1].thickness is not None:
            gaps.add(i - 1)
    last = len(surfs) - 2
    gaps.add(last)
    scale = max(10.0, float(sum((s.thickness or 0.0) for s in surfs[1:-1])))
    variables = []
    for i in sorted(gaps):
        t = float(surfs[i].thickness or 0.0)
        variables.append({"surface_id": surfs[i].id, "parameter": "thickness", "min": 0.1 if i == last else min_gap, "max": max(3.0 * t, t + 0.5 * scale)})
        if i != last and surfs[i].material.upper() in ("AIR", ""):
            ops.append({"type": "min_edge_thickness", "surface_id": surfs[i].id, "target": min_gap, "weight": 1.0})
    return OptimizationSpec.model_validate({"variables": variables, "operands": ops, "algorithm": "local", "max_evaluations": 400})


def plan_match(spec: StockMatchSpec, system: OpticalSystem, lenses: list[StockLens], custom_materials=()) -> tuple[list[StockLens], list[dict], dict]:
    """Match plan: the design's elements, each one's `per_element` nearest stock lenses (same number of glasses,
    clear aperture at least the element's, nearest power, then nearest first curvature) and every combination of
    them (a seeded sample when there are more than `prescreen`)."""
    import itertools

    elements = design_elements(system, custom_materials)
    bs = StockSpec(wavelengths=[w.value for w in system.wavelengths], primary=system.primary_wavelength, materials=spec.materials, generic=spec.generic)
    pool = lens_pool(bs, lenses, custom_materials)
    E = entry_table(pool, bs, custom_materials)
    choices = []
    for el in elements:
        c = match_candidates(E, pool, el, spec.per_element)
        if not c:
            raise StockDesignError(
                f"No stock lens matches the element at surfaces {el['first']}-{el['last']} (f = {el['efl']:.4g} mm, clear diameter {el['clear']:.3g} mm, {el['glasses']} glass{'es' if el['glasses'] > 1 else ''})"
            )
        choices.append(c)
    combos = list(itertools.product(*choices))
    if len(combos) > spec.prescreen:
        rng = np.random.default_rng(spec.seed)
        keep = sorted(rng.choice(len(combos), size=spec.prescreen, replace=False))
        combos = [combos[i] for i in keep]
    items = [{"id": k, "combo": [(int(E["lens"][e]), bool(E["rev"][e])) for e in c]} for k, c in enumerate(combos)]
    stats = {"elements": [{"first": e["first"], "last": e["last"], "efl": e["efl"], "clear": e["clear"], "glasses": e["glasses"]} for e in elements], "lenses": len(pool), "combinations": len(items)}
    return pool, items, stats


def matched_system(system: OpticalSystem, combo, lenses: list[StockLens], custom: list, min_gap: float) -> OpticalSystem:
    from .stock import lens_paraxial

    elements = design_elements(system, custom)
    lib = MaterialLibrary(custom)
    lp = system.wavelengths[system.primary_wavelength].value
    picks = [(lenses[li], rev, lens_paraxial(lenses[li], lib, lp, rev)) for li, rev in combo]
    return substitute(system, elements, picks, min_gap, combo_title(lenses, combo))


def match_prescreen_task(items: list[dict], spec_json: dict, system_json: dict, optimization_json: dict | None, lenses_json: list[dict], custom: list, slot: int | None = None) -> list[tuple[int, float, float]]:
    """Merit of each substitution at its principal-plane placement (worker): [(id, merit, 0)]."""
    from .optimize.merit import MeritFunction

    spec = StockMatchSpec.model_validate(spec_json)
    system = OpticalSystem.model_validate(system_json)
    opt = OptimizationSpec.model_validate(optimization_json) if optimization_json else None
    lenses = [StockLens.model_validate(d) for d in lenses_json]
    flag = None
    if slot is not None:
        from .workers import flag as _flag

        flag = _flag(slot)
    out = []
    for it in items:
        if flag is not None and flag.is_set():
            break
        try:
            s = matched_system(system, it["combo"], lenses, custom, spec.min_gap)
            mf = MeritFunction(s, match_merit(s, system, opt, spec.min_gap, custom), custom)
            val = float(mf.merit(mf.x0))
        except (StockError, StockDesignError, SystemError_, ValueError, ArithmeticError, MaterialError):
            val = math.inf
        out.append((it["id"], val if math.isfinite(val) else math.inf, 0.0))
    return out


def run_match_candidate(task: dict, spec_json: dict, system_json: dict, optimization_json: dict | None, lenses_json: list[dict], custom: list, slot: int | None = None) -> dict:
    """Optimise one substitution in its air gaps with the project's merit function, then measure it (worker)."""
    from .analysis.outline import system_outline
    from .jsonutil import jsonable
    from .optimize.engine import Control, optimize

    t0 = time.time()
    spec = StockMatchSpec.model_validate(spec_json)
    original = OpticalSystem.model_validate(system_json)
    opt = OptimizationSpec.model_validate(optimization_json) if optimization_json else None
    lenses = [StockLens.model_validate(d) for d in lenses_json]
    combo = [tuple(c) for c in task["combo"]]
    title = combo_title(lenses, combo)
    base = {
        "index": task["index"],
        "topology": f"stock_{len(combo)}",
        "glasses": sorted({m for li, _ in combo for m in lenses[li].materials}),
        "variant": 0,
        "title": title,
        "parts": [lenses[li].key for li, _ in combo],
    }
    flag = None
    if slot is not None:
        from .workers import flag as _flag

        flag = _flag(slot)
        if flag.is_set():
            return {**base, "status": "cancelled"}
    try:
        start = matched_system(original, combo, lenses, custom, spec.min_gap)
        ospec = match_merit(start, original, opt, spec.min_gap, custom)
        ctl = Control()
        if flag is not None:
            ctl.cancel = flag
        res = optimize(start, ospec, custom, control=ctl)
        if res["status"] == "cancelled":
            return {**base, "status": "cancelled"}
        system = OpticalSystem.model_validate(res["system"])
        ds = DesignSpaceSpec(mtf_frequency=spec.mtf_frequency, tolerances=spec.tolerances, wavelengths=[w.value for w in system.wavelengths], primary=system.primary_wavelength)
        m = metrics(system, custom, ds, flag)
        m["parts"] = len(combo)
        prices = [lenses[li].price for li, _ in combo]
        m["price"] = float(sum(prices)) if all(p is not None for p in prices) else None
        m["merit"] = float(res["final_merit"])
        v = [] if m["rays_ok"] else [{"kind": "rays", "value": None, "limit": None}]
        outline = system_outline(compile_system(system, custom))
    except (StockError, StockDesignError, SystemError_, MaterialError, ValueError, ArithmeticError) as exc:
        return {**base, "status": "failed", "error": f"{type(exc).__name__}: {exc}", "elapsed_s": time.time() - t0}
    return jsonable(
        {
            **base,
            "status": "finished",
            "feasible": not v,
            "violations": v,
            "metrics": m,
            "merit": res["final_merit"],
            "initial_merit": res["initial_merit"],
            "evaluations": res["evaluations"],
            "optimiser_status": res["status"],
            "system": system.model_dump(mode="json"),
            "optimization": ospec.model_dump(mode="json"),
            "outline": outline,
            "elapsed_s": time.time() - t0,
        }
    )


def match_runner(jobs, spec: StockMatchSpec, system: OpticalSystem, optimization: OptimizationSpec | None, lenses: list[StockLens], custom: list):
    """The job runner of a match: plan (job thread), prescreen by the merit at the placement, optimise the best."""

    def runner(job, pool, fl):
        job["phase"] = "search"
        pool_lenses, items, stats = plan_match(spec, system, lenses, custom)
        job["notes"].append(
            f"{len(stats['elements'])} element(s) matched against {stats['lenses']} stock lenses: "
            + "; ".join(f"surfaces {e['first']}-{e['last']} f = {e['efl']:.4g} mm, clear diameter {e['clear']:.3g} mm" for e in stats["elements"])
            + f"; {stats['combinations']} combinations"
        )
        sj = spec.model_dump(mode="json")
        sysj = system.model_dump(mode="json")
        oj = optimization.model_dump(mode="json") if optimization is not None else None
        lj = [l.model_dump(mode="json") for l in pool_lenses]
        job["phase"] = "prescreen"
        job["phase_total"] = len(items)
        scores: dict[int, float] = {}
        chunk = 20
        futures = {pool.submit(match_prescreen_task, items[i : i + chunk], sj, sysj, oj, lj, custom, fl.slot): i for i in range(0, len(items), chunk)}

        def take(k, r):
            if isinstance(r, list):
                for cid, val, _ in r:
                    scores[cid] = val
            job["phase_done"] = len(scores)

        jobs.gather(job, futures, take)
        if job["cancel"].is_set():
            return
        ranked = sorted((it for it in items if math.isfinite(scores.get(it["id"], math.inf))), key=lambda it: scores[it["id"]])[: spec.candidates]
        if not ranked:
            raise StockDesignError("Every stock substitution failed the real-ray trace")
        for k, it in enumerate(ranked):
            it["index"] = k
        job["total"] = len(ranked)
        job["topologies"] = sorted({f"stock_{len(it['combo'])}" for it in ranked})
        job["phase"] = "optimise"
        job["phase_total"] = len(ranked)
        job["phase_done"] = 0
        futures = {pool.submit(run_match_candidate, it, sj, sysj, oj, lj, custom, fl.slot): it["index"] for it in ranked}

        def keep(k, r):
            jobs.store(job, k, r)
            job["phase_done"] = len(job["order"])

        jobs.gather(job, futures, keep)

    return runner


def describe_match(spec: StockMatchSpec):
    def describe(job, index, c) -> str:
        return f"Stock lens match of the design ({', '.join(c.get('parts', []))}): air gaps reoptimised with the project's merit function (candidate {index + 1} of {job['total']}, seed {spec.seed})."

    return describe
