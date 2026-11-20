"""Element data of the sample doublet (precision-grade default tolerances) for the frontend drawing tests.

frontend/src/lib/__fixtures__/elements_achromat.json holds what POST /api/v1/elements returns for the
`achromat` sample, so the drawing round trip (frontend/src/lib/drawing.test.ts) runs on engine output and
a backend test notices when it goes stale.

Regenerate the fixture:  python -m opticore.tools.element_fixture --write
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..analysis.elements import elements
from ..jsonutil import jsonable
from ..samples import achromat
from ..tolerance import default_spec

FIXTURE = Path(__file__).resolve().parents[2].parent / "frontend" / "src" / "lib" / "__fixtures__" / "elements_achromat.json"


def build() -> dict:
    p = achromat(True)
    return json.loads(json.dumps(jsonable(elements(p.system, p.custom_materials, default_spec(p.system, "precision")))))


def main() -> None:
    data = build()
    if "--write" in sys.argv:
        FIXTURE.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {len(data['elements'])} elements to {FIXTURE}")
    else:
        print(json.dumps(data, indent=1)[:2000])


if __name__ == "__main__":
    main()
