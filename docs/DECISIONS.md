# Architectural decisions

The decisions are listed in number order; later ones refine or replace earlier ones where they say so.

## ADR-001: Python engine as the single source of physics truth
**Decision:** All optics (tracing, paraxial, analyses, optimisation) run in the
Python engine. The browser renders and edits.

**Why:**
* One validated implementation.
* NumPy vectorisation and SciPy optimisers.
* Straightforward testing with pytest.

**Trade-off:** Every live update is an HTTP round trip (≈10–70 ms for typical
lenses). This is acceptable for interactive work. A WebAssembly or TypeScript
port of the tracer could be added later for offline use, but it must then be
validated against the same suite.

## ADR-002: Own sequential tracer instead of an external optics package
**Decision:** The tracer, paraxial module and analyses are implemented
in-house. RayOptics and other packages were considered as dependencies.

**Why:**
* Full control of conventions, failure reporting and the data model.
* No coupling of the domain model to an external API.
* Compatible licensing.

We use NumPy/SciPy as trusted numerical foundations. External packages remain
candidates for cross-validation baselines.

## ADR-003: Curvature as the optimisation variable for radii
**Why:** Curvature is smooth through flat surfaces (R → ∞), whereas radius
bounds across infinity are ill-posed. The UI shows radii; bounds are entered in
1/mm.

## ADR-004: Least-squares residual structure for RMS spot
**Decision:** The RMS-spot operand exposes one residual per ray coordinate
instead of a single scalar.

**Why:** Trust-region least squares exploits this structure for much faster,
more robust convergence. The sum of squares equals the weighted RMS², so the
merit value keeps its physical meaning.

## ADR-005: Automatic apertures never clip
**Why:** Automatic semi-diameters are sized to pass the full defined beam; only
fixed apertures vignette. This matches common sequential practice and avoids
optimisation artefacts from apertures that move with the design.

## ADR-006: Indices relative to air; AIR = 1
**Why:** Catalogue data are air-relative. An absolute-index mode (vacuum
reference with an air dispersion model) is deferred.

## ADR-007: Browser-local persistence with a portable, checksummed format
**Decision:** Use IndexedDB for the library and autosave, and a JSON
`.opticore` file for exchange.

**Why:** This needs no account or cloud. The SHA-256 checksum uses canonical
JSON with ECMAScript number formatting implemented on both sides, so either
side can verify integrity. Server persistence can be layered on later without
changing the format.

## ADR-008: Undo by whole-document snapshots
**Decision:** Each commit stores the previous project document (structurally
cloned, 200-deep). No-op commits are ignored.

**Why:** Projects are small (kilobytes), and snapshots make undo provably
exact, including for compound operations such as delete, insert lens, apply
optimisation and restore revision.

## ADR-009: Plotly for scientific plots, custom SVG for the 2D layout, R3F for 3D
**Why:**
* Plotly gives zoom, hover cursors and export out of the box. The cloud-share
  button is removed because data must not leave the machine.
* The 2D layout needs exact control (hit testing, measuring, rays) and stays
  light as SVG.
* React Three Fiber renders lathe solids built from the exact sag.

**Trade-off:** Plotly is about 3 MB minified. Bundle splitting is on the
roadmap.

## ADR-010: Hand-built components instead of shadcn/ui and TanStack Table
**Why:**
* The engineering table needs bespoke cell editors (unit parsing, variable
  toggles, auto/fixed apertures) and drag reordering.
* A small set of Tailwind primitives kept dependencies and styling coherent.
* The component boundaries allow swapping in TanStack Table if virtualisation
  becomes necessary for very large systems.

## ADR-011: ZMX import as an independent text parser with diagnostics
**Why:** ZMX is line-oriented text. A small, auditable parser that classifies
every record as imported, partial, unsupported, missing material or conversion
difference serves engineers better than an opaque converter. Binary formats are
out of scope.

## ADR-012: Temperature stored but not applied (superseded by ADR-027)
**Why:** Only some materials have dn/dT data, and thermal expansion of
mechanics and air are not modelled. A partial thermal model would mislead, so
the trace ignores temperature until phase 5. The UI therefore does not expose
a temperature control.

## ADR-013: STL parsed in-house; STEP/IGES through OpenCascade in the engine

STL is a simple, documented format, so the engine parses it with NumPy. That
gives exact control over unit handling and mesh diagnostics, with no new
dependency.

STEP and IGES need a B-rep kernel, and both directions were required:
importing mechanics, and exporting the finished optical design to CAD.
occt-import-js only reads. The engine therefore uses OpenCascade 7.8 through
`cadquery-ocp`, pinned to 8.0.1.0.0 (Apache-2.0 bindings; OCCT is LGPL-2.1
with an exception; it pulls in VTK, BSD, about 150 MB in total).

The newest build (8.0.1.1.0) was skipped because, when the dependency was
added on 2026-10-11, it had been out for only six days.

The kernel is imported lazily, so the engine starts without it and only CAD
requests pay the roughly 0.6 s import. Lens solids are built from the exact
prescription rather than from any mesh.

Meshes are stored in the project as base64 float32/uint32 arrays. This keeps
files compact and canonical-JSON checksums stable.

## ADR-014: 3D view on WebGL2 with physically based rendering, not WebGPU
**Decision:** The 3D view stays on Three.js/React Three Fiber with the WebGL2
renderer. It uses physically based materials, a procedural studio
environment and a post-processing chain
(`@react-three/postprocessing`: N8AO ambient occlusion, bloom, SMAA,
vignette).

**Why:**
* WebGPU (`three/webgpu`) cannot yet run the post-processing, transmission
  and drei helpers this view needs (environment, contact shadows, view
  cube, fat lines, BVH picking). WebGL2 runs in every current browser,
  including older integrated graphics.
