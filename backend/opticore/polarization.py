"""Polarisation ray tracing (3x3 polarisation ray-tracing matrices).

Following Chipman's three-dimensional polarisation ray-tracing calculus
(R. A. Chipman, G. Young, W. S. T. Lam, *Polarized Light and Optical
Systems*, ch. 9-10), every ray intersection j contributes

    P_j = a_s s s^T + a_p p' p^T + k' k^T

with k, k' the incident and exiting unit propagation vectors, N the surface
normal, s = (k x N)/|k x N| (any unit vector perpendicular to k at normal
incidence), p = k x s and p' = k' x s. The amplitude coefficients a_s, a_p
are power-normalised (|a|^2 is the transmitted power fraction):

  refraction (bare or coated)  thin-film characteristic matrix
                               (thinfilm.stack_amplitudes; an empty stack is
                               the Fresnel interface)
  ideal mirror                 a_s = -1, a_p = +1 (perfect conductor; with the
                               basis above this reverses E at normal incidence)
  absorption                   both scaled by sqrt(exp(-alpha L))

The ray's matrix is P = P_N ... P_1. Writing the input field in the object-
space basis (x_in, y_in) perpendicular to k_0 (x_in = normalised projection of
global x) and the output in the matching image-space basis gives the 2x2
Jones pupil J(px, py). From J:

  transmission (input E)    |J E|^2
  unpolarised transmission  (sigma_1^2 + sigma_2^2) / 2   (singular values)
  diattenuation             (sigma_1^2 - sigma_2^2) / (sigma_1^2 + sigma_2^2)
  retardance                linear retardance: J = U H (polar decomposition),
                            U (global phase removed) = R(theta) L with L a
                            symmetric (linear) retarder; retardance is the
                            eigenvalue phase difference of L
  rotation                  theta: geometric rotation between the local bases
                            (skew rays) plus any circular retardance; it
                            depends on the basis convention and is reported
                            separately so it does not masquerade as retardance.
                            U is taken modulo its global phase, so U and -U
                            are the same element: theta is read in
                            [-pi/2, pi/2] (a rotation by pi is -I, a phase)

Mirror-image systems: with right-handed bases (x, y, k) on both sides an
odd number m of reflections gives an ideal mirror J = diag(-1, +1), which
reads as half a wave of retardance although the mirror retards nothing.
Retardance and rotation are therefore evaluated on F J with F = diag(1,
(-1)^m), i.e. in a mirror-image (left-handed) output basis after an odd
number of reflections (Chipman's geometric transform for reflecting
systems): an ideal mirror then has zero retardance and a metal mirror the
retardance arg(r_p / -r_s) (Born & Wolf signs) of its s-p phase. J, the
output ellipses and the Mueller matrix stay in the right-handed bases (there
an ideal mirror is M = diag(1, 1, -1, -1), the usual convention).

The projection bases are the "local x/y" convention; for strongly curved
pupils the choice of basis (not the physics) affects how J is split into
x and y components. Geometric rays only: no diffraction or scattering, and
dielectric reflections are not traced (sequential mode).

Uniaxial crystals (birefringence.py): at a crystal face the incident field
splits into the ordinary and extraordinary waves with amplitudes from the
continuity of tangential E and H; a trace follows one wave per crystal, and
P_j maps the incident mode vectors to the kept transmitted wave(s) through a
dual basis, P_j = [out_1, out_2, k'] [E_1, E_2, k]^-1. With crystal_modes =
"sum" every combination of waves is traced and the matrices are added
coherently with the phase of their optical path difference (measured on a
plane normal to the exit ray), which describes wave plates and other
elements whose two waves leave together; the largest lateral separation of
the waves is reported.

Ideal polarising elements (model.JonesElement) act after the interface in
the plane normal to the ray: polariser a a^T + k k^T, retarder
a a^T + exp(i delta) b b^T + k k^T (a the transmission / fast axis projected
normal to the ray, b = k x a, delay delta of the slow axis).

Mueller matrices: M = A (J ⊗ J*) A^-1 with Stokes S = A (E ⊗ E*), S3 =
2 Im(Ex* Ey) as in `ellipse`; the pupil average of M (Gaussian quadrature)
is the beam's Mueller matrix, depolarising when J varies over the pupil.
Depolarisation index DI = sqrt(sum M_ij^2 - M_00^2) / (sqrt(3) M_00)
(1: non-depolarising, 0: ideal depolariser).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import replace

import numpy as np

from .paraxial import compute_pupil
from .raytrace import gauss_pupil, launch, trace
from .system import CompiledSystem
from .thinfilm import stack_amplitudes

EX = np.array([1.0, 0.0, 0.0])
EY = np.array([0.0, 1.0, 0.0])

INPUT_STATES: dict[str, np.ndarray] = {
    "x": np.array([1.0, 0.0], dtype=complex),
    "y": np.array([0.0, 1.0], dtype=complex),
    "45": np.array([1.0, 1.0], dtype=complex) / math.sqrt(2.0),
    "-45": np.array([1.0, -1.0], dtype=complex) / math.sqrt(2.0),
    "rcp": np.array([1.0, -1j], dtype=complex) / math.sqrt(2.0),
    "lcp": np.array([1.0, 1j], dtype=complex) / math.sqrt(2.0),
}


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def _transverse_basis(k: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """x' = normalised projection of global x onto the plane normal to k (global y if degenerate), y' = k x x'."""
    x = EX[None, :] - (k @ EX)[:, None] * k
    bad = np.linalg.norm(x, axis=1) < 1e-9
    if np.any(bad):
        y = EY[None, :] - (k[bad] @ EY)[:, None] * k[bad]
        x[bad] = np.cross(y, k[bad])
    x = _unit(x)
    return x, np.cross(k, x)


