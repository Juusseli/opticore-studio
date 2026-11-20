"""Coatings in the system: metal-mirror designs, design round trip through project
coatings, angular data, surface context, coating performance analysis,
surface-reflectance operand and coating variables in the lens optimiser."""

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.analysis.coatings import coating_performance, incidence, surface_context, surface_reflectance
from opticore.analysis.ghosts import _reflectance
from opticore.api.main import app
from opticore.coatdesign import CoatingDesign, Resolver, angular, design_from_coating, recipe, spectrum, template, to_coating_definition
from opticore.model import OpticalSystem
from opticore.optimize import OptimizationSpec, optimize
from opticore.optimize.merit import MeritFunction
from opticore.paraxial import compute_pupil
from opticore.raytrace import launch, trace
from opticore.samples import get_sample
from opticore.system import compile_system

# test values for a metal (not data for a real metal)
NM, KM = 1.2, 7.0


def _metal(**kw):
    d = {"palette": [{"key": "H", "index": 2.35}, {"key": "L", "index": 1.46}], "substrate_index": NM, "substrate_extinction": KM}
    d.update(kw)
    return CoatingDesign.model_validate(d)


def test_bare_metal_substrate_and_mirror_templates():
    d = _metal()
    lam = np.array([550.0])
    sp = spectrum(d, Resolver(d), lam)
    R0 = ((NM - 1) ** 2 + KM**2) / ((NM + 1) ** 2 + KM**2)
    assert sp["R"][0] == pytest.approx(R0, rel=1e-12)
    assert sp["T"][0] == 0.0 and sp["A"][0] == pytest.approx(1 - R0, rel=1e-12)
    prot = CoatingDesign.model_validate(template(d, "protected_mirror", lambda0_nm=550.0)["design"])
    assert spectrum(prot, Resolver(prot), lam)["R"][0] == pytest.approx(R0, abs=1e-12)  # half-wave overcoat is absentee
    enh = CoatingDesign.model_validate(template(d, "enhanced_mirror", lambda0_nm=550.0, pairs=2)["design"])
    assert spectrum(enh, Resolver(enh), lam)["R"][0] > R0 + 0.02
    with pytest.raises(ValueError):
        template(CoatingDesign.model_validate({"palette": d.model_dump()["palette"]}), "enhanced_mirror")
    r = recipe(enh, monitor_wavelength_nm=550.0, monitor="T")
    assert r["monitor"] == "R" and any("Opaque" in w for w in r["warnings"])


def test_designed_mirror_coating_works_on_a_mirror_in_the_trace():
    d = CoatingDesign.model_validate(template(_metal(), "enhanced_mirror", lambda0_nm=550.0, pairs=2)["design"])
    cd = to_coating_definition(d, "enh al")
    assert cd["substrate_index"] == NM and cd["substrate_extinction"] == KM
    sysm = OpticalSystem.model_validate(
        {
            "surfaces": [
                {"id": "obj", "thickness": None},
                {"id": "stop", "thickness": 50.0, "is_stop": True},
                {"id": "m", "thickness": -50.0, "material": "MIRROR", "coating": "ENH AL"},
                {"id": "img"},
            ],
            "wavelengths": [{"value": 0.55}],
            "aperture": {"type": "epd", "value": 2.0},
            "custom_coatings": [cd],
        }
    )
    cs = compile_system(sysm)
    pupil = compute_pupil(cs)
    P0, D0, opl = launch(cs, 0, 0, np.array([0.0]), np.array([0.0]), pupil)
    r = trace(cs, 0, P0, D0, opl, fresnel=True)
    assert r.intensity[0] == pytest.approx(spectrum(d, Resolver(d), np.array([550.0]))["R"][0], rel=1e-12)


