"""Direct-path source-to-detector trace (nsdirect.py), anchored placements and the detector
operands of the optimiser.

References: the full non-sequential trace without splitting (independent per-ray B-rep trace)
for the same seeded rays, Fresnel transmission of a plane window in closed form, the second
moment of a uniform disc (D4sigma = disc diameter), the surface vertex frames, and root finding
on the direct trace for the detector-operand optimisation. The beam systems are the neutral test
systems of tests/beam_systems.py."""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.model import OpticalSystem
from opticore.nonseq import build_scene, trace_nonsequential
from opticore.nsdirect import trace_direct
from opticore.nssources import Detector, LightSource, placement_matrix, surface_frames
from opticore.optimize import optimize
from opticore.optimize.merit import MeritFunction
from opticore.samples import get_sample
from opticore.system import SystemError_, compile_system

from .beam_systems import THICK_LENS_TARGET, relay, singlet, thick_lens
from .conftest import make_system

client = TestClient(app)


def _window(t=5.0, gap=10.0, sd=10.0):
    return make_system(
        [
            {"id": "obj", "thickness": gap},
            {"id": "a", "thickness": t, "material": "N-BK7", "semi_diameter": sd, "semi_diameter_mode": "fixed", "is_stop": True},
            {"id": "b", "thickness": gap, "semi_diameter": sd, "semi_diameter_mode": "fixed"},
            {"id": "img"},
        ],
        wavelengths=[{"value": 0.5875618}],
        field_type="object_height",
        fields=[{"y": 0.0}],
        aperture={"type": "object_na", "value": 0.1},
    )


@pytest.mark.parametrize("make", [thick_lens, relay, singlet], ids=["thick-lens", "relay", "singlet"])
def test_direct_path_equals_nonsequential_trace_without_splitting(make):
    p = make()
    cs = compile_system(p.system, p.custom_materials)
    d = trace_direct(cs, p.sources, p.detectors, seed=3)
    scene = build_scene(cs, [], True, None, p.custom_materials, p.detectors)
    r = trace_nonsequential(cs, scene, sources=p.sources, split=False, seed=3, keep_paths=0)
    for a, b in zip(d["detectors"], r["detectors"]):
        assert a["fraction"] == pytest.approx(b["fraction"], abs=1e-12)
        np.testing.assert_allclose(a["width_2sigma_mm"], b["width_2sigma_mm"], rtol=1e-9)
        np.testing.assert_allclose(a["centroid_mm"], b["centroid_mm"], atol=1e-12)
    assert d["lost_w"]["outside_aperture"] == 0.0


def test_window_fresnel_and_uniform_disc_second_moment():
    cs = compile_system(_window())
    a = 2.0
    src = LightSource(placement={"anchor": "obj"}, shape="disk", size_x=a, angular="collimated", rays=4000, power_w=1.0)
    det = Detector(id="d", placement={"anchor": "img"}, size_x=5.0)
    r = trace_direct(cs, [src], [det])["detectors"][0]
    n = float(cs.n_after[0, 1])
    T = 1 - ((n - 1) / (n + 1)) ** 2
    assert r["fraction"] == pytest.approx(T * T, abs=1e-12)  # normal incidence, two bare faces
    # uniform disc of radius a: sigma_x = a/2, so D4sigma = 4 sigma = 2a (Monte Carlo, 4000 rays)
    assert 2 * r["plane"]["width_2sigma_mm"][0] == pytest.approx(2 * a, rel=0.03)
    assert r["plane"]["power_w"] == pytest.approx(T * T, abs=1e-12)


