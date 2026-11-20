"""General light sources and receivers for the non-sequential trace.

Sources and detectors are building blocks, not device presets: a fibre end,
an LED, a laser diode, a flash lamp, a sensor or a receiving fibre are
combinations of a placement, an emitting (or receiving) shape and an
angular law.

Placement (both)
    position (mm, global optical frame) and rotation (degrees, XYZ about the
    local axes: p_global = T Rx Ry Rz p_local, the same convention as CAD
    models). With `anchor` (a surface id) position and rotation are relative
    to that surface's vertex frame (p_global = O + M (T Rx Ry Rz p_local)),
    so the source or detector follows the surface when thicknesses change
    (for the object surface: its vertex at -d0 on the axis). A source emits about its local +z axis; a detector receives
    light travelling along its local +z axis (with zero rotation: light
    travelling in the direction of the optical axis).
    `aim` (a point in the frame of the position) points the local +z axis at
    that point: with d = (aim - position)/|aim - position| the angles are
    a = atan2(-d_y, d_z), b = asin(d_x) (then Rx(a) Ry(b) z = d) and the third
    angle rotation_deg[2] stays the roll about the axis; the first two are not
    used. The source keeps pointing at the aim point when it moves.

Gaussian beam source (kind "gaussian_beam")
    waist radii w0x, w0y (1/e^2 intensity), M^2 >= 1 and the waist position
    z_w along +z from the source plane (> 0: converging to a waist ahead; < 0:
    diverging from a waist behind). For each ray's wavelength the far-field
    1/e^2 half-angle is theta = M^2 lambda / (pi n w0), with lambda the
    wavelength (in air, as every wavelength) and n the index of the medium
    the source emits into, relative to that air: the surrounding air or the
    solid the source lies in (non-sequential trace), the object space (direct
    path). The Rayleigh range is then pi n w0^2 / (M^2 lambda). Positions x_w and
    direction tangents t at the waist are Gaussian with standard deviations
    w0/2 and theta/2; the ray starts on the source plane at x_w - z_w t, so
    position and direction are correlated. The second moments follow
    w(z)^2 = w0^2 + theta^2 (z - z_w)^2 exactly (the embedded-Gaussian ray
    model of a beam of quality M^2; no interference or diffraction).

Source (all sampled by seeded Monte Carlo; every ray carries power/rays)
    shape    point | disk (radius size_x) | rectangle (size_x * size_y) |
             sphere (volume, radius size_x) | box (volume, size_x/y/z)
    spatial  uniform | gaussian: intensity exp(-2 (x^2/wx^2 + y^2/wy^2)) on
             disk/rectangle (1/e^2 radii; truncated by the shape)
    angular  (theta from local +z, azimuth uniform)
             collimated    all rays along +z
             isotropic     uniform over the full sphere (4 pi)
             lambertian    I ~ cos(theta) (hemisphere)
             cosine_power  I ~ cos^n(theta)
             cone          uniform radiance within half_angle_deg (uniform in
                           solid angle)
             gaussian      direction tangents tan(theta_x), tan(theta_y)
                           Gaussian with 1/e^2 half-angles gaussian_x_deg,
                           gaussian_y_deg (elliptical beams)
             table         rotationally symmetric radiant intensity I(theta)
                           from [angle_deg, relative intensity] rows
             lambertian, cosine_power and gaussian are truncated at
             half_angle_deg when it is below 90 degrees.
    spectrum wavelengths with weights (empty: the system's wavelengths and
             weights); rays are split between wavelengths in proportion to
             the weights (largest remainder), so the spectral split is exact.
    A beam with Gaussian spatial and Gaussian angular laws (waist w0 and
    divergence theta0 = lambda / (pi w0)) is the geometric (Wigner)
    ray-ensemble model of a Gaussian beam: its second moments propagate as
    the Gaussian beam (w^2 = w0^2 + theta0^2 z^2 in free space and through
    paraxial optics). It has no interference or diffraction.

Detector (analytic plane z = 0 in its local frame)
    shape       circle (radius size_x) | rectangle (size_x * size_y)
    acceptance  half-angle to the local +z axis (degrees): light hitting
                the area outside this cone is "rejected" (e.g. outside a
                fibre's acceptance NA: theta_max = asin(NA / n))
    mode        absorb (rays end there) | monitor (recorded, rays continue)
    two_sided   also receive light travelling along -z; otherwise light
                arriving from the back is blocked (absorb mode) or ignored
                (monitor mode)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .model import Wavelength, new_id


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Placement(StrictModel):
    position: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    rotation_deg: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    anchor: str | None = Field(None, description="surface id: relative to that surface's vertex frame (None: global optical frame)")
    aim: list[float] | None = Field(None, min_length=3, max_length=3, description="point the local +z axis at this point (frame of the position); rotation_deg[2] is the roll")


class LightSource(StrictModel):
    id: str = Field(default_factory=new_id)
    name: str = "Source"
    enabled: bool = True
    kind: Literal["emitter", "system_field", "gaussian_beam"] = "emitter"  # system_field: rays through the sequential entrance pupil
    field: int = Field(0, ge=0)  # system_field
    overfill: float = Field(1.2, gt=0.0, le=10.0)  # system_field: pupil overfill
    power_w: float = Field(1.0, gt=0.0, le=1e9)
    rays: int = Field(2000, ge=1, le=200_000)
    placement: Placement = Field(default_factory=Placement)
    shape: Literal["point", "disk", "rectangle", "sphere", "box"] = "point"
    size_x: float = Field(1.0, gt=0.0)
    size_y: float = Field(1.0, gt=0.0)
    size_z: float = Field(1.0, gt=0.0)
    spatial: Literal["uniform", "gaussian"] = "uniform"
    gaussian_wx: float = Field(0.5, gt=0.0, description="1/e^2 intensity radius in x (mm)")
    gaussian_wy: float = Field(0.5, gt=0.0)
    angular: Literal["collimated", "isotropic", "lambertian", "cosine_power", "cone", "gaussian", "table"] = "lambertian"
    half_angle_deg: float = Field(90.0, gt=0.0, le=90.0)
    cos_power: float = Field(1.0, ge=0.0, le=1e4)
    gaussian_x_deg: float = Field(5.0, gt=0.0, lt=90.0)
    gaussian_y_deg: float = Field(5.0, gt=0.0, lt=90.0)
    table: list[list[float]] = Field(default_factory=list, max_length=2000)
    wavelengths: list[Wavelength] = Field(default_factory=list, max_length=64)
    # Gaussian beam (kind "gaussian_beam", module docstring)
    beam_waist_x: float = Field(0.5, gt=0.0, description="waist 1/e^2 intensity radius in x (mm)")
    beam_waist_y: float = Field(0.5, gt=0.0, description="waist 1/e^2 intensity radius in y (mm)")
    beam_m2: float = Field(1.0, ge=1.0, le=1000.0, description="beam quality M^2")
    beam_waist_z: float = Field(0.0, description="waist position along +z from the source plane (mm): > 0 converging, < 0 diverging")

    @model_validator(mode="after")
    def _check(self) -> "LightSource":
        if self.angular == "table":
            t = self.table
            if len(t) < 2 or any(len(r) != 2 for r in t):
                raise ValueError(f"Source '{self.name}': the intensity table needs at least two [angle_deg, intensity] rows")
            a = [r[0] for r in t]
            if any(b <= c for c, b in zip(a, a[1:])) or a[0] < 0 or a[-1] > 180:
                raise ValueError(f"Source '{self.name}': table angles must increase within 0…180°")
            if any(r[1] < 0 for r in t) or not any(r[1] > 0 for r in t):
                raise ValueError(f"Source '{self.name}': table intensities must be ≥ 0 and not all zero")
        if self.wavelengths and not any(w.weight > 0 for w in self.wavelengths):
            raise ValueError(f"Source '{self.name}': at least one wavelength needs a positive weight")
        return self


class Detector(StrictModel):
    id: str = Field(default_factory=new_id)
    name: str = "Detector"
    enabled: bool = True
    placement: Placement = Field(default_factory=Placement)
    shape: Literal["circle", "rectangle"] = "circle"
    size_x: float = Field(1.0, gt=0.0, description="circle: radius; rectangle: width (mm)")
    size_y: float = Field(1.0, gt=0.0, description="rectangle: height (mm)")
    acceptance_deg: float = Field(90.0, gt=0.0, le=90.0)
    mode: Literal["absorb", "monitor"] = "absorb"
    two_sided: bool = False
    pixels: int = Field(64, ge=4, le=512)


# ----------------------------------------------------------------------
Frames = dict[str, tuple[np.ndarray, np.ndarray]]  # surface id -> (matrix M, origin O): global = O + M local


def surface_frames(cs) -> Frames:
    """Vertex frames of a compiled system's surfaces by surface id (for anchored placements)."""
    return {s.id: (f.matrix, f.origin) for s, f in zip(cs.model.surfaces, cs.frames)}