* The look comes from materials and lighting, not the API:
  - transmissive glass with the real index of the primary wavelength
    (clamped to the renderer's 1–2.333 range) and centre thickness;
  - ground (frosted) lens edges, metal mirrors with a matte blank, an
    anodised stop iris;
  - an environment built from Lightformers (soft boxes, horizon strips,
    a ring). It is rendered once into the environment map, so no HDR image
    is downloaded and nothing leaves the machine.
* The glass writes no depth. Rays inside an element stay visible and
  ambient occlusion ignores the glass.
* Rendering is on demand (`frameloop="demand"`): an idle view uses no GPU
  time. Camera moves, damping, prop changes and imperative updates call
  `invalidate()`.
* "Fast" quality turns off transmission, post-processing and shadows for
  weak graphics. The setting is stored per browser, not in the project.

**Display only:** All of this is presentation. The tessellated lens solids,
the refraction of the background through the glass and the shadows are not
optical results. Ray paths come from the engine's exact trace (ADR-002).

**Trade-off:** The lazy 3D chunk grew to about 1.4 MB (460 kB gzip).
`preserveDrawingBuffer` is enabled for PNG snapshots, which costs a little
fill rate. Revisit WebGPU when its post-processing and helper ecosystem is
complete.

## ADR-015: Glass catalogues in the browser; projects carry the glasses they use
**Decision:** The engine parses AGF catalogues statelessly. The browser keeps
them (IndexedDB) for every project. A project gets a copy of each catalogue
glass it uses in `custom_materials`, added inside the same undoable commit.

**Why:**
* Glass data from manufacturers cannot be redistributed with OptiCore. The
  user supplies the files, and they stay on the user's machine.
* The engine stays stateless: every request carries the materials it needs.
  Optimisation requests also carry the definitions of glass-substitution
  candidates.
* Project files must evaluate identically anywhere, including without the
  catalogue (FILE_FORMATS, the invariants in DEVELOPMENT).

**Rules:** Built-in names win over catalogue glasses of the same name. This
keeps existing projects and baselines unchanged. Catalogues resolve in name
order, and shadowed names are listed. Unused glass copies stay in the
project until the user deletes them.

## ADR-016: Ideal lens as an exact tangent-space mapping
**Decision:** An ideal lens maps ray tangents `t' = t − h/f` in a uniform
medium. It adds an optical path that is exact for one design conjugate
(infinity by default).

**Why:**
* The tangent mapping is linear, so ideal lenses and the spaces between them
  form an exact ABCD system. Real rays then reproduce the paraxial
  predictions exactly, which gives analytic benchmarks.
* No lens is aberration-free for all conjugates. The OPD therefore has to
  name its conjugate rather than hide the residual.
* Requiring the same medium on both sides keeps Fresnel, polarisation and
  ghost analyses consistent: there is no interface, so nothing reflects.

## ADR-017: General sources and detectors instead of device presets
**Decision:** The non-sequential trace has general sources (placement,
emitting shape, spatial and angular law, spectrum, power) and detectors
(placement, area, acceptance angle, absorbing or monitor). There are no
fibre, LED or laser presets. Detectors are analytic planes.

**Why:**
* Users model any fibre, emitter, sensor or chamber. Presets would cover a
  few cases and hide the physics. The building blocks are documented laws
  that validate against radiometric closed forms.
* Analytic detector planes are exact and fast, and need no B-rep faces. A
  legacy detector face (role "detector") still works, so existing scenes
  and tests are unchanged.
* Gaussian beams use the geometric ray-ensemble (Wigner) model. Its second
  moments follow the Gaussian ABCD law exactly, which is enough for spot
  sizes and for the power on an area. Mode overlap, coherence and
  diffraction need physical-optics propagation, which stays on the roadmap
  and is not claimed.

## ADR-018: Manufacturer catalogues downloaded from refractiveindex.info, not bundled
**Decision:** The material library installs manufacturer catalogues on
request from the refractiveindex.info database. The browser downloads the
YAML pages from GitHub at a fixed commit, the engine converts them
statelessly, and the result is stored like an AGF import (ADR-015).

**Why:**
* The database is dedicated to the public domain (CC0 1.0), so its use is
  clear. The values themselves come from the manufacturers' catalogues, so
  OptiCore still ships none of them (ADR-015): the user's browser fetches
  them when the user asks.
* One click installs about 1600 glasses of six makers, without finding and
  downloading AGF files.
* The engine never makes network requests. Conversion and the nd/Vd
  self-check stay in Python, the only source of optical numbers.
* The commit is recorded with each catalogue, and projects embed the
  glasses they use, so results stay reproducible when the database changes.

**Trade-off:** Installing needs internet access to github.com (about 7 MB
for the six makers).

## ADR-019: Detector operands use a direct-path trace, not the non-sequential trace
**Decision:** The optimiser's detector operands trace the project sources
through the sequential surfaces with the vectorised ray trace and intersect
the detector planes (`nsdirect.py`). The non-sequential trace remains the
analysis.

**Why:**
* The non-sequential trace follows each ray in Python against B-rep solids
  (1.2 s for 1500 rays). An optimisation needs hundreds of evaluations; the
  direct path takes 20 ms.
* For light through the clear apertures the direct path is exactly the
  non-sequential trace without splitting (same seeded rays, the same
  physics), as the tests check. What it leaves out (ghosts, edges, CAD
  bodies) is second order for focusing a beam and stays visible in the
  analysis.
* The beam diameter is taken in the detector *plane* over all rays, so it
  is smooth in the design. The detector-area count is a step function,
  which least squares cannot follow.
* Sources and detectors anchored to surfaces move with thickness changes.
  Without anchors, a varied distance would leave the fibre and the sensor
  behind.

## ADR-020: Wave optics as three focused solvers, not one general field solver
**Decision:** Wave optics comes as three solvers:
* exact fibre modes (the eigenvalue equations of Maxwell's equations for
  step-index fibres);
* scalar physical-optics propagation through the sequential system (POP);
* a 2D FDTD solver for wavelength-scale structures.

**Why:**
* A lens is thousands of wavelengths wide. A 3D Maxwell solver of a whole
  system is out of reach in a browser application, and not needed: through
  lenses, the geometric phase transfer is exact to the stationary-phase
  order. Diffraction matters in free space, where POP uses exact scalar
  propagators (Rayleigh–Sommerfeld far field, angular spectrum, Debye).
* Fibre coupling needs the true mode shapes (exact
  Bessel solutions) and the overlap of the propagated field with the
  receiving mode.
* Wavelength-scale structures (layers, gratings, waveguides, microlenses,
  fibre tips) need the full Maxwell equations. 2D FDTD solves them directly.
  It is validated against the transfer-matrix and Fresnel results, and it
  runs in seconds in numpy (float32, slicing, PML-only auxiliary fields).
* Each solver states its regime and limits; nothing is labelled a full
  electromagnetic solution of a lens system.

## ADR-021: Large systems by coupled solvers: BPM inside the glass, axial FDTD at the fibre end

**Context:** Commercial wave-optics tools reach systems many wavelengths
large by dividing the problem, not by one 3D Maxwell grid:
* FDTD for the wavelength-scale part;
* beam propagation or the angular spectrum for long, slowly varying
  regions;
* physical optics through the lenses.

A fibre → lens → detector system is about 10¹⁵ cells in 3D FDTD. ADR-020's
POP misses diffraction inside the glass when a lens sits near a beam waist:
a plate within the Rayleigh range gets a 36 % error.

**Decision:**
1. **BPM** (`wave/bpm.py`) for rotationally symmetric refracting systems.
   * Built on exact homogeneous propagation by the quasi-discrete Hankel
     transform.
   * Through the faces: short steps in which each medium diffracts with its
     own k_z, over a smooth partition of unity, with the step's optical
     path as a phase screen.
   * It is selected in the POP view and returns POP's result structure.
2. **Axial FDTD** (`wave/fdtd_bor.py`, body of revolution m = 1). Fibre ends
   and other axial structures are true 3D cylinders in an (r, z) grid. The
   transmitted co-polarised field becomes a POP/BPM source on a plane after
   the object surface.

**Why:**
* **BPM over the alternatives.**
  * A paraxial or Padé finite-difference BPM with a single reference index
    was tried first. It misstated the optical path at an air/glass face by
    tens of percent (0.55 mm instead of 0.15 mm D4σ for a short rod lens). Its
    finite-difference Laplacian also added a 1 % width error even in
    homogeneous glass.
  * A spectral split step with one reference index left a 0.4 rad rms
    phase error at the exit of a steep singlet.
  * Per-medium diffraction removes that error (0.01 rad). PSPI's output
    stitching gained 0.2–0.3 % power (an O(1) flux double count at the
    medium boundary); partitioning the input field conserves it.
  * The smooth partition cuts the scatter from partition edges (on-axis
    ripple 13 % → below 2 %).
* **Scope of the BPM.** It costs ~N² per step through the face zones. Wide
  beams over strongly curved faces would take minutes, and there the ray
  transfer of POP is accurate (Fresnel number ≫ 1), so the BPM refuses them
  and says so.
* **POP stays the default.** It handles any axial refracting system quickly
  and is exact wherever its ray transfer is. The BPM is the choice near
  waists.
* **Axial FDTD.** It gives the exact 3D field of a cleaved or coated fibre
  end in seconds (a 2D slab would misstate the mode), and validates against
  the planar solver and Fresnel at n_eff. Exporting only the co-polarised
  rotationally symmetric part, with its depolarised fraction reported,
  keeps the hand-over to the scalar solvers honest.
* **Found on the way.** The cross-checks (BPM, an independent
  Rayleigh–Sommerfeld integral) showed POP's Debye path to be 4.6 % off in
  D4σ at Fresnel number 13 behind the focus, and its 128-point target grid
  to under-resolve sharp foci. POP now prefers the exact angular spectrum
  wherever the exit field can be sampled, refines the target grid to
  λ/(4 sin θ), and weights its ray statistics by power.

**Not done:** general (non-axial) 3D FDTD; two-way BPM with reflections;
polarisation in the BPM; automatic FDTD → POP placement for arbitrary
structures (the user gives the FDTD z of the object surface; the fibre
presets set it).

## ADR-022: Start screen over a reopened workspace; unsaved work reopened, not held in a dialog
**Decision:** At launch the app first reopens a project (unsaved work if the
last session left any, else the project that was open last, else the
tutorial sample) and then shows the start screen over it (unless *Show at
startup* is off and nothing needs recovering). Unsaved work is reopened as
the open, still-unsaved project; the start screen offers *Continue* or
*Discard changes*. The modal recovery dialog is gone.

**Why:**
* Closing the start screen must lead somewhere useful. With the last project
  already behind it, Esc is "carry on where I was", as in Blender's splash.
* Treating recovered work as the open, unsaved project needs no separate
  state: autosave keeps writing the same project, the title shows ●, and
  every other action (template, recent, file) goes through the normal
  unsaved-changes confirmation. Nothing is lost silently and nothing extra
  is written to the library.
* The previous design read the autosave only after the engine checks, and
  the autosave timer could overwrite it before that on a slow start. The
  launch now reads the autosave and the library first, and autosave stays
  off until a project has been opened.

**Thumbnails:** The engine draws nothing; it returns an outline (exact
profiles and real rays reduced to a few points, `/system/outline`, included
in `/samples`). The UI only scales polylines, so the "physics stays in the
engine" rule holds. Sample outlines are computed once per engine process
(the samples are frozen).

**Trade-off:** A first launch with the engine offline cannot show templates;
the start screen says so and fills the list when the engine comes up.

## ADR-023: Workspaces filter what is offered, not what is allowed
**Decision:** The six workspaces (`lib/workspaces.ts`) choose which bottom
tabs, sidebar sections, analysis groups and context commands are offered,
and remember a layout each. They never block a feature: the view menus list
the remaining analyses under *More analyses* and search all of them, and
opening a bottom tab that the workspace lacks switches to the workspace that
has it. The routing sits in `uiStore.set`, so every existing
`set({ bottomTab })` call keeps working.

**Why:**
* A new user should see the basics first (Fusion and Blender do the same),
  but an expert must not have to hunt for a module because they are in the
  "wrong" workspace.
* Keeping the active layout in the existing top-level fields (`leftView`,
  `bottomTab` …) means no view or panel had to change; a switch only copies
  nine fields in and out.

**Trade-off:** Views are not restricted per workspace: a pane may show an
analysis from another group (picked through *More analyses*), and it is
remembered with that workspace's layout.

## ADR-024: Bundled variable fonts and a four-step type scale
**Decision:** Inter and JetBrains Mono are bundled as variable fonts
(`@fontsource-variable/inter`, `@fontsource-variable/jetbrains-mono`, OFL)
and the UI uses four named text sizes, two control heights, icons of
12/14/16 px and radii of 4/6/8 px, enforced by a source-scanning test.

**Why:**
* The declared fonts were never loaded, so Windows showed Segoe UI and other
  systems something else; numbers and column widths differed per platform.
  Bundling makes the rendering, and the measured fit at 1366 px, the same
  everywhere, with no request to a font CDN.
* Nine ad-hoc sizes and eight control heights read as noise. A small scale
  is easier to keep consistent, and a test keeps it that way.
* Component classes (`.field-input`, `.num`, `.kbd`) moved into
  `@layer components` so Tailwind utilities can refine them; before, the
  unlayered CSS silently overrode classes such as `h-6` or `text-[11px]`.

**Trade-off:** About 100 kB of WOFF2 (Latin subsets load on demand by
`unicode-range`). Inter is slightly wider than Segoe UI, so some dense
labels were shortened and the default explorer width grew from 250 to
260 px.

## ADR-025: Analysis bars fold instead of wrapping
**Decision:** An analysis bar is one row of its primary settings followed by
*More settings ▾*. Controls never shrink. When a pane is too narrow for the
primary settings they fold, as a whole, into the same popover (then called
*Settings*), and unfold once the pane is 48 px wider than they need
(`lib/barFold.ts`).

**Why:**
* Every workspace opens split, so on a 1366 px laptop an analysis pane is
  400–550 px wide. A wrapping bar pushed the plot down by a variable amount;
  a horizontally scrolling one hid controls behind an invisible scrollbar;
  shrinking selects showed "F1" and "Pri" instead of their values.
* Folding keeps the plot area stable and every setting one click away, and
  it works for any combination of pane width, language and view without a
  per-view layout.
* The slack and the remembered width make the decision stable: the folded
  trigger is narrower than the unfolded one, so unfolding at exactly the
  measured width would overflow again.

**Trade-off:** In a narrow pane the primary settings are not visible at a
glance. Keeping each bar to the few settings changed while looking at the
result (field, wavelength, sampling) makes that rare.

## ADR-026: Below 1440 px the Inspector floats over the panes
**Decision:** Below a 1440 px window the Inspector is an overlay over the
analysis area, opened from the workspace bar or Ctrl+I and closed with Esc;
from 1440 px it is a docked column as before. The dock's default height
follows the window height (30 %, 180–300 px).

**Why:**
* On a 1366 px laptop the docked Inspector took 310 px, leaving the two
  analysis panes about 400 px each: their bars folded and the spot cells
  shrank to 100 px. Most of the acceptance scenario (radii, thicknesses,
  glass, aperture, optimisation) runs in the Lens Data Editor and the dock,
  not in the Inspector.
* Floating the Inspector over the panes, not over the dock, keeps the Lens
  Data Editor usable while the Inspector shows the selected surface.
* Docking from 1440 px keeps the established layout on desktop screens.

**Trade-off:** On a laptop the Inspector hides part of the right pane while
it is open, and it is one shortcut further away.

## ADR-027: An opt-in environment model referred to the system air
**Decision:** Temperature and pressure are modelled only when the user turns
the environment model on. Indices are then relative to the system air at its
temperature and pressure (wavelengths in that air); glass indices go through
absolute values (catalogue air at the glass's reference temperature, the
absolute Schott dn/dT model); the prescription is the 20 °C design and
expands once, before solves, with glass, spacer, housing and substrate CTEs.
The spacer expansion is an optimisation variable.

**Why:**
* Off by default keeps every existing project and frozen baseline
  bit-identical, and makes the extra physics a visible choice (System card
  row, info diagnostic) rather than a silent change.
* Referring indices to the system air keeps the catalogue convention and
  makes the reference conditions reproduce the catalogue exactly; a vacuum
  system (P = 0) then uses absolute indices without a special case.
* Expanding in the model (not in the compiled shapes) keeps every analysis
  consistent, since several of them read the prescription; solves see the
  system at its temperature, and freezing writes values back to 20 °C so the
  expansion is never applied twice.
* An effective spacer CTE is how passive athermalisation is designed (two
  materials realise the value), so it is the natural variable.

**Trade-off:** Temperatures are uniform: no gradients, no mount deformation
and no CAD expansion; those need a heat-conduction and, for deformations, a
structural (finite-element) model.

## ADR-028: A one-dimensional mount chain instead of a structural model
**Decision:** The mechanics are a tree of mount parts that expand freely
along the optical axis about their datums, each with its own CTE and
temperature. Surfaces are seated on parts at their vertices; glass-joined
surfaces move as a block from their seat, and the gaps between blocks are
whatever the placements leave. CAD parts are linked for their axial extent
only.

**Why:**
* For axial athermalisation (barrels, cells, re-entrant tubes, image-plane
  holders) the free axial expansion of each part is the dominant effect and
  has an exact closed form; summing it along the chain is what designers do
  by hand, so the model is checkable against analytic chain sums.
* It needs no meshing, no solver and no material data beyond a CTE, so it
  runs inside every compile and works in the optimiser and the temperature
  analysis without extra cost.
* Keeping E1's spacer rules for unseated gaps makes the tree an addition:
  a project without seats compiles exactly as before.

**Trade-off:** No radial expansion, bending, stress or temperature gradients
in parts, and no seats on folded (mirror or coordinate-break) systems. Those
need heat conduction (L1) and a structural finite-element model of the CAD
geometry (L2), which are kept for later.

## ADR-029: Tolerance allocation in the criterion's additive quantity
**Decision:** Inverse sensitivity maps the criterion to a quantity that adds
over independent small perturbations (c² for RMS criteria and the merit
function, −c for MTF), splits the budget between the nominal and the
specification equally over the unlocked tolerances, and scales each
tolerance's limits by root-finding on the real, compensated criterion. The
allocated limits are then used by the same run's Monte Carlo, whose yield is
the confirmation. Form errors are modelled as Zernike sag terms on the
toleranced surface (a standard or even-asphere surface becomes a Zernike
surface with the same base).

**Why:**
* RMS spot and wavefront errors of independent aberrations add in
  quadrature, and small MTF losses add linearly; an RSS of criterion changes
  (the estimate kept for the sensitivity table) over-counts near an
  optimum, where the criterion grows quadratically. In the additive quantity
  the "all at their limits" prediction is exact for orthogonal errors (the
  quadratic-merit benchmark).
* Equal shares need no cost model and are the textbook starting point;
  locking covers limits that are fixed by suppliers (glass grades) or by
  what a shop can do.
* Root-finding on the actual criterion, not on a linearisation, handles
  compensated, non-linear sensitivities; rounding toward zero keeps the
  applied limits inside the confirmed ones.
* Zernike sag on the existing surface reuses the exact intersection code of
  Zernike surfaces, so form errors are traced, not approximated by
  wavefront terms.

**Trade-off:** Equal shares are not cost-optimal, and the Monte Carlo
confirmation is only as good as its trial count (its interval is shown).
Biconic surfaces cannot carry form tolerances.

## ADR-030: Element drawings from engine data; catalogue absorption opt-in
**Decision:** The engine computes every number of an element (rim, edge
thickness, volume, mass, tolerances in ISO 10110 terms) and the UI only lays
the drawing out as an SVG, embedding the data as JSON. The catalogue internal
transmittance becomes bulk absorption only when the system's
`catalog_absorption` is on.

**Why:**
* The engine stays the only source of numbers (an invariant in DEVELOPMENT), and
  the same element data feed the drawing, the Inspector, the System card,
  the report and the CAD solids, which therefore agree (the exported solid
  volume equals the element volume).
* Embedding the data makes a drawing machine-readable and lets the tests
  check the round trip of the prescription values exactly; SVG prints to
  PDF in any browser, so no PDF library is needed.
* Absorption changes every intensity in every existing project that uses
  glasses with transmittance data (now including the built-in SCHOTT
  glasses); an explicit switch keeps old results and frozen baselines
  unchanged and makes the extra physics visible.

**Trade-off:** A user must turn the catalogue absorption on (the throughput
analysis offers it when data are available); drawings follow the
project's tolerances and leave unspecified ISO indications open rather than
inventing them.

## ADR-031: Importance sampling as a direction-space split
**Decision:** Importance sampling towards a detector (or a surface
aperture) sends K extra rays per scatter event at uniformly sampled points
of the target, weighted with the BSDF, and drops the regular scattered ray
when its direction falls into the target's cone. The fitted BSDFs (ABg,
Harvey–Shack) are normalised to the entered TIS at normal incidence.

