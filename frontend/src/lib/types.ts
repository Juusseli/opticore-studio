// TypeScript mirror of the backend schema (backend/opticore/model.py, project.py,
// optimize/merit.py). Schema version 1. Keep in sync with the backend.

export type SurfaceType = 'standard' | 'even_asphere' | 'odd_asphere' | 'biconic' | 'zernike' | 'qcon' | 'qbfs' | 'xy_polynomial' | 'coordinate_break' | 'ideal'
export type FieldType = 'angle' | 'object_height' | 'image_height' | 'paraxial_image_height'
export type ApertureType = 'epd' | 'image_fnum' | 'object_na'
export type RayAiming = 'paraxial' | 'real'
export type SemiDiameterMode = 'auto' | 'fixed'

/** Ideal polarising element at a surface (backend model.JonesElement). */
export interface JonesElement {
  kind: 'polarizer' | 'retarder'
  /** polariser: transmission axis; retarder: fast axis (deg, from local x towards local y) */
  angle_deg: number
  /** retarder: delay of the slow axis (waves) */
  retardance_waves: number
}

export interface Surface {
  id: string
  type: SurfaceType
  label: string
  comment: string
  radius: number | null // mm, null = infinity
  thickness: number | null // mm, null = infinity (object only)
  material: string
  semi_diameter: number
  semi_diameter_mode: SemiDiameterMode
  conic: number
  radius_x: number | null // biconic: x-z section radius (mm), null = flat in x
  conic_x: number // biconic: x-z section conic
  aspheric: number[] // A4, A6, ...
  is_stop: boolean
  /** where the optical surface ends (mm); null = it continues to the element's rim (elements.py) */
  mech_semi_diameter?: number | null
  /** 45° protective chamfer at the element's rim on this surface (mm, leg) */
  chamfer?: number
  coating: string // thin-film coating name (built-in or system.custom_coatings), '' = uncoated
  zernike_coefficients: number[] // Fringe Zernike sag terms Z1.. (mm), type 'zernike'
  /** odd asphere (type 'odd_asphere'): coefficients beta_1.. on r^1, r^2, ... (backend surfaces.OddShape) */
  odd_coefficients?: number[]
  /** Forbes Q coefficients a_0.. (mm), types 'qcon' / 'qbfs' (backend qpoly.py) */
  q_coefficients?: number[]
  q_norm_radius?: number
  /** XY-polynomial coefficients A_1.. (mm): x, y, x², xy, y², … in x/R, y/R (type 'xy_polynomial') */
  xy_coefficients?: number[]
  xy_norm_radius?: number
  zernike_norm_radius: number // mm
  grating_frequency: number // lines/mm (lines parallel to local x)
  focal_length: number | null // ideal lens: focal length in the surrounding medium (mm), null = no power
  ideal_object_distance: number | null // ideal lens: object distance (mm) for which the OPD is exact, null = infinity
  phase_coefficients: number[] // radial phase A1.. (radians at phase_norm_radius)
  phase_norm_radius: number // mm
  diffraction_order: number
  thickness_solve: Solve | null
  curvature_solve: Solve | null
  decenter_x: number
  decenter_y: number
  tilt_x: number
  tilt_y: number
  tilt_z: number
  cb_order: 0 | 1
  /** environment model: expansion (1e-6/K) of the spacer after this surface or of a mirror substrate; null = housing */
  mount_cte?: number | null
  /** mount tree: id of the MountPart holding this surface's vertex; null = placed by the gap before it */
  seat_part?: string | null
  /** temperature of the glass after this surface (its element); null = system */
  element_temperature_c?: number | null
  /** uniaxial crystal after this surface: optic axis in this surface's local frame (null = local z) */
  crystal_axis?: [number, number, number] | null
  /** wave the sequential trace follows in that crystal (null = ordinary) */
  crystal_mode?: 'ordinary' | 'extraordinary' | null
  /** ideal polariser / retarder at this surface (polarisation analyses) */
  jones?: JonesElement | null
  /** radius (mm) of a central circular obscuration: rays inside it are blocked (chief rays pass) */
  obscuration?: number | null
}

/** A mechanical part of the mount tree (backend environment.py). */
export interface MountPart {
  id: string
  name: string
  cte: number // 1e-6/K
  temperature_c: number | null // null = system temperature
  parent: string | null // null = the fixed reference
  datum_z: number // mm along the axis from surface 1, where it attaches to its parent
  cad_asset_id: string | null
  cad_node_id: string | null
}

/** Mount displacements at the system's environment (/system/mounts). */
export interface MountReport {
  enabled: boolean
  temperature_c?: number
  parts: { id: string; datum_shift_mm: number }[]
  seats: { surface: number; part: string; z_nominal_mm: number; shift_mm: number }[]
  diagnostics: Diagnostic[]
}

export type ConfigParameter =
  | 'thickness'
  | 'radius'
  | 'conic'
  | 'material'
  | 'semi_diameter'
  | 'decenter_x'
  | 'decenter_y'
  | 'tilt_x'
  | 'tilt_y'
  | 'tilt_z'
  | 'aperture_value'
  | 'temperature'
  | 'pressure'
  | 'vdx'
  | 'vdy'
  | 'vcx'
  | 'vcy'
/** configuration parameters that belong to the system, not to a surface */
export const CONFIG_SYSTEM_PARAMS: ConfigParameter[] = ['aperture_value', 'temperature', 'pressure']
/** a field's vignetting factors per configuration (a zoom lens vignettes differently at each position) */
export const CONFIG_FIELD_PARAMS: ConfigParameter[] = ['vdx', 'vdy', 'vcx', 'vcy']
export type ConfigValue = number | string | null

/** One row of the configuration editor: a parameter and its value in every configuration. */
export interface ConfigOperand {
  parameter: ConfigParameter
  surface_id: string | null // null for system and field parameters
  /** the field (index) of a field parameter (CONFIG_FIELD_PARAMS) */
  field?: number | null
  values: ConfigValue[]
}

export interface MultiConfig {
  names: string[]
  operands: ConfigOperand[]
  active: number
}

export type SolveType = 'marginal_height' | 'chief_height' | 'pickup' | 'marginal_angle' | 'chief_angle' | 'f_number'

/** Paraxial solve / pickup controlling a thickness or curvature (resolved by the engine). */
export interface Solve {
  type: SolveType
  target: number
  surface_id: string | null
  scale: number
  offset: number
  zone: number
}

export interface Wavelength {
  value: number // um
  weight: number
}

export interface FieldPoint {
  x: number
  y: number
  weight: number
  /** vignetting factors: the sampled pupil is px' = vdx + px (1 - vcx), py' = vdy + py (1 - vcy) (optional, 0) */
  vdx?: number
  vdy?: number
  vcx?: number
  vcy?: number
}

export interface VignettingResult {
  fields: { vdx: number; vdy: number; vcx: number; vcy: number; ok: boolean; note: string | null }[]
  wavelength_um: number
  method: string
}

export interface Aperture {
  type: ApertureType
  value: number
}

export interface OpticalSystem {
  name: string
  units: 'mm'
  surfaces: Surface[]
  wavelengths: Wavelength[]
  primary_wavelength: number
  field_type: FieldType
  fields: FieldPoint[]
  aperture: Aperture
  ray_aiming: RayAiming
  object_space_telecentric?: boolean // chief rays parallel to the axis in object space (entrance pupil at infinity)
  /** environment model (backend environment.py); off by default */
  temperature_c: number
  pressure_atm?: number
  environment_enabled?: boolean
  housing_cte?: number // 1e-6/K
  /** absorb in glass by the catalogue internal transmittance (per wavelength) where a material has it */
  catalog_absorption?: boolean
  /** image sensor for the sensor-aware analyses (pixel MTF, image simulation; backend analysis/imaging.py) */
  sensor?: Sensor | null
  mounts?: MountPart[]
  multi_config?: MultiConfig | null
  custom_coatings?: CoatingDefinition[]
}

/** Thin-film layer: fixed index n − ik, or n(λ) from a library material. */
export interface CoatingLayer {
  material: string // '' = fixed index
  index: number
  extinction: number
  thickness_nm: number
}

/** User-defined coating. Layers run from the low-index (air) side towards the substrate; on mirrors towards the metal substrate. */
export interface CoatingDefinition {
  name: string
  description: string
  layers: CoatingLayer[]
  substrate_index: number | null // mirror substrate n (null: not usable on mirrors)
  substrate_extinction: number
  /** coating designer source (palette, targets, deposition order) */
  design?: CoatingDesignSpec | null
}

export type VariableParam =
  | 'mount_cte'
  | 'curvature'
  | 'thickness'
  | 'conic'
  | 'asph_4'
  | 'asph_6'
  | 'asph_8'
  | 'asph_10'
  | 'asph_12'
  | 'decenter_x'
  | 'decenter_y'
  | 'tilt_x'
  | 'tilt_y'
  | 'tilt_z'
  | 'material'
  | 'curvature_x'
  | 'conic_x'
  | 'phase_1'
  | 'phase_2'
  | 'phase_3'
  | 'phase_4'
  | 'grating_frequency'
  | 'ideal_power'
  | `zern_${number}`
  | `q_${number}`
  | `xy_${number}`
  | `odd_${number}`
  | 'coating_scale'
  | `coat_layer_${number}`

export interface Variable {
  surface_id: string
  parameter: VariableParam
  min: number | null
  max: number | null
  enabled: boolean
  configuration?: number | null // per-configuration value (configuration editor)
  candidates?: string[] | null // material variables: allowed glasses (null = all catalogue glasses)
}

export type OperandType =
  | 'rms_spot'
  | 'throughput'
  | 'rms_wavefront'
  | 'mtf'
  | 'efl'
  | 'bfl'
  | 'fnum'
  | 'working_fnum'
  | 'total_track'
  | 'magnification'
  | 'axial_color'
  | 'distortion'
  | 'max_distortion'
  | 'max_lateral_color'
  | 'min_relative_illumination'
  | 'max_cra'
  | 'min_thickness'
  | 'max_thickness'
  | 'min_edge_thickness'
  | 'max_total_track'
  | 'surface_reflectance'
  | 'detector_size'
  | 'detector_power'

export interface Operand {
  type: OperandType
  target: number
  weight: number
  field: number | null
  wavelength: number | null
  surface_id: string | null
  rings: number
  reference: 'centroid' | 'chief'
  frequency?: number | null
  direction?: 'tangential' | 'sagittal' | 'average'
  configuration?: number | null // null = active configuration
  /** detector operands: id of the project detector */
  detector_id?: string | null
  /** exact constraints: a goal of the merit function or a constraint met to tolerance; auto by type (lib/constraints.ts) */
  role?: OperandRole
  enabled: boolean
}

export type OperandRole = 'auto' | 'objective' | 'constraint'

export interface OptimizationSpec {
  variables: Variable[]
  operands: Operand[]
  algorithm: 'local' | 'global' | 'multistart'
  max_evaluations: number
  multistart_runs: number
  seed: number
  /** constraint operands met to tolerance (augmented Lagrangian, engine optimize/constrained.py) or weighted penalties; absent = exact */
  constraints?: 'exact' | 'penalty'
}

export type MaterialFormula = 'sellmeier' | 'sellmeier_sq' | 'schott' | 'cauchy' | 'polynomial' | 'constant' | 'tabulated' | 'extended' | 'extended2' | 'extended3' | 'herzberger' | 'sellmeier2' | 'conrady' | 'handbook1' | 'handbook2' | 'sellmeier4'

export type GlassStatus = 'standard' | 'preferred' | 'obsolete' | 'special' | 'melt'

