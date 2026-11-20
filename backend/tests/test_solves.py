import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.model import OpticalSystem
from opticore.optimize.merit import MeritFunction, Operand, OptimizationSpec, Variable
from opticore.paraxial import chief_ray, compute_pupil, marginal_ray, max_field_value, paraxial_data
from opticore.project import dump_project, load_project
from opticore.samples import get_sample
from opticore.solves import freeze_solves
from opticore.system import SystemError_, compile_system

from .conftest import make_system


def _with(sample: str, edits: dict) -> OpticalSystem:
    d = get_sample(sample).system.model_dump()
    for sid, patch in edits.items():
        s = next(x for x in d["surfaces"] if x["id"] == sid)
        s.update(patch)
    return OpticalSystem.model_validate(d)


def test_marginal_height_zero_puts_image_at_paraxial_focus():
    sysm = _with("singlet", {"s2": {"thickness": 50.0, "thickness_solve": {"type": "marginal_height"}}})
    cs = compile_system(sysm)
    pd = paraxial_data(cs)
    ref = paraxial_data(compile_system(_with("singlet", {})))
    assert cs.model.surfaces[2].thickness == pytest.approx(ref.bfl, rel=1e-13)
    assert pd.image_surface_defocus == pytest.approx(0.0, abs=1e-10)
    assert any(d.code == "SOLVE_ACTIVE" for d in cs.diagnostics)


def test_marginal_height_target_and_zone():
    h = 0.75
    sysm = _with("singlet", {"s2": {"thickness_solve": {"type": "marginal_height", "target": h}}})
    cs = compile_system(sysm)
    m = marginal_ray(cs, cs.model.primary_wavelength, compute_pupil(cs))
    assert m.y[3] == pytest.approx(h, rel=1e-12)
    # zone 0.7 with target 0 is still the paraxial focus (paraxial rays scale linearly)
    z = compile_system(_with("singlet", {"s2": {"thickness_solve": {"type": "marginal_height", "zone": 0.7}}}))
    assert z.model.surfaces[2].thickness == pytest.approx(paraxial_data(z).bfl, rel=1e-13)


def test_f_number_solve_sets_working_f_number_with_focus():
    F = 4.0
    sysm = _with(
        "singlet",
        {"s2": {"radius": -500.0, "curvature_solve": {"type": "f_number", "target": F}, "thickness_solve": {"type": "marginal_height"}}},
    )
    cs = compile_system(sysm)
    pd = paraxial_data(cs)
    assert pd.working_fnum == pytest.approx(F, rel=1e-12)
    # infinite object: working F/# = EFL / EPD
    assert pd.efl == pytest.approx(F * 10.0, rel=1e-12)
    assert pd.image_surface_defocus == pytest.approx(0.0, abs=1e-10)


def test_marginal_angle_solve_on_a_mirror():
    target = 0.08  # slope after the mirror in the signed (unfolded) convention
    sysm = _with("spherical-mirror", {"m1": {"curvature_solve": {"type": "marginal_angle", "target": target}}})
    cs = compile_system(sysm)
    m = marginal_ray(cs, 0, compute_pupil(cs))
    assert m.u[2] == pytest.approx(target, rel=1e-12)
    # collimated marginal ray at y = 10: c = (0 - n'u') / (y (n' - n)) with n = 1, n' = -1 -> R = -20 / u'
    assert cs.model.surfaces[2].radius == pytest.approx(-20.0 / target, rel=1e-12)


def test_chief_height_solve_locates_exit_pupil():
    sysm = make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "a", "radius": 50.0, "thickness": 5.0, "material": "N-BK7", "is_stop": True},
            {"id": "b", "radius": None, "thickness": 20.0, "thickness_solve": {"type": "chief_height"}},
            {"id": "c", "thickness": 30.0},
            {"id": "img"},
        ],
        wavelengths=[{"value": 0.5875618}],
        fields=[{"y": 0.0}, {"y": 3.0}],
        aperture={"type": "epd", "value": 10.0},
    )
    cs = compile_system(sysm)
    pupil = compute_pupil(cs)
    c = chief_ray(cs, 0, pupil, max_field_value(cs))
    assert c.y[3] == pytest.approx(0.0, abs=1e-12)
    # stop on the first surface: the exit pupil is its image; thickness < 0 means virtual (before surface b)
    assert cs.model.surfaces[2].thickness < 0


def test_pickups_follow_their_source():
    sysm = make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "a", "radius": 60.0, "thickness": 6.0, "material": "N-BK7", "is_stop": True},
            {"id": "b", "radius": 10.0, "thickness": 40.0, "curvature_solve": {"type": "pickup", "surface_id": "a", "scale": -1.0}},
            {"id": "c", "thickness": 1.0, "thickness_solve": {"type": "pickup", "surface_id": "a", "scale": 2.0, "offset": 0.5}},
            {"id": "img"},
        ],
        wavelengths=[{"value": 0.55}],
    )
    cs = compile_system(sysm)
    assert cs.model.surfaces[2].radius == pytest.approx(-60.0)
    assert cs.model.surfaces[3].thickness == pytest.approx(12.5)
    d = sysm.model_dump()
    d["surfaces"][1]["radius"] = 80.0
    cs2 = compile_system(OpticalSystem.model_validate(d))
    assert cs2.model.surfaces[2].radius == pytest.approx(-80.0)
    # plane source stays plane
    d["surfaces"][1]["radius"] = None
    assert compile_system(OpticalSystem.model_validate(d)).model.surfaces[2].radius is None


