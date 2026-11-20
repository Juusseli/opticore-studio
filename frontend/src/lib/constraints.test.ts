import { describe, expect, it } from 'vitest'
import { exactMode, limitsMet, operandRole, priceLabel } from './constraints'
import type { ConstraintResult, Operand } from './types'

const op = (type: Operand['type'], role?: Operand['role']): Operand => ({ type, target: 0, weight: 1, field: null, wavelength: null, surface_id: null, rings: 4, reference: 'centroid', enabled: true, role })

const row = (patch: Partial<ConstraintResult>): ConstraintResult => ({
  index: 0,
  type: 'max_thickness',
  kind: 'bound',
  surface_id: 's1',
  field: null,
  configuration: null,
  target: 6,
  tolerance: 1e-3,
  before: 5,
  after: 6,
  unit: '',
  met_before: true,
  met: true,
  fixed: false,
  active: true,
  multiplier: 0.2,
  price: { dmerit_dtarget: -0.01, relaxed_target: 6.12, step: 0.12, merit: 0.02, merit_relaxed: 0.0198, change_percent: -1, stationarity: 0.01, approximate: false },
  ...patch,
})

describe('exact limits', () => {
  it('makes limits and first-order targets limits by default, image quality a goal, and lets the role override it', () => {
    const exact = { constraints: 'exact' as const }
    expect(operandRole(op('efl'), exact)).toBe('constraint')
    expect(operandRole(op('min_edge_thickness'), exact)).toBe('constraint')
    expect(operandRole(op('rms_spot'), exact)).toBe('objective')
    expect(operandRole(op('efl', 'objective'), exact)).toBe('objective')
    expect(operandRole(op('rms_spot', 'constraint'), exact)).toBe('constraint')
    // absent means exact (projects saved before the option); weighted makes every operand a goal
    expect(exactMode({})).toBe(true)
    expect(operandRole(op('efl', 'constraint'), { constraints: 'penalty' })).toBe('objective')
  })

  it('counts the limits met and prices only the active ones', () => {
    expect(limitsMet([row({}), row({ met: false })])).toEqual({ met: 1, total: 2 })
    expect(limitsMet(null)).toBeNull()
    expect(priceLabel(row({}))).toEqual({ target: 6.12, percent: -1, approximate: false })
    expect(priceLabel(row({ active: false }))).toBeNull()
    expect(priceLabel(row({ fixed: true }))).toBeNull()
  })
})
