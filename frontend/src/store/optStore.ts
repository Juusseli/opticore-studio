import { create } from 'zustand'
import { recordsFor } from '../lib/glassCatalog'
import { useCatalogStore } from './catalogStore'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import { applyMaterials, applyVariableValues, nsBody } from '../lib/project'
import type { DesignComparison, JobSnapshot, MaterialRecord, OpticalSystem, OptimizationResult, OptimizationSpec } from '../lib/types'
import { useEngineStore } from './engineStore'
import { useProjectStore } from './projectStore'

interface OptState {
  job: JobSnapshot | null
  result: OptimizationResult | null
  base: OpticalSystem | null
  /** the project the run belongs to: its result is never shown in or applied to another one */
  projectId: string | null
  /** the set-up and the materials of the run (a trade-off curve repeats it) */
  spec: OptimizationSpec | null
  custom: MaterialRecord[]
  /** before/after numbers of the image and the system, and what got worse (engine /optimize/compare) */
  compare: DesignComparison | null
  compareError: string | null
  error: string | null
  /** while a result waits to be applied: the views show it (a preview) or the project's design */
  showing: 'result' | 'original'
  start: () => Promise<void>
  show: (which: 'result' | 'original') => void
  pause: (p: boolean) => Promise<void>
  cancel: () => Promise<void>
  discard: () => void
  /** show another result of the same run (a trade-off curve's point) in place of the result */
  adopt: (r: OptimizationResult) => void
  /** another project was opened: stop following the run (cancel it) and drop its result and preview */
  abandon: () => void
}

let timer: number | null = null
let pollToken = 0
let lastPreview = 0
/** least time between two live previews of the best design while a run lasts */
export const PREVIEW_MS = 1500

