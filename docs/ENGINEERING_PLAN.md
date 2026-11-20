# Engineering plan: the additions a professional optical designer expects

Working plan for the engine and workflow additions after the UI overhaul
(`docs/UI_PLAN.md`). Work proceeds in the order below. Tick an item only
when its *Done when* holds, its benchmarks pass and the documents named in
the rules describe the result.

The list comes from the known limitations in `docs/OPTICAL_ENGINE.md` §12
and `docs/ROADMAP.md` (October 2026): what a designer using OpticStudio,
CODE V or OSLO would miss first.

## Rules for every item

**Physics**
* The Python engine computes every number. The UI shows, edits and plots.
* Each physical model needs an analytic or independently published
  benchmark in `backend/tests` and an entry in `docs/VALIDATION.md`.
  Approximations are labelled as such in the method line of the result.
* Data (glass constants, CTEs, BSDF parameters) come from cited, legally
  distributable sources. A missing value is reported, never invented.
* Defaults reproduce today's results exactly: existing projects and the
  frozen sample baselines do not change unless the user turns a model on.
* Schema changes: `model.py`/`project.py` and `frontend/src/lib/types.ts`
  together, defaults for old files, fixtures regenerated from the backend,
  `schema_version` bumped with a migration when old files need one.

**UI: the new UI's way of working** (`docs/UI_DESIGN.md`)
* Put each feature where its task lives: the matching workspace, analysis
  group, bottom tab, Inspector section or System card row. Do not add a
  toolbar button when a workspace command or menu entry fits.
* Analyses use `AnalysisFrame`: a few primary settings in the bar, the rest
  under *More settings*, settings through `useAnalysisSettings`, units in
  labels and headers, data colours from `lib/palette.ts`, colour maps from
  `COLORMAPS`.
* Shared controls only (`Label`, `Row`, `Stat`, `FieldSelect`,
  `WavelengthSelect`, `Button`/`IconButton`); every control named; text in
  `en` and `fi`; contrast tokens, no hex literals; no text in data colours.
* Every modelling edit goes through `projectStore` (undoable). Results of
  long computations are applied only as a new revision.
* Works at 1366×800 and 1920×1080, dark and light, English and Finnish
  (bars fold, plots keep minimum sizes, tables scroll).
* No controls for parts not yet implemented; those go in `docs/ROADMAP.md`.

**Process**
* `pytest`, `npm test` and `npm run typecheck` pass; the feature is checked
  in the browser on separate test servers (engine :8001, UI :5174),
  never on a working instance (:8000/:5173); servers stopped and viewport restored
  afterwards.
* `docs/OPTICAL_ENGINE.md` (method), `docs/VALIDATION.md` (benchmarks),
  `docs/UI_DESIGN.md` (UI), `docs/ROADMAP.md` (status) and, for a
  significant choice, `docs/DECISIONS.md` are updated with the item.

## E1. Temperature and pressure (athermal design)

* **What.**
  * An explicit environment model, off by default: system temperature and
    pressure, per configuration through the configuration editor.
  * Air index from temperature, pressure and wavelength; glass indices
    relative to the system air; `VACUUM` relative to it as well.
  * Glass index change with temperature by the absolute Schott model
    (D0, D1, D2, E0, E1, λTK, reference temperature of the material).
  * Thermal expansion: each glass element scales homothetically with the
    glass CTE (radii, aspheric terms, thickness, apertures); air gaps scale
    with the CTE of their spacer (housing by default, per gap override);
    mirrors with their substrate CTE.
  * Thermal data for the built-in glasses from cited data sheets; catalogue
    glasses from AGF and refractiveindex.info; missing data reported.
  * A temperature analysis (focus shift, EFL and RMS spot against
    temperature or pressure, with the diffraction depth of focus) and
    temperature/pressure in multi-configuration optimisation
    (athermalisation over several temperatures), with the spacer expansion as
    an optimisation variable for passive athermalisation.
* **Benchmarks.** Thin-lens focal shift df/dT = −f·β with the
  thermo-optic coefficient β = (dn/dT)/(n − 1) − α; uniform scaling of a
  system whose glass, mounts and air expand alike; published air indices;
  vacuum (P = 0) gives absolute indices; Schott data-sheet dn/dT values.
* **UI.** *Environment* section in the Aperture · Fields · Wavelengths
  tab; spacer/substrate CTE in the Inspector; temperature and pressure in
  the configuration editor; the temperature analysis in the *System*
  analysis group; a System card row when the model is on; thermal data in
  the material editor.
