// Imported glass catalogues: name resolution, embedding in projects and glass-map neighbours.
// Pure functions (tested in glassCatalog.test.ts); the catalogues themselves live in IndexedDB (catalogStore).
import type { GlassCatalog, MaterialRecord, MaterialSummary, Project } from './types'

export interface CatalogGlass {
  record: MaterialRecord
  summary: MaterialSummary
  catalog: string
}

export interface CatalogIndex {
  /** glasses addressable by name (built-in names and earlier catalogues take precedence) */
  byName: Map<string, CatalogGlass>
  /** catalogue glasses hidden by a built-in or an earlier catalogue's glass of the same name */
  shadowed: { name: string; catalog: string; by: string }[]
}

const RESERVED = new Set(['', 'AIR', 'VACUUM', 'MIRROR'])

/** Catalogues are resolved in name order; built-in materials always win (reproducible results). */
export function buildCatalogIndex(catalogs: GlassCatalog[], builtinNames: Iterable<string>): CatalogIndex {
  const builtin = new Set([...builtinNames].map((n) => n.toUpperCase()))
  const byName = new Map<string, CatalogGlass>()
  const shadowed: CatalogIndex['shadowed'] = []
  for (const c of [...catalogs].sort((a, b) => a.name.localeCompare(b.name))) {
    const sums = new Map(c.summaries.map((s) => [s.name.toUpperCase(), s]))
    for (const r of c.records) {
      const name = r.name.toUpperCase()
      const s = sums.get(name)
      if (!s) continue
      if (builtin.has(name)) shadowed.push({ name, catalog: c.name, by: 'built-in' })
      else if (byName.has(name)) shadowed.push({ name, catalog: c.name, by: byName.get(name)!.catalog })
      else byName.set(name, { record: r, summary: s, catalog: c.name })
    }
  }
  return { byName, shadowed }
}

/** Every material name the project refers to (surfaces, configuration values, coating layers). */
export function usedMaterialNames(p: Project): Set<string> {
  const out = new Set<string>()
  for (const s of p.system.surfaces) out.add((s.material ?? '').toUpperCase())
  for (const op of p.system.multi_config?.operands ?? []) if (op.parameter === 'material') for (const v of op.values) if (typeof v === 'string') out.add(v.toUpperCase())
  for (const c of p.system.custom_coatings ?? []) for (const l of c.layers) if (l.material) out.add(l.material.toUpperCase())
  for (const r of RESERVED) out.delete(r)
  return out
}

/** Copies the definitions of catalogue glasses the project uses into `custom_materials`, so the project
 * file stays self-contained (it evaluates identically without the catalogue). Mutates `p`; returns the names added. */
export function embedCatalogGlasses(p: Project, index: CatalogIndex): string[] {
  const have = new Set(p.custom_materials.map((m) => m.name.toUpperCase()))
  const added: string[] = []
  for (const name of usedMaterialNames(p)) {
    if (have.has(name)) continue
    const g = index.byName.get(name)
    if (!g) continue
    p.custom_materials.push(structuredClone(g.record))
    have.add(name)
    added.push(name)
  }
  return added
}

/** Records the engine needs for these names in addition to the project's own materials (e.g. glass-substitution candidates). */
export function recordsFor(names: Iterable<string>, index: CatalogIndex, custom: MaterialRecord[]): MaterialRecord[] {
  const have = new Set(custom.map((m) => m.name.toUpperCase()))
  const out: MaterialRecord[] = []
  for (const n of names) {
    const k = n.toUpperCase()
    const g = index.byName.get(k)
    if (g && !have.has(k)) {
      out.push(g.record)
      have.add(k)
    }
  }
  return out
}

export interface GlassPoint {
  name: string
  nd: number | null
  vd: number | null
  status?: string
  catalog?: string
  /** false: the coefficients do not reproduce the catalogue nd/Vd */
  verified?: boolean
}

/** Glasses closest to (nd, vd) on the glass map. Distance uses the usual scaling of the map
 * (0.01 in nd counts like 1 in Vd · `vdWeight`·100). Obsolete glasses are skipped unless asked for;
 * flagged (unverified) glasses are always skipped. */
export function nearestGlasses(target: { nd: number; vd: number }, glasses: GlassPoint[], n: number, opts: { includeObsolete?: boolean; catalogs?: string[] | null; vdWeight?: number } = {}): string[] {
  const w = opts.vdWeight ?? 0.01 // 1 Abbe unit ~ 0.01 in nd
  const cats = opts.catalogs ? new Set(opts.catalogs) : null
  return glasses
    .filter((g) => g.nd !== null && g.vd !== null && Number.isFinite(g.nd) && Number.isFinite(g.vd))
    .filter((g) => g.verified !== false && (opts.includeObsolete || g.status !== 'obsolete'))
    .filter((g) => !cats || cats.has(g.catalog ?? 'built-in'))
    .map((g) => ({ name: g.name, d: Math.hypot(g.nd! - target.nd, (g.vd! - target.vd) * w) }))
    .sort((a, b) => a.d - b.d || a.name.localeCompare(b.name))
    .slice(0, n)
    .map((g) => g.name)
}
