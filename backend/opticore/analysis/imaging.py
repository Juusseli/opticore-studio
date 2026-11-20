"""Relative illumination, the image sensor and image simulation (docs/OPTICAL_ENGINE.md §8k).

Relative illumination (real rays, energy form). A flat field of uniform radiance L sends, from an object
element d mu (a solid angle for an object at infinity, an area otherwise), the power L G T d mu through the
system, where G is the object-side étendue density of the beam (its cross-section perpendicular to the
collimated beam, or its projected solid angle at a finite object point) and T the transmitted fraction
(vignetting, and with `transmission` the rays' Fresnel/coating/absorption transmission). That power lands
on the image area dA given by the real chief-ray map, so E = L G T / (dA / d mu) with, for rotational
symmetry, dA / dOmega = h' (dh'/dtheta) / sin(theta) (object at infinity) or dA / dA_obj = (h'/h)(dh'/dh)
(finite object; angle fields there differentiate through the object height h = tan(theta) |d0 + z_EP|). The field
runs along the azimuth of the largest field (theta its true angle, fields.field_size) and h' is the chief-ray landing
projected on that azimuth. G and T come from a Gaussian pupil quadrature with Jacobians of the launched rays (central differences,
step 1e-4 in pupil coordinates); dh' from central differences of the chief ray. RI = E / E(axis). Local
blur by aberrations does not change a flat field's irradiance, so the chief-ray map is the right area
element; for an ideal lens with the stop at the lens this gives cos^4 exactly at any aperture.

Sensor (model.Sensor): square pixels of pitch p whose sensitive area is a centred square of width
w = p sqrt(fill factor). Pixel MTF = |sinc(nu w)| along x and y (sinc x = sin(pi x)/(pi x)); Nyquist
frequency 1/(2p); system MTF = lens MTF x pixel MTF.

Image simulation. The scene is defined on the ideal (distortion-free, first-order) image plane. On a
sub-pixel grid (`oversample` sub-pixels per pixel) of the real image plane:
1. Distortion: each sub-pixel at radius r maps back to the field whose real chief ray lands at r (the
   chief-ray height table, monotonic), and from that field to its ideal image radius k g(v) (k from a
   near-axis chief ray, g = tan for angle fields, else the field value); the scene is sampled there.
2. Relative illumination multiplies the scene (irradiance = radiance x Omega_p).
3. Blur: polychromatic FFT PSFs (scalar diffraction, centred on each wavelength's chief ray, weighted by
   the wavelength weights) at the nodes of a grid x grid net over the sensor; each PSF is resampled onto
   the sub-pixel grid and normalised to unit sum. The image is sum_k (w_k . I) * K_k with bilinear node
   weights w_k (which sum to one): every source point is blurred by the interpolated PSF of its own
   position, and the total signal is conserved apart from what leaves the sensor.
4. Pixels: the sub-pixel image is convolved with the pixel's sensitive square (exactly, as the sinc
   transfer function in Fourier space) and sampled at the pixel centres.
5. Sensor signal: the brightest noiseless pixel reaches `exposure` x full well; shot noise (Poisson in
   electrons) and read noise (Gaussian) are added with a fixed seed; then clipped and quantised to the
   bit depth.
"""

from __future__ import annotations

import base64
import math

import numpy as np

from ..model import OpticalSystem, Sensor
from ..paraxial import compute_pupil
from ..raytrace import gauss_pupil, trace_pupil
from ..system import compile_system, CompiledSystem, NotApplicable, SystemError_

STEP = 1e-4  # pupil-coordinate step of the Jacobian stencil
SCENES = ("siemens", "bars", "grid", "checker", "edge")


# ----------------------------------------------------------------------------- relative illumination
# The object-space field is followed along the azimuth of the largest field (+y when every field is on the axis), as a
# size v (fields.field_size: the true field angle in degrees for angle fields, else the object height in mm) built by
# fields.field_along; image heights are the chief-ray landing projected on that azimuth. A field along x is therefore
# traced along x (an anamorphic lens rotated by 90 degrees gives the same numbers), and a diagonal angle field is not
# taken as hypot of its degree components.
def _object_fields(cs: CompiledSystem) -> list[tuple[float, float]]:
    from ..fields import object_field

    return [object_field(cs, f.x, f.y) for f in cs.model.fields]