* **Done when** the achromat's focus shift from −20 °C to +60 °C matches the
  thin-lens prediction within its stated assumptions, and a three-temperature
  configuration of the sample can be optimised to a smaller focus spread.

## E1b. Mechanical mount tree: where the optics sit when the mechanics expand

The mechanics carry the optics: as lens holders, spacers and tubes expand,
the lenses and the image plane move. This item models that without a
finite-element solver.

* **What.**
  * Mount parts: each has a material (CTE), an optional temperature of its
    own (else the system temperature) and a datum where it attaches to its
    parent part; the root parts attach to the fixed reference. A part can be
    linked to a CAD part (assembly tree node), whose extent along the axis
    supplies datum and seat positions.
  * Seats: a lens element, a mirror or the image surface is held by a part
    at the vertex of one of its surfaces. The seat moves by the expansion of
    every part between it and the reference (signed lengths, so re-entrant
    athermal mounts work); the element then expands from its seated surface
    with its glass.
  * Element temperatures: a lens element can have its own temperature (its
    index and its expansion), e.g. a lens warmer than its housing.
  * Gaps not fixed by seats keep the E1 rules (spacer or housing CTE).
* **Benchmarks.** One part: seat shift L·α·ΔT exactly; two parts in a
  re-entrant arrangement with α₁L₁ = α₂L₂: no shift; a single housing part
  holding the image reproduces E1's housing expansion; a part at its own
  temperature; a lens at its own temperature against the thin-lens dn/dT
  prediction.
* **UI.** A *Mounts* tab (Design workspace) with the part tree, seats and
  their displacements at the current temperature, CAD-part linking with
  datum/seat positions from the part's axial extent, and an element
  temperature in the Inspector.
* **Done when** the achromat held in a barrel with the image plane on a
  re-entrant tube can be made athermal by the choice of tube material, the
  mount displacements match the analytic chain sums, and a warmer lens moves
  the focus as predicted.
* **As built.** Done (VALIDATION, *Mount tree*). Differences from the plan:
  seats work along a straight axis, so mirrors cannot be seated (systems
  with mirrors or coordinate breaks report `MOUNT_UNSUPPORTED` and keep the
  E1 rules); a seat is at a surface vertex, and a linked CAD part supplies
  datum values (its front or back), not seat positions; the warmer-lens
  benchmark is a thick-system matrix calculation, because the thin-lens
  estimate is too coarse for a cemented doublet.

## E2. Tolerancing: surface form, glass and yield

* **What.**
  * Surface irregularity: power and irregularity in fringes (ISO 10110-5
    3/A(B)) and Zernike surface-form tolerances.
  * Glass tolerances: index (Δnd) and Abbe number (ΔVd) of each element.
  * MTF at a frequency as a criterion.
  * Yield: probability of meeting the specification from the Monte Carlo
    run, with its statistical uncertainty.
  * Inverse sensitivity: tolerances allocated to meet a performance budget.
* **Benchmarks.** Wavefront error of a surface form error at normal
  incidence, (n − n′)·Δz; linear-model yield against the analytic normal
  distribution; inverse allocation of a quadratic merit.
* **UI.** Tolerance workspace and tab: new tolerance types and criterion,
  yield and allocation results in the tolerance analysis.
* **Done when** the sample doublet can be toleranced with irregularity and
  glass tolerances to a yield figure, and an inverse allocation meets a
  stated RMS-spot budget in a confirming Monte Carlo run.
* **As built.** Done (VALIDATION, *Form, glass, yield and allocation*).
  Irregularity is astigmatic (ISO B, random orientation in Monte Carlo) or
  rotationally symmetric (ISO C) and single Zernike terms are available;
  allocation works in the additive quantity of the criterion (c² for RMS
  criteria, −c for MTF), splits the budget equally over the unlocked
  tolerances and is confirmed by the Monte Carlo run at the allocated
  limits. Cost-weighted allocation and measured surface maps are not
  included.

## E3. Manufacturability: drawings, mechanics and glass data in use

* **What.**
  * ISO 10110 element drawings (SVG/PDF): radii, centre thickness,
    diameters, material, tolerances from E2, coatings.
  * Edge geometry: mechanical diameter, bevels and flats; spacers and a
    simple barrel in the CAD export.
  * Catalogue internal transmittance in throughput; glass cost and a
    material cost estimate in the System card.
* **Benchmarks.** Slab transmittance against the catalogue value scaled to
  the thickness; drawing values against the prescription; solid volumes of
  exported elements.
* **UI.** Drawings from the Inspector and the report; mechanical
  parameters in the Inspector; cost in the System card.
