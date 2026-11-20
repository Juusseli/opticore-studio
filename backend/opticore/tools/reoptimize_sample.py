"""Re-run the optimisation that produced a frozen sample and print the result.

    python -m opticore.tools.reoptimize_sample achromat-start
"""

from __future__ import annotations

import sys

from ..model import OpticalSystem
from ..optimize import optimize
from ..samples import get_sample


def main(argv: list[str]) -> int:
    sample_id = argv[1] if len(argv) > 1 else "achromat-start"
    p = get_sample(sample_id)
    ns = (p.sources, p.detectors) if (p.sources or p.detectors) else None
    r = optimize(p.system, p.optimization, p.custom_materials, ns=ns, parallel=False)  # the same design on any machine
    print(f"status={r['status']} evaluations={r['evaluations']} merit {r['initial_merit']:.6g} -> {r['final_merit']:.6g}")
    sysopt = OpticalSystem.model_validate(r["system"])
    for s in sysopt.surfaces:
        print(f"  {s.id:6s} R={s.radius!s:>22} t={s.thickness!s:>22} {s.material}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
