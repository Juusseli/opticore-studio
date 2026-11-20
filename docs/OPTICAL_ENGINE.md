# Optical engine: physics and numerical conventions

The engine (`backend/opticore`) is the single source of truth for every number
shown in the UI. This document records its conventions, algorithms and
limitations.

## 1. Units

| Quantity | Internal unit | Notes |
|---|---|---|
| Length | mm | UI accepts `nm, um/µm, mm, cm, m, in` suffixes |
| Wavelength | µm (vacuum) | UI accepts `nm` |
| Angle | rad internally | Degrees at the API for fields and coordinate breaks |
| Curvature | 1/mm | |
| Aspheric A₂ₖ | mm^(1−2k) | |
| Spot coordinates | µm in analysis output | |

Power-of-ten unit conversions shift the decimal exponent of the shortest
round-trip representation, so a typed `587.5618 nm` becomes exactly
`0.5875618 µm`. Plain multiplication by 10⁻³ would give `0.5875617999999999`.
See `units.py` / `frontend/src/lib/units.ts`.

## 2. Coordinates and sign conventions

* Right-handed global frame. Light initially travels towards **+z**. The
  vertex of surface 1 is the global origin.
* Each surface has a frame `(O, M)`, where the columns of `M` are the local
  x, y, z axes in global coordinates. A local point `p` maps to `O + M p`.
* **Radius** `R > 0`: the centre of curvature lies on the +z side of the
  vertex. `null` means an infinite radius (plane).
* **Thickness** `t_i`: signed distance from vertex *i* to vertex *i+1* along
  the local z axis of surface *i* (after any coordinate break). After a mirror,
  light travels towards −z, so subsequent thicknesses are normally negative.
  This is the usual sequential convention.
* **Rotations** are right-handed: positive about x turns +y towards +z.
* **Coordinate break**:
  * order 0: decenter in the current frame, then tilt about x, y′, z″.
  * order 1: tilt about z, y′, x″, then decenter.
  * A break with order 1 and negated parameters exactly restores the previous
    frame (tested).
* Object at infinity: `surfaces[0].thickness = null`. Finite object: the
  object plane lies at z = −t₀.
* Indices are **relative to air** (catalogue convention). AIR = 1 exactly.

## 3. Surfaces

Standard (sphere / conic / plane), with c = 1/R and conic constant k:

    z(r) = c r² / (1 + √(1 − (1+k) c² r²))

Even asphere: `z(r) = conic sag + Σ A_{2j+4} r^(2j+4)`, with coefficients
`[A4, A6, …]`. The r² term is intentionally absent because it duplicates
curvature. A ZMX `PARM 1` r² term is reported as *partial* on import.

Normals use the analytic gradient `(−g x, −g y, 1)` with `g = (dz/dr)/r`,
which stays finite at r = 0.

Domain: `1 − (1+k) c² r² ≥ 0`. Points outside the domain are reported as
`OUT_OF_DOMAIN` and are never silently clamped.

### Biconic surfaces

    z(x, y) = (cₓx² + c_y y²) / (1 + √(1 − (1+kₓ)cₓ²x² − (1+k_y)c_y²y²))

The surface has separate radius and conic for the x-z section (`radius_x`,
`conic_x`) and the y-z section (`radius`, `conic`).

* **Special cases:** cₓ = c_y with kₓ = k_y is the standard conic (tested to
  1e-12), and cₓ = 0 is a cylinder lens.
* **Normals:** from the analytic gradient.
* **Intersection:** Newton iteration on z − z(x, y), started from the y-conic
  solution.
* **First-order calculations:** the paraxial trace, solves, Seidel sums,
  pupils, the 2D layout and Gaussian beams use the y-z (tangential) section.
  A `BICONIC_PARAXIAL` note reminds you that the x-z section focuses
  differently; use real-ray analyses there.
* **Checks:** edge thickness takes the thinner of the two sections, and the
  aperture domain check covers both.
* **Optimisation:** `curvature_x` and `conic_x` are available as variables.
* **Not supported yet:** biconics are not exported to STEP/IGES (they are not
  solids of revolution); such elements are skipped with a reason.

### Zernike sag surfaces (`surfaces.ZernikeShape`)

    z(x, y) = z_base(r) + Σᵢ Aᵢ [Zᵢ(x/R, y/R) − Zᵢ(0, 0)],   i = 1 … 37

The base is a conic plus optional even-asphere terms (radius, conic, A4…).
The terms Zᵢ are the Fringe Zernike polynomials, peak-normalised and in the
same order as the wavefront Zernike fit (§8b).

* **Units:** the coefficients Aᵢ are sag in mm. R is the normalisation
  radius (`zernike_norm_radius`).
* **Vertex reference:** the polynomial is referenced to its value at the
  vertex, so the vertex stays at the local origin and piston (Z1) has no
  effect.
* **Tilt:** tilt terms, and the linear part of Fringe coma, tilt the surface
  at its vertex. A `ZERNIKE_TILT` warning reports the vertex slope.

**Evaluation.** Each term is expanded once into exact monomials
c_ij uᵘ vᵛ with (u, v) = (x, y)/R. The expansion is checked against the polar
definition for all 37 terms. Sag and gradient come from the monomials, which
have no singularity at r = 0. Intersection is Newton iteration started from
the base surface; normals use the analytic gradient.

**First order.** The paraxial trace, pupils and Gaussian beams use the
vertex curvature of the y-z section, c_y = c_base + 2c₀₂/R². The x-z vertex
curvature c_x = c_base + 2c₂₀/R² is reported, and a `ZERNIKE_PARAXIAL` note
gives both. Seidel sums omit the Zernike terms. Curvature solves are
rejected on Zernike surfaces, because the terms change the vertex
curvature.

**Checks:**
* Edge thickness is the minimum around the whole rim (144 azimuths).
* A semi-diameter beyond R gives `ZERNIKE_EXTRAPOLATED`.
* Zernike terms on a non-Zernike surface give `ZERNIKE_IGNORED`.

**Optimisation.** `zern_1` … `zern_37` are variables; the asphere terms of
the base surface are variables too.

**Not supported yet:** STEP/IGES export and non-sequential solids (these
surfaces are not solids of revolution; the export skips them with a
reason).

### Odd aspheres (`type = "odd_asphere"`, `surfaces.OddShape`)

z(r) = c r²/(1 + √(1 − (1 + k) c² r²)) + Σ_{i=1}^{N} β_i r^i, with both odd and
even powers (N ≤ 16; `odd_coefficients` = β₁, β₂, …).
* The paraxial vertex curvature is c + 2β₂.
* The Seidel sums use the fourth-order coefficient
  b₄ = (1 + k)c³ + 8β₄ − (c + 2β₂)³ (k c³ + 8β₄ when β₂ = 0).
* The r and r³ terms have no paraxial or third-order equivalent and act
  only in real-ray analyses (diagnostic). A non-zero β₁ makes a cone tip at
  the vertex (warning).
* Normals use dz/dr = conic slope + Σ i β_i r^(i−1). Intersections iterate
  Newton from the base conic. CAD export interpolates the profile with a
  B-spline.
* ZMX `ODDASPH` imports PARM 1…8 as β₁…β₈, scaled by f^(1−i) for the file's
  unit.
* Optimisation variables `odd_1` … `odd_16`.

### Q-type aspheres (`type = "qcon" | "qbfs"`, `qpoly.py`, `surfaces.QShape`)

Forbes polynomials (Opt. Express 15, 5218 (2007); recurrences from Opt.
Express 18, 19700 (2010), Appendix A), with u = r/r_n (`q_norm_radius`) and
coefficients a_m in mm (`q_coefficients`, up to 30):

* **Qcon**: z = conic(c, k) + u⁴ Σ a_m Q_m^con(u²), Q_m^con(x) = P_m^(0,4)(2x − 1)
  (Jacobi). Sag-orthogonal over the disc,
  ∫₀¹ x⁴ Q_m Q_n dx = δ_mn/(2n + 5); Q_m(1) = 1, so at the edge every term
  adds its coefficient. The terms leave the paraxial curvature c unchanged.
* **Qbfs**: z = sphere(c) + u²(1 − u²)/√(1 − c²r²) Σ a_m Q_m^bfs(u²), a
  departure along the best-fit sphere's normal. Q_m^bfs are orthonormal in
  the slope norm (2/π) ∫₀¹ D[Q_m] D[Q_n] du/√(1 − u²) with
  D[p](u) = d/du[u²(1 − u²)p(u²)], Q_m(0) > 0; evaluated by the
  three-term recurrence (P_0 = 2, P_1 = 6 − 8x, P_n = (2 − 4x)P_{n−1} − P_{n−2};
  Q_n = (P_n − g_{n−1}Q_{n−1} − h_{n−2}Q_{n−2})/f_n). The paraxial curvature
  is c + 2S(0)/r_n²; the conic constant is ignored (`QBFS_CONIC_IGNORED`).
* Derivatives come from differentiated recurrences (Qbfs) or
  dP_m^(a,b)/dt = (m + a + b + 1)/2 · P_{m−1}^(a+1,b+1) (Qcon); intersection is
  Newton iteration from the base conic, like even aspheres.
* Seidel sums use the surface's fourth-order term (8 × its r⁴ sag coefficient
  minus the cube of the paraxial curvature, the form c³k + 8A₄ takes for an
  even asphere).
* A semi-diameter beyond r_n gives `Q_EXTRAPOLATED`. Curvature solves are
  refused on Qbfs (the terms change the vertex curvature).
* **Conversion** (`POST /api/v1/surface/convert-q`): an even asphere over
  r ≤ r_n (default the clear semi-diameter) becomes Qcon with the same c and
  k, one Q term per asphere term, exactly (least squares on Chebyshev
  points of a polynomial of that degree); or Qbfs: the sphere through the
  vertex and the surface at r_n plus M terms (default the asphere terms + 3)
  fitted by least squares in sag. The largest and rms sag residuals are
  returned.
* Elements, drawings and the CAD export treat them as rotationally
  symmetric aspheres (B-spline profiles with the reported deviation).

### XY-polynomial freeforms (`type = "xy_polynomial"`, `surfaces.XYPolyShape`)

z = base conic/even asphere + Σ_k A_k (x/R)^i (y/R)^j, terms ordered by
degree and falling power of x (x, y, x², xy, y², x³, x²y, …; up to degree
10, 65 terms), A_k in mm, R = `xy_norm_radius`. The polynomial is expanded
into monomials once and uses the Zernike surface's machinery (sag,
gradient, Newton intersection, vertex curvatures R_y and R_x for the
paraxial trace; `XY_PARAXIAL`, `XY_TILT` for x and y terms,
`ZERNIKE_EXTRAPOLATED` beyond R). Not exported to STEP/IGES (not
rotationally symmetric); curvature solves are refused.

**Not supported yet (Q and XY):** ZMX import of OpticStudio's Q-type and
polynomial surfaces (no verified format reference was available), surface
form tolerances on them, and non-sequential solids.

### Ideal lens surfaces (`type = "ideal"`, `raytrace._ideal_lens`)

An ideal (paraxial) lens is a plane surface that focuses perfectly. It has a
focal length `f` in the surrounding medium (null = no power) and an optional
OPD object distance `s` (null = infinity).

* **Ray mapping.** Directions are written as tangents along the direction of
  travel, `t = (dx, dy)/|dz|`, and the lens maps `t' = t − h/f` at the hit
  point `h = (x, y)`. Light travelling towards −z (after a mirror) is
  handled the same way, so a positive `f` always converges.
* **Imaging.** The mapping is linear in (h, t), so ideal lenses and the
  propagation between them form an exact ABCD system. Every ray from an
  object point at distance s converges to the point at s' with
  `1/s' = 1/f − 1/s`, for every field and aperture. The image is
  distortion-free (`h' = f tan θ`) and has no field curvature.
* **Optical path.** The lens adds
  `ΔOPL = n(sgn(s)|Q| − s√(1+t²)) + n(sgn(s')|Q'| − s'√(1+t'²))`, with
  `Q = h − s(t, 1)` and `Q' = h + s'(t', 1)` in travel coordinates. This makes
  the path from the design object point Q to its image Q' equal for every
  ray, so wavefront, PSF and MTF analyses see a perfect lens.
  * For s → ∞ the first term becomes `−n(d·h)`; for s' → ∞ the second
    becomes `+n(d'·h)`.
  * Rays from other conjugates still image perfectly, but their OPD carries
    the residual of a lens corrected for the design conjugate. This is
    physical, because no lens is aberration-free for all conjugates.
  * Likewise a wavefront error carried by the incoming beam (rays deviated
    by an aberration upstream) is passed on with a relative error of order
    NA²: 0.19 % of its RMS at F/10, 2·10⁻⁵ at F/100 (measured in
    `test_tolerance_form_yield`). Benchmarks of transmitted wavefront errors use a
    slow ideal lens.
* **Paraxial data.** Power `|n|/f` in the y-nu trace. Seidel and colour
  contributions are zero.
* **Rules.**
  * The same medium is required on both sides (`IDEAL_MEDIA` error).
  * Radius, conic, asphere, coating and diffractive phase are ignored, with
    a diagnostic.
  * An ideal lens cannot be a mirror or the object or image surface.
  * Radius and conic tolerances do not apply.
  * It is refused by the non-sequential trace and not exported to CAD.
  * Optimisation variable: `ideal_power` = 1/f.
  * ZMX `PARAXIAL` surfaces import as ideal lenses (PARM 1 = focal length).

### Diffractive surfaces (`diffractive.py`)

Any refracting surface or mirror (not the object/image surface or a
coordinate break) can carry a thin diffractive phase, in radians:

    φ(x, y) = 2π f y + Σᵢ Aᵢ (r/R)²ⁱ,   r² = x² + y²   (i = 1 … 8)

* `grating_frequency` f (lines/mm): a linear grating with lines parallel to
  the local x axis, so the grating vector points along local y. Tilt the
  surface with a coordinate break to rotate it.
* `phase_coefficients` Aᵢ and `phase_norm_radius` R (mm): a radially
  symmetric phase (diffractive lens, kinoform).
* `diffraction_order` m (−50 … 50).

**Direction.** The exact vector grating equation is applied on the local
tangent plane of the (curved) substrate:

    n₂ d₂ₜ = n₁ d₁ₜ + m λ₀ Gₜ,   G = ∇φ / 2π  (cycles/mm)
    n₂ d₂ₙ = ±√(n₂² − |n₂ d₂ₜ|²)

A transmitted ray stays on the side of propagation, and a reflected ray
reverses its normal component (n₂ = n₁ for mirrors). When |n₂ d₂ₜ| > n₂ the
order is evanescent. The ray is then terminated with status `EVANESCENT`.

**Optical path.** The path length gains m λ₀ φ / 2π (Fermat's principle for a
surface phase). Wavefront, OPD, PSF and MTF analyses therefore include the
diffractive phase consistently. The OPL is referenced to the phase at the
surface vertex, not to an absolute zone count.

**First order.** The quadratic term adds the paraxial power
φ_d = −m λ A₁ / (π R²) at each wavelength. This power enters the y-nu trace,
the chromatic focal shift and Gaussian beams. Its dispersion is
f ∝ 1/λ (Abbe number λ_d/(λ_F − λ_C) ≈ −3.45). Linear gratings have no
paraxial power, and the `GRATING_PARAXIAL` note reminds you that their
deviation appears only in real-ray analyses.

**Assumptions.** This is a scalar, thin-element model:

* 100 % efficiency in the selected order; other orders are not traced.
* No rigorous coupled-wave theory, so there is no efficiency versus angle or
  polarisation.
* The phase has no physical relief. CAD export writes the substrate only.

**Not included.**

* The Seidel sums omit the diffractive phase terms.
* The non-sequential trace uses the geometry only.
* The `DOE_ACTIVE` diagnostic states both points.

**Optimisation.** `phase_1` … `phase_4` (A₁ … A₄) and `grating_frequency` can
be used as variables.

## 4. Ray–surface intersection

* **Conics** are solved in closed form. In local coordinates, substituting
  `P + sD` into `c(x² + y² + (1+k)z²) − 2z = 0` gives `a s² + 2b s + cc = 0`.
  Both roots are computed in cancellation-free form,

      q = −(b + sign(b)·√(b² − a·cc)),   s₁ = q/a,   s₂ = cc/q

  and the root lying on the vertex sheet `z = sag(r)` is kept. If both lie on
  it (hyperboloids, paraboloids), the one nearer the axis is kept. Selecting
  by sign(b) alone fails once the ray origin lies beyond the centre of
  curvature: an object past a concave mirror's centre, a rear-stop launch
  plane, or a Cassegrain secondary. These cases are regression-tested. A ray
  meeting only the far sheet is a `MISS`.
* **Aspheres**: Newton iteration on `f(s) = z(s) − sag(r(s))`, starting from the
  base-conic root (or the vertex plane). Tolerance 10⁻¹² mm, at most 60
  iterations. Non-convergence is reported as `NO_CONVERGENCE`.
* `s` may be negative: sequential tracing allows virtual propagation.

## 5. Interface physics (`physics.py`)

* **Refraction** (vector Snell), with N oriented along the propagation (cos i > 0):
  `t = μ d + (cos t − μ cos i) N`, where `μ = n₁/n₂` and
  `cos t = √(1 − μ²(1 − cos² i))`. A negative radicand flags **TIR**.
* **Reflection**: `r = d − 2(d·N)N`.
* **Fresnel** (lossless dielectric): amplitude coefficients rs, rp, ts, tp. Power
  transmittance includes the factor `n₂ cos t / (n₁ cos i)`, so `R + T = 1`
  exactly for each polarisation. Unpolarised values are the mean of s and p.
  In the sequential trace, Fresnel losses are optional (off by default) and
  affect only the reported ray intensity.
* **Absorption**: the intensity is multiplied by `exp(−α |s|)` in media with α > 0.

## 6. Sequential tracing (`raytrace.py`)

For each surface j = 1 … N−1:

1. Coordinate breaks: no intersection; the frame change is already encoded.
2. Transform the ray to local coordinates and intersect.
3. Accumulate optical path `n₁ · s` and absorption.
4. Apply the aperture check. Only **fixed** semi-diameters clip, giving status
   `VIGNETTED`. Automatic apertures never clip, by design.
5. Refract, or reflect at a mirror. The medium after a mirror or a coordinate
   break is the medium before it.

Each ray carries a status (`ok, miss, tir, vignetted, out-of-domain,
no-convergence`) and the index of the surface where it stopped. Analyses
report failed-ray counts. No ray is dropped silently.

### Ray launching and aiming

* The entrance pupil is computed paraxially (section 7).
* Normalised pupil coordinates (px, py) map to points on the entrance-pupil
  plane.
* **Object at infinity, angle fields**: the direction is `(tan θx, tan θy, 1)`
  normalised. Rays start on the plane through the EP centre perpendicular to
  that direction, which is the reference wavefront for OPL.
* **Finite object**: rays start at the object point, aimed at EP points.
  * Angle fields with a finite object place the object point at
    `h = −tan θ (d₀ + z_EP)`, the paraxial chief-ray definition.
  * **Virtual objects** (d₀ < 0, object behind surface 1): rays start on the EP
    plane converging towards the object point, with OPL referenced to it.
* **Real ray aiming** (`ray_aiming = "real"`): a chord-Newton iteration per
  ray adjusts the EP intercept until the ray crosses the stop at
  `(px, py)·r_stop`, to a tolerance of 10⁻¹¹ mm.
  * The finite-difference 2×2 Jacobian is reused while the error shrinks by at
    least 4× per step, and recomputed otherwise.
  * The optimiser passes a warm-start cache, so successive merit evaluations
    start from the previous solution. The difference between warm and cold
    residuals is about 10⁻¹⁴ mm, far below the finite-difference steps.
  * Use real aiming for wide-angle systems or when coordinate breaks precede
    the stop.
* **Paraxial aiming check** (`PARAXIAL_AIMING`, `analysis/evaluate.aiming_check`).
  * With paraxial aiming, the evaluation traces the chief ray and the four
    marginal rays of every field (primary wavelength) to the stop. It
    measures how far each lands from the point it stands for,
    (px, py)·r_stop, as a fraction of r_stop.
  * The largest miss above 5 % is a warning, and above 1 % a note.
  * With the stop as the first surface and the object at infinity, the miss
    is exactly 0.
  * Measured on the samples, a 5–9 % miss changed edge RMS spots, relative
    illumination or distortion by 6–26 %:
    * double Gauss, edge RMS 104.9 µm against 83.0 µm with real aiming;
    * Geiser triplet, relative illumination 0.773 against 0.869.
  * A 1.8 % miss changed results by 0.3 %.
* **Image-height fields** (`fields.py`). Rays are always launched from an
  object-space field: an angle for an object at infinity, an object height
  for a finite object. Image-space field types are converted at the primary
  wavelength, so all wavelengths of a field share the object point.
  * `paraxial_image_height`: linear. The paraxial chief ray of a unit object
    field (tan θ = 1 or 1 mm) gives the height per unit at the paraxial image
    plane.
  * `image_height`: the object field whose real chief ray (pupil centre, the
    system's ray aiming) meets the image surface at (hx, hy) in its local
    frame, to 10⁻¹² mm. It must lie on the **first branch** from the axis:
    wide-angle lenses can fold the field (the chief-ray height rises to a
    maximum and falls again), and beyond the fold several object fields meet
    the same height. On the first branch the chief-ray map keeps the
    orientation it has on the axis (the sign of det J).
    * Newton iteration with a finite-difference Jacobian (backward
      differences where the forward chief ray fails at the edge of the
      accepted field), damped steps and a backtracking line search: a trial
      point whose chief ray fails, or that does not reduce the error, is
      halved towards the last point.
    * Starts: the previous solution of the same field (the optimiser passes
      its warm-start cache, so successive designs start from the last
      solution), then the paraxial estimate.
    * If neither ends on the first branch, the field is followed out from the
      axis (continuation): targets from the axis image point to (hx, hy) in
      steps of a quarter, each Newton from the last solution, halving a step
      that fails (down to 1/512).
    * This replaced a plain Newton from the paraxial estimate, which gave up
      when it started beyond a fold. In the cell-phone lens optimisation that
      happened at a trial design whose 3.5 mm field lies at 22.5° (the height
      peaks at 3.93 mm near 27°), and the whole run failed.
  * A height no real chief ray reaches on the first branch (TIR, missed
    surfaces, beyond the fold) raises `FIELD_UNREACHABLE`.
  * Results are cached per compiled system.
* **Object-space telecentric** (`object_space_telecentric`). The entrance
  pupil is at infinity, so rays are not aimed at a pupil.
  * Every ray starts at the object point with direction cosines
    `(L, M) = NA/n₀ · (px, py)` about the axis; the chief ray is parallel to
    the axis.
  * Requires a real object at a finite distance, an object-space NA aperture
    and object- or image-height fields.
  * The stop belongs in the rear focal plane of the optics before it.
    `TELECENTRIC_STOP` warns when the edge-field chief ray misses the stop
    centre by more than 2 % of the stop radius.
  * Without the flag, a system whose entrance pupil is at infinity raises
    `TELECENTRIC_EP`, which tells the user to enable the mode.

### Pupil sampling

Hexapolar (centre plus 6k points on ring k), square grid clipped to the circle,
or a deterministic golden-angle disc ("dithered"). All patterns are
deterministic, so results are reproducible.

### Central obscurations (`Surface.obscuration`)

A surface may carry a central circular obscuration, given as its radius in
mm. When the apertures are applied (`clip`), rays that meet the surface
inside that radius are blocked with the status "blocked by central
obscuration". Typical uses are a secondary mirror's shadow on a plane at
its position, or a hole in a primary.

Chief rays that serve as references (spot and fan references, the merit
function's chief ray, the wavefront reference, the marginal-ray checks) are
traced through obscurations, because they define the geometry and not the
light. The diffraction analyses (FFT and Huygens PSF, MTF, vector PSF) see
an annular pupil, and so do throughput and relative illumination.
Obscurations on the object or image surface or on coordinate breaks are
ignored (diagnostic).

### Vignetting factors (`raytrace.vignetted_pupil`, `analysis/vignetting.py`)

Each field may carry the factors VDX, VDY, VCX and VCY. Geometric pupil
sampling then traces px′ = VDX + px(1 − VCX), py′ = VDY + py(1 − VCY)
instead of (px, py): the unit pupil is mapped onto an ellipse that the
apertures pass. This applies to spot diagrams, ray and OPD fans, the layout
rays, the marginal-ray checks, automatic semi-diameters, best focus,
geometric MTF and encircled energy, and the merit function. Chief rays are
not moved. The diffraction, wavefront, throughput, polarisation and
relative-illumination analyses trace the real pupil and let the apertures
clip it, which is exact.

*Set vignetting* finds, for every field at the primary wavelength, how far a
real (aimed) ray can move from the pupil centre along +y and −y before an
aperture clips it, by bisection to 10⁻⁷ of the pupil radius. It does the
same along ±x through the centre of that y range. Then VDY = (top + bottom)/2,
VCY = 1 − (top − bottom)/2, and VDX and VCX follow from the x range. The
marginal rays of every field then just pass.

The factors describe an ellipse. When the passed region is the lens-shaped
overlap of two aperture footprints (a double Gauss at full field), rays in
the ellipse's corners are still clipped, as in other lens-design programs.

### Automatic semi-diameters

The chief ray plus 16 rim rays are traced, unclipped, for every field and
wavelength, and the maximum radial height on each surface is taken.

## 7. Paraxial optics (`paraxial.py`)

y–nu trace on the unfolded axis, using signed indices (n′ = −n at a mirror)
and the signed thickness convention:

    n′u′ = n u − y φ,   φ = (n′ − n) c,   y_next = y + t u′

* System matrix from rays A (y = 1, nu = 0) and B (y = 0, nu = 1).
  Power = −C, EFL = 1/power, `BFL = −y_k/u′_k`, front focal point
  `n D / C`, principal planes `n(D−1)/C` (front, from surface 1) and
  `n′(1−A)/C` (rear, from the last surface).
* Entrance pupil: from the stop heights y_A, y_B of the unit rays,
  `z_EP = y_B / y_A` relative to surface 1, and `r_EP = r_stop / y_A`
  (independent of object distance). `y_A = 0` means a telecentric entrance
  pupil: it needs the object-space telecentric mode (§6, with an object-space
  NA); without it the system is refused with TELECENTRIC_EP.
* Aperture definitions: EPD; image-space F/# (`EPD = EFL / F#`); object-space
  NA (`r_EP = (z_EP + d₀) tan(asin(NA/n₀))`). The aperture is evaluated at the
  primary wavelength, and every wavelength is launched through that pupil.
  This covers the spot, the per-wavelength paraxial data, the diffraction
  sampling, and the Huygens and vector PSFs, ghosts and direct-path sources.
  Recomputing the pupil per wavelength resized the stop with EFL(λ) or n₀(λ):
  an N-SF6 singlet at F/10 reported a working F/# of 10.000 at the F line,
  while its traced beam was 9.726.
* Working F/# = `1 / (2 n′ |u′|)` of the paraxial marginal ray.
* Coordinate breaks: paraxial values are computed on the unfolded axis and
  flagged `approximate`.

### Seidel sums

Following the standard formulation (Welford, *Aberrations of Optical Systems*,
ch. 8), with refraction invariants `A = n(yc + u)` and `Ā = n(ȳc + ū)`:

    S_I = −A² y Δ(u/n),  S_II = −AĀ y Δ(u/n),  S_III = −Ā² y Δ(u/n)
    S_IV = −H² c Δ(1/n), S_V = (Ā/A)(S_III + S_IV)
    C_L = A y Δ(δn/n),   C_T = Ā y Δ(δn/n),   δn = n_F − n_C

The conic/A4 deformation adds `ΔS_I = (k c³ + 8A₄) Δn y⁴`, scaled by
(ȳ/y)^m for S_II, S_III and S_V.

**Sign note:** with OptiCore's slope sign (u′ < 0 for a converging ray above
the axis), the third-order transverse marginal aberration at the paraxial
focus is `δy = +S_I / (2 n′u′)`. The validation suite checks this against real
rays to within 1% at small aperture.

## 7a. Multiple configurations (`configs.py`)

`OpticalSystem.multi_config` holds configuration names, the active index and a
table of operands. Each operand has a parameter, a surface (none for the
system parameters), or a field for the vignetting factors, and one value per
configuration.

**Parameters:**
* thickness, radius (null = plane), conic, material, semi-diameter (fixes the
  aperture), and decenter/tilt of coordinate breaks;
* the system aperture value, temperature and pressure;
* a field's vignetting factors `vdx`, `vdy`, `vcx`, `vcy` (`field` = its
  index), since a zoom lens vignettes differently at each position.

