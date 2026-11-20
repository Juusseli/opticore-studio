"""Design advisor: diagnosis of what limits the image, and verified suggestions."""

import math
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore.analysis.advisor import default_spec, diagnose, suggest, zernike_classes
from opticore.analysis.wavefront import pupil_grid, zernike
from opticore.api.main import app
from opticore.model import OpticalSystem
from opticore.optimize.merit import MeritFunction
from opticore.paraxial import paraxial_data
from opticore.samples import get_sample
from opticore.system import compile_system

from .conftest import make_system

FDC = [{"value": 0.4861327}, {"value": 0.5875618}, {"value": 0.6562725}]


def _apply(system: OpticalSystem, patch: list) -> OpticalSystem:
    d = system.model_dump()
    for p in patch:
        for s in d["surfaces"]:
            if s["id"] == p["surface_id"]:
                s[p["key"]] = p["value"]
    return OpticalSystem.model_validate(d)


# ---- diagnosis -----------------------------------------------------------------------------------------------


def test_class_variances_add_up_and_match_the_zernike_norms():
    X, Y, inside = pupil_grid(200)
    x, y = X[inside], Y[inside]
    rho, th = np.hypot(x, y), np.arctan2(y, x)
    W = 0.3 * zernike(4, 0, rho, th) + 0.2 * zernike(3, 1, rho, th) + 0.1 * zernike(2, 2, rho, th) + 0.05 * zernike(1, 1, rho, th)
    zc = zernike_classes(x, y, W)
    v = zc["variance"]
    # Fringe Zernike RMS: c / sqrt(n + 1) for m = 0, c / sqrt(2 (n + 1)) otherwise (continuous pupil)
    assert v["spherical"] == pytest.approx(0.3**2 / 5, rel=0.01)
    assert v["coma"] == pytest.approx(0.2**2 / 8, rel=0.01)
    assert v["astigmatism"] == pytest.approx(0.1**2 / 6, rel=0.01)
    assert v["defocus"] == pytest.approx(0.0, abs=1e-6) and v["trefoil"] == pytest.approx(0.0, abs=1e-6)
    # exact (Parseval on the samples): the class variances and the residual add up to the variance of W
    # without its least-squares piston and tilt
    A = np.stack([np.ones_like(x), zernike(1, 1, rho, th), zernike(1, -1, rho, th)], axis=1)
    W0 = W - A @ np.linalg.lstsq(A, W, rcond=None)[0]
    assert sum(v.values()) + zc["residual"] == pytest.approx(np.mean(W0**2), rel=1e-9)


def _singlet(front_r, back_r, *, stop_gap=None, fields=(0.0,), epd=20.0, wavelengths=None, image_solve=True, extra_image=0.0):
    surfs = [{"thickness": None}]
    if stop_gap is not None:
        surfs.append({"thickness": stop_gap, "is_stop": True})
    surfs.append({"radius": front_r, "thickness": 5.0, "material": "N-BK7", **({} if stop_gap is not None else {"is_stop": True})})
    back = {"radius": back_r, "thickness": 100.0}
    if image_solve:
        back["thickness_solve"] = {"type": "marginal_height", "target": 0.0}
    surfs.append(back)
    surfs.append({})
    sysd = make_system(surfs, wavelengths=wavelengths or [{"value": 0.5875618}], fields=[{"y": f} for f in fields], aperture={"type": "epd", "value": epd})
    if extra_image:
        sysd.surfaces[-2].thickness_solve = None
        sysd = compile_system(sysd).model  # resolved thickness
        sysd = sysd.model_copy(deep=True)
        sysd.surfaces[-2].thickness += extra_image
    return sysd


def test_reversed_plano_convex_lens_is_limited_by_spherical_aberration():
    """Flat side towards a distant object (the wrong way round) at f/5: spherical aberration; at the paraxial focus
    much of the wavefront is defocus (a focus error), so the advisor also says the focus is off."""
    d = diagnose(compile_system(_singlet(None, -51.68)))
    f0 = d["fields"][0]
    assert f0["dominant"] == "spherical"
    kinds = [f["kind"] for f in d["findings"]]
    assert "focus" in kinds
    ab = next(f for f in d["findings"] if f["kind"] == "aberration")
    assert ab["class"] == "spherical" and ab["share"] > 0.9


