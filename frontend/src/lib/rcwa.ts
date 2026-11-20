// Settings of the Grating (RCWA) view: the /wave/rcwa request itself (analysis_settings.rcwa). The engine's library
// examples store the same shape (backend samples.py) and their tests send it unchanged.

export interface RcwaMedium {
  /** fixed index (with extinction k ≥ 0), or null when a library material is used */
  n: number | null
  k: number
  material: string | null
}

export type RcwaLayerKind = 'uniform' | 'lamellar' | 'sinusoidal' | 'sawtooth' | 'trapezoid' | 'pattern'

/** A shape of a crossed grating's pattern layer, in µm in the unit cell (a, b: side lengths or diameters). */
export interface RcwaShape {
  kind: 'rectangle' | 'ellipse'
  cx_um: number
  cy_um: number
  a_um: number
  b_um: number
  angle_deg: number
  /** null: the layer's ridge medium */
  medium: RcwaMedium | null
}

export interface RcwaLayer {
  kind: RcwaLayerKind
  thickness_um: number
  /** ridge width as a fraction of the period (lamellar) */
  fill: number
  fill_top: number
  fill_bottom: number
  /** lamellar slices of a relief profile */
  slices: number
  /** the layer's medium (uniform) or the ridge medium */
  ridge: RcwaMedium | null
  groove: RcwaMedium | null
  /** shapes of a pattern layer (crossed gratings) on the groove medium as background */
  shapes?: RcwaShape[]
}

export interface RcwaSweep {
  kind: 'wavelength' | 'angle'
  start: number
  stop: number
  points: number
  orders: number[]
  /** orders (m, q) of a crossed grating to plot */
  orders_2d?: [number, number][]
}

export interface RcwaRequest {
  wavelength_um: number
  period_um: number
  theta_deg: number
  phi_deg: number
  polarisation: 'TE' | 'TM' | 'unpolarised'
  harmonics: number
  /** period along y: a crossed grating or metasurface; null or absent: lines periodic in x only */
  period_y_um?: number | null
  harmonics_y?: number
  incident: RcwaMedium
  substrate: RcwaMedium
  layers: RcwaLayer[]
  sweep: RcwaSweep | null
}

export const AIR: RcwaMedium = { n: 1, k: 0, material: null }
export const SILICA: RcwaMedium = { n: null, k: 0, material: 'FUSED_SILICA' }

export function newLayer(kind: RcwaLayerKind = 'lamellar', periodX = 1, periodY = 1): RcwaLayer {
  const L: RcwaLayer = { kind, thickness_um: 0.3, fill: 0.5, fill_top: 0.3, fill_bottom: 0.7, slices: 10, ridge: { ...SILICA }, groove: kind === 'uniform' ? null : { ...AIR } }
  if (kind === 'pattern') L.shapes = [newShape(periodX, periodY)]
  return L
}

/** A centred ellipse (a pillar) of half the smaller period. */
export function newShape(periodX: number, periodY: number, kind: RcwaShape['kind'] = 'ellipse'): RcwaShape {
  const d = +(0.5 * Math.min(periodX, periodY)).toPrecision(4)
  return { kind, cx_um: +(periodX / 2).toPrecision(6), cy_um: +(periodY / 2).toPrecision(6), a_um: d, b_um: d, angle_deg: 0, medium: null }
}

export const isCrossed = (st: RcwaRequest): boolean => !!st.period_y_um

/** Settings for a crossed grating from a 1D one: a square cell and fewer harmonics (the cost grows as (2Mx+1)³(2My+1)³). */
export function crossedFrom(st: RcwaRequest): Partial<RcwaRequest> {
  return { period_y_um: st.period_um, harmonics: Math.min(st.harmonics, 5), harmonics_y: 5 }
}

/** Orders (2Mx+1)(2My+1) of a crossed grating; the engine accepts at most MAX_ORDERS_2D. */
export const orders2d = (st: RcwaRequest): number => (2 * st.harmonics + 1) * (2 * (st.harmonics_y ?? 5) + 1)
export const MAX_ORDERS_2D = 961

export const RCWA_DEFAULTS: RcwaRequest = {
  wavelength_um: 0.633,
  period_um: 1.0,
  theta_deg: 0,
  phi_deg: 0,
  polarisation: 'TE',
  harmonics: 20,
  incident: { ...AIR },
  substrate: { ...SILICA },
  layers: [newLayer('lamellar')],
  sweep: null,
}

/** "0 0; 1 1; −1 −1" ⇄ [[0, 0], [1, 1], [−1, −1]] (pairs m q, at most nine, unique). */
export function parseOrders2d(text: string): [number, number][] | null {
  const groups = text.split(/[;|]+/).map((g) => g.trim()).filter(Boolean)
  const out: [number, number][] = []
  for (const g of groups) {
    const v = g.replace(/[()]/g, ' ').split(/[\s,]+/).filter(Boolean).map((p) => Number(p.replace('−', '-')))
    if (v.length !== 2 || v.some((x) => !Number.isInteger(x) || Math.abs(x) > 50)) return null
    if (!out.some((o) => o[0] === v[0] && o[1] === v[1])) out.push([v[0], v[1]])
  }
  return out.length ? out.slice(0, 9) : null
}

export const formatOrders2d = (o: [number, number][]): string => o.map(([m, q]) => `${m} ${q}`).join('; ')

/** "−1, 0, 1" ⇄ [−1, 0, 1] (at most nine orders, unique, sorted). */
export function parseOrders(text: string): number[] | null {
  const parts = text.split(/[\s,;]+/).filter(Boolean)
  const v = parts.map((p) => Number(p.replace('−', '-')))
  if (!v.length || v.some((x) => !Number.isInteger(x) || Math.abs(x) > 50)) return null
  return [...new Set(v)].sort((a, b) => a - b).slice(0, 9)
}