def _object_measure(cs: CompiledSystem) -> tuple[bool, float]:
    """(angle fields, size of the largest object-space field: the true field angle in degrees or the object height in
    mm). Angle fields (fields.object_kind) include angle fields with a finite object."""
    from ..fields import field_size, object_kind

    kind = object_kind(cs)
    return kind == "angle", max(field_size(kind, *o) for o in _object_fields(cs))


def _field_direction(cs: CompiledSystem) -> tuple[float, float]:
    """Unit azimuth of the largest object-space field; +y when every field is on the axis."""
    from ..fields import field_direction, field_size, object_kind

    kind = object_kind(cs)
    obj = _object_fields(cs)
    big = max(obj, key=lambda o: field_size(kind, *o))
    return field_direction(kind, *big) or (0.0, 1.0)


def _along(cs: CompiledSystem, v: float, direction: tuple[float, float]) -> tuple[float, float]:
    """Object-space field of size v (degrees or mm) along the unit azimuth `direction`."""
    from ..fields import field_along, object_kind

    return field_along(object_kind(cs), v, *direction)


def _trace_obj(cs: CompiledSystem, wl: int, field: tuple[float, float], px, py, pupil, transmission: bool, obscure: bool = True):
    """Rays of the object-space field (degrees or mm) through pupil points (px, py)."""
    from ..raytrace import launch, trace

    P, D, opl = launch(cs, wl, field, px, py, pupil, object_units=True)
    return P, D, trace(cs, wl, P, D, opl, clip=True, fresnel=transmission, obscure=obscure)


def beam_etendue(cs: CompiledSystem, u: float, wl: int, rings: int = 8, transmission: bool = True, pupil=None, direction: tuple[float, float] = (0.0, 1.0)) -> tuple[float, float]:
    """(G T, unvignetted fraction) of the beam of the object-space field of size u along `direction`: its perpendicular
    cross-section (object at infinity, mm^2) or its projected solid angle at the object point (sr), times transmission."""
    pupil = pupil or compute_pupil(cs)
    px, py, w = gauss_pupil(rings)
    n = px.size
    PX = np.concatenate([px, px + STEP, px - STEP, px, px])
    PY = np.concatenate([py, py, py, py + STEP, py - STEP])
    P, D, r = _trace_obj(cs, wl, _along(cs, u, direction), PX, PY, pupil, transmission)
    if cs.model.surfaces[0].thickness is None:
        d0 = D[0] / np.linalg.norm(D[0])
        e1 = np.cross(d0, [1.0, 0.0, 0.0] if abs(d0[0]) < 0.9 else [0.0, 1.0, 0.0])
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(d0, e1)
        A, B = P @ e1, P @ e2
    else:
        Dl = cs.frames[0].to_local_dirs(D)
        A, B = Dl[:, 0], Dl[:, 1]
    Ax = (A[n : 2 * n] - A[2 * n : 3 * n]) / (2 * STEP)
    Ay = (A[3 * n : 4 * n] - A[4 * n :]) / (2 * STEP)
    Bx = (B[n : 2 * n] - B[2 * n : 3 * n]) / (2 * STEP)
    By = (B[3 * n : 4 * n] - B[4 * n :]) / (2 * STEP)
    J = np.abs(Ax * By - Ay * Bx)
    ok = r.ok[:n]
    T = r.intensity[:n] if transmission else np.ones(n)
    good = ok & np.isfinite(J) & np.isfinite(T)
    return float(math.pi * np.sum(w[good] * J[good] * T[good])), float(np.sum(w[good]))


def _chief_height(cs: CompiledSystem, wl: int, u: float, pupil, direction: tuple[float, float] = (0.0, 1.0)) -> float:
    """Signed real chief-ray height (mm) of the object-space field of size u along `direction`, measured along it."""
    # the chief ray is a reference: a central obscuration does not block it
    _P, _D, r = _trace_obj(cs, wl, _along(cs, u, direction), np.array([0.0]), np.array([0.0]), pupil, False, obscure=False)
    if not r.ok[0]:
        return float("nan")
    return float(r.image_xy()[0] @ np.asarray(direction, dtype=float))