def test_blocking_monitors_back_side_and_aperture_loss():
    cs = compile_system(_window(sd=1.0))
    src = LightSource(placement={"anchor": "obj"}, shape="disk", size_x=2.0, angular="collimated", rays=2000)
    mon = Detector(id="m", placement={"anchor": "img", "position": [0, 0, -2]}, size_x=5.0, mode="monitor")
    first = Detector(id="f", placement={"anchor": "img"}, size_x=5.0)
    second = Detector(id="s", placement={"anchor": "img", "position": [0, 0, 1]}, size_x=5.0)
    r = trace_direct(cs, [src], [mon, first, second])
    m, f, s = r["detectors"]
    # half the disc radius passes the 1 mm aperture: a quarter of the power, less the Fresnel loss
    assert r["lost_w"]["outside_aperture"] == pytest.approx(0.75, abs=0.03)
    assert m["power_w"] == pytest.approx(f["power_w"], abs=1e-12) and m["power_w"] > 0.2
    assert s["power_w"] == 0.0 and s["plane"]["rays"] == 0  # behind an absorbing detector
    # a one-sided absorber turned around blocks the light and records nothing
    back = Detector(id="b", placement={"anchor": "img", "rotation_deg": [180, 0, 0]}, size_x=5.0)
    rb = trace_direct(cs, [src], [back, second])
    assert rb["detectors"][0]["power_w"] == 0.0 and rb["detectors"][0]["blocked_back_w"] > 0.2
    assert rb["detectors"][1]["power_w"] == 0.0


def test_anchored_placements_follow_the_surfaces():
    sys = _window()
    cs = compile_system(sys)
    fr = surface_frames(cs)
    R, t = placement_matrix(Detector(placement={"anchor": "img", "position": [0.1, 0, 2]}).placement, fr)
    np.testing.assert_allclose(t, [0.1, 0, 5 + 10 + 2])  # surface 1 at z = 0
    R, t = placement_matrix(LightSource(placement={"anchor": "obj"}).placement, fr)
    np.testing.assert_allclose(t, [0, 0, -10])
    # tilted frame (coordinate break): the anchored rotation composes with the surface frame
    d = sys.model_dump()
    d["surfaces"].insert(2, {"id": "cb", "type": "coordinate_break", "tilt_x": 30.0, "thickness": 0.0})
    cs2 = compile_system(OpticalSystem.model_validate(d))
    R, _ = placement_matrix(Detector(placement={"anchor": "b"}).placement, surface_frames(cs2))
    np.testing.assert_allclose(R[:, 2], cs2.frames[3].matrix[:, 2], atol=1e-12)
    assert abs(R[2, 2]) == pytest.approx(math.cos(math.radians(30)), abs=1e-12)
    with pytest.raises(ValueError, match="anchor"):
        placement_matrix(Detector(placement={"anchor": "nope"}).placement, fr)
    with pytest.raises(SystemError_, match="anchor"):
        trace_direct(cs, [LightSource(placement={"anchor": "nope"})], [Detector()])


def test_source_spectrum_outside_the_system_wavelengths():
    """A source at 1.55 um in a system defined at 0.588 um refracts with the 1.55 um indices: the
    same rays as in a system that has 1.55 um."""
    src = LightSource(placement={"anchor": "obj"}, angular="cone", half_angle_deg=4, rays=500, wavelengths=[{"value": 1.55}])
    det = Detector(placement={"anchor": "img", "position": [0, 0, -3]}, size_x=8.0)
    p = get_sample("singlet").system
    a = trace_direct(compile_system(p), [src], [det])["detectors"][0]
    q = p.model_copy(update={"wavelengths": [*p.wavelengths, {"value": 1.55}]})
    q = OpticalSystem.model_validate(q.model_dump())
    b = trace_direct(compile_system(q), [src], [det])["detectors"][0]
    assert a["plane"]["width_2sigma_mm"] == pytest.approx(b["plane"]["width_2sigma_mm"], rel=1e-12)
    assert list(a["by_wavelength_w"]) == ["1.55"]


def _spot(s: float) -> float:
    """D4sigma (mean of x and y) in the detector plane of the thick-lens system at source distance s,
    from the direct trace with the merit function's seed."""
    p = thick_lens(s)
    d = trace_direct(compile_system(p.system), p.sources, p.detectors, seed=1)["detectors"][0]
    return 2 * 0.5 * sum(d["plane"]["width_2sigma_mm"])


