"""Temperature and pressure (opticore/environment.py).

Benchmarks: textbook air indices, vacuum = absolute indices, exact homothetic scaling of a system whose
parts all expand alike, the thick-lens focal length with the thermal index and geometry, the thin-lens
thermo-optic coefficient, and the achromat's focus shift against the thin-lens prediction.
"""

import math

import numpy as np
import pytest

from opticore.environment import T_REF, air_index, environment_of, glass_cte
from opticore.materials import MaterialLibrary
from opticore.model import ConfigOperand, MultiConfig, OpticalSystem, Solve, Surface
from opticore.paraxial import paraxial_data
from opticore.samples import achromat, spherical_mirror
from opticore.solves import freeze_solves
from opticore.system import SystemError_, compile_system


def env(system: OpticalSystem, **kw) -> OpticalSystem:
    return system.model_copy(update={"environment_enabled": True, **kw})


def codes(cs) -> list[str]:
    return [d.code for d in cs.diagnostics]


# ---------------------------------------------------------------- air
def test_air_index_matches_textbook_values():
    # standard air for the sodium D line: 1.000293 at 0 °C and 1.000277 at 15 °C, 1 atm
    assert air_index(0.5893, 0.0, 1.0) == pytest.approx(1.000293, abs=1.5e-6)
    assert air_index(0.5893, 15.0, 1.0) == pytest.approx(1.000277, abs=1.5e-6)


def test_air_index_is_one_in_vacuum_and_linear_in_pressure():
    assert air_index(0.55, 20.0, 0.0) == 1.0
    n1, n2 = air_index(0.55, 20.0, 1.0) - 1.0, air_index(0.55, 20.0, 2.0) - 1.0
    assert n2 == pytest.approx(2.0 * n1, rel=1e-12)
    # warmer air is thinner
    assert air_index(0.55, 40.0, 1.0) < air_index(0.55, 0.0, 1.0)


# ---------------------------------------------------------------- defaults
def test_model_is_off_by_default_and_exact_at_reference_conditions():
    p = achromat(True)
    assert environment_of(p.system) is None
    cs0 = compile_system(p.system, p.custom_materials)
    cs1 = compile_system(env(p.system), p.custom_materials)
    # the catalogue glasses are referred to 20 °C, 1 atm: nothing changes, also not the geometry
    assert np.array_equal(cs0.n_after, cs1.n_after)
    assert [s.thickness for s in cs0.model.surfaces] == [s.thickness for s in cs1.model.surfaces]
    assert "ENVIRONMENT" in codes(cs1) and "ENVIRONMENT" not in codes(cs0)


def test_vacuum_gives_absolute_indices():
    p = achromat(True)
    cs = compile_system(env(p.system, pressure_atm=0.0), p.custom_materials)
    lib = MaterialLibrary(p.custom_materials)
    for w, lam in enumerate(cs.wavelengths):
        # in vacuum the wavelength is a vacuum wavelength; the catalogue (relative to air at 20 °C, 1 atm)
        # is read at the corresponding air wavelength and multiplied by that air's index
        n_air = air_index(lam, 20.0, 1.0)
        expected = lib.index("N-BK7", lam / n_air) * n_air
        assert cs.n_after[w, 1] == pytest.approx(expected, rel=2e-9)
    assert cs.n_after[0, 3] == 1.0  # the "air" of a vacuum system


def test_vacuum_medium_is_relative_to_the_system_air():
    p = achromat(True)
    d = p.system.model_dump()
    d["surfaces"][3]["material"] = "VACUUM"
    cs = compile_system(env(OpticalSystem.model_validate(d)), p.custom_materials)
    lam = float(cs.wavelengths[0])
    assert cs.n_after[0, 3] == pytest.approx(1.0 / air_index(lam, 20.0, 1.0), rel=1e-15)


# ---------------------------------------------------------------- expansion
ALPHA = 12.0  # 1e-6 / K for every part of the uniform-scaling test


