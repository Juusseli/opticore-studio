// Which tabs of a tab strip fit, and which go into its overflow menu (docs/UI_DESIGN.md, Laptop layout).

/**
 * Indices of the tabs to show, in their order, for tab widths `widths` in `available` px.
 * When not all fit, room is kept for the overflow button (`moreWidth`) and the active tab always stays
 * visible: it takes the place of the last tab that fits, so the strip keeps its order otherwise.
 */
export function visibleTabs(widths: number[], available: number, active: number, moreWidth: number): number[] {
  const all = widths.map((_, i) => i)
  const total = widths.reduce((a, w) => a + w, 0)
  if (total <= available) return all
  const room = available - moreWidth
  const shown: number[] = []
  let used = 0
  for (const i of all) {
    if (used + widths[i] > room) break
    shown.push(i)
    used += widths[i]
  }
  if (active >= 0 && active < widths.length && !shown.includes(active)) {
    // drop tabs from the end until the active one fits, then append it
    while (shown.length && used + widths[active] > room) used -= widths[shown.pop()!]
    shown.push(active)
  }
  return shown
}
