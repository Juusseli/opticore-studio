"""First-lens starting prescriptions (design.py): analytic thin-lens solutions made thick.

Benchmarks:
* thick-lens EFL equals the requested focal length (exact paraxial trace, any f, F/#, field);
* the singlet uses Coddington's best-form shape factor 2(n^2-1)/(n+2), which minimises
  the third-order spherical aberration S_I: bending the lens either way increases it;
* the doublet's thin-lens powers satisfy phi1 + phi2 = phi and phi1/V1 + phi2/V2 = 0
  exactly, and the thick doublet's paraxial axial colour (F - C) is a small fraction of a
  singlet's of the same focal length;
* every element meets the minimum edge thickness and the image sits at the paraxial focus.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from opticore.analysis.aberrations import chromatic_focal_shift
from opticore.analysis.evaluate import edge_thickness
from opticore.api.main import app
from opticore.design import DesignError, achromat_powers, best_form_shape_factor, first_lens
from opticore.materials import MaterialLibrary
from opticore.paraxial import compute_pupil, paraxial_data, seidel_coefficients
from opticore.project import load_project
from opticore.system import compile_system

FDC = [0.4861327, 0.5875618, 0.6562725]


@pytest.mark.parametrize("kind", ["singlet", "doublet"])
@pytest.mark.parametrize("f,N,hf", [(100.0, 5.0, 2.0), (50.0, 4.0, 10.0), (250.0, 8.0, 0.0)])
def test_thick_lens_has_the_requested_focal_length_and_edges(kind, f, N, hf):
    p, info = first_lens(f, N, hf, FDC, 1, kind)
    cs = compile_system(p.system, p.custom_materials)
    pd = paraxial_data(cs, 1)
    assert pd.efl == pytest.approx(f, rel=1e-10)
    assert p.system.aperture.value == pytest.approx(f / N, rel=1e-12)
    assert pd.image_surface_defocus == pytest.approx(0.0, abs=1e-9 * f)
    h = 0.5 * f / N * 1.05
    e_min = info["design"]["min_edge_thickness"]
    for k in range(1, len(p.system.surfaces) - 2):
        assert edge_thickness(cs, k, h) >= e_min - 1e-6
    assert len(p.system.fields) == (1 if hf == 0 else 3)
    assert p.system.fields[-1].y == pytest.approx(hf)


def test_singlet_best_form_minimises_spherical_aberration():
    n = MaterialLibrary().index("N-BK7", 0.5875618)
    q = best_form_shape_factor(n)
    assert q == pytest.approx(2 * (n * n - 1) / (n + 2), rel=1e-15)
    p, info = first_lens(100.0, 8.0, 0.0, [0.5875618], 0, "singlet")
    assert info["design"]["shape_factor"] == pytest.approx(q, rel=1e-12)

    def s1(dc: float) -> float:
        s = p.system.model_copy(deep=True)
        for k in (1, 2):  # bend: same power, both curvatures shifted
            c = 1.0 / s.surfaces[k].radius if s.surfaces[k].radius else 0.0
            s.surfaces[k].radius = 1.0 / (c + dc)
        return abs(seidel_coefficients(compile_system(s))["total"]["SI"])

    best = s1(0.0)
    for dc in (-0.004, -0.002, 0.002, 0.004):
        assert s1(dc) > best
    # and a plano-convex lens of the same power has clearly more S_I
    s = p.system.model_copy(deep=True)
    c1 = 1.0 / s.surfaces[1].radius - 1.0 / s.surfaces[2].radius  # same thin-lens power, c2 = 0
    s.surfaces[1].radius, s.surfaces[2].radius = 1.0 / c1, None
    assert abs(seidel_coefficients(compile_system(s))["total"]["SI"]) > best


def test_doublet_satisfies_the_achromat_condition():
    p1, p2 = achromat_powers(0.01, 64.17, 36.37)
    assert p1 + p2 == pytest.approx(0.01, rel=1e-15)
    assert p1 / 64.17 + p2 / 36.37 == pytest.approx(0.0, abs=1e-18)
    p, info = first_lens(100.0, 5.0, 2.0, FDC, 1, "doublet")
    d = info["design"]
    v1, v2 = d["abbe"]
    assert d["phi1"] / v1 + d["phi2"] / v2 == pytest.approx(0.0, abs=1e-15)
    assert d["phi1"] + d["phi2"] == pytest.approx(0.01, rel=1e-14)
    single, _ = first_lens(100.0, 5.0, 2.0, FDC, 1, "singlet")

    def colour(project) -> float:
        cs = compile_system(project.system, project.custom_materials)
        shift = chromatic_focal_shift(cs, FDC[0], FDC[2], samples=2)["focal_shift_um"]
        return abs(shift[-1] - shift[0])

    assert colour(p) < 0.05 * colour(single)
    # the merit function carries axial colour for the doublet only
    assert any(o.type == "axial_color" for o in p.optimization.operands)
    assert not any(o.type == "axial_color" for o in single.optimization.operands)


def test_errors_are_reported():
    with pytest.raises(DesignError):
        first_lens(100.0, 5.0, 0.0, FDC, 1, "doublet", crown="F2", flint="N-BK7")
    with pytest.raises(DesignError):
        first_lens(100.0, 5.0, 0.0, [0.55], 0, "doublet")
    with pytest.raises(DesignError):
        first_lens(100.0, 5.0, 0.0, FDC, 1, "singlet", crown="NO-SUCH-GLASS")
    with pytest.raises(DesignError):
        first_lens(10.0, 0.6, 0.0, FDC, 1, "singlet")


def test_first_lens_endpoint_returns_a_valid_project():
    client = TestClient(app)
    r = client.post("/api/v1/design/first-lens", json={"focal_length": 80, "f_number": 4, "half_field_deg": 5, "wavelengths": FDC, "primary": 1, "kind": "doublet", "name": "My first lens"})
    assert r.status_code == 200, r.text
    body = r.json()
    proj, _ = load_project(body["project"])
    assert proj.metadata.name == "My first lens"
    assert paraxial_data(compile_system(proj.system), 1).efl == pytest.approx(80.0, rel=1e-9)
    assert compute_pupil(compile_system(proj.system)).r_ep == pytest.approx(10.0, rel=1e-12)
    bad = client.post("/api/v1/design/first-lens", json={"focal_length": 80, "f_number": 4, "wavelengths": [0.55], "kind": "doublet"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "DESIGN_ERROR"
