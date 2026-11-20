"""The fibre examples of the library (samples.py): each is run as the Fibre Modes or Fibre Cross-Section view runs it
(the stored view settings turned into the same request) and checked against an independent calculation.

* Single-mode step fibre: LP01 from the exact LP eigenvalue equation and from the transfer solution; the cut-off from
  V(lambda) = j_0,1 with the cladding's dispersion; MFD, effective area and core fraction by adaptive quadrature of the
  Bessel field; dispersion and group index from a seven-point stencil of the exact LP eigenvalue (fibermodes.py).
* Graded 50/125: the infinite parabola's modes, MFD and effective area; the LP11 cut-off of the truncated parabola
  from Kummer's function: psi = x exp(-V x^2 / 2) M(1 - V/4, 2, V x^2), x psi'/psi = -1 at the core edge.
* Trench-assisted fibre: finite differences against the exact transfer (modes, field quantities, dispersion) and the
  integrated radial equation against the exact layer solutions (cut-off).
* Six-hole microstructured fibre: the multipole method (White et al., JOSA B 19, 2322 (2002), as tabulated by Guo et
  al., Opt. Express 12, 3341 (2004)).
"""

import math
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.integrate import quad
from scipy.optimize import brentq
from scipy.special import hyp1f1, j0, j1, k0, k1

from opticore.api.main import app
from opticore.materials import MaterialLibrary
from opticore.samples import FIBRE_PCF_REFERENCE, FIBRE_TRENCH_RINGS, fibre_request, get_sample
from opticore.tools.fibre_examples import FIXTURE, collect
from opticore.wave.fibermodes import fibre_modes
from opticore.wave.fibreprofile import C_UM_PER_PS, Profile, _cell_properties, _cut_shoot, _fd_modes, lp_modes

client = TestClient(app)
LIB = MaterialLibrary()
J01 = 2.404825557695773


def silica(lam):
    return LIB.index("FUSED_SILICA", lam)


def _run(sid):
    p = get_sample(sid)
    st = p.analysis_settings["fibermodes"]
    body = fibre_request(st, p.system.wavelengths[p.system.primary_wavelength].value)
    r = client.post("/api/v1/wave/fiber_modes", json=body)
    assert r.status_code == 200, r.text
    d = None
    if st["dispersion"]:
        rd = client.post("/api/v1/wave/fiber_dispersion", json=dict(body, wl_min_um=st["disp_min_um"], wl_max_um=st["disp_max_um"], points=st["disp_points"]))
        assert rd.status_code == 200, rd.text
        d = rd.json()
    assert p.ui["open_view"] == "fibermodes"
    return p, body, r.json(), d


def _row(d, lam):
    return min(d["rows"], key=lambda x: abs(x["wavelength_um"] - lam))


def _D_of(neff_fn, lam, h_rel):
    """D (ps/(nm km)) and the group index from n_eff(lambda) on a seven-point stencil."""
    h = h_rel * lam
    f = [neff_fn(lam + j * h) for j in range(-3, 4)]
    d1 = (-f[0] + 9 * f[1] - 45 * f[2] + 45 * f[4] - 9 * f[5] + f[6]) / (60 * h)
    d2 = (2 * f[0] - 27 * f[1] + 270 * f[2] - 490 * f[3] + 270 * f[4] - 27 * f[5] + 2 * f[6]) / (180 * h * h)
    return -(lam / C_UM_PER_PS) * d2 * 1e6, f[3] - lam * d1


def _malitson_D(lam):
    B = (0.6961663, 0.4079426, 0.8974794)
    C = (0.0684043**2, 0.1162414**2, 9.896161**2)
    L2 = lam * lam
    f = 1 + sum(b * L2 / (L2 - c) for b, c in zip(B, C))
    f1 = sum(b * (-2 * c * lam) / (L2 - c) ** 2 for b, c in zip(B, C))
    f2 = sum(b * (-2 * c) * (-3 * L2 - c) / (L2 - c) ** 3 for b, c in zip(B, C))
    n = math.sqrt(f)
    return -(lam / C_UM_PER_PS) * (f2 / (2 * n) - f1 * f1 / (4 * n**3)) * 1e6