def image_area_per_object_measure(cs: CompiledSystem, wl: int, u: float, du: float, pupil, direction: tuple[float, float] = (0.0, 1.0)) -> float:
    """dA_image / d mu_object from the real chief ray (rotational symmetry) of the field of size u along `direction`:
    h' (dh'/dtheta) / sin(theta) for an object at infinity (theta the true field angle in radians), (h'/h)(dh'/dh)
    for a finite object, the object height h(u) = u for object-height fields and h(u) = tan(u) |d0 + z_EP| for angle
    fields (the object point the chief ray at u through the entrance-pupil centre meets, raytrace launch), so that
    dh'/dh = (dh'/du) / (dh/du) with dh/du = |d0 + z_EP| sec^2(u); the near-axis limit at u = 0."""
    from ..fields import object_kind

    if u == 0.0:
        u = du
    hp = _chief_height(cs, wl, u + du, pupil, direction)
    hm = _chief_height(cs, wl, max(u - du, 0.0), pupil, direction) if u > du else _chief_height(cs, wl, u - du, pupil, direction)
    h0 = _chief_height(cs, wl, u, pupil, direction)
    if not all(math.isfinite(x) for x in (hp, hm, h0)):
        return float("nan")
    if cs.model.object_at_infinity:
        th, dth = math.radians(u), math.radians(du)
        dh = (hp - hm) / (2 * dth)
        return abs(h0 * dh / math.sin(th))
    dh = (hp - hm) / (2 * du)  # dh'/du (u in degrees or mm)
    if object_kind(cs) == "angle":
        L = abs(cs.model.surfaces[0].thickness + pupil.z_ep)
        if not (L > 0 and math.isfinite(L)):
            return float("nan")  # every angle field is the same object point
        th = math.radians(u)
        h = math.tan(th) * L
        dh_obj = L / math.cos(th) ** 2 * math.radians(1.0)  # dh/du per degree
        return abs(h0 / h * dh / dh_obj)
    return abs(h0 / u * dh)


def relative_illumination(cs: CompiledSystem, points: int = 11, rings: int = 8, transmission: bool = True, wavelength: int | None = None, extent: float = 1.0, direction: tuple[float, float] | None = None) -> dict:
    """Relative illumination from the axis to `extent` x the largest object-space field, along `direction` (a unit
    azimuth; default the largest field's, see the notes above `_object_fields`)."""
    angle, umax = _object_measure(cs)
    if umax <= 0.0:
        raise NotApplicable("Relative illumination needs an off-axis field")
    direction = tuple(direction) if direction is not None else _field_direction(cs)
    wl = cs.model.primary_wavelength if wavelength is None else wavelength
    pupil = compute_pupil(cs)
    vals = np.linspace(0.0, extent * umax, points)
    du = 1e-4 * umax
    E, frac, heights, etendue, mapping = [], [], [], [], []
    for v in vals:
        g, f = beam_etendue(cs, float(v), wl, rings, transmission, pupil, direction)
        jm = image_area_per_object_measure(cs, wl, float(v), du, pupil, direction)
        etendue.append(g)
        mapping.append(jm)
        frac.append(f)
        E.append(g / jm if jm > 0 and math.isfinite(jm) else float("nan"))
        heights.append(_chief_height(cs, wl, float(v), pupil, direction))
    E = np.array(E)
    if not (math.isfinite(E[0]) and E[0] > 0):
        raise SystemError_("The on-axis beam does not reach the image")
    ri = E / E[0]
    return {
        "field_values": vals.tolist(),
        "field_unit": "deg" if angle else "mm",
        "object_space": True,
        "direction": [float(direction[0]), float(direction[1])],
        "image_heights_mm": heights,
        "relative_illumination": ri.tolist(),
        "etendue_relative": (np.array(etendue) / etendue[0]).tolist(),
        "area_ratio_relative": (np.array(mapping) / mapping[0]).tolist(),
        "unvignetted_fraction": frac,
        "wavelength": wl,
        "settings": {"points": points, "rings": rings, "transmission": transmission},
        "method": "Flat-field irradiance from energy: object-side beam étendue (Gaussian pupil quadrature, launched-ray Jacobians)"
        + (" × ray transmission (Fresnel, coatings, absorption)" if transmission else "")
        + " ÷ image area per object solid angle or area (real chief-ray map); relative to the axis; along the largest field's direction; Lambertian object; rotational symmetry",
    }


