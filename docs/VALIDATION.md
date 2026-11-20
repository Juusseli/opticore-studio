# Validation methodology

Every physics module is checked against analytical results or independently
documented values. Tolerances are chosen from the conditioning of each test:
machine-precision identities use ~10⁻¹²–10⁻¹⁵, iterative solvers use their
convergence tolerance, and third-order approximations use a relative tolerance
appropriate to the aperture. Tolerances are never loosened to hide a failure.

Run all checks:

```bash
cd backend && .venv/bin/python -m pytest -v   # Windows: .venv\Scripts\python
cd frontend && npm test
```

## Robustness matrix (`tests/test_analysis_matrix.py`, `tests/test_robustness.py`)

* Every analysis endpoint (every POST under `/analysis`, `/system` and
  `/elements`, found from the API itself) runs on every sample design.
  Fields are tried at the default and at the largest field, with the UI's
  defaults and lighter sampling for the heavy ones. Each call must either
  return finite numbers or refuse with `NOT_APPLICABLE`. New endpoints and
  new samples are covered without editing the test.
* The first run (720 calls, 18 samples, 32 endpoints) found:
  * POP failed on every imaging lens with the UI's default fibre-sized
    source. It now defaults to a beam that fills the pupil.
  * The live image refused image-height fields (cell phone lens). They are
    now resolved to object fields, and the image simulation and the live
    image drop no PSF node at the edge of the image circle.
  * A live image of a ±5 µm field took 25 s for a picture smaller than its
    blur. It is now not applicable.
  * The non-sequential trace of the cell phone lens took 292 s. A time
    limit with a random, scaled subset of rays now bounds it.
  * The mirror-system limitations of the ghost and POP analyses are now
    reported as not applicable.
* Targeted checks:
  * the limitations answer `NOT_APPLICABLE`;
  * the pupil-filling POP source equals a top-hat of radius r_EP;
  * a roomy time limit reproduces the full non-sequential trace (10⁻⁹);
  * a tiny limit traces one random ray scaled to the whole source, with
    the energy budget at 1 (10⁻⁹).

## Benchmarks (backend/tests)

| Benchmark | Reference | Tolerance | Test |
|---|---|---|---|
| Snell refraction at a plane interface | asin(sin θ / n) | 1e-14 rad | `test_snell_planar_interface` |
| Refraction independent of normal orientation | identity | exact | `test_snell_normal_orientation_independent` |
| Total internal reflection threshold | critical angle asin(n₂/n₁) | ±0.01 rad bracket | `test_total_internal_reflection` |
| Law of reflection, coplanarity | geometry | 1e-15 | `test_reflection_law` |
| Normal-incidence Fresnel reflectance | ((n₁−n₂)/(n₁+n₂))² = 0.04 | 1e-14 rel | `test_fresnel_normal_incidence` |
| Energy conservation R + T = 1 (s and p) | lossless dielectric | 1e-13 | `test_fresnel_energy_conservation` |
| Brewster angle R_p = 0 | atan(n₂/n₁) | 1e-15 | `test_brewster_angle` |
| Sphere intersection | |Q − C| = R on vertex hemisphere | 1e-10 mm | `test_sphere_intersection_matches_geometry` |
| Asphere intersection (Newton) | independent bisection | 1e-9 mm | `test_asphere_intersection_vs_bisection` |
| Surface normals | numerical gradient | 1e-7 | `test_normals_match_numerical_gradient` |
| Paraboloid sag | c r²/2 | 1e-13 | `test_paraboloid_sag` |
| Plane mirror / fold | unfolded equivalent spot, image position | 1e-9 | `test_fold_mirror_matches_unfolded` |
| Spherical mirror paraxial focus | f = R/2 | 1e-12 rel | `test_spherical_mirror_paraxial_focus` |
| Spherical mirror exact spherical aberration | axis crossing R − R/(2 cos θ) | 1e-9 mm | `test_spherical_mirror_exact_spherical_aberration` |
| Paraboloid perfect focus and equal OPL | aberration-free on axis | spot < 1e-10 mm, ΔOPL < 1e-9 mm | `test_paraboloid_perfect_focus_and_equal_opl` |
| Thick-lens EFL and BFL (lensmaker) | 1/f = (n−1)[1/R₁ − 1/R₂ + (n−1)d/(nR₁R₂)] | 1e-12 rel | `test_lensmaker_thick_lens_efl` |
| Thin-lens limit | (n−1)(1/R₁ − 1/R₂) | 1e-7 rel | `test_thin_lens_limit` |
| Principal planes and focal points (symmetric lens) | symmetry, F = P − f | 1e-12 | `test_symmetric_lens_principal_planes` |
| Parallel plate lateral displacement | t sin θ (1 − cos θ/√(n² − sin²θ)) | 1e-10 rel | `test_parallel_plate_lateral_displacement` |
| Real focus = paraxial focus as aperture → 0 | paraxial BFL | 1e-6 mm | `test_singlet_real_focus_close_to_paraxial` |
| Seidel S_I vs real-ray transverse aberration | δy = S_I/(2n′u′), small aperture | 1% | `test_seidel_SI_matches_real_transverse_aberration` |
| Distortion of a thin lens with the stop in contact | ≈ 0 | 1e-3 % | `test_distortion_zero_for_thin_lens_stop_at_lens_paraxially` |
| Spectral dispersion, catalogue transcription | published nd (5 decimals), Vd | 1.5e-5, 0.02 | `test_catalog_transcription_nd/vd` |
| N-BK7 nF, nC | SCHOTT datasheet | 1e-5 | `test_nbk7_reference_lines` |
| Normal dispersion | dn/dλ < 0 in the visible | — | `test_normal_dispersion_monotonic` |
| Chromatic focal shift sign | blue focuses closer for a positive singlet | sign | `test_chromatic_focal_shift_sign_singlet` |
| Achromat axial colour | F−C focal difference < 5% of the singlet's | — | `test_achromat_corrects_axial_color` |
| Real ray aiming | chief ray hits the stop centre, marginal ray the stop edge | 1e-8 mm | `test_real_ray_aiming_hits_stop_centre` |
| Vignetting / miss reporting | status codes and surface | exact | `test_vignetting_by_fixed_aperture`, `test_ray_miss_reported` |
| Reproducible spot diagrams | deterministic sampling | identical | `test_spot_reproducible_and_evaluate_runs` |
| Coordinate break inverse | order-1 negated break restores the frame | 1e-13 | `test_coordinate_break_inverse` |
| Unit conversions | exact decimal scaling | exact | `test_length_conversions` |

