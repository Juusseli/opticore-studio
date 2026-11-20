"""Manufacturability: element geometry, mass and drawing data, CAD solids of
elements, spacers and barrel, and the catalogue internal transmittance in the trace and throughput."""

import math

import numpy as np
import pytest
from scipy.integrate import quad

from opticore.analysis.elements import element_geometry, elements, glass_code
from opticore.analysis.evaluate import auto_semi_diameters, effective_semi_diameters
from opticore.analysis.throughput import transmission
from opticore.materials import MaterialLibrary
from opticore.model import OpticalSystem
from opticore.paraxial import compute_pupil
from opticore.raytrace import launch, trace
from opticore.samples import achromat, cooke_triplet, singlet
from opticore.system import compile_system
from opticore.tolerance import default_spec

from .conftest import make_system


def _cs_sd(system):
    cs = compile_system(system)
    return cs, effective_semi_diameters(cs, auto_semi_diameters(cs, compute_pupil(cs), {}))


def _sphere_sag(R, r):
    return R - math.copysign(math.sqrt(R * R - r * r), R)


def _with(system, **surface_patches):
    d = system.model_dump()
    for sid, patch in surface_patches.items():
        next(s for s in d["surfaces"] if s["id"] == sid).update(patch)
    return OpticalSystem.model_validate(d)


# ----------------------------------------------------------------------------- geometry
def test_plano_convex_volume_is_the_analytic_cap_plus_cylinder():
    sysm = singlet().system
    cs, sd = _cs_sd(sysm)
    g = element_geometry(cs, sd, 1)
    Rs, t, R = 51.68, 5.0, g["rim_radius_mm"]
    assert R == pytest.approx(max(sd[1], sd[2]))
    h = _sphere_sag(Rs, R)
    assert g["edge_thickness_mm"] == pytest.approx(t - h, rel=1e-13)
    cap = math.pi * h * h * (3 * Rs - h) / 3
    assert g["volume_mm3"] == pytest.approx(math.pi * R * R * (t - h) + cap, rel=1e-12)


def test_flats_and_chamfers_against_independent_integration():
    """A biconvex lens whose back surface ends at 7 mm and continues as a flat to the 10 mm rim set by the
    front's mechanical semi-diameter, with chamfers of 0.4 and 0.3 mm."""
    sysm = make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "a", "radius": 40.0, "thickness": 6.0, "material": "N-BK7", "is_stop": True, "mech_semi_diameter": 10.0, "chamfer": 0.4},
            {"id": "b", "radius": -60.0, "thickness": 50.0, "mech_semi_diameter": 7.0, "chamfer": 0.3},
            {"id": "img"},
        ],
        wavelengths=[{"value": 0.5875618}],
        fields=[{"y": 0.0}],
        aperture={"type": "epd", "value": 10.0},
    )
    cs, sd = _cs_sd(sysm)
    g = element_geometry(cs, sd, 1)
    R, cf, cb, t = 10.0, 0.4, 0.3, 6.0
    assert g["rim_radius_mm"] == R and g["profile_ends_mm"] == [10.0, 7.0]

    def zf(r):
        return _sphere_sag(40.0, r)

    def zb(r):
        return t + _sphere_sag(-60.0, min(r, 7.0))

    def front(r):
        if r <= R - cf:
            return zf(r)
        z0 = zf(R - cf)
        return z0 + (r - (R - cf)) / cf * (zf(R) + cf - z0)

    def back(r):
        if r <= R - cb:
            return zb(r)
        z0 = zb(R - cb)
        return z0 + (r - (R - cb)) / cb * (zb(R) - cb - z0)

    v = sum(quad(lambda r: 2 * math.pi * r * (back(r) - front(r)), lo, hi, epsabs=1e-12, epsrel=1e-13)[0] for lo, hi in ((0, 7), (7, R - cf), (R - cf, R - cb), (R - cb, R)))
    assert g["volume_mm3"] == pytest.approx(v, rel=1e-11)
    assert g["edge_thickness_mm"] == pytest.approx(zb(R) - zf(R), rel=1e-13)
    # the outline is closed through the axis and has the chamfer corners
    assert g["outline"][0] == [0.0, 0.0] and g["outline"][-1] == pytest.approx([0.0, t])
    assert [R, pytest.approx(zf(R) + cf)] in g["outline"]


