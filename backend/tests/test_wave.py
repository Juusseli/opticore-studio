"""Wave optics: step-index fibre modes from Maxwell's equations (wave/fibermodes.py) and
physical-optics propagation through the system (wave/pop.py).

References: the Bessel-function zeros and cut-offs of step-index fibres (Snyder & Love), the
weak-guidance (LP) limit of the exact vector modes, the TE01 > HE21 > TM01 order, Marcuse's
Gaussian approximation of the LP01 field, the exact propagation of Gaussian beams (complex beam
parameter, independently implemented in analysis/gaussian.py) and the closed-form overlap of
Gaussian modes (waist, offset and curvature mismatch)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.special import jn_zeros, jv, jvp, kv, kvp

from opticore.model import OpticalSystem
from opticore.system import SystemError_, compile_system
from opticore.wave.fibermodes import J01, fibre_modes, lp_equation
from opticore.wave.pop import gaussian_q, physical_optics

SMF = {"core_radius_um": 4.1, "n_core": 1.4557, "n_clad": 1.4504}


def _vector_residual(kind, nu, u, V, delta):
    """Snitzer's equation in its original (unmultiplied) form."""
    w = math.sqrt(V * V - u * u)
    xi = jvp(nu, u) / (u * jv(nu, u))
    kap = kvp(nu, w) / (w * kv(nu, w))
    if kind == "TE":
        return xi + kap
    if kind == "TM":
        return xi + delta * kap
    return (xi + kap) * (xi + delta * kap) - nu * nu * (1 / u**2 + 1 / w**2) * (1 / u**2 + delta / w**2)


def test_lp_modes_cutoffs_and_counts():
    a, n2 = 4.1, 1.4504
    for V in (2.3, 2.5):
        na = V * 1.55 / (2 * math.pi * a)
        r = fibre_modes(1.55, a, math.sqrt(n2 * n2 + na * na), n2)
        names = [m["name"] for m in r["lp_modes"]]
        assert r["v_number"] == pytest.approx(V, rel=1e-12)
        assert ("LP11" in names) == (V > J01) and r["single_mode"] == (V < J01)
        for m in r["lp_modes"]:
            assert n2 < m["neff"] < r["n_core"]
            assert abs(lp_equation(m["l"], V)(np.array([m["u"]]))[0]) < 1e-9
    assert J01 == pytest.approx(float(jn_zeros(0, 1)[0]), abs=1e-15)
    # cut-off wavelength: V = 2.404826 there
    r = fibre_modes(1.55, a, **{k: SMF[k] for k in ("n_core", "n_clad")})
    lc = r["cutoff_wavelength_um"]
    assert fibre_modes(lc * 1.001, a, SMF["n_core"], SMF["n_clad"])["single_mode"]
    assert not fibre_modes(lc * 0.999, a, SMF["n_core"], SMF["n_clad"])["single_mode"]


def test_vector_modes_solve_maxwell_and_reduce_to_lp():
    r = fibre_modes(0.8, 4.1, SMF["n_core"], SMF["n_clad"])  # V = 4.0: LP01, LP11, LP21, LP02
    V = r["v_number"]
    delta = (SMF["n_clad"] / SMF["n_core"]) ** 2
    vec = {m["name"]: m for m in r["vector_modes"]}
    lp = {m["name"]: m for m in r["lp_modes"]}
    for m in r["vector_modes"]:
        assert abs(_vector_residual(m["kind"], m["nu"], m["u"], V, delta)) < 1e-7 * (1 + abs(jvp(m["nu"], m["u"]) / (m["u"] * jv(m["nu"], m["u"]))) ** 2)
    dn = SMF["n_core"] - SMF["n_clad"]
    assert abs(vec["HE11"]["neff"] - lp["LP01"]["neff"]) < 1e-3 * dn
    # LP11 = TE01 + TM01 + HE21 (polarisation splitting of order delta^2), TE01 > HE21 > TM01
    for k in ("TE01", "HE21", "TM01"):
        assert abs(vec[k]["neff"] - lp["LP11"]["neff"]) < 1e-3 * dn
    assert vec["TE01"]["neff"] > vec["HE21"]["neff"] > vec["TM01"]["neff"]
    assert sum(m["degeneracy"] for m in r["vector_modes"]) == r["mode_count"] == 12
    # TE01 / TM01 cut off exactly at the first zero of J0
    na = 2.40 * 1.55 / (2 * math.pi * 4.1)
    below = fibre_modes(1.55, 4.1, math.sqrt(1.45**2 + na * na), 1.45)
    assert [m["name"] for m in below["vector_modes"]] == ["HE11"]
    # strongly guiding glass rod in air: the exact HE11 differs from LP01 but solves Snitzer's equation
    rod = fibre_modes(1.0, 0.4, 1.5, 1.0)
    he = next(m for m in rod["vector_modes"] if m["name"] == "HE11")
    assert abs(_vector_residual("HE", 1, he["u"], rod["v_number"], 1 / 2.25)) < 1e-6
    assert abs(he["neff"] - rod["lp_modes"][0]["neff"]) > 1e-3


