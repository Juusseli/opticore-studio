"""Physical-optics propagation (POP) of a complex scalar field through the sequential system.

The field U (|U|^2 = power per area through the plane, total power 1 at the source) goes
through four steps (lengths in mm, lambda_n = lambda / n in the medium):

1. Source plane -> entry plane (just before surface 1, before the whole first surface). A
   Gaussian source is sampled at its waist (waist_z after the object surface; flat phase) and
   propagated from there over D - z_w (z_R = pi w0^2 / lambda_n); a waist beyond the entry plane
   gives the converging beam as the conjugate of the waist field propagated over z_w - D:
   * far field (distance > 20 Rayleigh ranges of the source): the exact asymptotic
     Rayleigh-Sommerfeld solution U(r) = -i k z / (2 pi r^2) exp(i k r) A(k x/r, k y/r),
     A the angular spectrum of the source field (valid at any NA);
   * near field (< 2 Rayleigh ranges): the exact angular spectrum;
   * in between the Fresnel transform (separable, arbitrary output window), with its
     phase-error estimate k z theta^4 / 8 reported;
   * a collimated or converging Gaussian beam (object at infinity) is evaluated analytically
     at the entry plane.
2. Entry plane -> exit plane (just after the last surface): ray transfer. Every sample of the
   entry field starts a ray along the local phase gradient; the exact ray trace gives the
   optical path, the Fresnel or coating transmission and the clipping at clear apertures.
   Amplitudes follow from flux conservation across the ray tubes,
   |U_P|^2 dA_P = T |U_e|^2 dA_e, with dA_P / dA_e from the Jacobian of the ray map; the phase
   is the entry phase + k0 OPL. The exit field is resampled on a regular grid (the
   best-fit sphere is removed before interpolation and restored exactly).
3. Exit plane -> target plane (the image surface + an offset). A sphere is fitted to the exit
   wavefront; the residual (aberration) phase is what the exit grid has to resolve.
   * Strongly converging beams (Fresnel number w^2 / (lambda R) > 10, target within R/2 of the
     focus): the Debye integral about the sphere centre,
     U = -i k / (2 pi) Int a(s) exp(i k s.(r - C)) dsx dsy, with a(s) = U_res rho^2 / R the
     field on the reference sphere per unit direction-sine area (exact scalar focusing at any
     NA for large Fresnel numbers; evaluated as a separable matrix DFT);
   * otherwise the exact scalar angular spectrum of the full field,
     U(x, y, z) = (1/4 pi^2) Int A(kx, ky) exp(i (kx x + ky y + kz z)) dk,
     kz = sqrt(k^2 - kx^2 - ky^2), on the output window by a matrix DFT (evanescent components
     decay).
4. Results: irradiance, power, D4sigma widths, power inside a radius and the coupling
   efficiency into a target mode (Gaussian or a step-index fibre's LP01),
   eta = |Int U M*|^2 / Int |M|^2 (fraction of the source power coupled).

Assumptions: scalar field; axial, rotationally symmetric refracting systems (no mirrors or
coordinate breaks); the ray transfer is the geometric (stationary-phase) limit through the
lenses, so diffraction *inside* the lens group (e.g. at an internal aperture edge) is not
modelled, only the truncation of the field; |U|^2 counts as flux density (paraxial weighting of
the obliquity factor in free-space propagation).
"""

from __future__ import annotations

import math
import time

import numpy as np
from scipy.interpolate import LinearNDInterpolator, RectBivariateSpline, RegularGridInterpolator
from scipy.spatial import Delaunay

from ..system import CompiledSystem, NotApplicable, SystemError_
from .fibermodes import fibre_modes, lp_field

MAX_EXIT = 1024
MAX_ENTRY = 768  # rays per side after refinement


# ---------------------------------------------------------------------- fields
def gaussian_q(w0: float, z: float, lam_n: float) -> tuple[float, float, float]:
    """(w(z), R(z) or inf, Gouy phase) of a Gaussian beam with waist w0 at z = 0."""
    zR = math.pi * w0 * w0 / lam_n
    w = w0 * math.sqrt(1 + (z / zR) ** 2)
    R = math.inf if z == 0 else z * (1 + (zR / z) ** 2)
    return w, R, math.atan2(z, zR)


def gaussian_field(x: np.ndarray, y: np.ndarray, wx: float, wy: float, zx: float, zy: float, lam_n: float, x0: float = 0.0, y0: float = 0.0) -> np.ndarray:
    """Normalised (power 1) astigmatic Gaussian beam, waists wx, wy at distances -zx, -zy (z from
    the waists to the plane), on the grid x (cols), y (rows)."""
    k = 2 * math.pi / lam_n
    X, Y = np.meshgrid(x - x0, y - y0)
    out = np.ones_like(X, dtype=complex)
    for V, w0, z in ((X, wx, zx), (Y, wy, zy)):
        w, R, g = gaussian_q(w0, z, lam_n)
        out = out * (2 / math.pi) ** 0.25 / math.sqrt(w) * np.exp(-(V / w) ** 2 + (0 if math.isinf(R) else 1j * k * V * V / (2 * R)) - 0.5j * g)
    return out


def fibre_field(x: np.ndarray, y: np.ndarray, lam_um: float, core_radius_um: float, n_core: float, n_clad: float, x0: float = 0.0, y0: float = 0.0) -> tuple[np.ndarray, dict]:
    m = fibre_modes(lam_um, core_radius_um, n_core, n_clad, vector=False, profiles=0)
    lp = m["lp_modes"][0]
    X, Y = np.meshgrid(x - x0, y - y0)
    R = np.hypot(X, Y) / (core_radius_um * 1e-3)
    U = lp_field(0, lp["u"], lp["w"], R).astype(complex)
    dx, dy = x[1] - x[0], y[1] - y[0]
    U /= math.sqrt(float((np.abs(U) ** 2).sum() * dx * dy))
    return U, m


def power(U: np.ndarray, x: np.ndarray, y: np.ndarray) -> float:
    return float((np.abs(U) ** 2).sum() * (x[1] - x[0]) * (y[1] - y[0]))


def moments(U: np.ndarray, x: np.ndarray, y: np.ndarray) -> dict:
    I = np.abs(U) ** 2
    P = I.sum()
    if P <= 0:
        return {"centroid": [0.0, 0.0], "d4sigma": [0.0, 0.0]}
    X, Y = np.meshgrid(x, y)
    cx, cy = (I * X).sum() / P, (I * Y).sum() / P
    sx = math.sqrt(float((I * (X - cx) ** 2).sum() / P))
    sy = math.sqrt(float((I * (Y - cy) ** 2).sum() / P))
    return {"centroid": [float(cx), float(cy)], "d4sigma": [4 * sx, 4 * sy]}


# ---------------------------------------------------------------------- propagation
def angular_spectrum(U: np.ndarray, x: np.ndarray, y: np.ndarray, lam_n: float, dz: float, xo: np.ndarray, yo: np.ndarray) -> np.ndarray:
    """Exact scalar propagation by dz to the output grid (xo, yo); the padded period covers
    the input and output windows (no wrap-around)."""
    return AngularSpectrum(U, x, y, xo, yo).at(lam_n, dz, xo, yo)


