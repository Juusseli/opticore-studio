// The System card: setup checklist (status of each step from the engine's evaluation) and the optional
// spec table (target vs current). Only comparisons and grouping happen here; every number comes from the engine.
import type { Diagnostic, Evaluation, FocusResult, OptimizationSpec, Paraxial, SavedOptimization } from './types'
import { isActiveOperand } from './constraints'

export type CheckId = 'aperture' | 'fields' | 'wavelengths' | 'environment' | 'surfaces' | 'focus' | 'merit' | 'optimised'
export type CheckStatus = 'ok' | 'warn' | 'error' | 'none'

export interface CheckItem {
  id: CheckId
  status: CheckStatus
  /** i18n key of the detail text and its values */
  detail: string
  vars?: Record<string, string | number>
  /** diagnostics behind a warn/error status */
  diagnostics?: Diagnostic[]
}

/** Which checklist item an engine diagnostic belongs to (everything else is "Surfaces and materials"). */
export const DIAGNOSTIC_GROUP: Record<string, CheckId> = {
  ZERO_APERTURE: 'aperture',
  TELECENTRIC_EP: 'aperture',
  TELECENTRIC_STOP: 'aperture',
  CB_BEFORE_STOP: 'aperture',
  PARAXIAL_AIMING: 'aperture',
  RAY_FAILED: 'fields',
  FIELD_AFOCAL: 'fields',
  FIELD_SCALE: 'fields',
  FIELD_UNREACHABLE: 'fields',
  WAVELENGTH_EXTRAPOLATED: 'wavelengths',
  TRANSMITTANCE_EXTRAPOLATED: 'wavelengths',
  COATING_RANGE: 'wavelengths',
  THERMAL_NO_CTE: 'environment',
  THERMAL_NO_DNDT: 'environment',
  THERMAL_RANGE: 'environment',
  MOUNT_COLLISION: 'environment',
  MOUNT_OVERCONSTRAINED: 'environment',
  MOUNT_UNSUPPORTED: 'environment',
}

export const diagnosticGroup = (code: string): CheckId => DIAGNOSTIC_GROUP[code] ?? 'surfaces'

export interface ChecklistInput {
  evaluation: Evaluation | null
  /** message of a failed evaluation (the system cannot be traced) */
  evalError: string | null
  /** diagnostics of a failed evaluation */
  errorDiagnostics?: Diagnostic[]
  aperture: { type: string; value: number }
  fields: number
  wavelengths: number[] // µm
  surfaces: number
  focus: FocusResult | null
  optimization: OptimizationSpec
  savedOptimizations: SavedOptimization[]
  /** current merit function value, when known */
  merit: number | null
  /** the environment model, when it is on (temperature °C, pressure atm in effect) */
  environment?: { temperature: number; pressure: number } | null
  /** glass mass of the lens elements (g) and its mass-weighted relative cost, where known (elements.py) */
  glass?: { mass: number | null; cost: number | null } | null
}

const levelOf = (ds: Diagnostic[]): CheckStatus => (ds.some((d) => d.level === 'error') ? 'error' : ds.some((d) => d.level === 'warning') ? 'warn' : 'ok')

