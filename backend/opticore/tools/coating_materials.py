"""Generate the coating materials (materials/data/coating_materials.json): thin films and metals with n and k.

Source: the refractiveindex.info database (https://github.com/polyanskiy/refractiveindex.info-database), dedicated to
the public domain (CC0 1.0). Each entry keeps the original reference and the database page. Film data depend on the
deposition process and conditions: they are typical values for the stated process, not the films of a particular
chamber (measure your own and fit them in the coating designer's Measurement fit).

The YAML pages are downloaded separately (into a directory of their own) and converted here without network access:

    python -m opticore.tools.coating_materials <directory with the YAML pages>

Each page is expected under the name "<Material>__<page>.yml" (e.g. "TiO2__Franta.yml"), i.e. database/data/main/
<Material>/nk/<page>.yml. Conversions (wavelengths in um):

    formula 1   n^2 - 1 = c0 + sum B L^2 / (L^2 - C^2)  -> sellmeier_sq (c0 as the term B = c0, C = 0)
    formula 2   n^2 - 1 = c0 + sum B L^2 / (L^2 - C)    -> sellmeier
    formula 5   n = c0 + c1 L^-2 + c2 L^-4             -> cauchy (other exponents are not accepted)
    tabulated n / nk                                    -> tabulated n (PCHIP); k column -> extinction_table
    tabulated k                                         -> extinction_table
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

OUT = Path(__file__).resolve().parents[1] / "materials" / "data" / "coating_materials.json"
DB = "refractiveindex.info database (CC0 1.0)"

# (page file, name, category, label, process / note)
SELECTION: list[tuple[str, str, str, str, str]] = [
    ("SiO2__Lemarchand.yml", "SIO2_FILM", "film", "SiO₂", "580 nm magnetron-sputtered film on BK7"),
    ("TiO2__Franta.yml", "TIO2_FILM", "film", "TiO₂", "99.6 nm e-beam evaporated film (universal dispersion model)"),
    ("Ta2O5__Gao.yml", "TA2O5_FILM", "film", "Ta₂O₅", "400 nm ion-assisted e-beam film on BK7"),
    ("Nb2O5__Lemarchand.yml", "NB2O5_FILM", "film", "Nb₂O₅", "500 nm magnetron-sputtered film on BK7"),
    ("HfO2__Franta.yml", "HFO2_FILM", "film", "HfO₂", "112.7 nm e-beam evaporated film (universal dispersion model)"),
    ("Al2O3__Franta.yml", "AL2O3_FILM", "film", "Al₂O₃", "121.5 nm e-beam evaporated film (universal dispersion model)"),
    ("MgF2__Franta.yml", "MGF2_FILM", "film", "MgF₂", "134.2 nm e-beam evaporated film (universal dispersion model)"),
    ("ZnS__Amotchkina.yml", "ZNS_FILM", "film", "ZnS", "1.008 µm e-beam evaporated film on Ge (k measured 0.4–1.0 µm)"),
    ("Si3N4__Luke.yml", "SI3N4_FILM", "film", "Si₃N₄", "340 nm LPCVD film"),
    ("Ag__Johnson.yml", "AG", "metal", "Ag", "evaporated films, room temperature"),
    ("Ag__Rakic-LD.yml", "AG_LD", "metal", "Ag", "Lorentz–Drude fit of several sources, 0.25–12.4 µm"),
    ("Au__Johnson.yml", "AU", "metal", "Au", "evaporated films, room temperature"),
    ("Cu__Johnson.yml", "CU", "metal", "Cu", "evaporated films, room temperature"),
    ("Cr__Johnson.yml", "CR", "metal", "Cr", "evaporated films, room temperature"),
    ("Al__Rakic.yml", "AL", "metal", "Al", "evaporated films, self-consistent Kramers–Kronig analysis"),
]


def _floats(text: Any) -> list[float]:
    return [float(x) for x in str(text).split()]


def _plain(text: str) -> str:
    t = re.sub(r"<[^>]+>", "", text or "")
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def _sellmeier_terms(c: list[float]) -> list[float]:
    c0, rest = c[0], c[1:]
    if len(rest) % 2:
        raise ValueError("odd number of Sellmeier coefficients")
    terms = [x for B, C in zip(rest[0::2], rest[1::2]) if not (B == 0.0 and C == 0.0) for x in (B, C)]
    return ([c0, 0.0] if c0 != 0.0 else []) + terms


def convert(text: str, page: str) -> dict[str, Any]:
    """One refractiveindex.info page -> dispersion fields of a material record (formula/coefficients/table, range,
    extinction_table, reference)."""
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict) or not isinstance(doc.get("DATA"), list):
        raise ValueError(f"{page}: no DATA section")
    rec: dict[str, Any] = {}
    k_table: list[list[float]] = []
    for item in doc["DATA"]:
        typ = str(item.get("type", "")).strip()
        if typ in ("formula 1", "formula 2"):
            c = _floats(item.get("coefficients", ""))
            rng = _floats(item.get("wavelength_range", ""))
            rec.update(formula="sellmeier_sq" if typ == "formula 1" else "sellmeier", coefficients=_sellmeier_terms(c), lambda_min=rng[0], lambda_max=rng[1])
        elif typ == "formula 5":
            c = _floats(item.get("coefficients", ""))
            rng = _floats(item.get("wavelength_range", ""))
            terms = dict(zip(c[2::2], c[1::2]))  # exponent -> coefficient
            if set(terms) - {-2.0, -4.0}:
                raise ValueError(f"{page}: formula 5 with exponents {sorted(terms)} is not a Cauchy formula")
            rec.update(formula="cauchy", coefficients=[c[0], terms.get(-2.0, 0.0), terms.get(-4.0, 0.0)], lambda_min=rng[0], lambda_max=rng[1])
        elif typ in ("tabulated n", "tabulated nk"):
            rows = [_floats(line) for line in str(item.get("data", "")).strip().splitlines() if line.strip()]
            rec.update(formula="tabulated", coefficients=[], table=[[r[0], r[1]] for r in rows])
            if typ == "tabulated nk":
                k_table = [[r[0], max(0.0, r[2])] for r in rows]
        elif typ == "tabulated k":
            k_table = [[r[0], max(0.0, r[1])] for r in (_floats(line) for line in str(item.get("data", "")).strip().splitlines() if line.strip())]
        else:
            raise ValueError(f"{page}: {typ} is not supported")
    if "formula" not in rec:
        raise ValueError(f"{page}: no refractive-index data")
    if k_table and any(k > 0 for _, k in k_table):
        # values below 1e-30 are numerical noise of the source's model
        rec["extinction_table"] = [[w, k if k >= 1e-30 else 0.0] for w, k in k_table]
    rec["reference"] = _plain(str(doc.get("REFERENCES", "")))
    return rec


TOL_N = 2e-5  # largest change of n (and of k, or 1 % of k) at a dropped point, linear between kept points


def _keep(x, y, tol) -> set[int]:
    """Ramer-Douglas-Peucker on (log lambda, y): indices to keep so that linear interpolation between them reproduces
    every dropped point within tol (an array per point)."""
    import numpy as np

    keep = {0, len(x) - 1}
    stack = [(0, len(x) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        t = (x[a + 1 : b] - x[a]) / (x[b] - x[a])
        dev = np.abs(y[a + 1 : b] - (y[a] + t * (y[b] - y[a]))) - tol[a + 1 : b]
        i = int(np.argmax(dev))
        if dev[i] > 0:
            m = a + 1 + i
            keep.add(m)
            stack += [(a, m), (m, b)]
    return keep


def thin_table(rec: dict[str, Any]) -> float:
    """Drop table points that interpolation reproduces (n within TOL_N, k within max(TOL_N, 1 %)); returns the largest
    PCHIP deviation at the original points."""
    import numpy as np
    from scipy.interpolate import PchipInterpolator

    if rec.get("formula") != "tabulated":
        return 0.0
    tab = np.asarray(rec["table"], dtype=float)
    x = np.log(tab[:, 0])
    keep = _keep(x, tab[:, 1], np.full(len(x), TOL_N))
    kt = np.asarray(rec.get("extinction_table") or [], dtype=float)
    same = len(kt) == len(tab) and np.allclose(kt[:, 0], tab[:, 0])
    if same:
        keep |= _keep(x, kt[:, 1], np.maximum(TOL_N, 0.01 * kt[:, 1]))
    idx = sorted(keep)
    dev = float(np.max(np.abs(PchipInterpolator(tab[idx, 0], tab[idx, 1])(tab[:, 0]) - tab[:, 1])))
    rec["table"] = tab[idx].tolist()
    if same:
        k_new = PchipInterpolator(kt[idx, 0], kt[idx, 1])(kt[:, 0])
        dev = max(dev, float(np.max(np.abs(k_new - kt[:, 1]) - np.maximum(0.0, 0.01 * kt[:, 1] - TOL_N))))
        rec["extinction_table"] = kt[idx].tolist()
    return dev


def build(src: Path) -> list[dict[str, Any]]:
    out = []
    for fname, name, cat, label, note in SELECTION:
        material, page = fname[:-4].split("__", 1)
        path = f"main/{material}/nk/{page}.yml"
        rec = convert((src / fname).read_text(encoding="utf-8"), fname)
        ref = rec.pop("reference")
        rows = len(rec.get("table") or [])
        dev = thin_table(rec)
        if dev > 5 * TOL_N:
            raise SystemExit(f"{name}: thinning changed the data by {dev:.2e}")
        if rows:
            print(f"{name}: {rows} -> {len(rec['table'])} points (largest change {dev:.1e})")
        out.append({
            "name": name, "family": "FILM" if cat == "film" else "METAL", "category": cat, "label": label,
            **rec,
            "source": f"{label} {'film' if cat == 'film' else 'metal'}: {note}. {ref} — via the {DB}, {path}"[:600],
        })
    return out


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        raise SystemExit(__doc__)
    data = build(Path(args[0]))
    OUT.write_text(
        json.dumps({
            "catalog_version": 1,
            "generator": "opticore.tools.coating_materials",
            "notes": "Thin-film and metal optical constants (n, k) from the refractiveindex.info database, dedicated to the public domain (CC0 1.0); original references per entry. Film constants depend on the deposition process: typical values, not the films of a particular chamber.",
            "materials": data,
        }, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    for m in data:
        print(f"{m['name']:12s} {m['category']:6s} {m['formula']:12s} {len(m.get('table') or [])} n rows, {len(m.get('extinction_table') or [])} k rows")


if __name__ == "__main__":
    main()
