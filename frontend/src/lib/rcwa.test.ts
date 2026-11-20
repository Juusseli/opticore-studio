import { describe, expect, it } from 'vitest'
import { crossedFrom, formatOrders2d, isCrossed, newLayer, newShape, orders2d, parseOrders, parseOrders2d, RCWA_DEFAULTS } from './rcwa'

describe('grating settings', () => {
  it('parses the orders to plot', () => {
    expect(parseOrders('−1, 0, 1')).toEqual([-1, 0, 1])
    expect(parseOrders('2 1 1 -3')).toEqual([-3, 1, 2])
    expect(parseOrders('a')).toBeNull()
    expect(parseOrders('')).toBeNull()
    expect(parseOrders('0.5')).toBeNull()
    expect(parseOrders('1,2,3,4,5,6,7,8,9,10')?.length).toBe(9)
  })

  it('starts from a lamellar fused-silica grating; a uniform layer has no groove', () => {
    expect(RCWA_DEFAULTS.layers[0].kind).toBe('lamellar')
    expect(newLayer('uniform').groove).toBeNull()
    expect(newLayer('sinusoidal').groove).not.toBeNull()
  })
})

describe('crossed gratings', () => {
  it('parses the (m, q) orders to plot', () => {
    expect(parseOrders2d('0 0; 1 1; −1 −1')).toEqual([[0, 0], [1, 1], [-1, -1]])
    expect(parseOrders2d('(1, 0) | (1, 0) ; (0,1)')).toEqual([[1, 0], [0, 1]])
    expect(parseOrders2d('1')).toBeNull()
    expect(parseOrders2d('1 2 3')).toBeNull()
    expect(parseOrders2d('')).toBeNull()
    expect(formatOrders2d([[0, 0], [1, -1]])).toBe('0 0; 1 -1')
    expect(parseOrders2d(formatOrders2d([[2, -3]]))).toEqual([[2, -3]])
  })

  it('switches to a square cell with fewer harmonics; a pattern layer starts with a centred pillar', () => {
    const c = { ...RCWA_DEFAULTS, ...crossedFrom({ ...RCWA_DEFAULTS, period_um: 0.8 }) }
    expect(isCrossed(RCWA_DEFAULTS)).toBe(false)
    expect(isCrossed(c)).toBe(true)
    expect(c.period_y_um).toBe(0.8)
    expect(c.harmonics).toBe(5)
    expect(orders2d(c)).toBe(121)
    const L = newLayer('pattern', 0.8, 0.6)
    expect(L.shapes).toHaveLength(1)
    expect(L.shapes![0]).toMatchObject({ kind: 'ellipse', cx_um: 0.4, cy_um: 0.3, a_um: 0.3, b_um: 0.3, medium: null })
    expect(newShape(1, 1, 'rectangle').kind).toBe('rectangle')
    expect(newLayer('lamellar').shapes).toBeUndefined()
  })
})
