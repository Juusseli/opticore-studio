import { create } from 'zustand'
import { api } from '../lib/api'
import { canonicalJson } from '../lib/canonical'
import { fmt } from '../lib/format'
import { nsBody } from '../lib/project'
import type { AdvisorResult, AdvisorSnapshot, AdvisorSuggestion, Project } from '../lib/types'
import { useEngineStore } from './engineStore'
import { useProjectStore } from './projectStore'

/** How many earlier results are kept by design key (undoing an applied suggestion brings its list back). */
const KEEP = 8

interface AdvState {
  job: AdvisorSnapshot | null
  /** key of the design the running (or last) job belongs to */
  jobKey: string | null
  /** results by canonical key of the design they were computed for */
  results: Record<string, AdvisorResult>
  error: string | null
  /** look for suggestions for the current design (background job on the engine) */
  start: () => Promise<void>
  cancel: () => Promise<void>
}

let pollToken = 0

/** What the suggestions depend on: the design, the custom materials, the merit function and the detectors. */
export const advKey = (p: Project) => canonicalJson({ s: p.system, m: p.custom_materials, o: p.optimization.operands, ns: nsBody(p) })

export const useAdvisorStore = create<AdvState>((set, get) => ({
  job: null,
  jobKey: null,
  results: {},
  error: null,

  start: async () => {
    const { project } = useProjectStore.getState()
    const log = useEngineStore.getState().log_
    const key = advKey(project)
    const old = get().job
    if (old && old.state === 'running') void api.advisorCancel(old.job_id).catch(() => undefined)
    set({ error: null, job: null, jobKey: key })
    try {
      const { job_id } = await api.advisorStart({ system: project.system, custom_materials: project.custom_materials, ...nsBody(project), optimization: project.optimization })
      const token = ++pollToken
      const poll = async () => {
        if (token !== pollToken) return
        let s: AdvisorSnapshot
        try {
          s = await api.advisorStatus(job_id)
        } catch (e) {
          if (token === pollToken) set({ error: (e as Error).message })
          window.setTimeout(poll, 1000)
          return
        }
        if (token !== pollToken) return
        set({ job: s })
        if (s.state === 'running') {
          window.setTimeout(poll, 250)
          return
        }
        if (s.result) {
          const results = { ...get().results, [key]: s.result }
          const keys = Object.keys(results)
          for (const k of keys.slice(0, Math.max(0, keys.length - KEEP))) delete results[k]
          set({ results })
          const top = s.result.suggestions[0]
          log('success', `Advisor ${s.result.status}: ${s.result.moves_tried} moves, ${s.result.evaluations} merit evaluations, ${s.result.suggestions.length} improve the merit${top ? ` (best: ${top.kind}, −${fmt(top.gain * 100, 3)} %)` : ''}`)
        }
        if (s.state === 'failed') {
          set({ error: s.error })
          log('error', `Advisor failed: ${s.error}`)
        }
      }
      set({ job: { job_id, state: 'running', progress: { done: 0, total: 0 }, result: null, error: null } })
      window.setTimeout(poll, 150)
    } catch (e) {
      set({ error: (e as Error).message })
    }
  },

  cancel: async () => {
    const j = get().job
    if (j) await api.advisorCancel(j.job_id)
  },
}))

export const isAdvRunning = (s: AdvState) => !!s.job && s.job.state === 'running'

/** Apply a suggestion's new parameter values as one undoable edit. Returns false when the design no longer has
 * the surfaces it names. */
export function applySuggestion(sg: AdvisorSuggestion, label: string): boolean {
  const { project, updateProject } = useProjectStore.getState()
  if (!sg.patch.every((p) => project.system.surfaces.some((s) => s.id === p.surface_id))) return false
  updateProject((p) => {
    for (const c of sg.patch) {
      const s = p.system.surfaces.find((x) => x.id === c.surface_id)
      if (s) (s as unknown as Record<string, unknown>)[c.key] = c.value
    }
  }, label)
  return true
}
