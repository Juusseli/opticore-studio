// Stock lens catalogues: the engine's built-in generic library and the user's imported catalogues (vendor ZMX
// files or CSV), kept in this browser like glass catalogues (ADR-015). OptiCore ships no vendor data.
import { create } from 'zustand'
import { api } from '../lib/api'
import { newId } from '../lib/project'
import { storage } from '../lib/storage'
import type { MaterialRecord, StockCatalog, StockLens, StockLensInfo } from '../lib/types'
import { useCatalogStore } from './catalogStore'

export const GENERIC_ID = 'generic'

interface StockState {
  /** the engine's generic library (loaded on first use) */
  generic: StockLensInfo[] | null
  catalogs: StockCatalog[]
  loaded: boolean
  load: () => Promise<void>
  loadGeneric: () => Promise<StockLensInfo[]>
  /** vendor ZMX files (one lens each) into the catalogue of that name (created or extended) */
  importZmx: (files: { name: string; base64: string }[], name: string, vendor: string) => Promise<{ catalog: StockCatalog; added: number; failed: { filename: string; error: string }[] }>
  importCsv: (content: string, name: string) => Promise<{ catalog: StockCatalog; added: number; errors: string[] }>
  remove: (id: string) => Promise<void>
}

/** The record the engine accepts (without the paraxial data shown in the browser). */
export function toStockLens(l: StockLensInfo | StockLens): StockLens {
  return {
    part: l.part,
    vendor: l.vendor ?? '',
    catalog: l.catalog ?? '',
    kind: l.kind ?? 'other',
    radii: l.radii,
    thicknesses: l.thicknesses,
    materials: l.materials,
    diameter: l.diameter,
    clear_diameter: l.clear_diameter ?? null,
    focal_length: l.focal_length ?? null,
    price: l.price ?? null,
    currency: l.currency ?? '',
    source: l.source ?? '',
  }
}

/** Lenses and glass records of the chosen imported catalogues (the generic library is added by the engine). */
export function lensesFor(catalogIds: string[], catalogs: StockCatalog[]): { lenses: StockLens[]; custom: MaterialRecord[] } {
  const chosen = catalogs.filter((c) => catalogIds.includes(c.id))
  const custom = new Map<string, MaterialRecord>()
  for (const c of chosen) for (const r of c.custom_materials) custom.set(r.name.toUpperCase(), r)
  return { lenses: chosen.flatMap((c) => c.lenses.map(toStockLens)), custom: [...custom.values()] }
}

function merge(old: StockCatalog | undefined, name: string, vendor: string, source: 'zmx' | 'csv', lenses: StockLensInfo[], custom: MaterialRecord[], diagnostics: StockCatalog['diagnostics']): StockCatalog {
  const byPart = new Map<string, StockLensInfo>()
  for (const l of old?.lenses ?? []) byPart.set(l.part, l)
  for (const l of lenses) byPart.set(l.part, l)
  const mats = new Map<string, MaterialRecord>()
  for (const r of [...(old?.custom_materials ?? []), ...custom]) mats.set(r.name.toUpperCase(), r)
  return {
    id: old?.id ?? newId(),
    name,
    vendor: vendor || old?.vendor || '',
    imported_at: new Date().toISOString(),
    source,
    lenses: [...byPart.values()].sort((a, b) => a.part.localeCompare(b.part)),
    custom_materials: [...mats.values()],
    diagnostics: [...(old?.diagnostics ?? []), ...diagnostics].slice(-200),
  }
}

export const useStockStore = create<StockState>((set, get) => ({
  generic: null,
  catalogs: [],
  loaded: false,

  load: async () => {
    try {
      set({ catalogs: await storage.listStockCatalogs(), loaded: true })
    } catch {
      set({ loaded: true }) // storage unavailable (private mode): no imported catalogues
    }
  },

  loadGeneric: async () => {
    const have = get().generic
    if (have) return have
    const r = await api.stockGeneric()
    set({ generic: r.lenses })
    return r.lenses
  },

  importZmx: async (files, name, vendor) => {
    // glasses that are not built in may come from the user's glass catalogues
    const catalogMaterials = useCatalogStore.getState().catalogs.flatMap((c) => c.records)
    const r = await api.stockImportZmx({ files: files.map((f) => ({ filename: f.name, content_base64: f.base64 })), catalog: name, vendor, catalog_materials: catalogMaterials })
    const failed = r.files.filter((f) => !f.ok).map((f) => ({ filename: f.filename, error: f.error ?? '' }))
    const diags = [
      ...failed.map((f) => ({ file: f.filename, message: f.error })),
      ...r.files.flatMap((f) => (f.diagnostics ?? []).map((d) => ({ file: f.filename, message: d.message }))),
    ]
    const old = get().catalogs.find((c) => c.name === name)
    const cat = merge(old, name, vendor, 'zmx', r.lenses, r.custom_materials, diags)
    await storage.putStockCatalog(cat).catch(() => undefined)
    set({ catalogs: [...get().catalogs.filter((c) => c.id !== cat.id), cat].sort((a, b) => a.name.localeCompare(b.name)) })
    return { catalog: cat, added: r.lenses.length, failed }
  },

  importCsv: async (content, name) => {
    const custom = useCatalogStore.getState().catalogs.flatMap((c) => c.records)
    const r = await api.stockImportCsv({ content, catalog: name, custom_materials: custom })
    const errors = [...r.diagnostics.map((d) => d.message), ...r.missing_glasses.map((g) => `Unknown glass ${g}`)]
    const old = get().catalogs.find((c) => c.name === name)
    const used = new Set(r.lenses.flatMap((l) => l.materials.map((m) => m.toUpperCase())))
    const cat = merge(old, name, '', 'csv', r.lenses, custom.filter((m) => used.has(m.name.toUpperCase())), errors.map((message) => ({ message })))
    await storage.putStockCatalog(cat).catch(() => undefined)
    set({ catalogs: [...get().catalogs.filter((c) => c.id !== cat.id), cat].sort((a, b) => a.name.localeCompare(b.name)) })
    return { catalog: cat, added: r.lenses.length, errors }
  },

  remove: async (id) => {
    await storage.deleteStockCatalog(id).catch(() => undefined)
    set({ catalogs: get().catalogs.filter((c) => c.id !== id) })
  },
}))
