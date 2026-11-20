// Design space map: a background run of many optimised designs on the engine's process pool. The results
// stay in this session (they are not saved with the project); the specification is a view setting of the project.
import { create } from 'zustand'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import type { DesignCandidate, DesignMetricKey, DesignSpaceSnapshot, DesignSpaceSpec, MaterialRecord } from '../lib/types'
import { useEngineStore } from './engineStore'

export type FrontMode = 'default' | 'axes'

export interface DsJob {
  id: string
  state: DesignSpaceSnapshot['state']
  total: number
  done: number
  failed: number
  elapsed_s: number
  /** stock lens runs: the phase before the candidates and its progress, and the engine's notes */
  phase?: DesignSpaceSnapshot['phase']
  phase_done?: number
  phase_total?: number
  notes?: string[]
}

interface DsState {
  job: DsJob | null
  /** finished (and failed) candidates by plan index */
  candidates: Record<number, DesignCandidate>
  /** plan indices in the order they finished */
  order: number[]
  pareto: number[]
  objectives: DesignMetricKey[]
  front: FrontMode
  x: DesignMetricKey
  y: DesignMetricKey
  selected: number | null
  error: string | null
  start: (spec: DesignSpaceSpec, custom: MaterialRecord[]) => Promise<void>
  /** any run on the engine's design-space jobs (stock lens build or match): `launch` starts it and returns its id */
  startWith: (launch: () => Promise<{ job_id: string; total: number }>, what: string) => Promise<void>
  cancel: () => Promise<void>
  /** another project was opened: cancel the run and forget its candidates (they would be opened into that project) */
  reset: () => void
  setAxes: (p: { x?: DesignMetricKey; y?: DesignMetricKey }) => void
  setFront: (m: FrontMode) => void
  select: (i: number | null) => void
}

let pollToken = 0

/** The objectives of the Pareto front: the engine's default (performance, length, cost) or the two shown axes. */
function frontObjectives(s: Pick<DsState, 'front' | 'x' | 'y'>): DesignMetricKey[] | undefined {
  return s.front === 'axes' ? [s.x, s.y] : undefined
}

export const useDesignSpaceStore = create<DsState>((set, get) => {
  const apply = (s: DesignSpaceSnapshot) => {
    const candidates = { ...get().candidates }
    const order = [...get().order]
    for (const c of s.candidates) {
      if (!(c.index in candidates)) order.push(c.index)
      candidates[c.index] = c
    }
    set({
      job: { id: s.id, state: s.state, total: s.total, done: s.done, failed: s.failed, elapsed_s: s.elapsed_s, phase: s.phase ?? null, phase_done: s.phase_done ?? 0, phase_total: s.phase_total ?? 0, notes: s.notes ?? [] },
      candidates,
      order,
      pareto: s.pareto,
      objectives: s.objectives,
      error: s.error,
    })
  }

  /** the front again (after a change of objectives, or once more after the run) */
  const refreshFront = async () => {
    const job = get().job
    if (!job) return
    try {
      apply(await api.designSpaceStatus(job.id, get().order.length, frontObjectives(get())))
    } catch {
      // the engine forgot the job (restart): the shown front stays
    }
  }

  return {
    job: null,
    candidates: {},
    order: [],
    pareto: [],
    objectives: [],
    front: 'default',
    x: 'length_mm',
    y: 'rms_spot_um',
    selected: null,
    error: null,

    start: (spec, custom) => get().startWith(() => api.designSpaceStart({ spec, custom_materials: custom }), 'Design space'),

    startWith: async (launch, what) => {
      const log = useEngineStore.getState().log_
      const old = get().job
      if (old && old.state === 'running') void api.designSpaceCancel(old.id).catch(() => undefined)
      const token = ++pollToken
      set({ job: null, candidates: {}, order: [], pareto: [], objectives: [], selected: null, error: null })
      try {
        const { job_id, total } = await launch()
        if (token !== pollToken) {
          // a newer run started meanwhile: this one would only occupy the engine
          void api.designSpaceCancel(job_id).catch(() => undefined)
          return
        }
        set({ job: { id: job_id, state: 'running', total, done: 0, failed: 0, elapsed_s: 0 } })
        const poll = async () => {
          if (token !== pollToken) return
          let s: DesignSpaceSnapshot
          try {
            s = await api.designSpaceStatus(job_id, get().order.length, frontObjectives(get()))
          } catch (e) {
            if (token === pollToken) set({ error: (e as Error).message })
            window.setTimeout(poll, 1500)
            return
          }
          if (token !== pollToken) return
          apply(s)
          if (s.state === 'running') {
            window.setTimeout(poll, 700)
            return
          }
          const ok = Object.values(get().candidates).filter((c) => c.status === 'finished')
          if (s.state === 'failed') log('error', `${what} failed: ${s.error}`)
          else
            log(
              'success',
              `${what} ${s.state}: ${ok.length} designs (${ok.filter((c) => c.feasible).length} meet the specification, ${s.pareto.length} on the front) in ${fmt(s.elapsed_s, 3)} s`,
            )
        }
        window.setTimeout(poll, 300)
      } catch (e) {
        if (token === pollToken) set({ error: (e as Error).message })
      }
    },

    cancel: async () => {
      const job = get().job
      if (job && job.state === 'running') await api.designSpaceCancel(job.id).catch(() => undefined)
    },

    reset: () => {
      const job = get().job
      if (job && job.state === 'running') void api.designSpaceCancel(job.id).catch(() => undefined)
      pollToken++
      set({ job: null, candidates: {}, order: [], pareto: [], objectives: [], selected: null, error: null })
    },

    setAxes: (p) => {
      set(p)
      if (get().front === 'axes' && get().job?.state !== 'running') void refreshFront()
    },

    setFront: (m) => {
      set({ front: m })
      if (get().job?.state !== 'running') void refreshFront()
    },

    select: (i) => set({ selected: i }),
  }
})

export const isDsRunning = (s: DsState) => s.job?.state === 'running'