def test_design_round_trips_through_a_project_coating():
    d = CoatingDesign.model_validate(template(CoatingDesign.model_validate({"palette": [{"key": "H", "index": 2.35}, {"key": "L", "index": 1.46}]}), "longpass", edge_nm=600, pairs=6)["design"])
    cd = to_coating_definition(d, "lp")
    back = design_from_coating(cd)
    assert back.layers == d.layers and back.targets == d.targets and back.palette == d.palette
    assert back.source_coating == "LP"
    # a coating without stored design is rebuilt from its layers (deposition order)
    bare = {k: v for k, v in cd.items() if k != "design"}
    re = design_from_coating(bare)
    lam = np.linspace(450, 750, 31)
    assert np.allclose(spectrum(re, Resolver(re), lam)["R"], spectrum(d, Resolver(d), lam)["R"], atol=1e-13)
    # stored designs survive the system model and project files
    sysd = get_sample("singlet").system.model_dump()
    sysd["custom_coatings"] = [cd]
    assert OpticalSystem.model_validate(sysd).custom_coatings[0].design["layers"] == d.model_dump()["layers"]


def test_angular_curves_and_brewster_angle():
    d = CoatingDesign.model_validate({"palette": [{"key": "L", "index": 1.46}], "substrate_index": 1.5, "substrate_extinction": 0.0, "layers": []})
    a = angular(d, wavelengths_nm=[550.0], angle_max_deg=89.0, angles=891)
    c = a["curves"][0]
    ang = np.array(a["angles_deg"])
    k = int(np.argmin(c["Rp"]))
    assert ang[k] == pytest.approx(math.degrees(math.atan(1.5)), abs=0.1)  # Brewster
    assert c["Rp"][k] < 1e-6
    assert np.all(np.diff(c["Rs"]) > 0)
    sp = spectrum(d, Resolver(d), np.array([550.0]))
    assert c["R"][0] == pytest.approx(sp["R"][0], abs=1e-15)
    assert len(a["map"]["R"]) == 46 and len(a["map"]["R"][0]) == 81


def test_surface_context_angles():
    cs = compile_system(get_sample("cooke-triplet").system)
    front = surface_context(cs, 1)
    assert front["light_from"] == "incident" and front["incident"] == "AIR"
    assert front["angles_deg"]["max"] == pytest.approx(front["angles_actual_deg"]["max"], abs=1e-9)
    rear = surface_context(cs, 2)  # light leaves the glass: angles converted to the air side
    assert rear["light_from"] == "substrate"
    n_g = float(cs.n_after[cs.model.primary_wavelength, 1])
    assert math.sin(math.radians(rear["angles_deg"]["max"])) == pytest.approx(n_g * math.sin(math.radians(rear["angles_actual_deg"]["max"])), rel=1e-9)
    with pytest.raises(Exception):
        surface_context(cs, 0)


def test_coating_performance_and_surface_reflectance():
    sysd = get_sample("singlet").system.model_dump()
    sysd["custom_coatings"] = [{"name": "AR", "layers": [{"index": 1.38, "thickness_nm": 106.4}]}]
    sysd["surfaces"][1]["coating"] = "AR"
    cs = compile_system(OpticalSystem.model_validate(sysd))
    perf = coating_performance(cs, 450, 700, 26)
    rows = {r["surface"]: r for r in perf["surfaces"]}
    lam = np.array(perf["lambda_nm"])
    lib = cs.library
    n = np.array([lib.index("N-BK7", x * 1e-3) for x in lam])
    assert np.allclose(rows[2]["R"]["normal"], ((n - 1) / (n + 1)) ** 2, rtol=1e-12)  # uncoated rear surface
    assert rows[1]["coating"] == "AR" and max(rows[1]["R"]["normal"]) < min(rows[2]["R"]["normal"])
    # ray-averaged reflectance equals the ghost module's reflectance on the same rays
    wl = cs.model.primary_wavelength
    inc = incidence(cs, 1, wl, rings=4)
    ref = float((_reflectance(cs, wl, 1, True, inc["cos"]) * inc["weights"]).sum() / inc["weights"].sum())
    assert surface_reflectance(cs, 1, wl, None, 4) == pytest.approx(ref, rel=1e-12)
    # transmission estimate close to the ray-traced throughput at the primary wavelength
    from opticore.analysis.throughput import transmission

    tr = transmission(cs)
    i = int(np.argmin(np.abs(lam - cs.wavelengths[wl] * 1e3)))
    t_trace = np.mean([f["per_wavelength"][wl]["surface_losses"] for f in tr["fields"]])
    assert perf["system_transmission_estimate"][i] == pytest.approx(t_trace, abs=0.01)