## Physical optics (backend/tests/test_diffraction.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Perfect paraboloid wavefront | W ≡ 0 | < 1e-9 waves |
| Spherical aberration OPD vs Seidel | W(edge) = S_I/8, ρ⁴ scaling | 0.5% / 1% |
| Defocus OPD and sign | W = δz ρ²/(8F#²), Fringe Z4 = W020/2 | 1% / 2% |
| Perfect PSF | Strehl = 1, F#_w = 5 | 1e-9 |
| Airy encircled energy at the first dark ring | 0.838 | ±0.01 |
| Diffraction MTF vs analytic circular pupil | (2/π)(φ − cos φ sin φ) | 0.005 |
| Maréchal vs FFT Strehl (σ ≈ 0.05 waves) | Agreement | 2% |
| PSF centroid vs mean real-ray position | Fraunhofer centroid theorem | 3% (2° field) |
| Zernike fit of synthetic coefficients | Recovery | 1e-10 |
| Fringe ordering | Z1…Z9, Z16, Z25, Z36, Z37 | Exact |
| MTF never exceeds the diffraction limit | Physical bound | +0.02 |

## Huygens PSF (backend/tests/test_huygens.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Aberration-free F/10 focus (exact diffractive focusing phase) | Airy pattern [2J₁(v)/v]², v = 2π NA r/λ, x and y sections; first zero 0.61 λ/NA; Strehl 1 | 4e-3 of the peak / 0.4 µm / 2e-3 |
| On-axis intensity at defocus Δz, u/4 = π/4, π/2, π | [sin(u/4)/(u/4)]², u = (2π/λ) NA² Δz (Born & Wolf 8.8) | 6e-3 |
| Image plane tilted by 60° | PSF stretched by 1/cos 60° = 2 along the tilt (not modelled by the FFT PSF) | 3 % |
| Achromat sample (σ ≈ 0.11 waves), 48 and 65 image samples | FFT PSF Strehl; independent of the image grid (refined peak) | 0.005 |
| Sampling checks | alias and pupil under-sampling warnings; invalid settings rejected | — |
| API | — | — |

## Energy throughput (backend/tests/test_throughput.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Uncoated plate, normal incidence | T = (1−R)², R = ((n−1)/(n+1))² | 1e-9 |
| Bulk absorption | (1−R)² exp(−α t) | 1e-9 |
| Vignetting by a half-radius aperture | area fraction 0.25 | 0.01 |
| Ideal mirror | T = 1 | 1e-12 |
| Throughput operand equals the analysis | — | 1e-12 |

## Thin-film coatings (backend/tests/test_thinfilm.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Empty stack, 0–80° | Fresnel equations (s, p) | 1e-14 |
| Quarter-wave layer at design λ | R = ((n₀n_s − n₁²)/(n₀n_s + n₁²))² | rel 1e-12 |
| Ideal quarter-wave index n₁ = √n_s | R = 0 | 1e-28 |
| Half-wave layer | absentee (R = bare) | rel 1e-12 |
| Lossless stacks, 0–70°, 3 wavelengths | R + T = 1 (s and p) | 1e-12 |
| V-coat (exact two-layer design on n_s = 1.52) | R = 0 at the design wavelength | 1e-20 |
| Reciprocity (front vs rear face) | T identical | rel 1e-12 |
| Coated singlet chief ray in the trace | product of stack transmittances × absorption | rel 1e-10 |
| AR coating raises system throughput | > uncoated + 3 % | — |
| Unknown coating / built-in coating (no substrate) on a mirror | structured error / `COATING_IGNORED` warning | — |
| Coating API curve at 550 nm | quarter-wave formula | rel 1e-6 |

## Coating analyses (backend/tests/test_coatanalysis.py)

Spectra, phase, group delay and GDD, colour, standing-wave field and index profile of a stack (`coatanalysis.py`),
shared by the coating editor and the coating designer.

| Benchmark | Reference | Tolerance |
|---|---|---|
| Field by plane-wave amplitudes per medium (absorbing stack, s and p, 0°, 35°, 70°) | R and T of the characteristic matrix (independent code); layer absorptances sum to 1 − R − T; a lossless layer absorbs nothing | 1e-12 / 1e-9 / 1e-15 |
| Bare interface standing wave | \|1 + r e^{2ik₀n₀z}\|² with Fresnel's r in the incident medium; (2n₀/(n₀ + n_s))² in the substrate | 1e-12 |
| Group delay of a 3 µm vacuum gap (local stencil) | GD = d/c, GDD = 0 | rel 1e-9 / 1e-5 fs² |
| Gires–Tournois interferometer (spacer on a perfect mirror) | closed-form GD from φ = arg(r₁ − z) − arg(1 − r₁z); \|r\| = 1 | rel 2e-4 (finite differences) |
| Colour of a perfect reflector | D65 white point (x 0.312727, y 0.329023), L* = 100, a* = b* = 0 | 2e-5 / 1e-6 |
| Flat reflectance R | L* = 116 R^{1/3} − 16, chromaticity of D65, Rv = R, Tv = 1 − R | 1e-9 / 1e-12 |
| Colour swatch | hue at full brightness (the dim BBAR_VIS reflection: brightest channel 1); a flat reflection is white | 1e-12 / 2e-3 |
| Bare plate, incoherent back surface | T = 2n/(n² + 1); R + T = 1 | 1e-14 |
| Ellipsometric angles | ψ = 0 at Brewster's angle; Δ = 0 at normal incidence (Macleod's convention) | 1e-6° / 1e-9° |
| Phase where the amplitude vanishes (rp at Brewster's angle) | phase, GD and GDD undefined (null in the API); rs phase 180°, GD 0 | exact / 1e-12 fs |
| Opaque metal | T = 0, A = 1 − R; substrate plus layer absorptance = 1 − R | 1e-15 / 1e-9 |
| Index profile of a quarter wave | QWOT = 1; total thickness λ/(4n) | 1e-12 |
| Dispersive substrate and the analysis bundle | read-out at λref equals the spectrum; band mean within min…max; angle curve at 0° equals the spectrum | 1e-12 |
| API | `/coatings/analyze` (built-in, definition, unknown name → COATING), `/coating-design/analyze` | — |

## Built-in coating library (backend/tests/test_builtin_coatings.py)

29 coatings in `materials/data/builtin_coatings.json` (generated by `python -m opticore.tools.builtin_coatings`) of
measured film and metal materials on N-BK7, each with the specification it meets.

| Benchmark | Reference | Tolerance |
|---|---|---|
| Breadth | antireflection, mirrors, filters, beam splitters; ≥ 20 coatings, each with a description, design λ and specification | — |
| Every built-in on its design substrate and incident medium | every target of its specification (R/T, s/p/avg, angle, band) | 1e-12 beyond the stated tolerance |
| MgF₂ film quarter wave on N-BK7 | thickness λ₀/(4n); R = ((n_s − n²)/(n_s + n²))² | 1e-12 / 1e-14 |
| HR quarter-wave stacks (532, 633, 1064, 1550 nm) | QWOT = 1 of every layer; lossless stack R = ((1 − Y)/(1 + Y))², Y = (n_H/n_L)^{2N} n_H²/n_s; absorbing stack within its absorptance below | 1e-12 / 1e-13 |
| V-coats (355 … 1550 nm), complex film indices | R = 0 at λ₀ (not quarter waves) | 1e-18 |
| Metal mirrors | opaque (T < 1e-4); the bare metal film reproduces the semi-infinite metal | 2e-4 |
| MacNeille cube | n_g² = 2n_H²n_L²/(n_H² + n_L²); every H/L interface at Brewster's angle; Rs > 99.9 % at 550 nm, Tp > 98 % over 450–680 nm | rel 1e-6 / 1e-4° |
| Opened in the coating designer (`design_from_builtin`) | design λ, incident and substrate indices and targets carried over; every target met by the designer's own code; spectrum equal to `coatanalysis` | — / 1e-12 |
| Fixed incident index of a design | R = ((n₀ − n_s)/(n₀ + n_s))²; total reflection beyond asin(n_s/n₀) | rel 1e-13 / 1e-12 |

## Coating materials with n and k (backend/tests/test_coating_materials.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Converter: refractiveindex.info formulas 1, 2, 5 and tabulated n, k, nk | the formulas evaluated directly; table nodes; k held beyond its table | rel 1e-14 / 1e-14 |
| Table thinning (synthetic band with an absorption peak) | every original point reproduced | 1e-4 |
| Shipped films at 550 nm | typical film indices (SiO₂ 1.44–1.49, TiO₂ 2.2–2.5, …), k < 1e-4 | — |
| Bare metals at normal incidence | R = ((n − 1)² + k²)/((n + 1)² + k²): Ag, Al > 0.9 at 550 nm; Au > 0.95 at 1 µm and < 0.5 at 450 nm; Cu rises from blue to red | — |
| Metal as a lens medium | structured error | — |
| Library metal substrate in the designer | opaque; R = bare-metal formula; A = 1 − R | rel 1e-12 |
| Record validation | negative k refused; constant k | — |

## Professional coating tools (backend/tests/test_coating_pro.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Stack formula (HL)^7 H | quarter waves λ₀/(4n); identical to the explicit list; R = ((1 − Y)/(1 + Y))², Y = (n_H/n_L)¹⁴ n_H²/n_s | rel 1e-15 / exact / 1e-14 |
| Formula grammar | multipliers distribute over groups; nested repeats; "*" optional; structured errors (unbalanced, ^0, unknown key, empty, dangling number) | exact |
| Formula round trip of every built-in | parse(to_formula(d)) reproduces the layers; quarter-wave HR stacks as (HL)^N H exactly | rel 5e-4 / 1e-12 |
| Admittance of a quarter wave | a circle centred on the real axis from n_s to n²/n_s; R = ((1 − n²/n_s)/(1 + n²/n_s))² | 1e-12 |
| Admittance of a half wave | ends where it started (absentee) | 1e-12 |
| Admittance end point, absorbing stack at 35°, s and p | R of the characteristic matrix; points on the iso-R circles reflect that R | 1e-12 / rel 1e-12 |
| GD target, 3 µm vacuum gap in transmission | d/c | rel 1e-12 |
| GD and GDD targets of DM_800 | `coatanalysis.phase` (separate implementation) | rel 1e-9 |
| Retardance target, bare glass | 0° below, 180° above Brewster's angle | 1e-9° |
| Retardance target, total internal reflection (n₀ = 1.5, 50–70°) | 2 atan(cos θ √(sin²θ − n²)/sin²θ) − 180° (Macleod's p sign) | 1e-9° |
| Colour targets, flat 4 % reflection | Rv = 0.04, Tv = 0.96, L* = 116 R^{1/3} − 16, a* = b* = 0 | 1e-12 / 1e-9 / 1e-6 |
| Target validation | fractions within 0…1; GD/GDD need ≥ 5 points; transmitted phase of an opaque substrate refused | — |
| Dispersive mirror optimisation (library example) | from a chirped start: R ≥ 99 % and GDD −40 ± 15 fs² met | MET_TOL |
| Reverse engineering, BBAR_VIS with six known errors (R 0°, R 45°, T 0°) | errors recovered; RMS → 0 | 1e-6 / 1e-8 |
| Reverse engineering, LP_550 uniform +2.5 % | scale recovered; with 2·10⁻³ noise within 4σ and RMS ≈ noise | 1e-7 / 4σ / 20 % |
| API | /coating-design/formula, /fit, evaluate's formula, the admittance in /analyze | — |
| Absorbing plate, bare back face (n − ik, 3 mm) | T = (1 − R)² Ti / (1 − R² Ti²), R + (1 − R)² R Ti² / (1 − R² Ti²), Ti = exp(−4πkd/λ) | rel 1e-9 |
| The same coating on both faces (VCOAT_1064) | T = (1 − R₁)/(1 + R₁) | rel 1e-6 (the films' k) |
| Plate with a back coating and 2 mm substrate, 0° and 30° | designer spectrum = analysis module; transmitted GD equal | 1e-12 / rel 1e-9 |
| GD through 1 mm N-BK7 | d n_g / c with n_g from the analytic Sellmeier derivative; GDD from its derivative | rel 2e-6 / rel 1e-4 |
| Index fit (BBAR_VIS; R, T at 0° and 45°) | scale, Δn of both films, ΔB recovered; the fitted design carries them | 1e-8 |
| Absorption and substrate fit | k = 0.003 and Δn_s = 0.012 recovered; correlation between the films' k reported | 1e-5 |
| Edge filter (LP_550, 33 layers): 1 % rate with TiO₂ Δn and ΔB | recovered by the local fit | 1e-7 |
| Global search (LP_550): 1.5 % rate, both films' Δn, TiO₂ ΔB | recovered (Sobol multistart) | 1e-7 |
| Colour targets under D65, A (2°), F11, D50 (10°) | flat R: a* = b* = 0, L* = 116 R^{1/3} − 16; BBAR_VIS equals the analysis module; D65 and A differ | 1e-9 |
| Field map | its rows equal the single-wavelength field profiles; last boundary = total thickness | 1e-12 |
| One-wavelength GDD target (DM_800, 800 nm) | analysis module's stencil | 1e-5 fs² |
| Batched Jacobian (R, a* and GDD targets) | each row equals a single evaluation of that design | rel 1e-12 |
| Needle optimisation of a broadband AR (TiO₂, SiO₂, MgF₂ films on N-BK7, R ≤ 0.5 % over 400–700 nm) | met from the four-layer start within 30 s; no layer thinner than 1 nm | met |
| Back face linked to the front | the same spectrum as an explicit copy; a plate AR with T ≥ 99 % over 450–650 nm through 2 mm optimised on both faces | 1e-15 / met |

The built-in DM_800 is also checked in test_builtin_coatings.py: its GDD specification by
`coatanalysis.phase`, and every target by the designer.

## Tabulated targets, both faces and the OIC 2019 benchmark (backend/tests/test_coating_examples.py)

Reference: D. Poitras, L. Li, M. R. Jacobson, C. C. Cooksey, "2019 Topical Meeting on Optical Interference
Coatings: Manufacturing Problem Contest", Appl. Opt. 59(5), A31–A39 (2020); target data Figshare
doi:10.6084/m9.figshare.9915800 (CC BY 4.0).

| Benchmark | Reference | Tolerance |
|---|---|---|
| Contest target data | 626 points at 10° (450–1075 nm) and 586 at 50° (480–1065 nm), tolerance 0.01 throughout, as in the contest spreadsheet (MD5 08112d2a8d969a49bf21ef782a3759ba) | exact |
| Tabulated "=" targets weighted by their numbers of points, arbitrary two-sided design on 1 mm N-BK7 | designer merit / 0.01 = MF = √(mean(((Ts − Ts,target)/0.01)²)) (eq. 1 of the paper) recomputed with the analysis module's spectrum code | rel 1e-10 |
| Table validation | wavelengths strictly increasing; fractions within 0…1; the band set from the table | — |
| Two-sided optimisation | layer list front, locked separator, back; batched Jacobian rows equal single evaluations; refinement lowers the merit and changes the back layers | rel 1e-12 / — |
| The library example (Yucca problem, TiO₂/SiO₂ films, both faces) | its stored contest MF recomputed independently; within the contest designs' range (Table 3: MF 0.439–2.14); no layer thinner than 5 nm | rel 1e-9 / ≤ 2.14 |
| /coating-examples and /coating-design/evaluate of the example | one sample per listed wavelength (626 + 586); merit / 0.01 = stored MF | rel 1e-9 |

Result of the stored example (best of eight starts; `python -m opticore.tools.coating_examples 2400 60 50`, which
reached its time limit): MF 0.781 (10°: 0.633, 50°: 0.913; the largest deviation 3.9 % at the band edges), 76 + 56
layers, 5.98 + 4.72 µm, thinnest layer 5.04 nm. The contest's own designs: MF 0.439–2.14 with 74–255 layers and
8.24–17.6 µm (Table 3 of the paper); the organisers' example MF < 5. The other starts reached MF 1.35–2.27, two of the
thickest random starts 7.4 and 15.7 (too few needle steps within the budget).

## Coating design (backend/tests/test_coatdesign.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Spectral solver (absorbing layer, 0°, 30°, 60°, s and p) | `thinfilm.stack_rt` at each wavelength | 1e-13 |
| (HL)²⁰H stack on N-BK7 | peak R = ((1 − Y)/(1 + Y))²; stop-band half width Δg = (2/π) asin((n_H − n_L)/(n_H + n_L)), centred at g = 1 | 1e-6 / 4 % / 0.01 |
| Bare plate with the incoherent back surface | T = 2n/(n² + 1); at 50° per polarisation T = (1 − R)/(1 + R) | rel 1e-12 |
| Long-pass and short-pass templates, refined | every target met (blocking T ≤ 1 %) | met within 0.001 % |
| HR and notch templates | targets met without optimisation | — |
| Fabry–Perot band-pass | transmission peak at λ₀; narrow pass band | 0.05 nm |
| Needle optimisation of a broadband AR (420–680 nm, R ≤ 0.2 %) | met from a 4-layer start; layers added; none < 1 nm; merit never increases | met |
| Locked layers, thickness bounds | unchanged / within bounds | exact |
| Monte Carlo | σ = 0 reproduces the nominal design (yield 1); spread grows with σ; reproducible seed | exact |
| Recipe on a quarter-wave stack | monitor end levels = T of the partial stacks; QWOT at λm = 1; terminations at turning points (zero slope); crystal = d/tooling; time = d/rate | 1e-12 / rel 1e-12 |
| Saved project coating | same R as the design through `thinfilm` | 1e-12 |
| Dispersive palette material | library n(λ) | 1e-13 |
| Validation errors and API | structured errors; all endpoints | — |

## Coatings in the system (backend/tests/test_coatings_system.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Bare metal substrate in the designer | R = ((n − 1)² + k²)/((n + 1)² + k²), T = 0, A = 1 − R | rel 1e-12 |
| Protected mirror (half-wave overcoat) | absentee: R = bare metal at λ₀ | 1e-12 |
| Enhanced mirror | R above bare metal at λ₀; reflectance monitoring forced | — |
| Designed mirror coating on a sequential mirror | traced intensity = designer R | rel 1e-12 |
| Design ↔ project coating | stored design restored exactly; layers-only coating rebuilt with an identical spectrum (31 λ) | exact / 1e-13 |
| Angular curves | Brewster angle atan(n) with Rp < 1e-6; Rs monotonic; 0° equals the spectrum | 0.1° / 1e-15 |
| Surface context on the Cooke triplet | rear surface: n_glass sin θ_glass = sin θ_air (max angle); front surface unchanged | rel 1e-9 / 1e-9° |
| Coatings analysis | bare-surface R = ((n − 1)/(n + 1))² vs λ; coated surface below bare; system transmission estimate vs ray-traced throughput | rel 1e-12 / — / 0.01 |
| Surface-reflectance operand | equals the ghost module's reflectance on the same rays | rel 1e-12 |
| Optimising `coating_scale` and `coat_layer_1` for minimum surface reflectance (detuned AR) | R from > 2 % to < 1.6 % (single-layer quarter-wave limit ~1.3 %); thickness 85–125 nm; original untouched; throughput operand also improves | — |
| Variable validation | layer out of range, duplicate coating variables, built-in coating rejected | — |
| API | all new endpoints | — |

## User-defined, absorbing and mirror coatings (backend/tests/test_coatings_custom.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Bare absorbing interface, normal incidence | R = ((n − 1)² + k²)/((n + 1)² + k²) | rel 1e-13 |
| Bare absorbing interface, 20–85° | textbook complex Fresnel rₛ, rₚ (independent code) | rel 1e-12 |
| Absorbing film on glass | Airy summation of the complex film reflection and transmission; R + T + A = 1, A > 0 (s, p, 0–80°) | rel 1e-12 / 1e-14 |
| Quarter-wave (HL)ᴺH reflector, N = 1, 3, 6 | R = ((1 − Y)/(1 + Y))², Y = (n_H/n_L)²ᴺ n_H²/n_s | rel 1e-12 |
| Dispersive (material) layer | layer index = library n(λ); quarter-wave formula with n(λ) | rel 1e-15 / 1e-12 |
| Coated mirror amplitudes | → ideal mirror (a_s = −1, a_p = +1) as k → ∞; r_s = r_p at normal incidence | 1e-6 / 1e-14 |
| Coated concave mirror in the trace | ray intensity = (R_s + R_p)/2 at each ray's angle; geometry unchanged | rel 1e-12 / 1e-15 |
| 45° fold mirror, polarisation trace | chief-ray diattenuation (|rₛ|² − |rₚ|²)/(|rₛ|² + |rₚ|²); retardance |arg(rₛ/rₚ)| | rel 1e-9 / 1e-9 rad |
| Custom copy of a built-in AR coating | identical system throughput | rel 1e-14 |
| Coating API: custom HR stack, metal mirror in air and behind glass (n₀ = 1.5) | HR formula; R + T + A = 1; bare-metal R | rel 1e-3 (sampled λ) / 1e-12 |
| Reserved/duplicate names, unknown layer material, negative thickness, mirror without substrate, out-of-range material | structured errors and diagnostics | — |
| Project save/load | custom coatings round trip with a valid checksum | exact |

## Glass catalogues (backend/tests/test_agf.py, frontend/src/lib/glassCatalog.test.ts)

| Benchmark | Reference | Tolerance |
|---|---|---|
| AGF Sellmeier-1 glass written from the built-in N-BK7 record | identical indices at 6 wavelengths; nd = 1.5168 (SCHOTT datasheet) | 1e-15 / 2e-5 |
| Every AGF formula number fed with BK7-equivalent coefficients (Schott, Sellmeier 1/3/5, Extended 1/2/3) | imported and verified against its own Nd/Vd | 1e-4 |
| Catalogue formulas reduce exactly to known forms | Extended(A6 = A7 = 0) = Schott; Extended3 reordered = Schott; Sellmeier4(A = 1) and Handbook2(A = 1, D = 0) = Sellmeier; Sellmeier2(A = 0, B2 = 0) = Sellmeier with C in µm | 1e-14 |
| Handbook 1, Conrady, Herzberger at a point | direct evaluation of the documented formula | 1e-15 |
| Schott-formula BK7 coefficients | nd = 1.5168 | 1e-4 |
| Catalogue self-check | wrong Nd flagged (`verified` false); unknown formula, missing CD, duplicate reported | exact |
| Thermal (TD) coefficients | dn/dT model of the record equals the closed form; 1e-6 < dn/dT < 5e-6 /K for BK7 | rel 1e-12 |
| UTF-16 (BOM/no BOM), UTF-8 BOM, Latin-1 decoding; catalogue names from file names | exact | — |
| API: AGF parse, rejection of non-AGF data; ZMX import with catalogue glasses (copied into the project, evaluates identically) | indices equal the built-in N-BK7 | 1e-14 |
| Frontend: name resolution (built-in first, catalogues in name order, shadowed list); embedding of used glasses (surfaces, configuration values, coating layers) on commit and removal on undo; nearest glasses on the nd–Vd map (obsolete and flagged skipped) | exact | — |

## refractiveindex.info catalogues (backend/tests/test_rii.py, frontend/src/lib/rii.test.ts)

| Benchmark | Reference | Tolerance |
|---|---|---|
| `polynomial` formula with the Schott exponents | equals the `schott` formula at 6 wavelengths; n² = A alone | 1e-14 |
| Formula 2 page written from the built-in N-BK7 record | identical indices; dn/dT, density, expansion, dPgF, glass code and status mapped; τ(10 mm) = exp(−4πk d/λ) | 1e-14 / exact / 1e-6 |
| Formula 1 with c₀ ≠ 0; formula 3 with a zero term | direct evaluation of the documented formulas | 1e-14 |
| Tabulated nk page | n at a table point; τ from k | 1e-12 / 1e-6 |
| Self-check and diagnostics | wrong nd flagged; formula 4, invalid YAML and absorption-only pages skipped; infrared glass (no index at F) checked over its range only; duplicate names | exact |
| API `/materials/rii` | SCHOTT N-BK7 summary nd = 1.5168; empty request rejected | 1e-4 |
| Frontend: database index → makers, pages and shelves (duplicates removed, `main/` pages ignored); downloads at the pinned commit with progress and failed pages | exact | — |
| Full database (2026-10-11, manual run) | 1635 of 1636 glasses of the six makers import; every one reproduces its catalogue nd within 1e-4; Vd flags only where the catalogue rounds Vd (SUMITA, SCHOTT BOROFLOAT33) | 1e-4 / max(0.05, 0.1 %) |

## Ideal lenses, image-height fields, object-space telecentric (backend/tests/test_ideal_fields.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Ideal lens f = 100 mm, object at infinity, fields 0/10/20° | every ray lands at y = f tan θ; EFL = BFL = 100; Seidel sums 0 | 1e-10 mm / 1e-12 |
| Wavefront of the ideal lens at its design conjugate | RMS < 1e-7 waves, PV < 1e-6 waves at every field | — |
| Finite conjugate s = 300 mm | image at s' = 150 mm, heights −h/2, paraxial m = −0.5; OPD residual > 1e-3 waves with the infinity setting, < 1e-7 waves with ideal_object_distance = 300 | 1e-10 mm |
| Two ideal lenses f1 = 100, f2 = 50, d = 30 | EFL = f1 f2/(f1 + f2 − d), BFL = f2(f1 − d)/(f1 + f2 − d); off-axis image height = EFL tan θ | 1e-10 / 1e-9 mm |
| Ideal lens after a fold mirror (light towards −z) | EFL 80 mm; rays converge (spot extent) | 1e-9 mm |
| Validation | mirror ideal lens and different media refused | — |
| Real image-height fields (singlet) | chief ray lands at the requested (x, y) | 1e-8 mm |
| Image height of an ideal lens | object angle = atan(h/f) (real and paraxial types) | 1e-9 deg |
| Paraxial image-height fields | paraxial image height = requested | 1e-10 mm |
| Unreachable image height (TIR at a steep exit surface) | `FIELD_UNREACHABLE` error; reachable heights solved | — |
| 4f ideal relay, stop in the common focal plane, NA 0.05 | chief ray parallel to the axis, through the stop centre; image height −h; edge-ray direction cosine 0.05; paraxial NA 0.05, m = −1, stop radius 100 tan(asin 0.05), EP at infinity | 1e-12 |
| Telecentric validation | EPD aperture and angle fields refused; unflagged telecentric system raises `TELECENTRIC_EP` | — |
| Telecentric with image-height fields | chief ray lands at the requested height | 1e-9 mm |
| `ideal_power` variable | EFL target 125 mm reached; curvature variable on an ideal lens refused | rel 1e-6 |
| Non-sequential trace refuses ideal lenses; evaluation reports is_ideal / focal_length, `TELECENTRIC` / `TELECENTRIC_STOP` | — | — |
| ZMX `PARAXIAL` surface and FTYP 3 (real image height) fields | ideal lens f = 50 (EFL 50); chief ray at 4 mm | 1e-12 / 1e-8 mm |

## Multiple configurations (backend/tests/test_configs.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Active configuration applied on compile; base untouched; idempotent | — | exact |
| Two conjugates (∞ and 500 mm) | image shift f²/(s − f) (Newton) between the paraxial image distances | rel 1e-9 |
| Material, aperture and semi-diameter rows | index, EPD and fixed aperture change per configuration | exact |
| Invalid tables (length, unknown surface, duplicate row, empty material, system row with surface, R = 0, active out of range) | rejected | — |
| Configuration that invalidates the system; solve/configuration conflict | structured `CONFIG_INVALID` / `SystemError_` | — |
| Operands per configuration | identical to the same operand on the single-configuration system | rel 1e-12 |
| Per-configuration variables (thickness; curvature ↔ radius row) | read/write the table, original unmodified | exact |
| Variable validation | base variable on a per-configuration parameter, missing row, configuration index out of range | rejected |
| Optimisation of both back foci from a defocused start | reaches the frozen per-configuration optimum | 2e-3 mm |
| Frozen two-conjugate sample | is at its optimum (no further improvement) | rel 1e-3 |
| Tolerancing | analyses the active configuration with its values baked in | exact |
| Project round trip, evaluate API `configuration` | — | exact |

## Solves and pickups (backend/tests/test_solves.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Marginal-height solve h = 0 | thickness = paraxial BFL, image defocus 0 | rel 1e-13 / 1e-10 mm |
| Marginal-height target h, pupil zone | marginal ray height h at the next surface; zone-independent for h = 0 | rel 1e-12 |
| F-number solve + focus solve (infinite object) | working F/# = target, EFL = F·EPD, defocus 0 | rel 1e-12 |
| Marginal-angle solve on a concave mirror | R = −2y/(2u′) for a collimated ray at height y (n′ = −n) | rel 1e-12 |
| Chief-height solve | chief ray crosses the axis at the next surface (exit pupil) | 1e-12 mm |
| Thickness and radius pickups | follow the source (scale, offset); plane stays plane | exact |
| Solve before the stop (pupil-dependent) | converges; target height reached | rel 1e-10 |
| Undefined solve (collimated ray) | `SOLVE_FAILED`, stored value kept | — |
| Invalid solves | structured `SystemError_` | — |
| Variable on a solved parameter | rejected | — |
| Optimisation with a focus solve | EFL target met, image stays at paraxial focus | rel 1e-6 / 1e-9 mm |
| Tolerancing | solves frozen at nominal values | exact |
| Project round trip and evaluate API `solved` | — | rel 1e-12 |

## Biconic surfaces (backend/tests/test_biconic.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| cₓ = c_y, kₓ = k_y | intersections and normals equal to the standard conic | 1e-12 |
| Random rays on a biconic | intersection on the surface; normals equal the finite-difference gradient | 1e-11 / 1e-8 |
| x-fan and y-fan | each equals the meridional fan of a standard lens with that section's radius and conic; paraxial EFL follows the y section | 1e-12 / rel 1e-13 |
| Cylinder lens (cₓ = 0) | collimated x-fan undeviated; EFL = R/(n − 1) | 1e-12 |
| Edge thickness, aperture domain | both sections checked | rel 1e-12 |
| Variables `curvature_x`, `conic_x`; CAD export | read/write; rejected on non-biconic surfaces; export skipped with reason | exact |

## Zernike sag surfaces (backend/tests/test_zernike.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Monomial expansion of Z1…Z37 | polar definition R_n^m(ρ) cos/sin(mθ) (wavefront module) | 1e-11 |
| Defocus term Z4 on a plane | paraboloid c = 4A₄/R², k = −1: intersections, normals, vertex curvatures | 1e-12 / rel 1e-14 |
| Astigmatism Z5 on a plane | parabolic biconic c_x = −c_y = 2A₅/R² | 1e-12 |
| Z4 + Z9 combination | even asphere A4 r⁴ (A4 R⁴/2 · Z4 + A4 R⁴/6 · Z9): image points and OPL for two fields; EFL | 1e-11 / 1e-10 / rel 1e-13 |
| Random 37-term freeform | intersection on the surface; normals equal the finite-difference gradient; vertex at the origin | 1e-11 / 1e-7 / 1e-15 |
| Vertex curvature, tilt | c_base + 2(2A₄ − 6A₉)/R²; Z3 plane normal; diagnostics | rel 1e-14 / 1e-15 |
| Edge thickness with strong coma | minimum over 3 601 rim azimuths | 2e-4 mm |
| Checks | curvature solve, > 37 terms, terms on a standard surface, extrapolation beyond R, CAD export skipped, evaluate output | — |
| Optimisation with `zern_9` | RMS spot reduced > 5×; result applied to a copy | — |
| Project save/load | terms and radius round trip with a valid checksum | exact |

## Diffractive surfaces (backend/tests/test_diffractive.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Transmission grating at normal incidence (300–1200 l/mm, orders −1, 1, 2) | sin θₘ = m λ f | 1e-13 |
| Grating at 20° incidence into N-BK7 | n sin θₘ − sin θᵢ = m λ f | 1e-13 |
| Reflection grating in Littrow (1200 l/mm) | 2 sin θ = m λ f; ray returns along the incident direction | 1e-12 |
| Order 0 vs no grating; λf > 1 | identical directions; `EVANESCENT` status | 1e-15 / exact |
| Diffractive lens EFL, wavelength scaling, order 2 | f = −πR²/(mλA₁); f ∝ 1/λ; f/2 | rel 1e-12 |
| Ideal diffractive lens (series of −(2π/λ)(√(r²+f²) − f)) | on-axis focus; flat wavefront from the OPL phase term | 1e-6 mm / 1e-3 waves RMS |
| Chromatic focal shift of a diffractive lens | f(λ) = f₀λ₀/λ | rel 1e-10 |
| Hybrid achromat: optimise A₁ on a BK7 singlet for zero F−C focal shift | thin-lens condition (n_F − n_C)(c₁ − c₂) = (λ_F − λ_C)A₁/(πR²) | 1e-7 mm; A₁ within 2 % (1 mm thick lens) |
| Fresnel loss on a diffractive interface; variables on coordinate breaks | between single- and two-surface loss; rejected | — |

## CAD lens/mirror recognition (backend/tests/test_recognize.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Singlet, cemented achromat and Cooke triplet exported to STEP | radii (rel 1e-10), thicknesses (1e-9 mm), element count; after insertion the EFL equals the original | rel 1e-11 |
| Foreign STEP lens built from true spherical faces (Boolean intersection) | R1, R2 exact, thickness, clear aperture; thick-lens power (n−1)(1/R1 − 1/R2 + (n−1)t/(n R1 R2)) | rel 1e-10 / 1e-11 |
| Conic + even-asphere element | fitted sag within 2e-6 mm of the exact sag; EFL | rel 1e-6 |
| Spherical mirror | R exact; inserted mirror EFL 100 mm, paraxial focus solve −100 mm | rel 1e-9 |
| Decentred and tilted part (CAD placement) | inserted surface frame origin and axis equal the CAD vertex and axis; image unchanged | 1e-9 |
| Axis placement | gap, downstream positions kept; insufficient space rejected | exact |
| Lens mount (ring) / STL asset | rejected with a reason | — |
| API (recognise, insert, invalid material / index) | — | — |

## Non-sequential tracing (backend/tests/test_nonseq.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Singlet and Cooke triplet as solids, without splitting | detected power and RMS spot equal to the sequential trace with Fresnel losses | rel 1e-9 / 1e-8 |
| Energy conservation with ghost splitting | budget sums to 1; stray light reaches the image | 1e-12 |
| Absorber covering y > 0 | absorbed = blocked ray fraction; detected = sequential power of the passing rays | rel 1e-12 / 1e-9 |
| N-BK7 window, multiple reflections | direct (1−R)², after reflections (1−R)²R²/(1−R²), back-escaped R + (1−R)²R/(1−R²) | rel 1e-12 / 1e-6 |
| Right-angle prism | TIR turns the beam by 90°, power (1−R)² | rel 1e-9 / 1e-9 |
| CAD mirror at 45° | beam folded out of the detector, ideal reflection | 1e-12 |
| Refractive role without material; STL absorber | structured error; faceted note; absorbs | — |
| API | — | — |

## Light sources and detectors (backend/tests/test_ns_sources.py, frontend/src/lib/sources.test.ts)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Point source onto a coaxial disc (a = 6, d = 10 mm) | Lambertian sin²θ; isotropic (1 − cos θ)/2; cone 40° (1 − cos θ)/(1 − cos θm); cos³ 1 − cos⁴θ; watts = power × fraction; budget = 1 | 4 binomial σ (N = 20 000) / 1e-12 |
| Acceptance angle 20° on a large detector next to a Lambertian point | accepted sin²α, rest rejected and in the budget; no accepted power beyond 20° | 4σ / 1e-9 |
| Gaussian-beam ray ensemble (w0 = 5.2 µm, λ = 1.55 µm) at z = 0, zR/2, 2 zR, 20 zR | 2σ widths = w0 √(1 + (z/zR)²) in x and y; monitors see all rays and do not stop them | 2.5 % (N = 40 000) |
| Gaussian waist imaged 2f–2f by a slow lens | 2σ width at the paraxial image plane = |m| w0 (ABCD with B = 0) | 3 % |
| Monitor + absorbing detector; two-wavelength source (weights 1 : 3) | both see 100 %; power by wavelength 0.25 / 0.75 W exactly (largest remainder split) | 1e-12 |
| One-sided detector facing away; two-sided | back power blocked; two-sided receives 100 % | exact |
| Collimated 4 × 2 mm rectangle (8 W) onto a 2 × 2 mm detector | fraction 0.5; uniform irradiance 1 W/mm² | 4σ / 2 % |
| Isotropic sphere-volume source seen from 100 mm | ≈ point-source fraction; rotated collimated source along +x hits a rotated detector | 4σ / exact |
| Tabulated I(θ) = cos θ | equals the Lambertian fraction | 4σ + 2e-3 |
| Validation and reproducibility | bad tables refused; same seed identical, other seed different | exact |
| System-field source through a bare N-BK7 singlet onto a 1 mm sensor at the image | 88–94 % (two Fresnel losses); budget = 1 | — / 1e-9 |
| API and project round trip | detector fraction; disabled sources fall back to the system field; sources/detectors stored in the project; unknown field rejected | — |
| Gaussian relay (test system in `tests/beam_systems.py`: two AR-coated plano-convex N-BK7 lenses, f = 25 mm, 1.064 µm) | m = −1 and image on the detector (paraxial); collimated 1/e² radius f tan θ; detector power (1 − R)⁴ with R the AR_1064 reflectance from the thin-film model; spot 2σ < 100 µm | 1e-4 / 5 % / 0.02 |
| Thick lens (test system: N-SF11, R = ±2.5 mm, 2.8 mm thick, source and detector 9 mm apart, 1.55 µm) | EFL and back focal distance equal the thick-lens formulas; the shortest real conjugate 2(f + BFL) exceeds the 6.2 mm of air (the image lies behind the detector); > 99 % on the detector, > 99.9 % through the lens | rel 1e-9 / — |
| Frontend | defaults equal the engine defaults; editor summaries; older projects get empty lists | exact |

## Direct-path detector trace and detector operands (backend/tests/test_nsdirect.py, frontend/src/lib/sources.test.ts)

| Benchmark | Reference | Tolerance |
|---|---|---|
| The three beam test systems (relay, thick lens, singlet; `tests/beam_systems.py`) | detector fractions, centroids and 2σ widths equal the full non-sequential trace without splitting (independent per-ray B-rep trace, same seeded rays) | 1e-12 / 1e-9 rel |
| Collimated uniform disc through a plane N-BK7 window | power = T² with T = 1 − ((n − 1)/(n + 1))²; plane D4σ = disc diameter 2a | 1e-12 / 3 % (N = 4000) |
| Aperture, blocking and sides | 75 % of a disc of radius 2 mm lost at a 1 mm aperture; monitor = absorber behind it; nothing behind an absorber; a turned one-sided absorber blocks and records nothing | 0.03 / exact |
| Anchored placements | object surface at −d₀, image surface at its vertex plus the offset; rotation composed with a 30° coordinate-break frame; unknown anchor rejected; frontend: same composition, re-anchoring keeps the global pose, Euler XYZ round trip | 1e-12 / 1e-9 |
| Source wavelength outside the system wavelengths | identical to a system that contains the wavelength | 1e-12 rel |
| Detector operands | equal the direct-path result; missing source or detector is a configuration error; API merit and start | 1e-12 |
| Optimisation of the source distance of the thick-lens test system (a pickup keeps 9 mm) | from 1.0 mm and 3.4 mm to the two distances with D4σ = 120 µm, found independently by root finding on the direct trace (2.3924 and 3.9343 mm), with > 99 % on the detector | 2e-3 mm / 1e-4 mm |
| Detector anchored to the image surface (crossed at the vertex shared by two path segments), source distance 2.15–2.30 mm in 31 steps | every ray crosses the plane once; the power varies only with the Fresnel losses; at 2.2138 mm equal to the full trace. Rounding had dropped such crossings: 2 % of the power vanished unreported there, and the optimiser stalled | exact / 1e-5 / 1e-12 |

## Scattering and coatings in non-sequential mode (backend/tests/test_nonseq_scatter.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Lambertian sampler (40 000 draws, tilted normal) | E[cos θ] = 2/3; P(θ < t) = sin²t at 20°, 45°, 70°; isotropic azimuth | 4 standard errors |
| Gaussian sampler (σ = 1.5°) | RMS polar angle √2 σ, mean σ√(π/2); no directions into the surface at 88° specular | rel 2 % / exact |
| Lambertian plate (ρ = 1) seen by a coaxial annular detector | view factor F = a²/(a² + h²) − b²/(b² + h²) (differential area to parallel annulus) | 4 Monte Carlo standard errors (12 000 rays) |
| Partially diffuse baffle (ρ = 0.04) | absorbed 0.96, scattered 0.04 of the intercepted power; budget = 1 | rel 1e-12 |
| Forward-scattering N-BK7 window (f = 0.2, σ = 1°) | direct = T²(1 − f)²; after scattering = T²(1 − (1 − f)²) | rel 1e-12 / 2e-4 |
| Scattering 45° mirror | specular part folded by exactly 90°; scattered power = f | 1e-9 / rel 1e-12 |
| Same seed / different seed | identical / different results | exact |
| Singlet with an absorbing AR coating | direct power equal to the coated sequential trace; coating absorption > 0 | rel 1e-9 |
| Fold-mirror sample with a coated metal mirror | direct power equal to the sequential trace (mirror reflections are nominal, not ghosts) | rel 1e-9 |
| AR-coated CAD window | direct = T_coat² (reciprocity of the oriented stack) | rel 1e-12 |
| Unknown coating, mirror coating without substrate, scatter fraction > 1 | structured errors and notes | — |
| API seed and scatter fields | reproducible; model echoed | exact |

## CAD assemblies, measurements and sections (backend/tests/test_cad_assembly.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Nested STEP assembly written with XCAF (plate + sub-assembly of 2 post instances) | names, kinds, colour, volumes 200 mm³ and π·3²·5 mm³ per post, sums; instance locations (z 12–17, centres x = 2 and 8) | rel 1e-9 / 1e-6 / 1e-6 mm |
| Per-node triangle ranges | contiguous, nested in the parent range, covering the whole mesh | exact |
| Hidden parts and inherited role overrides | hidden subtree excluded; nearest override on the path | exact |
| Non-sequential tracing of an assembly | only the part with an absorber role absorbs (half the beam); hiding it and overriding the other part swaps the result; budget = 1 | 0.06 / 1e-12 |
| Exact point snapping with model placement | picked points move onto the exact face (z = 2, offset 0.04 mm; a point inside the solid: 1 mm) | 1e-9 |
| Clearance plate ↔ post and plate ↔ sub-assembly | 10 mm with closest points at z = 2 and 12 | 1e-9 |
| Interference (post sunk 1 mm into the plate) | distance 0, common volume π·3²·1 mm³ | 1e-9 / rel 1e-6 |
| Plane sections | plate perimeter 2(10 + 2); post chord 2√(3² − 2²) + height; parts the plane misses and hidden parts are absent; STL cube perimeter 4·5 | rel 1e-6 / 1e-9 |
| API | measure, clearance (invalid part rejected), section, import with tree | — |

## STEP/IGES export and import (backend/tests/test_cad.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Plano-convex singlet solid | closed-form volume π h² (t − s) + π s² (3R − s)/3 | rel 1e-9 |
| Achromat and Cooke triplet elements | numerical integral ∫2πr (z_back − z_front) dr of the exact sags | rel 1e-9 |
| Conic + even-asphere element | B-spline profile deviation from the exact sag < 1e-6 mm; volume vs integral | rel 1e-7 |
| STEP and IGES round trip (triplet) | names and volumes of all lens solids preserved; stop and rays present | rel 1e-7 |
| Folded system | mirror solid contains its global vertex | 1e-6 mm |
| External STEP box (written by the kernel directly) | volume 6000 mm³, area 2200 mm², size 10 × 20 × 30 | rel 1e-9 |
| CAD models in the export | STL cube sewn to a 1000 mm³ solid at its placement; hidden models excluded; STEP model re-exported from its source | rel 1e-6 |
| Unbuildable element (rim beyond the sphere) | skipped with reason; empty export refused | — |
| Invalid / unsupported files, API | structured errors (422) | — |

## STL import (backend/tests/test_stl.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Cube a = 12.5 mm, binary and ASCII | 12 triangles, 8 vertices, area 6a², volume a³, closed, size a | rel 1e-6 (float32) |
| Unit scaling (inches) | size 50.8 mm, volume (50.8)³ | rel 1e-6 |
| Inward winding / open mesh / degenerate triangle / contradicting facet normals | negative volume + diagnostic / no volume + `OPEN_MESH` / counted / `NORMALS_DISAGREE` (winding wins) | exact |
| Binary header starting with "solid" | detected as binary by size | exact |
| Truncated binary, two-vertex ASCII facet, garbage | structured `StlError` | — |
| Mesh round trip and project schema | decoded mesh reproduces the area; invalid counts and out-of-range indices rejected on load | rel 1e-6 |
| API (units, 422 on invalid data) | — | — |

## Ghost analysis (backend/tests/test_ghosts.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Plane window in a collimated beam before a singlet | E_ghost / E_main = R², with R = ((n−1)/(n+1))²; reflectances at normal incidence = R | rel 1e-10 |
| Window ghost | focuses at the main paraxial focus; footprint RMS equals the main spot RMS | 1e-9 mm / rel 1e-9 |
| Quarter-wave-coated window | ghost/main ratio = R_coat² (thin-film R at the face) | rel 1e-10 |
| Singlet ghost (S2 → S1) | paraxial ghost focus from an independent reduced ABCD product with signed indices | rel 1e-10 |
| Cooke triplet | 15 ghost pairs (stop in air has no index step); ghost-system thickness signs; ranking; E ≤ R_i R_j | exact |
| Mirror systems | structured error | — |
| API | — | — |

## Polarisation ray tracing (backend/tests/test_polarization.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Tilted plane interface (0–75°), N-BK7 | \|J_xx\|² = Ts, \|J_yy\|² = Tp (Fresnel); no cross-coupling; unpolarised T = (Ts + Tp)/2; zero retardance | rel 1e-12 |
| Brewster angle | Tp = 1, diattenuation = (1 − Ts)/(1 + Ts) | 1e-12 |
| Tilted plane-parallel plate | Ts², Tp² | rel 1e-12 |
| Ideal mirror, normal incidence | P E = −E; lossless, non-diattenuating | 1e-12 |
| Coated tilted interface (V-coat, 40°) | power = thin-film Ts, Tp; retardance = \|arg(t̃_p / t̃_s)\| (non-zero) | rel 1e-12 |
| Empty-stack amplitudes | Fresnel ts, tp (power) and rs | 1e-14 |
| Achromat, axial chief ray | unpolarised T = scalar Fresnel throughput | rel 1e-12 |
| Singlet Jones pupil | invariant under a 90° pupil rotation (diattenuation, retardance); zero linear retardance for uncoated glass, non-zero basis rotation; x-input on the x axis = y-input on the y axis | rel 1e-9 / 1e-12 |
| Jones decomposition | known diattenuator/retarder (also rotated), pure rotator, retarder + rotator | rel 1e-10 |
| API (`/analysis/polarization`, invalid input state → 422) | — | — |

## Focus status (backend/tests/test_focus.py)

The best polychromatic RMS focus is computed in closed form: after the last
surface every ray is straight, so the centroid-referenced RMS² on a plane
displaced by δ along the image normal is a quadratic A + 2Bδ + Cδ², minimised
at δ* = −B/C (`analysis/focus.py`).

| Benchmark | Reference | Tolerance |
|---|---|---|
| Ideal lens, image surface displaced by +0.5 and −0.8 mm | best focus at the focal plane (δ* = −d), best RMS 0 | 1e-9 mm / 1e-4 µm |
| Plano-convex singlet and optimised Cooke triplet | current RMS = spot diagram (field-weighted); RMS at δ* = spot diagram with the image distance moved by δ*; RMS at δ* ± step larger | rel 1e-9 / 1e-8 |
| Per-field RMS and the largest field RMS | spot diagram per field | rel 1e-9 |
| After refocusing by δ* | reported at best focus | exact |

## First-lens starting prescriptions (backend/tests/test_first_lens.py)

`design.py` builds the guided *First lens*: a best-form singlet or a cemented
thin-lens achromat, made thick and scaled to the exact focal length.

| Benchmark | Reference | Tolerance |
|---|---|---|
| Thick-lens EFL, singlet and doublet, f = 50/100/250 mm, F/4–F/8, field 0–10° | requested focal length (exact paraxial trace) | rel 1e-10 |
| Aperture and image position | EPD = f/N; image at the paraxial focus | 1e-12 / 1e-9 f |
| Edge thickness of every element | at least the stated minimum at the clear semi-diameter | 1e-6 mm |
| Singlet shape factor | Coddington best form q = 2(n²−1)/(n+2) | rel 1e-12 |
| Best form minimises S_I | bending ±0.002 and ±0.004 mm⁻¹ (same power) increases \|S_I\|; a plano-convex lens of the same power has more | strict |
| Achromat powers | φ1 + φ2 = φ, φ1/V1 + φ2/V2 = 0 | 1e-14 |
| Thick doublet axial colour (F − C) | below 5 % of the same-focal-length singlet | — |
| Invalid requests (crown V ≤ flint V, one wavelength for a doublet, unknown glass, aperture too large), API 422 | rejected | — |

## Fibre modes (backend/tests/test_wave.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| LP modes at V = 2.3 and 2.5 | LP11 exists iff V > j₀,₁ = 2.404826; roots satisfy the LP equation; n₂ < n_eff < n₁; single-mode exactly below λc | 1e-9 |
| Vector modes at V = 4 | every root satisfies Snitzer's equation in its original form; HE11 → LP01 and TE01, HE21, TM01 → LP11 within 10⁻³ (n₁ − n₂); order TE01 > HE21 > TM01; vector degeneracies sum to the LP count (12) | 1e-7 rel / exact |
| Cut-off of TE01/TM01 | below V = 2.405 only HE11 | exact |
| Glass rod in air (n = 1.5/1.0) | strongly guiding HE11 solves Snitzer's equation and differs from LP01 | 1e-6 |
| LP01 mode field diameter, V = 1.6 to 2.4 | best-overlap Gaussian = Marcuse's formula; overlap > 0.97 (V < 2) / 0.99 | 1.5 % |

## Fibre profiles, dispersion and cross-sections (backend/tests/test_fibre_profiles.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Step index (a 5 µm, 1.46/1.45, 1 µm): transfer method; finite differences | exact LP eigenvalue equation (fibermodes.py) | 1e-13; 5e-11 in n_eff |
| LP11 and LP21 cut-off of the step profile | V = j₀,₁ = 2.404826 and j₁,₁ = 3.831706 | 1e-10 rel |
| Parabolic profile (a 25 µm, Δn 0.0137, 0.85 µm), mode groups M ≤ 5 | infinite parabola, β² = k² n₁² − 2 k M NA/a | 2e-11 |
| Parabolic LP01 MFD and effective area | 2√2 a/√V and 2π a²/V | 1e-8 rel |
| Parabolic group index and D (LP01 at 0.85 and 1.3 µm, LP11) | the infinite parabola's analytic β(k) | 1e-10; 2e-5 ps/(nm·km) |
| Mode count of the parabolic fibre | V²/4 | 3 % |
| W profile (three rings) at 1.0 and 1.55 µm | transfer method against finite differences | 2e-11 |
| W profile LP11 cut-off | exact layer solutions against the integrated radial equation; LP11 present 0.1 % below and absent 0.1 % above | 1e-11 µm |
| 1 mm cores (step and graded) | no LP11 cut-off in 0.05–50 µm | exact |
| Material dispersion of fused silica (1.31, 1.55 µm) | analytic second derivative of Malitson's formula | 1e-4 ps/(nm·km) |
| Rod n 1.45 in 1.40, a = λ = 1 µm, cross-section solver | exact vector HE11 (Snitzer's equation): mesh 0.025 µm; Richardson from 0.05/0.025 µm | 1e-6; 3e-7 |
| API: graded and layered modes, dispersion, an invalid ring table (422) | — | — |

Library examples (backend/tests/test_fibre_examples.py). Each one runs its
stored settings as the view sends them and is checked against an
independent calculation:

| Example | Reference | Tolerance |
|---|---|---|
| Single-mode step fibre (a 4.1 µm, Δn 0.0052 over fused silica, 1550 nm) | LP01: exact LP equation and the transfer method; cut-off: V(λ) = j₀,₁ with the cladding's dispersion; MFD, A_eff, core fraction: adaptive quadrature of J₀/K₀; D and n_g at 1.31 and 1.55 µm: seven-point stencil (h = 10⁻³ λ) of the exact LP eigenvalue; the zero-dispersion wavelength likewise; material part: Malitson | 1e-13; 1e-10 µm; 1e-8 rel; 2e-3 ps/(nm·km) and 1e-9; 2e-5 µm; 1e-4 |
| Graded 50/125 (α = 2, NA 0.2, 850 nm) | infinite parabola (M ≤ 5), MFD, A_eff; LP11 cut-off V_c from Kummer's function, ψ = x e^(−V x²/2) M(1 − V/4, 2, V x²) with x ψ′/ψ = −1 at x = 1: V_c = 3.518; the note that the cut-off (11.4 µm) lies outside the silica data | 2e-11; 1e-8 rel; 1e-9 rel |
| Trench-assisted (4 / 9 / 14 µm, +0.005 / 0 / −0.005, 1550 nm) | finite differences: modes, field quantities (Richardson), D at 1.55 µm on a wider stencil (h = 4·10⁻³ λ); integrated radial equation: cut-off | 2e-11; 2e-8 rel; 0.02 ps/(nm·km); 1e-11 µm |
| Six-hole microstructured fibre (Λ 6.75 µm, d 5 µm, n 1.45, 1.45 µm; meshes 0.1/0.05 µm, PML 3 µm, Richardson) | multipole method: n_eff = 1.445395345 + 3.15·10⁻⁸ i (White et al., JOSA B 19, 2322 (2002), tabulated by Guo et al., Opt. Express 12, 3341 (2004)) | 5e-7 (result −1.75·10⁻⁷); 2 % in κ (result +0.4 %) |
| The frontend's requests for the examples (fixture `fibre_examples.json`) | `samples.fibre_request` | exact |

## Photometry and colorimetry (backend/tests/test_photometry.py, test_lighting_examples.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| The CIE datasets | MD5 sums from the CIE's metadata; table sizes | exact |
| K_m V(555.016 nm), K′_m V′(555.016 nm) | 683 lm/W (the candela); V(555) = V′(507) = 1 | 2e-3; 0.05 lm/W |
| Illuminant A from its formula | x, y = 0.44757, 0.40745 (CIE 015); CCT = 2848 × 1.4388/1.435 K on the locus (Duv 0) | 2e-5; 1e-4 K, 1e-9 |
| D65 table | x, y = 0.31271, 0.32902 (CIE 015); the CCT of that chromaticity ≈ 6504 K, Duv 0.0032 | 2e-5; 1 K, 2e-4 |
| Equal-energy spectrum | x = y = 1/3 | 5e-5 |
| Planckian radiators 1500–25 000 K | CCT = T, Duv = 0 | 1e-7 rel, 1e-9 |
| A point 0.01 along the locus normal at 4000 K (and −0.01, 0.06) | Duv = ±0.01 with the same CCT; no CCT beyond 0.05 | 1e-7, 1e-3 K |
| sRGB matrix | IEC 61966-2-1 matrix; D65 → (1, 1, 1); the transfer function at 0.0031308 | 1e-3; 1e-12; 1e-5 |
| 1 W at 555 nm; 2 W at 507 nm (scotopic); 1550 nm | 683.002 lm; 3400.26 lm; 0 lm with a note | 1e-9 |

Library examples, run as the Non-Sequential view runs them:

| Example | Reference | Tolerance |
|---|---|---|
| LED downlight: white LED (blue line + phosphor, 3 W, Lambertian Ø2 mm) 2 m above a 3 × 3 m work plane and a Ø600 mm desk (monitor), 200 000 rays | source flux and colour from its stored spectrum (CIE tables read in the test); flux on the plane = Φ × view factor of a Lambertian emitter to a centred parallel rectangle; on the desk = Φ ρ²/(ρ² + h²); the plane's x, y and CCT equal the source's; the detector's numbers from its detected spectrum | 1e-12; 4σ (σ < 2 %); 4σ; 4σ; 1e-9 |
| Additive colour mixing: three collimated monochromatic 60 mm beams (630, 532, 465 nm) on a 120 mm screen, 24 × 24 pixels | in each of the seven regions: chromaticity and illuminance from the beams' powers and areas (single colours exactly on the spectral locus, mixtures within 4σ of Poisson counts); the illuminance map = K_m Y; the image = the sRGB encoding of the X, Y, Z maps; all light on the screen | 1e-12 / 4σ; 1e-12; 1 level; 1e-9 |

Found while building the examples. All three were fixed and are in
tests/test_robustness.py:
* The image simulation of a system with only an on-axis field divided by zero
  (HTTP 500). It now says it does not apply: the largest field sets its
  scale.
* The vector PSF of a system with a collimated image space reported a system
  error. It now says it does not apply (no focus), like the other diffraction
  analyses.
* The chromatic focal shift of such a system returned empty values. It now
  says it does not apply.
* POP of a beam that cannot be sampled at the target is now reported as not
  applicable, with the same advice.

## Gratings: RCWA (backend/tests/test_rcwa.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Uniform layers (0.12 µm of 2.1, 0.2 µm of 1.38 + 0.05i, on 1.52) at 0°, 35°, 70°, TE and TM | thin-film transfer matrix (thinfilm.py) | 1e-12 |
| Lossless lamellar grating (TE, TM), conical incidence, sliced sinusoid | Σ R + Σ T = 1 | 1e-12 |
| Symmetric profile at normal incidence | η_m = η_−m | 1e-12 |
| Absorbing blazed grating (n 2 + 0.1i, 30 slices) at 15°, three reflected orders | Rayleigh reciprocity: R_m(k_x) = R_m(−k_x,m) | 2e-6 |
| Blazed fused-silica grating (period 10 µm, 2π step, 40 slices) thick at +x | scalar theory: the light goes to the +1 order (a prism deflects towards its base), > 90 % of the transmitted light and > 100 × the −1 order; the mirrored profile at the mirrored angle gives the mirrored orders (0° and 12°, TM) | — ; 1e-10 |
| Order angles | the grating equation | 1e-12 |
| Lamellar grating of period λ/40 (1.5/air, 0.3 µm), TE and TM | a film of the zeroth-order effective-medium index | 1e-4 in R |
| TM convergence (Li's rule): dielectric grating at M = 40 and 80; metallic grating at M = 20, 40, 80 | change < 2e-5; monotone convergence | — |
| API: trapezoid profile, angle sweep, unpolarised retardance, convergence estimate; a lossy incident medium refused; every grating example a valid request | — | — |

Library examples:

| Example | Reference | Tolerance |
|---|---|---|
| Binary phase grating (fused silica, period 20 µm, 50 % fill, half-wave depth, 633 nm, M = 60) | scalar theory: 4/π² in ±1 and 4/(9π²) in ±3 of the transmitted light, nothing in the zeroth order | 1 % rel; 2e-3 |
| Form-birefringent quarter-wave plate (fused silica, period 0.2 µm, 1.9 µm deep) | 90° retardance; only the zeroth order propagates; for periods λ/16, λ/32, λ/64 the retardance approaches the effective-medium film's, the error halving with the period (first order: the evanescent orders at the two interfaces) | 1°; ratio 1.6–2.2, < 0.07° at λ/64 |
| Guided-mode resonance filter (50 nm grating of index 2.0, period 0.45 µm, on 120 nm of 2.0 over fused silica) | a lossless grating with only the zeroth order propagating reflects completely at resonance (transmission zero < 1e-8); the resonance at period × n_eff of the slab's TE0 mode (grating layer as its TE effective medium; transfer-matrix mode solver in the test) | 0.2 % |

## Crossed gratings and metasurfaces: 2D RCWA (backend/tests/test_rcwa2d.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Structures invariant in y (lamellar, absorbing 12-slice sawtooth, metal) at 10° TE and TM and at 20°/30° conical | the 1D solver (rcwa.py), order by order; orders q ≠ 0 empty | 1e-12; 1e-20 |
| Lines along x | the 1D solver turned by 90° | 1e-12 |
| Two uniform layers (one absorbing) at 35°, TE and TM | thin-film transfer matrix | 1e-12 |
| Lossless rotated ellipse and rectangle | Σ R + Σ T = 1 | 1e-12 |
| The same structure and plane of incidence turned by 90° | the order maps turned | 1e-12 |
| Centred hole at normal incidence | TE and TM maps are each other turned (C4) | 1e-12 |
| Absorbing rotated ellipse (no symmetry), unpolarised, M = 6 | reciprocity: R_mq(k) = R_mq(−k_mq) | 2e-5 |
| The pattern translated across the cell edge | efficiencies unchanged | 1e-12 |
| Overlapping shapes, a shape larger than the period, too many orders | refused; a touching checkerboard accepted | — |
| API: (m, q) orders with directions, cross-polarisation, structure, sweep of (m, q), 1D profiles as stripes, refusals before any pool run | — | — |

Library examples:

| Example | Reference | Tolerance |
|---|---|---|
| Checkerboard fan-out grating (fused silica, period 20 µm, half-wave depth, 633 nm, M = 10 × 10) | scalar theory, the product of two binary gratings: 16/π⁴ in each (±1, ±1) and 16/(9π⁴) in (±1, ±3), (±3, ±1) of the transmitted light; orders with m + q odd vanish (the pattern is invariant under the half-diagonal shift); the zeroth order (scalar: zero) below 1 % and falling with the harmonics (the touching corners converge slowly; the view flags this) | 0.3 %; 2 %; 1e-20 |
| Subwavelength checkerboard antireflection (fused silica and air, period 0.16 µm, depth λ/(4√n)) | Dykhne's theorem: a checkerboard is a film of ε = √(ε₁ε₂), here index √n; R(633 nm) < 1e-4 (bare 3.5 %); the film's R from 450 to 900 nm; TE = TM; halving the period cuts the residual by more than 20 | 5e-4; 1e-12 |
| Photonic-crystal membrane reflector (index 2.0, 344 nm, 0.49 µm square holes, period 1.1 µm, in air, M = 8 × 8) | at its resonance T < 1e-4 and converged (change < 1e-3 from 5 × 5); TE = TM (C4); the resonance theorem for a lossless, up-down symmetric slab with one propagating order: complete reflection and complete transmission occur (both < 1e-10, solved at 5 × 5) | 1e-12 |

## Interferometric testing (backend/tests/test_interferometry.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| N-step phase shifting, N = 3, 4, 5, 8, visibility 1 and 0.35, random phases | the phase itself | 1e-12 rad |
| Flood-fill unwrapping of a smooth phase (defocus + tilt) | the phase itself, up to a constant; disconnected pixels stay empty | 1e-10 rad |
| Sphere at its centre of curvature with 10 tilt fringes | null test (P-V < 1e-6 waves); 20 crossings of the mean intensity across the diameter | exact count |
| Cooke triplet, single and double pass | twice the fringes in double pass; 5-step recovery of the double-pass wavefront with 6 tilt fringes | rel 1e-12; 1e-9 waves rms |
| API: request, refused phase steps (2) and passes (3) | — | — |

Library example:

| Example | Reference | Tolerance |
|---|---|---|
| f/4 paraboloid (D 150 mm, R 1200 mm) tested at its centre of curvature, 632.8 nm, 256 × 256 | the exact double-pass path, in closed form in the test: the ray through the vertex-plane point u meets z = R − h²/(2R), reflects and returns to the reference sphere through the vertex. At the mirror height h it is h⁴/(4R³) to fourth order. 7.18 fringes; 4-step recovery | 1e-6 waves; rel 2e-3; 1e-9 waves rms |

## Spectrometer analysis (backend/tests/test_spectrometer.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Ideal collimator, 600 lines/mm transmission grating, ideal camera (f = 100 mm), 450–650 nm | grating equation and ideal camera: y = f tan(asin(mλG)); centroid = chief ray | 1e-9 mm |
| Its linear dispersion | f m G / cos³β | rel 5e-5 |
| Its grating resolving power | R = m G w with w = the 20 mm beam: 12000, λ/R | rel 1e-12 |
| The camera as an N-BK7 plano-convex singlet | Δλ = 2.355 σ/\|D\| and λ/Δλ from the traced spot | rel 1e-12 |
| A mirror (no dispersion); API with a refused range | NOT_APPLICABLE; SPECTROMETER | — |

The library example *Grating spectrograph (ideal optics)* is the first case.

## Physical-optics propagation (backend/tests/test_wave.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Free-space Gaussian beam in the far-field, near-field and Fresnel regimes | w(z) = w₀ √(1 + (z/z_R)²) in x and y; power conserved | 5e-4 / 3e-4 / 5e-3 rel |
| Collimated Gaussian focused by an ideal lens | exact q-parameter beam at the focal plane and one Rayleigh range beyond | 1e-3 rel |
| Coupling at the focal plane | closed-form overlap with waist and curvature mismatch, 4/((w/w′ + w′/w)² + (π w w′/(λR))²); lateral offset e^{−d²/w²} | 1e-3 / 2e-3 |
| 4f relay of ideal lenses | Gaussian: η = (2m/(1 + m²))² and D4σ = 2m w₀ for m = 1 (Debye path) and m = 1.5 (exact angular spectrum; its imaged waist is 0.28 % below m w₀ at NA 0.1, converged in the exit sampling, a non-paraxial effect); fibre LP01 → identical fibre η > 0.997 | 3e-3 / 6e-3 |
| Thick-lens test system (Gaussian beam, 5.2 µm waist) | D4σ and power on the Ø0.4 mm detector equal the direct-path ray ensemble (Wigner second moments) | 3 % / 2e-3 |
| Mirror system, fibre source with the object at infinity | rejected | — |
| API: fibre modes (cladding material + NA), POP with a fibre source, detector radius and target mode; invalid input rejected | — | — |
| POP side view of the thick-lens test system | three regions (wave / geometric / wave); width on the cut at the target = that of the target plane's own meridional cut (the converging, aberrated spot is not Gaussian, so not D4σ/2); next to the source narrower than 20 µm; at the lens the Gaussian w(z) | 1 % / 5 % |
| Imported field (from the axial FDTD, below) | the LP01 far field and the carried power; a wrong wavelength or medium index is refused | 3e-3 / 2e-3 |

Cross-check (not a unit test), a strongly curved biconvex singlet, Gaussian fibre beam:
* At the exit plane of the lens the POP field and the BPM field agree to
  0.2 % in encircled energy and 0.01 rad rms in phase.
* An independent Rayleigh–Sommerfeld integral (first kind, azimuth by
  quadrature) from either exit field gives the same irradiance at the
  detector to 0.3 %.
* POP's earlier Debye path there (Fresnel number 13, 0.7 mm behind the
  focus) gave a D4σ 4.6 % too small. The exact angular spectrum is now used
  wherever the exit field can be sampled.
* POP's target grid had under-resolved the 14 µm focal peak; it is now
  refined to λ/(4 sin θ).

## Beam propagation method (backend/tests/test_bpm.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Quasi-discrete Hankel transform, Gaussian w₀ = 30 µm | power with the transform's weights = πw₀²/2 before and after 2 mm of propagation; width = w(z) | 1e-12 / 2e-4 |
| 5 mm N-BK7 plate, 20 µm waist 0.5, 2 and 20 mm before it | width of the free beam over d₀ + t/n + d₂; power T² (POP is > 20 % off at 0.5 mm, inside the Rayleigh range) | 1e-3 / 1e-4 |
| Singlets (R 20, 10, −15 mm) within the Rayleigh range of the source waist | ABCD Gaussian beam (reduced q, refraction at the curved face) | 1e-3 (found ≤ 2e-4) |
| Thick-lens and singlet test systems (strongly curved faces, POP valid) | POP D4σ and power on the Ø0.4 mm detector | 1 % / 2e-3 |
| Off-axis source; the relay test system (4 mm beam over R 12.7 mm faces) | refused (the second with the advice to use POP) | — |
| API `method: "bpm"` (side view on request; unknown method → 422) | — | — |

Exit-plane comparison with POP (not a unit test):
* phase within 0.02 rad rms (a short rod lens) and 0.006–0.017 rad (a
  biconvex singlet, steps 0.78–3 µm);
* power within 0.1 %;
* on-axis ripple from light scattered at the face zones below 2 % with the
  smooth partition (13 % with sharp partition edges).

## Rotationally symmetric 3D FDTD (backend/tests/test_fdtd_bor.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Wide Gaussian beam onto n = 1.5, 12 points per wavelength | R of the planar solver on the same grid (independent update equations; same cell position of the interface); Fresnel 0.04; R + T = 1 | 3e-4 / 6 % / 1e-4 |
| Cleaved step-index fibre (3D cylinder, LP01 source, reference = endless fibre) | Fresnel at n_eff of LP01; R + T = 1; depolarised fraction < 1 % | 0.006 / 3e-3 |
| Its exported field as the POP source, 1 mm of free space | D4σ of the analytic LP01 POP source; power = T (1 − f_x) | 3e-3 / 2e-3 |
| Tilted beam, off-axis source, plane wave, unknown geometry; API job; oversized domain | refused / runs / 422 | — |

As in 2D, the reflectance depends on where an interface falls within a
cell. At 12 points per wavelength the facet R is 0.0344 or 0.0369 for facet
positions 0.3 µm apart (Fresnel at n_eff 0.0333). The half-space R
alternates about 0.04 by ±5 % with resolution: 0.0382, 0.0376, 0.0417 and
0.0395 at 12, 15, 18 and 24 points, identical to the planar solver.

## 2D FDTD (backend/tests/test_fdtd.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Normal incidence on n = 1.5, s and p | R = ((n − 1)/(n + 1))² = 0.04; R + T = 1; steady state | 1.5e-3 / 1e-4 |
| Layers n = 2 (0.37 µm) and n = 1.5 + 0.02i (1 µm) | R, T, A of the transfer-matrix module (thinfilm.py) | 4e-3 |
| Resolution 15 → 60 points per wavelength | the error in R at least halves | — |
| Gaussian beam onto glass → air at 30° and 50° | Fresnel R_s at 30°; total internal reflection at 50° (T < 1 %) | 4e-3 |
| 2D Gaussian beam, w₀ = 3 µm | w(z) at the waist and at 18 µm | 2 % |
| Map sizes, a metal half-space (Fresnel), tilted periodic plane wave rejected, API job (start, status, R) | — | 2e-3 |
| Slab-waveguide mode source | the mode solves u tan u = w and has the analytic profile (cos, cos·e^{−w(|y|/d − 1)}) | 1e-9 / 1e-12 |
| 2D fibre end (SMF-like slab, λ = 1.55 µm), reference = endless fibre | R into the fibre = plane-wave Fresnel at n_eff ((n_eff − 1)/(n_eff + 1))²; R + T = 1; an MgF₂ quarter wave lowers R below 0.7 R | 0.008 / 0.015 |

## Dispersive metals and plasmons in the 2D FDTD (backend/tests/test_fdtd_metals.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Silver (0.0565 + 4.2756i) and gold (0.197 + 3.09i) half-spaces at 633 nm, s and p, 30 points per wavelength | Fresnel \|(1 − N)/(1 + N)\|²; R + T = 1 (T: the power entering the metal) | 1e-3 / 2e-3 |
| 40 nm silver and 30 nm gold on glass, s and p | transfer matrix (thinfilm.py): R and T at 70 points per wavelength, and better than at 30 | 3e-3 |
| The discrete Drude medium, Re ε from −18.3 to 0.99 | its z-domain response 1 − ω_p²/(W² + iWγ cos(ωΔt/2)) equals the target ε | rel 1e-5 (float32) |
| Glass slab guide (n 1.6 in 1.45, half-width 0.4 µm, λ = 1 µm), mode source | n_eff of the TE and TM eigenvalue equations; the TE error falls as the square of the cell (ratio 1.8–2.8 from 20 to 30 points) | 4e-3 |
| Plasmon source: s polarisation, a dielectric below, an interface in the absorbing layer; a metal in the rotationally symmetric solver | refused | — |

Library example:

| Example | Reference | Tolerance |
|---|---|---|
| Surface plasmon on gold (0.197 + 3.09i, 633 nm, air above; the plasmon source, 30 points per wavelength) | k_spp = k₀√(ε_m/(ε_m + 1)) = (1.05604 + 0.00780i)k₀: the fitted n_eff, the attenuation and the propagation length 6.46 µm; the field settled | 1e-3; 3 %; 3 % |

## Gaussian beams (backend/tests/test_gaussian.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Free-space propagation | w(z) = w₀√(1 + (z/z_R)²), R(z) = z(1 + (z_R/z)²), θ = λ/(πw₀) | rel 1e-12 |
| Waist entering glass through a plane face | waist size unchanged, z_R = πnw₀²/λ | rel 1e-12 |
| Thick singlet, 4 waist sizes and positions | Self's formula (Appl. Opt. 22, 658, 1983) with principal planes: waist position and magnification | rel 1e-9 / 1e-10 |
| Concave mirror, waist on the mirror | Self's formula with s = 0; far-field λf/(πw₀) | rel 1e-10 / 1e-4 |
| M² | identical to a beam with λ·M² | rel 1e-12 |
| Small-waist limit (z_R → 0) | paraxial image of the waist (Newton/Gauss imaging) | rel 1e-6 |
| Aperture transmission report | 1 − exp(−2a²/w²) | rel 1e-12 |
| Folded system | unfolded, with note | — |
| API errors (w₀ ≤ 0, wavelength index) | HTTP 422 | — |

## Parameter sweeps (backend/tests/test_sweep.py) and reports (frontend/src/lib/report.test.ts)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Radius sweep of a plano-convex lens | EFL = R/(n − 1) (exact for a plane back surface) | rel 1e-12 |
| Back-focus sweep | EFL constant; interior RMS minimum; value equals a direct merit evaluation | 1e-12 |
| 2D sweep | columns equal the corresponding 1D sweeps; EFL independent of back focus | rel 1e-12 |
| Vignetted points | omitted with a message, never shown with penalty values | — |
| Invalid sweeps (no parameter, start = stop, R through 0, no metric, too many points), API 422 | rejected | — |
| Report | user text HTML-escaped; no script/link/img or external URLs; project SHA-256 embedded; resolved solve values and diagnostics present | exact |

## Glass substitution (backend/tests/test_glass_substitution.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Substitution without continuous variables | brute-force argmin of the merit over the candidates | exact choice, rel 1e-12 |
| Substitution with re-optimisation (singlet, 4 glasses) | exhaustive search: separate local optimisation for every candidate | same glass, merit ≤ exhaustive best (rel 1e-6) |
| Candidates not covering the system wavelengths, unknown candidates | rejected | — |
| Material variable on air, per-configuration, or on a configuration-controlled material | rejected | — |
| Merit function given a material variable | rejected | — |
| Cancellation | best-so-far result, status `cancelled` | — |
| API job (`best_materials`, `materials`), live merit ignores material variables, 422 for invalid set-ups | — | — |

Achromat check, outside the suite: the flint is free among F2, SF2, N-SF5,
N-BAF10 and N-SF6, with R1–R3 and the back focus re-optimised. The greedy
result (N-SF5, MF 0.006720 → 0.0037787) equals the best of five separate
optimisations to 1e-12.

## Tolerancing (backend/tests/test_tolerance.py)

| Benchmark | Reference | Tolerance |
|---|---|---|
| Tilted plane-parallel plate (10°, N-BK7) | lateral shift t sin θ (1 − cos θ / √(n² − sin² θ)) | rel 1e-10 |
| Downstream frames after element and surface decenters/tilts | identical to the nominal global frames | 1e-12 |
| Decentred singlet, on-axis collimated beam (real ray aiming) | spot centroid on the shifted lens axis (y = δ) | 1e-9 mm |
| Index offset | applied only to the toleranced medium; follows the medium through coordinate breaks | exact |
| Index offset on a plano-convex singlet | Δφ = Δn / R (exact thick-lens result for a plano-convex lens) | rel 1e-6 |
| Pure defocus tolerance with a back-focus compensator | compensated criterion = nominal; compensator moves by the defocus difference | 1e-4 µm, 1e-3 mm |
| x-decenter of a system with y-fields | identical results at ±limit (mirror symmetry) | rel 1e-9 |
| RSS combination | √(Σ worst²) | rel 1e-12 |
| Monte Carlo reproducibility | identical values for the same seed | exact |
| Truncated-normal draws (±2σ) | within limits; mean; σ√(1 − 4φ(2)/(Φ(2) − Φ(−2))) | 2 % (20 000 draws) |
| Uniform draws | within limits; σ = (max − min)/√12 | 2 % |
| Configuration errors (plane radius, index in air, unknown id, empty merit) | structured `TOLERANCE_CONFIG` error | — |
| API job lifecycle, progress counts, cancellation | — | — |


### Form, glass, yield and allocation (`tests/test_tolerance_form_yield.py`)

* Power: the sag at the clear-aperture radius changes by exactly
  fringes × λ_t/2 (10⁻⁹), on curved and plane surfaces.
* Irregularity: the sag change has the stated peak-to-valley over the clear
  aperture (10⁻⁶), the astigmatic form is highest at its drawn orientation,
  the rotational form is rotationally symmetric with the vertex fixed.
* Wavefront at normal incidence (acceptance benchmark): a Fringe Z5, Z9 or
  Z10 sag error a on a window in a collimated beam changes the RMS
  wavefront by (n − 1)·a·RMS_j/λ with RMS_j = 1/√6, 1/√5, 1/√8, to 10⁻⁵.
  The beam is focused by an ideal lens of F/1000: the ideal lens is exact
  for its design conjugate only, and aberrated rays see O(NA²) residuals
  (0.19 % of the RMS at F/10; OPTICAL_ENGINE, Ideal lens surfaces).
* Reflection: one fringe of astigmatic irregularity on a concave mirror
  adds 2·a/√6 waves in quadrature to its spherical aberration (2·10⁻³,
  the cos i of F/5).
* A Zernike surface keeps its normalisation radius; biconic surfaces and a
  Zernike form without its term are refused.
* Abbe tolerance: nd unchanged (exact) and (nd − 1)/(nF − nC) = Vd + dVd to
  10⁻¹², also combined with an index offset and with the environment model
  at 40 °C; default sets carry power, irregularity and Abbe tolerances.
* Wilson interval: 5/10 → 0.2366…0.7634 and 0/10 → 0…z²/(n + z²), the
  textbook values.
* Yield of a criterion monotonic in one tolerance (the EFL against a radius
  error, 400 trials): its limit at the +1σ value is met with probability
  (Φ(1) − Φ(−2))/(Φ(2) − Φ(−2)) = 0.8576 for limits at ±2σ; the analytic value
  lies inside the reported 95 % interval and within 0.05 of the estimate.
* MTF criterion: equals the field mean of the MTF analysis at the same
  sampling (10⁻¹²), a ±0.2 mm defocus lowers it both ways, the RSS estimate
  subtracts and the yield counts trials at or above the limit.
* Allocation of a quadratic merit (benchmark): three orthogonal Zernike
  errors on the window give RMS² = Σ(k_j a_j)², so equal shares of L² give
  a_j = L/(√3 k_j). The allocated limits match within 5 % and never exceed
  the share; with all three at their limits together the RMS equals the
  predicted value (10⁻³) and meets L; a locked tolerance keeps its limits.
* Solver: an exact quadratic is solved in one step (aimed 2.5 % under the
  share), a linear-plus-quadratic one within 5 % under it, an insensitive
  one stops at the 10× bound; allocated limits round toward zero to three
  significant digits; allocation without a limit, or with a nominal that
  fails it, is refused.
* Acceptance benchmark (sample doublet): eight tolerances including irregularity and
  Abbe numbers and a back-focus compensator give a yield with its interval
  against 1.25 × the nominal RMS spot; the allocation (loosening most of
  the precision-grade limits, factors up to 10) predicts at most the
  specification, and every trial of the confirming Monte Carlo run with the
  allocated limits meets it (100 %; in the browser run with all 19 default
  tolerances: 30 of 30, 95 % interval 88.6…100 %).
* UI logic (`frontend/src/lib/tolerance.test.ts`): units and default limits
  of every type, and which surfaces each type is offered on.

## Finite conjugates

| Benchmark | Reference | Tolerance |
|---|---|---|
| Image distance and magnification of a thick lens, object at 250 mm | Independent reduced ABCD matrix | 1e-10 rel |
| Object-space NA aperture definition | n sin u = NA | 1e-9 |
| Real chief-ray height of a small field | m·h (distortion only) | 0.2 % |
| Near-axis conjugate spot | < 1 µm RMS | — |

## Regression tests from the independent review (backend/tests/test_review_regressions.py)

An independent read-only review on 2026-10-11 found 13 issues. All of them are
fixed and covered by tests:

* conic root selection beyond the centre of curvature: concave mirror with a
  distant object, Cassegrain with a hyperbolic secondary, rear-stop launch
  plane, ray starting inside a sphere
* finite-object angle fields
* virtual objects
* optimiser start values outside their bounds (reported, never hidden)
* differential-evolution polish budget
* multistart budget split
* ZMX active wavelength count
* glass thickness after mirrors
* stop on a coordinate break
* polychromatic MTF lateral colour (test_diffraction)
* frontend: operand index remapping on field/wavelength removal, stop
  cleared on a coordinate break, sequential optimisation polling, and
  applying optimised variables onto the current design

## Optimisation

| Check | Test |
|---|---|
| Merit value equals the independently computed quadrature-weighted RMS spot | `test_merit_definition_matches_weighted_spot_rms` |
| Gaussian pupil quadrature exact for ρ^(2k) and odd moments | `test_gauss_pupil_quadrature_is_exact_for_polynomials` |
| RMS-wavefront operand equals the analysis; optimum focus orthogonal to defocus | `test_rms_wavefront_operand_matches_analysis_and_optimises` |
| MTF operand value and improvement | `test_mtf_operand_value_and_improvement` |
| Focus optimisation improves the merit and respects bounds; best focus lies inside the paraxial focus for an undercorrected lens | `test_focus_optimisation_improves_and_respects_bounds` |
| Active bound is reported | `test_bounds_clamp_solution` |
| Doublet: merit reduced > 90%, EFL target met | `test_achromat_optimisation_large_improvement` |
| Global and multistart reach the local optimum | `test_global_and_multistart_find_focus` |
| EFL target by curvature | `test_efl_target_curvature` |
| Cancellation returns the best-so-far solution | `test_cancel_returns_best_so_far` |
| Original design never modified | asserted in the focus test |

## Temperature and pressure (`tests/test_environment.py`)

* Air index against textbook values: 1.000293 (0 °C) and 1.000277 (15 °C)
  for the sodium D line at 1 atm, within 1.5·10⁻⁶; 1 in vacuum; linear in
  pressure.
* Model off by default, and exact (bit-identical indices and geometry) at
  the reference conditions 20 °C, 1 atm.
* Vacuum: indices equal the catalogue index at the corresponding air
  wavelength times that air's index (absolute indices); VACUUM inside air is
  1/n_air.
* Uniform expansion: a system whose glass (no dn/dT), mounts and housing
  share one CTE, in vacuum, scales exactly: EFL and BFL by s to 10⁻¹², the
  real-ray RMS spot of an aspheric singlet by s to 10⁻⁹ (with an F-number
  aperture, which is scale invariant).
* Thick-lens focal length with the thermal index and expanded geometry,
  1/f = (n − 1)(c₁ − c₂ + (n − 1) t c₁c₂/n), to 10⁻¹⁰ at −20 and +60 °C.
* Thin-lens thermo-optic coefficient: df/dT = −f β, β = (dn/dT)/(n − 1) − α,
  within 0.2 % for a 0.05 mm thick N-BK7 lens.
* Achromat focus shift from −20 to +60 °C in air with an aluminium spacer:
  within 10 % of the thin-lens prediction (shift 0.159 mm against 0.168 mm
  from thin elements; the difference is the 8.5 mm element thickness).
* Mirror radius follows its substrate CTE, the gap behind it the housing;
  missing dn/dT or CTE and out-of-range temperatures are reported.
* Temperature and pressure per configuration equal the same values set on
  the system; frozen solves expand exactly once.
* Temperature analysis: slope, spread and the diffraction depth of focus
  2λN² (F/5, 587.6 nm); the swept value overrides a configuration value;
  API, including pressure (vacuum shortens the EFL).
* Passive athermalisation (acceptance benchmark): three temperature
  configurations (−20, 20, 60 °C) and a spacer-expansion variable reduce the
  achromat's focus spread from 158 µm to below 8 µm (0.5 µm in practice),
  with the spacer CTE within 15 % of the thin-lens value (df/dT)/L.
* Temperature analysis reference: the depth-of-focus band is centred on the
  best focus at the system's own condition (equal to the sweep point at
  20 °C to 10⁻¹² mm).

## Mount tree (`tests/test_mounts.py`)

* One part holding the image: the image vertex moves by L·α·ΔT (relative
  10⁻¹³), and the reported seat shift agrees.
* Re-entrant pair: a barrel to 150 mm and a holder folded back to the image
  with α₂ = α₁·150/(150 − L) leave the image fixed (10⁻¹³ mm); the holder's
  datum moves by 150·α₁·ΔT.
* A part at its own temperature (60 °C in a 20 °C system) moves its seat by
  L·α·(60 − 20) while the lens keeps its prescription.
* A single housing part holding the image, with glass and housing sharing
  one CTE, reproduces the housing expansion of the plain environment model
  (positions to 10⁻¹³).
* A seated lens carries its element: the seat moves by α·d·ΔT for a datum d
  behind it, and surface 1 stays the frame origin.
* A lens at its own temperature in vacuum has the EFL of the whole system at
  that temperature (10⁻¹³) while the image gap keeps its 20 °C length.
* Acceptance benchmark: a cemented doublet 10 K warmer than its air and housing. Its
  EFL equals an independent thick-system matrix calculation (reduced-angle
  refraction and transfer matrices, element indices at 30 °C, radii and
  thicknesses expanded with each glass) to 10⁻¹⁰, and the focus moves
  relative to the unchanged image gap. (A thin-lens estimate is 31 % off
  for this thick cemented pair, so it is not used as the benchmark.)
* Acceptance benchmark: an Invar barrel holds the achromat; the image plane sits on a
  holder attached to the barrel at 97 mm. Over −20…60 °C the focus spread
  orders by holder material aluminium < stainless < titanium < Invar, the
  aluminium holder gives 4.5 µm against 169 µm for an all-aluminium barrel
  (required: below 1/20), matching the chain image shift per kelvin
  97·α_Invar + (L − 97)·α_holder against the focus slope.
* Limits: seats with a mirror give `MOUNT_UNSUPPORTED`, both faces of one
  lens seated `MOUNT_OVERCONSTRAINED`, a mount that pulls the image into
  the lens `MOUNT_COLLISION`; the schema rejects parent cycles, missing
  parents, unknown seat parts and duplicate ids; API round trip.
* UI logic (`frontend/src/lib/mounts.test.ts`): axial extent of a placed
  and rotated CAD box, leaf parts of CAD assemblies, parent choices without
  cycles, vertex positions, and which gaps the mounts set.

## Odd aspheres (`tests/test_odd_asphere.py`)

* The sag equals the closed form to 10⁻¹⁵. The slope matches central
  differences to 10⁻⁷, normals are orthogonal to the radial tangent, and
  200 random rays intersect on the surface to 10⁻¹¹ mm.
* With r⁴ and r⁶ terms only, the odd asphere reproduces the even asphere
  exactly: image points (10⁻¹¹), optical paths, EFL and all Seidel totals.
* A plane with β₂ = 1/(2R) has the paraxial power of a sphere of radius R.
  The diagnostics for r/r³ terms and a cone tip are raised.
* Optimisation variables read and write the right coefficient, padding with
  zeros.
* ZMX `ODDASPH` imports β₃ and β₄, with the unit scaling f^(1−i) checked in cm.

## Central obscurations (`tests/test_obscuration.py`)

* The passed fraction of a uniformly sampled pupil is the annulus area
  1 − ε² (0.003 with 401² rays), with the obscured status inside ε.
* Chief rays pass as references, so there are no marginal or chief ray
  warnings and the chief-referenced spot diagram is defined.
* MTF of an annular pupil (benchmark): an ideal lens with ε = 0.33 equals
  O'Neill's analytic MTF (JOSA 46, 285, 1956) in both directions (10⁻³ on a
  256² pupil grid; 1.5·10⁻³ at 128², 2.4·10⁻³ at 64²); for ε = 0 the formula
  is the circular one.
* The Hubble design with its 33 % obscuration: the on-axis MTF is within
  0.02 of the aberration-free annular pupil and clearly differs from the
  unobscured one.
* An obscuration on the image surface is ignored (diagnostic).

## Vignetting factors (`tests/test_vignetting.py`)

* The mapping px′ = VDX + px(1 − VCX), py′ = VDY + py(1 − VCY) is exact, and
  zero factors leave every trace bit-identical. Out-of-range factors are
  refused.
* *Set vignetting* on the double Gauss without factors:
  * zero factors on axis;
  * compression grows with the field;
  * the four marginal rays of every field pass;
  * rays 10⁻⁵ of the pupil radius beyond the found edges are clipped, so
    the edges lie on the apertures.
* The factors remove the marginal-ray warnings of the published apertures
  (12 → 0). They sample the beam: at the primary wavelength at least as many
  spot-diagram rays pass in every field, and 1.9× as many at 19°. The
  corners of the ellipse outside the lens-shaped passed region are still
  clipped.
* API round trip.

## Published reference designs (`tests/test_reference_designs.py`)

Designs transcribed from public prescriptions and checked against the values
their sources state (the start of a reference-design suite).

* **Double Gauss f/1.7, 100 mm** (Lautebacher & Brendel, US 2,784,643; the
  prescription and clear apertures of W. J. Smith, *Modern Lens Design*,
  2005, p. 323; glasses HOYA LAF3 and BAF11 as in COMSOL's Ray Optics
  tutorial of the lens, SCHOTT N-SF5):
  * the HOYA formula-3 data reproduce the catalogue nd/Vd (10⁻⁵ / 0.01);
  * EFL 100.208 mm against the stated 100.2 mm (0.05), f/1.700 (0.005);
  * paraxial back focus 61.420 mm against the table's image distance
    61.418 mm (0.005);
  * 550 nm, on axis, 1027 hexapolar rays (18 rings, as in the tutorial): the
    minimum-RMS plane (exact quadratic minimum) lies 185.7 µm before the
    image surface against 187 µm from COMSOL's meshed-solid trace with Edlen
    air (3 µm); RMS 29.3 µm (spherical aberration);
  * regression baseline: the published apertures pass 39.7 % of the pupil
    at 19° (vignetting decreasing monotonically with field).
* **Geiser triplet f/4, 50 mm** (J. Sasián's OPTI 517 triplet as entered in
  the ray-optics documentation example; N-LAK9 / N-SF5 / N-LAK9): against
  ray-optics, an independent open-source lens-design code, to the printed
  digits — EFL 50.001 (50), BFL 41.238 (41.24), FFL −37.102 (−37.1),
  principal planes 12.899 / −8.7633 (12.9 / −8.763), entrance pupil 11.679
  (11.68), exit pupil −10.013 from the last surface and radius 6.406,
  optical invariant 2.2748 (2.275); paraxial marginal and chief ray heights
  at every surface (10⁻⁵ / 10⁻⁴); the surface-by-surface Seidel sums
  S_I…S_V and their totals (1.5·10⁻⁶ mm, the printed rounding).
* **Petzval f/2.4, 100 mm with a field flattener** (M. Kidger, *Fundamental
  Optical Design*, 2001, as modelled in COMSOL's tutorial with substituted
  glasses): EFL 100.78 mm against the nominal 100 mm (1 %), f/2.43
  (f/2.4); the tabulated image plane is the polychromatic (475/550/625 nm)
  minimum-RMS focus on axis to 1.3 µm (the tutorial's adjusted back focus).
* **Hubble Space Telescope** (nominal pre-launch Ritchey–Chrétien design:
  COMSOL tutorial table; M. Lallo, Opt. Eng. 51, 011011, 2012): f = 57 599.9
  mm (57.6 m, 10⁻⁴), f/24.000; paraxial focus 1500.13 mm behind the primary
  (1500 mm); aplanatic within the rounding of the published conics
  (W040 = 0.05 λ, W131 = 0.02 λ) with astigmatism remaining; the Petzval
  curvature from the Seidel sum equals 2(1/R_s − 1/R_p) for the two
  mirrors (10⁻⁹); the source's curved focal surface (R = 604.6 mm, labelled
  "Petzval curvature" there although the Petzval radius is 774 mm; the
  RMS-best surface lies between about 600 and 700 mm because of the
  astigmatism) cuts the 10′ RMS spot more than eightfold against a flat
  one; on axis the RMS spot is 5.2 µm outside the 33 % central obscuration
  (Airy radius 16 µm).
* **Cell phone lens F/2.8** (U.S. Patent 7,535,658, Example 1, read from
  the patent's FIGS. 10, 11, 28 and 29: a glass first lens and three resin
  lenses, eight odd aspheres with r³…r¹⁰ terms, model glasses from nd/Vd).
  * The conditional values of FIG. 28 to their two decimals: f1/f 0.78,
    |f2/f| 1.06, f3/f 5.07, bf/TL 0.24, TL/(2 Ih) 0.92.
  * TL 6.408 (6.41) and F/2.8.
  * f = 5.587 and bf = 1.538 against the printed 5.57 and 1.53, which is 0.3 %,
    within the rounding of the printed indices.
  * The distortion and astigmatism curves of FIG. 29: about −1.7 % near 15 %
    of the field, +0.5 % at the edge, and astigmatism within ±0.05 mm.
* **The ray-optics transcription** of the same lens (`cell_phone_lens("ray-optics")`,
  the sample until ADR-040) against ray-optics' documentation example.
  It differs from the patent in five places:
  * R5 is 5.694 instead of 5.794;
  * A5 of the fifth surface is 1.575e-3 instead of 5.175e-3;
  * the stop is at the first vertex instead of 0.20 mm behind it;
  * the cover glass is 0.40 instead of 0.30 mm;
  * the aperture is f/3.5 instead of F/2.8.

  Its numbers against ray-optics:
  * EFL 5.5551 (5.555), FFL −7.531, principal planes −1.976 / −4.987,
    BFL 0.5678, entrance pupil radius 0.7936 at the stop, exit-pupil radius
    0.5854, all to the printed digits. The exit-pupil distance (−3.530 from
    the last surface against ray-optics' −3.602) is not compared, because
    its reference with the filter plate is unclear.
  * ray-optics' field convention (the angle whose paraxial chief ray is
    3.5 mm high on the image surface, 31.76°) to 0.005°.
  * The real field-2 rays (relative angle 0.7071; pupil 0, ±1) land at
    2.373696 / 2.416836 / 2.341605 against 2.37370 / 2.41684 / 2.34160
    (10⁻⁵).
  * A ray parallel to the axis 1 mm high ends at −0.025727 (−0.02573) with
    direction cosines −0.185004 / 0.982738, equal to six decimals.
* **Zoom 17–119 mm F2.8–3.4** (Canon, JP2015094867A, Numerical Example 1).
  * **The lens:** 50 surfaces in four groups (groups 2 and 3 move), two
    conic aspheres and a fluorite element, at three zoom positions as
    configurations. The published effective diameters are the clear
    apertures.
  * **Glasses.** The patent gives nd and νd only. Each pair is a catalogue
    glass: 13 OHARA and 2 HOYA (refractiveindex.info). The coefficients
    reproduce the catalogue nd/Vd and the patent's nd/νd to its digits.
    1.43387 / 95.1 is fluorite, used as a model glass.
  * **The transcription** is machine-checked against the patent's table.
    The lens total length (325.03) and the four group lengths add up to
    0.01.
  * **First-order data at the e line (546.07 nm).** Measured against the
    published focal lengths (17.00 / 51.00 / 119.00), entrance pupils,
    exit pupil, front and rear principal points and the four groups' focal
    lengths and principal points, every value agrees within the printed
    digit plus 2.5 standard deviations of the spread that the table's own
    rounding causes. That spread comes from 150 draws within ±0.0005 mm of
    each radius and ±0.005 mm of each separation, and the largest deviation
    is 1.4 standard deviations.
    * At the d line the exit pupil misses by 1.19 mm (12 standard
      deviations), and the entrance pupils by 0.16–0.28 mm. The patent's data
      refer to the e line.
  * **Real rays.** At every zoom position the full F2.8 / F3.4 axial beam
    (real aiming) passes inside every published effective diameter, using
    up to 98 % of it.
  * **Vignetting per zoom position.** Each position carries its own
    vignetting factors, as configuration operands per field. They are the
    vignetting analysis of that position's published apertures (VD to
    10⁻⁴, VC rounded up plus 10⁻⁴). With them every marginal ray passes in
    every position, and the evaluation reports nothing.
  * **Independent trace.** A trace written into the test, with its own
    glass formulas, conic and asphere sag and Snell, gives the same image
    point and direction for at least 150 real-aimed rays to 10⁻¹⁰ mm and
    10⁻¹². These cover F, e and C, fields 0, 0.7 and 1.0 and the three zoom
    positions.

## Birefringence, polarisers and Mueller matrices (`tests/test_birefringence.py`)

* Materials: Ghosh (1999) CALCITE and QUARTZ against handbook indices at
  589.3 nm: n_o within 10⁻⁴; n_e within 10⁻⁴ for quartz and −2.7·10⁻⁴ for
  calcite (1.48613 against 1.4864, a known offset of the fit).
* Interface amplitudes: equal to the Fresnel coefficients for an isotropic
  face (10⁻¹²); energy conserved to 10⁻¹² for 20 random crystal axes and
  incidences, entering and leaving; leaving waves parallel to the incident
  ray; at normal incidence on a crystal with the axis in the face the
  ordinary and extraordinary waves take 4n_o/(1 + n_o)² and 4n_e/(1 + n_e)².
* Calcite walk-off (benchmark): axis at 45°, normal incidence: ray at
  ρ = 6.2324° (tan ρ = (n_o² − n_e²)/(n_o² + n_e²)), displacement t tan ρ
  (10⁻¹⁰), optical path difference (n_o − n_e(45°)) t (10⁻¹⁰), ordinary ray
  undeviated, both leave parallel to the input.
* Oblique extraordinary refraction (independent solution): the wave-normal
  angle from root finding of n_e(θ_t − α) sin θ_t = sin θ_i and the ray angle
  from tan ψ_S = (n_o²/n_e²) tan ψ_k for three axis angles and incidences
  (10⁻¹⁰ rad).
* Isotropic limit: a "crystal" with n_o = n_e traces (points, optical paths,
  Fresnel intensities) and polarises (Mueller matrix to 10⁻⁹) like the
  glass.
* Quarter-wave plate (benchmark): zero-order quartz plate λ/(4(n_e − n_o)):
  retardance 0.25 waves (10⁻⁸); 45° light leaves circular (S₃ = −1, 2·10⁻⁶);
  equal to an ideal retarder of 0.25 waves with the fast axis along y
  (Stokes 2·10⁻³, the plate's Fresnel diattenuation); with one wave only
  (as prescribed) no retardance and half the power.
* Half-wave plate at 22.5°: x light leaves linear at 45° (S₂ = 1 ± 2·10⁻³).
* Malus's law (benchmark): cos²θ for θ = 0–135° (10⁻¹²); unpolarised
  transmission 1/2, diattenuation 1; crossed polarisers 0; a quarter-wave
  plate at 45° between them passes 1/4 of unpolarised light.
* Mueller matrices of a polariser and a quarter-wave plate (exact), DI = 1
  for any Jones matrix, DI = 1/√3 for the average of crossed polarisers; the
  achromat's beam Mueller matrix is near the identity with 0.98 < DI ≤ 1.
* Refused layouts: crystals in the object space, crystals bordering mirrors,
  polarising elements facing into a crystal.

## Audit follow-up (November 2026, ADR-044)

The four items the code audit of ADR-043 left open (`tests/test_numerical_consistency.py`,
`tests/test_materials.py`, `tests/test_stock.py`).

* **Serial Jacobian of the weighted-limits solve.**
  * It now uses the pool's steps (`parallel.fd_steps`).
  * The most sensitive case is the former generator problem for the 500 mm
    N-BK7/SF2 achromat: a weighted focal-length goal that ends on its
    600-evaluation budget. Run serially it gives the forced pool's radii to
    10⁻⁶ mm (285.304395, −216.554912, −812.468279) and its merit to 12
    digits. With SciPy's steps the serial run had differed from the pool by
    64.1 mm.
  * The weighted frozen sample reproduces unchanged:
    `achromat-two-conjugates` (BFD 94.8055).
  * Why the achromat was so sensitive: the generator's runs never
    converged. With the focal length an F/# solve, all 126 runs converge in
    17–102 evaluations. The long-run optimum of the old formulation is
    reproduced: N-BK7/SF2 200 × 12.7 gives 122.765 / −81.832 / −270.019,
    against 122.760 / −81.834 / −270.044 after 1836 evaluations.
  * Regenerated library: the same 740 parts.
    * On the former generator merit (RMS spot, focal length, edge; each lens
      refocused), no achromat is worse.
    * Nine are better by more than 1 %, at most 1.8 %.
    * Every focal length is exact.
* **PMMA.**
  * Beadie et al. 2015 is evaluated independently, n² = A + Σ cλᵉ, to
    10⁻¹².
  * Independent benchmark: Szczurowski 2013, another sample. They agree
    within 2.5·10⁻³ in n over 0.42–1.08 µm and 1.5 in Vd (59.37 against
    58.00). The former one-term fit differs from it by 4.8 in Vd.
  * A one-term Sellmeier fitted to either measurement at nine wavelengths
    over 0.436–1.052 µm gives Vd 57.5 and 58.1, not 53.2. The old value
    came from the data, not from the model.
* **Chief-ray angle on a curved image surface** (analytic). An ideal
  f = 100 mm lens at the stop sends the chief ray undeviated from its
  centre, at fields of 10°, 7° × 7° and −12° along x:
  * on a plane the angle is the field angle;
  * on an image sphere of radius −100 mm (centred on the lens) it is 0° to
    10⁻⁶;
  * on a sphere of radius +100 mm it is the angle between the ray and the
    radius to its landing point, 10⁻⁶ from the closed-form intersection.
    That angle exceeds the axis angle by more than 5°, which the axis angle
    used before missed.
* **Gaussian beam source in a medium** (analytic). w₀ = 20 µm, M² = 1.5,
  λ = 1 µm, source 10 mm inside a 60 mm N-BK7 plate (n = 1.50731):
  * 40 mm on, the ray ensemble's width is √(w₀² + θ²z²) with
    θ = M²λ/(π n w₀), within 2 % (in air it would be 50 % wider);
  * 15 mm behind the plate it follows the air beam nθ from the virtual waist
    at the reduced distance d/n;
  * the direct path in an object space of index 1.4 follows
    θ = M²λ/(π 1.4 w₀);
  * `/sources/describe` reports the beam in air (`medium_index` 1).

## Code audit (November 2026, ADR-043)

Five independent audits (orientation, first-order optics and invariants, UI
state, optimiser, non-sequential and wave optics) reproduced each defect with
a script. Every fix has a regression test against an analytic or independent
reference.

* **Orientation invariance** (`tests/test_field_orientation.py`, `test_wave_regressions.py`).
  A system with its fields along y is compared with the same system rotated
  about the axis: along x, along −y, and on the exact 45° diagonal (angle
  fields at atan(tan θ/√2)). An anamorphic biconic lens with its field along
  x is compared with its 90° rotation.
  * Relative illumination and its operand agree: biconic 0.886904, where the
    x version gave 1.111576.
  * The image-simulation distortion tables, live-image chief heights and ray
    and OPD fans (to 10⁻⁶) agree.
  * Advisor lateral colour: Cooke 0.857658 µm in every direction (it was 0
    along x).
  * Automatic vignetting factors: double Gauss field 3 VCY 0.071155 along x
    (it was 0.156564). Design-space distortion is no longer None for x
    fields.
  * Diffraction and geometric MTF T/S equal the y-field values to 10⁻⁸ (Cooke
    field 2: T 0.4624 / S 0.5126 in every orientation; along x they were
    swapped and at 45° both read 0.4195). The pixel MTF along a cut matches
    the box's numerical Fourier integral.
  * Cell-phone distortion is 0.525830 % in every azimuth (it was 0.529361 %
    along x). The Richardson linear limit is within 10⁻⁸ of the paraxial
    3.4816922 mm.
  * The merit quadrature is invariant under 90° rotations, since its arm
    count is a multiple of 4.
* **Angle fields.**
  * An ideal f = 100 mm lens with the object at 300 mm: the 20° angle field
    and the same object point given by height (109.19 mm) have equal relative
    illumination, 0.78056 (the angle version gave 0.661028).
  * The diagonal 3.5 mm image-height field of the cell-phone lens resolves to
    (23.82°, 23.82°), a 31.98° field, with the relative illumination of the y
    field, 0.519286 (it was 0.461655). A diagonal Cooke field gives the
    paraxial image height of the y field.
* **First order** (`test_wave_regressions.py`, `test_environment.py`, `test_rii.py`, `test_focus.py`).
  * Every wavelength is launched through the primary pupil: an N-SF6 singlet
    at F/10 reports the traced working F/# at every wavelength (9.726 at the
    F line, where it reported 10.000) and the true MTF cut-off.
  * A Gaussian beam through an ideal lens matches Self's thin-lens waist
    transformation to 10⁻⁹ (f = 100, w₀ = 1 mm: 0.017504 mm at 99.969 mm).
  * Even, odd, XY and Q-con forms of one surface expand alike to 10⁻¹² mm
    (odd and XY were 1.4·10⁻⁴ mm off at 50 K).
  * Tabulated extinction keeps α = 4πk/λ to 10⁻⁹ for k = 10⁻⁴ (it floored at
    2.76 /mm) and k = 10⁻¹¹.
  * Best focus with real image-height fields is flagged as an estimate.
* **Non-sequential media, polarisation and physical optics** (`test_wave_regressions.py`).
  * A 50 mm N-BK7 window matches (1−R)²·e^(−αL), with α from the catalogue at
    the ray's wavelength, to 10⁻⁹ (0.899379; it was 0.913944).
  * A singlet element at 70 °C matches the sequential RMS to 10⁻⁶.
  * Ideal fold and spherical mirrors retard less than 10⁻⁹ waves (they read
    0.5). A metal fold mirror gives |arg(r_p/−r_s)| from textbook complex
    Fresnel amplitudes (0.2054 rad for 0.96 − 6.69i at 45°). Rotation is free
    of global phase: a coated Cooke triplet no longer reads 180°.
  * POP: the free-space D4σ equals 2w(z) within 10⁻³ for waists before,
    after, at and beyond the object (a waist 20 mm before it was +70 %). BPM
    follows the ABCD law within 10⁻³ for offset and converging waists.
  * FFT PSF/MTF: a singlet defocused 4 mm is flagged at grid 32 (phase step
    1.02 waves, window wrap-around). Grid 256 is clean and agrees with the
    Huygens PSF within 5 %.
  * The coating estimate equals (1−R)²·e^(−αt) and the throughput analysis at
    380 nm.
* **Optimiser** (`tests/test_optimizer_regressions.py`).
  * Independent benchmark: the finite-difference steps equal SciPy's
    one-sided bound adjustment at both bounds.
  * Analytic: an RMS operand at a field or wavelength of system weight 0
    equals the weight-1 value (singlet field 3: 43.89 µm, it read 0).
  * The tolerancing RMS-wavefront criterion equals the polychromatic operand.
  * Regression baselines:
    * the global polish starts at differential evolution's optimum (penalty
      42.0 rather than 107.7);
    * budget-limited global and multistart runs report `max_evaluations`;
    * the final pick meets the limits to V_TOL;
    * glass substitution keeps N-SF5 (0.006753 against F2's 0.011453, limits
      met);
    * the tolerancing merit nominal of the achromat equals the optimiser's
      goal merit (0.011453; 0.00672 weighted);
    * two-conjugate tolerancing uses the active configuration's operands;
    * a weight-0 EFL limit is met (95.0000001);
    * an RMS-spot limit row is in µm;
    * `at_bound` holds at 6 − 3.4·10⁻¹¹;
    * 30 evaluations serially and on the pool, plus 7 closing evaluations;
    * trade-off defaults are positive, and fractions at most 1;
    * an unevaluable limit and out-of-range field or wavelength indices are
      refused at set-up.
* **UI state and references** (`frontend/src/integrity/*.test.ts(x)`, 28
  tests).
  * A result never reaches another project: optimisation preview, apply and
    report; design-space map; FDTD hand-over; CAD import; quick focus.
  * A result never overwrites an edit made meanwhile: vignetting, Qcon,
    default tolerances, CAD and stock-lens insertion, coating assignment.
  * Save marks the copy written. *Open* on the open project asks.
  * Removing fields, wavelengths and configurations remaps operands,
    sources, analysis settings and sweeps. A restored revision or a candidate
    drops dangling references.
  * Detector, coating and material deletion is checked against all users.
  * An edit arriving during a drag gets its own undo step.

## Fixes from an external test run (November 2026)

* **Distortion along the field direction** (`test_system_optics.py`): a biconic
  lens (stop 10 mm in front, R_y = 30, R_x = 60 mm) with its fields along x
  equals the 90°-rotated lens with the sections swapped and fields along y:
  distortion to 10⁻⁶ (−6.357 %), tangential and sagittal foci to 10⁻⁹. The
  `max_distortion` limit reads −6.357 % in both orientations. Before, the
  x-field lens was evaluated along y. For a rotationally symmetric lens the
  real-ray reference (x) equals the paraxial one (y) to 10⁻⁶.
* **Quick focus** (`quickFocus.test.ts`): it applies its result to the design
  it was computed for. It does not touch a project opened while it ran, nor
  a design edited meanwhile. An image distance set per configuration is
  focused in the active configuration and written to its row. The two-conjugate
  achromat focuses in both configurations; the shared variable is refused
  (engine 422, as reported).
* **Deleting an anchor surface** (`projectStore.test.ts`) re-anchors sources
  and detectors to the first surface kept after it; undo restores the anchor.
* **Generic achromats** (`test_stock.py`): with the pool forced, the generator
  still reproduces the stored library (it runs in-process). With the pool, the
  500 mm N-BK7/SF2 achromat had differed by 64.148 mm in one radius.

## Exact constraints, prices, trade-off curves and the field profile (`tests/test_optimization_exact.py`, ADR-042)

* **Layout.** The split merit function puts one normalised value per limit,
  (v − t)/s, negative when a lower bound holds, after the goals' residuals.
  The goals' merit equals a weighted merit function of the goals alone
  (10⁻¹²). |distortion| ≤ t is violated in either direction.
* **A target is met.** Singlet, EFL = 95 mm with bending and focus: the
  result's EFL is within 0.05 of its tolerance (measured 95.0000001). The RMS
  spot equals that of the weighted merit function (10⁻³), which reaches the
  same design.
* **An active bound is a KKT point.** Singlet, thickness ≤ 6 mm (it would
  grow to 9.7 mm):
  * the bound holds to 5·10⁻⁵ mm, its multiplier is positive and the
    stationarity is below 0.05;
  * independently of the multiplier, the objective's finite-difference gradient
    lies in the span of the active constraints' gradients (the remainder is
    under 2 % of it).
