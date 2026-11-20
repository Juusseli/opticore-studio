"""Rigorous coupled-wave analysis of crossed gratings and metasurfaces: structures periodic in x and y.

Unit cell: a rectangle Lx × Ly (µm). Each layer is homogeneous or patterned: a background permittivity with shapes on
it, rectangles or ellipses of any size up to the period, centred anywhere in the cell and rotated by any angle (the
pattern repeats, so a shape across the cell boundary continues in the next cell). Shapes must not overlap.

Orders (p, q), p = −Mx … Mx, q = −My … My, with the grating equation k_x = k_x,in + p λ/Lx, k_y = k_y,in + q λ/Ly
(normalised by k0). The field equations, layer modes, scattering matrices and efficiencies are those of the 1D solver
(wave/rcwa.py, R. C. Rumpf, PIER B 35, 241 (2011)) with 2D convolution matrices.

Convention: the physics' ε(x, y) = (n + iκ)² has the Fourier coefficients c_pq in the e^{+j(p Gx x + q Gy y)} expansion.
With the orders labelled physically (k_x = k_x,in + p Gx), the solver's convolution matrices in exp(+j w t) are the
conjugates of the physics' Toeplitz matrices T[(p,q),(p′,q′)] = c_{p−p′, q−q′}.

Fourier factorisation (L. Li, JOSA A 14, 2758 (1997), "fast Fourier factorisation"):
* E_z, tangential to every wall of a layer (walls are parallel to z): Laurent's rule, [ε];
* E_x: along each line y = const the inverse rule in x (the line crosses walls normal to x), then Laurent's rule in y:
  Exx = ⌈⌊ε⌋_x⌉_y with ⌊ε⌋_x = T_x(1/ε)⁻¹;
* E_y likewise with x and y exchanged.
This is the correct rule for cells made of axis-aligned rectangles (the cross-sections are piecewise constant). Curved
or rotated boundaries enter the inner inverse rule as a fine staircase of line cross-sections (`STAIRS` per shape); the
Laurent matrices use the exact analytic coefficients of the shapes.

A structure invariant in y (shapes spanning the period Ly) reduces exactly to the 1D solver: the orders q decouple,
Exx = I ⊗ ⌊ε⌋_x and Eyy = [ε]_x ⊗ I. Validated in tests/test_rcwa2d.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.linalg import lu_factor, lu_solve
from scipy.special import j1

from .rcwa import RcwaError, _coeffs, _star, GratingLayer

MAX_ORDERS = 961  # (2Mx+1)(2My+1), e.g. Mx = My = 15: about 25 s per run on one core
STAIRS = 64  # line cross-sections per curved or rotated shape in the inner inverse rule
RASTER = 256  # pixels per side for the overlap check


@dataclass
class Shape:
    """kind 'rectangle' (a, b the side lengths) or 'ellipse' (a, b the diameters) along its own axes, rotated by
    angle_deg counter-clockwise; centre (cx, cy) in µm in the cell; eps its permittivity (physics convention)."""

    kind: str
    cx: float
    cy: float
    a: float
    b: float
    eps: complex
    angle_deg: float = 0.0

    @property
    def axis_aligned_rect(self) -> bool:
        return self.kind == "rectangle" and abs(math.remainder(self.angle_deg, 90.0)) < 1e-12

    def half_extent(self) -> tuple[float, float]:
        """Half the bounding box along x and y."""
        al = math.radians(self.angle_deg)
        c, s = abs(math.cos(al)), abs(math.sin(al))
        if self.kind == "rectangle":
            return 0.5 * (self.a * c + self.b * s), 0.5 * (self.a * s + self.b * c)
        ha, hb = self.a / 2, self.b / 2
        return math.hypot(ha * c, hb * s), math.hypot(ha * s, hb * c)


@dataclass
class PatternLayer:
    thickness: float
    eps_bg: complex
    shapes: list[Shape] = field(default_factory=list)

    @property
    def uniform(self) -> bool:
        return not self.shapes


def from_1d(layer: GratingLayer, Lx: float, Ly: float) -> PatternLayer:
    """A 1D layer (segments in fractions of the period along x) as stripes spanning the period Ly."""
    shapes = [Shape("rectangle", 0.5 * (x0 + x1) * Lx, 0.5 * Ly, (x1 - x0) * Lx, Ly, e) for x0, x1, e in layer.segments]
    return PatternLayer(layer.thickness, layer.eps_bg, shapes)


def _shape_ft(sh: Shape, gx: np.ndarray, gy: np.ndarray) -> np.ndarray:
    """∫∫_shape e^{−j(gx x + gy y)} dx dy (gx, gy in rad/µm, arrays of one shape)."""
    al = math.radians(sh.angle_deg)
    u = gx * math.cos(al) + gy * math.sin(al)  # the wave vector in the shape's own axes
    v = -gx * math.sin(al) + gy * math.cos(al)
    ph = np.exp(-1j * (gx * sh.cx + gy * sh.cy))
    if sh.kind == "rectangle":
        return ph * sh.a * sh.b * np.sinc(u * sh.a / (2 * math.pi)) * np.sinc(v * sh.b / (2 * math.pi))
    rho = np.hypot(u * sh.a / 2, v * sh.b / 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        g = np.where(rho > 1e-12, 2 * j1(rho) / np.where(rho > 1e-12, rho, 1.0), 1.0)
    return ph * (math.pi * sh.a * sh.b / 4) * g


def coeffs2d(layer: PatternLayer, inv: bool, Mx: int, My: int, Lx: float, Ly: float) -> np.ndarray:
    """Fourier coefficients c[p, q] (p = −Mx … Mx, q = −My … My as indices p + Mx, q + My) of ε (or 1/ε with inv)."""
    f = (lambda e: 1.0 / e) if inv else (lambda e: e)
    p = np.arange(-Mx, Mx + 1)[:, None]
    q = np.arange(-My, My + 1)[None, :]
    gx, gy = 2 * math.pi * p / Lx + 0 * q, 2 * math.pi * q / Ly + 0 * p
    c = np.zeros(gx.shape, complex)
    c[Mx, My] = f(layer.eps_bg)
    for sh in layer.shapes:
        c += (f(sh.eps) - f(layer.eps_bg)) * _shape_ft(sh, gx, gy) / (Lx * Ly)
    return c


def _interval(sh: Shape, axis: int, s: float) -> tuple[float, float] | None:
    """The (unwrapped) interval of the shape on the line {axis-coordinate free, other coordinate = s}: axis 0 a line
    y = s (interval in x), axis 1 a line x = s (interval in y)."""
    al = math.radians(sh.angle_deg)
    c, si = math.cos(al), math.sin(al)
    # point on the line: r(t) = (t, s) (axis 0) or (s, t) (axis 1); local coordinates u = A t + B, v = C t + D
    if axis == 0:
        A, B = c, (s - sh.cy) * si - sh.cx * c
        C, D = -si, (s - sh.cy) * c + sh.cx * si
    else:
        A, B = si, (s - sh.cx) * c - sh.cy * si
        C, D = c, -(s - sh.cx) * si - sh.cy * c
    ha, hb = sh.a / 2, sh.b / 2
    if sh.kind == "rectangle":
        lo, hi = -math.inf, math.inf
        for k, d, h in ((A, B, ha), (C, D, hb)):
            if abs(k) < 1e-15:
                if abs(d) >= h:
                    return None
                continue
            t1, t2 = (-h - d) / k, (h - d) / k
            lo, hi = max(lo, min(t1, t2)), min(hi, max(t1, t2))
        return (lo, hi) if hi > lo else None
    # ellipse: (A t + B)²/ha² + (C t + D)²/hb² <= 1
    a2 = A * A / ha**2 + C * C / hb**2
    b2 = 2 * (A * B / ha**2 + C * D / hb**2)
    c2 = B * B / ha**2 + D * D / hb**2 - 1
    disc = b2 * b2 - 4 * a2 * c2
    if disc <= 0:
        return None
    r = math.sqrt(disc)
    return (-b2 - r) / (2 * a2), (-b2 + r) / (2 * a2)


def line_segments(layer: PatternLayer, axis: int, s: float, Lx: float, Ly: float) -> list[tuple[float, float, complex]]:
    """The layer on one line as segments (x0, x1, eps) in fractions of that line's period (axis 0: along x at y = s)."""
    L_line, L_other = (Lx, Ly) if axis == 0 else (Ly, Lx)
    out = []
    for sh in layer.shapes:
        for k in (-1, 0, 1):  # the shape's periodic images across the line's normal direction
            dx, dy = (0.0, k * Ly) if axis == 0 else (k * Lx, 0.0)
            img = Shape(sh.kind, sh.cx + dx, sh.cy + dy, sh.a, sh.b, sh.eps, sh.angle_deg)
            iv = _interval(img, axis, s)
            if iv is None:
                continue
            t0, t1 = iv
            t1 = min(t1, t0 + L_line)  # a shape spans at most one period
            # wrap into [0, L_line)
            o = math.floor(t0 / L_line) * L_line
            a, b = t0 - o, t1 - o
            if b <= L_line:
                out.append((a / L_line, b / L_line, sh.eps))
            else:
                out.append((a / L_line, 1.0, sh.eps))
                out.append((0.0, b / L_line - 1.0, sh.eps))
    return [(a, b, e) for a, b, e in out if b - a > 1e-14]