def test_remote_stop_gives_field_curvature_astigmatism_and_barrel_distortion():
    """A biconvex singlet with the stop 40 mm in front, 12 deg: the edge of the field is out of focus (field
    curvature) and its remaining blur is astigmatism and coma; the distortion is barrel (negative)."""
    d = diagnose(compile_system(_singlet(50.0, -50.0, stop_gap=40.0, fields=(0.0, 12.0), epd=8.0)))
    edge = d["fields"][-1]
    assert edge["dominant"] in ("coma", "astigmatism")
    blur = 1.0 - edge["classes"]["defocus"]["share"]
    assert (edge["classes"]["coma"]["share"] + edge["classes"]["astigmatism"]["share"]) / blur > 0.6
    kinds = {f["kind"] for f in d["findings"]}
    assert {"field_curvature", "distortion"} <= kinds
    assert d["distortion_percent"] < -1.0
    assert d["attribution"]["coma"]["surfaces"] and d["attribution"]["astigmatism"]["surfaces"]


def test_uncorrected_singlet_in_white_light_shows_axial_colour():
    d = diagnose(compile_system(_singlet(51.68, None, wavelengths=FDC)))
    ax = next(f for f in d["findings"] if f["kind"] == "axial_colour")
    assert ax["ratio"] > 3.0
    assert d["colour"]["axial_colour_um"] == pytest.approx(d["colour"]["axial_colour_um"], rel=0)
    assert d["attribution"]["axial_colour"]["surfaces"]


def test_defocused_image_plane_is_a_focus_error_and_refocus_wins():
    p = get_sample("achromat")
    sysd = p.system.model_copy(deep=True)
    sysd.surfaces[-2].thickness += 0.5
    d = diagnose(compile_system(sysd))
    foc = next(f for f in d["findings"] if f["kind"] == "focus")
    assert foc["share"] > 0.9
    res = suggest(sysd, p.custom_materials, None)
    top = res["suggestions"][0]
    assert top["kind"] == "refocus"
    assert top["t"] == pytest.approx(-0.5, abs=0.05)  # back to the original best focus
    original = MeritFunction(p.system, default_spec(sysd), p.custom_materials).merit(np.array([]))
    assert top["merit_after"] == pytest.approx(original, rel=0.05)  # as good as the design before the shift


@pytest.mark.parametrize("sample", ["achromat", "cooke-triplet", "double-gauss"])
def test_designs_balanced_over_field_and_colour_are_in_focus(sample):
    """The focus finding uses the System card's criterion (focus.py): a design whose image surface sits at the best
    polychromatic RMS focus is in focus, even where one field's wavefront at one wavelength shows defocus."""
    from opticore.analysis.focus import focus_status

    p = get_sample(sample)
    cs = compile_system(p.system, p.custom_materials)
    d = diagnose(cs)
    assert focus_status(cs)["at_best_focus"] is True
    assert "focus" not in [f["kind"] for f in d["findings"]]
    # the field-curvature finding is the spread of the signed wavefront defocus over the field
    foc = [f["focus_signed_waves"] for f in d["fields"]]
    fc = [f for f in d["findings"] if f["kind"] == "field_curvature"]
    assert (max(foc) - min(foc) > 0.25 / math.sqrt(12)) == bool(fc)


def test_well_corrected_monochromatic_design_is_diffraction_limited():
    sysd = make_system(
        [{"thickness": None}, {"type": "ideal", "focal_length": 100.0, "thickness": 100.0, "is_stop": True, "semi_diameter": 60.0}, {"thickness": 0.0}],
        wavelengths=[{"value": 0.55}],
        fields=[{"y": 0.0}, {"y": 3.0}],
        aperture={"type": "epd", "value": 10.0},
    )
    d = diagnose(compile_system(sysd))
    assert [f["kind"] for f in d["findings"]] == ["diffraction_limited"]


