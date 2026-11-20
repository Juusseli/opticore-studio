import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { openProject } from '../actions'
import { api } from '../lib/api'
import { blankProject, defaultDetector, defaultSource } from '../lib/project'
import type { CadAsset, Project } from '../lib/types'
import { useEngineStore } from '../store/engineStore'
import { useProjectStore } from '../store/projectStore'
import { useUiStore } from '../store/uiStore'

vi.mock('../components/common/Plot', async (orig) => ({ ...(await orig<object>()), Plot: () => null }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const flush = () => act(async () => void (await new Promise((r) => setTimeout(r, 0))))
function mount(node: React.ReactNode) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const root = createRoot(el)
  act(() => root.render(node))
  return { el, done: () => (act(() => root.unmount()), el.remove()) }
}
const byTitle = (el: HTMLElement, title: string) => [...el.querySelectorAll('button')].filter((b) => b.getAttribute('title') === title)
function typeInto(input: HTMLInputElement, text: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  act(() => {
    set.call(input, text)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  act(() => void input.dispatchEvent(new FocusEvent('focusout', { bubbles: true })))
}
function cadAsset(optical: CadAsset['optical'], part_roles?: CadAsset['part_roles']): CadAsset {
  return {
    id: 'cad1', name: 'Window', source_filename: 'w.stl', format: 'stl', units: 'mm', imported: '', mesh: { positions_b64: '', indices_b64: '', vertices: 0, triangles: 0 },
    bbox_min: [0, 0, 0], bbox_max: [1, 1, 1], surface_area_mm2: 1, volume_mm3: 1, closed: true, diagnostics: [], transform: { translate: [0, 0, 0], rotate_deg: [0, 0, 0] },
    optical, part_roles, visible: true, color: '#888', opacity: 0.5,
  }
}

describe('references left behind by delete/rename in the editors', () => {
  beforeEach(() => {
    useUiStore.getState().setLang('en')
    useEngineStore.setState({ backend: 'offline', coatings: [], materials: [] })
  })
  afterEach(() => vi.restoreAllMocks())

  it('deleting a detector leaves no active detector operand on its id', async () => {
    const p = blankProject('D')
    const det = defaultDetector({ name: 'PD' })
    p.sources = [defaultSource()]
    p.detectors = [det]
    p.optimization.operands = [{ type: 'detector_power', target: 1, weight: 1, field: null, wavelength: null, surface_id: null, rings: 3, reference: 'centroid', detector_id: det.id, enabled: true }]
    openProject(p)
    const { SourcesPanel } = await import('../components/editors/SourcesPanel')
    const m = mount(<SourcesPanel />)
    const del = byTitle(m.el, 'Delete')
    expect(del.length).toBe(2)
    act(() => del[1].click())
    await flush()
    m.done()
    const q = useProjectStore.getState().project
    expect(q.detectors).toHaveLength(0)
    const ids = new Set((q.detectors ?? []).map((d) => d.id))
    expect(q.optimization.operands.filter((o) => o.enabled && o.detector_id && !ids.has(o.detector_id))).toEqual([])
  })

  it('renaming a project coating renames it on the CAD bodies too', async () => {
    const p: Project = blankProject('C')
    p.system.custom_coatings = [{ name: 'MYAR', description: '', layers: [{ material: '', index: 1.38, extinction: 0, thickness_nm: 100 }], substrate_index: null, substrate_extinction: 0 }]
    p.cad_assets = [cadAsset({ role: 'refractive', material: 'N-BK7', coating: 'MYAR' }, { '1.1': { role: 'refractive', material: 'N-BK7', coating: 'MYAR' } })]
    openProject(p)
    const { CoatingEditor } = await import('../components/dialogs/CoatingEditor')
    const m = mount(<CoatingEditor />)
    typeInto(m.el.querySelector('input[aria-label="Coating name"]') as HTMLInputElement, 'MYAR2')
    act(() => [...m.el.querySelectorAll('button')].find((b) => b.textContent?.includes('Save to project'))!.click())
    m.done()
    const q = useProjectStore.getState().project
    expect(q.system.custom_coatings!.map((c) => c.name)).toEqual(['MYAR2'])
    expect(q.cad_assets[0].optical?.coating).toBe('MYAR2')
    expect(q.cad_assets[0].part_roles?.['1.1'].coating).toBe('MYAR2')
  })

  it('deleting a project coating used only by a CAD body leaves no CAD body on a missing coating', async () => {
    const p: Project = blankProject('C')
    p.system.custom_coatings = [{ name: 'MYAR', description: '', layers: [{ material: '', index: 1.38, extinction: 0, thickness_nm: 100 }], substrate_index: null, substrate_extinction: 0 }]
    p.cad_assets = [cadAsset({ role: 'refractive', material: 'N-BK7', coating: 'MYAR' })]
    openProject(p)
    const { CoatingEditor } = await import('../components/dialogs/CoatingEditor')
    const m = mount(<CoatingEditor />)
    act(() => byTitle(m.el, 'Delete coating')[0].click())
    m.done()
    const q = useProjectStore.getState().project
    const names = new Set((q.system.custom_coatings ?? []).map((c) => c.name))
    expect(names.has('MYAR') || q.cad_assets[0].optical?.coating !== 'MYAR').toBe(true)
  })

  it('deleting a custom material leaves no surface or CAD body on a missing material', async () => {
    const p: Project = blankProject('M')
    p.custom_materials = [{ name: 'MYGLASS', formula: 'constant', coefficients: [1.6] }]
    p.system.surfaces[1].material = 'MYGLASS'
    p.cad_assets = [cadAsset({ role: 'refractive', material: 'MYGLASS' })]
    openProject(p)
    vi.spyOn(api, 'validateMaterial').mockResolvedValue({ material: { name: 'MYGLASS', formula: 'constant', coefficients: [1.6], nd: 1.6, vd: null, nF_minus_nC: 0, has_thermal_model: false, builtin: false } } as never)
    vi.spyOn(api, 'materialCurves').mockRejectedValue(new Error('offline'))
    vi.spyOn(api, 'resolveIndex').mockRejectedValue(new Error('offline'))
    const { MaterialBrowser } = await import('../components/dialogs/MaterialBrowser')
    const m = mount(<MaterialBrowser />)
    await flush()
    const row = [...m.el.querySelectorAll('tr')].find((r) => r.textContent?.includes('MYGLASS') && r.classList.contains('cursor-pointer'))!
    act(() => row.click())
    act(() => byTitle(m.el, 'Delete custom material')[0].click())
    m.done()
    const q = useProjectStore.getState().project
    const known = new Set(q.custom_materials.map((x) => x.name))
    const users = [q.system.surfaces[1].material, q.cad_assets[0].optical?.material].filter((x) => x === 'MYGLASS')
    expect(users.every((x) => known.has(x!))).toBe(true)
  })
})