**Why:**
* The two ray sets cover disjoint direction sets whose union is the whole
  hemisphere, so the estimate is unbiased without changing the regular
  sampler or re-weighting any ray (no multiple-importance-sampling weights,
  no change for scenes without a target); the aimed rays are traced fully,
  so baffles in the way and further events are handled by the same code.
* Uniform points on the target give a weight that varies little over a
  small detector, which is where brute force fails (one hit per few hundred
  rays in the acceptance benchmark; a sixtieth of the error with 1.8 % of the
  rays).
* Entering the TIS rather than A or b₀ keeps the fraction's meaning
  (diffuse reflectance, scattered part) the same for every model and role,
  and the energy balance at normal incidence exact.

**Trade-off:** Energy balances only in expectation with a target (reported
as added and dropped power); one target per run; Gaussian scatter, which
has no closed-form BSDF, is not importance-sampled. Error bars treat source
rays as independent, which holds for Monte Carlo sources and scatter, while
a deterministic pupil grid without scattering correctly reports zero.

## ADR-032: One crystal wave per trace, both waves summed in polarisation
**Decision:** The sequential trace follows one wave per uniaxial crystal (the
surface's `crystal_mode`). The polarisation analysis and the vector PSF trace
every combination of waves from the same launch rays and add their matrices
coherently, with the phase of their optical path difference on a plane
normal to the exit ray; *as prescribed* uses the set waves only.

**Why:**
* A sequential trace has one ray per launch; following both waves would
  split every ray at every crystal and change the shape of every analysis.
  Choosing the wave per crystal matches how a designer models a displacer
  (which beam goes where) and keeps all geometric analyses unchanged.
* Wave plates need both waves: their effect is the interference of the two.
  Summing the combinations' polarisation matrices gives the exact plane-wave
  result when the waves leave together, and the reported separation tells
  when they do not.
* The anisotropic face amplitudes come from Maxwell's boundary conditions
  (a 4 × 4 solve), so the isotropic limit reproduces the Fresnel and
  thin-film code exactly and the energy balance is checked directly.

**Trade-off:** 2^m traces for m crystals (at most 6 crystals summed); the
scalar throughput uses an isotropic Fresnel estimate at crystal faces; walk-off
is not part of the paraxial data.

## ADR-033: The advisor reports only evaluated gains, one parameter at a time
**Decision:** The design advisor's suggestions are one-parameter moves on a
copy of the design, each searched with a parabola fit on the squared merit
function; the reported gain is the best *evaluated* merit, never a model
prediction. Defocus is diagnosed as a focus error with the System card's
best-focus criterion, not as an aberration class.

**Why:**
* A suggestion the user applies must do exactly what it says. A
  sensitivity or Hessian prediction would be wrong for large moves (bending
  a reversed lens changes the spherical aberration by an order of
  magnitude), and the tests check the reported merit against a re-evaluation
  to 10⁻⁹.
* One parameter per move keeps each suggestion explainable ("bend this
  lens", "change this gap") and quick to undo; coordinated changes of many
  parameters are what the optimiser is for.
* At the paraxial focus most of the wavefront variance of pure spherical
  aberration is Zernike defocus, and a design optimised for RMS spot over
  field and colour sits away from any single field's Zernike focus. Calling
  either "defocus" would tell the user to refocus a design that is already
  at its best focus.

**Trade-off:** One-dimensional moves miss improvements that need two
parameters at once, and each move costs several merit evaluations (seconds
to tens of seconds on real-ray-aimed systems, in a background job with
cancel). Bending is defined at constant thick-lens power, so a focal-length
error needs the separate single-curvature move.

## ADR-034: Live image from chief-ray maps and per-channel PSFs, computed on demand
**Decision:**
* The live colour image is computed in the engine for every change. Each of
  the three channels is mapped through its own real chief-ray heights and
  blurred by its own monochromatic PSFs.
* Diffraction PSFs are used where their sampling holds the aberrations, and
  geometric PSFs where it cannot, or where the preview's pixels hide the
  diffraction structure.
* A per-tab channel lets a newer request stop an older render.
* The photo stays in the browser (IndexedDB) and travels with each request.

**Why:**
* Correctness comes before speed. The chief-ray map and per-wavelength PSFs
  reproduce the real-ray centroid of every wavelength (the benchmark), so
  the fringes on screen are the design's lateral colour and not an effect.
* The adaptive sampling and the geometric fallback keep the image right
  when a dragged radius defocuses by tens of waves. A fixed FFT grid would
  silently alias exactly then.
* Stopping stale renders matters more than raw speed: without it a
  full-quality render of several seconds would delay the next drag step.
  Only counters are kept, so the engine stays free of model state.
* The project file must not carry the user's photo (privacy, file size).
  The settings name it by a content hash.

**Trade-off:**
* Without a shared cache each step recomputes everything; the decoded photo
  is the only thing cached.
* Real-ray-aimed systems take seconds per preview.
* The preview's geometric PSFs omit diffraction where it is below half a
  pixel, and the full quality restores it.

## ADR-035: Limitations are "not applicable", and every analysis runs on every sample in the tests
**Decision:**
* An analysis that does not apply to a kind of system raises `NotApplicable`
  (API code `NOT_APPLICABLE`), and the UI shows it as information, not as a
  failure.
* A matrix test runs every analysis endpoint on every sample design. It
  accepts only finite results or `NOT_APPLICABLE`.
* A heavy live analysis gets a budget rather than an unbounded run time: the
  non-sequential trace's time limit.

**Why:**
* Bugs had been found one at a time, by hand, on one design. The first
  matrix run found five classes at once:
  * defaults that fail on whole families of systems;
  * unsupported field types;
  * energy lost at the image-circle edge;
  * analyses that are meaningless for a system but still compute;
  * run times of minutes.
* Telling a limitation from an error matters to the user: "this does not
  apply to mirrors" is an answer, "analysis failed" is a worry.
* The matrix discovers endpoints and samples from the code, so it grows with
  the program.

**Trade-off:** About three minutes more in the test suite. A time-limited
non-sequential result is a random subset with larger error bars (stated in
a note).

## ADR-036: Design space map on a shared process pool, starts from published designs, metrics from the normal analyses
**Decision:**
* The design space map (G3) runs every candidate in a separate process.
  * A shared `ProcessPoolExecutor` (`workers.py`) uses the spawn start
    method and CPU count − 1 workers.
  * It starts with the first job and stops after 5 minutes idle.
  * Each job cancels through a byte in a shared array that the workers
    inherit, read at every merit evaluation.
* Candidates start from closed-form thin-lens solutions (singlet,
  doublets) and from published prescriptions normalised to f = 1 (Geiser
  triplet, Kidger's Petzval, the double Gauss of US 2,784,643), with the
  crowns and flints replaced. They are optimised by the normal local
  optimiser with a fixed budget per topology.
* Every metric is the normal analysis at the UI's default settings: spot
  diagram, diffraction MTF, field curvature and distortion, elements and
  default tolerances.
* The engine computes the Pareto front (exact non-dominated set) for
  whatever objectives the view asks for.
* The merit function's RMS spot and the automatic apertures trace all
  fields of a wavelength in one call (`trace_fields`).

**Why:**
* NumPy ray tracing holds the GIL much of the time: threads gave no
  parallelism (G2 showed it). Processes scale with the cores, and spawn is
  the only start method on Windows.
* A shared array needs no manager process and no inter-process call per
  check. The optimiser checks the flag at every evaluation, so a cancel
  takes effect within one evaluation.
* Published designs are good basins for their topology. Scaling them and
  substituting glasses gives sensible starts at any focal length without a
  lens-design expert system. Random starts mostly fail for six elements.
* Metrics from the normal analyses keep the map honest: an opened design
  shows the same numbers. The tests compare them to the analysis endpoints.
* One Pareto implementation (in the engine) keeps the front exact and
  tested. The view never decides dominance.
* Batched fields were bit-identical on every sample and made a merit
  evaluation 2.4× faster. That speeds every optimisation and tolerance run,
  not just the map.

**Trade-off:**
* The map shows what a fixed effort reaches, not converged optima. Most
  runs end at their budget.
* Results are session data: they are not saved in the project. The
  specification is saved.
* Without prices in the built-in glasses, the default cost axis is glass
  mass. An AGF catalogue supplies relative prices.
* About 110 MB of memory per worker while the pool is alive.
* A full run of all six topologies (120 designs) takes about 10 minutes on
  6 cores. The default leaves out Petzval and double Gauss.

## ADR-037: Stock lenses as fixed prescriptions; vendor data imported by the user; build by first order, third order and real rays
**Decision:**
* A stock lens is a fixed spherical prescription with its clear aperture as
  a fixed semi-diameter.
* Vendor parts enter only through files the user imports: per-part ZMX
  files and CSV. They are kept in the browser.
* OptiCore ships a generic library of its own designs at standard focal
  lengths and diameters in several glasses.
* Systems are built by enumerating stock combinations:
  * the first-order solution is exact and vectorised;
  * a vectorised third-order ranking chooses the real-ray prescreen;
  * the best are optimised only in their air gaps, on the G3 process pool.
* Matching places stock lenses at the replaced element's principal planes
  and reoptimises the gaps with the project's merit function.

**Why:**
* The vendors' catalogues are their data. ADR-015 already keeps
  manufacturer glass data out of the program, and the same holds for lens
  catalogues. Per-part ZMX files are what vendors publish for download, and
  the ZMX reader already exists.
* A generic library makes the feature useful at once, for concept work and
  for tests, without pretending to be a vendor's catalogue. Its rules are
  stated and reproducible.
* Solving the gaps for the first-order target leaves no free first-order
  parameter for two lenses. Hundreds of thousands of combinations reduce to
  a few thousand checks in about a second. The third-order sums are exact
  for their order and equal the engine's own; real rays decide the final
  ranking.
* Fixed clear apertures make vignetting by a too-small part real, not
  hidden.

**Trade-off:**
* Three-lens builds sample the triples.
* Only spherical stock lenses.
* The stop is at the first lens in builds.
* Generic parts must be replaced by real vendor files before ordering.

## ADR-038: Aim points in placements, a Gaussian beam source kind, spectra from the engine
**Decision:**
* A placement may store an aim point. The engine turns it into the first
  two angles (a = atan2(−d_y, d_z), b = asin(d_x)), and the third stays the
  roll.
* The UI edits directions as angles, as a direction vector (converted to
  angles) or as an aim point, and shows the resulting global direction.
* A Gaussian beam is a source kind with waist, M² and waist position, not a
  combination of shape and angular settings.
* Spectra are generated by the engine (blackbody, Gaussian line, flat) and
  stored as ordinary wavelength lists.

**Why:**
* Euler angles about local axes were the only way to set a direction, and a
  user could not tell how to point a beam. An aim point is how people think
  about pointing. Stored in the model, it keeps a source pointed at its
  target when the source or the design moves.
* ADR-017 rejected device presets because they hide physics. A Gaussian
  beam is a physical model with its own parameters, not a device:
  * the waist position correlates positions with directions, which no
    combination of the independent spatial and angular laws can express;
  * M² generalises it to real lasers;
  * the divergence now comes from the engine, not from a UI button.
* Generated spectra stay plain wavelength lists, so the trace, the files and
  older projects do not change.

**Trade-off:**
* Directions edited as vectors or aim points must be converted to angles
  for the gimbal-lock case (a vector along ±x); the engine handles it, and
  the roll is then about the aimed axis.
* The Gaussian beam stays a ray ensemble: no interference, no diffraction
  (POP does that).
* Photometric units, IES files, ray files, polarised sources and
  quasi-random sampling are still open (ROADMAP).

## ADR-039: Optimisation that cannot quietly make the image worse
**Context:** The cell-phone sample (US 7,535,658) was optimised with the
wizard. The merit function improved by 26 %. The pictures looked no
better, and the numbers showed why:
* distortion went from 3.2 to 9.8 %;
* lateral colour from 0.9 to 2.3 µm;
* the corner illumination from 53 to 48 %;
* the field of view shrank by 1.7°.

Reproducing the run found three causes:
* the RMS wavefront operand used only the primary wavelength;
* the wizard's 1 mm edge default (sized for 25 mm lenses) fell on the 0.4 mm
  IR filter, where no variable could meet it. That one constant was 94 % of
  the merit function;
* nothing held distortion or the field of view.

The wizard's other goal, the RMS spot, crashed (`shapes (12,) (731,)`).
After the crash was fixed, that run made the spot four times worse
(12 → 52 µm) while the merit function improved by 2 %, to serve L1's edge
(0.86 mm against 1 mm).

**Decision:**
* **Merit function:**
  * every operand keeps its residual count when it fails;
  * targets above 0 of `rms_spot` and `rms_wavefront` are honoured (a spot of
    a given size);
  * `rms_wavefront` with all wavelengths is polychromatic against the
    primary chief ray's reference sphere, and its reference (centroid or
    chief) is honoured;
  * `mtf` with all fields averages them;
  * a new one-sided `max_distortion` operand.
* **Engine reports:**
  * the image-quality operands that got worse (`objective_worse`);
  * the targets no variable can change (`fixed_operands`, flagged `fixed` in
    the breakdown);
  * the variables that change nothing (`inert_variables`).
* **Engine robustness:**
  * an error inside the search returns the best design so far (status
    `error`);
  * global and multistart searches bound curvatures by the clear aperture;
  * the image-height solver keeps the first branch (warm start, line search,
    continuation from the axis).
* **Before/after numbers:** `analysis/summary.py` and `/optimize/compare`
  give spot, MTF, distortion, colour, field of view, illumination, chief-ray
  angle, length and edges before and after, flagged by documented
  thresholds. The optimisation result shows them in place of the
  RMS-spot-only table, and leads with the change of the image-quality
  operands, not only the merit function.
* **Wizard:**
  * the defaults scale with the smallest lens and are never stricter than
    the design is now;
  * plates get no edge target;
  * lens-to-lens gaps get a centre bound;
  * for the sharpest-image goals, *distortion at most* (at the current value,
    for off-axis systems) and the focal length are kept by default;
  * *total track at most* is offered;
  * the beam goal warns when the detector is not anchored to the image
    surface;
  * the goals include a spot of a given size and a beam of a given D4σ
    diameter on a detector (the beam-to-sensor case).
* **Quick focus** reports the RMS per field and names the fields it made
  worse, since it minimises the field-weighted mean.

**Why:**
* A least-squares merit function mixes units. A violated constraint in mm
  outweighs a spot in µm, so a missed constraint at the start wins over the
  image. Engineers learn this the hard way in every lens design program.
  OptiCore removes the trap from its defaults and reports it when it
  happens.
* The merit function is not the image. Showing the numbers it does not
  contain, from the normal analyses and flagged, answers "is the image
  better?" without the user opening five analyses.
* Every change was checked against analytic cases from the simplest use
  (VALIDATION):
  * a spot of a given size behind an ideal lens;
  * the best-form singlet;
  * a Gaussian beam focused by one and two lenses to a target diameter;
  * the polychromatic wavefront's identities.

**Trade-off:**
* Constraints stay penalties. A constrained solver (trust-constr, SLSQP)
  would give up the Gauss-Newton efficiency of `least_squares` on hundreds
  of residuals. Instead the defaults avoid starting violated, and the
  reports show the effect.
* Saved projects with `rms_wavefront` and no wavelength now evaluate
  polychromatically, with their (default centroid) reference. Their values
  change, and so do tolerancing runs with the RMS wavefront criterion on
  polychromatic systems. Choose a wavelength to get the old behaviour.
* The comparison costs about 1.5 s after each run (two summaries).
* The sample's sharpness was also low before any optimisation (RMS 13–24 µm
  off axis). The cause was its transcription, not the design (ADR-040).

## ADR-040: Reference designs from the primary source; the cell phone lens is the patent's Example 1
**Context:** The cell phone sample was entered from the ray-optics
documentation example of US 7,535,658. Off axis it was poor: RMS spots of 13
to 24 µm and 3.9 % distortion. Its optimisation results (ADR-039) therefore
started from a weak lens. Reading the patent (FIGS. 10, 11, 28 and 29 on
Google Patents) showed five differences in that transcription:
* R5 is 5.694 instead of 5.794;
* A5 of the fifth surface is 1.575e-3 instead of 5.175e-3 (digits swapped);
* the stop is at the first vertex, whereas the patent puts it 0.20 mm behind
  it ("the minus sign means the stop St is located on the image side of the
  surface S1");
* the cover glass is 0.40 mm instead of 0.30 mm;
* the aperture is f/3.5 instead of F/2.8.

The patent's aspheric equation confirms the conic convention K = 1 + k that
was already used.

**Decision:** The sample is now Example 1 as printed. The patent's own
numbers check it:
* the FIG. 28 conditional values;
* TL and F/#;
* f and bf, which agree to the rounding of the printed indices;
* the FIG. 29 distortion and astigmatism curves.

f3/f separates the two R5 readings: 5.07 in the patent, against 4.86 with
R5 = 5.694. The ray-optics transcription stays available as
`cell_phone_lens("ray-optics")` for the check of the engine against
ray-optics' printed output, and for the tests that reproduce the
optimisation run of ADR-039.

**Why:** A reference design is only a reference if it is the published one.
A comparison with independent software checks the engine, not the input, so
each serves its own test.

**Trade-off:**
* Projects saved from the old sample keep their own data.
* The optimisation examples and numbers in ADR-039 and VALIDATION refer to
  the ray-optics transcription, which is the design that run optimised.
* The patent was read from its drawings (images). Values that the patent's
  own numbers cannot confirm, such as most aspheric coefficients, rest on
  that reading. The only difference in them was confirmed at full
  resolution.

## ADR-041: The optimiser's evaluations on the process pool; limits for colour, illumination and chief-ray angle; sensor pixels in the live image
**Context:**
* A cell-phone optimisation took 70 s for 400 evaluations standalone and
  about four times longer in the UI. There the evaluations share the server
  process's interpreter lock with the views that follow the live preview.
* The comparison table (ADR-039) flags lateral colour, corner illumination and
  the chief-ray angle, but nothing could hold them.
* The live image's whole frame (14.6 µm pixels for the cell-phone lens)
  cannot show a sensor's sharpness.

**Decision:**
* **Parallel Jacobian.** The finite-difference Jacobian runs on the shared
  process pool (`optimize/parallel.py`), with SciPy's '2-point' steps, so the
  Jacobian equals the serial one. When the pool is used, the solver's trial
  steps and the closing sensitivities run there too. It is used when it pays:
  at least 3 variables, an evaluation of at least 20 ms and an idle pool.
* **Preview rate.** The live preview updates at most every 1.5 s.
* **New operands.** One-sided `max_lateral_color` (µm),
  `min_relative_illumination` and `max_cra`. They share their computation with
  the design summary. The wizard offers all three with the current values, and
  holds lateral colour by default for the sharpest-image goals.
* **Field tolerance.** Image-height fields are solved to 10⁻¹² mm (10⁻⁹
  before), so a Jacobian step sees the field move.
* **Sensor pixels.** The live image can show *1 px = one sensor pixel*, from
  the system's sensor model or a chosen pitch.

**Why:**
* Speed decides how often an engineer optimises. On a 12-thread machine, the
  2000-evaluation cell-phone run in the UI took 193 s instead of about 700 s.
* Running every evaluation in a worker makes the speed independent of what the
  views compute meanwhile.
* The comparison should not only report what got worse: the user must be able
  to forbid it. The units are chosen so that a small excess counts against a
  spot of a few µm.

**Trade-off:**
* The pool's first start costs a few seconds (spawned workers import the
  engine).
* Global (differential evolution) runs stay serial in their population, though
  each evaluation runs in a worker.
* A design-space map running at the same time makes the optimiser serial
  rather than queue behind it.

## ADR-042: Exact limits (augmented Lagrangian) with prices, trade-off curves, and the image between the fields
**Context:**
* Every optical optimiser we know of puts limits into one weighted merit
  function. Weights and units then decide how much image a limit may cost: a
  0.15 mm edge violation outweighed a spot of a few µm (ADR-039), and a focal
  length "held" by a weight drifts as the weights change.
* An engineer cannot ask the merit function what a limit costs. The answer
  ("allow 0.1 mm more length and the spot gets 5 % smaller") decides
  specifications, but it needs many hand-made runs.
* The merit function sees only the fields it is given. The image can fall
  apart between them without any number showing it.

**Decision:**
* **Exact limits by default.** Bounds and first-order targets are
  constraints met to a tolerance by an augmented Lagrangian
  (`optimize/constrained.py`) around the same bounded least-squares solver.
  The merit function holds only the goals. An operand's `role` (auto / goal /
  limit) can be set, and `constraints: "penalty"` keeps the weighted merit
  function.
