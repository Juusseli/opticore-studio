"""Coating analyses (coatanalysis.py): spectra, phase, GD/GDD, colour, field and profile.

Independent references:
* the field by plane-wave amplitudes per medium gives the same R and T as the characteristic matrix, and the layer
  absorptances sum to 1 - R - T (energy conservation);
* a bare interface: the standing wave in the incident medium is |1 + r exp(2 i k0 n0 z)|^2 with Fresnel's r, and the
  field in the substrate is |t|^2 = (2 n0 / (n0 + ns))^2;
* group delay of a vacuum gap d: d / c; of a Gires-Tournois interferometer (a spacer of index n1 on a perfect mirror):
  GD = -(n1 d / c) dphi/ddelta with phi = arg(r1 - z) - arg(1 - r1 z), z = exp(-2 i delta), in closed form;
* colour: a perfect reflector is the white point of D65 with L* = 100, a* = b* = 0; a flat reflectance R has
  L* = 116 R^(1/3) - 16 and the chromaticity of D65;
* a bare plate (incoherent back surface): T = 2n / (n^2 + 1) at normal incidence;
* psi = 0 at Brewster's angle; Delta = 0 at normal incidence (Macleod's convention, rp = rs there);
* an opaque metal: T = 0 and the field's substrate absorptance plus the layers' equals 1 - R.
"""

from __future__ import annotations

import cmath
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.coatanalysis import C_NM_PER_FS, Stack, _const, analyze, colour, field_profile, phase, profile, spectrum, stack_from_coating
from opticore.materials import MaterialLibrary
from opticore.thinfilm import COATINGS

c = _const
client = TestClient(app)


@pytest.mark.parametrize("pol", ["s", "p"])
@pytest.mark.parametrize("angle", [0.0, 35.0, 70.0])
def test_field_amplitudes_agree_with_the_matrix_and_conserve_energy(pol, angle):
    st = Stack([(c(2.3 - 0.05j), 60.0, "H"), (c(1.38), 110.0, "L"), (c(2.0 - 0.2j), 30.0, "M")], c(1.0), c(1.52))
    s = spectrum(st, np.array([550.0]), angle)
    f = field_profile(st, 550.0, angle, pol, 400)
    assert f["R"] == pytest.approx(s["R" + pol][0], abs=1e-12) and f["T"] == pytest.approx(s["T" + pol][0], abs=1e-12)
    assert sum(f["layer_absorptance"]) == pytest.approx(1 - s["R" + pol][0] - s["T" + pol][0], abs=1e-9)
    assert f["layer_absorptance"][1] == pytest.approx(0.0, abs=1e-15)  # the lossless layer absorbs nothing


def test_bare_interface_standing_wave():
    n0, ns, lam = 1.0, 1.5, 600.0
    f = field_profile(Stack([], c(n0), c(ns)), lam, 0.0, "s", outside_nm=300.0)
    r = (n0 - ns) / (n0 + ns)
    z = np.array(f["z_nm"])
    e2 = np.array(f["e2"])
    inc = z <= 0
    expected = np.abs(1 + r * np.exp(2j * 2 * math.pi * n0 * z[inc] / lam)) ** 2  # incident + reflected (physics sign)
    assert np.allclose(e2[inc], expected, atol=1e-12)
    assert np.allclose(e2[z > 0], (2 * n0 / (n0 + ns)) ** 2, atol=1e-12)