def _breaks(layer: PatternLayer, axis: int, Lx: float, Ly: float) -> np.ndarray:
    """Breakpoints along the line's normal direction (axis 0: in y) between which the cross-sections are constant
    (axis-aligned rectangles: exact) or nearly so (a staircase of STAIRS steps over other shapes)."""
    L = Ly if axis == 0 else Lx
    pts = [0.0, L]
    for sh in layer.shapes:
        hx, hy = sh.half_extent()
        c, h = (sh.cy, hy) if axis == 0 else (sh.cx, hx)
        if sh.axis_aligned_rect:
            ts = [c - h, c + h]
        else:
            ts = list(np.linspace(c - h, c + h, STAIRS + 1))
        pts += [t % L for t in ts]
    b = np.unique(np.round(np.array(pts) / L, 13)) * L
    return b


def _inverse_rule_matrix(layer: PatternLayer, axis: int, Mx: int, My: int, Lx: float, Ly: float) -> np.ndarray:
    """Li's ⌈⌊ε⌋_a⌉_b in the physics convention, as a matrix over the flattened orders (p major)."""
    Ma, Mb = (Mx, My) if axis == 0 else (My, Mx)
    Lb = Ly if axis == 0 else Lx
    na = 2 * Ma + 1
    br = _breaks(layer, axis, Lx, Ly)
    k = np.arange(-2 * Mb, 2 * Mb + 1)
    Ahat = np.zeros((len(k), na, na), complex)
    ia = np.arange(na)
    for s0, s1 in zip(br[:-1], br[1:]):
        if s1 - s0 < 1e-14 * Lb:
            continue
        segs = line_segments(layer, axis, 0.5 * (s0 + s1), Lx, Ly)
        g = GratingLayer(0.0, layer.eps_bg, segs)
        ci = _coeffs(g, True, 2 * Ma)
        A = np.linalg.inv(ci[(ia[:, None] - ia[None, :]) + 2 * Ma])
        with np.errstate(divide="ignore", invalid="ignore"):
            w = (np.exp(-2j * np.pi * k * s0 / Lb) - np.exp(-2j * np.pi * k * s1 / Lb)) / (2j * np.pi * k)
        w[k == 0] = (s1 - s0) / Lb
        Ahat += w[:, None, None] * A[None, :, :]
    nb = 2 * Mb + 1
    ib = np.arange(nb)
    blocks = Ahat[(ib[:, None] - ib[None, :]) + 2 * Mb]  # [b, b', a, a']
    if axis == 0:  # flattened index (p, q) p major: rows (p, q), columns (p', q'); a = p, b = q
        return blocks.transpose(2, 0, 3, 1).reshape(na * nb, na * nb)
    return blocks.transpose(0, 2, 1, 3).reshape(na * nb, na * nb)  # a = q, b = p


