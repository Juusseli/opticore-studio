import { describe, expect, it } from 'vitest'
import { type ChecklistInput, diagnosticGroup, specPass, specValues, systemChecklist } from './checklist'
import { en, fi } from './i18n'
import type { Diagnostic, Evaluation, FocusResult, OptimizationSpec, Paraxial } from './types'

const opt = (v = 0, o = 0): OptimizationSpec =>
  ({
    variables: Array.from({ length: v }, () => ({ surface_id: 's', parameter: 'thickness', min: null, max: null, enabled: true })),
    operands: Array.from({ length: o }, () => ({ type: 'rms_spot', target: 0, weight: 1, field: null, wavelength: null, surface_id: null, rings: 4, reference: 'centroid', enabled: true })),
    algorithm: 'local',
    max_evaluations: 100,
    multistart_runs: 2,
    seed: 1,
  }) as unknown as OptimizationSpec

const ev = (diagnostics: Diagnostic[] = []) => ({ diagnostics }) as unknown as Evaluation
const focus = (at: boolean, d = 0.12): FocusResult => ({ best_defocus_mm: d, rms_um: 10, rms_best_um: 8, at_best_focus: at, max_field_rms_um: 12, per_field: [], n_rays: 100, exact: true, method: '' })

const base: ChecklistInput = {
  evaluation: ev(),
  evalError: null,
  aperture: { type: 'epd', value: 10 },
  fields: 3,
  wavelengths: [0.486, 0.5876, 0.656],
  surfaces: 4,
  focus: focus(true),
  optimization: opt(),
  savedOptimizations: [],
  merit: null,
}
const byId = (items: ReturnType<typeof systemChecklist>) => Object.fromEntries(items.map((x) => [x.id, x]))

describe('setup checklist', () => {
  it('a clean, focused design without optimisation', () => {
    const c = byId(systemChecklist(base))
    expect([c.aperture.status, c.fields.status, c.wavelengths.status, c.surfaces.status, c.focus.status]).toEqual(['ok', 'ok', 'ok', 'ok', 'ok'])
    expect([c.merit.status, c.optimised.status]).toEqual(['none', 'none'])
    expect(c.wavelengths.vars).toMatchObject({ a: 486, b: 656 })
  })

  it('engine diagnostics land on their item', () => {
    const d = (level: Diagnostic['level'], code: string): Diagnostic => ({ level, code, message: code, surface: 2 })
    const c = byId(systemChecklist({ ...base, evaluation: ev([d('warning', 'RAY_FAILED'), d('warning', 'WAVELENGTH_EXTRAPOLATED'), d('error', 'NEGATIVE_EDGE_THICKNESS'), d('info', 'SOLVE_ACTIVE'), d('warning', 'ZERO_APERTURE')]) }))
    expect(c.fields.status).toBe('warn')
    expect(c.wavelengths.status).toBe('warn')
    expect(c.surfaces.status).toBe('error')
    expect(c.aperture.status).toBe('warn')
    expect(c.surfaces.diagnostics?.map((x) => x.code)).toEqual(['NEGATIVE_EDGE_THICKNESS'])
    expect(diagnosticGroup('SOMETHING_NEW')).toBe('surfaces')
  })

  it('an untraceable system is an error, and focus follows the engine', () => {
    const c = byId(systemChecklist({ ...base, evaluation: null, evalError: 'boom', focus: null }))
    expect(c.surfaces.status).toBe('error')
    expect(c.focus.status).toBe('none')
    const f = byId(systemChecklist({ ...base, focus: focus(false, -0.2) }))
    expect(f.focus).toMatchObject({ status: 'warn', vars: { d: -0.2 } })
  })

  it('variables, merit and optimisation', () => {
    expect(byId(systemChecklist({ ...base, optimization: opt(2, 0) })).merit.status).toBe('warn')
    expect(byId(systemChecklist({ ...base, optimization: opt(2, 3) })).merit.status).toBe('ok')
    const run = { id: 'r', timestamp: '', algorithm: 'local', initial_merit: 1, final_merit: 0.1, evaluations: 10, status: 'ok', variables: [], applied: true }
    expect(byId(systemChecklist({ ...base, savedOptimizations: [{ ...run, applied: false }] })).optimised).toMatchObject({ status: 'none', detail: 'chk.d.notApplied' })
    expect(byId(systemChecklist({ ...base, savedOptimizations: [run], merit: 0.1 })).optimised.status).toBe('ok')
    expect(byId(systemChecklist({ ...base, savedOptimizations: [run], merit: 0.2 })).optimised.status).toBe('warn')
  })

  it('every item and detail text exists in English and Finnish', () => {
    const items = systemChecklist({ ...base, evaluation: ev([{ level: 'warning', code: 'RAY_FAILED', message: '', surface: null }]) })
    for (const it of items) for (const k of [`chk.l.${it.id}`, `chk.h.${it.id}`, it.detail]) expect([en[k], fi[k]], k).toEqual([expect.any(String), expect.any(String)])
    for (const s of ['ok', 'warn', 'error', 'none']) expect(fi['chk.s.' + s]).toBeTruthy()
    for (const a of ['epd', 'image_fnum', 'object_na']) expect(fi['chk.ap.' + a]).toBeTruthy()
  })
})

describe('specifications', () => {
  it('compare engine values with targets', () => {
    const pd = { efl: 100.2, image_space_fnum: 5.01, total_track: 104 } as Paraxial
    const v = specValues(pd, focus(true))
    expect(v).toEqual({ efl: 100.2, fnum: 5.01, rms: 12, track: 104 })
    const specs = { efl: { target: 100, tol: 0.5 }, fnum: { target: 4, tol: 0.1 }, rms: { max: 10 }, track: { max: 110 } }
    expect(specPass('efl', specs, v.efl)).toBe(true)
    expect(specPass('fnum', specs, v.fnum)).toBe(false)
    expect(specPass('rms', specs, v.rms)).toBe(false)
    expect(specPass('track', specs, v.track)).toBe(true)
    expect(specPass('efl', {}, v.efl)).toBeNull()
    expect(specPass('efl', specs, null)).toBeNull()
  })
})