* **The price predicts the relaxed optimum.** The same lens re-optimised with
  the bound at the price's relaxed target (6.12 mm) changes its merit by
  0.8–1.25 times the predicted change.
* **Conflicting limits** (thickness ≥ 8 and ≤ 6 mm) end `infeasible`, with a
  note. The thickness returned lies between the two limits.
* **Weights.** With exact limits, a limit's weight changes nothing: the merit
  is identical to 10⁻¹² for weights 1, 100 and 0.01. With weighted limits, the
  bound's excess grows more than 20 times when its weight drops from 1 to
  0.01.
* **Global and multistart** end with every limit met and the EFL within 0.05
  of its tolerance.
* **Limits alone** (EFL = 80 mm by one curvature) are solved to 10⁻⁵.
* **Trade-off curve** (process pool), thickness bound at 5.76 / 6.00 / 6.24 mm:
  * every point meets its bound (10⁻³ mm), and the merit falls monotonically;
  * the middle point equals the run's own result (10⁻⁴);
  * the price at 6 mm agrees with the curve's central difference (20 %);
  * a point is reported against the design before optimisation (initial
    values and merit to 10⁻¹²).
* **Glass substitution** without continuous variables, EFL = 90 mm: N-SK16
  (83.3 mm) is chosen over N-BK7 (100 mm) and the run is `infeasible`. With
  EFL = 100 mm, N-BK7 meets it and wins over sharper glasses that do not.
