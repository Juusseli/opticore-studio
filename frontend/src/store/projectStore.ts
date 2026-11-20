import { create } from 'zustand'
import { canonicalJson } from '../lib/canonical'
import { baseValue, CONFIG_OF_VARIABLE, configRow, fieldConfigRow, isFieldConfigParam, isSystemConfigParam } from '../lib/configs'
import { blankProject, cloneSystem, defaultSurface, newId, nowIso, variableValue } from '../lib/project'
import { type CatalogIndex, embedCatalogGlasses } from '../lib/glassCatalog'
import { afterFieldRemoved, afterSurfaceMoved, afterWavelengthRemoved, clampIndices, pruneReferences } from '../lib/references'
import type { CadAsset, ConfigParameter, ConfigValue, FieldPoint, OpticalSystem, OptimizationSpec, Project, Solve, Surface, Variable, VariableParam, Wavelength, LightSource, DetectorSpec } from '../lib/types'

const HISTORY_LIMIT = 200

interface HistoryEntry {
  project: Project
  label: string
}

export interface ProjectState {
  project: Project
  savedKey: string
  past: HistoryEntry[]
  future: HistoryEntry[]
  selection: number[]
  lastAction: string
  storedInLibrary: boolean
  /** increases each time a project is opened (views reset their framing) */
  openCount: number

  setProject: (p: Project, opts?: { saved?: boolean; inLibrary?: boolean }) => void
  commit: (label: string, fn: (p: Project) => void) => void
  undo: () => void
  redo: () => void
  /** mark `saved` (the project as written; default: the open one) as saved, if it is still the open project */
  markSaved: (inLibrary?: boolean, saved?: Project) => void

  select: (i: number, mode?: 'single' | 'toggle' | 'range') => void
  selectAll: () => void

  updateSurface: (i: number, patch: Partial<Surface>, label?: string) => void
  updateSurfaces: (indices: number[], patch: Partial<Surface>, label?: string) => void
  insertSurface: (at: number, partial?: Partial<Surface>) => void
  insertLens: (at: number) => void
  deleteSurfaces: (indices: number[]) => void
  moveSurface: (from: number, to: number) => void
  duplicateSurface: (i: number) => void
  setStop: (i: number) => void
  updateSystem: (patch: Partial<OpticalSystem>, label?: string) => void
  setWavelengths: (w: Wavelength[], primary?: number) => void
  setFields: (f: FieldPoint[]) => void
  removeField: (i: number) => void
  removeWavelength: (i: number) => void
  setOptimization: (o: OptimizationSpec, label?: string) => void
  setSolve: (i: number, kind: 'thickness' | 'curvature', solve: Solve | null) => void
  toggleVariable: (surfaceId: string, parameter: VariableParam) => void
  enableConfigurations: () => void
  addCadAsset: (a: CadAsset) => void
  updateCadAsset: (id: string, patch: Partial<CadAsset>, label?: string) => void
  removeCadAsset: (id: string) => void
  disableConfigurations: () => void
  addConfiguration: () => void
  removeConfiguration: (k: number) => void
  renameConfiguration: (k: number, name: string) => void
  setActiveConfiguration: (k: number) => void
  addConfigOperand: (parameter: ConfigParameter, surfaceId: string | null, field?: number) => void
  removeConfigOperand: (row: number) => void
  setConfigValue: (row: number, k: number, value: ConfigValue) => void
  replaceSystem: (s: OpticalSystem, label: string, revisionLabel?: string) => void
  addRevision: (label: string) => void
  restoreRevision: (id: string) => void
  deleteRevision: (id: string) => void
  setMetadata: (patch: Partial<Project['metadata']>) => void
  updateProject: (fn: (p: Project) => void, label: string) => void
  /** a continuous edit (dragging a number): its commits make one undo step */
  beginGesture: () => void
  endGesture: () => void
}

// inside a gesture the first commit records the undo step and later ones replace the project in place
let gesture = false
let gestureRecorded = false
// the drag's own edit: another edit arriving during the drag (an engine answer) gets its own undo step
let gestureLabel: string | null = null

export function projectKey(p: Project): string {
  return canonicalJson({ ...p, checksum: null })
}

function clone<T>(x: T): T {
  return JSON.parse(JSON.stringify(x)) as T
}

