// Optimisation wizard: turns a few plain choices into variables and merit-function operands.
// No optics is computed here; the engine evaluates the spec (variables with bounds, operands with targets).
import { defaultBounds } from '../store/projectStore'
import type { OpticalSystem, Operand, OptimizationSpec, Surface, Variable } from './types'

export type WizardObjective = 'rms_spot' | 'rms_wavefront' | 'spot_size' | 'beam_size'

export interface WizardChoices {
  /** what may change */
  radii: boolean
  /** plane surfaces stay plane (their curvature is not a variable) */
  keepPlane: boolean
  airGaps: boolean
  glassThickness: boolean
  imageDistance: boolean
  /** the goal: the sharpest image (RMS spot or RMS wavefront), a spot of a given RMS radius, or a beam of a given
   * diameter on a detector (light sources and detectors of the project) */
  objective: WizardObjective
  reference: 'centroid' | 'chief'
  /** spot_size: RMS radius (µm) */
  spotTarget: number
  /** beam_size: D4σ diameter (µm) on this detector */
  beamTarget: number
  detectorId: string | null
  /** constraints (mm); null = none */
  minCentre: number | null
  maxCentre: number | null
  minEdge: number | null
  /** air gaps between lenses: at the edge (a merit target) and at the centre (a hard bound of the gap variable) */
  minAirEdge: number | null
  eflTarget: number | null
  /** |distortion| at the largest field at most this (%); null = free */
  maxDistortion: number | null
  /** total track at most this (mm); null = free */
  maxTrack: number | null
  /** |lateral colour| at the largest field at most this (µm); null = free */
  maxLateralUm: number | null
  /** relative illumination at the largest field at least this (%); null = free */
  minRiPct: number | null
  /** chief-ray angle on the image at the largest field at most this (degrees); null = free */
  maxCraDeg: number | null
  /** replace the current variables and operands, or add to them */
  mode: 'replace' | 'add'
}

export const DEFAULT_WIZARD: WizardChoices = {
  radii: true,
  keepPlane: true,
  airGaps: true,
  glassThickness: false,
  imageDistance: true,
  objective: 'rms_spot',
  reference: 'centroid',
  spotTarget: 20,
  beamTarget: 100,
  detectorId: null,
  minCentre: 1,
  maxCentre: null,
  minEdge: 1,
  minAirEdge: 0.1,
  eflTarget: null,
  maxDistortion: null,
  maxTrack: null,
  maxLateralUm: null,
  minRiPct: null,
  maxCraDeg: null,
  mode: 'replace',
}

const glass = (m: string) => !['AIR', 'VACUUM', 'MIRROR'].includes(m.toUpperCase())
const plainPlane = (s: Surface) => s.type === 'standard' && s.radius === null && !s.curvature_solve

/** Surfaces the wizard can use: curvatures, glass thicknesses, air gaps and the image distance (by surface id).
 * Coordinate breaks, ideal lenses and values driven by a solve are left alone. */
export function wizardTargets(s: OpticalSystem): { radii: string[]; plane: string[]; glass: string[]; air: string[]; image: string | null } {
  const n = s.surfaces.length
  const out = { radii: [] as string[], plane: [] as string[], glass: [] as string[], air: [] as string[], image: null as string | null }
  for (let i = 1; i <= n - 2; i++) {
    const sf = s.surfaces[i]
    if (sf.type === 'coordinate_break' || sf.type === 'ideal') continue
    if (!sf.curvature_solve) (sf.radius === null ? out.plane : out.radii).push(sf.id)
    if (sf.thickness_solve || sf.thickness === null) continue
    if (i === n - 2) out.image = sf.id
    else if (glass(sf.material)) out.glass.push(sf.id)
    else out.air.push(sf.id)
  }
  return out
}

/** Glass elements (by front-surface id) whose edge can change: not plane-parallel plates (a filter or window edge
 * is its centre thickness, so an edge target on it is either redundant or a constant no variable can meet). */
export function edgeElements(s: OpticalSystem): string[] {
  const t = wizardTargets(s)
  return t.glass.filter((id) => {
    const i = s.surfaces.findIndex((x) => x.id === id)
    return !(plainPlane(s.surfaces[i]) && plainPlane(s.surfaces[i + 1]))
  })
}

/** Air gaps (by surface id) between two lens surfaces: glass before and after. A stop or another plain surface on
 * either side is not a lens-to-lens gap (a stop may sit at a lens vertex). */