* **Fixed limits.** An edge limit on a filter plate (no variable changes it)
  makes the run `infeasible` and is marked fixed. The other edge limit is met
  (6.000 mm), and the spot that got worse for it is reported.
* **Field profile** (`test_optimization_usecases.py`): at the defined fields it
  equals the spot analysis (10⁻⁹). The gap rule on the cell-phone numbers finds
  10.73 µm at 40 % against 6.06 µm at the fields (ratio 1.77). It does not fire
  when a field lies there, or for growth under a quarter Airy radius, and it
  reports failing rays. `compare_designs` flags a new gap.
* **UI logic** (`constraints.test.ts`): the roles by type and their overrides,
  the limits met, and which limits have a price. A backend test checks that the
  UI's list of default limits equals the engine's.
* **Cell-phone lens, end to end** (script, 2000 evaluations, 11 workers): exact
  limits reach RMS 4.96 µm with every limit met (EFL 5.5870700, lateral colour
  1.6999999 µm, chief-ray angle 26.59999°). Weighted limits reach 5.05 µm with
  the focal length 34 nm off.

## Parallel Jacobian and the colour, illumination and chief-ray-angle operands (`tests/test_optimization_parallel.py`, ADR-041)

* The Jacobian computed on the process pool equals the serial finite-difference
  Jacobian with the same steps (Geiser triplet, seven variables: 10⁻⁶ of each
  column's scale). The steps equal SciPy's '2-point' scheme.
* An optimisation with the pool (forced) reaches the serial run's merit
  (10⁻⁴). At the same point, the sensitivities computed on the pool equal the
  serial ones (10⁻⁵).
* A cancel stops a parallel run within a few evaluations and frees the pool.
* `max_lateral_color`, `min_relative_illumination` and `max_cra` report the
  design summary's lateral colour, relative illumination and chief-ray angle
  exactly. Their contributions are zero inside the limit and (excess)²·w
  outside it. On the axis the chief-ray angle is 0.
* UI logic: the wizard builds the three limits with the rounded current
  values, and the live image's sensor-pixel zoom puts one image pixel on one
  sensor pixel (`liveZoom.test.ts`).

## Optimisation in everyday use (`tests/test_optimization_usecases.py`, ADR-039)

The cases an optical engineer runs first, with analytic answers, and the
failures found when optimising the cell-phone lens.

* A spot of a given size: an ideal lens f = 100 mm with a 5 mm pupil, the
  image distance as the variable and `rms_spot` target 50 µm.
  * From either side of focus it stops at dz = √2 r f / R = 2.828 mm
    (10⁻⁵ mm). A uniform pupil of radius R gives RMS R dz / (√2 f), exact for
    the ideal lens's straight converging rays.
  * The operand ends at 50 µm (10⁻⁶).
* Best-form singlet: N-BK7, 1.5 mm thick, f = 100 mm at F/10, with both
  curvatures and the focus free and EFL held. Minimising the RMS spot gives
  the shape factor X = (c₁ + c₂)/(c₁ − c₂) = 2(n² − 1)/(n + 2) = 0.740 of
  third-order theory (±0.03).
* A Gaussian beam onto a detector, from a `gaussian_beam` source (w₀ = 1 mm,
  λ = 1.064 µm, 20 000 rays) through thick N-BK7 lenses:
  * the smallest D4σ on the sensor is the Gaussian waist 2λf/(πw₀) (3 %);
  * a 0.30 mm target puts the sensor where q-parameter propagation through the
    lenses' paraxial ABCD matrices gives 2w = 0.30 mm (2 %);
  * two lenses (f ≈ 102 and 204 mm), with the spacing as the variable and the
    sensor fixed, reach a 0.20 mm beam; the ABCD beam agrees (3 %). The
    second moments of a Gaussian ray ensemble propagate like the beam, so
    the result includes diffraction.
* Polychromatic RMS wavefront:
  * with one wavelength and the chief reference it equals the RMS of the
    wavefront analysis (10⁻⁹), on and off axis, and with the centroid
    reference the RMS after a least-squares tilt (10⁻⁹);
  * on axis, with all wavelengths, it equals √(Σ wₖ (λₖ/λ_p)² RMSₖ² / Σ wₖ)
    of the per-wavelength analyses (10⁻⁴; the reference spheres are
    concentric);
  * axial colour makes the plano-convex singlet's value more than three times
    its primary-wavelength value;
  * off axis (Geiser triplet, 20°), the F line against the primary chief
    ray's reference sphere differs from its own by a tilt n′ δ sin U′ (5 %),
    with δ = 0.46 µm the chief-ray separation.
* `max_distortion` equals the distortion analysis and is one-sided.
  `mtf` with all fields is the field-weighted mean of the per-field MTF
  (10⁻¹²).
* With `max_distortion` at its current value, sharpening the Geiser triplet
  (six curvatures, focus, EFL held) lowers the RMS spots and keeps
  |distortion| within 0.02 % of the limit.
* Robustness:
  * every operand keeps its residual count when it fails, so the Jacobian stays
    defined (the cell-phone crash `shapes (12,) (731,)`);
  * an error inside the search returns the best design so far with status
    `error`;
  * global optimisation takes curvature bounds from the clear apertures and
    names any other unbounded variable;
  * the image-height field of a folded cell-phone trial design (height peak
    3.93 mm at about 27°) resolves on the first branch at 22.5° (10⁻⁸ mm), also
    from the optimiser's warm start.
* Reported, not hidden:
  * an image distance under an EFL-only merit function is reported as inert
    (sensitivity exactly 0);
  * a 1 mm edge target on a 0.4 mm plate is `fixed`, with its share of the
    final merit function;
  * an edge target thicker than the lens centre makes the optimiser give up
    the focus, and the result lists the RMS spot under `objective_worse`.
* Before/after numbers (`analysis/summary.py`), on the ray-optics transcription of
  the cell-phone lens (the design of the ADR-039 optimisation run) against its Quick-focus
  design:
  * the field equals the image-height solve;
  * distortion is 3.94 %, lateral colour −0.995 µm, the MTF frequency
    110 lp/mm, and the thinnest lens edge 0.855 mm (L1; the IR plate is left
    out);
  * the centre's RMS spot and MTF are flagged as worse, and nothing else among
    the spots;
  * a design compared with itself has no flags.
* UI logic (`frontend/src/lib/optWizardScaled.test.ts`, `optCompare.test.ts`):
  * the wizard defaults scale with the smallest lens and are capped by the
    design now, plates get no edge target, and the stop gap is not a lens gap;
  * the goal operands and the distortion and length limits are built as
    described;
  * the comparison rows and flags are formatted and counted correctly, and so
    is the Quick-focus report per field.

## Light sources: aim, Gaussian beam, spectra (`tests/test_light_sources.py`)

* Aim:
  * for five positions and aim points (on axis, oblique, along x, backwards)
    and three rolls, R·ẑ equals the unit vector to the aim point (10⁻¹²);
  * R is orthonormal with det 1;
  * the roll turns the local x axis by its angle;
  * the matrix equals the explicit angles from `aim_angles` with the roll.
  * Anchored to a Cooke triplet surface, the aimed axis is M·d_local and the
    position M·p + O.
  * A collimated source aimed at (0, 3, 4) emits along (0, 0.6, 0.8).
  * An aim point at the position is refused.
  * The UI's drawing transform reproduces the engine's matrix for a fixed
    case (10⁻¹¹, `frontend/src/lib/placement.test.ts`). Changing the
    reference surface keeps the aim point and the axis.
* Gaussian beam source: with w₀ = 0.05 × 0.08 mm, M² = 2, λ = 632.8 nm and
  the waist 0, 20 mm ahead and 15 mm behind the source, the 2σ widths of
  200 000 rays follow w(z)² = w₀² + θ²(z − z_w)² with θ = M²λ/(πw₀). This
  holds in x and y, at five planes before, at and after the waist (1 %).
  The described Rayleigh range, radius at the source and wavefront radius
  equal their formulas.
* Through a real lens: a converging beam whose waist lies 30 mm ahead of
  its source, at the object plane of a 2f–2f singlet, gives the width |m|w₀
  at the paraxial image plane in the non-sequential trace (3 %), as the
  hand-built Gaussian source does.
* Spectra:
  * 3000 K over 0.3–3 µm in 27 bins: the heaviest bin holds Wien's
    λ_max = 2897.77 µm·K/T;
  * the band fraction equals an independent `scipy.integrate.quad` of
    Planck's law over σT⁴/π (10⁻⁶), and the whole spectrum integrates to
    σT⁴/π (10⁻⁴);
  * a single bin's weight equals its quadrature share (10⁻⁸);
  * a Gaussian line (630 nm, FWHM 20 nm, 21 bins) has its weighted mean at
    the centre (10⁻¹²) and its standard deviation FWHM/(2√(2 ln 2)) (1 %);
  * a flat band has equal weights at the bin centres;
  * generated spectra are valid source spectra.

## Stock lens systems (`tests/test_stock.py`)

* Generic library (740 lenses):
  * every lens's paraxial EFL equals its nominal focal length (10⁻⁹);
  * the thickness rules hold: positive edges max(1, 0.07 D) to 10⁻⁹,
    negative centres max(1.5, 0.12 D), achromat flints max(1.5, 0.1 D) and
    crown edges at least max(1, 0.05 D) − 0.05 mm;
  * no radius is below 0.55 D and the focal lengths are within D…40 D;
  * the generator reproduces every singlet exactly, and two achromats
    (N-BAF10/N-SF6 f = 100 Ø25.4, N-BK7/SF2 f = 500 Ø50.8) to 10⁻⁹.
* A stock lens's matrix EFL and back focal distance equal the traced
  system's (10⁻¹²/10⁻⁹), either way round. Reversing keeps the EFL and swaps
  the principal planes.
* First-order solver and Seidel sums:
  * random feasible combinations of 1–3 lenses, at infinity (f = 80 mm) and
    at a finite distance (m = −0.5 at 120 mm);
  * the traced EFL or magnification equals the solved value (10⁻⁹) within
    the tolerance, and the back focus equals the solved image distance;
  * every vectorised Seidel sum equals `paraxial.seidel_coefficients` of
    the traced system (10⁻⁹);
  * two lenses follow Gullstrand's f = f₁f₂/(f₁ + f₂ − e) between the
    principal planes (10⁻¹²).
* ZMX import:
  * a vendor-style file keeps radius, thickness and glass;
  * the diameter comes from MEMA (25.4 mm) and the clear aperture from DIAM;
  * the part comes from the file name ("LA1131-A-Zemax(ZMX).zmx" →
    LA1131-A);
  * unknown glasses and aspheres are refused, and a broken file is listed
    with its reason while the others import.
* CSV import: singlets and achromats are read, a malformed row is reported
  with its line number, and a missing header is refused.
* Build:
  * plans are seeded (identical twice);
  * a candidate optimised twice gives identical metrics, and its metrics
    equal a re-evaluation of its stored design (10⁻¹²);
  * every surface is a stock surface with its clear aperture;
  * through the API (generic library, N-BK7/N-BAF10/N-SF6 only, f = 50 mm
    F/4) every result uses only the allowed glasses and opens as a valid
    project.
* 1:1 relay (m = −1, object 96 mm before the first lens, NA 0.08, object
  height 2 mm): the best design is two f = 100 mm achromats with their
  crowns facing each other, the classic 4f relay. Its magnification is
  within 1 %.
* Match: a design made of two generic singlets (f = 50 and −100 mm, 12 mm
  apart) with radii changed by 1 %:
  * the original parts are among the optimised candidates and recover the
    12 mm gap (±1.5 mm);
  * the best candidate may be another part (it was a best-form lens), never
    a worse one.

  A design without lens elements (a mirror) is refused.
* Measured (development machine, 6 cores):
  * f = 100 mm F/5 ±2° build from the generic library, 1–2 lenses: 34
    one-lens and 78 889 two-lens first-order solutions, 784 prescreened,
    40 optimised in 27.6 s in the browser. The best was two achromats at
    2.5 µm field-mean RMS spot (one achromat: 5.9 µm);
  * all three lens counts: 30 s;
  * 1:1 relay: 10 s;
  * matching the sample achromat: 2 s (G-ACH-BK7-SF2-100-25.4, 5.92 µm).
    Its spot diagram in the opened project showed 6.702 · 3.303 · 7.767 µm,
    where the map had 6.7 · 3.3 · 7.77.

## Design space map (`tests/test_design_space.py`)

* Pareto front: on random point sets with many ties, duplicates and missing
  values (80 points, two and three objectives, MTF counted larger-better),
  `pareto_front` equals an independent brute-force definition of the
  non-dominated set. Equal points are all kept, and unknown objectives are
  refused.
* Seeded plans: the same specification gives the same candidate list; a
  different seed gives another. The topologies respect the element limit,
  every pair satisfies V_flint ≤ 0.8 V_crown, and no pair repeats before
  every pair of a topology has been used.
* Reproducible candidates: one candidate run twice gives identical
  prescriptions and metrics. A candidate run on the process pool gives the
  same metrics as a direct run.
* Metrics equal the normal analyses of the stored design:
  * a re-evaluation equals the stored metrics (10⁻¹²);
  * the spot diagram endpoint's per-field RMS radii (10⁻¹²);
  * the MTF endpoint at the chosen frequency (10⁻¹²);
  * the field curvature and distortion endpoint at the full field (10⁻⁹);
  * the elements endpoint's mass (10⁻¹²);
  * the paraxial total track and EFL (10⁻¹²).
  In the browser the opened design's spot diagram showed 6.631, 3.083 and
  7.169 µm, where the map had 6.63 · 3.08 · 7.17.
* Benchmark against the sample: for the sample achromat's specification
  (f = 100 mm, F/5, 2°, F/d/C), the best of four planned doublets has a
  field-mean RMS spot at most 1.05 times the sample's (14.01 µm). A full
  run's best cemented doublet reached 5.42 µm. The sample keeps fixed
  thicknesses and a zero axial-colour target; the map frees the
  thicknesses and judges only the polychromatic spot.
* The job's Pareto front equals `pareto_front` of its feasible candidates,
  for the default objectives and for objectives asked for in the request.
  The candidate endpoint returns a valid project with the prescription and
  its optimisation set-up.
* Cancel: a run cancelled after its first result ends *cancelled* within a
  minute, and only finished candidates are kept. A run that nobody polls for
  `abandon_s` (the page was closed) is cancelled by itself.
* Field-batched tracing: for every sample, every wavelength, clipped and
  unclipped, `trace_fields` gives bit-identical local and global points,
  directions, optical paths, status, intensities and failure surfaces to
  `trace_pupil` field by field. Before and after the change the full test
  suite, including the frozen sample baselines, passed unchanged.
* Time (development machine: 6 cores, 12 threads, 11 workers):
  * the default specification (f = 100 mm, F/5, 2°; singlet to Cooke
    triplet; 100 designs with tolerance sensitivity) took 212 s in the
    engine, with no failures;
  * all six topologies with 120 designs took 583 s, with the first 100
    designs done after 352 s;
  * mean time per design in the pool: singlet 3.8 s, cemented doublet
    9.6 s, air-spaced doublet 19 s, triplet 50 s, Petzval 88 s, double
    Gauss 124 s. A process runs about 1.7 times slower in a full pool than
    alone (hyper-threading);
  * best field-mean RMS spot per topology in that run: singlet 44 µm,
    cemented 5.4 µm, air-spaced 4.9 µm, triplet 2.8 µm, Petzval 2.0 µm,
    double Gauss 1.7 µm.
  * one candidate of 120 failed: a triplet whose chief ray fails in the MTF.
    Such a design is now kept without an MTF and marked as missing the
    specification.

## Live colour image (`tests/test_live_image.py`)

* Energy: every channel's blurred image holds exactly the light of its
  mapped scene (10⁻¹², preview at zoom 1 and full quality at 8× in the
  corner).
* Preview against full quality (3 × 3 against 5 × 5 PSF nodes, coarser
  pupil and PSF sampling, geometric PSFs for large preview pixels): below
  3 % relative RMS on the achromat, the Petzval, the Geiser triplet and the
  Hubble telescope, over the whole frame and 8× in the corner.
* Colour fringes: a small Gaussian spot near the frame corner (32×) of the
  Petzval and the Geiser triplet. Each channel's centroid lies at the mean
  real-ray position of its wavelength, so red minus blue equals the
  real-ray lateral colour (0.1 px; measured 0.001–0.05 px). The chief-ray
  lateral colour differs from it by the PSF centroid offsets (coma), and the
  read-outs give the chief-ray value.
* Image-height fields: the cell phone lens (real image heights up to
  3.5 mm) is imaged through the object angles they resolve to. The frame
  corner is at 3.5 mm (10⁻⁶), its chief ray at that angle lands at 3.5 mm,
  all nine PSF nodes are computed and the energy is conserved (10⁻¹²). The
  image simulation runs on it too.
* Large aberrations: an ideal f/5 lens with the image plane 2 mm behind
  focus (about 18 waves of defocus) switches to the geometric PSF. The spot's
  RMS radius equals that of the uniform disc of diameter Δz/N, R/√2 (2 %).
* Monochrome scene: one wavelength in all three channels, framed on a
  96 × 72 sensor of the same pixels. The channels are identical and equal
  the image simulation's noiseless optics image within 2 % RMS (measured 1.3 %: a different
  PSF resampling and chief-ray interpolation).