// set by catalogStore (kept out of this module's imports to avoid an import cycle)
let catalogIndexProvider: () => CatalogIndex | null = () => null
export function registerCatalogIndex(fn: () => CatalogIndex | null) {
  catalogIndexProvider = fn
}

export const useProjectStore = create<ProjectState>((set, get) => {
  const initial = blankProject()
  return {
    project: initial,
    savedKey: projectKey(initial),
    past: [],
    future: [],
    selection: [1],
    lastAction: '',
    storedInLibrary: false,
    openCount: 0,

    setProject: (p, opts) =>
      set({
        openCount: get().openCount + 1,
        project: p,
        past: [],
        future: [],
        selection: [Math.min(1, p.system.surfaces.length - 1)],
        savedKey: opts?.saved === false ? '' : projectKey(p),
        lastAction: 'Open project',
        storedInLibrary: !!opts?.inLibrary,
      }),

    commit: (label, fn) => {
      const { project, past } = get()
      const next = clone(project)
      fn(next)
      // glasses taken from an imported catalogue are copied into the project (self-contained files)
      const idx = catalogIndexProvider()
      if (idx) embedCatalogGlasses(next, idx)
      // ignore no-op edits so undo/redo only records real changes
      if (JSON.stringify(next) === JSON.stringify(project)) return
      next.metadata.modified = nowIso()
      if (gesture && gestureRecorded && label === gestureLabel) {
        set({ project: next, future: [], lastAction: label })
        return
      }
      if (gesture) {
        // the drag's first edit opens its undo step; a foreign edit closes it, so the drag's next edit opens another
        gestureRecorded = !gestureRecorded || label === gestureLabel
        if (gestureRecorded && gestureLabel === null) gestureLabel = label
        if (label !== gestureLabel) gestureRecorded = false
      }
      const np = [...past, { project, label }]
      if (np.length > HISTORY_LIMIT) np.shift()
      // keep selection valid
      const n = next.system.surfaces.length
      const sel = get().selection.filter((i) => i < n)
      set({ project: next, past: np, future: [], lastAction: label, selection: sel.length ? sel : [Math.min(1, n - 1)] })
    },

    undo: () => {
      const { past, future, project } = get()
      if (!past.length) return
      const prev = past[past.length - 1]
      const n = prev.project.system.surfaces.length
      set({
        project: prev.project,
        past: past.slice(0, -1),
        future: [{ project, label: prev.label }, ...future],
        lastAction: `Undo ${prev.label}`,
        selection: get().selection.filter((i) => i < n).length ? get().selection.filter((i) => i < n) : [Math.min(1, n - 1)],
      })
    },

    redo: () => {
      const { past, future, project } = get()
      if (!future.length) return
      const nxt = future[0]
      set({ project: nxt.project, past: [...past, { project, label: nxt.label }], future: future.slice(1), lastAction: `Redo ${nxt.label}` })
    },

    markSaved: (inLibrary, saved) => {
      const p = saved ?? get().project
      // a save finishing after another project was opened says nothing about that one
      if (p.id !== get().project.id) return
      set({ savedKey: projectKey(p), ...(inLibrary !== undefined ? { storedInLibrary: inLibrary } : {}) })
    },

    select: (i, mode = 'single') => {
      const sel = get().selection
      if (mode === 'single') set({ selection: [i] })
      else if (mode === 'toggle') set({ selection: sel.includes(i) ? sel.filter((x) => x !== i) : [...sel, i] })
      else {
        const a = sel[0] ?? i
        const [lo, hi] = a < i ? [a, i] : [i, a]
        const r: number[] = []
        for (let k = lo; k <= hi; k++) r.push(k)
        set({ selection: [a, ...r.filter((x) => x !== a)] })
      }
    },
    selectAll: () => set({ selection: get().project.system.surfaces.map((_, i) => i) }),

    updateSurface: (i, patch, label) =>
      get().commit(label ?? `Edit surface ${i}`, (p) => {
        Object.assign(p.system.surfaces[i], patch)
        // a coordinate break cannot be the aperture stop
        if (p.system.surfaces[i].type === 'coordinate_break') p.system.surfaces[i].is_stop = false
      }),

    updateSurfaces: (indices, patch, label) =>
      get().commit(label ?? `Edit ${indices.length} surfaces`, (p) => {
        for (const i of indices) if (p.system.surfaces[i]) Object.assign(p.system.surfaces[i], patch)
      }),

    insertSurface: (at, partial) => {
      const n = get().project.system.surfaces.length
      const pos = Math.max(1, Math.min(at, n - 1))
      get().commit('Insert surface', (p) => {
        p.system.surfaces.splice(pos, 0, defaultSurface({ thickness: 5, ...partial }))
      })
      set({ selection: [pos] })
    },

    insertLens: (at) => {
      const surfs = get().project.system.surfaces
      const n = surfs.length
      let pos = Math.max(1, Math.min(at, n - 1))
      // never split an existing element: move to the next air space
      const glass = (m: string) => !['AIR', 'MIRROR', 'VACUUM'].includes(m)
      while (pos < n - 1 && pos > 0 && glass(surfs[pos - 1].material) && surfs[pos - 1].type !== 'coordinate_break') pos++
      get().commit('Insert lens', (p) => {
        p.system.surfaces.splice(
          pos,
          0,
          defaultSurface({ label: 'Lens front', radius: 50, thickness: 4, material: 'N-BK7' }),
          defaultSurface({ label: 'Lens back', radius: -50, thickness: 10 }),
        )
      })
      set({ selection: [pos, pos + 1] })
    },

    deleteSurfaces: (indices) => {
      const n = get().project.system.surfaces.length
      const del = [...new Set(indices)].filter((i) => i > 0 && i < n - 1).sort((a, b) => b - a)
      if (!del.length) return
      if (n - del.length < 3) return
      get().commit(del.length > 1 ? `Delete ${del.length} surfaces` : `Delete surface ${del[0]}`, (p) => {
        const ids = new Set(del.map((i) => p.system.surfaces[i].id))
        // sources and detectors anchored to a deleted surface follow the surface that takes its place (the first one
        // kept after it): a plain surface's vertex frame is where the deleted one's was, so they stay put
        const kept = p.system.surfaces.filter((x) => !ids.has(x.id))
        const heir = new Map<string, string>()
        p.system.surfaces.forEach((x, i) => {
          if (!ids.has(x.id)) return
          const next = p.system.surfaces.slice(i + 1).find((y) => !ids.has(y.id)) ?? kept[kept.length - 1]
          heir.set(x.id, next.id)
        })
        for (const item of [...(p.sources ?? []), ...(p.detectors ?? [])]) {
          const a = item.placement.anchor
          if (a && heir.has(a)) item.placement.anchor = heir.get(a)!
        }
        for (const i of del) p.system.surfaces.splice(i, 1)
        p.optimization.variables = p.optimization.variables.filter((v) => !ids.has(v.surface_id))
        p.optimization.operands = p.optimization.operands.filter((o) => !o.surface_id || !ids.has(o.surface_id))
        p.tolerancing.tolerances = p.tolerancing.tolerances.filter((x) => !ids.has(x.surface_id) && !(x.surface_id_end && ids.has(x.surface_id_end)))
        p.tolerancing.compensators = p.tolerancing.compensators.filter((c) => !ids.has(c.surface_id))
        if (p.system.multi_config) p.system.multi_config.operands = p.system.multi_config.operands.filter((o) => !o.surface_id || !ids.has(o.surface_id))
        for (const s of p.system.surfaces) {
          // pickups from a deleted surface cannot be resolved any more
          if (s.thickness_solve?.type === 'pickup' && s.thickness_solve.surface_id && ids.has(s.thickness_solve.surface_id)) s.thickness_solve = null
          if (s.curvature_solve?.type === 'pickup' && s.curvature_solve.surface_id && ids.has(s.curvature_solve.surface_id)) s.curvature_solve = null
        }
      })
      set({ selection: [Math.max(1, Math.min(del[del.length - 1], get().project.system.surfaces.length - 2))] })
    },

    moveSurface: (from, to) => {
      const n = get().project.system.surfaces.length
      if (from <= 0 || from >= n - 1 || to <= 0 || to >= n - 1 || from === to) return
      get().commit(`Move surface ${from} → ${to}`, (p) => {
        const [s] = p.system.surfaces.splice(from, 1)
        p.system.surfaces.splice(to, 0, s)
        afterSurfaceMoved(p)
      })
      set({ selection: [to] })
    },

    duplicateSurface: (i) => {
      const n = get().project.system.surfaces.length
      if (i <= 0 || i >= n - 1) return
      get().commit(`Duplicate surface ${i}`, (p) => {
        const s = clone(p.system.surfaces[i])
        s.id = newId()
        s.is_stop = false
        p.system.surfaces.splice(i + 1, 0, s)
      })
      set({ selection: [i + 1] })
    },

    setStop: (i) =>
      get().commit(`Set stop at surface ${i}`, (p) => {
        p.system.surfaces.forEach((s, k) => (s.is_stop = k === i))
      }),

    updateSystem: (patch, label) =>
      get().commit(label ?? 'Edit system', (p) => {
        Object.assign(p.system, patch)
      }),

    setWavelengths: (w, primary) =>
      get().commit('Edit wavelengths', (p) => {
        p.system.wavelengths = w
        const pr = primary ?? p.system.primary_wavelength
        p.system.primary_wavelength = Math.max(0, Math.min(pr, w.length - 1))
        clampIndices(p)
      }),

    setFields: (f) =>
      get().commit('Edit fields', (p) => {
        p.system.fields = f
        clampIndices(p)
      }),

    removeField: (i) =>
      get().commit(`Remove field ${i + 1}`, (p) => {
        if (p.system.fields.length <= 1) return
        p.system.fields.splice(i, 1)
        afterFieldRemoved(p, i)
      }),

    removeWavelength: (i) =>
      get().commit(`Remove wavelength ${i + 1}`, (p) => {
        const s = p.system
        if (s.wavelengths.length <= 1) return
        s.wavelengths.splice(i, 1)
        if (s.primary_wavelength === i) s.primary_wavelength = Math.min(i, s.wavelengths.length - 1)
        else if (s.primary_wavelength > i) s.primary_wavelength -= 1
        afterWavelengthRemoved(p, i)
      }),

    setSolve: (i, kind, solve) =>
      get().commit(solve ? `Surface ${i} ${kind} solve (${solve.type})` : `Surface ${i} remove ${kind} solve`, (p) => {
        const s = p.system.surfaces[i]
        if (!s) return
        if (kind === 'thickness') s.thickness_solve = solve
        else s.curvature_solve = solve
        // a solved parameter cannot also be an optimisation variable
        if (solve) p.optimization.variables = p.optimization.variables.filter((v) => !(v.surface_id === s.id && v.parameter === kind))
      }),

    setOptimization: (o, label) =>
      get().commit(label ?? 'Edit merit function', (p) => {
        p.optimization = o
      }),

    toggleVariable: (surfaceId, parameter) =>
      get().commit('Toggle variable', (p) => {
        const vs = p.optimization.variables
        // a parameter set per configuration becomes a per-configuration variable (active configuration)
        const cp = CONFIG_OF_VARIABLE[parameter]
        const perConfig = !!p.system.multi_config && !!cp && configRow(p.system, surfaceId, cp) >= 0
        const conf = perConfig ? p.system.multi_config!.active : null
        const k = vs.findIndex((v) => v.surface_id === surfaceId && v.parameter === parameter && (v.configuration ?? null) === conf)
        if (k >= 0) vs.splice(k, 1)
        else {
          const v = defaultBounds(p.system, surfaceId, parameter)
          if (perConfig) {
            v.configuration = conf
            if (parameter === 'thickness') {
              const cur = variableValue(p.system, surfaceId, parameter, conf)
              v.min = Number.isFinite(cur) ? Math.max(0, cur - Math.max(1, Math.abs(cur) * 0.5)) : null
              v.max = Number.isFinite(cur) ? cur + Math.max(1, Math.abs(cur) * 0.5) : null
            }
          }
          vs.push(v)
        }
      }),

    addCadAsset: (a) => get().commit(`Import CAD model ${a.name}`, (p) => void p.cad_assets.push(a)),
    updateCadAsset: (id, patch, label) =>
      get().commit(label ?? 'Edit CAD model', (p) => {
        const a = p.cad_assets.find((x) => x.id === id)
        if (a) Object.assign(a, patch)
      }),
    removeCadAsset: (id) =>
      get().commit('Remove CAD model', (p) => {
        p.cad_assets = p.cad_assets.filter((x) => x.id !== id)
        // mount parts linked to the model keep their mechanics, not the link
        for (const m of p.system.mounts ?? []) {
          if (m.cad_asset_id === id) {
            m.cad_asset_id = null
            m.cad_node_id = null
          }
        }
      }),

    enableConfigurations: () =>
      get().commit('Enable multiple configurations', (p) => {
        if (p.system.multi_config) return
        p.system.multi_config = { names: ['Config 1', 'Config 2'], operands: [], active: 0 }
      }),

    disableConfigurations: () =>
      get().commit('Remove configurations (keep active)', (p) => {
        const mc = p.system.multi_config
        if (!mc) return
        // write the active configuration into the base prescription
        for (const op of mc.operands) {
          const v = op.values[mc.active]
          if (op.parameter === 'aperture_value') p.system.aperture.value = Number(v)
          else if (op.parameter === 'temperature') p.system.temperature_c = Number(v)
          else if (op.parameter === 'pressure') p.system.pressure_atm = Number(v)
          else if (isFieldConfigParam(op.parameter)) {
            const f = p.system.fields[op.field ?? -1]
            if (f) f[op.parameter as 'vdx' | 'vdy' | 'vcx' | 'vcy'] = Number(v)
          } else {
            const s = p.system.surfaces.find((x) => x.id === op.surface_id)
            if (!s) continue
            if (op.parameter === 'semi_diameter') {
              s.semi_diameter = Number(v)
              s.semi_diameter_mode = 'fixed'
            } else (s as unknown as Record<string, ConfigValue>)[op.parameter] = v
          }
        }
        p.system.multi_config = null
        p.optimization.variables = p.optimization.variables.filter((v) => v.configuration === undefined || v.configuration === null)
        p.optimization.operands = p.optimization.operands.map((o) => ({ ...o, configuration: null }))
      }),

    addConfiguration: () =>
      get().commit('Add configuration', (p) => {
        const mc = p.system.multi_config
        if (!mc) return
        mc.names.push(`Config ${mc.names.length + 1}`)
        for (const op of mc.operands) op.values.push(op.values[mc.active])
        mc.active = mc.names.length - 1
      }),

    removeConfiguration: (k) =>
      get().commit(`Delete configuration ${k + 1}`, (p) => {
        const mc = p.system.multi_config
        if (!mc || mc.names.length <= 1) return
        mc.names.splice(k, 1)
        for (const op of mc.operands) op.values.splice(k, 1)
        if (mc.active >= k && mc.active > 0) mc.active -= 1
        const remap = (c: number | null | undefined) => (c === null || c === undefined ? c : c > k ? c - 1 : c)
        p.optimization.variables = p.optimization.variables.filter((v) => v.configuration !== k).map((v) => ({ ...v, configuration: remap(v.configuration) }))
        p.optimization.operands = p.optimization.operands.filter((o) => o.configuration !== k).map((o) => ({ ...o, configuration: remap(o.configuration) }))
        const sw = p.analysis_settings.sweep as { parameters?: { configuration?: number | null }[] } | undefined
        for (const q of sw?.parameters ?? []) q.configuration = q.configuration === k ? null : remap(q.configuration)
      }),

    renameConfiguration: (k, name) =>
      get().commit('Rename configuration', (p) => {
        if (p.system.multi_config && name.trim()) p.system.multi_config.names[k] = name.trim()
      }),

    setActiveConfiguration: (k) =>
      get().commit(`Active configuration ${k + 1}`, (p) => {
        const mc = p.system.multi_config
        if (mc && k >= 0 && k < mc.names.length) mc.active = k
      }),

    addConfigOperand: (parameter, surfaceId, field) =>
      get().commit(`Add configuration row (${parameter})`, (p) => {
        const mc = p.system.multi_config
        if (!mc) return
        if (isFieldConfigParam(parameter)) {
          // a field's vignetting factor: seeded with the field's own value
          const f = p.system.fields[field ?? -1]
          if (!f || fieldConfigRow(p.system, field!, parameter) >= 0) return
          const v = (f[parameter as 'vdx' | 'vdy' | 'vcx' | 'vcy'] as number | undefined) ?? 0
          mc.operands.push({ parameter, surface_id: null, field, values: mc.names.map(() => v) })
          return
        }
        if (configRow(p.system, surfaceId, parameter) >= 0) return
        const v = baseValue(p.system, surfaceId, parameter)
        mc.operands.push({ parameter, surface_id: isSystemConfigParam(parameter) ? null : surfaceId, values: mc.names.map(() => v) })
        // temperature and pressure act only through the environment model: turn it on in the same step
        if (parameter === 'temperature' || parameter === 'pressure') p.system.environment_enabled = true
        // a base variable on this parameter would have no effect any more
        const vp = (Object.entries(CONFIG_OF_VARIABLE) as [VariableParam, ConfigParameter][]).find(([, c]) => c === parameter)?.[0]
        if (vp) p.optimization.variables = p.optimization.variables.filter((x) => !(x.surface_id === surfaceId && x.parameter === vp && (x.configuration ?? null) === null))
      }),

    removeConfigOperand: (row) =>
      get().commit('Remove configuration row', (p) => {
        const mc = p.system.multi_config
        if (!mc) return
        const op = mc.operands[row]
        if (!op) return
        mc.operands.splice(row, 1)
        const vp = (Object.entries(CONFIG_OF_VARIABLE) as [VariableParam, ConfigParameter][]).find(([, c]) => c === op.parameter)?.[0]
        if (vp) p.optimization.variables = p.optimization.variables.filter((x) => !(x.surface_id === op.surface_id && x.parameter === vp && x.configuration !== null && x.configuration !== undefined))
      }),

    setConfigValue: (row, k, value) =>
      get().commit(`Configuration ${k + 1} value`, (p) => {
        const op = p.system.multi_config?.operands[row]
        if (op) op.values[k] = value
      }),

    replaceSystem: (s, label, revisionLabel) =>
      get().commit(label, (p) => {
        p.revisions.push({ id: newId(), timestamp: nowIso(), label: revisionLabel ?? `Before: ${label}`, system: cloneSystem(p.system) })
        if (p.revisions.length > 50) p.revisions.splice(0, p.revisions.length - 50)
        p.system = cloneSystem(s)
        pruneReferences(p)
      }),

    addRevision: (label) =>
      get().commit(`Save revision "${label}"`, (p) => {
        p.revisions.push({ id: newId(), timestamp: nowIso(), label, system: cloneSystem(p.system) })
        if (p.revisions.length > 50) p.revisions.splice(0, p.revisions.length - 50)
      }),

    restoreRevision: (id) => {
      const rev = get().project.revisions.find((r) => r.id === id)
      if (!rev) return
      get().commit(`Restore revision "${rev.label}"`, (p) => {
        p.revisions.push({ id: newId(), timestamp: nowIso(), label: `Before restoring "${rev.label}"`, system: cloneSystem(p.system) })
        p.system = cloneSystem(rev.system)
        pruneReferences(p)
      })
    },

    deleteRevision: (id) =>
      get().commit('Delete revision', (p) => {
        p.revisions = p.revisions.filter((r) => r.id !== id)
      }),

    setMetadata: (patch) =>
      get().commit('Edit project info', (p) => {
        Object.assign(p.metadata, patch)
      }),

    updateProject: (fn, label) => get().commit(label, fn),
    beginGesture: () => {
      gesture = true
      gestureRecorded = false
      gestureLabel = null
    },
    endGesture: () => {
      gesture = false
      gestureRecorded = false
      gestureLabel = null
    },
  }
})

