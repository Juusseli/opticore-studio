import math

import numpy as np
import pytest

from opticore.physics import fresnel
from opticore.thinfilm import COATINGS, Layer, quarter_wave, stack_rt


def test_bare_interface_equals_fresnel():
    n0, ns = 1.0, 1.52
    th = np.linspace(0, math.radians(80), 9)
    ci = np.cos(th)
    ct = np.sqrt(1 - (n0 / ns * np.sin(th)) ** 2)
    o = stack_rt(n0, ns, (), 0.55, ci)
    f = fresnel(n0, ns, ci, ct)
    assert np.allclose(o["Rs"], f["Rs"], atol=1e-14)
    assert np.allclose(o["Rp"], f["Rp"], atol=1e-14)
    assert np.allclose(o["Ts"], f["Ts"], atol=1e-14)


def test_quarter_wave_antireflection_formula():
    n0, n1, ns, lam = 1.0, 1.38, 1.52, 0.55
    o = stack_rt(n0, ns, (quarter_wave(n1, lam),), lam, np.array([1.0]))
    expected = ((n0 * ns - n1**2) / (n0 * ns + n1**2)) ** 2
    assert o["Rs"][0] == pytest.approx(expected, rel=1e-12)
    assert o["Rs"][0] < 0.013  # ~1.26 % vs 4.26 % uncoated


def test_ideal_quarter_wave_index_gives_zero_reflection():
    ns = 1.52
    o = stack_rt(1.0, ns, (quarter_wave(math.sqrt(ns), 0.6),), 0.6, np.array([1.0]))
    assert o["Rs"][0] < 1e-28


def test_half_wave_layer_is_absentee():
    lam = 0.5
    bare = stack_rt(1.0, 1.6, (), lam, np.array([1.0]))
    hw = stack_rt(1.0, 1.6, (Layer(2.0, lam * 1000 / (2 * 2.0)),), lam, np.array([1.0]))
    assert hw["Rs"][0] == pytest.approx(bare["Rs"][0], rel=1e-12)


@pytest.mark.parametrize("name", list(COATINGS))
def test_energy_conservation_lossless_stacks(name):
    """The built-ins' dispersive layers at each wavelength: R + T = 1 for the lossless stack of their real indices, and
    R + T <= 1 (A = 1 - R - T >= 0) with the films' and metals' k."""
    from opticore.thinfilm import Layer

    th = np.linspace(0, math.radians(70), 8)
    for lam in (0.45, 0.55, 0.7):
        L = COATINGS[name].layers_at(lam)
        lossless = tuple(Layer(x.index, x.thickness_nm) for x in L)
        o = stack_rt(1.0, 1.6, lossless, lam, np.cos(th))
        assert np.allclose(o["Rs"] + o["Ts"], 1.0, atol=1e-12)
        assert np.allclose(o["Rp"] + o["Tp"], 1.0, atol=1e-12)
        o = stack_rt(1.0, 1.6, L, lam, np.cos(th))
        assert np.all(o["Rs"] + o["Ts"] <= 1.0 + 1e-12) and np.all(o["Rp"] + o["Tp"] <= 1.0 + 1e-12)


def test_vcoat_minimum_at_design_wavelength():
    # on its design substrate (N-BK7) the two-layer V-coat of dispersive films reflects nothing at 550 nm (a minimum,
    # not a quarter-wave pair)
    from opticore.materials import MaterialLibrary

    bk7 = MaterialLibrary().get("N-BK7")
    co = COATINGS["VCOAT_550"]
    lams = np.linspace(0.45, 0.70, 101)
    R = [stack_rt(1.0, bk7.index(l), co.layers_at(l), l, np.array([1.0]))["Rs"][0] for l in lams]
    assert abs(lams[int(np.argmin(R))] - 0.55) < 0.003 and stack_rt(1.0, bk7.index(0.55), co.layers_at(0.55), 0.55, np.array([1.0]))["Rs"][0] < 1e-18


# ---- integration with the sequential trace -----------------------------

from fastapi.testclient import TestClient  # noqa: E402

