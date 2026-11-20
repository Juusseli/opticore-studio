// Rows of the optimisation before/after comparison. The numbers come from the engine (/optimize/compare,
// analysis/summary.py), including which ones got worse; this module only orders and formats them.
import { fmt } from './format'
import type { CompareKey, DesignComparison, DesignSummary, OperandBreakdown, OperandType, OptimizationResult } from './types'

export interface CompareRow {
  id: string
  key: CompareKey
  field: number | null
  before: string
  after: string
  delta: string
  flag: 'worse' | 'changed' | null
}

const SCALARS: (CompareKey & keyof DesignSummary)[] = ['distortion_pct', 'lateral_colour_um', 'axial_colour_um', 'relative_illumination', 'cra_deg', 'field', 'efl_mm', 'total_track_mm', 'min_glass_edge_mm', 'min_air_edge_mm']

const num = (x: number | null | undefined, sig = 4) => (x === null || x === undefined || !Number.isFinite(x) ? '—' : fmt(x, sig))
const signed = (x: number, sig = 3) => (x > 0 ? '+' : x < 0 ? '−' : '±') + fmt(Math.abs(x), sig)

export function compareRows(c: DesignComparison): CompareRow[] {
  const flagOf = (key: CompareKey, field: number | null) => c.flags.find((f) => f.key === key && f.field === field)?.kind ?? null
  const rows: CompareRow[] = []
  const nf = Math.max(c.before.rms_spot_um?.length ?? 0, c.after.rms_spot_um?.length ?? 0)
  for (let k = 0; k < nf; k++) {
    const b = c.before.rms_spot_um?.[k] ?? null
    const a = c.after.rms_spot_um?.[k] ?? null
    rows.push({ id: `rms${k}`, key: 'rms_spot_um', field: k, before: num(b), after: num(a), delta: a !== null && b ? `${signed(((a - b) / b) * 100, 3)} %` : '—', flag: flagOf('rms_spot_um', k) })
  }
  const nm = Math.max(c.before.mtf?.length ?? 0, c.after.mtf?.length ?? 0)
  for (let k = 0; k < nm; k++) {
    const b = c.before.mtf?.[k] ?? null
    const a = c.after.mtf?.[k] ?? null
    const ts = (m: [number, number] | null) => (m ? `${fmt(m[0], 2)} / ${fmt(m[1], 2)}` : '—')
    rows.push({ id: `mtf${k}`, key: 'mtf', field: k, before: ts(b), after: ts(a), delta: a && b ? signed((a[0] + a[1]) / 2 - (b[0] + b[1]) / 2, 2) : '—', flag: flagOf('mtf', k) })
  }
  for (const key of SCALARS) {
    const b = c.before[key] as number | null
    const a = c.after[key] as number | null
    if (b === null && a === null) continue
    rows.push({ id: key, key, field: null, before: num(b), after: num(a), delta: a !== null && b !== null ? signed(a - b) : '—', flag: flagOf(key, null) })
  }
  return rows
}

/** Keys that got worse / changed, once each (for the summary line). */
export function flagged(c: DesignComparison, kind: 'worse' | 'changed'): CompareKey[] {
  return [...new Set(c.flags.filter((f) => f.kind === kind).map((f) => f.key))]
}

const GOALS: OperandType[] = ['rms_spot', 'rms_wavefront', 'mtf', 'detector_size']

export interface GoalChange {
  type: OperandType
  before: number
  after: number
  unit: string
  /** closer to the target (MTF and the others: the error |value - target|) */
  better: boolean
}

/** How the image-quality operands of the merit function changed (the merit itself also holds the constraints). */
export function goalChanges(r: OptimizationResult): GoalChange[] {
  const out: GoalChange[] = []
  r.operands_after.forEach((a: OperandBreakdown, k) => {
    const b = r.operands_before[k]
    if (!GOALS.includes(a.type) || !b || a.value === null || b.value === null) return
    // the breakdown reports the RMS spot in µm (unit 'um'); its target is in mm
    const tgt = a.type === 'rms_spot' ? a.target * 1000 : a.target
    out.push({ type: a.type, before: b.value, after: a.value, unit: a.unit ?? '', better: Math.abs(a.value - tgt) <= Math.abs(b.value - tgt) })
  })
  return out.slice(0, 4)
}
