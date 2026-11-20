"""2D finite-difference time-domain (FDTD) solver of Maxwell's equations.

The structure is invariant along x; the computational plane is (z, y): z horizontal (the
propagation direction of the source), y vertical. Lengths in micrometres, time in units of
length / c (epsilon0 = mu0 = c = 1, H scaled by the vacuum impedance). Non-magnetic media.

Polarisations
    s (TE: E perpendicular to the plane):  Ex, Hy, Hz
        dHy/dt = -dEx/dz,  dHz/dt = dEx/dy,  eps dEx/dt = dHz/dy - dHy/dz - sigma Ex
    p (TM: H perpendicular to the plane):  Hx, Ey, Ez
        dHx/dt = dEy/dz - dEz/dy,  eps dEy/dt = dHx/dz - sigma Ey,  eps dEz/dt = -dHx/dy - sigma Ez

Yee staggering in space and leapfrog in time (second order); Courant number 0.5 (< 1/sqrt 2).
Boundaries: convolutional PML (stretched coordinates, Roden & Gedney 2000; polynomial grading
m = 3, sigma_max = 0.8 (m + 1) / dx, alpha for the evanescent tail) on the z ends and, unless
y is periodic, on the y ends.

Materials at the source wavelength: eps = (n + i k)^2, averaged over 4 x 4 sub-cells of each
cell (shapes: rectangles, circles, polygons; later shapes override earlier ones).
* Re eps >= 1: a dielectric with the conductivity sigma = omega Im(eps) = 2 n k omega.
* Re eps < 1 (metals, plasmas, and the boundary cells of metal shapes): eps_inf = 1 plus a
  Drude polarisation current J (auxiliary differential equation)
      dJ/dt + gamma J = wp^2 E,    dE/dt = curl H - J,
  discretised centrally: J at half steps, (J+ - J-)/dt + gamma (J+ + J-)/2 = wp^2 E^n. In the
  discrete steady state at the source frequency this medium has
      eps(omega) = 1 - wp^2 / (W^2 + i W gamma cos(omega dt / 2)),  W = 2 sin(omega dt / 2) / dt,
  and wp, gamma are chosen per cell so that it equals (n + i k)^2 exactly (Drude-Lorentz data
  of a material reduce to their eps at that frequency, since the run is monochromatic). The
  dispersion of the time stepping therefore adds no error to the metal; the error left is the
  Yee grid's, which needs cells small against the skin depth lambda / (4 pi k).

Source: a soft current sheet at z_src (Jx for s, an equivalent magnetic sheet Mx for p) with
the complex profile of a plane wave (periodic y), a 2D Gaussian beam (waist w0 at z_focus,
tilt angle), the fundamental guided mode of a symmetric slab waveguide (see slab_mode) or a
surface plasmon polariton (p only) on the interface y = spp_y between the medium below and
the medium above, both read from the structure at the source (see spp_mode), switched on
smoothly over a few periods; the field radiates both ways, the backward half is absorbed by
the PML behind the source.

Guided sources (mode, spp) also give the propagation constant along z: a least-squares fit of
log of the field (Ex for s, Hx for p) on the source's axis line (spp: 20 % of the decay length
above the interface) between the source and the transmission monitor, beta = n_eff k0 with
the attenuation 2 Im beta (power, 1/um).

Results (single-frequency DFTs over the last periods once the transients have passed): complex
field maps; the time-averaged Poynting flux S_z = 1/2 Re(E x H*)_z through monitor lines; with a
reference run without the structure, reflectance R = -flux(total - incident) / flux(incident) at
the reflection monitor, transmittance T = flux / flux(incident) at the transmission monitor and
absorption 1 - R - T.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np

COURANT = 0.5
MAX_CELLS = 2_000_000
MAX_STEPS = 60_000


class FdtdError(ValueError):
    pass


class Cancelled(Exception):
    pass


@dataclass
class Shape:
    kind: str  # rectangle | circle | polygon
    n: float
    k: float = 0.0
    z0: float = 0.0
    z1: float = 0.0
    y0: float = 0.0
    y1: float = 0.0
    zc: float = 0.0
    yc: float = 0.0
    r: float = 0.0
    points: list = field(default_factory=list)
    name: str = ""

    def inside(self, Z: np.ndarray, Y: np.ndarray) -> np.ndarray:
        if self.kind == "rectangle":
            return (Z >= min(self.z0, self.z1)) & (Z <= max(self.z0, self.z1)) & (Y >= min(self.y0, self.y1)) & (Y <= max(self.y0, self.y1))
        if self.kind == "circle":
            return (Z - self.zc) ** 2 + (Y - self.yc) ** 2 <= self.r * self.r
        raise FdtdError(f"Unknown shape '{self.kind}'")


def _poly_inside(pts: np.ndarray, Z: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Even-odd rule point-in-polygon, vectorised over the grid."""
    inside = np.zeros(Z.shape, bool)
    n = len(pts)
    for i in range(n):
        z1, y1 = pts[i]
        z2, y2 = pts[(i + 1) % n]
        cond = (y1 > Y) != (y2 > Y)
        with np.errstate(divide="ignore", invalid="ignore"):
            zc = (z2 - z1) * (Y - y1) / (y2 - y1) + z1
        inside ^= cond & (Z < zc)
    return inside