export interface MaterialRecord {
  name: string
  formula: MaterialFormula
  coefficients: number[]
  /** uniaxial crystals: extraordinary dispersion (the record's own formula is the ordinary index) */
  extraordinary?: { formula: MaterialFormula; coefficients: number[]; table?: number[][] | null; lambda_min?: number; lambda_max?: number | null; ne_d?: number | null } | null
  table?: number[][] | null
  /** extinction coefficient k(λ): [[λ µm, k], …] (films, metals) */
  extinction_table?: number[][] | null
  lambda_min?: number
  lambda_max?: number | null
  family?: string
  category?: string
  source?: string
  absorption_per_mm?: number
  thermal?: { D0: number; D1: number; D2: number; E0: number; E1: number; lambda_tk: number; T0: number } | null
  nd_ref?: number | null
  vd_ref?: number | null
  // glass-catalogue information (AGF import; display only)
  catalog?: string
  status?: GlassStatus
  verified?: boolean
  excluded?: boolean
  agf_formula?: number
  mil?: string
  comment?: string
  density?: number
  dpgf?: number
  tce_m30_70?: number
  relative_cost?: number
  internal_transmission?: number[][] // [lambda_um, internal transmittance, thickness_mm]
}

export interface MaterialSummary extends MaterialRecord {
  nd: number | null
  vd: number | null
  nF_minus_nC: number | null
  has_thermal_model: boolean
  builtin: boolean
}

/** A glass catalogue imported from an AGF file, kept in the browser (IndexedDB). */
export interface GlassCatalog {
  id: string
  name: string
  filename: string
  imported_at: string
  comments: string[]
  records: MaterialRecord[]
  summaries: MaterialSummary[]
  diagnostics: { level: 'info' | 'warning' | 'error'; message: string; glass: string | null }[]
}

export interface Revision {
  id: string
  timestamp: string
  label: string
  system: OpticalSystem
  merit?: number | null
}

export interface SavedAnalysis {
  id: string
  type: AnalysisKind
  label: string
  timestamp: string
  settings: Record<string, unknown>
  result: unknown
}

export interface Project {
  format: 'opticore-project'
  schema_version: number
  id: string
  metadata: {
    name: string
    description: string
    author: string
    created: string
    modified: string
    tags: string[]
    [k: string]: unknown
  }
  system: OpticalSystem
  custom_materials: MaterialRecord[]
  optimization: OptimizationSpec
  tolerancing: ToleranceSpec
  cad_assets: CadAsset[]
  sources?: LightSource[] // non-sequential light sources (optional in older files)
  detectors?: DetectorSpec[] // non-sequential detectors
  analysis_settings: {
    spot?: { pattern: 'hexapolar' | 'square' | 'dithered'; density: number; reference: 'centroid' | 'chief' }
    fan?: { samples: number }
    field?: { samples: number }
    wavefront?: { field: number; wavelength: number | null; grid: number }
    psf?: { field: number; wavelength: number | null; grid: number; pad: number; log: boolean }
    coating_design?: CoatingDesignSpec
    huygens?: { field: number; wavelength: number | null; pupil_samples: number; image_samples: number; image_delta_um: number | null; defocus_mm: number; transmission: boolean; log: boolean }
    mtf?: { kind: 'diffraction' | 'geometric'; max_frequency: number | null; samples: number; sensor?: boolean }
    gaussian?: { waist_radius: number; waist_distance: number; wavelength: number | null; m2: number }
    polarization?: { field: number; wavelength: number | null; grid: number; input: 'x' | 'y' | '45' | '-45' | 'rcp' | 'lcp' | 'unpolarized'; map: 'transmission' | 'diattenuation' | 'retardance' | 'rotation'; crystal_modes?: 'sum' | 'prescription' }
    saved?: SavedAnalysis[]
    [k: string]: unknown
  }
  ui: Record<string, unknown>
  revisions: Revision[]
  saved_optimizations: SavedOptimization[]
  provenance: { created_with: string; imports: unknown[]; warnings: string[]; [k: string]: unknown }
  checksum?: { algorithm: 'sha256'; value: string } | null
}

export type ToleranceType =
  | 'radius'
  | 'thickness'
  | 'conic'
  | 'index'
  | 'abbe'
  | 'power'
  | 'irregularity'
  | 'irregularity_rotational'
  | 'zernike_form'
  | 'surface_decenter_x'
  | 'surface_decenter_y'
  | 'surface_tilt_x'
  | 'surface_tilt_y'
  | 'element_decenter_x'
  | 'element_decenter_y'
  | 'element_tilt_x'
  | 'element_tilt_y'

export interface Tolerance {
  id: string
  type: ToleranceType
  surface_id: string
  surface_id_end: string | null // last surface of the group (element_* only)
  min: number
  max: number
  enabled: boolean
  /** Fringe Zernike term Z5..Z37 (zernike_form only) */
  term?: number | null
  /** kept as it is when tolerances are allocated to the specification */
  locked?: boolean
}

export interface Compensator {
  surface_id: string
  parameter: 'thickness' | 'curvature'
  range: number
  enabled: boolean
}

export interface ToleranceSpec {
  tolerances: Tolerance[]
  compensators: Compensator[]
  criterion: 'rms_spot' | 'rms_wavefront' | 'merit' | 'mtf'
  rings: number
  monte_carlo_trials: number
  distribution: 'normal' | 'uniform'
  seed: number
  compensator_evaluations: number
  /** cycles/mm (criterion mtf) */
  mtf_frequency?: number
  /** specification: criterion ≤ limit (≥ for MTF); yield and allocation */
  limit?: number | null
  /** test wavelength of the fringe tolerances (µm; ISO 10110-5: 0.54607) */
  test_wavelength_um?: number
}

export interface SensitivityRow {
  tolerance: number
  id: string
  type: ToleranceType
  surface_id: string
  surface_id_end: string | null
  term?: number | null
  min: number
  max: number
  unit: string
  at_min: number | null
  at_max: number | null
  at_min_uncompensated: number | null
  at_max_uncompensated: number | null
  at_min_compensators: number[]
  at_max_compensators: number[]
  worst_change: number
}

export interface ToleranceTrial {
  values: number[]
  value: number | null
  compensators: number[]
  /** orientation of each astigmatic irregularity in this trial (degrees) */
  angles_deg?: number[]
}

export interface ToleranceYield {
  limit: number
  passed: number
  trials: number
  fraction: number
  /** 95 % Wilson score interval */
  ci95: [number, number]
}

export interface AllocationRow {
  tolerance: number
  id: string
  type: ToleranceType
  surface_id: string
  surface_id_end: string | null
  term: number | null
  unit: string
  locked: boolean
  min: number
  max: number
  factor: number
  new_min: number
  new_max: number
  /** increase of the additive quantity at the new limits */
  q: number
  /** fraction of the budget */
  share: number | null
  capped: 'max' | 'min' | null
}

export interface ToleranceAllocation {
  limit: number
  nominal: number
  quantity: string
  budget: number
  share: number
  /** criterion with every tolerance at its allocated limit (quadrature model) */
  predicted: number
  rows: AllocationRow[]
}

export interface ToleranceResult {
  status: 'finished' | 'cancelled'
  criterion: ToleranceSpec['criterion']
  unit: string
  /** +1: lower is better; −1: higher is better (MTF) */
  sense?: 1 | -1
  nominal: number | null
  nominal_uncompensated: number | null
  sensitivity: SensitivityRow[]
  rss_change: number
  rss_estimate: number | null
  monte_carlo: {
    trials: number
    requested: number
    failures: number
    distribution: string
    seed: number
    statistics: Partial<Record<'mean' | 'std' | 'min' | 'max' | 'p2' | 'p10' | 'p50' | 'p90' | 'p98', number>>
    values: (number | null)[]
    best_trial: ToleranceTrial | null
    worst_trial: ToleranceTrial | null
    /** the trials used the allocated limits */
    allocated_limits?: boolean
  }
  yield?: ToleranceYield | null
  allocation?: ToleranceAllocation | null
  /** criterion merit with exact limits: the limits, reported apart from the criterion (they do not enter the yield) */
  limits?: ToleranceLimit[] | null
  tolerances: Tolerance[]
  compensators: Compensator[]
  evaluations: number
  elapsed_s: number
  notes: string[]
  method: string
}

export interface ToleranceLimit {
  index: number
  type: OperandType
  kind: 'target' | 'bound'
  surface_id: string | null
  field: number | null
  target: number
  tolerance: number
  unit: string
  nominal: number | null
  met_nominal: boolean
  monte_carlo: { trials: number; met: number; statistics: Partial<Record<'mean' | 'std' | 'min' | 'max' | 'p2' | 'p10' | 'p50' | 'p90' | 'p98', number>> }
}

export interface ToleranceSnapshot {
  id: string
  state: 'queued' | 'running' | 'finished' | 'cancelled' | 'failed'
  phase: string
  done: number
  total: number
  nominal: number | null
  trials: (number | null)[]
  elapsed_s: number
  error: string | null
  result: ToleranceResult | null
}

/** Imported CAD geometry (display, placement and measurement only; not ray traced). */
export interface CadAsset {
  id: string
  name: string
  source_filename: string
  format: 'stl' | 'step' | 'iges'
  units: string
  imported: string
  mesh: { positions_b64: string; indices_b64: string; vertices: number; triangles: number }
  bbox_min: [number, number, number]
  bbox_max: [number, number, number]
  surface_area_mm2: number
  volume_mm3: number | null
  closed: boolean
  diagnostics: { level: string; code: string; message: string }[]
  /** STEP/IGES: top-level bodies with exact B-rep properties */
  bodies?: CadBody[]
  /** STEP/IGES: original file (base64), re-exported exactly */
  source_b64?: string | null
  mesh_deflection_mm?: number | null
  /** p_global = Rx(rx) Ry(ry) Rz(rz) p + t (degrees, Three.js Euler 'XYZ') */
  transform: { translate: [number, number, number]; rotate_deg: [number, number, number] }
  /** role in non-sequential tracing */
  optical?: CadOptical
  /** STEP/IGES assembly structure (node ids '1', '1.2', …) with triangle ranges into the mesh */
  tree?: CadTreeNode[]
  /** node ids hidden in the views (and left out of non-sequential tracing) */
  hidden_parts?: string[]
  /** optical role overrides per node (inherited by its subtree) */
  part_roles?: Record<string, CadOptical>
  visible: boolean
  color: string
  opacity: number
}

export interface RecognizedFace {
  type: 'plane' | 'sphere' | 'conic' | 'asphere'
  radius: number | null
  conic: number
  aspheric: number[]
  semi_diameter: number
  fit_rms_mm: number
  fit_max_mm: number
  exact: boolean
}

export interface RecognizedElement {
  name: string
  front: RecognizedFace
  back: RecognizedFace
  thickness: number
  vertex: [number, number, number]
  axis: [number, number, number]
  rim_radius: number
  volume_mm3: number | null
}

export interface CadBody {
  name: string
  solids: number
  volume_mm3: number | null
  area_mm2: number
  bbox_min: [number, number, number]
  bbox_max: [number, number, number]
}

export interface CadTreeNode extends CadBody {
  id: string
  kind: 'assembly' | 'part'
  tri_start: number
  tri_count: number
  color: string | null
  children: CadTreeNode[]
}

export interface CadImportResult extends StlImportResult {
  bodies: CadBody[]
  tree?: CadTreeNode[]
  parts?: number
  source_b64: string
  mesh_deflection_mm: number
}

export interface CadExportResult {
  data_base64: string
  report: {
    solids: { name: string; surfaces: number[]; rim_radius_mm: number; front: string; back: string; volume_mm3: number | null; area_mm2: number }[]
    skipped: { surfaces: number[]; reason: string }[]
    mechanics?: { spacers: { between: number[]; inner_radius_mm: number; outer_radius_mm: number; length_mm: number; volume_mm3: number }[]; cells: { element_surfaces: number[]; inner_radius_mm: number; outer_radius_mm: number; volume_mm3: number }[]; barrel: { inner_radius_mm: number; outer_radius_mm: number; z_start_mm: number; z_end_mm: number; volume_mm3: number } | null }
    max_profile_deviation_mm: number
    notes: string[]
    items: { name: string; kind: string }[]
    cad_models?: string[]
    bytes: number
    format: 'step' | 'iges'
    units: string
  }
}

