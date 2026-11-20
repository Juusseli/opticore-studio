// FDTD runs (2D or rotationally symmetric 3D): started on demand (they take seconds), polled until done, cancellable.
import { create } from 'zustand'
import { api } from '../lib/api'
import { canonicalJson } from '../lib/canonical'
import type { FdtdResult, FdtdSettings, FdtdSnapshot, MaterialRecord } from '../lib/types'
import { useEngineStore } from './engineStore'

interface FdtdState {
  job: FdtdSnapshot | null
  result: FdtdResult | null
  /** settings of the shown result (to flag edits made after the run) */
  resultKey: string | null
  resultSpec: FdtdSettings | null
  error: string | null
  start: (s: FdtdSettings, custom: MaterialRecord[]) => Promise<void>
  cancel: () => Promise<void>
  /** another project was opened: cancel the run and drop its result (it belongs to the other project's settings) */
  reset: () => void
}

let token = 0

/** what the result depends on (the POP hand-over plane is not part of the run) */
export const fdtdKey = (s: FdtdSettings) => {
  const { pop_object_z_um: _, ...run } = s
  return canonicalJson(run)
}

export const useFdtdStore = create<FdtdState>((set, get) => ({
  job: null,
  result: null,
  resultKey: null,
  resultSpec: null,
  error: null,
  start: async (s, custom) => {
    const log = useEngineStore.getState().log_
    const my = ++token
    set({ error: null, job: null })
    try {
      const { job_id } = await api.fdtdStart({ ...s, custom_materials: custom })
      log('info', `FDTD started (${s.size_z_um} x ${s.size_y_um} um, ${s.geometry === 'axisymmetric' ? 'rotationally symmetric, x' : s.polarization}-polarised, ${s.wavelength_um} um)`)
      set({ job: { id: job_id, state: 'queued', progress: 0, elapsed_s: 0, eta_s: null, error: null, result: null } })
      const poll = async () => {
        if (my !== token) return
        let snap: FdtdSnapshot
        try {
          snap = await api.fdtdStatus(job_id)
        } catch (e) {
          set({ error: (e as Error).message })
          return
        }
        if (my !== token) return
        set({ job: snap })
        if (snap.state === 'finished' && snap.result) {
          set({ result: snap.result, resultKey: fdtdKey(s), resultSpec: s })
          const r = snap.result
          log('success', `FDTD finished in ${r.time_s.toFixed(1)} s` + (r.R !== undefined ? `: R ${(r.R * 100).toFixed(2)} %, T ${((r.T ?? 0) * 100).toFixed(2)} %` : ''))
        } else if (snap.state === 'failed') {
          set({ error: snap.error })
          log('error', `FDTD failed: ${snap.error}`)
        } else if (snap.state !== 'cancelled') {
          window.setTimeout(poll, 300)
        }
      }
      window.setTimeout(poll, 200)
    } catch (e) {
      set({ error: (e as Error).message })
    }
  },
  cancel: async () => {
    const j = get().job
    if (!j || (j.state !== 'running' && j.state !== 'queued')) return
    try {
      await api.fdtdCancel(j.id)
    } catch {
      /* finished meanwhile */
    }
    set({ job: { ...j, state: 'cancelled' } })
  },
  reset: () => {
    const j = get().job
    if (j && (j.state === 'running' || j.state === 'queued')) void api.fdtdCancel(j.id).catch(() => undefined)
    token++
    set({ job: null, result: null, resultKey: null, resultSpec: null, error: null })
  },
}))
