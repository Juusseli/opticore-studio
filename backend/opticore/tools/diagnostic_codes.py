"""List the diagnostic codes the engine can emit (static scan of every `Diagnostic(level, "CODE", ...)`).

The UI explains each code with a cause and a fix (frontend/src/lib/diagnostics.ts); the list is kept in
frontend/src/lib/__fixtures__/diagnostic_codes.json so a test on each side notices a new code.

Regenerate the fixture:  python -m opticore.tools.diagnostic_codes --write
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
FIXTURE = PACKAGE.parents[1] / "frontend" / "src" / "lib" / "__fixtures__" / "diagnostic_codes.json"


def collect_codes() -> dict[str, list[str]]:
    """{code: sorted levels} of every Diagnostic built with a literal code in the engine package."""
    codes: dict[str, set[str]] = {}
    for f in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "Diagnostic" or len(node.args) < 2 or not isinstance(node.args[1], ast.Constant):
                continue
            level = node.args[0].value if isinstance(node.args[0], ast.Constant) else "?"
            codes.setdefault(str(node.args[1].value), set()).add(str(level))
    return {k: sorted(v) for k, v in sorted(codes.items())}


def main() -> None:
    codes = collect_codes()
    text = json.dumps(codes, indent=2) + "\n"
    if "--write" in sys.argv:
        FIXTURE.write_text(text, encoding="utf-8")
        print(f"wrote {len(codes)} codes to {FIXTURE}")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