def test_single_mode_step_fibre_example():
    p, body, r, d = _run("fibre-smf")
    a, dn, lam = 4.1, 0.0052, 1.55
    assert body["dn"] == dn and body["wavelength_um"] == lam and body["clad_material"] == "FUSED_SILICA"
    nc = silica(lam)
    n1 = nc + dn
    lp = lp_modes(Profile("step", a, dn_core=dn), lam, silica)
    exact = fibre_modes(lam, a, n1, nc, vector=False)["lp_modes"]
    assert r["single_mode"] and [m["name"] for m in lp] == [m["name"] for m in exact] == ["LP01"]
    assert r["lp01"]["neff"] == pytest.approx(exact[0]["neff"], abs=1e-13) == pytest.approx(lp[0]["neff"], abs=1e-13)
    assert r["vector_modes"][0]["name"] == "HE11" and abs(r["vector_modes"][0]["neff"] - exact[0]["neff"]) < 2e-5
    lc = brentq(lambda x: 2 * math.pi * a * math.sqrt((silica(x) + dn) ** 2 - silica(x) ** 2) / x - J01, 0.8, 2.0, xtol=1e-14)
    assert r["cutoff_wavelength_um"] == pytest.approx(lc, abs=1e-10)
    # LP01 field quantities by adaptive quadrature of J0 / K0
    k = 2 * math.pi / lam
    neff = exact[0]["neff"]
    u, w = k * a * math.sqrt(n1**2 - neff**2), k * a * math.sqrt(neff**2 - nc**2)

    def integral(fin, fout):
        return quad(fin, 0, a, epsabs=0, epsrel=1e-13, limit=200)[0] + quad(fout, a, np.inf, epsabs=0, epsrel=1e-13, limit=200)[0]

    p2 = integral(lambda x: (j0(u * x / a) / j0(u)) ** 2 * x, lambda x: (k0(w * x / a) / k0(w)) ** 2 * x)
    q = integral(lambda x: (u / a * j1(u * x / a) / j0(u)) ** 2 * x, lambda x: (w / a * k1(w * x / a) / k0(w)) ** 2 * x)
    p4 = integral(lambda x: (j0(u * x / a) / j0(u)) ** 4 * x, lambda x: (k0(w * x / a) / k0(w)) ** 4 * x)
    core = quad(lambda x: (j0(u * x / a) / j0(u)) ** 2 * x, 0, a, epsabs=0, epsrel=1e-13)[0]
    assert r["lp01"]["mfd_petermann2"] == pytest.approx(2 * math.sqrt(2) * math.sqrt(p2 / q), rel=1e-8)
    assert r["lp01"]["effective_area_um2"] == pytest.approx(2 * math.pi * p2 * p2 / p4, rel=1e-8)
    assert r["lp01"]["core_power_fraction"] == pytest.approx(core / p2, rel=1e-8)
    # dispersion from the exact LP eigenvalue on a different stencil
    exact_neff = lambda x: fibre_modes(x, a, silica(x) + dn, silica(x), vector=False)["lp_modes"][0]["neff"]  # noqa: E731
    for lam_k in (1.31, 1.55):
        row = _row(d, lam_k)
        D, ng = _D_of(exact_neff, row["wavelength_um"], 1e-3)
        assert row["D_ps_nm_km"] == pytest.approx(D, abs=2e-3)
        assert row["group_index"] == pytest.approx(ng, abs=1e-9)
        assert row["D_material_ps_nm_km"] == pytest.approx(_malitson_D(row["wavelength_um"]), abs=1e-4)
    lam0 = brentq(lambda x: _D_of(exact_neff, x, 1e-3)[0], 1.25, 1.35, xtol=1e-9)
    assert d["zero_dispersion_um"] == pytest.approx(lam0, abs=2e-5)
    assert d["cutoff_lp11_um"] == pytest.approx(lc, abs=1e-10) and not d["notes"]


def test_graded_multimode_fibre_example():
    p, body, r, _ = _run("fibre-graded")
    a, lam = 25.0, 0.85
    assert body["profile_kind"] == "graded" and body["alpha"] == 2.0 and body["na"] == 0.2
    nc = silica(lam)
    n1 = math.sqrt(nc**2 + 0.04)
    k = 2 * math.pi / lam
    V = k * a * 0.2
    assert r["v_number"] == pytest.approx(V, rel=1e-12) and r["n_core"] == pytest.approx(n1, abs=1e-14)
    for m in r["lp_modes"][:15]:
        M = 2 * (m["m"] - 1) + m["l"] + 1
        if M <= 5:
            assert m["neff"] == pytest.approx(math.sqrt(k * k * n1 * n1 - 2 * k * M * 0.2 / a) / k, abs=2e-11)
    assert r["mode_count"] == pytest.approx(V * V / 4, rel=0.03)
    assert r["lp01"]["mfd_petermann2"] == pytest.approx(2 * math.sqrt(2) * a / math.sqrt(V), rel=1e-8)
    assert r["lp01"]["effective_area_um2"] == pytest.approx(2 * math.pi * a * a / V, rel=1e-8)

    def edge(v):  # x psi'/psi + 1 at x = 1 for LP11 at cut-off
        A = 1.0 - v / 4.0
        return 2.0 - v + v * A * hyp1f1(A + 1.0, 3.0, v) / hyp1f1(A, 2.0, v)

    Vc = brentq(edge, 3.0, 4.0, xtol=1e-14)  # the first root (M(A, 2, V) has a zero near V = 4.7)
    assert Vc == pytest.approx(3.518, abs=5e-4)
    lc = r["cutoff_wavelength_um"]
    nc_c = silica(lc)
    dn = n1 - nc  # the profile keeps its index offset at every wavelength
    assert 2 * math.pi / lc * a * math.sqrt((nc_c + dn) ** 2 - nc_c**2) == pytest.approx(Vc, rel=1e-9)
    assert any("outside the data range of FUSED_SILICA" in n for n in r["notes"])


