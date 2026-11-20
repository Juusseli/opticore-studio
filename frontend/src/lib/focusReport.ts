// Quick focus report: the per-field RMS spot before and after the refocus (engine /analysis/focus numbers).
// Quick focus minimises the field-weighted mean RMS², so a field can get worse (often the centre of a lens with
// field curvature); the report names those fields.
import type { FocusResult } from './types'

export interface FocusReport {
  /** "F1 3.9 → 13.4" per field (µm) */
  fields: string[]
  /** fields (0-based) whose RMS grew by more than 20 % and by more than 0.5 µm */
  worse: number[]
}

export function focusReport(before: FocusResult | null, after: FocusResult | null, digits = 3): FocusReport {
  if (!before || !after) return { fields: [], worse: [] }
  const fields: string[] = []
  const worse: number[] = []
  after.per_field.forEach((a, k) => {
    const b = before.per_field[k]
    if (!b || a.rms_um === null || b.rms_um === null) return
    fields.push(`F${k + 1} ${+b.rms_um.toPrecision(digits)} → ${+a.rms_um.toPrecision(digits)}`)
    if (a.rms_um > 1.2 * b.rms_um && a.rms_um - b.rms_um > 0.5) worse.push(k)
  })
  return { fields, worse }
}
