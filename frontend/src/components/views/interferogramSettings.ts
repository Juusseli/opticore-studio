/** Settings of the Interferogram view: the /analysis/interferogram request without the system. */
export interface InterferogramSettings {
  field: number
  wavelength: number | null
  grid: number
  passes: 1 | 2
  tilt_x: number
  tilt_y: number
  visibility: number
  phase_steps: number
}

export const INTERFEROGRAM_DEFAULTS: InterferogramSettings = { field: 0, wavelength: null, grid: 128, passes: 1, tilt_x: 0, tilt_y: 0, visibility: 1, phase_steps: 4 }
