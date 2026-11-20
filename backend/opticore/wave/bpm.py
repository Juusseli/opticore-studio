"""Rotationally symmetric beam propagation (BPM) through the lens system.

Unlike POP, which carries the field through the lenses along rays, the BPM propagates the wave
*inside* the glass: the lenses are a refractive-index distribution n(r, z) built from the surface
sags (glass between the faces within the element radius, the surrounding medium outside). The
scalar wave equation for a rotationally symmetric field U(r, z),

    d^2U/dz^2 + (1/r) d/dr (r dU/dr) + k0^2 n^2 U = 0,

is integrated one way. All propagation is exact (non-paraxial) in a homogeneous medium,
exp(i kz dz) with kz = sqrt(k0^2 n^2 - kr^2), by the quasi-discrete Hankel transform of order 0
(Guizar-Sicairos & Gutierrez-Vega, JOSA A 21, 53, 2004) on its Bessel-zero radial grid. Powers are
sums with the transform's own quadrature weights, which it conserves exactly.

Where the medium is uniform across the beam (inside a lens, in the gaps and the image space) the
field is propagated in one step. Where a face passes through the beam, the march takes short steps
(about one wavelength) in the manner of phase shift plus interpolation (PSPI; Gazdag & Sguazzero,
Geophysics 49, 124, 1984): each part of the field is diffracted exactly in the medium it lies in
during the step, the parts are summed in the spectrum, and the optical path k0 n h of the step
(n averaged over the step at each radius, so the path through a curved face is exact) is a phase
screen half before and half after. Each side of a face thus keeps its own kz: steep waves refract
as by Snell's law at the tilted face (a single reference index would misstate their kz by
kr^2 / 2k0 (1/n - 1/n_ref) per unit length).
Bulk absorption enters as Im(n).

The field starts at the entry plane of the physical-optics propagation (pop.py: the exact far
field / angular spectrum / Fresnel transform of the source). Fresnel or coating transmission at
normal incidence is applied where a surface is crossed (a one-way method has no reflected wave).
An absorbing layer at the outer radius takes light scattered out of the beam in the face slabs.

Assumptions: scalar (one transverse component, no polarisation coupling), rotationally symmetric
(on-axis source, axial system); one way (no reflections or ghosts); normal-incidence surface
transmission. The cost grows with the beam width where the faces curve through it; for wide
beams the ray transfer of POP is accurate and far cheaper (the BPM then refuses).
"""

from __future__ import annotations

import math
import time

import numpy as np
from scipy.special import j0, j1, jn_zeros

from ..physics import unpolarized_transmittance
from ..system import CompiledSystem, SystemError_
from ..thinfilm import unpolarized_T
from .pop import _fibre_indices, object_columns, physical_optics

MAX_R = 4000
MAX_STEPS = 20_000
MAX_WORK = 2.5e10  # slab steps x N^2 (about 30 s)
PART_CELLS = 9
PART_KERNEL = np.hanning(PART_CELLS + 2)[1:-1] / np.hanning(PART_CELLS + 2)[1:-1].sum()


