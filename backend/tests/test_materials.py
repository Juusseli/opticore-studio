import json
from importlib import resources

import numpy as np
import pytest

from opticore.materials import (
    LAMBDA_C,
    LAMBDA_D,
    LAMBDA_F,
    Dispersion,
    DispersionError,
    MaterialError,
    MaterialLibrary,
    abbe_number,
    builtin_materials,
)


def _catalog():
    raw = resources.files("opticore.materials").joinpath("data/catalog.json").read_text("utf-8")
    return json.loads(raw)["materials"]


@pytest.mark.parametrize("rec", [r for r in _catalog() if r.get("nd_ref")], ids=lambda r: r["name"])
def test_catalog_transcription_nd(rec):
    """Published nd (5 decimals) must be reproduced by the stored coefficients."""
    m = builtin_materials()[rec["name"]]
    assert m.nd == pytest.approx(rec["nd_ref"], abs=1.5e-5)


@pytest.mark.parametrize("rec", [r for r in _catalog() if r.get("vd_ref")], ids=lambda r: r["name"])
def test_catalog_transcription_vd(rec):
    m = builtin_materials()[rec["name"]]
    assert m.vd == pytest.approx(rec["vd_ref"], abs=0.02)


def test_nbk7_reference_lines():
    m = builtin_materials()["N-BK7"]
    # SCHOTT datasheet values nF = 1.52238, nC = 1.51432
    assert m.index(LAMBDA_F) == pytest.approx(1.52238, abs=1e-5)
    assert m.index(LAMBDA_C) == pytest.approx(1.51432, abs=1e-5)


def test_normal_dispersion_monotonic():
    for m in (m for m in builtin_materials().values() if m.category != "metal"):  # metals: anomalous dispersion
        lam = np.linspace(max(m.dispersion.lambda_min, 0.42), min(m.dispersion.lambda_max, 1.0), 50)
        n = m.dispersion.index(lam)
        assert np.all(np.diff(n) < 0), m.name


def test_sellmeier_squared_equivalence():
    a = Dispersion("sellmeier", [0.6961663, 0.0684043**2, 0.4079426, 0.1162414**2, 0.8974794, 9.896161**2])
    b = Dispersion("sellmeier_sq", [0.6961663, 0.0684043, 0.4079426, 0.1162414, 0.8974794, 9.896161])
    lam = np.linspace(0.3, 2.0, 20)
    assert np.allclose(a.index(lam), b.index(lam), atol=1e-12)


def test_cauchy_and_schott_and_constant():
    c = Dispersion("cauchy", [1.5, 0.004, 0.0])
    assert c.index(0.5) == pytest.approx(1.5 + 0.004 / 0.25)
    s = Dispersion("schott", [2.25])
    assert s.index(0.6) == pytest.approx(1.5)
    k = Dispersion("constant", [1.7])
    assert k.index(0.9) == pytest.approx(1.7)


def test_tabulated_interpolation_passes_through_points():
    t = Dispersion("tabulated", table=[[0.5, 1.52], [0.4, 1.53], [0.7, 1.51]])
    assert t.index(0.5) == pytest.approx(1.52)
    assert t.lambda_min == 0.4 and t.lambda_max == 0.7
    assert 1.51 < t.index(0.6) < 1.52
    assert not t.in_range(0.8)


@pytest.mark.parametrize(
    "formula,coef",
    [("sellmeier", [1.0]), ("schott", []), ("cauchy", [1, 2, 3, 4]), ("constant", [1, 2]), ("magic", [1])],
)
def test_invalid_coefficients(formula, coef):
    with pytest.raises(DispersionError):
        Dispersion(formula, coef)


def test_nonpositive_wavelength_rejected():
    with pytest.raises(DispersionError):
        builtin_materials()["N-BK7"].dispersion.index(0.0)


