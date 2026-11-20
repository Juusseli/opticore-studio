import { create } from 'zustand'
import { api, ApiError } from '../lib/api'
import { canonicalJson } from '../lib/canonical'
import type { AnalysisKind, CoatingSummary, Evaluation, MaterialRecord, MaterialSummary, OpticalSystem } from '../lib/types'
import { newId } from '../lib/project'
import { isSamplePhoto, loadSamplePhoto } from '../lib/samplePhotos'
import { usePhotoStore } from './photoStore'
import { useProjectStore } from './projectStore'

export interface LogEntry {
  id: number
  time: string
  level: 'info' | 'warning' | 'error' | 'success'
  text: string
}

interface AnalysisState {
  key: string
  data: unknown
  error: string | null
  loading: boolean
  ms: number | null
  /** engine error code; NOT_APPLICABLE: the analysis does not apply to this kind of system (not a failure) */
  code?: string | null
}

interface EngineState {
  backend: 'unknown' | 'online' | 'offline'
  engineVersion: string | null
  evaluation: Evaluation | null
  evalError: ApiError | null
  evalKey: string
  evaluating: boolean
  evalMs: number | null
  materials: MaterialSummary[]
  coatings: CoatingSummary[]
  analyses: Partial<Record<AnalysisKind, AnalysisState>>
  preview: OpticalSystem | null // live optimisation preview (not part of the project)
  /** incremented by "Re-trace rays": every open analysis view recomputes */
  retraceToken: number
  log: LogEntry[]

  setPreview: (s: OpticalSystem | null) => void
  log_: (level: LogEntry['level'], text: string) => void
  clearLog: () => void
  checkBackend: () => Promise<void>
  loadMaterials: () => Promise<void>
  evaluate: (force?: boolean) => Promise<void>
  runAnalysis: (kind: AnalysisKind, settings: Record<string, unknown>, force?: boolean) => Promise<void>
}

let logId = 1
let evalAbort: AbortController | null = null
const analysisAbort: Partial<Record<AnalysisKind, AbortController>> = {}

// set by catalogStore: definitions of catalogue glasses a system uses that are not (yet) in the project,
// e.g. in the live optimisation preview (kept out of this module's imports to avoid an import cycle)
let extraMaterials: (system: OpticalSystem, custom: MaterialRecord[]) => MaterialRecord[] = () => []
export function registerExtraMaterials(fn: typeof extraMaterials) {
  extraMaterials = fn
}

export function systemBody(system: OpticalSystem, custom: MaterialRecord[]) {
  const extra = extraMaterials(system, custom)
  return { system, custom_materials: extra.length ? [...custom, ...extra] : custom }
}

/** This tab's live-image channel (analysis/liveimage.py Channels). */
const LIVE_CHANNEL = newId()