export interface StlImportResult {
  name: string
  format: string
  units: string
  triangles: number
  vertices: number
  bbox_min: [number, number, number]
  bbox_max: [number, number, number]
  size: [number, number, number]
  surface_area_mm2: number
  volume_mm3: number | null
  closed: boolean
  diagnostics: { level: string; code: string; message: string }[]
  positions_b64: string
  indices_b64: string
}

export interface SavedOptimization {
  id: string
  timestamp: string
  algorithm: string
  initial_merit: number
  final_merit: number
  evaluations: number
  status: string
  variables: OptVariableResult[]
  applied: boolean
}

// ---------------------------------------------------------------- results
export interface Diagnostic {
  level: 'info' | 'warning' | 'error'
  code: string
  message: string
  surface: number | null
}

export interface Paraxial {
  wavelength_um: number
  efl: number | null
  bfl: number | null
  ffl: number | null
  front_principal_plane: number | null
  rear_principal_plane: number | null
  power: number
  entrance_pupil_position: number | null
  entrance_pupil_diameter: number
  exit_pupil_position: number | null
  exit_pupil_diameter: number | null
  stop_semi_diameter: number
  image_space_fnum: number | null
  working_fnum: number | null
  image_space_na: number | null
  object_space_na: number | null
  paraxial_magnification: number | null
  paraxial_image_distance: number | null
  paraxial_image_height: number | null
  image_surface_defocus: number | null
  lagrange_invariant: number | null
  total_track: number
  max_field: number
  approximate: boolean
}

export interface SurfaceGeometry {
  index: number
  id: string
  type: SurfaceType
  semi_diameter: number
  origin: [number, number, number]
  matrix: number[][]
  profile: [number, number][]
  curvature: number
  conic: number
  curvature_x?: number
  conic_x?: number
  aspheric: number[]
  /** Zernike surfaces: base curvature and exact monomials c[i][j] (x/R)^i (y/R)^j for drawing */
  zernike?: { base_curvature: number; norm_radius: number; poly: number[][] } | null
  /** Q-type asphere: base and the departure series S(x) = Σ series[j] x^j, x = (r/r_n)² (for drawing) */
  qpoly?: { kind: 'qcon' | 'qbfs'; base_curvature: number; conic: number; norm_radius: number; series: number[] } | null
  /** odd asphere: base conic and beta_1.. on r^1.. (for drawing) */
  odd?: { base_curvature: number; conic: number; coefficients: number[] } | null
  is_mirror: boolean
  is_stop: boolean
  is_ideal?: boolean
  focal_length?: number | null
}

export interface LayoutRay {
  field: number
  wavelength: number
  px: number
  py: number
  status: string
  fail_surface: number
  points: [number, number, number][]
  start: [number, number, number]
  start_dir: [number, number, number]
}

export interface Evaluation {
  pupil: { entrance_pupil_z: number; entrance_pupil_radius: number; stop_radius: number }
  paraxial: Record<string, Paraxial>
  auto_semi_diameters: number[]
  semi_diameters: number[]
  surfaces: SurfaceGeometry[]
  elements: { front: number; back: number; material: string }[]
  rays: LayoutRay[]
  rays3d: LayoutRay[]
  ray_checks: { field: number; status: Record<string, number> }[]
  diagnostics: Diagnostic[]
  axial: boolean
  global_vertex_z: number[]
  indices: number[][] // [wavelength][surface]
  edge_thickness: (number | null)[]
  configuration: { active: number; names: string[] } | null
  solved: { surface: number; thickness: number | null; radius: number | null; thickness_solve: boolean; curvature_solve: boolean }[]
  method: string
}

/** Focus status (/analysis/focus): best polychromatic RMS focus along the image surface normal. */
export interface FocusResult {
  best_defocus_mm: number | null
  rms_um: number | null
  rms_best_um: number | null
  at_best_focus: boolean | null
  max_field_rms_um: number | null
  per_field: { field: number; rms_um: number | null; rms_best_um: number | null; n_rays: number }[]
  n_rays: number
  exact: boolean
  method: string
}

/** Temperature or pressure analysis (/analysis/thermal, backend analysis/thermal.py). */
export interface ThermalRow {
  value: number
  efl_mm?: number
  bfl_mm?: number | null
  paraxial_defocus_mm?: number | null
  best_focus_mm?: number | null
  rms_um?: number | null
  rms_best_um?: number | null
  rms_field_um?: (number | null)[]
  error?: string
}
export interface ThermalResult {
  variable: 'temperature' | 'pressure'
  unit: string
  values: number[]
  rows: ThermalRow[]
  reference: { value: number; efl_mm: number; working_fnum: number | null; depth_of_focus_mm: number | null; best_focus_mm?: number | null } | null
  slopes_per_unit: { best_focus_mm?: number; efl_mm?: number; paraxial_defocus_mm?: number }
  focus_spread_mm: number | null
  reference_temperature_c: number
  method: string
  notes: string[]
}

export interface SpotResult {
  fields: {
    field: number
    field_value: [number, number]
    reference_xy: [number, number]
    chief_xy: [number, number]
    centroid_xy: [number, number]
    rms_radius_um: number | null
    geo_radius_um: number | null
    per_wavelength: {
      wavelength: number
      points_um: [number, number][]
      n_rays: number
      n_ok: number
      status: Record<string, number>
      rms_um: number | null
      geo_um: number | null
    }[]
  }[]
  airy_radius_um: number | null
  settings: { pattern: string; density: number; reference: string; rays_per_wavelength: number }
  units: Record<string, string>
  method: string
}

export interface RayFanResult {
  pupil: number[]
  fields: {
    field: number
    field_value: [number, number]
    /** the tangential azimuth (unit x, y) the fans run along and across; +y for fields along y */
    direction?: [number, number]
    per_wavelength: { wavelength: number; tangential_ey_um: (number | null)[]; sagittal_ex_um: (number | null)[] }[]
  }[]
  units: Record<string, string>
  method: string
}

export interface FieldResult {
  field_values: number[]
  field_type: FieldType
  per_wavelength: {
    wavelength: number
    tangential_mm: (number | null)[]
    sagittal_mm: (number | null)[]
    distortion_percent: (number | null)[]
    real_chief_height_mm: (number | null)[]
    paraxial_height_mm: (number | null)[]
  }[]
  units: Record<string, string>
  method: string
}

export interface LongitudinalResult {
  pupil: number[]
  per_wavelength: { wavelength: number; focus_mm: (number | null)[] }[]
  units: Record<string, string>
  method: string
}

export interface ChromaticResult {
  wavelength_um: number[]
  focal_shift_um: number[]
  units: Record<string, string>
  method: string
}

export interface SeidelResult {
  surfaces: { surface: number; SI: number; SII: number; SIII: number; SIV: number; SV: number; CL: number; CT: number }[]
  total: { SI: number; SII: number; SIII: number; SIV: number; SV: number; CL: number; CT: number }
  lagrange_invariant: number
  wavelength_um: number
  approximate: boolean
}

export interface ParaxialResult {
  per_wavelength: Paraxial[]
  seidel: SeidelResult | { error: string }
  method: string
}

export type AnalysisKind = 'designspace' | 'liveimage' | 'advisor' | 'vectorpsf' | 'focus' | 'thermal' | 'mounts' | 'elements' | 'relillum' | 'imagesim' | 'fdtd' | 'spot' | 'rayfan' | 'field' | 'longitudinal' | 'chromatic' | 'paraxial' | 'opdfan' | 'wavefront' | 'interferogram' | 'spectrometer' | 'psf' | 'mtf' | 'throughput' | 'gaussian' | 'polarization' | 'sweep' | 'ghosts' | 'nonseq' | 'huygens' | 'coatings' | 'pop' | 'fibermodes' | 'fiberdisp' | 'fiber2d' | 'rcwa'

export interface OptVariableResult {
  surface_id: string
  parameter: VariableParam
  initial: number
  final: number
  min: number | null
  max: number | null
  at_bound: boolean
  sensitivity: number | null
}

export interface OperandBreakdown {
  type: OperandType
  value: number | null
  target: number
  weight: number
  contribution?: number
  unit?: string
  error?: string
  /** detector operands */
  detector?: string
  power_fraction?: number
  /** no variable can change this operand (a plane-parallel plate's edge, a fixed thickness) */
  fixed?: boolean
  failed_rays?: number
  /** exact constraints: the operand's role, its signed value in tolerances (<= 0 met for a bound, |g| <= 1 for a target) */
  role?: 'objective' | 'constraint'
  g?: number
  met?: boolean
}

/** One exact constraint of an optimisation result (engine optimize/constrained.py, Constraints.report). */
export interface ConstraintResult {
  index: number
  type: OperandType
  kind: 'target' | 'bound'
  surface_id: string | null
  field: number | null
  configuration: number | null
  target: number
  tolerance: number
  before: number | null
  after: number | null
  unit: string
  met_before: boolean
  met: boolean
  /** no variable can change it */
  fixed: boolean
  /** a target, or a bound within one tolerance of its limit */
  active: boolean
  multiplier: number | null
  /** first-order prediction (Lagrange multiplier) of the merit with the constraint relaxed by `step` */
  price: { dmerit_dtarget: number; relaxed_target: number; step: number; merit: number; merit_relaxed: number; change_percent: number; stationarity: number | null; approximate: boolean } | null
}

export interface OptimizationResult {
  /** error: the search stopped on an error; the best design found so far is returned; infeasible: constraints not met */
  status: 'converged' | 'max_evaluations' | 'cancelled' | 'failed' | 'error' | 'infeasible' | 'stopped'
  message: string
  /** the closing evaluation of the design returned and its sensitivity points (not part of `evaluations`) */
  closing_evaluations?: number
  /** exact constraints, one row each (null: weighted merit function) */
  constraints?: ConstraintResult[] | null
  constraint_mode?: 'exact' | 'penalty'
  notes?: string[]
  /** image-quality operands (rms_spot, rms_wavefront, mtf) that got worse while the merit function improved */
  objective_worse?: { index: number; type: OperandType; before: number; after: number; target: number; unit: string }[]
  /** Jacobian columns evaluated on the engine's process pool (null: serial) */
  parallel?: { workers: number; columns: number; seconds: number } | null
  /** variables (indices into `variables`) that do not change the merit function at all */
  inert_variables?: number[]
  /** violated targets no variable can change, with their share of the final merit function (MF²) */
  fixed_operands?: { index: number; type: OperandType; surface_id: string | null; value: number | null; target: number; share: number }[]
  algorithm: string
  initial_merit: number
  final_merit: number
  improvement_percent: number
  evaluations: number
  variables: OptVariableResult[]
  materials?: { surface_id: string; initial: string; final: string; candidates: string[] }[]
  operands_before: OperandBreakdown[]
  operands_after: OperandBreakdown[]
  history: [number, number, number][]
  system: OpticalSystem
  elapsed_s: number
}

/** Key numbers of a design (engine analysis/summary.py); null where not applicable, reason in `missing`. */
export interface DesignSummary {
  rms_spot_um: number[] | null
  airy_radius_um: number | null
  mtf: [number, number][] | null
  mtf_frequency: number | null
  efl_mm: number | null
  working_fnum: number | null
  total_track_mm: number | null
  field: number | null
  field_unit: 'deg' | 'mm'
  image_height_mm: number | null
  distortion_pct: number | null
  lateral_colour_um: number | null
  axial_colour_um: number | null
  relative_illumination: number | null
  cra_deg: number | null
  min_glass_edge_mm: number | null
  min_glass_edge_surface: string | null
  min_air_edge_mm: number | null
  min_air_edge_surface: string | null
  max_field_index: number | null
  /** RMS spot from the axis to the largest field (11 points) and the sampling gap between the defined fields */
  field_profile?: FieldProfile | null
  missing: Record<string, string>
}

export type CompareKey = 'rms_spot_um' | 'mtf' | 'distortion_pct' | 'lateral_colour_um' | 'axial_colour_um' | 'relative_illumination' | 'cra_deg' | 'total_track_mm' | 'min_glass_edge_mm' | 'min_air_edge_mm' | 'field' | 'efl_mm' | 'field_gap'