def test_misfits_are_reported():
    sysm = singlet().system
    s = _with(sysm, s1={"chamfer": 3.0}, s2={"chamfer": 3.0})
    cs, sd = _cs_sd(s)
    with pytest.raises(ValueError):
        element_geometry(cs, sd, 1)  # 6 mm of chamfers on a thinner edge
    s = _with(sysm, s1={"mech_semi_diameter": 2.0})
    cs, sd = _cs_sd(s)
    assert any("smaller than the clear" in n for n in element_geometry(cs, sd, 1)["notes"])


# ----------------------------------------------------------------------------- parts and drawing data
def test_doublet_parts_mass_and_iso_data():
    p = achromat(True)
    r = elements(p.system, p.custom_materials, default_spec(p.system, "precision"))
    l1, l2 = r["elements"]
    assert [l1["material"]["name"], l2["material"]["name"]] == ["N-BK7", "F2"]
    assert [l1["material"]["code"], l2["material"]["code"]] == ["517642", "620364"]
    assert glass_code(1.5168, 64.17) == "517642"
    assert l1["radii_mm"] == [p.system.surfaces[1].radius, p.system.surfaces[2].radius]
    assert l1["center_thickness_mm"] == 6.0 and l2["center_thickness_mm"] == 2.5
    assert l1["cemented_surfaces"] == [2] and l2["cemented_surfaces"] == [2]
    # mass = volume x catalogue density (2.51 and 3.599 g/cm3, refractiveindex.info / SCHOTT)
    assert l1["mass_g"] == pytest.approx(l1["volume_mm3"] * 2.51e-3, rel=1e-14)
    assert l2["mass_g"] == pytest.approx(l2["volume_mm3"] * 3.599e-3, rel=1e-14)
    assert r["total_mass_g"] == pytest.approx(l1["mass_g"] + l2["mass_g"])
    assert r["relative_cost"] is None  # the built-in glasses carry no catalogue cost
    tl = l1["tolerances"]
    assert tl["surfaces"][0]["iso_3"] == "3/3(1)" and tl["surfaces"][1]["iso_3"] == "3/3(1)"
    assert tl["surfaces"][0]["iso_4"] == "4/1'"  # element tilt 1' of the cemented group
    assert tl["center_thickness"] == [-0.05, 0.05] and tl["nd"] == 0.0005
    assert tl["vd"] == pytest.approx(0.005 * 64.17, rel=2e-3)
    assert tl["surfaces"][0]["radius"] == pytest.approx([-0.0495259, 0.0495259])
    assert tl["test_wavelength_nm"] == pytest.approx(546.07)


def test_drawings_use_the_20_degree_design():
    p = achromat(True)
    d = p.system.model_dump()
    d.update(environment_enabled=True, temperature_c=60.0)
    warm = elements(OpticalSystem.model_validate(d), p.custom_materials)["elements"][0]
    cold = elements(p.system, p.custom_materials)["elements"][0]
    assert warm["radii_mm"] == cold["radii_mm"] and warm["center_thickness_mm"] == cold["center_thickness_mm"]


# ----------------------------------------------------------------------------- CAD solids
def test_exported_element_solids_have_the_element_volume():
    pytest.importorskip("OCP")
    from opticore.io.cad import build_optics

    sysm = make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "a", "radius": 40.0, "thickness": 6.0, "material": "N-BK7", "is_stop": True, "mech_semi_diameter": 10.0, "chamfer": 0.4},
            {"id": "b", "radius": -60.0, "thickness": 50.0, "mech_semi_diameter": 7.0, "chamfer": 0.3},
            {"id": "img"},
        ],
        wavelengths=[{"value": 0.5875618}],
        fields=[{"y": 0.0}],
        aperture={"type": "epd", "value": 10.0},
    )
    for system in (sysm, singlet().system, achromat(True).system):
        cs, sd = _cs_sd(system)
        _items, rep = build_optics(cs, sd, include_stop=False, include_image=False, include_rays=False)
        assert rep["solids"] and not rep["skipped"]
        for s in rep["solids"]:
            assert s["volume_mm3"] == pytest.approx(s["element_volume_mm3"], rel=1e-9)


