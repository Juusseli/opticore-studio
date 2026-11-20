import { create } from 'zustand'
import { api } from '../lib/api'
import { canonicalJson } from '../lib/canonical'
import { fmt } from '../lib/format'
import { nsBody } from '../lib/project'
import type { ToleranceResult, ToleranceSnapshot } from '../lib/types'
import { useEngineStore } from './engineStore'
import { useProjectStore } from './projectStore'

interface TolState {
  job: ToleranceSnapshot | null
  result: ToleranceResult | null
  /** canonical key of the system + spec the result belongs to (stale detection) */
  resultKey: string | null
  error: string | null
  /** run the analysis; allocate: first allocate the tolerances to the specification limit */
  start: (allocate?: boolean) => Promise<void>
  cancel: () => Promise<void>
  clear: () => void
}

let pollToken = 0

export const tolKey = () => {
  const p = useProjectStore.getState().project
  return canonicalJson({ s: p.system, t: p.tolerancing, m: p.custom_materials, o: p.tolerancing.criterion === 'merit' ? p.optimization.operands : null, ns: p.tolerancing.criterion === 'merit' ? nsBody(p) : null })
}

export const useTolStore = create<TolState>((set, get) => ({
  job: null,
  result: null,
  resultKey: null,
  error: null,

  start: async (allocate = false) => {
    const { project } = useProjectStore.getState()
    const log = useEngineStore.getState().log_
    const key = tolKey()
    set({ error: null, job: null })
    try {
      const { job_id } = await api.toleranceStart({
        system: project.system,
        custom_materials: project.custom_materials,
        ...nsBody(project),
        tolerance: project.tolerancing,
        optimization: project.optimization,
        allocate,
      })
      const n = project.tolerancing.tolerances.filter((x) => x.enabled).length
      log('info', `Tolerance ${allocate ? 'allocation' : 'analysis'} started (${n} tolerances, ${project.tolerancing.monte_carlo_trials} Monte Carlo trials, criterion ${project.tolerancing.criterion})`)
      const token = ++pollToken
      const poll = async () => {
        if (token !== pollToken) return
        let s: ToleranceSnapshot
        try {
          s = await api.toleranceStatus(job_id)
        } catch (e) {
          if (token === pollToken) set({ error: (e as Error).message })
          window.setTimeout(poll, 1000)
          return
        }
        if (token !== pollToken) return
        set({ job: s })
        if (s.state === 'queued' || s.state === 'running') {
          window.setTimeout(poll, 300)
          return
        }
        if (s.result) {
          set({ result: s.result, resultKey: key })
          const st = s.result.monte_carlo.statistics
          const y = s.result.yield
          const worse90 = (s.result.sense ?? 1) > 0 ? st.p90 : st.p10
          log('success', `Tolerance analysis ${s.result.status}: nominal ${fmt(s.result.nominal, 5)} ${s.result.unit}, RSS estimate ${fmt(s.result.rss_estimate, 5)}, MC 90% ${fmt(worse90 ?? null, 5)}${y ? `, yield ${fmt(y.fraction * 100, 3)} % (95 % CI ${fmt(y.ci95[0] * 100, 3)}–${fmt(y.ci95[1] * 100, 3)} %)` : ''} (${s.result.monte_carlo.trials} trials, ${s.result.elapsed_s.toFixed(1)} s)`)
          if (s.result.allocation) log('info', `Allocation: ${s.result.allocation.rows.filter((r) => !r.locked).length} tolerances scaled; all at their limits ${fmt(s.result.allocation.predicted, 5)} ${s.result.unit} (specification ${fmt(s.result.allocation.limit, 5)})`)
          for (const n of s.result.notes) log('warning', n)
        }
        if (s.state === 'failed') {
          set({ error: s.error })
          log('error', `Tolerance analysis failed: ${s.error}`)
        }
      }
      set({ job: { id: job_id, state: 'queued', phase: 'starting', done: 0, total: 0, nominal: null, trials: [], elapsed_s: 0, error: null, result: null } })
      window.setTimeout(poll, 150)
    } catch (e) {
      set({ error: (e as Error).message })
    }
  },

  cancel: async () => {
    const j = get().job
    if (j) await api.toleranceCancel(j.id)
  },
  clear: () => set({ result: null, resultKey: null, job: null, error: null }),
}))

export const isTolRunning = (s: TolState) => !!s.job && (s.job.state === 'queued' || s.job.state === 'running')
