import { describe, expect, it } from 'vitest'
import { compactNumber } from './uiUtils'

describe('compactNumber (display only)', () => {
  it('shows at most 10 significant digits without trailing zeros', () => {
    expect(compactNumber(44.78)).toBe('44.78')
    expect(compactNumber(100)).toBe('100')
    expect(compactNumber(48.964708029569564)).toBe('48.96470803')
    expect(compactNumber(-296.92916823072)).toBe('-296.9291682')
    expect(compactNumber(0)).toBe('0')
    expect(compactNumber(2.5e-9)).toBe('2.5e-9')
    expect(compactNumber(1.23456789e12)).toBe('1.234568e+12')
  })
})
