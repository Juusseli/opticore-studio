import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import { blankProject } from '../lib/project'
import { useEngineStore } from './engineStore'
import { useOptStore } from './optStore'
import { useProjectStore } from './projectStore'

const preview = () => useEngineStore.getState().preview

describe('optimisation result preview', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    useOptStore.getState().discard()
  })

  it('keeps the finished result on screen until it is applied, discarded or the design is edited', async () => {
    vi.useFakeTimers()
    useProjectStore.getState().setProject(blankProject('Opt'))
    const optimised = { ...useProjectStore.getState().project.system, name: 'optimised' }
    vi.spyOn(api, 'optimizeStart').mockResolvedValue({ job_id: 'j' })
    vi.spyOn(api, 'optimizeStatus').mockResolvedValue({
      id: 'j',
      state: 'finished',
      result: { system: optimised, notes: [], initial_merit: 1, final_merit: 0.5, evaluations: 3, elapsed_s: 1, variables: [], status: 'converged' },
    } as never)
    vi.spyOn(api, 'spot').mockRejectedValue(new Error('no engine'))
    await useOptStore.getState().start()
    await vi.advanceTimersByTimeAsync(200)
    expect(preview()?.name).toBe('optimised')
    // compare before and after in every view
    useOptStore.getState().show('original')
    expect(preview()).toBeNull()
    useOptStore.getState().show('result')
    expect(preview()?.name).toBe('optimised')
    // an edit shows the edited design (the result can still be applied)
    useProjectStore.getState().updateSurface(1, { radius: 42 }, 'edit')
    expect(preview()).toBeNull()
    expect(useOptStore.getState().showing).toBe('original')
    expect(useOptStore.getState().result).not.toBeNull()
    useOptStore.getState().show('result')
    useOptStore.getState().discard()
    expect(preview()).toBeNull()
  })
})
