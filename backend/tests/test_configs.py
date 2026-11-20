import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.configs import apply_configuration, with_active
from opticore.model import OpticalSystem
from opticore.optimize.engine import optimize
from opticore.optimize.merit import MeritFunction, Operand, OptimizationSpec, Variable, apply_values, get_variable_value
from opticore.paraxial import paraxial_data
from opticore.project import dump_project, load_project
from opticore.samples import TWO_CONJ_BFD, get_sample
from opticore.system import SystemError_, compile_system
from opticore.tolerance import Evaluator, ToleranceSpec, Tolerance


def _two():
    return get_sample("achromat-two-conjugates").system


def _edit(system: OpticalSystem, fn) -> OpticalSystem:
    d = system.model_dump()
    fn(d)
    return OpticalSystem.model_validate(d)


def test_active_configuration_is_applied_on_compile():
    s = _two()
    c0 = compile_system(with_active(s, 0))
    c1 = compile_system(with_active(s, 1))
    assert c0.model.surfaces[0].thickness is None and c0.model.surfaces[3].thickness == TWO_CONJ_BFD["inf"]
    assert c1.model.surfaces[0].thickness == 500.0 and c1.model.surfaces[3].thickness == TWO_CONJ_BFD["500"]
    assert paraxial_data(c0).paraxial_magnification is None
    assert paraxial_data(c1).paraxial_magnification == pytest.approx(-0.2499, abs=1e-3)
    # the base prescription is not modified, and applying twice changes nothing
    assert s.surfaces[0].thickness is None
    a = apply_configuration(with_active(s, 1))
    assert apply_configuration(a).model_dump() == a.model_dump()


def test_paraxial_conjugates_of_both_configurations():
    # Newtonian imaging: z z' = -f f' -> image moves by f^2 / (s - f) for the 500 mm object
    s = _two()
    p0 = paraxial_data(compile_system(with_active(s, 0)))
    p1 = paraxial_data(compile_system(with_active(s, 1)))
    f = p0.efl
    s_obj = 500.0 + p0.front_principal_plane  # object distance from the front principal plane
    shift = f * f / (s_obj - f)
    assert (p1.paraxial_image_distance - p0.paraxial_image_distance) == pytest.approx(shift, rel=1e-9)


def test_material_aperture_and_semi_diameter_operands():
    s = _edit(
        _two(),
        lambda d: d["multi_config"]["operands"].extend(
            [
                {"parameter": "material", "surface_id": "d1", "values": ["N-BK7", "N-SK16"]},
                {"parameter": "aperture_value", "surface_id": None, "values": [20.0, 10.0]},
                {"parameter": "semi_diameter", "surface_id": "d1", "values": [12.5, 8.0]},
            ]
        ),
    )
    c0, c1 = compile_system(with_active(s, 0)), compile_system(with_active(s, 1))
    assert c1.n_after[1, 1] != c0.n_after[1, 1]
    assert c1.model.surfaces[1].material == "N-SK16"
    assert c1.model.aperture.value == 10.0
    assert c1.model.surfaces[1].semi_diameter_mode == "fixed" and c1.model.surfaces[1].semi_diameter == 8.0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["multi_config"]["operands"][0]["values"].append(1.0),  # wrong length
        lambda d: d["multi_config"]["operands"].append({"parameter": "thickness", "surface_id": "nope", "values": [1.0, 2.0]}),
        lambda d: d["multi_config"]["operands"].append({"parameter": "thickness", "surface_id": "d3", "values": [1.0, 2.0]}),  # duplicate
        lambda d: d["multi_config"]["operands"].append({"parameter": "material", "surface_id": "d1", "values": ["", "F2"]}),
        lambda d: d["multi_config"]["operands"].append({"parameter": "aperture_value", "surface_id": "d1", "values": [1.0, 2.0]}),
        lambda d: d["multi_config"]["operands"].append({"parameter": "radius", "surface_id": "d1", "values": [0.0, 50.0]}),
        lambda d: d["multi_config"].update(active=5),
        lambda d: d["multi_config"]["operands"].append({"parameter": "vcy", "values": [0.1, 0.2]}),  # no field
        lambda d: d["multi_config"]["operands"].append({"parameter": "vcy", "surface_id": "d1", "field": 1, "values": [0.1, 0.2]}),
        lambda d: d["multi_config"]["operands"].append({"parameter": "vcy", "field": 7, "values": [0.1, 0.2]}),  # no such field
        lambda d: d["multi_config"]["operands"].append({"parameter": "vcy", "field": 1, "values": [0.1, 1.0]}),  # vc < 1
        lambda d: d["multi_config"]["operands"].append({"parameter": "vdy", "field": 1, "values": [0.1, -1.5]}),
        lambda d: d["multi_config"]["operands"].append({"parameter": "thickness", "surface_id": "d3", "field": 1, "values": [1.0, 2.0]}),
        lambda d: d["multi_config"]["operands"].extend([{"parameter": "vdy", "field": 1, "values": [0.1, 0.2]}, {"parameter": "vdy", "field": 1, "values": [0.0, 0.0]}]),
    ],
)
def test_invalid_configuration_tables_are_rejected(mutate):
    with pytest.raises(ValueError):
        _edit(_two(), mutate)


