import { projectChecksum } from './canonical'
import { CONFIG_OF_VARIABLE, configRow } from './configs'
import type { CoatingDefinition, DetectorSpec, LightSource, MaterialRecord, OpticalSystem, OptimizationSpec, Project, Surface, ToleranceSpec, VariableParam } from './types'

export const PROJECT_FORMAT = 'opticore-project'
export const PROJECT_SCHEMA_VERSION = 1
export const FILE_EXTENSION = '.opticore'

export function newId(): string {
  const a = new Uint8Array(6)
  crypto.getRandomValues(a)
  return Array.from(a, (b) => b.toString(16).padStart(2, '0')).join('')
}

export function nowIso(): string {
  return new Date().toISOString()
}

export function defaultSurface(partial: Partial<Surface> = {}): Surface {
  return {
    id: newId(),
    type: 'standard',
    label: '',
    comment: '',
    radius: null,
    thickness: 0,
    material: 'AIR',
    semi_diameter: 10,
    semi_diameter_mode: 'auto',
    conic: 0,
    radius_x: null,
    conic_x: 0,
    aspheric: [],
    is_stop: false,
    coating: '',
    zernike_coefficients: [],
    zernike_norm_radius: 10,
    q_coefficients: [],
    q_norm_radius: 10,
    xy_coefficients: [],
    xy_norm_radius: 10,
    grating_frequency: 0,
    focal_length: 100,
    ideal_object_distance: null,
    phase_coefficients: [],
    phase_norm_radius: 1,
    diffraction_order: 1,
    thickness_solve: null,
    curvature_solve: null,
    decenter_x: 0,
    decenter_y: 0,
    tilt_x: 0,
    tilt_y: 0,
    tilt_z: 0,
    cb_order: 0,
    ...partial,
  }
}

export function defaultTolerancing(): ToleranceSpec {
  return { tolerances: [], compensators: [], criterion: 'rms_spot', rings: 3, monte_carlo_trials: 50, distribution: 'normal', seed: 1, compensator_evaluations: 40 }
}

export function defaultOptimization(): OptimizationSpec {
  return { variables: [], operands: [], algorithm: 'local', max_evaluations: 2000, multistart_runs: 6, seed: 1, constraints: 'exact' }
}

/** A blank project: object at infinity, one N-BK7 biconvex lens, image. */
export function blankProject(name = 'Untitled project'): Project {
  const system: OpticalSystem = {
    name,
    units: 'mm',
    surfaces: [
      defaultSurface({ label: 'Object', thickness: null }),
      defaultSurface({ label: 'Front', radius: 100, thickness: 5, material: 'N-BK7', is_stop: true }),
      defaultSurface({ label: 'Back', radius: -100, thickness: 95 }),
      defaultSurface({ label: 'Image', thickness: 0 }),
    ],
    custom_coatings: [],
    wavelengths: [
      { value: 0.4861327, weight: 1 },
      { value: 0.5875618, weight: 1 },
      { value: 0.6562725, weight: 1 },
    ],
    primary_wavelength: 1,
    field_type: 'angle',
    fields: [
      { x: 0, y: 0, weight: 1 },
      { x: 0, y: 3, weight: 1 },
    ],
    aperture: { type: 'epd', value: 10 },
    ray_aiming: 'paraxial',
    temperature_c: 20,
  }
  const t = nowIso()
  return {
    format: PROJECT_FORMAT,
    schema_version: PROJECT_SCHEMA_VERSION,
    id: newId(),
    metadata: { name, description: '', author: '', created: t, modified: t, tags: [] },
    system,
    custom_materials: [],
    cad_assets: [],
    sources: [],
    detectors: [],
    optimization: defaultOptimization(),
    tolerancing: defaultTolerancing(),
    analysis_settings: { spot: { pattern: 'hexapolar', density: 6, reference: 'centroid' }, fan: { samples: 41 }, field: { samples: 21 }, saved: [] },
    ui: {},
    revisions: [],
    saved_optimizations: [],
    provenance: { created_with: 'OptiCore Studio 0.1.0', imports: [], warnings: [] },
    checksum: null,
  }
}

