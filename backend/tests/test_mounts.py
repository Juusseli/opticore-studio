"""Mount tree (opticore/environment.py).

Benchmarks: exact chain sums for one part, a re-entrant pair and a part at its own temperature; a single
housing part against the uniform housing expansion (test_environment.py); a lens at its own temperature; an
athermal barrel by the choice of holder material.
"""

import pytest

from opticore.analysis.thermal import thermal_analysis
from opticore.environment import T_REF, mount_report
from opticore.model import MountPart, OpticalSystem
from opticore.paraxial import paraxial_data
from opticore.samples import achromat, spherical_mirror
from opticore.system import compile_system


def mounted(system: OpticalSystem, parts: list[MountPart], seats: dict[int, str], **kw) -> OpticalSystem:
    d = system.model_dump()
    d["environment_enabled"] = True
    d["mounts"] = [m.model_dump() for m in parts]
    for i, pid in seats.items():
        d["surfaces"][i]["seat_part"] = pid
    d.update(kw)
    return OpticalSystem.model_validate(d)


def positions(cs) -> list[float]:
    """Axial vertex positions (from surface 1) of the compiled system."""
    out, z = [0.0], 0.0
    for s in cs.model.surfaces[1:-1]:
        z += s.thickness or 0.0
        out.append(z)
    return out  # index k = surface k + 1


def achromat_mounted(parts, seats, **kw):
    p = achromat(True)
    return mounted(p.system, parts, seats, **kw), p.custom_materials


L_IMG = 6.0 + 2.5 + 94.8055  # nominal axial position of the achromat's image surface


def test_one_part_moves_its_seat_by_its_expansion():
    alpha, dT = 23.6, 40.0
    s, mats = achromat_mounted([MountPart(id="h", cte=alpha)], {4: "h"}, temperature_c=T_REF + dT)
    cs = compile_system(s, mats)
    z_img = positions(cs)[3]
    assert z_img == pytest.approx(L_IMG * (1 + alpha * 1e-6 * dT), rel=1e-13)
    rep = mount_report(s, mats)
    assert rep["seats"][0]["shift_mm"] == pytest.approx(L_IMG * alpha * 1e-6 * dT, rel=1e-12)


def test_re_entrant_pair_cancels():
    # barrel forward to 150 mm (aluminium), holder back to the image: α1·150 = α2·(150 − L)
    a1 = 23.6
    a2 = a1 * 150.0 / (150.0 - L_IMG)
    parts = [MountPart(id="barrel", cte=a1), MountPart(id="holder", cte=a2, parent="barrel", datum_z=150.0)]
    s, mats = achromat_mounted(parts, {4: "holder"}, temperature_c=T_REF + 40.0)
    rep = mount_report(s, mats)
    assert rep["seats"][0]["shift_mm"] == pytest.approx(0.0, abs=1e-13)
    assert [p["datum_shift_mm"] for p in rep["parts"]] == pytest.approx([0.0, 150.0 * a1 * 1e-6 * 40.0], rel=1e-12)


def test_part_at_its_own_temperature():
    s, mats = achromat_mounted([MountPart(id="h", cte=17.3, temperature_c=60.0)], {4: "h"})
    rep = mount_report(s, mats)  # system at 20 °C: only the part is warm
    assert rep["seats"][0]["shift_mm"] == pytest.approx(L_IMG * 17.3e-6 * 40.0, rel=1e-12)
    cs = compile_system(s, mats)
    # the lens itself is at 20 °C and keeps its prescription
    assert [x.radius for x in cs.model.surfaces[1:4]] == [x.radius for x in achromat(True).system.surfaces[1:4]]


def test_single_housing_reproduces_the_uniform_expansion():
    """A system whose glass and housing share one CTE: holding the image on one housing part from
    surface 1 gives the same positions as the uniform housing expansion without a mount tree."""
    glass = {"name": "UNIFORM", "formula": "constant", "coefficients": [1.6], "tce_m30_70": 12.0}
    from opticore.model import Surface

    base = OpticalSystem(
        surfaces=[Surface(thickness=None), Surface(radius=60.0, thickness=8.0, material="UNIFORM", is_stop=True), Surface(radius=-150.0, thickness=90.0), Surface(thickness=0.0)],
        aperture={"type": "image_fnum", "value": 4.0},
        housing_cte=12.0,
        environment_enabled=True,
        temperature_c=70.0,
    )
    uniform = compile_system(base, [glass])
    housed = compile_system(mounted(base, [MountPart(id="h", cte=12.0)], {3: "h"}, temperature_c=70.0), [glass])
    assert positions(housed) == pytest.approx(positions(uniform), rel=1e-13)


