# PyInstaller build of the OptiCore Studio desktop program.
#
# The program is a folder (onedir), not a single file: it starts faster, and the LGPL libraries of Open CASCADE stay
# separate, replaceable files. Build from the repository root, after `npm run build` in frontend/ and
# `python packaging/collect_licenses.py`:
#
#     python -m PyInstaller packaging/opticore-studio.spec --noconfirm --distpath packaging/dist --workpath packaging/build/pyinstaller
#
# On Windows the result is "packaging/dist/OptiCore Studio/OptiCore Studio.exe", on Linux
# "packaging/dist/opticore-studio/opticore-studio".

import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT / "packaging"))
from collect_licenses import NOT_BUNDLED_MODULES  # noqa: E402

WINDOWS = sys.platform == "win32"
NAME = "OptiCore Studio" if WINDOWS else "opticore-studio"
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "backend" / "opticore" / "__init__.py").read_text(encoding="utf-8")).group(1)

for need in (ROOT / "frontend" / "dist" / "index.html", ROOT / "packaging" / "build" / "licenses" / "README.txt"):
    if not need.is_file():
        raise SystemExit(f"Missing {need}: build the user interface and collect the licences first (see this file's header)")

datas = collect_data_files("opticore", excludes=["**/__pycache__/**"])
datas += [
    (str(ROOT / "frontend" / "dist"), "ui"),
    (str(ROOT / "packaging" / "build" / "licenses"), "licenses"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]
# the engine imports most of its modules inside the request handlers; the generators in opticore.tools are not needed
hiddenimports = collect_submodules("opticore", filter=lambda m: not m.startswith("opticore.tools")) + collect_submodules("uvicorn")

binaries = []
if WINDOWS:
    # OCP's extension module links DLLs that its wheel keeps in cadquery_ocp.libs and vtk.libs, next to the package,
    # and OCP/__init__.py adds those two folders to the DLL search path. Collect exactly the DLLs it needs, recursively,
    # into folders of the same names.
    import importlib.util

    import pefile

    site = Path(importlib.util.find_spec("OCP").origin).parent.parent
    libdirs = [site / "cadquery_ocp.libs", site / "vtk.libs"]
    available = {p.name.lower(): p for d in libdirs for p in d.glob("*.dll")}

    def imported_dlls(path: Path) -> list[str]:
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"], pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
        entries = list(getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])) + list(getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", []))
        return [e.dll.decode("ascii", "replace").lower() for e in entries]

    todo = [next((site / "OCP").glob("OCP*.pyd"))]
    needed: dict[str, Path] = {}
    while todo:
        for name in imported_dlls(todo.pop()):
            if name in available and name not in needed:
                needed[name] = available[name]
                todo.append(available[name])
    binaries = [(str(p), p.parent.name) for p in needed.values()]
    for d in libdirs:  # OCP/__init__.py adds both folders; each must exist
        if not any(dest == d.name for _, dest in binaries):
            raise SystemExit(f"No DLL collected from {d}: check the OCP wheel layout")
    print(f"OCP: {len(needed)} DLLs from {', '.join(d.name for d in libdirs)}")

a = Analysis(
    [str(ROOT / "packaging" / "opticore_studio.py")],
    pathex=[str(ROOT / "backend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=NOT_BUNDLED_MODULES,
    noarchive=False,
)
pyz = PYZ(a.pure)

version_info = None
if WINDOWS:
    from PyInstaller.utils.win32.versioninfo import FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo

    nums = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("CompanyName", "Juuso Heiskanen"),
                            StringStruct("FileDescription", "OptiCore Studio: optical design and simulation"),
                            StringStruct("FileVersion", VERSION),
                            StringStruct("InternalName", "OptiCore Studio"),
                            StringStruct("LegalCopyright", "Copyright (C) 2026 Juuso Heiskanen. GNU AGPL v3 or later."),
                            StringStruct("OriginalFilename", "OptiCore Studio.exe"),
                            StringStruct("ProductName", "OptiCore Studio"),
                            StringStruct("ProductVersion", VERSION),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=not WINDOWS,  # Windows: a windowed program (the app window is the browser); the log is in %LOCALAPPDATA%
    icon=str(ROOT / "packaging" / "assets" / "opticore-studio.ico"),
    version=version_info,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)
