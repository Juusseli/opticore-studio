"""Paraxial Gaussian-beam propagation (complex beam parameter, ABCD).

The beam is described by the reduced complex beam parameter q^ = q / |n|,
with q = z + i z_R in a medium of index n (z measured from the waist along
the propagation direction, z_R = pi |n| w0^2 / lambda_eff). It transforms
with the same reduced ray matrices as the y-nu paraxial trace on the
unfolded axis:

    transfer   [[1, tau], [0, 1]],  tau = t / n_signed  (>= 0 along the beam)
    surface    [[1, 0], [-phi, 1]], phi = (n2 - n1) c   (signed indices; a
                                                         mirror has n2 = -n1)
                                         + |n| / f       (ideal lens of focal length f)
                                         + DOE paraxial power
    q^' = (A q^ + B) / (C q^ + D)

and the beam follows from 1/q^ = |n| / R - i lambda_eff / (pi w^2):

    w^2 = -lambda_eff / (pi Im(1/q^)),  R = |n| / Re(1/q^)  (R > 0: diverging)

lambda_eff = M^2 lambda_0 (embedded-Gaussian model of a multimode beam: w is
the real second-moment radius, the waist-divergence product is M^2 times
the Gaussian value).

Assumptions: paraxial, rotationally symmetric (stigmatic) beam on the
unfolded axis; coordinate breaks and tilted mirrors are unfolded, so the
astigmatism of off-axis or tilted elements is not modelled; aberrations,
aperture truncation and diffraction from clipping are ignored (the
transmitted fraction 1 - exp(-2 a^2 / w^2) of a centred circular aperture of
semi-diameter a is reported for information only). Validated in
tests/test_gaussian.py against free-space propagation, Self's thick-lens
waist transformation and mirror focusing, and in tests/test_wave_regressions.py
against Self's thin-lens transformation through an ideal lens.
"""

from __future__ import annotations

import math

import numpy as np

from ..system import CompiledSystem, NotApplicable, SystemError_


def _beam(qh: complex, lam_mm: float, n_abs: float) -> tuple[float, float | None]:
    inv = 1.0 / qh
    w = math.sqrt(-lam_mm / (math.pi * inv.imag))
    R = n_abs / inv.real if abs(inv.real) > 1e-300 else None
    return w, R