/** The RMS spot between the defined fields (engine analysis/summary.py, field_profile). */
export interface FieldProfile {
  /** fractions of the largest field, 0…1 */
  fractions: number[]
  rms_um: (number | null)[]
  /** radial fractions of the system's own fields */
  defined: number[]
  /** worst point between the fields that the merit function does not see, or null */
  gap: { fraction: number; rms_um: number | null; sampled_max_um: number; ratio: number | null } | null
}

/** Before/after numbers and what got worse (engine /optimize/compare). */
export interface DesignComparison {
  before: DesignSummary
  after: DesignSummary
  flags: { key: CompareKey; kind: 'worse' | 'changed'; field: number | null; before: number; after: number }[]
}

/** A trade-off curve (engine optimize/tradeoff.py): the best merit as one limit moves. */
export interface TradeoffPoint {
  index: number
  target: number
  status: 'finished' | 'failed' | 'cancelled'
  merit?: number
  feasible?: boolean
  /** the limit's value in the point's design */
  value?: number | null
  multiplier?: number | null
  price?: ConstraintResult['price']
  optimiser_status?: OptimizationResult['status']
  evaluations?: number
  elapsed_s?: number
  error?: string
  /** the front: the best feasible merit known at this target (for a bound, found here or at a tighter target) */
  envelope?: number | null
  envelope_from?: number | null
}

export interface TradeoffSnapshot {
  id: string
  state: 'running' | 'finished' | 'cancelled' | 'failed'
  total: number
  done: number
  failed: number
  elapsed_s: number
  error: string | null
  abandoned: boolean
  operand: number
  type: OperandType
  kind: 'target' | 'bound'
  /** +1: the bound loosens upwards (≤), −1: downwards (≥) */
  sign: number
  current: number
  targets: number[]
  points: TradeoffPoint[]
}

export interface JobSnapshot {
  id: string
  state: 'queued' | 'running' | 'paused' | 'finished' | 'cancelled' | 'failed'
  phase: string
  evaluations: number
  initial_merit: number | null
  current_merit: number | null
  best_merit: number | null
  best_values: number[] | null
  best_materials?: Record<string, string> | null
  /** exact limits of the run, and how many of them the best design does not meet yet */
  constraints?: number
  unmet?: number | null
  history: [number, number, number][]
  elapsed_s: number
  error: string | null
  result: OptimizationResult | null
}

/** Thumbnail drawing data from the engine (/system/outline): global (z, y) polylines of the layout. */
export interface SystemOutline {
  bbox: [number, number, number, number] // zmin, zmax, ymin, ymax
  items: { kind: 'glass' | 'mirror' | 'surface' | 'stop' | 'image' | 'object' | 'ideal'; points: [number, number][] }[]
  rays: { field: number; ok: boolean; points: [number, number][] }[]
  infinite_object: boolean
}

export type SampleCategory = 'liveimage' | 'imaging' | 'fibre' | 'lighting' | 'gratings' | 'mirrors' | 'multiconfig'

export interface SampleInfo {
  id: string
  name: string
  description: string
  category?: SampleCategory
  outline?: SystemOutline | null
}

export interface OpdFanResult {
  pupil: number[]
  fields: {
    field: number
    field_value: [number, number]
    per_wavelength: { wavelength: number; tangential_waves: (number | null)[]; sagittal_waves: (number | null)[]; error?: string }[]
  }[]
  units: Record<string, string>
  method: string
}

export interface WavefrontResult {
  field: number
  wavelength: number
  wavelength_um: number
  grid: number
  x: number[]
  y: number[]
  map_waves: (number | null)[][]
  rms_waves: number
  pv_waves: number
  strehl_marechal: number
  valid_fraction: number
  zernike: { convention: string; terms: { index: number; n: number; m: number; name: string; value: number }[]; fit_residual_rms_waves: number | null }
  reference: { reference_center_mm: number[]; reference_radius_mm: number; exit_pupil_point_mm: number[] }
  units: Record<string, string>
  method: string
}

export interface HuygensResult {
  field: number
  wavelength: number
  wavelength_um: number
  strehl: number
  peak_um: [number, number]
  x_um: number[]
  y_um: number[]
  psf: number[][]
  centroid_um: [number, number]
  chief_image_mm: [number, number]
  encircled_energy: { radius_um: number[]; fraction: number[] }
  airy_radius_um: number | null
  working_fnum: number | null
  reference_radius_mm: number
  defocus_mm: number
  sampling: { pupil_samples: number; rays: number; image_samples: number; image_delta_um: number; max_pupil_phase_step_waves: number; alias_period_um: number }
  warnings: string[]
  units: Record<string, string>
  method: string
}

export interface PsfResult {
  field: number
  wavelength: number
  wavelength_um: number
  strehl: number
  working_fnum: number
  airy_radius_um: number
  dx_um: number
  x_um: number[]
  y_um: number[]
  psf: number[][]
  centroid_um: [number, number]
  encircled_energy: { radius_um: number[]; fraction: number[] }
  settings: { grid: number; pad: number }
  units: Record<string, string>
  method: string
}

export interface MtfResult {
  frequency_cyc_per_mm: number[]
  fields: { field: number; tangential: number[]; sagittal: number[] }[]
  diffraction_limit: number[]
  cutoff_cyc_per_mm: number[]
  kind: 'diffraction' | 'geometric'
  units: Record<string, string>
  method: string
  /** with a sensor: pixel MTF, Nyquist and the system MTF (lens × pixel) per field */
  sensor?: { nyquist_cyc_per_mm: number; pixel_mtf: number[]; fields: { field: number; tangential: number[]; sagittal: number[] }[]; pitch_um: number; fill_factor: number }
}

export interface Sensor {
  pixel_pitch_um: number
  fill_factor: number
  width_px: number
  height_px: number
  full_well_e: number
  read_noise_e: number
  bit_depth: number
}

export interface RelativeIlluminationResult {
  field_values: number[]
  field_unit: string
  image_heights_mm: number[]
  relative_illumination: number[]
  etendue_relative: number[]
  area_ratio_relative: number[]
  unvignetted_fraction: number[]
  wavelength: number
  method: string
}

export interface ImageSimResult {
  width_px: number
  height_px: number
  pixel_pitch_um: number
  sensor_defined: boolean
  scene: string
  /** base64 uint16 little-endian, rows from the top; 65535 = full well */
  images: { ideal: string; optics: string; sensor: string; encoding: string }
  energy: { in_scene_x_ri: number; on_sensor: number; blurred_total: number; kept_fraction: number | null }
  relative_illumination: { field_values: number[]; relative_illumination: number[]; image_heights_mm: number[] }
  distortion: { r_real_mm: number[]; r_ideal_mm: number[] }
  psf_nodes: { x_mm: number; y_mm: number; field: [number, number]; peak: number }[]
  nyquist_cyc_per_mm: number
  settings: Record<string, unknown>
  notes: string[]
  method: string
}

/** Surface scatter model (BSDF) of a CAD body (non-sequential mode; backend bsdf.py). */
export interface CadScatter {
  model: 'none' | 'lambertian' | 'gaussian' | 'abg' | 'harvey'
  /** absorber: diffuse reflectance; mirror: scattered part of the reflected power; refractive: scattered part of the transmitted power (ABg / Harvey: TIS at normal incidence) */
  fraction: number
  sigma_deg: number
  /** ABg f = A/(B + x^g), A from the TIS; null = 1e-3 */
  abg_b?: number | null
  /** null = 2 */
  abg_g?: number | null
  /** Harvey-Shack f = b0 (1 + (x/l)^2)^(s/2); shoulder l in direction cosines, null = 0.01 */
  harvey_l?: number | null
  /** slope s < 0, null = -2 */
  harvey_s?: number | null
}

/** Importance sampling of scattered light towards a target (request of the non-sequential analysis). */
export interface NsImportance {
  target: { kind: 'none' | 'detector' | 'legacy' | 'surface'; id?: string | null; index?: number | null }
  /** extra rays per scatter event */
  rays: number
}

/** Detected power grouped by event path: S:<object> scatter, R:<object> partial (Fresnel) reflection. */
export interface NsPathRow {
  path: string
  power_w: number
  /** of the detector's power */
  fraction: number
  hits: number
  sigma_w: number
  /** legacy detector: power and sigma as fractions of the emitted power */
  power?: number
  sigma?: number
}

export interface CadOptical {
  role: 'none' | 'absorber' | 'mirror' | 'refractive'
  material: string | null
  coating?: string
  scatter?: CadScatter
}

export interface NonSeqResult {
  field: number
  wavelength_um: number
  source: { rays: number; overfill?: number; power: number; pupil_fraction?: number }
  sources: { name: string; kind: string; rays: number; power_w: number }[]
  total_power_w: number
  energy: { detected: number; detected_direct: number; detected_after_reflections: number; detected_after_scatter: number; absorbed: Record<string, number>; coating_absorption: number; escaped: number; discarded_reflections: number; truncated: number; bulk_absorption: number; scattered: number; importance_added?: number; importance_dropped?: number; detector_rejected?: number; detector_back?: number; total: number }
  /** legacy image-surface detector; power_sigma, stray and stray_sigma as fractions of the emitted power */
  detector: { power_sigma: number; stray: number; stray_sigma: number; paths: NsPathRow[]; radius_mm: number; pixels: number; irradiance: number[][]; units: string; hits: number; scatter_hits: number; direct_centroid_mm: [number, number] | null; direct_rms_mm: number | null } | null
  detectors: DetectorResult[]
  objects: { name: string; role: string; material: string | null; exact: boolean; coating: string | null; scatter: { model: string; fraction: number; sigma_deg: number; A?: number; B?: number; g?: number; b0?: number; l?: number; s?: number } | null }[]
  paths: { points: [number, number, number][]; reflections: number; scatters: number; end: string }[]
  settings: Record<string, unknown> & { importance?: { target: string; rays: number } | null }
  source_rays?: number
  events: number
  elapsed_s: number
  notes: string[]
  method: string
}

export interface GhostResult {
  field: number
  wavelength_um: number
  main: { energy_fraction: number; geo_radius_mm: number; airy_radius_mm: number; working_fnum: number }
  ghosts: {
    reflect_first: number
    reflect_second: number
    energy_fraction: number
    rms_radius_mm: number | null
    geo_radius_mm: number | null
    relative_irradiance: number | null
    focus_from_image_mm: number | null
    rays_ok: number
    rays: number
    mean_R_first?: number
    mean_R_second?: number
    centroid_mm?: [number, number]
    paths_zy: [number, number][][]
  }[]
  pairs_skipped_no_index_step: number
  settings: { rings: number; rays: number }
  units: Record<string, string>
  method: string
}

export interface SweepResult {
  axes: number[][]
  parameters: { surface_id: string; parameter: VariableParam; configuration: number | null; start: number; stop: number; steps: number; unit: string; current: number | null }[]
  metrics: { type: string; field: number | null; wavelength: number | null; configuration: number | null; frequency: number | null; unit: string; nominal: number | null; values: (number | null)[] | (number | null)[][] }[]
  points: number
  errors: string[]
  elapsed_s: number
  method: string
}

export interface PolarizationResult {
  field: number
  wavelength_um: number
  input: string
  grid: number
  px: number[]
  py: number[]
  ok: boolean[]
  transmission: (number | null)[]
  unpolarized_transmission: (number | null)[]
  diattenuation: (number | null)[]
  retardance_waves: (number | null)[]
  rotation_deg: (number | null)[]
  ellipse: { azimuth_rad: (number | null)[]; ellipticity_rad: (number | null)[] } | null
  summary: {
    unpolarized_transmission: number | null
    x_transmission: number | null
    y_transmission: number | null
    input_transmission: number | null
    mean_diattenuation: number | null
    max_diattenuation: number | null
    rms_retardance_waves: number | null
    max_retardance_waves: number | null
    max_rotation_deg: number | null
    vignetted_fraction: number
    /** the beam's Mueller matrix (pupil average; m00 = unpolarised transmission) */
    mueller?: number[][]
    depolarization_index?: number
    /** output Stokes vector for the input state, normalised to S0 = 1 */
    output_stokes?: number[] | null
    output_dop?: number | null
    crystal_modes?: 'sum' | 'prescription'
    wave_combinations?: number
    /** largest lateral separation of the crystal waves (sum mode) */
    wave_separation_mm?: number | null
  }
  crystals?: { surface: number; material: string; mode: 'ordinary' | 'extraordinary'; no: number; ne: number; axis: number[] }[]
  jones_elements?: { surface: number; kind: 'polarizer' | 'retarder'; angle_deg: number; retardance_waves: number | null }[]
  units: Record<string, string>
  method: string
}

