# Changelog

Notable changes to OptiCore Studio. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Design decisions are recorded as ADRs in
[docs/DECISIONS.md](docs/DECISIONS.md).

## [Unreleased]

### Added
- Installable packages: a one-click Windows installer and a Linux AppImage
  (ADR-058). The desktop program runs the engine and the user interface as one
  process in an app window, and works offline.
- Release workflow: a version tag builds and tests the packages and drafts a
  release with SHA-256 sums. Windows files are signed through SignPath
  Foundation once it is configured (`docs/CODE_SIGNING.md`).
- GitHub front page: a README with a gallery and validation summary, issue and
  pull request templates, a code of conduct, a security policy, citation
  metadata, Dependabot and a social preview image.
- Open-source release under AGPL-3.0-or-later, with third-party notices,
  contribution terms and a CI workflow (ADR-057).
- `docs/DEVELOPMENT.md`: running, testing and the invariants every change
  follows. The CI workflow also runs the linter, which must report no warnings.

### Changed
- Code comments, docstrings and documents reviewed for an outside reader:
  internal plan IDs replaced by feature names, outdated statements corrected
  (roadmap status, known limitations, the ZMX surface table), the decision
  records put in number order.
- Helper functions and constants moved out of React component files into
  their own modules, so the linter reports no warnings.
- Test files with internal names renamed after what they test.
- The user-interface package is named `opticore-studio-ui`, version 0.1.0.
- Licensing is AGPL-3.0-or-later only: contributions are accepted under the same
  licence, and no other licence is offered (ADR-059). The code signing policy
  names its authors, reviewers and approvers, and every release links to it.

### Removed
- The three fibre-to-photodiode coupler templates. The beam tests that used
  them now run on neutral test systems (`backend/tests/beam_systems.py`): a
  1:1 relay, a thick lens and a singlet.
- Unused imports in the engine and the tests.
- Local development files (tool configuration and working notes) are no
  longer in the repository.

### Fixed
- The direct-path detector trace (detector operands) could drop rays crossing
  a detector on a surface's vertex plane, such as one anchored to the image
  surface. At some distances 2 % of the power vanished without being reported
  as lost, and the optimiser stalled there.

## [0.1.0] - development, October–November 2026

The first development line, built incrementally with every phase validated by
automated tests.

### Lens design and analysis
- Sequential engine:
  - exact vectorised ray tracing with explicit per-ray failure states;
  - paraxial and real ray aiming;
  - surfaces: spherical, conic, even and odd aspheric, biconic, Zernike, Q-type
    and XY freeform, diffractive and ideal;
  - mirrors and coordinate breaks;
  - multiple configurations, solves and pickups.
- Analyses:
  - spot diagrams, ray and OPD fans, field curvature and distortion, chromatic
    focal shift;
  - wavefront with Zernike terms and interferograms;
  - FFT, Huygens and vector PSF; diffraction and geometric MTF with a sensor;
  - relative illumination, image simulation and the live colour image;
  - polarisation ray tracing with uniaxial crystals; Gaussian beams; ghosts.
- Design advisor, design space map with Pareto front, stock lens library and
  matching.
- Published reference designs reproduced as templates (ADR-040):
  - double Gauss US 2,784,643, Geiser triplet, Kidger Petzval;
  - cell phone lens US 7,535,658, Hubble, Canon zoom JP2015094867A.

### Optimisation and tolerancing
- Merit function editor and damped least squares (trust region).
- Exact limits by an augmented Lagrangian, with prices and trade-off curves
  (ADR-042).
- Parallel differential evolution and multistart; evaluations on a process pool
  (ADR-041).
- Glass substitution and multi-configuration optimisation.
- Tolerancing (ADR-029): sensitivity, RSS and Monte Carlo with compensators;
  yield and tolerance allocation.
- Temperature and pressure (ADR-027) and mount trees (ADR-028).
- ISO 10110 element drawings and manufacturability (ADR-030).

### Thin films
- Transfer-matrix engine, user-defined coatings, a coating designer with
  refinement and needle optimisation, and deposition recipes.
- Coating studio workspace (ADR-054).
- Measured film and metal materials (ADR-055).
- Tabulated targets, optimisation of both faces, and the OIC 2019 contest
  example (ADR-056).

### Non-sequential, illumination and wave optics
- Exact-solid non-sequential tracing of lenses and CAD bodies:
  - coatings and surface scattering (ABg, Harvey);
  - general sources and detectors;
  - stray-light path tables (ADR-031).
- Photometry and colorimetry with CIE data (ADR-048).
- Wave optics:
  - fibre modes, including graded, layered and photonic-crystal fibres (ADR-047);
  - physical-optics propagation and BPM;
  - 2D and axisymmetric 3D FDTD with metals and plasmons (ADR-051);
  - RCWA for gratings and metasurfaces (ADR-049, ADR-050);
  - interferometry and spectrometers (ADR-052).

### Files, CAD and interface
- Versioned `.opticore` projects with SHA-256 checksums, revision history,
  autosave and crash recovery.
- Imports: Zemax ZMX with diagnostics, AGF catalogues, manufacturer catalogues
  from refractiveindex.info, STEP/IGES/STL.
- STEP/IGES export of the optical design.
- Interface:
  - workspaces (Design, Analyze, Optimize, Tolerance, Illumination, Wave optics,
    Thin films) and the start screen;
  - command palette, undo and redo for every edit, value scrubbing;
  - dark and light themes, English and Finnish;
  - a laptop layout below 1440 px.

[Unreleased]: #unreleased
[0.1.0]: #010---development-octobernovember-2026
