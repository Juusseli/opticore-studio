// XY-polynomial term order matches the engine (backend qpoly.xy_exponents) and Q-type sags draw like the engine.
import { describe, expect, it } from 'vitest'
import { sagR, sagXY } from './sag'
import type { SurfaceGeometry } from './types'
import { xyExponents, xyTermName } from './xyTerms'

describe('XY terms', () => {
  it('orders terms by degree, falling power of x', () => {
    expect(xyExponents(10)).toEqual([
      [1, 0],
      [0, 1],
      [2, 0],
      [1, 1],
      [0, 2],
      [3, 0],
      [2, 1],
      [1, 2],
      [0, 3],
      [4, 0],
    ])
    expect([1, 3, 4, 5, 7, 65].map(xyTermName)).toEqual(['x', 'x²', 'xy', 'y²', 'x²y', 'y¹⁰'])
  })
})

describe('Q-type sags for drawing', () => {
  const geo = (qpoly: SurfaceGeometry['qpoly']) => ({ type: 'qcon', curvature: 0, conic: 0, aspheric: [], qpoly }) as unknown as SurfaceGeometry
  it('draws Qcon as the conic plus u⁴ S(u²)', () => {
    const c = 1 / 30
    const k = -0.5
    const s = geo({ kind: 'qcon', base_curvature: c, conic: k, norm_radius: 5, series: [1e-3, 2e-4] })
    const r = 3
    const x = (r / 5) ** 2
    const base = (c * r * r) / (1 + Math.sqrt(1 - (1 + k) * c * c * r * r))
    expect(sagR(s, r)).toBeCloseTo(base + x * x * (1e-3 + 2e-4 * x), 15)
    expect(sagXY(s, 0, r)).toBe(sagR(s, r))
  })
  it('draws Qbfs as the sphere plus u²(1−u²) S(u²) / √(1 − c²r²)', () => {
    const c = 1 / 25
    const s = geo({ kind: 'qbfs', base_curvature: c, conic: 0, norm_radius: 6, series: [2e-3] })
    const r = 4
    const x = (r / 6) ** 2
    const root = Math.sqrt(1 - c * c * r * r)
    expect(sagR(s, r)).toBeCloseTo((c * r * r) / (1 + root) + (x * (1 - x) * 2e-3) / root, 15)
  })
})
