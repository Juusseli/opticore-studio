import type { ConstraintResult, Operand, OperandType, OptimizationSpec } from './types'

/** Operands that are exact limits unless their role says otherwise (mirror of DEFAULT_CONSTRAINTS in the engine's
 * optimize/merit.py; a backend test compares the two lists). */
export const DEFAULT_CONSTRAINTS: OperandType[] = ['min_thickness', 'max_thickness', 'min_edge_thickness', 'max_total_track', 'max_distortion', 'max_lateral_color', 'min_relative_illumination', 'max_cra', 'efl', 'bfl', 'fnum', 'working_fnum', 'magnification', 'total_track']

/** Exact limits (the default) or one weighted merit function. */
export function exactMode(opt: Pick<OptimizationSpec, 'constraints'>): boolean {
  return (opt.constraints ?? 'exact') === 'exact'
}

/** The role an operand has in the optimiser: with weighted limits every operand is a goal. */
export function operandRole(o: Operand, opt: Pick<OptimizationSpec, 'constraints'>): 'objective' | 'constraint' {
  if (!exactMode(opt)) return 'objective'
  if (o.role === 'objective' || o.role === 'constraint') return o.role
  return DEFAULT_CONSTRAINTS.includes(o.type) ? 'constraint' : 'objective'
}

/** An operand the engine's merit function uses (merit.is_active): enabled, and a weight above 0 unless it is a limit
 * (by role or by type; a limit's weight is not used). The same in both constraint modes, so the active operands, in
 * order, number the engine's breakdowns, constraint rows, trade-off operands and tolerancing limits. */
export function isActiveOperand(o: Operand): boolean {
  return o.enabled && (o.weight > 0 || operandRole(o, { constraints: 'exact' }) === 'constraint')
}

/** The relaxed target of a limit and the merit change its price predicts, e.g. "6.12: −1.3 %" (null: no price). */
export function priceLabel(c: ConstraintResult): { target: number; percent: number; approximate: boolean } | null {
  if (!c.price || !c.active || c.fixed) return null
  return { target: c.price.relaxed_target, percent: c.price.change_percent, approximate: c.price.approximate }
}

/** Limits met by the design (n of m). */
export function limitsMet(rows: ConstraintResult[] | null | undefined): { met: number; total: number } | null {
  if (!rows || !rows.length) return null
  return { met: rows.filter((c) => c.met).length, total: rows.length }
}
