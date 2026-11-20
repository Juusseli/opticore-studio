// Browser-local persistence (IndexedDB): project library, autosave/recovery and imported glass catalogues.
import type { GlassCatalog, PhotoData, Project, StockCatalog } from './types'

const DB_NAME = 'opticore-studio'
const DB_VERSION = 3 // 2: glass catalogue store; 3: stock lens catalogues
const PROJECTS = 'projects'
const META = 'meta'
const CATALOGS = 'catalogs'
const STOCK = 'stock'

export interface StoredProject {
  id: string
  name: string
  savedAt: string
  project: Project
}

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') return reject(new Error('IndexedDB unavailable'))
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(PROJECTS)) db.createObjectStore(PROJECTS, { keyPath: 'id' })
      if (!db.objectStoreNames.contains(META)) db.createObjectStore(META)
      if (!db.objectStoreNames.contains(CATALOGS)) db.createObjectStore(CATALOGS, { keyPath: 'id' })
      if (!db.objectStoreNames.contains(STOCK)) db.createObjectStore(STOCK, { keyPath: 'id' })
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

async function tx<T>(store: string, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open()
  return new Promise<T>((resolve, reject) => {
    const t = db.transaction(store, mode)
    const r = fn(t.objectStore(store))
    r.onsuccess = () => resolve(r.result)
    r.onerror = () => reject(r.error)
    t.oncomplete = () => db.close()
  })
}

export const storage = {
  async listProjects(): Promise<StoredProject[]> {
    const all = await tx<StoredProject[]>(PROJECTS, 'readonly', (s) => s.getAll() as IDBRequest<StoredProject[]>)
    return all.sort((a, b) => b.savedAt.localeCompare(a.savedAt))
  },
  async getProject(id: string): Promise<StoredProject | undefined> {
    return tx<StoredProject | undefined>(PROJECTS, 'readonly', (s) => s.get(id) as IDBRequest<StoredProject | undefined>)
  },
  async putProject(p: Project): Promise<StoredProject> {
    const rec: StoredProject = { id: p.id, name: p.metadata.name, savedAt: new Date().toISOString(), project: p }
    await tx(PROJECTS, 'readwrite', (s) => s.put(rec))
    return rec
  },
  async deleteProject(id: string): Promise<void> {
    await tx(PROJECTS, 'readwrite', (s) => s.delete(id))
  },
  async setAutosave(p: Project, dirty: boolean): Promise<void> {
    await tx(META, 'readwrite', (s) => s.put({ project: p, dirty, at: new Date().toISOString() }, 'autosave'))
  },
  async getAutosave(): Promise<{ project: Project; dirty: boolean; at: string } | undefined> {
    return tx(META, 'readonly', (s) => s.get('autosave') as IDBRequest<{ project: Project; dirty: boolean; at: string } | undefined>)
  },
  async clearAutosave(): Promise<void> {
    await tx(META, 'readwrite', (s) => s.delete('autosave'))
  },
  async listCatalogs(): Promise<GlassCatalog[]> {
    const all = await tx<GlassCatalog[]>(CATALOGS, 'readonly', (s) => s.getAll() as IDBRequest<GlassCatalog[]>)
    return all.sort((a, b) => a.name.localeCompare(b.name))
  },
  async putCatalog(c: GlassCatalog): Promise<void> {
    await tx(CATALOGS, 'readwrite', (s) => s.put(c))
  },
  async deleteCatalog(id: string): Promise<void> {
    await tx(CATALOGS, 'readwrite', (s) => s.delete(id))
  },
  async listStockCatalogs(): Promise<StockCatalog[]> {
    const all = await tx<StockCatalog[]>(STOCK, 'readonly', (s) => s.getAll() as IDBRequest<StockCatalog[]>)
    return all.sort((a, b) => a.name.localeCompare(b.name))
  },
  async putStockCatalog(c: StockCatalog): Promise<void> {
    await tx(STOCK, 'readwrite', (s) => s.put(c))
  },
  async deleteStockCatalog(id: string): Promise<void> {
    await tx(STOCK, 'readwrite', (s) => s.delete(id))
  },
  /** the live image's photo: kept in this browser only, never in a project */
  async getPhoto(): Promise<{ photo: PhotoData; name: string } | undefined> {
    return tx(META, 'readonly', (s) => s.get('live-photo') as IDBRequest<{ photo: PhotoData; name: string } | undefined>)
  },
  async setPhoto(photo: PhotoData, name: string): Promise<void> {
    await tx(META, 'readwrite', (s) => s.put({ photo, name }, 'live-photo'))
  },
  async clearPhoto(): Promise<void> {
    await tx(META, 'readwrite', (s) => s.delete('live-photo'))
  },
}

// ------------------------------------------------------------------ per-viewer UI prefs
export function loadPref<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem('opticore.' + key)
    return v === null ? fallback : (JSON.parse(v) as T)
  } catch {
    return fallback
  }
}

export function savePref(key: string, value: unknown): void {
  try {
    localStorage.setItem('opticore.' + key, JSON.stringify(value))
  } catch {
    /* storage may be unavailable (private mode) */
  }
}

export function downloadText(filename: string, text: string, mime = 'application/json'): void {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Several files at once (an empty list when cancelled). */
export function pickFiles(accept: string): Promise<File[]> {
  return new Promise((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = accept
    input.multiple = true
    input.onchange = () => resolve(Array.from(input.files ?? []))
    input.oncancel = () => resolve([])
    input.click()
  })
}

export function pickFile(accept: string): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = accept
    input.onchange = () => resolve(input.files?.[0] ?? null)
    input.oncancel = () => resolve(null)
    input.click()
  })
}
