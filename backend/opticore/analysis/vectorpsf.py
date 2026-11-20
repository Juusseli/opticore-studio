"""Vector point spread function (Debye–Wolf / Richards–Wolf; docs/OPTICAL_ENGINE.md §8m).

In the Debye approximation the focal field near the image point C is a superposition of plane waves, one per
direction s of the converging beam:

    E(X) = C0 ∫∫ a(s) exp(i k s·(X - C)) dΩ,   k = 2π n' / λ,

with a(s) the vector strength factor on the reference sphere. Energy conservation through a pupil element
dA (unit input irradiance) gives |a|^2 dΩ = |E_out|^2 dA with E_out the power-normalised output field of
the ray (3D polarisation ray tracing, polarization.py: Fresnel and coating amplitudes, crystals, ideal
polarisers and retarders), and dΩ = |J| dA / s_z with J = ∂(s_x, s_y)/∂(p_x, p_y) the Jacobian of the
pupil-to-direction map. Hence

    E(X) = C0 Σ_q w_q E_out,q sqrt(|J_q| / s_z,q) exp(i k0 OPL_q) exp(i k s_q·(X - C)),

summed over a Gaussian quadrature of the entrance pupil (weights w_q, rings in ρ², equally spaced arms).
OPL_q is the ray's optical path to the reference sphere about C (wavefront.py), so aberrations enter as
phases; |J| comes from central differences of traced rays. For an aplanatic system (sin θ = NA ρ) this is
exactly the Richards–Wolf integral with its √cos θ apodisation. The sum over q is separable in x and y,
E = M_x^T diag(c) M_y, so maps cost one matrix product per component.

Valid when the Fresnel number of the focus is large (Debye) and in a homogeneous image medium; the field is
the time-harmonic electric field, I = |Ex|^2 + |Ey|^2 + |Ez|^2 (electric energy density, not the Poynting
flux along z).
"""

from __future__ import annotations

import math

import numpy as np

from ..paraxial import compute_pupil
from ..polarization import INPUT_STATES, _transverse_basis, crystal_owners, polarization_matrices, summed_matrices
from ..raytrace import gauss_pupil, launch, trace
from ..system import CompiledSystem, NotApplicable, SystemError_
from .wavefront import opl_to_reference, reference_geometry

VECTOR_INPUTS = tuple(INPUT_STATES) + ("radial", "azimuthal")


def debye_focus(s: np.ndarray, a: np.ndarray, k: float, xs: np.ndarray, ys: np.ndarray, z: float = 0.0) -> np.ndarray:
    """Field components (3, ny, nx) at (x, y, z) relative to C of plane waves with unit directions s (n, 3)
    and complex vector weights a (n, 3) (strength factor × quadrature weight × path phase)."""
    c = a * np.exp(1j * k * s[:, 2] * z)[:, None]
    Mx = np.exp(1j * k * np.outer(s[:, 0], xs))  # (n, nx)
    My = np.exp(1j * k * np.outer(s[:, 1], ys))  # (n, ny)
    return np.stack([My.T @ (c[:, i][:, None] * Mx) for i in range(3)])


def debye_xz(s: np.ndarray, a: np.ndarray, k: float, xs: np.ndarray, zs: np.ndarray) -> np.ndarray:
    """Field components (3, nz, nx) in the x-z plane through C (y = 0)."""
    Mx = np.exp(1j * k * np.outer(s[:, 0], xs))
    Mz = np.exp(1j * k * np.outer(s[:, 2], zs))
    return np.stack([Mz.T @ (a[:, i][:, None] * Mx) for i in range(3)])


def _input_jones(state: str, px: np.ndarray, py: np.ndarray) -> np.ndarray:
    if state in INPUT_STATES:
        return np.tile(INPUT_STATES[state], (len(px), 1))
    rho = np.hypot(px, py)
    rho = np.where(rho > 0, rho, 1.0)
    if state == "radial":
        return np.stack([px / rho, py / rho], axis=1).astype(complex)
    if state == "azimuthal":
        return np.stack([-py / rho, px / rho], axis=1).astype(complex)
    raise ValueError(f"Unknown input polarisation '{state}'")


def _fwhm(x: np.ndarray, I: np.ndarray) -> float | None:
    """Full width at half maximum of a profile about its peak (linear interpolation)."""
    k = int(np.argmax(I))
    h = 0.5 * I[k]
    lo = k
    while lo > 0 and I[lo] > h:
        lo -= 1
    hi = k
    while hi < len(I) - 1 and I[hi] > h:
        hi += 1
    if I[lo] > h or I[hi] > h:
        return None
    xl = x[lo] + (h - I[lo]) * (x[lo + 1] - x[lo]) / (I[lo + 1] - I[lo])
    xh = x[hi - 1] + (h - I[hi - 1]) * (x[hi] - x[hi - 1]) / (I[hi] - I[hi - 1])
    return float(xh - xl)


