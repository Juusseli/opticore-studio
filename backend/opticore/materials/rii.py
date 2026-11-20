"""Glass data from the refractiveindex.info database (YAML), converted to OptiCore material records.

The database (https://github.com/polyanskiy/refractiveindex.info-database) is dedicated to the
public domain (CC0 1.0). Its `specs/<maker>/...` books hold the manufacturers' catalogue data
(dispersion formulas from their Zemax catalogues, dn/dT, Nd/Vd, density, ...). OptiCore does not
ship these data: the browser downloads the files the user asks for and the engine converts them
statelessly here, like an AGF import (ADR-015, ADR-018).

Conversions (refractiveindex.info formula numbers, wavelengths in um):

formula 1   n^2 - 1 = c0 + sum B L^2 / (L^2 - C^2)   -> sellmeier_sq (c0 as the term B = c0, C = 0)
formula 2   n^2 - 1 = c0 + sum B L^2 / (L^2 - C)     -> sellmeier    (c0 as the term B = c0, C = 0)
formula 3   n^2 = c0 + sum c L^e                     -> polynomial
tabulated n / nk                                     -> tabulated (n column)
tabulated k / nk                                     -> internal transmittance tau = exp(-4 pi k d / L)
                                                        for d = 10 mm (display, like the AGF IT lines)
thermal_dispersion formula A (D0 D1 D2 E0 E1 Ltk)    -> thermal, T0 = CONDITIONS temperature
Other formulas (4-9) are reported and skipped. Every converted glass is checked against its own
nd / Vd (agf.verify_record), exactly as AGF imports are.
"""

from __future__ import annotations

import math
import re
from typing import Any

import yaml

from .agf import MAX_GLASSES, AgfCatalog, AgfDiagnostic, verify_record

RII_SOURCE = "refractiveindex.info database (CC0)"
IT_THICKNESS_MM = 10.0
MAX_FILE_BYTES = 1_000_000
STATUS = {"standard", "preferred", "obsolete", "special", "melt"}


def _floats(text: Any) -> list[float]:
    return [float(x) for x in str(text).split()]


def _plain(text: str) -> str:
    """References as plain text: HTML tags and Markdown links reduced to their text."""
    t = re.sub(r"<[^>]+>", "", text or "")
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def glass_name(path: str) -> str:
    return re.sub(r"\.ya?ml$", "", path.replace("\\", "/").split("/")[-1], flags=re.I).upper()


def _sellmeier_terms(c: list[float]) -> list[float]:
    c0, rest = c[0], c[1:]
    if len(rest) % 2:
        raise ValueError("odd number of Sellmeier coefficients")
    terms = [x for B, C in zip(rest[0::2], rest[1::2]) if not (B == 0.0 and C == 0.0) for x in (B, C)]
    return ([c0, 0.0] if c0 != 0.0 else []) + terms


