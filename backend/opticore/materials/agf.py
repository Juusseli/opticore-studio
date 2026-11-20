"""Glass catalogue import from the AGF text format.

AGF is the plain-text glass catalogue format that glass manufacturers publish
for optical design programs (one file per catalogue). Users download the
files from the manufacturer; OptiCore ships none of them. This module
converts a catalogue into OptiCore material records (`catalog.py`). It is an
independent implementation of the documented, line-oriented format:

    CC <comment>
    NM <name> <formula> <MIL> <Nd> <Vd> <exclude> <status> [<melt frequency>]
    GC <glass comment>
    ED <TCE -30..70> <TCE 100..300> <density> <dPgF> [<ignore thermal expansion>]
    CD <c1> ... <c10>              dispersion coefficients
    TD <D0> <D1> <D2> <E0> <E1> <lambda_tk> <T_ref>
    OD <relative cost> <CR> <FR> <SR> <AR> <PR>
    LD <lambda_min> <lambda_max>    data range (um)
    IT <lambda> <transmission> <thickness mm>   internal transmittance

Every glass is checked against its own catalogue data: the index computed
from the coefficients at the d line must reproduce the listed Nd (and Vd).
Glasses that fail the check are still imported but flagged (`verified`
false) and reported in the diagnostics, because a mismatch means an
unsupported formula variant or a damaged file.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .catalog import AIR_NAMES, MIRROR_NAME, VACUUM_NAMES, MaterialError, _material_from_record
from .dispersion import FIXED_COUNTS, LAMBDA_C, LAMBDA_F, DispersionError

# AGF formula number -> (OptiCore formula, number of coefficients used)
AGF_FORMULAS: dict[int, tuple[str, int]] = {
    1: ("schott", 6),
    2: ("sellmeier", 6),  # Sellmeier 1: K1 L1 K2 L2 K3 L3 (L in um^2)
    3: ("herzberger", 6),
    4: ("sellmeier2", 5),
    5: ("conrady", 3),
    6: ("sellmeier", 8),  # Sellmeier 3
    7: ("handbook1", 4),
    8: ("handbook2", 4),
    9: ("sellmeier4", 5),
    10: ("extended", 8),
    11: ("sellmeier", 10),  # Sellmeier 5
    12: ("extended2", 8),
    13: ("extended3", 9),
}
assert all(n <= FIXED_COUNTS.get(f, n) for f, n in AGF_FORMULAS.values())

STATUS = {0: "standard", 1: "preferred", 2: "obsolete", 3: "special", 4: "melt"}

# |n_d(coefficients) - Nd(catalogue)| above this flags the glass (catalogue Nd carry 5-6 decimals;
# dispersion fits reproduce them to a few 1e-6)
ND_TOLERANCE = 1e-4
VD_TOLERANCE = 0.05  # relative to Vd, in Abbe units: 0.05 % is generous for 4-decimal catalogue Vd

MAX_GLASSES = 5000


@dataclass
class AgfDiagnostic:
    level: str  # "info" | "warning" | "error"
    message: str
    glass: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "message": self.message, "glass": self.glass}


@dataclass
class AgfCatalog:
    name: str
    records: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[AgfDiagnostic] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)


def decode_agf(data: bytes) -> str:
    """AGF files come as UTF-16 (with BOM, as written by most tools), UTF-8 or a legacy 8-bit code page."""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    head = data[:400]
    if head and head.count(b"\x00") > len(head) // 4:  # UTF-16 without BOM
        return data.decode("utf-16-le" if head[1:2] == b"\x00" else "utf-16-be", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def catalog_name_from_filename(filename: str) -> str:
    stem = re.sub(r"\.[^.]*$", "", filename.replace("\\", "/").split("/")[-1])
    return re.sub(r"[^A-Za-z0-9_+-]+", "_", stem).upper().strip("_") or "CATALOG"


def _floats(parts: list[str]) -> list[float]:
    out = []
    for p in parts:
        try:
            out.append(float(p))
        except ValueError:
            out.append(float("nan"))
    return out


def _num(parts: list[float], i: int, default: float | None = None) -> float | None:
    if i < len(parts) and math.isfinite(parts[i]):
        return parts[i]
    return default


def parse_agf(text: str, catalog: str, filename: str = "") -> AgfCatalog:
    """Parse an AGF catalogue into OptiCore material records with diagnostics."""
    cat = AgfCatalog(name=catalog)
    glasses: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        key, _, rest = line.partition(" ")
        key = key.upper()
        parts = rest.split()
        if key == "CC":
            cat.comments.append(rest.strip())
        elif key == "NM":
            if len(parts) < 5:
                cat.diagnostics.append(AgfDiagnostic("error", f"line {lineno}: NM line needs name, formula, MIL, Nd and Vd"))
                cur = None
                continue
            f = _floats(parts[1:])
            cur = {
                "name": parts[0].upper(),
                "agf_formula": int(f[0]) if math.isfinite(f[0]) else -1,
                "mil": parts[2] if len(parts) > 2 else "",
                "nd": _num(f, 2),
                "vd": _num(f, 3),
                "exclude": bool(_num(f, 4, 0.0)),
                "status": STATUS.get(int(_num(f, 5, 0.0) or 0), "standard"),
                "line": lineno,
            }
            glasses.append(cur)
        elif cur is None:
            continue
        elif key == "GC":
            cur["comment"] = rest.strip()
        elif key == "ED":
            f = _floats(parts)
            cur["tce_m30_70"] = _num(f, 0)
            cur["tce_100_300"] = _num(f, 1)
            cur["density"] = _num(f, 2)
            cur["dpgf"] = _num(f, 3)
        elif key == "CD":
            cur["coefficients"] = [x if math.isfinite(x) else 0.0 for x in _floats(parts)]
        elif key == "TD":
            f = _floats(parts)
            if len(f) >= 7 and all(math.isfinite(x) for x in f[:7]):
                cur["thermal"] = {"D0": f[0], "D1": f[1], "D2": f[2], "E0": f[3], "E1": f[4], "lambda_tk": f[5], "T0": f[6]}
        elif key == "OD":
            f = _floats(parts)
            cur["relative_cost"] = _num(f, 0)
            if cur["relative_cost"] is not None and cur["relative_cost"] < 0:
                cur["relative_cost"] = None  # -1 means "not given"
        elif key == "LD":
            f = _floats(parts)
            cur["lambda_min"] = _num(f, 0)
            cur["lambda_max"] = _num(f, 1)
        elif key == "IT":
            f = _floats(parts)
            if len(f) >= 3 and all(math.isfinite(x) for x in f[:3]) and f[0] > 0 and f[2] > 0:
                cur.setdefault("internal_transmission", []).append([f[0], f[1], f[2]])
        # other keys (BD, RD, ...) carry no data OptiCore uses

    if len(glasses) > MAX_GLASSES:
        cat.diagnostics.append(AgfDiagnostic("error", f"{len(glasses)} glasses: only the first {MAX_GLASSES} are imported"))
        glasses = glasses[:MAX_GLASSES]

    seen: set[str] = set()
    for g in glasses:
        name = g["name"]
        if name in AIR_NAMES | VACUUM_NAMES | {MIRROR_NAME}:
            cat.diagnostics.append(AgfDiagnostic("error", "reserved name; skipped", name))
            continue
        if name in seen:
            cat.diagnostics.append(AgfDiagnostic("warning", "duplicate glass name in the catalogue; the first entry is kept", name))
            continue
        rec = _record(g, catalog, filename, cat.diagnostics)
        if rec is not None:
            seen.add(name)
            cat.records.append(rec)

    n_unverified = sum(1 for r in cat.records if not r["verified"])
    cat.diagnostics.insert(
        0,
        AgfDiagnostic(
            "info",
            f"{len(cat.records)} of {len(glasses)} glasses imported"
            + (f"; {n_unverified} do not reproduce their catalogue Nd/Vd and are flagged" if n_unverified else "; every glass reproduces its catalogue Nd and Vd"),
        ),
    )
    return cat


def _record(g: dict[str, Any], catalog: str, filename: str, diags: list[AgfDiagnostic]) -> dict[str, Any] | None:
    name = g["name"]
    fno = g["agf_formula"]
    if fno not in AGF_FORMULAS:
        diags.append(AgfDiagnostic("error", f"unsupported dispersion formula {fno}; skipped", name))
        return None
    formula, ncoef = AGF_FORMULAS[fno]
    coefs = list(g.get("coefficients") or [])
    if not coefs:
        diags.append(AgfDiagnostic("error", "no dispersion coefficients (CD line); skipped", name))
        return None
    coefs = (coefs + [0.0] * ncoef)[:ncoef]
    if formula == "sellmeier":
        # drop trailing all-zero terms so a 3-term glass stored as Sellmeier 3/5 stays compact
        while len(coefs) > 2 and coefs[-1] == 0.0 and coefs[-2] == 0.0:
            coefs = coefs[:-2]
    lmin = g.get("lambda_min")
    lmax = g.get("lambda_max")
    rec: dict[str, Any] = {
        "name": name,
        "formula": formula,
        "coefficients": coefs,
        "lambda_min": lmin if lmin and lmin > 0 else 0.0,
        "lambda_max": lmax if lmax and lmax > 0 and (not lmin or lmax > lmin) else None,
        "family": catalog,
        "category": "glass",
        "source": f"{catalog} glass catalogue" + (f" ({filename}, AGF import)" if filename else " (AGF import)"),
        "catalog": catalog,
        "status": g["status"],
        "agf_formula": fno,
    }
    if g.get("nd") is not None:
        rec["nd_ref"] = g["nd"]
    if g.get("vd") is not None:
        rec["vd_ref"] = g["vd"]
    for k in ("mil", "comment", "density", "dpgf", "tce_m30_70", "relative_cost", "internal_transmission"):
        v = g.get(k)
        if v not in (None, "", []):
            rec[k] = v
    if g.get("exclude"):
        rec["excluded"] = True
    th = g.get("thermal")
    if th and any(th[k] != 0.0 for k in ("D0", "D1", "D2", "E0", "E1")):
        rec["thermal"] = th

    if not verify_record(rec, diags):
        return None
    if lmin is None or lmax is None:
        diags.append(AgfDiagnostic("warning", "no data range (LD line): extrapolation warnings are not available", name))
    return rec


def verify_record(rec: dict[str, Any], diags: list[AgfDiagnostic]) -> bool:
    """Validates a catalogue record's dispersion and checks it against the catalogue's own Nd / Vd
    (`nd_ref`, `vd_ref`). Sets rec["verified"]; returns False (with an error diagnostic) when the
    data are unusable."""
    name = rec["name"]
    try:
        m = _material_from_record(rec, builtin=False)
        d = m.dispersion
        # (1e-4 um margin: ranges are often quoted to five decimals, e.g. 0.43583-0.65627 um for F'-C)
        if not (d.lambda_min - 1e-4 <= LAMBDA_F and LAMBDA_C <= d.lambda_max + 1e-4) and d.lambda_min > 0 and math.isfinite(d.lambda_max):
            # e.g. infrared glasses: the d, F and C lines lie outside the data; check the data range only
            for lam in np.linspace(d.lambda_min, d.lambda_max, 9):
                n = float(d.index(lam))
                if not (math.isfinite(n) and n > 0):
                    raise DispersionError(f"no real index at {lam:.4g} um")
            rec["verified"] = True
            diags.append(AgfDiagnostic("info", f"data range {d.lambda_min:g}-{d.lambda_max:g} um excludes the F and C lines: nd/Vd not checked", name))
            return True
        nd = m.nd
        vd = m.vd
    except (MaterialError, DispersionError, ZeroDivisionError, ValueError) as exc:
        diags.append(AgfDiagnostic("error", f"invalid dispersion data ({exc}); skipped", name))
        return False
    ok = math.isfinite(nd) and math.isfinite(vd)
    problems = []
    nd_ref = rec.get("nd_ref")
    vd_ref = rec.get("vd_ref")
    if not ok:
        problems.append("the formula gives no real index at the d, F or C line")
    if ok and nd_ref is not None and abs(nd - nd_ref) > ND_TOLERANCE:
        problems.append(f"computed nd {nd:.6f} differs from the catalogue Nd {nd_ref:.6f}")
    if ok and vd_ref is not None and vd_ref > 0 and abs(vd - vd_ref) > max(VD_TOLERANCE, 1e-3 * vd_ref):
        problems.append(f"computed Vd {vd:.3f} differs from the catalogue Vd {vd_ref:.3f}")
    rec["verified"] = not problems
    if problems:
        diags.append(AgfDiagnostic("warning", "; ".join(problems) + " (imported, flagged)", name))
    return True
