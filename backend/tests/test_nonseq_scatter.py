"""Surface scattering and thin-film coatings in the non-sequential trace."""

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.geometry import Frame
from opticore.model import OpticalSystem
from opticore.nonseq import NsObject, assemble_scene, build_scene, sample_gaussian, sample_lambertian, trace_nonsequential
from opticore.paraxial import compute_pupil
from opticore.raytrace import launch, trace
from opticore.samples import get_sample
from opticore.system import SystemError_, compile_system
from opticore.thinfilm import stack_rt

from .test_nonseq import _box, _empty, _grid, _step_asset


# ---- sampling distributions --------------------------------------------------

def test_lambertian_sampling_is_cosine_weighted():
    rng = np.random.default_rng(7)
    n = np.array([0.3, -0.2, 0.9])
    n /= np.linalg.norm(n)
    d = np.array([sample_lambertian(n, rng) for _ in range(40000)])
    assert np.allclose(np.linalg.norm(d, axis=1), 1.0, atol=1e-12)
    c = d @ n
    assert np.all(c > 0)
    se = 1 / math.sqrt(len(c))
    assert c.mean() == pytest.approx(2 / 3, abs=4 * 0.236 * se)  # E[cos] = 2/3, sd(cos) = sqrt(1/18)
    for t in (20.0, 45.0, 70.0):  # P(theta < t) = sin^2 t
        p = math.sin(math.radians(t)) ** 2
        assert np.mean(c > math.cos(math.radians(t))) == pytest.approx(p, abs=4 * math.sqrt(p * (1 - p)) * se)
    assert abs((d - np.outer(c, n)).mean(axis=0)).max() < 0.02  # isotropic in azimuth


def test_gaussian_sampling_width_and_truncation():
    rng = np.random.default_rng(3)
    n = np.array([0.0, 0.0, 1.0])
    sig = math.radians(1.5)
    th = np.array([math.acos(min(1.0, float(sample_gaussian(n, n, sig, rng) @ n))) for _ in range(20000)])
    # Rayleigh polar angle: E[theta^2] = 2 sigma^2, E[theta] = sigma sqrt(pi/2)
    assert math.sqrt((th**2).mean()) == pytest.approx(math.sqrt(2) * sig, rel=0.02)
    assert th.mean() == pytest.approx(sig * math.sqrt(math.pi / 2), rel=0.02)
    spec = np.array([math.sin(math.radians(88.0)), 0.0, math.cos(math.radians(88.0))])  # near-grazing specular
    d = np.array([sample_gaussian(spec, n, math.radians(10), rng) for _ in range(4000)])
    assert np.all(d @ n > 0)  # never scattered into the surface


# ---- analytic view factor -------------------------------------------------------

def _annulus(b: float, a: float):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt
    from OCP.TopoDS import TopoDS

    def wire(r):
        return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), r)).Edge()).Wire()

    mf = BRepBuilderAPI_MakeFace(wire(a), True)
    mf.Add(TopoDS.Wire(wire(b).Reversed()))
    return mf.Face()


def test_lambertian_scatterer_to_coaxial_annulus_matches_the_view_factor():
    """A narrow beam passes through the hole of an annular detector and hits a
    fully diffusing (rho = 1, Lambertian) plate a distance h behind it. The
    detected fraction equals the view factor from a differential area to a
    coaxial parallel annulus: F = a^2/(a^2 + h^2) - b^2/(b^2 + h^2)."""
    from opticore.io.cad import _frame_trsf, _place

    h, b, a = 20.0, 2.0, 20.0
    cs = compile_system(_empty(length=200.0, epd=0.2))
    plate = NsObject("plate", _box(-30, -30, 100, 60, 60, 2), "absorber", scatter={"model": "lambertian", "fraction": 1.0, "sigma": 0.0})
    det_frame = Frame(np.array([0.0, 0.0, 100.0 - h]), np.eye(3))
    det = NsObject("Detector", _place(_annulus(b, a), _frame_trsf(det_frame)), "detector")
    scene = assemble_scene([plate, det], det_frame, a)
    r = trace_nonsequential(cs, scene, rays=12000, overfill=1.0, split=False, seed=11)
    e = r["energy"]
    N = r["source"]["rays"]
    F = a * a / (a * a + h * h) - b * b / (b * b + h * h)
    assert e["detected_direct"] == 0.0 and e["detected_after_scatter"] == pytest.approx(e["detected"], rel=1e-12)
    assert e["detected"] == pytest.approx(F, abs=4 * math.sqrt(F * (1 - F) / N))
    assert e["scattered"] == pytest.approx(1.0, rel=1e-12)
    assert e["absorbed"]["plate"] == pytest.approx(0.0, abs=1e-12)
    assert e["total"] == pytest.approx(1.0, abs=1e-12)
    # reproducible with the same seed, different with another
    r2 = trace_nonsequential(cs, scene, rays=12000, overfill=1.0, split=False, seed=11)
    assert r2["energy"]["detected"] == e["detected"]
    r3 = trace_nonsequential(cs, scene, rays=12000, overfill=1.0, split=False, seed=12)
    assert r3["energy"]["detected"] != e["detected"]