export interface VectorPsfProfile {
  x_um: number[]
  total: number[]
  x: number[]
  y: number[]
  z: number[]
}

/** Debye–Wolf vector PSF (backend analysis/vectorpsf.py); intensities relative to the peak. */
export interface VectorPsfResult {
  field: number
  wavelength_um: number
  input: string
  na: number
  n_image: number
  x_um: number[]
  intensity: number[][]
  components: { x: number[][]; y: number[][]; z: number[][] }
  profile_x: VectorPsfProfile
  profile_y: VectorPsfProfile
  peak_um: [number, number]
  fwhm_x_um: number | null
  fwhm_y_um: number | null
  fwhm_x_waves: number | null
  fwhm_y_waves: number | null
  half_max_area_um2: number
  half_max_area_waves2: number
  energy_fraction: { x: number; y: number; z: number }
  strehl: number | null
  scalar_airy_fwhm_um: number
  transmission: number
  vignetted_fraction: number
  defocus_um: number
  samples: number
  section?: { x_um: number[]; z_um: number[]; intensity: number[][] }
  units: Record<string, string>
  method: string
}

export interface GaussianResult {
  wavelength_um: number
  m2: number
  object: { waist_radius: number; waist_distance: number; rayleigh_range: number; divergence_half_angle_mrad: number; index: number }
  image: {
    waist_radius: number
    waist_from_last_surface: number
    waist_from_image_surface: number
    rayleigh_range: number
    divergence_half_angle_mrad: number
    depth_of_focus: number
    w_at_image_surface: number
    R_at_image_surface: number | null
    index: number
  }
  surfaces: { surface: number; w: number; R_in: number | null; R_out: number | null; semi_diameter?: number; clip_transmission?: number }[]
  segments: { after_surface: number; index: number; length: number; waist_from_start: number; waist_inside: boolean; waist_radius: number; rayleigh_range: number }[]
  curve: { z: (number | null)[]; w: (number | null)[] }
  surface_z: number[]
  notes: string[]
  units: Record<string, string>
  method: string
}

export interface CoatingSummary {
  name: string
  description: string
  layers: (CoatingLayer & { label?: string })[]
  substrate_index: number | null
  substrate_extinction: number
  builtin: boolean
  /** built-in library: what the design is for */
  category?: string
  design_nm?: number | null
  band_nm?: [number, number] | null
  angle_deg?: number
  incident_index?: number
  design_substrate_index?: number | null
  /** library glass the built-in is designed on (e.g. N-BK7) */
  design_substrate_material?: string | null
  /** the specification it meets (coating-designer targets) */
  spec?: CoatingTarget[]
}

/** /coatings/analyze and /coating-design/analyze (backend coatanalysis.py). */
export interface CoatingAnalysis {
  lambda_nm: number[]
  angle_deg: number
  reference_nm: number
  spectrum: Record<'R' | 'T' | 'A' | 'Rs' | 'Rp' | 'Ts' | 'Tp' | 'As' | 'Ap' | 'OD', (number | null)[]>
  angles: { angle_deg: number; R: number[]; T: number[] }[]
  angle_curve: { wavelength_nm: number; angles_deg: number[]; R: number[]; Rs: number[]; Rp: number[]; T: number[]; Ts: number[]; Tp: number[]; A: number[] }
  /** degrees, fs and fs²; t entries are absent for an opaque substrate; null where the power is below phase_min_power */
  phase: Partial<Record<'phase_rs' | 'phase_rp' | 'phase_ts' | 'phase_tp' | 'gd_rs' | 'gd_rp' | 'gd_ts' | 'gd_tp' | 'gdd_rs' | 'gdd_rp' | 'gdd_ts' | 'gdd_tp' | 'psi' | 'delta', (number | null)[]>>
  phase_min_power: number
  colour: {
    illuminant: string
    observer: string
    R: CoatingColour
    T: CoatingColour
    Rv: number
    Tv: number
  }
  field: { wavelength_nm: number; angle_deg: number; polarization: 's' | 'p'; z_nm: number[]; e2: number[]; boundaries_nm: number[]; layer_absorptance: number[]; R: number; T: number; substrate_absorptance: number; labels: string[] }
  profile: { wavelength_nm: number; layers: { label: string; z0: number; z1: number; n: number; k: number; thickness_nm: number; qwot: number }[]; total_nm: number; incident_n: number; substrate_n: number; substrate_k: number }
  /** |E|² against wavelength (rows) and depth over the analysed band */
  field_map?: { wavelength_nm: number[]; z_nm: number[]; e2: number[][]; boundaries_nm: number[]; polarization: 's' | 'p'; angle_deg: number }
  /** admittance diagram at the reference wavelength, s and p */
  admittance?: Record<'s' | 'p', CoatingAdmittance>
  band?: { lambda_min_nm: number; lambda_max_nm: number; R: { mean: number; min: number; max: number }; T: { mean: number; min: number; max: number }; A: { mean: number; min: number; max: number } }
  at_reference: Record<'R' | 'T' | 'A' | 'Rs' | 'Rp' | 'Ts' | 'Tp', number>
  notes: string[]
  method: string
}

export interface CoatingAdmittance {
  wavelength_nm: number
  angle_deg: number
  polarization: 's' | 'p'
  eta0: [number, number]
  substrate: [number, number]
  /** one arc per layer, from the substrate outwards */
  arcs: { label: string; n: number; k: number; thickness_nm: number; re: number[]; im: number[] }[]
  end: [number, number]
  R: number
  phase_r_deg: number
  iso_R: { R: number; centre: number; radius: number }[]
}

/** A measured R or T spectrum for reverse engineering (values as fractions). */
export interface CoatingMeasurement {
  quantity: 'R' | 'T'
  polarization: 'avg' | 's' | 'p'
  angle_deg: number
  lambda_nm: number[]
  value: number[]
  weight?: number
}

export interface CoatingFit {
  mode: 'scale' | 'layers' | 'scale_layers' | 'none'
  /** kind: scale and layer are relative thickness errors; dA, dB, k, dns index corrections (units) */
  variables: { name: string; kind?: 'scale' | 'layer' | 'dA' | 'dB' | 'k' | 'dns'; units?: string; error: number; sigma: number }[]
  layer_errors: number[]
  correlation: number[][]
  rms_before: number
  rms_after: number
  fitted_design: CoatingDesignSpec
  curves: { quantity: 'R' | 'T'; polarization: string; angle_deg: number; lambda_nm: number[]; measured: number[]; design: number[]; fitted: number[] }[]
  status: string
  elapsed_s: number
  warnings: string[]
  method: string
}

export interface CoatingColour {
  /** luminous fraction (Rv or Tv) */
  Y: number
  x: number | null
  y: number | null
  L: number
  a: number
  b: number
  /** display colour (sRGB, normalised to its brightest channel) */
  srgb: [number, number, number]
}

/** A worked coating-design example (backend tools/coating_examples.py). */
export interface CoatingExample {
  id: string
  name: string
  category: string
  description: string
  contest_mf?: number
  layers_front?: number
  layers_back?: number
  thickness_um?: [number, number]
  reference?: Record<string, unknown>
  design: CoatingDesignSpec
}

/** Analysis settings shared by the coating editor and designer. */
export interface CoatingAnalysisParams {
  lambda_min_nm: number
  lambda_max_nm: number
  samples?: number
  angle_deg: number
  angles_deg: number[]
  reference_nm: number | null
  band_nm: [number, number] | null
  field_pol: 's' | 'p'
  illuminant?: CoatingIlluminant
  observer?: '2' | '10'
}
export type CoatingIlluminant = 'D65' | 'D50' | 'D55' | 'D75' | 'A' | 'C' | 'F2' | 'F7' | 'F11'

export interface CoatingCurve {
  wavelength_um: number[]
  reflectance: number[]
  transmittance: number[]
  absorptance: number[]
  rs: number[]
  rp: number[]
  coating: string
  substrate_index: number
  substrate_extinction: number
  angle_deg: number
  mirror: boolean
  method: string
}

export interface ThroughputResult {
  fields: { field: number; field_value: [number, number]; per_wavelength: { wavelength: number; geometric: number; total: number; surface_losses: number | null }[] }[]
  absorption?: { catalog: boolean; materials: { name: string; source: 'catalogue' | 'constant' | 'none'; catalog_data: boolean; alpha_per_mm: number[] }[] }
  notes?: string[]
  weighted_mean_total: number
  chief_ray_surfaces: { surface: number; transmission: number; cumulative: number; mirror: boolean; coating?: string | null }[]
  settings: { rings: number; rays: number }
  units: Record<string, string>
  method: string
}

// ---- thin-film coating design (backend coatdesign.py) ----
export interface PaletteMaterial {
  key: string
  label: string
  material: string // library material ('' = fixed index)
  index: number
  extinction: number
  tooling: number
  rate_nm_s: number
  /** index corrections (e.g. from a measurement fit): n(λ) + index_offset + index_offset_b / λ_µm² */
  index_offset?: number
  index_offset_b?: number
}
export interface DesignLayer {
  material: string // palette key
  thickness_nm: number
  locked: boolean
}
/** R, T, A, Rv, Tv: fractions; GD fs, GDD fs², phase and retardance degrees; L*, a*, b* CIELAB (D65, 2°). */
export type CoatingQuantity = 'R' | 'T' | 'A' | 'GD' | 'GDD' | 'phase' | 'retardance' | 'Rv' | 'Tv' | 'L*' | 'a*' | 'b*'
export interface CoatingTarget {
  quantity: CoatingQuantity
  /** GD, GDD, phase, retardance, L*, a*, b*: of the reflected or the transmitted light */
  of?: 'R' | 'T'
  /** a tabulated target curve [[λ nm, value], …] (replaces value / ramp / points) */
  table?: [number, number][] | null
  /** colour targets: CIE illuminant and observer */
  illuminant?: CoatingIlluminant
  observer?: '2' | '10'
  polarization: 'avg' | 's' | 'p'
  angle_deg: number
  lambda_min_nm: number
  lambda_max_nm: number
  value: number
  value_end: number | null
  kind: '=' | '<=' | '>='
  weight: number
  tolerance: number
  points: number
}
/** Layers in deposition order: layer 1 on the substrate. */
export interface CoatingDesignSpec {
  name: string
  incident: string
  /** fixed, non-absorbing incident index (e.g. the glass of a cube beam splitter); overrides `incident` */
  incident_index?: number | null
  substrate: string
  /** fixed substrate n − ik (a metal mirror); overrides `substrate` */
  substrate_index?: number | null
  substrate_extinction?: number
  /** project coating this design belongs to */
  source_coating?: string
  back_side: 'none' | 'uncoated' | 'coated'
  /** back-side coating (back_side 'coated'): deposition order on the back face, layer 1 on the substrate */
  back_layers?: DesignLayer[]
  /** the back face carries the front coating itself (a symmetric plate, optimised together) */
  back_same_as_front?: boolean
  /** substrate thickness: its bulk absorption and the group delay of the transmitted light (null: neither) */
  substrate_thickness_mm?: number | null
  /** index correction of the substrate (e.g. from a fit) */
  substrate_offset?: number
  palette: PaletteMaterial[]
  layers: DesignLayer[]
  targets: CoatingTarget[]
  design_wavelength_nm: number
  min_thickness_nm: number
  max_thickness_nm: number
}
export type CoatingTemplateKind = 'ar_broadband' | 'v_coat' | 'hr' | 'longpass' | 'shortpass' | 'bandpass' | 'notch' | 'beamsplitter' | 'enhanced_mirror' | 'protected_mirror'
export interface CoatingEvaluation {
  lambda_nm: number[]
  angle_deg: number
  spectrum: { R: number[]; T: number[]; A: number[]; Rs: number[]; Rp: number[]; Ts: number[]; Tp: number[] }
  layers: { index: number; material: string; thickness_nm: number; n_design: number; k_design: number; qwot: number; cumulative_nm: number; locked: boolean }[]
  total_thickness_nm: number
  layer_count: number
  substrate_n_design: number
  incident_n_design: number
  merit: number | null
  targets: { quantity?: CoatingQuantity; units?: string; lambda_nm: number[]; target: number[]; value: number[]; rms_violation: number; max_violation: number; met: boolean; mean: number; min: number; max: number }[]
  /** the layers as a stack formula (incident side first, quarter waves at λ₀) */
  formula?: string
  back_formula?: string
  opaque_substrate?: boolean
  warnings: string[]
  method: string
}
export interface CoatingOptimizeResult {
  design: CoatingDesignSpec
  initial_merit: number
  final_merit: number
  history: { step: string; merit: number; layers: number }[]
  status: string
  elapsed_s: number
  warnings: string[]
  method: string
}
export interface CoatingMonteCarlo {
  lambda_nm: number[]
  quantity: 'R' | 'T' | 'A'
  nominal: number[]
  p05: number[]
  p50: number[]
  p95: number[]
  merit: { nominal: number; mean: number; p95: number } | null
  yield: number | null
  settings: { sigma_rel: number; sigma_abs_nm: number; runs: number; seed: number }
  method: string
}
export interface CoatingRecipeRow {
  layer: number
  material: string
  material_name: string
  thickness_nm: number
  qwot_design: number
  qwot_monitor: number
  n_monitor: number
  cumulative_nm: number
  monitor_start: number
  monitor_end: number
  turning_points: number
  termination: 'turning point' | 'level'
  crystal_nm: number
  crystal_kA: number
  rate_nm_s: number
  time_s: number
}
export interface CoatingRecipe {
  name: string
  substrate: string
  incident: string
  monitor_wavelength_nm: number
  monitor: 'T' | 'R'
  monitor_back_side: 'none' | 'uncoated'
  layers: CoatingRecipeRow[]
  curves: { layer: number; thickness_nm: number[]; signal: number[] }[]
  total_thickness_nm: number
  total_time_s: number
  palette: PaletteMaterial[]
  warnings: string[]
  notes: string[]
}

