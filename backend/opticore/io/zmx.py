"""Zemax ZMX (sequential, text) import with detailed diagnostics.

Independent implementation of a reader for the line-oriented ZMX text format
(one keyword per line). Only sequential lenses are supported; binary ZAR
archives and non-sequential files are rejected with a clear message.

Every imported item is classified:
    imported         converted without loss
    partial          converted with simplification (see message)
    unsupported      not converted
    missing_material material not in the catalogue (surface kept, needs user action)
    conversion       potential numerical/convention difference worth checking
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..materials import MaterialLibrary
from ..model import OpticalSystem
from ..project import Metadata, Project, Provenance

UNIT_TO_MM = {"MM": 1.0, "CM": 10.0, "IN": 25.4, "METER": 1000.0, "M": 1000.0}

SUPPORTED_TYPES = {"STANDARD": "standard", "EVENASPH": "even_asphere", "ODDASPH": "odd_asphere", "COORDBRK": "coordinate_break", "PARAXIAL": "ideal"}

# Global records that carry no optical prescription relevant to the trace.
KNOWN_IGNORED_GLOBALS = {
    "VERS", "NOTE", "GCAT", "RAIM", "PUSH", "SDMA", "ROPD", "PICB", "XFLD", "YFLD", "VDXN", "VDYN",
    "VCXN", "VCYN", "VANN", "ZVDX", "ZVDY", "ZVCX", "ZVCY", "ZVAN", "WWGN", "MNUM", "MOFF", "TOL",
    "BLNK", "COFN", "GFAC", "GLRS", "ENVD", "POLS", "EFFL", "DMFS", "CONF", "MCDT", "SCOL",
}


class ZmxError(ValueError):
    pass


@dataclass
class ZmxDiagnostic:
    status: str  # imported | partial | unsupported | missing_material | conversion | info
    message: str
    surface: int | None = None
    line: int | None = None

    def as_dict(self) -> dict:
        return {"status": self.status, "message": self.message, "surface": self.surface, "line": self.line}


@dataclass
class _Surf:
    index: int
    type: str = "STANDARD"
    curv: float = 0.0
    disz: float | None = 0.0
    glas: str = ""
    glas_line: list[str] = field(default_factory=list)
    diam: float | None = None
    clap: float | None = None
    coni: float = 0.0
    parm: dict[int, float] = field(default_factory=dict)
    stop: bool = False
    comment: str = ""
    line: int = 0
    ignored: list[tuple[str, str]] = field(default_factory=list)


def decode_zmx(data: bytes) -> str:
    """ZMX files are UTF-16 LE (with BOM) in recent versions, ASCII/UTF-8/Latin-1 in older ones."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    if len(data) > 4 and data[1:2] == b"\x00" and data[3:4] == b"\x00":
        return data.decode("utf-16-le")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _num(tok: str) -> float:
    t = tok.strip().upper()
    if t in ("INFINITY", "INF", "1.0E+10", "1E+10"):
        return math.inf
    return float(tok)