def test_trench_assisted_fibre_example():
    p, body, r, d = _run("fibre-trench")
    lam = 1.55
    assert body["profile_kind"] == "layers" and body["layers"] == FIBRE_TRENCH_RINGS
    prof = Profile("layers", 0.0, layers=tuple(tuple(x) for x in FIBRE_TRENCH_RINGS))
    nc = silica(lam)
    k = 2 * math.pi / lam
    fd = lp_modes(prof, lam, silica, method="fd")
    assert [m["name"] for m in r["lp_modes"]] == [m["name"] for m in fd] == ["LP01"]
    assert r["lp01"]["neff"] == pytest.approx(fd[0]["neff"], abs=2e-11)
    assert r["core_radius_um"] == 4.0 and r["v_number"] == pytest.approx(k * 4.0 * math.sqrt((nc + 0.005) ** 2 - nc**2), rel=1e-12)
    # field quantities from the finite-difference fields (two grids, Richardson) against the exact field
    _, r2, v2, r1, v1 = _fd_modes(prof, 0, k, nc)[0]
    mfd, a_eff, frac = (4.0 * _cell_properties(r2, v2, 4.0) - _cell_properties(r1, v1, 4.0)) / 3.0
    assert r["lp01"]["mfd_petermann2"] == pytest.approx(mfd, rel=2e-8)
    assert r["lp01"]["effective_area_um2"] == pytest.approx(a_eff, rel=2e-8)
    assert r["lp01"]["core_power_fraction"] == pytest.approx(frac, rel=2e-8)
    lc = r["cutoff_wavelength_um"]
    assert brentq(lambda x: _cut_shoot(prof, 1, x, silica), lc * 0.99, lc * 1.01, xtol=1e-14) == pytest.approx(lc, abs=1e-11)
    assert [m["name"] for m in lp_modes(prof, lc * 0.999, silica)] == ["LP01", "LP11"]
    assert [m["name"] for m in lp_modes(prof, lc * 1.001, silica)] == ["LP01"]
    # dispersion from finite-difference n_eff on a wider stencil
    fd_neff = lambda x: lp_modes(prof, x, silica, l_max=0, method="fd")[0]["neff"]  # noqa: E731
    row = _row(d, 1.55)
    D, ng = _D_of(fd_neff, row["wavelength_um"], 4e-3)
    assert row["D_ps_nm_km"] == pytest.approx(D, abs=0.02)
    assert row["group_index"] == pytest.approx(ng, abs=1e-8)


def test_microstructured_fibre_example_matches_the_multipole_method():
    p = get_sample("fibre-pcf")
    assert p.ui["open_view"] == "fiber2d"
    spec = dict(p.analysis_settings["fiber2d"])
    spec["wavelength_um"] = spec["wavelength_um"] or p.system.wavelengths[p.system.primary_wavelength].value
    assert spec["wavelength_um"] == 1.45
    job = client.post("/api/v1/wave/fiber2d/start", json=spec)
    assert job.status_code == 200, job.text
    jid = job.json()["job_id"]
    t0 = time.time()
    while True:
        s = client.get(f"/api/v1/wave/fiber2d/{jid}").json()
        if s["state"] in ("finished", "failed", "cancelled"):
            break
        assert time.time() - t0 < 900
        time.sleep(1.0)
    assert s["state"] == "finished", s.get("error")
    res = s["result"]
    best = res["modes"][res["best"]]
    assert res["mesh"]["refined"] and res["mesh"]["symmetry"] == ["pec", "pmc"]
    assert best["neff"] == pytest.approx(FIBRE_PCF_REFERENCE["neff"], abs=5e-7)
    assert best["kappa"] == pytest.approx(FIBRE_PCF_REFERENCE["kappa"], rel=0.02)
    assert best["loss_db_per_m"] == pytest.approx(20 / math.log(10) * 2 * math.pi / 1.45e-6 * best["kappa"], rel=1e-9)
    assert best["core_fraction"] > 0.9 and len(res["fields"]["x_um"]) <= 161


def test_the_frontend_fixture_holds_the_examples_requests():
    """lib/fibre.test.ts builds the requests from the same settings and must arrive at these."""
    import json

    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == collect(), "regenerate: python -m opticore.tools.fibre_examples --write"