* Mirror symmetry: kernels reused by mirroring are bit-identical to direct
  computation. The chief-ray spline matches direct traces to 0.05 µm (Cooke
  triplet, double Gauss; measured below 0.02 µm).
* Photo: sRGB transfer functions (sRGB 0.5 → 0.21404 linear), decoding and
  orientation (a red top-left quadrant stays red and top-left through an
  ideal lens; sRGB 40 survives the linear round trip within 3 levels).
* Cancellation: a newer request on a channel stops the older render
  (Superseded); other channels are not affected.
* Preview time (`test_preview_time_on_the_doublet`, development machine): the
  achromat's preview takes 155–200 ms in the engine. In the browser at
  1366 × 800 with a 640 × 480 photo it took 219–278 ms per drag step, with
  the System card's analyses delayed until the drag pauses. Measured in the
  engine on the other samples: Geiser triplet 0.27 s, Petzval 0.41 s,
  double Gauss 0.48 s, Cooke triplet (real-ray aiming) 2.0 s.

## Design advisor (`tests/test_advisor.py`)

* Zernike classes: for W = 0.3 Z9 + 0.2 Z7 + 0.1 Z5 + 0.05 Z2 on 200²
  samples the class variances equal the continuous Fringe norms
  (c²/(n + 1), c²/(2(n + 1))) to 1 %, and the classes plus the residual
  equal the variance of W without its least-squares piston and tilt to
  10⁻⁹ (Parseval on the samples).