def test_group_delay_of_a_gap_and_of_a_gires_tournois_interferometer():
    gap = Stack([(c(1.0), 3000.0, "gap")], c(1.0), c(1.0))
    p = phase(gap, np.linspace(500, 600, 51))
    assert np.allclose(p["gd_ts"], 3000 / C_NM_PER_FS, rtol=1e-9) and np.abs(p["gdd_ts"]).max() < 1e-5  # stencil round-off
    n1, d = 2.0, 2500.0
    gti = Stack([(c(n1), d, "spacer")], c(1.0), c(1e-9 - 1e9j), opaque=True)  # a perfect mirror behind the spacer
    lam = np.linspace(780.0, 820.0, 4001)
    p = phase(gti, lam)
    r1 = (1.0 - n1) / (1.0 + n1)
    delta = 2 * math.pi * n1 * d / lam
    zz = np.exp(-2j * delta)
    dphi = np.imag(2j * zz / (r1 - zz)) - np.imag(2j * r1 * zz / (1 - r1 * zz))
    gd = -(n1 * d / C_NM_PER_FS) * dphi
    inner = slice(5, -5)
    assert np.allclose(p["gd_rs"][inner], gd[inner], rtol=2e-4, atol=1e-3)  # finite differences on the grid
    assert np.abs(np.abs(gd).max()) > 50  # the resonances of the interferometer are resolved
    assert np.all(np.isclose(np.abs(np.exp(1j * np.radians(p["phase_rs"]))), 1.0))


def test_colour_of_a_perfect_reflector_and_of_a_flat_reflectance():
    w = colour(Stack([], c(1.0), c(1e-9 - 1e9j), opaque=True))["R"]
    assert w["L"] == pytest.approx(100.0, abs=1e-6) and abs(w["a"]) < 1e-6 and abs(w["b"]) < 1e-6
    assert w["x"] == pytest.approx(0.312727, abs=2e-5) and w["y"] == pytest.approx(0.329023, abs=2e-5)  # D65 white
    R = 0.04
    ns = (1 + math.sqrt(R)) / (1 - math.sqrt(R))
    q = colour(Stack([], c(1.0), c(ns)))
    assert q["R"]["L"] == pytest.approx(116 * R ** (1 / 3) - 16, abs=1e-9) and q["Rv"] == pytest.approx(R, abs=1e-12)
    assert q["R"]["x"] == pytest.approx(w["x"], abs=1e-12) and q["Tv"] == pytest.approx(1 - R, abs=1e-12)


def test_bare_plate_and_ellipsometric_angles():
    n = 1.5
    plate = Stack([], c(1.0), c(n), back=True)
    s = spectrum(plate, np.array([550.0]))
    assert s["T"][0] == pytest.approx(2 * n / (n * n + 1), abs=1e-14) and s["R"][0] + s["T"][0] == pytest.approx(1.0, abs=1e-14)
    bare = Stack([], c(1.0), c(n))
    brewster = math.degrees(math.atan(n))
    lam = np.linspace(500, 600, 11)
    assert np.abs(phase(bare, lam, brewster)["psi"]).max() < 1e-6
    assert np.abs(phase(bare, lam, 0.0)["delta"]).max() < 1e-9


def test_opaque_metal_and_profile():
    st = Stack([(c(1.46), 100.0, "SiO2")], c(1.0), c(0.96 - 6.69j), opaque=True)
    s = spectrum(st, np.array([550.0]), 20.0)
    assert s["T"][0] == 0.0 and s["A"][0] == pytest.approx(1 - s["R"][0], abs=1e-15)
    f = field_profile(st, 550.0, 20.0, "p")
    assert f["substrate_absorptance"] + sum(f["layer_absorptance"]) == pytest.approx(1 - f["R"], abs=1e-9)
    pr = profile(Stack([(c(1.38), 550 / (4 * 1.38), "MgF2")], c(1.0), c(1.52)), 550.0)
    assert pr["layers"][0]["qwot"] == pytest.approx(1.0, abs=1e-12) and pr["total_nm"] == pytest.approx(550 / (4 * 1.38))