def aim_angles(direction) -> tuple[float, float]:
    """Intrinsic X and Y angles (degrees) that turn the local +z axis onto `direction` (no roll)."""
    d = np.asarray(direction, dtype=float)
    n = float(np.linalg.norm(d))
    if not n > 1e-12:
        raise ValueError("The aim point coincides with the position: no direction")
    d = d / n
    return math.degrees(math.atan2(-d[1], d[2])), math.degrees(math.asin(max(-1.0, min(1.0, d[0]))))


def placement_matrix(p: Placement, frames: Frames | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(R, t): p_global = R p_local + t with R = Rx Ry Rz (intrinsic XYZ, degrees), composed with the
    anchor surface's vertex frame when the placement has one."""
    from scipy.spatial.transform import Rotation

    rot = list(p.rotation_deg)
    if p.aim is not None:
        a, b = aim_angles(np.asarray(p.aim, dtype=float) - np.asarray(p.position, dtype=float))
        rot = [a, b, rot[2]]
    R = Rotation.from_euler("XYZ", rot, degrees=True).as_matrix()
    t = np.asarray(p.position, dtype=float)
    if p.anchor:
        if not frames or p.anchor not in frames:
            raise ValueError(f"Placement anchor '{p.anchor}' is not a surface of the system")
        M, O = frames[p.anchor]
        R, t = M @ R, M @ t + O
    return R, t


def _split_counts(n: int, weights: np.ndarray) -> np.ndarray:
    """Integer counts summing to n, proportional to weights (largest remainder)."""
    w = np.asarray(weights, dtype=float)
    w = w / w.sum()
    raw = w * n
    c = np.floor(raw).astype(int)
    rest = n - int(c.sum())
    if rest > 0:
        order = np.argsort(-(raw - c), kind="stable")
        c[order[:rest]] += 1
    return c


def _sample_positions(src: LightSource, n: int, rng) -> np.ndarray:
    P = np.zeros((n, 3))
    if src.shape == "point":
        return P
    if src.shape in ("disk", "rectangle"):
        if src.spatial == "gaussian":
            out = np.empty((0, 2))
            for _ in range(200):
                k = max(n - len(out), 1) * 2 + 16
                xy = np.stack([rng.normal(0.0, src.gaussian_wx / 2.0, k), rng.normal(0.0, src.gaussian_wy / 2.0, k)], axis=1)
                if src.shape == "disk":
                    xy = xy[np.hypot(xy[:, 0], xy[:, 1]) <= src.size_x]
                else:
                    xy = xy[(np.abs(xy[:, 0]) <= src.size_x / 2) & (np.abs(xy[:, 1]) <= src.size_y / 2)]
                out = np.vstack([out, xy])
                if len(out) >= n:
                    break
            if len(out) < n:
                raise ValueError(f"Source '{src.name}': the Gaussian profile lies almost entirely outside the emitting shape")
            P[:, :2] = out[:n]
        elif src.shape == "disk":
            r = src.size_x * np.sqrt(rng.random(n))
            a = 2 * math.pi * rng.random(n)
            P[:, 0], P[:, 1] = r * np.cos(a), r * np.sin(a)
        else:
            P[:, 0] = (rng.random(n) - 0.5) * src.size_x
            P[:, 1] = (rng.random(n) - 0.5) * src.size_y
        return P
    if src.shape == "sphere":
        v = rng.normal(size=(n, 3))
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        return v * (src.size_x * np.cbrt(rng.random(n)))[:, None]
    # box
    return (rng.random((n, 3)) - 0.5) * np.array([src.size_x, src.size_y, src.size_z])


def _dirs_from_cos(cos_t: np.ndarray, rng) -> np.ndarray:
    sin_t = np.sqrt(np.clip(1.0 - cos_t * cos_t, 0.0, None))
    a = 2 * math.pi * rng.random(cos_t.shape[0])
    return np.stack([sin_t * np.cos(a), sin_t * np.sin(a), cos_t], axis=1)


def _table_cdf(src: LightSource):
    t = np.asarray(src.table, dtype=float)
    th = np.radians(np.linspace(t[0, 0], t[-1, 0], 4001))
    I = np.interp(np.degrees(th), t[:, 0], t[:, 1])
    pdf = I * np.sin(th)  # radiant intensity per solid angle -> per polar angle
    cdf = np.concatenate([[0.0], np.cumsum(0.5 * (pdf[1:] + pdf[:-1]) * np.diff(th))])
    if cdf[-1] <= 0:
        raise ValueError(f"Source '{src.name}': the intensity table carries no power")
    return th, cdf / cdf[-1]


def _sample_dirs(src: LightSource, n: int, rng) -> np.ndarray:
    a = src.angular
    tm = math.radians(src.half_angle_deg)
    U = rng.random(n)
    if a == "collimated":
        D = np.zeros((n, 3))
        D[:, 2] = 1.0
        return D
    if a == "isotropic":
        return _dirs_from_cos(1.0 - 2.0 * U, rng)
    if a == "lambertian":
        return _dirs_from_cos(np.sqrt(1.0 - U * math.sin(tm) ** 2), rng)
    if a == "cosine_power":
        m = src.cos_power + 1.0
        c0 = math.cos(tm) ** m
        return _dirs_from_cos((c0 + U * (1.0 - c0)) ** (1.0 / m), rng)
    if a == "cone":
        return _dirs_from_cos(1.0 - U * (1.0 - math.cos(tm)), rng)
    if a == "gaussian":
        sx = math.tan(math.radians(src.gaussian_x_deg)) / 2.0
        sy = math.tan(math.radians(src.gaussian_y_deg)) / 2.0
        out = np.empty((0, 3))
        for _ in range(200):
            k = max(n - len(out), 1) * 2 + 16
            d = np.stack([rng.normal(0.0, sx, k), rng.normal(0.0, sy, k), np.ones(k)], axis=1)
            d /= np.linalg.norm(d, axis=1, keepdims=True)
            if tm < math.pi / 2:
                d = d[d[:, 2] >= math.cos(tm)]
            out = np.vstack([out, d])
            if len(out) >= n:
                break
        if len(out) < n:
            raise ValueError(f"Source '{src.name}': the angular truncation removes almost all of the Gaussian beam")
        return out[:n]
    # table
    th, cdf = _table_cdf(src)
    theta = np.interp(U, cdf, th)
    return _dirs_from_cos(np.cos(theta), rng)


def beam_divergence(src: LightSource, lam_um, n_medium=1.0) -> tuple[np.ndarray, np.ndarray]:
    """Far-field 1/e^2 half-angles (rad) in x and y in a medium of index n: theta = M^2 lambda / (pi n w0), the
    wavelength in the medium being lambda / n."""
    lam = np.asarray(lam_um, dtype=float) * 1e-3 / np.asarray(n_medium, dtype=float)
    return src.beam_m2 * lam / (math.pi * src.beam_waist_x), src.beam_m2 * lam / (math.pi * src.beam_waist_y)


def _gaussian_beam(src: LightSource, lam_um: np.ndarray, rng, n_medium=1.0) -> tuple[np.ndarray, np.ndarray]:
    """Positions on the source plane and directions of a Gaussian beam (module docstring)."""
    n = len(lam_um)
    tx_s, ty_s = beam_divergence(src, lam_um, n_medium)
    xw = rng.normal(0.0, src.beam_waist_x / 2.0, n)
    yw = rng.normal(0.0, src.beam_waist_y / 2.0, n)
    tx = rng.normal(0.0, 1.0, n) * tx_s / 2.0
    ty = rng.normal(0.0, 1.0, n) * ty_s / 2.0
    zw = src.beam_waist_z
    P = np.stack([xw - zw * tx, yw - zw * ty, np.zeros(n)], axis=1)
    D = np.stack([tx, ty, np.ones(n)], axis=1)
    D /= np.linalg.norm(D, axis=1, keepdims=True)
    return P, D


def describe_beam(src: LightSource, lam_um: float, n_medium: float = 1.0) -> dict:
    """Divergence, Rayleigh range, and the beam radius and wavefront radius on the source plane (x and y), in a
    medium of index n_medium."""
    tx, ty = beam_divergence(src, [lam_um], n_medium)
    out = {"wavelength_um": lam_um, "medium_index": float(n_medium)}
    for ax, w0, th in (("x", src.beam_waist_x, float(tx[0])), ("y", src.beam_waist_y, float(ty[0]))):
        zr = w0 / th  # pi w0^2 / (M^2 lambda)
        z = -src.beam_waist_z  # the source plane relative to the waist
        out[ax] = {
            "divergence_mrad": th * 1e3,
            "rayleigh_mm": zr,
            "radius_at_source_mm": w0 * math.sqrt(1.0 + (z / zr) ** 2),
            "wavefront_radius_mm": (z * (1.0 + (zr / z) ** 2)) if abs(z) > 1e-12 else None,
        }
    return out


@dataclass
class SourceRays:
    P: np.ndarray  # (n, 3) global start points
    D: np.ndarray  # (n, 3) global unit directions
    lam: np.ndarray  # (n,) wavelength um
    power: np.ndarray  # (n,) W per ray
    source: int  # index of the source


def sample_source(src: LightSource, k: int, system_wavelengths: list[tuple[float, float]], rng, frames: Frames | None = None, medium_index=None) -> SourceRays:
    """Rays of an emitter source in global coordinates. ``medium_index(lam_um)``: the index of the medium the source
    emits into (None: 1, the air); a Gaussian beam's divergence depends on it."""
    if src.wavelengths:
        wl = [(w.value, w.weight) for w in src.wavelengths if w.weight > 0]
    else:
        wl = [(v, w) for v, w in system_wavelengths if w > 0] or [system_wavelengths[0]]
    counts = _split_counts(src.rays, np.array([w for _, w in wl]))
    lam = np.repeat(np.array([v for v, _ in wl]), counts)
    n = src.rays
    if src.kind == "gaussian_beam":
        nm = np.ones(len(lam))
        if medium_index is not None:
            for v in np.unique(lam):  # once per wavelength
                nm[lam == v] = float(medium_index(float(v)))
        Pl, Dl = _gaussian_beam(src, lam, rng, nm)
    else:
        Pl = _sample_positions(src, n, rng)
        Dl = _sample_dirs(src, n, rng)
    R, t = placement_matrix(src.placement, frames)
    return SourceRays(P=Pl @ R.T + t, D=Dl @ R.T, lam=lam, power=np.full(n, src.power_w / n), source=k)


# ----------------------------------------------------------------------
@dataclass
class DetectorRT:
    """Runtime detector: analytic plane intersection and the recorded hits."""

    spec: Detector
    R: np.ndarray
    t: np.ndarray
    hits: list = field(default_factory=list)  # (x, y, power, cos_inc, lam, source, nrefl, nsc, source ray, event key)
    rejected_w: float = 0.0  # inside the area, outside the acceptance cone
    back_w: float = 0.0  # arriving from the back of a one-sided detector

    @classmethod
    def build(cls, spec: Detector, frames: Frames | None = None) -> "DetectorRT":
        R, t = placement_matrix(spec.placement, frames)
        return cls(spec, R, t)

    def intersect(self, P: np.ndarray, D: np.ndarray, eps: float) -> tuple[float, float, float, float] | None:
        """(distance, x, y, local d_z) of the hit of the ray with the detector area, or None."""
        p = self.R.T @ (P - self.t)
        d = self.R.T @ D
        if abs(d[2]) < 1e-15:
            return None
        w = -p[2] / d[2]
        if w <= eps:
            return None
        x, y = p[0] + w * d[0], p[1] + w * d[1]
        s = self.spec
        if s.shape == "circle":
            inside = x * x + y * y <= s.size_x * s.size_x
        else:
            inside = abs(x) <= s.size_x / 2 and abs(y) <= s.size_y / 2
        return (w, x, y, float(d[2])) if inside else None

    def extent(self) -> tuple[float, float]:
        s = self.spec
        return (s.size_x, s.size_x) if s.shape == "circle" else (s.size_x / 2, s.size_y / 2)

    def result(self, total_power: float, source_names: list[str], n_rays: int = 0) -> dict:
        from .nonseq import path_table, standard_error

        s = self.spec
        h = np.array([x[:9] if len(x) > 8 else (*x, 0) for x in self.hits], dtype=float) if self.hits else np.zeros((0, 9))
        keys = [x[9] if len(x) > 9 else () for x in self.hits]
        acc = float(h[:, 2].sum()) if len(h) else 0.0
        hx, hy = self.extent()
        nx = s.pixels
        ny = s.pixels if s.shape == "circle" else max(4, int(round(s.pixels * hy / hx)))
        ex = np.linspace(-hx, hx, nx + 1)
        ey = np.linspace(-hy, hy, ny + 1)
        irr = np.zeros((ny, nx))
        cen = rms = wx = wy = peak = None
        if len(h) and acc > 0:
            H, _, _ = np.histogram2d(h[:, 1], h[:, 0], bins=[ey, ex], weights=h[:, 2])
            irr = H / ((ex[1] - ex[0]) * (ey[1] - ey[0]))
            peak = float(irr.max())
            wts = h[:, 2] / acc
            c = (h[:, :2] * wts[:, None]).sum(0)
            cen = c.tolist()
            dx, dy = h[:, 0] - c[0], h[:, 1] - c[1]
            rms = float(math.sqrt(float((wts * (dx * dx + dy * dy)).sum())))
            wx = 2.0 * float(math.sqrt(float((wts * dx * dx).sum())))
            wy = 2.0 * float(math.sqrt(float((wts * dy * dy).sum())))
        # incidence-angle distribution (power per 1-degree bin up to the acceptance angle)
        amax = max(1.0, math.ceil(s.acceptance_deg))
        bins = np.arange(0.0, amax + 1.0, 1.0)
        ang = np.degrees(np.arccos(np.clip(h[:, 3], -1.0, 1.0))) if len(h) else np.zeros(0)
        hist, _ = np.histogram(ang, bins=bins, weights=h[:, 2] if len(h) else None)
        by_source = {}
        for k, name in enumerate(source_names):
            m = h[:, 5] == k if len(h) else np.zeros(0, bool)
            by_source[name] = float(h[m, 2].sum()) if len(h) else 0.0
        by_lam: dict[str, float] = {}
        if len(h):
            for lam in np.unique(h[:, 4]):
                by_lam[f"{lam:.6g}"] = float(h[h[:, 4] == lam, 2].sum())
        direct = float(h[(h[:, 6] == 0) & (h[:, 7] == 0), 2].sum()) if len(h) else 0.0
        stray = ((h[:, 6] > 0) | (h[:, 7] > 0)) if len(h) else np.zeros(0, bool)
        from .photometry import detector_maps

        area = math.pi * s.size_x**2 if s.shape == "circle" else s.size_x * s.size_y
        photometry = detector_maps(h[:, 0], h[:, 1], h[:, 2], h[:, 4], h[:, 8], n_rays, ex, ey, area, standard_error)
        return {
            "id": s.id,
            "name": s.name,
            "mode": s.mode,
            "shape": s.shape,
            "half_extent_mm": [hx, hy],
            "power_w": acc,
            "power_sigma_w": standard_error(h[:, 8], h[:, 2], n_rays) if len(h) else 0.0,
            "stray_w": float(h[stray, 2].sum()) if len(h) else 0.0,
            "stray_sigma_w": standard_error(h[stray, 8], h[stray, 2], n_rays) if len(h) else 0.0,
            "paths": path_table(keys, h[:, 8], h[:, 2], n_rays, acc) if len(h) else [],
            "fraction": acc / total_power if total_power > 0 else 0.0,
            "direct_w": direct,
            "rejected_angle_w": self.rejected_w,
            "blocked_back_w": self.back_w,
            "hits": int(len(h)),
            "by_source_w": by_source,
            "by_wavelength_w": by_lam,
            "irradiance": irr.tolist(),
            "pixels": [nx, ny],
            "peak_irradiance_w_mm2": peak,
            "centroid_mm": cen,
            "rms_radius_mm": rms,
            "width_2sigma_mm": [wx, wy] if wx is not None else None,
            "angle_hist": {"bin_deg": bins[:-1].tolist(), "power_w": hist.tolist()},
            "units": {"irradiance": "W/mm²", "power": "W"},
            "photometry": photometry,
        }