def _s_vectors(k: np.ndarray, n: np.ndarray) -> np.ndarray:
    s = np.cross(k, n)
    nn = np.linalg.norm(s, axis=1)
    bad = nn < 1e-12
    if np.any(bad):  # normal incidence: any vector perpendicular to k
        x, _ = _transverse_basis(k[bad])
        s[bad] = x
        nn[bad] = 1.0
    return s / nn[:, None]


def _jones_element_P(cs: CompiledSystem, j: int, k: np.ndarray) -> np.ndarray:
    """3x3 matrices of the ideal polariser / retarder of surface j for rays along k (global)."""
    el = cs.jones[j]
    th = math.radians(el.angle_deg)
    a0 = cs.frames[j].to_global_dirs(np.array([[math.cos(th), math.sin(th), 0.0]]))[0]
    a = a0[None, :] - (k @ a0)[:, None] * k
    bad = np.linalg.norm(a, axis=1) < 1e-9
    if np.any(bad):  # axis along the ray: use the transverse basis
        a[bad] = _transverse_basis(k[bad])[0]
    a = _unit(a)
    b = np.cross(k, a)
    P = np.einsum("ni,nj->nij", a, a).astype(complex) + np.einsum("ni,nj->nij", k, k)
    if el.kind == "retarder":
        P += np.exp(2j * math.pi * el.retardance_waves) * np.einsum("ni,nj->nij", b, b)
    return P


def _bend_P(k_in: np.ndarray, k_out: np.ndarray) -> np.ndarray:
    """Lossless rotation of the field with a ray turned from k_in to k_out (s = k_in x k_out kept, p = k x s
    follows the ray); the identity for rays that keep their direction."""
    s = np.cross(k_in, k_out)
    n = np.linalg.norm(s, axis=1)
    turned = n > 1e-15
    P = np.tile(np.eye(3, dtype=complex), (len(k_in), 1, 1))
    if np.any(turned):
        st = s[turned] / n[turned, None]
        ki, ko = k_in[turned], k_out[turned]
        P[turned] = np.einsum("ni,nj->nij", st, st) + np.einsum("ni,nj->nij", np.cross(ko, st), np.cross(ki, st)) + np.einsum("ni,nj->nij", ko, ki)
    return P


