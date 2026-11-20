import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { openProject } from '../actions'
import { api } from '../lib/api'
import { blankProject, defaultSurface } from '../lib/project'
import type { Project } from '../lib/types'
import { useEngineStore } from '../store/engineStore'
import { useProjectStore } from '../store/projectStore'
import { useUiStore } from '../store/uiStore'

vi.mock('../components/common/Plot', async (orig) => ({ ...(await orig<object>()), Plot: () => null }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}
const flush = () => act(async () => void (await new Promise((r) => setTimeout(r, 0))))
function mount(node: React.ReactNode) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const root = createRoot(el)
  act(() => root.render(node))
  return { el, done: () => (act(() => root.unmount()), el.remove()) }
}
const button = (el: HTMLElement, text: string) => [...el.querySelectorAll('button')].find((b) => b.textContent?.trim().includes(text))!

describe('engine results written after the open project changed', () => {
  beforeEach(() => {
    useUiStore.getState().setLang('en')
    useEngineStore.setState({ backend: 'online' })
  })
  afterEach(() => vi.restoreAllMocks())

  it('Set vignetting that finishes after another project was opened leaves the fields of that project alone', async () => {
    const a = blankProject('A')
    a.system.fields = [{ x: 0, y: 0, weight: 1 }, { x: 0, y: 3, weight: 1 }]
    const b = blankProject('B')
    b.system.fields = [{ x: 0, y: 0, weight: 1 }, { x: 0, y: 10, weight: 1 }, { x: 0, y: 20, weight: 1 }]
    openProject(a)
    const d = deferred<Awaited<ReturnType<typeof api.vignetting>>>()
    vi.spyOn(api, 'vignetting').mockReturnValue(d.promise)
    const { SystemEditor } = await import('../components/editors/SystemEditor')
    const m = mount(<SystemEditor />)
    act(() => button(m.el, 'Set vignetting').click())
    openProject(b)
    d.resolve({ fields: [{ ok: true, vdx: 0, vdy: 0.1, vcx: 0, vcy: 0.2 }, { ok: true, vdx: 0, vdy: 0.1, vcx: 0, vcy: 0.2 }] } as never)
    await flush()
    m.done()
    const f = useProjectStore.getState().project.system.fields
    expect(useProjectStore.getState().project.metadata.name).toBe('B')
    expect(f.map((x) => x.y)).toEqual([0, 10, 20]) // B's own fields, not A's [0, 3]
  })

  it('Set vignetting keeps a field added while it ran', async () => {
    openProject(blankProject('A'))
    const d = deferred<Awaited<ReturnType<typeof api.vignetting>>>()
    vi.spyOn(api, 'vignetting').mockReturnValue(d.promise)
    const { SystemEditor } = await import('../components/editors/SystemEditor')
    const m = mount(<SystemEditor />)
    act(() => button(m.el, 'Set vignetting').click())
    const s = useProjectStore.getState()
    s.setFields([...s.project.system.fields, { x: 0, y: 5, weight: 1 }])
    d.resolve({ fields: [{ ok: true, vdx: 0, vdy: 0, vcx: 0, vcy: 0 }, { ok: true, vdx: 0, vdy: 0.1, vcx: 0, vcy: 0.2 }] } as never)
    await flush()
    m.done()
    expect(useProjectStore.getState().project.system.fields.length).toBe(3) // the added field is kept
  })

  it('Convert to Qcon that finishes after another project was opened does not convert the surface of that project', async () => {
    const a = blankProject('A')
    a.system.surfaces[2] = defaultSurface({ ...a.system.surfaces[2], type: 'even_asphere', aspheric: [1e-6] })
    const b: Project = blankProject('B')
    openProject(a)
    useProjectStore.setState({ selection: [2] })
    const d = deferred<Awaited<ReturnType<typeof api.convertQ>>>()
    vi.spyOn(api, 'convertQ').mockReturnValue(d.promise)
    const { Inspector } = await import('../components/panels/Inspector')
    const m = mount(<Inspector />)
    act(() => button(m.el, 'Qcon').click())
    openProject(b)
    useProjectStore.setState({ selection: [2] })
    d.resolve({ surface: { type: 'qcon', radius: -100, conic: 0, aspheric: [], q_coefficients: [0.01], q_norm_radius: 9 }, residual_rms_mm: 0, residual_max_mm: 0, norm_radius_mm: 9 })
    await flush()
    m.done()
    const s2 = useProjectStore.getState().project.system.surfaces[2]
    expect(useProjectStore.getState().project.metadata.name).toBe('B')
    expect(s2.type).toBe('standard') // B's surface is not converted
  })

  it('default tolerances computed for project A are not written into project B', async () => {
    const a = blankProject('A')
    openProject(a)
    const d = deferred<Awaited<ReturnType<typeof api.toleranceDefault>>>()
    vi.spyOn(api, 'toleranceDefault').mockReturnValue(d.promise)
    const { TolerancePanel } = await import('../components/editors/TolerancePanel')
    const m = mount(<TolerancePanel />)
    act(() => button(m.el, 'Defaults').click())
    openProject(blankProject('B'))
    const tol = { ...a.tolerancing, tolerances: [{ id: 't1', type: 'radius', surface_id: a.system.surfaces[1].id, surface_id_end: null, min: -0.1, max: 0.1, enabled: true }], compensators: [] }
    d.resolve({ tolerance: tol } as never)
    await flush()
    m.done()
    const p = useProjectStore.getState().project
    expect(p.metadata.name).toBe('B')
    const ids = new Set(p.system.surfaces.map((s) => s.id))
    expect(p.tolerancing.tolerances.filter((x) => !ids.has(x.surface_id))).toEqual([])
  })
})