* Diagnosis on systems with a known dominant aberration:
  * plano-convex lens with the flat side to a distant object at f/5:
    spherical aberration (> 90 % of the blur at the best focus), and the
    paraxial image is out of focus;
  * biconvex singlet with the stop 40 mm in front, ±12°: field curvature at
    the edge, astigmatism and coma > 60 % of the remaining blur there,
    barrel distortion < −1 %, and causes for both;
  * uncorrected singlet in F, d, C light: axial colour > 3× the depth of
    focus, with its surfaces;
  * the achromat with its image plane moved 0.5 mm: a focus error (> 90 %
    of the wavefront variance);
  * an ideal lens: only *diffraction limited*.
* Designs balanced over field and colour (achromat, Cooke triplet, double
  Gauss samples) are in focus by the System card's criterion and get no
  focus finding; the field-curvature finding matches the spread of the
  signed defocus.
* Suggestions: every reported merit equals a re-evaluation of the patched
  design (10⁻⁹ relative) and lies below the original; they are sorted by
  gain. The defocused achromat's best move is refocus by −0.50 ± 0.05 mm,
  back to the original merit (5 %).
* Bending the reversed plano-convex lens turns it round (R1 > 0,
  |R2| > R1) with a gain above 70 % and the focal length unchanged (10⁻⁹);
  on one field and wavelength a conic on the back surface removes the
  spherical aberration (gain > 99 %) and ranks first. A dense scan along the
  bend found the minimum within 1 % of the reported merit.
