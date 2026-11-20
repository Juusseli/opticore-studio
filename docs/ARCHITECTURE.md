# Architecture

```
┌───────────────────────────── Browser (React 19 + TypeScript, Vite) ────────────────────────────┐
│  components/  views (2D SVG layout, 3D R3F model, Plotly analyses)  editors (LDE, system,      │
│               merit, optimisation)  panels (toolbar, explorer, inspector, dock)  dialogs       │
│  store/       projectStore  (project document + undo/redo history + selection)                 │
│               engineStore   (debounced live evaluation, analysis cache, catalogue, log)        │
│               optStore      (optimisation job lifecycle, polling, live preview)                │
│               uiStore       (layout, theme, language, dialogs; persisted per viewer)           │
│  lib/         api client · TS schema mirror · canonical JSON + SHA-256 · IndexedDB storage     │
│               · unit-aware parsing · i18n (en/fi)                                              │
└──────────────────────────────────────────┬─────────────────────────────────────────────────────┘
                                           │ JSON over HTTP  /api/v1  (Vite proxy in development)
┌──────────────────────────────────────────▼─────────────────────────────────────────────────────┐
│ FastAPI service  opticore/api/main.py  — versioned endpoints, structured errors                │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1 schema      model.py (OpticalSystem v1, pydantic)  project.py (.opticore, checksum, migrate) │
│ 2 geometry    geometry.py, surfaces.py (sag/normal/hit), qpoly.py, configs.py, solves.py       │
│ 3 tracing     physics.py (Snell/reflection/Fresnel)  raytrace.py (tracer, aiming, sampling)    │
│               polarization.py, birefringence.py, diffractive.py                                │
│ 4 first order paraxial.py (y-nu, pupils, cardinal points, Seidel)                              │
│ 5 materials   materials/ (dispersion, catalogues)  environment.py (temperature, mounts)        │
│ 6 analysis    analysis/ (layout, spot, aberrations, wavefront, PSF, MTF, live image, advisor)  │
│ 7 optimise    optimize/ (merit, least squares, limits, global search)  tolerance.py            │
│               designspace.py, stock.py, stockdesign.py, workers.py (process pool)              │
│ 8 non-seq.    nonseq.py, nsdirect.py, nssources.py, bsdf.py, spectra.py  photometry/ (CIE)     │
│ 9 thin films  thinfilm.py, coatanalysis.py, coatdesign.py                                      │
│ 10 wave       wave/ (fibre modes, POP, BPM, RCWA, FDTD)                                        │
│ 11 files      io/ (ZMX, STL, STEP/IGES via OpenCascade)                                        │
│ 12 samples    samples.py (templates)                                                           │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Layer responsibilities

1. **UI and rendering** (frontend). These components hold no optical formulas.
   Small exceptions are drawing helpers: the sag evaluation for drawing
   profiles in 3D mirrors the engine formula. The engine is authoritative.
2. **Optical project schema**: `model.py` and `project.py`, mirrored in
   `frontend/src/lib/types.ts`. Schema version 1.
3. **Geometry engine**: frames, coordinate breaks, sag/normal/intersection.
4. **Geometrical ray tracing**: `raytrace.py`, vectorised with NumPy over rays.
5. **Optical materials**: `materials/`.
6. **Physical optics**: `analysis/wavefront.py` (reference-sphere OPD,
   Zernike) and `analysis/diffraction.py` (FFT PSF, MTF, Strehl, encircled
   energy) are scalar diffraction; `analysis/vectorpsf.py` is the vector
   (Debye–Wolf) PSF. The wave-optics solvers are in `wave/`: fibre modes,
   physical-optics propagation, BPM, RCWA and FDTD.
7. **Optimisation**: `optimize/` (its finite-difference Jacobians and evaluations run on the shared process pool `workers.py`, `optimize/parallel.py`; exact limits by an augmented Lagrangian, `optimize/constrained.py`; trade-off curves, `optimize/tradeoff.py`). The design space map (`designspace.py`)
   runs many optimisations on a shared process pool (`workers.py`: spawn
   workers, CPU count − 1, a shared cancel byte per job, idle shutdown).
8. **File import/export**: `project.py` (native format), `io/zmx.py` (Zemax), `io/stl.py` (STL meshes) and `io/cad.py` (STEP/IGES import and export via the OpenCascade kernel, `cadquery-ocp`, imported lazily).
9. **Persistence**: in the browser (IndexedDB library, autosave), plus portable
   files. The backend is stateless apart from transient optimisation jobs.
10. **Analysis and reporting**: `analysis/`. Every result carries method,
    units and sampling.

## Data flow

* Every modelling edit goes through `projectStore.commit(label, fn)`, which:
  * deep-clones the project
  * applies the change
  * skips no-op edits
  * pushes the previous state onto the undo stack (200 entries)
  * clears redo
* `App.useLiveEvaluation` debounces system changes (≈110 ms) and calls
  `POST /system/evaluate`. Earlier in-flight requests are aborted, so stale
  results never overwrite newer ones.
* Visible analysis views subscribe through `useAnalysis(kind, settings)`. They
  recompute (debounced) when the system or settings change, and cache by a
  canonical key.
* Optimisation runs as a backend thread job. `optStore` polls every 250 ms,
  shows progress, and applies the best-so-far variable values to a *preview*
  copy of the system. The layout and analyses render the preview; the project
  itself is untouched. On completion the user compares before/after and
  chooses *apply as new revision*. That records the previous design in the
  revision history and is undoable.

## API (v1)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Engine and schema version |
| GET | `/api/v1/materials` | Catalogue summaries |
| POST | `/api/v1/materials/curves` · `/resolve` · `/validate` | Dispersion curves, index lookup, custom material validation |
| POST | `/api/v1/system/evaluate` | Pupil, paraxial data per λ, auto semi-diameters, surface geometry, lens elements, layout rays (2D/3D), indices, edge thickness, diagnostics |
| POST | `/api/v1/analysis/{spot,rayfan,field,longitudinal,chromatic,paraxial}` | Geometric and paraxial analyses |
| POST | `/api/v1/analysis/{opdfan,wavefront,psf,mtf,encircled}` | Wavefront, Zernike, FFT PSF, MTF, encircled energy |
| POST | `/api/v1/optimize/merit` | Evaluate the merit function and operand breakdown |
| POST | `/api/v1/optimize/compare` | Before/after numbers of two designs (spot, MTF, distortion, colour, field of view, illumination, chief-ray angle, length, edges) and what got worse (`analysis/summary.py`) |
| POST | `/api/v1/optimize/start` | Start a job. Configuration errors are returned synchronously |
| GET | `/api/v1/optimize/{id}` | Progress snapshot (history, best values, result) |
| POST | `/api/v1/optimize/{id}/pause`, `/cancel` | Job control |
| GET | `/api/v1/samples`, `/samples/{id}` | Templates: the listing has id, name, description, start-screen category and a thumbnail outline; `/samples/{id}` is the `.opticore` document |
| POST | `/api/v1/design-space/start` | Plan and start a design space run (specification, glass records); configuration errors (`DESIGN_SPACE`) at once |
| GET | `/api/v1/design-space/{id}?since=&objectives=` | Progress, the candidates finished after `since` (metrics, outline, feasibility), the Pareto front for the objectives |
| GET | `/api/v1/design-space/{id}/candidates/{n}` | One finished candidate as a project (prescription, optimisation set-up, used custom glasses) |
| POST | `/api/v1/design-space/{id}/cancel` | Stop the run, keeping finished candidates |
| POST | `/api/v1/sources/spectrum` | A source spectrum (blackbody, Gaussian line, flat band) as wavelength samples with power weights |
| POST | `/api/v1/sources/describe` | Where each source and detector is and points (global), and Gaussian beam parameters |
| GET | `/api/v1/stock/generic` | The generic stock lens library with paraxial data |
| POST | `/api/v1/stock/describe` · `/stock/import/zmx` · `/stock/import/csv` | Paraxial data of stock lenses; vendor ZMX files and CSV converted to stock lenses (stateless) |
| POST | `/api/v1/stock/surfaces` | A stock lens as design surfaces (either way round) |
| POST | `/api/v1/stock/build/start` · `/stock/match/start` | Build systems from stock lenses, or match a design's elements; progress, results and cancel via `/design-space/{id}` |
| POST | `/api/v1/design/first-lens` | Starting prescription (best-form singlet or thin-lens achromat made thick, exact EFL) as a project with variables and a merit function |
| POST | `/api/v1/analysis/focus` | Best polychromatic RMS focus along the image normal (closed form), current and best RMS, per-field RMS, at-best-focus flag |
| POST | `/api/v1/analysis/summary` | Key numbers of one design from the normal analyses (`analysis/summary.py`); the optimisation wizard reads the current values |
| POST | `/api/v1/system/outline` | Thumbnail drawing data of a system: glass outlines, mirrors, stop, image and a few real rays in global (z, y) |
| POST | `/api/v1/project/validate` | Schema validation, migration and checksum check |
| POST | `/api/v1/import/zmx` | ZMX import (base64 bytes) with diagnostics |

Errors have the shape
`{"error": {"code", "message", "details"}}`. Codes are `VALIDATION_ERROR`,
`SYSTEM_ERROR` (with structured diagnostics), `MATERIAL_ERROR`,
`DISPERSION_ERROR`, `PROJECT_ERROR`, `IMPORT_ERROR`, `OPTIMIZATION_CONFIG`, `DESIGN_SPACE`, `STOCK_DESIGN`, `STOCK_IMPORT`,
`JOB_NOT_FOUND` and `INTERNAL_ERROR`.

## Persistence design

* **Browser library**: IndexedDB database `opticore-studio`, with a
  `projects` store keyed by project id and a `meta/autosave` record holding the
  latest state and its dirty flag.
* **Autosave**: 1.2 s after the last change, and only after the launch has
  read the previous autosave. On start-up, a dirty autosave is reopened as the
  (unsaved) open project and offered on the start screen; a clean one is the
  project that was open last (`lib/startup.ts`).
* **Save** records a revision snapshot of the optical system (at most 50 per
  project) and writes the library entry.
* **Export/import**: `.opticore` JSON with a SHA-256 checksum over canonical
  JSON (see FILE_FORMATS.md). The browser and the engine produce byte-identical
  checksums; a cross-language fixture test enforces this.
* Per-viewer preferences (theme, language, panel sizes, chosen views) are kept
  in `localStorage` and never inside project files.

## Running

* Development: `scripts/dev.ps1` or `scripts/dev.sh` (see `docs/DEVELOPMENT.md`).
* Desktop program: `opticore/desktop.py` serves the API and the built user interface
  from one process on `127.0.0.1:47321` and opens an app window (ADR-058). The
  installable packages are built from it in `packaging/`.
* Production build: `npm run build` produces static files in `frontend/dist`.
  Serve them behind any reverse proxy that forwards `/api` to uvicorn.
* No cloud services are used or required. The engine binds to localhost.