def test_lp01_mode_field_diameters():
    for V in (1.6, 2.0, 2.4):
        na = V * 1.55 / (2 * math.pi * 4.1)
        r = fibre_modes(1.55, 4.1, math.sqrt(1.4504**2 + na * na), 1.4504)["lp01"]
        # Marcuse's formula approximates the best-fitting Gaussian (about 1 % for 1.2 < V < 2.4)
        assert 2 * r["gaussian_waist"] == pytest.approx(r["marcuse_mfd"], rel=0.015)
        assert r["gaussian_overlap"] > (0.97 if V < 2 else 0.99)  # exponential cladding tails at low V
        assert 0.9 < r["mfd_petermann2"] / (2 * r["gaussian_waist"]) <= 1.0


# ---------------------------------------------------------------------------- POP
def _free(d0, d1, lam=1.55):
    return compile_system(
        OpticalSystem.model_validate(
            {
                "surfaces": [{"id": "o", "thickness": d0}, {"id": "a", "thickness": d1, "semi_diameter": 5, "semi_diameter_mode": "fixed", "is_stop": True}, {"id": "i"}],
                "wavelengths": [{"value": lam}],
                "field_type": "object_height",
                "fields": [{"y": 0}],
                "aperture": {"type": "object_na", "value": 0.1},
            }
        )
    )


# The far-field case uses a slow beam (theta = 0.025 rad): for theta ~ 0.1 the exact (non-paraxial)
# Rayleigh-Sommerfeld field that POP computes is ~theta^2 / 2 wider than the paraxial w(z) formula.
@pytest.mark.parametrize("w0,d0,d1,tol,regime", [(0.02, 20.0, 5.0, 5e-4, "far field"), (0.05, 5.0, 20.0, 3e-4, "angular spectrum"), (0.2, 1.0, 100.0, 3e-4, "angular spectrum"), (0.0052, 1.0, 2.0, 5e-3, "Fresnel")])
def test_free_space_gaussian_propagation(w0, d0, d1, tol, regime):
    r = physical_optics(_free(d0, d1), {"kind": "gaussian", "waist_x": w0})
    assert regime in r["entry"]["method"]
    w = gaussian_q(w0, d0 + d1, 1.55e-3)[0]
    assert r["target"]["d4sigma_mm"][0] == pytest.approx(2 * w, rel=tol)
    assert r["target"]["d4sigma_mm"][1] == pytest.approx(2 * w, rel=tol)
    assert r["target"]["power"] == pytest.approx(1.0, abs=2e-3)


def _ideal(f=50.0, lam=1.0):
    return compile_system(
        OpticalSystem.model_validate(
            {
                "surfaces": [{"id": "o", "thickness": None}, {"id": "L", "type": "ideal", "focal_length": f, "thickness": f, "semi_diameter": 3, "semi_diameter_mode": "fixed", "is_stop": True}, {"id": "i"}],
                "wavelengths": [{"value": lam}],
                "fields": [{"y": 0}],
                "aperture": {"type": "epd", "value": 2.0},
            }
        )
    )