export interface CoatingAngular {
  angles_deg: number[]
  curves: { wavelength_nm: number; R: number[]; T: number[]; A: number[]; Rs: number[]; Rp: number[]; Ts: number[]; Tp: number[] }[]
  map: { lambda_nm: number[]; angles_deg: number[]; R: number[][]; T: number[][] }
  opaque_substrate: boolean
  warnings: string[]
  method: string
}
export interface AngleStats {
  min: number
  max: number
  mean: number
  p95: number
}
export interface SurfaceCoatingContext {
  surface: number
  is_mirror: boolean
  coating: string
  wavelength_band_nm: [number, number]
  primary_nm: number
  rays: number
  incident: string
  substrate: string | null
  light_from: 'incident' | 'substrate'
  angles_deg: AngleStats | null
  angles_in_medium: string
  angles_actual_deg?: AngleStats
  tir_fraction?: number
}
export interface CoatingPerformance {
  lambda_nm: number[]
  surfaces: { surface: number; label: string; coating: string | null; mirror: boolean; media: [string, string]; angles_deg: AngleStats; R: { mean: number[]; max: number[]; normal: number[] }; T: { mean: number[]; max: number[]; normal: number[] } }[]
  system_transmission_estimate: number[]
  system_wavelengths_nm: number[]
  method: string
}

export interface CadPartRef {
  asset_id: string
  part_id: string | null
}
export interface CadMeasureResult {
  points: { point: [number, number, number]; picked: [number, number, number]; offset_mm: number; exact: boolean; part: string }[]
  distance: { distance_mm: number; delta_mm: [number, number, number] } | null
}
export interface CadClearanceResult {
  distance_mm: number
  point_a: [number, number, number]
  point_b: [number, number, number]
  a: string
  b: string
  touching: boolean
  interference_volume_mm3: number
  exact: boolean
  method: string
}
export interface CadSectionResult {
  assets: { asset_id: string; parts: { part_id: string | null; polylines: [number, number, number][][] }[]; error?: string }[]
  plane: { origin: number[]; normal: number[] }
}

// ------------------------------------------------------------------ non-sequential sources and detectors (backend nssources.py)
export interface Placement {
  position: [number, number, number] // mm, global optical frame
  rotation_deg: [number, number, number] // XYZ about the local axes (as CAD models)
  /** surface id: position and rotation relative to that surface's vertex frame (null: global) */
  anchor?: string | null
  /** point the local +z axis at this point (same frame as the position); rotation_deg[2] is then the roll */
  aim?: [number, number, number] | null
}

export type SourceShape = 'point' | 'disk' | 'rectangle' | 'sphere' | 'box'
export type SourceAngular = 'collimated' | 'isotropic' | 'lambertian' | 'cosine_power' | 'cone' | 'gaussian' | 'table'

/** General light source: emits about its local +z axis. */
export interface LightSource {
  id: string
  name: string
  enabled: boolean
  kind: 'emitter' | 'system_field' | 'gaussian_beam'
  field: number
  overfill: number
  power_w: number
  rays: number
  placement: Placement
  shape: SourceShape
  size_x: number
  size_y: number
  size_z: number
  spatial: 'uniform' | 'gaussian'
  gaussian_wx: number
  gaussian_wy: number
  angular: SourceAngular
  half_angle_deg: number
  cos_power: number
  gaussian_x_deg: number
  gaussian_y_deg: number
  table: number[][]
  wavelengths: Wavelength[] // empty: the system's wavelengths
  /** Gaussian beam (kind gaussian_beam): waist 1/e² radii (mm), M², waist position along +z from the source plane (mm) */
  beam_waist_x?: number
  beam_waist_y?: number
  beam_m2?: number
  beam_waist_z?: number
}

/** Where a source or detector is and points (engine, global frame), and a Gaussian beam's parameters. */
export interface BeamAxis {
  /** 1/e² far-field half-angle M² λ / (π n w0) in the medium described (the surrounding air) */
  divergence_mrad: number
  rayleigh_mm: number
  radius_at_source_mm: number
  wavefront_radius_mm: number | null
}
export interface SourcePose {
  id: string
  kind?: LightSource['kind']
  position?: [number, number, number]
  direction?: [number, number, number]
  axis_angle_deg?: number
  error?: string
  beam?: { wavelength_um: number; /** index of the medium described (the surrounding air) */ medium_index: number; x: BeamAxis; y: BeamAxis }
  /** luminous flux and colour of the source's spectrum (engine photometry/) */
  light?: LightQuantities | null
}

/** Photometric and colorimetric quantities of light (engine photometry/: CIE 1931 2° observer, CIE 018:2019). */
export interface LightQuantities {
  power_w: number
  luminous_flux_lm: number
  scotopic_flux_lm: number
  luminous_efficacy_lm_per_w: number | null
  XYZ_w: [number, number, number]
  chromaticity: { x: number; y: number; u_prime: number; v_prime: number } | null
  /** null when the colour lies more than 0.05 from the Planckian locus */
  cct_k: number | null
  duv: number | null
  /** display colour (sRGB bytes, brightest channel 255) */
  srgb: [number, number, number] | null
  srgb_out_of_gamut?: boolean
  notes: string[]
}

/** A detector's light: Monte Carlo standard errors, illuminance map (lux), X Y Z maps and a true-colour image. */
export interface DetectorPhotometry extends LightQuantities {
  luminous_flux_sigma_lm: number
  chromaticity_sigma: { x: number; y: number } | null
  cct_sigma_k: number | null
  duv_sigma: number | null
  average_illuminance_lux: number | null
  peak_illuminance_lux: number
  /** rows along y, like the irradiance */
  illuminance_lux: number[][]
  xyz_w_mm2: [number[][], number[][], number[][]]
  /** rows along y; [r, g, b] bytes, one exposure for the map */
  colour_image: [number, number, number][][] | null
  colour_image_out_of_gamut: number
}
export interface SpectrumRequest {
  kind: 'blackbody' | 'gaussian' | 'flat'
  temperature_k?: number
  center_um?: number
  fwhm_um?: number
  lambda_min_um?: number | null
  lambda_max_um?: number | null
  samples: number
}

/** General detector: receives light travelling along its local +z axis. */
export interface DetectorSpec {
  id: string
  name: string
  enabled: boolean
  placement: Placement
  shape: 'circle' | 'rectangle'
  size_x: number
  size_y: number
  acceptance_deg: number
  mode: 'absorb' | 'monitor'
  two_sided: boolean
  pixels: number
}

export interface DetectorResult {
  id: string
  name: string
  mode: 'absorb' | 'monitor'
  shape: 'circle' | 'rectangle'
  half_extent_mm: [number, number]
  power_w: number
  /** standard error over the source rays */
  power_sigma_w: number
  /** power after at least one scatter or partial reflection */
  stray_w: number
  stray_sigma_w: number
  paths: NsPathRow[]
  fraction: number
  direct_w: number
  rejected_angle_w: number
  blocked_back_w: number
  hits: number
  by_source_w: Record<string, number>
  by_wavelength_w: Record<string, number>
  irradiance: number[][]
  pixels: [number, number]
  peak_irradiance_w_mm2: number | null
  centroid_mm: [number, number] | null
  rms_radius_mm: number | null
  width_2sigma_mm: [number, number] | null
  angle_hist: { bin_deg: number[]; power_w: number[] }
  photometry?: DetectorPhotometry
}

// ------------------------------------------------------------------ wave optics (backend wave/)
export interface FibreMode {
  name: string
  neff: number
  u: number
  degeneracy: number
  l?: number
  m?: number
  b?: number
  kind?: 'TE' | 'TM' | 'HE' | 'EH'
  nu?: number
}

export type FibreProfileKind = 'step' | 'graded' | 'layers'

/** The /wave/fiber_modes request: the core contrast as dn (index offset), n_core or NA (at the wavelength); graded
 *  profiles n² = n1² (1 − 2Δ (r/a)^α); layers are (outer radius µm, dn) rings from the axis outwards. */
export interface FibreRequest {
  wavelength_um: number
  core_radius_um: number
  dn?: number
  n_core?: number
  na?: number
  n_clad?: number
  clad_material?: string
  vector: boolean
  profile_kind: FibreProfileKind
  alpha: number
  layers: [number, number][]
}

export interface FibreModesResult {
  wavelength_um: number
  core_radius_um: number
  /** layered profiles: the outer radius of the last ring (core_radius_um is the highest ring's) */
  outer_radius_um?: number
  n_core: number
  n_clad: number
  na: number
  v_number: number
  single_mode: boolean
  /** null: LP11 has no cut-off between 0.05 and 50 µm */
  cutoff_wavelength_um: number | null
  lp_modes: FibreMode[]
  mode_count: number
  vector_modes: FibreMode[]
  /** the step-index extras (Gaussian fit, Marcuse) are absent for graded and layered profiles */
  lp01: { neff: number; mfd_petermann2: number; effective_area_um2: number; core_power_fraction: number; mfd_1e2?: number; gaussian_waist?: number; gaussian_overlap?: number; marcuse_mfd?: number }
  profiles: { name: string; l: number; r_um: number[]; field: number[] }[]
  profile_kind: FibreProfileKind
  index_profile: { r_um: number[]; n: number[] }
  notes: string[]
  method: string
}

export interface FibreDispersionRow {
  wavelength_um: number
  neff: number
  group_index: number
  D_ps_nm_km: number
  D_material_ps_nm_km: number
  D_waveguide_ps_nm_km: number
  n_clad: number
}

export interface FibreDispersionResult {
  mode: string
  rows: FibreDispersionRow[]
  zero_dispersion_um: number | null
  cutoff_lp11_um: number | null
  notes: string[]
  method: string
}