@dataclass
class Spec:
    wavelength: float  # um (vacuum)
    size_z: float  # um, without PML
    size_y: float
    polarization: str = "s"
    n_background: float = 1.0
    shapes: list[Shape] = field(default_factory=list)
    source: str = "plane"  # plane | gaussian
    waist: float = 2.0
    focus_z: float = 0.0  # um, waist position along z (absolute)
    focus_y: float = 0.0
    tilt_deg: float = 0.0
    z_source: float | None = None
    z_reflection: float | None = None
    z_transmission: float | None = None
    periodic_y: bool = True
    ppw: float = 30.0  # points per wavelength in the densest medium
    pml_cells: int = 20
    periods_avg: int = 6
    reference: bool = True
    map_cells: int = 240
    # structure of the reference run (None: none; e.g. an endless fibre for the facet reflectance)
    reference_shapes: list[Shape] | None = None
    # source = "mode": the guided mode of a symmetric slab waveguide (core half-width, indices, centre)
    mode_half_width: float = 1.0
    mode_n_core: float = 1.46
    mode_n_clad: float = 1.45
    mode_center_y: float = 0.0
    # source = "spp": the interface between the metal below and the dielectric above (y)
    spp_y: float = 0.0
    # "planar": 2D (x invariant); "axisymmetric": rotationally symmetric 3D about the z axis, y is
    # the radius (fdtd_bor.py; size_y is then the domain diameter)
    geometry: str = "planar"


def check_size(sp: Spec) -> None:
    """Raise FdtdError for a domain beyond the cell limit (before a job is queued)."""
    if sp.geometry == "axisymmetric":
        from .fdtd_bor import bor_dims

        bor_dims(sp)
    else:
        Grid(sp)


