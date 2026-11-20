"""The fibre examples' view settings and the requests the engine's tests send for them (samples.fibre_request).

frontend/src/lib/__fixtures__/fibre_examples.json holds both; the frontend test checks that lib/fibre.ts builds the
same request from the same settings, so the library examples are verified exactly as the Fibre Modes view runs them.

Regenerate the fixture:  python -m opticore.tools.fibre_examples --write
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..samples import SAMPLES, fibre_request, get_sample

FIXTURE = Path(__file__).resolve().parents[2].parent / "frontend" / "src" / "lib" / "__fixtures__" / "fibre_examples.json"


def collect() -> dict:
    out = {}
    for sid in SAMPLES:
        p = get_sample(sid)
        st = p.analysis_settings.get("fibermodes")
        if not st:
            continue
        lam = p.system.wavelengths[p.system.primary_wavelength].value
        out[sid] = {"settings": st, "system_wavelength_um": lam, "request": fibre_request(st, lam)}
    return out


def main() -> None:
    text = json.dumps(collect(), indent=2, ensure_ascii=False) + "\n"
    if "--write" in sys.argv:
        FIXTURE.write_text(text, encoding="utf-8")
        print(f"wrote {FIXTURE}")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
