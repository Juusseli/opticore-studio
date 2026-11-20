// Environment model settings (temperature, pressure, housing) shown in the UI; the engine computes
// everything (backend opticore/environment.py).
import { activeOverride } from './configs'
import type { OpticalSystem } from './types'

/** Reference temperature of the prescription and of the catalogue CTEs (°C). */
export const T_REF = 20
export const DEFAULT_HOUSING_CTE = 23.6

/** Housing / spacer materials: typical linear expansion near room temperature (1e-6/K, ASM handbook values). */
export const HOUSING_MATERIALS: { id: string; cte: number }[] = [
  { id: 'aluminium', cte: 23.6 },
  { id: 'stainless', cte: 17.3 },
  { id: 'brass', cte: 20.5 },
  { id: 'titanium', cte: 8.6 },
  { id: 'invar', cte: 1.3 },
]

/** The preset whose CTE matches (to 0.05e-6/K), or 'custom'. */
export function housingPreset(cte: number): string {
  return HOUSING_MATERIALS.find((m) => Math.abs(m.cte - cte) < 0.05)?.id ?? 'custom'
}

/** Temperature and pressure in effect (the active configuration's values where it sets them). */
export function effectiveEnvironment(sys: OpticalSystem): { enabled: boolean; temperature: number; pressure: number; perConfig: boolean } {
  const t = activeOverride(sys, null, 'temperature')
  const p = activeOverride(sys, null, 'pressure')
  return {
    enabled: !!sys.environment_enabled,
    temperature: t ? Number(t.value) : sys.temperature_c,
    pressure: p ? Number(p.value) : (sys.pressure_atm ?? 1),
    perConfig: !!(t || p),
  }
}