def _crystal_P(cs: CompiledSystem, wl: int, j: int, k_in, K_in, k_out, N) -> np.ndarray:
    """3x3 matrices of a face bordering a uniaxial crystal for the traced waves (see the module notes)."""
    from .birefringence import ORDINARY, Side, crystal_mode_field, interface_amplitudes, s_vector

    c_in, c_out = cs.crystal[j - 1], cs.crystal[j]
    med_in = c_in.at(wl) if c_in is not None else None
    med_out = c_out.at(wl) if c_out is not None else None
    side_in = Side(med=med_in) if med_in is not None else Side(n=float(cs.n_after[wl, j - 1]))
    side_out = Side(med=med_out) if med_out is not None else Side(n=float(cs.n_after[wl, j]))
    s = s_vector(K_in, N, _transverse_basis(k_in)[0])
    if med_in is None:
        E1 = s.astype(complex)
        E2 = np.cross(k_in, s).astype(complex)
        phys = (True, True)
    else:
        E1 = crystal_mode_field(K_in, med_in, med_in.mode, s)
        E2 = np.cross(k_in.astype(complex), E1)
        E2 = E2 / np.linalg.norm(E2, axis=1, keepdims=True)
        phys = (True, False)
    outs = []
    for E, ph in ((E1, phys[0]), (E2, phys[1])):
        if not ph:
            outs.append(np.zeros_like(E))
            continue
        _, trans = interface_amplitudes(K_in, E, k_in, N, side_in, side_out, s)
        if med_out is None:
            outs.append(trans[0][0][:, None] * trans[0][2] + trans[1][0][:, None] * trans[1][2])
        else:
            m = trans[0] if med_out.mode == ORDINARY else trans[1]
            outs.append(m[0][:, None] * m[2])
    Min = np.stack([E1, E2, k_in.astype(complex)], axis=2)
    Mout = np.stack([outs[0], outs[1], k_out.astype(complex)], axis=2)
    return np.einsum("nij,njk->nik", Mout, np.linalg.inv(Min))


def polarization_matrices(cs: CompiledSystem, wl: int, P0: np.ndarray, D0: np.ndarray, clip: bool = True) -> dict:
    """Trace rays and return per-ray 3x3 polarisation matrices (NaN for failed rays)."""
    r = trace(cs, wl, P0, D0, clip=clip, record=True)
    nr = P0.shape[0]
    end = r.end_surface
    lam = float(cs.wavelengths[wl])
    ok = r.ok.copy()
    P = np.tile(np.eye(3, dtype=complex), (nr, 1, 1))
    k_prev = _unit(D0.astype(float))
    last_pt = P0.astype(float).copy()
    for j in range(1, end + 1):
        if cs.is_cb[j]:
            continue
        idx = np.nonzero(ok)[0]
        if idx.size == 0:
            break
        q = r.points[idx, j, :]
        # absorption on the segment before surface j (amplitude: square root of intensity)
        alpha = cs.absorption[wl, j - 1]
        if alpha > 0:
            L = np.linalg.norm(q - last_pt[idx], axis=1)
            P[idx] *= np.sqrt(np.exp(-alpha * L))[:, None, None]
        last_pt[idx] = q
        if j == end:
            break  # image surface: no interaction
        k_in = k_prev[idx]
        k_out = r.dirs_after[idx, j, :]
        N = r.normals[idx, j, :]
        n1, n2 = cs.n_after[wl, j - 1], cs.n_after[wl, j]
        coat = cs.coatings[j] if cs.coatings else None
        cry = cs.crystal if cs.crystal else None
        if cry is not None and (cry[j - 1] is not None or cry[j] is not None):
            K_in = r.waves_after[idx, j - 1, :] if cry[j - 1] is not None else float(n1) * k_in
            Pj = _crystal_P(cs, wl, j, k_in, K_in, k_out, N)
            if cs.jones and cs.jones[j] is not None:
                Pj = np.einsum("nij,njk->nik", _jones_element_P(cs, j, k_out), Pj)
            P[idx] = np.einsum("nij,njk->nik", Pj, P[idx])
            k_prev[idx] = k_out
            continue
        if cs.is_mirror[j] and coat is not None:
            # coated mirror: Macleod r_s, r_p; the PRT p basis (k x s) flips on reflection, so a_p = -r_p
            cos_i = np.abs(np.einsum("ij,ij->i", k_in, N))
            amp = stack_amplitudes(abs(float(n1)), coat.substrate, coat.layers_at(lam), lam, cos_i)
            a_s, a_p = amp["rs"], -amp["rp"]
        elif cs.is_mirror[j]:
            a_s = np.full(idx.size, -1.0 + 0j)
            a_p = np.full(idx.size, 1.0 + 0j)
        elif n1 == n2 and coat is None:
            # no interface; an ideal lens or a diffractive phase may still turn the ray: rotate the field
            # with it about k_in x k_out (lossless, s and p kept), so that it stays transverse
            Pj = _bend_P(k_in, k_out)
            if cs.jones and cs.jones[j] is not None:
                Pj = np.einsum("nij,njk->nik", _jones_element_P(cs, j, k_out), Pj)
            P[idx] = np.einsum("nij,njk->nik", Pj, P[idx])
            k_prev[idx] = k_out
            continue
        else:
            cos_i = np.abs(np.einsum("ij,ij->i", k_in, N))
            layers = () if coat is None else coat.oriented(lam, n1, n2)
            amp = stack_amplitudes(n1, n2, layers, lam, cos_i)
            a_s, a_p = amp["ts"], amp["tp"]
        s = _s_vectors(k_in, N)
        p_in = np.cross(k_in, s)
        p_out = np.cross(k_out, s)
        Pj = (
            a_s[:, None, None] * np.einsum("ni,nj->nij", s, s)
            + a_p[:, None, None] * np.einsum("ni,nj->nij", p_out, p_in)
            + np.einsum("ni,nj->nij", k_out, k_in)
        )
        if cs.jones and cs.jones[j] is not None:
            Pj = np.einsum("nij,njk->nik", _jones_element_P(cs, j, k_out), Pj)
        P[idx] = np.einsum("nij,njk->nik", Pj, P[idx])
        k_prev[idx] = k_out
    P[~ok] = np.nan
    return {"P": P, "ok": ok, "k_in": _unit(D0.astype(float)), "k_out": k_prev, "trace": r}