def test_partially_diffuse_absorber_books_the_rest_as_absorbed():
    cs = compile_system(_empty())
    baffle = _step_asset(_box(-20, -20, 40, 40, 40, 3), "baffle", "absorber")
    baffle["optical"]["scatter"] = {"model": "lambertian", "fraction": 0.04}
    r = trace_nonsequential(cs, build_scene(cs, [baffle], False), rays=200, overfill=1.0, split=False)
    e = r["energy"]
    assert e["absorbed"]["baffle"] == pytest.approx(0.96, rel=1e-12)
    assert e["scattered"] == pytest.approx(0.04, rel=1e-12)
    assert e["detected"] == 0.0  # scattered back towards the source
    assert e["total"] == pytest.approx(1.0, abs=1e-12)


def test_forward_scattering_window_splits_direct_and_scattered_power():
    f = 0.2
    cs = compile_system(_empty())
    win = _step_asset(_box(-15, -15, 20, 30, 30, 4), "window", "refractive", "N-BK7")
    win["optical"]["scatter"] = {"model": "gaussian", "fraction": f, "sigma_deg": 1.0}
    r = trace_nonsequential(cs, build_scene(cs, [win], False), rays=300, overfill=0.8, split=False)
    n = cs.library.index("N-BK7", 0.5875618)
    T = 1 - ((n - 1) / (n + 1)) ** 2
    e = r["energy"]
    assert e["detected_direct"] == pytest.approx(T * T * (1 - f) ** 2, rel=1e-12)  # unscattered through both faces
    # small-angle scatter still reaches the detector; Fresnel at the exit face changes by < 1e-4
    assert e["detected_after_scatter"] == pytest.approx(T * T * (1 - (1 - f) ** 2), rel=2e-4)
    assert e["detected_after_reflections"] == 0.0
    assert e["total"] == pytest.approx(1.0, abs=1e-12)
    assert r["detector"]["scatter_hits"] > 0


def test_scattering_mirror_keeps_the_specular_part():
    cs = compile_system(_empty())
    m = _step_asset(_box(-15, -15, 0, 30, 30, 1), "fold", "mirror", transform={"translate": [0, 0, 50], "rotate_deg": [45, 0, 0]})
    m["optical"]["scatter"] = {"model": "gaussian", "fraction": 0.1, "sigma_deg": 0.5}
    r = trace_nonsequential(cs, build_scene(cs, [m], False), rays=100, overfill=1.0, split=False, keep_paths=100)
    e = r["energy"]
    assert e["scattered"] == pytest.approx(0.1, rel=1e-12)
    assert e["escaped"] == pytest.approx(1.0, rel=1e-12)
    spec = [p for p in r["paths"] if p["scatters"] == 0 and p["end"] == "escaped"]
    a, b = np.array(spec[0]["points"][-2]), np.array(spec[0]["points"][-1])
    d = (b - a) / np.linalg.norm(b - a)
    assert abs(abs(d[1]) - 1) < 1e-9  # specular part folded by exactly 90 degrees


# ---- coatings ----------------------------------------------------------------------

def _seq_reference(cs, n_rays=300):
    px, py = _grid(n_rays)
    pupil = compute_pupil(cs)
    w = cs.model.primary_wavelength
    P0, D0, opl = launch(cs, w, 0, px, py, pupil)
    s = trace(cs, w, P0, D0, opl, fresnel=True)
    return (s.intensity * s.ok).sum() / len(px)