* Acceptance benchmark: applying the top suggestion three times to *Achromat: starting
  point* and twice to *Cooke triplet: rough start* lowers the project merit
  function at every step by exactly the predicted amount (10⁻⁹), and each
  step starts from the previous result.
* The default merit function holds the focal length (double Gauss: target
  100.2075 mm). API: diagnosis, job start, progress to completion, an
  unknown job is 404.

## Vector PSF (`tests/test_vector_psf.py`)

* Richards–Wolf (benchmark): the Debye sum over an aplanatic NA 0.9 pupil
  (x polarisation) equals the I₀, I₁, I₂ integrals (1D quadrature) for |Ex|²,
  |Ey|², |Ez|² along x and y (10⁻¹⁰ of the peak).
* Acceptance benchmark, published width: uniform linear polarisation at NA 0.9: the
  half-maximum area is 0.314 λ² against 0.31 λ² (Dorn, Quabis, Leuchs, PRL
  91, 233901, 2003), wider along the polarisation; the scalar Airy value is
  0.256 λ².
* Whole chain at high NA: a paraboloid mirror focusing at NA 0.9, traced
  as a system (mirror polarisation, Jacobian, optical paths), equals the
  Richards–Wolf integrals with the paraboloid's apodisation 2f/(1 + cos θ)
  (10⁻⁸); Strehl 1.