def pupil_field(cs: CompiledSystem, field: int = 0, wavelength: int | None = None, input_state: str = "x", rings: int = 40, arms: int | None = None, crystal_modes: str = "sum", gaussian_fill: float | None = None) -> dict:
    """Directions, strength factors and phases of the converging beam (module notes), in image-local coordinates."""
    if input_state not in VECTOR_INPUTS:
        raise ValueError(f"Unknown input polarisation '{input_state}'")
    wl = cs.wl_index(wavelength)
    from .diffraction import _working_fnum

    _working_fnum(cs, wl)  # an afocal or collimated image space has no focus: NotApplicable
    pupil = compute_pupil(cs, cs.model.primary_wavelength)  # the aperture at the primary wavelength, as every launch uses
    C, Eref, R, _, n_img = reference_geometry(cs, wl, field, pupil)
    if Eref is None:
        raise NotApplicable("Exit pupil at infinity (image-space telecentric): the Debye focus needs a converging reference sphere")
    px, py, w = gauss_pupil(rings, arms or 2 * rings + 8)
    P0, D0, _ = launch(cs, wl, field, px, py, pupil)
    use_sum = crystal_modes == "sum" and crystal_owners(cs)
    m = summed_matrices(cs, wl, P0, D0) if use_sum else polarization_matrices(cs, wl, P0, D0)
    res = m["trace"]
    ok = m["ok"] & res.ok
    img = cs.n_surfaces - 1
    fr = cs.frames[img]
    # input field in the object-space basis of each ray -> 3D
    xi, yi = _transverse_basis(m["k_in"])
    Jin = _input_jones(input_state, px, py)
    if gaussian_fill:
        Jin = Jin * np.exp(-(px * px + py * py) / gaussian_fill**2)[:, None]
    E3 = Jin[:, 0:1] * xi + Jin[:, 1:2] * yi
    Eout = fr.to_local_dirs(np.einsum("nij,nj->ni", np.nan_to_num(m["P"]), E3))
    s = fr.to_local_dirs(res.dirs)
    opl = opl_to_reference(cs, res, C, Eref, R, n_img)
    ok &= np.isfinite(opl)
    # Jacobian of the pupil -> direction-cosine map by central differences (unclipped rays)
    h = 1e-4
    sx = {}
    for key, (dx, dy) in {"xp": (h, 0), "xm": (-h, 0), "yp": (0, h), "ym": (0, -h)}.items():
        Pd, Dd, _ = launch(cs, wl, field, px + dx, py + dy, pupil)
        rd = trace(cs, wl, Pd, Dd, clip=False)
        sx[key] = fr.to_local_dirs(rd.dirs)
        ok &= rd.ok
    J = ((sx["xp"][:, 0] - sx["xm"][:, 0]) * (sx["yp"][:, 1] - sx["ym"][:, 1]) - (sx["xp"][:, 1] - sx["xm"][:, 1]) * (sx["yp"][:, 0] - sx["ym"][:, 0])) / (4 * h * h)
    sz = s[:, 2]
    good = ok & (sz * np.sign(np.nanmedian(sz[ok])) > 0)
    lam_mm = float(cs.wavelengths[wl]) * 1e-3
    k0 = 2 * math.pi / lam_mm
    amp = np.sqrt(np.abs(J) / np.abs(sz))
    phase = np.exp(1j * k0 * (opl - np.nanmean(opl[good])))
    a = np.zeros((len(px), 3), dtype=complex)
    a[good] = (w[good] * amp[good] * phase[good])[:, None] * Eout[good]
    a0 = np.zeros_like(a)
    a0[good] = (w[good] * amp[good])[:, None] * Eout[good]
    # image-space NA from the real marginal rays (angle to the chief ray), not from the quadrature nodes
    mx = np.array([1.0, -1.0, 0.0, 0.0])
    my = np.array([0.0, 0.0, 1.0, -1.0])
    Pm, Dm, _ = launch(cs, wl, field, np.append(mx, 0.0), np.append(my, 0.0), pupil)
    rm = trace(cs, wl, Pm, Dm, clip=False)
    dm = fr.to_local_dirs(rm.dirs)
    if rm.ok.all():
        sin_max = float(np.mean(np.linalg.norm(np.cross(dm[:4], dm[4]), axis=1)))
    else:
        sin_max = float(np.nanmax(np.hypot(s[good, 0], s[good, 1]))) if good.any() else 0.0
    return {
        "s": np.where(good[:, None], s, 0.0),
        "a": a,
        "a_ideal": a0,
        "k": k0 * n_img,
        "lambda_um": float(cs.wavelengths[wl]),
        "n_img": n_img,
        "C": C,
        "good": good,
        "na": n_img * sin_max,
        "transmission": float((w[good] * np.einsum("ij,ij->i", Eout[good], np.conj(Eout[good])).real).sum()),
        "vignetted": float(w[~good].sum()),
        "crystal_sum": bool(use_sum),
    }