# ---- suggestions ---------------------------------------------------------------------------------------------


def test_bending_turns_the_reversed_lens_round_at_constant_power():
    """The plano-convex lens with its flat side to the distant object: the bend move turns it round (convex side
    first, the minimum-spherical-aberration shape) and holds the focal length exactly; on one field and one
    wavelength a conic on the back surface removes the spherical aberration altogether and ranks first."""
    sysd = _singlet(None, -51.68)
    efl0 = paraxial_data(compile_system(sysd)).efl
    res = suggest(sysd, [], None)
    kinds = [s["kind"] for s in res["suggestions"]]
    assert kinds[0] == "conic" and res["suggestions"][0]["gain"] > 0.99
    bend = res["suggestions"][kinds.index("bend")]
    r1, r2 = [p["value"] for p in bend["patch"]]
    assert 0 < r1 < abs(r2) and r2 < 0  # convex side towards the object, the back surface flatter
    assert bend["gain"] > 0.7
    assert paraxial_data(compile_system(_apply(sysd, bend["patch"]))).efl == pytest.approx(efl0, rel=1e-9)


def test_every_reported_gain_is_a_real_evaluation():
    p = get_sample("achromat-start")
    res = suggest(p.system, p.custom_materials, p.optimization)
    assert res["merit_kind"] == "project" and res["suggestions"]
    for s in res["suggestions"]:
        mf = MeritFunction(_apply(p.system, s["patch"]), p.optimization, p.custom_materials)
        assert mf.merit(np.array([])) == pytest.approx(s["merit_after"], rel=1e-9)
        assert s["merit_after"] < s["merit_before"]
    gains = [s["gain"] for s in res["suggestions"]]
    assert gains == sorted(gains, reverse=True)


def test_default_merit_holds_the_focal_length():
    p = get_sample("double-gauss")
    spec = default_spec(p.system, p.custom_materials)
    assert [o.type for o in spec.operands] == ["rms_spot", "efl"]
    assert spec.operands[1].target == pytest.approx(100.2075, abs=1e-3)


@pytest.mark.parametrize("sample,steps", [("achromat-start", 3), ("cooke-triplet-start", 2)])
def test_applying_the_top_suggestion_repeatedly_lowers_the_merit_as_predicted(sample, steps):
    """Acceptance criterion: each applied top suggestion lowers the merit function by exactly the predicted amount."""
    p = get_sample(sample)
    system = p.system
    merits = []
    for _ in range(steps):
        res = suggest(system, p.custom_materials, p.optimization)
        assert res["suggestions"], "no improving move found"
        top = res["suggestions"][0]
        system = _apply(system, top["patch"])
        m = MeritFunction(system, p.optimization, p.custom_materials).merit(np.array([]))
        assert m == pytest.approx(top["merit_after"], rel=1e-9)
        merits.append((top["merit_before"], m))
    assert all(after < before for before, after in merits)
    assert all(merits[k + 1][0] == pytest.approx(merits[k][1], rel=1e-9) for k in range(len(merits) - 1))


def test_advisor_api():
    client = TestClient(app)
    p = get_sample("achromat-start")
    body = {"system": p.system.model_dump(mode="json"), "optimization": p.optimization.model_dump(mode="json")}
    r = client.post("/api/v1/analysis/advisor", json=body)
    assert r.status_code == 200 and r.json()["fields"] and "findings" in r.json()
    job = client.post("/api/v1/advisor/start", json=body).json()["job_id"]
    for _ in range(300):
        st = client.get(f"/api/v1/advisor/{job}").json()
        if st["state"] != "running":
            break
        time.sleep(0.1)
    assert st["state"] == "finished" and st["progress"]["done"] == st["progress"]["total"] > 0
    assert st["result"]["suggestions"][0]["gain"] > 0
    assert client.get("/api/v1/advisor/nope").status_code == 404
    assert math.isfinite(st["result"]["merit"])