* **Feasibility first.** A design that meets the limits beats any that does
  not, in the best-design choice, in glass substitution, and across
  multistart runs. A run that cannot meet them says so (`infeasible`) and
  returns the least violating design.
* **Prices.** Every limit reports its Lagrange multiplier, estimated at the
  design returned from the closing sensitivities' differences (no extra
  evaluations), as the merit predicted if it were relaxed by a step. A
  stationarity measure marks prices taken away from an optimum.
* **Trade-off curves** (`optimize/tradeoff.py`). One click re-optimises a
  limit at nine values on all cores. Each point is an applicable result.
* **Field profile.** The comparison traces the RMS spot at 11 field points and
  flags a sampling gap.
* **Global search.** Differential evolution evaluates each generation on the
  process pool (deferred updating), and polishes with the exact limits.

**Why:**
* Limits that hold exactly make the optimiser trustworthy: the focal length
  is 5.5870700 when asked for 5.58707, whatever the weights. In the test runs
  the image was also better (cell-phone lens: 4.96 against 5.05 µm with the
  same budget).
* Prices and curves turn the optimiser from a black box into a design-trade
  instrument. The cost of every specification is visible.
* The field profile closes the commonest hidden failure of a well-optimised
  lens.

**Trade-off:**
* A constraint that cannot be met makes the run raise ρ until it gives up
  (≈ 15 outer iterations). The weighted mode stays available.