def parse_rii_file(text: str, path: str, catalog: str, diags: list[AgfDiagnostic]) -> dict[str, Any] | None:
    """One refractiveindex.info YAML book page -> material record (None, with a diagnostic, if unusable)."""
    name = glass_name(path)
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        diags.append(AgfDiagnostic("error", f"not a valid YAML file ({str(exc).splitlines()[0]}); skipped", name))
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("DATA"), list):
        diags.append(AgfDiagnostic("error", "no DATA section; skipped", name))
        return None
    rec: dict[str, Any] | None = None
    k_table: list[list[float]] = []
    for item in doc["DATA"]:
        typ = str(item.get("type", "")).strip()
        try:
            if typ in ("formula 1", "formula 2", "formula 3"):
                c = _floats(item.get("coefficients", ""))
                rng = _floats(item.get("wavelength_range", "")) or [0.0, 0.0]
                if typ == "formula 3":
                    if len(c) % 2 == 0:
                        raise ValueError("formula 3 needs c0 followed by (coefficient, exponent) pairs")
                    # drop all-zero terms
                    pairs = [(k, e) for k, e in zip(c[1::2], c[2::2]) if k != 0.0]
                    formula, coefs = "polynomial", [c[0], *[x for p in pairs for x in p]]
                else:
                    formula = "sellmeier_sq" if typ == "formula 1" else "sellmeier"
                    coefs = _sellmeier_terms(c)
                rec = {"formula": formula, "coefficients": coefs, "lambda_min": rng[0], "lambda_max": rng[1] if len(rng) > 1 and rng[1] > rng[0] else None}
            elif typ in ("tabulated n", "tabulated nk"):
                rows = [_floats(line) for line in str(item.get("data", "")).strip().splitlines() if line.strip()]
                rec = {"formula": "tabulated", "coefficients": [], "table": [[r[0], r[1]] for r in rows]}
                if typ == "tabulated nk":
                    k_table = [[r[0], r[2]] for r in rows if len(r) > 2]
            elif typ == "tabulated k":
                k_table = [[r[0], r[1]] for r in (_floats(line) for line in str(item.get("data", "")).strip().splitlines() if line.strip())]
            elif typ.startswith("formula"):
                diags.append(AgfDiagnostic("error", f"refractiveindex.info {typ} is not supported; skipped", name))
                return None
        except (ValueError, IndexError) as exc:
            diags.append(AgfDiagnostic("error", f"unreadable {typ} data ({exc}); skipped", name))
            return None
    if rec is None:
        diags.append(AgfDiagnostic("error", "no refractive-index data (only absorption); skipped", name))
        return None

    rec = {"name": name, **rec, "family": catalog, "category": "glass", "catalog": catalog}
    refs = _plain(str(doc.get("REFERENCES", "")))
    rec["source"] = f"{catalog}: {refs or 'manufacturer data'} — via the {RII_SOURCE}, {path}"[:400]
    props = doc.get("PROPERTIES") or {}
    cond = doc.get("CONDITIONS") or {}
    if isinstance(props.get("nd"), (int, float)):
        rec["nd_ref"] = float(props["nd"])
    if isinstance(props.get("Vd"), (int, float)):
        rec["vd_ref"] = float(props["Vd"])
    st = str(props.get("glass_status", "standard")).strip().lower()
    rec["status"] = st if st in STATUS else "standard"
    if props.get("glass_code") is not None:
        rec["comment"] = f"glass code {props['glass_code']}"
    if isinstance(props.get("dPgF"), (int, float)):
        rec["dpgf"] = float(props["dPgF"])
    dens = props.get("density")
    if isinstance(dens, list) and dens and isinstance(dens[0], dict) and isinstance(dens[0].get("value"), (int, float)):
        rec["density"] = round(float(dens[0]["value"]) / 1000.0, 6)  # kg/m^3 -> g/cm^3
    for te in props.get("thermal_expansion") or []:
        if isinstance(te, dict) and _floats(te.get("temperature_range", "")) == [243.0, 343.0] and isinstance(te.get("value"), (int, float)):
            rec["tce_m30_70"] = round(float(te["value"]) * 1e6, 6)  # 1/K -> 1e-6/K, -30..+70 degC
    for td in props.get("thermal_dispersion") or []:
        if isinstance(td, dict) and str(td.get("type", "")).strip() == "formula A":
            t = _floats(td.get("coefficients", ""))
            T = cond.get("temperature")
            if len(t) == 6 and any(x != 0.0 for x in t[:5]):
                T0 = round(float(T) - 273.15, 2) if isinstance(T, (int, float)) else 20.0
                rec["thermal"] = {"D0": t[0], "D1": t[1], "D2": t[2], "E0": t[3], "E1": t[4], "lambda_tk": t[5], "T0": T0}
            break
    if k_table:
        # internal transmittance tau = exp(-alpha d), alpha = 4 pi k / lambda. Kept unrounded (rounding tau to 6 decimals
        # at 10 mm would quantise alpha below ~1e-7 /mm), and over d = 1 / alpha where 10 mm would make tau underflow
        # (the tau floor of 1e-12 would then cap alpha at -ln(1e-12) / 10 mm = 2.76 /mm)
        it = []
        for lam, k in k_table:
            if lam > 0 and k >= 0:
                alpha = 4.0 * math.pi * k * 1e3 / lam  # 1/mm (lam in um)
                d = IT_THICKNESS_MM if alpha * IT_THICKNESS_MM <= 20.0 else 1.0 / alpha
                it.append([lam, math.exp(-alpha * d), d])
        if it:
            rec["internal_transmission"] = it
    if not verify_record(rec, diags):
        return None
    return rec


def parse_rii_catalog(files: list[tuple[str, str]], catalog: str) -> AgfCatalog:
    """Converts the YAML pages of one maker (path, text) into a catalogue with diagnostics."""
    cat = AgfCatalog(name=catalog)
    cat.comments.append(f"Downloaded from the {RII_SOURCE}: https://github.com/polyanskiy/refractiveindex.info-database")
    seen: set[str] = set()
    # a name on several shelves (optical, obsolete, infrared, ...): the "optical" page wins
    files = sorted(files, key=lambda f: ("/optical/" not in f[0].replace("\\", "/"), f[0]))
    for path, text in files[:MAX_GLASSES]:
        name = glass_name(path)
        if name in seen:
            cat.diagnostics.append(AgfDiagnostic("warning", f"duplicate glass name ({path}); the first one is kept", name))
            continue
        if len(text.encode("utf-8")) > MAX_FILE_BYTES:
            cat.diagnostics.append(AgfDiagnostic("error", "file too large; skipped", name))
            continue
        rec = parse_rii_file(text, path, catalog, cat.diagnostics)
        if rec is not None:
            seen.add(name)
            cat.records.append(rec)
    if len(files) > MAX_GLASSES:
        cat.diagnostics.append(AgfDiagnostic("warning", f"only the first {MAX_GLASSES} of {len(files)} files were read"))
    n_unverified = sum(1 for r in cat.records if not r["verified"])
    n_unchecked = sum(1 for d in cat.diagnostics if d.message.endswith("nd/Vd not checked"))
    msg = f"{len(cat.records)} of {len(files)} glasses imported"
    if n_unverified:
        msg += f"; {n_unverified} do not reproduce their catalogue nd/Vd and are flagged"
    elif len(cat.records) > n_unchecked:
        msg += "; every checked glass reproduces its catalogue nd and Vd"
    if n_unchecked:
        msg += f"; {n_unchecked} materials (e.g. infrared glasses) have no data at the F and C lines (nd/Vd not checked)"
    cat.diagnostics.insert(0, AgfDiagnostic("info", msg))
    return cat