* **Done when** each element of the doublet has an ISO 10110 drawing that
  round-trips its prescription values, and throughput includes internal
  transmittance.
* **As built.** Done (VALIDATION, *Lens elements, mechanics and glass
  transmittance*). Drawings are A4 SVGs with their data embedded (PDF by
  printing); the catalogue internal transmittance is an opt-in system
  setting, so existing results are unchanged; the built-in SCHOTT glasses
  gained density and transmittance from refractiveindex.info (CC0); costs
  exist only where a catalogue gives them (the built-in glasses have none);
  the barrel is a constant bore with cells and spacers, not a designed
  mechanical housing.

## E4. Surface types: Q-polynomial aspheres and XY freeforms

* **What.** Forbes Qcon and Qbfs aspheres and XY-polynomial freeforms:
  sag, normals, ray intersection, paraxial data, optimisation variables,
  conversion from even aspheres, ZMX import where the format allows.
* **Benchmarks.** Polynomial identities and orthogonality, closed forms of
  low orders, agreement with a densely sampled numerical sag, even-asphere
  conversion residuals.
* **UI.** Surface types in the Lens Data Editor and Inspector (coefficient
  tables like the existing aspheric and Zernike sections).
* **Done when** a Qcon asphere and an XY freeform trace and optimise like
  the existing surface types, with their benchmarks in the validation suite.
* **As built.** Done (VALIDATION, *Q-type aspheres and XY freeforms*). Qbfs
  conversion is a least-squares fit (Qcon is exact). ZMX import of these
  surface types is not included: no verified description of OpticStudio's
  stored parameters was available, so none is claimed.

## E5. Image simulation and sensors

* **What.**
  * Relative illumination from real rays.
  * A field-dependent PSF grid and image simulation of a test scene with
    distortion and relative illumination.
  * A sensor model: pixel pitch and fill factor (pixel MTF), Nyquist,
    shot and read noise; system MTF = lens × pixel.
* **Benchmarks.** cos⁴ relative illumination of an ideal lens; analytic
  pixel MTF; energy conservation of the simulated image; distortion mapping
  against the distortion analysis.
* **UI.** Image-quality analysis group; sensor parameters in the system
  settings.
* **Done when** a test pattern can be imaged through the doublet onto a
  defined sensor, and its relative illumination and system MTF match the
  benchmarks.
* **As built.** Done (VALIDATION, *Relative illumination, sensor and image
  simulation*). The relative illumination uses the energy (étendue) form,
  exact for the cos⁴ benchmark and checked against flat-field ray binning; a
  fixed-field image-side solid angle was rejected because aberrations bias
  it. Monochrome scenes and sensors only; distortion and relative
  illumination are applied with rotational symmetry.

## E6. Stray light: measured scatter models and importance sampling

* **What.** ABg and Harvey–Shack BSDF models (energy-normalised, TIS),
  importance sampling towards detectors, a stray-light path table ranked by
  flux, and statistical error bars on detector results.
* **Benchmarks.** The Lambertian limit of ABg; integrated TIS; importance
  sampling unbiased against brute force within its statistical error.
* **UI.** Scatter model in the CAD optics and coating settings; path table
  and error bars in the Non-sequential view (Illumination workspace).
* **Done when** a small detector's stray-light power converges with
  importance sampling at a stated fraction of the brute-force ray count,
  agreeing within the error bars.
* **As built.** Done (VALIDATION, *Stray light*): importance sampling with
  1.8 % of the brute-force rays agrees within the error bars and has a
  sixtieth of its standard error. ABg and Harvey–Shack are normalised to
  the TIS at normal incidence. Importance sampling is a direction-space
  split (ADR-031), one target per run; Gaussian scatter keeps plain
  sampling. The scatter models are set in the CAD optics cell; sequential
  surface coatings have no scatter model (non-sequential CAD bodies only).

## E7. Physics: birefringence, Mueller calculus, vector diffraction

* **What.** Uniaxial birefringent media (ordinary and extraordinary rays,
  crystal axis), Mueller matrices and depolarisation in the polarisation
  analysis, and a vector (Richards–Wolf) PSF for high numerical apertures.
* **Benchmarks.** Calcite walk-off angle; wave-plate retardance; Malus's
  law; the vector PSF's low-NA limit (Airy) and published high-NA focal
  spot widths and longitudinal field.
* **UI.** Crystal axis in the Inspector for birefringent materials; Mueller
  and vector-PSF results in the Image and Polarisation analyses.
* **Done when** a calcite plate and a quarter-wave plate trace with the
  benchmark values, and the vector PSF of an NA 0.9 focus matches the
  published widths.