/** Fill optional members so older/partial files behave like current ones. */
export function normalizeProject(p: Project): Project {
  const b = blankProject()
  // the non-sequential importance target named a surface by index in older projects: by id now
  const ns = p.analysis_settings?.nonseq as { imp_target?: string } | undefined
  if (ns?.imp_target?.startsWith('surf:')) {
    const sf = p.system.surfaces[Number(ns.imp_target.slice(5))]
    p = { ...p, analysis_settings: { ...p.analysis_settings, nonseq: { ...ns, imp_target: sf ? `sid:${sf.id}` : 'none' } } }
  }
  return {
    ...b,
    ...p,
    metadata: { ...b.metadata, ...p.metadata },
    optimization: { ...defaultOptimization(), ...p.optimization },
    tolerancing: { ...defaultTolerancing(), ...p.tolerancing },
    analysis_settings: { ...b.analysis_settings, ...p.analysis_settings },
    custom_materials: p.custom_materials ?? [],
    cad_assets: p.cad_assets ?? [],
    sources: p.sources ?? [],
    detectors: p.detectors ?? [],
    revisions: p.revisions ?? [],
    saved_optimizations: p.saved_optimizations ?? [],
    provenance: { ...b.provenance, ...p.provenance },
    ui: p.ui ?? {},
    system: { ...p.system, surfaces: p.system.surfaces.map((s) => defaultSurface(s)), custom_coatings: p.system.custom_coatings ?? [] },
  }
}

export class ProjectFileError extends Error {}

export interface ParsedProject {
  project: Project
  checksumOk: boolean | null // null = no checksum present
  notes: string[]
}

/** Parse and check a project file's text (format, schema version, checksum). */
export async function parseProjectFile(text: string): Promise<ParsedProject> {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch {
    throw new ProjectFileError('The file is not valid JSON')
  }
  if (!raw || typeof raw !== 'object') throw new ProjectFileError('The file does not contain a project object')
  const obj = raw as Record<string, unknown>
  if (obj.format !== PROJECT_FORMAT) throw new ProjectFileError("Not an OptiCore project (missing format 'opticore-project')")
  const v = obj.schema_version
  if (typeof v !== 'number') throw new ProjectFileError('Missing schema_version')
  if (v > PROJECT_SCHEMA_VERSION)
    throw new ProjectFileError(`Project schema version ${v} is newer than supported (${PROJECT_SCHEMA_VERSION}). Update OptiCore Studio.`)
  const notes: string[] = []
  let checksumOk: boolean | null = null
  const cs = obj.checksum as { value?: string } | null | undefined
  if (cs && typeof cs.value === 'string') {
    checksumOk = (await projectChecksum(obj)) === cs.value
    if (!checksumOk) notes.push('Checksum mismatch: the file was modified outside OptiCore Studio or is corrupted.')
  }
  return { project: normalizeProject(obj as unknown as Project), checksumOk, notes }
}

/** Serialise a project with an up-to-date checksum (pretty printed). */
export async function serializeProject(p: Project): Promise<string> {
  const copy: Record<string, unknown> = JSON.parse(JSON.stringify({ ...p, checksum: null }))
  delete copy.checksum
  const value = await projectChecksum(copy)
  copy.checksum = { algorithm: 'sha256', value }
  return JSON.stringify(copy, null, 2)
}

export function cloneSystem(s: OpticalSystem): OpticalSystem {
  return JSON.parse(JSON.stringify(s))
}

export function surfaceIndexById(s: OpticalSystem, id: string): number {
  return s.surfaces.findIndex((x) => x.id === id)
}