class Hankel:
    """Quasi-discrete Hankel transform of order 0 on N points within radius R."""

    def __init__(self, N: int, R: float):
        jz = jn_zeros(0, N + 1)
        self.S = float(jz[N])
        self.jn = jz[:N]
        self.R = R
        self.r = self.jn * R / self.S
        self.kr = self.jn / R  # transverse wave numbers (rad/mm)
        self.J1 = np.abs(j1(self.jn))
        self.T = 2 * j0(np.outer(self.jn, self.jn) / self.S) / (np.outer(self.J1, self.J1) * self.S)
        # sum |u(r_i)|^2 weights_i is the transform's (exactly conserved) discrete power, the
        # quadrature of the integral of |u|^2 2 pi r dr for a band-limited field
        self.weights = 4 * math.pi * R * R / (self.S * self.S * self.J1 * self.J1)

    def forward(self, u: np.ndarray) -> np.ndarray:
        return self._mul(u * (self.R / self.J1))

    def forward_rows(self, u: np.ndarray, a: int, b: int) -> np.ndarray:
        """The transform of a field that is zero outside r[a:b] (T is symmetric)."""
        x = u * (self.R / self.J1[a:b])
        T = self.T[a:b]
        return x.real @ T + 1j * (x.imag @ T)

    def inverse(self, v: np.ndarray) -> np.ndarray:
        return self._mul(v) * (self.J1 / self.R)

    def propagate(self, u: np.ndarray, k: float, k_ref: float, L: float) -> np.ndarray:
        """Exact (scalar) propagation by L in a homogeneous medium of wave number k; the reference
        phase exp(i k_ref L) is taken out."""
        kz = np.sqrt((k * k - self.kr * self.kr).astype(complex))
        v = self._mul(u * (self.R / self.J1))
        v *= np.exp(1j * (kz - k_ref) * L)
        return self._mul(v) * (self.J1 / self.R)

    def _mul(self, v: np.ndarray) -> np.ndarray:
        # real matrix times complex vector without promoting the matrix to complex
        return self.T @ v.real + 1j * (self.T @ v.imag)