def uniform_system() -> tuple[OpticalSystem, list[dict]]:
    """An aspheric singlet whose glass has no dn/dT and the same CTE as its mounts."""
    glass = {"name": "UNIFORM", "formula": "constant", "coefficients": [1.6], "tce_m30_70": ALPHA}
    surfs = [
        Surface(radius=None, thickness=None),
        Surface(radius=60.0, thickness=8.0, material="UNIFORM", type="even_asphere", aspheric=[-2e-6, 3e-10], is_stop=True),
        Surface(radius=-150.0, thickness=90.0),
        Surface(radius=None, thickness=0.0),
    ]
    # an F-number aperture is scale invariant (an entrance pupil diameter is a fixed specification)
    system = OpticalSystem(surfaces=surfs, wavelengths=[{"value": 0.55}], fields=[{"y": 0.0}, {"y": 3.0}], aperture={"type": "image_fnum", "value": 4.0}, housing_cte=ALPHA)
    return system, [glass]


def test_uniform_expansion_scales_the_whole_system():
    from opticore.analysis.spot import spot_diagram

    base, mats = uniform_system()
    # vacuum: no air whose index would change with temperature
    s0 = env(base, pressure_atm=0.0, temperature_c=T_REF)
    dT = 50.0
    s1 = env(base, pressure_atm=0.0, temperature_c=T_REF + dT)
    k = 1.0 + ALPHA * 1e-6 * dT
    cs0, cs1 = compile_system(s0, mats), compile_system(s1, mats)
    p0, p1 = paraxial_data(cs0), paraxial_data(cs1)
    assert p1.efl == pytest.approx(k * p0.efl, rel=1e-12)
    assert p1.bfl == pytest.approx(k * p0.bfl, rel=1e-12)
    # real rays: the spot of an expanded copy is the expanded spot (the aspheric terms scale with it)
    r0 = spot_diagram(cs0, density=6)["fields"][1]["rms_radius_um"]
    r1 = spot_diagram(cs1, density=6)["fields"][1]["rms_radius_um"]
    assert r1 == pytest.approx(k * r0, rel=1e-9)


def test_thick_lens_focal_length_with_thermal_index_and_geometry():
    p = achromat(True)
    d = p.system.model_dump()
    # an N-BK7 biconvex singlet in vacuum: the thick-lens formula with n(T), c/k and t*k
    d["surfaces"] = [d["surfaces"][0], {**d["surfaces"][1], "radius": 80.0, "thickness": 7.0}, {**d["surfaces"][2], "radius": -80.0, "thickness": 90.0, "material": "AIR"}, d["surfaces"][4]]
    d["multi_config"] = None
    for T in (-20.0, 60.0):
        s = env(OpticalSystem.model_validate(d), pressure_atm=0.0, temperature_c=T)
        cs = compile_system(s, p.custom_materials)
        w = s.primary_wavelength
        n = float(cs.n_after[w, 1])
        k = 1.0 + glass_cte(MaterialLibrary().get("N-BK7")) * (T - T_REF)
        c1, c2, t = 1 / (80.0 * k), 1 / (-80.0 * k), 7.0 * k
        f = 1.0 / ((n - 1.0) * (c1 - c2 + (n - 1.0) * t * c1 * c2 / n))
        assert paraxial_data(cs, w).efl == pytest.approx(f, rel=1e-10)


def test_thin_lens_thermo_optic_coefficient():
    # df/dT = -f beta, beta = (dn/dT)/(n - 1) - alpha (thin lens in vacuum)
    p = achromat(True)
    d = p.system.model_dump()
    d["surfaces"] = [d["surfaces"][0], {**d["surfaces"][1], "radius": 100.0, "thickness": 0.05}, {**d["surfaces"][2], "radius": -100.0, "thickness": 100.0, "material": "AIR"}, d["surfaces"][4]]
    d["multi_config"] = None
    base = OpticalSystem.model_validate(d)
    w = base.primary_wavelength
    h = 1.0

    def at(T):
        cs = compile_system(env(base, pressure_atm=0.0, temperature_c=T), p.custom_materials)
        return paraxial_data(cs, w).efl, float(cs.n_after[w, 1])

    (f_lo, n_lo), (f0, n0), (f_hi, n_hi) = at(T_REF - h), at(T_REF), at(T_REF + h)
    dfdT = (f_hi - f_lo) / (2 * h)
    beta = ((n_hi - n_lo) / (2 * h)) / (n0 - 1.0) - glass_cte(MaterialLibrary().get("N-BK7"))
    assert dfdT == pytest.approx(-f0 * beta, rel=2e-3)