class AngularSpectrum:
    """Angular spectrum of a sampled field, computed once (padded FFT) and evaluated at any
    distance on any output points inside the window given at construction."""

    def __init__(self, U: np.ndarray, x: np.ndarray, y: np.ndarray, xo: np.ndarray, yo: np.ndarray):
        self._prepare(U, x, y, xo, yo)

    def at(self, lam_n: float, dz: float, xo: np.ndarray, yo: np.ndarray) -> np.ndarray:
        k = 2 * math.pi / lam_n
        kz = np.sqrt((k * k - self.K2).astype(complex))
        AH = self.A * np.exp(1j * kz * dz)
        Ex = np.exp(1j * np.outer(xo - self.x0, self.kx))
        Ey = np.exp(1j * np.outer(yo - self.y0, self.ky))
        return (Ey @ AH @ Ex.T) * self.dk2

    def _prepare(self, U, x, y, xo, yo):
        dx, dy = x[1] - x[0], y[1] - y[0]
        span_x = (x[-1] - x[0]) + (xo[-1] - xo[0]) + 2 * abs(xo.mean() - x.mean()) + 4 * dx
        span_y = (y[-1] - y[0]) + (yo[-1] - yo[0]) + 2 * abs(yo.mean() - y.mean()) + 4 * dy
        nx = int(2 ** math.ceil(math.log2(max(len(x), span_x / dx))))
        ny = int(2 ** math.ceil(math.log2(max(len(y), span_y / dy))))
        if nx * ny > 4096 * 4096:
            # a limit of the method (the sampled window), not a fault of the system
            raise NotApplicable("The beam spreads far beyond the window that can be computed at the target (padded grid > 4096^2); move the target closer or enlarge the sampling window")
        P = np.zeros((ny, nx), complex)
        P[: len(y), : len(x)] = U
        self.kx = 2 * math.pi * np.fft.fftfreq(nx, dx)
        self.ky = 2 * math.pi * np.fft.fftfreq(ny, dy)
        self.A = np.fft.fft2(P) * dx * dy  # A(k) = sum U exp(-i k (x - x0)), x0 = x[0]
        KX, KY = np.meshgrid(self.kx, self.ky)
        self.K2 = KX * KX + KY * KY
        self.x0, self.y0 = x[0], y[0]
        self.dk2 = (2 * math.pi / (nx * dx)) * (2 * math.pi / (ny * dy)) / (4 * math.pi**2)


def fresnel(U: np.ndarray, x: np.ndarray, y: np.ndarray, lam_n: float, z: float, xo: np.ndarray, yo: np.ndarray) -> np.ndarray:
    """Fresnel transform (separable), arbitrary output grid."""
    k = 2 * math.pi / lam_n
    dx, dy = x[1] - x[0], y[1] - y[0]
    Mx = np.exp(1j * k / (2 * z) * (xo[:, None] - x[None, :]) ** 2)
    My = np.exp(1j * k / (2 * z) * (yo[:, None] - y[None, :]) ** 2)
    return np.exp(1j * k * z) / (1j * lam_n * z) * (My @ U @ Mx.T) * dx * dy


def far_field(U: np.ndarray, x: np.ndarray, y: np.ndarray, lam_n: float, z: float, xo: np.ndarray, yo: np.ndarray) -> np.ndarray:
    """Asymptotic (stationary-phase) Rayleigh-Sommerfeld field at distance z of a small source."""
    k = 2 * math.pi / lam_n
    dx, dy = x[1] - x[0], y[1] - y[0]
    Xo, Yo = np.meshgrid(xo, yo)
    r = np.sqrt(Xo * Xo + Yo * Yo + z * z)
    kxn, kyn = k * Xo / r, k * Yo / r
    # angular spectrum on a regular k grid covering the needed directions (matrix DFT)
    m = 2 * max(len(x), 64)
    kmax_x, kmax_y = float(np.abs(kxn).max()) * 1.05 + 1e-9, float(np.abs(kyn).max()) * 1.05 + 1e-9
    kgx, kgy = np.linspace(-kmax_x, kmax_x, m), np.linspace(-kmax_y, kmax_y, m)
    Fx = np.exp(-1j * np.outer(kgx, x))
    Fy = np.exp(-1j * np.outer(kgy, y))
    A = (Fy @ U @ Fx.T) * dx * dy
    inside = (np.abs(kxn) <= kmax_x) & (np.abs(kyn) <= kmax_y)

    def ip(part):  # bicubic spline (FITPACK), zero outside the computed directions
        v = RectBivariateSpline(kgy, kgx, part, kx=3, ky=3).ev(kyn, kxn)
        return np.where(inside, v, 0.0)

    Ak = ip(A.real) + 1j * ip(A.imag)
    return -1j * k * z / (2 * math.pi * r * r) * np.exp(1j * k * r) * Ak


