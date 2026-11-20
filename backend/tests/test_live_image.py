"""Live colour image through the lens: mapping, colour fringes, energy, preview against full quality."""

import base64
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

import opticore.analysis.liveimage as li
from opticore.analysis.imaging import simulate_image
from opticore.analysis.wavefront import pupil_grid
from opticore.api.main import app
from opticore.paraxial import compute_pupil
from opticore.raytrace import trace_pupil
from opticore.samples import get_sample
from opticore.system import compile_system

from .conftest import make_system


def rel_rms(a, b):
    return float(np.sqrt(np.mean((a - b) ** 2)) / np.sqrt(np.mean(b**2)))


def rgb_system(p):
    """The sample with the live image's channel wavelengths (red, green = primary, blue)."""
    d = p.system.model_dump()
    d["wavelengths"] = [{"value": v, "weight": 1.0} for v in li.channel_wavelengths(p.system)]
    d["primary_wavelength"] = 1
    return compile_system(type(p.system).model_validate(d), p.custom_materials)


# ---- pieces --------------------------------------------------------------------------------------------------


def test_srgb_transfer_and_photo_decoding():
    v = np.linspace(0, 1, 101)
    assert li.srgb_to_linear(li.linear_to_srgb(v)) == pytest.approx(v, abs=1e-12)
    assert li.srgb_to_linear(np.array([0.5]))[0] == pytest.approx(0.21404, abs=1e-5)  # IEC 61966-2-1
    raw = np.array([[[255, 0, 0], [0, 255, 0]], [[0, 0, 255], [128, 128, 128]]], dtype=np.uint8)
    ph = li.decode_photo(2, 2, base64.b64encode(raw.tobytes()).decode())
    assert ph.shape == (2, 2, 3) and ph[0, 0].tolist() == [1.0, 0.0, 0.0] and ph[1, 0].tolist() == [0.0, 0.0, 1.0]
    with pytest.raises(ValueError):
        li.decode_photo(3, 2, base64.b64encode(raw.tobytes()).decode())


def test_channel_wavelengths():
    assert li.channel_wavelengths(get_sample("achromat").system) == pytest.approx([0.6562725, 0.5875618, 0.4861327])
    one = make_system([{"thickness": None}, {"radius": 50.0, "thickness": 5.0, "material": "N-BK7", "is_stop": True}, {"thickness": 95.0}, {}], wavelengths=[{"value": 0.55}])
    assert li.channel_wavelengths(one) == list(li.DEFAULT_RGB)


def test_chief_ray_map_against_direct_traces():
    """The spline of the distortion factor reproduces traced chief-ray heights to 0.05 µm over the field."""
    for sid, um in (("cooke-triplet", 20.0), ("double-gauss", 19.0)):
        p = get_sample(sid)
        cs = compile_system(p.system, p.custom_materials)
        pu = compute_pupil(cs)
        k = li.chief_height(cs, 1, 1e-4 * um, pu) / math.tan(math.radians(1e-4 * um))
        vm, hm, _ = li.chief_maps(cs, pu, um, 1.2 * abs(li.chief_height(cs, 1, um, pu)), True, k)
        for v in np.linspace(0.3, um, 17):
            assert np.interp(v, vm[1], hm[1]) == pytest.approx(abs(li.chief_height(cs, 1, v, pu)), abs=5e-5)


def test_mirror_symmetric_kernels_are_exact(monkeypatch):
    p = get_sample("petzval")
    a = li.render(p.system, p.custom_materials, width=64, encode=False)
    assert a["settings"]["mirror_symmetry"] and a["settings"]["psf_computed"] < 3 * a["settings"]["psf_nodes"]
    monkeypatch.setattr(li, "mirror_symmetric", lambda cs: False)
    b = li.render(p.system, p.custom_materials, width=64, encode=False)
    assert np.abs(a["arrays"]["lens"] - b["arrays"]["lens"]).max() <= 1e-12