* **As built.** Done (VALIDATION, *Birefringence, polarisers and Mueller
  matrices* and *Vector PSF*). Calcite walk-off, oblique extraordinary
  refraction against an independent root find, quartz quarter- and
  half-wave plates, Malus's law and standard Mueller matrices; the vector
  PSF equals the Richards–Wolf integrals (aplanatic, and a paraboloid
  through the whole ray chain) and gives 0.314 λ² against the published
  0.31 λ² at NA 0.9. A trace follows one wave per crystal; the polarisation
  analysis and the vector PSF add both coherently (ADR-032). Ideal polarisers
  and retarders came with it (Malus's law needs a polariser). Uniaxial only;
  the depolarisation is that of the pupil average.

## G. Distinguishing features (planned 2026-10-13; done before E8)

Features that no established lens-design program offers in this form (G4 was added afterwards).
They follow the same rules as the E items: the engine computes every number
(including every predicted improvement), and the UI explains and applies.

## G1. Design advisor: what limits the image, and what to do about it

* **What.**
  * **Diagnosis.** For every field it shows what blurs the image: the real
    wavefront's Zernike decomposition (defocus, astigmatism, coma, spherical
    aberration, higher orders), axial and lateral colour, distortion, and the
    RMS spot against the diffraction limit. The surfaces that cause each
    aberration come from the surface-by-surface Seidel and colour sums.
  * **Suggestions.** Candidate design moves, each tried on a copy of the
    design with a short one-dimensional optimisation:
    * refocus;
    * bend a lens (shape change at constant power);
    * move the stop;
    * change an air gap or a thickness;
    * add a conic or an r⁴ term on the surface with the largest
      spherical-aberration contribution;
    * replace a glass with a catalogue neighbour.

    Moves are ranked by the actual gain in the merit function: the project's
    merit function, or RMS spot over fields and wavelengths when none is set.
  * **Plain-language explanations** in English and Finnish built from these
    numbers, for example "the edge of the field is blurred mainly by coma
    (62 %), from surfaces 3 and 4".
  * **Apply** creates one undoable edit.
* **Benchmarks.**
  * The Zernike shares add up to the total RMS wavefront error.
  * The diagnosis is right on systems with a known dominant aberration:
    * a plano-convex lens turned the wrong way: spherical aberration;
    * a singlet with a remote stop: coma and astigmatism off axis;
    * an uncorrected singlet in white light: axial colour;
    * a defocused image plane: defocus.
  * Every reported gain equals the re-evaluated merit after applying the
    move (10⁻⁹ relative).
  * The expected moves win: refocus with the paraxial focus shift for the
    defocused system, and bending for the reversed lens.
* **UI.**
  * The *Advisor* view in the Analyze workspace: a "what limits the image"
    summary per field (bars of the Zernike shares and the colour terms),
    the guilty surfaces highlighted in the layout, and a list of suggestions
    with their predicted gain, the changed parameter and *Apply*.
  * In the Design workspace, the System card shows the number of
    suggestions.
* **Done when** the advisor names the expected dominant aberration on the
  four benchmark systems, and applying its top suggestion repeatedly to the
  *Achromat: starting point* and *Cooke triplet: rough start* templates
  lowers the merit function at every step by exactly the predicted amount.
* **As built.** Done (OPTICAL_ENGINE §8n, VALIDATION *Design advisor*,
  ADR-033). Differences from the plan:
  * Defocus is reported as a focus error, not as an aberration: pure
    spherical aberration at the paraxial focus is mostly Zernike defocus.
    The focus finding uses the System card's best-focus criterion, so
    optimised designs balanced over field and colour are in focus.
  * Bending holds the element's thick-lens power exactly (the last
    curvature is solved), and a single-curvature move was added for power
    changes; without it no move could fix a focal-length error.
  * On the reversed plano-convex lens a conic on the back surface beats
    bending on axis (it removes the spherical aberration); bending is
    checked to turn the lens round at constant power.
  * The System card shows what limits the image (the diagnosis is cheap and
    live) rather than the number of suggestions (a search of seconds).
  * The search runs in one thread (threads do not speed it up under the
    GIL); a process pool comes with G3 and can serve the advisor too.
  * On the double Gauss sample it reports axial colour of 249 µm, 73× the
    depth of focus at f/1.7. The sample keeps the glasses of COMSOL's model
    of the patent (VALIDATION, reference designs), so the figure describes
    that model rather than the patent's original glass choice.

## G2. Live image: see the picture through the lens while designing

