import { fmt } from './format'
import type { CoatingDesignSpec, CoatingQuantity, CoatingRecipe, CoatingTarget, DesignLayer } from './types'

/** Quantities that are fractions (shown in %). */
export const FRACTION_Q: CoatingQuantity[] = ['R', 'T', 'A', 'Rv', 'Tv']
/** Quantities of the complex amplitudes (against wavelength). */
export const PHASE_Q: CoatingQuantity[] = ['GD', 'GDD', 'phase', 'retardance']
/** One value from the colour over 380–780 nm (D65, CIE 1931 2°). */
export const COLOUR_Q: CoatingQuantity[] = ['Rv', 'Tv', 'L*', 'a*', 'b*']
export const QUANTITIES: CoatingQuantity[] = ['R', 'T', 'A', 'GD', 'GDD', 'phase', 'retardance', 'Rv', 'Tv', 'L*', 'a*', 'b*']
export const isFraction = (q: CoatingQuantity) => FRACTION_Q.includes(q)
/** Units shown with a target value (fractions in %). */
export function quantityUnits(q: CoatingQuantity): string {
  return isFraction(q) ? '%' : q === 'GD' ? 'fs' : q === 'GDD' ? 'fs²' : q === 'phase' || q === 'retardance' ? '°' : ''
}
/** Display value of a target quantity (fractions × 100). */
export const shown = (q: CoatingQuantity, v: number) => (isFraction(q) ? v * 100 : v)
export const stored = (q: CoatingQuantity, v: number) => (isFraction(q) ? v / 100 : v)
/** Does the quantity take the reflected/transmitted choice? */
export const hasOf = (q: CoatingQuantity) => PHASE_Q.includes(q) || ['L*', 'a*', 'b*'].includes(q)

/** A target of another quantity: sensible value, range and samples for it. */
export function retarget(tg: CoatingTarget, q: CoatingQuantity): CoatingTarget {
  const base = { ...tg, quantity: q, value_end: null }
  const v: Record<CoatingQuantity, number> = { R: 0.01, T: 0.95, A: 0.01, GD: 0, GDD: 0, phase: 0, retardance: 90, Rv: 0.005, Tv: 0.95, 'L*': 50, 'a*': 0, 'b*': 0 }
  const tol: Record<CoatingQuantity, number> = { R: 0, T: 0, A: 0, GD: 2, GDD: 10, phase: 5, retardance: 2, Rv: 0, Tv: 0, 'L*': 1, 'a*': 1, 'b*': 1 }
  base.value = v[q]
  base.tolerance = tol[q]
  base.kind = q === 'R' || q === 'A' || q === 'Rv' ? '<=' : q === 'T' || q === 'Tv' ? '>=' : '='
  if (COLOUR_Q.includes(q)) Object.assign(base, { lambda_min_nm: 380, lambda_max_nm: 780, points: 1 })
  else if (PHASE_Q.includes(q) && q !== 'retardance' && q !== 'phase' && (base.points < 5 || base.lambda_max_nm <= base.lambda_min_nm)) Object.assign(base, { points: 31, lambda_max_nm: Math.max(base.lambda_max_nm, base.lambda_min_nm + 20) })
  if (hasOf(q) && !base.of) base.of = 'R'
  return base
}

/** One line for a target: "GDD(R) = −40 ±15 fs² @ 770–830 nm, 45°". */
export function targetText(g: CoatingTarget): string {
  const q = g.quantity
  const u = quantityUnits(q)
  const of = hasOf(q) ? `(${g.of ?? 'R'})` : ''
  const pol = g.polarization && g.polarization !== 'avg' ? g.polarization : ''
  const val = g.table?.length ? `[${g.table.length} pts]` : `${fmt(shown(q, g.value), 4)}${g.value_end != null ? `→${fmt(shown(q, g.value_end), 4)}` : ''}`
  const tol = g.tolerance ? ` ±${fmt(shown(q, g.tolerance), 3)}` : ''
  const unit = u && !g.table?.length ? ` ${u}` : ''
  const where = COLOUR_Q.includes(q) ? `${g.illuminant ?? 'D65'}${g.observer === '10' ? ' 10°' : ''}` : `${g.lambda_min_nm === g.lambda_max_nm ? fmt(g.lambda_min_nm, 5) : `${fmt(g.lambda_min_nm, 5)}–${fmt(g.lambda_max_nm, 5)}`} nm`
  return `${q}${pol}${of} ${g.kind ?? '='} ${val}${tol}${unit} @ ${where}${g.angle_deg ? `, ${fmt(g.angle_deg, 3)}°` : ''}`
}

