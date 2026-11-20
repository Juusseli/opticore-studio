# Roadmap and implementation status

Legend: ✅ done and tested · 🟡 partial (limits stated) · ⬜ not started

## Phase 1: Professional foundation ✅

Definition of done: a user can create, edit, trace, analyse, optimise, save and
reload a lens with physically correct results (acceptance test below).

| Item | Status |
|---|---|
| Premium UI design system (dark/light tokens, components) | ✅ |
| Project explorer, assembly tree | ✅ |
| Lens Data Editor (inline validation, units, multi-select, drag reorder, context menu) | ✅ |
| Surface and material editing, inspector | ✅ |
| Interactive 2D layout (pan/zoom/select/measure) | ✅ |
| 3D viewport (lathe solids from exact sag, rays, orbit) | ✅ |
| 3D view upgrade: physically based glass/mirror materials, procedural studio lighting, ambient occlusion, bloom, SMAA, contact shadows; view cube, standard views, orthographic projection, zoom to cursor, projected-box fit; section plane; PNG snapshot; quality toggle; render on demand; BVH picking of CAD models (ADR-014) | ✅ (display only; no capped section faces, no WebGPU renderer yet) |
| Accurate sequential ray tracing, Snell refraction, mirror reflection | ✅ |
| Wavelength-dependent indices | ✅ |
| Project save/load, autosave, recovery, revisions | ✅ |
| Undo/redo | ✅ |
| Validated sample lens (achromatic doublet, frozen baseline) | ✅ |

### Phase 1 acceptance test

| # | Step | Status |
|---|---|---|
| 1 | Open the browser application | ✅ |
| 2 | Create a new optical project (blank or template) | ✅ |
| 3 | Add a lens with two spherical surfaces (Insert lens) | ✅ |
| 4 | Select an optical glass (autocomplete, material library) | ✅ |
| 5 | Specify wavelengths and aperture | ✅ |
| 6 | Change radii, thicknesses and surface parameters | ✅ |
| 7 | See the updated model in 2D/3D | ✅ |
| 8 | Trace rays | ✅ |
| 9 | View physically calculated ray paths | ✅ |
| 10 | Display a real spot diagram | ✅ |
| 11 | Run a focus/radius optimisation (Quick focus; Optimize) | ✅ |
| 12 | Compare before/after | ✅ |
| 13 | Save the project | ✅ |
| 14 | Reload with matching engineering results | ✅ (verified in-browser and by `test_reload_gives_identical_engineering_results`) |

## Phase 2: Engineering analysis and optimisation ✅

