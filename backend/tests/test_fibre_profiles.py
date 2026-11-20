"""Fibres beyond the step index (wave/fibreprofile.py, wave/fibre2d.py, wave/fibreapi.py).

Benchmarks:
* Step index: the transfer method and the finite differences against the exact LP eigenvalue equation
  (fibermodes.py); the LP11 cut-off at V = 2.405 (the first zero of J0).
* Parabolic profile: the infinite parabola's modes beta^2 = k^2 n1^2 - 2 k (2p + l + 1) NA / a, its Gaussian
  fundamental mode (MFD 2 sqrt(2) a / sqrt(V), A_eff = 2 pi a^2 / V), its group index and dispersion from the
  analytic beta(k), and the mode count V^2 / 4.
* Layered (W) profile: two independent methods (exact transfer, finite differences) agree.
* Material dispersion: the cladding glass's D from the analytic second derivative of Malitson's formula.
* Cross-sections: the full-vector solver against the exact vector HE11 of a step-index rod (the six-hole
  microstructured fibre against the multipole method is the library example, test_fibre_examples.py).
"""

import math

import pytest
from fastapi.testclient import TestClient
from scipy.optimize import brentq

from opticore.api.main import app
from opticore.materials import MaterialLibrary
from opticore.wave.fibermodes import fibre_modes
from opticore.wave.fibre2d import CrossSection, Shape, solve_modes
from opticore.wave.fibreprofile import C_UM_PER_PS, Profile, _cut_shoot, cutoff_wavelength, dispersion, lp01_properties, lp_modes

client = TestClient(app)
LIB = MaterialLibrary()


def silica(lam):
    return LIB.index("FUSED_SILICA", lam)


@pytest.mark.parametrize("method,tol", [("tmm", 1e-13), ("fd", 5e-11)])
def test_step_index_matches_the_exact_lp_solution(method, tol):
    lam, a, n1, n2 = 1.0, 5.0, 1.46, 1.45
    exact = fibre_modes(lam, a, n1, n2, vector=False)["lp_modes"]
    got = lp_modes(Profile("step", a, dn_core=n1 - n2), lam, n2, method=method)
    assert [m["name"] for m in got] == [m["name"] for m in exact]
    assert max(abs(x["neff"] - y["neff"]) for x, y in zip(got, exact)) < tol
    lc = cutoff_wavelength(Profile("step", a, dn_core=n1 - n2), n2)
    assert lc == pytest.approx(2 * math.pi * a * math.sqrt(n1**2 - n2**2) / 2.404825557695773, rel=1e-10)


def test_parabolic_profile_matches_the_infinite_parabola():
    lam, a, n2, dn = 0.85, 25.0, 1.45, 0.0137
    n1 = n2 + dn
    k = 2 * math.pi / lam
    NA = math.sqrt(n1**2 - n2**2)
    V = k * a * NA
    prof = Profile("graded", a, dn_core=dn, alpha=2.0)
    modes = lp_modes(prof, lam, n2)
    for m in modes[:12]:
        M = 2 * (m["m"] - 1) + m["l"] + 1
        if M <= 5:  # well inside the core: the truncation of the parabola at r = a is negligible
            assert m["neff"] == pytest.approx(math.sqrt(k * k * n1 * n1 - 2 * k * M * NA / a) / k, abs=2e-11)
    p = lp01_properties(prof, lam, n2)
    assert p["mfd_petermann2_um"] == pytest.approx(2 * math.sqrt(2) * a / math.sqrt(V), rel=1e-8)
    assert p["effective_area_um2"] == pytest.approx(2 * math.pi * a * a / V, rel=1e-8)
    assert sum(m["degeneracy"] for m in modes) == pytest.approx(V * V / 4, rel=0.03)


def test_parabolic_group_index_and_dispersion_match_beta_of_k():
    """Constant indices (no material dispersion): beta^2 = k^2 n1^2 - 2 k M NA / a gives n_g = beta' and
    D = -(2 pi / (c lambda^2)) beta'' analytically."""
    a, n2, dn = 25.0, 1.45, 0.0137
    n1 = n2 + dn
    NA = math.sqrt(n1**2 - n2**2)
    prof = Profile("graded", a, dn_core=dn, alpha=2.0)
    for lam, (l, m, M) in ((0.85, (0, 1, 1)), (1.3, (0, 1, 1)), (0.85, (1, 1, 2))):
        k = 2 * math.pi / lam
        b = math.sqrt(k * k * n1 * n1 - 2 * k * M * NA / a)
        b1 = (k * n1 * n1 - M * NA / a) / b
        b2 = (n1 * n1 - b1 * b1) / b
        row = dispersion(prof, [lam], n2, l, m)["rows"][0]
        assert row["group_index"] == pytest.approx(b1, abs=1e-10)
        assert row["D_ps_nm_km"] == pytest.approx(-(2 * math.pi / (C_UM_PER_PS * lam * lam)) * b2 * 1e6, abs=2e-5)


