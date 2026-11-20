"""User-defined thin-film coatings: absorbing and dispersive layers, metal mirror
substrates, and their use in the sequential trace and polarisation analysis."""

import cmath
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.analysis.throughput import transmission
from opticore.api.main import app
from opticore.materials import MaterialLibrary
from opticore.model import OpticalSystem
from opticore.paraxial import compute_pupil
from opticore.polarization import jones_pupil, jones_properties
from opticore.project import dump_project, load_project
from opticore.raytrace import launch, trace
from opticore.samples import get_sample
from opticore.system import SystemError_, compile_system
from opticore.thinfilm import Coating, Layer, coating_curve, coating_from_definition, stack_amplitudes, stack_rt

from .conftest import make_system

# Test values only: N = n - ik with a large k behaves like a metal; these are
# not data for any real metal.
METAL = complex(1.2, -7.0)


def _fresnel_complex(n0, N, cos0):
    """Independent textbook Fresnel amplitudes for an absorbing medium."""
    s0 = math.sqrt(1 - cos0**2)
    ct = cmath.sqrt(1 - (n0 * s0 / N) ** 2)
    rs = (n0 * cos0 - N * ct) / (n0 * cos0 + N * ct)
    rp = (N * cos0 - n0 * ct) / (N * cos0 + n0 * ct)
    return rs, rp


def test_bare_absorbing_interface_matches_fresnel():
    n, k = 1.2, 7.0
    o = stack_rt(1.0, complex(n, -k), (), 0.55, np.array([1.0]))
    assert o["Rs"][0] == pytest.approx(((n - 1) ** 2 + k**2) / ((n + 1) ** 2 + k**2), rel=1e-13)
    for th in (20.0, 45.0, 70.0, 85.0):
        c0 = math.cos(math.radians(th))
        o = stack_rt(1.0, METAL, (), 0.55, np.array([c0]))
        rs, rp = _fresnel_complex(1.0, METAL, c0)
        assert o["Rs"][0] == pytest.approx(abs(rs) ** 2, rel=1e-12)
        assert o["Rp"][0] == pytest.approx(abs(rp) ** 2, rel=1e-12)
        assert o["Rp"][0] < o["Rs"][0]  # p dips towards the pseudo-Brewster angle


def test_absorbing_film_matches_airy_summation_and_conserves_energy():
    n0, ns, lam = 1.0, 1.52, 0.6
    N, d = complex(2.0, -0.4), 45.0
    o = stack_rt(n0, ns, (Layer(2.0, d, 0.4),), lam, np.array([1.0]))
    r01, r12 = (n0 - N) / (n0 + N), (N - ns) / (N + ns)
    t01, t12 = 2 * n0 / (n0 + N), 2 * N / (N + ns)
    ph = cmath.exp(-2j * math.pi * N * d / (lam * 1000))  # decays for N = n - ik
    r = (r01 + r12 * ph * ph) / (1 + r01 * r12 * ph * ph)
    t = t01 * t12 * ph / (1 + r01 * r12 * ph * ph)
    assert o["Rs"][0] == pytest.approx(abs(r) ** 2, rel=1e-12)
    assert o["Ts"][0] == pytest.approx(ns / n0 * abs(t) ** 2, rel=1e-12)
    assert o["As"][0] > 0.1
    assert o["Rs"][0] + o["Ts"][0] + o["As"][0] == pytest.approx(1.0, abs=1e-14)
    th = np.cos(np.radians(np.linspace(0, 80, 9)))
    o = stack_rt(n0, ns, (Layer(2.0, d, 0.4),), lam, th)
    assert np.all(o["As"] > 0) and np.all(o["Ap"] > 0)
    assert np.allclose(o["Rp"] + o["Tp"] + o["Ap"], 1.0, atol=1e-14)