def bpm(
    cs: CompiledSystem,
    source: dict,
    wavelength: int | None = None,
    target_offset: float = 0.0,
    grid: int = 128,
    target_mode: dict | None = None,
    detector_radius: float | None = None,
    side_cols: int = 240,
    dz_um: float | None = None,
) -> dict:
    """Propagate a source field through the (axial) system to the target plane; the result has the
    structure of physical_optics()."""
    t0 = time.time()
    if any(abs(float(c)) > 1e-12 for c in source.get("decenter", [0.0, 0.0])):
        raise SystemError_("The rotationally symmetric BPM needs an on-axis source")
    if target_mode and any(abs(float(c)) > 1e-12 for c in target_mode.get("decenter", [0.0, 0.0])):
        raise SystemError_("The rotationally symmetric BPM couples only into an on-axis mode")
    _check_system(cs)
    pre = physical_optics(cs, source, wavelength, target_offset, grid=grid, _transfer_only=True)
    notes = list(pre["notes"])
    wl, lam_um = pre["wl"], pre["lam_um"]
    lam0 = lam_um * 1e-3
    k0 = 2 * math.pi / lam0
    n_s = cs.n_surfaces
    j_last = n_s - 2
    sd = pre["sd"]
    z_e = pre["z_e"]
    tr = pre["tr_"]["tr"]
    good = pre["tr_"]["good"]
    n_obj, n_img = pre["n_obj"], pre["n_img"]
    z_img = float(cs.frames[n_s - 1].origin[2])
    z_t = z_img + float(target_offset)
    if z_t <= z_e:
        raise SystemError_("The target lies in front of surface 1")
    # complex media after each surface (bulk absorption as Im n = alpha lambda / 4 pi)
    n_med = np.array([complex(cs.n_after[wl, j], cs.absorption[wl, j] * lam0 / (4 * math.pi)) for j in range(j_last + 1)])

    # ---- extent and angles of the beam from the transferred rays
    P = tr.points[good]
    rad = np.hypot(P[:, 1 : j_last + 1, 0], P[:, 1 : j_last + 1, 1])
    hit = tr.points[good, j_last]
    Dn = tr.dirs[good]
    at_t = hit[:, :2] + (z_t - hit[:, 2:3]) * Dn[:, :2] / Dn[:, 2:3]
    wt = (pre["tr_"]["I_e"].ravel()[pre["tr_"]["iv"]] * tr.intensity)[good]  # power of each ray
    r_geo = float(max(np.nanmax(rad), np.nanmax(np.hypot(at_t[:, 0], at_t[:, 1])), 0.5 * pre["xe"][-1]))

    def q999(v):  # the value below which 99.9 % of the ray power lies
        o = np.argsort(v)
        c = np.cumsum(wt[o]) / wt.sum()
        return float(v[o][min(int(np.searchsorted(c, 0.999)), len(o) - 1)])

    nsin = [n_obj * q999(np.hypot(tr.start_dirs[good, 0], tr.start_dirs[good, 1]))]
    for j in range(1, j_last + 1):
        dj = tr.dirs_after[good, j]
        nsin.append(abs(n_med[j].real) * q999(np.nan_to_num(np.hypot(dj[:, 0], dj[:, 1]))))
    # diffraction: a beam of 1/e^2 radius w spreads by n sin = lambda0 / (pi w) (three times that
    # holds all its angular spectrum); near a waist this exceeds the ray angles
    Ue0, xe0, ye0 = pre["Ue"], pre["xe"], pre["ye"]
    Ie0 = np.abs(Ue0) ** 2
    Xe0, Ye0 = np.meshgrid(xe0, ye0)
    w_e = math.sqrt(2 * float((Ie0 * (Xe0**2 + Ye0**2)).sum() / max(Ie0.sum(), 1e-300)))
    nsin_max = max(max(nsin), 3 * lam0 / (math.pi * w_e), 0.01)
    # the grid holds the ray footprint and the diffraction spread of the entry beam over the path
    # (1/e^2 radius lambda0 L / (pi w) in air; 2.5 times holds 99.99 % of a Gaussian)
    r_diff = 2.5 * lam0 * (z_t - z_e) / (math.pi * w_e)
    R_beam = 1.3 * math.hypot(r_geo, r_diff) + 8 * lam0 / nsin_max
    R_tot = 1.25 * R_beam
    # spectral grid: the Hankel transform reaches k_r = pi N / R (2.5 times the steepest wave), and
    # at least 12 points across the entry beam radius
    N = int(min(MAX_R, max(256, math.ceil(2.5 * R_tot * k0 * nsin_max / math.pi), math.ceil(12 * R_tot / w_e))))
    if N == MAX_R:
        notes.append(f"BPM radial grid limited to {MAX_R} points: the steepest rays (n sin = {nsin_max:.3f}) are near the grid's spectral limit")
    H = Hankel(N, R_tot)
    r = H.r
    w = H.weights  # quadrature weights of the transform (its discrete Parseval norm): power = sum |u|^2 w

    # ---- the entry field on the radial grid (residual phase interpolated, reference sphere exact)
    Ue, xe, ye = pre["Ue"], pre["xe"], pre["ye"]
    jc = int(np.argmin(np.abs(xe)))
    ic = int(np.argmin(np.abs(ye)))
    yc, Uc = ye[ic:], Ue[ic:, jc]
    xc, yc0, Rc = pre["ref_c"]
    kn = k0 * n_obj

    def sphere(rr):
        if not math.isfinite(Rc) or Rc == 0:
            return np.zeros_like(rr)
        return math.copysign(1.0, Rc) * kn * (np.sqrt(rr * rr + Rc * Rc) - abs(Rc))

    res = Uc * np.exp(-1j * sphere(yc))
    amp = np.interp(r, yc, np.abs(res), right=0.0)
    ph = np.interp(r, yc, np.unwrap(np.angle(res)), right=0.0)
    u = amp * np.exp(1j * (ph + sphere(r)))
    P_in = float((np.abs(u) ** 2 * w).sum())
    if P_in > 0:
        u *= math.sqrt(pre["P_entry"] / P_in)

    # ---- index distribution: surface positions S_j(r), element radius, surrounding medium
    phys = [j for j in range(1, j_last + 1) if abs(n_med[j] - n_med[j - 1]) > 0]
    zv = {j: float(cs.frames[j].origin[2]) for j in range(1, j_last + 1)}
    S = {j: zv[j] + np.asarray(cs.shapes[j].sag(np.minimum(r, sd[j]) ** 2), float) for j in phys}
    bounds = [np.full(N, -np.inf)] + [S[j] for j in phys] + [np.full(N, np.inf)]
    media = [n_med[0]] + [n_med[j] for j in phys]
    n_out = n_med[0]
    nmed = []  # complex index of each interval (between consecutive physical surfaces) at each r
    r_el = []
    for q, j in enumerate([0] + phys):
        nn = np.full(N, media[q], complex)
        R_el = math.inf
        if j > 0 and abs(media[q] - n_out) > 0 and q < len(phys):
            R_el = max(sd[j], sd[phys[q]])
            nn = np.where(r > R_el, n_out, nn)  # outside the lens element
        nmed.append(nn)
        r_el.append(R_el)
    nmed = np.array(nmed)
    B = np.array(bounds)
    # normal-incidence transmission of each physical surface (coating or bare)
    Tj = {}
    for q, j in enumerate(phys):
        n1r, n2r = float(media[q].real), float(media[q + 1].real)
        coat = cs.coatings[j] if cs.coatings else None
        Tj[j] = float(unpolarized_T(n1r, n2r, coat.oriented(lam_um, n1r, n2r), lam_um, np.array([1.0]))[0]) if coat is not None else float(unpolarized_transmittance(n1r, n2r, np.array([1.0]), np.array([1.0]))[0])
    # face slabs: where a surface passes through the beam (short steps); elsewhere the medium is
    # uniform across the beam and the field is propagated exactly (one Hankel step)
    slabs = []
    for q, j in enumerate(phys):
        rj = float(np.nanmax(rad[:, j - 1])) if rad.shape[1] >= j else r_geo
        r_face = min(sd[j], 1.25 * rj + 10 * (r[1] - r[0]))
        sel = r <= r_face
        slabs.append([float(S[j][sel].min()) - 1e-9, float(S[j][sel].max()) + 1e-9])
    merged = []
    for zz in sorted(slabs):
        zz = [max(zz[0], z_e), min(zz[1], z_t)]
        if zz[1] <= zz[0]:
            continue
        if merged and zz[0] <= merged[-1][1] + 1e-12:
            merged[-1][1] = max(merged[-1][1], zz[1])
        else:
            merged.append(zz)
    dz = (dz_um * 1e-3) if dz_um else lam0
    for q in range(len(media)):
        if math.isfinite(r_el[q]) and r_geo > 0.95 * r_el[q]:
            notes.append("The beam reaches the edge of a lens element: the BPM treats the element as wider than it is there")
            break
    # gentle absorbing taper at the outer radius (face slabs)
    absorb = np.zeros(N)
    edge = r > R_beam
    absorb[edge] = ((r[edge] - R_beam) / (R_tot - R_beam)) ** 2
    rate = 40 * nsin_max / (R_tot - R_beam)  # 1/mm at the outer edge

    # ---- side-view rows and columns
    rows_r = np.linspace(0, R_beam, 160)
    yl = np.concatenate([-rows_r[::-1], rows_r])
    src_field = pre["src_field"]
    L_obj = (z_e - src_field["z_src"]) if src_field else 0.0
    L_rest = z_t - z_e
    n_obj_cols = max(20, int(side_cols * L_obj / (L_obj + L_rest))) if src_field else 0
    n_rest_cols = max(40, side_cols - n_obj_cols)
    col_z = list(np.linspace(z_e, z_t, n_rest_cols))
    side_cols_out: list[tuple[float, np.ndarray]] = []

    def record(z, uu):
        I = np.abs(uu) ** 2
        Ir = np.interp(rows_r, r, I)
        side_cols_out.append((float(z), np.concatenate([Ir[::-1], Ir])))

    def medium_at(z):
        q = int(np.searchsorted(B[1:-1, 0], z + 1e-12)) if len(phys) else 0
        return media[min(q, len(media) - 1)]

    def transmit(z_end):
        nonlocal u
        for j in phys:  # each surface once at each radius
            cross = ~crossed[j] & (S[j] <= z_end + 1e-12) & (r <= sd[j])
            if cross.any():
                u[cross] *= math.sqrt(Tj[j])
                crossed[j] |= cross

    _dp: dict = {}
    part_norm = np.convolve(np.ones(N), PART_KERNEL, mode="same")  # the kernel's sum at each r (edges)

    def diff_phase(nm: float, h: float) -> np.ndarray:
        key = (nm, round(h * 1e9))
        if key not in _dp:
            _dp[key] = np.exp(1j * (np.sqrt((k0 * k0 * nm * nm - H.kr * H.kr).astype(complex)) - k0 * nm) * h)
        return _dp[key]

    # ---- cost guard: the face slabs need ~2 N^2 multiply-adds per step (two real transforms each way)
    n_slab_steps = int(sum(math.ceil((zz[1] - zz[0]) / dz) for zz in merged))
    if n_slab_steps > MAX_STEPS or n_slab_steps * float(N) ** 2 > MAX_WORK:
        raise SystemError_(
            f"The BPM would need {n_slab_steps} steps on {N} radial points through the lens faces (the beam is wide "
            f"where the faces curve through it); the ray transfer of the physical-optics propagation is accurate for "
            f"such wide beams. Use POP, or a larger step"
        )

    # ---- march from the entry plane to the target
    crossed = {j: np.zeros(N, bool) for j in phys}
    z = z_e
    ci = 0
    n_steps = 0
    n_exact = 0
    while z < z_t - 1e-12:
        zone = next((zz for zz in merged if zz[0] - 1e-12 <= z < zz[1] - 1e-12), None)
        if zone is None:
            # uniform across the beam up to the next face slab (or the target): exact propagation
            nxt = min([zz[0] for zz in merged if zz[0] > z + 1e-12] + [z_t])
            k_seg = complex(k0 * medium_at(0.5 * (z + nxt)))
            while ci < len(col_z) and col_z[ci] <= nxt + 1e-12:
                record(col_z[ci], H.propagate(u, k_seg, 0.0, col_z[ci] - z))
                ci += 1
            u = H.propagate(u, k_seg, 0.0, nxt - z)
            transmit(nxt)
            n_exact += 1
            z = nxt
            continue
        # face slab: each part of the field is diffracted exactly in the medium it lies in during the
        # step, exp(i (kz - k0 n) h) with kz = sqrt(k0^2 n^2 - kr^2) (the parts are transformed
        # separately and summed in the spectrum), and the optical path of the step, k0 n h with n
        # averaged over the step at each radius, is a phase screen half before and half after
        zb_end = zone[1]
        while z < zb_end - 1e-12:
            za, zb = z, min(z + dz, zb_end)
            h = zb - za
            ov = np.clip(np.minimum(zb, B[1:]) - np.maximum(za, B[:-1]), 0.0, None)  # (intervals, N)
            nn = (ov * nmed).sum(axis=0) / h
            nref = nmed[np.argmax(ov, axis=0), np.arange(N)].real  # the medium filling most of the step
            screen = np.exp(0.5j * k0 * nn.real * h - 0.5 * (k0 * nn.imag + rate * absorb) * h)
            us = u * screen
            media_here = np.unique(nref)
            if media_here.size == 1:
                tot = H.forward(us) * diff_phase(float(media_here[0]), h)
            else:
                # a smooth partition of unity between the media (PART_CELLS wide) keeps the parts
                # free of sharp edges, whose diffraction would not cancel in the sum
                tot = 0
                for nm in media_here:
                    chi = np.convolve((nref == nm).astype(float), PART_KERNEL, mode="same") / part_norm
                    nz = np.flatnonzero(chi > 1e-12)
                    a_, b_ = int(nz[0]), int(nz[-1]) + 1
                    tot = tot + H.forward_rows((us * chi)[a_:b_], a_, b_) * diff_phase(float(nm), h)
            u = H.inverse(tot) * screen
            transmit(zb)
            z = zb
            n_steps += 1
            while ci < len(col_z) and col_z[ci] <= z + 1e-12:
                record(col_z[ci], u)
                ci += 1
    # ---- results at the target, in an analysis window as for the physical-optics propagation: the
    # geometric footprint (99.9 % of the ray power) plus diffraction. Light scattered far outside
    # (e.g. by the staircase of the faces) would otherwise dominate the second moment.
    I = np.abs(u) ** 2
    lam_i = lam0 / n_img.real if isinstance(n_img, complex) else lam0 / n_img
    sin_i = q999(np.hypot(Dn[:, 0], Dn[:, 1]))
    R_win = 1.15 * q999(np.hypot(at_t[:, 0], at_t[:, 1])) + 2 * lam_i / max(sin_i, 1e-3)
    # and the diffracted beam itself: 1.5 times the radius holding 99 % of its power (low-level
    # scattered light does not move that radius)
    Pw = np.cumsum((I * w)[r <= R_beam])
    r99 = float(r[min(int(np.searchsorted(Pw / max(Pw[-1], 1e-300), 0.99)), Pw.size - 1)])
    R_win = max(R_win, 1.5 * r99, 2 * lam_i, 4 * (r[1] - r[0]), 3 * _mode_r(target_mode, lam_um) if target_mode else 0.0)
    R_win = min(R_win, R_beam)
    inside = r <= R_win
    P_t = float((I * w)[inside].sum())
    P_all = float((I * w)[r <= R_beam].sum())
    r2 = float((I * w * r * r)[inside].sum() / max(P_t, 1e-300))
    d4 = 4 * math.sqrt(r2 / 2)
    half = R_win
    xo = np.linspace(-half, half, 128)
    X, Y = np.meshgrid(xo, xo)
    It = np.interp(np.hypot(X, Y), r, I, right=0.0)
    ut = np.interp(np.hypot(X, Y), r, u.real, right=0.0) + 1j * np.interp(np.hypot(X, Y), r, u.imag, right=0.0)
    out_t = {
        "z": z_t,
        "offset_from_image": float(target_offset),
        "power": P_t,
        "power_outside_window": max(P_all - P_t, 0.0),
        "window_radius_mm": float(R_win),
        "centroid_mm": [0.0, 0.0],
        "d4sigma_mm": [d4, d4],
        "peak_irradiance": float(I.max()),
        "x": xo.tolist(),
        "y": xo.tolist(),
        "irradiance": It.tolist(),
        "phase": np.angle(ut).tolist(),
        "profile_x": It[64].tolist(),
        "profile_y": It[:, 64].tolist(),
    }
    if detector_radius:
        out_t["power_in_radius"] = float((I * w)[r <= detector_radius].sum())
        out_t["detector_radius"] = float(detector_radius)
    if P_all > 0 and (P_all - P_t) > 0.01 * P_all:
        notes.append(f"{100 * (P_all - P_t) / P_all:.1f} % of the power lies outside the analysis window (radius {R_win:.4g} mm) at the target")
    result: dict = {
        "wavelength_um": lam_um,
        "source": pre["src_info"],
        "entry": {"z": z_e, "method": pre["entry_method"], "power": pre["P_entry"], "grid": int(len(xe)), "window_mm": float(2 * xe[-1]), "refined_from": None},
        "exit": {
            "z": float(z_t),
            "power": P_t,
            "grid": N,
            "window_mm": float(2 * R_beam),
            "max_sin": float(nsin_max),
            "sphere_radius_mm": None,
            "fresnel_number": None,
            "propagation": f"BPM through {len(merged)} face zones ({n_steps} steps of {dz * 1e3:.3g} um, each medium diffracted exactly), one exact Hankel step in each of {n_exact} uniform sections; {N} radial points",
        },
        "target": out_t,
        "geometric_d4sigma_mm": float(2 * math.sqrt(2) * math.sqrt((wt * np.sum(at_t**2, axis=1)).sum() / wt.sum())),
        "notes": notes,
        "method": "Rotationally symmetric beam propagation (scalar, one way): the lenses as an index distribution n(r, z); through the faces short steps in which each medium diffracts exactly (kz = sqrt(k0^2 n^2 - kr^2), quasi-discrete Hankel transform) with the step's optical path as a phase screen; one exact Hankel step through uniform glass and gaps; normal-incidence Fresnel/coating transmission; starts from the exact entry field of the physical-optics propagation",
    }
    if target_mode:
        Mr = _mode_profile(target_mode, r, lam_um)
        ov_ = (u * np.conj(Mr) * w).sum()
        eta = float(abs(ov_) ** 2 / (np.abs(Mr) ** 2 * w).sum())
        result["coupling"] = {"mode": target_mode, "efficiency": eta, "efficiency_of_arriving": eta / P_t if P_t > 0 else 0.0, "efficiency_db": 10 * math.log10(eta) if eta > 0 else None}
    # side view
    zz_obj, cc_obj, kinds = (object_columns(src_field, z_e, yl, n_obj_cols, L_obj) if src_field else ([], [], {}))
    zs_all = zz_obj + [c[0] for c in side_cols_out]
    cols = cc_obj + [c[1] for c in side_cols_out]
    regions = []
    if src_field:
        regions.append({"z0": src_field["z_src"], "z1": z_e, "method": "source to surface 1: " + ", ".join(kinds), "kind": "wave"})
    regions.append({"z0": z_e, "z1": z_t, "method": "BPM: short steps through the lens faces, exact (non-paraxial) Hankel propagation in glass and gaps", "kind": "wave"})
    result["side"] = {
        "z": zs_all,
        "y": yl.tolist(),
        "irradiance": np.array(cols).T.tolist(),
        "regions": regions,
        "surfaces_z": [zv[j] for j in phys],
        "source_z": src_field.get("z_src") if src_field else None,
        "entry_z": z_e,
        "exit_z": float(max(zz[1] for zz in merged)) if merged else z_e,
        "target_z": z_t,
        "time_s": time.time() - t0,
    }
    result["time_s"] = time.time() - t0
    return result


