"""Live colour image through the lens (docs/OPTICAL_ENGINE.md §8o).

The scene (a built-in test scene or the user's photo, sRGB) lies on the ideal (first-order, distortion-free)
image plane of the green channel. Each colour channel c is imaged at its own wavelength lambda_c, in linear light:
1. Mapping. An image point at radius r on the real image plane receives the scene from the ideal radius
   |k| g(v_c(r)), where v_c inverts the real chief-ray height of channel c (traced at lambda_c), g = tan for angle
   fields and the identity for object heights, and k is the green channel's first-order scale (near-axis chief
   ray). Lateral colour, the difference of the chief-ray heights between wavelengths, therefore displaces the
   channels against each other: the colour fringes. The heights are traced at a few fields per channel and
   interpolated by a cubic spline (smooth, odd functions of the field).
2. Relative illumination (green channel, imaging.relative_illumination) multiplies the scene.
3. Blur. Monochromatic FFT PSFs at lambda_c (scalar diffraction; their defocus against the image surface carries
   the axial colour) at a g x g net of field points over the shown region, each centred on the channel's own chief
   ray and integrated over the output pixels: the native PSF samples (pitch <= half a pixel) are binned into the
   pixel cells, so a PSF smaller than a pixel keeps all of its energy. Every source pixel is blurred by the
   bilinearly blended PSFs of its position (the source weights sum to one, as in imaging.py), so each channel
   conserves its energy.
4. Display. Linear light to sRGB (IEC 61966-2-1) with the same exposure for the ideal and the lens image; no
   sensor pixels or noise (that is the image simulation of imaging.py).

Framing: the sensor when one is defined, otherwise the largest rectangle of the scene's aspect inside the image
circle of the largest field (green real chief ray). A zoom shows a region of the frame (1/zoom of its width) at the
same output size, so aberrations smaller than the overview's pixels become visible.
"""

from __future__ import annotations

import base64
import math
from functools import lru_cache
from typing import Callable

import numpy as np

from ..model import OpticalSystem, Wavelength
from ..paraxial import compute_pupil
from ..system import compile_system, CompiledSystem, NotApplicable, SystemError_
from .imaging import SCENES, _along, _field_direction, _object_measure, _system_field, relative_illumination, scene, with_object_space_fields

#: default channel wavelengths (um) when the system has fewer than three: Fraunhofer C, d and F
DEFAULT_RGB = (0.6562725, 0.5875618, 0.4861327)
#: quality presets: PSF nodes per side, starting and largest pupil samples per side, scene samples per pixel side, RI points,
#: kernel half-size cap (pixels), the largest wavefront step between pupil samples (waves), the native PSF samples
#: per output pixel (at least) for the binning, and whether pixels of 2 lambda N or more use the geometric PSF (the
#: diffraction structure is then smaller than half a pixel), and whether the relative illumination is traced beyond
#: the largest field (the kernel margin; otherwise the field-edge value continues)
QUALITY = {
    "preview": {"grid": 3, "psf_grid": 32, "max_grid": 128, "supersample": 2, "ri_points": 5, "max_half": 64, "max_step": 0.5, "bin": 4, "geometric_pixels": True, "ri_beyond": False},
    "full": {"grid": 5, "psf_grid": 64, "max_grid": 256, "supersample": 2, "ri_points": 9, "max_half": 128, "max_step": 0.25, "bin": 8, "geometric_pixels": False, "ri_beyond": True},
}
MAX_PHOTO_PX = 1024 * 1024


class Superseded(Exception):
    """A newer request of the same view arrived: this render stops (its result would be thrown away)."""


class Channels:
    """Generation counters per client channel (a browser tab's live image): starting a render makes the earlier ones
    of that channel stale, and they stop at their next check, so dragging a value never waits for a full-quality
    render that nobody will see. Only counters are kept, no model state."""

    def __init__(self, max_channels: int = 256):
        import threading

        self._gen: dict[str, int] = {}
        self._lock = threading.Lock()
        self.max_channels = max_channels

    def begin(self, channel: str | None) -> Callable[[], bool]:
        if not channel:
            return lambda: False
        with self._lock:
            if channel not in self._gen and len(self._gen) >= self.max_channels:
                self._gen.pop(next(iter(self._gen)))
            g = self._gen.get(channel, 0) + 1
            self._gen[channel] = g
        return lambda: self._gen.get(channel) != g