* **What.**
  * **Colour image simulation.** The red, green and blue channels are
    imaged through the design at three system wavelengths (or chosen ones)
    with their own distortion and PSFs, so lateral and axial colour show as
    colour fringes. It uses a built-in test scene or the user's own photo.
  * **Preview quality** for interaction (target ≤ 0.3 s on the sample
    doublet): fewer PSF nodes, a downsampled scene, cached pupil sampling,
    and requests cancelled when a newer edit arrives. A full-quality
    refinement follows when the user stops.
  * A before/after slider: the ideal scene and the image through the lens.
  * **Scrubbing**: drag on a number field (radius, thickness, conic, …) to
    change it continuously, with the image following.
* **Benchmarks.**
  * The preview against the full-quality simulation: relative RMS
    difference below a stated bound on the samples.
  * Colour fringes: the channel offsets at the corner equal the lateral
    colour of the chief rays.
  * Each channel conserves energy, and a monochrome scene in three equal
    channels reproduces the E5 simulation.
  * The preview time is recorded per sample in VALIDATION.
* **UI.**
  * The *Live image* view in the Image quality group: the image with the
    before/after slider, the scene choice and *Use my photo*. The photo is
    kept in the browser, not in the project file.
  * Scrubbing on number fields in the Inspector and the Lens Data Editor.
  * Works next to the layout in a split view.
* **Done when** a user can load a photo, drag a radius in the Inspector and
  see the colour image update within about 0.3 s per step on the doublet at
  1366×800, with fringes matching the lateral-colour analysis.
