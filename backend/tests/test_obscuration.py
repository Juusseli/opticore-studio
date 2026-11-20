"""Central obscurations: blocked rays, chief-ray references, and the MTF of an annular pupil (O'Neill)."""

import math

import numpy as np
import pytest

from opticore.analysis.diffraction import mtf
from opticore.analysis.evaluate import evaluate_system
from opticore.analysis.spot import spot_diagram
from opticore.paraxial import compute_pupil
from opticore.raytrace import pupil_pattern, trace_pupil
from opticore.samples import get_sample
from opticore.surfaces import OBSCURED, STATUS_TEXT
from opticore.system import compile_system

from .conftest import make_system


def annular_mtf(nu: np.ndarray, e: float) -> np.ndarray:
    """MTF of an aberration-free circular pupil with a central obscuration of ratio e (E. L. O'Neill, JOSA 46,
    285 (1956)); nu normalised to the cutoff frequency."""
    out = []
    for v in np.atleast_1d(nu):
        if v >= 1.0:
            out.append(0.0)
            continue
        A = (2 / math.pi) * (math.acos(v) - v * math.sqrt(1 - v * v))
        B = 0.0
        if e > 0 and v <= e:
            x = v / e
            B = (2 * e * e / math.pi) * (math.acos(x) - x * math.sqrt(1 - x * x))
        if v <= (1 - e) / 2:
            C = -2 * e * e
        elif v < (1 + e) / 2:
            phi = math.acos((1 + e * e - 4 * v * v) / (2 * e))
            C = (2 * e / math.pi) * math.sin(phi) + ((1 + e * e) / math.pi) * phi - (2 * (1 - e * e) / math.pi) * math.atan((1 + e) / (1 - e) * math.tan(phi / 2)) - 2 * e * e
        else:
            C = 0.0
        out.append((A + B + C) / (1 - e * e))
    return np.array(out)


def ideal(e=0.33, epd=20.0):
    return make_system(
        [{"thickness": None}, {"type": "ideal", "focal_length": 100.0, "thickness": 100.0, "is_stop": True, "semi_diameter": 60.0, "obscuration": e * epd / 2}, {"thickness": 0.0}],
        wavelengths=[{"value": 0.55}],
        fields=[{"y": 0.0}, {"y": 2.0}],
        aperture={"type": "epd", "value": epd},
    )


def test_obscured_pupil_area_and_status():
    e = 0.33
    cs = compile_system(ideal(e))
    assert "OBSCURATION" in [d.code for d in cs.diagnostics]
    px, py = pupil_pattern("square", 401)
    r = trace_pupil(cs, 0, 0, px, py, compute_pupil(cs))
    assert r.ok.mean() == pytest.approx(1 - e * e, abs=0.003)  # area fraction of the annulus
    assert set(np.unique(r.status)) == {0, OBSCURED}
    assert STATUS_TEXT[OBSCURED] == "blocked by central obscuration"
    inner = np.hypot(px, py) < e - 1e-3
    assert np.all(r.status[inner] == OBSCURED) and np.all(r.ok[np.hypot(px, py) > e + 1e-3])


def test_chief_rays_are_references_through_the_obscuration():
    cs = compile_system(ideal())
    assert not trace_pupil(cs, 0, 1, np.array([0.0]), np.array([0.0]), compute_pupil(cs)).ok[0]
    assert trace_pupil(cs, 0, 1, np.array([0.0]), np.array([0.0]), compute_pupil(cs), obscure=False).ok[0]
    ev = evaluate_system(cs, layout_rays_per_field=5, ring_rays=0)
    assert "RAY_FAILED" not in [d["code"] if isinstance(d, dict) else d.code for d in ev["diagnostics"]]
    sp = spot_diagram(cs, reference="chief")
    assert all(math.isfinite(f["rms_radius_um"]) for f in sp["fields"])


def test_mtf_of_an_obscured_pupil_matches_oneill():
    e = 0.33
    cs = compile_system(ideal(e))
    r = mtf(cs, fields=[0], samples=41, grid=256, pad=4)
    nu = np.array(r["frequency_cyc_per_mm"]) / np.atleast_1d(r["cutoff_cyc_per_mm"])[0]
    ref = annular_mtf(nu, e)
    for k in ("tangential", "sagittal"):
        assert np.allclose(r["fields"][0][k], ref, atol=1e-3)
    assert annular_mtf(np.array([0.0, 0.5]), 0.0) == pytest.approx([1.0, (2 / math.pi) * (math.acos(0.5) - 0.5 * math.sqrt(0.75))])  # e = 0: circular


def test_hubble_mtf_with_its_obscuration_is_near_the_annular_limit():
    """The HST design on axis (Strehl about 0.99) with its 33 % obscuration: MTF within 0.02 of the
    aberration-free annular pupil."""
    p = get_sample("hubble")
    cs = compile_system(p.system)
    r = mtf(cs, fields=[0], samples=31, grid=128, pad=4)
    nu = np.array(r["frequency_cyc_per_mm"]) / np.atleast_1d(r["cutoff_cyc_per_mm"])[0]
    ref = annular_mtf(nu, 396.0 / 1200.0)
    assert np.allclose(r["fields"][0]["tangential"], ref, atol=0.02)
    assert not np.allclose(r["fields"][0]["tangential"], annular_mtf(nu, 0.0), atol=0.02)  # the obscuration shows


def test_obscuration_on_the_image_surface_is_ignored():
    sysd = ideal()
    sysd.surfaces[-1].obscuration = 1.0
    sysd.surfaces[1].obscuration = None
    cs = compile_system(sysd)
    assert "OBSCURATION_IGNORED" in [d.code for d in cs.diagnostics] and cs.obscuration is None
