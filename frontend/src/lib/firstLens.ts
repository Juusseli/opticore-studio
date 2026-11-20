// The guided First lens: inputs of the stepper (the engine builds the lens: /design/first-lens).

export const WAVELENGTH_PRESETS = {
  fdc: { values: [0.4861327, 0.5875618, 0.6562725], primary: 1 },
  visible: { values: [0.45, 0.5, 0.55, 0.6, 0.65], primary: 2 },
  hene: { values: [0.6328], primary: 0 },
} as const
export type WavelengthPreset = keyof typeof WAVELENGTH_PRESETS

export interface FirstLensSpec {
  focal_length: number
  f_number: number
  half_field_deg: number
  preset: WavelengthPreset
  kind: 'singlet' | 'doublet'
  crown: string
  flint: string
}

export const DEFAULT_FIRST_LENS: FirstLensSpec = { focal_length: 100, f_number: 5, half_field_deg: 2, preset: 'fdc', kind: 'singlet', crown: 'N-BK7', flint: 'F2' }

/** A step's inputs are usable (the engine checks the physics; this only keeps the stepper from going on with blanks). */
export function stepValid(step: number, s: FirstLensSpec): boolean {
  if (step === 0) return s.focal_length > 0 && s.f_number >= 0.5 && s.half_field_deg >= 0 && s.half_field_deg <= 60
  if (step === 2) return !!s.crown && (s.kind === 'singlet' || (!!s.flint && WAVELENGTH_PRESETS[s.preset].values.length > 1))
  return true
}