def crystal_owners(cs: CompiledSystem) -> list[int]:
    return sorted({c.owner for c in (cs.crystal or []) if c is not None})


def with_crystal_modes(cs: CompiledSystem, modes: dict[int, str]) -> CompiledSystem:
    """The compiled system with other waves followed in its crystals ({owner surface: mode})."""
    new = {}
    lst = []
    for c in cs.crystal:
        if c is None:
            lst.append(None)
            continue
        if c.owner not in new:
            new[c.owner] = replace(c, mode=modes.get(c.owner, c.mode))
        lst.append(new[c.owner])
    return replace(cs, crystal=lst)


def summed_matrices(cs: CompiledSystem, wl: int, P0: np.ndarray, D0: np.ndarray, clip: bool = True) -> dict:
    """Coherent sum of the polarisation matrices of every combination of waves in the crystals (module notes)."""
    owners = crystal_owners(cs)
    combos = list(itertools.product(("ordinary", "extraordinary"), repeat=len(owners)))
    if len(combos) > 64:
        raise ValueError("Summing the waves of more than 6 crystals is not supported")
    lam_mm = float(cs.wavelengths[wl]) * 1e-3
    n_img = float(cs.n_after[wl, cs.n_surfaces - 2])
    runs = []
    for combo in combos:
        m = polarization_matrices(with_crystal_modes(cs, dict(zip(owners, combo))), wl, P0, D0, clip)
        r = m["trace"]
        runs.append((m, r.points[:, r.end_surface, :], r.opl))
    nr = P0.shape[0]
    # phase reference: the combination with the most rays, else the first one that passes
    k0 = int(np.argmax([int(r[0]["ok"].sum()) for r in runs]))
    ref = np.where(runs[k0][0]["ok"], k0, -1)
    for k, (m, _, _) in enumerate(runs):
        ref[m["ok"] & (ref < 0)] = k
    ok_any = ref >= 0
    Xr = np.full((nr, 3), np.nan)
    kr = np.full((nr, 3), np.nan)
    Lr = np.full(nr, np.nan)
    for k, (m, X, L) in enumerate(runs):
        sel = ref == k
        Xr[sel], kr[sel], Lr[sel] = X[sel], m["k_out"][sel], L[sel]
    P = np.zeros((nr, 3, 3), dtype=complex)
    sep = 0.0
    for m, X, L in runs:
        ok = m["ok"] & ok_any
        if not ok.any():
            continue
        dX = Xr[ok] - X[ok]
        along = np.einsum("ij,ij->i", kr[ok], dX)
        phase = 2.0 * math.pi * (L[ok] + n_img * along - Lr[ok]) / lam_mm
        P[ok] += np.exp(1j * phase)[:, None, None] * m["P"][ok]
        sep = max(sep, float(np.linalg.norm(dX - along[:, None] * kr[ok], axis=1).max()))
    P[~ok_any] = np.nan
    k_out = np.where(ok_any[:, None], kr, runs[0][0]["k_out"])
    return {"P": P, "ok": ok_any, "k_in": runs[0][0]["k_in"], "k_out": k_out, "trace": runs[k0][0]["trace"], "separation_mm": sep, "combinations": len(combos)}


