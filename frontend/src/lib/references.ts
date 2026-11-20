// Keeping a project's references valid when what they point at is removed, renumbered or replaced. Surfaces are
// referenced by id, fields, wavelengths and configurations by index: a removal must shift the indices behind it
// and drop (or disable) what pointed at the removed item, never leave it pointing at a neighbour.
import type { Project } from './types'

type Settings = Record<string, unknown>

/** analysis_settings entries that are plain objects (one per analysis kind), saved snapshots excluded. */
function settingsObjects(p: Project): Settings[] {
  return Object.entries(p.analysis_settings ?? {})
    .filter(([k, v]) => k !== 'saved' && v !== null && typeof v === 'object' && !Array.isArray(v))
    .map(([, v]) => v as Settings)
}

/** After field `i` was removed from p.system.fields. */
export function afterFieldRemoved(p: Project, i: number): void {
  for (const o of p.optimization.operands) {
    if (o.field === null) continue
    if (o.field === i) {
      o.field = null
      o.enabled = false // its target no longer exists: disable rather than retarget silently
    } else if (o.field > i) o.field -= 1
  }
  for (const s of p.sources ?? []) {
    if (s.field === i) {
      s.field = 0
      if (s.kind === 'system_field') s.enabled = false
    } else if (s.field > i) s.field -= 1
  }
  for (const s of settingsObjects(p)) {
    if (typeof s.field !== 'number') continue
    if (s.field === i) s.field = 0
    else if (s.field > i) s.field -= 1
  }
  // a removed field's vignetting factors go with it; later fields move up
  const mc = p.system.multi_config
  if (mc) {
    mc.operands = mc.operands.filter((o) => (o.field ?? null) !== i)
    for (const o of mc.operands) if (o.field !== null && o.field !== undefined && o.field > i) o.field -= 1
  }
}

/** After wavelength `i` was removed (p.system.primary_wavelength already updated). */
export function afterWavelengthRemoved(p: Project, i: number): void {
  for (const o of p.optimization.operands) {
    if (o.wavelength === null) continue
    if (o.wavelength === i) {
      o.wavelength = null
      o.enabled = false
    } else if (o.wavelength > i) o.wavelength -= 1
  }
  for (const s of settingsObjects(p)) {
    if (typeof s.wavelength !== 'number') continue
    if (s.wavelength === i) s.wavelength = p.system.primary_wavelength
    else if (s.wavelength > i) s.wavelength -= 1
  }
}

/** Field, wavelength and configuration indices beyond the system's current lists (a wholesale replacement). */
export function clampIndices(p: Project): void {
  const nf = p.system.fields.length
  const nw = p.system.wavelengths.length
  const nc = p.system.multi_config ? p.system.multi_config.names.length : 0
  for (const o of p.optimization.operands) {
    if (o.field !== null && o.field >= nf) o.field = null
    if (o.wavelength !== null && o.wavelength >= nw) o.wavelength = null
    if (o.configuration !== null && o.configuration !== undefined && o.configuration >= nc) o.configuration = null
  }
  p.optimization.variables = p.optimization.variables.filter((v) => v.configuration === null || v.configuration === undefined || v.configuration < nc)
  for (const s of p.sources ?? []) {
    if (s.field >= nf) {
      s.field = 0
      if (s.kind === 'system_field') s.enabled = false
    }
  }
  for (const s of settingsObjects(p)) {
    if (typeof s.field === 'number' && s.field >= nf) s.field = 0
    if (typeof s.wavelength === 'number' && s.wavelength >= nw) s.wavelength = p.system.primary_wavelength
  }
  if (p.system.multi_config) p.system.multi_config.operands = p.system.multi_config.operands.filter((o) => o.field === null || o.field === undefined || o.field < nf)
  const sw = p.analysis_settings?.sweep as { parameters?: { configuration?: number | null }[] } | undefined
  for (const q of sw?.parameters ?? []) if (q.configuration !== null && q.configuration !== undefined && q.configuration >= nc) q.configuration = null
}

/** After the whole system was replaced (a revision restored, a candidate applied): references to surfaces the new
 * system lacks are dropped (optimisation, tolerancing) or released (a source or detector anchored to a missing
 * surface keeps its coordinates in the global frame), and indices are clamped. Returns what was changed. */