@pytest.mark.parametrize("pairs", [1, 3, 6])
def test_quarter_wave_high_reflector_formula(pairs):
    nH, nL, ns, lam = 2.35, 1.38, 1.52, 0.633
    H, L = Layer(nH, lam * 1000 / (4 * nH)), Layer(nL, lam * 1000 / (4 * nL))
    layers = (H, L) * pairs + (H,)  # (HL)^N H, H next to air
    Y = (nH / nL) ** (2 * pairs) * nH**2 / ns
    o = stack_rt(1.0, ns, layers, lam, np.array([1.0]))
    assert o["Rs"][0] == pytest.approx(((1 - Y) / (1 + Y)) ** 2, rel=1e-12)
    assert o["Ts"][0] + o["Rs"][0] == pytest.approx(1.0, abs=1e-13)


def test_dispersive_layer_uses_the_material_index():
    lib = MaterialLibrary()
    c = coating_from_definition({"name": "sio2 qw", "layers": [{"material": "fused_silica", "thickness_nm": 94.0}]}, lib)
    assert c.name == "SIO2 QW"
    for lam in (0.45, 0.55, 0.7):
        (L,) = c.layers_at(lam)
        assert L.index == pytest.approx(lib.index("FUSED_SILICA", lam), rel=1e-15)
    # quarter wave at the wavelength where n d = lambda / 4
    n55 = lib.index("FUSED_SILICA", 0.55)
    c = coating_from_definition({"name": "q", "layers": [{"material": "FUSED_SILICA", "thickness_nm": 550 / (4 * n55)}]}, lib)
    o = stack_rt(1.0, 1.7, c.layers_at(0.55), 0.55, np.array([1.0]))
    assert o["Rs"][0] == pytest.approx(((1.7 - n55**2) / (1.7 + n55**2)) ** 2, rel=1e-12)
    with pytest.raises(ValueError):
        coating_from_definition({"name": "x", "layers": [{"material": "UNOBTAINIUM", "thickness_nm": 10}]}, lib)


def test_coated_mirror_amplitudes_tend_to_the_ideal_mirror():
    a = stack_amplitudes(1.0, complex(1.0, -1e7), (), 0.55, np.array([1.0, 0.7]))
    assert np.allclose(a["rs"], -1.0, atol=1e-6)
    assert np.allclose(-a["rp"], 1.0, atol=1e-6)  # the PRT uses a_p = -r_p (p basis flips on reflection)
    a = stack_amplitudes(1.0, METAL, (Layer(1.45, 80.0),), 0.55, np.array([1.0]))
    assert a["rs"][0] == pytest.approx(a["rp"][0], abs=1e-14)  # no s/p distinction at normal incidence


# ---- trace integration -----------------------------------------------------

def _mirror_system(coating="METAL", substrate=(1.2, 7.0), layers=()):
    return make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "stop", "thickness": 20.0, "is_stop": True},
            {"id": "m", "radius": -200.0, "thickness": -100.0, "material": "MIRROR", "coating": coating},
            {"id": "img"},
        ],
        aperture={"type": "epd", "value": 10.0},
        custom_coatings=[{"name": "metal", "layers": list(layers), "substrate_index": substrate[0] if substrate else None, "substrate_extinction": substrate[1] if substrate else 0.0}],
    )


def test_coated_mirror_reflectance_in_the_trace():
    cs = compile_system(_mirror_system(layers=[{"index": 1.45, "thickness_nm": 95.0}]))
    assert cs.coatings[2] is not None
    assert any(d.code == "MIRROR_COATING" for d in cs.diagnostics)
    pupil = compute_pupil(cs)
    rho = np.linspace(0, 1, 6)
    P0, D0, opl = launch(cs, 0, 0, 0 * rho, rho, pupil)
    r = trace(cs, 0, P0, D0, opl, fresnel=True, record=True)
    lam = float(cs.wavelengths[0])
    N = r.normals[:, 2, :]
    d_in = r.dirs_after[:, 1, :]
    cos_i = np.abs(np.einsum("ij,ij->i", d_in, N))
    o = stack_rt(1.0, METAL, (Layer(1.45, 95.0),), lam, cos_i)
    assert np.allclose(r.intensity, 0.5 * (o["Rs"] + o["Rp"]), rtol=1e-12)
    assert np.all(r.intensity < 0.95)
    # the geometry is unchanged by the coating
    r0 = trace(compile_system(_mirror_system(coating="")), 0, P0, D0, opl, fresnel=True)
    assert np.allclose(r0.intensity, 1.0)
    assert np.allclose(r.image_xy(), r0.image_xy(), atol=1e-15)
    t = transmission(cs)
    assert t["weighted_mean_total"] < 0.95