def test_dispersive_substrate_and_analysis_bundle():
    lib = MaterialLibrary()
    st = stack_from_coating(COATINGS["MGF2_QW550"], lib, 1.0, {"material": "N-BK7"})
    nb = lib.index("N-BK7", 0.55)
    nl = lib.index("MGF2_FILM", 0.55)  # the built-in is a quarter wave of the MgF2 film (k ~ 1e-17 there)
    R550 = ((nb - nl * nl) / (nb + nl * nl)) ** 2  # quarter wave on the glass at its index at 550 nm
    a = analyze(st, 400, 700, 301, 0.0, [30, 45], 550.0, (450, 650))
    assert a["at_reference"]["R"] == pytest.approx(R550, abs=1e-12)
    assert len(a["angles"]) == 2 and a["band"]["R"]["max"] >= a["band"]["R"]["mean"] >= a["band"]["R"]["min"]
    assert a["angle_curve"]["R"][0] == pytest.approx(R550, abs=1e-12)


def test_analyze_endpoints():
    r = client.post("/api/v1/coatings/analyze", json={"name": "HR_1064", "lambda_min_nm": 900, "lambda_max_nm": 1250, "reference_nm": 1064})
    assert r.status_code == 200 and r.json()["at_reference"]["R"] > 0.9999
    assert client.post("/api/v1/coatings/analyze", json={"name": "NOPE"}).json()["error"]["code"] == "COATING"
    d = {"palette": [{"key": "H", "index": 2.35}, {"key": "L", "index": 1.46}], "layers": [{"material": "H", "thickness_nm": 58}, {"material": "L", "thickness_nm": 94}]}
    j = client.post("/api/v1/coating-design/analyze", json={"design": d, "reference_nm": 550}).json()
    # deposition order: H on the substrate, L faces the air -> the stack from the incident side is L, H
    st = Stack([(c(1.46), 94.0, "L"), (c(2.35), 58.0, "H")], c(1.0), c(cmath.sqrt(1.5168**2)))
    assert j["profile"]["layers"][0]["n"] == pytest.approx(1.46) and j["profile"]["layers"][1]["n"] == pytest.approx(2.35)
    assert j["at_reference"]["R"] == pytest.approx(spectrum(st, np.array([j["reference_nm"]]))["R"][0], abs=2e-3)  # N-BK7 vs 1.5168


def test_phase_is_undefined_where_the_amplitude_vanishes():
    """At Brewster's angle of a bare interface rp = 0: its phase, GD and GDD are undefined (NaN, null in the API)
    while those of rs (a real, negative r: phase 180 deg, no delay) stay finite."""
    lam = np.linspace(500.0, 600.0, 21)
    brewster = math.degrees(math.atan(1.5))
    p = phase(Stack([], c(1.0), c(1.5)), lam, brewster)
    assert np.all(np.isnan(p["phase_rp"])) and np.all(np.isnan(p["gd_rp"])) and np.all(np.isnan(p["gdd_rp"]))
    assert np.allclose(np.abs(p["phase_rs"]), 180.0, atol=1e-9) and np.abs(p["gd_rs"]).max() < 1e-12
    r = TestClient(app).post("/api/v1/coatings/analyze", json={"name": "MGF2_QW550", "substrate_index": 1.5, "lambda_min_nm": 500, "lambda_max_nm": 600, "angle_deg": brewster, "field_pol": "p"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["phase_min_power"] == 1e-3 and all(v is None or math.isfinite(v) for v in j["phase"]["gdd_rp"])


def test_colour_swatch_is_the_hue_at_full_brightness():
    """The swatch of a dim reflection (a broadband AR, Rv ~ 0.1 %) is its hue normalised to the brightest channel, and
    a spectrally flat reflection is white whatever its level."""
    co = COATINGS["BBAR_VIS"]
    st = Stack([(c(complex(L.index, -L.extinction)), L.thickness_nm, "") for L in co.layers], c(1.0), c(1.52))
    col = colour(st)
    assert col["R"]["Y"] < 0.005 and max(col["R"]["srgb"]) == pytest.approx(1.0, abs=1e-12)
    flat = colour(Stack([], c(1.0), c(1.5)))  # 4 %, no dispersion: the illuminant's own chromaticity
    assert flat["R"]["srgb"] == pytest.approx([1.0, 1.0, 1.0], abs=2e-3)