from opticore.analysis.throughput import transmission  # noqa: E402
from opticore.api.main import app  # noqa: E402
from opticore.raytrace import trace  # noqa: E402
from opticore.samples import get_sample  # noqa: E402
from opticore.system import SystemError_, compile_system  # noqa: E402


def _singlet(coating=""):
    sysm = get_sample("singlet").system.model_copy(deep=True)
    for s in sysm.surfaces[1:-1]:
        if s.type != "coordinate_break":
            s.coating = coating
    return sysm


def test_coated_surface_matches_stack_at_normal_incidence():
    sysm = _singlet("MGF2_QW550")
    cs = compile_system(sysm)
    coated = [j for j, c in enumerate(cs.coatings) if c is not None]
    assert coated, "sample should have coated refracting surfaces"
    w = 0
    lam = float(cs.wavelengths[w])
    P = np.array([[0.0, 0.0, cs.frames[1].origin[2] - 1.0]])
    D = np.array([[0.0, 0.0, 1.0]])
    r = trace(cs, w, P, D, clip=False, fresnel=True)
    expected = 1.0
    for j in coated:
        n1, n2 = cs.n_after[w, j - 1], cs.n_after[w, j]
        layers = cs.coatings[j].layers_at(lam) if n1 <= n2 else cs.coatings[j].layers_at(lam)[::-1]
        o = stack_rt(n1, n2, layers, lam, np.array([1.0]))
        expected *= 0.5 * (o["Ts"][0] + o["Tp"][0])
    expected *= np.exp(-sum(cs.absorption[j] * abs(sysm.surfaces[j].thickness or 0) for j in range(1, cs.n_surfaces - 1)))
    assert r.intensity[0] == pytest.approx(expected, rel=1e-10)


def test_coating_is_symmetric_for_front_and_rear_faces():
    # reciprocity: T is identical in both directions for the correctly oriented stack
    L = COATINGS["VCOAT_550"].layers_at(0.55)
    a = stack_rt(1.0, 1.6, L, 0.55, np.array([1.0]))
    b = stack_rt(1.6, 1.0, L[::-1], 0.55, np.array([1.0]))
    assert a["Ts"][0] == pytest.approx(b["Ts"][0], rel=1e-12)


def test_ar_coating_raises_throughput():
    t0 = transmission(compile_system(_singlet("")))["weighted_mean_total"]
    t1 = transmission(compile_system(_singlet("MGF2_QW550")))["weighted_mean_total"]
    assert t1 > t0 + 0.03  # two surfaces, ~4 % -> ~1.3-2 % loss each


def test_unknown_coating_is_a_structured_error():
    with pytest.raises(SystemError_) as ei:
        compile_system(_singlet("NOPE"))
    assert ei.value.diagnostics[0].code == "UNKNOWN_COATING"


def test_coating_on_mirror_is_ignored_with_diagnostic():
    sysm = get_sample("spherical-mirror").system.model_copy(deep=True)
    j = next(i for i, s in enumerate(sysm.surfaces) if s.is_mirror)
    sysm.surfaces[j].coating = "MGF2_QW550"
    cs = compile_system(sysm)
    assert cs.coatings[j] is None
    assert any(d.code == "COATING_IGNORED" and d.surface == j for d in cs.diagnostics)


def test_coating_api():
    c = TestClient(app)
    lst = c.get("/api/v1/coatings").json()["coatings"]
    assert {x["name"] for x in lst} >= {"MGF2_QW550", "VCOAT_550"}
    r = c.post("/api/v1/coatings/curve", json={"name": "MGF2_QW550", "substrate_index": 1.52}).json()
    i = int(np.argmin(np.abs(np.array(r["wavelength_um"]) - 0.55)))
    n = COATINGS["MGF2_QW550"].layers_at(0.55)[0].index  # the MgF2 film's index at 550 nm
    assert r["reflectance"][i] == pytest.approx(((1.52 - n**2) / (1.52 + n**2)) ** 2, rel=1e-6)
    assert c.post("/api/v1/coatings/curve", json={"name": "NOPE"}).status_code == 400