The surfaces and fields hold the base values.

**Vignetting factors per configuration.** *Set vignetting* on a system with
configurations runs the vignetting analysis in every configuration. It
writes one row per field and factor that is non-zero in some configuration,
and clears the fields' own factors. Removing a field drops its rows and
renumbers later fields. *Single configuration* writes the active
configuration's values back into the base, including temperature, pressure
and vignetting factors.

**Compilation:** `compile_system` first writes the active configuration's
values into the prescription, then resolves solves. Applying is idempotent.
If an applied configuration is invalid (e.g. object-height fields with an
infinite object), the result is a structured `CONFIG_INVALID` error. A
parameter controlled by both a solve and a configuration row is also
rejected.

**Merit function:**
* Operands carry an optional `configuration` (default: the active one).
* Each evaluation compiles every configuration that is referenced, once, with
  its own paraxial and semi-diameter caches and ray-aiming warm starts.
* Variables can be per-configuration (`configuration` = k). They then read and
  write the value in the configuration table. `curvature` maps onto the
  radius row, and `thickness`, `conic`, decenters and tilts onto rows of the
  same name.
* A base variable on a parameter that is set per configuration is rejected,
  because it would have no effect.

**Other uses:**
* The evaluation response reports `configuration: {active, names}`.
* Tolerancing analyses the active configuration with its values baked into
  the prescription.

## 7b. Solves and pickups (`solves.py`)

A solve replaces a stored thickness or curvature with a value computed from
the system's own paraxial trace (primary wavelength). Marginal and chief rays
are those defined in §7.

| Parameter | Solve | Definition |
|---|---|---|
| thickness | `marginal_height` | t_j = (h − ζy_j)/(ζu_j): marginal ray (zone ζ) at height h on surface j+1. h = 0 is the paraxial focus |
| thickness | `chief_height` | the same for the chief ray at the maximum field. h = 0 locates a pupil |
| thickness | `pickup` | t_j = scale · t_src + offset |
| curvature | `marginal_angle` | c = (nu_{j−1} − n′_j u′)/(y_j (n′_j − n_j)): slope u′ after the surface. Signed indices, so mirrors are included |
| curvature | `chief_angle` | the same for the chief ray |
| curvature | `f_number` | n′u′ = −sign(y_j)/(2F): converging marginal ray with image-space F/# F |
| curvature | `pickup` | R_j = scale · R_src (a plane stays a plane) |

**Iteration.** All solves are updated together and the system is recompiled
until no value changes by more than 1e-13 (relative), with at most 40
iterations. Solves before the stop change the entrance pupil, so they
iterate; solves after the stop converge in one step. Failure modes give
structured diagnostics:
* `SOLVE_FAILED`: a ray parallel to the axis or a zero height. The stored
  value is kept.
* `SOLVE_NOT_CONVERGED`
* `SOLVE_INVALID`: an object/image surface, a self pickup, or a wrong type for
  the parameter.

**Where resolution happens.** Solves are resolved inside `compile_system`.
Every analysis, every merit-function evaluation (so a marginal-height solve
keeps an optimised design in paraxial focus) and the evaluation response
(`solved`) see the resolved values.

**Restrictions.**
* A solved parameter cannot be an optimisation variable.
* Tolerancing freezes solves at their nominal values, so a perturbation is
  never silently re-solved. Use compensators instead.

## 8. Analyses

| Analysis | Method | Reference / units |
|---|---|---|
| Spot diagram | Real rays on the image surface; deterministic pupil pattern; RMS weighted by wavelength weights | Polychromatic centroid or primary chief ray; µm |
| Airy radius | 1.22 λ_primary × working F/# | Geometric comparison only; this is not a diffraction calculation |
| Ray fan | e_y(P_y) tangential, e_x(P_x) sagittal | Primary-wavelength chief ray; µm |
| Field curvature | Closest-approach focus of real ray pairs at ±10⁻³ pupil in the tangential/sagittal planes, along the direction of the largest field (the tangential plane contains it) | mm from the image surface along its local z |
| Distortion | (h_real − h_ref)/h_ref along the largest field's direction, both on the image surface. h_ref: the paraxial chief-ray height when every field lies on the y axis; otherwise the linear limit of the real chief ray (a 2×2 map from the launched object field to the landing, measured at 10⁻⁴ of the field along x and y), which follows the x-z section of an anamorphic system where the paraxial trace knows only the y-z section. Before the fix a field along x was evaluated along y: a biconic lens gave its y-section value | %; equals F-tan θ distortion when the image surface is at focus |
| Longitudinal aberration | Axial intercept of meridional rays from the axial object point | mm from the image surface |
| Chromatic focal shift | Paraxial marginal-ray image distance versus λ | µm relative to the primary λ |
| System data | Paraxial table plus Seidel sums | Explicitly labelled paraxial / third-order |
| Focus status | Real rays (hexapolar, all fields and wavelengths, weighted) on planes along the image normal: the centroid-referenced RMS² is quadratic in the defocus δ, so the best focus is δ* = −B/C in closed form. *At best focus* means the current RMS is within 5 % (or 0.1 µm) of the best | mm along the image surface normal; µm. Exact for a plane image surface, a first-order estimate (`exact = false`) for a curved one (tangent plane) and for real image-height fields (re-solved when the surface moves: the cell-phone lens predicts −0.0406 mm, the re-traced optimum is −0.0392 mm) |

Every analysis response states its method, sampling and units.

### Field directions and angle fields

* **Angle fields** are tan components: the chief ray's direction is
  (tan x, tan y, 1). The size of an angle field is its true field angle
  atan(hypot(tan x, tan y)), and its azimuth is that of (tan x, tan y). For
  example, (23.82°, 23.82°) is a 31.98° field. Heights combine as vectors.
  The helpers are `fields.field_size`, `field_direction` and `field_along`;
  `paraxial.max_field_value` and `summary.largest_field` rank fields by true
  size.
* **Analyses that follow one field direction** use the largest field's
  azimuth (+y when every field is on the axis), with image heights the
  chief-ray landings projected on it. These are relative illumination, the
  image simulation's distortion table and PSF nodes, the live image's
  chief-ray maps, distortion and field curvature, and lateral colour. The
  `min_relative_illumination` operand and the summary use each field's own
  azimuth.
* **Ray and OPD fans** run along each field's own azimuth u (pupil p·u,
  error along u) and across it (s = (uy, −ux)). An on-axis field takes the
  largest field's azimuth, so fields along +y keep e_y(P_y) and e_x(P_x);
  the UI labels other azimuths e_T(P_T) and e_S(P_S).
* **Automatic vignetting factors** bisect the pupil along the field's
  dominant axis first, then measure the other axis through the centre
  found.
* **Relative illumination** with angle fields and a finite object
  differentiates through the object height h = tan θ·|d₀ + z_EP|.
* **Distortion reference.** Fields along y, and any azimuth in a
  rotationally symmetric system, are referred to the paraxial chief ray. In
  other systems the reference is the linear limit of the real chief ray,
  taken with a Richardson step M = 2M(d) − M(2d), d = 10⁻⁵ of the largest
  field. This removes the error linear in d that a one-sided step carries:
  from the h² terms of decentred systems and the h|h| term of r³ odd
  aspheres. A symmetric difference would not cancel the h|h| term, since it
  is odd.

## 8b. Physical optics (wavefront, PSF, MTF)

**Reference sphere.** For each field and wavelength the sphere is centred on the
chief-ray image point C (image surface). It passes through E, where the chief
ray crosses the paraxial exit-pupil plane. Each ray's real optical path is
extended from the image surface to that sphere along its image-space direction.
The root nearest E is used, and virtual propagation is allowed.

**Sign (Welford).** `W = OPL_ref(chief) − OPL_ref(ray)`. A wavefront ahead of
the reference is positive; an undercorrected positive lens has
`W(edge) = +S_I/8 > 0`. Defocusing the image by δz beyond focus gives
`W = δz ρ²/(8F#²)`. Both are verified in the test suite.

**Zernike.** A least-squares Fringe fit (peak-normalised, 37 terms) over the
valid samples. P-V and RMS are computed from the samples, not from the fit.

**FFT PSF.**

* Pupil function `P = A·exp(−i2πW)` on an N×N grid in normalised
  entrance-pupil coordinates, zero-padded to M = Q·N.