def vector_psf(cs: CompiledSystem, field: int = 0, wavelength: int | None = None, input_state: str = "x", rings: int = 40, grid: int = 81, half_width_um: float | None = None, defocus_um: float = 0.0, section: bool = True, crystal_modes: str = "sum", gaussian_fill: float | None = None) -> dict:
    """Vector PSF maps and metrics of one field and wavelength (module notes)."""
    pf = pupil_field(cs, field, wavelength, input_state, rings, None, crystal_modes, gaussian_fill)
    lam_mm = pf["lambda_um"] * 1e-3
    na = max(pf["na"], 1e-6)
    h_mm = (half_width_um * 1e-3) if half_width_um else 2.0 * lam_mm / na
    xs = np.linspace(-h_mm, h_mm, grid)
    z = defocus_um * 1e-3
    s, a, k = pf["s"], pf["a"], pf["k"]
    E = debye_focus(s, a, k, xs, xs, z)
    I = (np.abs(E) ** 2).sum(axis=0)
    E0 = debye_focus(s, pf["a_ideal"], k, xs, xs, z)
    I0max = float((np.abs(E0) ** 2).sum(axis=0).max())
    peak = float(I.max())
    if not peak > 0:
        raise SystemError_("No light reaches the focus (all rays vignetted or blocked)")
    iy, ix = np.unravel_index(int(np.argmax(I)), I.shape)
    comps = np.abs(E) ** 2
    # fine evaluation about the peak for widths and the half-maximum area
    xp, yp = float(xs[ix]), float(xs[iy])
    hf = min(h_mm, 1.2 * lam_mm / na)
    nf = 241
    xf = np.linspace(-hf, hf, nf)
    Ef = debye_focus(s, a * np.exp(1j * k * (s[:, 0] * xp + s[:, 1] * yp))[:, None], k, xf, xf, z)
    If = (np.abs(Ef) ** 2).sum(axis=0)
    c = nf // 2
    fx = _fwhm(xf, If[c, :])
    fy = _fwhm(xf, If[:, c])
    area = float((If >= 0.5 * If.max()).sum() * (xf[1] - xf[0]) ** 2)
    lam_img_mm = lam_mm / pf["n_img"]
    tot = comps.sum(axis=(1, 2))
    um = 1e3
    out = {
        "field": field,
        "wavelength_um": pf["lambda_um"],
        "input": input_state,
        "na": pf["na"],
        "n_image": pf["n_img"],
        "x_um": (xs * um).tolist(),
        "intensity": (I / peak).tolist(),
        "components": {name: (comps[i] / peak).tolist() for i, name in enumerate(("x", "y", "z"))},
        "profile_x": {"x_um": (xs * um).tolist(), "total": (I[iy, :] / peak).tolist(), "x": (comps[0][iy, :] / peak).tolist(), "y": (comps[1][iy, :] / peak).tolist(), "z": (comps[2][iy, :] / peak).tolist()},
        "profile_y": {"x_um": (xs * um).tolist(), "total": (I[:, ix] / peak).tolist(), "x": (comps[0][:, ix] / peak).tolist(), "y": (comps[1][:, ix] / peak).tolist(), "z": (comps[2][:, ix] / peak).tolist()},
        "peak_um": [xp * um, yp * um],
        "fwhm_x_um": None if fx is None else fx * um,
        "fwhm_y_um": None if fy is None else fy * um,
        "fwhm_x_waves": None if fx is None else fx / lam_img_mm,
        "fwhm_y_waves": None if fy is None else fy / lam_img_mm,
        "half_max_area_um2": area * um * um,
        "half_max_area_waves2": area / lam_img_mm**2,
        "energy_fraction": {name: float(tot[i] / tot.sum()) for i, name in enumerate(("x", "y", "z"))},
        "strehl": peak / I0max if I0max > 0 else None,
        "scalar_airy_fwhm_um": 0.5145 * lam_mm / na * um,
        "transmission": pf["transmission"],
        "vignetted_fraction": pf["vignetted"],
        "defocus_um": defocus_um,
        "samples": int(pf["good"].sum()),
        "units": {"coordinates": "µm in the image surface frame, from the chief-ray image point", "intensity": "|E|^2 relative to the peak"},
    }
    if section:
        zh = 2.0 * lam_mm / (na * na) if na < 0.99 else 2.0 * lam_mm
        zs = np.linspace(-zh, zh, grid) + z
        Exz = debye_xz(s, a, k, xs, zs)
        Ixz = (np.abs(Exz) ** 2).sum(axis=0)
        out["section"] = {"x_um": (xs * um).tolist(), "z_um": (zs * um).tolist(), "intensity": (Ixz / Ixz.max()).tolist()}
    out["method"] = (
        "Debye–Wolf vector diffraction: plane waves of the real rays (3D polarisation ray tracing: Fresnel, coatings"
        + (", both waves of the crystals" if pf["crystal_sum"] else "")
        + ", polarising elements) with amplitudes sqrt(|J|/s_z) from the pupil-to-direction Jacobian and phases from the optical path to the reference sphere; "
        f"Gaussian pupil quadrature ({rings} rings, {pf['samples'] if 'samples' in pf else int(pf['good'].sum())} rays); I = |Ex|² + |Ey|² + |Ez|²"
    )
    return out
