"""Rotationally symmetric 3D FDTD (body of revolution) for linearly polarised light.

The structure is invariant under rotation about the z axis; the light is polarised along x, so the
fields are the azimuthal harmonic m = 1 (Taflove & Hagness, "Computational Electrodynamics",
ch. 12):

    E_r = e_r(r, z) cos phi,  E_phi = e_phi(r, z) sin phi,  E_z = e_z(r, z) cos phi
    H_r = h_r(r, z) sin phi,  H_phi = h_phi(r, z) cos phi,  H_z = h_z(r, z) sin phi

Maxwell's curl equations then become six coupled equations on the (r, z) half plane
(epsilon0 = mu0 = c = 1, lengths in micrometres):

    eps de_r/dt   = m h_z / r - dh_phi/dz - sigma e_r
    eps de_phi/dt = dh_r/dz - dh_z/dr - sigma e_phi
    eps de_z/dt   = (1/r) d(r h_phi)/dr - m h_r / r - sigma e_z
    dh_r/dt       = m e_z / r + de_phi/dz
    dh_phi/dt     = de_z/dr - de_r/dz
    dh_z/dt       = -(1/r) (d(r e_phi)/dr + m e_r)

This is the exact 3D field of the rotationally symmetric structure (no 2D slab model): a fibre is a
cylinder, a ball-lens tip a sphere. Yee grid in (r, z) (e_r and h_z at r half nodes, e_phi and h_r
at integer r; e_z, h_r, h_phi at z half nodes); on the axis e_z = 0 and dh_z/dr = 2 h_z(dr/2)/dr
(h_z is odd across the axis for m = 1). Courant number 0.4. Convolutional PML on the z ends and
the outer radius (stretching applied to the r and z differences; the m/r terms are not
stretched). Sources: a soft x-polarised current sheet (J_r = J cos phi, J_phi = -J sin phi) with
the profile of a 3D Gaussian beam or of the LP01 mode of a step-index fibre.

Results as for the 2D solver: field maps (azimuthally averaged |E|^2, mirrored to -r for
display), the Poynting flux P(z) = (pi/2) Int Re(e_r h_phi* - e_phi h_r*) r dr through monitor planes,
R, T, A from a reference run, and the transmitted field for physical-optics propagation:
E_x = (e_r - e_phi)/2 + (e_r + e_phi)/2 cos 2 phi, whose rotationally symmetric co-polarised part
(e_r - e_phi)/2 is exported (the cos 2 phi / sin 2 phi part is the depolarised fraction, reported).
"""

from __future__ import annotations

import math
import time

import numpy as np

from .fdtd import MAX_CELLS, MAX_STEPS, Cancelled, FdtdError, Shape, Spec, _poly_inside

COURANT_BOR = 0.4
M = 1


def _eps(shapes: list[Shape], n_bg: float, r: np.ndarray, z: np.ndarray, omega: float, sub: int = 4):
    """eps_r and conductivity on the (r, z) points, averaged over sub x sub sub-cells."""
    eps = np.full((len(r), len(z)), n_bg * n_bg)
    sig = np.zeros_like(eps)
    if not shapes:
        return eps, sig
    d = (r[1] - r[0]) if len(r) > 1 else (z[1] - z[0])
    off = (np.arange(sub) + 0.5) / sub - 0.5
    Z0, R0 = np.meshgrid(z, r)
    for s in shapes:
        e_r = s.n * s.n - s.k * s.k
        if e_r <= 0.05:
            raise FdtdError(f"Shape '{s.name or s.kind}': n^2 - k^2 = {e_r:.3g} (metal-like); dispersive media are not supported")
        frac = np.zeros_like(eps)
        for o1 in off:
            for o2 in off:
                Z, Rr = Z0 + o2 * d, np.abs(R0 + o1 * d)
                frac += _poly_inside(np.asarray(s.points, float), Z, Rr) if s.kind == "polygon" else s.inside(Z, Rr)
        frac /= sub * sub
        eps = eps * (1 - frac) + e_r * frac
        sig = sig * (1 - frac) + 2 * s.n * s.k * omega * frac
    return eps, sig


def _profile_z(N: int, P: int, d: float, dt: float, pos: np.ndarray):
    """CPML (b, a) at node positions `pos` (index units) for layers at both z ends."""
    m = 3
    smax = 0.8 * (m + 1) / d
    left = (P - pos) / P
    right = (pos - (N - 1 - P)) / P
    dd = np.clip(np.maximum(left, right), 0, 1) if P > 0 else np.zeros_like(pos)
    return _ba(dd, smax, dt)