def test_seated_lens_carries_its_element():
    # the front of the lens sits 10 mm in front of the part's datum: it moves by α·10·ΔT; the gap behind
    # the lens follows the housing as without a mount
    s, mats = achromat_mounted([MountPart(id="cell", cte=23.6, datum_z=-10.0)], {1: "cell"}, temperature_c=60.0)
    cs = compile_system(s, mats)
    ref = compile_system(OpticalSystem.model_validate({**s.model_dump(), "mounts": [], "surfaces": [{**x, "seat_part": None} for x in s.model_dump()["surfaces"]]}), mats)
    shift = 23.6e-6 * 10.0 * 40.0
    # surface 1 stays the frame origin: the object distance takes the shift (infinite object: unchanged)
    assert positions(cs) == pytest.approx(positions(ref), abs=1e-12)
    rep = mount_report(s, mats)
    assert rep["seats"][0]["shift_mm"] == pytest.approx(shift, rel=1e-12)


def test_lens_at_its_own_temperature():
    """A lens warmer than its housing: in vacuum its focal length changes exactly as when the whole
    system is at that temperature (the gaps do not enter the EFL of a single element)."""
    p = achromat(True)
    d = p.system.model_dump()
    d.update(environment_enabled=True, pressure_atm=0.0)
    d["surfaces"][1]["element_temperature_c"] = 50.0
    d["surfaces"][2]["element_temperature_c"] = 50.0
    warm_lens = compile_system(OpticalSystem.model_validate(d), p.custom_materials)
    d2 = p.system.model_dump()
    d2.update(environment_enabled=True, pressure_atm=0.0, temperature_c=50.0)
    warm_all = compile_system(OpticalSystem.model_validate(d2), p.custom_materials)
    assert paraxial_data(warm_lens).efl == pytest.approx(paraxial_data(warm_all).efl, rel=1e-13)
    # but the image gap stays at 20 °C
    assert warm_lens.model.surfaces[3].thickness == pytest.approx(94.8055, rel=1e-14)


def test_warmer_lens_moves_the_focus_as_predicted():
    """Acceptance criterion: a cemented doublet 10 K warmer than its air and housing. Its focal length follows an
    independent thick-system matrix calculation (reduced angles: refraction [[1, 0], [-(n'-n)c, 1]],
    transfer [[1, t/n], [0, 1]]) with the element indices at 30 °C and radii and thicknesses expanded
    with each glass; the image gap stays at 20 °C, so the focus moves relative to the image surface."""
    import numpy as np

    from opticore.environment import glass_cte
    from opticore.materials import MaterialLibrary

    p = achromat(True)
    w = p.system.primary_wavelength
    dt = 10.0

    def at(delta):
        d = p.system.model_dump()
        d["environment_enabled"] = True
        for i in (1, 2):
            d["surfaces"][i]["element_temperature_c"] = T_REF + delta
        return compile_system(OpticalSystem.model_validate(d), p.custom_materials)

    c0, c1 = at(0.0), at(dt)
    lib = MaterialLibrary(p.custom_materials)
    k1 = 1 + glass_cte(lib.get("N-BK7")) * dt
    k2 = 1 + glass_cte(lib.get("F2")) * dt
    s = p.system.surfaces
    n = [1.0, float(c1.n_after[w, 1]), float(c1.n_after[w, 2]), 1.0]
    c = [1 / (s[1].radius * k1), 1 / (s[2].radius * k2), 1 / (s[3].radius * k2)]
    t = [s[1].thickness * k1, s[2].thickness * k2]

    def refr(cv, na, nb):
        return np.array([[1.0, 0.0], [-(nb - na) * cv, 1.0]])

    def move(tt, nn):
        return np.array([[1.0, tt / nn], [0.0, 1.0]])

    M = refr(c[2], n[2], n[3]) @ move(t[1], n[2]) @ refr(c[1], n[1], n[2]) @ move(t[0], n[1]) @ refr(c[0], n[0], n[1])
    assert paraxial_data(c1, w).efl == pytest.approx(-1.0 / M[1, 0], rel=1e-10)
    # the image gap is unchanged, so the defocus changes with the lens
    assert c1.model.surfaces[3].thickness == c0.model.surfaces[3].thickness
    assert abs(paraxial_data(c1, w).image_surface_defocus - paraxial_data(c0, w).image_surface_defocus) > 1e-3