* **As built.** Done (OPTICAL_ENGINE §8o, VALIDATION *Live colour image*,
  ADR-034). In the browser at 1366×800 with a photo, a drag step on the
  achromat took 219–278 ms. Differences from the plan:
  * **Zoom.** At the whole frame the pixels are 15–300 µm, so blur and
    fringes are far below a pixel (the achromat's lateral colour is
    0.03 px). The view therefore zooms (to 32×) into a region chosen by
    preset or by panning.
  * **Fringes.** They match the *real-ray* lateral colour (the centroid of
    each wavelength's rays): the chief ray carries the mapping and the PSF
    its offset. The read-out gives the chief-ray value.
  * **Accuracy and speed.**
    * Pupil sampling adapts to the aberrations, with a geometric PSF where
      they are too large for diffraction sampling (a dragged radius quickly
      defocuses by many waves).
    * The preview uses the geometric PSF while its pixels exceed 2 λN.
    * Mirror symmetry halves the PSF work.
    * A newer request stops an older render (per-tab channel), and the
      System card's analyses wait for a pause.
  * **Scrubbing** is a general NumberField feature (one undo step per drag),
    used in the Inspector and the Lens Data Editor.
  * Examples (added afterwards): two built-in photos (the Eiffel Tower,
    CC0; Hubble's Pillars of Creation, NASA) and two start-screen templates
    that open in the Live image view (`live-eiffel`, `live-pillars`).
  * Found on the way: E5 stopped its chief rays at a central obscuration,
    and its Siemens scene computed arctan2 on the whole grid. Both are fixed;
    the results are unchanged.

## G3. Design space map: many solutions at once

* **What.**
  * **Specification.** From a specification (focal length, f-number, field,
    wavelengths, maximum length, number of elements), a background job
    generates starting designs over several topologies: singlet, cemented
    and air-spaced doublets, triplet, Petzval, double Gauss.
  * **Candidates.** Glasses are sampled from a catalogue subset (crown/flint
    pairs chosen for achromatism), and every candidate is optimised to the
    specification (multistart, seeded).
  * **Metrics.** Each design's metrics come from the normal analyses: RMS
    spot and MTF, length, mass, a relative glass cost where the catalogue
    has it, distortion, and tolerance sensitivity (RSS).
  * **Map.** An interactive map with selectable axes highlights the Pareto
    front. Any point opens as a project or as a new revision.
* **Benchmarks.**
  * The Pareto set is the exact non-dominated set (unit tests).
  * Seeded runs reproduce.
  * Every point's metrics equal a re-evaluation of its stored design.
  * For the f/5, 100 mm doublet specification the map's best design is at
    least as good as the sample achromat (or within 5 %).
  * Cancelling stops the job and keeps the finished candidates.
* **UI.**
  * The *Design space* view in the Optimize workspace: the specification
    form, *Run* with progress and cancel, the scatter map with axis choice
    and the Pareto front.
  * Hovering a point shows its numbers and a small layout; clicking it
    opens the design.
* **Done when** a specification produces at least 100 optimised designs
  over at least three topologies in a few minutes on the development
  machine, the performance–length–cost Pareto front is highlighted, and an
  opened design shows the same numbers in the normal analyses.
* **As built.** Done (OPTICAL_ENGINE §8p, VALIDATION *Design space map*,
  ADR-036). The default specification gave 100 optimised designs over four
  topologies in 212 s (6 cores). The Pareto front is highlighted, and an
  opened design's spot diagram shows the map's numbers. Differences from
  the plan:
  * **Starts.** Triplet, Petzval and double Gauss start from the published
    reference designs in samples.py, normalised to f = 1 with the crowns
    and flints replaced; singlets and doublets from thin-lens solutions.
    The multistart is over glass pairs and perturbed starts. One local
    optimisation per candidate, with a fixed budget per topology, so the
    map shows what a fixed effort reaches.
  * **Cost.** The built-in glasses have no prices, so the default cost
    objective is the glass mass. A catalogue with relative prices (AGF)
    selected as the glass pool gives the glass cost axis and front.
  * **Process pool** (`workers.py`): spawn workers, CPU count − 1, cancel
    through a shared byte read at every merit evaluation, idle shutdown. A
    run nobody polls for a minute is cancelled. The advisor can submit its
    moves to the same pool; it still runs in a thread today.
  * **Faster tracing for everything.** The merit function and the
    automatic apertures trace all fields of a wavelength in one call,
    bit-identical and 2.4 times faster per merit evaluation. Every
    optimisation and tolerance run gains from it.
  * Petzval and double Gauss are optional in the view (about 90 and 120 s
    per design in a full pool); all six topologies with 120 designs took
    about 10 minutes.

## G4. Systems from stock lenses: insert, match and build (added 2026-10-13)

* **What.**
  * **Stock lens library.** Catalogues of purchasable lenses (singlets and
    cemented achromats): part, vendor, prescription (radii, thicknesses,
    glasses), diameter and clear aperture, and the price where the source
    gives one. Sources:
    * **Vendor ZMX files** that the user downloads from the vendor (the
      large vendors publish one per part), imported several at once into a
      named catalogue kept in the browser. This follows ADR-015: OptiCore
      ships no vendor data.
    * A documented **CSV** format for a user's own stock (part, vendor,
      radii, thicknesses, glasses, diameter, price).
    * A built-in **generic** library of OptiCore's own lenses at standard
      focal lengths and diameters, clearly marked as generic and not a
      vendor's part, for concept work before a vendor is chosen:
      * plano-convex, bi-convex, plano-concave, bi-concave and best-form
        meniscus singlets in N-BK7;
      * cemented achromats designed by OptiCore's optimiser.
  * **Insert** a stock lens into the design at a chosen place, either way
    round. The part is named in the surfaces' labels and comments.
  * **Build.** From a specification:
    * an object at infinity (focal length, F/# or entrance pupil, field) or
      at a finite distance (magnification, object-space NA, object height);
    * wavelengths, maximum length and 1–3 lenses.

    The engine:
    1. enumerates ordered stock-lens combinations and orientations;
    2. solves the air spaces for the first-order target from the
       thick-lens matrices (vectorised);
    3. keeps those whose spaces, length, image distance and paraxial beam
       fit the clear apertures;
    4. ranks them with a real-ray prescreen at the best focus;
    5. optimises the best ones in their air spaces and image distance on
       the process pool (G3), with the real-ray RMS spot and the target;
    6. maps them against length, number of lenses and price, with the
       Pareto front.
  * **Match.** For an existing design, each lens element (singlet or
    cemented group) gets its nearest stock lenses: the same number of
    glasses, the focal length close to the element's, the clear aperture at
    least the element's. Combinations and orientations are placed with
    their principal planes on the original element's (first order kept),
    prescreened, then reoptimised in the air spaces with the project's merit
    function. They are ranked by merit.
* **Benchmarks.**
  * Generic library: each lens's paraxial EFL (d line) equals its nominal
    focal length (10⁻⁶ relative). The centre and edge thickness rules hold.
    The library is reproduced exactly by its generator.
  * Stock lens paraxial data (EFL, principal planes, back focus) equal those
    of the traced system. A flipped lens has the same EFL and swapped
    principal planes.
  * The first-order solver: the solved spaces give the target EFL or
    magnification in the traced system (10⁻⁹). Two thin-like lenses agree
    with f = f₁f₂/(f₁ + f₂ − e).
  * ZMX import of a stock lens file keeps its prescription. The CSV parser
    rejects malformed rows with their line numbers.
  * Match: a design assembled from stock lenses, whose radii are then
    perturbed, matches back to those parts (top rank) and recovers its
    spaces.
  * Build:
    * a 1:1 relay from two identical achromats finds the symmetric
      back-to-back arrangement among the best;
    * the targets are met within tolerance;
    * seeded runs reproduce;
    * every candidate's metrics equal a re-evaluation.
* **UI.**
  * *Stock lenses* dialog (Materials menu and the Lens Data Editor's insert
    menu):
    * catalogues: Generic (built-in) and imported;
    * import ZMX files or CSV;
    * search and filter by type, focal length, diameter and vendor;
    * details with the outline and paraxial data;
    * *Insert* before the selected surface, with *Reversed*.
  * The *Design space* view gets a mode switch, *Lens forms* (G3) |
    *Stock lenses*:
    * the stock specification;
    * the catalogues to use;
    * *Build* or *Match this design*;
    * the same map, front, hover card and *Open as project* / *Use in this
      project*.
* **Done when** a user can:
  * build a two- or three-lens system for a focal length or a magnification
    from the generic library or imported vendor files, and get ranked,
    real-ray-optimised stock-lens systems in about a minute;
  * match an optimised doublet design to stock parts;
  * open the result with the same numbers in the normal analyses.
* **As built.** Done (OPTICAL_ENGINE §8q, VALIDATION *Stock lens systems*,
  FILE_FORMATS *Stock lenses*, ADR-037).
  * Results: an f = 100 mm F/5 build from the generic library gave 40
    optimised one- and two-lens systems in 28 s in the browser, and
    matching the sample achromat took 2 s.
  * The opened design's spot diagram equals the map.
  * Materials (added during the work): the generic library has N-BK7,
    UV fused silica, N-SF11 and CaF2 singlets and three achromat glass
    pairs. Builds and matches take a list of allowed glasses.
  * Differences from the plan:
    * The 1:1 relay benchmark became "two f = 100 mm achromats, crowns
      facing" (the classic 4f relay). The best pair uses a larger second
      lens when the field needs it.
    * The match benchmark checks that the original parts are among the
      results with their spacing recovered. A better part, a best-form
      lens, may win.
    * The stock lens entries are the Lens Data Editor's button and context
      menu and the command palette. The toolbar's *Materials* stays a
      single button.

## G5. Light sources: direction, Gaussian beams and spectra (added 2026-10-14)

Review of the light sources (ADR-017, ADR-019): there was no way to point a
Gaussian beam in a chosen direction.

* **What was there.**
  * Sources:
    * emitters: point, disk, rectangle, sphere and box shapes; uniform or
      Gaussian spatial laws; collimated, isotropic, Lambertian, cosⁿ, cone,
      Gaussian and tabulated angular laws;
    * system-field sources;
    * power, ray count, a spectrum as a list, and a placement (position and
      intrinsic XYZ angles, optionally anchored to a surface).
  * The direction existed only as three Euler angles about the local axes.
    Nothing showed where the source pointed, and it could not be aimed at a
    point.
  * A Gaussian beam had to be assembled by hand:
    * a disk with a Gaussian profile plus a Gaussian angular law and *From
      waist*;
    * the source plane had to be the waist, and there was no M²;
    * the divergence was computed in the UI.
  * Spectra had to be typed as wavelength/weight rows.
* **What.**
  * **Direction.**
    * A placement can aim its +z axis at a point (`aim`, in the frame of its
      position). The roll about that axis stays settable, and the source
      stays aimed when it moves.
    * The UI edits the direction as angles, as a direction vector, or as an
      aim point (or *Aim at* a surface vertex).
    * It shows the resulting direction and its angle to the optical axis.
    * 2D and 3D draw an arrow along the emission direction and a line to
      the aim point.
    * Detectors get the same.
  * **Gaussian beam** as a source kind:
    * waist radii (1/e² intensity, x and y), M² and the waist position
      along the beam (in front of or behind the source plane);
    * divergence θ = M²λ/(πw₀) per ray wavelength;
    * rays sampled at the waist and propagated to the source plane, so
      positions and directions are correlated (converging and diverging
      beams).

    The engine reports the divergence, the Rayleigh range and the beam
    radius and wavefront radius at the source plane.
  * **Spectra** from the engine:
    * blackbody (temperature, band, samples): Planck's law integrated over
      each bin;
    * Gaussian line (centre, FWHM, samples);
    * flat band.

    They fill the source's wavelength list.
* **Benchmarks.**
  * Aim: R·ẑ equals the unit vector to the aim point (10⁻¹²), globally and
    anchored to a surface, for any roll. The UI's drawing transform equals
    the engine's (fixed cases).
  * Gaussian beam:
    * the RMS widths of 200 000 rays follow
      w(z)² = w₀² + (M²λ/(πw₀))²(z − z_w)² at planes before, at and beyond
      the waist (1 %);
    * a converging beam reaches its waist where set;
    * a beam through a thin lens forms the ABCD waist (2 %).
  * Spectra:
    * a blackbody's sampled peak lies at Wien's λ_max = 2897.77 µm·K/T
      within a bin;
    * a band's power fraction equals the quadrature of Planck's law
      (10⁻⁶);
    * a Gaussian line's weighted mean and standard deviation equal the
      centre and FWHM/(2√(2 ln 2)) (1 %).
* **UI.**
  * Sources and detectors panel:
    * a *Direction* row with a mode (angles / direction vector / aim point)
      and a read-out of where it points;
    * *Aim at* a surface;
    * the *Gaussian beam* kind with its parameters and the engine's beam
      read-outs;
    * *Generate spectrum* (blackbody, Gaussian line, flat band).
  * 2D and 3D: direction arrows and aim lines.
* **Later** (in ROADMAP, not built here):
  * photometric power (lm) with the CIE V(λ);
  * IES/LDT intensity files with azimuthal variation;
  * ray files;
  * polarised sources;
  * quasi-random (Sobol) sampling.
* **Done when** a user can point a Gaussian beam (or any source) in any
  direction by angles, vector or aim point and see it in the layout. A
  converging Gaussian beam with M² > 1 focuses where the theory says, and a
  blackbody or LED-like spectrum fills the source in one step.
* **As built.** Done (OPTICAL_ENGINE *Light sources and detectors*,
  VALIDATION *Light sources*, UI_DESIGN, ADR-038).
  * In the browser, the source of a fibre-to-detector project (1550 nm):
    * was aimed at a point 3 mm off axis: it showed "points along
      (0, 0.287, 0.958), 16.7° from the optical axis", the arrow and aim
      line in 2D and 3D, and the non-sequential rays tilted with it;
    * switched to a Gaussian beam: the engine's read-outs (0.987 mrad,
      Rayleigh range 507 mm at 1550 nm) appeared;
    * a 3000 K blackbody filled its spectrum in one undo step.
  * Detectors share the direction editor; their read-out names the
    direction of the light they receive.
  * POP's *From the project* also takes a Gaussian beam source's waist and
    waist position.

## E8. Python API

* **What.** A documented, versioned Python API over the engine: load and
  edit projects, run every analysis, optimise and tolerance, custom merit
  operands as Python functions, a batch runner, and notebook examples.
* **Benchmarks.** The API reproduces the UI's numbers for every sample;
  the examples run in the test suite.
* **UI.** None besides a link in Help; scripts read and write `.opticore`
  projects that the UI opens.
* **Done when** a notebook can load the doublet, sweep a parameter with a
  custom operand and save a project that the UI opens with identical
  results.

## Later (to be evaluated)

Kept here so they are not lost; they need more than the uniform-temperature
model of E1/E1b.

* **L1. Heat conduction and thermal lensing.** Absorbed power from the
  trace (bulk and coating absorption, e.g. a high-power laser) as the heat
  source; a temperature field in lenses and mounts from the heat equation
  (axially symmetric parts: a 2D finite-difference/finite-element solver);
  results back into the optics as index gradients (thermal lens, OPD and
  Zernike terms) and surface bulging.
* **L2. Structural-thermal-optical analysis of the CAD model.** Meshing the
  STEP geometry, a 3D heat and linear thermo-elastic finite-element solution,
  and the results as surface form errors (Zernike fits) and rigid-body
  decenters and tilts of the elements. Open-source meshing and solvers exist;
  their licences need checking before use (e.g. gmsh is GPL).

## Status

| Item | Done |
|---|---|
| E1 Temperature and pressure | ☑ |
| E1b Mechanical mount tree | ☑ |
| E2 Tolerancing: form, glass, yield | ☑ |
| E3 Manufacturability | ☑ |
| E4 Q-type aspheres, XY freeforms | ☑ |
| E5 Image simulation and sensors | ☑ |
| E6 Stray light: BSDF, importance sampling | ☑ |
| E7 Birefringence, Mueller, vector PSF | ☑ |
| G1 Design advisor | ☑ |
| G2 Live image | ☑ |
| G3 Design space map | ☑ |
| G4 Systems from stock lenses | ☑ |
| G5 Light sources: direction, Gaussian beams, spectra | ☑ |
| E8 Python API | ☐ |