export function defaultBounds(s: OpticalSystem, surfaceId: string, parameter: VariableParam): Variable {
  const surf = s.surfaces.find((x) => x.id === surfaceId)
  let min: number | null = null
  let max: number | null = null
  if (parameter === 'thickness' && surf) {
    const t = surf.thickness ?? 0
    const glass = !['AIR', 'MIRROR', 'VACUUM'].includes(surf.material)
    min = glass ? 0.5 : t < 0 ? t * 3 : 0
    max = t < 0 ? 0 : Math.max(10, Math.abs(t) * 3)
  }
  // curvature: unbounded by default (bounds in 1/mm can be added; global and
  // multistart algorithms require them)
  if (parameter === 'conic') {
    min = -10
    max = 10
  }
  if (parameter === 'coating_scale') {
    min = 0.5
    max = 2
  }
  // effective spacer expansion (1e-6/K): a two-material spacer can reach negative values
  if (parameter === 'mount_cte') {
    min = -20
    max = 60
  }
  if (parameter.startsWith('coat_layer_')) {
    min = 0
    max = 1000
  }
  return { surface_id: surfaceId, parameter, min, max, enabled: true }
}

export const isDirty = (s: ProjectState) => s.savedKey !== projectKey(s.project)

const NO_SOURCES: LightSource[] = []
const NO_DETECTORS: DetectorSpec[] = []
/** Selectors with a stable empty value (older projects have no sources/detectors). */
export const selectSources = (s: { project: Project }) => s.project.sources ?? NO_SOURCES
export const selectDetectors = (s: { project: Project }) => s.project.detectors ?? NO_DETECTORS