def test_library_custom_and_errors():
    lib = MaterialLibrary([{"name": "myglass", "formula": "constant", "coefficients": [1.6]}])
    assert lib.index("MYGLASS", 0.55) == 1.6
    assert lib.index("air", 0.55) == 1.0
    with pytest.raises(MaterialError):
        lib.get("does-not-exist")
    with pytest.raises(MaterialError):
        MaterialLibrary([{"name": "MIRROR", "formula": "constant", "coefficients": [1.6]}])
    with pytest.raises(MaterialError):
        MaterialLibrary([{"name": "bad", "formula": "sellmeier", "coefficients": [1.0]}])


def test_range_flags():
    m = builtin_materials()["PMMA"]
    assert m.in_range(0.55)
    assert not m.in_range(0.40)


def test_thermal_model_magnitude():
    """N-BK7 absolute dn/dT near 20 degC at the d line is ~ +1.6e-6 /K (datasheet ~1.6-2.4e-6)."""
    d = builtin_materials()["N-BK7"].dispersion
    n20 = d.index_at_temperature(LAMBDA_D, 20.0)
    n40 = d.index_at_temperature(LAMBDA_D, 40.0)
    dndt = (n40 - n20) / 20.0
    assert 1.0e-6 < dndt < 3.5e-6


def test_abbe_number_definition():
    d = Dispersion("constant", [1.5])
    with pytest.raises(ZeroDivisionError):
        abbe_number(d)


def test_pmma_is_beadie_2015_and_agrees_with_an_independent_measurement():
    """PMMA is the formula of Beadie et al. (Appl. Opt. 54, F139 (2015), 20.1 degC, accuracy < 2e-4), evaluated here
    independently: n^2 = A + sum c L^e. Independent benchmark: Szczurowski 2013 (3-term Sellmeier, 23 degC, other
    sample; refractiveindex.info, CC0) agrees within the spread of PMMA samples, 2.5e-3 in n over 0.42-1.08 um and
    1.5 in Vd. The one-term Sellmeier fit of Sultanova et al. (2009) gives Vd 53.2, 4.8 below it."""
    m = builtin_materials()["PMMA"]
    A, terms = 2.1778, [(6.1209e-3, 2), (-1.5004e-3, 4), (2.3678e-2, -2), (-4.2137e-3, -4), (7.3417e-4, -6), (-4.5042e-5, -8)]
    for L in (0.42, LAMBDA_F, LAMBDA_D, LAMBDA_C, 1.064, 1.55, 1.62):
        assert m.index(L) == pytest.approx((A + sum(c * L**e for c, e in terms)) ** 0.5, abs=1e-12)
    assert m.in_range(1.55) and not m.in_range(0.41) and not m.in_range(1.7)

    szc = Dispersion("sellmeier", [0.99654, 0.00787, 0.18964, 0.02191, 0.00411, 3.85727])
    lam = np.linspace(0.42, 1.08, 34)
    assert np.max(np.abs(m.dispersion.index(lam) - szc.index(lam))) < 2.5e-3
    assert abs(m.vd - abbe_number(szc)) < 1.5
    assert abs(abbe_number(Dispersion("sellmeier", [1.1819, 0.011313])) - abbe_number(szc)) > 4.0


@pytest.mark.parametrize("name,vd_other", [("POLYCARBONATE", 28.1), ("POLYSTYRENE", 31.2)])
def test_generic_polymers_state_their_data_and_its_spread(name, vd_other):
    """PC and PS keep the only formula data in the CC0 database (Sultanova et al. 2009, one-term fit). Their source
    text states nd and Vd and the other sample's value, so the spread between grades is visible where they are
    chosen."""
    rec = next(r for r in _catalog() if r["name"] == name)
    m = builtin_materials()[name]
    assert f"nd {m.nd:.5f}" in rec["source"] and f"Vd {m.vd:.1f}" in rec["source"]
    assert f"Vd about {vd_other}" in rec["source"] and "maker's data" in rec["source"]