def _ar_system(thick=145.0):
    sysd = get_sample("singlet").system.model_dump()
    sysd["custom_coatings"] = [{"name": "AR", "layers": [{"index": 1.38, "thickness_nm": thick}]}]
    sysd["surfaces"][1]["coating"] = "AR"
    sysd["surfaces"][2]["coating"] = "AR"
    return OpticalSystem.model_validate(sysd)


def test_coating_variables_minimise_surface_reflectance():
    sysm = _ar_system()  # quarter wave at ~800 nm: detuned at the visible wavelengths
    s1 = sysm.surfaces[1].id
    for param, lo, hi in (("coating_scale", 0.3, 2.0), ("coat_layer_1", 20.0, 300.0)):
        spec = OptimizationSpec.model_validate(
            {"variables": [{"surface_id": s1, "parameter": param, "min": lo, "max": hi}], "operands": [{"type": "surface_reflectance", "surface_id": s1, "target": 0.0}], "algorithm": "local"}
        )
        res = optimize(sysm, spec)
        # a single n = 1.38 layer on N-BK7 bottoms out near 1.3 % (quarter-wave limit)
        assert res["initial_merit"] > 0.02 and res["final_merit"] < 0.016
        out = OpticalSystem.model_validate(res["system"])
        t_new = out.custom_coatings[0].layers[0].thickness_nm
        assert 85.0 < t_new < 125.0  # near a quarter wave in the visible
        assert sysm.custom_coatings[0].layers[0].thickness_nm == 145.0  # original untouched
    # the throughput operand sees the same coating change
    spec = OptimizationSpec.model_validate({"variables": [{"surface_id": s1, "parameter": "coating_scale", "min": 0.3, "max": 2.0}], "operands": [{"type": "throughput", "target": 1.0}]})
    res = optimize(sysm, spec)
    assert res["final_merit"] < res["initial_merit"]


def test_coating_variable_validation():
    sysm = _ar_system()
    s1, s2 = sysm.surfaces[1].id, sysm.surfaces[2].id
    with pytest.raises(ValueError, match="only 1 layers"):
        MeritFunction(sysm, OptimizationSpec.model_validate({"variables": [{"surface_id": s1, "parameter": "coat_layer_2"}], "operands": [{"type": "efl", "target": 100}]}))
    with pytest.raises(ValueError, match="already a variable"):
        MeritFunction(sysm, OptimizationSpec.model_validate({"variables": [{"surface_id": s1, "parameter": "coating_scale"}, {"surface_id": s2, "parameter": "coating_scale"}], "operands": [{"type": "efl", "target": 100}]}))
    bi = get_sample("singlet").system.model_dump()
    bi["surfaces"][1]["coating"] = "MGF2_QW550"
    bi = OpticalSystem.model_validate(bi)
    with pytest.raises(ValueError, match="built-in"):
        MeritFunction(bi, OptimizationSpec.model_validate({"variables": [{"surface_id": bi.surfaces[1].id, "parameter": "coating_scale"}], "operands": [{"type": "efl", "target": 100}]}))


def test_api_endpoints():
    c = TestClient(app)
    sysd = get_sample("cooke-triplet").system.model_dump()
    r = c.post("/api/v1/analysis/surface-context", json={"system": sysd, "surface": 2})
    assert r.status_code == 200 and r.json()["light_from"] == "substrate"
    p = c.post("/api/v1/analysis/coatings", json={"system": sysd, "samples": 11}).json()
    assert len(p["system_transmission_estimate"]) == 11
    d = _metal().model_dump()
    a = c.post("/api/v1/coating-design/angular", json={"design": d, "wavelengths_nm": [500, 600], "angles": 10}).json()
    assert len(a["curves"]) == 2 and a["opaque_substrate"]
    cd = to_coating_definition(_metal(layers=[{"material": "L", "thickness_nm": 90}]), "m")
    f = c.post("/api/v1/coating-design/from-coating", json={"coating": cd}).json()
    assert f["design"]["substrate_extinction"] == KM
