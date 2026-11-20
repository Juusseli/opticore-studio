"""The lighting examples of the library (samples.py), run as the Non-Sequential view runs them (its stored settings)
and checked against independent results.

* LED downlight: the luminous flux of the source from its stored spectrum (the CIE tables read here); the flux on the
  3 m x 3 m work plane from the view factor of a Lambertian emitter to a centred parallel rectangle (four corner
  rectangles, F = 1/(2 pi) [A/sqrt(1+A^2) atan(B/sqrt(1+A^2)) + B/sqrt(1+B^2) atan(A/sqrt(1+B^2))]); the flux on the
  desk from the coaxial disc, rho^2 / (rho^2 + h^2); the chromaticity and CCT of the light on the work plane equal to
  the source's within the Monte Carlo standard errors; the detector's numbers recomputed from its detected spectrum.
* Additive colour mixing: in every region of the three collimated beams the light's chromaticity and illuminance from
  the beams' powers and areas (single colours exactly on the spectral locus); the true-colour image as the sRGB
  encoding of the X, Y, Z maps with one exposure; all light on the screen.
"""

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from opticore import photometry as ph
from opticore.api.main import app
from opticore.samples import DESK_RADIUS_MM, LED_HEIGHT_MM, RGB_BEAM_SIZE_MM, RGB_BEAMS, RGB_PIXELS, RGB_SCREEN_MM, get_sample

client = TestClient(app)
CMF = np.loadtxt(ph.DATA / "CIE_xyz_1931_2deg.csv", delimiter=",")


def xyz_of(lam_um, power):
    """Tristimulus values of lines, the 1931 tables interpolated here (independent of the module)."""
    lam = np.asarray(lam_um) * 1000.0
    P = np.asarray(power, dtype=float)
    return np.array([(P * np.interp(lam, CMF[:, 0], CMF[:, k], left=0.0, right=0.0)).sum() for k in (1, 2, 3)])


def run(sid):
    p = get_sample(sid)
    st = p.analysis_settings["nonseq"]
    body = {"system": p.system.model_dump(mode="json"), "custom_materials": [], "sources": [s.model_dump(mode="json") for s in p.sources],
            "detectors": [d.model_dump(mode="json") for d in p.detectors], "rays": st["rays"], "split": st["split"], "include_system": st["include_system"],
            "pixels": st["pixels"], "seed": st["seed"], "max_seconds": st["max_seconds"]}
    r = client.post("/api/v1/analysis/nonseq", json=body)
    assert r.status_code == 200, r.text
    d = client.post("/api/v1/sources/describe", json=body).json()
    assert p.ui["open_view"] == "nonseq"
    return p, r.json(), d


def corner_view_factor(A, B):
    a, b = math.sqrt(1 + A * A), math.sqrt(1 + B * B)
    return (A / a * math.atan(B / a) + B / b * math.atan(A / b)) / (2 * math.pi)


def test_led_downlight_example():
    p, res, desc = run("led-downlight")
    assert res["complete"]
    src = p.sources[0]
    lam = [w.value for w in src.wavelengths]
    P = np.array([w.weight for w in src.wavelengths]) * src.power_w / sum(w.weight for w in src.wavelengths)
    X = xyz_of(lam, P)
    phi = ph.KM * X[1]
    light = desc["sources"][0]["light"]
    assert light["luminous_flux_lm"] == pytest.approx(phi, rel=1e-12)
    xs, ys = X[0] / X.sum(), X[1] / X.sum()
    assert light["chromaticity"]["x"] == pytest.approx(xs, abs=1e-12) and light["chromaticity"]["y"] == pytest.approx(ys, abs=1e-12)
    plane = next(d for d in res["detectors"] if d["id"] == "det-plane")
    desk = next(d for d in res["detectors"] if d["id"] == "det-desk")
    q, k = plane["photometry"], desk["photometry"]
    # flux: view factors of a point Lambertian emitter (the 1 mm radius is 5e-4 of the height)
    F_plane = 4 * corner_view_factor(1500.0 / LED_HEIGHT_MM, 1500.0 / LED_HEIGHT_MM)
    h_desk = LED_HEIGHT_MM - 1.0
    F_desk = DESK_RADIUS_MM**2 / (DESK_RADIUS_MM**2 + h_desk**2)
    for got, F in ((q, F_plane), (k, F_desk)):
        assert got["luminous_flux_sigma_lm"] < 0.02 * got["luminous_flux_lm"]
        assert abs(got["luminous_flux_lm"] - phi * F) < 4 * got["luminous_flux_sigma_lm"]
    assert q["average_illuminance_lux"] == pytest.approx(q["luminous_flux_lm"] / 9.0, rel=1e-12)
    assert k["average_illuminance_lux"] == pytest.approx(k["luminous_flux_lm"] / (math.pi * 0.3**2), rel=1e-12)
    px = (3.0 / plane["pixels"][0]) * (3.0 / plane["pixels"][1])
    assert float(np.sum(q["illuminance_lux"])) * px == pytest.approx(q["luminous_flux_lm"], rel=1e-9)
    # the light on the plane has the source's colour within its standard errors
    c, s = q["chromaticity"], q["chromaticity_sigma"]
    assert abs(c["x"] - xs) < 4 * s["x"] and abs(c["y"] - ys) < 4 * s["y"] and s["x"] < 2e-3
    assert abs(q["cct_k"] - light["cct_k"]) < 4 * q["cct_sigma_k"]
    # the detector's numbers from its detected spectrum
    det_lam = [float(x) for x in plane["by_wavelength_w"]]
    Xd = xyz_of(det_lam, list(plane["by_wavelength_w"].values()))
    assert q["luminous_flux_lm"] == pytest.approx(ph.KM * Xd[1], rel=1e-9)
    assert c["x"] == pytest.approx(Xd[0] / Xd.sum(), abs=1e-12)