export function variableValue(s: OpticalSystem, surfaceId: string, p: VariableParam, configuration?: number | null): number {
  if (configuration !== undefined && configuration !== null) {
    const cp = CONFIG_OF_VARIABLE[p]
    const r = cp ? configRow(s, surfaceId, cp) : -1
    if (r < 0 || !s.multi_config) return NaN
    const v = s.multi_config.operands[r].values[configuration]
    if (p === 'curvature') return v === null ? 0 : 1 / Number(v)
    return Number(v)
  }
  const surf = s.surfaces.find((x) => x.id === surfaceId)
  if (!surf) return NaN
  if (p === 'curvature') return surf.radius === null ? 0 : 1 / surf.radius
  if (p === 'curvature_x') return surf.radius_x === null ? 0 : 1 / surf.radius_x
  if (p === 'ideal_power') return surf.focal_length === null ? 0 : 1 / surf.focal_length
  if (p === 'thickness') return surf.thickness ?? NaN
  if (p === 'conic') return surf.conic
  if (p.startsWith('asph_')) {
    const k = (parseInt(p.slice(5), 10) - 4) / 2
    return surf.aspheric[k] ?? 0
  }
  if (p.startsWith('phase_')) return surf.phase_coefficients[parseInt(p.slice(6), 10) - 1] ?? 0
  if (p.startsWith('zern_')) return surf.zernike_coefficients[parseInt(p.slice(5), 10) - 1] ?? 0
  if (p.startsWith('q_')) return surf.q_coefficients?.[parseInt(p.slice(2), 10) - 1] ?? 0
  if (p.startsWith('xy_')) return surf.xy_coefficients?.[parseInt(p.slice(3), 10) - 1] ?? 0
  if (p === 'mount_cte') return surf.mount_cte ?? s.housing_cte ?? 23.6
  if (p === 'coating_scale') return 1
  if (p.startsWith('coat_layer_')) return coatingOf(s, surf.coating)?.layers[parseInt(p.slice(11), 10) - 1]?.thickness_nm ?? NaN
  return surf[p as 'tilt_x']
}

/** Apply optimiser variable values to a copy of a system (mirror of backend apply_values). */
export function applyVariableValues(s: OpticalSystem, vars: { surface_id: string; parameter: VariableParam; configuration?: number | null }[], values: number[]): OpticalSystem {
  const out = cloneSystem(s)
  vars.forEach((v, i) => {
    if (v.parameter === 'material') return // discrete: see applyMaterials
    const val = values[i]
    if (v.configuration !== undefined && v.configuration !== null) {
      const cp = CONFIG_OF_VARIABLE[v.parameter]
      const r = cp ? configRow(out, v.surface_id, cp) : -1
      if (r >= 0 && out.multi_config) out.multi_config.operands[r].values[v.configuration] = v.parameter === 'curvature' ? (Math.abs(val) < 1e-15 ? null : 1 / val) : val
      return
    }
    const surf = out.surfaces.find((x) => x.id === v.surface_id)
    if (!surf) return
    if (v.parameter === 'coating_scale' || v.parameter.startsWith('coat_layer_')) {
      const cd = coatingOf(out, surf.coating)
      if (!cd) return
      if (v.parameter === 'coating_scale') {
        const base = coatingOf(s, surf.coating)!
        cd.layers.forEach((L, k) => (L.thickness_nm = Math.max(0, base.layers[k].thickness_nm * val)))
      } else {
        const L = cd.layers[parseInt(v.parameter.slice(11), 10) - 1]
        if (L) L.thickness_nm = Math.max(0, val)
      }
      return
    }
    if (v.parameter === 'curvature') surf.radius = Math.abs(val) < 1e-15 ? null : 1 / val
    else if (v.parameter === 'curvature_x') surf.radius_x = Math.abs(val) < 1e-15 ? null : 1 / val
    else if (v.parameter === 'ideal_power') surf.focal_length = Math.abs(val) < 1e-15 ? null : 1 / val
    else if (v.parameter.startsWith('asph_')) {
      const k = (parseInt(v.parameter.slice(5), 10) - 4) / 2
      while (surf.aspheric.length <= k) surf.aspheric.push(0)
      surf.aspheric[k] = val
    } else if (v.parameter.startsWith('phase_')) {
      const k = parseInt(v.parameter.slice(6), 10) - 1
      while (surf.phase_coefficients.length <= k) surf.phase_coefficients.push(0)
      surf.phase_coefficients[k] = val
    } else if (v.parameter.startsWith('zern_')) {
      const k = parseInt(v.parameter.slice(5), 10) - 1
      while (surf.zernike_coefficients.length <= k) surf.zernike_coefficients.push(0)
      surf.zernike_coefficients[k] = val
    } else if (v.parameter.startsWith('q_') || v.parameter.startsWith('xy_')) {
      const q = v.parameter.startsWith('q_')
      const k = parseInt(v.parameter.slice(q ? 2 : 3), 10) - 1
      const a = [...((q ? surf.q_coefficients : surf.xy_coefficients) ?? [])]
      while (a.length <= k) a.push(0)
      a[k] = val
      if (q) surf.q_coefficients = a
      else surf.xy_coefficients = a
    } else (surf as unknown as Record<string, number>)[v.parameter] = val
  })
  return out
}