def _toeplitz2d(c: np.ndarray, P: np.ndarray, Q: np.ndarray, Mx: int, My: int) -> np.ndarray:
    """T[i, j] = c[P_i − P_j, Q_i − Q_j] with c indexed from −2Mx, −2My."""
    return c[(P[:, None] - P[None, :]) + 2 * Mx, (Q[:, None] - Q[None, :]) + 2 * My]


def check_shapes(layers: list[PatternLayer], Lx: float, Ly: float):
    """Raster test: no two shapes overlap, and no shape overlaps its own periodic image."""
    xs = (np.arange(RASTER) + 0.5) / RASTER * Lx
    ys = (np.arange(RASTER) + 0.5) / RASTER * Ly
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    for n, L in enumerate(layers):
        if not L.thickness >= 0:
            raise RcwaError(f"Layer {n + 1}: the thickness must be zero or positive")
        cover = np.zeros(X.shape, int)
        for sh in L.shapes:
            if not (sh.a > 0 and sh.b > 0):
                raise RcwaError(f"Layer {n + 1}: shape sizes must be positive")
            if sh.kind not in ("rectangle", "ellipse"):
                raise RcwaError(f"Layer {n + 1}: unknown shape '{sh.kind}'")
            al = math.radians(sh.angle_deg)
            for i in (-1, 0, 1):
                for j in (-1, 0, 1):
                    dx, dy = X - sh.cx - i * Lx, Y - sh.cy - j * Ly
                    u = dx * math.cos(al) + dy * math.sin(al)
                    v = -dx * math.sin(al) + dy * math.cos(al)
                    tol = 1e-9 * max(Lx, Ly)
                    if sh.kind == "rectangle":
                        inside = (np.abs(u) < sh.a / 2 - tol) & (np.abs(v) < sh.b / 2 - tol)
                    else:
                        inside = (u / (sh.a / 2)) ** 2 + (v / (sh.b / 2)) ** 2 < 1 - 1e-9
                    cover += inside
        if cover.max() > 1:
            raise RcwaError(f"Layer {n + 1}: shapes overlap (each other or their copies in the neighbouring cells)")