def test_coated_lens_system_matches_the_coated_sequential_trace():
    d = get_sample("singlet").system.model_dump()
    d["custom_coatings"] = [{"name": "abs ar", "layers": [{"index": 1.38, "extinction": 0.002, "thickness_nm": 106.0}]}]
    for s in d["surfaces"][1:-1]:
        s["coating"] = "ABS AR"
    cs = compile_system(OpticalSystem.model_validate(d))
    sc = build_scene(cs, [], True)
    assert any(o.surface_coatings for o in sc.objects)
    r = trace_nonsequential(cs, sc, rays=300, overfill=1.0, split=False)
    e = r["energy"]
    assert e["detected_direct"] == pytest.approx(_seq_reference(cs), rel=1e-9)
    assert e["coating_absorption"] > 1e-4
    assert e["total"] == pytest.approx(1.0, abs=1e-12)
    bare = trace_nonsequential(compile_system(get_sample("singlet").system), build_scene(compile_system(get_sample("singlet").system), [], True), rays=300, overfill=1.0, split=False)
    assert e["detected_direct"] > bare["energy"]["detected_direct"] + 0.02


def test_coated_fold_mirror_matches_the_sequential_trace():
    p = get_sample("fold-mirror")
    d = p.system.model_dump()
    jm = next(i for i, s in enumerate(p.system.surfaces) if s.is_mirror)
    d["surfaces"][jm]["coating"] = "METAL"
    d["custom_coatings"] = [{"name": "metal", "layers": [{"index": 1.45, "thickness_nm": 95.0}], "substrate_index": 1.2, "substrate_extinction": 7.0}]
    cs = compile_system(OpticalSystem.model_validate(d))
    sc = build_scene(cs, [], True)
    assert any(o.role == "mirror" and o.surface_coatings for o in sc.objects)
    r = trace_nonsequential(cs, sc, rays=300, overfill=1.0, split=False)
    e = r["energy"]
    ref = _seq_reference(cs)
    assert ref < 0.9
    assert e["detected_direct"] == pytest.approx(ref, rel=1e-9)
    assert e["coating_absorption"] > 0.05
    assert e["total"] == pytest.approx(1.0, abs=1e-12)


def test_coated_cad_window_and_mirror():
    sysd = _empty().model_dump()
    sysd["custom_coatings"] = [{"name": "ar", "layers": [{"index": 1.23, "thickness_nm": 119.4}]}, {"name": "dielectric only", "layers": [{"index": 2.0, "thickness_nm": 70}]}]
    cs = compile_system(OpticalSystem.model_validate(sysd))
    win = _step_asset(_box(-15, -15, 20, 30, 30, 4), "window", "refractive", "N-BK7")
    win["optical"]["coating"] = "AR"
    r = trace_nonsequential(cs, build_scene(cs, [win], False), rays=60, overfill=0.8, split=False)
    n = cs.library.index("N-BK7", 0.5875618)
    o = stack_rt(1.0, n, cs.coating_library["AR"].layers, 0.5875618, np.array([1.0]))
    T = 0.5 * (o["Ts"][0] + o["Tp"][0])
    assert r["energy"]["detected_direct"] == pytest.approx(T * T, rel=1e-12)  # reciprocity: same T leaving the glass
    m = _step_asset(_box(-15, -15, 0, 30, 30, 1), "fold", "mirror", transform={"translate": [0, 0, 50], "rotate_deg": [45, 0, 0]})
    m["optical"]["coating"] = "dielectric only"
    sc = build_scene(cs, [m], False)
    assert any("no mirror substrate" in x for x in sc.notes)
    bad = dict(win, optical={"role": "refractive", "material": "N-BK7", "coating": "NOPE"})
    with pytest.raises(SystemError_):
        build_scene(cs, [bad], False)
    bad = dict(win, optical={"role": "absorber", "scatter": {"model": "lambertian", "fraction": 1.5}})
    with pytest.raises(SystemError_):
        build_scene(cs, [bad], False)


def test_nonseq_api_seed_and_scatter_fields():
    from .test_nonseq import _step_asset as mk

    c = TestClient(app)
    sysd = _empty().model_dump()
    baffle = mk(_box(-20, -20, 40, 40, 40, 3), "b", "absorber")
    baffle["optical"]["scatter"] = {"model": "lambertian", "fraction": 0.5}
    body = {"system": sysd, "cad_assets": [baffle], "include_system": False, "rays": 50, "seed": 5}
    a = c.post("/api/v1/analysis/nonseq", json=body).json()
    b = c.post("/api/v1/analysis/nonseq", json=body).json()
    assert a["energy"] == b["energy"] and a["settings"]["seed"] == 5
    assert a["objects"][0]["scatter"]["model"] == "lambertian"
    from opticore.project import CadOptical

    with pytest.raises(ValueError):
        CadOptical.model_validate({"role": "absorber", "scatter": {"model": "lambertian", "fraction": 2}})
