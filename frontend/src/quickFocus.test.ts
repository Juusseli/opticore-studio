import { afterEach, describe, expect, it, vi } from 'vitest'
import { quickFocus } from './actions'
import { api } from './lib/api'
import { blankProject } from './lib/project'
import { quickFocusSetup } from './lib/quickFocus'
import type { OptimizationSpec, Project } from './lib/types'
import { useProjectStore } from './store/projectStore'

const finished = (final: number) => ({ id: 'q', state: 'finished', result: { variables: [{ final }], initial_merit: 0.01, final_merit: 0.005 } }) as never
const imageDistance = () => {
  const s = useProjectStore.getState().project.system
  return s.surfaces[s.surfaces.length - 2].thickness
}

/** A blank lens whose image distance is set per configuration (90 / 120 mm), the second configuration active. */
function twoConjugates(): Project {
  const p = blankProject('Two conjugates')
  const last = p.system.surfaces[p.system.surfaces.length - 2]
  p.system.multi_config = { names: ['far', 'near'], operands: [{ parameter: 'thickness', surface_id: last.id, values: [90, 120] }], active: 1 }
  return p
}

async function run(status: () => Promise<unknown>) {
  vi.useFakeTimers()
  vi.spyOn(api, 'focus').mockResolvedValue(null as never)
  const start = vi.spyOn(api, 'optimizeStart').mockResolvedValue({ job_id: 'q' })
  vi.spyOn(api, 'optimizeStatus').mockImplementation(status as never)
  const done = quickFocus()
  await vi.advanceTimersByTimeAsync(400)
  await done
  return start.mock.calls[0]?.[0] as { optimization: OptimizationSpec } | undefined
}

describe('quick focus', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('moves the image surface of the design it was computed for', async () => {
    useProjectStore.getState().setProject(blankProject('A'))
    await run(async () => finished(97.5))
    expect(imageDistance()).toBe(97.5)
  })

  it('leaves a project opened while it ran alone, and a design edited meanwhile', async () => {
    useProjectStore.getState().setProject(blankProject('A'))
    const b = blankProject('B')
    b.system.surfaces[b.system.surfaces.length - 2].thickness = 55
    await run(async () => {
      useProjectStore.getState().setProject(b)
      return finished(87)
    })
    expect(useProjectStore.getState().project.metadata.name).toBe('B')
    expect(imageDistance()).toBe(55)
    // the same project, edited while the focus ran: the result belongs to the earlier design
    useProjectStore.getState().setProject(blankProject('C'))
    await run(async () => {
      useProjectStore.getState().updateSurface(1, { radius: 80 }, 'edit')
      return finished(87)
    })
    expect(imageDistance()).toBe(95)
  })

  it('focuses an image distance set per configuration in the active configuration', async () => {
    const p = twoConjugates()
    const setup = quickFocusSetup(p.system)!
    expect([setup.configuration, setup.t0, setup.row]).toEqual([1, 120, 0])
    expect(quickFocusSetup(blankProject().system)?.configuration).toBeNull()
    p.system.multi_config!.operands[0].values[1] = null
    expect(quickFocusSetup(p.system)).toBeNull()

    useProjectStore.getState().setProject(twoConjugates())
    const req = await run(async () => finished(118))
    expect(req?.optimization.variables[0]).toMatchObject({ parameter: 'thickness', configuration: 1 })
    const s = useProjectStore.getState().project.system
    expect(s.multi_config!.operands[0].values).toEqual([90, 118])
    expect(imageDistance()).toBe(95) // the shared value stays
  })
})