* Prices are first order. The curve shows how far they hold, and costs nine
  optimisations.
* The stock-lens generic library keeps the weighted set-up it was generated
  with, so its data stay reproducible.
* Global search now updates its population per generation, so seeded results
  differ from earlier versions.
* Projects saved before this have no `constraints` field. They open with exact
  limits; *Limits: weighted* in the Merit Function tab restores the earlier
  behaviour.

## ADR-043: Conventions fixed by a code audit (field directions, the launched pupil, active operands, results that belong to their design)
**Context:**
* After an external report of five defects, five audits checked the code by
  invariance and analytic references and reproduced about 60 defects. Most
  came from four implicit assumptions:
  * the field lies along +y;
  * a pupil may be recomputed per wavelength;
  * an operand with weight 0 is inactive;
  * an engine answer can be written into whatever design is open when it
    arrives.

**Decision:**
* **Field directions.** Every analysis and operand that has a field direction
  follows the field's azimuth. Tangential means along the field, and
  sagittal across it. Angle fields are tan components: their size is
  atan(hypot(tan x, tan y)) (`fields.field_size`, `field_along`). Fields along
  +y give exactly the old numbers.
* **One pupil.** The aperture is evaluated at the primary wavelength, and
  every wavelength is launched through that pupil: analyses, paraxial data
  and diffraction sampling.
* **Active operands** are `enabled and (weight > 0 or role == constraint)`, in
  both constraint modes. Their order numbers every result.
* **Tolerancing follows the optimiser's constraint mode.** With exact limits
  the criterion is the goals' merit, and the limits are reported apart.
* **Results belong to their design.** Asynchronous writes check the project
  and, where they depend on it, the optical system (`store/designGuard.ts`).
  Opening a project cancels the previous one's runs. References are
  maintained in one module (`lib/references.ts`).
* **Polarisation after mirrors** is read in a mirror-image output basis.
  Rotation is taken modulo the global phase.
* **Merit quadrature** arm counts are multiples of 4.

**Why:**
* Each defect gave a plausible number, so none could be seen from the
  result. Invariance tests (rotate the system, scale it, change the field
  type) catch whole classes of them. They are now regression tests.

**Trade-off:**
* Merit values of RMS operands change slightly with the arm count: 12 arms
  instead of 10 at the default 4 rings.
* MTF T/S and fans of fields off the y axis change meaning: they were the
  y and x cuts. They now follow the field.
* Projects whose stored analysis settings pointed at a removed field keep
  field 0 rather than the wrong field.

## ADR-044: The serial Jacobian takes the pool's steps; generic achromats by an F/# solve; built-in PMMA from Beadie 2015; CRA to the local normal; Gaussian sources in their medium
**Context:**
* The code audit of ADR-043 left four items open: the serial weighted-limits
  Jacobian's step, the polymer Abbe numbers, the chief-ray angle on a curved
  image surface, and the Gaussian source divergence in a medium. Each was
  checked against an analytic or independent reference, and each was
  wrong.
* Fixing the step showed why the generic achromats depended on it: their
  runs ended on the 600-evaluation budget in a curved valley (the focal
  length was a weighted goal), so any detail of the finite differences moved
  the design.

**Decision:**
* **One finite-difference rule.** Every Jacobian, serial or on the pool,
  in both constraint modes, uses `parallel.fd_steps`: h = 10⁻⁷·max(1, |x|),
  adjusted to the bounds. SciPy no longer chooses steps.
* **Generic achromats.**
  * The last curvature is an F/# solve, so the focal length holds by
    construction. The optimiser runs to convergence (at most 3000
    evaluations), and a lens that does not converge is left out.
  * The library is regenerated. Its achromats are now the converged optima,
    independent of the pool and of the steps.
* **Built-in PMMA** is the formula of Beadie et al. 2015 (accuracy
  < 2·10⁻⁴). Polycarbonate and polystyrene keep Sultanova's one-term fit,
  the only formula data in the CC0 database. Their source text states nd,
  Vd and the other sample's value.
* **The chief-ray angle** (summary, `max_cra`) is measured against the image
  surface's local normal at the landing point.
* **Gaussian beam sources** diverge by M²λ/(π n w₀) in the medium they
  emit into. The beam description is in air and says so.

**Why:**
* Each of these gave a plausible number. A design that depends on the
  finite-difference step is not an optimum, and a library made of such
  designs cannot be reproduced.

**Trade-off:**
* All 99 generic achromats change.
  * The radii change by 0.04 % at the median. The weakly bound back radius
    of the long achromats changes by up to 55 %.
  * On the former generator merit, none is worse and nine are better by
    1–1.8 %.
  * Generation takes 75 s instead of 585 s.
  * Projects that inserted one keep their copy.
* Projects using PMMA get the new data. The old one-term fit can be entered
  as a custom material: Sellmeier B = 1.1819, C = 0.011313 µm².
* Weighted-limits runs move slightly where the step changed (curvatures).
  Results now match the pool's.

## ADR-045: A warning when paraxial ray aiming misses the stop
**Context:**
* Paraxial aiming launches rays through the paraxial entrance pupil. In a
  wide-angle lens with an aberrated pupil they can miss the stop points
  they stand for. Every pupil-dependent result is then wrong, and nothing
  said so.

**Decision:**
* `PARAXIAL_AIMING` (`analysis/evaluate.aiming_check`). With paraxial
  aiming, the chief and marginal rays of every field are traced to the
  stop, and the largest miss is measured as a fraction of the stop radius.
  * Above 5 % this is a warning, above 1 % a note.
  * The fix offered is real aiming.

**Why:**
* The thresholds come from the samples. A 5–9 % miss changed edge RMS spots,
  relative illumination or distortion by 6–26 %. A 1.8 % miss changed them
  by 0.3 %.

**Trade-off:**
* The double Gauss and Geiser samples (6.0 %, 8.9 %) show the warning, and
  Petzval and Eiffel show the note. They keep paraxial aiming, because
  their source comparisons use it.

## ADR-046: Vignetting factors per configuration; an evaluation belongs to its project
**Context:**
* A published zoom lens (Canon JP2015094867A, 17–119 mm) was reproduced at
  its three zoom positions. Its published effective diameters vignette
  differently at each position. Vignetting factors were per field only, so
  the template opened with eight clipped-ray warnings in some
  configuration.
* Opening another project left the previous project's evaluation (layout,
  surface profiles, messages) on screen until the new one arrived. For a
  large lens under load that lasted 15 s.

**Decision:**
* Configuration operands can name a field (`field`, an index) for the
  parameters `vdx`, `vdy`, `vcx`, `vcy`, validated to their ranges.
  * *Set vignetting* with configurations computes every configuration and
    fills these rows.
  * The field table shows and edits the active configuration's value. So
    do the aperture value, temperature and pressure fields and the
    explorer, which used to show the base value.
  * Field removal drops and renumbers the rows.
  * *Single configuration* bakes them in, and now also temperature and
    pressure, which it used to drop.
* `openProject` clears the evaluation as well as the analyses. An
  evaluation answer whose key is no longer current is discarded.

**Why:**
* Zoom lenses are designed with vignetting that changes with the zoom
  position.
* A view must never show another project's results.

**Trade-off:**
* The schema gains an optional key, `field` on configuration operands. Older
  files load unchanged, but a file that uses field rows needs this version.
* After opening a project, the layout is empty until its first evaluation.

## ADR-047: Fibres beyond the step index: radial profiles, dispersion and cross-sections, each with a library example
**Context:**
* Fibres were step-index only (exact vector modes, cut-off, MFD).
* The request was optical fibres first, with every function shown by an
  example kept in the library.

**Decision:**
* **Radial profiles** (`wave/fibreprofile.py`): step, graded (power law) and
  layered rings.
  * Exact transfer of (ψ, ψ′) for piecewise-constant profiles.
  * Finite differences with Richardson extrapolation for graded profiles.
  * The step profile keeps its exact vector solver.
* **One index model**: a constant offset over a dispersive cladding. Modes,
  cut-off and dispersion all use it, including the step profile's cut-off
  (1315.2 nm instead of 1313.9 nm from the constant-index formula for the
  single-mode example).
