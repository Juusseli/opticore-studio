"""Full-vector modes of fibres and waveguides with an arbitrary cross-section (photonic crystal fibres, elliptical and
stress-free polarisation-maintaining cores, rectangular guides).

Maxwell's equations for fields exp(i(omega t - beta z)) on a Yee mesh of the cross-section (step h):
Ex at (i+1/2, j), Ey at (i, j+1/2), Ez at (i, j); Hx at (i, j+1/2), Hy at (i+1/2, j), Hz at (i+1/2, j+1/2). With
H scaled by the vacuum impedance, forward differences U (E mesh -> H mesh) and backward differences V (H -> E),
eliminating Ez and Hz gives

    beta [Ex, Ey]^T = P [Hx, Hy]^T,   P = [[-Ux ez^-1 Vy / k,   k + Ux ez^-1 Vx / k],
                                         [-k - Uy ez^-1 Vy / k,  Uy ez^-1 Vx / k]]
    beta [Hx, Hy]^T = Q [Ex, Ey]^T,   Q = [[Vx Uy / k,          -k ey - Vx Ux / k],
                                         [k ex + Vy Uy / k,     -Vy Ux / k]]

so beta^2 is an eigenvalue of P Q (k = 2 pi / lambda); the modes nearest a guess are found by shift-invert Arnoldi.

* Interfaces: in a cell that an interface crosses, the permittivity is the averaged tensor
  eps = eps_par (I - n n) + eps_perp n n (eps_par the mean of eps over 64 x 64 sub-samples, eps_perp the harmonic
  mean, n the interface normal), off-diagonal terms included (Ey averaged to the Ex points and Ex to the Ey points);
  Ez sees eps_par. A staircase would leave a first-order error at curved interfaces.
* Open structures (leaky modes of photonic crystal fibres): a perfectly matched layer of complex coordinate stretch
  s = 1 - i sigma (d/w)^2 ends the domain; Im(n_eff) gives the confinement loss 20 log10(e) k Im(n_eff).
* Symmetry: the domain can be the quadrant x, y >= 0 with an electric wall (PEC: tangential E = 0) or a magnetic
  wall (PMC: tangential H = 0) on each axis. The x-polarised fundamental mode has PEC at x = 0, PMC at y = 0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import eigs

from .fibermodes import FibreError

DB_PER_NEPER = 20.0 / math.log(10.0)


@dataclass
class Shape:
    """kind: circle (x, y, r) | ellipse (x, y, rx, ry, angle_deg) | rect (x, y, w, hgt, angle_deg); index n."""

    kind: str
    x: float
    y: float
    n: float
    r: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    w: float = 0.0
    hgt: float = 0.0
    angle_deg: float = 0.0

    def _local(self, X, Y):
        c, s = math.cos(math.radians(self.angle_deg)), math.sin(math.radians(self.angle_deg))
        dx, dy = X - self.x, Y - self.y
        return c * dx + s * dy, -s * dx + c * dy, c, s

    def inside(self, X, Y):
        if self.kind == "circle":
            return (X - self.x) ** 2 + (Y - self.y) ** 2 < self.r**2
        u, v, _, _ = self._local(X, Y)
        if self.kind == "ellipse":
            return (u / self.rx) ** 2 + (v / self.ry) ** 2 < 1.0
        return (np.abs(u) < self.w / 2) & (np.abs(v) < self.hgt / 2)

    def normal(self, X, Y):
        """Unit normal of the nearest boundary (x, y components)."""
        if self.kind == "circle":
            dx, dy = X - self.x, Y - self.y
        else:
            u, v, c, s = self._local(X, Y)
            if self.kind == "ellipse":
                gu, gv = u / self.rx**2, v / self.ry**2
            else:
                along_u = (self.w / 2 - np.abs(u)) < (self.hgt / 2 - np.abs(v))
                gu, gv = np.where(along_u, np.sign(u), 0.0), np.where(along_u, 0.0, np.sign(v))
            dx, dy = c * gu - s * gv, s * gu + c * gv
        nn = np.hypot(dx, dy)
        nn = np.where(nn > 0, nn, 1.0)
        return dx / nn, dy / nn

    def extent(self) -> float:
        return {"circle": self.r, "ellipse": max(self.rx, self.ry), "rect": 0.5 * math.hypot(self.w, self.hgt)}[self.kind]


@dataclass
class CrossSection:
    """Background index and shapes, later shapes on top of earlier ones."""

    n_background: float
    shapes: list[Shape] = field(default_factory=list)

    def index(self, X, Y):
        n = np.full(np.broadcast(X, Y).shape, self.n_background, dtype=float)
        for s in self.shapes:
            n = np.where(s.inside(X, Y), s.n, n)
        return n

    def extent(self) -> float:
        return max([math.hypot(s.x, s.y) + s.extent() for s in self.shapes] + [0.0])


def hexagonal_holes(pitch: float, d: float, rings: int, n_hole: float = 1.0, missing_centre: bool = True) -> list[Shape]:
    """Air holes on a triangular lattice (pitch, hole diameter d), `rings` rings around the centre."""
    out = []
    for q in range(-rings, rings + 1):
        for r in range(-rings, rings + 1):
            s = -q - r
            if max(abs(q), abs(r), abs(s)) > rings or (missing_centre and q == 0 and r == 0):
                continue
            x = pitch * (q + r / 2.0)
            y = pitch * (r * math.sqrt(3.0) / 2.0)
            out.append(Shape("circle", x, y, n_hole, r=d / 2))
    return out


def _averaged_eps(cs: CrossSection, X, Y, h: float, comp: str, ss: int = 64):
    """Permittivity of a field component at the points (X, Y), averaged over the h x h cell (module notes). For
    comp 'x' or 'y' returns (eps_xx or eps_yy, eps_xy) of the averaged tensor eps_par (I - n n) + eps_perp n n."""
    eps0 = cs.index(X, Y) ** 2
    o = (np.arange(ss) + 0.5) / ss - 0.5
    ox, oy = np.meshgrid(o * h, o * h, indexing="ij")
    # points whose cell meets an interface: index differs somewhere on the cell's corners or centre
    test = [cs.index(X + dx, Y + dy) for dx in (-h / 2, 0, h / 2) for dy in (-h / 2, 0, h / 2)]
    mixed = np.zeros(X.shape, dtype=bool)
    for t in test:
        mixed |= t != test[4]
    if not np.any(mixed):
        return eps0 if comp == "z" else (eps0, np.zeros_like(eps0))
    xm, ym = X[mixed], Y[mixed]
    samples = cs.index(xm[:, None, None] + ox[None], ym[:, None, None] + oy[None]) ** 2
    e_par = samples.mean(axis=(1, 2))
    e_perp = 1.0 / (1.0 / samples).mean(axis=(1, 2))
    if comp == "z":
        eps = e_par
    else:
        # the normal of the shape whose boundary passes through the cell (the topmost such shape)
        nx = np.zeros(xm.shape)
        ny = np.zeros(xm.shape)
        for s in cs.shapes:
            ins = s.inside(xm[:, None, None] + ox[None], ym[:, None, None] + oy[None])
            hit = ins.any(axis=(1, 2)) & ~ins.all(axis=(1, 2))
            if np.any(hit):
                a, b = s.normal(xm[hit], ym[hit])
                nx[hit], ny[hit] = a, b
        nc = nx if comp == "x" else ny
        eps = e_par * (1.0 - nc * nc) + e_perp * nc * nc
        exy = (e_perp - e_par) * nx * ny
        out = eps0.copy()
        out[mixed] = eps
        off = np.zeros_like(eps0)
        off[mixed] = exy
        return out, off
    out = eps0.copy()
    out[mixed] = eps
    return out


def _d1(n: int, h: np.ndarray, kind: str, lo: str | None) -> sp.csr_matrix:
    """1-D difference with per-point scale 1/(s h). kind 'U' (to the half points, forward) or 'V' (to the integer
    points, backward). lo, the half-point value just outside x = 0 for V: None (zero: the domain edge), 'even'
    (f[-1] = f[0]) or 'odd' (f[-1] = -f[0]). Half-point quantities (Ex, Hy, Hz and x-derivatives of Ey, Ez) are even
    about an electric wall and odd about a magnetic wall."""
    main = np.ones(n)
    if kind == "U":
        D = sp.diags([-main, main[:-1]], [0, 1], shape=(n, n), format="lil")
    else:
        D = sp.diags([main, -main[:-1]], [0, -1], shape=(n, n), format="lil")
        if lo == "odd":
            D[0, 0] = 2.0  # f[0] - f[-1] with f[-1] = -f[0]
        elif lo == "even":
            D[0, 0] = 0.0  # f[0] - f[-1] with f[-1] = f[0]
    D = sp.diags(1.0 / h) @ D.tocsr()
    return D.tocsr()


def _a1(n: int, kind: str, lo: str | None) -> sp.csr_matrix:
    """1-D two-point average: 'U' integer -> half points ((f[i] + f[i+1]) / 2), 'V' half -> integer points
    ((f[i-1] + f[i]) / 2) with the outside value f[-1] as for _d1 (None: 0, 'even': f[0], 'odd': -f[0])."""
    main = 0.5 * np.ones(n)
    if kind == "U":
        A = sp.diags([main, main[:-1]], [0, 1], shape=(n, n), format="lil")
    else:
        A = sp.diags([main, main[:-1]], [0, -1], shape=(n, n), format="lil")
        if lo == "odd":
            A[0, 0] = 0.0
        elif lo == "even":
            A[0, 0] = 1.0
    return A.tocsr()


def solve_modes(
    cs: CrossSection,
    wavelength_um: float,
    half_width_um: float,
    h_um: float,
    n_guess: float | None = None,
    count: int = 6,
    symmetry: tuple[str, str] | None = ("pec", "pmc"),
    pml_um: float = 0.0,
    pml_sigma: float = 5.0,
):
    """Modes nearest n_guess. symmetry (x = 0 wall, y = 0 wall) on the quadrant x, y >= 0, or None for the full square
    [-W, W]^2. Returns (modes, mesh info)."""
    lam = float(wavelength_um)
    k = 2 * math.pi / lam
    h = float(h_um)
    W = float(half_width_um) + pml_um
    if symmetry is None:
        N = int(round(2 * W / h))
        x0 = -W
    else:
        N = int(round(W / h))
        x0 = 0.0
    if N < 8 or N > 1400:
        raise FibreError("The mesh must have between 8 and 1400 cells across")
    xi = x0 + np.arange(N) * h  # integer points (Ez, Ey's x, Ex's y ...)
    xh = xi + h / 2  # half points

    def stretch(pos):
        if pml_um <= 0:
            return np.ones_like(pos, dtype=complex)
        inner = W - pml_um
        d = np.clip((np.abs(pos) - inner) / pml_um, 0.0, None)
        return 1.0 - 1j * pml_sigma * d**2

    sx_i, sx_h = stretch(xi), stretch(xh)
    wall_x = symmetry[0] if symmetry else None
    wall_y = symmetry[1] if symmetry else None
    # walls on the axes. Electric wall at x = 0 (tangential E = 0): Ey vanishes on the line i = 0 (those unknowns are
    # dropped below), Ez follows; half-point quantities mirror evenly. Magnetic wall (tangential H = 0): they mirror
    # oddly. Without a wall the line x = 0 is the domain edge (zero outside).
    mirror = {"pec": "even", "pmc": "odd", None: None}
    Ux = _d1(N, sx_h * h, "U", None)
    Vx = _d1(N, sx_i * h, "V", mirror[wall_x])
    Uy = _d1(N, sx_h * h, "U", None)
    Vy = _d1(N, sx_i * h, "V", mirror[wall_y])
    I = sp.identity(N, format="csr")
    # 2-D operators on vectors ordered [i * N + j] (x index major)
    UX, VX = sp.kron(Ux, I, format="csr"), sp.kron(Vx, I, format="csr")
    UY, VY = sp.kron(I, Uy, format="csr"), sp.kron(I, Vy, format="csr")

    Xi, Yi = np.meshgrid(xi, xi, indexing="ij")
    Xh, Yh = np.meshgrid(xh, xh, indexing="ij")
    ex, exy_x = (a.ravel() for a in _averaged_eps(cs, Xh, Yi, h, "x"))  # at Ex (i+1/2, j): eps_xx, eps_xy
    ey, exy_y = (a.ravel() for a in _averaged_eps(cs, Xi, Yh, h, "y"))  # at Ey (i, j+1/2): eps_yy, eps_xy
    ez = _averaged_eps(cs, Xi, Yi, h, "z").ravel()  # Ez at (i, j)
    # off-diagonal coupling: Ey averaged to the Ex points (x: integer -> half, y: half -> integer) and Ex to the Ey
    # points (x: half -> integer, y: integer -> half), with the walls' parities
    A_y_to_x = sp.kron(_a1(N, "U", None), _a1(N, "V", mirror[wall_y]), format="csr")
    A_x_to_y = sp.kron(_a1(N, "V", mirror[wall_x]), _a1(N, "U", None), format="csr")
    Dxx = sp.diags(ex)
    Dxy = sp.diags(exy_x) @ A_y_to_x
    Dyy = sp.diags(ey)
    Dyx = sp.diags(exy_y) @ A_x_to_y
    iez = sp.diags(1.0 / ez)
    P = sp.bmat([[-(UX @ iez @ VY) / k, k * sp.identity(N * N) + (UX @ iez @ VX) / k], [-k * sp.identity(N * N) - (UY @ iez @ VY) / k, (UY @ iez @ VX) / k]], format="csr")
    # D_x = eps_xx Ex + eps_xy Ey, D_y = eps_xy Ex + eps_yy Ey on the Yee points
    Q = sp.bmat([[(VX @ UY) / k - k * Dyx, -k * Dyy - (VX @ UX) / k], [k * Dxx + (VY @ UY) / k, k * Dxy - (VY @ UX) / k]], format="csr")
    A = (P @ Q).tocsc()
    # electric walls: drop the tangential E unknowns on the wall lines (Ey on x = 0, Ex on y = 0)
    keep = np.ones(2 * N * N, dtype=bool)
    if wall_x == "pec":
        keep[N * N + np.arange(N)] = False  # Ey(i = 0, j)
    if wall_y == "pec":
        keep[np.arange(N) * N] = False  # Ex(i, j = 0)
    if not keep.all():
        A = A[keep][:, keep]
    nmax = float(max([cs.n_background] + [s.n for s in cs.shapes]))
    sigma = (k * (n_guess if n_guess is not None else nmax * 0.9999)) ** 2
    vals, vecs = eigs(A, k=min(count, A.shape[0] - 2), sigma=sigma, which="LM", tol=1e-12, maxiter=5000)
    modes = []
    for v, vec in zip(vals, vecs.T):
        full = np.zeros(2 * N * N, dtype=complex)
        full[keep] = vec
        Exf = full[: N * N].reshape(N, N)
        Eyf = full[N * N :].reshape(N, N)
        beta = np.sqrt(v)
        if beta.real < 0:
            beta = -beta
        # exp(i(omega t - beta z)) decays for Im(beta) < 0; reported as n_eff = n + i kappa with kappa > 0 for loss
        neff = np.conj(beta / k)
        modes.append({"neff": complex(neff), "loss_db_per_m": float(DB_PER_NEPER * k * neff.imag * 1e6), "_Ex": Exf, "_Ey": Eyf})
    modes.sort(key=lambda m: -m["neff"].real)
    return modes, {"x": xi, "x_half": xh, "h": h, "cells": N, "unknowns": int(keep.sum()), "eps_z": ez.reshape(N, N)}


def core_fraction(mode: dict, mesh: dict, radius: float) -> float:
    """Share of |E_t|^2 within `radius` of the origin (a crude core-localisation measure for picking modes)."""
    X, Y = np.meshgrid(mesh["x"], mesh["x"], indexing="ij")
    w = np.abs(mode["_Ex"]) ** 2 + np.abs(mode["_Ey"]) ** 2
    tot = w.sum()
    return float(w[np.hypot(X, Y) <= radius].sum() / tot) if tot > 0 else 0.0
