"""Dispersive metals in the 2D FDTD (wave/fdtd.py): a Drude current fitted to eps at the source frequency, the surface
plasmon source and the fitted propagation constant of guided fields; the plasmonics example of the library.

References (independent of the solver):
* Fresnel reflectance of a metal half-space at normal incidence, |(1 - N) / (1 + N)|^2, s and p;
* the transfer matrix of thin silver and gold films on glass (thinfilm.py), converging with the resolution;
* the discrete Drude medium reproduces the target permittivity exactly (its z-transform response);
* the dielectric slab waveguide's TE and TM effective indices (the eigenvalue equations), second order in the cell;
* the surface plasmon's dispersion k_spp = k0 sqrt(em ed / (em + ed)), real and imaginary parts.
"""

from __future__ import annotations

import cmath
import math

import numpy as np
import pytest

from opticore.samples import SPP_GOLD_NK, SPP_WAVELENGTH_UM, get_sample
from opticore.thinfilm import Layer, stack_rt
from opticore.wave.fdtd import FdtdError, Shape, Spec, _medium, run, slab_mode_neff, spec_from_dict

LAM = 0.633
METALS = {"silver": (0.0565, 4.2756), "gold": (0.197, 3.09)}


@pytest.mark.parametrize("metal", list(METALS))
@pytest.mark.parametrize("pol", ["s", "p"])
def test_metal_half_space_matches_fresnel(metal, pol):
    n, k = METALS[metal]
    N = complex(n, k)
    sp = Spec(wavelength=LAM, size_z=1.2, size_y=0.05, polarization=pol, shapes=[Shape("rectangle", n=n, k=k, z0=0.7, z1=50.0, y0=-5, y1=5)],
              z_source=0.1, z_reflection=0.3, z_transmission=0.65, ppw=30)
    r = run(sp)
    assert r["R"] == pytest.approx(abs((1 - N) / (1 + N)) ** 2, abs=1e-3)
    assert r["R"] + r["T"] == pytest.approx(1.0, abs=2e-3)  # T: the power entering the metal (monitor before it)


def test_thin_metal_films_match_the_transfer_matrix():
    for metal, d in (("silver", 0.040), ("gold", 0.030)):
        n, k = METALS[metal]
        tf = stack_rt(1.0, 1.5, (Layer(n, d * 1000, k, ""),), LAM, np.array([1.0]))
        for pol in ("s", "p"):
            err = {}
            for ppw in (30, 70):
                sp = Spec(wavelength=LAM, size_z=1.2, size_y=0.05, polarization=pol,
                          shapes=[Shape("rectangle", n=1.5, z0=0.7 + d, z1=50.0, y0=-5, y1=5), Shape("rectangle", n=n, k=k, z0=0.7, z1=0.7 + d, y0=-5, y1=5)],
                          z_source=0.1, z_reflection=0.3, z_transmission=1.0, ppw=ppw)
                r = run(sp)
                err[ppw] = max(abs(r["R"] - tf["Rs"][0]), abs(r["T"] - tf["Ts"][0]))
            # a film of two skin depths needs cells well below the skin depth: 3e-3 at 70 points per wavelength in |n|
            assert err[70] < 3e-3 and err[70] < err[30], (metal, pol, err)


def test_the_discrete_drude_medium_has_the_target_permittivity():
    dt, dx, omega = 0.002, 0.004, 2 * math.pi / LAM
    eps = np.array([[-9.51, -18.28, 0.5, 0.99]])
    sig = np.array([[1.22, 0.48, 0.3, 0.0]]) * omega
    ca, cb, (idx, kj, bj) = _medium(eps, sig, dt, dx, omega)
    assert list(idx) == [0, 1, 2, 3] and np.all(ca == 1) and np.allclose(cb, dt / dx)
    gamma = (2 / dt) * (1 - kj.astype(float)) / (1 + kj.astype(float))
    wp2 = bj.astype(float) * (1 + gamma * dt / 2) / dt
    W, c = 2 * math.sin(omega * dt / 2) / dt, math.cos(omega * dt / 2)
    got = 1 - wp2 / (W * W + 1j * W * gamma * c)
    assert np.allclose(got, eps[0] + 1j * sig[0] / omega, rtol=1e-5)  # float32 coefficients
    ca, cb, dr = _medium(np.array([[2.25]]), np.array([[0.0]]), dt, dx, omega)
    assert dr is None and ca[0, 0] == 1 and cb[0, 0] == pytest.approx(dt / dx / 2.25)