# ----------------------------------------------------------------------------- sensor
def pixel_mtf(nu, sensor: Sensor) -> np.ndarray:
    """|sinc(nu w)| of the pixel's sensitive width w = pitch sqrt(fill factor) (nu in cycles/mm)."""
    w = sensor.pixel_pitch_um * 1e-3 * math.sqrt(sensor.fill_factor)
    return np.abs(np.sinc(np.asarray(nu, dtype=float) * w))


def nyquist(sensor: Sensor) -> float:
    return 1.0 / (2.0 * sensor.pixel_pitch_um * 1e-3)


def sensor_mtf_terms(mtf_result: dict, sensor: Sensor) -> dict:
    """Pixel MTF, Nyquist and system MTF (lens x pixel) on an MTF analysis's frequency axis."""
    from .diffraction import pixel_mtf_along

    nu = np.asarray(mtf_result["frequency_cyc_per_mm"])
    pm = pixel_mtf(nu, sensor)
    w = sensor.pixel_pitch_um * 1e-3 * math.sqrt(sensor.fill_factor)

    def along(f: dict, key: str) -> np.ndarray:
        # a square pixel's MTF depends on the cut's direction: T and S of a diagonal field are not cuts along x or y
        d = f.get(f"{key}_direction")
        return pm if d is None else pixel_mtf_along(nu, w, d)

    return {
        "nyquist_cyc_per_mm": nyquist(sensor),
        "pixel_mtf": pm.tolist(),
        "fields": [{"field": f["field"], "tangential": (np.asarray(f["tangential"]) * along(f, "tangential")).tolist(), "sagittal": (np.asarray(f["sagittal"]) * along(f, "sagittal")).tolist()} for f in mtf_result["fields"]],
        "pitch_um": sensor.pixel_pitch_um,
        "fill_factor": sensor.fill_factor,
    }


# ----------------------------------------------------------------------------- PSF kernels
def psf_kernel(cs: CompiledSystem, field: tuple[float, float], dx_um: float, half: int, grid: int = 64, pupil=None) -> np.ndarray:
    """Polychromatic intensity PSF on a (2 half + 1)^2 grid of pitch dx_um centred on the primary chief ray,
    unit sum. Each wavelength's FFT PSF (about its own chief ray) is shifted by its chief-ray offset."""
    from .diffraction import _working_fnum, pupil_function

    pupil = pupil or compute_pupil(cs)
    model = cs.model
    weights = np.array([w.weight for w in model.wavelengths], dtype=float)
    prim = model.primary_wavelength
    ch0 = trace_pupil(cs, prim, field, np.array([0.0]), np.array([0.0]), pupil, clip=False)
    if not ch0.ok[0]:
        raise SystemError_(f"The chief ray of field ({field[0]:.4g}, {field[1]:.4g}) fails")
    ref = ch0.image_xy()[0] * 1e3  # um
    out = np.zeros((2 * half + 1, 2 * half + 1))
    tx = (np.arange(-half, half + 1)) * dx_um
    sub = np.array([-1 / 3, 0.0, 1 / 3]) * dx_um  # 3 x 3 samples per target cell
    for w in range(len(model.wavelengths)):
        if weights[w] <= 0:
            continue
        lam = float(cs.wavelengths[w])
        fn = _working_fnum(cs, w)
        pad = max(4, int(math.ceil(2.0 * lam * fn / dx_um)))  # native pitch <= dx/2
        P, A, _W = pupil_function(cs, field, w, grid, pupil)
        if A.sum() == 0:
            continue
        Mn = grid * pad
        big = np.zeros((Mn, Mn), dtype=complex)
        big[:grid, :grid] = P
        I = np.abs(np.fft.fftshift(np.fft.fft2(big))) ** 2
        dn = lam * fn / pad
        ch = trace_pupil(cs, w, field, np.array([0.0]), np.array([0.0]), pupil, clip=False)
        off = (ch.image_xy()[0] * 1e3 - ref) if ch.ok[0] else np.zeros(2)
        # bilinear samples of the native PSF at the target cells (x: columns, y: rows)
        acc = np.zeros_like(out)
        for sy in sub:
            for sx in sub:
                gx = (tx[None, :] + sx - off[0]) / dn + Mn // 2
                gy = (tx[:, None] + sy - off[1]) / dn + Mn // 2
                i0 = np.floor(gx).astype(int)
                j0 = np.floor(gy).astype(int)
                fx, fy = gx - i0, gy - j0
                valid = (i0 >= 0) & (i0 < Mn - 1) & (j0 >= 0) & (j0 < Mn - 1)
                i0c, j0c = np.clip(i0, 0, Mn - 2), np.clip(j0, 0, Mn - 2)
                v = (I[j0c, i0c] * (1 - fx) * (1 - fy) + I[j0c, i0c + 1] * fx * (1 - fy) + I[j0c + 1, i0c] * (1 - fx) * fy + I[j0c + 1, i0c + 1] * fx * fy)
                acc += np.where(valid, v, 0.0)
        s = acc.sum()
        if s > 0:
            out += weights[w] * acc / s
    tot = out.sum()
    if tot <= 0:
        raise SystemError_("No light reaches the image for a PSF node")
    return out / tot