def test_spacers_cells_and_barrel():
    """Triplet: two spacers (one around the stop), cells for the two smaller lenses, a barrel. Solid
    volumes equal the analytic ones (annuli and frusta); no ray of the design meets a spacer."""
    pytest.importorskip("OCP")
    from opticore.io.cad import build_mechanics
    from opticore.raytrace import trace_pupil

    system = cooke_triplet(True).system
    cs, sd = _cs_sd(system)
    items, lay = build_mechanics(cs, sd)
    assert [x["kind"] for x in items] == ["spacer", "spacer", "cell", "cell", "barrel"]  # the 2nd and 3rd lenses are smaller than the bore
    rb = lay["barrel"]["inner_radius_mm"]
    for sp in lay["spacers"] + lay["cells"]:
        assert sp["solid_volume_mm3"] == pytest.approx(sp["volume_mm3"], rel=1e-9)
    c = lay["cells"][0]
    assert c["volume_mm3"] == pytest.approx(math.pi * (rb**2 - c["inner_radius_mm"] ** 2) * (c["z_end_mm"] - c["z_start_mm"]), rel=1e-14)
    b = lay["barrel"]
    assert b["solid_volume_mm3"] == pytest.approx(math.pi * (b["outer_radius_mm"] ** 2 - rb**2) * (b["z_end_mm"] - b["z_start_mm"]), rel=1e-9)
    # rays of every field and wavelength stay inside the spacer bores
    pupil = compute_pupil(cs)
    a = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    px, py = np.concatenate([np.cos(a), 0.7 * np.cos(a), [0.0]]), np.concatenate([np.sin(a), 0.7 * np.sin(a), [0.0]])
    checked = 0
    for f in range(len(system.fields)):
        for w in range(len(system.wavelengths)):
            r = trace_pupil(cs, w, f, px, py, pupil, clip=True)
            for sp in lay["spacers"]:
                zs = np.linspace(sp["z_start_mm"], sp["z_end_mm"], 40)
                bore = np.interp(zs, [q[1] for q in sp["bore"]], [q[0] for q in sp["bore"]])
                for k in np.nonzero(r.ok)[0]:
                    for kk in range(sp["between"][0] - 1, sp["between"][1] + 1):
                        p0, p1 = r.points[k, kk], r.points[k, kk + 1]
                        sel = (zs >= min(p0[2], p1[2])) & (zs <= max(p0[2], p1[2]))
                        if not sel.any() or p1[2] == p0[2]:
                            continue
                        u = (zs[sel] - p0[2]) / (p1[2] - p0[2])
                        rho = np.hypot(p0[0] + u * (p1[0] - p0[0]), p0[1] + u * (p1[1] - p0[1]))
                        assert np.all(rho <= bore[sel] + 1e-9)
                        checked += int(sel.sum())
    assert checked > 1000
    # a cemented doublet has no spacer
    cs2, sd2 = _cs_sd(achromat(True).system)
    assert build_mechanics(cs2, sd2)[1]["spacers"] == []


# ----------------------------------------------------------------------------- internal transmittance
def _plate(material="N-BK7", t=25.0, lam=0.546, catalog=True):
    return make_system(
        [
            {"id": "obj", "thickness": None},
            {"id": "p1", "thickness": t, "material": material, "is_stop": True},
            {"id": "p2", "thickness": 10.0},
            {"id": "img"},
        ],
        wavelengths=[{"value": lam}],
        fields=[{"y": 0.0}],
        aperture={"type": "epd", "value": 4.0},
        catalog_absorption=catalog,
    )


def _internal(system):
    cs = compile_system(system)
    P, D, opl = launch(cs, 0, 0, np.array([0.0]), np.array([0.0]), compute_pupil(cs))
    r = trace(cs, 0, P, D, opl, clip=True, fresnel=False)
    return float(r.intensity[0]), cs