# ------------------------------------------------------------------ 2 x 2 blocks of diagonal matrices
# The gap, the half-spaces and uniform layers have matrices made of 2 x 2 blocks of diagonal N x N matrices, stored as
# arrays (2, 2, N); their algebra costs O(N).
def _bmul(A, B):
    return np.einsum("ikn,kjn->ijn", A, B)


def _binv(A):
    a, b, c, d = A[0, 0], A[0, 1], A[1, 0], A[1, 1]
    det = a * d - b * c
    return np.array([[d, -b], [-c, a]]) / det


def _beye(N):
    o, z = np.ones(N, complex), np.zeros(N, complex)
    return np.array([[o, z], [z, o]])


def _bdense(A):
    N = A.shape[2]
    out = np.zeros((2 * N, 2 * N), complex)
    for i in (0, 1):
        for j in (0, 1):
            out[i * N:(i + 1) * N, j * N:(j + 1) * N] = np.diag(A[i, j])
    return out


def _bleft(A, M):
    """A (blocks) @ M (dense with 2N rows, or a vector)."""
    N = A.shape[2]
    M0, M1 = M[:N], M[N:]
    if M.ndim == 1:
        return np.concatenate([A[0, 0] * M0 + A[0, 1] * M1, A[1, 0] * M0 + A[1, 1] * M1])
    return np.vstack([A[0, 0][:, None] * M0 + A[0, 1][:, None] * M1, A[1, 0][:, None] * M0 + A[1, 1][:, None] * M1])