# ----------------------------------------------------------------------------- scenes
def scene(name: str, x: np.ndarray, y: np.ndarray, half_w: float, half_h: float) -> np.ndarray:
    """Test scenes on the ideal image plane (mm), values 0..1."""
    a = min(half_w, half_h)
    if name == "siemens":
        out = np.full(x.shape, 0.5)
        for cx, cy, R in ((0.0, 0.0, 0.42 * a), (0.62 * half_w, 0.62 * half_h, 0.25 * a), (-0.62 * half_w, 0.62 * half_h, 0.25 * a), (0.62 * half_w, -0.62 * half_h, 0.25 * a), (-0.62 * half_w, -0.62 * half_h, 0.25 * a)):
            dx, dy = x - cx, y - cy
            inside = dx * dx + dy * dy <= R * R
            # the spokes only where they are seen (arctan2 over the whole grid is the slow part)
            out[inside] = 0.5 + 0.5 * np.sign(np.sin(18 * np.arctan2(dy[inside], dx[inside])))
        return out
    if name == "bars":
        # three-bar groups: periods from a / 6 down to a / 60 in rows, horizontal and vertical bars
        out = np.zeros(x.shape)
        periods = a / np.geomspace(6, 60, 6)
        for k, per in enumerate(periods):
            cy = half_h * (0.75 - 0.3 * k)
            for cx, vertical in ((-0.45 * half_w, True), (0.45 * half_w, False)):
                u = (x - cx) if vertical else (y - cy)
                v = (y - cy) if vertical else (x - cx)
                inside = (np.abs(u) <= 2.5 * per) & (np.abs(v) <= 2.5 * per)
                bar = (np.mod(u + 2.5 * per, 2 * per) < per)
                out = np.where(inside & bar, 1.0, out)
        return out
    if name == "grid":
        sp = a / 4.0
        gx = np.round(x / sp) * sp
        gy = np.round(y / sp) * sp
        return (np.hypot(x - gx, y - gy) <= 0.08 * sp).astype(float)
    if name == "checker":
        sp = a / 5.0
        return (np.mod(np.floor(x / sp) + np.floor(y / sp), 2) == 0).astype(float)
    if name == "edge":
        t = math.radians(5.0)
        return (x * math.cos(t) - y * math.sin(t) > 0).astype(float) * 0.8 + 0.1
    raise ValueError(f"Unknown scene '{name}' (one of {', '.join(SCENES)})")


