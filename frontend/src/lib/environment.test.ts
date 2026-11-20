// Environment model in the UI (ADR-027): settings, labels and the System card row.
import { describe, expect, it } from 'vitest'
import { systemChecklist } from './checklist'
import { CONFIG_PARAMS, configParamKey, isSystemConfigParam } from './configs'
import { effectiveEnvironment, HOUSING_MATERIALS, housingPreset } from './environment'
import { dictionaries } from './i18n'
import { blankProject } from './project'

describe('environment settings', () => {
  it('recognises housing presets and falls back to custom', () => {
    expect(housingPreset(23.6)).toBe('aluminium')
    expect(housingPreset(1.3)).toBe('invar')
    expect(housingPreset(5)).toBe('custom')
    for (const m of HOUSING_MATERIALS) expect(dictionaries.en[`env.mat.${m.id}`] && dictionaries.fi[`env.mat.${m.id}`]).toBeTruthy()
  })

  it('takes temperature and pressure from the active configuration when it sets them', () => {
    const p = blankProject()
    const sys = { ...p.system, environment_enabled: true, temperature_c: 20, pressure_atm: 1 }
    expect(effectiveEnvironment(sys)).toEqual({ enabled: true, temperature: 20, pressure: 1, perConfig: false })
    const mc = { names: ['cold', 'hot'], active: 1, operands: [{ parameter: 'temperature' as const, surface_id: null, values: [-20, 60] }] }
    expect(effectiveEnvironment({ ...sys, multi_config: mc })).toEqual({ enabled: true, temperature: 60, pressure: 1, perConfig: true })
  })

  it('names every configuration parameter in both languages; temperature and pressure belong to the system', () => {
    for (const p of CONFIG_PARAMS) {
      expect(dictionaries.en[configParamKey(p)], p).toBeTruthy()
      expect(dictionaries.fi[configParamKey(p)], p).toBeTruthy()
    }
    expect(isSystemConfigParam('temperature') && isSystemConfigParam('pressure') && isSystemConfigParam('aperture_value')).toBe(true)
    expect(isSystemConfigParam('thickness')).toBe(false)
  })
})

describe('System card', () => {
  const base = {
    evaluation: null,
    evalError: null,
    aperture: { type: 'epd', value: 10 },
    fields: 1,
    wavelengths: [0.5876],
    surfaces: 2,
    focus: null,
    optimization: { variables: [], operands: [], algorithm: 'local', max_evaluations: 100 } as never,
    savedOptimizations: [],
    merit: null,
  }

  it('shows the environment row only when the model is on, with its label in both languages', () => {
    expect(systemChecklist(base).some((x) => x.id === 'environment')).toBe(false)
    const items = systemChecklist({ ...base, environment: { temperature: 60, pressure: 0.5 } })
    const env = items.find((x) => x.id === 'environment')!
    expect(env.detail).toBe('chk.d.env')
    expect(env.vars).toEqual({ t: 60, p: 0.5 })
    expect(items.map((x) => x.id).indexOf('environment')).toBe(items.map((x) => x.id).indexOf('wavelengths') + 1)
    expect(dictionaries.en['chk.l.environment'] && dictionaries.fi['chk.l.environment']).toBeTruthy()
  })
})
