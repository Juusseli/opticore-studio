// Fibre cross-section mode runs (full-vector finite differences, seconds to minutes): started on demand, polled until
// done, cancellable; the result is bound to the settings it was computed for.
import { create } from 'zustand'
import { api } from '../lib/api'
import { canonicalJson } from '../lib/canonical'
import type { Fibre2dResult, Fibre2dSettings, Fibre2dSnapshot, MaterialRecord } from '../lib/types'
import { useEngineStore } from './engineStore'

type Spec = Fibre2dSettings & { wavelength_um: number }

interface Fibre2dState {
  job: Fibre2dSnapshot | null
  result: Fibre2dResult | null
  /** settings of the shown result (to flag edits made after the run) */
  resultKey: string | null
  error: string | null
  start: (s: Spec, custom: MaterialRecord[]) => Promise<void>
  cancel: () => Promise<void>
  /** another project was opened: cancel the run and drop its result */
  reset: () => void
}

let token = 0

export const fibre2dKey = (s: Spec) => canonicalJson(s)

export const useFibre2dStore = create<Fibre2dState>((set, get) => ({
  job: null,
  result: null,
  resultKey: null,
  error: null,
  start: async (s, custom) => {
    const log = useEngineStore.getState().log_
    const my = ++token
    set({ error: null, job: null })
    try {
      const { job_id } = await api.fiber2dStart({ ...s, custom_materials: custom })
      if (my !== token) {
        void api.fiber2dCancel(job_id).catch(() => undefined)
        return
      }
      log('info', `Fibre cross-section modes started (${s.wavelength_um} um, ${s.refine ? 'meshes h and h/2' : 'one mesh'})`)
      set({ job: { id: job_id, state: 'queued', progress: 0, elapsed_s: 0, eta_s: null, error: null, result: null } })
      const poll = async () => {
        if (my !== token) return
        let snap: Fibre2dSnapshot
        try {
          snap = await api.fiber2dStatus(job_id)
        } catch (e) {
          set({ error: (e as Error).message })
          return
        }
        if (my !== token) return
        set({ job: snap })
        if (snap.state === 'finished' && snap.result) {
          set({ result: snap.result, resultKey: fibre2dKey(s) })
          const b = snap.result.best !== null ? snap.result.modes[snap.result.best] : null
          log('success', `Fibre cross-section modes in ${snap.elapsed_s.toFixed(1)} s` + (b ? `: n_eff ${b.neff.toFixed(9)}, loss ${b.loss_db_per_m.toPrecision(3)} dB/m` : ''))
        } else if (snap.state === 'failed') {
          set({ error: snap.error })
          log('error', `Fibre cross-section modes failed: ${snap.error}`)
        } else if (snap.state !== 'cancelled') {
          window.setTimeout(poll, 400)
        }
      }
      window.setTimeout(poll, 200)
    } catch (e) {
      if (my === token) set({ error: (e as Error).message })
    }
  },
  cancel: async () => {
    const j = get().job
    if (!j || (j.state !== 'running' && j.state !== 'queued')) return
    try {
      await api.fiber2dCancel(j.id)
    } catch {
      /* finished meanwhile */
    }
    set({ job: { ...j, state: 'cancelled' } })
  },
  reset: () => {
    const j = get().job
    if (j && (j.state === 'running' || j.state === 'queued')) void api.fiber2dCancel(j.id).catch(() => undefined)
    token++
    set({ job: null, result: null, resultKey: null, error: null })
  },
}))
