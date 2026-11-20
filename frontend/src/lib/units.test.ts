import { describe, expect, it } from 'vitest'
import { degToRad, LENGTH_TO_MM, parseEngineering, radToDeg, WAVELENGTH_TO_UM } from './units'

describe('parseEngineering', () => {
  it('parses plain numbers, decimal commas and exponents', () => {
    expect(parseEngineering('12.5')).toEqual({ ok: true, value: 12.5 })
    expect(parseEngineering('12,5')).toEqual({ ok: true, value: 12.5 })
    expect(parseEngineering('-1e-3')).toEqual({ ok: true, value: -0.001 })
    expect(parseEngineering('.5')).toEqual({ ok: true, value: 0.5 })
  })

  it('converts unit suffixes exactly', () => {
    expect(parseEngineering('1in', { units: LENGTH_TO_MM })).toEqual({ ok: true, value: 25.4 })
    expect(parseEngineering('2.5 cm', { units: LENGTH_TO_MM })).toEqual({ ok: true, value: 25 })
    expect(parseEngineering('500um', { units: LENGTH_TO_MM })).toEqual({ ok: true, value: 0.5 })
    expect(parseEngineering('587.5618nm', { units: WAVELENGTH_TO_UM })).toEqual({ ok: true, value: 0.5875618 })
  })

  it('handles infinity only where allowed', () => {
    expect(parseEngineering('inf', { allowInfinity: true })).toEqual({ ok: true, value: null })
    expect(parseEngineering('Infinity', { allowInfinity: true })).toEqual({ ok: true, value: null })
    expect(parseEngineering('∞', { allowInfinity: true })).toEqual({ ok: true, value: null })
    expect(parseEngineering('inf').ok).toBe(false)
  })

  it('rejects invalid input with a message', () => {
    for (const bad of ['', 'abc', '12mm', '1.2.3', '5 parsecs']) {
      const r = parseEngineering(bad)
      expect(r.ok).toBe(false)
    }
    const r = parseEngineering('5 furlong', { units: LENGTH_TO_MM })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toMatch(/Unknown unit/)
  })

  it('enforces bounds and integers', () => {
    expect(parseEngineering('-1', { min: 0 }).ok).toBe(false)
    expect(parseEngineering('2.5', { integer: true }).ok).toBe(false)
    expect(parseEngineering('3', { integer: true, max: 3 })).toEqual({ ok: true, value: 3 })
  })

  it('converts angles', () => {
    expect(radToDeg(degToRad(37.25))).toBeCloseTo(37.25, 12)
    expect(degToRad(180)).toBeCloseTo(Math.PI, 15)
  })
})