def test_focusing_by_an_ideal_lens_and_gaussian_coupling():
    f, w, lam = 50.0, 0.5, 1e-3
    cs = _ideal(f)
    # exact Gaussian beam behind the lens (q-parameter): waist and its position
    zR = math.pi * w * w / lam
    q1 = 1 / (1 / complex(0, zR) - 1 / f)  # q just after the lens
    z_w = -q1.real  # waist distance behind the lens
    w0 = math.sqrt(lam * q1.imag / math.pi)

    def w_at(z):
        return gaussian_q(w0, z - z_w, lam)[:2]

    r = physical_optics(cs, {"kind": "gaussian", "waist_x": w})
    wf, Rf = w_at(f)
    assert r["target"]["d4sigma_mm"][0] == pytest.approx(2 * wf, rel=1e-3)
    zRf = math.pi * w0 * w0 / lam
    r = physical_optics(cs, {"kind": "gaussian", "waist_x": w}, target_offset=zRf)
    assert r["target"]["d4sigma_mm"][0] == pytest.approx(2 * w_at(f + zRf)[0], rel=1e-3)
    # coupling at the focal plane: the beam there has radius wf and curvature Rf
    for wm, d in ((wf, 0.0), (2 * wf, 0.0)):
        r = physical_optics(cs, {"kind": "gaussian", "waist_x": w}, target_mode={"kind": "gaussian", "waist": wm, "decenter": [d, 0.0]})
        eta = 4 / ((wf / wm + wm / wf) ** 2 + (math.pi * wf * wm / (lam * Rf)) ** 2)
        assert r["coupling"]["efficiency"] == pytest.approx(eta, abs=1e-3)
    # lateral offset of a matched mode: exp(-d^2 / w^2) (curvature term negligible here)
    r = physical_optics(cs, {"kind": "gaussian", "waist_x": w}, target_mode={"kind": "gaussian", "waist": wf, "decenter": [wf, 0.0]})
    assert r["coupling"]["efficiency"] == pytest.approx(math.exp(-1.0), abs=2e-3)


def test_fibre_to_fibre_imaging():
    """4f relay with ideal lenses: the LP01 mode is imaged onto an identical fibre (eta -> 1); with
    magnification m the Gaussian overlap is (2m / (1 + m^2))^2."""
    fib = {"kind": "fibre", **SMF}
    for f2, m in ((10.0, 1.0), (15.0, 1.5)):
        cs = compile_system(
            OpticalSystem.model_validate(
                {
                    "surfaces": [
                        {"id": "o", "thickness": 10.0},
                        {"id": "L1", "type": "ideal", "focal_length": 10.0, "ideal_object_distance": 10.0, "thickness": 5.0, "semi_diameter": 3, "semi_diameter_mode": "fixed", "is_stop": True},
                        {"id": "L2", "type": "ideal", "focal_length": f2, "thickness": f2, "semi_diameter": 3, "semi_diameter_mode": "fixed"},
                        {"id": "i"},
                    ],
                    "wavelengths": [{"value": 1.55}],
                    "field_type": "object_height",
                    "fields": [{"y": 0}],
                    "aperture": {"type": "object_na", "value": 0.1},
                }
            )
        )
        rg = physical_optics(cs, {"kind": "gaussian", "waist_x": 0.005}, target_mode={"kind": "gaussian", "waist": 0.005})
        # paraxial Gaussian overlap; at NA 0.1 the exact propagation differs by O(NA^2) (the imaged
        # waist of the m = 1.5 relay is 0.28 % below m w0, converged in the exit sampling)
        assert rg["coupling"]["efficiency"] == pytest.approx((2 * m / (1 + m * m)) ** 2, abs=3e-3)
        assert rg["target"]["d4sigma_mm"][0] == pytest.approx(2 * m * 0.005, rel=6e-3)
        # Debye only where the full converging field cannot be sampled for the exact angular spectrum
        assert ("Debye" if m == 1.0 else "exact angular spectrum") in rg["exit"]["propagation"]
        if m == 1.0:
            rf = physical_optics(cs, fib, target_mode=fib)
            assert rf["coupling"]["efficiency"] > 0.997
            assert rf["source"]["single_mode"]