def test_colour_mixing_example():
    p, res, _ = run("colour-mixing")
    det = res["detectors"][0]
    q = det["photometry"]
    pix = RGB_SCREEN_MM / RGB_PIXELS
    edges = -RGB_SCREEN_MM / 2 + pix * np.arange(RGB_PIXELS + 1)
    maps = np.array(q["xyz_w_mm2"])  # (3, ny, nx), rows along y
    # every ray lands on the screen
    total = xyz_of([b[2] for b in RGB_BEAMS], [b[3] for b in RGB_BEAMS])
    assert q["luminous_flux_lm"] == pytest.approx(ph.KM * total[1], rel=1e-9)
    half = RGB_BEAM_SIZE_MM / 2
    regions = {  # (x0, x1, y0, y1) inside exactly the named beams
        "R": (-45, -30, 15, 40), "G": (30, 45, 15, 40), "B": (-15, 15, -45, -20),
        "RG": (-15, 15, 15, 40), "RB": (-30, -15, -20, 15), "GB": (15, 30, -20, 15), "RGB": (-15, 15, -20, 15),
    }
    letter = {0: "R", 1: "G", 2: "B"}
    for name, (x0, x1, y0, y1) in regions.items():
        ix = (edges[:-1] >= x0 - 1e-9) & (edges[1:] <= x1 + 1e-9)
        iy = (edges[:-1] >= y0 - 1e-9) & (edges[1:] <= y1 + 1e-9)
        area = (x1 - x0) * (y1 - y0)
        assert ix.sum() * iy.sum() * pix * pix == pytest.approx(area)
        got = maps[:, iy][:, :, ix].sum(axis=(1, 2)) * pix * pix  # W of X, Y, Z in the region
        beams = [k for k in range(3) if letter[k] in name]
        for k in beams:  # the region lies inside these beams only
            (cx, cy), lam, pw = RGB_BEAMS[k][1], RGB_BEAMS[k][2], RGB_BEAMS[k][3]
            assert cx - half <= x0 and x1 <= cx + half and cy - half <= y0 and y1 <= cy + half
        # expected: each beam's power on the region, and its Poisson standard error (hits = rays x area share)
        parts = [xyz_of([RGB_BEAMS[k][2]], [RGB_BEAMS[k][3] * area / RGB_BEAM_SIZE_MM**2]) for k in beams]
        n_hits = [p.sources[k].rays * area / RGB_BEAM_SIZE_MM**2 for k in beams]
        want = sum(parts)
        x_w, y_w = want[0] / want.sum(), want[1] / want.sum()
        x_g, y_g = got[0] / got.sum(), got[1] / got.sum()
        if len(beams) == 1:
            assert x_g == pytest.approx(x_w, abs=1e-12) and y_g == pytest.approx(y_w, abs=1e-12)
        else:
            # linear error propagation of the beams' relative standard errors 1/sqrt(n) to x and y
            def xy(scales):
                v = sum(s * part for s, part in zip(scales, parts))
                return np.array([v[0] / v.sum(), v[1] / v.sum()])
            sig = np.sqrt(sum(((xy([1 + (1e-6 if j == i else 0) for j in range(len(beams))]) - xy([1] * len(beams))) / 1e-6 / math.sqrt(n)) ** 2 for i, n in enumerate(n_hits)))
            assert abs(x_g - x_w) < 4 * sig[0] + 1e-12 and abs(y_g - y_w) < 4 * sig[1] + 1e-12
        sig_Y = math.sqrt(sum((part[1] / math.sqrt(n)) ** 2 for part, n in zip(parts, n_hits)))
        assert abs(got[1] - want[1]) < 4 * sig_Y
    # illuminance map = K_m Y per area
    lux = np.array(q["illuminance_lux"])
    assert np.allclose(lux, ph.KM * maps[1] * 1e6, rtol=1e-12, atol=1e-9)
    # the colour image is the sRGB encoding of the X, Y, Z maps with one exposure (brightest channel 1)
    rgb = np.clip(np.einsum("ij,jyx->yxi", ph.srgb_matrix(), maps), 0.0, None)
    want_img = np.round(255 * ph.srgb_encode(rgb / rgb.max()))
    assert np.abs(np.array(q["colour_image"]) - want_img).max() <= 1
    assert 0.0 < q["colour_image_out_of_gamut"] < 1.0  # the spectral red, green and blue lie outside the sRGB gamut
