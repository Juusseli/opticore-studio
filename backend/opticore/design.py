"""Starting prescriptions for a first lens (the guided "First lens" setup).

Both designs start from closed-form thin-lens solutions and are then made thick:

* Singlet: Coddington's best-form bending for an object at infinity, the shape factor
  of minimum third-order spherical aberration,
      q = (c1 + c2) / (c1 - c2) = 2 (n^2 - 1) / (n + 2),
  with c1 - c2 = phi / (n - 1) (thin-lens lensmaker equation).
* Cemented doublet: the thin-lens achromat condition phi1/V1 + phi2/V2 = 0 with
  phi1 + phi2 = phi, i.e. phi1 = phi V1/(V1 - V2), phi2 = -phi V2/(V1 - V2), where
  V = (n_p - 1)/(n_s - n_l) at the system's primary, shortest and longest wavelengths;
  equiconvex crown, the flint shares the cemented radius.

Thickening: centre thicknesses give at least the minimum edge thickness at the clear
semi-diameter; then every curvature is scaled by one common factor so that the exact
paraxial EFL of the thick lens equals the target (secant iteration), and the image
surface is placed at the paraxial back focus. The stop is the first lens surface.

These are starting points, not optimised designs; the project also carries a merit
function (RMS spot, EFL, edge thickness and, for the doublet, axial colour) and variables
(radii, image distance) so it can be optimised directly.
"""

from __future__ import annotations

import math
from typing import Literal

from .materials import MaterialLibrary
from .model import OpticalSystem
from .optimize.merit import OptimizationSpec
from .paraxial import paraxial_data
from .project import Metadata, Project
from .system import compile_system


class DesignError(ValueError):
    pass


def best_form_shape_factor(n: float) -> float:
    """Coddington shape factor of minimum spherical aberration for an object at infinity."""
    return 2.0 * (n * n - 1.0) / (n + 2.0)


def achromat_powers(phi: float, v1: float, v2: float) -> tuple[float, float]:
    """Thin-lens powers of a cemented achromat (phi1/V1 + phi2/V2 = 0, phi1 + phi2 = phi)."""
    if v1 <= v2:
        raise DesignError(f"The crown glass needs a higher Abbe number than the flint (V1 = {v1:.2f}, V2 = {v2:.2f})")
    return phi * v1 / (v1 - v2), -phi * v2 / (v1 - v2)


def _sag(c: float, h: float) -> float:
    x = c * c * h * h
    if x >= 1.0:
        raise DesignError("The aperture is too large for these curvatures: choose a larger F/# or a longer focal length")
    return c * h * h / (1.0 + math.sqrt(1.0 - x))


def _system(curv: list[float], thick: list[float], mats: list[str], wavelengths: list[float], primary: int, epd: float, fields: list[float], bfd: float) -> OpticalSystem:
    surfaces: list[dict] = [{"id": "obj", "label": "Object", "thickness": None}]
    labels = ["Front", "Back"] if len(curv) == 2 else ["Crown front", "Cemented", "Flint back"]
    ids = ["s1", "s2", "s3"]
    for k, c in enumerate(curv):
        last = k == len(curv) - 1
        surfaces.append(
            {
                "id": ids[k],
                "label": labels[k],
                "radius": (1.0 / c) if c != 0 else None,
                "thickness": bfd if last else thick[k],
                "material": "AIR" if last else mats[k],
                "is_stop": k == 0,
            }
        )
    surfaces.append({"id": "img", "label": "Image"})
    return OpticalSystem.model_validate(
        {
            "name": "First lens",
            "surfaces": surfaces,
            "wavelengths": [{"value": w, "weight": 1.0} for w in wavelengths],
            "primary_wavelength": primary,
            "fields": [{"y": f} for f in fields],
            "aperture": {"type": "epd", "value": epd},
        }
    )