def test_achromat_focus_shift_matches_the_thin_lens_prediction():
    """Acceptance benchmark: the cemented achromat from -20 °C to +60 °C in air.

    Thin lenses: dφ_i/dT = φ_i β_i with β = (dn_rel/dT)/(n - 1) - α, so the focal length changes by
    df = -(β1 φ1 + β2 φ2)/φ² ΔT, while the image surface moves with the aluminium spacer behind the lens
    (α_h L ΔT). The engine's image_surface_defocus is (image surface - paraxial focus)."""
    p = achromat(True)
    lib = MaterialLibrary(p.custom_materials)
    w = p.system.primary_wavelength
    T0, T1 = -20.0, 60.0
    cs0 = compile_system(env(p.system, temperature_c=T0), p.custom_materials)
    cs1 = compile_system(env(p.system, temperature_c=T1), p.custom_materials)
    shift = paraxial_data(cs1, w).image_surface_defocus - paraxial_data(cs0, w).image_surface_defocus

    s = p.system.surfaces
    c = [0.0 if x.radius is None else 1.0 / x.radius for x in s]
    csr = compile_system(env(p.system, temperature_c=T_REF), p.custom_materials)
    n1, n2 = float(csr.n_after[w, 1]), float(csr.n_after[w, 2])
    dn1 = (float(cs1.n_after[w, 1]) - float(cs0.n_after[w, 1])) / (T1 - T0)
    dn2 = (float(cs1.n_after[w, 2]) - float(cs0.n_after[w, 2])) / (T1 - T0)
    phi1, phi2 = (n1 - 1) * (c[1] - c[2]), (n2 - 1) * (c[2] - c[3])
    b1 = dn1 / (n1 - 1) - glass_cte(lib.get("N-BK7"))
    b2 = dn2 / (n2 - 1) - glass_cte(lib.get("F2"))
    phi = phi1 + phi2
    df = -(b1 * phi1 + b2 * phi2) / phi**2 * (T1 - T0)
    spacer = p.system.housing_cte * 1e-6 * s[3].thickness * (T1 - T0)
    predicted = spacer - df
    # thin-lens model of an 8.5 mm thick doublet: agreement within 10 % of the shift
    assert abs(shift) > 1e-3
    assert shift == pytest.approx(predicted, rel=0.10)


def test_mirror_follows_its_substrate():
    p = spherical_mirror()
    d = p.system.model_dump()
    d["surfaces"][2]["mount_cte"] = 0.5  # a low-expansion substrate
    s = env(OpticalSystem.model_validate(d), temperature_c=T_REF + 100.0)
    cs = compile_system(s, p.custom_materials)
    assert cs.model.surfaces[2].radius == pytest.approx(-200.0 * (1 + 0.5e-6 * 100.0), rel=1e-14)
    # the gap after the mirror follows the housing
    assert cs.model.surfaces[2].thickness == pytest.approx(-100.0 * (1 + 23.6e-6 * 100.0), rel=1e-14)


def test_missing_thermal_data_is_reported():
    p = achromat(True)
    d = p.system.model_dump()
    d["surfaces"][1]["material"] = "FUSED_SILICA"
    cs = compile_system(env(OpticalSystem.model_validate(d), temperature_c=40.0), p.custom_materials)
    assert {"THERMAL_NO_CTE", "THERMAL_NO_DNDT"} <= set(codes(cs))
    cs = compile_system(env(OpticalSystem.model_validate(d), temperature_c=90.0), p.custom_materials)
    assert "THERMAL_RANGE" in codes(cs)


# ---------------------------------------------------------------- configurations and solves
def test_temperature_and_pressure_per_configuration():
    p = achromat(True)
    mc = MultiConfig(names=["cold", "warm"], operands=[ConfigOperand(parameter="temperature", values=[-20.0, 60.0]), ConfigOperand(parameter="pressure", values=[1.0, 0.5])])
    s = env(p.system, multi_config=mc)
    from opticore.configs import with_active

    e = [paraxial_data(compile_system(with_active(s, k), p.custom_materials)).efl for k in (0, 1)]
    e_cold = paraxial_data(compile_system(env(p.system, temperature_c=-20.0), p.custom_materials)).efl
    e_warm = paraxial_data(compile_system(env(p.system, temperature_c=60.0, pressure_atm=0.5), p.custom_materials)).efl
    assert e == [pytest.approx(e_cold, rel=1e-14), pytest.approx(e_warm, rel=1e-14)]
    with pytest.raises(ValueError):
        MultiConfig(names=["a"], operands=[ConfigOperand(parameter="temperature", surface_id="x", values=[20.0])])


