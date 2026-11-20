// Imported glass catalogues (AGF files or refractiveindex.info downloads), stored in the browser and shared by all projects.
import { useMemo } from 'react'
import { create } from 'zustand'
import { api } from '../lib/api'
import { buildCatalogIndex, type CatalogIndex, recordsFor } from '../lib/glassCatalog'
import { storage } from '../lib/storage'
import type { GlassCatalog, MaterialSummary } from '../lib/types'
import { registerExtraMaterials, useEngineStore } from './engineStore'
import { registerCatalogIndex } from './projectStore'

interface CatalogState {
  catalogs: GlassCatalog[]
  loaded: boolean
  index: CatalogIndex
  load: () => Promise<void>
  /** parses the file in the engine and stores it; a catalogue with the same name is replaced */
  importFile: (filename: string, content_base64: string) => Promise<GlassCatalog>
  /** converts a maker's downloaded refractiveindex.info pages in the engine and stores them (same rules) */
  importRii: (catalog: string, files: { path: string; content: string }[], note: string[]) => Promise<GlassCatalog>
  remove: (id: string) => Promise<void>
}

const EMPTY: CatalogIndex = { byName: new Map(), shadowed: [] }

function reindex(catalogs: GlassCatalog[]): CatalogIndex {
  return buildCatalogIndex(
    catalogs,
    useEngineStore.getState().materials.map((m) => m.name),
  )
}

type Parsed = Awaited<ReturnType<typeof api.importAgf>>

export const useCatalogStore = create<CatalogState>((set, get) => {
  const keep = async (r: Parsed, filename: string, note: string[]): Promise<GlassCatalog> => {
    const cat: GlassCatalog = {
      id: r.catalog,
      name: r.catalog,
      filename,
      imported_at: new Date().toISOString(),
      comments: [...r.comments, ...note],
      records: r.records,
      summaries: r.summaries.map((s) => ({ ...s, builtin: false })),
      diagnostics: r.diagnostics,
    }
    await storage.putCatalog(cat)
    const catalogs = [...get().catalogs.filter((c) => c.id !== cat.id), cat]
    set({ catalogs, index: reindex(catalogs) })
    return cat
  }
  return {
    catalogs: [],
    loaded: false,
    index: EMPTY,
    load: async () => {
      try {
        const catalogs = await storage.listCatalogs()
        set({ catalogs, loaded: true, index: reindex(catalogs) })
      } catch {
        set({ loaded: true }) // storage unavailable (private mode): no catalogues
      }
    },
    importFile: async (filename, content_base64) => {
      const r = await api.importAgf(filename, content_base64)
      return keep(r, filename, [])
    },
    importRii: async (catalog, files, note) => {
      const r = await api.importRii(catalog, files)
      return keep(r, r.filename, note)
    },
    remove: async (id) => {
      await storage.deleteCatalog(id)
      const catalogs = get().catalogs.filter((c) => c.id !== id)
      set({ catalogs, index: reindex(catalogs) })
    },
  }
})

registerCatalogIndex(() => useCatalogStore.getState().index)
registerExtraMaterials((system, custom) => {
  const index = useCatalogStore.getState().index
  if (!index.byName.size) return []
  return recordsFor(
    system.surfaces.map((s) => s.material),
    index,
    custom,
  )
})

// the built-in names decide which catalogue glasses are shadowed: re-index when they arrive
useEngineStore.subscribe((s, prev) => {
  if (s.materials !== prev.materials) useCatalogStore.setState((c) => ({ index: reindex(c.catalogs) }))
})

/** Built-in materials followed by the addressable catalogue glasses (for pickers and lookups). */
export function useAllMaterials(): MaterialSummary[] {
  const builtin = useEngineStore((s) => s.materials)
  const index = useCatalogStore((s) => s.index)
  return useMemo(() => [...builtin, ...[...index.byName.values()].map((g) => g.summary)], [builtin, index])
}