def _bright(M, A):
    """M (dense with 2N columns) @ A (blocks)."""
    N = A.shape[2]
    M0, M1 = M[:, :N], M[:, N:]
    return np.hstack([M0 * A[0, 0][None, :] + M1 * A[1, 0][None, :], M0 * A[0, 1][None, :] + M1 * A[1, 1][None, :]])


def _bstar(SA, SB):
    """Redheffer star product of block scattering matrices."""
    A11, A12, A21, A22 = SA
    B11, B12, B21, B22 = SB
    I = _beye(A11.shape[2])
    D = _bmul(A12, _binv(I - _bmul(B11, A22)))
    F = _bmul(B21, _binv(I - _bmul(A22, B11)))
    return (A11 + _bmul(_bmul(D, B11), A21), _bmul(D, B12), _bmul(F, A21), B22 + _bmul(_bmul(F, A22), B12))


def _layer_s(A, B, x):
    """Rumpf's symmetric layer S-matrix (S11 = S22, S12 = S21) from A, B and the propagation factors x (dense)."""
    Ai = np.linalg.inv(A)
    XB = x[:, None] * B
    XBAi = XB @ Ai
    lu = lu_factor(A - XBAi @ XB)
    S11 = lu_solve(lu, XBAi @ (x[:, None] * A) - B)
    S12 = lu_solve(lu, x[:, None] * (A - B @ Ai @ B))
    return S11, S12


