import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it } from 'vitest'
import { blankProject } from '../../lib/project'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { SystemCard } from './SystemCard'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('System card', () => {
  it('renders every checklist item and opens the right editor on click', () => {
    useEngineStore.setState({ backend: 'offline' })
    useProjectStore.getState().setProject(blankProject(), { saved: true })
    useUiStore.setState({ workspace: 'design', bottomTab: 'lde', bottomOpen: false })
    const el = document.createElement('div')
    document.body.appendChild(el)
    const root = createRoot(el)
    act(() => root.render(<SystemCard />))
    const rows = [...el.querySelectorAll('li button[aria-label]')]
    expect(rows.length).toBe(7)
    act(() => (rows[0] as HTMLButtonElement).click()) // aperture
    expect(useUiStore.getState()).toMatchObject({ bottomTab: 'system', bottomOpen: true })
    act(() => (rows[5] as HTMLButtonElement).click()) // variables and merit: nothing yet → the optimisation wizard
    expect(useUiStore.getState().dialog).toBe('optWizard')
    act(() => useUiStore.getState().closeDialog())
    act(() => (rows[6] as HTMLButtonElement).click()) // optimised → the Optimize workspace
    expect(useUiStore.getState()).toMatchObject({ workspace: 'optimize', bottomTab: 'optimization' })
    // a spec target is stored in analysis_settings as one undoable edit
    const specs = [...el.querySelectorAll('button[aria-expanded]')].find((b) => b.textContent?.includes('Spec')) as HTMLButtonElement
    act(() => specs.click())
    expect(el.querySelectorAll('tbody tr').length).toBe(4)
    act(() => root.unmount())
    el.remove()
  })

  it('shows what limits the image and opens the advisor', () => {
    useEngineStore.setState({ backend: 'offline', analyses: { advisor: { key: 'k', data: { findings: [{ kind: 'field_curvature', field: 1, rms_waves: 0.4 }, { kind: 'aberration', field: 1, class: 'coma', share: 0.6, rms_waves: 0.2, blur_rms_waves: 0.3 }, { kind: 'axial_colour', value_um: 80, ratio: 4 }] }, error: null, loading: false, ms: null } } })
    useProjectStore.getState().setProject(blankProject(), { saved: true })
    useUiStore.setState({ workspace: 'design', split: true, leftView: 'layout2d', rightView: 'spot', focusedPane: 'right', lang: 'en' })
    const el = document.createElement('div')
    document.body.appendChild(el)
    const root = createRoot(el)
    act(() => root.render(<SystemCard />))
    const row = [...el.querySelectorAll('li button[aria-label]')].find((b) => b.getAttribute('aria-label')?.startsWith('Image:')) as HTMLButtonElement
    expect(row.getAttribute('aria-label')).toBe('Image: field curvature, coma, axial colour')
    expect(row.textContent).toContain('field curvature, coma +1')
    act(() => row.click())
    expect(useUiStore.getState().rightView).toBe('advisor')
    act(() => root.unmount())
    el.remove()
    useEngineStore.setState({ analyses: {} })
  })
})