def test_detector_operands_and_optimisation_of_the_source_distance():
    from scipy.optimize import brentq

    p = thick_lens()
    ns = (p.sources, p.detectors)
    mf = MeritFunction(p.system, p.optimization, p.custom_materials, ns=ns)
    _, bd = mf.evaluate(mf.x0)
    cs = compile_system(p.system, p.custom_materials)
    ref = trace_direct(cs, p.sources, p.detectors, seed=1)["detectors"][0]
    assert bd[0]["value"] == pytest.approx(2 * 0.5 * sum(ref["plane"]["width_2sigma_mm"]), rel=1e-12)
    assert bd[1]["value"] == pytest.approx(ref["fraction"], abs=1e-15)
    # the spot has one minimum (no sharp image fits in the length), so the target spot has two
    # source distances, found independently by root finding on the direct trace
    roots = [brentq(lambda s: _spot(s) - THICK_LENS_TARGET, a, b, xtol=1e-7) for a, b in ((1.0, 3.1), (3.1, 5.0))]
    # from the source too close and from beyond the sharpest focus, the optimiser moves the lens to
    # the nearer of the two
    for s0, want in zip((1.0, 3.4), roots):
        d = p.system.model_dump()
        d["surfaces"][0]["thickness"] = s0
        r = optimize(OpticalSystem.model_validate(d), p.optimization, p.custom_materials, ns=ns)
        so = OpticalSystem.model_validate(r["system"])
        assert so.surfaces[0].thickness == pytest.approx(want, abs=2e-3)
        assert r["operands_after"][0]["value"] == pytest.approx(THICK_LENS_TARGET, abs=1e-4)
        assert r["operands_after"][1]["value"] > 0.99
    # without sources / with an unknown detector the operand is a configuration error
    with pytest.raises(ValueError, match="light source"):
        MeritFunction(p.system, p.optimization, p.custom_materials)
    bad = p.optimization.model_copy(update={"operands": [p.optimization.operands[0].model_copy(update={"detector_id": "x"})]})
    with pytest.raises(ValueError, match="detector"):
        MeritFunction(p.system, bad, p.custom_materials, ns=ns)


def test_detector_on_a_surface_vertex_counts_every_ray_once():
    """A detector anchored to the image surface is crossed at the vertex shared by the last finite path
    segment and the semi-infinite one. Rounding must not drop such crossings (at s = 2.2138 mm that
    would lose 2 % of the power unreported): every ray crosses the plane once, and the direct path
    equals the full non-sequential trace."""
    fractions = []
    for s in np.linspace(2.15, 2.30, 31):
        p = thick_lens(float(s))
        d = trace_direct(compile_system(p.system), p.sources, p.detectors, seed=1)["detectors"][0]
        assert d["plane"]["rays"] == p.sources[0].rays
        fractions.append(d["fraction"])
    assert max(fractions) - min(fractions) < 1e-5  # inside the detector throughout: only the Fresnel losses vary
    p = thick_lens(2.2138)
    cs = compile_system(p.system)
    a = trace_direct(cs, p.sources, p.detectors, seed=1)["detectors"][0]
    b = trace_nonsequential(cs, build_scene(cs, [], True, None, (), p.detectors), sources=p.sources, split=False, seed=1, keep_paths=0)["detectors"][0]
    assert a["fraction"] == pytest.approx(b["fraction"], abs=1e-12)


def test_api_merit_with_sources_and_detectors():
    p = thick_lens()
    body = {"system": p.system.model_dump(), "custom_materials": p.custom_materials, "optimization": p.optimization.model_dump()}
    assert client.post("/api/v1/optimize/merit", json=body).status_code == 422
    body["sources"] = [s.model_dump() for s in p.sources]
    body["detectors"] = [d.model_dump() for d in p.detectors]
    r = client.post("/api/v1/optimize/merit", json=body)
    assert r.status_code == 200, r.text
    ops = r.json()["operands"]
    assert ops[0]["type"] == "detector_size" and ops[0]["value"] == pytest.approx(_spot(2.4), rel=1e-12)
    assert ops[0]["detector"].startswith("Detector")
    assert client.post("/api/v1/optimize/start", json=body).status_code == 200