CHIEF_SAMPLES = 10  # traced fields per channel for the chief-ray height spline


def channel_wavelengths(system: OpticalSystem) -> list[float]:
    """Red, green and blue channel wavelengths (um): the longest, primary (or middle) and shortest system
    wavelength when there are three or more, else Fraunhofer C, d, F."""
    wls = [w.value for w in system.wavelengths]
    if len(wls) < 3:
        return list(DEFAULT_RGB)
    s = sorted(wls)
    prim = wls[system.primary_wavelength]
    g = prim if s[0] < prim < s[-1] else s[len(s) // 2]
    return [s[-1], g, s[0]]


def srgb_to_linear(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(v: np.ndarray) -> np.ndarray:
    v = np.clip(np.asarray(v, dtype=float), 0.0, 1.0)
    return np.where(v <= 0.0031308, 12.92 * v, 1.055 * np.power(v, 1 / 2.4) - 0.055)


@lru_cache(maxsize=2)
def decode_photo(width: int, height: int, data_b64: str) -> np.ndarray:
    """(height, width, 3) linear-light array from base64 RGB bytes (sRGB, row-major from the top row). Cached by
    content: while a design is dragged every request carries the same photo (read-only result)."""
    if width < 2 or height < 2 or width * height > MAX_PHOTO_PX:
        raise ValueError(f"Photo size {width} × {height} is outside 2…{MAX_PHOTO_PX} pixels")
    raw = base64.b64decode(data_b64, validate=True)
    if len(raw) != width * height * 3:
        raise ValueError(f"Photo data has {len(raw)} bytes, expected {width * height * 3} (RGB)")
    out = srgb_to_linear(np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3) / 255.0)
    out.flags.writeable = False
    return out


def _bilinear(img: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Sample img (h, w) at column u, row v (pixel centres at integers), clamped to the edges."""
    h, w = img.shape
    u = np.clip(u, 0.0, w - 1.0)
    v = np.clip(v, 0.0, h - 1.0)
    i0 = np.minimum(np.floor(u).astype(int), w - 2)
    j0 = np.minimum(np.floor(v).astype(int), h - 2)
    fu, fv = u - i0, v - j0
    return img[j0, i0] * (1 - fu) * (1 - fv) + img[j0, i0 + 1] * fu * (1 - fv) + img[j0 + 1, i0] * (1 - fu) * fv + img[j0 + 1, i0 + 1] * fu * fv


def photo_scene(photo: np.ndarray, half_w: float, half_h: float) -> Callable:
    """Scene function of a photo that covers the frame (2 half_w x 2 half_h mm) on the ideal image plane, centred,
    cropped to the frame's aspect; beyond the photo the edge pixels continue."""
    hp, wp = photo.shape[:2]
    s = max(2 * half_w / wp, 2 * half_h / hp)  # mm per photo pixel

    def f(x: np.ndarray, y: np.ndarray, c: int) -> np.ndarray:
        return _bilinear(photo[:, :, c], x / s + wp / 2.0 - 0.5, -y / s + hp / 2.0 - 0.5)

    return f


def builtin_scene(name: str, half_w: float, half_h: float) -> Callable:
    """A grey-level test scene of imaging.scene, the same in all three channels (white light)."""
    if name not in SCENES:
        raise ValueError(f"Unknown scene '{name}' (one of {', '.join(SCENES)})")

    def f(x: np.ndarray, y: np.ndarray, c: int) -> np.ndarray:
        return scene(name, x, y, half_w, half_h)

    f.grey = True  # the same in every channel
    return f


def mono_kernel(cs: CompiledSystem, field: tuple[float, float], wl: int, fnum: float, dx_um: float, grid: int, pupil, max_half: int, max_step: float, per_px: int = 4, max_grid: int = 256) -> tuple[np.ndarray, dict]:
    """Monochromatic intensity PSF integrated over output pixels of pitch dx_um, centred on the wavelength's own chief
    ray; unit sum. The pupil grid starts at `grid` and doubles (up to max_grid) until at most 1 % of the neighbouring
    pupil samples differ by more than `max_step` waves: a step of half a wave puts the ray of that sample at the edge
    of the FFT window (transverse aberration N lambda grid dW), so its light would alias. When even max_grid cannot
    hold the aberrations (the steps shrink as 1/grid), diffraction is negligible against them and the PSF is the
    geometric one of traced rays instead (geometric_kernel). The kernel spans the FFT window, at most max_half pixels
    each side, cropped to 99.9 % of the energy; `kept` is the PSF energy inside it. `step_waves` is the 99th
    percentile of the steps."""
    from .diffraction import pupil_function

    lam = float(cs.wavelengths[wl])
    g = grid
    while True:
        P, A, Wf = pupil_function(cs, field, wl, g, pupil)
        if A.sum() == 0:
            raise SystemError_(f"No rays of field ({field[0]:.4g}, {field[1]:.4g}) reach the image at {lam:g} µm")
        d = np.concatenate([np.abs(np.diff(Wf, axis=0)).ravel(), np.abs(np.diff(Wf, axis=1)).ravel()])
        d = d[np.isfinite(d)]
        over = float(np.mean(d > max_step)) if d.size else 0.0
        step = float(np.quantile(d, 0.99)) if d.size else 0.0
        if over <= 0.01:
            break
        if g >= max_grid or g * step / max_step > 1.05 * max_grid:
            return geometric_kernel(cs, field, wl, dx_um, pupil, max_half, step)
        g *= 2
    # native pitch: per_px samples per output pixel while the PSF is smaller than a pixel (binning accuracy), never
    # finer than lambda N / 8 (the PSF has no finer structure) and at least two samples per pixel
    lnf = lam * fnum
    dn_target = min(dx_um / 2.0, max(dx_um / per_px, lnf / 8.0))
    pad = max(2, int(math.ceil(lnf / dn_target)))
    M = g * pad
    big = np.zeros((M, M), dtype=complex)
    big[:g, :g] = P
    I = np.abs(np.fft.fftshift(np.fft.fft2(big))) ** 2
    dn = lam * fnum / pad
    half = int(min(max_half, max(1, math.ceil(0.5 * g * lam * fnum / dx_um))))
    ix = np.rint((np.arange(M) - M // 2) * dn / dx_um).astype(int) + half
    keep = (ix >= 0) & (ix <= 2 * half)
    # binning is separable: K = B I B^T with B the one-hot map of native samples to cells
    # (rows: y, columns: x, the pupil grid's orientation as in imaging.psf_kernel)
    B = np.zeros((2 * half + 1, int(keep.sum())))
    B[ix[keep], np.arange(B.shape[1])] = 1.0
    K = B @ I[np.ix_(keep, keep)] @ B.T
    total = float(I.sum())
    # crop to the smallest centred square that holds all but `tail` of the PSF energy (the FFT window is usually far
    # larger than the PSF of a corrected lens); the kept fraction is reported
    tail = 1e-3
    cum = np.array([K[half - h : half + h + 1, half - h : half + h + 1].sum() for h in range(half + 1)])
    h_need = int(np.argmax(cum >= cum[-1] - tail * total)) if cum[-1] > 0 else half
    K = K[half - h_need : half + h_need + 1, half - h_need : half + h_need + 1]
    s = K.sum()
    if s <= 0:
        raise SystemError_("The PSF falls outside its window")
    return K / s, {"grid": g, "step_waves": step, "aliased": False, "geometric": False, "kept": float(s / total)}


def geometric_kernel(cs: CompiledSystem, field: tuple[float, float], wl: int, dx_um: float, pupil, max_half: int, step: float = float("nan"), grid: int = 96) -> tuple[np.ndarray, dict]:
    """Geometric PSF: real rays of a uniform pupil grid (clipped by the apertures) binned into output pixels about the
    unclipped chief ray; unit sum. Used where the aberrations are many waves, so that diffraction does not matter."""
    from ..raytrace import trace_pupil
    from .wavefront import pupil_grid

    X, Y, inside = pupil_grid(grid)
    r = trace_pupil(cs, wl, field, X[inside], Y[inside], pupil)
    ch = trace_pupil(cs, wl, field, np.array([0.0]), np.array([0.0]), pupil, clip=False, obscure=False)
    if not np.any(r.ok) or not ch.ok[0]:
        raise SystemError_(f"No rays of field ({field[0]:.4g}, {field[1]:.4g}) reach the image")
    d = (r.image_xy()[r.ok] - ch.image_xy()[0]) * 1e3 / dx_um  # pixels (x, y)
    half = int(min(max_half, max(1, math.ceil(float(np.abs(d).max())) + 1)))
    ij = np.rint(d).astype(int) + half
    keep = np.all((ij >= 0) & (ij <= 2 * half), axis=1)
    K = np.zeros((2 * half + 1, 2 * half + 1))
    np.add.at(K, (ij[keep, 1], ij[keep, 0]), 1.0)  # rows: y, columns: x
    return K / K.sum(), {"grid": grid, "step_waves": step, "aliased": False, "geometric": True, "reason": "aberrations", "kept": float(keep.sum() / len(d))}


def _pad_kernel(K: np.ndarray, half: int) -> np.ndarray:
    h = (K.shape[0] - 1) // 2
    return np.pad(K, half - h) if h < half else K


def chief_height(cs: CompiledSystem, wl: int, v: float, pupil, direction: tuple[float, float] | None = None) -> float:
    """Signed real chief-ray height on the image surface (mm) of the object-space field of size v (true angle or height,
    fields.field_size) along `direction` (default the largest field's azimuth, imaging._field_direction), measured along
    it. The chief ray is a position reference: apertures and obscurations do not stop it (the relative illumination
    carries the vignetting)."""
    from ..raytrace import launch, trace

    direction = direction if direction is not None else _field_direction(cs)
    P, D, opl = launch(cs, wl, _along(cs, v, direction), np.array([0.0]), np.array([0.0]), pupil, object_units=True)
    r = trace(cs, wl, P, D, opl, clip=False, obscure=False)
    return float(r.image_xy()[0] @ np.asarray(direction, dtype=float)) if r.ok[0] else float("nan")


def chief_maps(cs: CompiledSystem, pupil, umax: float, r_need: float, infinite: bool, k: float, n: int = CHIEF_SAMPLES, direction: tuple[float, float] | None = None) -> tuple[list[np.ndarray], list[np.ndarray], list[str]]:
    """Real chief-ray height |h_c(v)| of the three channels on a dense field grid, from n traced fields between the
    axis and the largest field plus a few beyond it until the green chief ray reaches r_need, along `direction`
    (chief_height). The interpolated quantity is the smooth distortion factor h / (|k| g(v)) (1 on the axis; g = tan
    for angle fields (`infinite`, also with a finite object) or the identity), by a cubic spline. Each map ends at its
    first failed ray or turn-back (the map must be monotonic).
    Returns (fields, heights, notes) per channel."""
    from scipy.interpolate import CubicSpline

    direction = direction if direction is not None else _field_direction(cs)
    limit = 89.0 if infinite else 10.0 * umax
    vs = list(np.linspace(0.0, umax, n))
    hg = [0.0] + [abs(chief_height(cs, 1, float(v), pupil, direction)) for v in vs[1:]]
    for _ in range(3):  # beyond the largest field, while the green chief ray falls short of r_need
        last, vlast = hg[-1], vs[-1]
        if not (math.isfinite(last) and 0 < last < r_need and vlast < limit):
            break
        vmax = min(limit, vlast * r_need / last * 1.02)
        for v in np.linspace(vlast, vmax, 4)[1:]:
            vs.append(float(v))
            hg.append(abs(chief_height(cs, 1, float(v), pupil, direction)))
    vs = np.array(vs)
    notes: list[str] = []
    vd_out, hd_out = [], []
    for c in range(3):
        hs = hg if c == 1 else [0.0] + [abs(chief_height(cs, c, float(v), pupil, direction)) for v in vs[1:]]
        n_ok = 1
        while n_ok < len(hs) and math.isfinite(hs[n_ok]) and hs[n_ok] > hs[n_ok - 1]:
            n_ok += 1
        v_ok, h_ok = vs[:n_ok], np.array(hs[:n_ok])
        if n_ok < 2:
            raise SystemError_("Chief rays fail next to the axis")
        if n_ok >= 4:
            ideal = lambda v: abs(k) * (np.tan(np.radians(v)) if infinite else np.asarray(v, dtype=float))  # noqa: E731
            ratio = np.concatenate([[1.0], h_ok[1:] / ideal(v_ok[1:])])
            vd = np.linspace(0.0, v_ok[-1], 400)
            hd = ideal(vd) * CubicSpline(v_ok, ratio)(vd)
            j = 1
            while j < len(hd) and hd[j] > hd[j - 1]:
                j += 1
            vd, hd = vd[:j], hd[:j]
        else:
            vd, hd = v_ok, h_ok
        if n_ok < len(vs) and v_ok[-1] < umax:
            notes.append(f"Chief rays at {cs.wavelengths[c]:g} µm fail or turn back beyond {v_ok[-1]:.4g} {'°' if infinite else 'mm'}, inside the field")
        vd_out.append(vd)
        hd_out.append(hd)
    return vd_out, hd_out, notes


def mirror_symmetric(cs: CompiledSystem) -> bool:
    """True when the system is symmetric about the x-z and y-z planes, so the PSF of the field point (-x, y) is the
    mirror image of that of (x, y): axial, rotationally symmetric or biconic surfaces, no linear gratings, no crystals."""
    from ..surfaces import BiconicShape, OddShape, QShape, Shape

    return (
        cs.axial
        and all(type(s) in (Shape, OddShape, QShape, BiconicShape) for s in cs.shapes)
        and all(d is None or d.frequency == 0 for d in cs.does)
        and all(c is None for c in cs.crystal)
    )


def _frame(cs: CompiledSystem, aspect: float, umax: float, pupil, direction: tuple[float, float] | None = None) -> tuple[float, float]:
    sensor = cs.model.sensor
    if sensor is not None:
        p = sensor.pixel_pitch_um * 1e-3
        return sensor.width_px * p / 2.0, sensor.height_px * p / 2.0
    r0 = abs(chief_height(cs, 1, umax, pupil, direction))
    if not (math.isfinite(r0) and r0 > 0):
        raise NotApplicable("The chief ray of the largest field does not reach the image; the image needs a field of view")
    d = math.hypot(aspect, 1.0)
    return r0 * aspect / d, r0 / d


def _encode(rgb: np.ndarray) -> str:
    """(3, H, W) linear light, rows from the bottom (+y up) -> base64 sRGB bytes, rows from the top."""
    v = np.round(linear_to_srgb(rgb) * 255.0).astype(np.uint8)
    return base64.b64encode(np.ascontiguousarray(np.transpose(v[:, ::-1, :], (1, 2, 0))).tobytes()).decode("ascii")


def render(
    system: OpticalSystem,
    custom_materials=(),
    scene_fn: Callable | None = None,
    scene_name: str = "siemens",
    photo: np.ndarray | None = None,
    width: int = 192,
    quality: str = "preview",
    channels_um: list[float] | None = None,
    zoom: float = 1.0,
    center: tuple[float, float] = (0.0, 0.0),
    encode: bool = True,
    stale: Callable[[], bool] | None = None,
) -> dict:
    """The colour image through the lens (module notes). scene_fn(x, y, channel) -> linear values on the ideal image
    plane (mm) overrides the scene; `photo` is a (h, w, 3) linear-light array. zoom >= 1 shows 1/zoom of the frame;
    center (-1…1 each) places that region from one edge of the frame to the other. `stale()` true stops the render
    (Superseded) at the next step."""
    from scipy.signal import fftconvolve

    from .diffraction import _working_fnum

    if quality not in QUALITY:
        raise ValueError(f"quality must be one of {', '.join(QUALITY)}")
    q = QUALITY[quality]
    if not 16 <= width <= 1024:
        raise ValueError("width must be 16…1024 pixels")
    if not 1.0 <= zoom <= 256.0:
        raise ValueError("zoom must be 1…256")
    rgb_um = list(channels_um) if channels_um else channel_wavelengths(system)
    if len(rgb_um) != 3 or any(not (0.2 <= v <= 20.0) for v in rgb_um):
        raise ValueError("Three channel wavelengths between 0.2 and 20 µm are needed")
    # image-height fields resolve (at the system's own primary wavelength) to the object-space fields they mean
    m = with_object_space_fields(system, custom_materials).model_copy(deep=True)
    m.wavelengths = [Wavelength(value=v, weight=1.0) for v in rgb_um]
    m.primary_wavelength = 1
    cs = compile_system(m, custom_materials)
    pupil = compute_pupil(cs)
    infinite, umax = _object_measure(cs)  # infinite: angle fields (g = tan), also with a finite object
    if umax <= 0:
        raise NotApplicable("The live image needs an off-axis field (the field of view sets the frame)")
    direction = _field_direction(cs)  # the chief-ray maps follow the largest field's azimuth
    gfun = (lambda v: np.tan(np.radians(v))) if infinite else (lambda v: np.asarray(v, dtype=float))
    v0 = 1e-4 * umax
    h0 = chief_height(cs, 1, v0, pupil, direction)
    if not math.isfinite(h0):
        raise SystemError_("The near-axis chief ray fails")
    k = h0 / float(gfun(v0))
    sign = -1.0 if k < 0 else 1.0
    fnums = [_working_fnum(cs, c) for c in range(3)]
    aspect = (photo.shape[1] / photo.shape[0]) if photo is not None else 4.0 / 3.0
    half_w, half_h = _frame(cs, aspect, umax, pupil, direction)
    airy = 2.44 * max(rgb_um) * max(fnums) * 1e-3  # Airy disc diameter (mm)
    if 2.0 * math.hypot(half_w, half_h) < 8.0 * airy:
        raise NotApplicable(
            f"The field of view ({2e3 * math.hypot(half_w, half_h):.3g} µm across) holds fewer than 8 diffraction spots ({airy * 1e3:.3g} µm): "
            "the picture would be one blur; the PSF, POP and image-simulation views suit such a system"
        )
    # the shown region
    rw, rh = half_w / zoom, half_h / zoom
    cx = float(np.clip(center[0], -1.0, 1.0)) * (half_w - rw)
    cy = float(np.clip(center[1], -1.0, 1.0)) * (half_h - rh)
    W = int(width)
    H = max(8, int(round(W * half_h / half_w)))
    dx = 2.0 * rw / W
    corner = math.hypot(half_w, half_h)
    # chief-ray maps far enough for the largest possible margin
    cap = q["max_half"]
    r_far = math.hypot(abs(cx) + rw, abs(cy) + rh) + (2 * cap + 1) * dx * math.sqrt(2.0)
    def check():
        if stale is not None and stale():
            raise Superseded("A newer live-image request replaced this one")

    check()
    vmaps, hmaps, notes = chief_maps(cs, pupil, umax, max(r_far, corner), infinite, k, direction=direction)
    v_of_r = lambda c, r: np.interp(r, hmaps[c], vmaps[c])  # noqa: E731
    # PSF kernels at a gn x gn net of nodes over the region (a zoomed region spans little of the field: fewer nodes)
    gn = max(2, min(q["grid"], int(math.ceil(q["grid"] * 2.0 / zoom))))
    gxs = np.linspace(cx - rw, cx + rw, gn)
    gys = np.linspace(cy - rh, cy + rh, gn)
    sym = mirror_symmetric(cs)
    computed: dict = {}
    infos: list[dict] = []

    def kernel(c: int, x: float, y: float) -> np.ndarray:
        """PSF kernel of channel c at image point (x, y); with mirror symmetry the one of (|x|, |y|), flipped."""
        ax, ay = (abs(x), abs(y)) if sym else (x, y)
        key = (c, round(ax, 12), round(ay, 12))
        if key not in computed:
            check()
            r = math.hypot(ax, ay)
            vn = float(v_of_r(1, r))
            u = (ax / r, ay / r) if r > 0 else (0.0, 1.0)
            # the field of size vn along the point's azimuth (not vn times the azimuth in degrees: fields.field_along)
            field = _system_field(cs, _along(cs, sign * vn, u))
            if q["geometric_pixels"] and dx * 1e3 >= 2.0 * rgb_um[c] * fnums[c]:
                K, info = geometric_kernel(cs, field, c, dx * 1e3, pupil, cap, grid=48)
                info["reason"] = "pixels"
            else:
                K, info = mono_kernel(cs, field, c, fnums[c], dx * 1e3, q["psf_grid"], pupil, cap, q["max_step"], q["bin"], q["max_grid"])
            computed[key] = K
            infos.append(info)
        K = computed[key]
        if sym and x < 0:
            K = K[:, ::-1]
        if sym and y < 0:
            K = K[::-1, :]
        return K

    # every node gets a kernel (the blending weights must sum to one); a node beyond the last chief ray uses the PSF
    # at the end of the map in its direction (v_of_r holds the last field)
    node_k = {(iy, ix): [kernel(c, float(px_), float(py_)) for c in range(3)] for iy, py_ in enumerate(gys) for ix, px_ in enumerate(gxs)}
    half_k = max((K.shape[0] - 1) // 2 for ks in node_k.values() for K in ks)
    n_geo = sum(1 for i in infos if i["geometric"] and i.get("reason") == "aberrations")
    if n_geo:
        notes.append(f"{n_geo} of {len(infos)} PSFs are geometric (traced rays): their aberrations are too large for diffraction sampling at {q['max_grid']} × {q['max_grid']}, and diffraction is negligible against them")
    kept = min(i["kept"] for i in infos)
    if kept < 0.98:
        notes.append(f"The PSF kernels hold only {kept * 100:.3g} % of the PSF energy (the kernel is capped at {2 * cap + 1} pixels); the blur is underestimated — zoom out")
    # the computation grid: the region plus a margin that keeps all blurred light
    margin = 2 * half_k + 1
    nx, ny = W + 2 * margin, H + 2 * margin
    xs = cx + (np.arange(nx) - (nx - 1) / 2.0) * dx
    ys = cy + (np.arange(ny) - (ny - 1) / 2.0) * dx
    X, Y = np.meshgrid(xs, ys)
    R = np.hypot(X, Y)
    # only the shown region counts (rays may fail in the margin just beyond the largest field)
    r_shown = math.hypot(abs(cx) + rw, abs(cy) + rh)
    if r_shown - min(h[-1] for h in hmaps) > dx:  # a gap narrower than a pixel is not seen
        notes.append(f"Chief rays reach only {min(h[-1] for h in hmaps):.4g} mm from the axis; beyond it the image is dark")
    # relative illumination (green), as a function of the image radius through the green map
    # inside the field (its edge a sample, where vignetting often sets in) and a few fields beyond it for the margin
    check()
    ri_res = relative_illumination(cs, points=q["ri_points"], rings=6, wavelength=1, extent=1.0)
    ri_v, ri_vals = list(ri_res["field_values"]), list(ri_res["relative_illumination"])
    if q["ri_beyond"] and vmaps[1][-1] > umax * 1.001:
        beyond = relative_illumination(cs, points=4, rings=6, wavelength=1, extent=float(vmaps[1][-1]) / umax)
        ri_v += [v for v in beyond["field_values"] if v > umax]
        ri_vals += [x for v, x in zip(beyond["field_values"], beyond["relative_illumination"]) if v > umax]
    # beyond the last field that passes light the relative illumination is zero
    ri_vals = np.nan_to_num(np.asarray(ri_vals, dtype=float), nan=0.0)
    ri = np.interp(v_of_r(1, R), ri_v, ri_vals)
    # the scene
    if scene_fn is None:
        scene_fn = photo_scene(photo, half_w, half_h) if photo is not None else builtin_scene(scene_name, half_w, half_h)
    ss = q["supersample"]
    offs = [((i + 0.5) / ss - 0.5) * dx for i in range(ss)]
    reach = (np.abs(X - cx) <= rw + half_k * dx) & (np.abs(Y - cy) <= rh + half_k * dx)
    grey = getattr(scene_fn, "grey", False)
    geo, ideal = [], []
    for c in range(3):
        inside = R <= hmaps[c][-1]
        scale = np.where(R > 0, abs(k) * gfun(v_of_r(c, R)) / np.where(R > 0, R, 1.0), 1.0)
        acc = np.zeros_like(X)
        idl = np.zeros_like(X)
        for ox in offs:
            for oy in offs:
                acc += scene_fn((X + ox) * scale, (Y + oy) * scale, c)
                if not (grey and c > 0):
                    idl += scene_fn(X + ox, Y + oy, c)
        geo.append(acc / ss**2 * inside * reach * ri)
        ideal.append(ideal[0] if grey and c > 0 else idl / ss**2)
    # blur: every source pixel by the bilinearly blended PSFs of its position
    out = [np.zeros_like(X) for _ in range(3)]
    # source rows and columns that can hold light (the scene is zero beyond `reach`)
    rr = np.nonzero(reach.any(axis=1))[0]
    cc = np.nonzero(reach.any(axis=0))[0]
    for (iy, ix), ks in node_k.items():
        check()
        px_, py_ = gxs[ix], gys[iy]
        # separable bilinear weights; beyond the outer nodes the outermost PSFs continue
        wx = np.clip(1.0 - np.abs(xs - px_) / (gxs[1] - gxs[0]), 0.0, 1.0) if gn > 1 else np.ones_like(xs)
        wy = np.clip(1.0 - np.abs(ys - py_) / (gys[1] - gys[0]), 0.0, 1.0) if gn > 1 else np.ones_like(ys)
        if ix == 0:
            wx[xs < gxs[0]] = 1.0
        if ix == gn - 1:
            wx[xs > gxs[-1]] = 1.0
        if iy == 0:
            wy[ys < gys[0]] = 1.0
        if iy == gn - 1:
            wy[ys > gys[-1]] = 1.0
        # convolve only the node's support: out[r0 - h + i, c0 - h + j] += full convolution[i, j]
        cols = np.nonzero(wx > 0)[0]
        rows = np.nonzero(wy > 0)[0]
        c0, c1 = max(int(cols[0]), int(cc[0])), min(int(cols[-1]), int(cc[-1]))
        r0, r1 = max(int(rows[0]), int(rr[0])), min(int(rows[-1]), int(rr[-1]))
        if c1 < c0 or r1 < r0:
            continue
        wk = wy[r0 : r1 + 1, None] * wx[None, c0 : c1 + 1]
        for c in range(3):
            full = fftconvolve(wk * geo[c][r0 : r1 + 1, c0 : c1 + 1], _pad_kernel(ks[c], half_k), mode="full")
            out[c][r0 - half_k : r1 + 1 + half_k, c0 - half_k : c1 + 1 + half_k] += full
    nodes = len(node_k)
    crop = (slice(margin, margin + H), slice(margin, margin + W))
    lens = np.stack([o[crop] for o in out])
    ideal_img = np.stack([i[crop] for i in ideal])
    energy = [{"in": float(geo[c].sum()), "out": float(out[c].sum())} for c in range(3)]

    def colour_at(r: float) -> dict | None:
        """Lateral colour (red minus blue chief-ray radius) and distortion at image radius r (green)."""
        if r > hmaps[1][-1] * (1 + 1e-6):
            return None
        r = min(r, float(hmaps[1][-1]))  # the frame corner may sit exactly at the end of the map
        v = float(v_of_r(1, r))
        hs = [abs(chief_height(cs, c, v, pupil, direction)) for c in (0, 2)] if v > 0 else [0.0, 0.0]
        lat = (hs[0] - hs[1]) * 1e3 if all(math.isfinite(x) for x in hs) else None
        return {
            "radius_mm": r,
            "field": v,
            "lateral_colour_um": lat,
            "lateral_colour_px": lat / (dx * 1e3) if lat is not None else None,
            "distortion_percent": (r / (abs(k) * float(gfun(v))) - 1.0) * 100.0 if v > 0 else 0.0,
            "relative_illumination": float(np.interp(v, ri_v, ri_vals)),
        }

    res = {
        "width_px": W,
        "height_px": H,
        "pixel_um": dx * 1e3,
        "frame_mm": [2 * half_w, 2 * half_h],
        "region_mm": {"center": [cx, cy], "size": [2 * rw, 2 * rh]},
        "zoom": zoom,
        "framing": "sensor" if cs.model.sensor is not None else "image circle",
        "field_unit": "deg" if infinite else "mm",
        "channels_um": rgb_um,
        "quality": quality,
        "scene": "photo" if photo is not None else scene_name,
        "corner": colour_at(corner),
        "region": colour_at(math.hypot(cx + math.copysign(rw, cx or 1.0), cy + math.copysign(rh, cy or 1.0))),
        "energy": energy,
        "settings": {
            "grid": gn,
            "psf_grid": q["psf_grid"],
            "psf_grid_used": max(i["grid"] for i in infos if not i["geometric"]) if any(not i["geometric"] for i in infos) else None,
            "geometric_psfs": n_geo,
            "geometric_for_pixels": sum(1 for i in infos if i.get("reason") == "pixels"),
            "wavefront_step_p99_waves": max(i["step_waves"] for i in infos),
            "psf_energy_kept": kept,
            "supersample": ss,
            "kernel_half_px": half_k,
            "psf_nodes": nodes,
            "psf_computed": len(computed),
            "mirror_symmetry": sym,
            "chief_samples": CHIEF_SAMPLES,
        },
        "notes": notes,
        "method": "Red, green and blue channels at their own wavelengths: the scene on the green ideal image plane mapped through each channel's real chief-ray heights "
        "(lateral colour), times relative illumination, blurred by monochromatic FFT PSFs (axial colour) at a "
        f"{gn} × {gn} field net with energy-conserving bilinear blending, integrated over {dx * 1e3:.3g} µm pixels; linear light, sRGB display",
    }
    if encode:
        res["images"] = {"ideal": _encode(ideal_img), "lens": _encode(lens), "encoding": "sRGB bytes R, G, B per pixel, row-major from the top row"}
    else:
        res["arrays"] = {"ideal": ideal_img, "lens": lens, "x_mm": xs[margin : margin + W], "y_mm": ys[margin : margin + H]}
    return res
