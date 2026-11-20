import { describe, expect, it } from 'vitest'
import { FIT_MARGIN, fitView, framing, needsRefit } from './framing'

const box = { zmin: 0, zmax: 100, ymin: -10, ymax: 10 }

describe('2D layout framing', () => {
  it('a fit frames the whole system with the margin', () => {
    const v = fitView(box, 800, 400)
    expect(v.cx).toBe(50)
    expect(v.cy).toBe(0)
    expect(v.scale).toBeCloseTo((800 - 2 * FIT_MARGIN) / 100, 9)
    const f = framing(box, v, 800, 400)
    expect(f.inView).toBe(true)
    expect(f.fill).toBeCloseTo(1, 6)
    expect(needsRefit(box, v, 800, 400)).toBe(false)
  })

  it('refits when the system grows out of view', () => {
    const v = fitView(box, 800, 400)
    expect(needsRefit({ ...box, zmax: 160 }, v, 800, 400)).toBe(true)
    // a small change that still fits keeps the view
    expect(needsRefit({ ...box, zmax: 104 }, v, 800, 400)).toBe(false)
  })

  it('refits when another system is a small part of the old view (2 mm in a 100 mm frame)', () => {
    const v = fitView(box, 800, 400)
    expect(needsRefit({ zmin: 10, zmax: 12, ymin: -0.5, ymax: 0.5 }, v, 800, 400)).toBe(true)
  })

  it('reports a zoomed-in view as out of view', () => {
    const v = { ...fitView(box, 800, 400), scale: 50 }
    expect(framing(box, v, 800, 400).inView).toBe(false)
  })
})