export function pruneReferences(p: Project): string[] {
  const ids = new Set(p.system.surfaces.map((s) => s.id))
  const notes: string[] = []
  const nv = p.optimization.variables.length
  p.optimization.variables = p.optimization.variables.filter((v) => ids.has(v.surface_id))
  const no = p.optimization.operands.length
  p.optimization.operands = p.optimization.operands.filter((o) => !o.surface_id || ids.has(o.surface_id))
  const nt = p.tolerancing.tolerances.length + p.tolerancing.compensators.length
  p.tolerancing.tolerances = p.tolerancing.tolerances.filter((x) => ids.has(x.surface_id) && !(x.surface_id_end && !ids.has(x.surface_id_end)))
  p.tolerancing.compensators = p.tolerancing.compensators.filter((c) => ids.has(c.surface_id))
  const dropped = nv - p.optimization.variables.length + (no - p.optimization.operands.length) + (nt - p.tolerancing.tolerances.length - p.tolerancing.compensators.length)
  if (dropped) notes.push(`${dropped} optimisation or tolerance entries referred to surfaces this design does not have and were removed`)
  for (const item of [...(p.sources ?? []), ...(p.detectors ?? [])]) {
    if (item.placement.anchor && !ids.has(item.placement.anchor)) {
      item.placement.anchor = null
      notes.push(`"${item.name}" was anchored to a surface this design does not have: its position is now in the global frame`)
    }
  }
  const ns = p.analysis_settings?.nonseq as { imp_target?: string } | undefined
  if (ns?.imp_target?.startsWith('sid:') && !ids.has(ns.imp_target.slice(4))) ns.imp_target = 'none'
  clampIndices(p)
  return notes
}

const same = (a: string | null | undefined, b: string) => !!a && a.trim().toUpperCase() === b.trim().toUpperCase()

/** Where a coating is used: surfaces (by index) and CAD bodies (model names). */
export function coatingUsers(p: Project, name: string): { surfaces: number[]; cad: string[] } {
  const surfaces = p.system.surfaces.map((s, i) => (same(s.coating, name) ? i : -1)).filter((i) => i >= 0)
  const cad = p.cad_assets.filter((a) => same(a.optical?.coating, name) || Object.values(a.part_roles ?? {}).some((r) => same(r.coating, name))).map((a) => a.name)
  return { surfaces, cad }
}

/** Rename a coating everywhere it is referenced (surfaces, CAD bodies and their parts, the coating designer's
 * source); returns the number of references changed. */
export function renameCoating(p: Project, from: string, to: string): number {
  let n = 0
  const holders: { coating?: string }[] = [...p.system.surfaces]
  for (const a of p.cad_assets) {
    if (a.optical) holders.push(a.optical)
    holders.push(...Object.values(a.part_roles ?? {}))
  }
  const cd = p.analysis_settings?.coating_design as { source_coating?: string } | undefined
  for (const h of holders) {
    if (same(h.coating, from)) {
      h.coating = to
      n++
    }
  }
  if (cd && same(cd.source_coating, from)) {
    cd.source_coating = to
    n++
  }
  return n
}

/** Where a custom material is used: surfaces (by index), configuration values, CAD bodies and coating layers. */
export function materialUsers(p: Project, name: string): string[] {
  const out: string[] = []
  p.system.surfaces.forEach((s, i) => same(s.material, name) && out.push(`surface ${i}`))
  for (const op of p.system.multi_config?.operands ?? []) if (op.parameter === 'material' && op.values.some((v) => typeof v === 'string' && same(v, name))) out.push('configuration editor')
  for (const a of p.cad_assets) if (same(a.optical?.material, name) || Object.values(a.part_roles ?? {}).some((r) => same(r.material, name))) out.push(`CAD model ${a.name}`)
  for (const c of p.system.custom_coatings ?? []) if (c.layers.some((L) => same(L.material, name))) out.push(`coating ${c.name}`)
  return out
}

/** After a surface moved: an element tolerance whose last surface now comes before its first is turned round. */
export function afterSurfaceMoved(p: Project): void {
  const pos = new Map(p.system.surfaces.map((s, i) => [s.id, i]))
  for (const t of p.tolerancing.tolerances) {
    if (!t.surface_id_end) continue
    const a = pos.get(t.surface_id)
    const b = pos.get(t.surface_id_end)
    if (a !== undefined && b !== undefined && b < a) [t.surface_id, t.surface_id_end] = [t.surface_id_end, t.surface_id]
  }
}