export function lensGaps(s: OpticalSystem): string[] {
  return wizardTargets(s).air.filter((id) => {
    const i = s.surfaces.findIndex((x) => x.id === id)
    return i > 1 && glass(s.surfaces[i - 1].material) && i + 1 < s.surfaces.length - 1 && glass(s.surfaces[i + 1].material)
  })
}

const round2 = (x: number) => (x > 0 ? +x.toPrecision(2) : x)
/** Round down to two significant digits (a limit just inside the current value). */
const floor2 = (x: number) => {
  if (!(x > 0)) return x
  const e = Math.floor(Math.log10(x)) - 1
  return Math.floor(x / 10 ** e) * 10 ** e
}

/** What the engine knows about the design now (from its evaluation): semi-diameters and edge thicknesses per surface. */
export interface WizardDesignState {
  semiDiameters: number[]
  edgeThickness: (number | null)[]
}

/** Default constraints scaled to the lenses and never stricter than the design is now. A target the starting design
 * already misses makes a least-squares optimiser trade image quality for it (its error, in mm, outweighs a spot of
 * a few µm), so the defaults hold what the design has rather than asking for something new:
 *   glass edge ≥ min(10 % of the smallest lens diameter, at most 1 mm; 90 % of the thinnest lens edge now)
 *   glass centre ≥ min(15 % of that diameter, at most 1 mm; the thinnest centre now)
 *   air gaps between lenses ≥ min(2 % of that diameter, at most 0.1 mm; 90 % of the narrowest lens-to-lens gap now)
 * Without an evaluation the fixed defaults of DEFAULT_WIZARD stay. */
export function scaledConstraints(s: OpticalSystem, st: WizardDesignState | null): Pick<WizardChoices, 'minEdge' | 'minCentre' | 'minAirEdge'> {
  const els = edgeElements(s)
  if (!st || !els.length) return { minEdge: DEFAULT_WIZARD.minEdge, minCentre: DEFAULT_WIZARD.minCentre, minAirEdge: DEFAULT_WIZARD.minAirEdge }
  const idx = (id: string) => s.surfaces.findIndex((x) => x.id === id)
  const diam = els.map((id) => 2 * Math.max(st.semiDiameters[idx(id)] ?? 0, st.semiDiameters[idx(id) + 1] ?? 0)).filter((d) => d > 0)
  if (!diam.length) return { minEdge: DEFAULT_WIZARD.minEdge, minCentre: DEFAULT_WIZARD.minCentre, minAirEdge: DEFAULT_WIZARD.minAirEdge }
  const D = Math.min(...diam)
  const edges = els.map((id) => st.edgeThickness[idx(id)]).filter((e): e is number => e !== null && e !== undefined && Number.isFinite(e))
  const centres = els.map((id) => s.surfaces[idx(id)].thickness).filter((t): t is number => t !== null && t > 0)
  const gaps = lensGaps(s).flatMap((id) => [st.edgeThickness[idx(id)], s.surfaces[idx(id)].thickness]).filter((e): e is number => e !== null && e !== undefined && Number.isFinite(e))
  const cap = (scaled: number, now: number[], k: number) => (now.length ? Math.min(scaled, floor2(k * Math.min(...now))) : scaled)
  return {
    minEdge: Math.max(0, cap(round2(Math.min(1, 0.1 * D)), edges, 0.9)),
    minCentre: Math.max(0, cap(round2(Math.min(1, 0.15 * D)), centres, 1)),
    minAirEdge: Math.max(0, cap(round2(Math.min(0.1, 0.02 * D)), gaps, 0.9)),
  }
}

const operand = (type: Operand['type'], target: number, extra: Partial<Operand> = {}): Operand => ({ type, target, weight: 1, field: null, wavelength: null, surface_id: null, rings: 4, reference: 'centroid', enabled: true, ...extra })