def test_frozen_solves_expand_once():
    p = achromat(True)
    d = p.system.model_dump()
    d["surfaces"][3]["thickness_solve"] = Solve(type="marginal_height", target=0.0).model_dump()
    s = env(OpticalSystem.model_validate(d), temperature_c=70.0)
    solved = compile_system(s, p.custom_materials)
    frozen = freeze_solves(s, p.custom_materials)
    again = compile_system(frozen, p.custom_materials)
    assert again.model.surfaces[3].thickness == pytest.approx(solved.model.surfaces[3].thickness, rel=1e-12)
    # the frozen prescription is the nominal (20 °C) one
    assert frozen.surfaces[3].thickness == pytest.approx(solved.model.surfaces[3].thickness / (1 + 23.6e-6 * 50.0), rel=1e-12)


def test_unknown_material_still_fails_cleanly():
    p = achromat(True)
    d = p.system.model_dump()
    d["surfaces"][1]["material"] = "NO-SUCH-GLASS"
    with pytest.raises(SystemError_):
        compile_system(env(OpticalSystem.model_validate(d), temperature_c=40.0), p.custom_materials)
    assert math.isfinite(air_index(0.5, -40.0, 1.0))


# ---------------------------------------------------------------- analysis and athermalisation
def test_thermal_analysis_reports_focus_shift_and_depth_of_focus():
    from opticore.analysis.thermal import thermal_analysis

    p = achromat(True)
    r = thermal_analysis(p.system, p.custom_materials, "temperature", -20.0, 60.0, 5)
    assert r["values"] == [-20.0, 0.0, 20.0, 40.0, 60.0]
    assert all("error" not in row for row in r["rows"])
    # the analysis turns the model on and says so
    assert r["notes"]
    # linear slope of the best focus against the end points
    bf = [row["best_focus_mm"] for row in r["rows"]]
    assert r["slopes_per_unit"]["best_focus_mm"] == pytest.approx((bf[-1] - bf[0]) / 80.0, rel=0.02)
    assert r["focus_spread_mm"] == pytest.approx(max(bf) - min(bf))
    # diffraction depth of focus 2 λ N² at F/5, 587.6 nm
    assert r["reference"]["depth_of_focus_mm"] == pytest.approx(2 * 0.5875618e-3 * 25.0, rel=1e-3)
    # the band is centred on the best focus at the system's own temperature (20 °C is a sweep point)
    assert r["reference"]["best_focus_mm"] == pytest.approx(bf[2], abs=1e-12)
    # the swept value wins over a configuration value for the same quantity
    mc = MultiConfig(names=["a"], operands=[ConfigOperand(parameter="temperature", values=[55.0])])
    r2 = thermal_analysis(env(p.system, multi_config=mc), p.custom_materials, "temperature", -20.0, 60.0, 5)
    assert [row["best_focus_mm"] for row in r2["rows"]] == pytest.approx(bf, rel=1e-12)


def test_thermal_api():
    from fastapi.testclient import TestClient

    from opticore.api.main import app

    p = achromat(True)
    c = TestClient(app)
    body = {"system": p.system.model_dump(mode="json"), "custom_materials": p.custom_materials, "variable": "pressure", "start": 0.0, "stop": 1.0, "steps": 3}
    r = c.post("/api/v1/analysis/thermal", json=body)
    assert r.status_code == 200
    rows = r.json()["rows"]
    # in vacuum the glass is relatively denser: shorter focal length
    assert rows[0]["efl_mm"] < rows[-1]["efl_mm"]
    assert c.post("/api/v1/analysis/thermal", json={**body, "start": -1.0}).status_code == 422