class Grid:
    def __init__(self, sp: Spec):
        self.sp = sp
        n_max = max([sp.n_background] + [abs(complex(s.n, s.k)) for s in sp.shapes + (sp.reference_shapes or [])])
        self.dx = sp.wavelength / (n_max * sp.ppw)
        dx = self.dx
        self.P = int(sp.pml_cells)
        self.Nz = int(round(sp.size_z / dx)) + 2 * self.P
        self.Py = 0 if sp.periodic_y else self.P
        self.Ny = max(int(round(sp.size_y / dx)), 2) + 2 * self.Py
        if self.Nz * self.Ny > MAX_CELLS:
            raise FdtdError(f"{self.Nz} x {self.Ny} cells exceed the limit of {MAX_CELLS}: reduce the domain or the points per wavelength")
        self.z = (np.arange(self.Nz) - self.P) * dx  # E nodes; the physical domain is [0, size_z]
        self.y = (np.arange(self.Ny) - self.Py) * dx - sp.size_y / 2 + 0.5 * dx
        self.dt = COURANT * dx
        self.omega = 2 * math.pi / sp.wavelength

    def eps_sigma(self, with_shapes: bool | list = True, sub: int = 4, shift: tuple[float, float] = (0.0, 0.0), along: str | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Permittivity and conductivity (Re eps, omega Im eps) averaged over the cell centred on each node, the nodes
        shifted by `shift` = (dy, dz) cells (staggered field components). The sub x sub sub-cells are painted with the
        shapes in order (later ones win). `along` = "y" or "z": the field component along that axis, whose cell mean is
        harmonic along it and arithmetic across it (exact for layers normal to that axis, where the component is normal
        and D is continuous, and for layers along it); None: arithmetic (Ex, tangential to every wall)."""
        sp = self.sp
        bg = complex(sp.n_background**2)
        shapes = with_shapes if isinstance(with_shapes, list) else (sp.shapes if with_shapes else [])
        if not shapes:
            return np.full((self.Ny, self.Nz), bg.real), np.zeros((self.Ny, self.Nz))
        off = (np.arange(sub) + 0.5) / sub - 0.5
        Z0, Y0 = np.meshgrid(self.z + shift[1] * self.dx, self.y + shift[0] * self.dx)
        values = [complex(s.n, s.k) ** 2 for s in shapes]
        acc = np.zeros((self.Ny, self.Nz), complex)
        for a in off:  # across the component
            inner = np.zeros_like(acc)
            for b in off:  # along it
                oy, oz = (b, a) if along == "y" else (a, b)
                Z, Y = Z0 + oz * self.dx, Y0 + oy * self.dx
                e = np.full(Z.shape, bg)
                for s, v in zip(shapes, values):
                    m = _poly_inside(np.asarray(s.points, float), Z, Y) if s.kind == "polygon" else s.inside(Z, Y)
                    e[m] = v
                inner += 1.0 / e if along else e
            acc += sub / inner if along else inner / sub
        epsc = acc / sub
        return epsc.real, epsc.imag * self.omega


def _pml_profiles(N: int, P: int, dx: float, dt: float, periodic: bool = False):
    """CPML coefficients (b, a) at integer and half-integer nodes along one axis."""
    m = 3
    smax = 0.8 * (m + 1) / dx
    amax = 0.05

    def prof(pos):  # pos: node index (may be half-integer)
        d = np.zeros_like(pos)
        if P > 0 and not periodic:
            left = (P - pos) / P
            right = (pos - (N - 1 - P)) / P
            d = np.clip(np.maximum(left, right), 0, 1)
        sigma = smax * d**m
        alpha = amax * (1 - d)
        b = np.exp(-(sigma + alpha) * dt)
        with np.errstate(invalid="ignore", divide="ignore"):
            a = np.where(sigma > 0, sigma / (sigma + alpha) * (b - 1), 0.0)
        return b, a, d > 0

    i = np.arange(N, dtype=float)
    return prof(i), prof(i + 0.5)


def _medium(eps: np.ndarray, sig: np.ndarray, dt: float, dx: float, omega: float):
    """Update coefficients (ca, cb with 1/dx) of one E component, and the Drude current of the cells with Re eps < 1:
    (flat indices, kj, bj) with J+ = kj J- + bj E^n, fitted so that the discrete medium has eps + i sig / omega at omega."""
    dis = eps < 1.0
    e_hi = np.where(dis, 1.0, eps)
    s_hi = np.where(dis, 0.0, sig)
    ca = ((1 - s_hi * dt / (2 * e_hi)) / (1 + s_hi * dt / (2 * e_hi))).astype(np.float32)
    cb = ((dt / e_hi) / (1 + s_hi * dt / (2 * e_hi)) / dx).astype(np.float32)
    if not dis.any():
        return ca, cb, None
    idx = np.flatnonzero(dis)
    target = eps.ravel()[idx] + 1j * sig.ravel()[idx] / omega
    q = -1.0 / (target - 1.0)  # Re q > 0, Im q >= 0 for Re eps < 1, Im eps >= 0
    W = 2 * math.sin(omega * dt / 2) / dt
    c = math.cos(omega * dt / 2)
    wp2 = W * W / q.real
    gamma = W * q.imag / (q.real * c)
    kj = ((1 - gamma * dt / 2) / (1 + gamma * dt / 2)).astype(np.float32)
    bj = (wp2 * dt / (1 + gamma * dt / 2)).astype(np.float32)
    return ca, cb, (idx, kj, bj)


def spp_constants(eps_m: complex, eps_d: complex, lam: float) -> tuple[complex, complex, complex]:
    """Surface plasmon on a planar interface (exp(-i omega t), fields ~ exp(i beta z)): beta = k0 sqrt(em ed / (em + ed))
    and the decay constants kappa = sqrt(beta^2 - k0^2 eps) into the metal and the dielectric (Re kappa > 0)."""
    k0 = 2 * math.pi / lam
    if not (eps_m + eps_d).real < 0:
        raise FdtdError(f"No surface plasmon: Re(eps_metal + eps_dielectric) = {(eps_m + eps_d).real:.3g} must be negative")
    beta = k0 * np.sqrt(eps_m * eps_d / (eps_m + eps_d) + 0j)
    km = np.sqrt(beta * beta - k0 * k0 * eps_m + 0j)
    kd = np.sqrt(beta * beta - k0 * k0 * eps_d + 0j)
    km, kd = (k if k.real > 0 else -k for k in (km, kd))
    return complex(beta), complex(km), complex(kd)


def spp_mode(y: np.ndarray, y0: float, eps_m: complex, eps_d: complex, lam: float, field: str = "Hx") -> np.ndarray:
    """The surface plasmon across the interface y0: Hx = exp(-kappa_d (y - y0)) above, exp(kappa_m (y - y0)) below
    (1 on it); field "Ey" gives Ey ~ beta Hx / (omega eps(y)), normalised to Hx above (it changes sign across the
    interface, since eps_metal < 0). A magnetic current sheet Mx launches the transverse E it carries, so the source
    uses the Ey profile."""
    _, km, kd = spp_constants(eps_m, eps_d, lam)
    d = np.asarray(y, float) - y0
    h = np.where(d >= 0, np.exp(-kd * d), np.exp(km * d))
    return h if field == "Hx" else h * np.where(d >= 0, 1.0, eps_d / eps_m)


def _source_profile(g: Grid, n_src: float) -> np.ndarray:
    sp = g.sp
    k = 2 * math.pi * n_src / sp.wavelength
    y = g.y
    if sp.source == "mode":
        return slab_mode(y - sp.mode_center_y, sp.mode_half_width, sp.mode_n_core, sp.mode_n_clad, sp.wavelength, sp.polarization).astype(complex)
    if sp.source == "spp":
        em, ed = g.spp_media
        return spp_mode(y, sp.spp_y, em, ed, sp.wavelength, "Ey").astype(complex)
    if sp.source == "plane":
        if abs(sp.tilt_deg) > 1e-9 and sp.periodic_y:
            raise FdtdError("A tilted plane wave needs Bloch-periodic boundaries (not supported): use a Gaussian beam with PML in y")
        return np.ones_like(y, dtype=complex)
    th = math.radians(sp.tilt_deg)
    # 2D Gaussian beam: waist w0 at (focus_z, focus_y), axis tilted by th; evaluated on the source line
    zs = g.z[g.j_src]
    yy = y - sp.focus_y
    zz = zs - sp.focus_z
    # coordinates along / across the tilted beam axis
    u = zz * math.cos(th) + yy * math.sin(th)
    v = -zz * math.sin(th) + yy * math.cos(th)
    w0 = sp.waist
    zR = k * w0 * w0 / 2
    q = u - 1j * zR  # exp(-i omega t) convention: exp(i k v^2 / 2q) = exp(-v^2 / w0^2) at the waist
    return np.sqrt(-1j * zR / q) * np.exp(1j * k * u + 1j * k * v * v / (2 * q))


def run(sp: Spec, progress=None, control=None) -> dict:
    t0 = time.time()
    g = Grid(sp)
    dx, dt, P = g.dx, g.dt, g.P
    Nz, Ny = g.Nz, g.Ny
    zs = sp.z_source if sp.z_source is not None else 0.1 * sp.size_z
    zr = sp.z_reflection if sp.z_reflection is not None else zs + 0.06 * sp.size_z
    zt = sp.z_transmission if sp.z_transmission is not None else 0.95 * sp.size_z
    if not (0 <= zs < zr < zt <= sp.size_z) and sp.reference:
        raise FdtdError("Monitors need 0 <= source < reflection monitor < transmission monitor <= domain length")
    g.j_src = int(round(zs / dx)) + P
    j_r = int(round(zr / dx)) + P
    j_t = int(round(zt / dx)) + P
    if sp.source == "spp":
        if sp.polarization != "p":
            raise FdtdError("A surface plasmon is TM: use p polarisation")
        e0, s0 = g.eps_sigma(True, sub=1)
        i0 = int(np.searchsorted(g.y, sp.spp_y))
        if not (g.Py + 3 <= i0 <= Ny - g.Py - 4):
            raise FdtdError("The plasmon interface must lie inside the domain, away from the absorbing layers")
        g.spp_media = tuple(complex(e0[i, g.j_src], s0[i, g.j_src] / g.omega) for i in (i0 - 3, i0 + 2))
        spp_constants(*g.spp_media, sp.wavelength)
    for name, j in (("source", g.j_src), ("reflection monitor", j_r), ("transmission monitor", j_t)):
        if not (P + 1 <= j <= Nz - P - 2):
            raise FdtdError(f"The {name} lies in the absorbing layer")
    period_steps = sp.wavelength / dt
    n_max = math.sqrt(max(g.eps_sigma(False)[0].max(), max([s.n**2 for s in sp.shapes], default=1.0)))
    transit = (sp.size_z + (0 if sp.periodic_y else sp.size_y)) * n_max * 2.5
    ramp = 3 * sp.wavelength
    n_steps = int(math.ceil((ramp + transit) / dt + sp.periods_avg * period_steps))
    if n_steps > MAX_STEPS:
        raise FdtdError(f"{n_steps} time steps exceed the limit of {MAX_STEPS}")
    runs = [("total", True)] + ([("reference", False)] if sp.reference else [])
    total_steps = n_steps * len(runs)
    done = [0]

    def one(with_shapes: bool | list) -> dict:
        f32 = np.float32
        eps, sig = g.eps_sigma(with_shapes)
        ca, cbx, drF = _medium(eps, sig, dt, dx, g.omega)  # cbx includes 1/dx
        (bz, az, mz), (bzh, azh, mzh) = _pml_profiles(Nz, P, dx, dt)
        (by, ay, my), (byh, ayh, myh) = _pml_profiles(Ny, g.Py, dx, dt, sp.periodic_y)
        col = eps[:, g.j_src]  # the source's medium (metal cells, Re eps < 0, left out)
        n_src = math.sqrt(col[col > 0].mean()) if np.any(col > 0) else 1.0
        prof = _source_profile(g, n_src)
        amp, ph = np.abs(prof), np.angle(prof)
        w = g.omega
        s_pol = sp.polarization == "s"
        cdt = f32(dt / dx)
        F = np.zeros((Ny, Nz), f32)  # Ex (s) or Hx (p): the out-of-plane component, integer nodes
        A = np.zeros((Ny, Nz), f32)  # Hy (s) / Ey (p) at (i, j+1/2)
        B = np.zeros((Ny, Nz), f32)  # Hz (s) / Ez (p) at (i+1/2, j)
        dFz = np.zeros((Ny, Nz), f32)
        dFy = np.zeros((Ny, Nz), f32)
        dAz = np.zeros((Ny, Nz), f32)
        dBy = np.zeros((Ny, Nz), f32)
        tmp = np.zeros((Ny, Nz), f32)
        # CPML auxiliary fields only where the profiles act (the absorbing layers plus a margin)
        cols = np.unique(np.r_[0 : P + 2, Nz - P - 2 : Nz]) if P else np.zeros(0, int)
        rows = np.unique(np.r_[0 : g.Py + 2, Ny - g.Py - 2 : Ny]) if (g.Py and not sp.periodic_y) else np.zeros(0, int)
        bzh_c, azh_c, bz_c, az_c = (x[cols].astype(f32) for x in (bzh, azh, bz, az))
        byh_r, ayh_r, by_r, ay_r = (x[rows, None].astype(f32) for x in (byh, ayh, by, ay))
        psiFz = np.zeros((Ny, cols.size), f32)
        psiAz = np.zeros((Ny, cols.size), f32)
        psiFy = np.zeros((rows.size, Nz), f32)
        psiBy = np.zeros((rows.size, Nz), f32)
        if not s_pol:
            # in-plane E components at their own (staggered) positions: Ey at (i, j+1/2), Ez at (i+1/2, j)
            def coeffs(shift, along):
                e, sg = g.eps_sigma(with_shapes, shift=shift, along=along)
                return _medium(e, sg, dt, dx, g.omega)

            caA, cbA, drA = coeffs((0.0, 0.5), "y")  # Ey: normal to walls along z
            caB, cbB, drB = coeffs((0.5, 0.0), "z")  # Ez
        cb_src = (cbx[:, g.j_src] if s_pol else np.full(Ny, dt / dx, f32)).astype(np.float64)
        # Drude currents of the dispersive cells: (flat indices, kj, bj, J) per E component
        cur = {"F": drF} if s_pol else {"A": drA, "B": drB}
        J = {k: np.zeros(v[0].size, f32) for k, v in cur.items() if v is not None}
        dtf = f32(dt)

        def drude_step(name, E):  # J+ = kj J- + bj E^n (before E is advanced)
            idx, kj, bj = cur[name]
            Jn = J[name]
            Jn *= kj
            Jn += bj * E.ravel()[idx]

        def drude_apply(name, E):  # E^{n+1} -= dt J+
            idx = cur[name][0]
            E.ravel()[idx] -= dtf * J[name]
        n_avg = int(round(sp.periods_avg * period_steps))
        start_avg = n_steps - n_avg
        dft_F = np.zeros((Ny, Nz), complex)
        dft_A = np.zeros((Ny, Nz), complex)
        dft_B = np.zeros((Ny, Nz), complex)
        dftF_half = [np.zeros(Ny, complex), np.zeros(Ny, complex)]
        js = g.j_src
        for n in range(n_steps):
            t = n * dt
            if control is not None and control.get("cancel"):
                raise Cancelled()
            # ---- differences of F (forward: at j+1/2 and i+1/2), with CPML
            np.subtract(F[:, 1:], F[:, :-1], out=dFz[:, :-1])
            np.subtract(F[1:], F[:-1], out=dFy[:-1])
            if sp.periodic_y:
                np.subtract(F[0], F[-1], out=dFy[-1])
            if cols.size:
                psiFz *= bzh_c
                psiFz += azh_c * dFz[:, cols]
                dFz[:, cols] += psiFz
            if rows.size:
                psiFy *= byh_r
                psiFy += ayh_r * dFy[rows]
                dFy[rows] += psiFy
            if s_pol:  # dHy/dt = -dEx/dz, dHz/dt = dEx/dy
                A -= cdt * dFz
                B += cdt * dFy
            else:  # eps dEy/dt = dHx/dz - Jy, eps dEz/dt = -dHx/dy - Jz
                if "A" in J:
                    drude_step("A", A)
                if "B" in J:
                    drude_step("B", B)
                A *= caA
                A += cbA * dFz
                B *= caB
                B -= cbB * dFy
                if "A" in J:
                    drude_apply("A", A)
                if "B" in J:
                    drude_apply("B", B)
            # ---- differences of A, B (backward: at integer nodes), with CPML
            np.subtract(A[:, 1:], A[:, :-1], out=dAz[:, 1:])
            np.subtract(B[1:], B[:-1], out=dBy[1:])
            if sp.periodic_y:
                np.subtract(B[0], B[-1], out=dBy[0])
            if cols.size:
                psiAz *= bz_c
                psiAz += az_c * dAz[:, cols]
                dAz[:, cols] += psiAz
            if rows.size:
                psiBy *= by_r
                psiBy += ay_r * dBy[rows]
                dBy[rows] += psiBy
            ramp_f = 0.5 * (1 - math.cos(math.pi * min(1.0, t / ramp)))
            src = ramp_f * amp * np.cos(w * (t + 0.5 * dt) - ph)
            np.subtract(dBy, dAz, out=tmp)
            if s_pol:  # eps dEx/dt = dHz/dy - dHy/dz - Jx
                if "F" in J:
                    drude_step("F", F)
                F *= ca
                F += cbx * tmp
                if "F" in J:
                    drude_apply("F", F)
                F[:, js] -= (cb_src * src).astype(f32)  # soft current sheet (one cell thick)
            else:  # dHx/dt = dEy/dz - dEz/dy - Mx
                F -= cdt * tmp
                F[:, js] -= (cb_src * src).astype(f32)  # magnetic current sheet
            if n >= start_avg:
                ph_n = np.exp(1j * w * (n + 1) * dt)  # F at t = (n+1) dt, A/B at (n+1/2) dt
                ph_h = np.exp(1j * w * (n + 0.5) * dt)
                dft_F += F * ph_n
                dft_A += A * ph_h
                dft_B += B * ph_h
                k_half = 0 if n < start_avg + n_avg // 2 else 1
                dftF_half[k_half] += F[:, j_r] * ph_n
            done[0] += 1
            if progress is not None and n % 50 == 0:
                progress(done[0] / total_steps)
        norm = 2.0 / n_avg
        Fc, Ac, Bc = dft_F * norm, dft_A * norm, dft_B * norm
        h0, h1 = dftF_half
        conv = float(np.linalg.norm(h0 - h1) / max(np.linalg.norm(h0 + h1) / 2, 1e-300))
        return {"F": Fc, "A": Ac, "B": Bc, "eps": eps, "sig": sig, "convergence": conv}

    def flux_line(res: dict, j: int, ref: dict | None = None) -> float:
        """Time-averaged S_z through column j (per unit length in x, integrated over y)."""
        F, Acol = res["F"], res["A"]
        if ref is not None:
            F, Acol = F - ref["F"], Acol - ref["A"]
        Fj = F[:, j]
        Aj = 0.5 * (Acol[:, j] + Acol[:, j - 1])  # A (half node) interpolated to j
        yslice = slice(g.Py, Ny - g.Py)
        if sp.polarization == "s":  # S_z = 1/2 Re(Ex Hy*)
            s = 0.5 * np.real(Fj * np.conj(Aj))
        else:  # S_z = -1/2 Re(Ey Hx*)
            s = -0.5 * np.real(Aj * np.conj(Fj))
        return float(s[yslice].sum() * dx)

    tot = one(True)
    out: dict = {"cells": [int(Nz), int(Ny)], "dx_um": dx, "dt": dt, "steps": n_steps, "periods_averaged": sp.periods_avg, "convergence": tot["convergence"], "polarization": sp.polarization}
    notes = []
    if tot["convergence"] > 0.02:
        notes.append(f"The field has not settled (last periods differ by {tot['convergence'] * 100:.1f} %): enlarge the domain transit time or check resonances")
    F_t_tot = flux_line(tot, j_t)
    if sp.reference:
        ref = one(sp.reference_shapes if sp.reference_shapes else False)
        F_inc = flux_line(ref, j_r)
        F_inc_t = flux_line(ref, j_t)
        if F_inc <= 0:
            raise FdtdError("No incident power at the reflection monitor")
        R = -flux_line(tot, j_r, ref) / F_inc
        T = F_t_tot / F_inc
        out.update({"R": R, "T": T, "A": 1 - R - T, "incident_flux": F_inc, "reference_transmission": F_inc_t / F_inc})
        if abs(F_inc_t / F_inc - 1) > 0.02 and sp.periodic_y:
            notes.append(f"The reference field loses {abs(1 - F_inc_t / F_inc) * 100:.1f} % between the monitors (absorbing background?)")
    else:
        out.update({"transmitted_flux": F_t_tot})
    if sp.source in ("mode", "spp"):
        try:
            out["propagation"] = _propagation(g, sp, tot, j_t)
        except FdtdError as exc:
            notes.append(f"No propagation constant: {exc}")
    # maps (downsampled), physical domain only
    ys = slice(g.Py, Ny - g.Py)
    zsl = slice(P, Nz - P)
    if sp.polarization == "s":
        I = np.abs(tot["F"][ys, zsl]) ** 2
        field_re = np.real(tot["F"][ys, zsl])
    else:
        Ey = 0.5 * (tot["A"] + np.roll(tot["A"], 1, axis=1))
        Ez = 0.5 * (tot["B"] + np.roll(tot["B"], 1, axis=0))
        I = (np.abs(Ey) ** 2 + np.abs(Ez) ** 2)[ys, zsl]
        field_re = np.real(tot["F"][ys, zsl])
    epsm = np.abs(tot["eps"][ys, zsl] + 1j * tot["sig"][ys, zsl] / g.omega)  # |eps|: the map shows |n + i k|
    f = max(1, int(math.ceil(max(I.shape) / sp.map_cells)))
    zc, yc = g.z[zsl], g.y[ys]
    out.update(
        {
            # every map and both axes use the same f x f blocks (block means)
            "z_um": _block(zc[None, :], 1, f)[0].tolist(),
            "y_um": _block(yc[:, None], f, 1)[:, 0].tolist(),
            "intensity": _block(I, f, f).tolist(),
            "field": _block(field_re, f, f).tolist(),
            "index": np.sqrt(_block(epsm, f, f)).tolist(),
            "monitors": {"source_z": zs, "reflection_z": zr, "transmission_z": zt},
            "notes": notes,
            "time_s": time.time() - t0,
            "method": "2D FDTD (Yee, second order, Courant 0.5) with convolutional PML; single-frequency DFT of the steady state; Poynting flux through monitor lines; R, T from a reference run (incident field subtracted)",
        }
    )
    return out


def _propagation(g: Grid, sp: Spec, res: dict, j_t: int) -> dict:
    """beta of the guided field: least squares of log(field) on the source's axis line from 2 wavelengths past the
    source to the transmission monitor, or to where the cross-section first changes (phase unwrapped)."""
    if sp.source == "spp":
        _, _, kd = spp_constants(*g.spp_media, sp.wavelength)
        y_line = sp.spp_y + 0.2 / kd.real
    else:
        y_line = sp.mode_center_y
    i = int(np.argmin(np.abs(g.y - y_line)))
    j0 = g.j_src + int(math.ceil(2 * sp.wavelength / g.dx))
    col = res["eps"][:, g.j_src]
    changed = [j for j in range(g.j_src + 1, j_t) if np.max(np.abs(res["eps"][:, j] - col)) > 1e-9 or np.max(np.abs(res["sig"][:, j] - res["sig"][:, g.j_src])) > 1e-9]
    if changed:
        j_t = changed[0]
    if j_t - j0 < 8:
        raise FdtdError("the guide is too short between the source and the transmission monitor (or the end of the guide)")
    f = res["F"][i, j0:j_t]
    if np.any(np.abs(f) == 0):
        raise FdtdError("the guided field vanishes on its axis line")
    z = g.z[j0:j_t]
    ph = np.unwrap(np.angle(f))
    la = np.log(np.abs(f))
    A = np.vstack([z, np.ones_like(z)]).T
    (b_re, _), *_ = np.linalg.lstsq(A, ph, rcond=None)
    (b_im, _), *_ = np.linalg.lstsq(A, -la, rcond=None)
    k0 = 2 * math.pi / sp.wavelength
    out = {"n_eff": b_re / k0, "kappa": b_im / k0, "attenuation_per_um": 2 * b_im, "y_um": float(g.y[i]), "z_um": [float(z[0]), float(z[-1])]}
    if sp.source == "spp":
        beta, _, _ = spp_constants(*g.spp_media, sp.wavelength)
        out["analytic_n_eff"] = beta.real / k0
        out["analytic_kappa"] = beta.imag / k0
        out["eps_metal"] = [g.spp_media[0].real, g.spp_media[0].imag]
        out["eps_dielectric"] = [g.spp_media[1].real, g.spp_media[1].imag]
    return out


def _block(a: np.ndarray, fy: int, fz: int) -> np.ndarray:
    """Means over fy x fz blocks (a trailing partial block is dropped)."""
    if fy == 1 and fz == 1:
        return a
    ny, nz = (a.shape[0] // fy) * fy, (a.shape[1] // fz) * fz
    return a[:ny, :nz].reshape(ny // fy, fy, nz // fz, fz).mean(axis=(1, 3))


def spec_from_dict(d: dict, index_of=None) -> Spec:
    """API dictionary -> Spec. Shapes give n (and k) or a material name resolved by `index_of(name)`."""
    lam = float(d["wavelength_um"])

    def shapes_of(items):
        out = []
        for s in items:
            n, k = s.get("n"), s.get("k", 0.0)
            if s.get("material"):
                if index_of is None:
                    raise FdtdError("Material names need the material library")
                n = index_of(s["material"], lam)
            if n is None:
                raise FdtdError("Every shape needs a refractive index or a material")
            kw = {kk: float(s[kk]) for kk in ("z0", "z1", "y0", "y1", "zc", "yc", "r") if kk in s}
            out.append(Shape(kind=s.get("kind", "rectangle"), n=float(n), k=float(k or 0.0), points=s.get("points", []), name=s.get("name", ""), **kw))
        return out

    shapes = shapes_of(d.get("shapes", []))
    bg = d.get("n_background", 1.0)
    if d.get("background_material") and index_of is not None:
        bg = index_of(d["background_material"], lam)
    return Spec(
        wavelength=lam,
        size_z=float(d["size_z_um"]),
        size_y=float(d["size_y_um"]),
        polarization=d.get("polarization", "s"),
        n_background=float(bg),
        shapes=shapes,
        source=d.get("source", "plane"),
        waist=float(d.get("waist_um", 2.0)),
        focus_z=float(d.get("focus_z_um", 0.0)),
        focus_y=float(d.get("focus_y_um", 0.0)),
        tilt_deg=float(d.get("tilt_deg", 0.0)),
        z_source=d.get("source_z_um"),
        z_reflection=d.get("reflection_z_um"),
        z_transmission=d.get("transmission_z_um"),
        periodic_y=bool(d.get("periodic_y", d.get("source", "plane") == "plane")),
        ppw=float(d.get("points_per_wavelength", 30.0)),
        pml_cells=int(d.get("pml_cells", 20)),
        periods_avg=int(d.get("periods_averaged", 6)),
        reference=bool(d.get("reference", True)),
        reference_shapes=shapes_of(d["reference_shapes"]) if d.get("reference_shapes") else None,
        mode_half_width=float(d.get("mode_half_width_um", 1.0)),
        mode_n_core=float(d.get("mode_n_core", 1.46)),
        mode_n_clad=float(d.get("mode_n_clad", 1.45)),
        mode_center_y=float(d.get("mode_center_y_um", 0.0)),
        spp_y=float(d.get("spp_y_um", 0.0)),
        map_cells=int(d.get("map_cells", 240)),
        geometry=_geometry(d.get("geometry", "planar")),
    )


def _geometry(g: str) -> str:
    if g not in ("planar", "axisymmetric"):
        raise FdtdError(f"Unknown geometry '{g}' (planar or axisymmetric)")
    return g


def slab_mode(y: np.ndarray, d: float, n1: float, n2: float, lam: float, pol: str = "s") -> np.ndarray:
    """Fundamental (even) guided mode of a symmetric slab waveguide, core |y| < d, from Maxwell's
    equations: with u = d sqrt(k0^2 n1^2 - beta^2), w = d sqrt(beta^2 - k0^2 n2^2), u^2 + w^2 = V^2,
        TE (s, field Ex):  u tan u = w
        TM (p, field Hx):  u tan u = (n1 / n2)^2 w
    and the out-of-plane field cos(u y / d) in the core, cos(u) exp(-w (|y| / d - 1)) outside.
    Peak 1. The even mode has no cut-off."""
    from scipy.optimize import brentq

    if not n1 > n2 > 0:
        raise FdtdError("The waveguide core index must exceed the cladding index")
    V = 2 * math.pi / lam * d * math.sqrt(n1 * n1 - n2 * n2)
    r = 1.0 if pol == "s" else (n1 / n2) ** 2
    hi = min(V, math.pi / 2) * (1 - 1e-12)
    u = brentq(lambda u: u * math.tan(u) - r * math.sqrt(max(V * V - u * u, 0.0)), 1e-12, hi, xtol=1e-14)
    w = math.sqrt(max(V * V - u * u, 0.0))
    a = np.abs(np.asarray(y, float)) / d
    return np.where(a <= 1, np.cos(u * a), math.cos(u) * np.exp(-w * (a - 1)))


def slab_mode_neff(d: float, n1: float, n2: float, lam: float, pol: str = "s") -> float:
    """Effective index of the fundamental slab mode (same equation as slab_mode)."""
    from scipy.optimize import brentq

    V = 2 * math.pi / lam * d * math.sqrt(n1 * n1 - n2 * n2)
    r = 1.0 if pol == "s" else (n1 / n2) ** 2
    hi = min(V, math.pi / 2) * (1 - 1e-12)
    u = brentq(lambda u: u * math.tan(u) - r * math.sqrt(max(V * V - u * u, 0.0)), 1e-12, hi, xtol=1e-14)
    return math.sqrt(n1 * n1 - (u * lam / (2 * math.pi * d)) ** 2)