/** The variables and operands for the choices. Field and wavelength weights are the system's own. */
export function buildWizardSpec(s: OpticalSystem, current: OptimizationSpec, c: WizardChoices): OptimizationSpec {
  const t = wizardTargets(s)
  const gaps = lensGaps(s)
  const vars: Variable[] = []
  const add = (id: string, p: Variable['parameter']) => vars.push(defaultBounds(s, id, p))
  if (c.radii) for (const id of [...t.radii, ...(c.keepPlane ? [] : t.plane)]) add(id, 'curvature')
  if (c.glassThickness) for (const id of t.glass) add(id, 'thickness')
  if (c.airGaps) for (const id of t.air) add(id, 'thickness')
  if (c.imageDistance && t.image) add(t.image, 'thickness')
  for (const v of vars) {
    if (v.parameter !== 'thickness') continue
    if (t.glass.includes(v.surface_id)) {
      // centre-thickness bounds become the variables' own bounds (exact), not penalties
      if (c.minCentre !== null) v.min = Math.max(v.min ?? -Infinity, c.minCentre)
      if (c.maxCentre !== null) v.max = Math.min(v.max ?? Infinity, c.maxCentre)
    } else if (gaps.includes(v.surface_id) && c.minAirEdge !== null) {
      // a lens-to-lens air gap keeps the same minimum at its centre (never above where it starts)
      const t0 = s.surfaces.find((x) => x.id === v.surface_id)?.thickness ?? 0
      v.min = Math.max(v.min ?? -Infinity, Math.min(c.minAirEdge, t0))
    }
  }
  const ops: Operand[] = []
  if (c.objective === 'rms_spot' || c.objective === 'rms_wavefront') ops.push(operand(c.objective, 0, { reference: c.reference, rings: 4 }))
  if (c.objective === 'spot_size') ops.push(operand('rms_spot', c.spotTarget / 1000, { reference: c.reference, rings: 4 }))
  if (c.objective === 'beam_size' && c.detectorId) {
    ops.push(operand('detector_size', c.beamTarget / 1000, { detector_id: c.detectorId, direction: 'average' }))
    ops.push(operand('detector_power', 1, { detector_id: c.detectorId, weight: 0.1 }))
  }
  if (c.eflTarget !== null) ops.push(operand('efl', c.eflTarget))
  if (c.maxDistortion !== null) ops.push(operand('max_distortion', c.maxDistortion))
  if (c.maxTrack !== null) ops.push(operand('max_total_track', c.maxTrack))
  if (c.maxLateralUm !== null) ops.push(operand('max_lateral_color', c.maxLateralUm))
  if (c.minRiPct !== null) ops.push(operand('min_relative_illumination', c.minRiPct / 100))
  if (c.maxCraDeg !== null) ops.push(operand('max_cra', c.maxCraDeg))
  if (c.minEdge !== null) for (const id of edgeElements(s)) ops.push(operand('min_edge_thickness', c.minEdge, { surface_id: id }))
  if (c.minAirEdge !== null && c.airGaps) for (const id of t.air) ops.push(operand('min_edge_thickness', c.minAirEdge, { surface_id: id }))
  if (c.mode === 'replace') return { ...current, variables: vars, operands: ops }
  // add: keep what exists, skip duplicates of the same variable or operand
  const key = (v: Variable) => `${v.surface_id}:${v.parameter}:${v.configuration ?? ''}`
  const okey = (o: Operand) => `${o.type}:${o.surface_id ?? ''}:${o.field ?? ''}:${o.wavelength ?? ''}:${o.detector_id ?? ''}`
  const haveV = new Set(current.variables.map(key))
  const haveO = new Set(current.operands.map(okey))
  return { ...current, variables: [...current.variables, ...vars.filter((v) => !haveV.has(key(v)))], operands: [...current.operands, ...ops.filter((o) => !haveO.has(okey(o)))] }
}

/** Rounded up to one decimal: a distortion limit (%) just above the current value. */
export function distortionLimit(d: number): number {
  return Math.max(0.1, Math.ceil(Math.abs(d) * 10 - 1e-9) / 10)
}

/** Rounded up to 0.1 µm (at least 0.1): a lateral-colour limit just above the current |value|. */
export function lateralLimit(um: number): number {
  return Math.max(0.1, Math.ceil(Math.abs(um) * 10 - 1e-9) / 10)
}

/** Rounded down to a whole per cent: a relative-illumination floor (%) just below the current value (a fraction). */
export function riLimit(fraction: number): number {
  return Math.floor(fraction * 100 + 1e-9)
}

/** Rounded up to 0.1°: a chief-ray-angle limit just above the current value. */
export function craLimit(deg: number): number {
  return Math.ceil(deg * 10 - 1e-9) / 10
}

/** Rounded up to two decimals: a total-track limit (mm) just above the current value. */
export function trackLimit(t: number): number {
  return Math.ceil(t * 100 - 1e-9) / 100
}