* Radial polarisation: the longitudinal field peaks on the axis (> 40 % of
  the energy at NA 0.9); azimuthal: a dark centre (< 10⁻¹⁰) and no Ez.
* Low-NA limit: an ideal lens at NA 0.01 gives the Airy FWHM 0.5145 λ/NA in
  x and y (2·10⁻⁴), Ez below 10⁻⁴ of the energy, Strehl 1.
* Aberrated systems: the singlet's and the achromat's Strehl ratios equal
  the scalar FFT PSF's (±0.005).
* API round trip; invalid input polarisation is a 422 error.

## Stray light: BSDF, importance sampling, error bars (`tests/test_stray_light.py`)

* Integrated TIS (benchmark): for ABg (B = 10⁻³, g = 2; B = 10⁻², g = 1.5)
  and Harvey–Shack (l = 0.01, s = −2; l = 0.05, s = −3) the TIS equals the
  entered fraction at normal incidence (10⁻⁹) and, at |β₀| = 0.3, 0.7 and
  0.95, an independent integral in polar coordinates about β₀ out to the
  unit circle (10⁻⁶); it falls towards grazing incidence.
* Lambertian limit (benchmark): ABg with g = 0 has ρ = πA/(B + 1) and
  TIS = ρ at every incidence (10⁻⁹); its sampled directions have a uniform
  sin²θ and azimuth (Kolmogorov–Smirnov, p > 10⁻³).
* Sampling: the fraction of 40 000 ABg samples with x < x₀ equals the BSDF
  integral over that region divided by the TIS (4 binomial standard
  errors), on the outgoing side of a tilted surface.
* Lambertian limit in the trace: ABg (g = 0, ρ = 1) plate and a 1 mm disc
  detector 20 mm away, offset 10 mm: the detected power equals the view
  factor ½[1 − (h² + r² − a²)/√((h² + r² + a²)² − 4r²a²)] = 1.5987·10⁻³
  within 4σ (importance sampling, 400 source rays: 1.5983·10⁻³ ±
  0.0017·10⁻³).
* Acceptance benchmark: the same detector with an ABg plate (B = 0.1, g = 2): brute
  force with 39 381 source rays gives (2.26 ± 0.24)·10⁻³ (89 hits, 12 s);
  importance sampling with 1.8 % of the rays (709, 4 per scatter event)
  gives (2.234 ± 0.004)·10⁻³ (0.55 s); they agree within 3 combined σ and the
  importance error is below a tenth of the brute-force one.
* Error bars: the brute-force σ equals the binomial standard error of
  equal-power hits (10⁻⁹); the estimator against the sample standard
  deviation of per-ray sums (10⁻¹²).
* Path table: a window's double Fresnel reflection reaches the image
  detector with (1 − R)²R² (10⁻⁹); the rows add up to the detected power, the
  stray part to detected − direct, and a deterministic ray grid has σ = 0.
* Importance targets: unknown or disabled detectors and a missing image
  detector are refused; a surface aperture works; Gaussian scatter is not
  importance-sampled (note). API round trip with a Harvey–Shack plate; an
  invalid slope is a 422 error.

## Relative illumination, sensor and image simulation (`tests/test_imaging.py`)

* cos⁴ law (benchmark): an ideal lens with the stop at the lens gives
  RI = cos⁴θ to 10⁻⁷ at 0–40° for F/50 and F/5 (the energy form is exact at
  any aperture), with no vignetting.
* Acceptance benchmark: the doublet's relative illumination against an independent
  flat-field estimate that bins the power of rays from 800 object directions
  (each with a Gaussian pupil quadrature, weighted by the projected entrance
  pupil and sin θ dθ) into image annuli, aberration blur included: equal to
  10⁻³.
* A fixed aperture that clips the triplet's front lens lowers the RI and its
  unvignetted fraction.
* Pixel MTF (benchmark): |sinc(νw)| with w = p√(fill factor), and the image
  simulation's pixel-aperture filter scales the modulation of sinusoids of
  5, 12 and 33 cycles on the grid by exactly that sinc (10⁻⁹).
* System MTF = lens MTF × pixel MTF and Nyquist 1/(2p) in the MTF result.
* Noise: a flat 5000 e⁻ field has mean 5000 ± 1 e⁻ and variance
  5000 + σ_read² + quantisation within 2 %.
* Distortion mapping (benchmark): the simulation's chief-ray table
  (real/first-order height − 1) equals the distortion analysis of the Cooke
  triplet to 10⁻⁴ %.
* Acceptance benchmark: Siemens stars imaged through the doublet onto a defined
  1024 × 768, 3.45 µm sensor: the blur conserves the signal to 10⁻¹², the
  three images decode to the sensor region, the brightest noiseless pixel
  sits at the exposure level; API round trips for the simulation, the
  relative illumination and the MTF with a sensor.

## Q-type aspheres and XY freeforms (`tests/test_qpoly.py`)

* Qcon: Q₀ = 1, Q₁ = 6x − 5, Q₂ = P₂^(0,4)(2x − 1) (SciPy), Q_m(1) = 1, and the
  Gram matrix ∫₀¹ x⁴ Q_m Q_n dx = δ_mn/(2n + 5) for m, n < 16 (Gauss–Legendre,
  10⁻¹³).
* Qbfs: Q₀ = 1, Q₁ = (13 − 16x)/√19, Q₂ = √(2/95)(29 − 4x(25 − 19x)), and
  orthonormality in the slope norm (2/π)∫₀¹ D[Q_m] D[Q_n] du/√(1 − u²) for
  m, n < 14 by Gauss–Chebyshev quadrature (exact for these polynomials;
  10⁻¹¹), Q_m(0) > 0. The recurrence's polynomials are therefore the
  slope-orthonormal set, checked independently of the recurrence.
* Derivatives against finite differences (10⁻⁷) and the power series against
  the recurrence (10⁻¹²) for both kinds.
* Sags against the defining formulas (10⁻¹⁵ mm), the Qbfs paraxial
  curvature c + 2S(0)/r_n² against the sag's r² coefficient, the Qcon Seidel
  fourth-order term against the equivalent even asphere (10⁻¹³).
* Intersections of 300 random rays lie on the surface (10⁻¹¹ mm) with normals
  equal to the numerical gradient (10⁻⁸) for a Qcon, a Qbfs and an XY surface.
* XY: term order x, y, x², xy, y², x³, x²y, xy², y³, x⁴; x² + y² terms a on a
  plane are the paraboloid c = 2a/R², k = −1 (intersections to 10⁻¹² mm).
* Conversion: an even asphere rewritten as Qcon has a sag residual below
  10⁻¹² mm and traces identically (RMS spot to 10⁻¹¹ mm); as Qbfs (6 terms)
  below 10⁻⁹ mm; Seidel SI and EFL agree (10⁻⁶, 10⁻⁹).
* Acceptance benchmark: a Qcon front surface of the singlet with its first two Q
  coefficients and the image distance as variables reduces the on-axis RMS
  spot more than 20-fold; an XY surface with an astigmatic x² term returns
  to a sharp focus (5-fold smaller RMS) with its x² and y² terms equal.
* A Qcon element exports to STEP with its element volume (10⁻⁶; B-spline
  profile deviation below 10⁻⁶ mm); validation refuses curvature solves on
  XY surfaces and Q variables on other types; `QBFS_CONIC_IGNORED`; API
  conversion and the drawing geometry.
* UI (`frontend/src/lib/xyTerms.test.ts`): the XY term order and names, and
  the drawing sags of Qcon and Qbfs against their formulas.

## Lens elements, mechanics and glass transmittance (`tests/test_elements.py`)

* Plano-convex singlet: edge thickness t − h and volume π R² (t − h) +
  π h² (3R_s − h)/3 (cylinder plus spherical cap) to 10⁻¹².
* Flats and chamfers: a biconvex lens whose back surface ends at 7 mm and
  continues as a flat to the 10 mm rim, with chamfers of 0.4 and 0.3 mm:
  volume against an independent adaptive integration (SciPy `quad`) of the
  same boundaries to 10⁻¹¹; the outline closes through the axis with the
  chamfer corners; misfitting chamfers and a mechanical semi-diameter
  inside the clear aperture are reported.
* Doublet parts: glass codes 517642 and 620364; masses = volume × catalogue
  density exactly; tolerances in ISO terms (3/3(1), 4/1′, CT ± 0.05,
  Δnd 0.0005, ΔVd 0.5 % of Vd, radius tolerances); drawings use the 20 °C
  design even with the environment model at 60 °C.
* Exported element solids (OpenCascade B-rep volume) equal the element
  volume to 10⁻⁹, with flats and chamfers, for three systems.
* Spacers, cells and barrel of the Cooke triplet: solid volumes equal the
  analytic annuli and frusta to 10⁻⁹; rays of every field and wavelength
  (48 pupil points each, over 1000 samples along the gaps) stay inside the
  spacer bores; a cemented doublet gets no spacer.
* Slab transmittance (benchmark): through d = 5, 25 and 100 mm of N-BK7 at
  546 nm the internal transmittance is τ₁₀^(d/10) with the catalogue τ₁₀
  (10⁻¹²); between tabulated wavelengths α is linear; with the switch off
  there is no absorption; outside the data the end value is used and
  reported.
* Acceptance benchmark: the doublet's throughput with catalogue absorption is lower,
  the analysis names the source per glass, and the chief-ray ratio equals
  exp(−α₁t₁ − α₂t₂) (10⁻¹²).
* API round trip; the frontend fixture of the doublet's elements is current
  engine output.
* Drawings (`frontend/src/lib/drawing.test.ts`, acceptance benchmark): the SVG of each
  doublet element embeds its data, and parsing it back gives the
  prescription's surface ids, radii, centre thickness, conics and material
  exactly; the visible text states R 49.5259 CX, 6.000 ± 0.05, 3/3(1), 4/1′,
  nd = 1.51680 ± 0.0005 and the glass code; text is escaped.
* The built-in SCHOTT data (density, internal transmittance at 10 mm) are
  the refractiveindex.info SCHOTT pages (CC0, rev. c5c2f18), converted by the
  same code as user-installed catalogues and checked to reproduce the
  built-in dispersion coefficients.

## Formats, API and UI logic

* Project round trips for every sample, identical engineering results after
  reload, checksum tamper detection, rejection of foreign or newer files
  (`test_project.py`).
* ECMAScript number formatting parity, with the same fixture checked in
  Python and TypeScript.
* API structure, structured errors and the optimisation job lifecycle
  (`test_api.py`).
* ZMX: an inch-unit copy of the doublet reproduces the native mm design's EFL
  and per-field RMS spot to 1e-4. Also covered: asphere coefficient unit
  scaling, model glass nd/Vd reproduction, diagnostics categories, and
  UTF-16 decoding (`test_zmx.py`).
* Frontend (`vitest`):
  * unit parsing
  * canonical JSON and SHA-256 equality with backend-written files
  * project parse/serialise
  * the undo/redo store: no-op suppression, object/image protection,
    variable cleanup, revisions
  * every UI translation key exists in English and Finnish
  * UI overhaul logic (docs/UI_PLAN.md): the launch plan and recovery
    (`startup.test.ts`), every view in exactly one analysis group
    (`viewGroups.test.ts`), workspaces and their remembered layouts
    (`workspaces.test.ts`), in-app confirmations and Save / Don't save /
    Cancel (`confirmStore.test.tsx`), 2D layout framing (`framing.test.ts`),
    the System card statuses and specs (`checklist.test.ts`,
    `SystemCard.test.tsx`), the First lens request (`FirstLensDialog.test.tsx`),
    the optimisation wizard's spec (`optWizard.test.ts`), named and uniquely
    iconed toolbar buttons (`TopToolbar.test.tsx`), and a cause, fix and
    actions for every engine diagnostic code (`diagnostics.test.ts`, with the
    code list kept current by `backend/tests/test_diagnostic_codes.py`),
    design tokens and colours (`designTokens.test.ts`), and the shared
    analysis controls: bar folding without flapping, one definition of each
    control, settings only through `useAnalysisSettings`, translated button
    names, no bare row-action buttons and no units in uppercase headings
    (`controls.test.ts`), and the laptop layout rules: Inspector overlay
    threshold, dock height, bottom-tab overflow keeping the active tab, and
    minimum spot cell sizes (`laptopLayout.test.ts`), and WCAG AA text
    contrast of the colour tokens in both themes (`palette.test.ts`), and the
    environment settings, configuration labels and System card row
    (`environment.test.ts`)
* Visual QA (docs/UI_PLAN.md C5, done in the browser, not automated): an
  audit script lists every visible control without an accessible name and
  every text node whose rendered colour is below 4.5:1 against its
  composited background, over the start screen, every workspace and bottom
  tab and the dialogs, in dark/light × English/Finnish at 1366×800 and
  1920×1080. The final pass found none. Screenshots of the same matrix were
  reviewed for spacing and clipping.

## Regression baselines (expected outputs)

`achromat(optimized=True)` (N-BK7/F2, f = 100 mm, F/5, fields 0/1.4/2°, F-d-C),
hexapolar 6 rings, centroid reference:

| Field | RMS spot (µm) |
|---|---|
| 0° | 12.99 |
| 1.4° | 12.98 |
| 2° | 16.07 |

EFL = 100.00 mm, F/# = 5.00, F−C paraxial focal separation 8.5 µm

`cooke_triplet(optimized=True)` (N-SK16/F2/N-SK16, f = 50 mm, F/4.5, fields 0/14/20°, F-d-C, real ray aiming):
RMS spot 7.86 / 19.74 / 18.28 µm, EFL = 50.000 mm, distortion −0.013 % at 14° and −0.002 % at 20°, total track 60.67 mm, no validation warnings
(`test_cooke_triplet_baseline`; reproducible with `python -m opticore.tools.reoptimize_sample cooke-triplet-start`, 1255 evaluations).
(`test_achromat_baseline_values`). The frozen prescription is reproducible
with `python -m opticore.tools.reoptimize_sample achromat-start`.

## Interpreting results

* Results labelled **paraxial** or **third-order** are first-order or
  third-order approximations.
* Spot diagrams are **geometric**. The Airy radius is shown for scale only.
  No diffraction calculation is implied.
* Failed rays are counted and listed. Warnings appear in the Validation tab
  and in the analysis footers.