def test_three_temperature_optimisation_athermalises_with_the_spacer():
    """Acceptance benchmark: passive athermalisation of the achromat's back focal spacer.

    Thin-lens prediction of the effective spacer expansion that keeps the image on the focus:
    α_s = (df/dT) / L."""
    from opticore.analysis.thermal import thermal_analysis
    from opticore.optimize.engine import optimize
    from opticore.optimize.merit import Variable

    p = achromat(True)
    mc = MultiConfig(names=["-20 °C", "20 °C", "60 °C"], operands=[ConfigOperand(parameter="temperature", values=[-20.0, 20.0, 60.0])], active=1)
    s = env(p.system, multi_config=mc)
    spec = p.optimization.model_copy(deep=True)
    ops = []
    for o in spec.operands:
        ops += [o.model_copy(update={"configuration": k}) for k in range(3)] if o.type == "rms_spot" else [o]
    spec.operands = ops
    spec.variables = list(spec.variables) + [Variable(surface_id="d3", parameter="mount_cte", min=-20.0, max=60.0)]
    before = thermal_analysis(s, p.custom_materials, "temperature", -20.0, 60.0, 5)
    res = optimize(s, spec, p.custom_materials)
    out = OpticalSystem.model_validate(res["system"])
    after = thermal_analysis(out, p.custom_materials, "temperature", -20.0, 60.0, 5)
    assert after["focus_spread_mm"] < before["focus_spread_mm"] / 20.0
    dfdT = before["slopes_per_unit"]["efl_mm"]
    assert out.surfaces[3].mount_cte * 1e-6 == pytest.approx(dfdT / out.surfaces[3].thickness, rel=0.15)
    # without the environment model the variable is refused
    with pytest.raises(ValueError):
        from opticore.optimize.engine import validate_spec

        validate_spec(p.system, spec.model_copy(update={"operands": p.optimization.operands}), p.custom_materials)


def test_thermal_expansion_scales_every_polynomial_surface_form():
    """A glass element expands homothetically, z_k(x, y) = k z(x / k, y / k). The same surface written as an even
    asphere, an odd asphere, a Q-con asphere and an XY polynomial must expand alike (odd, Q and XY terms and
    obscurations left at their 20 °C values give a sag error of -1.4e-4 mm at r = 9 mm for 50 K)."""
    from opticore.model import Aperture, FieldPoint, Wavelength

    R, A4, Rn, T = 40.0, -2.0e-5, 10.0, 70.0
    xy = [0.0] * 14  # x, y, x^2, xy, y^2, x^3, x^2y, xy^2, y^3, x^4, x^3y, x^2y^2, xy^3, y^4
    xy[9], xy[11], xy[13] = A4 * Rn**4, 2 * A4 * Rn**4, A4 * Rn**4
    forms = {
        "even": dict(type="even_asphere", aspheric=[A4]),
        "odd": dict(type="odd_asphere", odd_coefficients=[0.0, 0.0, 0.0, A4]),
        "xy": dict(type="xy_polynomial", xy_coefficients=xy, xy_norm_radius=Rn, obscuration=1.0),
    }

    def build(kw, temp):
        return OpticalSystem(
            surfaces=[Surface(thickness=None), Surface(radius=R, thickness=6.0, material="N-BK7", is_stop=True, **kw), Surface(radius=-200.0, thickness=60.0), Surface()],
            wavelengths=[Wavelength(value=0.5875618)], aperture=Aperture(type="epd", value=20.0), fields=[FieldPoint(y=0.0), FieldPoint(y=3.0)],
            environment_enabled=True, temperature_c=temp, housing_cte=0.0,
        )

    k = 1 + glass_cte(MaterialLibrary().get("N-BK7")) * (T - T_REF)
    for name, kw in forms.items():
        z20 = float(compile_system(build(kw, T_REF)).shapes[1].sag_xy(np.array([0.0]), np.array([9.0]))[0])
        cs = compile_system(build(kw, T))
        z70 = float(cs.shapes[1].sag_xy(np.array([0.0]), np.array([9.0 * k]))[0])
        assert z70 == pytest.approx(k * z20, abs=1e-12), name
        if name == "xy":
            assert cs.model.surfaces[1].obscuration == pytest.approx(k, rel=1e-12)
    # Q-con: amplitudes and normalisation radius
    q = dict(type="qcon", q_coefficients=[1e-3, -2e-4], q_norm_radius=Rn)
    z20 = float(compile_system(build(q, T_REF)).shapes[1].sag_xy(np.array([0.0]), np.array([9.0]))[0])
    z70 = float(compile_system(build(q, T)).shapes[1].sag_xy(np.array([0.0]), np.array([9.0 * k]))[0])
    assert z70 == pytest.approx(k * z20, abs=1e-12)