def parse_zmx(text: str, filename: str = "lens.zmx", catalog_materials: list[dict[str, Any]] | None = None) -> tuple[Project, list[ZmxDiagnostic]]:
    """`catalog_materials`: records of the user's imported glass catalogues. Glasses found there (and not
    built in) are copied into the project's custom materials, so the imported project is self-contained."""
    diags: list[ZmxDiagnostic] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not any(l.strip().startswith(("SURF", "MODE")) for l in lines):
        raise ZmxError("Not a ZMX lens file (no SURF records found). Binary .zar archives must be unpacked first.")

    unit = "MM"
    name = ""
    mode = "SEQ"
    aperture: tuple[str, float] | None = None
    waves: list[tuple[float, float]] = []
    wavl_old: list[float] = []
    wwgt_old: list[float] = []
    pwav = 1
    ftyp: list[float] = []
    xfln: list[float] = []
    yfln: list[float] = []
    fwgn: list[float] = []
    surfs: list[_Surf] = []
    cur: _Surf | None = None
    unknown_global: set[str] = set()

    for ln, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        key = parts[0].upper()
        args = parts[1:]
        indented = raw[:1] in (" ", "\t")
        try:
            if key == "SURF":
                cur = _Surf(index=int(args[0]), line=ln)
                surfs.append(cur)
                continue
            if cur is not None and indented:
                if key == "TYPE":
                    cur.type = args[0].upper()
                elif key == "CURV":
                    cur.curv = float(args[0])
                elif key == "DISZ":
                    v = _num(args[0])
                    cur.disz = None if math.isinf(v) or abs(v) >= 1e10 else v
                elif key == "GLAS":
                    cur.glas = args[0].upper()
                    cur.glas_line = args
                elif key == "DIAM":
                    cur.diam = float(args[0])
                elif key == "CLAP":
                    cur.clap = float(args[1]) if len(args) > 1 else float(args[0])
                elif key == "CONI":
                    cur.coni = float(args[0])
                elif key == "PARM":
                    cur.parm[int(args[0])] = float(args[1])
                elif key == "STOP":
                    cur.stop = True
                elif key == "COMM":
                    cur.comment = line[4:].strip().strip('"')
                elif key == "COAT":
                    what = f"Coating {args[0]}" if args else "Coating"
                    cur.ignored.append(("partial", f"{what} not imported: Zemax coating definitions are not read. Assign a project coating to this surface in the inspector"))
                elif key in ("VPAR", "VDSZ", "VCRV", "VCON"):
                    cur.ignored.append(("partial", "Optimisation variable flags not imported (re-create variables in OptiCore)"))
                elif key in ("PZUP", "CRVS", "THIS"):
                    cur.ignored.append(("partial", "Solve/pickup not imported; the current value is used as fixed"))
                else:
                    cur.ignored.append(("info", f"Keyword {key} ignored"))
                continue
            # global records
            cur = None if not indented else cur
            if key == "UNIT":
                unit = args[0].upper()
            elif key == "NAME":
                name = line[4:].strip()
            elif key == "MODE":
                mode = args[0].upper()
            elif key == "ENPD":
                aperture = ("epd", float(args[0]))
            elif key == "FNUM":
                aperture = ("image_fnum", float(args[0]))
            elif key == "OBNA":
                aperture = ("object_na", float(args[0]))
            elif key == "FLOA":
                aperture = ("float", 0.0)
            elif key == "WAVM":
                if len(args) >= 2:
                    idx = int(args[0])
                    while len(waves) < idx:
                        waves.append((0.0, 0.0))
                    waves[idx - 1] = (float(args[1]), float(args[2]) if len(args) > 2 else 1.0)
            elif key == "WAVL":
                wavl_old = [float(a) for a in args]
            elif key == "WWGT":
                wwgt_old = [float(a) for a in args]
            elif key == "PWAV":
                pwav = int(args[0])
            elif key == "FTYP":
                ftyp = [float(a) for a in args]
            elif key == "XFLN":
                xfln = [float(a) for a in args]
            elif key == "YFLN":
                yfln = [float(a) for a in args]
            elif key == "FWGN" or key == "FWGT":
                fwgn = [float(a) for a in args]
            elif key not in KNOWN_IGNORED_GLOBALS:
                unknown_global.add(key)
        except (ValueError, IndexError) as exc:
            diags.append(ZmxDiagnostic("conversion", f"Line {ln}: could not parse '{line[:60]}' ({exc})", line=ln))

    if mode.startswith("NSC"):
        raise ZmxError("Non-sequential ZMX files are not supported (OptiCore non-sequential mode is planned).")
    if unit not in UNIT_TO_MM:
        raise ZmxError(f"Unsupported lens unit '{unit}'")
    f = UNIT_TO_MM[unit]
    if f != 1.0:
        diags.append(ZmxDiagnostic("conversion", f"Lens units {unit} converted to millimetres (factor {f})"))
    if not surfs:
        raise ZmxError("No surfaces found")
    surfs.sort(key=lambda s: s.index)

    lib = MaterialLibrary()
    user_cat = {str(r.get("name", "")).upper(): r for r in (catalog_materials or [])}
    custom: list[dict[str, Any]] = []
    out_surfs: list[dict[str, Any]] = []
    n = len(surfs)
    for k, s in enumerate(surfs):
        t = SUPPORTED_TYPES.get(s.type)
        d: dict[str, Any] = {"id": f"z{k}", "label": s.comment or "", "comment": s.comment}
        if t is None:
            diags.append(ZmxDiagnostic("unsupported", f"Surface type {s.type} is not supported; imported as a plane dummy surface", k, s.line))
            t = "standard"
            s.curv = 0.0
            s.coni = 0.0
            s.parm = {}
        d["type"] = t
        if t == "coordinate_break":
            p = s.parm
            d.update(
                decenter_x=p.get(1, 0.0) * f,
                decenter_y=p.get(2, 0.0) * f,
                tilt_x=p.get(3, 0.0),
                tilt_y=p.get(4, 0.0),
                tilt_z=p.get(5, 0.0),
                cb_order=1 if p.get(6, 0.0) != 0 else 0,
            )
            if any(p.get(i, 0.0) for i in (3, 4, 5)):
                diags.append(ZmxDiagnostic("conversion", "Coordinate-break tilts imported with OptiCore's right-handed convention; verify folded geometry in the layout", k, s.line))
        elif t == "ideal":
            # paraxial surface: PARM 1 = focal length, PARM 2 = OPD mode
            fl = s.parm.get(1, 0.0)
            d["focal_length"] = None if fl == 0 else fl * f
            mode = int(s.parm.get(2, 0.0))
            diags.append(
                ZmxDiagnostic(
                    "conversion",
                    f"Paraxial surface imported as an OptiCore ideal lens (f = {d['focal_length']} mm); its OPD is exact for an object at infinity"
                    + ("" if mode == 0 else f" (ZMX OPD mode {mode} has no equivalent: set the ideal lens's OPD object distance if the design conjugate is finite)"),
                    k,
                    s.line,
                )
            )
        else:
            d["radius"] = None if s.curv == 0 else (1.0 / s.curv) * f
            d["conic"] = s.coni
        d["thickness"] = None if s.disz is None else s.disz * f
        if k != 0 and d["thickness"] is None:
            diags.append(ZmxDiagnostic("conversion", "Infinite thickness on an inner surface replaced by 1e6 mm", k, s.line))
            d["thickness"] = 1e6
        if t == "even_asphere":
            coeffs = []
            for j in range(2, 10):  # PARM 2 = r^4 ... PARM 9 = r^18
                a = s.parm.get(j, 0.0)
                power = 2 * j  # r^(2j)
                coeffs.append(a * f ** (1 - power))
            while coeffs and coeffs[-1] == 0.0:
                coeffs.pop()
            d["aspheric"] = coeffs[:8]
            if s.parm.get(1, 0.0):
                diags.append(ZmxDiagnostic("partial", "Even-asphere r^2 term (PARM 1) is not supported by OptiCore and was dropped; fold it into the base curvature manually", k, s.line))
        if t == "odd_asphere":
            coeffs = [s.parm.get(j, 0.0) * f ** (1 - j) for j in range(1, 9)]  # PARM j = beta_j on r^j
            while coeffs and coeffs[-1] == 0.0:
                coeffs.pop()
            d["odd_coefficients"] = coeffs
        # material
        g = s.glas
        if t == "coordinate_break":
            d["material"] = "AIR"
        elif g in ("", "AIR"):
            d["material"] = "AIR"
        elif g == "MIRROR":
            d["material"] = "MIRROR"
        elif g == "___BLANK" or g.startswith("___"):
            # model glass: GLAS ___BLANK flag ? nd vd ...
            try:
                nd = float(s.glas_line[3])
                vd = float(s.glas_line[4])
                nm = f"MODEL_{nd:.4f}_{vd:.2f}".replace(".", "_")
                if not any(c["name"] == nm for c in custom):
                    custom.append(_model_glass(nm, nd, vd))
                d["material"] = nm
                diags.append(ZmxDiagnostic("conversion", f"Model glass nd={nd}, Vd={vd} approximated with a two-term Cauchy fit through nd and nF-nC", k, s.line))
            except (IndexError, ValueError):
                d["material"] = "AIR"
                diags.append(ZmxDiagnostic("unsupported", "Model glass without nd/Vd could not be converted; set to AIR", k, s.line))
        elif lib.has(g):
            d["material"] = g
        elif g in user_cat:
            d["material"] = g
            if not any(c["name"] == g for c in custom):
                custom.append(user_cat[g])
                diags.append(ZmxDiagnostic("conversion", f"Material '{g}' taken from the imported {user_cat[g].get('catalog', 'user')} catalogue and stored in the project", k, s.line))
        else:
            d["material"] = "AIR"
            d["comment"] = (s.comment + " " if s.comment else "") + f"[missing material {g}]"
            diags.append(ZmxDiagnostic("missing_material", f"Material '{g}' is not in the OptiCore catalogue; surface set to AIR. Define it in the Material library and assign it.", k, s.line))
        # aperture
        sd = s.clap if s.clap is not None else s.diam
        if sd is not None:
            d["semi_diameter"] = sd * f
            d["semi_diameter_mode"] = "fixed" if s.clap is not None else "auto"
        if s.stop and 0 < k < n - 1:
            d["is_stop"] = True
        for status, msg in sorted(set(s.ignored)):
            diags.append(ZmxDiagnostic(status, msg, k, s.line))
        out_surfs.append(d)

    # wavelengths
    if not waves and wavl_old:
        waves = [(w, wwgt_old[i] if i < len(wwgt_old) else 1.0) for i, w in enumerate(wavl_old)]
    # OpticStudio writes all WAVM slots; FTYP's 4th value is the active count
    if len(ftyp) >= 4 and ftyp[3] > 0 and len(waves) > int(ftyp[3]):
        waves = waves[: int(ftyp[3])]
    waves = [(w, wt) for (w, wt) in waves if w > 0]
    if not waves:
        waves = [(0.5875618, 1.0)]
        diags.append(ZmxDiagnostic("conversion", "No wavelengths found; using the d line"))
    prim = max(0, min(len(waves) - 1, pwav - 1))

    # fields
    ftype_code = int(ftyp[0]) if ftyp else 0
    nf = int(ftyp[2]) if len(ftyp) >= 3 and ftyp[2] > 0 else max(1, len([1 for x, y in zip(xfln or [0.0] * len(yfln), yfln) if x or y]) + 1)
    nf = max(1, min(nf, 25, max(len(yfln), 1)))
    fields = []
    for i in range(nf):
        fx = xfln[i] if i < len(xfln) else 0.0
        fy = yfln[i] if i < len(yfln) else 0.0
        w = fwgn[i] if i < len(fwgn) else 1.0
        fields.append({"x": fx, "y": fy, "weight": w if w >= 0 else 1.0})
    field_type = "angle"
    if ftype_code == 1:
        field_type = "object_height"
        for fd in fields:
            fd["x"] *= f
            fd["y"] *= f
    elif ftype_code in (2, 3):
        # FTYP 2: paraxial image height, 3: real image height (lens units)
        field_type = "paraxial_image_height" if ftype_code == 2 else "image_height"
        for fd in fields:
            fd["x"] *= f
            fd["y"] *= f
        diags.append(ZmxDiagnostic("conversion", f"{'Paraxial' if ftype_code == 2 else 'Real'} image-height fields imported; OptiCore resolves them to object fields at the primary wavelength"))
    elif ftype_code not in (0,):
        diags.append(ZmxDiagnostic("unsupported", f"Field type {ftype_code} is not supported; values imported as angles in degrees — re-enter the fields"))
    if field_type == "object_height" and out_surfs[0]["thickness"] is None:
        field_type = "angle"
        diags.append(ZmxDiagnostic("conversion", "Object-height fields with an object at infinity converted to angle fields"))

    # aperture
    ap = {"type": "epd", "value": 10.0}
    if aperture is None:
        diags.append(ZmxDiagnostic("conversion", "No aperture definition found; entrance pupil diameter set to 10 mm"))
    elif aperture[0] == "float":
        stop_k = next((i for i, s in enumerate(surfs) if s.stop), 1)
        sd = surfs[stop_k].diam or 5.0
        ap = {"type": "epd", "value": 2 * sd * f}
        diags.append(ZmxDiagnostic("partial", "'Float by stop size' converted to an entrance pupil diameter equal to the stop diameter (exact only if the stop is in object space)"))
    elif aperture[0] == "epd":
        ap = {"type": "epd", "value": aperture[1] * f}
    else:
        ap = {"type": aperture[0], "value": aperture[1]}
    if ap["type"] == "object_na" and out_surfs[0]["thickness"] is None:
        ap = {"type": "epd", "value": 10.0}
        diags.append(ZmxDiagnostic("conversion", "Object NA with an object at infinity is undefined; EPD set to 10 mm"))

    if not any(d.get("is_stop") for d in out_surfs):
        diags.append(ZmxDiagnostic("info", "No STOP record; surface 1 is used as the aperture stop"))

    for key in sorted(unknown_global):
        diags.append(ZmxDiagnostic("info", f"Global keyword {key} ignored"))

    sysdict = {
        "name": name or filename,
        "surfaces": out_surfs,
        "wavelengths": [{"value": w, "weight": wt} for w, wt in waves][:24],
        "primary_wavelength": prim,
        "field_type": field_type,
        "fields": fields,
        "aperture": ap,
        "ray_aiming": "paraxial",
    }
    try:
        system = OpticalSystem.model_validate(sysdict)
    except Exception as exc:
        raise ZmxError(f"The converted system is invalid: {exc}") from exc

    n_imp = len(out_surfs)
    diags.insert(0, ZmxDiagnostic("imported", f"Imported {n_imp} surfaces, {len(waves)} wavelengths and {len(fields)} fields from {filename}"))
    project = Project(
        metadata=Metadata(name=name or filename.rsplit(".", 1)[0], description=f"Imported from {filename}"),
        system=system,
        custom_materials=custom,
        provenance=Provenance(
            imports=[{"format": "zmx", "file": filename, "unit": unit, "diagnostics": [d.as_dict() for d in diags]}],
            warnings=[d.message for d in diags if d.status in ("unsupported", "missing_material", "partial")],
        ),
    )
    return project, diags


def _model_glass(name: str, nd: float, vd: float) -> dict[str, Any]:
    """Two-term Cauchy n = A + B/L^2 through nd with dispersion nF - nC = (nd-1)/vd."""
    lf, lc, ld = 0.4861327, 0.6562725, 0.5875618
    dn = (nd - 1.0) / vd if vd else 0.0
    B = dn / (1.0 / lf**2 - 1.0 / lc**2)
    A = nd - B / ld**2
    return {
        "name": name,
        "formula": "cauchy",
        "coefficients": [A, B],
        "lambda_min": 0.4,
        "lambda_max": 0.8,
        "family": "MODEL",
        "category": "model glass",
        "source": f"Model glass from ZMX (nd={nd}, Vd={vd}); Cauchy approximation",
    }