def pixel_aperture(img: np.ndarray, dx: float, w: float) -> np.ndarray:
    """Signal of a square sensitive area of width w centred on every sample: the image (energy per sample of
    pitch dx) convolved with the box, exactly as its transfer function sinc(nu w) on the periodic grid."""
    ny, nx = img.shape
    hx = np.sinc(np.fft.fftfreq(nx, d=dx) * w)
    hy = np.sinc(np.fft.fftfreq(ny, d=dx) * w)
    return np.real(np.fft.ifft2(np.fft.fft2(img) * hy[:, None] * hx[None, :])) * (w / dx) ** 2


def sensor_signal(e_clean: np.ndarray, sensor: Sensor, noise: bool = True, seed: int = 1) -> np.ndarray:
    """Digital numbers of a sensor: shot noise (Poisson in electrons) and read noise (Gaussian, e-) added to the
    noiseless electron counts, clipped to [0, full well] and quantised to the bit depth."""
    e = np.asarray(e_clean, dtype=float)
    if noise:
        rng = np.random.default_rng(seed)
        e = rng.poisson(np.clip(e, 0.0, None)).astype(float) + rng.normal(0.0, sensor.read_noise_e, e.shape)
    e = np.clip(e, 0.0, sensor.full_well_e)
    return np.round(e / sensor.full_well_e * (2**sensor.bit_depth - 1))


def _b64(img: np.ndarray, full: float) -> str:
    v = np.clip(np.round(img / full * 65535.0), 0, 65535).astype("<u2")
    return base64.b64encode(v.tobytes()).decode("ascii")


# ----------------------------------------------------------------------------- simulation
def _distortion_table(cs: CompiledSystem, wl: int, r_need: float, pupil) -> dict:
    """Real chief-ray radius against the object-space field size (true angle or height) along the largest field's
    azimuth, extended until it covers r_need (or rays fail)."""
    angle, fmax = _object_measure(cs)
    if not fmax > 0:
        raise NotApplicable("Image simulation needs an off-axis field: the largest field sets the scale of the distortion map and the relative illumination")
    direction = _field_direction(cs)
    g = (lambda v: math.tan(math.radians(v))) if angle else (lambda v: v)
    v0 = 1e-4 * fmax
    h0 = _chief_height(cs, wl, v0, pupil, direction)
    if not math.isfinite(h0):
        raise SystemError_("The near-axis chief ray fails")
    if h0 == 0.0:
        raise NotApplicable("The system forms no image of an off-axis point (the chief ray height on the image does not change with the field)")
    k = h0 / g(v0)
    sign = -1.0 if k < 0 else 1.0
    vs, rr, ri = [0.0], [0.0], [0.0]
    v, step = 0.0, fmax / 40.0
    limit = (89.0 if angle else 10.0 * fmax)
    while rr[-1] < r_need and v < limit:
        v = min(v + step, limit)
        hv = _chief_height(cs, wl, v, pupil, direction)
        if not math.isfinite(hv):
            break
        r_real = abs(hv)
        if r_real <= rr[-1]:
            break  # not monotonic any more
        vs.append(v)
        rr.append(r_real)
        ri.append(abs(k * g(v)))
    return {"v": np.array(vs), "r_real": np.array(rr), "r_ideal": np.array(ri), "k": k, "sign": sign, "covered": rr[-1]}


def with_object_space_fields(system: OpticalSystem, custom_materials=()) -> OpticalSystem:
    """The same system with image-height fields (real or paraxial) replaced by the object-space fields they resolve to
    (fields.object_field: angles for an object at infinity, object heights otherwise). The image simulations map and
    blur by object-space fields; the physics is unchanged."""
    from ..fields import IMAGE_FIELDS, object_field, object_kind

    if system.field_type not in IMAGE_FIELDS:
        return system
    cs = compile_system(system, custom_materials)
    d = system.model_dump()
    d["field_type"] = object_kind(cs)
    for f, fd in zip(system.fields, d["fields"]):
        fd["x"], fd["y"] = object_field(cs, f.x, f.y)
    return OpticalSystem.model_validate(d)


def _system_field(cs: CompiledSystem, obj: tuple[float, float]) -> tuple[float, float]:
    """System field units for an object-space field (the simulations convert image-height fields first)."""
    from ..fields import IMAGE_FIELDS

    if cs.model.field_type in IMAGE_FIELDS:
        raise ValueError("Internal: image-height fields must be converted with with_object_space_fields first")
    return obj


