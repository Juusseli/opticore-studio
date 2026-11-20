// An analysis bar is one row. When its primary settings do not fit (a narrow split pane), they fold into the
// settings popover instead of wrapping or scrolling out of sight; they come back when the pane is wide enough.

/** Extra width required before unfolding: the folded bar's trigger may be narrower than the unfolded one,
 *  so unfolding at exactly the measured width could overflow again and flap. */
export const UNFOLD_SLACK = 48

export interface FoldState {
  folded: boolean
  /** width the primary settings needed when they last overflowed (px) */
  need: number
}

/**
 * Next fold state from a measurement of the controls area.
 * Unfolded: `scroll` and `client` are the controls row's scrollWidth and clientWidth; it folds when the content
 * overflows. Folded: `client` is the free width the row would have; it unfolds once that exceeds the need.
 */
export function nextFold(s: FoldState, scroll: number, client: number): FoldState {
  if (!s.folded) return scroll > client + 1 ? { folded: true, need: scroll } : s
  return client >= s.need + UNFOLD_SLACK ? { folded: false, need: s.need } : s
}