# ---- physics -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("quality,zoom,center", [("preview", 1, (0, 0)), ("full", 8, (1, 1))])
def test_every_channel_conserves_its_energy(quality, zoom, center):
    p = get_sample("achromat")
    r = li.render(p.system, p.custom_materials, width=96, quality=quality, zoom=zoom, center=center, encode=False)
    for e in r["energy"]:
        assert e["out"] == pytest.approx(e["in"], rel=1e-12)


@pytest.mark.parametrize("sample", ["achromat", "petzval", "geiser-triplet", "hubble"])
def test_preview_against_full_quality(sample):
    """The preview (3 × 3 PSF nodes, coarser pupil and PSF sampling) differs from the full quality by < 3 % RMS."""
    p = get_sample(sample)
    for zoom, center in ((1, (0, 0)), (8, (1, 1))):
        a = li.render(p.system, p.custom_materials, width=128, quality="preview", zoom=zoom, center=center, encode=False)
        b = li.render(p.system, p.custom_materials, width=128, quality="full", zoom=zoom, center=center, encode=False)
        assert rel_rms(a["arrays"]["lens"], b["arrays"]["lens"]) < 0.03


@pytest.mark.parametrize("sample", ["petzval", "geiser-triplet"])
def test_colour_fringes_equal_the_real_ray_lateral_colour(sample):
    """A small spot near the corner of the frame: the red, green and blue images are displaced as the real rays say.
    Each channel's centroid lies at the mean real-ray position of its wavelength (the chief ray carries the
    mapping, the PSF its offset from the chief ray), so red minus blue is the real-ray lateral colour (0.1 px)."""
    p = get_sample(sample)
    base = li.render(p.system, p.custom_materials, width=160, quality="full", zoom=32, center=(0.7, 0.7), encode=False)
    cx, cy = base["region_mm"]["center"]
    pix = base["pixel_um"] * 1e-3

    def spot(x, y, c):
        return np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * (2 * pix) ** 2))

    r = li.render(p.system, p.custom_materials, width=160, quality="full", zoom=32, center=(0.7, 0.7), scene_fn=spot, encode=False)
    assert not r["notes"]
    L = r["arrays"]["lens"]
    X, Y = np.meshgrid(r["arrays"]["x_mm"], r["arrays"]["y_mm"])
    radius = [math.hypot(float((L[c] * X).sum() / L[c].sum()), float((L[c] * Y).sum() / L[c].sum())) for c in range(3)]
    # the field whose green ideal image is at the spot, and the mean real-ray position per wavelength there
    cs = rgb_system(p)
    pu = compute_pupil(cs)
    v0 = 1e-4
    k = li.chief_height(cs, 1, v0, pu) / math.tan(math.radians(v0))
    v = math.degrees(math.atan(math.hypot(cx, cy) / abs(k)))
    px, py, inside = pupil_grid(128)
    mean = []
    for c in range(3):
        t = trace_pupil(cs, c, (0.0, -v if k < 0 else v), px[inside], py[inside], pu)
        mean.append(abs(float(t.image_xy()[t.ok][:, 1].mean())))
    assert (radius[0] - radius[2]) == pytest.approx(mean[0] - mean[2], abs=0.1 * pix)
    assert radius[1] == pytest.approx(mean[1], abs=0.1 * pix)
    # the corner read-out is the chief-ray lateral colour at the frame corner
    assert r["corner"]["lateral_colour_um"] is not None