/** Write glass-substitution results (surface id -> material) into a copy of a system. */
export function applyMaterials(s: OpticalSystem, mats: Record<string, string> | { surface_id: string; final: string }[] | null | undefined): OpticalSystem {
  const out = cloneSystem(s)
  if (!mats) return out
  const entries: [string, string][] = Array.isArray(mats) ? mats.map((m) => [m.surface_id, m.final]) : Object.entries(mats)
  for (const [id, m] of entries) {
    const surf = out.surfaces.find((x) => x.id === id)
    if (surf) surf.material = m
  }
  return out
}

export function usedMaterials(s: OpticalSystem): string[] {
  const set = new Set<string>()
  for (const x of s.surfaces) if (!['AIR', 'MIRROR', 'VACUUM', ''].includes(x.material)) set.add(x.material)
  return [...set]
}

export function customMaterialByName(list: MaterialRecord[], name: string): MaterialRecord | undefined {
  return list.find((m) => m.name.toUpperCase() === name.toUpperCase())
}

/** Project coating used by a surface (case-insensitive), if any. */
export function coatingOf(s: OpticalSystem, name: string): CoatingDefinition | undefined {
  const k = (name ?? '').trim().toUpperCase()
  return k ? (s.custom_coatings ?? []).find((c) => c.name.trim().toUpperCase() === k) : undefined
}

/** Name of the physical medium light travels in before surface i (mirrors and coordinate breaks keep the medium). */
export function mediumBefore(system: OpticalSystem, i: number): string {
  let name = system.surfaces[0]?.material ?? 'AIR'
  for (let k = 1; k < i; k++) {
    const s = system.surfaces[k]
    if (s.material.toUpperCase() !== 'MIRROR' && s.type !== 'coordinate_break') name = s.material
  }
  return name.toUpperCase() || 'AIR'
}

/** A new light source with the engine's defaults (point, Lambertian, 1 W). */
export function defaultSource(partial: Partial<LightSource> = {}): LightSource {
  return {
    id: newId(),
    name: 'Source',
    enabled: true,
    kind: 'emitter',
    field: 0,
    overfill: 1.2,
    power_w: 1,
    rays: 2000,
    placement: { position: [0, 0, 0], rotation_deg: [0, 0, 0] },
    shape: 'point',
    size_x: 1,
    size_y: 1,
    size_z: 1,
    spatial: 'uniform',
    gaussian_wx: 0.5,
    gaussian_wy: 0.5,
    angular: 'lambertian',
    half_angle_deg: 90,
    cos_power: 1,
    gaussian_x_deg: 5,
    gaussian_y_deg: 5,
    table: [],
    wavelengths: [],
    beam_waist_x: 0.5,
    beam_waist_y: 0.5,
    beam_m2: 1,
    beam_waist_z: 0,
    ...partial,
  }
}

/** The project's sources and detectors for engine requests that may evaluate detector operands
 * (merit function, optimisation, tolerancing); omitted when the project has none. */
export function nsBody(p: Project): { sources?: LightSource[]; detectors?: DetectorSpec[] } {
  const sources = p.sources ?? []
  const detectors = p.detectors ?? []
  return sources.length || detectors.length ? { sources, detectors } : {}
}

/** A new detector with the engine's defaults (circle r = 1 mm, absorbing, one-sided). */
export function defaultDetector(partial: Partial<DetectorSpec> = {}): DetectorSpec {
  return {
    id: newId(),
    name: 'Detector',
    enabled: true,
    placement: { position: [0, 0, 0], rotation_deg: [0, 0, 0] },
    shape: 'circle',
    size_x: 1,
    size_y: 1,
    acceptance_deg: 90,
    mode: 'absorb',
    two_sided: false,
    pixels: 64,
    ...partial,
  }
}
