# UI plan: easy to start, easy to find, professional to look at

Working plan for the usability and visual-design overhaul. Work proceeds in
the order below. Tick an item only when its *Done when* holds, tests pass and
`docs/UI_DESIGN.md` describes the result.

Research behind the plan (October 2026):
* a walkthrough as a new user on a 1366×800 screen;
* an audit of `frontend/src`;
* a survey of how OpticStudio, CODE V, LightTools, OSLO, COMSOL, Lumerical,
  Fusion 360, Blender, Figma, KiCad and Onshape onboard users.

Sources are at the end.

## Goal and acceptance scenario

The plan is done when a **new user** can do the following without the manual,
in about ten minutes, and the result looks like commercial engineering
software in dark and light theme, in English and Finnish:
* on a fresh browser profile at **1366×800**, start a lens from the start
  screen (template or *First lens*);
* set the aperture, fields and wavelengths;
* see the layout and spot diagram;
* focus;
* optimise;
* compare before/after;
* save.

The canonical first-lens sequence of the established tools (Ansys'
OpticStudio singlet tutorial; Build → Analyze → Optimize) is:

1. aperture
2. fields
3. wavelengths
4. surfaces and glass
5. layout
6. spot / ray fan
7. Quick Focus
8. variables and merit (wizard)
9. optimise
10. check
11. report

Those steps must each be one click away.

## Findings (current state)

**Getting started**
* No start screen. `App.tsx:26-70` silently opens the last project or the
  `achromat-start` sample, with all five regions open.
* The templates are text-only cards reached only through the icon-only *New*
  button: 11 samples, no thumbnails or categories (`Dialogs.tsx:138-189`).
* Nothing guides the first lens. Aperture, fields and wavelengths sit in a
  bottom tab; the sidebar shows them read-only.

**Finding things**
* **Toolbar.** 24 toolbar buttons are labelled only at ≥ 1800 px
  (`TopToolbar.tsx:50`). At least 8 have no accessible name. `Box` is the icon
  for both CAD export and Show rays.
* **Analyses.** 23 views sit in one flat list in the pane selects, the
  Analyze menu and the palette. Spot and MTF are mixed with FDTD and fibre
  modes. The Analyze menu is 644 px tall and runs off small screens.
* **Panes.** `showView` always replaces the right pane (`uiStore.ts:84-85`).
* **Optimisation.** Variables are small "V" toggles in the LDE. Merit and
  Optimization are separate tabs. Quick Focus is an unlabelled icon.

**Space at 1366×800**
* Spot plots are about 50 px and the MTF about 140 px tall.
* LDE columns and the ten bottom tabs are truncated.
* The 2D layout keeps the previous zoom after a new project: 2 mm of a
  100 mm system is shown.
* Crowded control rows:
  * POP: about 32 controls in one row;
  * FDTD: about 29, with its own bar instead of `AnalysisFrame`;
  * 3D view: about 16.

**Visual consistency**
* **Fonts.** Inter and JetBrains Mono are declared but never loaded, so
  Windows renders Segoe UI.
* **Sizes.** 9 arbitrary text sizes (388 uses), about 8 control heights and
  12 icon sizes.
* **Colours.** 156 hard-coded hex colours; `#3ab0ff` ×30 duplicates the
  accent token.
* **Elements.** 71 raw `<button>` elements against 102 `Button`s.
* **Duplicated helpers.** `Stat`, `L`, `WavelengthSelect` and settings hooks.

**Small defects**
* **Native `window.confirm`** is used for unsaved changes and deletes:
  * `actions.ts:22`
  * `Dialogs.tsx:117`
  * `MaterialBrowser.tsx:305`
* **Stale text.** About says polarisation, thin films, non-sequential and
  Huygens are not implemented. The *Sequential mode* tooltip calls
  non-sequential "planned".
* **Inspector.** It shows raw parameter ids (`asph_4`, `coat_layer_1`) and the
  internal surface id.
* **Offline state.** It shows a raw uvicorn command (`ViewState.tsx:16`).
* **Translations.** About 23 hard-coded English strings: Layout2D tooltips,
  About, Save as, Project info and Spot.

## Rules for every item

* New strings go into both `en` and `fi` (the i18n test).
* No controls for unimplemented features.
* Every button has an accessible name and a tooltip.
* Physics stays in the engine. A design wizard calls an engine endpoint;
  the UI does not compute radii.