def test_configuration_that_breaks_the_system_is_a_structured_error():
    # object-height fields need a finite object: configuration 1 has an infinite object
    s = _edit(_two(), lambda d: (d["surfaces"][0].update(thickness=1000.0), d.update(field_type="object_height")))
    compile_system(with_active(s, 1))  # finite in both? configuration 1 object = 500 mm: fine
    with pytest.raises(SystemError_) as ei:
        compile_system(with_active(s, 0))
    assert ei.value.diagnostics[0].code == "CONFIG_INVALID"


def test_solve_and_configuration_on_the_same_parameter_conflict():
    s = _edit(_two(), lambda d: d["surfaces"][3].update(thickness_solve={"type": "marginal_height"}))
    with pytest.raises(SystemError_):
        compile_system(s)


def _strip(system: OpticalSystem) -> OpticalSystem:
    d = apply_configuration(system).model_dump()
    d["multi_config"] = None
    return OpticalSystem.model_validate(d)


def test_merit_operands_per_configuration_match_single_configuration_systems():
    s = _two()
    ops = [Operand(type="rms_spot", rings=3, configuration=0), Operand(type="efl", target=100.0, configuration=1), Operand(type="rms_spot", rings=3, configuration=1)]
    mf = MeritFunction(s, OptimizationSpec(operands=ops))
    _, bd = mf.evaluate(mf.x0)
    for o, b in zip(ops, bd):
        single = MeritFunction(_strip(with_active(s, o.configuration)), OptimizationSpec(operands=[o.model_copy(update={"configuration": None})]))
        _, sb = single.evaluate(single.x0)
        assert b["value"] == pytest.approx(sb[0]["value"], rel=1e-12)
        assert b["configuration"] == o.configuration
    # operand without configuration uses the active one
    mf2 = MeritFunction(with_active(s, 1), OptimizationSpec(operands=[Operand(type="rms_spot", rings=3)]))
    _, bd2 = mf2.evaluate(mf2.x0)
    assert bd2[0]["value"] == pytest.approx(bd[2]["value"], rel=1e-12)


def test_per_configuration_variables_read_and_write_the_table():
    s = _two()
    v = Variable(surface_id="d3", parameter="thickness", configuration=1)
    assert get_variable_value(s, v) == TWO_CONJ_BFD["500"]
    idx = {x.id: i for i, x in enumerate(s.surfaces)}
    d = apply_values(s.model_dump(), [v], np.array([111.0]), idx)
    assert d["multi_config"]["operands"][1]["values"] == [TWO_CONJ_BFD["inf"], 111.0]
    assert s.multi_config.operands[1].values[1] == TWO_CONJ_BFD["500"]  # original untouched
    # curvature variables map onto radius rows
    s2 = _edit(s, lambda d: d["multi_config"]["operands"].append({"parameter": "radius", "surface_id": "d1", "values": [50.0, None]}))
    vc = Variable(surface_id="d1", parameter="curvature", configuration=0)
    assert get_variable_value(s2, vc) == pytest.approx(1 / 50.0)
    d2 = apply_values(s2.model_dump(), [vc], np.array([0.025]), idx)
    assert d2["multi_config"]["operands"][2]["values"][0] == pytest.approx(40.0)