export function systemChecklist(i: ChecklistInput): CheckItem[] {
  const all = i.evaluation ? i.evaluation.diagnostics : (i.errorDiagnostics ?? [])
  const issues = all.filter((d) => d.level !== 'info')
  const of = (id: CheckId) => issues.filter((d) => diagnosticGroup(d.code) === id)
  const traced = !!i.evaluation
  const groupItem = (id: CheckId, okDetail: string, vars?: Record<string, string | number>): CheckItem => {
    const ds = of(id)
    if (!traced && !ds.length) return { id, status: 'none', detail: okDetail, vars }
    return { id, status: ds.length ? levelOf(ds) : 'ok', detail: ds.length ? 'chk.d.issues' : okDetail, vars: ds.length ? { n: ds.length } : vars, diagnostics: ds }
  }
  const items: CheckItem[] = []
  items.push(groupItem('aperture', `chk.ap.${i.aperture.type}`, { v: i.aperture.value }))
  items.push(groupItem('fields', 'chk.d.count', { n: i.fields }))
  const nm = i.wavelengths.map((w) => Math.round(w * 1000))
  items.push(groupItem('wavelengths', nm.length > 1 ? 'chk.d.wlRange' : 'chk.d.wlOne', { a: Math.min(...nm), b: Math.max(...nm), n: nm.length }))
  // only when the environment model is on: it changes every result
  if (i.environment) items.push(groupItem('environment', 'chk.d.env', { t: i.environment.temperature, p: i.environment.pressure }))
  const surf = of('surfaces')
  if (i.evalError && !traced) items.push({ id: 'surfaces', status: 'error', detail: 'chk.d.untraceable', diagnostics: surf })
  else if (i.glass?.mass) items.push({ ...groupItem('surfaces', i.glass.cost ? 'chk.d.surfacesCost' : 'chk.d.surfacesMass', { n: i.surfaces, g: i.glass.mass, c: i.glass.cost ?? 0 }) })
  else items.push({ ...groupItem('surfaces', 'chk.d.surfaces', { n: i.surfaces }) })
  // focus: the engine says whether the image surface is at the best RMS focus
  if (!i.focus || i.focus.at_best_focus === null || i.focus.best_defocus_mm === null) items.push({ id: 'focus', status: 'none', detail: 'chk.d.unknown' })
  else items.push({ id: 'focus', status: i.focus.at_best_focus ? 'ok' : 'warn', detail: i.focus.at_best_focus ? 'chk.d.atFocus' : 'chk.d.defocus', vars: { d: i.focus.best_defocus_mm } })
  const vars = i.optimization.variables.filter((v) => v.enabled).length
  const ops = i.optimization.operands.filter(isActiveOperand).length
  items.push({ id: 'merit', status: vars && ops ? 'ok' : vars || ops ? 'warn' : 'none', detail: 'chk.d.merit', vars: { v: vars, o: ops } })
  // optimised: an applied run whose result still holds (the merit has not grown since)
  const applied = i.savedOptimizations.filter((r) => r.applied)
  if (!applied.length) items.push({ id: 'optimised', status: 'none', detail: i.savedOptimizations.length ? 'chk.d.notApplied' : 'chk.d.notYet' })
  else {
    const best = Math.min(...applied.map((r) => r.final_merit))
    const changed = i.merit !== null && i.merit > best * 1.01 + 1e-12
    items.push({ id: 'optimised', status: changed ? 'warn' : 'ok', detail: changed ? 'chk.d.changed' : 'chk.d.optimised', vars: { mf: best } })
  }
  return items
}

// ------------------------------------------------------------------ specifications
export type SpecId = 'efl' | 'fnum' | 'rms' | 'track'

/** Targets stored in `analysis_settings.specs`: a value with a ± tolerance, or an upper limit. */
export interface Specs {
  efl?: { target: number; tol: number }
  fnum?: { target: number; tol: number }
  rms?: { max: number }
  track?: { max: number }
}

export const SPEC_IDS: SpecId[] = ['efl', 'fnum', 'rms', 'track']

/** Current values of the specified quantities, from the engine (paraxial data and the focus analysis). */
export function specValues(pd: Paraxial | undefined, focus: FocusResult | null): Record<SpecId, number | null> {
  return {
    efl: pd?.efl ?? null,
    fnum: pd?.image_space_fnum ?? null,
    rms: focus?.max_field_rms_um ?? null,
    track: pd?.total_track ?? null,
  }
}

/** Pass/fail of one spec: null when there is no target or no current value. */
export function specPass(id: SpecId, specs: Specs, value: number | null): boolean | null {
  if (value === null || !Number.isFinite(value)) return null
  if (id === 'efl' || id === 'fnum') {
    const s = specs[id]
    return s ? Math.abs(value - s.target) <= Math.abs(s.tol) : null
  }
  const s = specs[id]
  return s ? value <= s.max : null
}