def test_image_height_fields_are_imaged_through_their_object_fields():
    """The cell phone lens gives its fields as real image heights (up to 3.5 mm): the live image and the image
    simulation resolve them to object angles (fields.object_field), so the frame's corner is the 3.5 mm image height,
    every PSF node is computed and the energy is conserved."""
    p = get_sample("cell-phone-lens")
    assert p.system.field_type == "image_height"
    r = li.render(p.system, p.custom_materials, width=96, encode=False)
    assert r["corner"]["radius_mm"] == pytest.approx(3.5, abs=1e-6)
    assert r["settings"]["psf_nodes"] == 9 and not r["notes"]
    for e in r["energy"]:
        assert e["out"] == pytest.approx(e["in"], rel=1e-12)
    obj = li.with_object_space_fields(p.system, p.custom_materials)
    assert obj.field_type == "angle" and r["corner"]["field"] == pytest.approx(obj.fields[-1].y, rel=1e-6)
    cs = compile_system(p.system, p.custom_materials)
    assert abs(li.chief_height(cs, cs.model.primary_wavelength, obj.fields[-1].y, compute_pupil(cs))) == pytest.approx(3.5, abs=1e-6)
    assert simulate_image(p.system, p.custom_materials, "siemens", crop_px=32, noise=False, grid=3)["width_px"] == 32


def test_large_defocus_uses_the_geometric_disc():
    """An ideal f/5 lens with the image plane 2 mm behind focus: the wavefront is ~18 waves of defocus, too much for
    the diffraction sampling, so the PSF is geometric: a uniform disc of diameter dz / N = 400 µm, whose RMS radius is
    R / sqrt(2) (plus the source spot's own width)."""
    sysd = make_system(
        [{"thickness": None}, {"type": "ideal", "focal_length": 50.0, "thickness": 52.0, "is_stop": True, "semi_diameter": 30.0}, {"thickness": 0.0}],
        wavelengths=[{"value": 0.55}],
        fields=[{"y": 0.0}, {"y": 10.0}],
        aperture={"type": "epd", "value": 10.0},
    )
    base = li.render(sysd, (), width=384, quality="full", zoom=16, channels_um=[0.55] * 3, encode=False)
    pix = base["pixel_um"] * 1e-3
    sig = 2 * pix

    def spot(x, y, c):
        return np.exp(-(x * x + y * y) / (2 * sig * sig))

    r = li.render(sysd, (), width=384, quality="full", zoom=16, channels_um=[0.55] * 3, scene_fn=spot, encode=False)
    assert r["settings"]["geometric_psfs"] == r["settings"]["psf_computed"] > 0
    L = r["arrays"]["lens"][1]
    X, Y = np.meshgrid(r["arrays"]["x_mm"], r["arrays"]["y_mm"])
    w = L / L.sum()
    rms = math.sqrt(float((w * (X * X + Y * Y)).sum()))
    R = 2.0 / 5.0 / 2.0  # disc radius (mm): dz / (2 N)
    assert rms == pytest.approx(math.sqrt(R * R / 2 + 2 * sig * sig), rel=0.02)


def test_monochrome_scene_reproduces_the_image_simulation():
    """One wavelength in all three channels, framed on a sensor of the same pixels: the live image equals the image
    simulation's noiseless optics image (different PSF resampling and chief-ray interpolation: 2 % RMS), and the
    channels are identical."""
    p = get_sample("achromat")
    d = p.system.model_dump()
    d["wavelengths"] = [d["wavelengths"][d["primary_wavelength"]]]
    d["primary_wavelength"] = 0
    d["sensor"] = {"pixel_pitch_um": 3.45, "width_px": 96, "height_px": 72, "fill_factor": 1e-6}
    mono = type(p.system).model_validate(d)
    e5 = simulate_image(mono, p.custom_materials, "siemens", crop_px=96, oversample=1, grid=5, noise=False, psf_grid=64)
    raw = np.frombuffer(base64.b64decode(e5["images"]["optics"]), dtype="<u2").reshape(72, 96).astype(float)
    lam = mono.wavelengths[0].value
    r = li.render(mono, p.custom_materials, width=96, quality="full", channels_um=[lam] * 3, encode=False)
    assert r["framing"] == "sensor" and r["pixel_um"] == pytest.approx(3.45) and (r["width_px"], r["height_px"]) == (96, 72)
    lens = r["arrays"]["lens"]
    assert np.array_equal(lens[0], lens[1]) and np.array_equal(lens[1], lens[2])
    ours = lens[1][::-1]  # rows from the top, as the image simulation stores them
    assert rel_rms(ours / ours.max(), raw / raw.max()) < 0.02