def jones_pupil(cs: CompiledSystem, wl: int, P0: np.ndarray, D0: np.ndarray, clip: bool = True, crystal_modes: str = "prescription") -> dict:
    """2x2 Jones matrices in the local x/y bases of object and image space. crystal_modes "sum" adds the
    waves of the crystals coherently (summed_matrices)."""
    if crystal_modes == "sum" and crystal_owners(cs):
        m = summed_matrices(cs, wl, P0, D0, clip)
    else:
        m = polarization_matrices(cs, wl, P0, D0, clip)
    xi, yi = _transverse_basis(m["k_in"])
    xo, yo = _transverse_basis(m["k_out"])
    Bi = np.stack([xi, yi], axis=2).astype(complex)  # (n, 3, 2)
    Bo = np.stack([xo, yo], axis=2).astype(complex)
    J = np.einsum("nji,njk,nkl->nil", Bo.conj(), m["P"], Bi)
    # reflections on the way to the image (the same for every ray of a sequential trace); jones_properties
    # reads retardance and rotation in the mirror-image output basis when it is odd (module notes)
    refl = int(np.count_nonzero(cs.is_mirror[1 : m["trace"].end_surface]))
    return {"J": J, "ok": m["ok"], "trace": m["trace"], "separation_mm": m.get("separation_mm"), "combinations": m.get("combinations", 1), "reflections": refl}


_A = np.array([[1, 0, 0, 1], [1, 0, 0, -1], [0, 1, 1, 0], [0, 1j, -1j, 0]], dtype=complex)
_A_INV = np.linalg.inv(_A)


def mueller(J: np.ndarray) -> np.ndarray:
    """Mueller matrices (n, 4, 4) of Jones matrices (n, 2, 2): M = A (J ⊗ J*) A^-1."""
    n = J.shape[0]
    K = np.einsum("nij,nkl->nikjl", J, np.conj(J)).reshape(n, 4, 4)
    return np.einsum("ij,njk,kl->nil", _A, K, _A_INV).real


def stokes(E: np.ndarray) -> np.ndarray:
    """Stokes vectors (n, 4) of Jones vectors (n, 2)."""
    ex, ey = E[:, 0], E[:, 1]
    return np.stack([np.abs(ex) ** 2 + np.abs(ey) ** 2, np.abs(ex) ** 2 - np.abs(ey) ** 2, 2 * np.real(np.conj(ex) * ey), 2 * np.imag(np.conj(ex) * ey)], axis=1)


def depolarization_index(M: np.ndarray) -> float:
    m00 = float(M[0, 0])
    if m00 <= 0:
        return float("nan")
    return float(math.sqrt(max(0.0, float((M**2).sum()) - m00 * m00)) / (math.sqrt(3.0) * m00))


def jones_properties(J: np.ndarray, reflections: int = 0) -> dict:
    """Unpolarised transmission, diattenuation and retardance of Jones matrices (n, 2, 2) in right-handed
    bases. `reflections` (jones_pupil's count): when odd, retardance and rotation are read on
    diag(1, -1) J, the output in the mirror-image basis, so that an ideal mirror retards nothing."""
    n = J.shape[0]
    if reflections % 2:
        J = J * np.array([1.0, -1.0])[None, :, None]
    T = np.full(n, np.nan)
    D = np.full(n, np.nan)
    R = np.full(n, np.nan)
    ROT = np.full(n, np.nan)
    TOT = np.full(n, np.nan)
    good = np.all(np.isfinite(J.reshape(n, -1)), axis=1)
    if np.any(good):
        W, sig, Vh = np.linalg.svd(J[good])
        t1, t2 = sig[:, 0] ** 2, sig[:, 1] ** 2
        T[good] = 0.5 * (t1 + t2)
        D[good] = np.where(t1 + t2 > 0, (t1 - t2) / np.where(t1 + t2 > 0, t1 + t2, 1.0), 0.0)
        U = np.einsum("nij,njk->nik", W, Vh)
        # remove the global phase (U -> SU(2)), then split U = R(theta) L into a
        # rotator and a linear (symmetric) retarder: tan(theta) = (u21 - u12) / (u11 + u22)
        U = U / np.sqrt(np.linalg.det(U))[:, None, None]
        # U and -U differ by a global phase only (the principal root may pick either): take the one with
        # Re tr U >= 0, so that theta lies in [-pi/2, pi/2] and a pure phase is no rotation
        U = np.where((np.real(U[:, 0, 0] + U[:, 1, 1]) < 0.0)[:, None, None], -U, U)
        th = np.arctan2(np.real(U[:, 1, 0] - U[:, 0, 1]), np.real(U[:, 0, 0] + U[:, 1, 1]))
        c, s_ = np.cos(th), np.sin(th)
        Rm = np.zeros_like(U)
        Rm[:, 0, 0], Rm[:, 0, 1], Rm[:, 1, 0], Rm[:, 1, 1] = c, s_, -s_, c  # R(-theta)
        L = np.einsum("nij,njk->nik", Rm, U)
        ev = np.linalg.eigvals(L)
        R[good] = np.abs(np.angle(ev[:, 0] / ev[:, 1]))
        ROT[good] = th
        evu = np.linalg.eigvals(U)
        TOT[good] = np.abs(np.angle(evu[:, 0] / evu[:, 1]))
    return {"transmission": T, "diattenuation": D, "retardance": R, "rotation": ROT, "total_retardance": TOT}


