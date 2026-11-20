// Automatic framing of the 2D layout: fit on open, keep the user's zoom, refit when the system no
// longer fits or has shrunk to a small part of the view.

export interface Bounds {
  zmin: number
  zmax: number
  ymin: number
  ymax: number
}

/** Centre (world z, y) and scale (px per mm) of the 2D layout. */
export interface View {
  cx: number
  cy: number
  scale: number
}

export const FIT_MARGIN = 30 // px on each side

export function fitView(b: Bounds, w: number, h: number): View {
  const zw = b.zmax - b.zmin + 1e-9
  const yh = b.ymax - b.ymin + 1e-9
  const scale = Math.min((w - 2 * FIT_MARGIN) / zw, (h - 2 * FIT_MARGIN) / yh)
  return { cx: (b.zmin + b.zmax) / 2, cy: (b.ymin + b.ymax) / 2, scale: Math.max(scale, 1e-6) }
}

/** fill: largest fraction of the usable pane the content spans (1 right after a fit);
 * inView: the whole content is inside the pane. */
export function framing(b: Bounds, v: View, w: number, h: number): { fill: number; inView: boolean } {
  const X = (z: number) => (z - v.cx) * v.scale + w / 2
  const Y = (y: number) => h / 2 - (y - v.cy) * v.scale
  const tol = 1
  const inView = X(b.zmin) >= -tol && X(b.zmax) <= w + tol && Y(b.ymax) >= -tol && Y(b.ymin) <= h + tol
  const fill = Math.max(((b.zmax - b.zmin) * v.scale) / Math.max(w - 2 * FIT_MARGIN, 1), ((b.ymax - b.ymin) * v.scale) / Math.max(h - 2 * FIT_MARGIN, 1))
  return { fill, inView }
}

/** Refit when part of the system is out of view or it fills less than a third of the pane. */
export function needsRefit(b: Bounds, v: View, w: number, h: number): boolean {
  const f = framing(b, v, w, h)
  return !f.inView || f.fill < 1 / 3
}