/** A region of a fibre cross-section (µm); n or a library material. */
export interface Fibre2dShape {
  kind: 'circle' | 'ellipse' | 'rect'
  x: number
  y: number
  r?: number
  rx?: number
  ry?: number
  w?: number
  h?: number
  angle_deg?: number
  n?: number | null
  material?: string | null
}

/** The /wave/fiber2d request (stored as analysis_settings.fiber2d; wavelength_um null: the system's primary). */
export interface Fibre2dSettings {
  wavelength_um: number | null
  n_background: number | null
  background_material: string | null
  lattice: { pitch_um: number; d_um: number; rings: number; n_hole: number | null; hole_material: string | null; missing_centre: boolean } | null
  shapes: Fibre2dShape[]
  window_um: number | null
  mesh_um: number | null
  pml_um: number
  polarisation: 'x' | 'y'
  count: number
  n_guess: number | null
  refine: boolean
}

export interface Fibre2dMode {
  index: number
  neff: number
  kappa: number
  loss_db_per_m: number
  core_fraction: number
  effective_area_um2: number
  neff_coarse?: number
}

export interface Fibre2dResult {
  wavelength_um: number
  polarisation: 'x' | 'y' | 'all'
  n_guess: number
  modes: Fibre2dMode[]
  best: number | null
  fields: { x_um: number[]; intensity: number[][]; index: number[][] } | null
  mesh: { h_um: number; cells: number; unknowns: number; refined: boolean; symmetry: string[] | null }
  notes: string[]
  method: string
}

export interface Fibre2dSnapshot {
  id: string
  state: 'queued' | 'running' | 'finished' | 'failed' | 'cancelled'
  progress: number
  elapsed_s: number
  eta_s: number | null
  error: string | null
  result: Fibre2dResult | null
}

/** Source of a physical-optics propagation (lengths in mm unless noted). */
/** A rotationally symmetric complex field U(r) handed over from another solver (e.g. the
 * co-polarised field the rotationally symmetric FDTD exports at its transmission monitor). */
export interface ImportedField {
  r_um: number[]
  re: number[]
  im: number[]
  /** the field plane lies this far after the object surface (mm) */
  plane_offset_mm: number
  /** power carried (fraction of the solver's incident power) */
  power: number
  wavelength_um: number
  n_medium: number
  origin?: string
}

export interface PopSource extends Partial<ImportedField> {
  kind: 'pupil' | 'gaussian' | 'fibre' | 'tophat' | 'field'
  waist_x?: number
  waist_y?: number
  waist_z?: number
  radius?: number
  core_radius_um?: number
  n_core?: number | null
  na?: number | null
  n_clad?: number
  decenter?: [number, number]
}

export interface PopMode {
  kind: 'gaussian' | 'fibre'
  waist?: number
  core_radius_um?: number
  n_core?: number | null
  na?: number | null
  n_clad?: number
  decenter?: [number, number]
}

export interface PopResult {
  wavelength_um: number
  source: Record<string, unknown>
  entry: { z: number; method: string; power: number; grid: number; window_mm: number; refined_from: number | null }
  exit: { z: number; power: number; grid: number; window_mm: number; max_sin: number; sphere_radius_mm: number | null; fresnel_number: number | null; propagation: string }
  target: {
    z: number
    offset_from_image: number
    power: number
    centroid_mm: [number, number]
    d4sigma_mm: [number, number]
    peak_irradiance: number
    x: number[]
    y: number[]
    irradiance: number[][]
    phase: number[][]
    profile_x: number[]
    profile_y: number[]
    power_in_radius?: number
    detector_radius?: number
    /** coordinates of the (block-averaged) irradiance map cells */
    map_x?: number[]
    map_y?: number[]
    /** BPM: power beyond the analysis window, and its radius */
    power_outside_window?: number
    window_radius_mm?: number
  }
  coupling?: { mode: PopMode; efficiency: number; efficiency_of_arriving: number; efficiency_db: number | null }
  /** the field along the system on the meridional cut (side_view) */
  side?: {
    z: number[]
    y: number[]
    irradiance: number[][]
    regions: { z0: number; z1: number; method: string; kind: 'wave' | 'geometric' }[]
    surfaces_z: number[]
    source_z: number | null
    entry_z: number
    exit_z: number
    target_z: number
    time_s: number
  }
  geometric_d4sigma_mm: number
  notes: string[]
  time_s: number
  method: string
}

export interface FdtdShape {
  kind: 'rectangle' | 'circle' | 'polygon'
  name?: string
  n?: number
  k?: number
  material?: string
  z0?: number
  z1?: number
  y0?: number
  y1?: number
  zc?: number
  yc?: number
  r?: number
  points?: [number, number][]
}

/** FDTD set-up (lengths in micrometres). 'planar': 2D, invariant along x; 'axisymmetric':
 * rotationally symmetric 3D about z, y is the radius and size_y the domain diameter. */
export interface FdtdSettings {
  geometry?: 'planar' | 'axisymmetric'
  /** FDTD z of the POP object surface (e.g. the fibre facet), for handing the field to POP */
  pop_object_z_um?: number
  wavelength_um: number
  polarization: 's' | 'p'
  size_z_um: number
  size_y_um: number
  n_background: number
  source: 'plane' | 'gaussian' | 'mode' | 'spp'
  waist_um: number
  focus_z_um: number
  focus_y_um: number
  tilt_deg: number
  points_per_wavelength: number
  reference: boolean
  shapes: FdtdShape[]
  /** structure of the reference run (default: none), e.g. an endless fibre for a facet */
  reference_shapes?: FdtdShape[]
  /** source 'mode': fundamental mode of a slab waveguide */
  mode_half_width_um?: number
  mode_n_core?: number
  mode_n_clad?: number
  mode_center_y_um?: number
  /** source 'spp' (p only): y of the interface, the metal below and the dielectric above */
  spp_y_um?: number
  source_z_um?: number
  reflection_z_um?: number
  transmission_z_um?: number
}

export interface FdtdResult {
  geometry?: 'axisymmetric'
  cells: [number, number]
  dx_um: number
  steps: number
  convergence: number
  polarization: string
  /** rotationally symmetric runs: the co-polarised field at the transmission monitor */
  exported_field?: Omit<ImportedField, 'plane_offset_mm'> & { z_um: number; depolarised_fraction: number }
  R?: number
  T?: number
  A?: number
  transmitted_flux?: number
  z_um: number[]
  y_um: number[]
  intensity: number[][]
  field: number[][]
  index: number[][]
  monitors: { source_z: number; reflection_z: number; transmission_z: number }
  /** guided sources: the propagation constant fitted to the field along the guide (beta = (n_eff + i kappa) k0) */
  propagation?: {
    n_eff: number
    kappa: number
    attenuation_per_um: number
    y_um: number
    z_um: [number, number]
    /** surface plasmon: the analytic value for the media read at the source */
    analytic_n_eff?: number
    analytic_kappa?: number
    eps_metal?: [number, number]
    eps_dielectric?: [number, number]
  }
  notes: string[]
  time_s: number
  method: string
}

export interface FdtdSnapshot {
  id: string
  state: 'queued' | 'running' | 'finished' | 'failed' | 'cancelled'
  progress: number
  elapsed_s: number
  eta_s: number | null
  error: string | null
  result: FdtdResult | null
}

// ---- lens elements as parts (backend analysis/elements.py) ----
export interface ElementSurfaceTolerances {
  radius?: [number, number]
  power_fringes?: number
  irregularity_fringes?: number
  rotational_fringes?: number
  zernike_um?: { term: number; max: number }[]
  tilt_arcmin?: number
  decenter_mm?: number
  /** ISO 10110-5 notation, e.g. 3/3(1) */
  iso_3?: string
  /** ISO 10110-6 notation, e.g. 4/1' */
  iso_4?: string
}

export interface ElementTolerances {
  surfaces?: [ElementSurfaceTolerances, ElementSurfaceTolerances]
  center_thickness?: [number, number]
  nd?: number
  vd?: number
  decenter_mm?: number
  test_wavelength_nm?: number
  notes?: string[]
}

export interface LensElement {
  index: number
  name: string
  surfaces: [number, number]
  surface_ids: [string, string]
  labels: [string, string]
  radii_mm: [number | null, number | null]
  conics: [number, number]
  aspheric: [number[], number[]]
  types: [string, string]
  coatings: [string | null, string | null]
  cemented_surfaces: number[]
  material: { name: string; catalog: string; nd: number; vd: number; code: string; density_g_cm3: number | null; relative_cost: number | null; internal_transmittance_10mm_d: number | null }
  mass_g: number | null
  center_thickness_mm: number
  clear_semi_diameters_mm: [number, number]
  mech_semi_diameters_mm: [number | null, number | null]
  profile_ends_mm: [number, number]
  rim_radius_mm: number
  edge_thickness_mm: number
  min_thickness_mm: number
  sag_clear_mm: [number, number]
  sag_rim_mm: [number, number]
  chamfers_mm: [number, number]
  volume_mm3: number
  /** meridional half section (r, z) from the front vertex out along the front, back in along the back */
  outline: [number, number][]
  notes: string[]
  tolerances: ElementTolerances
}

export interface ElementsResult {
  elements: LensElement[]
  skipped: { surfaces: number[]; reason: string }[]
  total_mass_g: number | null
  mass_known_g: number
  relative_cost: number | null
  units: Record<string, string>
  method: string
}

/** Design advisor (backend analysis/advisor.py): what limits the image. */
export type AberrationClass = 'defocus' | 'spherical' | 'coma' | 'astigmatism' | 'trefoil' | 'higher'
export type AdvisorFinding =
  | { kind: 'focus'; defocus_mm: number; rms_um: number; rms_best_um: number; share: number | null }
  | { kind: 'field_curvature'; field: number; rms_waves: number }
  | { kind: 'aberration'; field: number; class: AberrationClass; rms_waves: number; share: number; blur_rms_waves: number }
  | { kind: 'axial_colour'; value_um: number; ratio: number }
  | { kind: 'lateral_colour'; value_um: number; ratio: number; field: number }
  | { kind: 'distortion'; percent: number }
  | { kind: 'diffraction_limited' }
export interface AdvisorField {
  field: number
  field_value: [number, number]
  /** total RMS wavefront error without piston and tilt (waves); null when the wavefront has no reference */
  rms_waves: number | null
  /** RMS (waves) and share of the variance of each class, plus the unfitted residual */
  classes: Record<AberrationClass | 'residual', { rms_waves: number; share: number }> | null
  focus_rms_waves?: number
  focus_signed_waves?: number
  /** RMS wavefront error at the best focus of this field (waves) */
  blur_rms_waves?: number
  dominant?: AberrationClass | null
  diffraction_limited?: boolean
  rms_spot_um: number | null
  note?: string
}
export interface AdvisorDiagnosis {
  wavelength_um: number
  airy_radius_um: number | null
  findings: AdvisorFinding[]
  fields: AdvisorField[]
  focus: { best_defocus_mm: number | null; rms_um: number | null; rms_best_um: number | null; at_best_focus: boolean | null } | null
  colour: { axial_colour_um?: number; depth_of_focus_um?: number | null; lateral_colour_um?: number; field?: number }
  distortion_percent: number | null
  /** the three surfaces with the largest third-order contributions to each aberration */
  attribution: Partial<Record<'spherical' | 'coma' | 'astigmatism' | 'field_curvature' | 'distortion' | 'axial_colour' | 'lateral_colour', { total: number; surfaces: { surface: number; value: number; share: number }[] }>>
  attribution_note: string
  method: string
}
export type AdvisorMoveKind = 'refocus' | 'bend' | 'curvature' | 'stop' | 'gap' | 'thickness' | 'conic' | 'glass'
export interface AdvisorSuggestion {
  kind: AdvisorMoveKind
  /** the surface the move acts on (bend: `surfaces`, the lens or cemented group) */
  surface?: number
  surfaces?: number[]
  from?: string
  to?: string
  /** the change along the move (mm, 1/mm for a bend, conic units) */
  t: number
  merit_before: number
  merit_after: number
  /** relative improvement (merit_before - merit_after) / merit_before */
  gain: number
  /** the new parameter values, by surface id */
  patch: { surface_id: string; key: string; value: number | string | null }[]
  rms_spot_before_um: (number | null)[]
  rms_spot_after_um: (number | null)[] | null
}
export interface AdvisorResult {
  merit: number
  merit_kind: 'project' | 'default'
  moves_tried: number
  evaluations: number
  suggestions: AdvisorSuggestion[]
  status: 'finished' | 'cancelled'
  method: string
}
export interface AdvisorSnapshot {
  job_id: string
  state: 'running' | 'finished' | 'cancelled' | 'failed'
  progress: { done: number; total: number }
  result: AdvisorResult | null
  error: string | null
}