def test_photo_keeps_its_orientation_and_colours():
    """Through an ideal lens the image is the photo: a red top-left quadrant stays red and top-left."""
    sysd = make_system(
        [{"thickness": None}, {"type": "ideal", "focal_length": 50.0, "thickness": 50.0, "is_stop": True, "semi_diameter": 30.0}, {"thickness": 0.0}],
        wavelengths=[{"value": 0.6563}, {"value": 0.5876}, {"value": 0.4861}],
        fields=[{"y": 0.0}, {"y": 10.0}],
        aperture={"type": "epd", "value": 5.0},
    )
    photo = np.full((48, 64, 3), 40, dtype=np.uint8)
    photo[:24, :32] = [255, 0, 0]
    r = li.render(sysd, (), photo=li.decode_photo(64, 48, base64.b64encode(photo.tobytes()).decode()), width=64, quality="preview")
    assert (r["width_px"], r["height_px"]) == (64, 48)
    for key in ("ideal", "lens"):
        img = np.frombuffer(base64.b64decode(r["images"][key]), dtype=np.uint8).reshape(48, 64, 3).astype(int)
        tl, br = img[6:18, 6:26].mean(axis=(0, 1)), img[30:42, 38:58].mean(axis=(0, 1))
        assert tl[0] > 200 and tl[1] < 30 and tl[2] < 30, (key, tl)
        assert abs(br - 40).max() <= 3, (key, br)  # sRGB 40 survives the linear-light round trip


def test_preview_time_on_the_doublet():
    """Acceptance criterion: about 0.3 s per update on the doublet (measured, generous bound for slow machines)."""
    import time

    p = get_sample("achromat")
    li.render(p.system, p.custom_materials, width=192)  # warm-up (imports)
    t0 = time.perf_counter()
    li.render(p.system, p.custom_materials, width=192, quality="preview")
    assert time.perf_counter() - t0 < 1.0


def test_a_newer_request_on_the_channel_stops_the_older_render():
    ch = li.Channels()
    first = ch.begin("tab-1")
    other = ch.begin("tab-2")
    assert not first() and not other()
    second = ch.begin("tab-1")
    assert first() and not second() and not other()  # other channels are not affected
    assert not ch.begin(None)()
    p = get_sample("achromat")
    with pytest.raises(li.Superseded):
        li.render(p.system, p.custom_materials, width=64, stale=first)


def test_live_image_api():
    client = TestClient(app)
    p = get_sample("achromat")
    body = {"system": p.system.model_dump(mode="json"), "width": 64, "zoom": 4, "center": [1, -1]}
    r = client.post("/api/v1/analysis/live-image", json=body)
    assert r.status_code == 200
    j = r.json()
    assert len(base64.b64decode(j["images"]["lens"])) == j["width_px"] * j["height_px"] * 3
    assert j["region_mm"]["size"][0] == pytest.approx(j["frame_mm"][0] / 4)
    photo = {"width": 2, "height": 2, "data": base64.b64encode(bytes(12)).decode()}
    assert client.post("/api/v1/analysis/live-image", json={**body, "photo": photo}).status_code == 200
    assert client.post("/api/v1/analysis/live-image", json={**body, "photo": {**photo, "data": "@@@"}}).status_code == 422
    assert client.post("/api/v1/analysis/live-image", json={**body, "photo": {**photo, "width": 3}}).status_code == 422
    assert client.post("/api/v1/analysis/live-image", json={**body, "zoom": 0.5}).status_code == 422