def simulate_image(system: OpticalSystem, custom_materials=(), scene_name: str = "siemens", crop_px: int = 256, oversample: int = 3, grid: int = 5, exposure: float = 0.7, noise: bool = True, seed: int = 1, psf_grid: int = 64) -> dict:
    from scipy.signal import fftconvolve

    if scene_name not in SCENES:
        raise ValueError(f"Unknown scene '{scene_name}'")
    if oversample < 1 or oversample % 2 == 0:
        raise ValueError("oversample must be an odd number >= 1")
    cs = compile_system(with_object_space_fields(system, custom_materials), custom_materials)
    model = cs.model
    sensor = model.sensor or Sensor()
    wl = model.primary_wavelength
    pupil = compute_pupil(cs)
    W = min(sensor.width_px, crop_px)
    H = min(sensor.height_px, crop_px)
    p = sensor.pixel_pitch_um * 1e-3
    s = oversample
    dxs = p / s
    half_w, half_h = W * p / 2.0, H * p / 2.0
    r_need = math.hypot(half_w, half_h)
    dist = _distortion_table(cs, wl, r_need, pupil)
    notes = []
    if dist["covered"] < r_need * (1 - 1e-9):
        notes.append(f"Chief rays reach only {dist['covered']:.4g} mm of the {r_need:.4g} mm sensor half-diagonal; beyond it the image is dark")
    # PSF kernel size: the FFT window of the PSF, at most 48 sub-pixels each side
    from .diffraction import _working_fnum

    fn = _working_fnum(cs, wl)
    lam = float(cs.wavelengths[wl])
    half_k = int(min(48, max(4, math.ceil(0.45 * psf_grid * lam * fn * 1e-3 / dxs))))
    # light from up to one kernel radius outside the sensor reaches it; the padding (two radii) keeps all of
    # the blurred light on the grid, so the convolution conserves the signal exactly
    margin = 2 * half_k + s
    nx, ny = W * s + 2 * margin, H * s + 2 * margin
    xs = (np.arange(nx) - (nx - 1) / 2.0) * dxs
    ys = (np.arange(ny) - (ny - 1) / 2.0) * dxs
    X, Y = np.meshgrid(xs, ys)
    R = np.hypot(X, Y)
    inside = R <= dist["covered"]
    vR = np.interp(R, dist["r_real"], dist["v"])
    r_id = np.interp(vR, dist["v"], dist["r_ideal"])
    scale = np.where(R > 0, r_id / np.where(R > 0, R, 1.0), 1.0)
    # the scene is defined on the ideal image plane; sample it with 2 x 2 supersampling of each sub-pixel
    geo = np.zeros_like(X)
    for ox in (-0.25, 0.25):
        for oy in (-0.25, 0.25):
            geo += scene(scene_name, (X + ox * dxs) * scale, (Y + oy * dxs) * scale, half_w, half_h)
    reach = (np.abs(X) <= half_w + half_k * dxs) & (np.abs(Y) <= half_h + half_k * dxs)
    geo = geo / 4.0 * inside * reach
    ideal_full = geo.copy()
    # relative illumination along the radius
    ri_res = relative_illumination(cs, points=9, extent=max(1e-9, float(dist["v"][-1]) / _object_measure(cs)[1]))
    ri = np.interp(vR, ri_res["field_values"], ri_res["relative_illumination"])
    geo = geo * ri
    # PSF net over the sensor (node positions in image coordinates)
    gxs = np.linspace(-half_w, half_w, grid)
    gys = np.linspace(-half_h, half_h, grid)
    out = np.zeros_like(geo)
    kernels = []
    for iy, py_ in enumerate(gys):
        for ix, px_ in enumerate(gxs):
            # every node gets a kernel (the blending weights must sum to one): beyond the last chief ray the PSF at
            # the end of the map in this direction (np.interp holds the last field)
            r = math.hypot(px_, py_)
            v = float(np.interp(r, dist["r_real"], dist["v"]))
            u = (px_ / r, py_ / r) if r > 0 else (0.0, 1.0)
            # the field of size v along the node's azimuth (not v times the azimuth in degrees: fields.field_along)
            field = _system_field(cs, _along(cs, dist["sign"] * v, u))
            K = psf_kernel(cs, field, dxs * 1e3, half_k, psf_grid, pupil)
            # bilinear weight of this node over the sub-pixel grid
            wx = np.clip(1.0 - np.abs(X - px_) / (gxs[1] - gxs[0]), 0.0, 1.0) if grid > 1 else np.ones_like(X)
            wy = np.clip(1.0 - np.abs(Y - py_) / (gys[1] - gys[0]), 0.0, 1.0) if grid > 1 else np.ones_like(Y)
            # beyond the outer nodes the outermost PSFs continue
            if ix == 0:
                wx = np.where(X < gxs[0], 1.0, wx)
            if ix == grid - 1:
                wx = np.where(X > gxs[-1], 1.0, wx)
            if iy == 0:
                wy = np.where(Y < gys[0], 1.0, wy)
            if iy == grid - 1:
                wy = np.where(Y > gys[-1], 1.0, wy)
            wk = wx * wy
            out += fftconvolve(wk * geo, K, mode="same")
            kernels.append({"x_mm": float(px_), "y_mm": float(py_), "field": [float(field[0]), float(field[1])], "peak": float(K.max())})
    total_in = float(geo.sum())
    # pixel aperture, then sample at the pixel centres
    w_ap = p * math.sqrt(sensor.fill_factor)
    pixel = pixel_aperture(out, dxs, w_ap)
    ideal_pix = pixel_aperture(ideal_full, dxs, w_ap)
    cy0 = margin + s // 2
    cx0 = margin + s // 2
    sel_y = cy0 + s * np.arange(H)
    sel_x = cx0 + s * np.arange(W)
    # rows from the top (+y) down, as images are stored
    S = pixel[np.ix_(sel_y, sel_x)][::-1]
    S_ideal = ideal_pix[np.ix_(sel_y, sel_x)][::-1]
    crop = (slice(margin, margin + H * s), slice(margin, margin + W * s))
    on_sensor = float(out[crop].sum())
    smax = float(S.max())
    if smax <= 0:
        raise SystemError_("The simulated image is dark")
    fw = sensor.full_well_e
    e_clean = S / smax * exposure * fw
    dn = sensor_signal(e_clean, sensor, noise, seed)
    levels = 2**sensor.bit_depth - 1
    ideal_e = S_ideal / max(float(S_ideal.max()), 1e-300) * exposure * fw
    return {
        "width_px": W,
        "height_px": H,
        "pixel_pitch_um": sensor.pixel_pitch_um,
        "sensor_defined": model.sensor is not None,
        "scene": scene_name,
        "images": {
            "ideal": _b64(ideal_e, fw),
            "optics": _b64(e_clean, fw),
            "sensor": _b64(dn / levels * fw, fw),
            "encoding": "uint16 little-endian, row-major from the top row (+y up), 65535 = full well",
        },
        "energy": {"in_scene_x_ri": total_in, "on_sensor": on_sensor, "blurred_total": float(out.sum()), "kept_fraction": on_sensor / total_in if total_in > 0 else None},
        "relative_illumination": {"field_values": ri_res["field_values"], "relative_illumination": ri_res["relative_illumination"], "image_heights_mm": ri_res["image_heights_mm"]},
        "distortion": {"r_real_mm": dist["r_real"].tolist(), "r_ideal_mm": dist["r_ideal"].tolist()},
        "psf_nodes": kernels,
        "nyquist_cyc_per_mm": nyquist(sensor),
        "settings": {"oversample": s, "grid": grid, "exposure": exposure, "noise": noise, "seed": seed, "psf_grid": psf_grid, "kernel_half_subpixels": half_k},
        "notes": notes + ([] if model.sensor is not None else ["No sensor is defined: a default 3.45 µm, 640 × 480 sensor is used"]),
        "method": "Scene on the ideal image plane, mapped through the real chief-ray distortion, times relative illumination; blurred by polychromatic FFT PSFs at a grid of field points with bilinear blending of the source weights (energy conserving); integrated over the pixels' sensitive squares; shot and read noise; quantised",
    }