def test_slab_transmittance_scales_the_catalogue_value():
    """Benchmark: through d mm of glass the internal transmittance is tau_cat^(d / d_cat) at a tabulated
    wavelength (N-BK7, 546 nm: tau = 0.998558 at 10 mm, refractiveindex.info / SCHOTT)."""
    tab = {lam: tau for lam, tau, _d in MaterialLibrary().get("N-BK7").extra["internal_transmission"]}
    for d in (5.0, 25.0, 100.0):
        tau, _ = _internal(_plate(t=d))
        assert tau == pytest.approx(tab[0.546] ** (d / 10.0), rel=1e-12)
    # between tabulated wavelengths alpha is interpolated linearly
    a1, a2 = -math.log(tab[0.5]) / 10, -math.log(tab[0.546]) / 10
    tau, _ = _internal(_plate(lam=0.523))
    assert tau == pytest.approx(math.exp(-25.0 * (a1 + (a2 - a1) * (0.523 - 0.5) / 0.046)), rel=1e-12)
    # off by default: no absorption (the built-in glasses have no constant coefficient)
    assert _internal(_plate(catalog=False))[0] == 1.0
    # outside the tabulated range the end value is used and reported
    _, cs = _internal(_plate(lam=2.6))
    assert "TRANSMITTANCE_EXTRAPOLATED" in [d.code for d in cs.diagnostics]


def test_throughput_includes_internal_transmittance():
    """Acceptance criterion: the doublet's throughput with catalogue absorption is lower by the internal
    transmittance, and the analysis names the source per glass."""
    p = achromat(True)
    off = transmission(compile_system(p.system, p.custom_materials))
    d = p.system.model_dump()
    d["catalog_absorption"] = True
    on = transmission(compile_system(OpticalSystem.model_validate(d), p.custom_materials))
    assert on["weighted_mean_total"] < off["weighted_mean_total"]
    assert {m["name"]: m["source"] for m in on["absorption"]["materials"]} == {"N-BK7": "catalogue", "F2": "catalogue"}
    assert off["notes"] and not on["notes"]
    # chief ray at the primary wavelength (587.6 nm): the ratio is exp(-alpha1 t1 - alpha2 t2) along the axis
    mats = MaterialLibrary()
    a1, _ = mats.get("N-BK7").catalog_absorption(0.5875618)
    a2, _ = mats.get("F2").catalog_absorption(0.5875618)
    ratio = on["chief_ray_surfaces"][-1]["cumulative"] / off["chief_ray_surfaces"][-1]["cumulative"]
    assert ratio == pytest.approx(math.exp(-a1 * 6.0 - a2 * 2.5), rel=1e-12)


def test_elements_api():
    from fastapi.testclient import TestClient

    from opticore.api.main import app

    p = achromat(True)
    r = TestClient(app).post("/api/v1/elements", json={"system": p.system.model_dump(mode="json"), "custom_materials": p.custom_materials, "tolerancing": default_spec(p.system).model_dump()})
    assert r.status_code == 200
    body = r.json()
    assert len(body["elements"]) == 2 and body["elements"][0]["tolerances"]["surfaces"][0]["iso_3"] == "3/3(1)"


def _close(a, b, path="$"):
    """Recursive equality with floats compared to 1e-9 relative (the fixture is engine output)."""
    if isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys(), path
        for k in a:
            _close(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b), path
        for k, (x, y) in enumerate(zip(a, b)):
            _close(x, y, f"{path}[{k}]")
    elif isinstance(a, float) or isinstance(b, float):
        assert b == pytest.approx(a, rel=1e-9, abs=1e-12), path
    else:
        assert a == b, path


def test_frontend_element_fixture_is_current():
    """frontend/src/lib/__fixtures__/elements_achromat.json is engine output (regenerate:
    python -m opticore.tools.element_fixture --write)."""
    import json

    from opticore.tools.element_fixture import FIXTURE, build

    _close(build(), json.loads(FIXTURE.read_text(encoding="utf-8")))
