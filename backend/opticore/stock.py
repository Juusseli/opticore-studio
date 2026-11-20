"""Stock lenses: purchasable singlets and cemented doublets as fixed prescriptions.

A stock lens is a short list of surfaces (front to back): radii (None = flat), centre thicknesses, glasses,
the mechanical diameter and the clear aperture. It enters a design as surfaces with fixed clear semi-diameters
(rays outside the clear aperture are clipped) and the mechanical semi-diameter, labelled with its part.

Sources:

* **Generic library** (`materials/data/stock_generic.json`, written by `python -m opticore.tools.make_stock_library`):
  OptiCore's own lenses at standard focal lengths and diameters, not any vendor's part. Rules, all at the d line
  (587.56 nm), every focal length exact (radius solved by the thick-lens EFL):
  * singlet forms: plano-convex, equi-bi-convex, best form (Coddington, object at infinity), positive meniscus
    (shape factor 2), plano-concave, equi-bi-concave;
  * positive singlets: edge thickness max(1 mm, 0.07 D) at the rim, centre thickness from the sags;
    negative singlets: centre thickness max(1.5 mm, 0.12 D);
  * a surface may not be steeper than |R| = 0.55 D, and D <= |f| <= 40 D;
  * glasses and forms: N-BK7 in every form; UV fused silica plano and bi-convex and concave; N-SF11 and CaF2
    plano-convex and plano-concave;
  * cemented achromats (N-BAF10/N-SF6, N-BK7/SF2, N-SK16/N-SF5), 12.7 to 50.8 mm, f >= 20 mm and >= 1.2 D: crown
    in front, optimised by OptiCore's optimiser for an object at infinity (F, d, C; fields 0 and 1 deg; aperture
    min(0.9 D, f/3); RMS spot and crown edge). The last curvature is an F/# solve (f / aperture), so the focal
    length is exact for every trial design, and the two front curvatures and the image distance are optimised
    until the solver converges (at most MAX_ACHROMAT_EVALUATIONS; a lens that does not converge is left out).
    With the focal length as a weighted goal instead, the runs end on a 600-evaluation budget in a long curved
    valley and the design depends on finite-difference details (ADR-044). The crown's centre thickness comes from
    its thin-lens start with the edge max(1 mm, 0.05 D) and the flint's is max(1.5 mm, 0.1 D); one common radius
    scale then removes the solve's last rounding of the focal length;
  * clear aperture 90 % of the diameter; no price (generic parts have none).
* **Vendor ZMX files** the user downloads (one lens per file), and a **CSV** format for one's own stock. Both are
  converted here statelessly; the browser keeps the catalogues (like glass catalogues, ADR-015).

Paraxial data use reduced 2 x 2 matrices on (y, n u) from the front vertex to the back vertex, in air:
refraction [[1, 0], [-(n' - n)/R, 1]], transfer [[1, t/n], [0, 1]]; EFL = -1/C, back focal distance -A/C from the
back vertex, front focal distance D/C from the front vertex, rear principal plane (1 - A)/C from the back vertex and
front principal plane (D - 1)/C from the front vertex. A reversed lens has its radii in reverse order with
opposite signs.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from functools import lru_cache
from importlib import resources
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .materials import MaterialError, MaterialLibrary

StockKind = Literal["plano_convex", "biconvex", "best_form", "meniscus", "plano_concave", "biconcave", "achromat", "other"]
LAMBDA_D = 0.5875618
GENERIC = "Generic"


class StockError(ValueError):
    pass


class StockLens(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part: str = Field(min_length=1, max_length=80)
    vendor: str = ""
    catalog: str = ""
    kind: StockKind = "other"
    radii: list[float | None] = Field(min_length=2, max_length=4, description="front to back, mm; null = flat")
    thicknesses: list[float] = Field(min_length=1, max_length=3, description="centre thicknesses, mm")
    materials: list[str] = Field(min_length=1, max_length=3)
    diameter: float = Field(gt=0.0, le=1000.0, description="mechanical diameter, mm")
    clear_diameter: float | None = Field(default=None, gt=0.0, description="clear aperture, mm (null = 90 % of the diameter)")
    focal_length: float | None = Field(default=None, description="nominal focal length from the source, mm (informative)")
    price: float | None = Field(default=None, ge=0.0)
    currency: str = ""
    source: str = ""

    @model_validator(mode="after")
    def _check(self):
        n = len(self.radii)
        if len(self.thicknesses) != n - 1 or len(self.materials) != n - 1:
            raise ValueError("a lens with n surfaces needs n - 1 thicknesses and materials")
        if any(not (t > 0.0 and math.isfinite(t)) for t in self.thicknesses):
            raise ValueError("centre thicknesses must be positive")
        if any(r is not None and (r == 0.0 or not math.isfinite(r)) for r in self.radii):
            raise ValueError("radii must be finite and non-zero (null for flat)")
        if any(m.strip().upper() in ("", "AIR", "VACUUM", "MIRROR") for m in self.materials):
            raise ValueError("every element needs a glass")
        if self.clear_diameter is not None and self.clear_diameter > self.diameter + 1e-9:
            raise ValueError("the clear aperture cannot exceed the diameter")
        return self

    @property
    def clear(self) -> float:
        return self.clear_diameter if self.clear_diameter is not None else 0.9 * self.diameter

    @property
    def key(self) -> str:
        return f"{self.catalog}:{self.part}" if self.catalog else self.part


# ---------------------------------------------------------------------------------------------- paraxial data
def oriented(lens: StockLens, reversed_: bool) -> tuple[list[float | None], list[float], list[str]]:
    """Radii, thicknesses and glasses in the order light meets them."""
    if not reversed_:
        return list(lens.radii), list(lens.thicknesses), list(lens.materials)
    return [(-r if r is not None else None) for r in lens.radii[::-1]], lens.thicknesses[::-1], lens.materials[::-1]


def lens_matrix(lens: StockLens, lib: MaterialLibrary, wavelength_um: float, reversed_: bool = False) -> np.ndarray:
    """Reduced paraxial matrix [[A, B], [C, D]] from the front vertex to the back vertex (in air)."""
    radii, thick, mats = oriented(lens, reversed_)
    ns = [1.0] + [lib.index(m, wavelength_um) for m in mats] + [1.0]
    M = np.eye(2)
    for k, r in enumerate(radii):
        phi = 0.0 if r is None else (ns[k + 1] - ns[k]) / r
        M = np.array([[1.0, 0.0], [-phi, 1.0]]) @ M
        if k < len(thick):
            M = np.array([[1.0, thick[k] / ns[k + 1]], [0.0, 1.0]]) @ M
    return M


def lens_paraxial(lens: StockLens, lib: MaterialLibrary, wavelength_um: float = LAMBDA_D, reversed_: bool = False) -> dict:
    """EFL, focal distances and principal planes of a stock lens (module docstring)."""
    (A, B), (C, D) = lens_matrix(lens, lib, wavelength_um, reversed_)
    if abs(C) < 1e-15:
        return {"efl": None, "bfd": None, "ffd": None, "rear_principal": None, "front_principal": None, "length": float(sum(lens.thicknesses))}
    return {
        "efl": -1.0 / C,
        "bfd": -A / C,
        "ffd": D / C,
        "rear_principal": (1.0 - A) / C,
        "front_principal": (D - 1.0) / C,
        "length": float(sum(lens.thicknesses)),
    }


def describe(lens: StockLens, custom_materials=()) -> dict:
    """Lens record plus its paraxial data at the d line (for the catalogue view)."""
    lib = MaterialLibrary(list(custom_materials))
    try:
        p = lens_paraxial(lens, lib)
    except MaterialError as exc:
        p = {"error": str(exc)}
    return {**lens.model_dump(mode="json"), "clear": lens.clear, "key": lens.key, "paraxial": p}


# ---------------------------------------------------------------------------------------------- surfaces in a design
def lens_surfaces(lens: StockLens, reversed_: bool, gap_after: float, start_id: str, stop_first: bool = False) -> list[dict]:
    """The lens as design surfaces: fixed clear semi-diameters, the mechanical semi-diameter, the part in the labels."""
    radii, thick, mats = oriented(lens, reversed_)
    name = f"{lens.vendor} {lens.part}".strip()
    comment = f"Stock lens {name}" + (f" ({lens.catalog})" if lens.catalog else "") + (", reversed" if reversed_ else "")
    out = []
    n = len(radii)
    for k, r in enumerate(radii):
        label = f"{lens.part} front" if k == 0 else (f"{lens.part} back" if k == n - 1 else f"{lens.part} cemented")
        out.append(
            {
                "id": f"{start_id}{k}",
                "label": label,
                "comment": comment,
                "radius": r,
                "thickness": thick[k] if k < n - 1 else gap_after,
                "material": mats[k] if k < n - 1 else "AIR",
                "semi_diameter": lens.clear / 2.0,
                "semi_diameter_mode": "fixed",
                "mech_semi_diameter": lens.diameter / 2.0,
                "is_stop": stop_first and k == 0,
            }
        )
    return out


# ---------------------------------------------------------------------------------------------- generic library
GENERIC_SINGLET_FORMS = {
    "N-BK7": ("plano_convex", "biconvex", "best_form", "meniscus", "plano_concave", "biconcave"),
    "FUSED_SILICA": ("plano_convex", "biconvex", "plano_concave", "biconcave"),
    "N-SF11": ("plano_convex", "plano_concave"),
    "CAF2": ("plano_convex", "plano_concave"),
}
GENERIC_ACHROMATS = (("N-BAF10", "N-SF6"), ("N-BK7", "SF2"), ("N-SK16", "N-SF5"))
GENERIC_DIAMETERS = (6.0, 12.7, 25.4, 50.8)
POSITIVE_F = (10, 15, 20, 25, 30, 35, 40, 50, 60, 75, 100, 125, 150, 200, 250, 300, 400, 500, 750, 1000)
NEGATIVE_F = (-10, -15, -20, -25, -30, -40, -50, -75, -100, -150, -200, -250, -300, -500)
GLASS_CODE = {"N-BK7": "BK7", "FUSED_SILICA": "FS", "N-SF11": "SF11", "CAF2": "CAF2", "N-BAF10": "BAF10", "N-SF6": "SF6", "SF2": "SF2", "N-SK16": "SK16", "N-SF5": "SF5"}
KIND_CODE = {"plano_convex": "PCX", "biconvex": "BCX", "best_form": "BFM", "meniscus": "PMN", "plano_concave": "PCV", "biconcave": "BCV", "achromat": "ACH"}


def _sag(r: float | None, h: float) -> float:
    if r is None:
        return 0.0
    c = 1.0 / r
    x = c * c * h * h
    if x >= 1.0:
        raise StockError("aperture beyond the sphere")
    return c * h * h / (1.0 + math.sqrt(1.0 - x))


def _singlet_shape(kind: str, n: float) -> tuple[float, float]:
    """Curvatures (c1, c2) per unit thin-lens power phi = 1 for each singlet kind."""
    k = 1.0 / (n - 1.0)
    if kind in ("plano_convex", "plano_concave"):
        return k, 0.0
    if kind in ("biconvex", "biconcave"):
        return 0.5 * k, -0.5 * k
    q = 2.0 * (n * n - 1.0) / (n + 2.0) if kind == "best_form" else 2.0  # Coddington shape factor
    return 0.5 * k * (q + 1.0), 0.5 * k * (q - 1.0)


def generic_singlet(kind: str, glass: str, f: float, D: float, lib: MaterialLibrary) -> StockLens | None:
    """One generic singlet with its exact focal length, or None when the rules exclude it (module docstring)."""
    if not (D <= abs(f) <= 40.0 * D):
        return None
    n = lib.index(glass, LAMBDA_D)
    u1, u2 = _singlet_shape(kind, n)
    positive = f > 0
    h = D / 2.0

    def build(scale: float, t: float) -> StockLens:
        c1, c2 = u1 * scale, u2 * scale
        return StockLens(
            part="x", kind=kind, radii=[1.0 / c1 if c1 else None, 1.0 / c2 if c2 else None], thicknesses=[t], materials=[glass], diameter=D
        )

    def thickness(scale: float) -> float:
        c1, c2 = u1 * scale, u2 * scale
        r1, r2 = (1.0 / c1 if c1 else None), (1.0 / c2 if c2 else None)
        for r in (r1, r2):
            if r is not None and abs(r) < 0.55 * D:
                raise StockError("too steep")
        if positive:
            return max(1.0, 0.07 * D) + _sag(r1, h) - _sag(r2, h)
        return max(1.5, 0.12 * D)

    scale = 1.0 / f
    try:
        for _ in range(60):  # thickness follows the curvature; secant on 1/EFL
            t = thickness(scale)
            s0, s1 = scale, scale * 1.001
            g0 = 1.0 / lens_paraxial(build(s0, t), lib)["efl"] - 1.0 / f
            for _ in range(50):
                g1 = 1.0 / lens_paraxial(build(s1, t), lib)["efl"] - 1.0 / f
                if g1 == g0 or abs(g1) < 1e-15 / abs(f):
                    break
                s0, s1, g0 = s1, s1 - g1 * (s1 - s0) / (g1 - g0), g1
            if abs(thickness(s1) - t) < 1e-12:
                scale = s1
                break
            scale = s1
        t = thickness(scale)
        if positive and t - (_sag(build(scale, t).radii[0], h) - _sag(build(scale, t).radii[1], h)) < max(1.0, 0.07 * D) - 1e-9:
            return None
    except StockError:
        return None
    lens = build(float(scale), float(t))
    sign = "" if positive else "-"
    part = f"G-{KIND_CODE[kind]}-{GLASS_CODE[glass]}-{sign}{abs(f):g}-{D:g}"
    return lens.model_copy(update={"part": part, "vendor": "OptiCore", "catalog": GENERIC, "focal_length": float(f), "source": "OptiCore generic (rules in stock.py)"})


MAX_ACHROMAT_EVALUATIONS = 3000


def generic_achromat(crown: str, flint: str, f: float, D: float, lib: MaterialLibrary) -> StockLens | None:
    """A generic cemented achromat optimised for an object at infinity (module docstring)."""
    from .design import achromat_powers
    from .model import OpticalSystem
    from .optimize.engine import optimize
    from .optimize.merit import OptimizationSpec

    if not (1.2 * D <= f <= 40.0 * D):
        return None
    lF, ld, lC = 0.4861327, LAMBDA_D, 0.6562725
    n1, n2 = lib.index(crown, ld), lib.index(flint, ld)
    v1 = (n1 - 1.0) / (lib.index(crown, lF) - lib.index(crown, lC))
    v2 = (n2 - 1.0) / (lib.index(flint, lF) - lib.index(flint, lC))
    p1, p2 = achromat_powers(1.0 / f, v1, v2)
    c1 = p1 / (2.0 * (n1 - 1.0))
    c2 = -c1
    c3 = c2 - p2 / (n2 - 1.0)
    h = D / 2.0
    t2 = max(1.5, 0.1 * D)
    e1 = max(1.0, 0.05 * D)
    try:
        t1 = e1 + _sag(1.0 / c1, h) - _sag(1.0 / c2, h)
    except StockError:
        return None
    epd = min(0.9 * D, f / 3.0)
    sysd = {
        "name": "achromat",
        "surfaces": [
            {"id": "obj", "thickness": None},
            {"id": "a1", "radius": 1.0 / c1, "thickness": t1, "material": crown, "is_stop": True},
            {"id": "a2", "radius": 1.0 / c2, "thickness": t2, "material": flint},
            # the focal length by construction: image-space F/# = f / aperture for an object at infinity
            {"id": "a3", "radius": 1.0 / c3, "thickness": f, "curvature_solve": {"type": "f_number", "target": f / epd}},
            {"id": "img"},
        ],
        "wavelengths": [{"value": lF}, {"value": ld}, {"value": lC}],
        "primary_wavelength": 1,
        "fields": [{"y": 0.0}, {"y": 1.0}],
        "aperture": {"type": "epd", "value": epd},
    }
    system = OpticalSystem.model_validate(sysd)
    cmax = 12.0 / f
    spec = OptimizationSpec.model_validate(
        {
            "variables": [{"surface_id": s, "parameter": "curvature", "min": -cmax, "max": cmax} for s in ("a1", "a2")]
            + [{"surface_id": "a3", "parameter": "thickness", "min": 0.3 * f, "max": 1.5 * f}],
            "operands": [
                {"type": "rms_spot", "rings": 4},
                {"type": "min_edge_thickness", "surface_id": "a1", "target": e1, "weight": 1.0},
            ],
            "algorithm": "local",
            "max_evaluations": MAX_ACHROMAT_EVALUATIONS,
            # the stored generic library (stock_generic.json) is generated with the weighted merit function (the edge a
            # penalty, checked below), so the data stay reproducible
            "constraints": "penalty",
        }
    )
    # always in this process: on the pool the run can end on a different design, and the stored library must be
    # reproduced whatever the machine's load (engine.optimize)
    res = optimize(system, spec, parallel=False)
    if res["status"] != "converged":
        return None
    from .solves import freeze_solves

    s = freeze_solves(OpticalSystem.model_validate(res["system"])).model_dump()["surfaces"]
    radii = [s[1]["radius"], s[2]["radius"], s[3]["radius"]]
    if any(r is None or abs(r) < 0.55 * D for r in radii):
        return None
    lens = StockLens(part="x", kind="achromat", radii=[float(r) for r in radii], thicknesses=[float(t1), float(t2)], materials=[crown, flint], diameter=D)
    # exact focal length: one common curvature scale (the optimiser met it to its tolerance)
    for _ in range(30):
        efl = lens_paraxial(lens, lib)["efl"]
        if abs(efl - f) < 1e-12 * f:
            break
        k = f / efl  # radii scale with the focal length
        lens = lens.model_copy(update={"radii": [float(r * k) for r in lens.radii]})
    try:
        edge = lens.thicknesses[0] + _sag(lens.radii[1], h) - _sag(lens.radii[0], h)
    except StockError:
        return None
    if edge < e1 - 0.05:
        return None
    part = f"G-ACH-{GLASS_CODE[crown]}-{GLASS_CODE[flint]}-{f:g}-{D:g}"
    return lens.model_copy(update={"part": part, "vendor": "OptiCore", "catalog": GENERIC, "focal_length": float(f), "source": "OptiCore generic (rules in stock.py)"})


def make_generic_library(achromats: bool = True) -> list[StockLens]:
    """Every generic lens (deterministic; the achromats take about a minute)."""
    lib = MaterialLibrary()
    out: list[StockLens] = []
    for glass, forms in GENERIC_SINGLET_FORMS.items():
        for D in GENERIC_DIAMETERS:
            for kind in forms:
                if kind in ("best_form", "meniscus") and D < 25.4:
                    continue
                for f in NEGATIVE_F if kind in ("plano_concave", "biconcave") else POSITIVE_F:
                    lens = generic_singlet(kind, glass, float(f), D, lib)
                    if lens:
                        out.append(lens)
    if achromats:
        for crown, flint in GENERIC_ACHROMATS:
            for D in GENERIC_DIAMETERS[1:]:
                for f in POSITIVE_F:
                    if f < 20:
                        continue
                    lens = generic_achromat(crown, flint, float(f), D, lib)
                    if lens:
                        out.append(lens)
    return out


@lru_cache(maxsize=1)
def _generic_json() -> tuple[dict, ...]:
    raw = resources.files("opticore.materials").joinpath("data/stock_generic.json").read_text("utf-8")
    return tuple(json.loads(raw)["lenses"])


def generic_library() -> list[StockLens]:
    return [StockLens.model_validate(d) for d in _generic_json()]


# ---------------------------------------------------------------------------------------------- import
_PART_FROM_FILE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9.\-+]*?)(?:[-_ ](?:zemax|zmx).*)?$", re.IGNORECASE)


def _part_from_filename(filename: str) -> str:
    stem = re.sub(r"\.zmx$", "", filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1], flags=re.IGNORECASE)
    stem = re.sub(r"\(zmx\)", "", stem, flags=re.IGNORECASE).strip(" -_")
    m = _PART_FROM_FILE.match(stem)
    return (m.group(1) if m else stem)[:80] or "lens"


def _mema(text: str) -> dict[int, float]:
    """Mechanical semi-apertures (MEMA) per surface number: the ZMX reader does not keep them."""
    out, cur = {}, None
    for raw in text.replace("\r", "\n").split("\n"):
        parts = raw.split()
        if not parts:
            continue
        if parts[0].upper() == "SURF" and len(parts) > 1:
            try:
                cur = int(parts[1])
            except ValueError:
                cur = None
        elif parts[0].upper() == "MEMA" and cur is not None and raw[:1] in (" ", "\t") and len(parts) > 1:
            try:
                out[cur] = float(parts[1])
            except ValueError:
                pass
    return out


def lens_from_zmx(text: str, filename: str, catalog: str, vendor: str = "", catalog_materials=()) -> tuple[StockLens, list[dict], list[dict]]:
    """A stock lens from a vendor's ZMX file: the first run of glass surfaces (a singlet or a cemented group).
    Returns the lens, the custom glass records it needs (from the user's catalogues) and diagnostics."""
    from .io.zmx import parse_zmx

    project, diags = parse_zmx(text, filename, list(catalog_materials))
    d = [x.as_dict() for x in diags]
    surfs = project.system.surfaces
    missing = [x for x in d if x["status"] == "missing_material"]
    if missing:
        raise StockError("; ".join(x["message"] for x in missing))
    glass = [i for i, s in enumerate(surfs[:-1]) if s.material.upper() not in ("AIR", "", "VACUUM", "MIRROR") and s.type == "standard"]
    if not glass:
        raise StockError("No lens (glass between standard surfaces) in the file")
    a = glass[0]
    b = a
    while b + 1 < len(surfs) - 1 and surfs[b + 1].material.upper() not in ("AIR", "", "VACUUM", "MIRROR"):
        b += 1
    back = b + 1
    if back > len(surfs) - 1:
        raise StockError("The lens has no back surface")
    if len(glass) > back - a:
        d.append({"status": "partial", "message": "The file holds more than one lens; the first one was imported", "surface": None, "line": None})
    if any(s.type != "standard" or s.conic != 0.0 for s in surfs[a : back + 1]):
        raise StockError("Only spherical stock lenses are supported (the file has an asphere or another surface type)")
    radii = [s.radius for s in surfs[a : back + 1]]
    thick = [float(s.thickness or 0.0) for s in surfs[a:back]]
    mats = [s.material for s in surfs[a:back]]
    mema = _mema(text)
    semi = [float(s.semi_diameter) for s in surfs[a : back + 1]]
    mech = [mema.get(i) for i in range(a, back + 1)]
    D = 2.0 * max([m for m in mech if m] or semi)
    clear = min(2.0 * max(semi), D)
    part = _part_from_filename(filename)
    used = {m.upper() for m in mats}
    custom = [r for r in project.custom_materials if str(r.get("name", "")).upper() in used]
    lens = StockLens(
        part=part,
        vendor=vendor,
        catalog=catalog,
        kind="achromat" if len(mats) == 2 else "other",
        radii=radii,
        thicknesses=thick,
        materials=mats,
        diameter=D,
        clear_diameter=clear,
        source=filename,
    )
    if lens.kind == "other":
        lens = lens.model_copy(update={"kind": classify(lens)})
    return lens, custom, d


def classify(lens: StockLens) -> StockKind:
    if len(lens.materials) == 2:
        return "achromat"
    if len(lens.materials) != 1:
        return "other"
    r1, r2 = lens.radii
    c1 = 0.0 if r1 is None else 1.0 / r1
    c2 = 0.0 if r2 is None else 1.0 / r2
    power = c1 - c2
    if power == 0.0:
        return "other"
    flat = c1 == 0.0 or c2 == 0.0
    if power > 0:
        return "plano_convex" if flat else ("biconvex" if c1 > 0 > c2 else "meniscus")
    return "plano_concave" if flat else ("biconcave" if c1 < 0 < c2 else "other")


CSV_COLUMNS = ("part", "vendor", "diameter", "clear_diameter", "focal_length", "price", "currency", "r1", "t1", "glass1", "r2", "t2", "glass2", "r3")


def lenses_from_csv(text: str, catalog: str) -> tuple[list[StockLens], list[dict]]:
    """Stock lenses from CSV (header row with the columns of CSV_COLUMNS; r* in mm, 'inf' or empty for flat; a
    singlet leaves t2, glass2 and r3 empty). Malformed rows are reported with their line numbers."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or not {"part", "diameter", "r1", "t1", "glass1", "r2"} <= {f.strip().lower() for f in reader.fieldnames}:
        raise StockError("CSV header needs at least: part, diameter, r1, t1, glass1, r2 (see FILE_FORMATS.md)")
    out, diags = [], []
    for ln, row in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if not any(row.values()):
            continue

        def num(k: str, required: bool = False) -> float | None:
            v = row.get(k, "")
            if v == "" and not required:
                return None
            return float(v)

        def radius(k: str) -> float | None:
            v = row.get(k, "").lower()
            return None if v in ("", "inf", "infinity", "flat") else float(v)

        try:
            radii = [radius("r1"), radius("r2")]
            thick = [num("t1", True)]
            mats = [row["glass1"]]
            if row.get("glass2"):
                radii.append(radius("r3"))
                thick.append(num("t2", True))
                mats.append(row["glass2"])
            lens = StockLens(
                part=row["part"],
                vendor=row.get("vendor", ""),
                catalog=catalog,
                radii=radii,
                thicknesses=thick,
                materials=mats,
                diameter=num("diameter", True),
                clear_diameter=num("clear_diameter"),
                focal_length=num("focal_length"),
                price=num("price"),
                currency=row.get("currency", ""),
                source="CSV",
            )
            out.append(lens.model_copy(update={"kind": classify(lens)}))
        except (ValueError, TypeError, KeyError) as exc:
            msg = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            diags.append({"status": "error", "message": f"Line {ln}: {msg}", "line": ln})
    if not out and not diags:
        raise StockError("The CSV file has no lens rows")
    return out, diags


def check_glasses(lenses: list[StockLens], custom_materials=()) -> list[str]:
    """Glasses of the lenses that the library cannot resolve."""
    lib = MaterialLibrary(list(custom_materials))
    return sorted({m for l in lenses for m in l.materials if not lib.has(m)})
