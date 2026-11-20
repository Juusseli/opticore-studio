"""Generate the coating design examples (materials/data/coating_examples.json).

OIC 2019 Manufacturing Problem ("Yucca problem"): D. Poitras, L. Li, M. R. Jacobson, C. C. Cooksey, "2019 Topical
Meeting on Optical Interference Coatings: Manufacturing Problem Contest", Appl. Opt. 59(5), A31-A39 (2020),
doi:10.1364/AO.59.000A31. Target data: Figshare doi:10.6084/m9.figshare.9915800.v1 (CC BY 4.0), converted unchanged to
materials/data/oic2019_yucca_targets.csv.

The problem: s-polarised transmittance targets at 10 deg (450-1075 nm, 626 points) and 50 deg (480-1065 nm, 586 points)
on a 1 mm N-BK7 substrate, coatings allowed on both faces; merit function MF = sqrt(mean(((T - T_target) / 0.01)^2))
over all points (eq. 1 of the paper). The designer's merit with "=" targets, zero tolerance and weights proportional to
the number of points is exactly MF x 0.01.

The example is designed here with the coating designer itself (TiO2 / SiO2 films, both faces): needle optimisation and
gradual evolution against every fourth target point (until no needle or new layer pair helps, or 80 % of the time
budget), then refinement against all of them (the rest of the budget). It takes tens of minutes:

    python -m opticore.tools.coating_examples [seconds] [front layers] [back layers] [output or -] [seed]

The start is a quarter-wave stack (front at 700 nm, back at 600 nm) or, with a seed, a broadband random start: every
layer a quarter wave at a wavelength drawn uniformly from 450-1100 nm.

The computation is deterministic, but a run that reaches a time limit depends on the machine's speed. The stored example
records its settings, and its merit is recomputed independently by tests/test_coating_examples.py.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

from ..coatdesign import CoatingDesign, Merit, Resolver, _pairs_all, optimize_design
from ..materials import MaterialLibrary

DATA = Path(__file__).resolve().parents[1] / "materials" / "data"
TARGETS = DATA / "oic2019_yucca_targets.csv"
OUT = DATA / "coating_examples.json"
REFERENCE = {
    "paper": "D. Poitras, L. Li, M. R. Jacobson, C. C. Cooksey, Appl. Opt. 59(5), A31-A39 (2020), doi:10.1364/AO.59.000A31",
    "data": "Figshare doi:10.6084/m9.figshare.9915800.v1, CC BY 4.0",
    # Table 3 of the paper: the contest designs' computed MF and the winning sample's measured MF
    "design_mf_range": [0.439, 2.14],
    "design_layers_range": [74, 255],
    "design_thickness_um_range": [8.24, 17.6],
    "winner_measured_mf": 1.164,
    "organisers_example": "50 layers, 3.8 um (one face) or 30 + 24 layers, 2.7 + 1.7 um (both faces): MF < 5",
}


def yucca_targets(step: int = 1) -> list[dict]:
    """The contest's two tabulated targets (every `step`-th point), weighted by their numbers of points so that the
    merit is the contest MF x 0.01."""
    tab: dict[int, list[tuple[float, float]]] = {10: [], 50: []}
    with open(TARGETS, encoding="utf-8") as f:
        rows = [r for r in csv.reader(f) if r and not r[0].startswith("#")]
    for a, w, t, tol in rows[1:]:
        if float(tol) != 0.01:
            raise ValueError("the contest tolerance is 0.01 throughout")
        tab[int(a)].append((float(w), float(t)))
    out = []
    for a in (10, 50):
        pts = tab[a][::step]
        out.append({"quantity": "T", "polarization": "s", "angle_deg": a, "lambda_min_nm": pts[0][0], "lambda_max_nm": pts[-1][0], "value": 0.5, "kind": "=", "weight": len(pts), "table": pts})
    return out


def contest_mf(design: CoatingDesign) -> float:
    d = design.model_copy(update={"targets": CoatingDesign.model_validate({"palette": [{"key": "H"}], "targets": yucca_targets()}).targets})
    p, _ = _pairs_all(d)
    return Merit(d, Resolver(d)).value(p) / 0.01


def build_yucca(seconds: float = 1500.0, front: int = 20, back: int = 16, seed: int | None = None) -> dict:
    lib = MaterialLibrary()
    nH, nL = lib.index("TIO2_FILM", 0.7), lib.index("SIO2_FILM", 0.7)

    rng = np.random.default_rng(seed) if seed is not None else None

    def stack(n: int, lam: float) -> list[dict]:
        lams = rng.uniform(450.0, 1100.0, n) if rng is not None else np.full(n, lam)
        return [{"material": "H" if i % 2 == 0 else "L", "thickness_nm": float(lams[i] / (4 * (nH if i % 2 == 0 else nL)))} for i in range(n)]

    d = CoatingDesign(
        name="OIC 2019 Yucca problem", palette=[{"key": "H", "label": "TiO₂", "material": "TIO2_FILM"}, {"key": "L", "label": "SiO₂", "material": "SIO2_FILM"}],
        substrate="N-BK7", back_side="coated", substrate_thickness_mm=1.0, layers=stack(front, 700.0), back_layers=stack(back, 600.0),
        targets=yucca_targets(step=4), design_wavelength_nm=700.0, min_thickness_nm=5.0, max_thickness_nm=1500.0,
    )
    t0 = time.time()
    r1 = optimize_design(d, method="needle", time_limit_s=0.8 * seconds, max_needles=400)
    d1 = CoatingDesign.model_validate(r1["design"]).model_copy(update={"targets": CoatingDesign.model_validate({"palette": [{"key": "H"}], "targets": yucca_targets()}).targets})
    r2 = optimize_design(d1, method="refine", time_limit_s=0.2 * seconds)
    d2 = CoatingDesign.model_validate(r2["design"])
    mf = contest_mf(d2)
    um_front = sum(L.thickness_nm for L in d2.layers) / 1000
    um_back = sum(L.thickness_nm for L in d2.back_layers) / 1000
    steps = sum(1 for h in r1.get("history", []) if h.get("step") in ("needle", "evolution"))
    print(f"Yucca: {steps} needle/evolution steps, MF {mf:.4f}, front {len(d2.layers)} layers {um_front:.2f} um, back {len(d2.back_layers)} layers {um_back:.2f} um, {time.time() - t0:.0f} s", flush=True)
    return {
        "id": "oic2019_yucca",
        "name": "OIC 2019 Yucca problem",
        "category": "Benchmarks",
        "description": (f"The 2019 Optical Interference Coatings manufacturing contest: s-polarised transmittance at 10° and 50° following a yucca "
                        f"silhouette (1212 points, 450–1075 nm) through a 1 mm N-BK7 plate coated on both faces. Designed here with TiO₂ / SiO₂ films: "
                        f"{len(d2.layers)} + {len(d2.back_layers)} layers, {um_front:.2f} + {um_back:.2f} µm, contest merit MF {mf:.3f} (contest designs: MF 0.44–2.14)."),
        "contest_mf": mf,
        "layers_front": len(d2.layers),
        "layers_back": len(d2.back_layers),
        "thickness_um": [um_front, um_back],
        "reference": REFERENCE,
        "generator": {"command": f"python -m opticore.tools.coating_examples {seconds:g} {front} {back}" + (f" - {seed}" if seed is not None else ""),
                      "start": (f"front {front}, back {back} quarter waves at random wavelengths 450-1100 nm (seed {seed})" if seed is not None else f"front {front} quarter waves at 700 nm, back {back} at 600 nm"),
                      "needle_targets": "every fourth contest point", "steps": steps, "seconds": round(time.time() - t0)},
        "design": d2.model_dump(),
    }


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    seconds = float(args[0]) if args else 1500.0
    front = int(args[1]) if len(args) > 1 else 20
    back = int(args[2]) if len(args) > 2 else 16
    out = Path(args[3]) if len(args) > 3 and args[3] != "-" else OUT
    seed = int(args[4]) if len(args) > 4 else None
    ex = [build_yucca(seconds, front, back, seed)]
    out.write_text(json.dumps({"generator": "opticore.tools.coating_examples", "examples": ex}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
