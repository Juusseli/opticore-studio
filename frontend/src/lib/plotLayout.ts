// Sizes of analysis plots in small panes (docs/UI_DESIGN.md, Laptop layout): below a minimum a plot
// scrolls instead of shrinking to an unreadable size.

/** Smallest spot diagram plot (px, square) */
export const SPOT_MIN = 180
/** Smallest single-plot height (px); Tailwind `min-h-60` in the views */
export const PLOT_MIN_H = 240

/**
 * Grid of `n` square spot cells in a `w` × `h` area; every cell has a `header` px title row.
 * Picks the column count with the largest cells. If even those are smaller than `min`, the cells keep
 * `min` (or the column width, if larger) and the grid scrolls: `rowHeight` is then the fixed row height.
 */
export function spotGrid(n: number, w: number, h: number, header = 44, min = SPOT_MIN): { cols: number; rowHeight: number | null } {
  const count = Math.max(n, 1)
  let cols = 1
  let best = 0
  for (let c = 1; c <= count; c++) {
    const rows = Math.ceil(count / c)
    const cell = Math.min(w / c, (h - rows * header) / rows)
    if (cell > best) {
      best = cell
      cols = c
    }
  }
  if (best >= min || w <= 0 || h <= 0) return { cols, rowHeight: null }
  const c = Math.max(1, Math.min(count, Math.floor(w / min)))
  return { cols: c, rowHeight: Math.floor(Math.max(min, w / c)) + header }
}
