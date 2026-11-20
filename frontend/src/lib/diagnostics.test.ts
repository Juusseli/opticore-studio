import { describe, expect, it } from 'vitest'
import codes from './__fixtures__/diagnostic_codes.json'
import { DIAG_FIXES, explainKeys, explanationKeys, fixActions } from './diagnostics'
import { en, fi } from './i18n'

describe('messages with causes and fixes', () => {
  it('every diagnostic code of the engine is explained, and no stale code is', () => {
    // the fixture is checked against the engine source by backend/tests/test_diagnostic_codes.py
    const engine = Object.keys(codes)
    expect(engine.length).toBeGreaterThanOrEqual(40)
    expect(engine.filter((c) => !(c in DIAG_FIXES))).toEqual([])
    expect(Object.keys(DIAG_FIXES).filter((c) => !engine.includes(c))).toEqual([])
  })

  it('every cause and fix exists in English and Finnish', () => {
    const missing = explanationKeys().filter((k) => !en[k] || !fi[k])
    expect(missing).toEqual([])
    for (const a of ['surface', 'system', 'materials', 'coatings', 'configs', 'lde']) expect([en['dg.act.' + a], fi['dg.act.' + a]].every(Boolean)).toBe(true)
  })

  it('ray failures are told apart by the engine status, and actions fit the message', () => {
    expect(explainKeys({ code: 'RAY_FAILED', message: 'Field 2: marginal +y ray failed at surface 4 (ray misses surface)' }).cause).toBe('dg.RAY_FAILED.miss.cause')
    expect(explainKeys({ code: 'RAY_FAILED', message: 'Field 1: chief ray failed at surface 3 (total internal reflection)' }).fix).toBe('dg.RAY_FAILED.tir.fix')
    expect(explainKeys({ code: 'RAY_FAILED', message: '… (clipped by aperture)' }).cause).toBe('dg.RAY_FAILED.clip.cause')
    expect(explainKeys({ code: 'NEW_CODE', message: '' }).cause).toBe('dg.unknown.cause')
    expect(fixActions({ code: 'RAY_FAILED', surface: 4 })).toEqual(['surface', 'system'])
    expect(fixActions({ code: 'RAY_FAILED', surface: null })).toEqual(['system'])
    expect(fixActions({ code: 'NEGATIVE_EDGE_THICKNESS', surface: 2 })).toEqual(['surface'])
  })
})