def test_slab_mode_propagation_constant():
    lam, a, n1, n2 = 1.0, 0.4, 1.6, 1.45

    def neff(pol, ppw):
        sp = Spec(wavelength=lam, size_z=10.0, size_y=5.0, polarization=pol, n_background=n2, source="mode", mode_half_width=a, mode_n_core=n1, mode_n_clad=n2,
                  shapes=[Shape("rectangle", n=n1, z0=-50, z1=50, y0=-a, y1=a)], periodic_y=False, reference=False, z_source=0.5, z_transmission=9.5, ppw=ppw)
        return run(sp)["propagation"]["n_eff"]

    e20, e30 = (neff("s", p) - slab_mode_neff(a, n1, n2, lam, "s") for p in (20, 30))
    assert abs(e30) < 4e-3 and 1.8 < e20 / e30 < 2.8  # the Yee grid's phase error, second order in the cell
    assert neff("p", 30) == pytest.approx(slab_mode_neff(a, n1, n2, lam, "p"), abs=4e-3)


def test_plasmon_example_follows_the_dispersion_relation():
    p = get_sample("spp-gold")
    assert p.ui["open_view"] == "fdtd"
    sp = spec_from_dict(p.analysis_settings["fdtd"])
    r = run(sp)
    pr = r["propagation"]
    em = complex(*SPP_GOLD_NK) ** 2
    n_spp = cmath.sqrt(em / (em + 1.0))  # k_spp / k0 on gold / air
    assert pr["n_eff"] == pytest.approx(n_spp.real, abs=1e-3)
    assert pr["kappa"] == pytest.approx(n_spp.imag, rel=0.03)
    assert 1 / pr["attenuation_per_um"] == pytest.approx(SPP_WAVELENGTH_UM / (4 * math.pi * n_spp.imag), rel=0.03)  # 6.5 um
    assert pr["analytic_n_eff"] == pytest.approx(n_spp.real, abs=1e-12) and pr["eps_metal"][0] == pytest.approx(em.real, rel=1e-9)
    assert r["convergence"] < 0.02 and all(math.isfinite(v) for row in r["index"] for v in row)


def test_plasmon_source_is_checked():
    base = dict(wavelength=LAM, size_z=2.0, size_y=1.0, source="spp", spp_y=0.0, periodic_y=False, reference=False,
                shapes=[Shape("rectangle", n=0.197, k=3.09, z0=-50, z1=50, y0=-5, y1=0.0)])
    with pytest.raises(FdtdError, match="TM"):
        run(Spec(polarization="s", **base))
    with pytest.raises(FdtdError, match="No surface plasmon"):  # a dielectric below: no plasmon
        run(Spec(polarization="p", **{**base, "shapes": [Shape("rectangle", n=1.5, z0=-50, z1=50, y0=-5, y1=0.0)]}))
    with pytest.raises(FdtdError, match="inside the domain"):
        run(Spec(polarization="p", **{**base, "spp_y": 0.49}))
    from opticore.wave.fdtd_bor import run_bor

    with pytest.raises(FdtdError, match="metal"):  # the rotationally symmetric solver keeps dielectrics only
        run_bor(Spec(polarization="s", wavelength=LAM, size_z=2.0, size_y=2.0, geometry="axisymmetric", source="gaussian", waist=0.5, periodic_y=False,
                 shapes=[Shape("rectangle", n=0.197, k=3.09, z0=1.0, z1=50, y0=-5, y1=5)]))