def _profile_r(N: int, P: int, d: float, dt: float, pos: np.ndarray):
    """CPML (b, a) for the layer at the outer radius only."""
    m = 3
    smax = 0.8 * (m + 1) / d
    dd = np.clip((pos - (N - 1 - P)) / P, 0, 1) if P > 0 else np.zeros_like(pos)
    return _ba(dd, smax, dt)


def _ba(dd, smax, dt):
    sigma = smax * dd**3
    alpha = 0.05 * (1 - dd)
    b = np.exp(-(sigma + alpha) * dt)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(sigma > 0, sigma / (sigma + alpha) * (b - 1), 0.0)
    return b, a


def bor_dims(sp: Spec) -> tuple[float, int, int, int, float]:
    """Cell size, PML cells, radial and axial node counts, n_max; raises FdtdError for an invalid
    or oversized rotationally symmetric set-up. size_y is the domain diameter (0 <= r <= size_y / 2)."""
    n_max = max([sp.n_background] + [abs(complex(s.n, s.k)) for s in sp.shapes + (sp.reference_shapes or [])])
    d = sp.wavelength / (n_max * sp.ppw)
    P = int(sp.pml_cells)
    Nr = max(int(round(0.5 * sp.size_y / d)), 4) + P
    Nz = int(round(sp.size_z / d)) + 2 * P
    if Nr * Nz > MAX_CELLS:
        raise FdtdError(f"{Nz} x {Nr} cells exceed the limit of {MAX_CELLS}: reduce the domain or the points per wavelength")
    if sp.source not in ("gaussian", "mode"):
        raise FdtdError("A rotationally symmetric run needs a Gaussian-beam or fibre-mode source")
    if abs(sp.tilt_deg) > 1e-9:
        raise FdtdError("A rotationally symmetric run has no tilted beams")
    if abs(sp.focus_y) > 1e-9 or (sp.source == "mode" and abs(sp.mode_center_y) > 1e-9):
        raise FdtdError("A rotationally symmetric run needs the source on the axis (y = 0)")
    return d, P, Nr, Nz, n_max