def _unwrap2d(phase: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Unwrap a smooth phase: along the central row, then every column from it."""
    ny, nx = phase.shape
    p = np.where(valid, phase, 0.0)
    r0 = ny // 2
    out = np.empty_like(p)
    out[r0] = np.unwrap(p[r0])
    for j in range(nx):
        col = p[:, j].copy()
        col[r0] = out[r0, j]
        up = np.unwrap(col[r0:])
        dn = np.unwrap(col[: r0 + 1][::-1])[::-1]
        out[r0:, j] = up
        out[: r0 + 1, j] = dn
    return out


# ---------------------------------------------------------------------- main
def physical_optics(
    cs: CompiledSystem,
    source: dict,
    wavelength: int | None = None,
    target_offset: float = 0.0,
    grid: int = 128,
    out_grid: int = 128,
    out_window: float | None = None,
    target_mode: dict | None = None,
    detector_radius: float | None = None,
    side_view: bool = False,
    side_view_cols: int = 240,
    _transfer_only: bool = False,
) -> dict:
    t0 = time.time()
    model = cs.model
    n_s = cs.n_surfaces
    if not cs.axial or any(cs.is_cb) or any(cs.is_mirror[1:]):
        raise NotApplicable("Physical optics propagation needs an axial refracting system (no mirrors, tilts or decentres)")
    wl = cs.wl_index(wavelength)
    lam_um = float(cs.wavelengths[wl])
    lam0 = lam_um * 1e-3
    k0 = 2 * math.pi / lam0
    n_obj = float(cs.n_after[wl, 0])
    j_last = n_s - 2
    n_img = float(cs.n_after[wl, j_last])
    notes: list[str] = []
    grid = int(min(max(grid, 32), 512))
    out_grid = int(min(max(out_grid, 16), 512))

    # ---- entry plane: in front of the whole first surface
    from ..analysis.evaluate import auto_semi_diameters, effective_semi_diameters
    from ..paraxial import compute_pupil

    sd = effective_semi_diameters(cs, auto_semi_diameters(cs, compute_pupil(cs)))
    r1 = np.linspace(0, sd[1], 50)
    sag1 = cs.shapes[1].sag(r1 * r1)
    z_e = float(min(0.0, np.nanmin(sag1))) - 1e-6
    kind = source.get("kind", "gaussian")
    infinite = model.surfaces[0].thickness is None
    src_info: dict = {"kind": kind}
    src_field: dict = {}  # the source field (finite object), for the side view
    first = [True]

    def make_entry(n_e: int):
        """Entry field on an n_e x n_e grid: (U, x, y, reference sphere (xc, yc, R), method)."""
        entry_notes = notes if first[0] else []
        if infinite:
            if kind not in ("gaussian", "tophat"):
                raise SystemError_("With the object at infinity the source is a Gaussian beam or a uniform (top-hat) beam at surface 1")
            lam_n = lam0 / n_obj
            if kind == "gaussian":
                wx, wy = float(source.get("waist_x", 1.0)), float(source.get("waist_y", source.get("waist_x", 1.0)))
                zw = float(source.get("waist_z", 0.0))  # waist position relative to surface 1 (mm; < 0: before it)
                wex = gaussian_q(wx, z_e - zw, lam_n)[0]
                wey = gaussian_q(wy, z_e - zw, lam_n)[0]
                half = 2.2 * max(wex, wey)
            else:
                rad = float(source.get("radius", 1.0))
                half = 1.05 * rad
            xe = np.linspace(-half, half, n_e)
            ye = xe.copy()
            if kind == "gaussian":
                Ue = gaussian_field(xe, ye, wx, wy, z_e - zw, z_e - zw, lam_n, *source.get("decenter", [0.0, 0.0]))
                src_info.update({"waist_x": wx, "waist_y": wy, "waist_z": zw})
                ref_c = (*source.get("decenter", [0.0, 0.0]), gaussian_q(math.sqrt(wx * wy), z_e - zw, lam_n)[1])
            else:
                X, Y = np.meshgrid(xe, ye)
                Ue = (np.hypot(X, Y) <= rad).astype(complex)
                Ue /= math.sqrt(power(Ue, xe, ye))
                src_info.update({"radius": rad})
                ref_c = (0.0, 0.0, math.inf)
            entry_method = "analytic beam at surface 1"
        else:
            z_src = float(cs.frames[0].origin[2])
            D = z_e - z_src
            if D <= 0:
                raise SystemError_("The object surface must lie in front of surface 1")
            lam_n = lam0 / n_obj
            # source field on its own grid
            zw = 0.0  # plane of the sampled source field relative to the object surface
            if kind == "gaussian":
                wx, wy = float(source.get("waist_x", 0.005)), float(source.get("waist_y", source.get("waist_x", 0.005)))
                zw = float(source.get("waist_z", 0.0))  # waist relative to the object surface (mm)
                # sampled at its waist (flat, real field; 3.5 w0 holds it): the beam elsewhere follows by exact
                # propagation, so the strongly curved field on the object surface of a beam whose waist lies
                # far from it is never sampled (a curvature R needs a step <= lambda_n R / (4 half-width))
                hs = 3.5 * max(wx, wy)
                xs = np.linspace(-hs, hs, grid)
                Us = gaussian_field(xs, xs, wx, wy, 0.0, 0.0, lam_n, *source.get("decenter", [0.0, 0.0]))
                src_info.update({"waist_x": wx, "waist_y": wy, "waist_z": zw})
            elif kind == "fibre":
                a_um = float(source["core_radius_um"])
                n1, n2 = _fibre_indices(source, lam_um)
                m = fibre_modes(lam_um, a_um, n1, n2, vector=False, profiles=0)
                hs = 3.5 * m["lp01"]["gaussian_waist"] * 1e-3
                xs = np.linspace(-hs, hs, grid)
                Us, _ = fibre_field(xs, xs, lam_um, a_um, n1, n2, *source.get("decenter", [0.0, 0.0]))
                src_info.update({"core_radius_um": a_um, "n_core": n1, "n_clad": n2, "v_number": m["v_number"], "mfd_um": m["lp01"]["mfd_petermann2"], "single_mode": m["single_mode"]})
                if not m["single_mode"]:
                    entry_notes.append(f"The source fibre is not single-mode at {lam_um:g} um (V = {m['v_number']:.3f}); only LP01 is launched")
            elif kind == "tophat":
                rad = float(source.get("radius", 0.01))
                hs = 1.6 * rad
                xs = np.linspace(-hs, hs, grid)
                X, Y = np.meshgrid(xs, xs)
                Us = (np.hypot(X, Y) <= rad).astype(complex)
                Us /= math.sqrt(power(Us, xs, xs))
                src_info.update({"radius": rad})
            elif kind == "field":
                Us, xs, p_field = field_source(source, grid)
                lam_f = source.get("wavelength_um")
                if lam_f is not None and abs(float(lam_f) - lam_um) > 1e-4 * lam_um:
                    raise SystemError_(f"The imported field is for {float(lam_f):.6g} um, the propagation wavelength is {lam_um:.6g} um")
                n_f = source.get("n_medium")
                if n_f is not None and abs(float(n_f) - n_obj) > 2e-3:
                    raise SystemError_(f"The imported field was computed in a medium of index {float(n_f):.4g}, the object space has {n_obj:.4g}: place the FDTD transmission monitor in the object-space medium")
                Us *= math.sqrt(p_field)  # the field carries the power that left the FDTD region
                src_info.update({"from": source.get("origin", "field"), "plane_offset_mm": float(source.get("plane_offset_mm", 0.0)), "power": p_field})
            else:
                raise SystemError_(f"Unknown source kind '{kind}'")
            mom = moments(Us, xs, xs)
            # waist radius: analytic for a Gaussian, else the second-moment (1/e^2-equivalent) radius of the
            # sampled source field; z_R and the far-field angle follow from it
            ws = max(wx, wy) if kind == "gaussian" else 0.5 * max(mom["d4sigma"])
            if kind == "field":
                # the given field lies plane_offset_mm after the object surface
                off = float(source.get("plane_offset_mm", 0.0))
                if off >= D:
                    raise SystemError_("The imported field plane lies at or behind surface 1")
                z_src += off
                D -= off
            # the sampled field must resolve its own phase: more than a quarter wave between neighbouring
            # samples of its bright part aliases its angular spectrum (the propagation to surface 1 is then wrong)
            Is = np.abs(Us) ** 2
            br = Is > 1e-3 * Is.max()
            steps = [
                np.abs(np.angle(Us[1:, :] * np.conj(Us[:-1, :])))[br[1:, :] & br[:-1, :]],
                np.abs(np.angle(Us[:, 1:] * np.conj(Us[:, :-1])))[br[:, 1:] & br[:, :-1]],
            ]
            step_s = max((float(v.max()) for v in steps if v.size), default=0.0)
            if step_s > math.pi / 2:
                entry_notes.append(f"The source field changes its phase by up to {step_s:.2g} rad between samples (> pi/2): it is under-sampled and its propagation to surface 1 is approximate; raise the grid")
            z_f = z_src + zw  # plane of the sampled field (a Gaussian's waist)
            Dw = z_e - z_f  # from it to the entry plane; < 0: the waist lies beyond the entry plane
            dist = abs(Dw)
            R_e = gaussian_q(ws, Dw, lam_n)[1]
            ref_c = (*mom["centroid"], R_e)  # wavefront sphere at the entry plane
            zR = math.pi * ws * ws / lam_n
            theta = lam_n / (math.pi * ws)  # 1/e^2 far-field half-angle (Gaussian-equivalent)
            he = 2.4 * max(ws * math.sqrt(1 + (dist / zR) ** 2), ws)
            xe = np.linspace(-he, he, n_e)
            ye = xe.copy()
            if dist > 20 * zR:
                Ue = far_field(Us, xs, xs, lam_n, dist, xe, ye)
                entry_method = f"far field (exact asymptotic Rayleigh-Sommerfeld), distance {dist / zR:.1f} z_R"
            elif dist < 2 * zR:
                # near field: the beam barely grows; exact angular spectrum
                Ue = angular_spectrum(Us, xs, xs, lam_n, dist, xe, ye)
                entry_method = f"angular spectrum (exact scalar), distance {dist / zR:.2f} z_R"
            else:
                Ue = fresnel(Us, xs, xs, lam_n, dist, xe, ye)
                err = 2 * math.pi / lam_n * dist * (2 * theta) ** 4 / 8
                entry_method = f"Fresnel transform, distance {dist / zR:.2f} z_R, phase error at 2x divergence ~{err:.2g} rad"
                if err > 0.5:
                    entry_notes.append(f"Source to surface 1: Fresnel phase error ~{err:.2g} rad (wide source divergence close to the lens); results approximate")
            if Dw < 0:
                # a real waist field propagated back by |Dw| is the complex conjugate of the one propagated
                # forward by |Dw| (time reversal, exact for the propagating waves): the converging beam
                Ue = np.conj(Ue)
            if kind == "gaussian" and zw != 0.0:
                where = "after" if zw > 0 else "before"
                entry_method += f", from the waist {abs(zw):g} mm {where} the object surface" + (" (beyond surface 1: back-propagated)" if Dw < 0 else "")
            src_info.update({"plane_z": z_src, "distance_to_surface1": D, "field_plane_z": z_f, "phase_step_rad": step_s})
            src_field.update(U=Us, x=xs, lam_n=lam_n, ws=ws, zR=zR, z_src=z_src, z_field=z_f, xc=mom["centroid"][0], yc=mom["centroid"][1])

        first[0] = False
        return Ue, xe, ye, ref_c, entry_method

    Ue, xe, ye, ref_c, entry_method = make_entry(grid)
    P_entry = power(Ue, xe, ye)
    if P_entry < 0.98 * float(src_info.get("power", 1.0)):
        notes.append(f"Only {P_entry / float(src_info.get('power', 1.0)) * 100:.1f} % of the source power falls in the entry window")

    # ---- ray transfer through the lenses
    from ..raytrace import trace

    def transfer(Ue, xe, ye, ref_c):
        dxe = xe[1] - xe[0]
        I_e = np.abs(Ue) ** 2
        valid = I_e > 1e-7 * I_e.max()
        kn = k0 * n_obj
        Xe, Ye = np.meshgrid(xe, ye)
        # the wavefront sphere (centre ref_c) is handled analytically; only the slowly varying rest is
        # differentiated and unwrapped numerically (no aliasing of the steep far-field phase)
        xc, yc, Rc = ref_c
        if math.isfinite(Rc) and abs(Rc) > 0:
            rr = np.sqrt((Xe - xc) ** 2 + (Ye - yc) ** 2 + Rc * Rc)
            ref = math.copysign(1.0, Rc) * kn * (rr - abs(Rc))
            rgx = math.copysign(1.0, Rc) * kn * (Xe - xc) / rr
            rgy = math.copysign(1.0, Rc) * kn * (Ye - yc) / rr
        else:
            ref = np.zeros_like(Xe)
            rgx = np.zeros_like(Xe)
            rgy = np.zeros_like(Xe)
        Ures = Ue * np.exp(-1j * ref)
        ph = np.angle(Ures)
        gx = rgx.copy()
        gy = rgy.copy()
        gx[:, 1:-1] += np.angle(Ures[:, 2:] * np.conj(Ures[:, :-2])) / (2 * dxe)
        gy[1:-1, :] += np.angle(Ures[2:, :] * np.conj(Ures[:-2, :])) / (2 * dxe)
        L, M = gx / kn, gy / kn
        s2 = L * L + M * M
        valid &= s2 < 0.98
        valid[[0, -1], :] = False
        valid[:, [0, -1]] = False
        psi_e = ref + _unwrap2d(ph, valid)
        iv = np.nonzero(valid.ravel())[0]
        P0 = np.stack([Xe.ravel()[iv], Ye.ravel()[iv], np.full(iv.size, z_e)], axis=1)
        N = np.sqrt(1 - s2.ravel()[iv])
        D0 = np.stack([L.ravel()[iv], M.ravel()[iv], N], axis=1)
        tr = trace(cs, wl, P0, D0, end=j_last, clip=True, fresnel=True, record=True)
        ok = tr.ok.copy()
        # clear apertures of the physical surfaces
        for j in range(1, j_last + 1):
            if np.any(cs.n_after[:, j] != cs.n_after[:, j - 1]):
                q = tr.local[:, j]
                ok &= np.all(np.isfinite(q), axis=1) & (np.hypot(q[:, 0], q[:, 1]) <= sd[j] * (1 + 1e-9) + 1e-12)
        hit = tr.points[:, j_last]
        Dend = tr.dirs
        z_P = float(np.nanmax(np.where(ok, hit[:, 2], np.nan))) + 1e-6 if ok.any() else float(cs.frames[j_last].origin[2])
        tP = (z_P - hit[:, 2]) / Dend[:, 2]
        xP = hit[:, 0] + tP * Dend[:, 0]
        yP = hit[:, 1] + tP * Dend[:, 1]
        opl = tr.opl + n_img * tP
        psi_P = psi_e.ravel()[iv] + k0 * opl
        # ray-tube Jacobian on the entry grid
        XP = np.full(I_e.shape, np.nan)
        YP = np.full(I_e.shape, np.nan)
        XP.ravel()[iv[ok]] = xP[ok]
        YP.ravel()[iv[ok]] = yP[ok]
        dXdx = np.gradient(XP, dxe, axis=1)
        dXdy = np.gradient(XP, dxe, axis=0)
        dYdx = np.gradient(YP, dxe, axis=1)
        dYdy = np.gradient(YP, dxe, axis=0)
        jac = np.abs(dXdx * dYdy - dXdy * dYdx).ravel()[iv]
        good = ok & np.isfinite(jac) & (jac > 0)
        T = tr.intensity
        IP = np.where(good, I_e.ravel()[iv] * T / np.where(good, jac, 1.0), 0.0)
        if good.sum() < 16:
            raise SystemError_("Too few rays reach the exit of the system (beam clipped or outside the apertures)")
        P_lens = float((I_e.ravel()[iv] * T)[good].sum() * dxe * dxe)

        return dict(xP=xP, yP=yP, psi_P=psi_P, IP=IP, Dend=Dend, good=good, z_P=z_P, P_lens=P_lens, iv=iv, shape=I_e.shape, I_e=I_e, tr=tr, xe=xe, ye=ye)

    def fit(t):
        """Best-fit sphere of the exit wavefront and the residual (aberration) phase."""
        g = t["good"]
        xs_, ys_, w8 = t["xP"][g], t["yP"][g], t["IP"][g]
        A = np.stack([np.ones_like(xs_), xs_, ys_, xs_ * xs_ + ys_ * ys_], axis=1)
        coef, *_ = np.linalg.lstsq(A * np.sqrt(w8)[:, None], t["psi_P"][g] * np.sqrt(w8), rcond=None)
        return coef

    def residual_step(t, coef):
        """Largest change of the residual phase between neighbouring rays (rad), bright part of the beam."""
        g = t["good"]
        res = np.full(t["shape"], np.nan)
        ki_ = k0 * n_img
        if abs(coef[3]) > 1e-12:
            R_ = ki_ / (2 * coef[3])
            xc_, yc_ = -coef[1] / (2 * coef[3]), -coef[2] / (2 * coef[3])
            sph = math.copysign(1.0, R_) * ki_ * (np.sqrt((t["xP"] - xc_) ** 2 + (t["yP"] - yc_) ** 2 + R_ * R_) - abs(R_))
        else:
            sph = coef[1] * t["xP"] + coef[2] * t["yP"]
        bright = g & (t["IP"] > 1e-3 * t["IP"][g].max())
        res.ravel()[t["iv"][bright]] = (t["psi_P"] - sph)[bright]
        d0 = np.abs(np.diff(res, axis=0))
        d1 = np.abs(np.diff(res, axis=1))
        return float(max(np.nanmax(d0, initial=0.0), np.nanmax(d1, initial=0.0)))

    tr_ = transfer(Ue, xe, ye, ref_c)
    coef0 = fit(tr_)
    step0 = residual_step(tr_, coef0)
    refined = None
    if step0 > math.pi / 2 and grid < MAX_ENTRY:
        n2 = int(min(MAX_ENTRY, math.ceil(grid * step0 / (math.pi / 3))))
        Ue, xe, ye, ref_c, entry_method = make_entry(n2)
        tr_ = transfer(Ue, xe, ye, ref_c)
        refined = (grid, n2, step0)
        step1 = residual_step(tr_, fit(tr_))
        notes.append(f"Aberrated beam: the ray grid was refined from {grid} to {n2} per side (residual phase {step0:.2g} -> {step1:.2g} rad between rays)")
        if step1 > math.pi / 2:
            notes.append(f"The aberration is still undersampled ({step1:.2g} rad between rays at {n2} rays per side): the wave result is approximate; the geometric spot dominates")
    xP, yP, psi_P, IP, Dend, good, z_P, P_lens = (tr_[k] for k in ("xP", "yP", "psi_P", "IP", "Dend", "good", "z_P", "P_lens"))
    n_rays_side = len(xe)
    if _transfer_only:
        return {"Ue": Ue, "xe": xe, "ye": ye, "ref_c": ref_c, "z_e": z_e, "tr_": tr_, "src_info": src_info, "src_field": src_field, "notes": notes, "entry_method": entry_method, "P_entry": P_entry, "sd": sd, "wl": wl, "lam_um": lam_um, "n_obj": n_obj, "n_img": n_img, "j_last": j_last}

    # ---- exit plane: reference sphere (fitted), residual phase, regular grid
    xs_, ys_ = xP[good], yP[good]
    w8 = IP[good]  # irradiance at the exit points (the amplitude there)
    pw = (tr_["I_e"].ravel()[tr_["iv"]] * tr_["tr"].intensity)[good]  # power of each ray (regular entry grid)
    lam_i = lam0 / n_img
    ki = k0 * n_img
    A = np.stack([np.ones_like(xs_), xs_, ys_, xs_ * xs_ + ys_ * ys_], axis=1)
    coef, *_ = np.linalg.lstsq(A * np.sqrt(w8)[:, None], psi_P[good] * np.sqrt(w8), rcond=None)
    if abs(coef[3]) > 1e-12:
        R_s = ki / (2 * coef[3])  # > 0 diverging, < 0 converging
        xc, yc = -coef[1] / (2 * coef[3]), -coef[2] / (2 * coef[3])
    else:
        R_s, xc, yc = math.inf, 0.0, 0.0

    def sphere(X, Y):
        if not math.isfinite(R_s):
            return coef[1] * X + coef[2] * Y
        rho = np.sqrt((X - xc) ** 2 + (Y - yc) ** 2 + R_s * R_s)
        return math.copysign(1.0, R_s) * ki * (rho - abs(R_s))

    resid = psi_P[good] - sphere(xs_, ys_)
    resid -= float((w8 * resid).sum() / w8.sum())
    half_P = 1.02 * max(np.abs(xs_).max(), np.abs(ys_).max())
    wP = math.sqrt(float((pw * (xs_ * xs_ + ys_ * ys_)).sum() / pw.sum()))  # radial RMS radius
    z_img = float(cs.frames[n_s - 1].origin[2])
    z_t = z_img + float(target_offset)
    dz = z_t - z_P
    # the exact angular spectrum of the full field (sphere included) needs 0.45 lambda / sin at the
    # 99.99 % power radius; the Debye integral about the focus is used only for strongly converging
    # beams with a large Fresnel number whose full field cannot be sampled (it is approximate: about
    # 5 % in D4sigma at Fresnel number 13 and 0.7 mm from the focus, against the exact spectrum)
    fresnel_no = (wP * wP) / (lam_i * abs(R_s)) if math.isfinite(R_s) else math.inf
    sin_max = float(np.max(np.hypot(Dend[good, 0], Dend[good, 1])))
    r_all = np.hypot(xs_, ys_)
    order = np.argsort(r_all)
    cum = np.cumsum(pw[order]) / pw.sum()
    r99 = float(r_all[order][min(int(np.searchsorted(cum, 0.9999)), len(order) - 1)])
    sin99 = r99 / math.hypot(r99, R_s) if math.isfinite(R_s) else 0.0
    sin99 = max(sin99, math.hypot(coef[1], coef[2]) / ki)
    dx_need = 0.45 * lam_i / max(sin99, 1e-6)
    nP_need = max(n_rays_side, int(math.ceil(2 * half_P / dx_need)) + 1)
    debye_ok = bool(math.isfinite(R_s) and R_s < 0 and fresnel_no > 10 and abs(dz + R_s) < 0.5 * abs(R_s))
    debye = debye_ok and nP_need > MAX_EXIT
    if debye:
        nP = n_rays_side
    else:
        nP = nP_need
        if nP > MAX_EXIT:
            notes.append(f"Exit-plane sampling limited to {MAX_EXIT} points (the converging field needs {nP}); the outer pupil may alias")
            nP = MAX_EXIT
    xP_g = np.linspace(-half_P, half_P, nP)
    dxP = xP_g[1] - xP_g[0]
    XG, YG = np.meshgrid(xP_g, xP_g)
    # one triangulation of the exit points for amplitude and residual phase together
    lin = LinearNDInterpolator(Delaunay(np.stack([xs_, ys_], axis=1)), np.stack([np.sqrt(w8), resid], axis=1), fill_value=0.0)
    ar = np.nan_to_num(lin(XG, YG))
    amp, res = ar[..., 0], ar[..., 1]
    amp *= math.sqrt(P_lens / max(float((amp * amp).sum() * dxP * dxP), 1e-300))  # keep the traced power exactly
    bright = amp > 0.03 * amp.max()  # 1e-3 of the peak irradiance
    lit0 = bright[1:] & bright[:-1]
    lit1 = bright[:, 1:] & bright[:, :-1]
    step = max(float(np.abs(np.diff(res, axis=0))[lit0].max(initial=0.0)), float(np.abs(np.diff(res, axis=1))[lit1].max(initial=0.0)))
    if step > math.pi / 2:
        notes.append(f"The aberrated wavefront changes by up to {step:.2g} rad between exit samples: increase the grid")

    # output window: geometric footprint at the target plus diffraction
    xt_geo = xs_ + dz * Dend[good, 0] / Dend[good, 2]
    yt_geo = ys_ + dz * Dend[good, 1] / Dend[good, 2]
    cxg = float((pw * xt_geo).sum() / pw.sum())
    cyg = float((pw * yt_geo).sum() / pw.sum())
    rg = math.sqrt(float((pw * ((xt_geo - cxg) ** 2 + (yt_geo - cyg) ** 2)).sum() / pw.sum()))
    # embedded-Gaussian estimate of the diffraction spread: exit radius and wavefront curvature, q' = q + dz
    w_e = math.sqrt(2.0) * wP
    inv_q = (1 / R_s if math.isfinite(R_s) else 0.0) - 1j * lam_i / (math.pi * w_e * w_e)
    q2 = 1 / inv_q + dz
    w_gauss = math.sqrt(-lam_i / (math.pi * (1 / q2).imag))
    mode_half = 3.0 * _mode_radius(target_mode, lam_um) if target_mode else 0.0
    # radius holding 99.9 % of the geometric power (aberration halo) about the centroid
    rr_geo = np.hypot(xt_geo - cxg, yt_geo - cyg)
    o_ = np.argsort(rr_geo)
    c_ = np.cumsum(pw[o_]) / pw.sum()
    r999 = float(rr_geo[o_][min(int(np.searchsorted(c_, 0.999)), len(o_) - 1)])
    if out_window is None:
        # diffraction margin about the geometric footprint: a few spot sizes lambda / sin of a focused
        # beam, at most the embedded-Gaussian spread (a beam leaving the lens near its waist has almost
        # parallel rays, and lambda / sin would ask for a window far wider than the beam)
        half_o = max(2.5 * w_gauss, 1.15 * r999 + min(2 * lam_i / max(sin_max, 1e-3), 2.5 * w_gauss), mode_half, 2 * lam_i)
    else:
        half_o = 0.5 * float(out_window)
    # the irradiance is band-limited to 2 sin / lambda: sample it at lambda / (4 sin) (99.9 % of the
    # ray power) so that the power, moments and overlaps on the grid are exact sums
    s_all = np.hypot(Dend[good, 0], Dend[good, 1])
    o_s = np.argsort(s_all)
    sin_t = float(s_all[o_s][min(int(np.searchsorted(np.cumsum(pw[o_s]) / pw.sum(), 0.999)), len(o_s) - 1)])
    n_need = int(math.ceil(2 * half_o / (lam_i / (4 * max(sin_t, 1e-6))))) + 1
    if n_need > out_grid:
        if n_need > 512:
            notes.append(f"Target sampling limited to 512 points (the focused irradiance needs {n_need}): the peak irradiance is approximate")
        out_grid = min(n_need, 512) | 1  # odd: the profiles run through the centre
    if target_mode:
        c = target_mode.get("decenter", [0.0, 0.0])
        xo = np.linspace(-half_o, half_o, out_grid) + float(c[0])
        yo = np.linspace(-half_o, half_o, out_grid) + float(c[1])
    else:
        xo = np.linspace(cxg - half_o, cxg + half_o, out_grid)
        yo = np.linspace(cyg - half_o, cyg + half_o, out_grid)
    if debye:
        # a(s) on a regular grid of direction sines towards the sphere centre C = (xc, yc, z_P + |R|):
        # x1 = xc - sx rho, rho = |R| / sqrt(1 - s^2); a = U_res rho^2 / |R| (dsx dsy = R^2 / rho^4 dA)
        Rabs = abs(R_s)
        ex = np.array([-half_P - xc, half_P - xc, -half_P - yc, half_P - yc])
        smax = min(float(np.max(np.abs(ex) / np.sqrt(ex * ex + Rabs * Rabs))) * 1.02, 0.999)
        reach = max(abs(xo[0] - xc), abs(xo[-1] - xc), abs(yo[0] - yc), abs(yo[-1] - yc))
        ns_ = min(max(grid, int(math.ceil(2 * smax * ki * reach / math.pi * 1.3))), 1024)
        sg = np.linspace(-smax, smax, ns_)
        SX, SY = np.meshgrid(sg, sg)
        s2 = SX * SX + SY * SY
        inside = s2 < smax * smax
        rho = Rabs / np.sqrt(np.clip(1 - s2, 1e-9, None))
        X1, Y1 = xc - SX * rho, yc - SY * rho
        Ures = amp * np.exp(1j * res)
        ipr = RegularGridInterpolator((xP_g, xP_g), Ures.real, bounds_error=False, fill_value=0.0)
        ipi = RegularGridInterpolator((xP_g, xP_g), Ures.imag, bounds_error=False, fill_value=0.0)
        pts = np.stack([Y1.ravel(), X1.ravel()], axis=1)
        a = (ipr(pts) + 1j * ipi(pts)).reshape(SX.shape) * rho * rho / Rabs
        a = np.where(inside, a, 0.0)
        Zc = z_t - (z_P + Rabs)
        sz = np.sqrt(np.clip(1 - s2, 0, None))
        aZ = a * np.exp(1j * ki * (sz - 1) * Zc)
        ds = sg[1] - sg[0]
        Mx = np.exp(1j * ki * np.outer(xo - xc, sg))
        My = np.exp(1j * ki * np.outer(yo - yc, sg))
        Ut = -1j * ki / (2 * math.pi) * (My @ aZ @ Mx.T) * ds * ds
        debye_parts = (a, sz, sg, ds, Rabs)
        prop_method = f"Debye integral about the focus (reference sphere R = {Rabs:.4g} mm, Fresnel number {fresnel_no:.3g})"
    else:
        UP = amp * np.exp(1j * (sphere(XG, YG) + res))
        Ut = angular_spectrum(UP, xP_g, xP_g, lam_i, dz, xo, yo)
        debye_parts = None
        prop_method = "exact angular spectrum (matrix DFT)"
    P_t = power(Ut, xo, yo)
    mom = moments(Ut, xo, yo)
    I_t = np.abs(Ut) ** 2
    side = None
    if side_view:
        side = _side_view(
            cs=cs, wl=wl, j_last=j_last, tr_=tr_, src_field=src_field, z_e=z_e, z_P=z_P, z_t=z_t, lam_i=lam_i, ki=ki,
            amp=amp, res=res, xP_g=xP_g, sphere=sphere, debye_parts=debye_parts, xc=xc, yc=yc, n_cols=int(side_view_cols), cx=cxg,
        )
    out: dict = {
        "wavelength_um": lam_um,
        "source": src_info,
        "entry": {"z": z_e, "method": entry_method, "power": P_entry, "grid": n_rays_side, "window_mm": float(2 * xe[-1]), "refined_from": (refined[0] if refined else None)},
        "exit": {"z": z_P, "power": P_lens, "grid": nP, "window_mm": float(2 * half_P), "max_sin": sin_max, "sphere_radius_mm": (R_s if math.isfinite(R_s) else None), "fresnel_number": (fresnel_no if math.isfinite(fresnel_no) else None), "propagation": prop_method},
        "target": {
            "z": z_t,
            "offset_from_image": float(target_offset),
            "power": P_t,
            "centroid_mm": mom["centroid"],
            "d4sigma_mm": mom["d4sigma"],
            "peak_irradiance": float(I_t.max()),
            "x": xo.tolist(),
            "y": yo.tolist(),
            "irradiance": _down(I_t).tolist(),
            "map_x": _down_axis(xo).tolist(),
            "map_y": _down_axis(yo).tolist(),
            "phase": _down(np.angle(Ut), mean=False).tolist(),
            "profile_x": I_t[out_grid // 2].tolist(),
            "profile_y": I_t[:, out_grid // 2].tolist(),
        },
        "geometric_d4sigma_mm": 2 * math.sqrt(2) * rg,
        **({"side": side} if side is not None else {}),
        "notes": notes,
        "time_s": time.time() - t0,
        "method": "Scalar physical-optics propagation: source -> surface 1 by the asymptotic Rayleigh-Sommerfeld far field, the angular spectrum or the Fresnel transform; ray transfer through the lenses (phase k0 OPL, flux-conserving ray-tube amplitudes, Fresnel/coating transmission, clear apertures); to the target by the exact angular spectrum or, for strongly converging beams, the Debye integral about the focus",
    }
    if detector_radius:
        X, Y = np.meshgrid(xo, yo)
        inside = np.hypot(X - 0.0, Y - 0.0) <= float(detector_radius)
        out["target"]["power_in_radius"] = float(I_t[inside].sum() * (xo[1] - xo[0]) * (yo[1] - yo[0]))
        out["target"]["detector_radius"] = float(detector_radius)
        if half_o < detector_radius:
            notes.append("The output window is smaller than the detector radius: the power in the radius counts the window only")
    if target_mode:
        Mf = target_mode_field(target_mode, xo, yo, lam_um, lam_i)
        dA = (xo[1] - xo[0]) * (yo[1] - yo[0])
        ov = (Ut * np.conj(Mf)).sum() * dA
        nm = (np.abs(Mf) ** 2).sum() * dA
        eta = float(abs(ov) ** 2 / nm)
        out["coupling"] = {"mode": target_mode, "efficiency": eta, "efficiency_of_arriving": eta / P_t if P_t > 0 else 0.0, "efficiency_db": 10 * math.log10(eta) if eta > 0 else None}
    return out


def _fibre_indices(spec: dict, lam_um: float) -> tuple[float, float]:
    n2 = float(spec["n_clad"])
    if spec.get("n_core") is not None:
        return float(spec["n_core"]), n2
    na = float(spec["na"])
    return math.sqrt(n2 * n2 + na * na), n2


def _mode_radius(mode: dict, lam_um: float) -> float:
    if mode.get("kind", "gaussian") == "gaussian":
        return float(mode["waist"])
    n1, n2 = _fibre_indices(mode, lam_um)
    m = fibre_modes(lam_um, float(mode["core_radius_um"]), n1, n2, vector=False, profiles=0)
    return m["lp01"]["gaussian_waist"] * 1e-3


def target_mode_field(mode: dict, x: np.ndarray, y: np.ndarray, lam_um: float, lam_n: float) -> np.ndarray:
    """Mode to couple into, centred at mode['decenter'] (mm), its waist in the target plane."""
    c = mode.get("decenter", [0.0, 0.0])
    if mode.get("kind", "gaussian") == "gaussian":
        w = float(mode["waist"])
        return gaussian_field(x, y, w, w, 0.0, 0.0, lam_n, c[0], c[1])
    n1, n2 = _fibre_indices(mode, lam_um)
    U, _ = fibre_field(x, y, lam_um, float(mode["core_radius_um"]), n1, n2, c[0], c[1])
    return U


def _down(a: np.ndarray, n: int = 128, mean: bool = True) -> np.ndarray:
    if a.shape[0] <= n:
        return a
    f = int(math.ceil(a.shape[0] / n))
    m = (a.shape[0] // f) * f
    b = a[:m, :m]
    if mean:
        return b.reshape(m // f, f, m // f, f).mean(axis=(1, 3))
    return b[f // 2 :: f, f // 2 :: f]


def _down_axis(x: np.ndarray, n: int = 128) -> np.ndarray:
    """Coordinates of the cells of _down (block centres)."""
    if x.size <= n:
        return x
    f = int(math.ceil(x.size / n))
    m = (x.size // f) * f
    return x[:m].reshape(m // f, f).mean(axis=1)


def _side_view(*, cs, wl, j_last, tr_, src_field, z_e, z_P, z_t, lam_i, ki, amp, res, xP_g, sphere, debye_parts, xc, yc, n_cols, cx) -> dict:
    """|U|^2 on the meridional cut (x = centroid) along the whole system:
    * object space: the source field propagated to each plane (far field / angular spectrum / Fresnel);
    * inside the lens group: geometric intensity of the meridional rays (flux conservation of a
      rotationally symmetric beam, I = I_e T / ((y/y0) dy/dy0)), as the ray transfer;
    * image space: the exit field by the angular spectrum (one FFT) or, near the focus of a strongly
      converging beam, the Debye integral; elsewhere geometric.
    Irradiance in 1/mm^2 (source power 1)."""
    t0 = time.time()
    tr = tr_["tr"]
    good = tr_["good"]
    iv = tr_["iv"]
    xe, ye = tr_["xe"], tr_["ye"]
    nx = len(xe)
    jc = int(np.argmin(np.abs(xe - (src_field.get("xc", 0.0) if src_field else 0.0))))
    row = good & ((iv % nx) == jc)
    order = np.argsort(ye[iv[row] // nx])
    ridx = np.nonzero(row)[0][order]
    y0 = ye[iv[ridx] // nx]
    I0 = tr_["I_e"].ravel()[iv[ridx]]
    # ray paths: surface hits 1..j_last, then straight on with the final direction
    zs = [z_e] + [float(np.nanmedian(tr.points[ridx, j, 2])) for j in range(1, j_last + 1)]
    path_z = np.concatenate([np.full((len(ridx), 1), z_e), tr.points[ridx, 1 : j_last + 1, 2]], axis=1)
    path_y = np.concatenate([tr.start_points[ridx, 1:2], tr.points[ridx, 1 : j_last + 1, 1]], axis=1)
    inten = np.concatenate([np.ones((len(ridx), 1)), tr.intensity_after[ridx, 1 : j_last + 1]], axis=1)
    Dend = tr.dirs[ridx]

    def ray_y(z: float):
        """y and intensity factor of the meridional rays at plane z (geometric)."""
        n_v = path_z.shape[1]
        rows = np.arange(len(ridx))
        k = np.clip((path_z <= z).sum(axis=1) - 1, 0, n_v - 2)
        z0, z1 = path_z[rows, k], path_z[rows, k + 1]
        f = (z - z0) / np.maximum(z1 - z0, 1e-15)
        y = path_y[rows, k] + f * (path_y[rows, k + 1] - path_y[rows, k])
        T = inten[rows, k]
        beyond = z > path_z[:, -1]
        y = np.where(beyond, path_y[:, -1] + (z - path_z[:, -1]) * Dend[:, 1] / Dend[:, 2], y)
        T = np.where(beyond, inten[:, -1], T)
        return y, T

    def geometric(z: float, yl: np.ndarray) -> np.ndarray:
        y, T = ray_y(z)
        if len(y) < 3:
            return np.zeros_like(yl)
        dyd0 = np.gradient(y, y0)
        lat = np.where(np.abs(y0) > 1e-12, y / np.where(np.abs(y0) > 1e-12, y0, 1.0), dyd0)
        stretch = np.abs(lat * dyd0)
        I = np.where(stretch > 1e-12, I0 * T / np.maximum(stretch, 1e-12), 0.0)
        o = np.argsort(y)
        return np.interp(yl, y[o], I[o], left=0.0, right=0.0)

    # transverse line: the beam extent along the whole path
    ext = [float(np.nanmax(np.abs(ray_y(z)[0]))) for z in np.linspace(z_e, z_t, 25)]
    half = 1.15 * max(ext + [float(np.abs(ye[iv[ridx] // nx]).max())])
    ny = 220
    yl = np.linspace(-half, half, ny) + 0.0
    xl = np.array([cx if math.isfinite(cx) else 0.0])
    regions = []
    cols_z: list[float] = []
    cols: list[np.ndarray] = []
    L_obj = (z_e - src_field["z_src"]) if src_field else 0.0
    L_lens = z_P - z_e
    L_img = max(z_t - z_P, 0.0)
    tot = max(L_obj + L_lens + L_img, 1e-9)
    n_obj = max(24, int(n_cols * L_obj / tot)) if src_field else 0
    n_lens = max(16, int(n_cols * L_lens / tot))
    n_img = max(24, int(n_cols * L_img / tot)) if L_img > 0 else 0

    if src_field:
        zz, cc, kinds = object_columns(src_field, z_e, yl, n_obj, L_obj)
        cols_z += zz
        cols += cc
        regions.append({"z0": src_field["z_src"], "z1": z_e, "method": "source to surface 1: " + ", ".join(kinds), "kind": "wave"})
    for z in np.linspace(z_e, z_P, n_lens):
        cols_z.append(float(z))
        cols.append(geometric(float(z), yl))
    regions.append({"z0": z_e, "z1": z_P, "method": "inside the lens group: geometric (ray transfer)", "kind": "geometric"})
    if n_img:
        if debye_parts is None:
            XG, YG = np.meshgrid(xP_g, xP_g)
            UP = amp * np.exp(1j * (sphere(XG, YG) + res))
            prop = AngularSpectrum(UP, xP_g, xP_g, xl, yl)
            for z in np.linspace(z_P, z_t, n_img):
                cols_z.append(float(z))
                cols.append(np.abs(prop.at(lam_i, z - z_P, xl, yl)[:, 0]) ** 2)
            regions.append({"z0": z_P, "z1": z_t, "method": "exit to target: exact angular spectrum", "kind": "wave"})
        else:
            a, sz, sg, ds, Rabs = debye_parts
            zc = z_P + Rabs
            n_geo = n_deb = 0
            Mx = np.exp(1j * ki * np.outer(xl - xc, sg))
            spot = lam_i / (math.pi * max(float(sg[-1]), 1e-6))  # diffraction-limited radius scale
            period = 2 * math.pi / (ki * ds)  # the Debye sum repeats with this period in y
            for z in np.linspace(z_P, z_t, n_img):
                cols_z.append(float(z))
                yg, _ = ray_y(float(z))
                halfw = 1.2 * float(np.nanmax(np.abs(yg - yc))) + 4 * spot
                if abs(z - zc) < 0.5 * Rabs and 2 * halfw < 0.9 * period:
                    aZ = a * np.exp(1j * ki * (sz - 1) * (z - zc))

                    def deb(y, aZ=aZ):
                        My = np.exp(1j * ki * np.outer(y - yc, sg))
                        return np.abs((-1j * ki / (2 * math.pi) * (My @ aZ @ Mx.T) * ds * ds)[:, 0]) ** 2

                    cols.append(_sampled(yl, yc, halfw, deb))
                    n_deb += 1
                else:
                    cols.append(geometric(float(z), yl))
                    n_geo += 1
            regions.append({"z0": z_P, "z1": z_t, "method": "exit to target: " + ("Debye integral near the focus" if n_deb else "") + (", geometric further away" if n_geo else ""), "kind": "wave"})
    M = np.array(cols).T  # (ny, nz)
    surfaces = [{"z": float(z)} for z in zs[1:]]
    return {
        "z": cols_z,
        "y": yl.tolist(),
        "irradiance": M.tolist(),
        "regions": regions,
        "surfaces_z": [s["z"] for s in surfaces],
        "source_z": src_field.get("z_src") if src_field else None,
        "entry_z": z_e,
        "exit_z": z_P,
        "target_z": z_t,
        "time_s": time.time() - t0,
    }


def _sampled(yl: np.ndarray, yc: float, half: float, fn) -> np.ndarray:
    """Irradiance on the display rows yl of a beam centred at yc within +-half: evaluated on the rows
    where the beam is wide, or on a fine local grid averaged over each row's bin where it is
    narrower than the row spacing (a narrow beam does not fall between rows)."""
    dy = yl[1] - yl[0]
    out = np.zeros(len(yl))
    if 2 * half / 64 < dy:
        yf = np.linspace(yc - half, yc + half, 96)
        If = fn(yf)
        edges = np.concatenate([yl - dy / 2, [yl[-1] + dy / 2]])
        out += np.histogram(yf, bins=edges, weights=If * (yf[1] - yf[0]))[0] / dy
    else:
        sel = np.abs(yl - yc) <= half + dy
        if sel.any():
            out[sel] = fn(yl[sel])
    return out


def object_columns(src_field: dict, z_e: float, yl: np.ndarray, n_cols: int, L_obj: float):
    """Side-view columns between the source plane and surface 1: the source field propagated to
    each plane (far field / angular spectrum / Fresnel) on the meridional line yl (x = centre)."""
    Us, xs, lam_n = src_field["U"], src_field["x"], src_field["lam_n"]
    ws, zR, z_src = src_field["ws"], src_field["zR"], src_field["z_src"]
    z_f = src_field.get("z_field", z_src)  # plane of the sampled field (a Gaussian's waist, possibly after z_src)
    x_src = np.array([src_field["xc"]])
    kinds: dict = {}
    zz, cc = [], []
    for z in np.linspace(z_src + 1e-3 * L_obj, z_e, n_cols):
        # distance from the sampled field; in front of a real waist field |U(-d)| = |U(d)|
        Dz = abs(z - z_f)
        w = gaussian_q(ws, Dz, lam_n)[0]
        if Dz > 20 * zR:
            fn, m = far_field, "far field"
        elif Dz < 2 * zR:
            fn, m = angular_spectrum, "angular spectrum"
        else:
            fn, m = fresnel, "Fresnel"
        cc.append(_sampled(yl, src_field["yc"], 4.0 * w, lambda y, fn=fn, Dz=Dz: np.abs(fn(Us, xs, xs, lam_n, Dz, x_src, y)[:, 0]) ** 2))
        kinds[m] = kinds.get(m, 0) + 1
        zz.append(float(z))
    return zz, cc, kinds


def field_source(source: dict, grid: int) -> tuple[np.ndarray, np.ndarray, float]:
    """A rotationally symmetric complex field U(r) (r_um, re, im; e.g. the co-polarised field exported
    by the rotationally symmetric FDTD) sampled on a square grid, normalised to power 1."""
    r = np.asarray(source["r_um"], float) * 1e-3
    u = np.asarray(source["re"], float) + 1j * np.asarray(source["im"], float)
    if r.size < 4 or r.size != u.size:
        raise SystemError_("The imported field needs matching r, re and im samples")
    I = np.abs(u) ** 2
    cum = np.cumsum(I * r)
    if cum[-1] <= 0:
        raise SystemError_("The imported field is zero")
    r_max = float(r[min(int(np.searchsorted(cum / cum[-1], 0.99999)), r.size - 1)]) * 1.25
    r_max = min(max(r_max, 4 * (r[1] - r[0])), float(r[-1]))
    xs = np.linspace(-r_max, r_max, grid)
    X, Y = np.meshgrid(xs, xs)
    R = np.hypot(X, Y)
    U = np.interp(R, r, u.real, right=0.0) + 1j * np.interp(R, r, u.imag, right=0.0)
    p = float(source.get("power", 1.0))
    U /= math.sqrt(power(U, xs, xs))
    return U, xs, p