def ellipse(E: np.ndarray) -> dict:
    """Polarisation ellipse of Jones vectors (n, 2): azimuth (rad, from x), ellipticity angle chi (rad, >0 left-handed in this convention), intensity."""
    ex, ey = E[:, 0], E[:, 1]
    I = np.abs(ex) ** 2 + np.abs(ey) ** 2
    s1 = np.abs(ex) ** 2 - np.abs(ey) ** 2
    s2 = 2 * np.real(np.conj(ex) * ey)
    s3 = 2 * np.imag(np.conj(ex) * ey)
    with np.errstate(invalid="ignore", divide="ignore"):
        az = 0.5 * np.arctan2(s2, s1)
        chi = 0.5 * np.arcsin(np.clip(s3 / np.where(I > 0, I, np.nan), -1, 1))
    return {"azimuth": az, "ellipticity": chi, "intensity": I}


def polarization_pupil(cs: CompiledSystem, field: int = 0, wavelength: int | None = None, grid: int = 15, input_state: str = "x", crystal_modes: str = "sum") -> dict:
    """Jones-pupil maps and pupil-averaged polarisation properties (with the beam's Mueller matrix) for one
    field and wavelength. crystal_modes: "sum" (both waves of every crystal, coherently) or "prescription"
    (the waves set in the prescription)."""
    if input_state not in INPUT_STATES and input_state != "unpolarized":
        raise ValueError(f"Unknown input polarisation '{input_state}'")
    if crystal_modes not in ("sum", "prescription"):
        raise ValueError(f"Unknown crystal mode handling '{crystal_modes}'")
    wl = cs.wl_index(wavelength)
    pupil = compute_pupil(cs, wl)
    u = np.linspace(-1.0, 1.0, grid)
    gx, gy = np.meshgrid(u, u)
    inside = gx**2 + gy**2 <= 1.0 + 1e-12
    px, py = gx[inside], gy[inside]
    P0, D0, _ = launch(cs, wl, field, px, py, pupil)
    jp = jones_pupil(cs, wl, P0, D0, crystal_modes=crystal_modes)
    J = jp["J"]
    props = jones_properties(J, jp["reflections"])
    if input_state == "unpolarized":
        T_in = props["transmission"]
        el = None
    else:
        E = np.einsum("nij,j->ni", J, INPUT_STATES[input_state])
        el = ellipse(E)
        T_in = el["intensity"]

    # pupil-area averages by Gaussian quadrature (independent of the display grid)
    qx, qy, qw = gauss_pupil(6)
    Q0, QD, _ = launch(cs, wl, field, qx, qy, pupil)
    qj = jones_pupil(cs, wl, Q0, QD, crystal_modes=crystal_modes)
    qp = jones_properties(qj["J"], qj["reflections"])
    okq = qj["ok"]
    wsum = qw[okq].sum()

    def avg(v):
        return float((qw[okq] * v[okq]).sum() / wsum) if wsum > 0 else None

    summary = {
        "unpolarized_transmission": avg(qp["transmission"]),
        "x_transmission": avg(np.abs(qj["J"][:, 0, 0]) ** 2 + np.abs(qj["J"][:, 1, 0]) ** 2),
        "y_transmission": avg(np.abs(qj["J"][:, 0, 1]) ** 2 + np.abs(qj["J"][:, 1, 1]) ** 2),
        "mean_diattenuation": avg(qp["diattenuation"]),
        "max_diattenuation": float(np.nanmax(qp["diattenuation"][okq])) if okq.any() else None,
        "rms_retardance_waves": math.sqrt(avg(qp["retardance"] ** 2)) / (2 * math.pi) if wsum > 0 else None,
        "max_retardance_waves": float(np.nanmax(qp["retardance"][okq]) / (2 * math.pi)) if okq.any() else None,
        "max_rotation_deg": float(np.degrees(np.nanmax(np.abs(qp["rotation"][okq])))) if okq.any() else None,
        "vignetted_fraction": float(1 - wsum),
    }
    if input_state != "unpolarized":
        Eq = np.einsum("nij,j->ni", qj["J"], INPUT_STATES[input_state])
        summary["input_transmission"] = avg(np.abs(Eq[:, 0]) ** 2 + np.abs(Eq[:, 1]) ** 2)
    else:
        summary["input_transmission"] = summary["unpolarized_transmission"]
    # the beam's Mueller matrix: pupil average of the rays' Mueller matrices (incoherent over the pupil)
    if wsum > 0:
        Mq = mueller(qj["J"][okq])
        Mavg = (qw[okq][:, None, None] * Mq).sum(axis=0) / wsum
        S_in = np.array([1.0, 0.0, 0.0, 0.0]) if input_state == "unpolarized" else stokes(INPUT_STATES[input_state][None, :])[0]
        S_out = Mavg @ S_in
        dop = float(math.sqrt(float((S_out[1:] ** 2).sum())) / S_out[0]) if S_out[0] > 0 else None
        summary["mueller"] = Mavg.tolist()
        summary["depolarization_index"] = depolarization_index(Mavg)
        summary["output_stokes"] = (S_out / S_out[0]).tolist() if S_out[0] > 0 else None
        summary["output_dop"] = dop
    crystals = []
    seen = set()
    for c in cs.crystal or []:
        if c is not None and c.owner not in seen:
            seen.add(c.owner)
            crystals.append({"surface": c.owner, "material": c.material, "mode": c.mode, "no": float(c.no[wl]), "ne": float(c.ne[wl]), "axis": c.axis.tolist()})
    if crystals:
        summary["crystal_modes"] = crystal_modes
        summary["wave_combinations"] = qj.get("combinations", 1)
        summary["wave_separation_mm"] = qj.get("separation_mm") if crystal_modes == "sum" else None

    def lst(a):
        return [None if not np.isfinite(v) else float(v) for v in a]

    return {
        "field": field,
        "wavelength_um": float(cs.wavelengths[wl]),
        "input": input_state,
        "grid": grid,
        "px": px.tolist(),
        "py": py.tolist(),
        "ok": jp["ok"].tolist(),
        "transmission": lst(T_in),
        "unpolarized_transmission": lst(props["transmission"]),
        "diattenuation": lst(props["diattenuation"]),
        "retardance_waves": lst(props["retardance"] / (2 * math.pi)),
        "rotation_deg": lst(np.degrees(props["rotation"])),
        "ellipse": None if el is None else {"azimuth_rad": lst(el["azimuth"]), "ellipticity_rad": lst(el["ellipticity"])},
        "summary": summary,
        "crystals": crystals,
        "jones_elements": [{"surface": i, "kind": e.kind, "angle_deg": e.angle_deg, "retardance_waves": e.retardance_waves if e.kind == "retarder" else None} for i, e in enumerate(cs.jones or []) if e is not None],
        "units": {"transmission": "power fraction", "retardance": "waves", "angles": "rad"},
        "method": "3D polarisation ray-tracing matrices (Chipman); power-normalised Fresnel / thin-film amplitudes; ideal mirrors (r_s = −1, r_p = +1)"
        + ("; retardance and rotation in the mirror-image output basis (odd number of reflections)" if jp["reflections"] % 2 else "")
        + ("; uniaxial crystals: ordinary and extraordinary waves from the continuity of tangential E and H" + (", both waves of every crystal added coherently" if crystal_modes == "sum" else ", the waves set in the prescription") if crystals else "")
        + ("; ideal polarisers / retarders" if any(e is not None for e in (cs.jones or [])) else "")
        + "; local x/y Jones bases; pupil averages and the beam's Mueller matrix by Gaussian quadrature (6 rings)",
    }