* `PSF = |FFT(P)|²`, image sampling `Δx = λ·F#_w/Q` (paraxial working F/#).
* Strehl is the peak relative to the unaberrated PSF of the same aperture.
* Encircled energy is taken about the PSF centroid.
* Assumptions: scalar Fraunhofer, uniform amplitude, linear entrance-to-exit
  pupil mapping (pupil aberrations neglected), no off-axis anamorphism.

**MTF.**

* Diffraction MTF is `|FFT(PSF)|`, i.e. the pupil autocorrelation, normalised
  at zero frequency. Tangential means frequency along y.
* Polychromatic MTF is the weighted average of the complex OTF of each
  wavelength, interpolated onto a common frequency axis.
* Lateral colour is included as the phase `exp(−2πiνΔ)` of each wavelength's
  chief-ray image shift relative to the primary wavelength. This is checked
  against the analytic bound in tests.
* Geometric MTF is the Fourier transform of the weighted real-ray spot.
* The diffraction-limited reference is
  `(2/π)(φ − cos φ sin φ)`, with `φ = acos(ν/ν_c)` and `ν_c = 1/(λF#_w)`.

**Measured accuracy of the approximations** (tests/test_diffraction.py):

| Check | Result |
|---|---|
| MTF of a perfect paraboloid vs analytic | Within 0.005 |
| Encircled energy at the Airy radius | 0.838 ± 0.01 |
| Maréchal vs FFT Strehl at σ ≈ 0.05 waves | Within 2% |
| PSF centroid vs mean real-ray position (F/10 singlet, 2°) | Within 3% |

At 4° the PSF-centroid agreement is ≈ 5%. The difference is pupil aberration:
real transverse ray errors deviate by ±1.5% across the pupil from the linear
pupil mapping.

**Pupil integration for merit operands.** RMS spot and RMS wavefront
operands use Gaussian quadrature: Gauss–Legendre rings in ρ² × equally spaced
arms, with area weights summing to 1. This is exact for ρ^(2k), k ≤ 2·rings − 1.
Hexapolar patterns over-weight the rim and bias RMS objectives; quadrature
removes that bias. A minimum-RMS-wavefront focus therefore makes the residual
orthogonal to defocus, to better than 10⁻³ (tested).

### Tangential and sagittal MTF; FFT sampling

* **Tangential and sagittal.** The tangential (meridional) MTF is the cut
  along the field direction u, the sagittal one the cut along
  s = (u_y, −u_x).
  * u is the unit vector of the field components as the trace uses them:
    (tan θx, tan θy) for angle fields, the heights otherwise, and +y on the
    axis.
  * The FFT pupil grid and the hexapolar pattern of the geometric MTF are
    turned into (s, u). Lateral-colour shifts and spot coordinates are
    projected on u and s.
  * A field turned about the axis of a rotationally symmetric lens therefore
    gives the same T and S. Before this, T and S were the y and x cuts: an
    x field had them swapped, and a 45° field had both wrong.
  * Each field reports `tangential_direction` and `sagittal_direction`.
  * A square pixel of width w has the MTF sinc(νw cosφ)·sinc(νw sinφ) along
    a cut at angle φ to x (`diffraction.pixel_mtf_along`). The sensor MTF
    applies it along each cut.
* **Sampling.** The FFT PSF and MTF report the largest wavefront change
  between neighbouring pupil samples, and warn above 0.5 wave, where the
  pupil function aliases. The FFT PSF is periodic with period N·λ·F#w about
  the chief-ray image point, so it also warns when the geometric spot plus
  one Airy radius exceeds half that window (the PSF wraps around). Both
  warnings mean the grid should be raised. They appear under `warnings`, as
  in the Huygens PSF. The merit, summary and design-space MTF calls use grid
  32 and do not show these warnings.

### Huygens PSF (`analysis/huygens.py`)

Each traced ray k is a secondary source Q_k on the exit-pupil reference sphere
(centre C at the chief-ray image point, radius R). L_k is its optical path
from the object. The scalar field at a point r of the image surface is

    U(r) = Σₖ aₖ exp(i k₀ [L_k + n |r − Q_k|]) / |r − Q_k|

with exact distances and an obliquity factor of ≈ 1.

**Amplitude.** The rays sample the entrance pupil uniformly, so each carries
the same power. A ray's amplitude is aₖ = √dSₖ, where dSₖ is its area
element on the reference sphere: the Jacobian of the sphere points over the
pupil grid. The source density on the sphere is what matters. Ray
directions are not used, because aberrations bunch them into caustics.
Optionally aₖ is multiplied by √(ray transmission) (Fresnel, coatings,
absorption) to include apodisation.

**What it adds over the FFT PSF.** The field is evaluated on the real image
surface, or on a plane displaced from it along local z, using the true ray
geometry. Off-axis anamorphism, image-plane tilt, defocus and pupil
distortion are therefore included.

**Normalisation and Strehl.** U₀ = Σ aₖ / R is the field of the same samples
with all phases equal, i.e. the diffraction-limited peak. The PSF is
|U|²/|U₀|². The Strehl ratio is its maximum, refined continuously around the
best grid sample, so it does not depend on the image grid.

**Sampling checks** (reported as warnings):
* the wavefront step between neighbouring rays must be ≤ 0.5 waves;
* the image window must stay below 90 % of the alias period λ/(nΔq) of the
  discrete sources;
* the geometric spot must fit inside the window.

**Limits:**
* scalar theory: no polarisation or vector high-NA effects;
* the wavelets start on the reference sphere, so the Fresnel number must be
  large;
* the image surface is treated as the plane through the chief-ray image
  point, parallel to its vertex plane;
* encircled energy is relative to the energy inside the window.

## 8c. Energy throughput

* The transmitted fraction of the power entering the entrance pupil is a
  pupil-area integral evaluated by Gaussian quadrature.
* Contributions:
  * **vignetting**: rays clipped by fixed apertures or failing
  * **bare surfaces**: unpolarised Fresnel transmission
  * **coated surfaces**: thin-film transmittance (§8d)
  * **bulk absorption**: `exp(−α·path)`, with α per wavelength: the
    catalogue internal transmittance when the system's
    `catalog_absorption` is on and the glass has it, α = −ln τ / d
    (linear in wavelength between the tabulated points, the nearest end
    value outside them with `TRANSMITTANCE_EXTRAPOLATED`), otherwise the
    material's constant coefficient. The switch is off by default, so
    existing results do not change; the analysis names the source of each
    glass's absorption and says when catalogue data go unused. The same α
    applies wherever the trace absorbs (intensities, polarisation, BPM,
    direct-path detector traces).
* An uncoated mirror is ideal (R = 1). A coating on a mirror sets its
  reflectance by the thin-film calculation (§8d) in the throughput and
  polarisation analyses (info diagnostic MIRROR_COATING).
* Single pass: reflected branches and ghosts are not traced.
* A per-surface breakdown is given for the on-axis chief ray.

## 8d. Thin-film coatings (`thinfilm.py`)

Characteristic-matrix method (Macleod, *Thin-Film Optical Filters*, ch. 2).
Layer j has the complex index N_j = n_j − i k_j (k ≥ 0: absorbing) and the
physical thickness d_j. Light arrives at angle θ₀ from a lossless incident
medium n₀.

* Snell in every layer gives y_j = N_j cos θ_j = √(N_j² − (n₀ sin θ₀)²). The
  layer matrix is even in y, so the branch matters only for the substrate.
  There the root with Im y ≤ 0 is taken: a decaying wave. This also covers
  absorbing (metal) substrates and total internal reflection.
* Phase thickness δ_j = 2π y_j d_j / λ.
* Tilted admittance η = y (s) or N²/y = N / cos θ (p).
* M_j = [[cos δ, i sin δ / η], [i η sin δ, cos δ]] and
  [B, C]ᵀ = Π M_j [1, η_sub]ᵀ.
* r = (η₀B − C)/(η₀B + C), R = |r|², T = 4 Re η₀ Re η_sub / |η₀B + C|², and
  the absorptance is A = 1 − R − T.

In the trace, a coated refracting surface uses the unpolarised mean
(T_s + T_p)/2 in place of the bare Fresnel value. Layers are listed from the
lower-index side towards the denser medium, and are reversed automatically
when light travels from the dense side (e.g. the rear face of a lens), so one
coating definition is valid on both faces. Reciprocity makes T direction-
independent for a correctly oriented stack (tested).

**User-defined coatings** (`OpticalSystem.custom_coatings`, coating editor):

* Each layer has either a fixed n and k, or a library material, which gives a
  dispersive n(λ) from its formula (k from the layer). Material layers outside
  the material's data range produce a `COATING_RANGE` warning.
* Names are case-insensitive and must not reuse a built-in name.
* **Mirror coatings.** A coating with a substrate index N_s = n − ik can be
  used on a mirror. Its layers are listed from the incident medium towards
  the substrate, and the mirror then reflects R = (R_s + R_p)/2 at each ray's
  angle, in place of the ideal R = 1. The incident medium is the medium in
  front of the mirror, e.g. glass for a rear-surface mirror.
* In the polarisation trace, a coated mirror uses a_s = r_s and a_p = −r_p
  (Macleod's r_p; the minus accounts for the PRT p basis k × s flipping on
  reflection). A perfect conductor therefore gives the ideal-mirror
  a_s = −1, a_p = +1 (tested).
* A coating without a substrate index cannot be used on mirrors; the mirror
  stays ideal and a `COATING_IGNORED` warning is raised. On a refracting
  surface the substrate index is ignored and the adjacent glass is the
  substrate.

**Coating materials with n and k** (`materials/data/coating_materials.json`,
generated by `python -m opticore.tools.coating_materials <pages>`; ADR-055).
Measured optical constants of deposited films and metals from the
refractiveindex.info database (CC0), with the original references:
* films: SiO₂, TiO₂, Ta₂O₅, Nb₂O₅, HfO₂, Al₂O₃, MgF₂, ZnS, Si₃N₄
  (`*_FILM`);
* metals: Ag (Johnson & Christy, and a Lorentz–Drude fit to 12.4 µm), Au,
  Cu, Cr, Al (Rakić).

A material record may carry `extinction_table` [[λ µm, k], …]. k is
interpolated by PCHIP and held at its end values outside the table, so the
complex index is N = n − ik. A layer's own extinction adds to the
material's. Dense tables are thinned when generated: every original point is
reproduced within 2·10⁻⁵ in n and k.

Metals are coating layers and mirror substrates, not lens media; the
compiler refuses a metal as the medium after a surface. A metal mirror is
modelled as it is made: an opaque metal layer (100–150 nm) on the glass
blank under its overcoats.

**Assumptions:**
* coherent single-pass interference within the stack;
* isotropic, homogeneous layers;
* the stack is thin compared with the ray geometry (no lateral shift, no
  change of ray direction);
* absorbed power is removed from the ray.

**Built-in library** (`materials/data/builtin_coatings.json`, generated by
`python -m opticore.tools.builtin_coatings`; ADR-053, ADR-055). It holds 29
generic designs (no vendor data) made of the dispersive film and metal
materials above, on N-BK7 unless stated. The generator evaluates every
specification and stops if one is not met.
* *Antireflection:*
  - `MGF2_QW550`, a single quarter wave;
  - V-coats `VCOAT_355` … `VCOAT_1550`: two layers MgF₂/Ta₂O₅ whose
    thicknesses solve r(λ₀) = 0 exactly on n_s = 1.52 (least-squares root of
    the complex r; not quarter waves);
  - broadband AR `BBAR_VIS`, `BBAR_NIR`, `BBAR_SWIR`, refined to their
    specification.
* *Mirrors:*
  - quarter-wave (HL)ᴺH stacks `HR_532` … `HR_1550` (quarter waves of the
    films' real index at λ₀), and `HR_1064_45` for s and p at 45°;
  - metal mirrors `AL_PROTECTED`, `AL_ENHANCED`, `AL_UV`, `AG_PROTECTED`,
    `AU_PROTECTED`;
  - the dispersive mirror `DM_800`.
* *Filters:* `HOT_MIRROR` and `COLD_MIRROR`.
* *Filters:* also `LP_550`, `SP_550`, a band-pass `BP_532` and a notch
  `NOTCH_532`.
* *Beam splitters:*
  - `BS_50_45`, a 50/50 plate at 45°;
  - `PBS_MACNEILLE`, a cube whose glass index satisfies
    n_g² = 2n_H²n_L²/(n_H² + n_L²) for the films' real indices at 550 nm, so
    every H/L interface is at Brewster's angle for p at 45° in the glass (an
    ideal glass of exactly that index).

Each built-in stores its category, design wavelength, band, angle of
incidence, incident and substrate indices, and its specification as
coating-designer targets. The tests check that every built-in meets its
specification. On a lens the coating sits on the real glass of the surface.

### Coating design (`coatdesign.py`)

**Design.** Layers are stored in deposition order: layer 1 is deposited
first, on the substrate. Each layer references a palette material:
* a library material, with n(λ) from its formula and an optional extinction
  k; or
* a fixed index n − ik.

The built-in fixed indices (H = 2.35, L = 1.46) are nominal design values,
not film data. For production, users enter the measured dispersion of their
own films as custom materials, e.g. as tabulated CSV.

**Spectrum.** The characteristic-matrix solver of §8d is vectorised over
wavelength; at normal incidence s = p is computed once. Optionally the
uncoated back surface of the substrate is added incoherently, per
polarisation:

    T = T_f T_b / (1 − R_f′ R_b),   R = R_f + T_f² R_b / (1 − R_f′ R_b)

* R_f′ is the film reflectance seen from the substrate side.
* R_b and T_b are the bare back surface, at the Snell angle in the
  substrate.

**Targets.** A target has a quantity, polarisation (unpolarised, s or p),
angle of incidence, wavelength range, constant or linearly ramped value,
comparison (=, ≤, ≥), tolerance band, weight and number of samples
(ADR-054). Quantities:
* R, T, A: fractions against wavelength.
* GD = −dφ/dω (fs), GDD = dGD/dω (fs²) and the phase φ (°) of r or t
  (`of`). GD and GDD come from a local central-difference stencil at each
  target wavelength: amplitudes at ω(1 ± 3·10⁻⁵), and phase differences
  arg(a₊/a₋) taken without unwrapping. They are therefore independent of the
  target grid; a single wavelength is a valid target. Round-off is about
  10⁻⁶ fs².
* Retardance arg(r_p/r_s) or arg(t_p/t_s) (°), compared modulo 360°.
* Rv, Tv (luminous fractions) and L*, a*, b* of the reflected or
  transmitted light (380–780 nm) under a CIE illuminant (D65, D50, D55,
  D75, A, C, F2, F7, F11) for the 2° or 10° observer. One value each.

A spectral target can instead carry a **table** of (λ, value) pairs
(ADR-056): the target value at each listed wavelength, which are then the
samples (up to 20 000; strictly increasing wavelengths, fractions within
0…1). The wavelength range is set from the table. With "=" targets, zero
tolerance and weights equal to the numbers of points, the merit is the RMS
deviation over all listed points, which is the merit function of published
design contests.

Reflection phase is of the coated face: the light reflected by the back face
of a thick plate is incoherent with it. Transmission phase through a plate
(back side bare or coated) is that of the directly transmitted wave,
t_front · t_back, plus one pass through the substrate. The substrate adds
the group delay d dk_z/dω and the GDD d d²k_z/dω², with
k_z = (ω/c)√(n_s² − n₀² sin²θ₀), by the same stencil.

**Back side and substrate** (ADR-055). The back face can be bare or carry
its own coating (`back_layers`, deposition order on the back face). With a
substrate thickness the bulk transmittance Ti = exp(−αd/cos θ_s) enters:
  T = T_f T_i T_b / (1 − R_f′ R_b T_i²),  R = R_f + T_f² R_b T_i² / (1 − R_f′ R_b T_i²).
α is 4πk/λ of the substrate, or the catalogue internal transmittance of a
glass without k data. A library substrate counts as opaque (a metal) when its
k at λ₀ exceeds 10⁻³; so does a fixed substrate with k > 10⁻³. A weakly
absorbing glass therefore stays a plate.

* The merit is the weighted RMS of the violations, each divided by the
  quantity's scale: 1 for fractions, 100 fs for GD, 1000 fs² for GDD,
  360° for phase and retardance, and 100 for L*a*b*. Inequalities only
  penalise the violating side; the tolerance band is free.
* A target is met when no sample violates it by more than 10⁻⁵ of its
  scale: 0.001 % absolute for fractions, 0.01 fs² for GDD.

**Stack formula.** `parse_formula` reads Macleod's notation from the incident
medium to the substrate ("Air | (HL)^7 H | Glass"). Letters are palette keys
(longest match first). A number multiplies the quarter-wave optical
thickness at λ₀ (normal incidence) of the key or group after it, and
"(...)^n" repeats. Physical thickness d = m λ₀ / (4 n(λ₀)). `to_formula`
writes a design back with 4 significant figures, compressing repeated runs.

**Reverse engineering.** `fit_measurement` fits measured R or T spectra (any
number, any angles and polarisations) by bounded least squares (SciPy TRF,
3-point Jacobian, tolerances 10⁻¹²).
* Thickness: one common scale d_j(1 + s) (a rate or tooling error), every
  unlocked layer d_j(1 + e_j), both, or none.
* Index, per palette material used by the layers: an offset Δn, a Cauchy
  dispersion term ΔB/λ² (µm²) and an absorption k ≥ 0, so that
  N = n(λ) + Δn + ΔB/λ² − i(k_material + k).
* The substrate index offset Δn_s.

The fitted design carries the corrections (`PaletteMaterial.index_offset`,
`index_offset_b`, `extinction`; `CoatingDesign.substrate_offset`), so it
keeps reproducing the measurement.

Search strategies:
* *Local:* least squares from the design. With a thickness scale, the
  scale is first scanned (241 values) and least squares runs from the three
  best minima of the scan.
* *Global:* quasi-random Sobol sampling of the whole parameter box
  (thickness ±max error, index terms ±range; k within half the range), then
  least squares from the six best distinct samples and the local starts.
  The best result is kept.

Uncertainties are s²(JᵀJ)⁻¹ with s² = SSR/(m − n). The correlation matrix
is reported. Strong correlations (|r| > 0.98), an ill-conditioned fit
(condition number above 10¹²) and variables at a bound are flagged.

**Starting designs** (all quarter waves at λ₀, using the palette indices at
λ₀):
* broadband AR: (½H ½L H L) at √(λ₁λ₂);
* V-coat;
* high reflector (HL)ᴺH;
* long-pass (½L H ½L)ᴺ and short-pass (½H L ½H)ᴺ. Their stop-band edge
  follows from Δg = (2/π) asin((n_H − n_L)/(n_H + n_L)): λ₀ = edge(1 ∓ Δg);
* Fabry–Perot band-pass [(HL)ᵖH 2L H(LH)ᵖ], optionally coupled cavities;
* notch;
* 45° beam splitter.

**Optimisation:**
* *Refine:* bounded least squares (SciPy trust-region reflective) on the
  unlocked thicknesses, within [min, max].
  - The Jacobian is forward differences (steps 10⁻⁴ relative) of all
    thicknesses in one batched evaluation. The stack matrices are computed
    for every perturbed design at once, which makes a refinement about 20
    times faster than one evaluation per thickness.
  - Equal neighbouring layers are merged first.
  - The best point seen is kept if the time limit is reached.
  - The search stops as soon as every target is met.
  - The design is never made worse.
* *Needle* (Tikhonravov's idea): the needle function is approximated by
  the merit change of an infinitesimal (0.2 nm) needle, for every layer at
  15 positions, at both outer interfaces, and for every other palette
  material.
  - The five most negative needles (one per layer or interface) are
    inserted in turn and refined, until one lowers the merit.
  - When none does, *gradual evolution* adds quarter-wave pairs of two
    palette materials at the incident or the substrate side and refines.
  - This repeats until the targets are met, nothing helps, or the limit is
    reached: 40 steps by default, and the time limit.
  - Needles that did not grow (< 1 nm) are removed at the end and the
    design is refined again. The removal is accepted only if the targets
    met before stay met.
* A back face linked to the front (`back_same_as_front`) carries the front
  layers, so both faces of a symmetric plate are optimised together.
* *Two faces* (ADR-056): a coated back face that is not linked is optimised
  together with the front. The optimiser's layer list is the front layers,
  a locked separator and the back layers (deposition order on the back
  face). Refinement, the batched Jacobian, needles (inside every layer and
  at all four outer interfaces) and gradual evolution (pairs at the
  incident side, at the substrate on the front, and at the outer side of
  the back face) act on both faces; the separator is never merged or
  removed.

**Examples** (`materials/data/coating_examples.json`, generated by
`python -m opticore.tools.coating_examples`; ADR-056). Published design
problems solved with the designer itself and stored with their reference
results and generator settings:
* *OIC 2019 Manufacturing Problem* ("Yucca problem", Poitras et al., Appl.
  Opt. 59(5), A31 (2020)): Ts at 10° and 50° on the contest's 1212 tabulated
  points, through a 1 mm N-BK7 plate coated on both faces; TiO₂ and SiO₂
  films; MF = √(mean(((T − T_target)/0.01)²)). The needle and evolution
  steps run on every fourth contest point, the final refinement on all of
  them. The stored design (best of eight starts, a 60 + 50 quarter-wave
  start) reaches MF 0.781 with 76 + 56 layers, 10.7 µm; the contest's
  designs reached 0.439–2.14. A run that reaches its time limit depends on
  the machine's speed, so the design is stored and its MF recomputed by the
  tests, not regenerated.

**Monte Carlo.** Each layer gets an independent Gaussian thickness error
(relative σ and absolute σ). The result is the 5 / 50 / 95 % bands of the
spectrum, the merit statistics, and the yield (fraction of runs that meet
every target).

**Recipe:**
* Every layer, in deposition order, with its physical thickness, QWOT at λ₀
  and at the monitor wavelength, and cumulative thickness.
* *Optical monitor:* direct monitoring on the part at normal incidence,
  through the plate by default. The signal is traced while each layer grows
  on the previous ones. The recipe gives the start and termination level,
  the turning points inside the layer, and whether the layer ends on a
  turning point (QWOT at λm a whole number of quarter waves).
* A warning is given when a layer changes the signal by less than 0.5 %.
* *Quartz crystal:* the crystal thickness is the film thickness divided by
  the tooling factor; the time is the thickness divided by the rate.
* Exported as CSV or JSON.

**Not modelled:** witness-chip strategies and chip changes, error
self-compensation in turning-point monitoring, rate and index drift,
inhomogeneous or rough layers, and stress.

**Mirror substrates.** A design can use a fixed substrate N = n − ik
instead of a library glass, typically a metal. An absorbing substrate is
opaque: T = 0 and A = 1 − R. The *enhanced* template puts (LH)ᴺ quarter
waves on the metal, low index first. The *protected* template puts a
half-wave low-index overcoat on it, which is absentee at λ₀. The recipe
monitors such parts in reflectance.

**Angular data.** R, T and A (s, p and mean) are computed against the angle
of incidence in the incident medium at up to 8 wavelengths, plus R(λ, θ) and
T(λ, θ) maps. The spectrum can also be shown on a log scale or as optical
density OD = −log₁₀ T.

**Project coatings.** "Save as project coating" stores the stack in
`custom_coatings` (air side first, as §8d expects), with the full design in
`design`, so it can be reopened, re-optimised and updated. A mirror design
keeps its substrate n, k, so the coating works on mirror surfaces.

A coating without a stored design is rebuilt from its layers: the palette
comes from the distinct layer materials and the order is reversed into
deposition order. The rebuilt design reproduces the coating's spectrum
exactly (tested).

### Coating analyses (`coatanalysis.py`)

One stack model serves the coating editor (`/coatings/analyze`: a built-in
or a definition on a chosen incident index and substrate) and the designer
(`/coating-design/analyze`: the working design). A stack has layers
N_j(λ) = n_j − ik_j with thickness d_j (incident side first), an incident
index n₀ and a substrate N_s. It is either opaque or a plate whose bare back
surface is added incoherently, as in the designer.

* **Spectrum.** R, T, A for s, p and their mean (characteristic matrix,
  §8d), and the optical density OD = −log₁₀ T. Further angles of incidence
  can be overlaid.
* **Angle.** R, T (s, p, mean) and A from 0 to 89° at the reference
  wavelength.
* **Phase.** The phases of r and t (s and p, Macleod's convention:
  r_p = r_s at normal incidence) are unwrapped along the grid in ω for
  display.
  - GD = −dφ/dω (fs) and GDD = dGD/dω (fs²) come from the local stencil at
    each wavelength (as for the targets), independent of the grid.
  - Where the power of an amplitude is below 0.1 % (|r|² or T), its phase,
    GD and GDD are undefined (null). At a zero of the amplitude the phase
    jumps by up to π, and its derivatives would show the jump, not the
    dispersion.
  - Ellipsometric angles: tan ψ = |r_p|/|r_s| and Δ = arg(r_p/r_s).
  - Reflection: the coated face. Transmission through a plate: front and
    back faces and the substrate's group delay, as for the targets. The
    phase shown excludes the substrate's propagation phase.
* **Colour.** Under a CIE illuminant with the CIE 1931 2° or CIE 1964 10°
  observer (`photometry/data`, CC BY-SA 4.0):
  - D65 is tabulated; D50, D55 and D75 come from the daylight components
    S₀, S₁, S₂ by the CIE formula. That formula reproduces the D65 table
    (tested), and the white points match the CIE values to 4·10⁻⁴.
  - A is computed from its formula; C, F2, F7 and F11 are tabulated.
  - XYZ of the reflected and transmitted light;
  - chromaticity x y;
  - CIE L*a*b* against the perfect diffuser under the same illuminant;
  - luminous Rv and Tv (Y);
  - a display swatch: linear sRGB normalised to its brightest channel, so a
    dim residual reflection shows its hue.
* **Field.** The standing-wave |E|²/|E_inc|² against depth, by forward and
  backward plane-wave amplitudes in each medium. This is independent of the
  characteristic matrix.
  - s: E is tangential. p: from the tangential H (amplitudes H⁺, H⁻),
    E_x = (q/ε)(H⁺ − H⁻), E_z = (n₀ sin θ₀/ε)(H⁺ + H⁻), |E|² = |E_x|² + |E_z|².
  - The absorptance of layer j is A_j = k₀ Im(ε_j) ∫|E|² dz / (n₀ cos θ₀).
    For an opaque substrate, the power entering it is its absorptance.
  - The field's R and T equal the matrix values to 10⁻¹², and
    Σ A_j + A_sub = 1 − R − T (tested).
  - A map of |E|² against wavelength (61 wavelengths over the analysed band)
    and depth (400 points) shows how the standing wave moves through the
    stack.
* **Profile.** n and k of each layer at the reference wavelength, with
  depth and the quarter-wave optical thickness 4nd/λ.
* **Band statistics.** Mean, minimum and maximum of R, T and A over a
  chosen band.
* **Admittance diagram** (`admittance_locus`, Macleod ch. 2). The running
  admittance Y = C/B is built up from the substrate (Y = η_s) towards the
  incident medium. Through a layer, at phase δ from 0 to δ_j:

      Y(δ) = (i η_j sin δ + Y₀ cos δ) / (cos δ + i (Y₀/η_j) sin δ)

  - Tilted admittances: η = N cos θ (s) and N / cos θ (p), in units of
    the free-space admittance.
  - The end point gives r = (η₀ − Y)/(η₀ + Y).
  - Iso-reflectance circles for a real η₀ have centre
    η₀(1 + ρ²)/(1 − ρ²) and radius 2ρη₀/(1 − ρ²), with ρ = √R.

A built-in opened in the designer (`design_from_builtin`) carries over its
design wavelength, substrate index, specification (as targets) and incident
index. The incident index is a fixed, non-absorbing `incident_index` of the
design (e.g. the glass of a cube beam splitter); it overrides the incident
material.

### Coatings in the system (`analysis/coatings.py`)

* **Ray angles per surface.** For every field, the pupil-quadrature rays
  are traced to the surface at the primary wavelength. The angle of
  incidence is measured in the medium in front of the surface and
  reported as min, mean, max and the 95th percentile.
* **Design context.** "Design…" on a surface opens the designer with:
  - the two media of the interface and the system band;
  - targets at the mean and 95th-percentile angles: R ≤ 0.5 % and ≤ 1.5 %,
    or R ≥ 95 % and ≥ 90 % for mirrors.

  Angles of light that leaves the glass (rear faces) are converted into
  the equivalent angle on the low-index side, using n sin θ invariant
  through the stack. This works because designs describe light from the
  low-index side, and T is reciprocal (R too for lossless films). Rays
  that are totally internally reflected have no equivalent and are
  counted separately.
* **Coatings analysis.** For each coated and bare surface: R and T versus
  wavelength at normal incidence and at the ray-averaged and maximum
  angles; ideal mirrors appear as R = 1. The system transmission is
  estimated as the product of the per-surface transmittances at the mean
  angle, the mirror reflectances and the on-axis bulk transmittance
  (incoherent). It agrees with the ray-traced throughput to < 1 % (tested).
* **Optimising coatings in the system:**
  - Lens-optimiser variables: `coating_scale` (a multiplier of all layer
    thicknesses of a project coating, relative to the starting design)
    and `coat_layer_k` (the thickness of layer k, air side first). Both
    are attached to a surface that uses the coating, and every surface
    with that coating changes together. Built-in coatings must be
    duplicated into the project first.
  - The `surface_reflectance` operand is the unpolarised reflectance of a
    surface averaged over the rays that reach it (pupil quadrature,
    chosen or all fields and wavelengths). Use it for ghost suppression.
  - With the throughput operand, coatings can be optimised for system
    performance alongside or instead of their spectral targets.

* The coating system-transmission estimate uses exp(−α(λ)·t), with α from
  `system.medium_absorption` at each wavelength (catalogue internal
  transmittance when `catalog_absorption` is set).

## 8e. Gaussian beams (`analysis/gaussian.py`)

The beam travels on the unfolded axis. It uses the reduced complex beam
parameter q̂ = q/|n|, where q = z + i z_R and z_R = π|n|w₀²/λ_eff. The reduced
ray matrices are the same as in the y-nu trace:

* transfer [[1, τ], [0, 1]], with τ = t/n_signed (≥ 0 along the beam)
* surface [[1, 0], [−φ, 1]], with φ = (n′ − n)c and signed indices, so mirrors
  are included
* q̂′ = (A q̂ + B)/(C q̂ + D)

The beam follows from 1/q̂ = |n|/R − iλ_eff/(πw²):

* w² = −λ_eff/(π Im(1/q̂))
* R = |n|/Re(1/q̂), with R > 0 for a diverging beam

In each segment the waist lies where Re(q̂) = 0, with w₀² = λ_eff Im(q̂)/π and
z_R = |n| Im(q̂). Reported:

* image-space waist radius and position (from the last surface and from the
  image surface)
* Rayleigh range, depth of focus 2z_R, far-field half-angle λ_eff/(π|n|w₀)
* w and R at every surface
* w(z) along the system

**Multimode beams.** The embedded-Gaussian model is used: λ_eff = M²λ₀, and w
is the real second-moment radius.

**Apertures.** The transmitted fraction 1 − exp(−2a²/w²) of a centred circular
aperture with semi-diameter a is reported for information only.

**Limitations.**
* Paraxial and stigmatic only.
* Coordinate breaks and tilted mirrors are unfolded, so the astigmatism of
  tilted elements is ignored (a note is shown).
* No aberrations.
* Truncation and its diffraction are not propagated. Use the FFT PSF for
  aperture-limited focusing.

* The ABCD trace includes ideal lenses, with φ = |n|/f as in the paraxial
  trace. They used to be skipped, so the beam was not focused.

## 8f. Polarisation ray tracing (`polarization.py`)

Three-dimensional polarisation ray-tracing matrices follow Chipman, Young and
Lam, *Polarized Light and Optical Systems*, ch. 9–10. Each intersection
contributes

    P_j = a_s s sᵀ + a_p p′ pᵀ + k′ kᵀ

where s = (k × N)/|k × N| (any vector ⟂ k at normal incidence), p = k × s
and p′ = k′ × s. The ray's matrix is P = P_N … P_1.

**Amplitudes** are complex and power-normalised, so that |a|² is the power
fraction:
* Refraction uses `thinfilm.stack_amplitudes`: t̃ = τ·√(Re η_sub / Re η₀),
  with τ = 2η₀/(η₀B + C). An empty stack is the bare Fresnel interface, and
  the same coating orientation rule as the scalar trace applies.
* Ideal mirrors use a_s = −1, a_p = +1, so E reverses at normal incidence
  (tested).
* Bulk absorption scales both by √exp(−αL).

**Jones pupil.** J = B_outᴴ P B_in, in local bases. x is the normalised
projection of global x onto the plane ⟂ k, and y = k × x.

**Properties from the singular values σ₁ ≥ σ₂:**
* unpolarised transmission (σ₁² + σ₂²)/2
* diattenuation (σ₁² − σ₂²)/(σ₁² + σ₂²)

**Retardance.** The unitary factor U of J = UH, with its global phase
removed, is split as U = R(θ)·L, where L is a symmetric (linear) retarder and
tan θ = (u₂₁ − u₁₂)/(u₁₁ + u₂₂).
* **Retardance** is the eigenvalue phase difference of L.
* **Basis rotation** θ is the geometric rotation between the local bases for
  skew rays, plus any circular retardance. It is reported separately because
  it depends on the basis convention: uncoated dielectric lenses give zero
  linear retardance but a non-zero basis rotation (tested).

**Outputs:**
* the output polarisation ellipse (azimuth and ellipticity) for a chosen input
  state (x, y, ±45°, R/L circular or unpolarised)
* maps on a square pupil grid
* pupil averages by Gaussian quadrature

**Elements that turn a ray without an interface** (ideal lenses, diffractive
phases between equal media) rotate the field with the ray about k × k′
(s kept, p′ = k′ × s), so it stays transverse and lossless.

**Ideal polarising elements** (`Surface.jones`, applied after the
interface in the plane normal to the outgoing ray k′; a = the element's axis
(cos θ, sin θ, 0) in the surface frame projected normal to k′, b = k′ × a):
* linear polariser: a aᵀ + k′ k′ᵀ (transmission axis a);
* retarder: a aᵀ + e^{iδ} b bᵀ + k′ k′ᵀ (fast axis a, the slow axis delayed
  by δ = 2π × retardance in waves; e^{+iδ} for a longer optical path, the
  same convention as the crystal waves).
The ray trace, spot and throughput analyses ignore them (diagnostic).

**Uniaxial crystals** (§8l): at a crystal face the incident field splits
into the ordinary and extraordinary waves. A trace follows one wave per
crystal (the surface's `crystal_mode`); P_j maps the incident mode vectors to
the kept transmitted wave(s) through a dual basis,
P_j = [out₁, out₂, k′][E₁, E₂, k]⁻¹, where outᵢ is the transmitted field
(power-normalised amplitudes of §8l) of incident mode Eᵢ (in a crystal the
traced mode and its complement k × E). With **crystal waves = both** (the
default), every combination of waves (2^m for m crystals, at most 6
crystals) is traced from the same launch rays and the matrices are added
coherently, Σ_c e^{2πi(L_c − L_ref)/λ} P_c, with L the optical path to a
plane normal to the exit ray through the reference wave's end point (the
combination with the most rays). This describes wave plates and other
elements whose waves leave together; the largest lateral separation of the
waves is reported (beam displacers separate them: use *as prescribed*).

**Mueller matrices.** M = A (J ⊗ J*) A⁻¹ with Stokes S = A (E ⊗ E*),
A = [[1,0,0,1],[1,0,0,−1],[0,1,1,0],[0,i,−i,0]], so S₃ = 2 Im(Ex* Ey) as for
the ellipses. The beam's Mueller matrix is the pupil average of the rays'
matrices (Gaussian quadrature, an incoherent sum over the pupil); it
depolarises when J varies over the pupil. Depolarisation index
DI = √(Σ M_ij² − M₀₀²)/(√3 M₀₀) (1: none, 0: ideal depolariser); output
Stokes vector and degree of polarisation for the input state.

**Limitations:**
* Geometric rays only: no scattering, diffraction or ghost reflections; the
  depolarisation is that of the pupil average.
* Uncoated mirrors are ideal. Coated mirrors use the thin-film amplitudes of their stack on a user-given substrate N = n − ik at one wavelength (§8d).
* Uniaxial crystals only (no biaxial or optically active media); coatings on
  crystal faces are ignored in the polarisation trace (diagnostic).
* The scalar throughput analysis multiplies per-surface unpolarised averages.
  This equals the polarisation trace exactly at normal incidence (tested); for
  oblique, polarisation-coupled paths the polarisation trace is the more
  accurate figure.

### Polarisation bases with mirrors

* Jones pupils use right-handed bases (x′, y′, k). After an odd number m of
  reflections, an ideal mirror is therefore J = diag(−1, 1). Retardance and
  rotation are evaluated on diag(1, (−1)^m)·J, a mirror-image output basis
  (Chipman's geometric transform).
* An ideal mirror then retards nothing; it used to read half a wave. A metal
  mirror retards by arg(r_p / −r_s) in Born & Wolf signs.
* J, the ellipses and the Mueller matrix stay right-handed, so an ideal
  mirror is M = diag(1, 1, −1, −1).
* The unitary part is reduced to SU(2) and taken with Re tr U ≥ 0, since U
  and −U differ only by a global phase. The rotation therefore lies in
  [−90°, 90°], and a pure phase gives no rotation. A coated lens used to
  read 180°.

## 8l. Uniaxial birefringent media (`birefringence.py`)

**Materials.** A catalogue or project material with an `extraordinary`
dispersion record is a uniaxial crystal; its own formula is the ordinary
index n_o. Built in: CALCITE and QUARTZ (Ghosh 1999, 0.20–2.17 µm and
0.20–2.05 µm). The thermal model and tolerance index offsets act on n_o only.

**Crystal media.** The medium after a surface with such a material is a
crystal with the optic axis `crystal_axis` (in that surface's local frame;
default local z) and the traced wave `crystal_mode` (ordinary by default).
Crystals cannot be the object or image space or border mirrors, ideal lenses
or diffractive surfaces (errors). Paraxial data use the phase index along the
local z axis (n_o, or n_e(θ_z) for the extraordinary wave); walk-off and the
other wave are in the real-ray and polarisation analyses only.

**Waves.** With wave vectors K in units of k₀ (|K| = phase index) and the
unit optic axis c, ε = n_o²(I − c cᵀ) + n_e² c cᵀ:
* ordinary: |K| = n_o, E ∝ K × c, the ray along K;
* extraordinary: (K·c)²/n_o² + (|K|² − (K·c)²)/n_e² = 1, D ∝ K × (c × K),
  E = ε⁻¹D, ray (Poynting) direction S ∝ K/n_e² + (1/n_o² − 1/n_e²)(K·c)c,
  which leaves K by the walk-off angle (tan ρ = (n_o² − n_e²)/(n_o² + n_e²)
  at 45° to the axis: 6.23° for calcite at 589.3 nm).

**Refraction.** The tangential part K_t of K is conserved. The normal
component γ follows from |K_t|² + γ² = n² (isotropic medium, ordinary wave)
or, for the extraordinary wave, from Aγ² + Bγ + C = 0 with u = 1/n_o²,
v = 1/n_e², a = K_t·c, b = N·c: A = (u − v)b² + v, B = 2(u − v)ab,
C = (u − v)a² + v|K_t|² − 1. Of the two roots the wave leaving the interface
on side σ is the one with σ S·N > 0 (evanescent waves: decaying away);
no real root is total internal reflection.

**Sequential trace** (`raytrace.trace`). Rays carry K. In a crystal they
travel along S and gain the optical path (K·d) s over a segment of length s
(the ray index n cos ρ); faces conserve K_t; the trace follows the wave of
the crystal's `crystal_mode`. Fresnel losses at crystal faces (throughput)
use the isotropic unpolarised formula with the phase indices of the incident
and the traced waves — the polarisation analysis gives the exact split.

**Amplitudes** (polarisation trace). Tangential E and H = K × E are continuous
(non-magnetic media): for an incident wave a 4 × 4 linear system for the two
reflected and the two transmitted modes (s and p in an isotropic medium,
ordinary and extraordinary in a crystal). Power-normalised amplitudes
a = t √(F_t/F_i) use the energy flux through the face F = Re(E × H*)·N, so
the |a|² of a lossless face add up to 1 (tested to 10⁻¹²); with n_o = n_e they
are the Fresnel coefficients.

## 8m. Vector PSF (`analysis/vectorpsf.py`)

**Debye–Wolf integral** from the real rays. Near the image point C the field
is a superposition of plane waves, E(X) = C₀ ∫∫ a(s) e^{ik s·(X − C)} dΩ with
k = 2πn′/λ. Energy conservation through a pupil element (unit input
irradiance) gives |a|² dΩ = |E_out|² dA with E_out the ray's power-normalised
3D output field (§8f: Fresnel and coating amplitudes, crystals with both
waves summed by default, ideal polarisers and retarders), and
dΩ = |J| dA / s_z with J = ∂(s_x, s_y)/∂(p_x, p_y) from central differences of
traced rays (step 10⁻⁴). Hence

    E(X) = C₀ Σ_q w_q E_out,q √(|J_q|/s_z,q) e^{ik₀ L_q} e^{ik s_q·(X − C)}

over a Gaussian pupil quadrature (rings in ρ², 2 × rings + 8 arms), with L_q
the optical path to the reference sphere about C (§8b). For an aplanatic
system (sin θ = NA ρ) this is the Richards–Wolf integral with its √cos θ
apodisation. The sum separates in x and y (E = M_xᵀ diag(c) M_y), and the
x–z section in x and z.

**Inputs.** Linear (x, y, ±45°), circular, radial or azimuthal polarisation
in the object-space basis of each ray; uniform or Gaussian illumination
(1/e field radius relative to the pupil).

**Outputs.** |E|² = |Ex|² + |Ey|² + |Ez|² (electric energy density, not the
axial Poynting flux) and its components in the image-surface frame, relative
to the peak; profiles through the peak; FWHM in x and y and the area inside
the half-maximum contour (on a 241² grid about the peak); the energy
fractions of the components in the map; the x–z section; the Strehl ratio
(peak against the same pupil without the path differences); the scalar
Airy FWHM 0.5145 λ/NA for comparison. NA is that of the real marginal rays.

**Limits.** Debye approximation (Fresnel number of the focus ≫ 1),
homogeneous image space, no image-space telecentric systems; the map
covers ±2 λ/NA by default, so energy fractions refer to that area.

## 8n. Design advisor (`analysis/advisor.py`)

**Diagnosis: what limits the image** (`POST /api/v1/analysis/advisor`).
* **Wavefront classes.** Per field, the real-ray wavefront at the primary
  wavelength (§8b, 48 × 48 pupil samples) is fitted with the first 37
  Fringe Zernike terms made orthonormal on the actual samples (QR in Fringe
  order). Each coefficient's square over the sample count is a variance, so
  the class variances and the unfitted residual add up exactly to the
  variance of W without its least-squares piston and tilt. Classes: defocus
  (n = 2, m = 0), spherical aberration (m = 0, n ≥ 4), coma (|m| = 1),
  astigmatism (|m| = 2), trefoil (|m| = 3), higher (|m| ≥ 4), residual.
* **Defocus is a focus error, not blur.** Pure spherical aberration at the
  paraxial focus is about 94 % Zernike defocus, so the blur classes are
  those left at each field's best focus: blur RMS² = RMS² − defocus². The
  dominant class is the largest of the others; a field is diffraction
  limited when its blur is ≤ 0.0707 waves (Maréchal, Strehl ≈ 0.8).
* **Findings**, most important first, as structured data (the UI words
  them):
  * *focus*: the image surface is not at the best polychromatic RMS focus,
    by the criterion of the System card (`focus.py`: within 5 % or 0.1 µm of
    the best RMS). A design balanced over field and colour therefore counts
    as in focus even where one field's wavefront shows defocus;
  * *field curvature*: the signed Zernike defocus (sign of +Z4) spreads over
    the fields by more than a quarter wave of defocus (0.25/√12 waves RMS);
  * *aberration*: per field with blur > 0.0707 waves, the dominant class and
    its share of the blur;
  * *axial colour*: the spread of the paraxial back focal lengths over the
    system wavelengths exceeds the depth of focus ±2 λ N²;
  * *lateral colour*: the spread of the real chief-ray heights at the
    largest field exceeds the Airy radius;
  * *distortion*: |distortion| at the largest field > 1 %;
  * *diffraction limited*: none of the above and every field within
    Maréchal.
* **Causes.** The three surfaces with the largest third-order contributions
  (|S_I|, |S_II|, |S_III|, |S_IV|, |S_V|, |C_L|, |C_T| over the sum of the
  magnitudes, §7) for spherical aberration, coma, astigmatism, field
  curvature (Petzval), distortion and the two colours. Third order only, and
  marked approximate for systems that are not rotationally symmetric.
* RMS spots per field are the spot diagram's (hexapolar, density 6, all
  wavelengths).

**Suggestions: what to do about it** (`POST /api/v1/advisor/start`, then
`GET /api/v1/advisor/{id}` and `POST …/cancel`; a background job with
progress).
* **Merit function.** The project's when it has enabled operands with a
  weight; otherwise RMS spot (4 rings, all fields and wavelengths) plus the
  current focal length as a target.
* **Moves**, each one parameter t on a copy of the design:
  * *refocus*: the image distance (when it is not solved);
  * *bend* a lens or cemented group: the same Δc on every curvature but the
    last, whose curvature is solved from a paraxial y–nu trace through the
    group so that its power at the primary wavelength stays the same (thick
    lens; the power is linear in the last curvature);
  * *curvature*: one radius (changes the power);
  * *stop*: a dummy stop between two air gaps, moved with their sum kept;
  * *gap*, *thickness*: an air gap or a centre thickness (bounded:
    −60 %…+100 % + 0.5 mm, −30 %…+50 %);
  * *conic* on the two surfaces with the largest |S_I|;
  * *glass*: the three nearest catalogue glasses in (nd/0.05, Vd/5) of each
    glass, with the image distance as t (refocus), or a single swap when the
    image distance is solved; not for plates (no curved surface), whose
    glass only shifts the focus.
  Surfaces with curvature or thickness solves are left out of the moves
  that would change them.
* **Line search.** The squared merit along t is modelled by a parabola
  through t = 0 and ±h, its vertex evaluated, and the fit repeated on the
  three best points up to six times or until the vertex stops moving (a
  concave fit steps halfway to the bound). The best evaluated point is kept:
  **every gain shown is a real merit evaluation of the changed design**, and
  applying the patch reproduces it to rounding.
* Moves whose results agree to 10⁻⁶ (for example a gap in front of a plate
  and refocusing) are reported once, as the simplest (refocus, bend,
  curvature, stop, gap/thickness, conic, glass). The best eight are
  returned with the RMS spot of every field before and after.
* **Limits.** One parameter at a time: a coordinated change of several
  parameters is the optimiser's job. The search runs in one thread (about
  1 s for the achromat start, 7 s for the double Gauss and 25 s for the
  rough Cooke triplet start, whose merit function aims real rays).

## 8g. Two-surface ghost analysis (`analysis/ghosts.py`)

For every pair of interfaces (i > j) with an index step, the double-reflection
path is built as a sequential system:

    S0…S(i−1), S(i) as mirror (t = −t(i−1)), S(i−1)…S(j+1) backwards
    (t = −t(k−1), medium = forward medium before S(k)), S(j) as mirror (t = +t(j)),
    S(j+1)…image

**Tracing:**
* Rays use the main system's entrance pupil (Gaussian quadrature) and are
  traced exactly through this path.
* Fixed apertures clip ghost rays; automatic apertures do not.

**Energy per ray:** the unpolarised transmittances on all refracting passes
(Fresnel or coating) × bulk absorption × the unpolarised reflectances R_i
and R_j at the ray's actual angles. The reflectances use Fresnel or the
coating stack, incident from the correct side, with total internal
reflection giving R = 1.

**Per ghost:**
* paraxial ghost focus relative to the image surface
* RMS and geometric radius of the ghost footprint on the image surface
* energy fraction of the entrance-pupil power
* relative irradiance: mean irradiance over the geometric footprint compared
  with the main image, both radii floored at the Airy radius. This is used
  for ranking.
* meridional ghost ray paths for display

**Limitations:**
* Two-surface ghosts only, single field and wavelength, no scattering or
  diffraction.
* Systems with mirrors or coordinate breaks are not supported yet.
* Full non-sequential tracing (beam splitting at every surface, stray light)
  remains on the roadmap.

## 8h. CAD models in the optical model

### Assemblies, measurements and sections (`io/cad_assembly.py`)

**Product structure.** STEP/IGES files are read into an XCAF document and
walked from their free shapes. An assembly lists component instances that
refer to a part or a sub-assembly with a location; locations accumulate
down the tree, so repeated parts appear once per instance at their own
place (tested).

* Node ids are 1-based index paths ("1", "1.2", "1.2.3").
* Part names come from the instance or the referred shape. Automatic
  `=>[0:1:…]` reference names are skipped.
* Surface colours are read when the file has them.
* Parsed files are cached by content.

**Display mesh.** The mesh is tessellated part by part in depth-first
order, so every node owns one contiguous range of triangles. The UI hides
and highlights parts with geometry groups over these ranges, and maps a
picked triangle to its part. Exact volume, area, bounding box and solid
count are stored per node; assemblies sum their parts.

**Per-part optics.** `part_roles[node]` overrides the optical role,
material, coating and scatter for that node and its subtree. A part uses
the nearest override on its path, otherwise the model's role. In
non-sequential tracing every visible part of an assembly is a separate
object with its own role, and hidden parts (`hidden_parts`) are left out.

**Measurements.** All measurements are in the global optical frame,
including the model's placement.

* *Distance:* points picked on the display mesh are moved to the nearest
  point of the exact part surface (BRepExtrema_DistShapeShape against the
  part's faces). The distance and Δx, Δy, Δz are computed between the
  snapped points. Picks on lens surfaces use the drawn geometry.
* *Clearance:* the exact minimum distance between two parts or
  sub-assemblies, with the closest points. Touching or interfering parts
  give 0, and the volume of their common part is reported
  (BRepAlgoAPI_Common). STL meshes use their triangle shells, flagged as
  not exact.

**Sections.** BRepAlgoAPI_Section of every visible part with the layout
plane (global x = 0), discretised with a chordal deflection of 0.2 % of the
model diagonal. STL meshes are sliced triangle by triangle. The 2D layout
draws the result in the model colour, with the selected part highlighted.

### Lens and mirror recognition (`io/recognize.py`)

A STEP/IGES solid is analysed on its exact B-rep.

**Symmetry axis:** the common axis of its revolution, cylinder, cone and torus
faces; otherwise the line through its sphere centres; or, for windows, the
normal of its largest plane.

**Optical faces:** a lens or mirror substrate crosses the axis exactly twice.
The two crossed faces are the front and back optical surfaces.

**Face classification:**
* exact planes, spheres, and surfaces of revolution with a line or a centred
  circle as meridian are read exactly
* any other face is sampled by exact line/face intersections along a
  meridian and fitted with an even asphere (c, k, A4–A10); the fit residual
  is reported

**Measurements:** clear semi-diameters come from the face boundaries, and the
centre thickness from the vertex spacing.

**Insertion** puts the element into the sequential prescription after a
chosen surface:
* at its CAD position, where decentred or tilted parts get an exact
  coordinate-break pair, or
* on the axis at a chosen gap
* Touching elements become cemented groups.
* Downstream surfaces keep their positions.
* Clear apertures become fixed semi-diameters.
* The user assigns the glass.
* A mirror is inserted before the image with a paraxial focus solve.

After insertion the element is an ordinary part of the prescription.

### Non-sequential tracing (`nonseq.py`)

**Scene:**
* the lens system as exact solids (the same solids as the STEP export).
  The thin-film coatings of the sequential surfaces apply to the matching
  faces: a hit point within 1e-5 mm of the surface sag in that surface's
  frame belongs to it. Rims are uncoated.
* imported CAD models with an optical role: absorber, mirror (every face
  reflects; R = 1, or the R of the body's coating on its substrate), or
  refractive (catalogue or custom material, optionally coated on every face)
* a detector disc on the image surface

STEP/IGES models are traced exactly. STL models are traced against their
triangles; they are marked faceted and approximate.

**Each step:**
* Find the nearest exact line/face intersection (IntCurvesFace). Outward
  normals come from BRepGProp_Face, so a face's orientation decides inside
  or outside.
* Refract with Snell's law. Touching solids hand the ray straight from glass
  to glass (cemented interfaces).
* Split the power with unpolarised Fresnel coefficients. A coated face
  uses its thin-film R, T and absorptance instead (layers oriented as in
  §8d); the absorbed part is booked as coating absorption. The reflected
  branch is followed when ghost splitting is on.
* Total internal reflection, mirrors, absorbers, surface scattering and
  bulk absorption are applied.

**Surface scattering** (CAD bodies, `optical.scatter`; `bsdf.py`). Each
scattering event spawns one Monte Carlo ray that carries the full scattered
power. The generator is seeded (`seed`), so results are reproducible.
Directions are described by their direction cosines β (a 2-vector) in the
surface's tangent plane; the projected solid angle is cos θ dΩ = d²β, so a
BSDF f(β) (sr⁻¹) sends dP = P_in f d²β into d²β and the total integrated
scatter is TIS = ∫_{|β|<1} f d²β. β₀ is the specular (or regular
transmission) direction and x = |β − β₀|.

* **Lambertian:** f = ρ/π; cosine-weighted about the surface normal on the
  outgoing side, θ = asin √u₁ and φ = 2πu₂, so P(θ < t) = sin²t.
* **Gaussian** (phenomenological, no closed-form f): polar angle from the
  specular direction with (θ cos φ, θ sin φ) ~ N(0, σ²) per axis, so the RMS
  angle is √2 σ. Directions that fall into the surface are redrawn, which
  truncates the distribution at the surface.
* **ABg:** f = A/(B + x^g) (B > 0, g ≥ 0; g = 0 is Lambertian with
  ρ = πA/(B + 1)).
* **Harvey–Shack:** f = b₀ (1 + (x/l)²)^{s/2} (shoulder l > 0 in direction
  cosines, slope s < 0).

For ABg and Harvey–Shack the amplitude (A, b₀) is set so that the TIS at
normal incidence equals the entered fraction: the models are
energy-normalised and the fraction keeps its meaning for every model. At
oblique incidence the lobe is clipped by the horizon:
TIS(b) = A ∫₀^{1+b} shape(x) x θ_in(x, b) dx with b = |β₀| and θ_in the angle
of the circle |β − β₀| = x inside the unit disc (2π for x ≤ 1 − b,
2 arccos((x² + b² − 1)/(2xb)) up to 1 + b); adaptive quadrature with the
kinks as break points, cached per b. Directions are sampled exactly from
f/TIS: x by inverting the tabulated CDF of shape(x)·x (6000-point grid,
geometric near 0), a uniform azimuth about β₀, and rejection of |β| ≥ 1.

The fraction f means something different for each role:

* absorber: the diffuse reflectance ρ (the rest is absorbed);
* mirror: the part of the reflected power that scatters (TIS);
* refractive body: the part of the transmitted power that scatters forward.

**Importance sampling** (`importance` = target and rays per event). The
target is an enabled analytic detector (a disc or rectangle), the
image-surface disc, or the clear aperture of a sequential surface (a disc
at its vertex). At every scatter event with a closed-form BSDF, K extra
rays aim at uniformly sampled points X of the target (area A) and carry
P_in f(d) cos θ_s A cos θ_t /(r² K) (d the unit vector to X, r the
distance, θ_s and θ_t the angles to the scattering surface's and the
target's normals); they are traced like any other ray, so blocking and
further events are included. The regular scattered ray is dropped when its
direction points into the target's cone (the same ray–target test), so the
importance rays and the regular rays together cover every direction once:
the estimate is unbiased. The energy budget then balances only in
expectation; the run reports the power added by the aimed rays and the
power of the dropped regular rays. Gaussian scatter is sampled the normal
way (noted).

**Statistics.** Every ray carries the index of its source ray. A detector's
power is a sum over independent source rays, so its standard error is
σ = √(N/(N − 1) Σᵢ (Xᵢ − X̄)²) with Xᵢ the power that reached it from
source ray i (also for its stray part and for each path). The **path table**
groups detected power by the sequence of scatter (S:object) and partial
reflection (R:object, Fresnel or coating) events, at most six per path,
largest first (15 rows).

**Time limit** (`max_seconds`; the UI's default is 15 s). The source rays
are traced in a random order (its own seeded generator, so the scatter draws
stay those of the seed). The trace stops between source rays once the time
is up, so every traced ray is complete. The traced rays are then a random
subset: their powers are scaled by total/traced source power and renumbered
for the statistics. The energy budget and every detector's power estimate
the whole source, with standard errors over the traced rays. A note says how
many rays were traced, and `complete` is false. Without a limit, or when it
is not reached, the results are those of the full trace. A ghost tree that
splits at every face of many aspheric surfaces (the cell phone lens: about
5000 events per ray with OpenCascade B-spline faces) would otherwise keep
the view busy for minutes.

**Light classes on the detector:**

* *direct*: the ray took only refractions, mirror reflections and TIR, i.e.
  the nominal path, including fold mirrors;
* *after ghost reflections*: at least one partial (Fresnel or coating)
  reflection at a refractive face;
* *after scattering*: at least one scattering event.

**Source:** the system's field and wavelength, on an entrance-pupil disc
overfilled by a factor. For objects at infinity the start points are moved
back along their straight object-space rays to before every object.

**Energy budget:** detected (direct, after ghost reflections, after
scattering) + absorbed per object + coating absorption + escaped + bulk +
below-threshold = 1, checked to 1e-12. The re-emitted (scattered) power is
reported separately; it is already contained in those sinks.

**Limitations:**
* geometric only (no diffraction or polarisation);
* the BSDFs are fitted models (ABg, Harvey–Shack) or phenomenological
  (Lambertian, Gaussian), not measured tables; they are isotropic about β₀
  and the same for every wavelength;
* importance sampling aims at one target per run;
* mirrors reflect on every face;
* diffractive phases are not applied;
* single field and wavelength per run.

* **Media.** Lens solids carry the id of the surface that starts their
  glass. Their index is the glass at that element's temperature; CAD bodies
  are at the system temperature. Bulk absorption uses
  `system.medium_absorption` at each ray's own wavelength: the catalogue
  internal transmittance when `catalog_absorption` is set, else the
  constant α. These are the same media as in the sequential trace and
  `nsdirect`.

### Light sources and detectors (`nssources.py`)

Sources and detectors are general building blocks for the non-sequential
trace, not device presets. A fibre end, LED, laser diode or flash lamp is a
source; a sensor, photodiode or receiving fibre is a detector. They are
stored in the project (`sources`, `detectors`).

* **Placement (both).** Position in the global optical frame and rotation
  `R = Rx·Ry·Rz` (degrees, as for CAD models). A source emits about its
  local +z axis. A detector receives light travelling along its local +z
  axis; with zero rotation that is the direction of the optical axis.
* **Anchors.** A placement may name a surface (`anchor`). Position and
  rotation are then relative to that surface's vertex frame:
  p = O + M (R p_local + t). The object surface's vertex lies at −d₀ on the
  axis. An anchored fibre end or sensor therefore moves with its surface
  when thicknesses change, which the optimiser needs when it varies
  distances. For a coordinate break the frame is the one before the break.
  Deleting the anchor surface moves the anchor to the first surface kept after
  it, whose vertex frame is the deleted one's for a plain surface, so the
  source stays put (an anchor to a missing surface is refused with 422).
* **Aim.** A placement may give an aim point in the frame of its
  position. With d = (aim − position)/|aim − position| the first two angles
  become a = atan2(−d_y, d_z) and b = asin(d_x), so that Rx(a)·Ry(b)·ẑ = d.
  The third angle stays the roll about the aimed axis. An aimed source keeps
  pointing at its aim point when it moves. A detector's +z axis aims the
  same way: it receives light travelling towards the point.
* **Source, emitting shape.** Point, disk, rectangle, or a sphere or box
  volume. The spatial profile is uniform, or Gaussian
  `exp(−2(x²/wx² + y²/wy²))` truncated by the shape.
* **Source, angular law.** θ is measured from +z and the azimuth is uniform.
  * collimated;
  * isotropic over 4π (cos θ uniform in [−1, 1]);
  * Lambertian (sin²θ uniform);
  * cosⁿ (cosⁿ⁺¹θ uniform);
  * uniform cone (cos θ uniform in [cos θm, 1]);
  * elliptical Gaussian (tan θx, tan θy normal with σ = tan θ₁/e²/2);
  * tabulated rotationally symmetric radiant intensity I(θ) (inverse CDF of
    I(θ) sin θ).
  The Lambertian, cosⁿ and Gaussian laws can be truncated at a maximum
  angle.
* **Spectrum and sampling.** Wavelengths carry weights (default: the
  system's). Rays are split between wavelengths by largest remainder, so the
  spectral split is exact, and every ray carries its own wavelength through
  the indices and coatings. Sampling is seeded Monte Carlo. Each ray carries
  power/N, and results are in watts.
* **Start medium.** A source whose centre lies inside a refractive solid
  emits into that medium (solid classifier).
* **Gaussian beams.** Gaussian spatial and angular laws with
  θ = λ/(π w₀) form the geometric (Wigner) ray-ensemble model of a
  Gaussian beam. Its second moments propagate exactly like the beam: in
  free space and through paraxial optics, w² = A²w₀² + B²θ². There is no
  interference or diffraction.
* **Gaussian beam source** (kind `gaussian_beam`).
  * Parameters: the waist radii w₀ₓ, w₀ᵧ (1/e² intensity), the beam
    quality M² ≥ 1 and the waist position z_w along +z from the source
    plane (> 0 converging to a waist ahead, < 0 diverging from a waist
    behind).
  * For each ray's wavelength the far-field 1/e² half-angle is
    θ = M²λ/(π n w₀), where λ is the wavelength (in the system air, as every
    wavelength) and n the index of the medium the source emits into: the
    surrounding air (n = 1), or the solid the source's origin lies in for the
    non-sequential trace (a note gives n), or the object space for the
    direct path. The wavelength in the medium is λ/n. A source inside glass
    used to diverge as in air, n times too fast.
  * Positions x_w and direction tangents t at the waist are normal with
    σ = w₀/2 and θ/2. The ray starts on the source plane at x_w − z_w·t, so
    position and direction are correlated, and
    w(z)² = w₀² + θ²(z − z_w)² holds exactly for the ray ensemble (the
    embedded-Gaussian model of an M² beam).
  * `/sources/describe` reports, per axis at the source's first
    wavelength, in the surrounding air (`medium_index`):
    * the divergence;
    * the Rayleigh range z_R = π n w₀²/(M²λ);
    * the beam radius w₀√(1 + (z/z_R)²) on the source plane (z = −z_w);
    * the wavefront radius z(1 + (z_R/z)²), negative when converging.
* **Spectra** (`spectra.py`). A spectrum is n bins of equal width over a
  band, each represented by its centre, weighted by its power and
  normalised to a sum of one. It fills the source's wavelength list.
  * Blackbody: Planck's law B(λ, T) = 2hc²/λ⁵/(exp(hc/λkT) − 1), integrated
    over each bin by 16-point Gauss–Legendre. The band's fraction of σT⁴/π
    is reported.
  * Gaussian line: centre and FWHM, over centre ± 2 FWHM, with exact bin
    integrals (error functions). A model of an LED or a broadened line.
  * Flat band: equal weights.
* **Detectors.** A detector is an analytic plane patch, circle or
  rectangle, intersected exactly and compared with the nearest B-rep hit.
  * Optional acceptance half-angle: light inside the area but outside the
    cone is "rejected". This models a fibre core with its NA:
    θ = asin(NA/n).
  * Mode *absorb* (rays end) or *monitor* (a transparent measuring plane;
    rays continue).
  * One-sided (light from the back is blocked in absorb mode, ignored in
    monitor mode) or two-sided.
* **Detector results.** Power (W) and fraction of the emitted power, direct
  part, power by source and by wavelength, rejected and back-blocked power,
  an irradiance map (W/mm²), peak, centroid, RMS radius, second-moment
  widths 2σ (the 1/e² radius of a Gaussian beam) and the incidence-angle
  distribution.
* **Energy budget.** Rejected and back-blocked power enter the budget.
  Monitors are not part of it, because their rays continue.
* **Defaults.** Without project sources, the system field source of the
  previous versions is used; without detectors, a disc on the image
  surface.

### Photometry and colorimetry (`photometry/`)

Light is weighted with the CIE 1931 standard colorimetric observer. The data
are unmodified CIE datasets (CC BY-SA 4.0), with their sources and MD5 sums in
`photometry/data/README.md`:

* x̄, ȳ, z̄ of the 2° observer, 360–830 nm at 1 nm (CIE 018:2019, Table 6).
  The photopic efficiency is V(λ) = ȳ(λ).
* The scotopic V′(λ), 380–780 nm (CIE 018:2019, Table 2).
* D65, 300–830 nm (ISO/CIE 11664-2:2022, Table B.1).

Values are interpolated linearly between the tabulated wavelengths and are
zero outside them. Illuminant A comes from its defining formula.

* **Luminous flux:** Φv = K_m Σ P V(λ), with K_m = 683.002 lm/W.
  * The scotopic flux uses K′_m = 1700.13 lm/W.
  * Both give 683 lm/W at 555.016 nm, the definition of the candela.
* **Colour:**
  * Tristimulus values (X, Y, Z) = Σ P (x̄, ȳ, z̄).
  * Chromaticity x, y, and u′, v′.
  * The correlated colour temperature is that of the Planckian radiator
    nearest in CIE 1960 (u, v). The locus is computed with the same tables
    and c₂ = 1.4388·10⁻² m K. The minimum is found on a grid and then by
    Brent's method in mireds.
  * Duv is the signed distance, positive towards larger v. The CCT is
    reported only for |Duv| ≤ 0.05 and 1000–100 000 K.
  * sRGB uses the IEC 61966-2-1 primaries and the D65 white; colours outside
    the gamut are clipped and counted.
* **Light sources:** the quantities of a source's wavelength samples and
  power. These are exact for the discrete spectrum the tracer uses.
* **Detectors:** the same quantities for the rays that reach the detector.
  * The X, Y, Z maps are per pixel area.
  * Illuminance K_m Y in lux; the average illuminance is the flux over the
    detector area.
  * The true-colour image is the linear sRGB of every pixel with one
    exposure for the map (its brightest channel is 1), clipped and encoded.
  * The standard errors of the flux, x, y, CCT and Duv come from the
    source-ray estimator. The colour errors use each hit's linearised
    contribution, (X_i − x S_i)/S, and the gradients of CCT and Duv in
    (x, y).
  * The errors treat the rays as independent draws. The wavelength split is
    in fact stratified, so the errors are upper bounds.

## 8k. Relative illumination, sensor and image simulation (`analysis/imaging.py`)

(The chief rays of the distortion table are not stopped by a
central obscuration, so obscured telescopes simulate too. Image-height
fields are resolved to object-space fields first, and every PSF node gets a
kernel, as in §8o.)

**Relative illumination** (energy form, real rays). A flat field of uniform
radiance L sends from an object element dμ (a solid angle for an object at
infinity, an area otherwise) the power L·G·T·dμ, with G the object-side
étendue density of the beam (its cross-section perpendicular to the
collimated beam, or its projected solid angle at a finite object point) and
T the transmitted fraction (vignetting; with *transmission* also the rays'
Fresnel, coating and absorption transmission). The power lands on the image
area given by the real chief-ray map, so E = L·G·T/(dA/dμ) with, for
rotational symmetry, dA/dΩ = h′(dh′/dθ)/sin θ (object at infinity) or
dA/dA_obj = (h′/h)(dh′/dh). G and T come from a Gaussian pupil quadrature
with Jacobians of the launched rays (central differences, step 10⁻⁴ in pupil
coordinates), dh′ from central differences of the chief ray. RI = E/E(axis).
Local blur by aberrations does not change a flat field's irradiance, so the
chief-ray map is the right area element (a fixed-field image-side solid
angle is not: aberrations change where a beam lands by about
(spot size)/(f·NA), 0.3 % for the sample doublet). For an ideal lens with
the stop at the lens it gives cos⁴θ exactly, at any aperture. Image-height
field types are traced through their object-space equivalents (the image
simulation does not support them yet).

**Sensor** (`OpticalSystem.sensor`, optional): square pixels of pitch p
whose sensitive area is a centred square of width w = p·√(fill factor);
pixel MTF |sinc(νw)| (sinc x = sin πx/πx), Nyquist 1/(2p), full well, read
noise and bit depth. With a sensor the MTF analysis also returns the pixel
MTF, the Nyquist frequency and the system MTF (lens × pixel) per field.

**Image simulation.** The scene (Siemens stars, bar targets, dot grid,
checkerboard, slanted edge) is defined on the ideal, distortion-free image
plane. On a sub-pixel grid of the real image plane:
1. each sub-pixel at radius r maps through the real chief-ray table back to
   its field and on to the ideal radius k·g(v) (k from a near-axis chief ray,
   g = tan for angle fields, else the field), where the scene is sampled
   (2 × 2 supersampling);
2. relative illumination multiplies the scene;
3. blur: polychromatic FFT PSFs (§8b; each wavelength's PSF shifted by its
   chief-ray offset, weighted by the wavelength weights, resampled onto the
   sub-pixel grid by 3 × 3 bilinear samples per cell, unit sum) at a
   grid × grid net of field points over the sensor; the image is
   Σ_k (w_k·I) ⊛ K_k with bilinear node weights w_k that sum to one, so
   every source point is blurred by the interpolated PSF of its own position
   and the signal is conserved exactly (the grid is padded by two kernel
   radii; light from one radius outside the sensor is included);
4. pixels integrate the image over their sensitive squares (the exact box
   transfer function on the periodic grid) and are sampled at their centres;
5. the brightest noiseless pixel reaches the chosen exposure of the full
   well; shot noise (Poisson in electrons) and read noise (Gaussian) are added
   with a fixed seed; the signal is clipped and quantised.
The result holds the ideal scene, the noiseless optical image and the
sensor image (uint16), the relative-illumination and distortion tables used,
the PSF nodes and the energy bookkeeping. Limits: rotationally symmetric
mapping of distortion and relative illumination; scalar FFT PSFs within
their window (about grid·λ·F across); no colour sensor (the scene is
monochrome, the PSF polychromatic); at most 512 × 512 pixels.

## 8o. Live colour image (`analysis/liveimage.py`)

`POST /api/v1/analysis/live-image`: a test scene or the user's photo imaged
through the design in red, green and blue, fast enough to follow a dragged
value.

* **Channels.** Red, green and blue are the longest, primary (or middle) and
  shortest system wavelength when there are three or more, otherwise
  Fraunhofer C, d and F. The trace uses a copy of the system with just these
  wavelengths (green primary).
* **Scene.** It lies on the green ideal image plane: first order, no
  distortion, scale k from a near-axis chief ray (`|k| tan v` for angle
  fields, `|k| v` for object heights). A photo (sRGB bytes) is linearised
  (IEC 61966-2-1), centred and cropped to the frame's aspect. Test scenes
  are those of §8k, white light.
* **Frame.** The sensor when one is defined, otherwise the largest rectangle
  of the scene's aspect inside the image circle of the largest field (green
  real chief ray). A zoom z shows 1/z of the frame at the same pixel count;
  `center` (−1…1) moves that region from edge to edge.
* **Mapping per channel.** An output pixel at radius r receives the scene
  from the ideal radius `|k| g(v_c(r))`, where v_c inverts the real
  chief-ray height of channel c traced at λ_c. Chief rays are position
  references: apertures and obscurations do not stop them; the relative
  illumination carries the vignetting. The heights are traced at ten fields
  from the axis to the largest field (plus a few beyond for the margin), and
  the smooth distortion factor `h / (|k| g(v))` is interpolated by a cubic
  spline (within 0.02 µm of direct traces on the samples). Lateral colour
  therefore displaces the channels against each other.
* **Relative illumination.** §8k at the green wavelength, multiplied in
  linear light; the largest field is always a sample.
* **Blur.** Monochromatic PSFs at λ_c (their defocus against the image
  surface carries the axial colour) at a g × g net over the shown region
  (g = 3 for preview, 5 for full quality; 2 at high zoom, where the region
  spans little of the field), each centred on the channel's own chief ray.
  Every source pixel is blurred by the bilinearly blended PSFs of its
  position (weights summing to one), so each channel conserves its energy
  exactly. In mirror-symmetric systems (axial, rotationally symmetric or
  biconic surfaces, no gratings or crystals) the PSF of (−x, y) is the
  mirror image of that of (x, y), which is reused (bit-identical).
  * *Diffraction PSF*: the FFT of the pupil function (§8b). The pupil grid
    starts at 32 (preview) or 64 (full) and doubles until at most 1 % of
    neighbouring pupil samples differ by more than 0.5 (preview) or 0.25
    (full) waves. A step of half a wave puts that sample's ray at the edge
    of the FFT window (transverse aberration N λ grid ΔW), so its light
    would alias. The native PSF is sampled at least four (preview) or eight
    (full) times per output pixel while the PSF is unresolved, never finer
    than λN/8, and binned into the pixels (energy exact). It is then cropped
    to the smallest square holding all but 0.1 % of its energy, capped at
    129 (preview) or 257 (full) pixels; a note reports a kept fraction
    below 98 %.
  * *Geometric PSF*: where even 128 (preview) or 256 (full) samples cannot
    hold the aberrations, these are many waves and diffraction is
    negligible. The PSF is then the histogram of real rays of a uniform
    pupil grid about the chief ray (a note says how many). The preview also
    uses it when its pixels are at least 2 λN, so the diffraction structure
    is under half a pixel.
* **Display.** Linear light to sRGB with the same exposure for the ideal
  and the lens image. There are no sensor pixels or noise (that is §8k).
  Read-outs at the frame corner and the region's outer corner: red-minus-
  blue chief-ray radius (µm and pixels), distortion and relative
  illumination.
* **Requests.** The preview (at most 192 px wide) follows every change, and
  the full quality runs half a second after the last one. Each browser tab
  sends a channel id: a newer request on the channel stops an older render
  at its next step (HTTP 409, ignored by the client), so a full-quality
  render never delays the next drag. The decoded photo is cached by content
  (two entries); the engine keeps no other state.
* **Image-height fields.** Real or paraxial image heights are first
  replaced by the object-space fields they resolve to (§3, `fields.py`,
  at the system's primary wavelength; `with_object_space_fields`, also used
  by §8k), so the frame's corner is the largest image height.
* **Nodes beyond the chief rays.** Every PSF node gets a kernel, so the
  blending weights always sum to one. A node beyond the last chief ray (for
  example a corner exactly on the image circle) uses the PSF at the end of
  the map in its direction. This also holds in §8k.
* **Limits.** The scalar diffraction and geometric PSFs are those of §8b and
  the spot diagram. Image-space telecentric systems are refused (as in
  §8k). Real-ray aiming makes each PSF cost several traces: about 1.5 s per
  preview for the Cooke triplet sample and 0.8 s for the cell phone lens.

## 8j. Lens elements as parts (`analysis/elements.py`)

Each glass between two consecutive refracting surfaces is one element (a
cemented doublet has two). The data describe the design at 20 °C: the
active configuration with the environment model off and the solves
resolved, so a drawing does not change with the operating temperature.

* **Rim.** The element's outer radius R is the largest of its surfaces'
  mechanical semi-diameters (`Surface.mech_semi_diameter`); a surface
  without one counts with its clear (effective) semi-diameter, plus the CAD
  export's margin. A surface with a mechanical semi-diameter ends there and
  a flat perpendicular to the axis continues to the rim; a surface without
  one continues to the rim.
* **Chamfers.** `Surface.chamfer` c is a 45° protective chamfer at the rim on
  that side: for r > R − c the face is replaced by the chord from the face
  at R − c to the rim point c from the face.
* **Profiles** are the exact sags (meridional y-z section for biconic and
  Zernike surfaces). Thickness T(r) = t + z_b(r) − z_f(r) with these
  boundaries; edge thickness T(R) (before chamfers); the minimum of T is
  checked (the surfaces must not meet).
* **Volume** 2π ∫₀ᴿ r T(r) dr by Gauss–Legendre quadrature (48 nodes per
  smooth piece, breaks at the flats and chamfers), exact for these
  boundaries; **mass** = volume × catalogue density.
* **Cost.** Where every glass carries a catalogue relative cost (AGF `OD`),
  the system's mass-weighted relative cost; the built-in glasses have none.
* **Glass code** 1000(nd − 1) and 10 Vd, each rounded (517642).
* **ISO 10110 data** from the project's enabled tolerances: radius and
  centre-thickness tolerances; 3/A(B/C) from the power, irregularity and
  rotational-irregularity tolerances (fringes at the test wavelength);
  Zernike form terms; 4/σ (arc minutes) from surface tilts and the tilts of
  element groups that contain the element; decenters; Δnd and ΔVd from the
  index and Abbe tolerances. Indications the project does not specify
  (0/ stress birefringence, 1/ bubbles, 2/ inhomogeneity, 5/ surface
  imperfections) are left open.
* The UI lays the drawing out (A4 landscape SVG, `lib/drawing.ts`) from
  these data only and embeds them as JSON in the SVG's `<metadata>`.

`POST /api/v1/elements` returns the elements, their outlines for drawings,
masses and the totals. Mechanical data never change the ray trace.

**CAD export.** Element solids use the same rim, flats and chamfers, so the
exported solid volume equals the element volume (tested to 1e-9). The
optional mechanics (`include_mechanics`) add, for axial systems without
mirrors or coordinate breaks:
* a barrel: a tube whose bore is the largest element rim, wall
  max(1 mm, 10 % of the bore), from the first element's front rim to the
  last element's back rim;
* cells: rings from a smaller element's rim to the bore, as long as its edge;
* spacers between elements separated by air: outer radius the bore, flat
  ends touching each lens where it protrudes most between the spacer's bore
  and the lens rim. The bore is an upper bound of every ray that passes the
  clear apertures in the gap: a ray's distance from the axis is convex along
  its path, so it stays under the chords through the aperture edges taken at
  both ends of each surface's sag span; the bound is convex between its
  breakpoints, so a polyline through samples of it lies on or above it.

## 8r. Wave optics (`wave/`)

Five modules solve wave problems that geometric optics cannot:
* fibre modes;
* the physical-optics propagation (POP, rays inside the lenses);
* the beam propagation method (BPM, the wave inside the lenses);
* a 2D FDTD Maxwell solver;
* a rotationally symmetric 3D FDTD.

POP and the BPM are scalar. The FDTD solvers are vector Maxwell solvers,
either 2D (invariant along x) or 3D for bodies of revolution. None is a
general 3D field solver for arbitrary structures (ADR-020, ADR-021).

### Fibre modes (`wave/fibermodes.py`): Maxwell's equations for step-index fibres

Core radius a, indices n₁ > n₂, k₀ = 2π/λ, V = k₀ a √(n₁² − n₂²),
u² + w² = V². Exact vector modes from Snitzer's eigenvalue equation
(Snyder & Love ch. 12; Okamoto ch. 3), with ξ = J′ᵥ(u)/(u Jᵥ(u)),
κ = K′ᵥ(w)/(w Kᵥ(w)) and δ = n₂²/n₁²:

    (ξ + κ)(ξ + δκ) = ν² (1/u² + 1/w²)(1/u² + δ/w²)
    TE₀ₘ: ξ + κ = 0     TM₀ₘ: ξ + δκ = 0
    HEᵥₘ / EHᵥₘ: the − / + root of the quadratic in ξ

Weakly guiding LP modes: u Jₗ₋₁(u)/Jₗ(u) = −w Kₗ₋₁(w)/Kₗ(w). The equations
are multiplied through by u Jᵥ(u) (and K₀) so that they have no poles. Roots
are bracketed on a fine u grid and refined with Brent's method. Results:
n_eff, b, degeneracies, single-mode cut-off λc = 2π a NA / 2.404826, LP
field profiles and the LP01 mode field diameters (Petermann II, 1/e²
intensity, best-overlap Gaussian and its overlap; Marcuse's formula for
comparison). Indices from the user or from library materials (cladding
material plus NA).

### Radial index profiles (`wave/fibreprofile.py`)

The index is the cladding's n_clad(λ) (a library material or a constant) plus
an offset that is the same at every wavelength:

* step: Δn = dn for r < a;
* graded: n² = n₁² (1 − 2Δ (r/a)^α) for r < a, with n₁ = n_clad + dn and
  2Δ = 1 − n_clad²/n₁², so the index is continuous at r = a (α = 2:
  parabolic);
* layers: rings (outer radius, Δn) from the axis outwards (W, trench and
  multi-clad profiles).

A request gives the core contrast as Δn, or as n_core or NA at its
wavelength, which becomes Δn.

Weakly guiding LP_lm modes of ψ″ + ψ′/r + (k² n² − β² − l²/r²) ψ = 0:

* **Piecewise-constant profiles** (step, layers) are solved exactly. In each
  layer ψ = A Z₁(q r) + B Z₂(q r) with (J_l, Y_l) where n > n_eff and
  (I_l, K_l) below; the axis layer holds the regular solution. (ψ, ψ′) is
  carried through the interfaces and renormalised in every layer, and the
  cladding must hold K_l alone. The mismatch has no poles; its roots are
  bracketed on 800 points and refined by Brent's method.
* **Graded profiles** use second-order finite differences of (1/r)(r ψ′)′ on
  a cell-centred grid r_i = (i − ½) h, symmetrised with √r_i (a symmetric
  tridiagonal eigenproblem for β²). Two grids h and h/2 are combined by
  Richardson extrapolation. The domain grows until every mode has decayed by
  e⁻²⁰, and h divides every interface radius.
* The step profile's vector modes come from fibermodes.py (above); this
  module adds its LP01 field quantities and the cut-off.

LP01 field quantities: the Petermann II mode field diameter
2√2 [∫ψ² r dr / ∫ψ′² r dr]^½, the effective area 2π (∫ψ² r dr)² / ∫ψ⁴ r dr
and the power in the core (below a, or below the outer radius of a layered
profile's highest ring). An exact field is integrated by Simpson's rule layer
by layer with its analytic slope; a finite-difference field by midpoint sums
on both grids (the slope on the cell faces) with Richardson extrapolation.

Dispersion of LP_lm: n_eff on a five-point stencil in wavelength
(h = 2·10⁻³ λ), group index n_g = n_eff − λ dn_eff/dλ and
D = −(λ/c) d²n_eff/dλ² in ps/(nm·km). The material part is the cladding glass
alone on the same stencil (the core keeps its offset); the waveguide part is
the rest. The zero-dispersion wavelength is the root of D (Brent's method).
Each wavelength starts from the previous one's root in a narrow bracket. A
root found there counts only if its field has m − 1 radial nodes (the
oscillation theorem), so a neighbouring mode is never taken for it;
otherwise the full search runs.

Cut-off of LP_l1 (l ≥ 1): at n_eff = n_clad the cladding field is r^−l, so
F = (a ψ′ + l ψ)/|(ψ, a ψ′)| = 0 at the edge a of the index structure. ψ comes
from the exact layer solutions at n_eff = n_clad (J/Y, I/K, or r^l and r^−l in
a ring at the cladding index), or for a graded profile from integrating the
radial equation from the axis (DOP853, rtol 10⁻¹²). F > 0 as λ → ∞ and changes
sign at every LP_lm cut-off. The scan runs from 50 µm down to 0.05 µm and stops
at the first sign change. F < 0 at 50 µm, or an LP_l mode guided there,
places the cut-off above the range, and none is reported. A wavelength or
cut-off outside the cladding material's data range is reported as
extrapolated. The step profile's cut-off uses the same model (with a
dispersive cladding it differs from 2π a NA(λ)/2.405 at the operating
wavelength).

Limits:
* Graded and layered profiles have scalar LP modes only (no polarisation
  splitting).
* The core shares the cladding's material dispersion (a constant offset).
* No bends, absorption or microbending.

### Fibre cross-sections (`wave/fibre2d.py`)

Full-vector modes of an arbitrary cross-section: circles, ellipses and
rectangles over a background, and hexagonal hole lattices (photonic crystal
fibres); where regions overlap, the last one counts.

* Transverse E on a Yee mesh: Ex at (i + ½, j), Ey at (i, j + ½), Ez at
  (i, j). The eigenproblem β² for (Ex, Ey) is P·Q, solved by shift-invert
  (ARPACK) near an index guess. The default guess is a step-index core of the
  radius of the high-index region at the centre.
* Interfaces: in a cell that an interface crosses, the permittivity is the
  averaged tensor ε = ε_∥ (I − n n) + ε_⊥ n n. ε_∥ is the mean of ε over
  64 × 64 sub-samples, ε_⊥ the harmonic mean and n the interface normal. The
  off-diagonal terms are included (Ey averaged to the Ex points and Ex to the
  Ey points). Ez sees ε_∥. A staircase would leave a first-order error at
  curved interfaces.
* A structure symmetric about both axes is solved on one quadrant, with
  electric and magnetic walls chosen for the polarisation (Ex: electric wall
  at x = 0, magnetic wall at y = 0). Other structures are solved on the full
  window.
* Leaky modes: a perfectly matched layer (coordinate stretch
  s = 1 − i σ (d/w)², σ = 5) makes n_eff = n + iκ complex. The loss is
  (20/ln 10) k κ dB/m.
* Optional refinement solves on meshes h and h/2 and extrapolates the
  complex n_eff (Richardson).
* Results: n_eff, κ and the loss of the modes nearest the guess, the power in
  the core and the effective area of |E_t|². Intensity and index maps are
  given for the most core-confined mode.

Limits:
* Isotropic, non-magnetic media.
* A uniform mesh of at most 700 cells per side.

### Fibre examples

The library has four fibre templates (category *Fibres*). Each opens
its view with the stored settings (`analysis_settings.fibermodes` or
`fiber2d`):

* a single-mode step fibre: a = 4.1 µm, Δn = 0.0052 over fused silica,
  1550 nm, with dispersion over 1.2–1.65 µm;
* a graded 50/125 multimode fibre: α = 2, NA 0.2, 850 nm;
* a trench-assisted single-mode fibre: rings 4 / 9 / 14 µm, Δn
  +0.005 / 0 / −0.005, 1550 nm;
* the six-hole microstructured fibre of the multipole benchmark.

Their optics is a 1:1 relay of two ideal lenses at the fibre's wavelength.
tests/test_fibre_examples.py runs the stored settings as the views send them.
The request mapping of `samples.fibre_request` and the frontend's
`lib/fibre.ts` is pinned by a fixture.

### Gratings: rigorous coupled-wave analysis (`wave/rcwa.py`, `wave/rcwaapi.py`)

A grating is periodic in x with period Λ. It is a stack of layers between a
lossless incident medium and a substrate. Each layer is one of:

* uniform;
* lamellar: a ridge of width fill · Λ centred in the period;
* a relief profile of the layer's thickness: sinusoidal, sawtooth (blazed) or
  trapezoid. It is cut into a user-set number of lamellar slices, each with
  the profile's width at its mid-height.

Media are n + iκ or library materials.

* **Orders.** m = −M … M with k_x,m = k_x,in + m λ/Λ (the grating equation
  n sin θ_m = n_in sin θ + m λ/Λ) and k_y = k_y,in, which covers conical
  incidence.
* **Fields.** The tangential fields obey d/dz′ [Ex, Ey] = P [Hx, Hy] and
  d/dz′ [Hx, Hy] = Q [Ex, Ey], with P and Q as in R. C. Rumpf (PIER B 35, 241
  (2011)). The convention is exp(+jωt), so the medium is the pointwise
  conjugate of the physics' ε(x) = (n + iκ)². Its convolution matrix is
  T(ε)ᴴ (coefficient n is conj c₋ₙ), not the conjugate of T(ε), which would
  mirror an asymmetric profile.
* **Li's Fourier factorisation** (JOSA A 13, 1870 (1996)):
  * for E_y and E_z, parallel to the grating's interfaces, the Toeplitz
    matrix of ε (Laurent's rule);
  * for E_x, normal to them, the inverse of the Toeplitz matrix of 1/ε (the
    inverse rule).

  This is what makes TM and metallic gratings converge. With Laurent's rule
  alone, a metallic TM grating's efficiency wanders as the orders grow
  (0.67 → 0.58); with Li's rule it converges monotonically (0.652 → 0.731).
* **Modes.** Ω² = P Q = W λ² W⁻¹ and V = Q W λ⁻¹. Uniform layers are solved
  analytically.
* **S-matrices.** Each layer's matrix is taken relative to a zero-thickness
  gap whose modes have k_z = 1 in every order (permittivity I + Kx² + Ky²),
  so no gap mode is singular at a Wood anomaly. The layers are joined by
  Redheffer star products; the incident and substrate half-spaces follow
  Rumpf.
* **Efficiencies.**
  * R_m = Re(−k_z,ref/k_z,in) |r|² and T_m = Re(k_z,trn/k_z,in) |t|², with r_z
    and t_z from div E = 0.
  * A lossless structure conserves energy to rounding.
* **Outputs.**
  * Per propagating order: the angles, R_m and T_m; the absorption.
  * The zeroth orders projected on their TE and TM unit vectors. Phase delays
    are given in the physics sign (k · OPL positive), and the retardance as
    TE − TM.
  * A convergence estimate: the largest change of any efficiency between M
    and 0.6 M harmonics. Above 10⁻³ it is flagged.
  * Wavelength or angle sweeps of chosen orders.
* **Execution.** From the API the runs go to the shared process pool (single-threaded BLAS workers, the sweep in parallel; ADR-049).
* **Limits.**
  * Relief profiles are staircases, which converge with the number of
    slices.
  * Isotropic media.
  * A corner of a metallic profile converges algebraically in the harmonics.

### Crossed gratings and metasurfaces: 2D RCWA (`wave/rcwa2d.py`)

The structure is periodic in x and y with a rectangular cell Lx × Ly. A layer
is uniform, a 1D profile (stripes along y), or a **pattern**: a background
medium with shapes on it.

* **Shapes.** Rectangles or ellipses, each with:
  * a centre in µm in the cell;
  * two sizes (sides or diameters) along its own axes, each at most one
    period;
  * a rotation;
  * a medium.

  A shape may cross the cell edge and continues in the next cell. Shapes
  must not overlap each other or their own periodic copies; a raster test
  checks this, and touching (a checkerboard) is allowed.
* **Orders.** (m, q), m = −Mx … Mx, q = −My … My, with
  k_x = k_x,in + m λ/Lx and k_y = k_y,in + q λ/Ly. The orders are labelled
  physically, so the convolution matrices in exp(+jωt) are the conjugates of
  the physics' Toeplitz matrices T[(m,q),(m′,q′)] = c_{m−m′, q−q′}.
* **Fourier coefficients** of each shape are analytic: a sinc product for a
  rectangle, 2 J₁(ρ)/ρ for an ellipse, in the shape's own axes, with the phase
  of its centre.
* **Li's fast Fourier factorisation** (JOSA A 14, 2758 (1997)):
  * E_z (tangential to every wall): Laurent's rule, [ε];
  * E_x: the inverse rule along each line y = const, then Laurent's rule in
    y, Exx = ⌈⌊ε⌋_x⌉_y;
  * E_y: the same with x and y exchanged.

  The inner inverse rule uses the line cross-sections between breakpoints.
  For axis-aligned rectangles these are exact. A curved or rotated boundary is
  a staircase of 64 steps per shape in that rule only.
* **Algebra.** The gap, the half-spaces and uniform layers are 2 × 2 blocks
  of diagonal matrices, which cost O(N). Patterned layers are dense. Only the
  response to the incident wave is assembled: the reference and substrate
  sides are joined by two LU solves instead of full star products.
* **Outputs.**
  * Per propagating order: the polar angle, the azimuth, R and T.
  * Zeroth orders: phases and power, and the power converted into the
    orthogonal polarisation.
  * The convergence estimate (both harmonics at 0.6 ×).
  * Sweeps of chosen (m, q).
* **Reduction.** A structure invariant in y reduces exactly to the 1D
  solver: the q decouple, Exx = I ⊗ ⌊ε⌋_x and Eyy = [ε]_x ⊗ I.
* **Cost.**
  * The work grows as N³ with N = (2Mx + 1)(2My + 1). The limit is 961
    orders.
  * One run on one core: N = 441 about 3 s, N = 625 about 9 s.
  * Requests are validated before any run goes to the pool.
* **Limits.**
  * Rectangular cells only (a hexagonal lattice needs its rectangular
    supercell).
  * Isotropic media.
  * Touching corners (a checkerboard) and curved boundaries converge
    algebraically in the harmonics. Square holes converge faster than round
    ones because Li's rule is exact for them.

### Interferometric testing (`analysis/interferometry.py`)

**The interferometer.**
* The test arm is the system as traced. Examples: a mirror at its centre of
  curvature (the source and the return focus at the object and image
  points), or a lens's transmitted wavefront in a Mach–Zehnder.
* Double pass is a perfect return mirror at the focus, e.g. a lens in a
  Twyman–Green with a return sphere. It doubles the wavefront error.
* The reference arm is a perfect sphere centred on the image point (the
  wavefront map's reference sphere), tilted by t_x, t_y fringes across the
  pupil diameter.

**The interferogram** on the normalised pupil:
φ = 2π(passes·W + t_x x/2 + t_y y/2) and I = (1 + V cos φ)/2, with V the
visibility.

**Phase shifting.**
* N = 3…8 frames with the reference shifted by 2πk/N.
* φ = atan2(−Σ I_k sin δ_k, Σ I_k cos δ_k), which is exact for equal steps.
* The phase is unwrapped by a breadth-first flood fill from the pupil centre.
  Pixels not connected to the centre stay empty.
* The carrier is removed and the result divided by the passes, then compared
  with W after removing piston.

**Sampling.** The largest phase step between neighbouring pixels is
reported. Above 0.9π the fringes are undersampled and the view says so.
Unwrapping needs less than π.

**Wavefront sign.** The map shows the wavefront error, which has the
opposite sign to the optical path excess of the rays.

### Spectrometer analysis (`analysis/spectrometer.py`)

The system is traced at a sweep of wavelengths (3–201), not only at its own
list. Copies of the system carry up to 23 sweep wavelengths beside the
primary. For each wavelength a hexapolar bundle from the chosen field point
(the slit point) goes to the image surface.

* **Calibration.** The bundle's centroid. The dispersion direction u is that
  of the centroid track; the position along it is s(λ).
* **Dispersion.** The linear dispersion D = ds/dλ, by second-order
  differences (also at the ends), and the reciprocal dispersion 1/D.
* **Geometric resolution.** Δλ = 2.355 σ/|D|, with σ the rms spot width along
  u (a Gaussian-equivalent FWHM), and the resolving power λ/Δλ. Below 1 nm of
  spot width the resolution is diffraction-limited and is not given.
* **Grating.** The first linear grating (a diffractive surface with lines)
  gives the Rayleigh resolving power R = |m|·G·w, with w the extent of the
  traced rays on it across its lines.
* **Not applicable.** A system whose image does not move with wavelength
  raises NotApplicable.

### Physical-optics propagation (`wave/pop.py`)

A complex scalar field U (|U|² = power per area, source power 1) goes
through the system:

1. **Source → surface 1** (finite object): the field on the object surface
   is propagated to a plane in front of the whole first surface. The field
   is a Gaussian, the LP01 mode of a fibre, a top-hat, or an imported
   rotationally symmetric field U(r). An imported field (e.g. from the
   axial FDTD) is given on a plane a set distance after the object surface.
   The propagation uses:
   * beyond 20 Rayleigh ranges by the exact asymptotic Rayleigh–Sommerfeld
     far field, U = −i k z/(2π r²) e^{ikr} A(k x/r, k y/r), valid at any NA;
   * within 2 z_R by the exact angular spectrum;
   * in between by the Fresnel transform, with the phase error
     k z (2θ)⁴/8 reported.

   An object at infinity takes a Gaussian or top-hat beam at surface 1
   analytically. The source `pupil` is the top-hat that fills the entrance
   pupil (radius r_EP, the beam an imaging lens sees; the default for an
   object at infinity). The steep spherical phase is handled analytically about
   its centre. Only the slow rest is differentiated and unwrapped, so it
   does not alias.
2. **Through the lenses:** each sample of the entry field starts a ray along
   the local phase gradient. The exact ray trace gives the optical path, the
   Fresnel or coating transmission and the clipping at the clear apertures.
   Amplitudes follow from flux conservation across the ray tubes
   (|U_P|² dA_P = T |U_e|² dA_e, Jacobian of the ray map); the phase is
   k₀ (entry phase / k₀ + OPL). The ray grid is refined (up to 768² rays)
   when the aberration phase changes by more than π/2 between rays.
3. **Exit plane → target** (the image surface + an offset):
   * The exact angular spectrum of the full field (matrix DFT onto any
     output window). The exit field is sampled at 0.45 λ/sin θ at the
     99.99 % power radius, up to 1024² samples; the reference sphere is
     analytic and the residual interpolated.
   * Only where that sampling is not possible, the Debye integral about the
     fitted reference sphere, for a strongly converging beam (Fresnel
     number w²/(λR) > 10, target within R/2 of the focus):
     U = −ik/(2π) ∫ a(s) e^{ik s·(r − C)} d²s, with a = U_res ρ²/R (a
     separable matrix DFT).
   * The Debye integral is approximate at moderate Fresnel numbers and away
     from the focus. For a strongly curved biconvex singlet (Fresnel number 13,
     target 0.7 mm behind the focus) it gives a D4σ 4.6 % smaller than the
     exact spectrum. The BPM and an independent Rayleigh–Sommerfeld
     integral confirm the exact spectrum.
4. **Results:**
   * irradiance and phase maps, power, D4σ and the power inside a radius;
   * the coupling efficiency into a Gaussian or fibre LP01 mode,
     η = |∫ U M*|² / ∫ |M|² (a fraction of the source power).

   The irradiance is band-limited to 2 sin θ/λ. The target grid is
   therefore refined to λ/(4 sin θ) (99.9 % of the ray power, up to 512²
   points), so its sums are exact. The output window, the geometric D4σ and
   the exit-beam radius weight each ray by its power: entry irradiance ×
   transmission on the regular entry grid.

* **Side view** (`side_view`): |U|² on the meridional cut along the whole
  system, in three regions:
  * object space: the source field propagated to every column (far field,
    angular spectrum or Fresnel, as for the entry plane);
  * inside the lens group: the geometric intensity of the meridional rays,
    I = I_e T / ((y/y₀) ∂y/∂y₀), i.e. flux conservation of a rotationally
    symmetric beam, the same ray transfer as above;
  * image space: the exit field by one angular spectrum (prepared once) or,
    near the focus of a strongly converging beam, by the Debye integral;
    geometric elsewhere.

  Narrow beams are evaluated on a fine local grid and averaged over the
  display rows. The regions and their methods are part of the result.

Assumptions: scalar; axial refracting systems (no mirrors, tilts or
decentres); geometric transfer inside the lens group, so diffraction inside
the glass and at internal aperture edges is not modelled, only the
truncation of the field. Near a beam waist the BPM (below) is the accurate
choice.
The non-paraxial far field is wider than the paraxial w(z) by about θ²/2
(0.45 % at θ = 0.095 rad); this is physics, not error.

* **Gaussian sources with a finite object.**
  * The source is sampled at its waist (flat phase, ±3.5 w₀) and propagated
    over |D − z_w| to the entry plane. z_R = π w₀²/λₙ, and the regime
    follows from |D − z_w|.
  * A waist beyond the entry plane gives the converging beam as the complex
    conjugate of the waist field propagated over z_w − D.
  * Any sampled source field whose phase changes by more than π/2 between
    samples gets a note.
  * The BPM starts from this entry field.
  * The source plane's second-moment radius used to be taken for the waist:
    +70 % for a waist 20 mm before the object.

### Beam propagation through the lenses (`wave/bpm.py`)

POP carries the field through the lens group along rays. That is exact only
when diffraction inside the glass is negligible. With a lens within a few
Rayleigh ranges of a waist (a fibre close to a microlens, a plate in the
focus) the beam diffracts inside the glass and the ray transfer fails: a
5 mm plate 0.5 mm after a 20 µm waist gets a width 36 % too small. The BPM
propagates the wave inside the glass instead.

* **Model.** The lenses are an index distribution n(r, z) built from the
  surface sags: glass between the faces within the element radius, the
  surrounding medium outside. The scalar wave equation for a rotationally
  symmetric field is integrated one way in z.
* **Exact homogeneous propagation.**
  * In a homogeneous medium the field moves by exp(i k_z Δz), with
    k_z = √(k₀²n² − k_r²) (non-paraxial).
  * The step uses the quasi-discrete Hankel transform of order 0
    (Guizar-Sicairos & Gutiérrez-Vega, JOSA A 21, 53, 2004) on its
    Bessel-zero radial grid.
  * The power Σ |u_i|² w_i, with the transform's weights
    w_i = 4πR²/(S² J₁(j_i)²), is conserved exactly.
  * Where the medium is uniform across the beam (inside a lens, in the gaps,
    in image space), one step covers the whole section.
* **Face zones.** Where a face passes through the beam, the march takes
  steps of about one wavelength, in the manner of phase shift plus
  interpolation (Gazdag & Sguazzero, Geophysics 49, 124, 1984):
  * the field is split by a smooth partition of unity (nine grid cells
    wide) into the parts lying in each medium during the step;
  * each part is diffracted exactly in its own medium,
    exp(i (k_z − k₀n) h), and the parts are summed in the spectrum;
  * the optical path of the step, k₀ n̄ h with n̄ averaged over the step at
    each radius, is a phase screen half before and half after, so the path
    through a curved face is exact.

  Each side of a face thus keeps its own k_z, and steep waves refract as by
  Snell's law at the tilted face. A single reference index would misstate
  k_z by k_r²/(2k₀) (1/n − 1/n_ref) per unit length. At the exit of a
  strongly curved singlet that is a 0.4 rad rms phase error, against 0.01 rad here.

  Sharp partition edges scatter light, which modulates the on-axis
  irradiance by up to 13 %; the smooth partition keeps it below 2 %.
* **Entry and transmission.** The field starts at the entry plane of the
  POP propagation (its far field, angular spectrum or Fresnel transform of
  the source). Fresnel or coating transmission at normal incidence is
  applied once per radius where a face is crossed. A one-way method has no
  reflected wave.
* **Grid.**
  * The radius holds the ray footprint and the diffraction spread of the
    entry beam over the path, 2.5 λ₀L/(πw).
  * The spectral limit π N/R is 2.5 times the steepest wave: 99.9 % of the
    ray power, or three times the diffraction angle λ₀/(πw).
  * At least 12 points lie across the entry beam.
  * A quadratic absorbing taper beyond the beam takes light scattered out of
    it in the face zones.
* **Results.** The structure is the same as POP's.
  * D4σ and power are evaluated in an analysis window like POP's: the ray
    footprint (99.9 %) plus 2λ/sin θ. The window is at least 1.5 times the
    radius holding 99 % of the computed power.
  * Power outside the window is reported.
  * Coupling is a radial overlap.
  * The side view shows the wave inside the glass.
* **Cost guard.** A face-zone step costs about 2N² multiply-adds. Above
  2.5·10¹⁰ (about 30 s), or 20 000 steps, the BPM refuses and recommends
  POP. Wide beams over strongly curved faces (such as the 1:1 relay of the
  beam tests) are exactly where the ray transfer is accurate.

Assumptions:
* scalar;
* rotationally symmetric: an axial refracting system, an on-axis source and
  rotationally symmetric surfaces;
* mirrors, ideal lenses and diffractive surfaces are refused;
* one way (no reflections or ghosts);
* normal-incidence surface transmission.

Accuracy (`tests/test_bpm.py`):
* Gaussian beam through a plate or a singlet within the Rayleigh range:
  width within 2·10⁻⁴ of the ABCD law, power T² to 10⁻⁴.
* Strongly curved lenses, where POP is valid: D4σ within 0.7 % of POP,
  power on the detector within 0.1 %, exit phase within 0.03 rad rms.

### Rotationally symmetric 3D FDTD (`wave/fdtd_bor.py`)

A body of revolution about z with x-polarised light needs only the azimuthal
harmonic m = 1 (Taflove & Hagness ch. 12):

    E_r = e_r cos φ,  E_φ = e_φ sin φ,  E_z = e_z cos φ
    H_r = h_r sin φ,  H_φ = h_φ cos φ,  H_z = h_z sin φ

Maxwell's curl equations then become six coupled equations on the (r, z)
half plane. This is the exact 3D field of the structure: a fibre is a
cylinder, not a slab.

* **Grid.** Yee in (r, z), Courant 0.4. On the axis e_z = 0 and
  ∂h_z/∂r = 2 h_z(dr/2)/dr (h_z is odd across the axis for m = 1).
* **Boundaries.** CPML at the z ends and the outer radius.
* **Sources.** A soft x-polarised current sheet,
  J_r = J cos φ, J_φ = −J sin φ, with the profile of a 3D Gaussian beam or
  of the LP01 mode of a step-index fibre (fibermodes.py). Sources must be
  on the axis and untilted.
* **Shapes** as in 2D, with y read as the radius |y|. size_y is the domain
  diameter, so a set-up keeps its picture when switched between 2D and 3D.
* **Results** as in 2D:
  * azimuthally averaged |E|² maps, mirrored to −r for display;
  * the flux P = (π/2) ∫ Re(e_r h_φ* − e_φ h_r*) r dr;
  * R, T and A from a reference run.

**Hand-over to POP.** At the transmission monitor
E_x = (e_r − e_φ)/2 + (e_r + e_φ)/2 cos 2φ.
* The rotationally symmetric co-polarised part (e_r − e_φ)/2 is exported,
  normalised to the transmitted co-polarised power T (1 − f_x).
* The depolarised fraction f_x (the cos 2φ part and E_z) is reported.
* POP takes the field as its source (`kind: "field"`) on a plane
  `plane_offset_mm` after the object surface: the monitor's z minus the
  FDTD z of the object surface, e.g. the fibre facet.
* The wavelength and the medium index must match the optical system's
  object space, or POP refuses.

The facet reflectance, the near field (FDTD) and lenses millimetres away
(POP or BPM) thus form one chain, without a 3D grid of the whole system.

### 2D FDTD Maxwell solver (`wave/fdtd.py`)

The structure is invariant along x and computed in the (z, y) plane, in µm
with c = ε₀ = μ₀ = 1. s (TE: Ex, Hy, Hz) and p (TM: Hx, Ey, Ez)
polarisation on a Yee grid with leapfrog time stepping (second order,
Courant 0.5).

* **Boundaries.** Convolutional PML (Roden & Gedney: m = 3,
  σ_max = 0.8(m+1)/dx, α for evanescent tails) at the z ends and, unless y
  is periodic, at the y ends.
* **Materials** at the source wavelength: ε = (n + ik)².
  * Re ε ≥ 1: a dielectric with the conductivity σ = ω Im ε = 2nkω.
  * Re ε < 1 (metals, and the boundary cells of metal shapes): ε∞ = 1 plus a
    Drude polarisation current, dJ/dt + γJ = ω_p²E, with
    dE/dt = ∇ × H − J. J lives at half steps and is updated as
    (J⁺ − J⁻)/Δt + γ(J⁺ + J⁻)/2 = ω_p²Eⁿ.
  * In the discrete steady state at ω this medium has
    ε = 1 − ω_p²/(W² + iWγ cos(ωΔt/2)) with W = 2 sin(ωΔt/2)/Δt. ω_p and γ
    are solved per cell so that this equals the target exactly. The time
    stepping therefore adds no dispersion error to the metal.
  * The run is monochromatic, so a Drude–Lorentz model of a material enters
    only through its ε at the wavelength.
* **Shapes.** Rectangles, circles and polygons; later shapes cover earlier
  ones. Each cell's 4 × 4 sub-cells are painted in order and averaged:
  * Ex (tangential to every wall): arithmetic mean of the complex ε;
  * Ey: harmonic mean along y and arithmetic across;
  * Ez: harmonic mean along z and arithmetic across.

  This is exact for layers normal to either axis, where the normal
  component's D is continuous. It matters at metal surfaces, where ε changes
  sign. A plain arithmetic mean put a gold–air plasmon's n_eff 3.7 % off; the
  directional mean is within 1.3 × 10⁻⁴.
* **Sources.** A soft current sheet (Jx; a magnetic sheet Mx for p),
  switched on over three periods, with one of these profiles:
  * a plane wave (periodic y);
  * a 2D Gaussian beam (waist, focus, tilt);
  * the fundamental guided mode of a symmetric slab waveguide, from
    Maxwell's equations (TE: u tan u = w; TM: u tan u = (n₁/n₂)² w; cos in the
    core, exponential outside);
  * a surface plasmon (p) on the interface y = y₀. The metal below and the
    dielectric above are read from the structure at the source.
    β = k₀√(ε_mε_d/(ε_m + ε_d)) and κ = √(β² − k₀²ε) on each side. The sheet
    carries the plasmon's E_y ∝ H_x/ε(y), which changes sign across the
    interface, because a magnetic sheet launches the transverse E it
    carries.
* **Propagation constant** of the guided sources:
  * a least-squares fit of log(field) along the guide's axis line (a
    plasmon: 0.2/κ_d above the interface);
  * from two wavelengths past the source to the transmission monitor, or to
    where the cross-section first changes;
  * gives β = (n_eff + iκ)k₀ and the propagation length 1/(2 Im β). For a
    plasmon the analytic value is listed beside it.
* **Reference structure.** The reference run can have its own structure,
  e.g. the endless fibre for a fibre-end preset. R is then the power
  reflected back into the fibre.
* **Results.** The run continues for the domain transit time; DFTs are then
  taken over the last six periods, and the two halves of that window are
  compared as a steady-state check. The Poynting flux
  S_z = ½ Re(E × H*)_z goes through the monitor lines. A reference run
  without the structure gives R (incident field subtracted), T and
  A = 1 − R − T.

Accuracy:
* About 1 % in R at 30 points per wavelength in the densest medium (|n + ik|
  for metals). The error depends on where an interface lies within a cell
  and converges with resolution.
* Metals need cells small against the skin depth λ/(4πk); at 30 points per
  wavelength there are about 2.4 cells per skin depth.
  * A metal half-space reflects within 3 × 10⁻⁴ of Fresnel.
  * A film only two skin depths thick (30 nm of gold) is within 1.6 × 10⁻²
    at 30 and 1.2 × 10⁻³ at 70 points per wavelength.
* Guided modes carry the Yee grid's phase error, second order in the cell:
  n_eff + 2.5 × 10⁻³ for a glass slab at 30 points per wavelength.

Limits: 2D only, single frequency, no Bloch-periodic oblique plane waves (use
a tilted Gaussian beam). The rotationally symmetric solver keeps dielectrics
only.

## 8i. First-lens starting prescriptions (`design.py`)

The guided *First lens* (start screen) asks for the focal length f, the F/#
N, the half field angle and the wavelengths, and builds:

* **Singlet**: Coddington's best-form bending for an object at infinity,
  q = (c₁ + c₂)/(c₁ − c₂) = 2(n² − 1)/(n + 2) at the primary wavelength,
  with c₁ − c₂ = φ/(n − 1) (thin lens). This minimises third-order spherical
  aberration.
* **Cemented doublet**: the thin-lens achromat φ₁ = φV₁/(V₁ − V₂),
  φ₂ = −φV₂/(V₁ − V₂) with V = (n_p − 1)/(n_s − n_l) at the primary, shortest
  and longest wavelengths; equiconvex crown, the flint shares the cemented
  radius. The crown must have the higher V.

**Thickening.** EPD = f/N, stop on the first surface, clear semi-diameter
h = 1.05·EPD/2. Centre thicknesses give an edge of at least
max(1 mm, 0.04·2h) (and a centre of at least max(1 mm, 0.03·2h)). All
curvatures are then scaled by one factor until the exact paraxial EFL equals
f (secant iteration on 1/EFL, alternating with the thickness update until
the thicknesses no longer change). The image surface is placed at the
paraxial back focus; fields are 0, 0.7 and 1 times the half field.

**Merit function.** The project also gets variables (all lens curvatures
within ±10/f, the image distance within 0.5–1.5 × BFD) and operands (RMS
spot, EFL = f, minimum edge thickness, and axial colour for a doublet whose
wavelengths span F to C), so it can be optimised at once. These are
starting points, not optimised designs.

## 8p. Design space map (`designspace.py`, `workers.py`)

A specification is mapped by many optimised designs over several lens
topologies, and the Pareto front of the ones that meet it is marked. The map
is a seeded multistart: over topologies, glass pairs and perturbed starts.
Every number on it comes from the normal optimiser and analyses.

**Specification.**
* Focal length f, F/# N (EPD = f/N, image-space F/# of an object at
  infinity) and the half field (fields 0, 0.7 and 1 times it, angles).
* Wavelengths and primary (the UI takes the design's).
* Optionally a maximum length: the paraxial total track, first surface to
  image.
* The topologies, the number of candidates, the glass pool (the built-in
  glasses unless names are given), the MTF frequency, whether to compute the
  tolerance sensitivity, and the seed.

**Topologies and their starts.** Everything is scaled to f.

| Topology | Start | Elements |
|---|---|---|
| Singlet | Coddington best form (§8i) | 1 |
| Cemented doublet | thin-lens achromat, equiconvex crown in front (§8i) | 2 |
| Air-spaced doublet | the same, cemented interface opened by max(a_min, 0.005 f) | 2 |
| Cooke triplet | the Geiser triplet (samples.py) normalised to f = 1 | 3 |
| Petzval | Kidger's Petzval with field flattener (samples.py) | 5 |
| Double Gauss | US 2,784,643 (samples.py) | 6 |

* In the published prescriptions every crown is replaced by the
  candidate's crown and every flint by its flint.
* Variant v > 0 of a glass choice multiplies the curvatures by 1 + 0.2u and
  the air gaps by 1 + 0.3u, with u uniform in [−1, 1] from the candidate's
  seed (run seed, topology, candidate number).
* Then, in up to eight rounds:
  1. one common curvature factor makes the paraxial EFL exactly f (secant);
  2. the image moves to the paraxial back focus;
  3. glass centre thicknesses grow until every edge, at the full-field
     clear aperture (automatic semi-diameters), is at least e_min and every
     centre at least t_min;
  4. air gaps next to a lens grow until the edge clearance is a_min.
* Limits: e_min = t_min = max(0.3 mm, 0.04 EPD, 0.01 f) and
  a_min = max(0.05 mm, 0.002 f).

**Glass pairs.**
* Abbe numbers are taken at the specification's wavelengths:
  V = (n_p − 1)/(n_short − n_long). With one wavelength the catalogue Vd is
  used.
* A pair (crown a, flint b) qualifies when V_b ≤ 0.8 V_a.
* Pairs are drawn without replacement with probability ∝ 1/s², where
  s = (V_a + V_b)/(V_a − V_b) = (|φ₁| + |φ₂|)/φ of the thin achromat. Pairs
  with weaker element powers therefore come first.
* A singlet takes the glasses of the pool in a seeded random order.
* A glass whose dispersion data do not cover the wavelengths is left out.
  An unknown name is an error.

**Plan.** The topologies share the candidates evenly. Each topology cycles
through its glass choices, then repeats them as perturbed variants. The plan
is a pure function of the specification, so a seed reproduces the map.

**Optimisation of one candidate.** This is the normal optimiser (§10),
`local` (trust-region least squares).
* Variables:
  * every lens surface's curvature, within ±max(10/f, 2|c₀|);
  * every glass thickness, within [t_min, max(3t₀, t₀ + 0.1f)];
  * every air gap, within [0, max(3t₀, 0.3f)];
  * the image distance.
* Operands:
  * RMS spot (4 rings, every field and wavelength);
  * EFL = f;
  * minimum edge thickness e_min of every glass, and a_min of every air
    gap;
  * the maximum length, when given.
* Evaluation budget: singlet 300, cemented doublet 500, air-spaced doublet
  700, triplet 1500, Petzval 2000, double Gauss 2500. Most runs end at the
  budget, still improving slowly. The map shows what a fixed effort
  reaches, not converged optima. The stored optimisation set-up lets the
  user continue an opened design.

**Metrics.** Each metric comes from the normal analysis at the UI's
defaults, so an opened design shows the same numbers:
* RMS spot radius per field: spot diagram, hexapolar density 6, centroid
  reference. The map uses the field mean and the worst field.
* Diffraction MTF at the chosen frequency: 64 × 64 pupil, padding 4,
  (T + S)/2 per field, and their mean.
* Length: the paraxial total track.
* Mass: elements.py, from catalogue densities.
* Glass cost: Σ mass × catalogue relative cost, only when every glass has
  one. The built-in glasses have none; AGF catalogues have them.
* Distortion at the full field: primary wavelength, the *Field curvature
  and distortion* analysis.
* Tolerance sensitivity: the RSS of the worst changes of the RMS spot (µm)
  under the default precision tolerances, with the back-focus compensator
  (tolerance.py, Monte Carlo off). This is the RSS change of the Tolerance
  view with the default precision set.
* An analysis that cannot be computed (a failing chief ray) gives no
  value.

**Feasibility.** A design meets the specification when:
* |EFL − f| ≤ 1 %;
* the length is within the maximum (10⁻³);
* every glass edge is at least 0.9 e_min;
* no air edge is negative (lenses do not collide);
* every ray of the spot diagram reaches the image.

Designs that miss it never count for the front; the view hides them unless asked (then hollow).

**Pareto front.** This is the exact non-dominated set of the feasible
designs over the chosen objectives. A design is dominated when another is at
least as good in every objective and better in one. MTF counts larger as
better, every other metric smaller. Designs with equal values are all kept.
Designs without a value of an objective are left out. The default
objectives are the RMS spot, the length and the cost: the glass cost when
every feasible design has one, else the glass mass. The view can instead
use the two shown axes. The engine computes the front for whatever
objectives the view asks for.

**Process pool.** The tracer is NumPy code that holds the GIL much of the
time, so candidates run in separate processes:
* `concurrent.futures.ProcessPoolExecutor` with the spawn start method;
* `OPTICORE_WORKERS` workers, by default the number of CPUs minus one;
* the pool starts with the first job and shuts down after 5 minutes idle.

Cancel uses a byte per job in a shared array that the workers inherit at
start-up. The optimiser and the tolerance analysis read it at every
evaluation, so a running candidate stops within one merit evaluation. Queued
candidates are dropped. Finished candidates are kept in plan order and
survive a cancel. The pool is meant to be shared by other CPU-heavy jobs
(the advisor's moves).

**Field-batched tracing.** The merit function's RMS spot and the automatic
semi-diameters (used by the edge-thickness operands) trace the rays of all
fields of a wavelength in one call (`raytrace.trace_fields`), instead of one
call per field. Every ray is traced on its own, so the results are identical
to the last bit (tested on every sample). The per-surface work is done once
instead of once per field. A merit evaluation of the triplet candidate went
from 36 to 15 ms, which speeds every optimisation and tolerance run.

## 8q. Systems from stock lenses (`stock.py`, `stockdesign.py`)

A stock lens is a purchasable singlet or cemented doublet with a fixed
prescription: radii (front to back, flat as null), centre thicknesses,
glasses, mechanical diameter and clear aperture (default 90 % of the
diameter), and the price when the source gives one. In a design it becomes
surfaces with **fixed** clear semi-diameters, so rays outside the clear
aperture are clipped. The mechanical semi-diameter is kept, and the part is
named in the labels and comments.

**Paraxial data.** These use reduced 2 × 2 matrices on (y, n u) from the
front vertex to the back vertex in air: refraction [[1, 0], [−(n′ − n)/R, 1]]
and transfer [[1, t/n], [0, 1]]. From M = [[A, B], [C, D]]:
* EFL = −1/C;
* back focal distance −A/C from the back vertex, front focal distance D/C
  from the front vertex;
* rear principal plane (1 − A)/C from the back vertex, front principal plane
  (D − 1)/C from the front vertex.

A reversed lens has its radii in reverse order with opposite signs. Its EFL
is unchanged and its principal planes are swapped.

**Generic library** (`materials/data/stock_generic.json`, 740 lenses, written
by `python -m opticore.tools.make_stock_library`). These are OptiCore's own
designs at standard focal lengths (±10 … 1000 mm) and diameters (6, 12.7,
25.4 and 50.8 mm). They are not any vendor's parts and have no prices.
* Forms by glass:
  * N-BK7: plano-convex, equi-bi-convex, best form (Coddington, object at
    infinity), positive meniscus (shape factor 2), plano-concave and
    equi-bi-concave;
  * UV fused silica: plano and bi-convex, plano and bi-concave;
  * N-SF11 and CaF2: plano-convex and plano-concave.
* Rules:
  * D ≤ |f| ≤ 40 D, and no surface steeper than |R| = 0.55 D;
  * positive singlets have an edge of max(1 mm, 0.07 D) at the rim;
    negative ones a centre of max(1.5 mm, 0.12 D);
  * each radius is solved so that the thick-lens EFL equals the nominal
    focal length (secant).
* Achromats (crown in front: N-BAF10/N-SF6, N-BK7/SF2, N-SK16/N-SF5;
  12.7 to 50.8 mm; f ≥ 20 mm and ≥ 1.2 D):
  * optimised by the normal optimiser for an object at infinity at F, d
    and C, fields 0 and 1°, aperture min(0.9 D, f/3): RMS spot, with the
    crown's edge as a penalty;
  * the last curvature is an F/# solve (f / aperture), so every trial design
    has the focal length exactly. The two front curvatures and the image
    distance are optimised until the solver converges: 17 to 102
    evaluations over the 126 runs. The limit is 3000, and a lens that does
    not converge is left out;
  * before ADR-044 the focal length was a weighted goal, and the runs ended
    on their 600-evaluation budget in a long, curved valley. The design
    then depended on details of the finite differences (the pool, the step),
    by up to 64 mm in a radius of the 500 mm N-BK7/SF2 achromat. The stored
    lenses were up to 1.8 % above their optimum on the generator's merit;
  * the flint's centre thickness is max(1.5 mm, 0.1 D) and the crown's
    edge max(1 mm, 0.05 D);
  * one common radius scale then removes the solve's last rounding of the
    focal length.

**Import.** Vendor ZMX files hold one lens each: the first run of glass
surfaces is taken.
* The mechanical diameter comes from MEMA and the clear aperture from DIAM.
* The part number comes from the file name (vendor suffixes such as
  "-Zemax(ZMX)" are removed).
* Aspheres and other surface types are refused.
* Glasses not built in are looked up in the user's glass catalogues and
  copied with the lens.

There is also a CSV format (FILE_FORMATS.md). Catalogues are kept in the
browser, and OptiCore ships no vendor data (ADR-015, ADR-037).

**Build.** This places ordered combinations of 1–3 stock lenses for a
specification:
* an object at infinity (EFL f, F/#, half field), or at the distance s
  (magnification m, object NA, object height);
* the wavelengths, the maximum length, the minimum air gap and the target
  tolerance (1 % by default);
* the allowed glasses and catalogues.

Each lens may be either way round (a symmetric lens is used once), and a
part may be used twice. The steps:
1. **First order**, vectorised over every combination. With the lens
   matrices L and air gaps T(d) = [[1, d], [0, 1]], the system matrix is
   M = L_n T(d_{n−1}) … T(d_1) L_1.
   * At infinity C(M) = −1/f is linear in the last gap, which is solved. The
     image lies −A/C behind the last vertex.
   * At a finite distance, with N = M T(s), the image lies −B(N)/D(N) behind
     the last vertex and m = 1/D(N), again linear in the last gap.
   * One lens must match the target within the tolerance.
   * For three lenses the first gap takes 6 log-spaced values up to
     min(max length, 2 × the scale). The triples are a seeded sample of
     200 000 when there are more.
   * Kept are combinations whose:
     * gaps are at least the minimum at the vertices and at the smaller
       lens's rim (sags at its mechanical radius);
     * image distance is at least max(minimum gap, 1 mm);
     * length fits;
     * paraxial marginal plus chief ray heights fit every lens's clear
       aperture (98 %). The stop is at the first lens.
2. **Third-order ranking.** Seidel sums S_I…S_V, C_L and C_T are computed
   per combination, vectorised, with the formulas of
   `paraxial.seidel_coefficients` (equal to it to 10⁻⁹ in the tests). The
   ranking score estimates the RMS wavefront over the fields 0, 0.7 and 1
   with one common refocus:
   * the balanced Zernike RMS of spherical W040/(6√5), coma W131 H/(6√2),
     astigmatism W222 H²/(2√6) and the residual field curvature /(2√3);
   * the spread of the axial and lateral colour over the wavelengths.

   It only chooses which combinations get a real-ray check and is never
   reported.
3. **Real-ray prescreen** on the process pool: the polychromatic RMS spot at
   the best common focus (`analysis/focus.py`, hexapolar density 3). The best
   1500 by the third-order score are checked, shared by the lens counts.
4. **Optimisation** on the process pool of the best `candidates` (40 by
   default, shared by the lens counts):
   * variables: the air gaps and the image distance;
   * operands: RMS spot (4 rings), the EFL or magnification target, rim
     clearance and the maximum length;
   * then the normal metrics (§8p), the number of parts, the summed price
     (when every part has one) and, at a finite distance, the
     magnification.
   * A design meets the specification when the target is within the
     tolerance, the length fits, no lenses collide and every ray passes.

**Match.** This replaces the lens elements of an existing design with stock
lenses.
* **Elements** are the design's singlets and cemented groups in air, with
  spherical surfaces.
* **Candidates.** Each element gets its `per_element` (4) nearest stock
  lenses, both ways round: the same number of glasses, a clear aperture at
  least the element's, and the smallest score
  |φ_stock f − 1| + 0.25 |c₁ − c₁,element| |f| + 0.5 |n̄_stock − n̄| +
  0.05 max(0, oversize).
* **Placement.** Each stock lens sits with its principal-plane midpoint
  where the element's was, which keeps the first order as far as one lens
  allows. Gaps below the minimum are raised to it.
* **Prescreen.** The combinations are ranked by the merit at this placement.
* **Optimisation.** The best ones are optimised in the air gaps around the
  stock lenses and the image distance, with the project's merit function.
  Operands on replaced surfaces are dropped. Without operands, the merit is
  the RMS spot and the original EFL.

**Results.** Candidates appear in the Design space map, with the same jobs,
pool, cancel, Pareto front and opening as a design space run (§8p). The default front is RMS spot,
length and price, or the number of parts when the price is unknown.

## 9. Materials

| Model | Formula (λ in µm) |
|---|---|
| sellmeier | n² − 1 = Σ Bᵢ λ²/(λ² − Cᵢ), with Cᵢ in µm² |
| sellmeier_sq | n² − 1 = Σ Bᵢ λ²/(λ² − Cᵢ²), with Cᵢ in µm |
| schott | n² = A0 + A1λ² + A2λ⁻² + A3λ⁻⁴ + A4λ⁻⁶ + A5λ⁻⁸ |
| cauchy | n = A + B/λ² + C/λ⁴ |
| polynomial | n² = A + Σ cᵢ λ^eᵢ, coefficients A, c₁, e₁, c₂, e₂, … (refractiveindex.info formula 3) |
| constant | n |
| tabulated | Monotone cubic (PCHIP) through measured (λ, n) |
| extended | n² = A0 + A1λ² + A2λ⁻² + A3λ⁻⁴ + A4λ⁻⁶ + A5λ⁻⁸ + A6λ⁻¹⁰ + A7λ⁻¹² |
| extended2 | n² = A0 + A1λ² + A2λ⁻² + A3λ⁻⁴ + A4λ⁻⁶ + A5λ⁻⁸ + A6λ⁴ + A7λ⁶ |
| extended3 | n² = A0 + A1λ² + A2λ⁴ + A3λ⁻² + A4λ⁻⁴ + A5λ⁻⁶ + A6λ⁻⁸ + A7λ⁻¹⁰ + A8λ⁻¹² |
| herzberger | n = A + B L + C L² + D λ² + E λ⁴ + F λ⁶, L = 1/(λ² − 0.028) |
| sellmeier2 | n² − 1 = A + B1 λ²/(λ² − λ1²) + B2/(λ² − λ2²) |
| sellmeier4 | n² = A + B λ²/(λ² − C) + D λ²/(λ² − E) |
| conrady | n = n0 + A/λ + B/λ^3.5 |
| handbook1 | n² = A + B/(λ² − C) − D λ² |
| handbook2 | n² = A + B λ²/(λ² − C) − D λ² |

* `Vd = (nd − 1)/(nF − nC)` with d = 587.5618 nm, F = 486.1327 nm,
  C = 656.2725 nm.
* The Schott absolute dn/dT model (D0, D1, D2, E0, E1, λtk) and the
  thermal expansion coefficient are used by the environment model (§9a).
* Wavelengths outside a material's data range produce a
  `WAVELENGTH_EXTRAPOLATED` warning.

**Built-in polymers.** Polymer grades differ by a few 10⁻³ in nd and by up
to about 2 in Vd, so for a specific grade the maker's data belong in a
custom material. The built-in ones are generic, from the refractiveindex.info
database (CC0):

| Material | Data | nd | Vd |
|---|---|---|---|
| PMMA | Beadie et al., Appl. Opt. 54, F139 (2015): formula n² = A + Σ cλᵉ, 0.42–1.62 µm, 20.1 °C, accuracy < 2·10⁻⁴ | 1.49253 | 59.4 |
| POLYCARBONATE | Sultanova et al., Acta Phys. Pol. A 116, 585 (2009), 20 °C: one-term Sellmeier fit of their data by M. Polyanskiy, 0.4368–1.052 µm | 1.58476 | 27.9 |
| POLYSTYRENE | as polycarbonate | 1.59163 | 29.5 |

* PMMA used to be the one-term Sultanova fit too. Its Vd of 53.2 lay 4.8
  below an independent measurement (Szczurowski 2013, 3-term Sellmeier,
  23 °C: nd 1.49060, Vd 58.0) and 6.2 below Beadie's.
  * A one-term Sellmeier is not the cause. Fitted to Szczurowski's or
    Beadie's indices at nine wavelengths over 0.436–1.052 µm (residuals at
    most 2.2·10⁻⁴), it gives Vd 57.5 and 58.1, not 53.
  * Beadie agrees with Szczurowski within 2.5·10⁻³ in n over 0.42–1.08 µm
    and 1.4 in Vd.
* For polycarbonate and polystyrene the database has no other formula
  data, only the tables of Zhang et al., Appl. Opt. 59, 2337 (2020). Those
  are for other samples, and they scatter about a smooth fit by 3·10⁻⁴ (PC)
  and 10⁻⁴ (PS).
  * A smooth fit of the Zhang tables gives PC Vd about 28.1, which agrees
    with Sultanova's 27.9.
  * For PS it gives nd about 1.589 and Vd about 31.2. Sultanova gives
    nd 1.5916 and Vd 29.5.
  * The source text of each material states these numbers, so the spread is
    visible where the material is chosen.

## 9a. Temperature and pressure (`environment.py`)

The environment model is **off by default** (`OpticalSystem.environment_enabled`);
then catalogue indices are used as they are and the prescription as entered.
When it is on, the system has a temperature T, a pressure P (atm, 0 = vacuum)
and a housing expansion coefficient (default aluminium 6061, 23.6·10⁻⁶/K).
Temperature and pressure can be set per configuration (§7a).

**Indices.** Indices are relative to the system air at (T, P), and
wavelengths are wavelengths in that air (the catalogue convention). AIR has
index 1, VACUUM 1/n_air. For a glass at system wavelength λ:

1. n_air,sys = n_air(λ, T, P); vacuum wavelength λ₀ = λ·n_air,sys.
2. The catalogue index is relative to air at the glass's reference
   temperature T₀ and 1 atm: n_air,0 = n_air(λ, T₀, 1); the catalogue is read
   at λ₀/n_air,0 and n_abs(T₀) = n_cat · n_air,0.
3. Absolute Schott model (SCHOTT TIE-19):
   Δn_abs = (n² − 1)/(2n) · [D0 ΔT + D1 ΔT² + D2 ΔT³ + (E0 ΔT + E1 ΔT²)/(λ₀² − λtk²)],
   ΔT = T − T₀.
4. n_rel = (n_abs(T₀) + Δn_abs)/n_air,sys.

The air index is Edlén's 1953 dispersion formula for standard air (15 °C,
1 atm) scaled to T and P by the Kohlrausch (ideal gas) relation:
n_ref − 1 = [6432.8 + 2949810 λ²/(146 λ² − 1) + 25540 λ²/(41 λ² − 1)]·10⁻⁸,
n − 1 = (n_ref − 1)·P/(1 + 3.4785·10⁻³ (T − 15)). The air formula takes the
same wavelength argument in steps 1 and 2 (its air/vacuum distinction is far
below its accuracy), so at the reference conditions (T = T₀ = 20 °C,
P = 1 atm) the result is exactly the catalogue index (tested).

**Thermal expansion.** The prescription is the design at T_REF = 20 °C. With
s = 1 + α ΔT (ΔT = T − 20 °C):
* a refracting surface follows the glass after it, else the glass before it
  (the rear face of an element); a mirror follows its substrate
  (`Surface.mount_cte`, else the housing); surfaces between two gases (stop,
  dummies) do not change;
* a shape scales homothetically: R → sR, sag z(r) → s·z(r/s) (aspheric
  term A₂ₘ → A₂ₘ s^(1−2m), odd term βᵢ → βᵢ s^(1−i), Zernike, Q and XY
  amplitudes and their normalisation radii → s×, radial phase normalisation
  radius → s×, grating frequency → /s), fixed semi-diameters and central
  obscurations → s×. (The odd, Q and XY terms and obscurations used to keep
  their 20 °C values);
* a thickness follows the glass of its medium, else its spacer
  (`Surface.mount_cte` of the surface before the gap, else the housing; the
  gap behind a mirror always uses the housing, since a mirror's `mount_cte` is
  its substrate);
* not scaled: the object distance (outside the lens), the aperture
  specification (an EPD is a specification; F/# and NA are scale invariant),
  coordinate-break decenters and tilts, ideal-lens focal lengths.

The expansion is applied once, in `compile_system`, after the active
configuration and before solves, so solves act on the system at its
temperature; `freeze_solves` writes solved values back into the 20 °C
prescription (divided by s) so that compiling the frozen system expands it
once. Glasses without dn/dT keep their index except through the air
(`THERMAL_NO_DNDT`); glasses without a CTE keep their shape
(`THERMAL_NO_CTE`); temperatures outside −30…+70 °C, the range of the
catalogue CTEs, give `THERMAL_RANGE`.

**Data.** The built-in SCHOTT glasses carry the data-sheet D0…λtk and CTE
(−30…+70 °C) from the refractiveindex.info database (CC0). Fused silica,
CaF₂, sapphire and the polymers have none built in (their literature sources
give none in the same form); users can enter them in a project copy of the
material. Catalogue glasses get them from AGF and refractiveindex.info.

**Analysis (`analysis/thermal.py`).** Over a temperature (or pressure) range
the analysis compiles the system with the model on and reports the paraxial
EFL and BFL, the best polychromatic RMS focus relative to the image surface
(§8, focus status: closed form, exact for a plane image surface) and the RMS
spot on the image surface and at best focus; least-squares slopes per kelvin
(or atm); the focus spread; and the diffraction depth of focus ±2λN_w² at the
system's own condition for comparison. The active configuration is used
without its temperature and pressure values (the swept value wins).

**Passive athermalisation.** `mount_cte` is an optimisation variable (needs
the model on): the effective expansion of a spacer, which a two-material
spacer can realise. With merit operands in several temperature
configurations, the optimiser finds the spacer that keeps the image on the
focus (benchmark in VALIDATION).

**Mount tree.** The mechanics that carry the optics can be modelled
as a tree of parts (`OpticalSystem.mounts`, used only with the model on).
Positions are measured along the axis from the surface-1 vertex of the
20 °C prescription.

* A part has a CTE α_p, an optional temperature T_p of its own (else the
  system temperature), an optional parent and a datum z_d where it attaches
  to the parent (root parts attach to the fixed reference). A point z on
  the part moves by
  u_p(z) = α_p (T_p − 20 °C)(z − z_d) + u_parent(z_d), with u = 0 for the
  reference. Lengths are signed, so re-entrant (folded-back) parts subtract.
* A part may be linked to a CAD part. Only its axial extent is used: it
  offers the part's front and back as datum values. The CAD body itself
  does not expand.
* A surface can be seated on a part (`Surface.seat_part`): its vertex moves
  by u_p(z_nominal). The contact is idealised to the vertex; the real
  contact point (edge or chamfer) differs by the sag, which changes by
  α ΔT·sag (nm for ordinary lenses).
* Surfaces joined by glass form a block (a lens or a cemented group) that
  keeps its expanded internal thicknesses. A seated block is placed by its
  seat; with several seats in one block the first one places it
  (`MOUNT_OVERCONSTRAINED`). An unseated block follows the gap before it,
  expanded by the rules above (spacer or housing). The gap between two
  blocks is the difference of their placements; a gap that closes gives
  `MOUNT_COLLISION`.
* Surface 1 stays the origin: a seat that moves it changes the object
  distance instead (the object is fixed to the reference).
* Element temperatures: `Surface.element_temperature_c` on the surface that
  starts a glass medium sets that element's temperature, for its index
  (dn/dT) and its expansion; the gaps and the air keep the system
  temperature.
* Limits: the seats work along a straight axis; with mirrors or coordinate
  breaks they are ignored (`MOUNT_UNSUPPORTED`) and the gaps follow their
  spacers. A part is uniform in temperature and expands freely along the
  axis (no gradients, no radial expansion, no stress or bending): heat
  conduction and structural FEM are planned for later (ROADMAP).
* `POST /api/v1/system/mounts` reports each part's datum displacement and
  each seat's displacement at the system's condition (the *Mounts* tab).

### Glass catalogues (`materials/agf.py`)

Manufacturers publish their glass catalogues as AGF text files. OptiCore
reads them but ships none.

* **Records.** `NM` (name, formula, MIL code, Nd, Vd, exclude, status), `CD`
  (coefficients), `LD` (data range), `TD` (Schott dn/dT coefficients), `ED`
  (thermal expansion, density, ΔPg,F), `OD` (relative cost), `IT` (internal
  transmittance) and `GC` (comment).
* **Formula numbers.**

  | AGF | OptiCore model | AGF | OptiCore model |
  |---|---|---|---|
  | 1 | schott | 8 | handbook2 |
  | 2, 6, 11 | sellmeier (Sellmeier 1/3/5) | 9 | sellmeier4 |
  | 3 | herzberger | 10 | extended |
  | 4 | sellmeier2 | 12 | extended2 |
  | 5 | conrady | 13 | extended3 |
  | 7 | handbook1 | | |

* **Self-check.** Every glass is checked against its own catalogue data:
  |nd(coefficients) − Nd| ≤ 10⁻⁴ and the Vd difference ≤ max(0.05, 0.1 %).
  A failing glass is imported with `verified = false` and reported, because
  a mismatch means an unsupported formula variant or a damaged file.
  Unsupported formulas, missing coefficients, reserved names and duplicates
  are skipped and reported.
* **Encoding.** UTF-16 (with or without BOM), UTF-8 and 8-bit files are
  detected.
* **Data in use.** The internal transmittance feeds the bulk absorption
  when the system's catalogue absorption is on (§8c); the density gives
  element masses and the relative cost a mass-weighted cost (§8j). Status
  and the other records are shown only.
* **Thermal model.** The dn/dT coefficients and the expansion feed the
  environment model (§9a) when it is on.
* **Storage and portability.** Catalogues are parsed by the engine
  (stateless) and kept in the browser (ADR-015).
  * A project stores a copy of every catalogue glass it uses, so it
    evaluates identically without the catalogue.
  * Built-in materials take precedence over catalogue glasses of the same
    name, and earlier catalogues (name order) over later ones. Shadowed
    names are listed.

### Manufacturer catalogues from refractiveindex.info (`materials/rii.py`)

The refractiveindex.info database (Polyanskiy, *Sci. Data* 11, 94 (2024);
CC0 1.0) republishes the manufacturers' Zemax catalogue data as YAML pages
under `specs/<maker>/`. The material library's *Makers* installer downloads
the chosen makers' pages in the browser, at the database commit current at
the time (recorded with the catalogue). The engine converts them; OptiCore
ships none of these data.

| refractiveindex.info | OptiCore |
|---|---|
| formula 1: n² − 1 = c₀ + Σ B λ²/(λ² − C²) | `sellmeier_sq`; c₀ ≠ 0 becomes the term (B = c₀, C = 0) |
| formula 2: n² − 1 = c₀ + Σ B λ²/(λ² − C) | `sellmeier`; c₀ likewise |
| formula 3: n² = c₀ + Σ c λ^e | `polynomial` (all-zero terms dropped) |
| tabulated n, nk | `tabulated` (n column) |
| tabulated k, nk | internal transmittance τ = exp(−4πk d/λ), unrounded, for d = 10 mm (or d = 1/α where 10 mm would underflow), so α = 4πk/λ is kept exactly |
| thermal_dispersion formula A | Schott dn/dT (D0, D1, D2, E0, E1, λtk), T0 = CONDITIONS temperature − 273.15 |
| nd, Vd, glass_status, glass_code, density, dPgF, expansion −30…+70 °C | `nd_ref`, `vd_ref`, `status`, `comment`, `density` (g/cm³), `dpgf`, `tce_m30_70` (10⁻⁶/K) |

* **Self-check.** The same check as for AGF files (|Δnd| ≤ 10⁻⁴, ΔVd ≤
  max(0.05, 0.1 %)). Materials whose data range excludes the F and C lines
  (infrared glasses) are checked for a real index over their data range
  instead, and reported as *nd/Vd not checked*. The range test allows
  10⁻⁴ µm, because ranges are quoted to five decimals.
* **Names.** The page file name (upper case) is the glass name. A name on
  several shelves of one maker keeps the `optical` page.
* **Results (database of 2026-10-11).** SCHOTT 170 of 171 glasses, OHARA
  410, HOYA 190, CDGM 314, HIKARI 375 and SUMITA 176 import. Every glass
  reproduces its catalogue nd. Flagged are SCHOTT BOROFLOAT33 (datasheet
  nominal values) and 33 SUMITA glasses, whose catalogue Vd is given to one
  decimal. SCHOTT DURAN (a single tabulated point) is skipped.
* **Limitations.** Formulas 4–9 are not converted (no glass maker uses
  them). The internal transmittance is used like an AGF catalogue's (§8c).

## 10. Optimisation (`optimize/`)

Merit function, a weighted RMS of operand errors:

    MF² = Σₖ wₖ (vₖ − tₖ)² / Σₖ wₖ

With exact limits (the default, ADR-042) the sum runs over the goals only, and
the limits are constraints met to their tolerance (*Exact constraints* below).
With weighted limits (`constraints: "penalty"`) every operand is in the sum,
as described here.

* The RMS-spot operand contributes one residual per ray coordinate (√(wᵢ/W)
  scaling). The sum of squares therefore equals the weighted RMS², and
  least-squares solvers see the full aberration structure.
* **Targets of the image-quality operands.** `rms_spot` and `rms_wavefront`
  minimise when their target is 0. With a target above 0 (a spot or a
  wavefront of a given size, e.g. a defocused beam on a sensor) they
  contribute the single error RMS − target, padded with zeros to their fixed
  size. Before ADR-039 the target of these two operands was ignored.
* **Polychromatic RMS wavefront.** With `wavelength` null the operand uses
  every wavelength, with its weight:
  * every wavelength's OPD is taken against the reference sphere of the
    primary wavelength's chief ray (§9), so lateral colour is a relative
    tilt and axial colour a relative defocus;
  * each wavelength's piston is removed and, with the centroid reference,
    also the best common tilt (linear in the pupil coordinates); with the
    chief reference the tilt stays;
  * the RMS is in waves of the primary wavelength, field-weighted;
  * the pupil is sampled through the fields' vignetting factors, as for the
    spot.

  With one wavelength chosen it is that wavelength against its own chief
  ray, in its own waves. Before ADR-039 a null wavelength meant the primary
  one only, so colour could grow unseen while the operand improved.
* `mtf` with `field` null is the field-weighted mean over all fields (it
  used to take field 1).
* `max_distortion` (%) penalises |distortion| at the largest field above the
  target, one-sided. With image-height fields it also keeps the field of view,
  which moves with distortion and focal length.
* Three more one-sided bounds act at the operand's field, or the largest field.
  They use the numbers of the design summary (`analysis/summary.py`), so the
  optimiser and the before/after table agree:
  * `max_lateral_color`: |lateral colour| in µm, the chief ray of the shortest
    minus the longest wavelength along the field direction. Measured in µm, a
    0.1 µm excess weighs like 0.1 % of distortion; in mm it would be a soft
    limit against a spot of a few µm.
  * `min_relative_illumination`: relative illumination, as a fraction of the
    axis.
  * `max_cra`: the chief-ray angle on the image, in degrees, which matters for
    image sensors. It is the angle of the primary chief ray to the local
    normal of the image surface where the ray lands: on a curved (or tilted)
    image surface the sensor's acceptance direction there, not the surface's
    axis. A chief ray from the centre of an image sphere meets it at 0°.
* With weighted limits, bound operands (`min_*`, `max_*`) contribute only when violated.
* **Fixed residual count.** A failed ray contributes a 1 mm penalty per
  coordinate. An operand that cannot be evaluated (a failed reference, an
  unreachable image-height field) contributes a large constant spread over
  its own number of residuals, and a system that cannot be compiled the same
  for every operand. Every operand therefore keeps its size in every
  evaluation, so the finite-difference Jacobian stays defined. (A failing RMS
  operand used to return one residual, and SciPy stopped with
  `operands could not be broadcast together`.)
* **Units decide the balance** (weighted limits). Errors are in each operand's own unit (mm, %,
  waves). A violated constraint in mm, such as an edge thickness 0.15 mm short,
  outweighs a spot of a few µm by orders of magnitude. The optimiser then
  serves the constraint at the image's expense: the cell-phone lens with the
  old 1 mm edge default went from 12 to 52 µm RMS while the merit function
  improved by 2 %. The wizard therefore never starts from a missed
  constraint (*Optimisation wizard defaults* below). The result reports image-quality operands that got worse
  (`objective_worse`).
* **Fixed operands.** Thickness and edge operands that no variable can
  change are listed in `fixed_operands`, with their share of the final MF²:
  * the thickness is not a variable, a solve or a pickup;
  * for an edge, both surfaces are plain planes, as on a filter plate whose
    edge is its centre thickness.

  The merit breakdown marks them `fixed`. They add a constant, so the
  improvement figure of MF understates the change in the image (94 % of the
  cell-phone run's final MF was a 1 mm edge target on its 0.4 mm IR filter).
* **Inert variables.** `inert_variables` lists the variables whose
  sensitivity at the solution is exactly zero: nothing the operands measure
  depends on them. A typical case is an image distance with a detector placed
  in global coordinates, which does not move with the image surface.
* Radius variables are optimised as **curvature**, which is smooth through a
  flat surface.
* Algorithms:
  * `local`: `scipy.optimize.least_squares(method="trf")`, a bounded
    trust-region reflective solver with `x_scale` from the variable magnitudes.
  * `global`: `scipy.optimize.differential_evolution` (Latin hypercube init,
    finite bounds required), followed by a least-squares polish. The population
    is updated per generation (`deferred`), and a generation is evaluated on the
    process pool when the parallel Jacobian is in use. The same seed gives the
    same search with and without the pool.
  * `multistart`: local runs from Latin-hypercube starts.
  * The global and multistart searches need finite bounds. A curvature
    without bounds gets the limit of its clear aperture, |c| ≤ 1 / semi-diameter
    (at most a hemisphere; widened to the start value if that is steeper). This
    is reported in the notes. Any other unbounded variable is refused, and the
    message names it.
* The solution is the best point evaluated. Cancellation returns the best
  point found so far. An error inside the search (not in the set-up) ends the
  run with status `error` and the best point found so far, instead of losing
  the run. The original system is never modified.
* **Parallel Jacobian** (`optimize/parallel.py`):
  * *How.* The finite-difference columns of the least-squares Jacobian run on
    the shared process pool (`workers.py`), one chunk per worker. Each worker
    compiles the system once per run and keeps its warm starts. The steps are
    SciPy's '2-point' scheme (h = 10⁻⁷·max(1, |x|) with the sign of x, reversed
    at an upper bound), so the Jacobian equals the serial one (10⁻⁶ in the test).
  * *Isolation.* The solver's trial steps, and the 2n points of the closing
    sensitivities, run in a worker too, so the optimisation does not share the
    server process's interpreter lock with the views that follow its preview.
    In the UI those had slowed the main-process evaluations about tenfold.
  * *When.* At least 3 variables, a first evaluation of at least 20 ms, two or
    more workers and an idle pool; `OPTICORE_PARALLEL_JACOBIAN=0` turns it off.
    The result reports workers, columns and time.
  * *Reproducibility.* The choice measures the first evaluation, so it can
    depend on the machine's load. The pool and the server process agree to
    the warm-start tolerances, but a run that ends on its budget far from a
    minimum can follow the two to different designs: the generic 500 mm
    achromat differed by 64 mm in one radius. Results that must not depend on
    the machine (the stored generic stock lenses, `reoptimize_sample`) are
    computed with `optimize(..., parallel=False)`.
  * *Speed.* Cell phone lens F/2.8 (14 variables, about 0.2 s per evaluation,
    11 workers):
    * standalone, 400 evaluations took 70 s serially and 29 s in parallel;
    * in the UI, 2000 evaluations took 193 s, against about 700 s before.
* Image-height fields are solved to 10⁻¹² mm. A Jacobian step of 10⁻⁷ moves
  the field by about that much, so a looser tolerance would leave the warm
  start in place and hide the field's change from the derivative.
* Sensitivities are central finite differences of MF at the solution.
* **Active operands.** An operand is in the merit function when it is
  enabled and its weight is above 0, or when it is a limit (role
  `constraint`, explicit or by type).
  * A limit's weight is not used, so a weight-0 limit is still met exactly.
    With weighted limits it stays in the breakdown with no contribution.
  * The order of the active operands numbers every result: the breakdowns,
    the constraint rows' `index`, the trade-off operand and the tolerancing
    limits.
  * A field or wavelength index that an operand names must exist, otherwise
    the set-up is refused.
  * The RMS operands weigh a field or wavelength they name with 1, whatever
    its system weight, so a field of weight 0 can still be measured and
    limited. It used to read 0.
* **Budget and status.**
  * With exact limits, the global search polishes differential evolution's
    own optimum (its lowest penalty), not the design with the smallest
    violation.
  * A local run, the global polish or any multistart run that stops on its
    share of the budget before converging makes the status
    `max_evaluations`. Multistart reports how many runs completed within
    their share.
  * A run that reaches the augmented Lagrangian's outer-iteration limit with
    budget left is `stopped` (its multipliers have not settled).
  * `evaluations` counts the search and never exceeds `max_evaluations`, with
    or without the pool: a finite-difference Jacobian starts only when all
    its columns fit. The closing evaluation of the design returned and its
    2n sensitivity points are `closing_evaluations`.
  * Finite-difference steps are h = 10⁻⁷·max(1, |x|) with the sign of x,
    adjusted at both bounds like SciPy's one-sided scheme. The serial
    Jacobian uses the same steps as the pool in both constraint modes, so a
    run gives the same design with and without the pool. (The serial
    weighted-limits solve used to leave the Jacobian to SciPy, whose
    '2-point' steps 10⁻⁷·|x| with `diff_step` and about 1.5·10⁻⁸·max(1, |x|)
    without it: the local run and the global polish and multistart runs each
    differed from the pool for curvatures, |x| < 1.)
  * `at_bound` holds within 10⁻⁹·max(1, |x|).

### Exact constraints (`optimize/constrained.py`, ADR-042)

A limit is something the design must meet, not something to trade: a focal
length, an edge thickness, a length, a chief-ray angle. In a weighted merit
function its weight decides how much image quality it may cost, and its unit
decides it as much (above). With exact limits the optimiser meets them to a
tolerance and minimises the goals among the designs that do.

* **Roles.** Each operand has a `role`: `objective` (a goal, in the merit
  function with its weight), `constraint` (a limit), or `auto` (the default):
  * limits: the bounds (`min_thickness`, `max_thickness`, `min_edge_thickness`,
    `max_total_track`, `max_distortion`, `max_lateral_color`,
    `min_relative_illumination`, `max_cra`) and the first-order targets (`efl`,
    `bfl`, `fnum`, `working_fnum`, `magnification`, `total_track`);
  * goals: the image quality (`rms_spot`, `rms_wavefront`, `mtf`) and the
    others.

  A limit's weight is not used. The goals' weights are among themselves.
* **Normalised constraint values.** g = σ(v − t)/s, or (|v| − t)/s for
  `max_distortion`, with σ = +1 for an upper bound or a target and −1 for a
  lower bound. A bound is met for g ≤ 1, a target for |g| ≤ 1. The tolerance s
  is in the operand's unit: 1 µm for thicknesses, edges and lengths; 10⁻⁴·|EFL|
  (at least 10 nm) for the focal length; 10⁻³ for F/#, distortion (%) and
  relative illumination; 0.01 µm of lateral colour and 0.01° of chief-ray angle
  (`merit.CONSTRAINT_SCALE`).
* **Augmented Lagrangian** (Powell–Hestenes–Rockafellar), with the bounded
  least-squares solver as the inner solver. The residual vector is
  T = [r_goals / √f₀, √(ρ/2) (g + λ/ρ) for targets, √(ρ/2) max(0, g + λ/ρ) for bounds],
  so |T|² = f/f₀ + the PHR terms, with f = |r_goals|² and f₀ its value at the
  start. Its Jacobian is the raw residuals' Jacobian with scaled rows, so the
  parallel Jacobian serves it unchanged.
  * After each inner solve: λ ← λ + ρg (targets), max(0, λ + ρg) (bounds). ρ
    grows tenfold when V = max(|g_target|, |max(g_bound, −λ/ρ)|) is above 0.05
    and did not fall below a quarter of its previous value (the first time: of
    its value at the start).
  * ρ₀ = 10 / max(1, |c₀|²/2), c₀ being the violations at the start (Birgin &
    Martínez 2014). At a start that meets its limits, a violation of one
    tolerance costs five times the starting objective. Rejected: a constant
    ρ₀ = 10 (feasibility first) drove a distant start into a poor region (merit
    6.2 against 0.94), and 100 times the formula slowed a start that met its
    limits (cell-phone lens, RMS 5.28 against 4.96 µm).
  * An inner solve may use all of the remaining budget but a small reserve, since it
    is the optimisation itself. Converged: every limit met, V ≤ 0.05, the inner
    solve converged, and the next inner solve (restarted with a fresh trust
    region) improved the objective by less than 10⁻⁶. The run gives up when ρ
    exceeds 10¹⁰.
* **Units of a constraint row.** Target, tolerance, price step, relaxed
  target and dmerit_dtarget are in the unit of its before/after values. For
  the RMS spot that is µm, although its operand target is in mm. The
  trade-off curve's targets use the same unit.
* **Limits that cannot be evaluated** at the starting design (e.g. a
  magnification of an infinite-conjugate system) are refused at set-up,
  since their violation is a constant that no step reduces.
* **Best design.** Designs are ordered by the feasibility rules (Deb 2000).
  Any design that meets every limit beats any that does not. Among those that
  do, the lower goal merit wins; among the others, the smaller total
  violation. For this ordering a limit counts as met within 0.05 of its
  tolerance, so the best design does not gain by using the tolerance up. The
  solver's converged solution is returned unless a recorded design is better
  by more than 10⁻³.
* **Limits no variable can change** (`fixed_operands`) stay out of the solve
  and the ordering, since they are constant. A violated one is reported as
  fixed and not met, and makes the run `infeasible`.
* **Infeasible.** If a limit is not met at the end, the status is
  `infeasible` (or `max_evaluations` when the budget ran out and every unmet
  limit could still change), with a note. The design returned violates the
  limits least.
* **Prices.** The result lists every limit (`constraints`): before, after,
  met, active, and its Lagrange multiplier.
  * The multipliers are estimated at the design returned by least squares on
    the stationarity condition, over the free variables (not at a bound) in
    their scales D: min |D(∇f/f₀ + Σ λⱼ∇gⱼ)| over the active limits (targets and
    bounds within one tolerance of their limit), λ ≥ 0 for bounds. The
    gradients come from the central differences of the closing sensitivities,
    so this costs no evaluations and works even when the run ended on its
    budget.
  * The relative gradient that remains, |D(∇f/f₀ + Gᵀλ)| / |D∇f/f₀|, is
    reported as `stationarity`. Above 0.05 the design is not yet a constrained
    optimum, and the price is marked approximate (≈).
  * Relaxing a limit by its step δ (`merit.RELAX_STEP`: 2 % of a thickness,
    0.5 % of EFL, 0.1 % of distortion, 0.1 µm of lateral colour, 1° of
    chief-ray angle, …) changes the optimum by Δf = −f₀ λ δ / s to first
    order. This is reported as the merit predicted with the limit relaxed:
    `price.merit_relaxed`, `change_percent` and `dmerit_dtarget`.
* **Global and multistart.** Differential evolution minimises
  f/f₀ + Σ (violation · s / δ)², so a violation of one relax step costs as much
  as the starting objective. Its best design is then polished by the augmented
  Lagrangian. Multistart runs the augmented Lagrangian from every start.
* **Glass substitution** orders the glass trials by the same feasibility
  rules. A glass that meets the limits wins over a sharper one that does not.
* **Weighted limits** (`constraints: "penalty"`) keep the earlier behaviour.
  The stored generic stock-lens library is generated that way, so the data
  stay reproducible.
* **Cell-phone lens**, wizard set-up with limits on the focal length, nine
  edges, distortion, lateral colour and chief-ray angle; 2000 evaluations:
  * exact limits: RMS 7.18 → 4.96 µm, every limit met (EFL 5.5870700 against
    5.58707, lateral colour 1.6999999 µm at a 1.7 limit, chief-ray angle
    26.59999°);
  * weighted limits: 5.05 µm, with the focal length 34 nm off.

### Trade-off curves (`optimize/tradeoff.py`)

A price is the slope of the best merit against one limit at the current
target. The trade-off curve shows that function itself, so an engineer can
see what a limit costs over a range: how much sharper the lens gets per 0.1 mm
of length, per degree of chief-ray angle, per micrometre of lateral colour.

* Each target is a full optimisation with that limit exact. It runs locally
  from the optimised design, with at most 800 evaluations per point (UI), and
  the points run in parallel, one per worker of the process pool.
* Default targets: the current one and four steps of two relax steps to each
  side. A target at or below zero is skipped for quantities that must be
  positive (thicknesses, lengths, EFL, F/#, RMS spot and wavefront, beam
  size, colour, CRA, distortion bounds, fractions). Fractions (MTF,
  throughput, detector power, relative illumination, reflectance) are capped
  to [0, 1], and duplicates are dropped.
* Every point is a complete optimisation result, reported against the design
  before optimisation: initial values, merit and operands. A point can
  therefore be shown, compared and applied like the run's own result.
* Check: for the singlet with its thickness bound at 6 mm, the curve at
  5.76 / 6.00 / 6.24 mm falls monotonically. The price at 6 mm agrees with the
  curve's central difference to 20 %. Each point meets its bound to 10⁻³ mm.
* API: `POST /optimize/tradeoff/start`, `GET /optimize/tradeoff/{id}`,
  `GET /optimize/tradeoff/{id}/points/{k}`, `POST /optimize/tradeoff/{id}/cancel`.

### Detector operands (`nsdirect.py`)

Two operands evaluate the project's light sources at an analytic detector:

* `detector_size`: the second-moment beam diameter D4σ = 4σ in the detector
  *plane* (mm), in x, y or their average. For a Gaussian beam it is the 1/e²
  diameter; for a uniform disc of radius a it is 2a. All rays that cross the
  plane count, weighted by power, so the value is a smooth function of the
  design even when the beam is larger than the detector.
* `detector_power`: the fraction of the emitted power the detector accepts
  (area, side, acceptance angle). It changes in steps of about 1/rays, so
  gradients are mostly zero. Combine it with `detector_size`, or use the
  global algorithm.

Both use the **direct-path trace**. The seeded source rays (the same
sampling as the non-sequential trace) are traced with the vectorised
sequential ray trace: exact refraction, Fresnel or thin-film transmission
and absorption, with clipping at the clear apertures of the refracting and
reflecting surfaces. The path is the polyline source → surface hits →
straight on, and each detector plane is intersected with its segments.
A crossing at a vertex shared by two segments (a detector on a surface's
vertex plane, such as one anchored to the image surface) belongs to the
segment that ends there, so every ray counts once. An earlier rounding gap
dropped such crossings at some distances without reporting a loss.
Absorbing detectors stop the ray, monitors do not, and back hits and
acceptance angles follow the detector rules.

For light that passes the clear apertures, the result equals the
non-sequential trace without splitting. It is about 60 times faster (20 ms
instead of 1.2 s for 1500 rays). Not modelled: ghosts, lens edges, rays
that pass beside a lens, scattering and CAD bodies. The full
non-sequential analysis shows those. The seed is fixed, so the merit
function is deterministic. Sources with their own wavelengths refract with
the indices at those wavelengths, added to the compiled system without
changing its solves.

### Before/after numbers (`analysis/summary.py`)

The merit function sees only its operands, so an optimisation can improve it
while the image gets worse in ways no operand measures. `design_summary`
collects, from the normal analyses:

* the RMS spot per field;
* the polychromatic diffraction MTF per field (T and S). It is taken at half
  the sensor's Nyquist frequency, or else at a quarter of the incoherent cutoff
  of the longest wavelength (rounded to two digits), and both designs use the
  same frequency;
* EFL, working F/# and total track;
* the object field of the largest field: the field of view, which moves for
  image-height fields;
* at the largest field: distortion, lateral colour (the chief ray of the
  shortest minus the longest wavelength), relative illumination and the
  chief-ray angle on the image;
* axial colour;
* the thinnest lens edge and air gap. Plane-parallel plates are left out,
  since their edge is their centre thickness.

* the **field profile**: the RMS spot at 11 points from the axis to the
  largest field, along its direction, with the vignetting factors interpolated
  from the defined fields. An optimiser sees only the fields it is given, and
  the image can fall apart between them. A *sampling gap* is a profile point
  more than 0.05 of the field away from every defined field where:
  * the RMS spot exceeds the largest RMS spot of the defined fields by more
    than 25 % and by more than 0.25 Airy radius; or
  * the rays fail although the defined fields trace.

  The cell-phone lens optimised on the axis and the full field only reached
  6.1 and 4.9 µm there, but 10.7 µm at 40 % of the field. The comparison flags
  that as `field_gap`.

`compare_designs` runs it on both designs and flags what got worse. The
thresholds are in the module notes; for example, distortion is flagged when
|D| grows by more than 0.5 percentage points. The field of view and EFL are
flagged as *changed*. The endpoints are `POST /analysis/summary` and
`POST /optimize/compare`. The optimisation result shows the table, which
replaced the RMS-spot-only table.

For the user's cell-phone run (wavefront objective, on the ray-optics transcription that was the sample then;
ADR-040) the comparison flags:

* distortion, 3.2 → 9.8 %;
* lateral colour, −0.9 → +2.3 µm;
* corner illumination, 53 → 48 %;
* length, 6.70 → 6.91 mm;
* the field of view, 30.4° → 28.7°.

Meanwhile the RMS spots fell from 13.4 / 15.3 / 9.7 to 2.7 / 5.4 / 6.6 µm.

### Optimisation wizard defaults (UI, `lib/optWizard.ts`)

The wizard's constraints scale with the lenses and are never stricter than
the design is now. A constraint the start already misses makes the optimiser
trade image quality for it (above).

| Constraint | Scaled default | Cap from the current design |
|---|---|---|
| Lens edge | 10 % of the smallest lens diameter, at most 1 mm | 90 % of the thinnest lens edge now |
| Lens centre | 15 % of that diameter, at most 1 mm | the thinnest centre now |
| Air gaps between lenses | 2 % of that diameter, at most 0.1 mm | 90 % of the narrowest lens-to-lens gap now |

* The lens-gap minimum applies at the edge as a merit target and at the
  centre as a hard bound of the gap variable.
* Plane-parallel plates get no edge target.
* A stop at a lens vertex is not a lens gap.
* For the sharpest-image goals:
  * *Distortion at most* is on by default for systems with an off-axis field,
    at the current |distortion| rounded up to 0.1 %;
  * *Keep the focal length* is on by default, at the current EFL.
* For a spot or beam of a given size, both are off unless ticked: the size is
  set by the power and the focus.
* *Total track at most* is offered with the current value.
* *Lateral colour at most*, *Corner illumination at least* and *Chief-ray angle
  at most* show the engine's current values.
  * Lateral colour is on by default for the sharpest-image goals, at the current
    value rounded up to 0.1 µm.
  * The other two are offered, rounded to 1 % and 0.1°.
* For the beam goal, the wizard warns when the chosen detector is not anchored
  to the image surface, since the image distance then does not move it.
* The goals are the sharpest image (RMS spot or polychromatic RMS wavefront),
  a spot of a given RMS radius, or a beam of a given D4σ diameter on a
  detector. The beam goal uses the light sources and detectors; a Gaussian
  beam source gives the real beam diameter including diffraction, since the
  ray ensemble's second moments propagate as the Gaussian beam's.

## 10a. Glass substitution (`optimize/glass.py`)

With exact limits, a trial that meets every limit some variable changes
(within one tolerance, the rule of the report) beats any trial that misses
one. Among those, the lower goal merit wins; otherwise, the smaller excess.
The stricter order used inside one solve (0.05 of a tolerance) had rejected
trials whose short budget met the limits but not to that margin. Trials skip
their sensitivities, since only the design returned needs them.

A `material` variable makes the glass after a surface a discrete optimisation
variable.

**Candidates:** the variable's candidate list, or all built-in materials of
category "glass". In either case only materials whose data range covers every
system wavelength are used, and the current glass is always included.

**Search:**
1. Optimise the continuous variables locally (TRF) with the current glasses.
2. For each material variable, try every other candidate. Each trial
   re-optimises the continuous variables locally, warm-started from the best
   design so far, with an equal share of the evaluation budget
   (`max_evaluations / (1 + 2·Σ(candidates − 1))`).
3. Keep a candidate when it lowers the merit.
4. Repeat whole passes until a pass brings no improvement (at most 3 passes)
   or the budget is used up.

**Result:**
* This is a greedy local optimum in the mixed discrete/continuous space, not
  an exhaustive search. The result note states how many of the possible glass
  combinations were evaluated.
* The result lists `materials` (initial → final, plus the candidate set) next
  to the continuous variables. During the run the live preview shows the best
  glasses (`best_materials`).

**Restrictions:**
* Material variables cannot be per-configuration.
* They cannot act on a material set by the configuration editor.
* They need a glass after the surface.
* The merit function itself rejects them, because they are discrete.

## 10c. Parameter sweeps and reports

**Sweeps** (`analysis/sweep.py`) evaluate merit-function operands over a 1D
grid or a 2D grid of one or two parameters, with at most 2601 points.
* A parameter is any continuous optimisation variable (radius, thickness,
  conic, aspheric terms, coordinate-break decenter or tilt), optionally per
  configuration. Radius sweeps are specified in mm.
* Values are computed with the same code path as the merit function and the
  optimiser.
* Points where an RMS operand has failed or vignetted rays are omitted and
  reported. They are not shown with the optimiser's failure penalty. The merit
  breakdown carries `failed_rays` for this purpose.

**Engineering reports** (`frontend/src/lib/report.ts`) are self-contained
HTML: inline CSS and SVG charts, and no scripts or external resources.
* Contents: system summary, layout, prescription (resolved solve and
  configuration values), spot diagrams, MTF, field curvature and distortion,
  throughput, the latest optimisation and the tolerance results if they are
  current, and diagnostics.
* Every number comes from engine calls made when the report is generated, and
  the design state is identified by the project SHA-256.

## 10b. Tolerancing (`tolerance.py`)

**Perturbations** (signed value d within [min, max] per tolerance):

| Type | Effect |
|---|---|
| `radius` | R → R + d (mm; curved surfaces only) |
| `thickness` | t → t + d (mm) |
| `conic` | k → k + d |
| `index` | n(λ) → n(λ) + d for the medium starting at the surface (all wavelengths; dispersion unchanged) |
| `abbe` | Vd → Vd + d at constant nd for the medium starting at the surface (below) |
| `power` | sagitta (power) error, d fringes over the clear aperture (ISO 10110-5 A; below) |
| `irregularity` | astigmatic irregularity, d fringes peak-to-valley (ISO 10110-5 B) |
| `irregularity_rotational` | rotationally symmetric irregularity, d fringes peak-to-valley (ISO 10110-5 C) |
| `zernike_form` | one Fringe Zernike sag term `term` (Z5…Z37), coefficient d in µm |
| `surface_decenter_x/y`, `surface_tilt_x/y` | one surface, about its vertex (mm / degrees) |
| `element_decenter_x/y`, `element_tilt_x/y` | lens or cemented group a…b, about the front vertex |

Decenters and tilts use exact coordinate-break pairs. With D the axial length
of the group and t_b the thickness after its last surface:

    CB(dx, dy, tx, ty; order 0; t = 0), a, …, b (t = −D), CB(−dx, −dy, −tx, −ty; order 1; t = D + t_b)

Order 1 with negated values is the exact inverse of order 0, so every surface
downstream keeps its nominal global position and orientation (tested to
1e-12). Several decenters/tilts of the same group are combined in one pair.
Element pairs are inserted outside surface pairs, so nested perturbations
compose exactly. A thickness compensator on the last surface of a perturbed
group acts on the return break (which now carries that thickness).

**Surface form.** One fringe is half the test wavelength λ_t of surface
height (`test_wavelength_um`, default 546.07 nm as in ISO 10110-5). Form
errors refer to the clear aperture r_ca: the nominal effective
semi-diameter of the surface (a Zernike surface uses its normalisation
radius).
* Power: the base curvature changes by dc with
  sag(c + dc, r_ca) − sag(c, r_ca) = d·λ_t/2 for the conic base
  (Newton with d sag/dc = r²/(s(1 + s)), s = √(1 − (1 + k)c²r²); exact).
  Plane surfaces get a curvature (flatness error). Aspheric terms are kept.
* Irregularity: Fringe Z5/Z6 sag with coefficient d·λ_t/4 (ρ² cos 2θ has a
  peak-to-valley of 2 over the disc), orientation 0° in the sensitivity run
  and uniformly random in [0°, 180°) for every Monte Carlo trial (drawn after
  the values, so runs without irregularity draw exactly as before; the angles
  are reported with the trials).
* Rotational irregularity: Fringe Z9 referenced to the vertex,
  6ρ⁴ − 6ρ², with coefficient d·λ_t/3 (peak-to-valley 1.5); the vertex and
  so the thickness stay put.
* A form error makes a standard or even-asphere surface a Zernike surface
  with the same base (`zernike_norm_radius` = r_ca; leftover aspheric
  terms of a standard surface are dropped, as the standard surface ignores
  them). Biconic and ideal surfaces and coordinate breaks are refused.
* The wavefront change at normal incidence is (n − n′)·Δz (2Δz in
  reflection); VALIDATION has the benchmarks.

**Abbe number.** For the medium of the surface, with nd, nF, nC from the
library at the system's conditions (so also with the environment model on):
n(λ) → n(λ) + dn + κ(n(λ) − nd), κ = −dVd/(Vd + dVd). This keeps nd (plus
any `index` offset dn) and changes nF − nC so that Vd becomes exactly
Vd + dVd (with an `index` offset as well, the index offset keeps its
"dispersion unchanged" meaning). The offsets travel to the compiled system as
(dn, dVd) pairs (`system.index_offset`).

**Criterion**:
* RMS spot radius in µm (centroid reference, all fields and wavelengths)
* RMS wavefront in waves of the primary wavelength. It is polychromatic,
  like the `rms_wavefront` operand without a wavelength (ADR-039): every
  wavelength against the primary chief ray's reference sphere, wavelength-
  and field-weighted.
* the project merit function: the active operands of the active
  configuration. Operands pinned to other configurations are left out with a
  note.
  * With exact limits (the optimisation's mode, which the UI passes), the
    criterion is the merit function of the goals, as in the optimiser. The
    compensators minimise the goals.
  * The limits are reported apart (`limits`): the nominal value, the value
    at each sensitivity side and in each Monte Carlo trial, and how many
    trials meet them to the optimiser's tolerance. Limits do not enter the
    yield.
  * With weighted limits, every operand is in the criterion.
* MTF: the diffraction MTF at `mtf_frequency` (cycles/mm), mean over the
  fields of the average of tangential and sagittal values, polychromatic
  (the `mtf` merit operand: FFT of a 32 × 32 pupil, padding 4). Higher is
  better: compensators maximise it (target 1), the RSS estimate subtracts
  (clipped at 0) and the percentiles of interest are the low ones.

All use the merit-function machinery with Gaussian pupil quadrature
(`rings`). Automatic semi-diameters are recomputed for every perturbed
system. Fixed apertures vignette as usual.

**Compensators**: each enabled compensator (thickness or curvature) is
re-solved for every perturbed system. The solver is bounded trust-region least
squares on the criterion residuals, within ±range of its value in the
perturbed system (≤ `compensator_evaluations` evaluations). A compensated
result is only accepted if it is no worse than the uncompensated one. Both
values are reported.

**Sensitivity**: each tolerance alone at min and at max. Δ is measured from the
compensated nominal. The rows are sorted by worst |Δ|.

**RSS estimate**: nominal + √(Σ max(|Δ_min|, |Δ_max|)²). This assumes
independent, approximately linear, degrading tolerances. It is an estimate;
compare it with the Monte Carlo statistics.

**Monte Carlo**: all enabled tolerances are drawn independently with
`numpy.random.default_rng(seed)`, so runs are reproducible.
* `uniform`: drawn on [min, max].
* `normal`: mean at the centre, limits at ±2σ, truncated at the limits
  (scipy `truncnorm`).

Reported statistics: mean, σ, min, max and the 2/10/50/90/98 % percentiles.
Trials that fail (ray failures, invalid geometry) are counted and excluded,
and a warning is shown. A warning is also shown below 20 trials.

**Yield.** With a specification `limit` (criterion ≤ limit, ≥ for MTF) the
yield is the fraction of Monte Carlo trials that meet it; failed trials
count as failing. Its 95 % Wilson score interval,
(p̂ + z²/2n ± z√(p̂(1 − p̂)/n + z²/4n²))/(1 + z²/n), z = 1.96, is reported
(exact 0 and 1 at the ends), so a small run shows how little it proves.

**Allocation (inverse sensitivity).** `allocate` (API flag) distributes a
performance budget over the tolerances before the Monte Carlo run:
1. The criterion maps to a quantity that adds over independent small
   perturbations: Q = c² for the RMS criteria and the merit function
   (variances add), Q = −c for MTF (losses add). Budget
   B = Q(limit) − Q(nominal); the nominal must meet the specification.
2. Locked tolerances (`locked`) keep their limits; their worst-side increase
   of Q at the limits is taken from B first. The rest is split equally over
   the free tolerances.
3. Each free tolerance's limits are scaled by one factor f (1e-3 … 10) until
   its worst-side increase of Q (real, compensated criterion at f·min and
   f·max) equals its share: power-law secant steps in log f from the
   sensitivity run, aimed 2.5 % under the share and never over it, at most
   eight steps. Factors at the bounds are reported (insensitive or cannot be
   tightened enough).
4. New limits are rounded toward zero to three significant digits. With
   every tolerance at its limit together, the quadrature model predicts
   Q⁻¹(Q(nominal) + Σ shares) ≤ limit; the Monte Carlo run then uses the
   allocated limits and its yield confirms the allocation (or not, where
   the tolerances interact).
The result lists the current and allocated limits, factors and shares; the
UI applies them to the tolerance list only on request (one undoable edit).

**Default grades** are generic, illustrative values: user-editable starting
points, not vendor specifications.

| Grade | ΔR/R | power (fr) | irregularity (fr) | Δt (mm) | Δn | ΔVd/Vd | decenter (mm) | tilt |
|---|---|---|---|---|---|---|---|---|
| commercial | 0.5 % | 5 | 2 | 0.10 | 0.001 | 0.8 % | 0.05 | 3′ |
| precision | 0.1 % | 3 | 1 | 0.05 | 0.0005 | 0.5 % | 0.02 | 1′ |
| high precision | 0.05 % | 1 | 0.25 | 0.02 | 0.0002 | 0.2 % | 0.01 | 0.5′ |

The defaults cover radii, power and (astigmatic) irregularity of every
standard, even-asphere and Zernike surface, glass centre thicknesses, air
gaps (except back focus), indices and Abbe numbers (from the material's Vd;
none for a material without visible dispersion data), and element decenters
and tilts. The back focus is a ±2 mm thickness compensator.

Not modelled yet: wedge as a separate type (use a surface tilt), measured
surface maps, inhomogeneity and birefringence of the glass, and cost-weighted
allocation (the allocation splits the budget equally).

## 11. Diagnostics

**Not applicable.** An analysis that does not apply to a kind of system
raises `system.NotApplicable` (a `SystemError_`), and the API answers 422
with the code `NOT_APPLICABLE` (also inside endpoints that handle their own
`ValueError`, through `refused`). The UI then shows the reason as *Not
available for this design* instead of a failure. Examples:
* ghosts of mirror or folded systems;
* POP of non-axial or reflecting systems;
* diffraction analyses of afocal systems;
* wavefront, Huygens and vector PSF of image-space telecentric systems;
* relative illumination and the live image without an off-axis field;
* a live image whose frame holds fewer than 8 Airy discs;
* ideal lenses in the non-sequential trace.

Every other refusal is an error in the design or the settings. The matrix
test (VALIDATION, *Robustness matrix*) holds every analysis to this on
every sample.

`system.py` and `analysis/evaluate.py` report structured diagnostics:

* unknown material
* extrapolated wavelength
* ignored aspheric terms
* non-axial system
* coordinate break before the stop
* semi-diameter beyond the surface domain
* non-positive glass thickness
* negative edge thickness
* zero aperture
* failed chief or marginal rays per field

## 12. Known limitations

* Tolerancing (§10b) is sensitivity, RSS, Monte Carlo, yield and
  inverse-sensitivity allocation on one criterion; no separate wedge type,
  measured surface maps, glass inhomogeneity or birefringence, and the
  allocation splits the budget equally (no cost weighting).
* Polarisation ray tracing (§8f) handles uniaxial crystals (§8l) and ideal
  polarisers and retarders; no biaxial or optically active media, no
  scattering depolarisation (the beam's Mueller matrix is a pupil average).
  Thin-film coatings (§8d) are isotropic and coherent, and mirror substrate
  indices are single-wavelength values.
* Non-sequential tracing (§8h) is geometric. Scattering uses Lambertian,
  Gaussian, ABg or Harvey–Shack models (no tabulated BSDF measurements, no
  anisotropic or wavelength-dependent scatter); importance sampling aims
  at one target per run. Sources and detectors are geometric: Gaussian
  beams are ray ensembles (second moments exact), and no mode overlap,
  coherence or diffraction is computed. Ideal lenses and diffractive phases
  are not part of the non-sequential trace.
* Diffraction in the image analyses is scalar, except for the vector
  (Debye–Wolf) PSF (§8m). The FFT PSF neglects pupil aberrations and
  off-axis anamorphism; the Huygens PSF (§8b) includes them but remains
  scalar. Wave optics (§8r) adds scalar physical-optics propagation and BPM,
  exact fibre modes, RCWA and FDTD Maxwell solvers.
* Object-space telecentric systems are traced as such only when the mode is
  enabled (§6). Image-space telecentric systems have their exit pupil at
  infinity, so the spherical OPD reference of the wavefront analyses is
  undefined there (reported).
* Real image-height fields are resolved at the primary wavelength. Heights
  that no real chief ray can reach are rejected, not extrapolated.
* Catalogue internal transmittance is used only with the system's catalogue
  absorption on; it is interpolated linearly in α between the catalogue's
  wavelengths (10 nm to 0.5 µm apart), which does not resolve narrow
  absorption bands.
* Sapphire is built in with its ordinary index only (`SAPPHIRE_O`, no
  extraordinary record), so it is traced as an isotropic glass; uniaxial
  birefringence applies to materials with an extraordinary record (§8l).
* Diffractive surfaces are scalar thin phase elements with 100 % efficiency in one order (§3, Diffractive surfaces): no multi-order or RCWA efficiency, no Seidel phase terms, no phase in non-sequential mode.
* Temperature and pressure (§9a) are uniform within each element and mount
  part (elements and parts can have their own temperatures): no
  thermal gradients, no stress birefringence, no deformation of lens seats
  or CAD bodies (CAD models do not expand; mount parts expand only along the
  axis), and thin-film coatings use their
  layer materials' room-temperature-relative indices through the same
  library (no layer thickness change).
* Paraxial values for systems with coordinate breaks are approximate (flagged).
* Stock lens systems (§8q):
  * spherical stock lenses only;
  * builds of 1-3 lenses in air, with the stop at the first lens (no
    separate stop surface or field lens rules);
  * three-lens builds sample the triples when there are many.
  The generic library is OptiCore's own, so a real part's prescription must
  be imported from the vendor before ordering.
* The design space map (§8p) optimises each candidate once, locally, with a
  fixed budget: the points are good designs of their topology and glasses,
  not proven optima. Only rotationally symmetric, all-spherical topologies
  with an object at infinity are generated, and glasses come in crown/flint
  pairs (no per-element glass choice). The results are session data, not
  saved in the project.
