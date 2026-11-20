import { CONFIG_OF_VARIABLE, configRow } from './configs'
import { variableValue } from './project'
import type { OpticalSystem, OptimizationSpec } from './types'

/** Quick focus set-up: the image distance as the only variable, the polychromatic RMS spot as the merit.
 * An image distance set per configuration (a row in the configuration editor) is a per-configuration variable of
 * the active configuration, and its result goes back to that row. Null without a finite image distance. */
export function quickFocusSetup(s: OpticalSystem): { t0: number; spec: OptimizationSpec; row: number; configuration: number | null } | null {
  const last = s.surfaces[s.surfaces.length - 2]
  if (!last) return null
  const row = configRow(s, last.id, CONFIG_OF_VARIABLE.thickness!)
  const configuration = row >= 0 && s.multi_config ? s.multi_config.active : null
  // an empty configuration value is no distance (variableValue would read it as 0)
  if (configuration !== null && typeof s.multi_config!.operands[row].values[configuration] !== 'number') return null
  const t0 = variableValue(s, last.id, 'thickness', configuration)
  if (!Number.isFinite(t0)) return null
  const spec: OptimizationSpec = {
    variables: [
      {
        surface_id: last.id,
        parameter: 'thickness',
        configuration,
        min: t0 >= 0 ? Math.max(0, t0 - Math.abs(t0) * 0.5 - 10) : t0 * 1.5 - 10,
        max: t0 >= 0 ? t0 * 1.5 + 10 : Math.min(0, t0 * 0.5 + 10),
        enabled: true,
      },
    ],
    operands: [{ type: 'rms_spot', target: 0, weight: 1, field: null, wavelength: null, surface_id: null, rings: 5, reference: 'centroid', enabled: true, configuration }],
    algorithm: 'local',
    max_evaluations: 300,
    multistart_runs: 2,
    seed: 1,
  }
  return { t0, spec, row, configuration }
}