/** The user's photo for the live image (kept in the browser, never in the project): sRGB bytes R, G, B per pixel,
 *  row-major from the top row, base64. */
export interface PhotoData {
  width: number
  height: number
  data: string
}
/** A point of the live image: the field imaged there and its lateral colour, distortion and relative illumination. */
export interface LiveImagePoint {
  radius_mm: number
  field: number
  /** red minus blue real chief-ray radius (µm) and in output pixels */
  lateral_colour_um: number | null
  lateral_colour_px: number | null
  distortion_percent: number
  relative_illumination: number
}
/** Live colour image through the lens (backend analysis/liveimage.py). */
export interface LiveImageResult {
  width_px: number
  height_px: number
  pixel_um: number
  frame_mm: [number, number]
  region_mm: { center: [number, number]; size: [number, number] }
  zoom: number
  framing: 'sensor' | 'image circle'
  field_unit: 'deg' | 'mm'
  channels_um: [number, number, number]
  quality: 'preview' | 'full'
  scene: string
  /** at the frame corner, and at the shown region's outer corner */
  corner: LiveImagePoint | null
  region: LiveImagePoint | null
  energy: { in: number; out: number }[]
  settings: { grid: number; psf_grid: number; psf_grid_used: number | null; geometric_psfs: number; wavefront_step_p99_waves: number; psf_energy_kept: number; supersample: number; kernel_half_px: number; psf_nodes: number; psf_computed: number; mirror_symmetry: boolean; chief_samples: number }
  notes: string[]
  method: string
  /** sRGB bytes R, G, B per pixel, row-major from the top row, base64 */
  images: { ideal: string; lens: string; encoding: string }
}

/** Design space map (backend designspace.py). */
export type DesignTopology = 'singlet' | 'cemented_doublet' | 'air_spaced_doublet' | 'triplet' | 'petzval' | 'double_gauss'
export const DESIGN_TOPOLOGIES: DesignTopology[] = ['singlet', 'cemented_doublet', 'air_spaced_doublet', 'triplet', 'petzval', 'double_gauss']
export const TOPOLOGY_ELEMENTS: Record<DesignTopology, number> = { singlet: 1, cemented_doublet: 2, air_spaced_doublet: 2, triplet: 3, petzval: 5, double_gauss: 6 }
export interface DesignSpaceSpec {
  focal_length: number
  f_number: number
  half_field_deg: number
  wavelengths: number[]
  primary: number
  max_length: number | null
  max_elements: number
  topologies: DesignTopology[]
  candidates: number
  glasses: string[] | null
  mtf_frequency: number
  tolerances: boolean
  seed: number
}
export type DesignMetricKey = 'rms_spot_um' | 'rms_spot_max_um' | 'mtf' | 'length_mm' | 'mass_g' | 'glass_cost' | 'abs_distortion_pct' | 'tolerance_rss_um' | 'elements' | 'parts' | 'price' | 'merit'
export interface DesignMetrics {
  /** null where rays fail (the design then misses the specification) */
  rms_spot_um: number | null
  rms_spot_max_um: number | null
  rms_spot_fields_um: (number | null)[]
  mtf: number | null
  mtf_fields: number[] | null
  length_mm: number
  mass_g: number | null
  glass_cost: number | null
  distortion_pct: number | null
  abs_distortion_pct: number | null
  tolerance_rss_um: number | null
  elements: number
  efl_mm: number | null
  fnum: number | null
  airy_radius_um: number | null
  rays_ok: boolean
  /** stock lens systems: number of parts, their summed price (when every part has one), the merit (match), the
   *  paraxial magnification (finite conjugates) */
  parts?: number
  price?: number | null
  merit?: number
  magnification?: number | null
}
export interface DesignViolation {
  kind: 'efl' | 'length' | 'rays' | 'edge' | 'collision' | 'magnification'
  value: number | null
  limit: number | null
}
export type StockTopology = 'stock_1' | 'stock_2' | 'stock_3'
export interface DesignCandidate {
  index: number
  topology: DesignTopology | StockTopology
  /** stock lens systems: the parts (catalogue:part) */
  parts?: string[]
  glasses: string[]
  variant: number
  title: string
  status: 'finished' | 'failed'
  error?: string
  feasible?: boolean
  violations?: DesignViolation[]
  metrics?: DesignMetrics
  merit?: number
  initial_merit?: number
  evaluations?: number
  optimiser_status?: string
  outline?: SystemOutline
  elapsed_s?: number
}
export interface DesignSpaceSnapshot {
  id: string
  state: 'running' | 'finished' | 'cancelled' | 'failed'
  total: number
  done: number
  failed: number
  elapsed_s: number
  error: string | null
  since: number
  candidates: DesignCandidate[]
  objectives: DesignMetricKey[]
  pareto: number[]
  topologies: (DesignTopology | StockTopology)[]
  /** a stock lens run's phase before its candidates: search, prescreen, optimise */
  phase?: 'search' | 'prescreen' | 'optimise' | null
  phase_done?: number
  phase_total?: number
  notes?: string[]
}

/** Stock lenses (backend stock.py): a purchasable singlet or cemented doublet as a fixed prescription. */
export type StockKind = 'plano_convex' | 'biconvex' | 'best_form' | 'meniscus' | 'plano_concave' | 'biconcave' | 'achromat' | 'other'
export interface StockLens {
  part: string
  vendor?: string
  catalog?: string
  kind?: StockKind
  /** front to back, mm; null = flat */
  radii: (number | null)[]
  thicknesses: number[]
  materials: string[]
  diameter: number
  clear_diameter?: number | null
  focal_length?: number | null
  price?: number | null
  currency?: string
  source?: string
}
/** A stock lens with its paraxial data at the d line (engine). */
export interface StockLensInfo extends StockLens {
  clear: number
  key: string
  paraxial: { efl: number | null; bfd: number | null; ffd: number | null; rear_principal: number | null; front_principal: number | null; length: number; error?: string }
}
/** An imported stock lens catalogue, kept in the browser (IndexedDB) like glass catalogues. */
export interface StockCatalog {
  id: string
  name: string
  vendor: string
  imported_at: string
  source: 'zmx' | 'csv'
  lenses: StockLensInfo[]
  /** glasses the lenses use that come from the user's glass catalogues */
  custom_materials: MaterialRecord[]
  diagnostics: { file?: string; message: string }[]
}
export interface StockSpec {
  conjugate: 'infinite' | 'finite'
  focal_length: number
  f_number: number
  half_field_deg: number
  object_distance: number
  magnification: number
  object_na: number
  object_height: number
  wavelengths: number[]
  primary: number
  max_length: number | null
  lens_counts: number[]
  materials: string[] | null
  generic: boolean
  min_gap: number
  tolerance: number
  candidates: number
  prescreen: number
  mtf_frequency: number
  tolerances: boolean
  seed: number
}
export interface StockMatchSpec {
  materials: string[] | null
  generic: boolean
  per_element: number
  min_gap: number
  candidates: number
  prescreen: number
  mtf_frequency: number
  tolerances: boolean
  seed: number
}
export interface DesignCandidateProject {
  index: number
  title: string
  metrics: DesignMetrics
  project: { metadata: { name: string; description: string }; system: OpticalSystem; optimization: OptimizationSpec; custom_materials: MaterialRecord[] }
}

// ------------------------------------------------------------------ spectrometers (backend analysis/spectrometer.py)
export interface SpectrometerResult {
  field: number
  wavelength_um: number[]
  centroid_mm: ([number, number] | null)[]
  chief_mm: ([number, number] | null)[]
  /** unit vector of the dispersion on the image surface */
  direction: [number, number]
  position_mm: (number | null)[]
  dispersion_mm_per_nm: (number | null)[]
  reciprocal_nm_per_mm: (number | null)[]
  rms_along_um: (number | null)[]
  rms_across_um: (number | null)[]
  /** geometric resolution (Gaussian-equivalent FWHM); null where the spot is below 1 nm */
  resolution_nm: (number | null)[]
  resolving_power: (number | null)[]
  rays: number
  rays_ok: number[]
  span_mm: number
  grating?: { surface: number; label: string; order: number; lines_per_mm: number; illuminated_mm: (number | null)[]; resolving_power: (number | null)[]; resolution_nm: (number | null)[] }
  notes: string[]
  method: string
}

// ------------------------------------------------------------------ interferometry (backend analysis/interferometry.py)
export interface InterferogramResult {
  field: number
  wavelength: number
  wavelength_um: number
  grid: number
  passes: 1 | 2
  tilt_x: number
  tilt_y: number
  visibility: number
  x: number[]
  y: number[]
  /** (1 + V cos phi) / 2 on the normalised pupil; null outside it */
  intensity: (number | null)[][]
  wavefront_waves: (number | null)[][]
  pv_waves: number
  rms_waves: number
  /** passes x P-V: the aberration fringes (without tilt) */
  fringes_pv: number
  /** largest phase step between neighbouring pixels (rad); above 0.9 pi the fringes are undersampled */
  max_step_rad: number
  phase_steps?: number
  recovered_waves?: (number | null)[][]
  recovery_rms_error_waves?: number
  recovered_fraction?: number
  notes: string[]
  method: string
}

// ------------------------------------------------------------------ gratings (backend wave/rcwa.py, wave/rcwaapi.py)
export interface RcwaOrder {
  m: number
  /** order along y of a crossed grating */
  q?: number
  R: number | null
  T: number | null
  /** polar angle of the propagating order (degrees) */
  angle_r_deg?: number
  angle_t_deg?: number
  /** azimuth of a crossed grating's order (degrees from x) */
  azimuth_r_deg?: number
  azimuth_t_deg?: number
}

export interface RcwaZeroth {
  abs2: number
  /** phase delay of the zeroth order, degrees (k · OPL positive) */
  delay_deg: number
  /** power fraction in this polarisation */
  power?: number
  /** power fraction converted into the orthogonal polarisation (crossed gratings) */
  cross_power?: number
}

export interface RcwaShapeDraw {
  kind: 'rectangle' | 'ellipse'
  cx: number
  cy: number
  a: number
  b: number
  angle: number
  n: number
  k: number
}

export interface RcwaResult {
  wavelength_um: number
  theta_deg: number
  phi_deg: number
  polarisation: 'TE' | 'TM' | 'unpolarised'
  harmonics: number
  harmonics_y?: number
  orders: RcwaOrder[]
  total_R: number
  total_T: number
  absorbed: number
  zeroth: Record<string, { t: RcwaZeroth | null; r: RcwaZeroth | null }>
  /** TE delay minus TM delay of the zeroth transmitted order (unpolarised runs) */
  retardance_deg?: number
  convergence?: { harmonics_low: number; harmonics_y_low?: number; max_change: number }
  /** slices: lines (segments, 1D) or shapes in the cell (crossed gratings, with period_y_um) */
  structure: {
    period_um: number
    period_y_um?: number
    slices: { z0: number; z1: number; groove: [number, number]; segments?: [number, number, number, number][]; shapes?: RcwaShapeDraw[]; layer: number }[]
  }
  /** orders: labels of the curves ("-1", "0" … or "(m,q)" for crossed gratings) */
  sweep?: { kind: 'wavelength' | 'angle'; x: number[]; orders: string[]; curves: Record<string, (number | null)[]> }
  notes: string[]
  method: string
}
