import { create } from 'zustand'

export type MeasureMode = 'off' | 'distance' | 'clearance'
export type V3 = [number, number, number]

export interface MeasurePick {
  asset_id: string
  part_id: string | null
  point: V3 // global, picked on the display mesh
  label: string
}

export interface Measurement {
  id: number
  kind: 'distance' | 'clearance'
  a: V3
  b: V3
  distance_mm: number
  delta_mm: V3
  exact: boolean
  labels: [string, string]
  note?: string
  pending?: boolean
}

/** 3D measuring tool state (session only, not saved with the project). */
interface MeasureState {
  mode: MeasureMode
  picks: MeasurePick[]
  results: Measurement[]
  /** selected part for highlighting: asset id + node id (null = whole asset) */
  selected: { asset_id: string; part_id: string | null } | null
  setMode: (m: MeasureMode) => void
  addPick: (p: MeasurePick) => MeasurePick[]
  clearPicks: () => void
  addResult: (r: Omit<Measurement, 'id'>) => number
  updateResult: (id: number, patch: Partial<Measurement>) => void
  removeResult: (id: number) => void
  clearAll: () => void
  select: (s: { asset_id: string; part_id: string | null } | null) => void
}

let nextId = 1

export const useMeasureStore = create<MeasureState>((set, get) => ({
  mode: 'off',
  picks: [],
  results: [],
  selected: null,
  setMode: (mode) => set({ mode, picks: [] }),
  addPick: (p) => {
    const picks = [...get().picks, p]
    set({ picks })
    return picks
  },
  clearPicks: () => set({ picks: [] }),
  addResult: (r) => {
    const id = nextId++
    set({ results: [...get().results, { ...r, id }] })
    return id
  },
  updateResult: (id, patch) => set({ results: get().results.map((r) => (r.id === id ? { ...r, ...patch } : r)) }),
  removeResult: (id) => set({ results: get().results.filter((r) => r.id !== id) }),
  clearAll: () => set({ results: [], picks: [] }),
  select: (selected) => set({ selected }),
}))