def test_athermal_barrel_by_holder_material():
    """Acceptance criterion: an Invar barrel holds the lens; the image plane sits on a holder attached to the barrel
    at 97 mm. An aluminium holder makes the mount follow the focus; other holder materials do worse, and
    an all-aluminium barrel is far off."""
    spreads = {}
    for name, cte in (("aluminium", 23.6), ("stainless", 17.3), ("titanium", 8.6), ("invar", 1.3)):
        parts = [MountPart(id="barrel", cte=1.3), MountPart(id="holder", cte=cte, parent="barrel", datum_z=97.0)]
        s, mats = achromat_mounted(parts, {1: "barrel", 4: "holder"})
        spreads[name] = thermal_analysis(s, mats, "temperature", -20.0, 60.0, 5)["focus_spread_mm"]
    s, mats = achromat_mounted([MountPart(id="barrel", cte=23.6)], {1: "barrel", 4: "barrel"})
    all_al = thermal_analysis(s, mats, "temperature", -20.0, 60.0, 5)["focus_spread_mm"]
    assert min(spreads, key=spreads.get) == "aluminium"
    assert spreads["aluminium"] < all_al / 20.0
    # the analytic chain: image shift per K = 97·α_invar + (L − 97)·α_holder; focus shift per K ≈ EFL slope
    assert spreads["aluminium"] < spreads["stainless"] < spreads["titanium"] < spreads["invar"]


def test_limits_are_reported():
    # mirrors: seats are ignored
    p = spherical_mirror()
    s = mounted(p.system, [MountPart(id="h", cte=23.6)], {3: "h"}, temperature_c=40.0)
    cs = compile_system(s, p.custom_materials)
    assert "MOUNT_UNSUPPORTED" in [d.code for d in cs.diagnostics]
    # both faces of one lens seated
    s, mats = achromat_mounted([MountPart(id="a", cte=23.6), MountPart(id="b", cte=1.3)], {1: "a", 3: "b"}, temperature_c=40.0)
    assert "MOUNT_OVERCONSTRAINED" in [d.code for d in compile_system(s, mats).diagnostics]
    # a mount that pulls the image into the lens
    s, mats = achromat_mounted([MountPart(id="h", cte=500.0, temperature_c=1000.0, datum_z=1000.0)], {4: "h"})
    assert "MOUNT_COLLISION" in [d.code for d in compile_system(s, mats).diagnostics]


def test_schema_rejects_bad_trees():
    p = achromat(True)
    with pytest.raises(ValueError):
        mounted(p.system, [MountPart(id="a", parent="b"), MountPart(id="b", parent="a")], {})
    with pytest.raises(ValueError):
        mounted(p.system, [MountPart(id="a", parent="missing")], {})
    with pytest.raises(ValueError):
        mounted(p.system, [MountPart(id="a")], {4: "nope"})
    with pytest.raises(ValueError):
        mounted(p.system, [MountPart(id="a"), MountPart(id="a")], {})


def test_mounts_api():
    from fastapi.testclient import TestClient

    from opticore.api.main import app

    s, mats = achromat_mounted([MountPart(id="h", name="Housing", cte=23.6)], {4: "h"}, temperature_c=60.0)
    r = TestClient(app).post("/api/v1/system/mounts", json={"system": s.model_dump(mode="json"), "custom_materials": mats})
    assert r.status_code == 200
    j = r.json()
    assert j["enabled"] and j["seats"][0]["surface"] == 4
    assert j["seats"][0]["shift_mm"] == pytest.approx(L_IMG * 23.6e-6 * 40.0, rel=1e-12)