def run_bor(sp: Spec, progress=None, control=None, export_field: bool = True) -> dict:
    from .fibermodes import fibre_modes, lp_field

    t0 = time.time()
    lam = sp.wavelength
    d, P, Nr, Nz, n_max = bor_dims(sp)
    dt = COURANT_BOR * d
    w = 2 * math.pi / lam
    ri = np.arange(Nr) * d  # integer r nodes
    rh = (np.arange(Nr) + 0.5) * d  # half r nodes
    zi = (np.arange(Nz) - P) * d
    zh = zi + 0.5 * d
    zs = sp.z_source if sp.z_source is not None else 0.1 * sp.size_z
    zr = sp.z_reflection if sp.z_reflection is not None else zs + 0.06 * sp.size_z
    zt = sp.z_transmission if sp.z_transmission is not None else 0.95 * sp.size_z
    if not (0 <= zs < zr < zt <= sp.size_z) and sp.reference:
        raise FdtdError("Monitors need 0 <= source < reflection monitor < transmission monitor <= domain length")
    ks, kr, kt = (int(round(v / d)) + P for v in (zs, zr, zt))
    for name, k in (("source", ks), ("reflection monitor", kr), ("transmission monitor", kt)):
        if not (P + 1 <= k <= Nz - P - 2):
            raise FdtdError(f"The {name} lies in the absorbing layer")
    period = lam / dt
    transit = (sp.size_z + 0.5 * sp.size_y) * n_max * 2.5
    ramp = 3 * lam
    n_steps = int(math.ceil((ramp + transit) / dt + sp.periods_avg * period))
    if n_steps > MAX_STEPS:
        raise FdtdError(f"{n_steps} time steps exceed the limit of {MAX_STEPS}")
    runs = 2 if sp.reference else 1
    done = [0]

    # source profile J(r) at the source plane
    if sp.source == "mode":
        fm = fibre_modes(lam, sp.mode_half_width, sp.mode_n_core, sp.mode_n_clad, vector=False, profiles=0)
        lp = fm["lp_modes"][0]

        def J(r):
            return lp_field(0, lp["u"], lp["w"], r / sp.mode_half_width).astype(complex)
    else:
        n_src = sp.n_background

        def J(r):
            k = 2 * math.pi * n_src / lam
            zR = k * sp.waist**2 / 2
            q = (zs - sp.focus_z) - 1j * zR
            return (-1j * zR / q) * np.exp(1j * k * (zs - sp.focus_z) + 1j * k * r * r / (2 * q))

    Jh, Ji = J(rh), J(ri)

    def one(shapes) -> dict:
        f32 = np.float32
        e_er, s_er = _eps(shapes, sp.n_background, rh, zi, w)
        e_ep, s_ep = _eps(shapes, sp.n_background, ri, zi, w)
        e_ez, s_ez = _eps(shapes, sp.n_background, ri, zh, w)

        def coef(e, s):
            return ((1 - s * dt / (2 * e)) / (1 + s * dt / (2 * e))).astype(f32), ((dt / e) / (1 + s * dt / (2 * e))).astype(f32)

        ca_r, cb_r = coef(e_er, s_er)
        ca_p, cb_p = coef(e_ep, s_ep)
        ca_z, cb_z = coef(e_ez, s_ez)
        er = np.zeros((Nr, Nz), f32)
        ep = np.zeros((Nr, Nz), f32)
        ez = np.zeros((Nr, Nz), f32)
        hr = np.zeros((Nr, Nz), f32)
        hp = np.zeros((Nr, Nz), f32)
        hz = np.zeros((Nr, Nz), f32)
        # CPML: z layers (columns) and the outer r layer (rows)
        cols = np.unique(np.r_[0 : P + 2, Nz - P - 2 : Nz])
        rows = np.arange(max(Nr - P - 2, 0), Nr)
        bzi, azi = (x[cols].astype(f32) for x in _profile_z(Nz, P, d, dt, np.arange(Nz, dtype=float)))
        bzh, azh = (x[cols].astype(f32) for x in _profile_z(Nz, P, d, dt, np.arange(Nz) + 0.5))
        bri, ari = (x[rows, None].astype(f32) for x in _profile_r(Nr, P, d, dt, np.arange(Nr, dtype=float)))
        brh, arh = (x[rows, None].astype(f32) for x in _profile_r(Nr, P, d, dt, np.arange(Nr) + 0.5))
        psi = {k: np.zeros((Nr, cols.size), f32) for k in ("hr_z", "hp_z", "er_z", "ep_z")}
        psi.update({k: np.zeros((rows.size, Nz), f32) for k in ("hp_r", "hz_r", "ep_r", "ez_r")})
        inv_ri = np.zeros(Nr)
        inv_ri[1:] = 1 / ri[1:]
        inv_ri = inv_ri.astype(f32)[:, None]
        inv_rh = (1 / rh).astype(f32)[:, None]
        rif = ri.astype(f32)[:, None]
        rhf = rh.astype(f32)[:, None]
        dtf = f32(dt)
        invd = f32(1 / d)
        D = np.zeros((Nr, Nz), f32)  # scratch
        amp_h, ph_h = np.abs(Jh), np.angle(Jh)
        amp_i, ph_i = np.abs(Ji), np.angle(Ji)
        n_avg = int(round(sp.periods_avg * period))
        start_avg = n_steps - n_avg
        acc = {k: np.zeros((Nr, Nz), complex) for k in ("er", "ep", "ez", "hr", "hp", "hz")}
        half = [np.zeros(Nr, complex), np.zeros(Nr, complex)]

        def cpml_z(key, diff, b, a):
            p = psi[key]
            p *= b
            p += a * diff[:, cols]
            diff[:, cols] += p

        def cpml_r(key, diff, b, a):
            p = psi[key]
            p *= b
            p += a * diff[rows]
            diff[rows] += p

        for n in range(n_steps):
            t = n * dt
            if control is not None and control.get("cancel"):
                raise Cancelled()
            # ---------------- H from E (time n)
            # h_r += dt (m e_z / r + de_phi/dz)   [at (i, k+1/2)]
            D[:] = 0
            np.subtract(ep[:, 1:], ep[:, :-1], out=D[:, :-1])
            D *= invd
            cpml_z("hr_z", D, bzh, azh)
            hr += dtf * (D + M * ez * inv_ri)
            hr[0] += dtf * M * ez[1] * invd  # axis: m e_z / r -> m de_z/dr (e_z(0) = 0)
            # h_phi += dt (de_z/dr - de_r/dz)   [at (i+1/2, k+1/2)]
            D[:] = 0
            np.subtract(ez[1:], ez[:-1], out=D[:-1])
            D *= invd
            cpml_r("hp_r", D, brh, arh)
            hp += dtf * D
            D[:] = 0
            np.subtract(er[:, 1:], er[:, :-1], out=D[:, :-1])
            D *= invd
            cpml_z("hp_z", D, bzh, azh)
            hp -= dtf * D
            # h_z -= dt ((1/r) d(r e_phi)/dr + m e_r / r)   [at (i+1/2, k)]
            D[:] = 0
            np.subtract(rif[1:] * ep[1:], rif[:-1] * ep[:-1], out=D[:-1])
            D *= invd
            cpml_r("hz_r", D, brh, arh)
            hz -= dtf * inv_rh * (D + M * er)
            # ---------------- E from H (time n + 1/2)
            ramp_f = 0.5 * (1 - math.cos(math.pi * min(1.0, t / ramp)))
            ct = ramp_f
            src_h = (ct * amp_h * np.cos(w * (t + 0.5 * dt) - ph_h)).astype(f32)
            src_i = (ct * amp_i * np.cos(w * (t + 0.5 * dt) - ph_i)).astype(f32)
            # e_r: m h_z / r - dh_phi/dz   [at (i+1/2, k)]
            D[:] = 0
            np.subtract(hp[:, 1:], hp[:, :-1], out=D[:, 1:])
            D *= invd
            cpml_z("er_z", D, bzi, azi)
            er *= ca_r
            er += cb_r * (M * hz * inv_rh - D)
            # e_phi: dh_r/dz - dh_z/dr   [at (i, k)]
            D[:] = 0
            np.subtract(hr[:, 1:], hr[:, :-1], out=D[:, 1:])
            D *= invd
            cpml_z("ep_z", D, bzi, azi)
            G = D.copy()
            D[:] = 0
            np.subtract(hz[1:], hz[:-1], out=D[1:])
            D[0] = 2 * hz[0]  # axis: h_z odd across r = 0
            D *= invd
            cpml_r("ep_r", D, bri, ari)
            ep *= ca_p
            ep += cb_p * (G - D)
            # e_z: (1/r) d(r h_phi)/dr - m h_r / r   [at (i, k+1/2)]
            D[:] = 0
            np.subtract(rhf[1:] * hp[1:], rhf[:-1] * hp[:-1], out=D[1:])
            D *= invd
            cpml_r("ez_r", D, bri, ari)
            ez *= ca_z
            ez += cb_z * inv_ri * (D - M * hr)
            ez[0] = 0.0
            # soft x-polarised current sheet: J_r = J cos phi, J_phi = -J sin phi
            er[:, ks] -= cb_r[:, ks] * src_h * invd
            ep[:, ks] += cb_p[:, ks] * src_i * invd
            if n >= start_avg:
                pe = np.exp(1j * w * (n + 1) * dt)
                ph = np.exp(1j * w * (n + 0.5) * dt)
                acc["er"] += er * pe
                acc["ep"] += ep * pe
                acc["ez"] += ez * pe
                acc["hr"] += hr * ph
                acc["hp"] += hp * ph
                acc["hz"] += hz * ph
                half[0 if n < start_avg + n_avg // 2 else 1] += er[:, kr] * pe
            done[0] += 1
            if progress is not None and n % 50 == 0:
                progress(done[0] / (n_steps * runs))
        norm = 2.0 / n_avg
        out = {k: v * norm for k, v in acc.items()}
        h0, h1 = half
        out["convergence"] = float(np.linalg.norm(h0 - h1) / max(np.linalg.norm(h0 + h1) / 2, 1e-300))
        out["eps"] = e_ep
        return out

    def flux(res: dict, k: int, ref: dict | None = None) -> float:
        er, ep, hr, hp = (res[x] - (ref[x] if ref is not None else 0) for x in ("er", "ep", "hr", "hp"))
        sel = slice(0, Nr - P)
        hp_k = 0.5 * (hp[:, k] + hp[:, k - 1])
        hr_k = 0.5 * (hr[:, k] + hr[:, k - 1])
        s = np.real(er[:, k] * np.conj(hp_k)) * rh - np.real(ep[:, k] * np.conj(hr_k)) * ri
        return float(0.5 * math.pi * s[sel].sum() * d)

    tot = one(sp.shapes)
    res: dict = {"geometry": "axisymmetric", "cells": [int(Nz), int(Nr)], "dx_um": d, "dt": dt, "steps": n_steps, "periods_averaged": sp.periods_avg, "convergence": tot["convergence"], "polarization": "x (m = 1)"}
    notes = []
    if tot["convergence"] > 0.02:
        notes.append(f"The field has not settled (last periods differ by {tot['convergence'] * 100:.1f} %): enlarge the domain transit time or check resonances")
    T_scale = 1.0
    if sp.reference:
        ref = one(sp.reference_shapes or [])
        F_inc = flux(ref, kr)
        if F_inc <= 0:
            raise FdtdError("No incident power at the reflection monitor")
        R = -flux(tot, kr, ref) / F_inc
        T = flux(tot, kt) / F_inc
        res.update({"R": R, "T": T, "A": 1 - R - T, "incident_flux": F_inc, "reference_transmission": flux(ref, kt) / F_inc})
        T_scale = T
    else:
        res["transmitted_flux"] = flux(tot, kt)
    # maps: phi-averaged |E|^2 on integer nodes, mirrored to -r
    er_i = np.vstack([tot["er"][:1], 0.5 * (tot["er"][1:] + tot["er"][:-1])])  # r half -> integer
    ez_i = np.hstack([tot["ez"][:, :1], 0.5 * (tot["ez"][:, 1:] + tot["ez"][:, :-1])])  # z half -> integer
    I = 0.5 * (np.abs(er_i) ** 2 + np.abs(tot["ep"]) ** 2 + np.abs(ez_i) ** 2)
    rs = slice(0, Nr - P)
    zsl = slice(P, Nz - P)
    I = I[rs, zsl]
    nmap = np.sqrt(tot["eps"][rs, zsl])
    fld = np.real(er_i[rs, zsl])
    f = max(1, int(math.ceil(max(2 * I.shape[0], I.shape[1]) / sp.map_cells)))

    def blk(a):
        ny, nz = (a.shape[0] // f) * f, (a.shape[1] // f) * f
        return a[:ny, :nz].reshape(ny // f, f, nz // f, f).mean(axis=(1, 3)) if f > 1 else a

    def blk1(v):
        m = (len(v) // f) * f
        return v[:m].reshape(-1, f).mean(1) if f > 1 else v

    rr = blk1(ri[rs])
    zz = blk1(zi[zsl])

    def mirror(a):
        return np.vstack([a[::-1], a])

    res.update(
        {
            "z_um": zz.tolist(),
            "y_um": np.concatenate([-rr[::-1], rr]).tolist(),
            "intensity": mirror(blk(I)).tolist(),
            "field": mirror(blk(fld)).tolist(),
            "index": mirror(blk(nmap)).tolist(),
            "monitors": {"source_z": zs, "reflection_z": zr, "transmission_z": zt},
        }
    )
    if export_field:
        # co-polarised, rotationally symmetric part of E_x at the transmission plane (integer r nodes)
        e_r_t = er_i[:, kt]
        e_p_t = tot["ep"][:, kt]
        co = 0.5 * (e_r_t - e_p_t)
        cross = 0.5 * (e_r_t + e_p_t)
        sel = slice(0, Nr - P)
        r_ = ri[sel]
        p_co = float((np.abs(co[sel]) ** 2 * r_).sum() * 2 * math.pi * d)
        p_x = float(2 * (np.abs(cross[sel]) ** 2 * r_).sum() * math.pi * d + (np.abs(ez_i[sel, kt]) ** 2 * r_).sum() * math.pi * d)
        scale = math.sqrt(T_scale * p_co / (p_co + p_x) / p_co) if p_co > 0 else 0.0
        U = co[sel] * scale
        res["exported_field"] = {
            "r_um": r_.tolist(),
            "re": np.real(U).tolist(),
            "im": np.imag(U).tolist(),
            "z_um": zt,
            "wavelength_um": lam,
            "n_medium": float(np.sqrt(tot["eps"][0, kt])),
            "power": float(T_scale * p_co / (p_co + p_x)) if p_co > 0 else 0.0,
            "depolarised_fraction": p_x / (p_co + p_x) if p_co > 0 else 0.0,
        }
        if p_co > 0 and p_x / (p_co + p_x) > 0.02:
            notes.append(f"{p_x / (p_co + p_x) * 100:.1f} % of the transmitted field is cross-polarised or longitudinal (high NA): the exported scalar field leaves it out")
    res.update({"notes": notes, "time_s": time.time() - t0, "method": "Rotationally symmetric 3D FDTD (body of revolution, m = 1, Yee in r-z, Courant 0.4) with CPML; single-frequency DFT; Poynting flux through monitor planes; R, T from a reference run (incident field subtracted)"})
    return res