def test_variable_validation_with_configurations():
    s = _two()
    ops = [Operand(type="rms_spot", rings=2)]
    with pytest.raises(ValueError):  # base variable on a parameter set per configuration
        MeritFunction(s, OptimizationSpec(variables=[Variable(surface_id="d3", parameter="thickness")], operands=ops))
    with pytest.raises(ValueError):  # per-configuration variable without a table row
        MeritFunction(s, OptimizationSpec(variables=[Variable(surface_id="d1", parameter="curvature", configuration=0)], operands=ops))
    with pytest.raises(ValueError):  # configuration out of range
        MeritFunction(s, OptimizationSpec(variables=[Variable(surface_id="d3", parameter="thickness", configuration=2)], operands=ops))
    with pytest.raises(ValueError):
        MeritFunction(s, OptimizationSpec(operands=[Operand(type="efl", configuration=3)]))


def test_multi_configuration_optimisation_refocuses_both_configurations():
    p = get_sample("achromat-two-conjugates")
    s = _edit(p.system, lambda d: d["multi_config"]["operands"][1].update(values=[100.0, 112.0]))
    res = optimize(s, p.optimization)
    assert res["final_merit"] < 0.5 * res["initial_merit"]
    final = {(v["configuration"]): v["final"] for v in res["variables"]}
    assert final[0] == pytest.approx(TWO_CONJ_BFD["inf"], abs=2e-3)
    assert final[1] == pytest.approx(TWO_CONJ_BFD["500"], abs=2e-3)
    out = OpticalSystem.model_validate(res["system"])
    assert out.multi_config.operands[1].values == pytest.approx([final[0], final[1]])


def test_frozen_sample_is_at_its_optimum():
    p = get_sample("achromat-two-conjugates")
    res = optimize(p.system, p.optimization)
    assert res["final_merit"] == pytest.approx(res["initial_merit"], rel=1e-3)


def test_tolerancing_uses_the_active_configuration_baked_in():
    s = with_active(_two(), 1)
    ev = Evaluator(s, ToleranceSpec(tolerances=[Tolerance(type="thickness", surface_id="d3", min=-0.1, max=0.1)], monte_carlo_trials=0), [])
    assert ev.system.multi_config is None
    assert ev.system.surfaces[0].thickness == 500.0 and ev.system.surfaces[3].thickness == TWO_CONJ_BFD["500"]
    r = ev.evaluate(np.array([0.1]))
    assert r["value"] is not None


def test_project_round_trip_and_evaluate_api():
    p = get_sample("achromat-two-conjugates")
    proj, _ = load_project(dump_project(p))
    assert proj.system.multi_config.names == p.system.multi_config.names
    assert proj.optimization.variables[1].configuration == 1
    c = TestClient(app)
    ev = c.post("/api/v1/system/evaluate", json={"system": with_active(proj.system, 1).model_dump()}).json()
    assert ev["configuration"] == {"active": 1, "names": ["Object at infinity", "Object at 500 mm"]}
    assert ev["paraxial"]["1"]["paraxial_magnification"] == pytest.approx(-0.2499, abs=1e-3)


def test_field_vignetting_factors_per_configuration():
    """A field's vignetting factors can differ per configuration (a zoom lens vignettes differently at each position):
    the active configuration's values replace the field's, and the vignetted pupil follows them."""
    from opticore.raytrace import vignetted_pupil

    s = _edit(_two(), lambda d: d["multi_config"]["operands"].extend([
        {"parameter": "vdy", "field": 1, "values": [-0.05, 0.0]},
        {"parameter": "vcy", "field": 1, "values": [0.2, 0.0]},
        {"parameter": "vcx", "field": 2, "values": [0.0, 0.1]},
    ]))
    c0, c1 = compile_system(with_active(s, 0)), compile_system(with_active(s, 1))
    f0, f1 = c0.model.fields, c1.model.fields
    assert (f0[1].vdy, f0[1].vcy, f0[2].vcx) == (-0.05, 0.2, 0.0)
    assert (f1[1].vdy, f1[1].vcy, f1[2].vcx) == (0.0, 0.0, 0.1)
    assert s.fields[1].vdy == 0.0  # the base field is unchanged
    px, py = vignetted_pupil(c0, 1, np.array([0.0]), np.array([1.0]))
    assert (px[0], py[0]) == pytest.approx((0.0, -0.05 + 1.0 * (1 - 0.2)))
    # a removed field must not be referenced: the system refuses an out-of-range field
    with pytest.raises(ValueError):
        _edit(s, lambda d: d.update(fields=d["fields"][:1]))