def gaussian_beam(
    cs: CompiledSystem,
    waist_radius: float,
    waist_distance: float,
    wavelength: int | None = None,
    m2: float = 1.0,
    samples: int = 60,
    semi_diameters: list[float] | None = None,
) -> dict:
    """Propagate a beam whose waist (1/e^2 radius `waist_radius`, mm) lies
    `waist_distance` mm before surface 1 (negative: virtual waist behind it)
    in object space."""
    if not (waist_radius > 0 and math.isfinite(waist_radius)):
        raise SystemError_("Waist radius must be positive")
    if m2 < 1.0:
        raise SystemError_("M² must be >= 1")
    wl = cs.wl_index(wavelength)
    lam0_mm = float(cs.wavelengths[wl]) * 1e-3
    lam = lam0_mm * m2
    surfs = cs.model.surfaces
    n_s = cs.n_surfaces
    ns = cs.n_signed[wl]
    nabs = np.abs(ns)

    zR0 = math.pi * nabs[0] * waist_radius**2 / lam
    qh = complex(waist_distance, zR0) / nabs[0]  # at surface 1 (before refraction)

    # unfolded axial coordinate of each surface (surface 1 at z = 0)
    zpos = [0.0] * n_s
    for j in range(1, n_s):
        zpos[j] = 0.0 if j == 1 else zpos[j - 1] + abs(surfs[j - 1].thickness or 0.0)

    z_curve: list[float] = []
    w_curve: list[float] = []
    segs: list[dict] = []
    at_surfaces: list[dict] = []

    def sample_segment(q_start: complex, z0: float, length: float, n_abs: float, seg_index: int, extend_to_waist: bool = False):
        """Sample w(z) along a homogeneous segment of physical length `length`."""
        a = q_start.real
        s_waist = -a * n_abs  # physical distance from the segment start to the waist
        L = length
        if extend_to_waist and s_waist > L:
            zr = q_start.imag * n_abs
            L = s_waist + max(zr, 0.1 * max(L, 1e-9))
        k = max(2, samples)
        ss = np.linspace(0.0, L, k) if L > 0 else np.array([0.0])
        if 0 < s_waist < L:
            ss = np.sort(np.append(ss, s_waist))
        for s in ss:
            w, _ = _beam(q_start + s / n_abs, lam, n_abs)
            z_curve.append(z0 + float(s))
            w_curve.append(w)
        w0 = math.sqrt(lam * q_start.imag / math.pi)
        segs.append(
            {
                "after_surface": seg_index,
                "index": float(n_abs),
                "length": float(length),
                "waist_from_start": float(s_waist),
                "waist_inside": bool(0.0 <= s_waist <= length),
                "waist_radius": w0,
                "rayleigh_range": float(q_start.imag * n_abs),
            }
        )
        z_curve.append(math.nan)  # break between segments in the plot
        w_curve.append(math.nan)

    # object space: from the waist (if real, in front of surface 1) to surface 1
    if waist_distance > 0:
        sample_segment(complex(0.0, zR0) / nabs[0], -waist_distance, waist_distance, nabs[0], 0)

    for j in range(1, n_s):
        w_in, R_in = _beam(qh, lam, nabs[j - 1])
        if j == n_s - 1:
            at_surfaces.append({"surface": j, "w": w_in, "R_in": R_in, "R_out": R_in})
            break
        c = cs.shapes[j].curvature if not cs.is_cb[j] else 0.0
        phi = (ns[j] - ns[j - 1]) * c
        if cs.does and cs.does[j] is not None:
            phi += cs.does[j].paraxial_power(float(cs.wavelengths[wl]) * 1e-3)
        if cs.ideal and cs.ideal[j] is not None:
            # ideal lens of focal length f in a medium n: phi = |n| / f, as in paraxial.trace_paraxial
            phi += nabs[j - 1] * cs.ideal[j].inv_f
        # surface matrix [[1,0],[-phi,1]]: q' = q / (1 - phi q)
        qh = qh / (1.0 - phi * qh)
        w_out, R_out = _beam(qh, lam, nabs[j])
        row = {"surface": j, "w": w_in, "R_in": R_in, "R_out": R_out}
        if semi_diameters is not None and j < len(semi_diameters) and not cs.is_cb[j]:
            a = semi_diameters[j]
            row["semi_diameter"] = a
            row["clip_transmission"] = float(1.0 - math.exp(-2.0 * a * a / (w_in * w_in))) if a > 0 else 0.0
        at_surfaces.append(row)
        t = surfs[j].thickness or 0.0
        tau = t / ns[j]
        if tau < -1e-12:
            raise NotApplicable(f"Surface {j}: thickness sign inconsistent with the propagation direction (Gaussian beam needs a sequential axial path)")
        sample_segment(qh, zpos[j], abs(t), nabs[j], j, extend_to_waist=(j == n_s - 2))
        qh = qh + tau

    # image space: segment after the last optical surface
    last = n_s - 2
    img_seg = segs[-1]
    t_last = surfs[last].thickness or 0.0
    w_img, R_img = _beam(qh, lam, nabs[last])
    n_img = nabs[last]
    w0_img = img_seg["waist_radius"]
    zR_img = img_seg["rayleigh_range"]
    image = {
        "waist_radius": w0_img,
        "waist_from_last_surface": img_seg["waist_from_start"],
        "waist_from_image_surface": img_seg["waist_from_start"] - abs(t_last),
        "rayleigh_range": zR_img,
        "divergence_half_angle_mrad": lam / (math.pi * n_img * w0_img) * 1e3,
        "depth_of_focus": 2 * zR_img,
        "w_at_image_surface": w_img,
        "R_at_image_surface": R_img,
        "index": float(n_img),
    }
    obj = {
        "waist_radius": waist_radius,
        "waist_distance": waist_distance,
        "rayleigh_range": zR0,
        "divergence_half_angle_mrad": lam / (math.pi * nabs[0] * waist_radius) * 1e3,
        "index": float(nabs[0]),
    }
    notes = []
    if not cs.axial:
        notes.append("Coordinate breaks are unfolded: astigmatism from tilted or decentred elements is not modelled.")
    clipped = [r for r in at_surfaces if r.get("clip_transmission") is not None and r["clip_transmission"] < 0.99]
    if clipped:
        notes.append(
            "Beam radius approaches the aperture at surface(s) "
            + ", ".join(str(r["surface"]) for r in clipped)
            + " (<99 % transmitted); truncation and its diffraction are not modelled."
        )
    if m2 > 1:
        notes.append(f"Embedded-Gaussian model with M² = {m2:g} (λ_eff = M² λ).")
    return {
        "wavelength_um": float(cs.wavelengths[wl]),
        "m2": m2,
        "object": obj,
        "image": image,
        "surfaces": at_surfaces,
        "segments": segs,
        "curve": {"z": z_curve, "w": w_curve},
        "surface_z": zpos,
        "notes": notes,
        "units": {"length": "mm", "w": "mm (1/e² intensity radius)", "divergence": "mrad (half angle, far field)"},
        "method": "Paraxial complex-beam-parameter (ABCD) propagation on the unfolded axis in reduced coordinates; stigmatic beam; no aberrations or aperture truncation",
    }
