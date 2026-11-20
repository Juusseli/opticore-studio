import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../../lib/api'
import { blankProject } from '../../lib/project'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { AnalysisFrame } from './AnalysisFrame'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('analysis that does not apply to the design', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    useEngineStore.setState({ analyses: {} })
  })

  it('keeps the engine code and shows the reason without a failure or a retry', async () => {
    useProjectStore.getState().setProject(blankProject('NA'))
    useUiStore.setState({ lang: 'en' })
    useEngineStore.setState({ backend: 'online' })
    vi.spyOn(api, 'ghosts').mockRejectedValue(new ApiError(422, 'NOT_APPLICABLE', 'Ghost analysis currently supports refractive systems without mirrors'))
    await useEngineStore.getState().runAnalysis('ghosts', {}, true)
    expect(useEngineStore.getState().analyses.ghosts?.code).toBe('NOT_APPLICABLE')
    const el = document.createElement('div')
    document.body.appendChild(el)
    const root = createRoot(el)
    const st = useEngineStore.getState().analyses.ghosts!
    act(() =>
      root.render(
        <AnalysisFrame kind="ghosts" title="Ghosts" loading={false} error={st.error} hasData={false} ms={null} onRefresh={() => undefined} settings={{}} result={null}>
          <div />
        </AnalysisFrame>,
      ),
    )
    expect(el.textContent).toContain('Not available for this design')
    expect(el.textContent).toContain('refractive systems without mirrors')
    expect(el.textContent).not.toContain('This analysis failed')
    expect(el.textContent).not.toMatch(/Try again/)
    act(() => root.unmount())
    el.remove()
  })
})