| Item | Status |
|---|---|
| Spot diagrams (patterns, references, Airy, per-λ statistics) | ✅ |
| Ray fans, field curvature, distortion, longitudinal aberration, chromatic focal shift | ✅ |
| Optical system properties (cardinal points, pupils, F/#, NA, Seidel) | ✅ |
| Multifield / multiwavelength | ✅ |
| Image-height fields (real chief-ray height solved by Newton iteration; paraxial image height) and object-space telecentric systems (object-space NA, chief rays parallel to the axis, stop-position check) | ✅ |
| Glass catalogue import (AGF formulas 1–13, data range, dn/dT, status, density, cost, internal transmittance; self-check against catalogue Nd/Vd; import report; catalogue browser with status filter and glass map; glasses copied into projects; catalogue candidates and nearest-glass selection for glass substitution) | ✅ (catalogues are user-supplied; internal transmittance enters the trace only with catalogue absorption on, E3) |
| Manufacturer catalogues installed from the refractiveindex.info database (CC0): SCHOTT, OHARA, HOYA, CDGM, HIKARI, SUMITA and others; formulas 1–3 and tabulated data, dn/dT, properties, transmittance from k; same self-check and store as AGF | ✅ (downloaded on request, not bundled; formulas 4–9 not converted) |
| Detector operands for the optimiser: beam diameter D4σ on a detector and power on a detector, by a direct-path trace of the project sources (equal to the non-sequential trace without splitting through the clear apertures, ~60× faster); sources and detectors anchored to surfaces follow thickness changes | ✅ (ghosts, lens edges and CAD bodies not in the operands; parameter sweep UI has no detector metrics yet) |
| Merit Function Editor (live value, contributions) | ✅ |
| Real numerical optimisation (TRF least squares, DE, multistart; bounds; sensitivities) | ✅ |
| Optimisation monitoring (live chart, preview geometry, pause/resume/stop) | ✅ |
| Before/after comparison, apply as revision, save as new project | ✅ |
| ZMX importer with diagnostics | ✅ (sequential STANDARD/EVENASPH/ODDASPH/COORDBRK/PARAXIAL; angle, object-height and image-height fields; glasses from imported catalogues) |
| Target MTF / RMS wavefront operands | ✅ |
| Glass substitution variables (greedy discrete search with local re-optimisation per candidate) | ✅ |
| Paraxial solves and pickups (marginal/chief height, marginal/chief angle, F-number, thickness/radius pickups) | ✅ |

## Phase 3: Advanced CAD and modelling 🟡

| Item | Status |
|---|---|
| STEP/IGES import (OpenCascade via cadquery-ocp; names, exact volume/area, IGES face sewing, display mesh, original kept) | ✅ |
| STEP/IGES export of the optical system (exact lens solids, mirror substrates, stop, image plane, rays, imported CAD models; named and coloured) | ✅ |
| STL import (binary/ASCII, units, indexed mesh, closedness/orientation/degeneracy diagnostics, area and volume) | ✅ |
| CAD models list, transforms (position, rotation), visibility/colour, bounding-box size, area and volume; 3D rendering in the optical frame | ✅ |
| CAD assembly structure (STEP/IGES product tree with instance locations, names and colours; per-part visibility, highlight, exact properties and optical roles used by non-sequential tracing) | ✅ |
| 3D measuring tools: point-to-point distance snapped to the exact B-rep, exact clearance / interference between parts | ✅ |
| CAD sections in the 2D layout (exact plane section of every visible part; STL slicing) | ✅ |
| Assembly constraints (mates), moving individual parts | ⬜ |
| CAD bodies in the optical model: lens/mirror recognition into the prescription; optical roles (absorber, mirror, refractive) in non-sequential tracing | ✅ |
| Biconic surfaces (incl. cylinder lenses; exact trace, both-section checks, x-section variables, 3D rendering) | ✅ |
| Diffractive surfaces: linear gratings and radial phase (diffractive lenses) on any surface or mirror; exact vector grating equation, OPL phase, paraxial power, evanescent orders, optimisation variables | ✅ (scalar thin element, 100 % efficiency in one order) |
| Zernike sag surfaces (Fringe Z1–Z37 on a conic/asphere base; exact monomial evaluation, Newton intersection, vertex-curvature paraxial data, rim edge checks, variables, 3D/2D drawing) | ✅ (no STEP/IGES export or non-sequential solids yet) |
| Ideal (paraxial) lens surfaces (exact tangent-space imaging, OPD exact for a chosen conjugate, paraxial power, `ideal_power` variable, ZMX PARAXIAL import) | ✅ (not in non-sequential mode or CAD export) |
| More surface types (toroid, extended asphere; odd aspheres are done, and Q-type aspheres and XY polynomials with E4) | ⬜ |
| Multi-configuration (configuration editor; thickness, radius, conic, material, semi-diameter, decenter/tilt, aperture per configuration; active-configuration analyses) | ✅ |

## Phase 4: Advanced optical physics 🟡

| Item | Status |
|---|---|
| Fresnel losses and energy throughput (vignetting × Fresnel/coating × absorption; throughput operand) | ✅ |
| Fresnel reflected-branch splitting (ghost paths) | ✅ (non-sequential mode) |
| Two-surface ghost analysis (exact ghost-path tracing, Fresnel/coating reflectances, ghost focus, footprint, energy, relative irradiance) | ✅ (refractive systems; single field/wavelength) |
| Non-sequential tracing against exact CAD solids (refraction, Fresnel splitting, TIR, mirrors, absorbers, detector irradiance, energy budget) | ✅ (geometric) |
| Photometry and colorimetry (CIE 1931 2°, CIE 018:2019): luminous flux (photopic, scotopic), illuminance maps in lux, chromaticity, CCT and Duv, true-colour detector maps with standard errors; the light of each source; LED downlight and RGB mixing examples (ADR-048) | ✅ (no colour rendering index; detector colour uses the 2° observer, the 10° observer is used for coating colour) |
| Coatings in non-sequential mode (lens-system surface coatings on their faces; per-body CAD coatings; coated metal mirrors) | ✅ |
| Surface scattering on CAD bodies (Lambertian, Gaussian; Monte Carlo, seeded; scattered light class and energy rows) | ✅ (phenomenological models; ABg and Harvey BSDFs below) |
| General light sources (point/disk/rectangle/sphere/box; uniform or Gaussian profile; collimated, isotropic, Lambertian, cosⁿ, cone, elliptical Gaussian or tabulated I(θ); spectrum; power; any placement) and detectors (circle/rectangle, acceptance angle, absorbing or monitor, one- or two-sided; power, irradiance, centroid, 2σ widths, angle and wavelength distributions) in the non-sequential trace; editor, 3D glyphs (ADR-017) | ✅ (geometric; no mode overlap or coherence) |
| ABg/Harvey BSDF, importance sampling, standard errors, stray-light path table (E6, ADR-031) | ✅ (no tabulated BSDF data; importance sampling towards one target per run) |
| Non-sequential detector metrics in parameter sweeps (the optimisation operands are done, see Phase 2) | ⬜ |
| Thin-film coatings (transfer matrix, s/p, per-surface assignment, throughput; user-defined stacks with dispersive and absorbing layers; coated metal mirrors in throughput, polarisation and non-sequential mode; coating editor with R/T/A curves) | ✅ (measured metal data added by ADR-055) |
| Coatings in the system: design for a selected surface (real ray angles, media, band), designs stored with project coatings (reopen / update), metal-mirror designs, coatings analysis view (per-surface R/T vs λ at real angles, system transmission), coating thickness variables and surface-reflectance operand in the lens optimiser | ✅ |
| Coating designer: R/T/A targets, classical starting designs (AR, V-coat, HR, edge, band-pass, notch, beam splitter), least-squares refinement and needle optimisation, Monte Carlo thickness errors, deposition recipe (optical-monitor trace with turning points and termination levels, crystal thickness via tooling factors, times), CSV/JSON export, save as project coating, angle curves and R/T(λ, θ) maps, optical-density view | ✅ (no process drift, witness-chip strategies or rugate/inhomogeneous layers) |
| Tabulated coating targets (any measured or specified curve, imported from text or CSV), optimisation of both faces of a plate (refinement, needles and evolution on front and back), worked examples in the studio's library: the OIC 2019 Manufacturing Problem ("Yucca", Appl. Opt. 59(5) A31, CC BY 4.0 targets) designed with the designer, its contest merit recomputed independently (ADR-056) | ✅ |
| Measured film and metal materials with n, k (ADR-055: SiO₂, TiO₂, Ta₂O₅, Nb₂O₅, HfO₂, Al₂O₃, MgF₂, ZnS, Si₃N₄ films; Ag, Au, Cu, Cr, Al); built-ins rebuilt of them with metal mirrors; coated back face, substrate thickness and absorption, transmission phase through the plate; GD/GDD by a local stencil; index, dispersion, absorption and substrate fitting with a global (Sobol multistart) search; colour under CIE D65, D50, D55, D75, A, C, F2, F7, F11 for the 2° and 10° observers; field map λ × depth | ✅ |
| Thin films workspace (ADR-054): coating studio with library rail (project coatings, system surfaces, built-ins), start-screen entry; GD, GDD, phase, retardance, Rv/Tv and L*a*b* targets; stack formulas (Macleod notation); admittance diagram; reverse engineering of measured R/T (scale, every layer, uncertainties); dispersive mirror DM_800 | ✅ (its first limitations were removed by ADR-055) |
| Coating analyses in the editor and the designer (ADR-053): spectrum with OD and extra angles, angle curves, phase · GD · GDD and ellipsometric ψ/Δ, colour (D65, 2°: x y, L*a*b*, Rv/Tv), standing-wave field with absorptance per layer, index profile with QWOT, band statistics; built-in library of coatings (23 at first, 29 since ADR-055; AR, V-coats, BBAR, HR, hot/cold mirrors, edge, band-pass, notch, 50/50 and MacNeille beam splitters) with stated specifications, opened in the designer under their design conditions (fixed incident index) | ✅ (its first limitations were removed by ADR-055) |
| Polarisation ray tracing (3D PRT matrices, Jones pupil, diattenuation, linear retardance, basis rotation, output ellipses; Fresnel and coating amplitudes) | ✅ (uniaxial crystals, ideal polarisers and retarders and the beam's Mueller matrix added by E7, ADR-032; no biaxial or optically active media) |
| Wavefront / OPD maps, OPD fans, Zernike (Fringe 37) | ✅ |
| FFT PSF, Strehl, encircled energy, diffraction & geometric MTF | ✅ (scalar FFT; limits in OPTICAL_ENGINE §8b) |
| Huygens PSF (wavelet summation from the real-ray reference sphere; tilted/defocused image planes, apodisation, refined Strehl, sampling warnings) | ✅ (scalar) |
| Physical-optics propagation (scalar): source fields (Gaussian, fibre LP01, top-hat, imported U(r)), far-field/angular-spectrum/Fresnel to the lens, flux-conserving ray transfer, exact angular spectrum (Debye only where the field cannot be sampled) to the target; irradiance, D4σ, power in a radius, coupling efficiency into a Gaussian or fibre mode; side view | ✅ (axial refracting systems; no diffraction inside the glass or at internal apertures) |
| Beam propagation through the lenses (BPM, scalar, rotationally symmetric): the wave inside the glass, exact Hankel propagation, per-medium diffraction through the faces (PSPI-type), POP-compatible results and side view; selectable in the POP view (ADR-021) | ✅ (axial refracting systems, on-axis source; one way, normal-incidence transmission; wide beams over strongly curved faces refused in favour of POP) |
| Fibre modes from Maxwell's equations: exact vector (TE, TM, HE, EH) and LP modes of step-index fibres, cut-off, MFD | ✅ |
| Radial fibre profiles: graded (power law) and layered rings (W, trench), LP modes, LP01 MFD, effective area, power in the core, LP11 cut-off; chromatic dispersion (material, waveguide, group index, zero-dispersion wavelength); four library examples (ADR-047) | ✅ (scalar modes for graded and layered profiles; constant index offset; no bends) |
| Fibre cross-sections: full-vector finite-difference modes of arbitrary cross-sections and hole lattices (photonic crystal fibres), leakage loss through a PML, Richardson refinement (ADR-047) | ✅ (isotropic media; uniform mesh up to 700 cells per side) |
| Gratings by RCWA: lamellar, sinusoidal, sawtooth and trapezoid profiles in stacks, TE/TM/conical, Li's factorisation, efficiencies and angles of all orders, zeroth-order phases and retardance, convergence estimate, wavelength and angle sweeps; three library examples (ADR-049) | ✅ (1D periodic) |
| Crossed gratings and metasurfaces by 2D RCWA: rectangles and ellipses (rotated, across the cell edge) in pattern layers, Li's fast Fourier factorisation, (m, q) orders with directions, cross-polarisation of the zeroth orders, sweeps; three library examples (ADR-050) | ✅ (rectangular cells, at most 961 orders) |
| Normal-vector factorisation for round shapes in 2D RCWA | ⬜ later |
| Dispersive metals in the 2D FDTD: a Drude current fitted exactly at the wavelength (Drude–Lorentz data enter through their ε there), directional sub-cell means, surface plasmon source, fitted propagation constant of guided sources; plasmonics example (ADR-051) | ✅ (monochromatic; planar 2D) |
| Broadband (pulsed) FDTD with Drude–Lorentz poles; metals in the rotationally symmetric FDTD | ⬜ later |
| Interferogram (single/double pass, tilt fringes, visibility) with N-step phase-shifting recovery and flood-fill unwrapping; paraboloid null-test example (ADR-052) | ✅ |
| Spectrometer analysis from real rays at a wavelength sweep: calibration, linear/reciprocal dispersion, geometric resolution, grating resolving power; grating spectrograph example (ADR-052) | ✅ (point slit; geometric resolution) |
| Slit width and detector pixels in the spectrometer analysis; coherence in the interferogram | ⬜ later |
| 2D FDTD Maxwell solver: s/p, CPML, plane-wave or tilted Gaussian sources, lossy media, rectangles/circles/polygons, field maps, R/T/A by flux monitors | ✅ (2D, single frequency; metals added by ADR-051; no Bloch-periodic oblique plane waves; RCWA and the axial 3D FDTD are separate solvers) |
| Rotationally symmetric 3D FDTD (body of revolution, m = 1, x-polarised; Gaussian-beam or fibre LP01 source; fibre-end presets as true cylinders) with the transmitted co-polarised field handed to POP/BPM as their source (ADR-021) | ✅ (axial structures, on-axis sources, single frequency; no dispersive media) |
| General 3D Maxwell solvers (the vector PSF and RCWA are done: E7, ADR-049, ADR-050) | ⬜ |
| Gaussian beams (paraxial ABCD/q, waist, Rayleigh range, divergence, M², aperture transmission) | ✅ (stigmatic, paraxial; no astigmatic/tilted-element or truncation propagation) |

## Phase 5: Professional engineering release 🟡

| Item | Status |
|---|---|
| Multi-configuration optimisation (operands and variables per configuration) | ✅ |
| Tolerancing: sensitivity, RSS estimate, Monte Carlo, compensators (radius, thickness, conic, index, surface/element decenter & tilt) | ✅ (surface form, Abbe number, yield and inverse-sensitivity allocation added by E2, ADR-029; limits in OPTICAL_ENGINE §10b) |
| Thermal/environmental analysis | ✅ (E1: air index, glass dn/dT, thermal expansion of glass, spacers and mirror substrates, temperature/pressure per configuration, temperature analysis, passive athermalisation; temperatures uniform within each element and mount part (E1b), see OPTICAL_ENGINE §12) |
| Parameter sweeps (1D/2D, any continuous variable, merit metrics) and automated engineering reports (self-contained HTML) | ✅ |
| Large-project performance, code splitting | 🟡 (lazy Plotly/3D chunks; merit evaluation 7.6× faster via shared semi-diameters and warm-started chord-Newton ray aiming; 3D view renders on demand with BVH-accelerated CAD picking) |
| Optional backend persistence and accounts | ⬜ |
| Open-source release: AGPL-3.0-or-later licence, third-party notices, contribution terms, CI workflow; GitHub front page (README with gallery and validation summary, issue and PR templates, code of conduct, security policy, citation, changelog, Dependabot, social preview; `docs/GITHUB_SETUP.md`) (ADR-057) | 🟡 (prepared; the public repository is not yet created, and the CI workflow has not yet run on GitHub) |
| Installable packages (ADR-058): one-click Windows installer, Linux AppImage, desktop program in an app window that ends with its last window, release workflow with self-tests and SHA-256 sums, Windows signing through SignPath Foundation | 🟡 (built and tested here; Windows signing waits for SignPath approval; no macOS package) |

## Next: engineering plan

The next additions are planned item by item in
[docs/ENGINEERING_PLAN.md](ENGINEERING_PLAN.md), in this order:

| Item | Status |
|---|---|
| E1 Temperature and pressure (athermal design) | ✅ |
| E1b Mechanical mount tree (CAD-linked parts with their own materials and temperatures, seats, element temperatures) | ✅ |
| E2 Tolerancing: surface form, glass tolerances, yield, inverse sensitivity | ✅ |
| E3 Manufacturability: ISO 10110 drawings, mechanics, glass transmittance and cost in use | ✅ |
| E4 Forbes Q-type aspheres and XY-polynomial freeforms | ✅ |
| E5 Image simulation, relative illumination and sensor model | ✅ |
| E6 Stray light: ABg/Harvey BSDF, importance sampling, path table | ✅ |
| E7 Birefringence, Mueller calculus, vector (Richards–Wolf) PSF | ✅ |
| G1 Design advisor: diagnosis and ranked, verified suggestions | ✅ |
| G2 Live colour image through the lens while designing | ✅ |
| G3 Design space map (many optimised designs, Pareto front) | ✅ |
| G4 Systems from stock lenses: library, insert, match and build | ✅ |
| G5 Light sources: direction and aim, Gaussian beam sources, generated spectra | ✅ |
| Vignetting factors per configuration (ADR-046): field rows in the configuration table, *Set vignetting* per zoom position; an evaluation belongs to its project | ✅ |
| Reference design: Canon 17–119 mm F2.8–3.4 zoom (JP2015094867A) with catalogue glasses, first-order and group data at the e line, effective diameters, independent real-ray trace | ✅ |
| Paraxial-aiming check (ADR-045): `PARAXIAL_AIMING` warning or note when paraxially aimed rays miss the stop | ✅ |
| Code audit follow-up (ADR-044): serial Jacobian with the pool's steps, generic achromats by an F/# solve to convergence, PMMA from Beadie 2015 (polymer spread stated), chief-ray angle to the local image normal, Gaussian sources in their medium | ✅ |
| Code audit (ADR-043): field directions, one launched pupil, active operands, non-sequential media, mirror polarisation, POP waists, FFT sampling warnings, tolerancing with exact limits, results bound to their design, reference integrity | ✅ |
| Exact limits and design trades (ADR-042): augmented-Lagrangian constraints with prices, trade-off curves on the process pool, field profile with sampling-gap check, parallel differential evolution | ✅ |
| Optimisation speed and limits (ADR-041): Jacobian and evaluations on the process pool, lateral colour / relative illumination / chief-ray angle limits, live image at sensor pixels | ✅ |
| Optimisation robustness and honest results (ADR-039): fixed residual counts, spot/wavefront targets, polychromatic wavefront, max distortion, first-branch image-height fields, before/after comparison, scaled wizard defaults, beam-size goal | ✅ |
| E8 Python API | ⬜ |
| Later (light sources): photometric power (lm, CIE V(λ)); IES/LDT intensity files with azimuthal variation; ray files; polarised sources; quasi-random (Sobol) source sampling | to be evaluated |
| Later: L1 heat conduction and thermal lensing; L2 structural-thermal-optical FEM of the CAD model | to be evaluated |

## Known limitations (current release)

See docs/OPTICAL_ENGINE.md §12. Panels are resizable and collapsible with
workspace presets. Free-form docking (dragging panels between dock zones) is
not implemented.
