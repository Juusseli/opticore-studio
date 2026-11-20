"""Every analysis endpoint on every sample design (the robustness matrix).

Each call must either succeed with finite numbers, or refuse with NOT_APPLICABLE (a documented limitation of the
analysis for that kind of system, shown as such by the UI). Any other error is a bug. The settings are the UI's
defaults with lighter sampling where an analysis is heavy (the point is that nothing breaks, not the numbers).
"""

import math
import typing

import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.samples import SAMPLES, get_sample

client = TestClient(app, raise_server_exceptions=False)
ROUTES = [r for r in app.routes if getattr(r, "path", "").startswith(("/api/v1/analysis", "/api/v1/system", "/api/v1/elements")) and "POST" in getattr(r, "methods", set())]
SKIP = {"/api/v1/analysis/surface-context"}  # needs a chosen surface; covered by the coating tests
LIGHT = {
    "/api/v1/analysis/nonseq": {"rays": 16, "max_seconds": 2},
    "/api/v1/analysis/image-simulation": {"crop_px": 32, "grid": 3, "oversample": 1},
    "/api/v1/analysis/live-image": {"width": 48},
    "/api/v1/analysis/pop": {"grid": 64, "out_grid": 64},
    "/api/v1/analysis/vector-psf": {"rings": 12, "grid": 41},
    "/api/v1/analysis/thermal": {"steps": 3},
}


def _model(route):
    for name, M in typing.get_type_hints(route.endpoint).items():
        if name != "return" and hasattr(M, "model_fields"):
            return M
    return None


def _nonfinite(x, path="", out=None):
    out = [] if out is None else out
    if len(out) >= 3:
        return out
    if isinstance(x, float) and not math.isfinite(x):
        out.append(path)
    elif isinstance(x, dict):
        for k, v in x.items():
            _nonfinite(v, f"{path}.{k}", out)
    elif isinstance(x, list):
        for i, v in enumerate(x[:5000]):
            _nonfinite(v, f"{path}[{i}]", out)
    return out


@pytest.mark.parametrize("sid", list(SAMPLES))
def test_every_analysis_runs_or_says_it_does_not_apply(sid):
    p = get_sample(sid)
    base = {"system": p.system.model_dump(mode="json"), "custom_materials": [m if isinstance(m, dict) else m.model_dump(mode="json") for m in p.custom_materials]}
    if p.sources:
        base["sources"] = [s.model_dump(mode="json") for s in p.sources]
    if p.detectors:
        base["detectors"] = [d.model_dump(mode="json") for d in p.detectors]
    infinite = p.system.surfaces[0].thickness is None
    nf = len(p.system.fields)
    failures = []
    for r in ROUTES:
        if r.path in SKIP:
            continue
        M = _model(r)
        fields = M.model_fields if M else {}
        extra = dict(LIGHT.get(r.path, {}))
        if r.path.endswith("/pop") and infinite:
            extra["source"] = {"kind": "pupil"}  # the UI's default for an object at infinity
        if r.path.endswith("/sweep"):
            s1 = p.system.surfaces[1]
            t1 = s1.thickness or 1.0
            extra = {"parameters": [{"surface_id": s1.id, "parameter": "thickness", "start": 0.9 * t1, "stop": 1.1 * t1, "steps": 3}], "metrics": [{"type": "rms_spot"}]}
        variants = [extra]
        if "field" in fields and nf > 1:
            variants.append({**extra, "field": nf - 1})
        for v in variants:
            body = {k: val for k, val in {**base, **v}.items() if k in fields or k in ("system", "custom_materials")}
            res = client.post(r.path, json=body)
            j = res.json() if res.headers.get("content-type", "").startswith("application/json") else None
            if res.status_code == 200:
                bad = _nonfinite(j)
                if bad:
                    failures.append(f"{r.path} {v.get('field', '')}: non-finite numbers at {bad}")
            elif not (res.status_code == 422 and isinstance(j, dict) and (j.get("error") or {}).get("code") == "NOT_APPLICABLE"):
                err = (j or {}).get("error", {}) if isinstance(j, dict) else {}
                failures.append(f"{r.path} {v.get('field', '')}: HTTP {res.status_code} {err.get('code')}: {str(err.get('message'))[:200]}")
    assert not failures, f"{sid}:\n" + "\n".join(failures)
