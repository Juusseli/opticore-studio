// Tolerance types, their engine units and default limits, and which surfaces can carry them (the engine,
// backend tolerance.validate_tolerances, applies the same rules).
import type { Surface, ToleranceSpec, ToleranceType } from './types'

export const TYPES: ToleranceType[] = [
  'radius',
  'thickness',
  'conic',
  'power',
  'irregularity',
  'irregularity_rotational',
  'zernike_form',
  'index',
  'abbe',
  'surface_decenter_x',
  'surface_decenter_y',
  'surface_tilt_x',
  'surface_tilt_y',
  'element_decenter_x',
  'element_decenter_y',
  'element_tilt_x',
  'element_tilt_y',
]

/** Engine units of each tolerance type (backend tolerance.TOLERANCE_UNITS). */
export const UNIT: Record<ToleranceType, string> = {
  radius: 'mm',
  thickness: 'mm',
  conic: '',
  index: '',
  abbe: '',
  power: 'fringes',
  irregularity: 'fringes',
  irregularity_rotational: 'fringes',
  zernike_form: 'um',
  surface_decenter_x: 'mm',
  surface_decenter_y: 'mm',
  surface_tilt_x: 'deg',
  surface_tilt_y: 'deg',
  element_decenter_x: 'mm',
  element_decenter_y: 'mm',
  element_tilt_x: 'deg',
  element_tilt_y: 'deg',
}

export const DEFAULT_LIMIT: Record<ToleranceType, number> = {
  radius: 0.05,
  thickness: 0.05,
  conic: 0.01,
  index: 0.0005,
  abbe: 0.3,
  power: 3,
  irregularity: 1,
  irregularity_rotational: 0.5,
  zernike_form: 0.05,
  surface_decenter_x: 0.02,
  surface_decenter_y: 0.02,
  surface_tilt_x: 1 / 60,
  surface_tilt_y: 1 / 60,
  element_decenter_x: 0.02,
  element_decenter_y: 0.02,
  element_tilt_x: 1 / 60,
  element_tilt_y: 1 / 60,
}

export const CRITERIA: ToleranceSpec['criterion'][] = ['rms_spot', 'rms_wavefront', 'merit', 'mtf']
const FORM = new Set<ToleranceType>(['power', 'irregularity', 'irregularity_rotational', 'zernike_form'])
const FORM_SURFACES = new Set<Surface['type']>(['standard', 'even_asphere', 'zernike'])
export const TERMS = Array.from({ length: 33 }, (_, k) => k + 5) // Fringe Z5..Z37

const isGlass = (m: string) => !['AIR', 'VACUUM', 'MIRROR', ''].includes(m.toUpperCase())

/** Whether surface i can carry a tolerance of this type (the engine validates the same rules). */
export function supportsTolerance(type: ToleranceType, s: Surface, i: number, n: number): boolean {
  if (type === 'thickness') return i < n - 1 && s.thickness !== null && s.type !== 'coordinate_break'
  if (i < 1 || i >= n - 1 || s.type === 'coordinate_break') return false
  if (type === 'radius') return s.radius !== null && s.type !== 'ideal'
  if (type === 'conic') return s.type !== 'ideal'
  if (type === 'index' || type === 'abbe') return isGlass(s.material)
  if (FORM.has(type)) return FORM_SURFACES.has(s.type)
  return true
}
