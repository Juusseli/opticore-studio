// Tolerance rules of the tolerance editor: types, units and supported surfaces.
import { describe, expect, it } from 'vitest'
import { blankProject } from './project'
import { DEFAULT_LIMIT, supportsTolerance, TERMS, TYPES, UNIT } from './tolerance'
import type { Surface } from './types'

describe('tolerance rules', () => {
  it('covers every type with a unit and a default limit', () => {
    for (const ty of TYPES) {
      expect(UNIT[ty]).toBeDefined()
      expect(DEFAULT_LIMIT[ty]).toBeGreaterThan(0)
    }
    expect(UNIT.power).toBe('fringes')
    expect(UNIT.zernike_form).toBe('um')
    expect(TERMS[0]).toBe(5)
    expect(TERMS[TERMS.length - 1]).toBe(37)
  })

  it('offers each type only on surfaces the engine accepts', () => {
    const sys = blankProject().system // object, N-BK7 front (R 100), air back (R -100), image
    const s = sys.surfaces
    const n = s.length
    const ok = (ty: Parameters<typeof supportsTolerance>[0], i: number, patch: Partial<Surface> = {}) => supportsTolerance(ty, { ...s[i], ...patch }, i, n)
    expect(ok('thickness', 0)).toBe(false) // an object at infinity
    expect(ok('thickness', 0, { thickness: 500 })).toBe(true) // a finite object distance
    expect(ok('thickness', n - 1)).toBe(false) // never the image
    expect(ok('radius', 1)).toBe(true)
    expect(ok('radius', 1, { radius: null })).toBe(false) // plane
    expect(ok('power', 1, { radius: null })).toBe(true) // a flat can have power (flatness) error
    expect(ok('index', 1)).toBe(true)
    expect(ok('abbe', 2)).toBe(false) // air after the surface
    expect(ok('irregularity', 1, { type: 'biconic' })).toBe(false)
    expect(ok('zernike_form', 1, { type: 'zernike' })).toBe(true)
    expect(ok('surface_tilt_x', 1, { type: 'coordinate_break' })).toBe(false)
    expect(ok('power', n - 1)).toBe(false)
  })
})
