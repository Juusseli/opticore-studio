import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { importCadFile, openDesignCandidate, openProject } from '../actions'
import { api } from '../lib/api'
import { blankProject, defaultSource } from '../lib/project'
import type { FdtdResult } from '../lib/types'
import { useDesignSpaceStore } from '../store/designSpaceStore'
import { useEngineStore } from '../store/engineStore'
import { useFdtdStore } from '../store/fdtdStore'
import { useProjectStore } from '../store/projectStore'
import { useUiStore } from '../store/uiStore'

vi.mock('../components/common/Plot', async (orig) => ({ ...(await orig<object>()), Plot: () => null }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}

describe('session results and long requests across a project switch', () => {
  beforeEach(() => useUiStore.getState().setLang('en'))
  afterEach(() => vi.restoreAllMocks())

  it('opening project B clears the evaluation of A (layout, messages), and a late answer for A is dropped', async () => {
    openProject(blankProject('A'))
    const d = deferred<unknown>()
    vi.spyOn(api, 'evaluate').mockReturnValue(d.promise as never)
    const pending = useEngineStore.getState().evaluate(true)
    useEngineStore.setState({ evaluation: { diagnostics: [{ code: 'SHOWN_FOR_A' }] } as never })
    openProject(blankProject('B'))
    expect(useEngineStore.getState().evaluation).toBeNull()
    d.resolve({ diagnostics: [{ code: 'LATE_FOR_A' }] })
    await pending
    expect(useEngineStore.getState().evaluation).toBeNull()
  })

  it('opening project B clears the design space map of project A', async () => {
    openProject(blankProject('A'))
    useDesignSpaceStore.setState({ job: { id: 'ds', state: 'finished', total: 1, done: 1, failed: 0, elapsed_s: 1 }, candidates: { 0: { index: 0, status: 'finished' } as never }, order: [0], selected: 0 } as never)
    openProject(blankProject('B'))
    expect(useDesignSpaceStore.getState().job).toBeNull()
  })

  it('applying a design-space candidate as a revision leaves no anchors or tolerances on the replaced surfaces', async () => {
    const p = blankProject('A')
    const s1 = p.system.surfaces[1].id
    p.sources = [defaultSource({ placement: { position: [0, 0, 0], rotation_deg: [0, 0, 0], anchor: s1 } })]
    p.tolerancing.tolerances = [{ id: 't', type: 'radius', surface_id: s1, surface_id_end: null, min: -0.1, max: 0.1, enabled: true }]
    openProject(p)
    const cand = blankProject('cand')
    vi.spyOn(api, 'designSpaceCandidate').mockResolvedValue({ title: 'doublet', project: { metadata: cand.metadata, system: cand.system, optimization: cand.optimization, custom_materials: [] } } as never)
    await openDesignCandidate('ds', 0, 'revision')
    const q = useProjectStore.getState().project
    const ids = new Set(q.system.surfaces.map((s) => s.id))
    const dangling = [...q.sources!.map((s) => s.placement.anchor), ...q.tolerancing.tolerances.map((t) => t.surface_id)].filter((a) => a && !ids.has(a))
    expect(dangling).toEqual([])
  })

  it('a STEP import that finishes after another project was opened does not land in that project', async () => {
    openProject(blankProject('A'))
    const d = deferred<Awaited<ReturnType<typeof api.importCad>>>()
    vi.spyOn(api, 'importCad').mockReturnValue(d.promise)
    const done = importCadFile(new File([new Uint8Array([1, 2, 3])], 'housing.step'))
    await new Promise((r) => setTimeout(r, 0))
    openProject(blankProject('B'))
    d.resolve({ name: 'housing', format: 'step', positions_b64: '', indices_b64: '', vertices: 0, triangles: 0, bbox_min: [0, 0, 0], bbox_max: [1, 1, 1], surface_area_mm2: 1, volume_mm3: 1, closed: true, diagnostics: [], bodies: [], source_b64: '', mesh_deflection_mm: 0.1, tree: [], size: [1, 1, 1] } as never)
    await done
    const q = useProjectStore.getState().project
    expect(q.metadata.name).toBe('B')
    expect(q.cad_assets).toHaveLength(0)
  })

  it('"Use as POP source" does not hand over a stale FDTD field', async () => {
    openProject(blankProject('B'))
    useEngineStore.setState({ backend: 'online' })
    const exported = { r_um: [0, 1], re: [1, 0.5], im: [0, 0], power: 1, wavelength_um: 1, n_medium: 1, z_um: 5, depolarised_fraction: 0 }
    const result = { geometry: 'axisymmetric', cells: [10, 10], dx_um: 0.03, steps: 100, convergence: 1e-4, polarization: 'x', exported_field: exported, z_um: [0, 1], y_um: [0, 1], intensity: [[0, 1], [1, 0]], field: [[0, 1], [1, 0]], index: [[1, 1], [1, 1]], monitors: { source_z: 0, reflection_z: 0, transmission_z: 5 }, notes: [], time_s: 1, method: '' } as unknown as FdtdResult
    useFdtdStore.setState({ job: null, result, resultKey: 'settings of another run', resultSpec: null, error: null })
    const { FdtdView } = await import('../components/views/WaveViews')
    const el = document.createElement('div')
    document.body.appendChild(el)
    const root = createRoot(el)
    act(() => root.render(<FdtdView />))
    expect(el.textContent).toContain('settings changed: run again')
    const btn = [...el.querySelectorAll('button')].find((b) => b.textContent?.includes('Use as POP source'))
    if (btn) act(() => btn.click())
    act(() => root.unmount())
    el.remove()
    const pop = useProjectStore.getState().project.analysis_settings.pop as { field_source?: unknown } | undefined
    expect(pop?.field_source).toBeUndefined()
  })
})