def _check_system(cs: CompiledSystem) -> None:
    """The BPM needs glass to propagate through, in a rotationally symmetric, one-way system."""
    from ..surfaces import Shape

    inner = range(1, cs.n_surfaces - 1)
    if not cs.axial:
        raise SystemError_("The rotationally symmetric BPM needs an axial system (no tilts, decentres or folds): use POP")
    if any(bool(cs.is_mirror[j]) for j in inner):
        raise SystemError_("The BPM propagates one way through refracting systems; mirrors: use POP")
    if any(cs.ideal and cs.ideal[j] is not None for j in inner):
        raise SystemError_("An ideal lens has no glass for the BPM to propagate through: use POP")
    if any(cs.does and cs.does[j] is not None for j in inner):
        raise SystemError_("Diffractive surfaces are not modelled in the BPM: use POP")
    if any(type(cs.shapes[j]) is not Shape for j in inner):
        raise SystemError_("The BPM needs rotationally symmetric surfaces (no biconic or Zernike sags): use POP")


def _mode_profile(mode: dict, r: np.ndarray, lam_um: float) -> np.ndarray:
    from .fibermodes import fibre_modes, lp_field

    if mode.get("kind", "gaussian") == "gaussian":
        return np.exp(-((r / float(mode["waist"])) ** 2)).astype(complex)
    n1, n2 = _fibre_indices(mode, lam_um)
    a = float(mode["core_radius_um"]) * 1e-3
    m = fibre_modes(lam_um, float(mode["core_radius_um"]), n1, n2, vector=False, profiles=0)["lp_modes"][0]
    return lp_field(0, m["u"], m["w"], r / a).astype(complex)


def _mode_r(mode: dict, lam_um: float) -> float:
    from .pop import _mode_radius

    return _mode_radius(mode, lam_um)


__all__ = ["bpm", "Hankel"]