/** Parse a measured spectrum pasted as text: one "wavelength value" pair per line (comma, semicolon, tab or space
 * separated; lines starting with # or text are skipped). Values in percent when `percent`. */
export function parseSpectrum(text: string, percent: boolean): { lambda_nm: number[]; value: number[]; skipped: number } {
  const lambda_nm: number[] = []
  const value: number[] = []
  let skipped = 0
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const parts = line.split(/[\s,;]+/).filter(Boolean)
    const a = Number(parts[0])
    const b = Number(parts[1])
    if (parts.length < 2 || !Number.isFinite(a) || !Number.isFinite(b)) {
      skipped++
      continue
    }
    lambda_nm.push(a)
    value.push(percent ? b / 100 : b)
  }
  return { lambda_nm, value, skipped }
}

/** Nominal starting palette. The indices are generic design values, not film data:
 * replace them with the measured dispersion of your own chamber's films (custom materials). */
export function defaultCoatingDesign(): CoatingDesignSpec {
  return {
    name: 'Coating design',
    incident: 'AIR',
    substrate: 'N-BK7',
    back_side: 'none',
    palette: [
      { key: 'H', label: 'high index (nominal)', material: '', index: 2.35, extinction: 0, tooling: 1, rate_nm_s: 0.3 },
      { key: 'L', label: 'low index (nominal)', material: '', index: 1.46, extinction: 0, tooling: 1, rate_nm_s: 0.8 },
    ],
    layers: [],
    targets: [],
    design_wavelength_nm: 550,
    min_thickness_nm: 0,
    max_thickness_nm: 2000,
  }
}

export function defaultTarget(lam0: number): CoatingTarget {
  return { quantity: 'T', polarization: 'avg', angle_deg: 0, lambda_min_nm: Math.round(lam0 * 0.9), lambda_max_nm: Math.round(lam0 * 1.1), value: 0.95, value_end: null, kind: '>=', weight: 1, tolerance: 0, points: 41 }
}

/** Drop unlocked layers thinner than `minNm` and merge equal unlocked neighbours (data edit only). */
export function removeThinLayers(layers: DesignLayer[], minNm: number): DesignLayer[] {
  const out: DesignLayer[] = []
  for (const L of layers) {
    if (!L.locked && L.thickness_nm < minNm) continue
    const last = out[out.length - 1]
    if (last && last.material === L.material && !last.locked && !L.locked) last.thickness_nm += L.thickness_nm
    else out.push({ ...L })
  }
  return out
}

const csvCell = (v: string | number) => {
  const s = typeof v === 'number' ? (Number.isInteger(v) ? String(v) : v.toPrecision(8).replace(/\.?0+$/, '')) : v
  return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/** Deposition recipe as CSV (layer 1 = first deposited, on the substrate). */
export function recipeToCsv(r: CoatingRecipe): string {
  const head = [
    `# OptiCore Studio deposition recipe: ${r.name}`,
    `# substrate ${r.substrate}; incident medium ${r.incident}; layer 1 is deposited first (on the substrate)`,
    `# optical monitor: ${r.monitor} at ${r.monitor_wavelength_nm} nm, normal incidence, ${r.monitor_back_side === 'uncoated' ? 'through the plate (uncoated back surface)' : 'single surface'}`,
    `# total physical thickness ${r.total_thickness_nm.toFixed(2)} nm; estimated deposition time ${(r.total_time_s / 60).toFixed(1)} min (rates below, excluding pumping, heating and rate stabilisation)`,
    ...r.palette.map((p) => `# material ${p.key}: ${p.label || p.material || 'fixed index'}${p.material ? ` (${p.material})` : ` n = ${p.index}${p.extinction ? `, k = ${p.extinction}` : ''}`}; tooling ${p.tooling}; rate ${p.rate_nm_s} nm/s`),
  ]
  const cols = ['layer', 'material', 'physical_nm', 'cumulative_nm', 'qwot_design', 'qwot_monitor', `${r.monitor}_start`, `${r.monitor}_end`, 'turning_points', 'termination', 'crystal_nm', 'crystal_kA', 'rate_nm_s', 'time_s']
  const rows = r.layers.map((x) =>
    [x.layer, x.material, x.thickness_nm, x.cumulative_nm, x.qwot_design, x.qwot_monitor, x.monitor_start, x.monitor_end, x.turning_points, x.termination, x.crystal_nm, x.crystal_kA, x.rate_nm_s, x.time_s].map(csvCell).join(','),
  )
  return [...head, cols.join(','), ...rows].join('\n') + '\n'
}
