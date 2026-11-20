"""Rotationally symmetric 3D FDTD (wave/fdtd_bor.py, body of revolution m = 1) and its coupling to
the physical-optics propagation.

References: the planar solver (fdtd.py, an independent set of update equations) for a dielectric
half space, the Fresnel reflectance at the LP01 effective index for a fibre facet (the 3D cylinder,
not a slab), energy conservation, and the analytic LP01 far field for the exported field. Like the
planar solver, the facet reflectance depends on where the interface falls within a cell (about
+-10 % in R at 12 points per wavelength)."""

from __future__ import annotations

import math
import time

import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.model import OpticalSystem
from opticore.system import compile_system
from opticore.wave.fdtd import FdtdError, Shape, Spec, run, spec_from_dict
from opticore.wave.fdtd_bor import run_bor
from opticore.wave.fibermodes import fibre_modes
from opticore.wave.pop import physical_optics

LAM = 1.55
A, N2 = 4.1, 1.444
N1 = math.sqrt(N2 * N2 + 0.12**2)


def test_half_space_matches_the_planar_solver_and_fresnel():
    """A wide Gaussian beam onto glass: R as the planar plane-wave run on the same grid (the cell
    position of the interface is the same), within 6 % of Fresnel, R + T = 1."""
    half = [Shape(kind="rectangle", n=1.5, z0=6.0, z1=100, y0=-100, y1=100)]
    common = dict(wavelength=LAM, size_z=12.0, shapes=half, z_source=1.0, z_reflection=2.0, z_transmission=10.0, ppw=12)
    rb = run_bor(Spec(size_y=36.0, geometry="axisymmetric", source="gaussian", waist=6.0, focus_z=6.0, **common))
    rp = run(Spec(size_y=0.1, polarization="s", periodic_y=True, **common))
    assert rb["geometry"] == "axisymmetric"
    assert rb["R"] == pytest.approx(rp["R"], abs=3e-4)
    assert rb["R"] == pytest.approx(0.04, rel=0.06)
    assert rb["R"] + rb["T"] == pytest.approx(1.0, abs=1e-4)


def test_fibre_facet_and_its_field_as_a_pop_source():
    """Cleaved step-index fibre (3D cylinder) into air: R about Fresnel at n_eff of LP01; the
    co-polarised transmitted field, handed to POP 9 um after the facet, spreads like the analytic
    LP01 far field and carries the transmitted power."""
    clad = lambda z1: Shape(kind="rectangle", n=N2, z0=-50, z1=z1, y0=-100, y1=100)  # noqa: E731
    core = lambda z1: Shape(kind="rectangle", n=N1, z0=-50, z1=z1, y0=-A, y1=A)  # noqa: E731
    sp = Spec(
        wavelength=LAM, size_z=22, size_y=28, geometry="axisymmetric", shapes=[clad(10.0), core(10.0)], reference_shapes=[clad(1e3), core(1e3)],
        source="mode", mode_half_width=A, mode_n_core=N1, mode_n_clad=N2, z_source=2.0, z_reflection=5.0, z_transmission=19.0, ppw=12,
    )
    r = run_bor(sp)
    neff = fibre_modes(LAM, A, N1, N2, vector=False, profiles=0)["lp_modes"][0]["neff"]
    assert r["R"] == pytest.approx(((neff - 1) / (neff + 1)) ** 2, abs=0.006)
    assert r["R"] + r["T"] == pytest.approx(1.0, abs=3e-3)
    ef = r["exported_field"]
    assert ef["depolarised_fraction"] < 0.01
    assert ef["power"] == pytest.approx(r["T"] * (1 - ef["depolarised_fraction"]), rel=1e-9)
    cs = compile_system(
        OpticalSystem.model_validate(
            {
                "surfaces": [{"id": "o", "thickness": 1.0}, {"id": "s", "thickness": 0.0, "semi_diameter": 2, "semi_diameter_mode": "fixed", "is_stop": True}, {"id": "i"}],
                "wavelengths": [{"value": LAM}],
                "field_type": "object_height",
                "fields": [{"y": 0}],
                "aperture": {"type": "object_na", "value": 0.1},
            }
        )
    )
    src = {"kind": "field", "r_um": ef["r_um"], "re": ef["re"], "im": ef["im"], "plane_offset_mm": 9e-3, "power": ef["power"], "wavelength_um": LAM, "n_medium": ef["n_medium"]}
    rf = physical_optics(cs, src)
    rm = physical_optics(cs, {"kind": "fibre", "core_radius_um": A, "n_core": N1, "n_clad": N2})
    assert rf["target"]["d4sigma_mm"][0] == pytest.approx(rm["target"]["d4sigma_mm"][0], rel=3e-3)
    assert rf["target"]["power"] == pytest.approx(ef["power"], rel=2e-3)
    from opticore.system import SystemError_

    with pytest.raises(SystemError_, match="medium of index"):
        physical_optics(cs, {**src, "n_medium": 1.45})
    with pytest.raises(SystemError_, match="um, the propagation wavelength"):
        physical_optics(cs, {**src, "wavelength_um": 1.31})


def test_validation_and_api():
    base = dict(wavelength=LAM, size_z=6.0, size_y=6.0, geometry="axisymmetric", source="gaussian", waist=1.5, ppw=8)
    with pytest.raises(FdtdError, match="tilted"):
        run_bor(Spec(**base, tilt_deg=5.0))
    with pytest.raises(FdtdError, match="axis"):
        run_bor(Spec(**base, focus_y=0.5))
    with pytest.raises(FdtdError, match="Gaussian-beam or fibre-mode"):
        run_bor(Spec(**{**base, "source": "plane"}))
    with pytest.raises(FdtdError, match="geometry"):
        spec_from_dict({"wavelength_um": 1.0, "size_z_um": 4, "size_y_um": 4, "geometry": "spherical"})
    client = TestClient(app)
    body = {"geometry": "axisymmetric", "wavelength_um": LAM, "size_z_um": 6.0, "size_y_um": 6.0, "source": "gaussian", "waist_um": 1.5, "focus_z_um": 3.0, "points_per_wavelength": 8, "shapes": [{"kind": "rectangle", "n": 1.5, "z0": 3.0, "z1": 100, "y0": -50, "y1": 50}]}
    j = client.post("/api/v1/wave/fdtd/start", json=body)
    assert j.status_code == 200, j.text
    for _ in range(400):
        s = client.get(f"/api/v1/wave/fdtd/{j.json()['job_id']}").json()
        if s["state"] in ("finished", "failed", "cancelled"):
            break
        time.sleep(0.05)
    assert s["state"] == "finished", s
    res = s["result"]
    assert res["geometry"] == "axisymmetric" and "exported_field" in res
    assert len(res["y_um"]) == len(res["intensity"]) and len(res["z_um"]) == len(res["intensity"][0])
    assert client.post("/api/v1/wave/fdtd/start", json={**body, "source": "plane"}).status_code == 422
    assert client.post("/api/v1/wave/fdtd/start", json={**body, "size_z_um": 1e5}).status_code == 422