* **Dispersion** from n_eff on a five-point stencil in wavelength. It works
  for any profile. A tracked root counts only with m − 1 radial nodes.
* **The LP_l1 cut-off** from the edge function at n_eff = n_clad, scanned
  from long to short wavelengths. A cut-off beyond the range is reported as
  none, and one outside the cladding's data as extrapolated.
* **Cross-sections** (`wave/fibre2d.py`): an own full-vector finite-difference
  solver (Yee mesh, averaged permittivity tensor, PML, quadrant symmetry) on
  SciPy's sparse eigensolver, so no new dependency. It runs as a background
  job on the FDTD job runner; its result is bound to its settings and dropped
  when another project opens.
* **Examples**: four library templates (step, graded, trench-assisted,
  six-hole PCF) open their view with stored settings. Their tests send exactly
  those settings and compare with independent results. The frontend's request
  builder is checked against a fixture written by the engine.

**Why:**
* Graded-index and layered fibres and PCFs are the common designs. Without
  dispersion and cut-off there is no fibre design.
* Independent references exist for each part: the infinite parabola,
  Kummer's function, the exact step-index and vector solutions, and the
  multipole method.

**Trade-off:**
* Graded and layered profiles have scalar modes, without polarisation
  splitting.
* The uniform 2D mesh is limited to 700 cells per side.
* Refinement costs about 5 × the time: the PCF example takes about 70 s.
* The core shares the cladding's material dispersion.

## ADR-048: Photometry and colorimetry from the CIE tables; lighting examples
**Context:**
* Lighting design needs lumens, lux and the colour of light. The tracer
  carried only watts.
* The CIE colour-matching functions cannot be derived; they are measured
  data.

**Decision:**
* **CIE data:** the CIE datasets (1931 2° colour-matching functions, D65,
  scotopic V′) are the CIE's published files, kept
  unmodified with their CC BY-SA 4.0 attribution and MD5 sums. Git keeps
  them byte for byte (`-text`). Illuminant A comes from its formula.
* **Module:** `photometry/` gives luminous flux (photopic and scotopic),
  efficacy, XYZ, x/y/u′/v′, CCT and Duv by the definition (nearest Planckian
  radiator in CIE 1960 uv, the locus from the same tables), and sRGB.
* **Detectors** report lux maps, X, Y, Z maps, a true-colour image and
  standard errors for the flux and colour. **Sources** report the light of
  their spectrum.
* **UI:** the Non-Sequential view chooses irradiance, illuminance or true
  colour for the detector map (a display option, outside the analysis key).
  The sources editor shows each source's light.
* **Examples:** an LED downlight (checked against view factors) and additive
  RGB mixing (checked region by region). Their free-space systems revealed
  three analyses that crashed or returned empty values instead of saying
  they do not apply (image simulation with only an axial field, vector PSF
  and chromatic focal shift without a focus); these and the POP sampling
  limit now report that they do not apply.

**Why:**
* The CCT by its definition, rather than an approximation (McCamy, Robertson
  tables), is exact to the data. It recovers T for Planckian radiators to
  1e-7.
* Colour from a Monte Carlo trace is noisy. Without its standard error a
  detector's x, y or CCT would look more certain than it is.

**Trade-off:**
* The colour standard errors assume independent rays, and the wavelength
  split is stratified, so they are upper bounds.
* No colour rendering index: the CIE 13.3 test colours would need another
  dataset.

## ADR-049: Rigorous coupled-wave analysis of 1D gratings with Li's factorisation
**Context:** Gratings (beam splitters, wave plates, resonant filters) need
rigorous diffraction efficiencies. Scalar theory fails near and below the
wavelength.

**Decision:**
* **Own RCWA** (`wave/rcwa.py`) in Rumpf's S-matrix formulation. It is stable
  for thick and lossy layers and handles conical incidence.
* **Li's factorisation:** Laurent's rule for the field components parallel to
  the interfaces, the inverse rule for the normal one.
* **Profiles:** relief profiles as lamellar slices.
* **Outputs:** per-order efficiencies and angles, zeroth-order phases and
  retardance, a convergence estimate, and sweeps.
* **View:** a Grating (RCWA) view with a layer editor and the structure
  drawing.
* **Examples:** three library examples, each checked against an independent
  result: scalar theory, effective-medium theory, and the resonance theorem
  with the slab mode.

**Why:**
* RCWA is the standard method for periodic structures and is exact apart
  from truncation.
* The S-matrix form avoids the overflow of the transfer-matrix form.
* The gap with k_z = 1 in every order avoids singular gap modes at Wood
  anomalies.

**Trade-off:**
* One-dimensional periodicity only. Crossed gratings and metasurfaces need
  the 2D formulation (next).
* Staircase profiles converge with the number of slices.
* The cost grows as (2M + 1)³ per slice.

**Runs on the process pool.** The endpoint sends the point, the convergence
check and the sweep (in chunks) to the shared process pool (`workers.py`).

Its workers use one BLAS thread. OpenBLAS's default threading made the small
dense matrices of RCWA (about 100 × 100) slow whenever other work ran, for
example the test suite or concurrent analyses. Measured with 12 cores under
load:

| Operation | One thread | Default threads |
|---|---|---|
| Inverse of a 102 × 102 complex matrix | 1.2 ms | 0.68 s |
| 1024² complex matrix product | 0.38 s | 0.13 s |

The engine's own BLAS threading is therefore left as it is (large products
gain from threads), and RCWA uses the pool. The guided-mode resonance
example's 81-point sweep takes 0.5 s on the pool; in the loaded server it took
more than a minute.

**Correction (mirrored asymmetric profiles).** The solver works in exp(+jωt),
where the medium is the pointwise conjugate of the physics' ε(x). The first
version conjugated the Toeplitz matrix of ε instead of building the Toeplitz
matrix of conj ε(x) (= T(ε)ᴴ, coefficient n is conj c₋ₙ). For a symmetric
profile the two agree. For an asymmetric one, such as a sawtooth, the first
version computed the mirror image x → −x: a blazed grating thick at +x sent
its light into the −1 order instead of +1.

* Energy, reciprocity and the symmetric examples could not see this, since
  they hold for the mirror image as well.
* The test now checks the direction against scalar theory (a prism deflects
  towards its base), and that the mirrored structure at the mirrored angle
  gives the mirrored orders.
* The three library examples are symmetric and unchanged.

## ADR-050: Crossed gratings and metasurfaces by 2D RCWA with Li's fast Fourier factorisation
**Context:** Metasurfaces, photonic-crystal slabs, fan-out gratings and
subwavelength antireflection structures are periodic in two directions. The
1D solver (ADR-049) cannot model them.

**Decision:**
* **Own 2D RCWA** (`wave/rcwa2d.py`): the same S-matrix formulation with 2D
  convolution matrices and Li's 1997 fast Fourier factorisation. Patterns
  are shapes (rectangles, ellipses; rotated; across the cell edge) with
  analytic Fourier coefficients.
* **Physical order labels.** The orders are labelled physically. The
  convolution matrices are the conjugated physics Toeplitz matrices, so no
  relabelling is needed. Building the 2D code this way exposed the mirror
  error of the 1D solver (ADR-049, correction).
* **Structured algebra.** The half-spaces and uniform layers are kept as
  2 × 2 blocks of diagonals, and only the incident wave's response is
  assembled. This made a run 3–8 times faster than plain star products.
* **API.** The same endpoint and view: `period_y_um` makes the grating
  crossed. 1D profiles become stripes along y, so 1D designs can be
  combined with patterns.
* **Validation.** Every request is validated before any run goes to the
  pool. A refused request once left its convergence run computing for
  minutes.
* **Examples.** Three library examples, each checked against an independent
  result:
  * scalar theory (checkerboard fan-out);
  * Dykhne's exact theorem (checkerboard antireflection);
  * the resonance theorem of symmetric lossless slabs (photonic-crystal
    membrane).

**Why:**
* Li's factorisation is the correct rule for cells made of axis-aligned
  rectangles, and it reduces exactly to the 1D rule for stripes.
* Analytic shape coefficients avoid rasterising the Laurent matrices.
* The reduction to 1D, the thin-film limit, energy, the 90° rotation,
  reciprocity and translation invariance hold to rounding or to truncation.
  Each would expose an indexing, sign or factorisation error.

**Trade-off:**
* Curved and rotated boundaries are staircases in the inner inverse rule.
* A normal-vector factorisation would converge faster for round holes. It
  is not implemented; the membrane example uses square holes, whose
  resonance converges to 10⁻⁴ µm by 8 × 8.
* Touching corners converge slowly. The checkerboard's zeroth order is
  6 × 10⁻³ at 10 × 10 against scalar zero, and the view's convergence
  estimate flags it.
* The cost grows as N³. At most 961 orders, about 25 s per run on one core.
* Rectangular cells only.

## ADR-051: Metals in the FDTD by a Drude current fitted exactly at the wavelength; directional sub-cell means; plasmon source
**Context:** Plasmonics needs metals (Re ε < 0) in the FDTD, which rejected
them. The solver is monochromatic, with a CW source and the DFT of the
steady state.

**Decision:**
* **Drude current per cell.** A cell with Re ε < 1 gets ε∞ = 1 and a Drude
  polarisation current (auxiliary differential equation). Its ω_p and γ are
  solved so that the discrete scheme's steady-state permittivity at the
  source frequency equals (n + ik)² exactly. A Drude–Lorentz description of
  a material therefore reduces to its ε at the wavelength; separate Lorentz
  poles would add nothing to a monochromatic run.
* **Directional sub-cell means.** Arithmetic for Ex; for Ey and Ez,
  harmonic along the component and arithmetic across it.
* **Plasmon source** for p polarisation, with the media read from the
  structure. The sheet carries E_y ∝ H_x/ε.
* **Propagation-constant fit** for guided sources.

**Why:**
* The exact discrete fit removes the time-stepping dispersion error from the
  metal. A metal half-space then reflects within 3 × 10⁻⁴ of Fresnel at 30
  points per wavelength.
* A plasmon depends on the normal field at the interface. With arithmetic
  means its index came out 3.7 % too high; with a plain staircase it was
  1.1 % too low. Directional means give 1.3 × 10⁻⁴ and an attenuation within
  0.2 %.
* An H_x-shaped magnetic sheet launches the wrong field in the metal, where
  ε < 0. That gave a growing "attenuation" for silver.

**Trade-off:**
* Monochromatic only; a broadband pulse would need the full Drude–Lorentz
  poles.
* Metals need small cells for thin films (two skin depths: 1.6 × 10⁻² at 30
  points per wavelength, 1.2 × 10⁻³ at 70).
* The directional means also change dielectric p-polarised results
  slightly. All earlier FDTD tests pass unchanged.
* Painting sub-cells in order also corrects cells where two shapes meet.
  The old sequential fraction mixing was not exact there.
* The rotationally symmetric solver keeps dielectrics only.

## ADR-052: Interferograms with phase-shifting recovery; a spectrometer analysis from real rays
**Context:** Optical testing and spectroscopy are everyday optical
engineering tasks.
* Testing: the fringes a surface or lens shows in an interferometer, and
  the wavefront recovered from them.
* Spectroscopy: calibration, dispersion and resolution.

**Decision:**
* **Interferogram view.**
  * The traced wavefront against a tilted perfect reference sphere, in
    single or double pass.
  * N-step phase shifting with flood-fill unwrapping, and the recovered
    wavefront shown beside the computed one with their difference.
  * The sampling (phase step per pixel) is reported.