def test_thick_lens_beam_agrees_with_the_ray_ensemble():
    """Gaussian beam (5.2 um waist) through a strongly curved N-SF11 lens (tests/beam_systems.py): the
    wave D4sigma and the power on the detector agree with the direct-path ray ensemble, whose second
    moments are those of the Wigner function."""
    from opticore.nsdirect import trace_direct

    from .beam_systems import thick_lens

    p = thick_lens()
    cs = compile_system(p.system, p.custom_materials)
    r = physical_optics(cs, {"kind": "gaussian", "waist_x": 0.0052}, detector_radius=0.2)
    d = trace_direct(cs, p.sources, p.detectors)["detectors"][0]
    assert r["target"]["d4sigma_mm"][0] == pytest.approx(2 * 0.5 * sum(d["plane"]["width_2sigma_mm"]), rel=0.03)
    assert r["target"]["power_in_radius"] == pytest.approx(d["fraction"], abs=2e-3)
    assert "far field" in r["entry"]["method"]


def test_pop_rejects_unsupported_systems():
    from opticore.samples import get_sample

    with pytest.raises(SystemError_, match="axial refracting"):
        physical_optics(compile_system(get_sample("spherical-mirror").system), {"kind": "gaussian", "waist_x": 1.0})
    with pytest.raises(SystemError_, match="infinity"):
        physical_optics(_ideal(), {"kind": "fibre", **SMF})


def test_wave_api():
    from fastapi.testclient import TestClient

    from opticore.api.main import app

    from .beam_systems import thick_lens

    c = TestClient(app)
    r = c.post("/api/v1/wave/fiber_modes", json={"wavelength_um": 1.55, "core_radius_um": 4.1, "na": 0.124, "clad_material": "FUSED_SILICA"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["single_mode"] and d["lp_modes"][0]["name"] == "LP01" and d["vector_modes"][0]["name"] == "HE11"
    assert c.post("/api/v1/wave/fiber_modes", json={"wavelength_um": 1.55, "core_radius_um": 4.1, "n_core": 1.44, "n_clad": 1.45}).status_code == 422
    p = thick_lens()
    body = {"system": p.system.model_dump(), "custom_materials": p.custom_materials, "source": {"kind": "fibre", **SMF}, "detector_radius": 0.2, "target_mode": {"kind": "gaussian", "waist": 0.06}}
    r = c.post("/api/v1/analysis/pop", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert 0.9 < d["target"]["power_in_radius"] <= 1.0 and 0 < d["coupling"]["efficiency"] <= 1.0
    assert len(d["target"]["irradiance"]) == 128
    assert c.post("/api/v1/analysis/pop", json={**body, "source": {"kind": "fibre"}}).status_code == 422


def test_pop_side_view_of_a_thick_lens():
    """The side view follows the beam from the source (a few um) through the lens to the detector; its
    width on the meridional cut at the target equals that of the target plane's own meridional cut
    (not half its D4sigma: the converging, aberrated spot is not Gaussian, and a cut through its
    centre differs from the marginal second moment)."""
    from .beam_systems import thick_lens

    p = thick_lens()
    cs = compile_system(p.system, p.custom_materials)
    r = physical_optics(cs, {"kind": "gaussian", "waist_x": 0.0052}, side_view=True)
    sv = r["side"]
    z, y, M = np.array(sv["z"]), np.array(sv["y"]), np.array(sv["irradiance"])
    assert M.shape == (len(y), len(z)) and np.all(np.diff(z) >= -1e-12)
    assert [g["kind"] for g in sv["regions"]] == ["wave", "geometric", "wave"]
    assert "angular spectrum" in sv["regions"][2]["method"]

    def width(j):
        c = M[:, j]
        return 2 * math.sqrt((c * y * y).sum() / c.sum())

    assert width(0) < 0.02  # next to the fibre end (5.2 um waist, binned on the rows)
    t = r["target"]
    prof, yt = np.array(t["profile_y"]), np.array(t["y"])
    assert width(len(z) - 1) == pytest.approx(2 * math.sqrt((prof * yt * yt).sum() / prof.sum()), rel=0.01)
    j_e = int(np.argmin(np.abs(z - sv["entry_z"])))
    assert width(j_e - 1) == pytest.approx(2 * gaussian_q(0.0052, -sv["source_z"], 1.55e-3)[0] / 2, rel=0.05)
