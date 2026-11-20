import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../lib/api'
import { DEFAULT_FIRST_LENS, stepValid } from '../../lib/firstLens'
import { blankProject } from '../../lib/project'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { FirstLensDialog } from './FirstLensDialog'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

afterEach(() => vi.restoreAllMocks())

const click = (el: Element | null | undefined) => act(() => (el as HTMLButtonElement).click())
const byText = (root: Element, text: string) => [...root.querySelectorAll('button')].find((b) => b.textContent?.includes(text))

describe('First lens', () => {
  it('validates the steps', () => {
    expect(stepValid(0, DEFAULT_FIRST_LENS)).toBe(true)
    expect(stepValid(0, { ...DEFAULT_FIRST_LENS, f_number: 0.2 })).toBe(false)
    expect(stepValid(2, { ...DEFAULT_FIRST_LENS, kind: 'doublet', preset: 'hene' })).toBe(false)
    expect(stepValid(2, { ...DEFAULT_FIRST_LENS, kind: 'doublet' })).toBe(true)
  })

  it('sends the inputs to the engine and opens the lens in Design with layout and spot', async () => {
    useEngineStore.setState({ backend: 'online', materials: [] })
    useProjectStore.getState().setProject(blankProject(), { saved: true })
    useUiStore.setState({ lang: 'en', workspace: 'optimize', dialog: 'firstLens', nextHint: null })
    const engineProject = { ...blankProject(), metadata: { ...blankProject().metadata, name: 'Achromat f = 100 mm F/5' } }
    const call = vi.spyOn(api, 'firstLens').mockResolvedValue({ project: engineProject, notes: [], design: {} })
    vi.spyOn(api, 'optimizeStart').mockRejectedValue(new Error('no engine in tests'))
    const el = document.createElement('div')
    document.body.appendChild(el)
    const root = createRoot(el)
    act(() => root.render(<FirstLensDialog />))
    click(byText(el, 'Next'))
    click(byText(el, 'Visible: F, d, C'))
    click(byText(el, 'Next'))
    click(byText(el, 'Cemented doublet'))
    await act(async () => {
      ;(byText(el, 'Create lens') as HTMLButtonElement).click()
    })
    expect(call).toHaveBeenCalledWith(expect.objectContaining({ focal_length: 100, f_number: 5, half_field_deg: 2, kind: 'doublet', crown: 'N-BK7', flint: 'F2', wavelengths: [0.4861327, 0.5875618, 0.6562725], primary: 1, name: 'Achromat f = 100 mm F/5' }))
    const ui = useUiStore.getState()
    expect([ui.workspace, ui.leftView, ui.rightView, ui.nextHint]).toEqual(['design', 'layout2d', 'spot', 'optimise'])
    expect(useProjectStore.getState().project.metadata.name).toBe('Achromat f = 100 mm F/5')
    act(() => root.unmount())
    el.remove()
  })
})