* Project format: prefer `analysis_settings` / `ui` for UI state. A schema
  change needs a migration (the invariants in DEVELOPMENT.md).
* Verify in the browser on separate test servers (engine :8001, UI
  :5174):
  * at 1366×800 and 1920×1080;
  * in the dark and light themes;
  * in EN and FI.
* Add vitest tests where logic is involved, e.g. every `ViewKind` lies in
  exactly one group.

## Phase A: quick wins with the largest effect

### A1. Start screen
* **What.** A start screen at launch, also reachable from *New*, *Help* and
  the palette.
  * A **"Show at startup"** checkbox on the start screen (also in the
    settings) can be unticked so the app opens the last project directly.
    The choice persists per browser (`opticore.ui`) and is on for a first
    run.
  * *New from template*: cards with a lens-profile thumbnail (an SVG drawn
    from sample profiles served by the engine) and a one-line purpose,
    grouped as Imaging lenses / Fibres / Mirrors and folded systems /
    Multi-configuration.
  * *Recent projects* (IndexedDB) and *Resume unsaved work*, which replaces
    the recovery dialog.
  * *Open file / Import ZMX*.
  * *First lens* (B3).
* **Files.** `App.tsx` startup, `Dialogs.tsx` (Templates, ProjectManager,
  Recovery), new `components/start/StartScreen.tsx`, `api.ts`, and the
  backend sample listing (profile thumbnails).
* **Done when**:
  * a fresh profile lands on the start screen and every action works;
  * after "Show at startup" is unticked, a reload opens the last project
    directly (unsaved work is still offered for recovery);
  * the old recovery dialog and the Templates grid are merged into the start
    screen.

### A2. Grouped analyses
* **What.** One definition of `VIEW_GROUPS`:

  | Group | Views |
  |---|---|
  | Layout | 2D, 3D |
  | Geometric | spot, ray fan, OPD fan, field curvature/distortion, longitudinal, chromatic |
  | Image quality | wavefront, FFT PSF, Huygens PSF, MTF |
  | System | system data, dispersion, coatings, polarisation pupil |
  | Beams and wave optics | Gaussian beam, POP/BPM, fibre modes, FDTD |
  | Illumination and stray light | non-sequential, ghosts |
  | Tools | parameter sweep |

  The groups are used by the pane selector (a grouped, searchable menu
  instead of the native select), the Analyze menu (grouped, scrolling, never
  off-screen) and the palette (category prefix).
* `showView` opens in the focused pane.
* **Done when** a test checks that every `ViewKind` is in exactly one group,
  and the menu fits at 1366×800.

### A3. Toolbar that explains itself
* **What.**
  * Labelled primary commands from 1280 px: New, Open, Save, Analyze,
    Quick focus, Optimize.
  * Secondary file commands (Save as, Import, Export, Report, CAD export)
    move into a *File ▾* menu.
  * Every button gets an accessible name and its own icon.
* **Done when** no unnamed buttons remain (checked with the accessibility
  tree), labels show at 1366 px, and the toolbar does not wrap.

### A4. Fixes that remove friction
* **Layout.** The 2D layout fits the view when the project changes or the
  system grows out of view (unless the user zoomed since).
* **Confirmations.** An in-app `ConfirmDialog` replaces `window.confirm`,
  with Save / Don't save / Cancel for unsaved changes and named delete
  confirmations.
* **Texts.**
  * Correct About and the mode tooltip.
  * Human labels instead of raw ids in the Inspector.
  * A friendly offline message, with the developer command folded away.
  * Move the hard-coded English strings into i18n.
* **Empty states.** They say why and offer the action, e.g. "No variables →
  Optimisation wizard", "No fields → Add field", and "No data yet" replaced
  by the reason.
* **Done when** each point is verified in the browser, with vitest for the
  dialog logic.

## Phase B: workflow

### B1. Workspaces
* **What.** A workspace bar under the toolbar, as in Fusion and Blender:
  **Design · Analyze · Optimize · Tolerance · Illumination · Wave optics**.
  * Each workspace has its default panes, bottom tab, toolbar context group
    and visible sections.
  * Advanced modules (POP/BPM, fibre modes, FDTD, coating designer) stay out
    of Design.
  * Layouts are remembered per workspace, with *Reset layout*.
  * This replaces the current three presets (`uiStore.applyPreset`) and the
    static "Sequential mode" pill.