* **Spectrometer view.**
  * Real rays at a sweep of wavelengths (system copies with the sweep as
    their wavelengths).
  * The centroid track gives the calibration and the dispersion direction.
  * Linear and reciprocal dispersion, the geometric resolution, and the
    first grating's Rayleigh resolving power |m|Gw.
* **Examples.**
  * A paraboloid tested at its centre of curvature, against the exact
    double-pass path.
  * A grating spectrograph with ideal optics, against the grating equation.

**Why:**
* Recovering the computed wavefront by phase shifting validates the fringe
  model and the unwrapping. It also shows when the fringes are too dense.
* The paraboloid's classic r⁴/(4R³) holds at the mirror height; in pupil
  coordinates the exact path is the honest reference. The engine matches it
  to 2 × 10⁻⁹ waves.
* Real rays make the spectrometer analysis valid for any layout: gratings,
  prisms, folded and tilted systems.

**Trade-off:**
* No intensity effects. Fringe visibility is a parameter, not a
  coherence or polarisation calculation.
* Unwrapping needs less than π per pixel.
* The spectral resolution is geometric (diffraction is given only as the
  grating's mN).
* The slit is a point; slit width and the detector pixel are not convolved.

## ADR-053: Coating analyses shared by the editor and the designer; a built-in library with stated specifications
**Context:** The thin-film coating editor showed only R and T of three
built-ins. One of them (VCOAT_550) reflected 4.3 % at its own design
wavelength. Coating engineering needs more than the spectrum:
* phase and group-delay dispersion (ultrafast mirrors, chirped stacks);
* the colour of a residual reflection (visible AR coatings);
* the standing-wave field and the absorption in each layer (laser damage,
  absorbing films);
* optical density for blocking filters, and the back surface of a plate.

**Decision:**
* **One analysis module, `coatanalysis.py`.** A stack is a list of layers
  N(λ) = n − ik with thicknesses, between an incident medium and a
  substrate (optionally opaque, optionally with a bare back surface added
  incoherently). The same code serves the coating editor
  (`/coatings/analyze`) and the coating designer (`/coating-design/analyze`):
  * spectrum: R, T, A for s, p and their mean, and the optical density;
  * R and T against the angle of incidence at the reference wavelength;
  * phase of r and t, group delay −dφ/dω and GDD dGD/dω, ellipsometric
    ψ and Δ. The phase is left undefined (null) where the power is below
    0.1 %: at a zero of the amplitude it jumps by up to π, and its
    derivatives would show the jump, not the dispersion;
  * colour under D65 for the CIE 1931 2° observer: x y, L*a*b*, Rv and Tv,
    and a swatch of the hue at full brightness;
  * the standing-wave |E|² by plane-wave amplitudes in each medium, with
    the absorptance of each layer and of the substrate. This is a second,
    independent solution of the same problem as the characteristic matrix;
  * the index profile with QWOT, and band statistics (mean, min, max).
* **Built-in library** (`materials/data/builtin_coatings.json`, 23
  coatings, generated by `tools/builtin_coatings.py`). It covers:
  * antireflection: MgF₂ quarter wave, exact two-layer V-coats from 355 to
    1550 nm, broadband AR for the visible, NIR and SWIR;
  * mirrors: quarter-wave HR stacks, a 45° HR, hot and cold mirrors;
  * filters: long-pass, short-pass, band-pass and notch;
  * beam splitters: a 50/50 plate at 45° and a MacNeille polarising cube.

  Each built-in stores its design wavelength, band, angle, incident and
  substrate indices, and the specification it meets (coating-designer
  targets). The tests check every specification. VCOAT_550 was replaced
  by an exact V-coat (R = 0 at 550 nm).
* **Built-ins open in the designer under their design conditions**
  (`design_from_builtin`): λ₀, the substrate index, the targets, and the
  incident index. For the incident index the designer got a fixed,
  non-absorbing value (`incident_index`, e.g. the glass of a cube beam
  splitter). Saving makes a new project coating; the built-in is never
  changed.
* The engineering tables' CSS moved into `@layer components`. Unlayered
  rules beat Tailwind utilities, so utility classes on table cells had no
  effect.

**Why:**
* The field method reproduces the matrix R and T to 10⁻¹², and energy is
  conserved to 10⁻⁹. Two independent solutions of one problem are a
  stronger check than either alone.
* A specification stored with each built-in states what it is for and
  makes the library testable. A wrong built-in (VCOAT_550) is caught
  automatically.
* Opening a built-in at 550 nm with the previous design's targets would
  show a different coating from the one in the editor.

**Trade-off:**
* Built-ins use nominal, non-dispersive film indices (TiO₂ 2.35,
  Ta₂O₅ 2.1, Al₂O₃ 1.63, SiO₂ 1.46, MgF₂ 1.38). Real deposited films
  differ by process. On a lens the coating sits on the real glass, not on
  the design substrate n = 1.52.
* Colour is for D65 and the 2° observer only.
* The field is shown at one wavelength and polarisation.
* The back surface can only be bare, and it is added incoherently.
* No metal mirrors with dispersive n, k: that needs tabulated metal data,
  which is not yet in the project.

## ADR-054: Thin films as a workspace (the coating studio) with professional design tools
**Context:** The coating designer was a modal dialog, reachable from the
command palette, two workspace bars and the inspector. Users did not find
it. It also lacked tools that thin-film engineers use every day:
* design targets beyond R, T and A: group delay and GDD (ultrafast
  mirrors), phase and retardance (phase retarders), colour (visible AR);
* stack formulas such as (HL)^7 H;
* the admittance diagram;
* reverse engineering of a deposited coating from its measured spectrum.

**Decision:**
* **Workspace "Thin films".** The designer is a workspace (`studio:
  'coatings'` in `lib/workspaces.ts`). Its centre is the coating studio
  (`CoatingStudio`): a library rail beside the designer's three columns.
  - The rail lists project coatings, the system's surfaces with their
    coatings, and the built-in library by category, with a search box.
  - `openDialog('coatingDesigner', arg)` now switches to the workspace and
    hands `arg` ({ coating } or { surfaces }) over in `coatingArg`. Every
    existing entry point (editor, inspector, Coatings view, palette)
    therefore lands in the studio.
  - The start screen has a *Thin-film coating design* action and cards of
    featured built-ins.
* **Target quantities** (`coatdesign.Target`, ADR-053's designer):
  - R, T, A against wavelength, as before;
  - GD (fs), GDD (fs²) and phase (°) of r or t (`of`), and the retardance
    arg(rp/rs) or arg(tp/ts) (°). They are evaluated from the complex
    amplitudes on the target's own grid, with the phase unwrapped in ω;
  - Rv, Tv, and L*, a*, b* of the reflected or transmitted light (D65, CIE
    1931 2°): one value each.

  The merit divides each violation by a scale: 1 % in R, T or A weighs as
  much as 1 fs of GD, 10 fs² of GDD, 3.6° of phase or 1 unit of L*a*b*.
  A target is met when its violation is below 10⁻⁵ of that scale.
* **Stack formula** (`parse_formula`, `to_formula`): written from the
  incident medium to the substrate, as on paper, in quarter waves at λ₀.
  Supports multipliers, groups and repeats. Every evaluation reports the
  design as a formula, with repeated runs compressed.
* **Admittance diagram** (`coatanalysis.admittance_locus`): the running
  admittance Y = C/B from the substrate outwards, with tilted admittances
  for s and p and iso-reflectance circles. It is a tab of the shared
  analyses, so it appears in both the editor and the designer.
* **Reverse engineering** (`fit_measurement`, *Measurement fit* tab):
  - fits measured R or T spectra (pasted or imported as text) by bounded
    least squares;
  - unknowns: one common thickness scale (a rate or tooling error), every
    layer, or both;
  - reports the errors with 1σ uncertainties from s²(JᵀJ)⁻¹, the
    correlations, the RMS before and after, and a warning when the fit is
    ill-conditioned;
  - *Apply as-built thicknesses* is one undoable step; the design is never
    changed silently.
* **Library example `DM_800`:** a dispersive mirror (R ≥ 99 % over
  760–840 nm, GDD −40 ± 15 fs² over 770–830 nm). It is refined from a
  linearly chirped stack and checked by both phase implementations.
  `tools/builtin_coatings.py --only DM_800` rebuilds it without touching
  the other entries.

**Why:**
* A workspace makes thin films a first-class task beside lens design. The
  rest of the project (Lens Data, sidebar) stays a toggle away.
* Phase, colour and retardance targets cover laser and ultrafast optics,
  display and eyewear AR coatings, and polarisation optics. These are the
  everyday cases that R/T targets alone cannot express.
* The admittance diagram is the standard way to understand why a design
  works. Its end point reproduces the matrix R to 10⁻¹².
* Production needs the as-built thicknesses. Fitting a measurement is how
  rate and tooling errors are found and corrected.

**Trade-off:**
* The merit scales are conventions; the weights balance them.
* The studio's three columns plus the rail need about 1500 px. Below
  1600 px the rail floats over the designer and closes after a pick.
* (The grid-bound GD/GDD, the front-face-only phase and the thickness-only
  fit of the first version were removed by ADR-055.)

## ADR-055: Measured film and metal materials; no remaining coating limitations that professional tools lack
**Context:** After ADR-053 and ADR-054 the coating tools still had
limitations that professional thin-film software does not:
* built-ins of nominal, non-dispersive indices;
* no metals;
* a bare back face only, without substrate absorption;
* phase only of the front face;
* GD and GDD tied to the target grid;
* a measurement fit of thicknesses only, local only;
* colour for D65 and 2° only;
* the field at one wavelength.

**Decision:**
* **Materials with k.**
  - Material records take `extinction_table`, giving N = n − ik.
  - Measured films (SiO₂, TiO₂, Ta₂O₅, Nb₂O₅, HfO₂, Al₂O₃, MgF₂, ZnS,
    Si₃N₄) and metals (Ag, Au, Cu, Cr, Al) come from the refractiveindex.info
    database (CC0) via `tools/coating_materials.py`, with references.
  - Metals are refused as lens media.
* **Built-ins rebuilt of these materials** on N-BK7, plus metal mirrors
  (protected, enhanced and UV aluminium, protected silver and gold). The
  generator checks every specification before writing.
* **Back side.**
  - Bare or coated (`back_layers`), with the substrate thickness and its
    bulk absorption (k, or the catalogue internal transmittance).
  - Transmission phase through the plate: t_front t_back plus the
    substrate's group delay.
  - Opacity: k above 10⁻³ (library or fixed).
* **GD and GDD** by a local stencil at each wavelength: no grid dependence,
  and single-wavelength targets.
* **Measurement fit:**
  - index corrections per material: Δn, ΔB/λ², k, and the substrate's Δn;
  - a global search: Sobol sampling of the parameter box, then least
    squares from the best samples;
  - the fitted design keeps the corrections.
* **Colour:** illuminants D65, D50, D55, D75, A, C, F2, F7, F11 and the 2°
  and 10° observers. The new CIE tables are the CIE's own
  datasets (CC BY-SA 4.0, attribution in `photometry/data/README.md`).
* **Field map** |E|²(λ, z) over the analysed band.
* **Optimiser:**
  - a batched finite-difference Jacobian (about 20 times faster
    refinements);
  - needle insertion trying the five best needle positions;
  - gradual evolution when no needle helps;
  - 40 needle steps by default;
  - thin-layer removal that keeps met targets met;
  - a back face linked to the front, optimised together.

**Why:**
* Coating results depend on the films' dispersion and absorption.
  Nominal constants made built-ins and designs look better than real films
  allow. Measured film data are what professional tools ship.
* Metal mirrors are everyday coatings.
* Ultrafast transmissive optics need the plate's GDD.
* Reverse engineering of a run needs the films' index as well as the
  thickness. Large combined errors need a global start.

**Validation:** independent references for every addition (VALIDATION.md):
* converter formulas;
* bare-metal R;
* the absorbing-plate closed form and T = (1 − R₁)/(1 + R₁) for one
  coating on both faces;
* GD through N-BK7 from the analytic Sellmeier derivative;
* CIE white points;
* index fits recovering known errors to 10⁻⁸.

**Trade-off:**
* Film constants are typical for the stated process, not the user's chamber.
  This is the reason for the fit.
* Ag, Au, Cu and Cr data end at 1.94 µm (a warning beyond; Ag also has a
  Lorentz–Drude set to 12.4 µm).
* The global search costs tens of seconds on long stacks.

## ADR-056: Tabulated targets, optimisation of both faces and a published benchmark as a library example
**Context:** The coating designer had to be shown on a reliable, demanding
problem from outside the project. The OIC 2019 Manufacturing Problem (the
"Yucca problem", Poitras et al., Appl. Opt. 59(5), A31 (2020)) is such a
problem:
* s-polarised transmittance at 10° and 50° following the silhouette of a
  yucca: 1212 target points over 450–1075 nm;
* a 1 mm N-BK7 plate that may be coated on both faces;
* a stated merit function MF = √(mean(((T − T_target)/0.01)²)) and
  published results (the contest designs: MF 0.44–2.14 with 74–255 layers
  and 8.2–17.6 µm; the best measured sample: MF 1.16).

The designer could not express it: targets were constants or linear ramps,
and only the front face (or a back face linked to it) was optimised.

**Decision:**
* **Tabulated targets** (`Target.table`, up to 20 000 (λ, value) pairs): the
  target value at each listed wavelength. With "=" targets, zero tolerance
  and weights equal to the numbers of points the merit is the contest MF ×
  0.01. The studio imports a table from text or CSV per target.
* **Both faces optimised.** A coated, unlinked back face joins the
  optimiser: the layer list is front, a locked separator, back. Refinement
  (batched Jacobian), needles (inside every layer and at the four outer
  interfaces) and gradual evolution act on both faces.
* **Examples** (`materials/data/coating_examples.json`, endpoint
  `/coating-examples`, the studio's library rail): published problems
  designed with the designer itself by `tools/coating_examples.py`, stored
  with their reference results and generator settings.
* The contest targets come from Figshare (CC BY 4.0) and were converted
  unchanged; attribution in
  `materials/data/README.md`.

**Why:**
* Published contests are the field's independent benchmarks: the problem,
  the merit function and the competitors' results are public.
* Measured or specified target curves (filters matched to a sensor, a
  spectrum from a datasheet) are tables, not ramps.
* Thick-plate problems with coatings on both faces are common (beam
  splitters, windows, the contest), and splitting a task between the faces
  halves the stack per face.

**Result:** MF 0.781 with 76 + 56 layers of TiO₂/SiO₂ films (5.98 + 4.72 µm),
the best of eight starting designs; the contest's designs reached 0.439–2.14.
Thin needle starts stalled at MF 3.3 (4 µm), a 30 + 24 quarter-wave start
reached 2.09: the problem needs about 10 µm of coating, and the needle method
reaches it more surely from a thick start than by gradual growth.

**Validation:** the contest MF recomputed by the analysis module's spectrum
code (`coatanalysis`, a separate implementation) equals designer merit /
0.01 to 10⁻¹⁰; batched Jacobian rows equal single evaluations on a two-sided
design; refinement changes the back layers; the stored example's MF is
recomputed and lies within the contest designs' range
(`tests/test_coating_examples.py`).

**Trade-off:**
* A generation that reaches its time limit depends on the machine's speed,
  so the example is stored and its MF recomputed by the tests, not
  regenerated.
* The contest left the coating materials to the participants. The example
  uses this project's measured TiO₂ and SiO₂ film data; its MF compares
  with the contest designs' computed MFs, each obtained with its authors'
  own materials.
* Needle steps on hundreds of layers take seconds each; the example's
  generation takes tens of minutes.

## ADR-057: Open-source release under AGPL-3.0-or-later
**Context:** The application is to be published. Running a public server is not
wanted, and direct sales of a new optical design program are hard: buyers pay
for a track record, support and verified results. A public repository lets
every user run the engine on their own machine at no hosting cost.

**Decision:**
* The code is licensed under the **GNU Affero General Public License, version 3
  or later** (`LICENSE`, the unmodified text from gnu.org, SHA-256
  0d96a4ff…abcb0). Copyright: Juuso Heiskanen.
* `backend/pyproject.toml` declares `license = "AGPL-3.0-or-later"` (PEP 639,
  setuptools ≥ 77), and `frontend/package.json` declares the same SPDX expression.
* The data files keep their own licences, and `THIRD_PARTY_NOTICES.md` lists
  them with their sources: CIE tables (CC BY-SA 4.0), the OIC 2019 targets
  (CC BY 4.0), refractiveindex.info constants (CC0), the sample photographs (CC0
  and NASA public domain), the glass coefficients (factual data cited per entry).
  It also lists the dependencies' licences and the trademark statement.
* `CONTRIBUTING.md`: contributions are licensed under AGPL-3.0-or-later, and the
  maintainer may also license them on other terms. This keeps dual licensing
  possible.
* `.github/workflows/ci.yml` runs the engine tests (Python 3.14,
  `OPTICORE_WORKERS=2`), the type check and the UI tests on every push.

**Why AGPL rather than MIT:**
* The program stays free for everyone, including engineers in companies.
* A modified version offered as a web service must publish its source
  (section 13), so nobody can turn it into a closed hosted product.
* Only the copyright holder can sell other terms: a commercial licence for
  companies that cannot accept the AGPL, or a hosted version.
* MIT would give the widest use but no such option.

**Compatibility:**
* All dependencies are permissive: BSD, MIT, Apache-2.0, Zlib, ISC and OFL-1.1.
* Open CASCADE Technology is LGPL-2.1 with an exception. It can be combined
  with AGPL code and is installed as a separate package.
* CC BY-SA 4.0 data is distributed as separate, unmodified files with
  attribution.

**Checked before release:**
* The git history contains no third-party files other than those listed. The
  two `.zmx` test files were written for this project.
* The code and documents contain no personal paths or e-mail addresses.
* No proprietary software has been analysed or copied (`docs/DEVELOPMENT.md`,
  *Independent implementation*).
* Internal development files stay out of the repository: local working notes
  and the local tool configuration. The rules that matter to contributors are
  in `docs/DEVELOPMENT.md`.

**Repository presentation:**
* The README is the front page:
  * a centred header with badges;
  * a hero screenshot in dark and light (`<picture>` with
    `prefers-color-scheme`);
  * a six-image gallery of the workspaces;
  * a short feature table, with the full table and all samples folded into
    `<details>`;
  * a table of results reproduced from published work.
* English is the project's main language. Finnish is mentioned as the UI's second
  language.
* The images in `docs/img` are screenshots of the running app, taken in English
  from fresh browser storage on the test servers, with headless Chrome driven
  over the DevTools protocol.
* The community files GitHub recognises are included: issue forms,
  a pull-request checklist that mirrors the invariants, `CODE_OF_CONDUCT.md`,
  `SECURITY.md` (private vulnerability reporting, local deployment model),
  `CITATION.cff`, `CHANGELOG.md` and monthly grouped Dependabot updates.
* `docs/GITHUB_SETUP.md` lists the settings that files cannot set: social
  preview, topics, Discussions, branch protection and the CI badge.

**Trade-offs:**
* Companies that avoid the AGPL will not use or contribute without another
  licence.
* Dual licensing needs the contributors' consent (CONTRIBUTING.md).
* The AGPL's network clause applies only to modified versions run as a service.
  Local use has no obligations.
* The CI workflow cannot be run before the repository exists on GitHub.

## ADR-058: Installable desktop packages
**Context:** Running from source needs Python, Node.js and a terminal, but most
users of an optical design program are not developers. The packages must
install with one click, and the Windows packages must be signed.

**Decision:**
* **One program.** `opticore/desktop.py` serves the API and the built user
  interface from one process on `127.0.0.1:47321`, and opens an app window:
  Edge or Chrome in app mode, else the default browser.
  * The port is fixed because the browser keeps the project library per origin.
  * The program ends when its last window has been closed. The page sends a
    heartbeat every 10 s and a goodbye on closing.
  * A second start opens a window on the running program.
* **PyInstaller, as a folder.** The folder starts faster than a single file, and
  the LGPL libraries of Open CASCADE stay separate, replaceable files.
  * On Windows only the DLLs that the OCP module needs are collected: the
    closure of its PE imports over the wheel's two library folders, 102 files.
* **Windows.** An Inno Setup installer that asks nothing.
  * It installs for the current user without administrator rights.
  * It adds Start menu and desktop shortcuts and opens the program when done.
  * An update replaces the previous files. Uninstallation removes the program
    and its log; the projects, kept in the browser, stay.
* **Linux.** An AppImage built on Ubuntu 22.04, so it runs with glibc 2.35 and
  newer.
* **No macOS package.** Signing and notarisation need an Apple developer
  membership. macOS users run from source.
* **Release workflow** (`.github/workflows/release.yml`). A version tag builds
  both packages and runs the self-test of each. On Windows it also installs,
  self-tests and uninstalls the installer. The result is a draft release with
  SHA-256 sums.
  * The Windows program and installer are signed through SignPath Foundation
    when it is configured. The policy is in `docs/CODE_SIGNING.md`.
* **Licences.** The licence texts of everything bundled are collected per
  platform by `packaging/collect_licenses.py` into the package's `licenses`
  folder.

**Why not the alternatives:**
* Electron or Tauri would add a second runtime and toolchain, and the interface
  already runs in a browser.
* pywebview would need a native web view per platform, with GTK dependencies on
  Linux.
* A single-file executable unpacks itself on every start and makes the LGPL
  libraries harder to replace.
* Docker is not one click.

**Validation:**
* `--self-test` checks the server, the user interface, an evaluation, the
  process pool started through the frozen executable, and the CAD kernel.
* Checked here on the Windows folder and the installed program, and on the Linux
  folder and AppImage (Ubuntu 24.04 in WSL). The workflow runs the same checks.
* Lifetime:
  * the program was serving after 7.5 s;
  * a second start reused it and exited after 1 s;
  * the program ended 8 s after its page was closed.
* The silent install, the self-test and the uninstallation left nothing behind.
* `tests/test_desktop.py`.

**Trade-offs:**
* Size: the Windows installer is 88 MB (the installed folder 444 MB). The Linux
  folder is 925 MB and the AppImage 169 MB. On Linux the VTK
  Python modules are included as well; trimming them is possible later.
* Windows files are unsigned until SignPath approves the project; until then
  Windows shows "Unknown publisher".
* The library belongs to `http://127.0.0.1:47321`. If another program holds the
  port, the next free one is used, its library is separate, and the log says so.
* The app window uses the user's Edge or Chrome profile.