export const useEngineStore = create<EngineState>((set, get) => ({
  backend: 'unknown',
  engineVersion: null,
  evaluation: null,
  evalError: null,
  evalKey: '',
  evaluating: false,
  evalMs: null,
  materials: [],
  coatings: [],
  analyses: {},
  preview: null,
  retraceToken: 0,
  log: [],

  setPreview: (preview) => set({ preview }),

  log_: (level, text) => {
    const entry = { id: logId++, time: new Date().toLocaleTimeString(), level, text }
    const log = [...get().log, entry]
    if (log.length > 500) log.splice(0, log.length - 500)
    set({ log })
  },
  clearLog: () => set({ log: [] }),

  checkBackend: async () => {
    try {
      const h = await api.health()
      const wasOnline = get().backend === 'online'
      if (!wasOnline) get().log_('success', `Connected to OptiCore engine ${h.engine_version} (schema v${h.schema_version})`)
      set({ backend: 'online', engineVersion: h.engine_version })
      // (re)load the catalogue whenever the engine becomes reachable
      if (!wasOnline || !get().materials.length) void get().loadMaterials()
    } catch {
      if (get().backend !== 'offline') get().log_('error', 'Engine offline: start it with Start OptiCore.bat or scripts/dev.ps1 (see README); its window names its port')
      set({ backend: 'offline' })
    }
  },

  loadMaterials: async () => {
    try {
      const [r, c] = await Promise.all([api.materials(), api.coatings()])
      set({ materials: r.materials, coatings: c.coatings })
    } catch (e) {
      get().log_('error', `Failed to load material catalogue: ${(e as Error).message}`)
    }
  },

  evaluate: async (force = false) => {
    const { project } = useProjectStore.getState()
    const system = get().preview ?? project.system
    const key = canonicalJson({ s: system, m: project.custom_materials })
    if (!force && key === get().evalKey && get().evaluation) return
    evalAbort?.abort()
    const ctrl = new AbortController()
    evalAbort = ctrl
    set({ evaluating: true, evalKey: key })
    const t0 = performance.now()
    try {
      const ev = await api.evaluate(systemBody(system, project.custom_materials), ctrl.signal)
      // a newer request, or opening another project (which clears the key), makes this answer stale
      if (ctrl.signal.aborted || get().evalKey !== key) return
      set({ evaluation: ev, evalError: null, evaluating: false, evalMs: performance.now() - t0, backend: 'online' })
    } catch (e) {
      if ((e as Error).name === 'AbortError' || get().evalKey !== key) return
      const err = e instanceof ApiError ? e : new ApiError(0, 'ERROR', (e as Error).message)
      set({ evalError: err, evaluating: false, backend: err.code === 'NETWORK_ERROR' ? 'offline' : 'online' })
      get().log_('error', `Evaluation failed: ${err.message}`)
    }
  },

  runAnalysis: async (kind, settings, force = false) => {
    const { project } = useProjectStore.getState()
    const system = get().preview ?? project.system
    const key = canonicalJson({ s: system, m: project.custom_materials, settings })
    const cur = get().analyses[kind]
    if (!force && cur && cur.key === key && (cur.data || cur.loading)) return
    analysisAbort[kind]?.abort()
    const ctrl = new AbortController()
    analysisAbort[kind] = ctrl
    set({ analyses: { ...get().analyses, [kind]: { key, data: cur?.data ?? null, error: null, loading: true, ms: null } } })
    const body = { ...systemBody(system, project.custom_materials), ...settings }
    const t0 = performance.now()
    try {
      let data: unknown
      if (kind === 'focus') data = await api.focus(body, ctrl.signal)
      else if (kind === 'thermal') data = await api.thermal(body, ctrl.signal)
      else if (kind === 'mounts') data = await api.mounts(body, ctrl.signal)
      else if (kind === 'elements') data = await api.elements(body, ctrl.signal)
      else if (kind === 'relillum') data = await api.relativeIllumination(body, ctrl.signal)
      else if (kind === 'imagesim') data = await api.imageSimulation(body, ctrl.signal)
      else if (kind === 'spot') data = await api.spot(body as Parameters<typeof api.spot>[0], ctrl.signal)
      else if (kind === 'rayfan') data = await api.rayfan(body as Parameters<typeof api.rayfan>[0], ctrl.signal)
      else if (kind === 'field') data = await api.field(body as Parameters<typeof api.field>[0], ctrl.signal)
      else if (kind === 'longitudinal') data = await api.longitudinal(body as Parameters<typeof api.longitudinal>[0], ctrl.signal)
      else if (kind === 'chromatic') data = await api.chromatic(body as Parameters<typeof api.chromatic>[0], ctrl.signal)
      else if (kind === 'opdfan') data = await api.opdfan(body as Parameters<typeof api.opdfan>[0], ctrl.signal)
      else if (kind === 'wavefront') data = await api.wavefront(body, ctrl.signal)
      else if (kind === 'interferogram') data = await api.interferogram(body, ctrl.signal)
      else if (kind === 'spectrometer') data = await api.spectrometer(body, ctrl.signal)
      else if (kind === 'psf') data = await api.psf(body, ctrl.signal)
      else if (kind === 'huygens') data = await api.huygens(body, ctrl.signal)
      else if (kind === 'coatings') data = await api.coatingPerformance(body, ctrl.signal)
      else if (kind === 'mtf') data = await api.mtf(body, ctrl.signal)
      else if (kind === 'throughput') data = await api.throughput(body, ctrl.signal)
      else if (kind === 'gaussian') data = await api.gaussian(body, ctrl.signal)
      else if (kind === 'pop') data = await api.pop(body, ctrl.signal)
      else if (kind === 'fibermodes') data = await api.fiberModes({ ...(settings as unknown as Parameters<typeof api.fiberModes>[0]), custom_materials: project.custom_materials }, ctrl.signal)
      else if (kind === 'rcwa') data = await api.rcwa({ ...(settings as unknown as Parameters<typeof api.rcwa>[0]), custom_materials: project.custom_materials }, ctrl.signal)
      else if (kind === 'fiberdisp') data = await api.fiberDispersion({ ...(settings as unknown as Parameters<typeof api.fiberDispersion>[0]), custom_materials: project.custom_materials }, ctrl.signal)
      else if (kind === 'polarization') data = await api.polarization(body, ctrl.signal)
      else if (kind === 'vectorpsf') data = await api.vectorPsf(body, ctrl.signal)
      else if (kind === 'advisor') data = await api.advisor(body, ctrl.signal)
      else if (kind === 'liveimage') {
        // the photo travels from this browser's store; the settings only name it (photo_id)
        const { photo_id, scene, ...rest } = body as typeof body & { photo_id?: string | null; scene?: string }
        const ph = usePhotoStore.getState()
        if (scene === 'photo' && (!ph.photo || ph.id !== photo_id)) throw new Error('The photo is not loaded in this browser: choose it again with "Use my photo"')
        // built-in photos (lib/samplePhotos) are sent like the user's photo
        const photo = scene === 'photo' ? ph.photo! : isSamplePhoto(scene) ? await loadSamplePhoto(scene) : null
        if (ctrl.signal.aborted) return
        // the tab's channel lets the engine stop an older render of this view as soon as a newer one starts
        data = await api.liveImage({ ...rest, ...(photo ? { photo } : { scene }), channel: LIVE_CHANNEL }, ctrl.signal)
      }
      else if (kind === 'sweep') data = await api.sweep(body, ctrl.signal)
      else if (kind === 'ghosts') data = await api.ghosts(body, ctrl.signal)
      else if (kind === 'nonseq') {
        // full CAD models (meshes and exact sources) are sent only for the models that take part
        const ids = new Set(((settings as { scene?: { id: string }[] }).scene ?? []).map((x) => x.id))
        const nsBody = { ...body, cad_assets: project.cad_assets.filter((a) => ids.has(a.id)) } as typeof body
        delete (nsBody as Record<string, unknown>).scene
        data = await api.nonseq(nsBody, ctrl.signal)
      }
      else data = await api.paraxial(body, ctrl.signal)
      if (ctrl.signal.aborted) return
      set({ analyses: { ...get().analyses, [kind]: { key, data, error: null, loading: false, ms: performance.now() - t0 } } })
    } catch (e) {
      if ((e as Error).name === 'AbortError') return
      if (e instanceof ApiError && e.code === 'SUPERSEDED') return // a newer request of this view is running
      set({ analyses: { ...get().analyses, [kind]: { key, data: null, error: (e as Error).message, code: e instanceof ApiError ? e.code : null, loading: false, ms: null } } })
    }
  },
}))
