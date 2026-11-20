// Laptop layout rules (docs/UI_DESIGN.md, Laptop layout).
import { describe, expect, it } from 'vitest'
import { PLOT_MIN_H, SPOT_MIN, spotGrid } from './plotLayout'
import { visibleTabs } from './tabOverflow'
import { defaultBottomHeight, inspectorAsOverlay, maxBottomHeight } from './viewport'
import { defaultLayout, workspace } from './workspaces'

describe('inspector placement', () => {
  it('floats over the analysis area below 1440 px and docks from 1440 px', () => {
    expect(inspectorAsOverlay(1280)).toBe(true)
    expect(inspectorAsOverlay(1366)).toBe(true)
    expect(inspectorAsOverlay(1439)).toBe(true)
    expect(inspectorAsOverlay(1440)).toBe(false)
    expect(inspectorAsOverlay(1920)).toBe(false)
  })
})

describe('bottom panel height', () => {
  it('defaults lower on a short window (30 %, 180…300 px)', () => {
    expect(defaultBottomHeight(800)).toBe(240)
    expect(defaultBottomHeight(1080)).toBe(300)
    expect(defaultBottomHeight(600)).toBe(180)
  })

  it('applies to the workspace default layouts, which keep their views and tabs', () => {
    const l = defaultLayout('analyze', 800)
    expect(l.bottomHeight).toBe(240)
    expect(l.rightView).toBe(workspace('analyze').layout.rightView)
    expect(l.bottomTab).toBe(workspace('analyze').layout.bottomTab)
  })

  it('cannot be dragged over the analysis area', () => {
    expect(maxBottomHeight(800)).toBe(540)
    expect(maxBottomHeight(300)).toBe(140)
  })
})

describe('bottom tab overflow', () => {
  const w = [100, 80, 120, 90, 110, 70, 95]

  it('shows every tab when they fit', () => {
    expect(visibleTabs(w, 700, 0, 56)).toEqual([0, 1, 2, 3, 4, 5, 6])
  })

  it('keeps room for the menu button and the order of the tabs', () => {
    // 400 − 56 = 344: 100 + 80 + 120 = 300 fit, 90 more does not
    expect(visibleTabs(w, 400, 1, 56)).toEqual([0, 1, 2])
  })

  it('always shows the active tab, in place of the last tabs that fit', () => {
    expect(visibleTabs(w, 400, 6, 56)).toEqual([0, 1, 6])
    expect(visibleTabs(w, 200, 4, 56)).toEqual([4])
  })
})

describe('plot minimum sizes', () => {
  it('lets spot cells fill a large pane', () => {
    expect(spotGrid(3, 1200, 500)).toEqual({ cols: 3, rowHeight: null })
  })

  it('keeps spot cells at least SPOT_MIN in a small pane and scrolls', () => {
    const g = spotGrid(3, 400, 280)
    expect(g.rowHeight).not.toBeNull()
    expect(400 / g.cols).toBeGreaterThanOrEqual(SPOT_MIN)
    expect(g.rowHeight! - 44).toBeGreaterThanOrEqual(SPOT_MIN)
  })

  it('uses one column in a pane narrower than one cell', () => {
    expect(spotGrid(3, 150, 200).cols).toBe(1)
  })

  it('matches the Tailwind minimum height used by single plots (min-h-60)', () => {
    expect(PLOT_MIN_H).toBe(60 * 4)
  })
})