* **Done when** switching workspaces is instant, keeps the user's
  adjustments, and a new user in Design sees only the basics.

### B2. Setup checklist and spec status
* **What.** A *System* card at the top of the sidebar lists Aperture, Fields
  (n), Wavelengths (n), Surfaces and materials (diagnostics), Focus,
  Variables and merit, and Optimised. Each item has a status (✓ / ! / –) and
  opens its editor on click.
  * An optional spec table of target vs current value with pass/fail
    (EFL, F/#, RMS spot, total track; CODE V's SpecBuilder idea).
  * Targets are stored in `analysis_settings`.
* **Done when** each status follows the engine evaluation and a click lands
  in the right editor.

### B3. First lens (guided setup)
* **What.** A short stepper from the start screen:
  1. focal length, F/# and field angle;
  2. wavelength preset;
  3. glass (singlet or cemented doublet).
* **Engine.** A starting prescription comes from a new engine endpoint
  (thin-lens/achromat solution; tests against the lensmaker and achromat
  conditions).
* **Afterwards.** The app runs Quick Focus and opens Layout + Spot in Design,
  with a one-line "next: Optimise" hint.
* **Done when** the acceptance scenario works end to end, and the endpoint
  has analytic tests and a `docs/VALIDATION.md` entry.

### B4. Optimisation wizard
* **What.** In one dialog and one undoable commit:
  * *What may change*: radii, air gaps, glass thicknesses, image distance;
  * *What to minimise*: RMS spot or wavefront, centroid or chief ray, field
    and wavelength weights;
  * *Constraints*: centre and edge thickness bounds, optional EFL target.

  It creates the variables and operands, then opens Optimize. The LDE "V"
  toggles stay for experts.
* **Done when** a blank singlet can be optimised from the wizard alone, and a
  test checks the generated spec.

### B5. Messages with causes and fixes
* **What.** A non-modal messages panel (as in OpticStudio's later Messages
  Window). Every diagnostic code gets a plain-language cause and a fix
  action, e.g.:
  * ray misses surface 4 at field 2 → reduce field/aperture or fix the
    semi-diameter;
  * negative edge thickness → jump to the row;
  * TIR.

  The status bar count opens the panel; a click selects the surface.
* **Done when** all existing diagnostic codes are mapped (a test checks
  coverage) in en and fi.

## Phase C: visual system

### C1. Typography and tokens
* **Fonts.** Load Inter and JetBrains Mono (bundled `@fontsource`, OFL).
  Use `tabular-nums` for every number column and stat.
* **Type scale.** Four named sizes replace the nine arbitrary ones:

  | Name | Size |
  |---|---|
  | caption | 10.5 |
  | small | 11.5 |
  | body | 12.5 |
  | title | 14 |
* **Controls.** Two heights, 24 and 28 px.
* **Spacing and shape.** A 4/8 px spacing grid; icon sizes 12/14/16; radii
  4/6/8.
* **Done when** no `text-[Npx]` and no stray `h-[..px]` remain in components
  (a grep check in a test).

### C2. Colour
* **What.**
  * Tokens replace the hard-coded hex values.
  * Neutral chrome with one accent for selection and interaction.
  * A fixed data palette: wavelengths in their own colours; fields in the
    colour-blind-safe Okabe–Ito palette; the same in every plot and in the
    2D/3D rays.
  * Colormap policy:
    * irradiance and PSF: inferno/viridis (perceptually uniform);
    * signed quantities: diverging RdBu centred on zero;
    * phase: cyclic;
    * no jet.
* **Done when** the plots share one theme in dark and light, and a test
  checks that no hex literals remain outside the token and palette files.

### C3. Component consolidation and control bars
* **What.**
  * `Stat`, `Label` (with a visible hint affordance), `WavelengthSelect` and
    the settings hook move into `components/common`.
  * Raw `<button>` becomes `Button`/`IconButton`.
  * `FdtdView` uses `AnalysisFrame`.
  * Every analysis bar shows its few primary settings, with the rest under
    *More settings ▾* (POP, FDTD, 3D).
  * Units go in every label and column header.
* **Done when** no analysis bar wraps at 1366 px.

### C4. Fits a laptop
* **What.** At 1366×800:
  * the Inspector becomes an overlay below 1440 px;
  * the bottom panel defaults lower;
  * analysis plots get minimum sizes (spot cells, MTF);
  * the bottom tabs get an overflow menu;
  * LDE columns get minimum widths, with full text in tooltips.
* **Done when** the acceptance scenario runs at 1366×800 without truncated
  primary controls.

### C5. Visual QA pass
Check screenshots of the start screen, Design, Analyze, Optimize and Wave
optics in dark/light × EN/FI at 1366×800 and 1920×1080:
* text contrast ≥ 4.5:1;
* every button named;
* consistent spacing.

Update `docs/UI_DESIGN.md` (design tokens, workspaces, start screen) and
`README.md` screenshots in `docs/img`.

## Status

| Item | Status |
|---|---|
| A1 Start screen | ☑ |
| A2 Grouped analyses | ☑ |
| A3 Toolbar | ☑ |
| A4 Friction fixes | ☑ |
| B1 Workspaces | ☑ |
| B2 Setup checklist and specs | ☑ |
| B3 First lens | ☑ |
| B4 Optimisation wizard | ☑ |
| B5 Messages with fixes | ☑ |
| C1 Typography and tokens | ☑ |
| C2 Colour | ☑ |
| C3 Components and control bars | ☑ |
| C4 Laptop layout | ☑ |
| C5 Visual QA | ☑ |

## Sources

* Ansys, Fundamentals of Optics singlet tutorial (canonical first-lens
  sequence): https://innovationspace.ansys.com/courses/wp-content/uploads/sites/5/2023/03/Summary-Software-Design-of-Optical-Systems.pdf
* OpticStudio User Guide (Setup / System Explorer): https://ansyshelp.ansys.com/public/Views/Secured/Zemax/v26102/en/OpticStudio_User_Guide/index.html
* Zemax Messages Window and System Check: https://optics.ansys.com/hc/en-us/articles/45361764016659-Zemax-Messages-Window ,
  https://community.zemax.com/got-a-question-7/how-do-you-use-the-system-check-feature-438
* Common beginner errors (ray failures): https://community.zemax.com/got-a-question-7/missed-surface-error-message-possible-solution-proposed-1511
* CODE V New Lens Wizard and SpecBuilder: https://wp.optics.arizona.edu/jsasian/wp-content/uploads/sites/33/2019/08/CODEV-Introduction-August-2019_OPTI517.pdf ,
  https://news.synopsys.com/2017-03-06-Synopsys-Releases-CODE-V-11-0-with-New-SpecBuilder-and-SpecEvaluator-Tools
* OSLO slider wheels: https://lambdares.com/news/did-you-know-interactive-optimizer-sliderwheels
* COMSOL Model Wizard / Model Builder: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_environment.18.43.html
* Fusion workspaces: https://www.autodesk.com/products/fusion-360/blog/autodesk-fusion-interface/
* Blender splash screen and workspaces: https://www.blender.org/manual/en/interface/window_system/splash.html ,
  https://docs.blender.org/manual/en/dev/interface/window_system/workspaces.html
* Figma UI3 (inline labels, "speed is a feature"): https://www.figma.com/blog/our-approach-to-designing-ui3/
* VS Code command palette guidelines: https://code.visualstudio.com/api/ux-guidelines/command-palette
* NN/g: empty states https://nngroup.com/articles/empty-state-interface-design ; tutorials
  https://www.nngroup.com/articles/mobile-tutorials/ ; progressive disclosure
  https://jakobnielsenphd.substack.com/p/progressive-disclosure
* Data-dense design systems: Blueprint https://github.com/palantir/blueprint ; Carbon tables and type
  https://carbondesignsystem.com/components/data-table/style , https://carbondesignsystem.com/elements/typography/overview/ ;
  Atlassian spacing https://atlassian.design/foundations/spacing ; Siemens iX https://ix.siemens.io
* Tabular numbers: https://developer.mozilla.org/docs/Web/CSS/font-variant-numeric
* Dark theme guidance: https://m2.material.io/design/color/dark-theme
* Colour-blind-safe palette and colormaps: https://search.r-project.org/CRAN/refmans/bggum/html/color_palettes.html ,
  https://blogs.egu.eu/divisions/gd/2017/08/23/the-rainbow-colour-map/