def test_layered_profile_two_methods_agree():
    W = Profile("layers", 0.0, layers=((4.0, 0.0055), (7.0, -0.0025), (9.0, 0.001)))
    for lam in (1.0, 1.55):
        t = lp_modes(W, lam, silica)
        f = lp_modes(W, lam, silica, method="fd")
        assert [m["name"] for m in t] == [m["name"] for m in f]
        assert max(abs(x["neff"] - y["neff"]) for x, y in zip(t, f)) < 2e-11
    lc = cutoff_wavelength(W, silica)
    assert [m["name"] for m in lp_modes(W, lc * 0.999, silica)] == ["LP01", "LP11"]
    assert [m["name"] for m in lp_modes(W, lc * 1.001, silica)] == ["LP01"]
    # the exact layer solutions against the numerically integrated radial equation
    assert brentq(lambda x: _cut_shoot(W, 1, x, silica), lc * 0.99, lc * 1.01, xtol=1e-14) == pytest.approx(lc, abs=1e-11)


def test_cut_offs_of_higher_modes_and_outside_the_range():
    """LP21 cuts off at V = j_1,1 = 3.8317; a 1 mm core guides LP11 beyond 50 um (no cut-off in the range)."""
    lam, a, n1, n2 = 1.0, 5.0, 1.46, 1.45
    V_lc = 2 * math.pi * a * math.sqrt(n1**2 - n2**2)
    assert cutoff_wavelength(Profile("step", a, dn_core=n1 - n2), n2, l=2) == pytest.approx(V_lc / 3.8317059702075125, rel=1e-10)
    for kind in ("step", "graded"):
        assert cutoff_wavelength(Profile(kind, 500.0, dn_core=0.017), silica, 1, (0.05, 50.0)) is None


def test_material_dispersion_is_the_glass_formula():
    """D_material = -(lambda / c) d2n/dlambda2 of Malitson's fused silica, differentiated analytically here."""
    B = (0.6961663, 0.4079426, 0.8974794)
    C = (0.0684043**2, 0.1162414**2, 9.896161**2)

    def n_and_d2(lam):
        L2 = lam * lam
        f = 1 + sum(b * L2 / (L2 - c) for b, c in zip(B, C))
        f1 = sum(b * (-2 * c * lam) / (L2 - c) ** 2 for b, c in zip(B, C))  # df/dlambda
        f2 = sum(b * (-2 * c) * (L2 - c - 4 * L2) / (L2 - c) ** 3 for b, c in zip(B, C))
        n = math.sqrt(f)
        return n, f2 / (2 * n) - f1 * f1 / (4 * n**3)

    smf = Profile("step", 4.1, dn_core=0.0052)
    for lam in (1.31, 1.55):
        row = dispersion(smf, [lam], silica)["rows"][0]
        n, d2 = n_and_d2(lam)
        assert row["n_clad"] == pytest.approx(n, abs=1e-12)
        assert row["D_material_ps_nm_km"] == pytest.approx(-(lam / C_UM_PER_PS) * d2 * 1e6, abs=1e-4)


def test_rod_cross_section_matches_the_exact_vector_mode():
    """HE11 of a step-index rod (n 1.45 in 1.40, a = 1 um, 1 um): meshes h and h/2 with Richardson extrapolation."""
    exact = fibre_modes(1.0, 1.0, 1.45, 1.40, vector=True)["vector_modes"][0]
    assert exact["name"] == "HE11"
    cs = CrossSection(1.40, [Shape("circle", 0.0, 0.0, 1.45, r=1.0)])
    got = []
    for h in (0.05, 0.025):
        ms, _ = solve_modes(cs, 1.0, 4.0, h, n_guess=1.43, count=2)
        got.append(ms[0]["neff"].real)
    assert abs(got[1] - exact["neff"]) < 1e-6
    assert abs((4 * got[1] - got[0]) / 3 - exact["neff"]) < 3e-7


def test_fibre_endpoints():
    r = client.post("/api/v1/wave/fiber_modes", json={"wavelength_um": 0.85, "core_radius_um": 25, "na": 0.2, "clad_material": "FUSED_SILICA", "profile_kind": "graded", "alpha": 2}).json()
    assert r["profile_kind"] == "graded" and r["mode_count"] > 300 and r["lp01"]["effective_area_um2"] > 0 and len(r["index_profile"]["r_um"]) == 401
    r = client.post("/api/v1/wave/fiber_modes", json={"wavelength_um": 1.55, "core_radius_um": 4.1, "dn": 0.0052, "clad_material": "FUSED_SILICA"}).json()
    assert r["single_mode"] and r["vector_modes"][0]["name"] == "HE11" and "core_power_fraction" in r["lp01"]
    d = client.post("/api/v1/wave/fiber_dispersion", json={"wavelength_um": 1.55, "core_radius_um": 4.1, "dn": 0.0052, "clad_material": "FUSED_SILICA", "wl_min_um": 1.2, "wl_max_um": 1.6, "points": 5}).json()
    assert len(d["rows"]) == 5 and 1.25 < d["zero_dispersion_um"] < 1.35 and d["cutoff_lp11_um"] == pytest.approx(cutoff_wavelength(Profile("step", 4.1, dn_core=0.0052), silica), rel=1e-9)
    bad = client.post("/api/v1/wave/fiber_modes", json={"wavelength_um": 1.55, "core_radius_um": 4.1, "clad_material": "FUSED_SILICA", "profile_kind": "layers", "layers": [[4, -0.001]]})
    assert bad.status_code == 422