export const useOptStore = create<OptState>((set, get) => ({
  job: null,
  result: null,
  base: null,
  projectId: null,
  spec: null,
  custom: [],
  compare: null,
  compareError: null,
  error: null,
  showing: 'result',

  start: async () => {
    const { project } = useProjectStore.getState()
    const eng = useEngineStore.getState()
    const opt = project.optimization
    const vars = opt.variables.filter((v) => v.enabled)
    const cvars = vars.filter((v) => v.parameter !== 'material') // order of best_values
    const sys0 = JSON.parse(JSON.stringify(project.system)) as OpticalSystem
    // glass-substitution candidates from imported catalogues travel with the request (the project keeps
    // only the glasses it uses; the chosen one is embedded when the result is applied)
    const candNames = vars.filter((v) => v.parameter === 'material').flatMap((v) => v.candidates ?? [])
    const custom = [...project.custom_materials, ...recordsFor(candNames, useCatalogStore.getState().index, project.custom_materials)]
    set({ error: null, result: null, compare: null, compareError: null, base: sys0, job: null, spec: JSON.parse(JSON.stringify(opt)) as OptimizationSpec, custom, projectId: project.id })
    try {
      const { job_id } = await api.optimizeStart({ system: sys0, custom_materials: custom, ...nsBody(project), optimization: opt })
      eng.log_('info', `Optimization started (${opt.algorithm}, ${vars.length} variables, ${opt.operands.filter((o) => o.enabled).length} operands)`)
      // visible immediately so Pause/Stop work before the first poll returns
      set({ job: { id: job_id, state: 'queued', phase: 'starting', evaluations: 0, initial_merit: null, current_merit: null, best_merit: null, best_values: null, history: [], elapsed_s: 0, error: null, result: null } })
      const token = ++pollToken
      const poll = async () => {
        if (token !== pollToken) return // a newer run superseded this one
        let s: JobSnapshot
        try {
          s = await api.optimizeStatus(job_id)
        } catch (e) {
          if (token === pollToken) set({ error: (e as Error).message })
          timer = window.setTimeout(poll, 1000)
          return
        }
        if (token !== pollToken) return
        if (useProjectStore.getState().project.id !== project.id) {
          get().abandon() // the run's project is no longer open (openProject abandons it too)
          return
        }
        set({ job: s })
        const done = s.state === 'finished' || s.state === 'cancelled' || s.state === 'failed'
        if (!done) {
          // the views follow the best design at most every PREVIEW_MS: each preview makes them recompute in the engine
          const now = Date.now()
          if (s.best_values && now - lastPreview >= PREVIEW_MS) {
            lastPreview = now
            useEngineStore.getState().setPreview(applyMaterials(applyVariableValues(sys0, cvars, s.best_values), s.best_materials))
          }
          timer = window.setTimeout(poll, 250) // next poll only after this one completed
          return
        }
        timer = null
        // the finished result stays on screen (a preview, not applied) until it is applied or discarded
        useEngineStore.getState().setPreview(s.result ? s.result.system : null)
        if (s.result) {
          set({ result: s.result, showing: 'result' })
          useEngineStore.getState().log_('success', `Optimization ${s.result.status}: MF ${fmt(s.result.initial_merit, 6)} → ${fmt(s.result.final_merit, 6)} (${s.result.evaluations} evaluations, ${s.result.elapsed_s.toFixed(1)} s)`)
          for (const n of s.result.notes ?? []) useEngineStore.getState().log_('warning', n)
          api
            .optimizeCompare({ before: sys0, after: s.result.system, custom_materials: custom })
            .then((compare) => token === pollToken && set({ compare }))
            .catch((e) => token === pollToken && set({ compareError: (e as Error).message }))
        }
        if (s.state === 'failed') {
          set({ error: s.error })
          useEngineStore.getState().log_('error', `Optimization failed: ${s.error}`)
        }
      }
      if (timer) window.clearTimeout(timer)
      timer = window.setTimeout(poll, 150)
    } catch (e) {
      set({ error: (e as Error).message })
    }
  },

  pause: async (p) => {
    const j = get().job
    if (j) await api.optimizePause(j.id, p)
  },
  cancel: async () => {
    const j = get().job
    if (j) await api.optimizeCancel(j.id)
  },
  show: (which) => {
    const r = get().result
    set({ showing: which })
    useEngineStore.getState().setPreview(which === 'result' && r ? r.system : null)
  },
  discard: () => {
    set({ result: null, job: null, compare: null, compareError: null, error: null, showing: 'result' })
    useEngineStore.getState().setPreview(null)
  },
  abandon: () => {
    const j = get().job
    if (j && isRunning(get())) void api.optimizeCancel(j.id).catch(() => undefined)
    pollToken++
    if (timer) window.clearTimeout(timer)
    timer = null
    set({ result: null, job: null, compare: null, compareError: null, error: null, showing: 'result', base: null, projectId: null, spec: null, custom: [] })
    useEngineStore.getState().setPreview(null)
  },
  adopt: (r) => {
    const { base, custom } = get()
    if (!base || isRunning(get())) return
    const token = ++pollToken
    // the run's progress strip and history belong to the run, not to this result
    set({ result: r, job: null, compare: null, compareError: null, showing: 'result' })
    useEngineStore.getState().setPreview(r.system)
    api
      .optimizeCompare({ before: base, after: r.system, custom_materials: custom })
      .then((compare) => token === pollToken && set({ compare }))
      .catch((e) => token === pollToken && set({ compareError: (e as Error).message }))
  },
}))

// an edit of the design while a result waits: show the edited design (the result can still be applied to it)
useProjectStore.subscribe((s, prev) => {
  if (s.project.system === prev.project.system) return
  const o = useOptStore.getState()
  if (o.result && !isRunning(o) && o.showing === 'result') {
    useOptStore.setState({ showing: 'original' })
    useEngineStore.getState().setPreview(null)
  }
})

export const isRunning = (s: OptState) => !!s.job && (s.job.state === 'running' || s.job.state === 'paused' || s.job.state === 'queued')