def first_lens(
    focal_length: float,
    f_number: float,
    half_field_deg: float,
    wavelengths: list[float],
    primary: int,
    kind: Literal["singlet", "doublet"] = "singlet",
    crown: str = "N-BK7",
    flint: str = "F2",
    custom_materials: list[dict] | None = None,
    name: str | None = None,
) -> tuple[Project, dict]:
    """Starting prescription and project for a lens of the given focal length, F/# and field."""
    if not wavelengths or not 0 <= primary < len(wavelengths):
        raise DesignError("Give at least one wavelength and a valid primary wavelength")
    custom = list(custom_materials or [])
    lib = MaterialLibrary(custom)
    for g in [crown] + ([flint] if kind == "doublet" else []):
        if not lib.has(g):
            raise DesignError(f"Unknown glass '{g}'")
    lp, ls, ll = wavelengths[primary], min(wavelengths), max(wavelengths)
    phi = 1.0 / focal_length
    epd = focal_length / f_number
    h = 0.5 * epd * 1.05  # clear semi-diameter at the lens (stop at the first surface) with 5 % margin
    e_min = max(1.0, 0.04 * 2 * h)  # minimum edge thickness, mm
    t_min = max(1.0, 0.03 * 2 * h)  # minimum centre thickness, mm
    n1 = lib.index(crown, lp)
    notes: list[str] = []
    info: dict = {"focal_length": focal_length, "f_number": f_number, "epd": epd, "min_edge_thickness": e_min}
    if kind == "singlet":
        q = best_form_shape_factor(n1)
        c1 = phi * (q + 1.0) / (2.0 * (n1 - 1.0))
        c2 = phi * (q - 1.0) / (2.0 * (n1 - 1.0))
        curv0 = [c1, c2]
        mats = [crown]
        info.update({"shape_factor": q, "index": n1, "thin_curvatures": curv0})
    else:
        if len(wavelengths) < 2 or ls == ll:
            raise DesignError("An achromat needs at least two wavelengths")
        n2 = lib.index(flint, lp)
        v1 = (n1 - 1.0) / (lib.index(crown, ls) - lib.index(crown, ll))
        v2 = (n2 - 1.0) / (lib.index(flint, ls) - lib.index(flint, ll))
        p1, p2 = achromat_powers(phi, v1, v2)
        # equiconvex crown: c1 = -c2 = phi1 / (2 (n1 - 1)); flint: phi2 = (n2 - 1)(c2 - c3)
        c1 = p1 / (2.0 * (n1 - 1.0))
        c2 = -c1
        c3 = c2 - p2 / (n2 - 1.0)
        curv0 = [c1, c2, c3]
        mats = [crown, flint]
        info.update({"phi1": p1, "phi2": p2, "abbe": [v1, v2], "index": [n1, n2], "thin_curvatures": curv0})
    hfov = max(0.0, float(half_field_deg))
    fields = [0.0] if hfov == 0 else [0.0, round(0.7 * hfov, 6), hfov]

    def thicknesses(curv: list[float]) -> list[float]:
        out = []
        for k in range(len(curv) - 1):
            # edge = t + sag(back) - sag(front) >= e_min
            t = max(t_min, e_min - (_sag(curv[k + 1], h) - _sag(curv[k], h)))
            out.append(t)
        return out

    def efl(curv: list[float], thick: list[float]) -> float:
        cs = compile_system(_system(curv, thick, mats, wavelengths, primary, epd, fields, focal_length), custom)
        f = paraxial_data(cs, primary).efl
        if f is None or not math.isfinite(f):
            raise DesignError("The starting lens is afocal")
        return f

    def solve_scale(thick: list[float], s: float) -> float:
        """Common curvature scale giving EFL = focal_length for fixed thicknesses (secant on 1/EFL)."""
        s0, s1 = s, s * 1.001
        g0 = 1.0 / efl([c * s0 for c in curv0], thick) - phi
        for _ in range(40):
            g1 = 1.0 / efl([c * s1 for c in curv0], thick) - phi
            if abs(g1) <= 1e-14 * phi or g1 == g0:
                break
            s0, s1, g0 = s1, s1 - g1 * (s1 - s0) / (g1 - g0), g1
        return s1

    # thicknesses follow the curvatures and the scale follows the thicknesses: a few rounds converge
    scale, thick = 1.0, thicknesses(curv0)
    for _ in range(10):
        scale = solve_scale(thick, scale)
        nxt = thicknesses([c * scale for c in curv0])
        if max(abs(a - b) for a, b in zip(nxt, thick)) < 1e-9:
            break
        thick = nxt
    scale = solve_scale(thick, scale)
    curv = [c * scale for c in curv0]
    sys0 = _system(curv, thick, mats, wavelengths, primary, epd, fields, focal_length)
    pd = paraxial_data(compile_system(sys0, custom), primary)
    bfd = pd.bfl if pd.bfl is not None and pd.bfl > 0 else focal_length
    system = _system(curv, thick, mats, wavelengths, primary, epd, fields, bfd)
    info.update({"curvatures": curv, "thicknesses": thick, "back_focus": bfd, "efl": efl(curv, thick)})
    if f_number < 2.5 and kind == "singlet":
        notes.append("Fast single lenses have large spherical aberration; consider a doublet or optimise the bending")

    lens_ids = ["s1", "s2", "s3"][: len(curv)]
    cmax = 10.0 / focal_length
    variables = [{"surface_id": i, "parameter": "curvature", "min": -cmax, "max": cmax} for i in lens_ids]
    variables.append({"surface_id": lens_ids[-1], "parameter": "thickness", "min": 0.5 * bfd, "max": 1.5 * bfd})
    operands = [
        {"type": "rms_spot", "target": 0.0, "weight": 1.0, "rings": 4},
        {"type": "efl", "target": focal_length, "weight": 1.0},
    ]
    operands += [{"type": "min_edge_thickness", "surface_id": i, "target": e_min, "weight": 1.0} for i in lens_ids[:-1]]
    f_line, c_line = 0.4861327, 0.6562725
    if kind == "doublet" and ls <= f_line + 1e-9 and ll >= c_line - 1e-9:
        operands.append({"type": "axial_color", "target": 0.0, "weight": 0.05})
    spec = OptimizationSpec.model_validate({"variables": variables, "operands": operands, "algorithm": "local", "max_evaluations": 2000})
    title = name or (f"Singlet f = {focal_length:g} mm F/{f_number:g}" if kind == "singlet" else f"Achromat f = {focal_length:g} mm F/{f_number:g}")
    desc = (
        f"{'Best-form ' + crown + ' singlet' if kind == 'singlet' else 'Cemented ' + crown + '/' + flint + ' achromat'}: thin-lens start made thick for EFL = {focal_length:g} mm, "
        f"EPD {epd:.4g} mm (F/{f_number:g}), half field {hfov:g} deg."
    )
    used = {m.upper() for m in mats}
    project = Project(metadata=Metadata(name=title, description=desc), system=system, optimization=spec, custom_materials=[r for r in custom if str(r.get("name", "")).upper() in used])
    return project, {"notes": notes, "design": info}