def test_coating_without_substrate_is_ignored_on_mirrors():
    cs = compile_system(_mirror_system(substrate=None, layers=[{"index": 1.45, "thickness_nm": 95.0}]))
    assert cs.coatings[2] is None
    assert any(d.code == "COATING_IGNORED" and d.level == "warning" for d in cs.diagnostics)


def test_fold_mirror_coating_diattenuation_matches_fresnel():
    p = get_sample("fold-mirror")
    sysd = p.system.model_dump()
    j = next(i for i, s in enumerate(p.system.surfaces) if s.is_mirror)
    sysd["surfaces"][j]["coating"] = "BARE METAL"
    sysd["custom_coatings"] = [{"name": "bare metal", "layers": [], "substrate_index": 1.2, "substrate_extinction": 7.0}]
    cs = compile_system(OpticalSystem.model_validate(sysd))
    wl = cs.model.primary_wavelength
    pupil = compute_pupil(cs, wl)
    P0, D0, _ = launch(cs, wl, 0, np.array([0.0]), np.array([0.0]), pupil)
    jp = jones_pupil(cs, wl, P0, D0)
    assert jp["reflections"] == 1
    props = jones_properties(jp["J"], jp["reflections"])
    rs, rp = _fresnel_complex(1.0, METAL, math.cos(math.radians(45.0)))
    D = (abs(rs) ** 2 - abs(rp) ** 2) / (abs(rs) ** 2 + abs(rp) ** 2)
    assert props["diattenuation"][0] == pytest.approx(D, rel=1e-9)
    # retardance in the mirror-image output basis: zero for the ideal mirror (r_p = -r_s in Born & Wolf
    # signs), so the metal's retardance is its s-p phase relative to that, arg(r_p / -r_s)
    ret = abs(cmath.phase(rp / -rs))
    assert props["retardance"][0] == pytest.approx(ret, abs=1e-9)
    assert 0.05 < props["retardance"][0] < 1.0


def test_custom_refracting_coating_matches_builtin_equivalent():
    base = get_sample("singlet").system.model_dump()
    for s in base["surfaces"][1:-1]:
        s["coating"] = "MGF2_QW550"
    builtin = transmission(compile_system(OpticalSystem.model_validate(base)))["weighted_mean_total"]
    for s in base["surfaces"][1:-1]:
        s["coating"] = "my ar"
    from opticore.thinfilm import COATINGS

    L = COATINGS["MGF2_QW550"].layers[0]  # the same film material and thickness as the built-in
    base["custom_coatings"] = [{"name": "My AR", "layers": [{"material": L.material, "index": L.index, "thickness_nm": L.thickness_nm}]}]
    custom = transmission(compile_system(OpticalSystem.model_validate(base)))["weighted_mean_total"]
    assert custom == pytest.approx(builtin, rel=1e-14)


def test_coating_definition_errors():
    base = get_sample("singlet").system.model_dump()
    base["custom_coatings"] = [{"name": "MGF2_QW550", "layers": []}]
    with pytest.raises(SystemError_) as ei:
        compile_system(OpticalSystem.model_validate(base))
    assert ei.value.diagnostics[0].code == "COATING_NAME"
    base["custom_coatings"] = [{"name": "a", "layers": [{"material": "NOPE", "thickness_nm": 1}]}]
    with pytest.raises(SystemError_) as ei:
        compile_system(OpticalSystem.model_validate(base))
    assert ei.value.diagnostics[0].code == "COATING_MATERIAL"
    base["custom_coatings"] = [{"name": "a", "layers": []}, {"name": " A ", "layers": []}]
    with pytest.raises(ValueError, match="unique"):
        OpticalSystem.model_validate(base)
    base["custom_coatings"] = [{"name": "a", "layers": [{"index": 1.4, "thickness_nm": -1}]}]
    with pytest.raises(ValueError):
        OpticalSystem.model_validate(base)


