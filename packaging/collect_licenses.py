"""Collect the licence texts of everything the packaged program contains, for the folder ``licenses`` in the package.

* the Python runtime;
* every Python distribution the engine needs at run time (``opticore`` and its dependencies, recursively);
* every npm package bundled into the user interface (``frontend/package.json`` dependencies, recursively).

Writes ``packaging/build/licenses/<package>/<licence files>`` and an index ``packaging/build/licenses/README.txt``.
Run with the engine's Python from the repository root: python packaging/collect_licenses.py
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "packaging" / "build" / "licenses"
# Python distributions that dependencies declare but the program never imports; the package leaves them out
# (opticore-studio.spec excludes their modules), so their licences are not listed either.
NOT_BUNDLED = {"matplotlib", "pillow", "contourpy", "cycler", "fonttools", "kiwisolver", "pyparsing", "python-dateutil", "six"}
NOT_BUNDLED_MODULES = ["matplotlib", "PIL", "contourpy", "cycler", "fontTools", "kiwisolver", "pyparsing", "dateutil", "tkinter", "pytest", "IPython", "PyInstaller"]
LICENCE_NAME = re.compile(r"^(licen[cs]e|copying|notice|authors)([.-].*)?$", re.I)


def _wanted(requirements: list[str], extras: set[str]) -> list[tuple[str, set[str]]]:
    """(name, extras) of the requirements that apply here: platform markers evaluated, optional extras only if asked."""
    from packaging.requirements import Requirement

    out = []
    for text in requirements:
        req = Requirement(text)
        if req.marker is not None and not any(req.marker.evaluate({"extra": e}) for e in (extras or {""})):
            continue
        out.append((req.name, set(req.extras)))
    return out


def python_distributions() -> list[metadata.Distribution]:
    import tomllib

    project = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    seen: dict[str, metadata.Distribution] = {}
    todo = _wanted(project["dependencies"], set())  # the engine's own list (installed metadata can be stale)
    while todo:
        name, extras = todo.pop()
        key = name.lower().replace("_", "-")
        if key in NOT_BUNDLED:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        if key not in seen or extras:
            todo += _wanted(dist.requires or [], extras)
        seen[key] = dist
    return [d for _, d in sorted(seen.items())]


def npm_packages() -> list[Path]:
    modules = ROOT / "frontend" / "node_modules"
    todo = list(json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8")).get("dependencies", {}))
    seen: dict[str, Path] = {}
    while todo:
        name = todo.pop()
        if name in seen or not (modules / name / "package.json").is_file():
            continue
        seen[name] = modules / name
        todo += list(json.loads((modules / name / "package.json").read_text(encoding="utf-8")).get("dependencies", {}))
    return [seen[n] for n in sorted(seen)]


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    index = ["Licences of the components bundled with OptiCore Studio.", "OptiCore Studio itself: GNU AGPL v3 or later (LICENSE); data: THIRD_PARTY_NOTICES.md.", ""]

    py_licence = next((p for p in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE") if p.is_file()), None)
    if py_licence:
        (OUT / "python").mkdir()
        shutil.copy(py_licence, OUT / "python" / "LICENSE.txt")
    index.append(f"python {sys.version.split()[0]}: PSF License")

    for dist in python_distributions():
        name, version = dist.metadata["Name"], dist.version
        files = [f for f in (dist.files or []) if LICENCE_NAME.match(Path(str(f)).name) or "/licenses/" in str(f).lower()]
        target = OUT / f"python-{name}"
        for f in files:
            src = Path(dist.locate_file(f))
            if src.is_file():
                target.mkdir(exist_ok=True)
                shutil.copy(src, target / src.name)
        expr = dist.metadata.get("License-Expression") or next((c.split("::")[-1].strip() for c in dist.metadata.get_all("Classifier") or [] if c.startswith("License ::")), None) or (dist.metadata.get("License") or "").splitlines()[0][:80]
        index.append(f"{name} {version} (Python): {expr or 'see folder'}")

    for pkg in npm_packages():
        meta = json.loads((pkg / "package.json").read_text(encoding="utf-8"))
        files = [p for p in pkg.iterdir() if p.is_file() and LICENCE_NAME.match(p.name)]
        target = OUT / ("npm-" + meta["name"].replace("/", "__"))
        for f in files:
            target.mkdir(exist_ok=True)
            shutil.copy(f, target / f.name)
        lic = meta.get("license") or meta.get("licenses") or "see folder"
        index.append(f"{meta['name']} {meta.get('version', '')} (npm): {lic if isinstance(lic, str) else json.dumps(lic)}")

    (OUT / "README.txt").write_text("\n".join(index) + "\n", encoding="utf-8")
    print(f"{len(index) - 3} components, licences in {OUT}")


if __name__ == "__main__":
    main()
