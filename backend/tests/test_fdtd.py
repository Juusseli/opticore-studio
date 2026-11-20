"""2D FDTD Maxwell solver (wave/fdtd.py).

References: Fresnel reflectance of an interface, the transfer-matrix (Airy) reflectance and
transmittance of single layers, also absorbing ones (thinfilm.py, an independent implementation),
energy conservation, total internal reflection and the 2D Gaussian-beam width law. Tolerances
reflect the second-order Yee scheme at 30 points per wavelength (interface position within a
cell: about 1 % in R)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.api.main import app
from opticore.thinfilm import Layer, stack_rt
from opticore.wave.fdtd import FdtdError, Shape, Spec, run, spec_from_dict

client = TestClient(app)


def _slab(pol, n, k=0.0, d=100.0, ppw=30):
    sp = Spec(wavelength=1.0, size_z=6.0, size_y=0.1, polarization=pol, shapes=[Shape(kind="rectangle", n=n, k=k, z0=3.0, z1=3.0 + d, y0=-50, y1=50)], periodic_y=True, ppw=ppw)
    return run(sp)


@pytest.mark.parametrize("pol", ["s", "p"])
def test_interface_and_layers_match_fresnel_and_transfer_matrix(pol):
    # half-space n = 1.5 (into the PML): R = ((n - 1) / (n + 1))^2
    r = _slab(pol, 1.5)
    assert r["R"] == pytest.approx(0.04, abs=1.5e-3)
    assert r["R"] + r["T"] == pytest.approx(1.0, abs=1e-4)
    assert r["convergence"] < 1e-3
    for n, k, d in ((2.0, 0.0, 0.37), (1.5, 0.02, 1.0)):
        ref = stack_rt(1.0, 1.0, (Layer(index=n, thickness_nm=d * 1000, extinction=k),), 1.0, np.array([1.0]))
        r = _slab(pol, n, k, d)
        assert r["R"] == pytest.approx(float(ref["Rs"][0]), abs=4e-3)
        assert r["T"] == pytest.approx(float(ref["Ts"][0]), abs=4e-3)
        assert r["A"] == pytest.approx(float(ref["As"][0]), abs=4e-3)


def test_resolution_convergence():
    errs = [abs(_slab("s", 1.5, ppw=p)["R"] - 0.04) for p in (15, 60)]
    assert errs[1] < errs[0] / 2


def test_oblique_gaussian_beam_fresnel_and_total_internal_reflection():
    n1 = 1.5

    def beam(tilt, width):
        sp = Spec(wavelength=1.0, size_z=8.0, size_y=width, polarization="s", n_background=n1, shapes=[Shape(kind="rectangle", n=1.0, z0=4.0, z1=100, y0=-100, y1=100)], source="gaussian", waist=2.5, focus_z=4.0, tilt_deg=tilt, periodic_y=False, z_source=0.8, z_reflection=1.2, z_transmission=6.0, ppw=14)
        return run(sp)

    th = math.radians(30)
    ct = math.sqrt(1 - (n1 * math.sin(th)) ** 2)
    rs = (n1 * math.cos(th) - ct) / (n1 * math.cos(th) + ct)
    r = beam(30.0, 12.0)
    assert r["R"] == pytest.approx(rs * rs, abs=4e-3)
    # beyond the critical angle (41.8 deg) nothing crosses the transmission monitor
    assert beam(50.0, 18.0)["T"] < 0.01


def test_gaussian_beam_width_law():
    sp = Spec(wavelength=1.0, size_z=24.0, size_y=16.0, polarization="s", source="gaussian", waist=3.0, focus_z=2.0, periodic_y=False, reference=False, ppw=12, map_cells=4000)
    r = run(sp)
    z, y, I = np.array(r["z_um"]), np.array(r["y_um"]), np.array(r["intensity"])
    zR = math.pi * 9.0 / 1.0
    for zz in (2.0, 20.0):
        col = I[:, int(np.argmin(abs(z - zz)))]
        m = (col * y).sum() / col.sum()
        w = 2 * math.sqrt((col * (y - m) ** 2).sum() / col.sum())
        assert w == pytest.approx(3.0 * math.sqrt(1 + ((zz - 2.0) / zR) ** 2), rel=0.02)


def test_validation_and_api():
    # a metal (Re eps < 0) is a dispersive medium (Drude current, tests/test_fdtd_metals.py): Fresnel at normal incidence
    N = complex(0.2, 3.0)
    assert _slab("s", 0.2, 3.0)["R"] == pytest.approx(abs((1 - N) / (1 + N)) ** 2, abs=2e-3)
    with pytest.raises(FdtdError, match="Bloch"):
        run(Spec(wavelength=1.0, size_z=4.0, size_y=1.0, source="plane", tilt_deg=10.0))
    sp = spec_from_dict({"wavelength_um": 1.0, "size_z_um": 6.0, "size_y_um": 0.1, "shapes": [{"kind": "rectangle", "material": "N-BK7", "z0": 3.0, "z1": 100, "y0": -50, "y1": 50}]}, index_of=lambda name, lam: 1.5)
    assert sp.shapes[0].n == 1.5 and sp.periodic_y
    body = {"wavelength_um": 1.0, "size_z_um": 6.0, "size_y_um": 0.1, "points_per_wavelength": 20, "shapes": [{"kind": "rectangle", "n": 1.5, "z0": 3.0, "z1": 100, "y0": -50, "y1": 50}]}
    j = client.post("/api/v1/wave/fdtd/start", json=body)
    assert j.status_code == 200, j.text
    jid = j.json()["job_id"]
    import time

    for _ in range(200):
        s = client.get(f"/api/v1/wave/fdtd/{jid}").json()
        if s["state"] in ("finished", "failed", "cancelled"):
            break
        time.sleep(0.05)
    assert s["state"] == "finished", s
    assert s["result"]["R"] == pytest.approx(0.04, abs=3e-3)
    assert client.post("/api/v1/wave/fdtd/start", json={**body, "size_z_um": 1e5}).status_code == 422


def test_maps_and_axes_have_matching_sizes():
    r = run(Spec(wavelength=1.0, size_z=8.0, size_y=0.2, shapes=[Shape(kind="rectangle", n=1.5, z0=3, z1=4, y0=-50, y1=50)], map_cells=240))
    for k in ("intensity", "field", "index"):
        a = np.array(r[k])
        assert a.shape == (len(r["y_um"]), len(r["z_um"])), k


def test_slab_mode_and_fibre_facet_reflectance():
    """The guided slab mode solves its eigenvalue equation (TE: u tan u = w); a facet of the 2D fibre
    model reflects about the plane-wave Fresnel value at n_eff, an MgF2 quarter wave lowers it.
    The reference run is the endless fibre, so R is the power reflected back into the fibre."""
    from opticore.wave.fdtd import slab_mode, slab_mode_neff

    lam, a, n2 = 1.55, 4.1, 1.444
    n1 = math.sqrt(n2 * n2 + 0.12**2)
    neff = slab_mode_neff(a, n1, n2, lam, "s")
    u = a * math.sqrt((2 * math.pi / lam) ** 2 * (n1 * n1 - neff * neff))
    w = a * math.sqrt((2 * math.pi / lam) ** 2 * (neff * neff - n2 * n2))
    assert u * math.tan(u) == pytest.approx(w, rel=1e-9)
    f = slab_mode(np.array([0.0, a, 2 * a]), a, n1, n2, lam)
    assert f[0] == 1.0 and f[1] == pytest.approx(math.cos(u), rel=1e-12) and f[2] == pytest.approx(math.cos(u) * math.exp(-w), rel=1e-12)

    def facet(ar):
        clad = lambda z1: Shape(kind="rectangle", n=n2, z0=-50, z1=z1, y0=-100, y1=100)  # noqa: E731
        core = lambda z1: Shape(kind="rectangle", n=n1, z0=-50, z1=z1, y0=-a, y1=a)  # noqa: E731
        shapes = [clad(10.0), core(10.0)] + ([Shape(kind="rectangle", n=1.38, z0=10.0, z1=10.0 + lam / (4 * 1.38), y0=-100, y1=100)] if ar else [])
        sp = Spec(wavelength=lam, size_z=22, size_y=22, polarization="s", shapes=shapes, reference_shapes=[clad(1e3), core(1e3)], source="mode", mode_half_width=a, mode_n_core=n1, mode_n_clad=n2, z_source=2.0, z_reflection=5.0, z_transmission=19.0, periodic_y=False, ppw=10)
        return run(sp)

    bare = facet(False)
    assert bare["R"] == pytest.approx(((neff - 1) / (neff + 1)) ** 2, abs=0.008)
    assert bare["R"] + bare["T"] == pytest.approx(1.0, abs=0.015)
    assert facet(True)["R"] < 0.7 * bare["R"]