def test_solve_before_the_stop_converges():
    # thickness solve before the stop changes the entrance pupil, which changes the ray it solves for
    sysm = make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "l1", "radius": 40.0, "thickness": 4.0, "material": "N-BK7"},
            {"id": "l2", "radius": None, "thickness": 10.0, "thickness_solve": {"type": "marginal_height", "target": 3.0}},
            {"id": "stp", "thickness": 20.0, "is_stop": True, "semi_diameter": 3.0},
            {"id": "img"},
        ],
        wavelengths=[{"value": 0.55}],
        aperture={"type": "epd", "value": 10.0},
    )
    cs = compile_system(sysm)
    assert not any(d.code == "SOLVE_NOT_CONVERGED" for d in cs.diagnostics)
    m = marginal_ray(cs, 0, compute_pupil(cs))
    assert m.y[3] == pytest.approx(3.0, rel=1e-10)


def test_solve_validation_errors():
    bad = [
        {"s1": {"curvature_solve": {"type": "marginal_height"}}},  # not a curvature solve
        {"s2": {"thickness_solve": {"type": "pickup", "surface_id": "s2"}}},  # self pickup
        {"s2": {"thickness_solve": {"type": "pickup", "surface_id": "nope"}}},
        {"s2": {"curvature_solve": {"type": "f_number", "target": 0.0}}},
        {"obj": {"curvature_solve": {"type": "marginal_angle"}}},
    ]
    for e in bad:
        with pytest.raises(SystemError_):
            compile_system(_with("singlet", e))


def test_parallel_ray_reports_failed_solve():
    # an afocal ray after surface 2 (plane surfaces, collimated light): solve undefined
    sysm = make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "a", "thickness": 5.0, "material": "N-BK7", "is_stop": True},
            {"id": "b", "thickness": 7.0, "thickness_solve": {"type": "marginal_height"}},
            {"id": "img"},
        ],
        wavelengths=[{"value": 0.55}],
    )
    cs = compile_system(sysm)
    assert cs.model.surfaces[2].thickness == 7.0
    assert any(d.code == "SOLVE_FAILED" for d in cs.diagnostics)


def test_variable_on_solved_parameter_is_rejected():
    sysm = _with("singlet", {"s2": {"thickness_solve": {"type": "marginal_height"}}})
    spec = OptimizationSpec(variables=[Variable(surface_id="s2", parameter="thickness")], operands=[Operand(type="rms_spot")])
    with pytest.raises(ValueError):
        MeritFunction(sysm, spec)


def test_optimisation_keeps_focus_through_solve():
    from opticore.optimize.engine import optimize

    sysm = _with("singlet", {"s2": {"thickness_solve": {"type": "marginal_height"}}})
    spec = OptimizationSpec(variables=[Variable(surface_id="s1", parameter="curvature", min=1 / 200, max=1 / 30)], operands=[Operand(type="efl", target=80.0)], max_evaluations=200)
    res = optimize(sysm, spec)
    out = compile_system(OpticalSystem.model_validate(res["system"]))
    pd = paraxial_data(out)
    assert pd.efl == pytest.approx(80.0, rel=1e-6)
    assert pd.image_surface_defocus == pytest.approx(0.0, abs=1e-9)
    assert out.model.surfaces[2].thickness_solve is not None


def test_freeze_solves_and_tolerancing_nominal():
    sysm = _with("singlet", {"s2": {"thickness_solve": {"type": "marginal_height"}}})
    fz = freeze_solves(sysm)
    assert all(s.thickness_solve is None and s.curvature_solve is None for s in fz.surfaces)
    assert fz.surfaces[2].thickness == pytest.approx(compile_system(sysm).model.surfaces[2].thickness, rel=0, abs=0)


def test_solves_survive_project_round_trip_and_api():
    p = get_sample("singlet")
    d = p.model_dump()
    d["system"]["surfaces"][2]["thickness_solve"] = {"type": "marginal_height", "target": 0.0, "surface_id": None, "scale": 1.0, "offset": 0.0, "zone": 1.0}
    raw = dump_project(type(p).model_validate(d))
    proj, _ = load_project(raw)
    assert proj.system.surfaces[2].thickness_solve.type == "marginal_height"
    c = TestClient(app)
    ev = c.post("/api/v1/system/evaluate", json={"system": proj.system.model_dump()}).json()
    assert ev["solved"][0]["surface"] == 2
    assert ev["solved"][0]["thickness"] == pytest.approx(paraxial_data(compile_system(proj.system)).bfl + 0.0, rel=1e-12)
