"""Generate the built-in coating library (materials/data/builtin_coatings.json).

Generic, vendor-neutral designs of dispersive thin-film and metal materials (materials/data/coating_materials.json:
measured n and k of deposited films from the refractiveindex.info database) on N-BK7 unless stated. Each entry keeps
its specification as designer targets; the tests (tests/test_builtin_coatings.py) check every coating against it with
two independent implementations (the analysis module and the designer), and the quarter-wave stacks also against
their analytic reflectance at the design wavelength.

* Optimised entries: a classical start (coatdesign.template) refined (and needle-optimised) by the coating designer.
* Quarter-wave entries (HR mirrors, band-pass, notch, MacNeille polarising beam splitter): exact quarter-wave optical
  thicknesses of the films' real index at the design wavelength and angle, d = lambda0 / (4 Re sqrt(N^2 - s0^2)).
* V-coats: the two-layer root of r = 0 at the design wavelength with the complex film indices.
* Metal mirrors: an opaque metal layer on the glass blank with dielectric overcoats (thicknesses by a scan).
* Phase entries (dispersive mirror): a start refined against GDD targets.

Every specification is evaluated at the end and the generator stops if one is not met.

Run:  python -m opticore.tools.builtin_coatings              (all; the optimised entries may change slightly)
      python -m opticore.tools.builtin_coatings --only DM_800 (rebuild named entries, keep the others as they are)
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from ..coatdesign import CoatingDesign, Resolver, Target, evaluate_design, optimize_design, spectrum, template
from ..materials import MaterialLibrary

OUT = Path(__file__).resolve().parents[1] / "materials" / "data" / "builtin_coatings.json"
FILM = {"MGF2": "MGF2_FILM", "SIO2": "SIO2_FILM", "AL2O3": "AL2O3_FILM", "TA2O5": "TA2O5_FILM", "TIO2": "TIO2_FILM", "HFO2": "HFO2_FILM", "NB2O5": "NB2O5_FILM", "AL": "AL", "AG": "AG", "AU": "AU"}
LABEL = {"MGF2": "MgF₂", "SIO2": "SiO₂", "AL2O3": "Al₂O₃", "TA2O5": "Ta₂O₅", "TIO2": "TiO₂", "HFO2": "HfO₂", "NB2O5": "Nb₂O₅", "AL": "Al", "AG": "Ag", "AU": "Au"}
SUB = "N-BK7"
LIB = MaterialLibrary()


def N(m: str, lam_nm: float) -> complex:
    """Complex index of a coating material (short name) or a library material at a wavelength."""
    return LIB.complex_index(FILM.get(m, m), lam_nm * 1e-3)


def n_re(m: str, lam_nm: float) -> float:
    return float(N(m, lam_nm).real)


def layer(m: str, d: float, lam0: float) -> dict:
    return {"material_label": LABEL[m], "material": FILM[m], "index": round(n_re(m, lam0), 6), "thickness_nm": float(d)}


def _design(pal: dict[str, str], layers=None, targets=None, lam0=550.0, min_nm=8.0, substrate: str | float = SUB, incident: float | None = None) -> CoatingDesign:
    fixed = not isinstance(substrate, str)
    return CoatingDesign(
        name="builtin", incident="AIR", incident_index=incident, substrate=SUB if fixed else substrate, substrate_index=float(substrate) if fixed else None, substrate_extinction=0.0,
        palette=[{"key": k, "label": LABEL[m], "material": FILM[m]} for k, m in pal.items()],
        layers=[{"material": k, "thickness_nm": d} for k, d in (layers or [])], targets=targets or [], design_wavelength_nm=lam0,
        min_thickness_nm=min_nm, max_thickness_nm=1500.0,
    )


def _air_side_first(d: CoatingDesign, pal: dict[str, str]) -> list[dict]:
    return [layer(pal[L.material], L.thickness_nm, d.design_wavelength_nm) for L in reversed(d.layers)]


def _margin(targets: list[dict], m: float) -> list[dict]:
    """Design targets tightened by m (absolute) against the specification they must meet."""
    out = []
    for t in targets:
        k = t.get("kind", "=")
        v = t["value"] - m if k == "<=" else t["value"] + m if k == ">=" else t["value"]
        out.append(dict(t, value=min(1.0, max(0.0, v))))
    return out


def _entry(name, category, description, layers, spec, design_nm, band=None, angle=0.0, incident=1.0, substrate: str | float = SUB, mirror=False):
    fixed = not isinstance(substrate, str)
    return {"name": name, "category": category, "description": description, "design_nm": design_nm, "band_nm": band, "angle_deg": angle,
            "incident_index": incident, "substrate_material": None if fixed else substrate,
            "substrate_index": round(float(substrate) if fixed else n_re(substrate, design_nm), 6),
            **({"mirror_substrate": [round(n_re(SUB, design_nm), 6), 0.0]} if mirror else {}),
            "layers": layers, "spec": spec}


def _qw(m: str | float, lam0: float, n0: float = 1.0, angle_deg: float = 0.0) -> float:
    """Quarter-wave physical thickness of a film (real index at lam0) at an angle in the incident medium n0."""
    n = m if isinstance(m, float) else n_re(m, lam0)
    s0 = n0 * math.sin(math.radians(angle_deg))
    return lam0 / (4 * math.sqrt(n * n - s0 * s0))


def _opt(pal, start_kind, targets, lam0, method="needle", time_s=40.0, margin=0.0, **kw) -> CoatingDesign:
    base = _design(pal, lam0=lam0)
    t = template(base, start_kind, high="H", low="L", lambda0_nm=lam0, **kw)
    d = CoatingDesign.model_validate(t["design"]).model_copy(update={"targets": [Target(**x) for x in _margin(targets, margin)]})
    r = optimize_design(d, method=method, time_limit_s=time_s)
    return CoatingDesign.model_validate(r["design"])


def _vcoat(lam0: float) -> tuple[float, float]:
    """Thicknesses (outer MgF2, inner Ta2O5) of the two-layer coating with zero reflectance at lam0 on N-BK7 (normal
    incidence, complex film indices): the root of r(dL, dH) = 0 with the smallest total thickness."""
    from scipy.optimize import least_squares

    from ..coatanalysis import _matrix

    nL, nH, ns = N("MGF2", lam0), N("TA2O5", lam0), N(SUB, lam0)

    def res(x):
        f = _matrix(np.array([1.0]), np.array([ns]), [(np.array([nL]), x[0]), (np.array([nH]), x[1])], np.array([lam0]), 0.0)
        return [f["rs"][0].real, f["rs"][0].imag]

    best = None
    for a in np.linspace(0.05, 0.95, 7):
        for b in np.linspace(0.05, 0.95, 7):
            sol = least_squares(res, [a * lam0 / (2 * nL.real), b * lam0 / (2 * nH.real)], bounds=([1, 1], [lam0 / (2 * nL.real), lam0 / (2 * nH.real)]), xtol=1e-15, ftol=1e-15, gtol=1e-15)
            if sol.fun[0] ** 2 + sol.fun[1] ** 2 < 1e-20 and (best is None or sol.x.sum() < best.sum() - 1e-6):
                best = sol.x
    if best is None:
        raise RuntimeError(f"No two-layer zero at {lam0} nm")
    return float(best[0]), float(best[1])


def _dm_800() -> dict:
    """Dispersive (chirped) mirror for Ti:sapphire pulses: R >= 99 % over 760-840 nm and GDD -40 +- 15 fs² over
    770-830 nm, refined from a linearly chirped quarter-wave stack (thicker layers deeper: the long wavelengths
    penetrate further and are delayed more, which gives negative GDD)."""
    pal = {"H": "TIO2", "L": "SIO2"}
    lam0, n = 800.0, 24
    layers = []
    for i in range(n):  # deposition order: layer 1 on the substrate
        k = "H" if i % 2 == 0 else "L"
        layers.append((k, (1 + 0.12 * (0.5 - i / (n - 1))) * _qw(pal[k], lam0)))
    spec = [{"quantity": "R", "lambda_min_nm": 760, "lambda_max_nm": 840, "value": 0.99, "kind": ">=", "points": 41},
            {"quantity": "GDD", "of": "R", "lambda_min_nm": 770, "lambda_max_nm": 830, "value": -40.0, "tolerance": 15.0, "kind": "=", "points": 31}]
    design = [dict(spec[0], value=0.995), dict(spec[1], tolerance=10.0)]
    d = _design(pal, layers, [Target(**t) for t in design], lam0, min_nm=8.0)
    r = optimize_design(d, method="refine", time_limit_s=120.0)
    d = CoatingDesign.model_validate(r["design"])
    return _entry("DM_800", "Mirrors", "Dispersive (chirped) mirror for 800 nm ultrafast pulses: R ≥ 99 % over 760–840 nm and GDD −40 ± 15 fs² per bounce over 770–830 nm, 24 TiO₂ / SiO₂ layers refined from a linearly chirped quarter-wave stack",
                  _air_side_first(d, pal), spec, lam0, band=[760, 840])


def _metal_mirror(name: str, metal: str, metal_nm: float, over: list[tuple[str, float]], spec: list[dict], lam0: float, band: list[float], description: str) -> dict:
    """An opaque metal layer on the glass blank with overcoats (listed from the air side)."""
    layers = [layer(m, d, lam0) for m, d in over] + [layer(metal, metal_nm, lam0)]
    return _entry(name, "Mirrors", description, layers, spec, lam0, band=band, mirror=True)


def _best_overcoat(metal: str, over: str, band: tuple[float, float], d_range: tuple[float, float], metal_nm: float = 150.0) -> tuple[float, float]:
    """Single overcoat thickness maximising the smallest R over a band (scan); returns (thickness, min R)."""
    lam = np.linspace(band[0], band[1], 61)
    best = (-1.0, 0.0)
    for d in np.arange(d_range[0], d_range[1] + 0.5, 1.0):
        des = _design({"M": metal, "O": over}, [("M", metal_nm), ("O", float(d))], lam0=float(np.sqrt(band[0] * band[1])))
        R = spectrum(des, Resolver(des), lam)["R"].min()
        if R > best[0]:
            best = (float(R), float(d))
    return best[1], best[0]


def _metal_mirrors() -> list[dict]:
    out = []
    # protected aluminium: a half-wave SiO2 overcoat at 550 nm (absentee there)
    q = 2 * _qw("SIO2", 550.0)
    out.append(_metal_mirror("AL_PROTECTED", "AL", 100.0, [("SIO2", q)],
                             [{"quantity": "R", "lambda_min_nm": 420, "lambda_max_nm": 700, "value": 0.85, "kind": ">=", "points": 57}], 550.0, [400, 1000],
                             "Protected aluminium: 100 nm Al under a half-wave SiO₂ overcoat at 550 nm (absentee there); R ≥ 85 % from 420 to 700 nm"))
    # enhanced aluminium: (L H)^2 quarter waves on the metal, low index first
    over = [("TIO2", _qw("TIO2", 550.0)), ("SIO2", _qw("SIO2", 550.0))] * 2
    out.append(_metal_mirror("AL_ENHANCED", "AL", 100.0, over,
                             [{"quantity": "R", "lambda_min_nm": 480, "lambda_max_nm": 620, "value": 0.95, "kind": ">=", "points": 29}], 550.0, [400, 800],
                             "Enhanced aluminium: 100 nm Al with (L H)² quarter waves of SiO₂ / TiO₂ at 550 nm; R ≥ 95 % from 480 to 620 nm"))
    # UV-enhanced aluminium: the classic 25 nm MgF2 overcoat
    d = 25.0
    out.append(_metal_mirror("AL_UV", "AL", 100.0, [("MGF2", d)],
                             [{"quantity": "R", "lambda_min_nm": 200, "lambda_max_nm": 400, "value": 0.85, "kind": ">=", "points": 41}], 300.0, [180, 800],
                             f"UV-enhanced aluminium: 100 nm Al with {d:.0f} nm MgF₂ (the classic UV overcoat); R ≥ 85 % from 200 to 400 nm"))
    # protected silver and gold: one overcoat chosen for the best smallest R over the band
    d, _ = _best_overcoat("AG", "AL2O3", (450.0, 1900.0), (40.0, 200.0), 150.0)
    out.append(_metal_mirror("AG_PROTECTED", "AG", 150.0, [("AL2O3", d)],
                             [{"quantity": "R", "lambda_min_nm": 450, "lambda_max_nm": 1900, "value": 0.95, "kind": ">=", "points": 59}], 900.0, [400, 1937],
                             f"Protected silver: 150 nm Ag under {d:.0f} nm Al₂O₃; R ≥ 95 % from 450 to 1900 nm (Ag data end at 1.94 µm)"))
    # protective overcoats are at least ~40 nm thick
    d, _ = _best_overcoat("AU", "SIO2", (700.0, 1900.0), (40.0, 150.0), 150.0)
    out.append(_metal_mirror("AU_PROTECTED", "AU", 150.0, [("SIO2", d)],
                             [{"quantity": "R", "lambda_min_nm": 700, "lambda_max_nm": 1900, "value": 0.95, "kind": ">=", "points": 49}], 1200.0, [550, 1937],
                             f"Protected gold: 150 nm Au under {d:.0f} nm SiO₂; R ≥ 95 % from 700 to 1900 nm (Au data end at 1.94 µm)"))
    return out


SINGLE = {"DM_800": _dm_800}


def build() -> list[dict]:
    out: list[dict] = []
    add = lambda *a, **k: out.append(_entry(*a, **k))  # noqa: E731

    # ---------------------------------------------------------------- antireflection
    q = _qw("MGF2", 550.0)
    add("MGF2_QW550", "Antireflection", "Single quarter-wave MgF₂ film at 550 nm: R ≈ 1.3 % on N-BK7, the classic single-layer AR",
        [layer("MGF2", q, 550.0)], [{"quantity": "R", "lambda_min_nm": 550, "lambda_max_nm": 550, "value": 0.014, "kind": "<=", "points": 1}], 550)
    for lam0 in (355.0, 532.0, 550.0, 633.0, 1064.0, 1550.0):
        dL, dH = _vcoat(lam0)
        add(f"VCOAT_{int(lam0)}", "Antireflection", f"V-coat for {lam0:g} nm: MgF₂ {dL:.1f} nm over Ta₂O₅ {dH:.1f} nm (not quarter waves), zero reflectance at the laser line on N-BK7",
            [layer("MGF2", dL, lam0), layer("TA2O5", dH, lam0)],
            [{"quantity": "R", "lambda_min_nm": lam0, "lambda_max_nm": lam0, "value": 1e-8, "kind": "<=", "points": 1}], lam0)
    for name, (a, b), desc in (("BBAR_VIS", (420.0, 680.0), "visible"), ("BBAR_NIR", (650.0, 1050.0), "near infrared"), ("BBAR_SWIR", (1000.0, 1650.0), "short-wave infrared")):
        pal = {"H": "TA2O5", "L": "MGF2"}
        spec = [{"quantity": "R", "lambda_min_nm": a, "lambda_max_nm": b, "value": 0.006, "kind": "<=", "points": 61}]
        d = _opt(pal, "ar_broadband", [dict(spec[0], value=0.0, kind="=")], math.sqrt(a * b), method="needle", time_s=60.0, band_min_nm=a, band_max_nm=b)
        add(name, "Antireflection", f"Broadband antireflection for the {desc} ({a:g}–{b:g} nm), {len(d.layers)} layers Ta₂O₅ / MgF₂: R < 0.6 % across the band",
            _air_side_first(d, pal), spec, math.sqrt(a * b), band=[a, b])

    # ---------------------------------------------------------------- dielectric mirrors (quarter waves, exact)
    for lam0, pairs in ((532.0, 12), (633.0, 12), (1064.0, 12), (1550.0, 12)):
        L = []
        for _ in range(pairs):
            L += [layer("TIO2", _qw("TIO2", lam0), lam0), layer("SIO2", _qw("SIO2", lam0), lam0)]
        L += [layer("TIO2", _qw("TIO2", lam0), lam0)]
        add(f"HR_{int(lam0)}", "Mirrors", f"Dielectric high reflector at {lam0:g} nm, normal incidence: (HL)^{pairs} H quarter waves TiO₂ / SiO₂, R > 99.9 %",
            L, [{"quantity": "R", "lambda_min_nm": lam0 * 0.97, "lambda_max_nm": lam0 * 1.03, "value": 0.999, "kind": ">=", "points": 21}], lam0, band=[lam0 * 0.97, lam0 * 1.03])
    lam0 = 1064.0
    L = []
    for _ in range(14):
        L += [layer("TIO2", _qw("TIO2", lam0, 1.0, 45.0), lam0), layer("SIO2", _qw("SIO2", lam0, 1.0, 45.0), lam0)]
    L += [layer("TIO2", _qw("TIO2", lam0, 1.0, 45.0), lam0)]
    add("HR_1064_45", "Mirrors", "Dielectric high reflector at 1064 nm for 45° (both polarisations): (HL)^14 H TiO₂ / SiO₂ quarter waves at 45°",
        L, [{"quantity": "R", "polarization": "s", "angle_deg": 45.0, "lambda_min_nm": 1040, "lambda_max_nm": 1090, "value": 0.999, "kind": ">=", "points": 21},
            {"quantity": "R", "polarization": "p", "angle_deg": 45.0, "lambda_min_nm": 1050, "lambda_max_nm": 1080, "value": 0.995, "kind": ">=", "points": 11}], 1064.0, band=[1040, 1090], angle=45.0)
    out.extend(_metal_mirrors())

    # ---------------------------------------------------------------- filters
    pal = {"H": "TIO2", "L": "SIO2"}
    spec = [{"quantity": "T", "lambda_min_nm": 420, "lambda_max_nm": 650, "value": 0.93, "kind": ">=", "points": 47},
            {"quantity": "T", "lambda_min_nm": 750, "lambda_max_nm": 1100, "value": 0.03, "kind": "<=", "points": 71}]
    d = _opt(pal, "shortpass", spec, 700.0, method="needle", margin=0.01, time_s=90.0, edge_nm=700.0, pairs=14)
    add("HOT_MIRROR", "Filters", "Hot mirror (0°): transmits the visible (420–650 nm) and reflects the near infrared (750–1100 nm); TiO₂ / SiO₂", _air_side_first(d, pal), spec, 700.0, band=[420, 1100])
    spec = [{"quantity": "R", "lambda_min_nm": 430, "lambda_max_nm": 640, "value": 0.95, "kind": ">=", "points": 43},
            {"quantity": "T", "lambda_min_nm": 760, "lambda_max_nm": 1100, "value": 0.85, "kind": ">=", "points": 69}]
    d = _opt(pal, "longpass", spec, 700.0, method="needle", margin=0.01, time_s=90.0, edge_nm=700.0, pairs=14)
    add("COLD_MIRROR", "Filters", "Cold mirror (0°): reflects the visible (430–640 nm) and transmits the near infrared (760–1100 nm); TiO₂ / SiO₂", _air_side_first(d, pal), spec, 700.0, band=[430, 1100])
    for kind, edge, spec in (
        ("longpass", 550.0, [{"quantity": "T", "lambda_min_nm": 450, "lambda_max_nm": 525, "value": 0.01, "kind": "<=", "points": 31},
                             {"quantity": "T", "lambda_min_nm": 575, "lambda_max_nm": 800, "value": 0.93, "kind": ">=", "points": 46}]),
        ("shortpass", 550.0, [{"quantity": "T", "lambda_min_nm": 400, "lambda_max_nm": 525, "value": 0.93, "kind": ">=", "points": 26},
                              {"quantity": "T", "lambda_min_nm": 575, "lambda_max_nm": 680, "value": 0.01, "kind": "<=", "points": 31}]),
    ):
        d = _opt(pal, kind, spec, edge, method="needle", margin=0.01, time_s=90.0, edge_nm=edge, pairs=16)
        nm_ = "LP_550" if kind == "longpass" else "SP_550"
        add(nm_, "Filters", f"{'Long' if kind == 'longpass' else 'Short'}-pass edge filter at 550 nm (0°), TiO₂ / SiO₂: blocks below 1 % and passes above 93 % 25 nm from the edge", _air_side_first(d, pal), spec, edge, band=[400, 800])
    # band-pass: two-cavity Fabry-Perot at 532 nm (quarter waves of the films' index at 532 nm)
    lam0 = 532.0
    mirror = [("TIO2", _qw("TIO2", lam0)), ("SIO2", _qw("SIO2", lam0))] * 3 + [("TIO2", _qw("TIO2", lam0))]
    cavity = mirror + [("SIO2", 2 * _qw("SIO2", lam0))] + mirror[::-1]
    stack = cavity + [("SIO2", _qw("SIO2", lam0))] + cavity
    spec = [{"quantity": "T", "lambda_min_nm": 532, "lambda_max_nm": 532, "value": 0.95, "kind": ">=", "points": 1},
            {"quantity": "T", "lambda_min_nm": 480, "lambda_max_nm": 524, "value": 0.01, "kind": "<=", "points": 45},
            {"quantity": "T", "lambda_min_nm": 540, "lambda_max_nm": 600, "value": 0.01, "kind": "<=", "points": 61}]
    add("BP_532", "Filters", "Band-pass at 532 nm (0°): two-cavity Fabry–Perot of TiO₂ / SiO₂ quarter waves (HL)³H 2L (LH)³ L (HL)³H 2L (LH)³, FWHM ≈ 4 nm, blocking < 1 % beyond ±8 nm",
        [layer(m, d, lam0) for m, d in stack], spec, lam0, band=[480, 600])
    lam0 = 532.0
    L = []
    for _ in range(40):
        L += [layer("AL2O3", _qw("AL2O3", lam0), lam0), layer("SIO2", _qw("SIO2", lam0), lam0)]
    L += [layer("AL2O3", _qw("AL2O3", lam0), lam0)]
    add("NOTCH_532", "Filters", "Notch (band-block) at 532 nm: (HL)^40 H quarter waves of the low-contrast pair Al₂O₃ / SiO₂, a narrow stop band (T < 1 %); the pass bands ripple (T > 70 % from 450 to 490 nm)",
        L, [{"quantity": "T", "lambda_min_nm": 530, "lambda_max_nm": 534, "value": 0.01, "kind": "<=", "points": 9},
            {"quantity": "T", "lambda_min_nm": 450, "lambda_max_nm": 490, "value": 0.70, "kind": ">=", "points": 21}], 532.0, band=[450, 620])

    # ---------------------------------------------------------------- beam splitters
    pal = {"H": "TA2O5", "L": "SIO2"}
    spec = [{"quantity": "R", "angle_deg": 45.0, "lambda_min_nm": 450, "lambda_max_nm": 650, "value": 0.5, "tolerance": 0.04, "points": 41}]
    d = _opt(pal, "beamsplitter", spec, 550.0, method="needle", time_s=90.0, band_min_nm=450, band_max_nm=650)
    spec = [dict(spec[0], tolerance=0.1)]
    add("BS_50_45", "Beam splitters", "Plate beam splitter at 45° (unpolarised mean R 50 ± 10 %) for 450–650 nm, Ta₂O₅ / SiO₂", _air_side_first(d, pal), spec, 550.0, band=[450, 650], angle=45.0)
    # MacNeille cube: Brewster's angle at every H/L interface for p at 45° in glass n_g^2 = 2 nH^2 nL^2 / (nH^2 + nL^2),
    # with the films' real index at 550 nm (the cube glass is an ideal glass of exactly that index)
    lam0 = 550.0
    nH, nL = n_re("TIO2", lam0), n_re("SIO2", lam0)
    ng = round(math.sqrt(2 * nH * nH * nL * nL / (nH * nH + nL * nL)), 6)
    L = []
    for _ in range(8):
        L += [layer("TIO2", _qw(nH, lam0, ng, 45.0), lam0), layer("SIO2", _qw(nL, lam0, ng, 45.0), lam0)]
    L += [layer("TIO2", _qw(nH, lam0, ng, 45.0), lam0)]
    add("PBS_MACNEILLE", "Beam splitters", f"MacNeille polarising beam-splitter cube (45° in glass n {ng:.4f}): every TiO₂ / SiO₂ interface at Brewster's angle for p at 550 nm, so p is transmitted and s reflected",
        L, [{"quantity": "T", "polarization": "p", "angle_deg": 45.0, "lambda_min_nm": 460, "lambda_max_nm": 680, "value": 0.97, "kind": ">=", "points": 23},
            {"quantity": "R", "polarization": "s", "angle_deg": 45.0, "lambda_min_nm": 500, "lambda_max_nm": 600, "value": 0.98, "kind": ">=", "points": 21}], lam0, band=[450, 680], angle=45.0, incident=ng, substrate=ng)
    # ---------------------------------------------------------------- phase
    out.append(_dm_800())
    return out


def check(entry: dict) -> list[str]:
    """Specification targets an entry misses, evaluated by the coating designer (empty: all met)."""
    pal_keys: dict[str, str] = {}
    for L in entry["layers"]:
        pal_keys.setdefault(L["material"], "HLMNPQXYZW"[len(pal_keys)])
    sub = entry["substrate_material"] or float(entry["substrate_index"])
    des = CoatingDesign(
        name=entry["name"], incident="AIR", incident_index=None if entry["incident_index"] == 1.0 else entry["incident_index"],
        substrate=sub if isinstance(sub, str) else SUB, substrate_index=None if isinstance(sub, str) else sub,
        palette=[{"key": k, "material": m} for m, k in pal_keys.items()],
        layers=[{"material": pal_keys[L["material"]], "thickness_nm": L["thickness_nm"]} for L in reversed(entry["layers"])],
        targets=entry["spec"], design_wavelength_nm=entry["design_nm"],
    )
    ev = evaluate_design(des)
    return [f"{entry['name']} target {i + 1}: violation {t['max_violation']:.3g}" for i, t in enumerate(ev["targets"]) if not t["met"]]


def main(argv: list[str] | None = None):
    import sys

    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["--only"]:
        names = [a.upper() for a in args[1:]]
        unknown = [n for n in names if n not in SINGLE]
        if unknown or not names:
            raise SystemExit(f"--only takes entries of {sorted(SINGLE)} (got {unknown or 'none'})")
        data = json.loads(OUT.read_text(encoding="utf-8"))["coatings"]
        for nm in names:
            new = SINGLE[nm]()
            i = next((j for j, c in enumerate(data) if c["name"] == nm), None)
            if i is None:
                data.append(new)
            else:
                data[i] = new
    else:
        data = build()
    failed = [m for c in data for m in check(c)]
    for c in data:
        print(f"{c['name']:16s} {len(c['layers']):3d} layers  {c['category']}")
    if failed:
        raise SystemExit("Specification not met:\n" + "\n".join(failed))
    OUT.write_text(json.dumps({"generator": "opticore.tools.builtin_coatings", "coatings": data}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