def solve2d(Lx: float, Ly: float, layers: list[PatternLayer], eps_in: float, eps_out: complex, wavelength_um: float,
            theta_deg: float = 0.0, phi_deg: float = 0.0, pol="TE", Mx: int = 5, My: int = 5, factorisation: str = "li") -> dict:
    """Diffraction efficiencies of the orders (p, q). pol: TE, TM or a pair (a_te, a_tm) on the incident wave's TE/TM
    unit vectors. factorisation 'li' (default) or 'laurent' (for comparison). Arrays are shaped (2Mx+1, 2My+1).

    The gap, half-spaces and uniform layers are kept as 2 x 2 blocks of diagonals; patterned layers are dense. Only the
    response to the one incident wave is assembled: the reference and substrate sides are joined by vector solves."""
    if not (Lx > 0 and Ly > 0 and wavelength_um > 0):
        raise RcwaError("The periods and the wavelength must be positive")
    if not (np.isreal(eps_in) and float(np.real(eps_in)) > 0):
        raise RcwaError("The incident medium must be lossless")
    Mx, My = int(Mx), int(My)
    if not (0 <= Mx <= 40 and 0 <= My <= 40):
        raise RcwaError("Harmonics must be between 0 and 40 in each direction")
    check_shapes(layers, Lx, Ly)
    nx, ny = 2 * Mx + 1, 2 * My + 1
    N = nx * ny
    if N > MAX_ORDERS:
        raise RcwaError(f"{N} orders: at most {MAX_ORDERS} ((2Mx+1)(2My+1)); lower the harmonics")
    lam, k0 = wavelength_um, 2 * math.pi / wavelength_um
    n_in = math.sqrt(float(np.real(eps_in)))
    th, ph = math.radians(theta_deg), math.radians(phi_deg)
    kin = n_in * np.array([math.sin(th) * math.cos(ph), math.sin(th) * math.sin(ph), math.cos(th)])
    Pg, Qg = np.meshgrid(np.arange(-Mx, Mx + 1), np.arange(-My, My + 1), indexing="ij")
    P, Q = Pg.ravel(), Qg.ravel()
    kx = (kin[0] + P * lam / Lx).astype(complex)
    ky = (kin[1] + Q * lam / Ly).astype(complex)
    conj = np.conj
    one = np.ones(N, complex)
    Ib = _beye(N)

    # gap with k_z = 1 in every order: W0 = I, V0 = Q0 / j
    V0 = np.array([[kx * ky, one + ky * ky], [-(one + kx * kx), -ky * kx]]) / 1j
    V0i = _binv(V0)

    def half(eps: complex):
        """V (blocks) and k_z of a homogeneous medium (W = I)."""
        e = conj(eps)
        kz = conj(np.sqrt(conj(e) - kx * kx - ky * ky + 0j))
        Qh = np.array([[kx * ky, e - kx * kx], [ky * ky - e, -ky * kx]])
        return Qh / (1j * kz), kz

    Vr, kz_r = half(eps_in)
    G = _bmul(V0i, Vr)  # A = W0⁻¹ W + V0⁻¹ V with W = W0 = I
    A, B = Ib + G, Ib - G
    Ai = _binv(A)
    S_ref = (-_bmul(Ai, B), 2 * Ai, 0.5 * (A - _bmul(_bmul(B, Ai), B)), _bmul(B, Ai))
    Vt, kz_t = half(eps_out)
    G = _bmul(V0i, Vt)
    A, B = Ib + G, Ib - G
    Ai = _binv(A)
    S_trn = (_bmul(B, Ai), 0.5 * (A - _bmul(_bmul(B, Ai), B)), 2 * Ai, -_bmul(Ai, B))

    # the device: patterned layers dense; uniform ones as blocks until a dense layer has come
    dev = None
    dense = False
    for L in layers:
        if L.thickness == 0:
            continue
        if L.uniform:
            Vh, kz = half(L.eps_bg)
            G = _bmul(_binv(Vh), V0)  # A = W⁻¹ W0 + V⁻¹ V0 with W = I
            Ab, Bb = Ib + G, Ib - G
            xb = np.exp(-1j * kz * k0 * L.thickness)
            Xb = np.array([[xb, 0 * xb], [0 * xb, xb]])
            Aib = _binv(Ab)
            XBAi = _bmul(_bmul(Xb, Bb), Aib)
            Db = _binv(Ab - _bmul(_bmul(XBAi, Xb), Bb))
            S11 = _bmul(Db, _bmul(_bmul(XBAi, Xb), Ab) - Bb)
            S12 = _bmul(Db, _bmul(Xb, Ab - _bmul(_bmul(Bb, Aib), Bb)))
            Sl = (S11, S12, S12, S11)
            if dev is None:
                dev = Sl
            elif not dense:
                dev = _bstar(dev, Sl)
            else:
                dev = _star(dev, tuple(_bdense(m) for m in Sl))
            continue
        Ezz = conj(_toeplitz2d(coeffs2d(L, False, 2 * Mx, 2 * My, Lx, Ly), P, Q, Mx, My))
        Ezi = np.linalg.inv(Ezz)
        if factorisation == "laurent":
            Exx = Eyy = Ezz
        else:
            Exx = conj(_inverse_rule_matrix(L, 0, Mx, My, Lx, Ly))
            Eyy = conj(_inverse_rule_matrix(L, 1, Mx, My, Lx, Ly))
        I = np.eye(N)

        def kek(a, b):
            return a[:, None] * Ezi * b[None, :]  # diag(a) Ezz⁻¹ diag(b)

        Pm = np.block([[kek(kx, ky), I - kek(kx, kx)], [kek(ky, ky) - I, -kek(ky, kx)]])
        Qm = np.block([[np.diag(kx * ky), Eyy - np.diag(kx * kx)], [np.diag(ky * ky) - Exx, -np.diag(ky * kx)]])
        l2, W = np.linalg.eig(Pm @ Qm)
        lam_ = np.sqrt(l2 + 0j)
        V = (Qm @ W) / lam_[None, :]
        Wi, Vi = np.linalg.inv(W), np.linalg.inv(V)
        G = _bright(Vi, V0)
        S11, S12 = _layer_s(Wi + G, Wi - G, np.exp(-lam_ * k0 * L.thickness))
        Sl = (S11, S12, S12, S11)
        if dev is None:
            dev = Sl
        elif not dense:
            dev = _star(tuple(_bdense(m) for m in dev), Sl)
        else:
            dev = _star(dev, Sl)
        dense = True

    # source: unit polarisation vector of the incident plane wave (TE along z x k, TM = k x TE)
    kh = kin / n_in
    if abs(kh[0]) < 1e-12 and abs(kh[1]) < 1e-12:
        a_te = np.array([0.0, 1.0, 0.0])
    else:
        a_te = np.cross([0.0, 0.0, 1.0], kh)
        a_te /= np.linalg.norm(a_te)
    a_tm = np.cross(kh, a_te)
    a_tm /= np.linalg.norm(a_tm)
    if isinstance(pol, str):
        p_te, p_tm = {"TE": (1.0, 0.0), "TM": (0.0, 1.0)}[pol.upper()]
    else:
        p_te, p_tm = pol
    Pv = p_te * a_te + p_tm * a_tm
    Pv = Pv / np.linalg.norm(Pv)
    i0 = Mx * ny + My
    v = np.zeros(2 * N, complex)
    v[i0], v[N + i0] = Pv[0], Pv[1]

    R11, R12, R21, R22 = S_ref
    T11, T12, T21, T22 = S_trn
    if not dense:
        tot = S_ref if dev is None else _bstar(S_ref, dev)
        tot = _bstar(tot, S_trn)
        r = _bleft(tot[0], v)
        t = _bleft(tot[2], v)
    else:
        D11, D12, D21, D22 = dev
        # H = S_ref * dev (only what the next product needs), then (H * S_trn) applied to v
        u = _bleft(R21, v)
        lu1 = lu_factor(np.eye(2 * N) - _bleft(R22, D11))
        y = lu_solve(lu1, u)
        H21v = D21 @ y
        H11v = _bleft(R11, v) + _bleft(R12, D11 @ y)
        H22 = D22 + D21 @ lu_solve(lu1, _bleft(R22, D12))
        lu2 = lu_factor(np.eye(2 * N) - _bright(H22, T11))
        w = lu_solve(lu2, H21v)
        t = _bleft(T21, w)
        z = D12 @ _bleft(T11, w)
        r = H11v + _bleft(R12, z + D11 @ lu_solve(lu1, _bleft(R22, z)))
    rx, ry = r[:N], r[N:]
    tx, ty = t[:N], t[N:]
    kz_ref = -kz_r
    with np.errstate(divide="ignore", invalid="ignore"):
        rz = -(kx * rx + ky * ry) / kz_ref
        tz = -(kx * tx + ky * ty) / kz_t
    kz_in = kin[2]
    R = np.real(-kz_ref / kz_in) * (np.abs(rx) ** 2 + np.abs(ry) ** 2 + np.abs(rz) ** 2)
    T = np.real(kz_t / kz_in) * (np.abs(tx) ** 2 + np.abs(ty) ** 2 + np.abs(tz) ** 2)
    R = np.where(np.isfinite(R), R, 0.0)
    T = np.where(np.isfinite(T), T, 0.0)
    prop_r = np.real(kz_r) > 1e-12
    prop_t = np.real(kz_t) > 1e-12 if abs(np.imag(eps_out)) < 1e-15 else np.zeros(N, bool)
    shp = (nx, ny)
    return {"p": Pg, "q": Qg, "kx": kx.real.reshape(shp), "ky": ky.real.reshape(shp),
            "R": np.where(prop_r, R, 0.0).reshape(shp), "T": np.where(prop_t, T, 0.0).reshape(shp),
            "r": tuple(a.reshape(shp) for a in (rx, ry, rz)), "t": tuple(a.reshape(shp) for a in (tx, ty, tz)),
            "kz_ref": kz_r.reshape(shp), "kz_trn": kz_t.reshape(shp),
            "propagating_r": prop_r.reshape(shp), "propagating_t": prop_t.reshape(shp), "kin": kin}
