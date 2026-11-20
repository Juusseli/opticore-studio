/** Multi-configuration helpers (pure data substitution; the engine applies the active configuration). */
import { CONFIG_FIELD_PARAMS, CONFIG_SYSTEM_PARAMS, type ConfigParameter, type ConfigValue, type OpticalSystem, type VariableParam } from './types'

export const CONFIG_PARAMS: ConfigParameter[] = ['thickness', 'radius', 'conic', 'material', 'semi_diameter', 'decenter_x', 'decenter_y', 'tilt_x', 'tilt_y', 'tilt_z', 'aperture_value', 'temperature', 'pressure', 'vdx', 'vdy', 'vcx', 'vcy']

/** i18n key of a configuration parameter's name */
export const configParamKey = (p: ConfigParameter) => `mc.p.${p}`

export const isSystemConfigParam = (p: ConfigParameter) => CONFIG_SYSTEM_PARAMS.includes(p)

export const isFieldConfigParam = (p: ConfigParameter) => CONFIG_FIELD_PARAMS.includes(p)

export type VigFactors = { vdx: number; vdy: number; vcx: number; vcy: number }
const VIG_KEYS = ['vdx', 'vdy', 'vcx', 'vcy'] as const

/** Write vignetting factors per configuration (perConfig[k][field]) into the configuration table: one row per field
 * and factor that is non-zero in some configuration; rows whose factor is zero everywhere are removed, and the base
 * fields' own factors are cleared (the table holds them all). Mutates the system (call inside a commit). */
export function setConfigVignetting(sys: OpticalSystem, perConfig: VigFactors[][]): void {
  const mc = sys.multi_config
  if (!mc) return
  sys.fields.forEach((f, i) => {
    for (const key of VIG_KEYS) {
      delete f[key]
      const values = perConfig.map((r) => r[i]?.[key] ?? 0)
      const row = fieldConfigRow(sys, i, key)
      if (values.every((v) => v === 0)) {
        if (row >= 0) mc.operands.splice(row, 1)
      } else if (row >= 0) mc.operands[row].values = values
      else mc.operands.push({ parameter: key, surface_id: null, field: i, values })
    }
  })
}

/** Remove every vignetting factor: the fields' own and the configuration table's. */
export function clearVignetting(sys: OpticalSystem): void {
  for (const f of sys.fields) for (const key of VIG_KEYS) delete f[key]
  if (sys.multi_config) sys.multi_config.operands = sys.multi_config.operands.filter((o) => !isFieldConfigParam(o.parameter))
}

/** Row of a field's vignetting factor in the configuration table, or -1. */
export function fieldConfigRow(sys: OpticalSystem, field: number, parameter: ConfigParameter): number {
  return sys.multi_config ? sys.multi_config.operands.findIndex((o) => o.parameter === parameter && (o.field ?? null) === field) : -1
}

/** Optimisation variable parameter -> configuration-table parameter. */
export const CONFIG_OF_VARIABLE: Partial<Record<VariableParam, ConfigParameter>> = {
  curvature: 'radius',
  thickness: 'thickness',
  conic: 'conic',
  decenter_x: 'decenter_x',
  decenter_y: 'decenter_y',
  tilt_x: 'tilt_x',
  tilt_y: 'tilt_y',
  tilt_z: 'tilt_z',
}

export function configRow(sys: OpticalSystem, surfaceId: string | null, parameter: ConfigParameter): number {
  const mc = sys.multi_config
  if (!mc) return -1
  return mc.operands.findIndex((o) => o.parameter === parameter && o.surface_id === surfaceId && (o.field ?? null) === null)
}

/** Value of a configuration-controlled parameter in the active configuration, or undefined if not controlled. */
export function activeOverride(sys: OpticalSystem, surfaceId: string | null, parameter: ConfigParameter): { row: number; value: ConfigValue } | undefined {
  const r = configRow(sys, surfaceId, parameter)
  if (r < 0 || !sys.multi_config) return undefined
  return { row: r, value: sys.multi_config.operands[r].values[sys.multi_config.active] }
}

/** Current base value of a parameter, used to seed a new configuration row. */
export function baseValue(sys: OpticalSystem, surfaceId: string | null, parameter: ConfigParameter): ConfigValue {
  if (parameter === 'aperture_value') return sys.aperture.value
  if (parameter === 'temperature') return sys.temperature_c
  if (parameter === 'pressure') return sys.pressure_atm ?? 1
  const s = sys.surfaces.find((x) => x.id === surfaceId)
  if (!s) return null
  if (parameter === 'semi_diameter') return s.semi_diameter
  return s[parameter as keyof typeof s] as ConfigValue
}