def test_material_layer_out_of_range_warns():
    base = get_sample("singlet").system.model_dump()
    base["wavelengths"] = [{"value": 0.55}, {"value": 2.6}]
    base["surfaces"][1]["coating"] = "c"
    base["custom_coatings"] = [{"name": "c", "layers": [{"material": "N-BK7", "thickness_nm": 90}]}]
    cs = compile_system(OpticalSystem.model_validate(base))
    assert any(d.code == "COATING_RANGE" for d in cs.diagnostics)


def test_custom_coatings_survive_a_project_round_trip():
    p = get_sample("singlet")
    p.system.custom_coatings = OpticalSystem.model_validate({**p.system.model_dump(), "custom_coatings": [{"name": "c", "layers": [{"index": 2.1, "extinction": 0.01, "thickness_nm": 60}], "substrate_index": 0.9, "substrate_extinction": 6.5}]}).custom_coatings
    q, notes = load_project(dump_project(p))
    assert q.system.custom_coatings == p.system.custom_coatings
    assert not [n for n in notes if "Checksum" in n]


def test_coating_curve_api_for_custom_and_mirror_coatings():
    c = TestClient(app)
    d = {"name": "hr", "layers": [{"index": 2.35, "thickness_nm": 633 / 9.4}, {"index": 1.38, "thickness_nm": 633 / 5.52}] * 3 + [{"index": 2.35, "thickness_nm": 633 / 9.4}]}
    r = c.post("/api/v1/coatings/curve", json={"definition": d, "substrate_index": 1.52, "lambda_min": 0.5, "lambda_max": 0.8, "samples": 31}).json()
    i = int(np.argmin(np.abs(np.array(r["wavelength_um"]) - 0.633)))
    Y = (2.35 / 1.38) ** 6 * 2.35**2 / 1.52
    assert r["reflectance"][i] == pytest.approx(((1 - Y) / (1 + Y)) ** 2, rel=1e-3)  # sampled near 633 nm
    assert np.allclose(np.array(r["reflectance"]) + r["transmittance"] + np.array(r["absorptance"]), 1.0, atol=1e-12)
    m = {"name": "m", "layers": [], "substrate_index": 1.2, "substrate_extinction": 7.0}
    r = c.post("/api/v1/coatings/curve", json={"definition": m, "mirror": True, "samples": 3}).json()
    assert r["reflectance"][0] == pytest.approx((0.2**2 + 49) / (2.2**2 + 49), rel=1e-12)
    assert r["substrate_extinction"] == pytest.approx(7.0)
    # rear-surface mirror inside glass: incident medium n0 = 1.5
    r = c.post("/api/v1/coatings/curve", json={"definition": m, "mirror": True, "samples": 3, "incident_index": 1.5}).json()
    assert r["reflectance"][0] == pytest.approx((0.3**2 + 49) / (2.7**2 + 49), rel=1e-12)
    assert r["incident_index"] == 1.5
    assert c.post("/api/v1/coatings/curve", json={"definition": {"name": "m", "layers": []}, "mirror": True}).status_code == 400
    assert c.post("/api/v1/coatings/curve", json={"definition": {"name": "VCOAT_550", "layers": []}}).status_code == 400
    lst = c.get("/api/v1/coatings").json()["coatings"]
    assert all("extinction" in L for x in lst for L in x["layers"])


def test_coating_curve_function_accepts_coating_objects():
    c = Coating("X", (Layer(1.38, 99.6),), builtin=False)
    out = coating_curve(c, 1.52, 0.5, 0.6, 3)
    assert out["coating"] == "X" and len(out["reflectance"]) == 3
