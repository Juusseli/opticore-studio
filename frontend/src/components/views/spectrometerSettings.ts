/** Settings of the Spectrometer view: the /analysis/spectrometer request without the system. */
export interface SpectrometerSettings {
  field: number
  /** null: the system's own wavelength range */
  wl_min_um: number | null
  wl_max_um: number | null
  points: number
  density: number
}

export const SPECTROMETER_DEFAULTS: SpectrometerSettings = { field: 0, wl_min_um: null, wl_max_um: null, points: 41, density: 6 }
