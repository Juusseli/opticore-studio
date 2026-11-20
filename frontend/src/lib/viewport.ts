// Window-size rules of the laptop layout (docs/UI_DESIGN.md, Laptop layout).
import { useSyncExternalStore } from 'react'

/** Below this window width the Inspector floats over the analysis area instead of taking a column. */
export const INSPECTOR_OVERLAY_BELOW = 1440

export function inspectorAsOverlay(windowWidth: number): boolean {
  return windowWidth < INSPECTOR_OVERLAY_BELOW
}

/** Default bottom panel height for a window height: 30 % of it, between 180 and 300 px
 *  (240 px at 800 px, 300 px from 1000 px). */
export function defaultBottomHeight(windowHeight: number): number {
  return Math.round(Math.min(300, Math.max(180, windowHeight * 0.3)))
}

/** Largest bottom panel that still leaves the analysis area usable. */
export function maxBottomHeight(windowHeight: number): number {
  return Math.max(140, windowHeight - 260)
}

const subscribe = (cb: () => void) => {
  window.addEventListener('resize', cb)
  return () => window.removeEventListener('resize', cb)
}

export function useWindowWidth(): number {
  return useSyncExternalStore(
    subscribe,
    () => window.innerWidth,
    () => 1920,
  )
}
