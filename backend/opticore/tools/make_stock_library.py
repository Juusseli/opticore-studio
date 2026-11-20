"""Write the generic stock lens library (opticore/materials/data/stock_generic.json).

    python -m opticore.tools.make_stock_library

The rules are in opticore/stock.py. The output is deterministic; tests/test_stock.py regenerates a sample of
lenses and compares them with the file.
"""

from __future__ import annotations

import json
import pathlib
import time

from ..stock import make_generic_library

OUT = pathlib.Path(__file__).resolve().parents[1] / "materials" / "data" / "stock_generic.json"


def main() -> None:
    t0 = time.time()
    lenses = make_generic_library()
    doc = {
        "catalog_version": 1,
        "notes": "OptiCore generic stock lenses: OptiCore's own designs at standard focal lengths and diameters, not any vendor's parts. "
        "Rules in opticore/stock.py; regenerate with python -m opticore.tools.make_stock_library.",
        "lenses": [l.model_dump(mode="json", exclude_none=True) for l in lenses],
    }
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    kinds: dict[str, int] = {}
    for l in lenses:
        kinds[l.kind] = kinds.get(l.kind, 0) + 1
    print(f"{len(lenses)} lenses {kinds} in {time.time() - t0:.1f} s -> {OUT}")


if __name__ == "__main__":
    main()
