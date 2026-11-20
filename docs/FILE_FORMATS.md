# File formats

## Native project: `.opticore` (schema version 1)

UTF-8 JSON. Top-level members:

| Member | Content |
|---|---|
| `format` | Always `"opticore-project"` |
| `schema_version` | Integer, currently `1` |
| `id` | Project id (12 hex chars) |
| `metadata` | name, description, author, created, modified (ISO 8601 UTC), tags |
| `system` | Optical prescription: `OpticalSystem` (see `backend/opticore/model.py`) |
| `custom_materials` | Project-local material records (same shape as catalogue entries; a uniaxial crystal adds `"extraordinary": { "formula", "coefficients", "lambda_min", "lambda_max" }` for n_e, the record's own formula being n_o; an absorbing film or metal adds `"extinction_table": [[λ µm, k], …]`, N = n − ik) |
| `optimization` | `OptimizationSpec`: variables, operands (each with an optional `role`: `auto`, `objective` or `constraint`), algorithm, budget, `constraints` (`exact` or `penalty`; absent = `exact`, ADR-042; optional, schema v1 stays backward compatible) |
| `tolerancing` | `ToleranceSpec`: tolerances (type, surface ids, min/max, Zernike `term`, `locked` for allocation), compensators, criterion (with `mtf_frequency`), specification `limit`, fringe `test_wavelength_um`, Monte Carlo settings. Optional; defaults to an empty set; the newer fields have defaults, so older files load unchanged |
| `sources` | Non-sequential light sources (optional, default empty): `kind` (`emitter` or `system_field` with `field`, `overfill`), `power_w`, `rays`, `placement` {`position` mm, `rotation_deg` (Rx·Ry·Rz), `anchor` (optional surface id: relative to that surface's vertex frame)}, `shape` (point/disk/rectangle/sphere/box) with `size_x/y/z`, `spatial` (uniform/gaussian with `gaussian_wx/wy` 1/e² radii), `angular` (collimated/isotropic/lambertian/cosine_power/cone/gaussian/table) with `half_angle_deg`, `cos_power`, `gaussian_x_deg/y_deg`, `table` [[angle_deg, I]], `wavelengths` [{value µm, weight}] (empty: system wavelengths), `enabled`, `name`, `id` |
| `detectors` | Non-sequential detectors (optional, default empty): `placement`, `shape` (circle radius `size_x` / rectangle `size_x` × `size_y`), `acceptance_deg`, `mode` (absorb/monitor), `two_sided`, `pixels`, `enabled`, `name`, `id` |
| `cad_assets` | Imported CAD models: name, source file, units, indexed mesh (`positions_b64` = little-endian float32 xyz in mm, `indices_b64` = uint32 triangles, with counts validated on load), bounding box, area, volume, closedness, import diagnostics, `optical` (`role`: none/absorber/mirror/refractive, `material`), transform (`translate` mm, `rotate_deg` with R = Rx·Ry·Rz), visibility, colour, opacity. Optional; defaults to an empty list |
| `analysis_settings` | Spot/fan/field settings, plus `saved` analysis snapshots |
| `ui` | Reserved for workspace state that belongs to the project |
| `revisions` | Up to 50 `{id, timestamp, label, system}` snapshots |
| `saved_optimizations` | Optimisation run records |
| `provenance` | created_with, imports (with full import diagnostics), warnings |
| `checksum` | `{"algorithm": "sha256", "value": hex}` |

### Optical system

```jsonc
{
  "name": "…", "units": "mm",
  "surfaces": [ { "id": "…", "type": "standard|even_asphere|odd_asphere|biconic|zernike|qcon|qbfs|xy_polynomial|coordinate_break|ideal",
                  "label": "", "comment": "",
                  "radius": 51.68 /* null = ∞ */, "thickness": 5.0 /* null = ∞, object only */,
                  "material": "N-BK7|AIR|MIRROR|<custom>",
                  "semi_diameter": 12.7, "semi_diameter_mode": "auto|fixed",
                  "conic": 0, "radius_x": null /* biconic x-z section, null = flat */, "conic_x": 0, "aspheric": [/* A4, A6, … */], "is_stop": true,
                  "coating": "" /* built-in or custom_coatings name (case-insensitive), "" = uncoated; optional, defaults to "" (schema v1 stays backward compatible) */,
                  "zernike_coefficients": [/* Fringe Z1.. sag terms, mm (type zernike) */], "zernike_norm_radius": 10,
                  "odd_coefficients": [/* beta_1.. on r^1, r^2, … (type odd_asphere) */],
                  "q_coefficients": [/* Forbes a_0.., mm (types qcon, qbfs) */], "q_norm_radius": 10,
                  "xy_coefficients": [/* A_1.. for x, y, x², xy, y², … (type xy_polynomial) */], "xy_norm_radius": 10 /* the four are optional */,
                  "grating_frequency": 0 /* lines/mm, lines along local x */, "phase_coefficients": [/* A1, A2, … radians */], "phase_norm_radius": 1, "diffraction_order": 1 /* optional; defaults keep older files valid */,
                  "focal_length": 100 /* ideal lens, mm; null = no power */, "ideal_object_distance": null /* ideal lens OPD conjugate, mm; null = infinity (both optional) */,
                  "thickness_solve": null /* or { "type": "marginal_height|chief_height|pickup", "target": 0, "surface_id": null, "scale": 1, "offset": 0, "zone": 1 } */,
                  "curvature_solve": null /* or { "type": "marginal_angle|chief_angle|f_number|pickup", … } */,
                  "decenter_x": 0, "decenter_y": 0, "tilt_x": 0, "tilt_y": 0, "tilt_z": 0,
                  "cb_order": 0,
                  "mount_cte": null /* spacer or mirror-substrate CTE, 1e-6/K; null = housing */, "seat_part": null /* mount part id */,
                  "element_temperature_c": null /* own temperature of the element this surface starts */,
                  "mech_semi_diameter": null /* where the optical surface ends, mm; null = to the element rim */, "chamfer": 0 /* 45° chamfer at the rim, mm */,
                  "crystal_axis": null /* optic axis [x, y, z] of a uniaxial crystal after this surface, local frame; null = local z */,
                  "crystal_mode": null /* "ordinary" | "extraordinary": the wave the trace follows; null = ordinary */,
                  "jones": null /* or { "kind": "polarizer" | "retarder", "angle_deg": 0, "retardance_waves": 0.25 } (ideal element) */,
                  "obscuration": null /* radius (mm) of a central circular obscuration on this surface */
                  /* these are optional with these defaults (older files stay valid) */ } ],
  "custom_coatings": [ { "name": "MY_AR", "description": "",
                         "layers": [ { "material": "" /* library material = dispersive n(λ); "" = fixed index */, "index": 1.38, "extinction": 0 /* k, N = n − ik */, "thickness_nm": 99.6 } ],
                         "substrate_index": null /* mirror substrate n; null = not usable on mirrors */, "substrate_extinction": 0,
                         "design": null /* optional coating-designer source (palette, targets, deposition order) */ } ]
                  /* optional; defaults to [] (older files stay valid) */,
  "wavelengths": [ { "value": 0.5875618, "weight": 1 } ], "primary_wavelength": 0,
  "field_type": "angle|object_height|image_height|paraxial_image_height", "fields": [ { "x": 0, "y": 0, "weight": 1, "vdx": 0, "vdy": 0, "vcx": 0, "vcy": 0 /* vignetting factors, optional */ } ],
  "aperture": { "type": "epd|image_fnum|object_na", "value": 10 },
  "ray_aiming": "paraxial|real", "object_space_telecentric": false /* optional */, "temperature_c": 20,
  "pressure_atm": 1, "environment_enabled": false, "housing_cte": 23.6 /* environment model (OPTICAL_ENGINE §9a) */,
  "mounts": [ { "id": "…", "name": "Barrel", "cte": 1.3, "temperature_c": null, "parent": null /* part id */, "datum_z": 0,
                "cad_asset_id": null, "cad_node_id": null } ] /* mount tree */,
  "catalog_absorption": false /* catalogue internal transmittance as bulk absorption (§8c) */,
  "sensor": null /* or { "pixel_pitch_um": 3.45, "fill_factor": 1, "width_px": 640, "height_px": 480,
                         "full_well_e": 10000, "read_noise_e": 5, "bit_depth": 12 } (OPTICAL_ENGINE §8k) */
  /* the environment, mount and absorption members are optional with these defaults */,
  "multi_config": null /* or { "names": ["Wide", "Tele"], "active": 0,
                     "operands": [ { "parameter": "thickness|radius|conic|material|semi_diameter|decenter_x|…|aperture_value|temperature|pressure|vdx|vdy|vcx|vcy",
                                     "surface_id": "…" /* null for system and field parameters */,
                                     "field": null /* the field index of vdx…vcy (optional) */, "values": [12.0, 3.5] } ] } */
}
```

Validation rules include:

* at least object, one surface and image
* exactly zero or one stop, and never on the object or image surface
* an infinite thickness only on the object
* radius 0 is rejected (use `null`)
* object-height fields and object NA require a finite object distance
* unique surface ids

### Checksum

`checksum.value = SHA-256(canonical_json(project without "checksum"))`.

Canonical JSON:

* object keys sorted (code-point order), no whitespace
* strings escaped as `JSON.stringify` does (non-ASCII left as is)
* numbers in **ECMAScript Number-to-String** form: `1` not `1.0`, `1e-7`,
  `0.000001`, `1e+21`; non-finite numbers become `null`

`project.py:js_number` implements the ECMAScript algorithm in Python, so the
engine and the browser produce byte-identical canonical text. The fixtures in
`frontend/src/lib/__fixtures__` are written by the engine and verified by the
frontend test suite.

A checksum mismatch does **not** block loading. The user is warned that the
file was modified outside OptiCore Studio or is corrupted.

### Migration

`project.py:migrate` chains upgrades from older schema versions; none exist
yet. Files with a newer `schema_version` are rejected with a request to update
the application. Unknown top-level members are rejected (`extra="forbid"`), so
files are never silently truncated.

## Glass catalogue AGF (import into the material library)

AGF is the plain-text catalogue format of the glass manufacturers. Download
the files from the manufacturer; OptiCore ships none. Supported content:

* Dispersion formulas 1–13 (OPTICAL_ENGINE §9).
* Data range, Schott dn/dT coefficients, thermal expansion, density, ΔPg,F,
  relative cost, internal transmittance, status and comments.

Every glass is checked against its own Nd/Vd (see the import report).

The catalogue is kept in the browser (IndexedDB store `catalogs`) and shared
by all projects. A project stores a copy of each catalogue glass it uses in
`custom_materials`. Besides the material fields, the copy has the optional
display keys `catalog`, `status`, `verified`, `excluded`, `agf_formula`,
`mil`, `comment`, `density`, `dpgf`, `tce_m30_70`, `relative_cost`,
`internal_transmission`, `nd_ref`, `vd_ref` and `thermal`. Files therefore
evaluate identically on a machine without the catalogue. Built-in names take
precedence over catalogue glasses with the same name.

## refractiveindex.info glass pages (download into the material library)

The *Makers* button of the material library installs manufacturer
catalogues (SCHOTT, OHARA, HOYA, CDGM, HIKARI, SUMITA, LZOS, …) from the
public-domain refractiveindex.info database
(`github.com/polyanskiy/refractiveindex.info-database`, CC0 1.0). The browser
reads the database index `catalog-nk.yml`, downloads the maker's YAML pages
(`database/data/specs/<maker>/…`) at a fixed commit and sends them to
`POST /api/v1/materials/rii` (`{catalog, files: [{path, content}]}`, at most
5000 pages). The response has the same form as an AGF import and is kept in
the same browser store. The catalogue's comments record the database commit.
An installed catalogue replaces one of the same name (for example a SCHOTT
AGF import). Conversion rules: OPTICAL_ENGINE §9.

## Material CSV (import into the material library)

Two numeric columns per line, separated by commas, semicolons, tabs or spaces:
wavelength (µm, or nm if > 50) and refractive index. It creates a `tabulated`
material with monotone cubic interpolation; the data range sets the valid
range.

## Stock lenses (import into the stock lens catalogues)

Stock lens catalogues are kept in the browser (IndexedDB store `stock`), not
in projects. A design that uses a stock lens holds its surfaces, and its
glasses are copied into the project like catalogue glasses.

* **Vendor ZMX files** (sequential, one lens per file, as vendors publish them
  for each part). Several files can be imported at once into a named
  catalogue; importing again under the same name adds to it. The first run of
  glass surfaces is the lens:
  * radii, thicknesses and glasses from SURF/CURV/DISZ/GLAS;
  * the mechanical diameter from MEMA (else 2 × DIAM) and the clear aperture
    from 2 × DIAM;
  * the part number from the file name without a "-Zemax(ZMX)" style suffix.

  Aspheres and other surface types are refused. Glasses that are not built
  in must be in an installed glass catalogue. A file that fails is listed
  with its reason, and the others import.
* **CSV** (comma-separated, header row, one lens per row):

  | Column | Meaning |
  |---|---|
  | `part` | part number (required) |
  | `vendor` | vendor name |
  | `diameter` | mechanical diameter, mm (required) |
  | `clear_diameter` | clear aperture, mm (empty: 90 % of the diameter) |
  | `focal_length` | nominal focal length, mm (informative) |
  | `price`, `currency` | price of one part |
  | `r1`, `t1`, `glass1`, `r2` | first element: radii (mm; `inf` or empty for flat), centre thickness, glass (required) |
  | `t2`, `glass2`, `r3` | second element of a cemented doublet (empty for a singlet) |

  Malformed rows are reported with their line numbers and skipped.
* OptiCore ships no vendor data. The built-in *Generic* library is
  OptiCore's own (OPTICAL_ENGINE §8q).

## Zemax ZMX (import)

Sequential text `.zmx` files, UTF-16 (with BOM) or UTF-8/Latin-1. Rules:

| ZMX record | Conversion |
|---|---|
| `UNIT MM/CM/IN/METER` | All lengths converted to mm; A₂ₖ scaled by f^(1−2k); curvature by 1/f |
| `SURF n` + `TYPE STANDARD` | standard surface |
| `TYPE EVENASPH` | even asphere: `PARM 2…9` become A4…A18; `PARM 1` (r² term) is dropped with a *partial* diagnostic |
| `TYPE ODDASPH` | odd asphere: `PARM 1…8` become β₁…β₈ (terms in r¹…r⁸) |
| `TYPE COORDBRK` | coordinate break: `PARM 1,2` decenter, `3,4,5` tilts (deg), `6` order. Tilts are flagged *conversion* for visual verification |
| `TYPE PARAXIAL` | ideal lens: `PARM 1` focal length. OPD exact for an object at infinity (*conversion*); OPD modes other than 0 have no equivalent |
| Other `TYPE` | Imported as a plane dummy (*unsupported*) |
| `CURV`, `DISZ` (`INFINITY`), `CONI`, `STOP`, `COMM` | Direct |
| `GLAS name` | Catalogue glass if known. Otherwise AIR plus *missing material* |
| `GLAS MIRROR` | Mirror |
| `GLAS ___BLANK … nd vd` | Model glass: two-term Cauchy fit through nd and nF−nC (*conversion*) |
| `DIAM` / `CLAP` | Semi-diameter. Automatic for `DIAM`, fixed (clipping) for `CLAP` |
| `ENPD`, `FNUM`, `OBNA` | EPD, image F/#, object NA |
| `FLOA` | Approximated as EPD = stop diameter (*partial*) |
| `WAVM` (or `WAVL`/`WWGT`), `PWAV` | Wavelengths, weights, primary |
| `FTYP`, `XFLN`, `YFLN`, `FWGN` | Fields: angle (0), object height (1), paraxial (2) and real (3) image height (*conversion*: resolved to object fields at the primary wavelength). Other types are reported *unsupported* |
| `COAT`, variable flags, pickups/solves | Ignored with *partial* diagnostics (values imported as fixed) |
| `MODE NSC…` | Rejected (non-sequential not supported) |

Every import returns a report. Each item is one of `imported`, `partial`,
`unsupported`, `missing_material`, `conversion` or `info`. The report is shown
in the UI and stored in `provenance.imports`.

**Conversion workflow for unsupported files:**

1. In the source program, replace unsupported surface types (toroids,
   Zernike, gratings, …) with the closest supported type.
2. Convert solves and pickups to fixed values.
3. Replace private or unknown glasses with catalogue or model glasses.
4. Save as a sequential `.zmx` and import.
5. Compare EFL, BFL and RMS spot against the source program before continuing.

Binary `.zar` archives are not read directly; unpack them first. Universal
binary compatibility is not claimed.

## STL (import, CAD geometry)

Binary and ASCII STL are both supported. The importer:
* Detects the format by size. A binary file is exactly 84 + 50·n bytes, so
  binary files whose header starts with "solid" are still read correctly.
* Scales to mm by the unit chosen on import (mm, µm, cm, m or in), because STL
  has no units.
* Merges coincident vertices into an indexed mesh.

Diagnostics:
* degenerate triangles
* facet normals that contradict the winding (the winding is used)
* boundary and non-manifold edges, which make the mesh open
* inconsistent winding
* the enclosed volume by the divergence theorem, for closed meshes only; a
  negative volume means inward-facing triangles

The mesh is limited to 2 million triangles.

Imported models are display and measurement geometry only. They stay separate
from the optical prescription and are not ray traced, and the triangulation is
never treated as an exact optical surface.

## STEP / IGES (import and export, OpenCascade kernel)

The engine uses OpenCascade 7.8 through the `cadquery-ocp` bindings
(`backend/opticore/io/cad.py`).

**Export** (toolbar *Export CAD*, `POST /api/v1/export/cad`). The output is
STEP AP214 or IGES 5.3 with B-rep solids, in millimetres, in the optical
global frame (z along the optical axis, surface 1 vertex at the origin).

Contents:
* **Lenses:** one solid per glass element, so a cemented group is two solids
  sharing the cemented face.
  * They are revolved from the meridional profile: spheres as exact circular
    arcs, planes as lines, conics and even aspheres as interpolating
    B-splines. The maximum deviation from the exact sag is reported (below
    1e-6 mm in the tests).
  * The rim follows the element's mechanical data (OPTICAL_ENGINE §8j): the
    largest mechanical (else effective) semi-diameter plus the optional
    margin, flats beyond a smaller mechanical semi-diameter, 45° chamfers.
* **Mirrors:** a substrate solid behind the reflecting surface.
* **Optional extras:**
  * the aperture stop, as a circle
  * the image plane, as a disc
  * the meridional layout rays of every field, as polylines
  * imported CAD models with their placement: STEP/IGES from their exact
    source; STL as a sewn shell, up to 60 000 triangles
  * spacers, cells and a simple barrel around the elements (`Spacer 1
    (S2-S3)`, `Cell 1 (S3-S4)`, `Barrel`), for axial systems without mirrors
* Every item is named (e.g. `L1 N-BK7 (S1-S2)`, `M1 mirror (S4)`,
  `Aperture stop (S1, r = 5.0000 mm)`) and coloured through XDE, so CAD
  programs show a readable assembly.

**Skipped elements.** An element whose rim exceeds a sphere's radius or a
conic's extent, or whose edge thickness is not positive, is skipped with a
reason in the export report. Nothing is silently clipped.

**Import** (`.step/.stp/.iges/.igs`, `POST /api/v1/import/cad`):
* Files are read with the XDE readers, keeping body names, and converted to
  mm.
* Loose faces, which are common in IGES, are sewn into closed solids when
  possible.
* Each top-level body is listed with its exact B-rep volume, area and bounding
  box.
* The display mesh is tessellated with a linear deflection of 0.1 % of the
  bounding-box diagonal.
* The original file is stored with the asset (`source_b64`, up to 40 MB), so
  re-export uses the exact geometry.

**Round trip.** OptiCore → STEP/IGES → OptiCore reproduces every lens volume to
better than 1e-7 relative (tested).

**Using STEP/IGES parts optically:**
* *Optical…* in the CAD models tab recognises lens and mirror solids and
  inserts them as exact surfaces, including fitted aspheres, into the
  prescription.
* The *Optical role* column makes a model an absorber, a mirror or a
  refractive body for non-sequential tracing. It is stored as
  `cad_assets[].optical = { "role", "material", "coating": "" /* every face */,
  "scatter": { "model": "none|lambertian|gaussian|abg|harvey", "fraction": 0, "sigma_deg": 5,
  "abg_b": null, "abg_g": null, "harvey_l": null, "harvey_s": null } }`
  (ABg B and g, Harvey–Shack shoulder l and slope s; null = the defaults
  10⁻³, 2, 0.01, −2; OPTICAL_ENGINE §8h).
  `coating`, `scatter` and the BSDF parameters are optional, so older files
  stay valid.
* Assemblies are read with their full product structure. It is stored as
  `cad_assets[].tree` (node ids "1", "1.2", …; names, part or assembly,
  exact volume, area, bounding box, solid count, colour and the node's
  triangle range in the display mesh). `hidden_parts` lists hidden node ids,
  and `part_roles` maps node ids to optical role overrides with the same
  fields as `optical`. All three are optional. Models imported earlier can
  read their structure from the stored source ("Read assembly structure").
* Imported geometry gets no optical properties until you assign them: STEP
  geometry alone is not an optical prescription. Recognition (*Optical…*)
  proposes surfaces, and you confirm them before they are inserted.
