import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { openProject } from '../actions'
import { api } from '../lib/api'
import { blankProject } from '../lib/project'
import type { OptimizationResult, Project } from '../lib/types'
import { useEngineStore } from '../store/engineStore'
import { useOptStore } from '../store/optStore'
import { useProjectStore } from '../store/projectStore'

vi.mock('../components/common/Plot', async (orig) => ({ ...(await orig<object>()), Plot: () => null }))
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function twoProjects(): { a: Project; b: Project } {
  const a = blankProject('A')
  a.optimization.variables = [{ surface_id: a.system.surfaces[2].id, parameter: 'thickness', min: 0, max: 200, enabled: true }]
  a.optimization.operands = [{ type: 'rms_spot', target: 0, weight: 1, field: null, wavelength: null, surface_id: null, rings: 3, reference: 'centroid', enabled: true }]
  const b: Project = JSON.parse(JSON.stringify(a))
  b.id = 'project-b'
  b.metadata.name = 'B'
  b.system.surfaces[1].radius = 60
  b.system.surfaces[2].thickness = 40
  return { a, b }
}

function resultFor(a: Project, t: number): OptimizationResult {
  const sys = JSON.parse(JSON.stringify(a.system))
  sys.name = 'A optimised'
  sys.surfaces[2].thickness = t
  return {
    status: 'converged', message: 'ok', algorithm: 'local', initial_merit: 1, final_merit: 0.5, improvement_percent: 50, evaluations: 10,
    variables: [{ surface_id: a.system.surfaces[2].id, parameter: 'thickness', initial: 95, final: t, min: 0, max: 200, at_bound: false, sensitivity: null }],
    operands_before: [], operands_after: [], history: [], system: sys, elapsed_s: 1, notes: [],
  }
}

async function finishedRunInA(a: Project) {
  vi.spyOn(api, 'optimizeStart').mockResolvedValue({ job_id: 'j' })
  vi.spyOn(api, 'optimizeStatus').mockResolvedValue({ id: 'j', state: 'finished', result: resultFor(a, 97.25) } as never)
  vi.spyOn(api, 'optimizeCompare').mockRejectedValue(new Error('no engine'))
  await useOptStore.getState().start()
  await vi.advanceTimersByTimeAsync(200)
}

describe('optimisation state across a project switch', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    useOptStore.getState().discard()
  })

  it('a run of project A stops previewing in the views when project B is opened', async () => {
    vi.useFakeTimers()
    const { a, b } = twoProjects()
    openProject(a)
    let calls = 0
    vi.spyOn(api, 'optimizeStart').mockResolvedValue({ job_id: 'j' })
    vi.spyOn(api, 'optimizeCancel').mockResolvedValue({ ok: true })
    vi.spyOn(api, 'optimizeStatus').mockImplementation(async () => {
      calls++
      return { id: 'j', state: 'running', phase: 'local', evaluations: calls, initial_merit: 1, current_merit: 1, best_merit: 1, best_values: [97.25], history: [], elapsed_s: 0, error: null, result: null } as never
    })
    vi.spyOn(api, 'optimizeCompare').mockRejectedValue(new Error('no engine'))
    await useOptStore.getState().start()
    await vi.advanceTimersByTimeAsync(200)
    openProject(b)
    expect(useEngineStore.getState().preview).toBeNull()
    await vi.advanceTimersByTimeAsync(2000)
    expect(useProjectStore.getState().project.metadata.name).toBe('B')
    const preview = useEngineStore.getState().preview
    expect(preview?.surfaces[1].radius ?? null).not.toBe(100) // no preview of A's design (radius 100; B has 60)
  })

  it('opening project B drops the finished optimisation result of project A', async () => {
    vi.useFakeTimers()
    const { a, b } = twoProjects()
    openProject(a)
    await finishedRunInA(a)
    expect(useOptStore.getState().result).not.toBeNull()
    openProject(b)
    expect(useOptStore.getState().result).toBeNull() // A's result is dropped
  })

  it('Apply in project B does not write the values optimised for project A', async () => {
    vi.useFakeTimers()
    const { a, b } = twoProjects()
    openProject(a)
    await finishedRunInA(a)
    vi.useRealTimers()
    // the result is still there if it was not discarded: it must not be applicable to B
    const kept = useOptStore.getState().result
    openProject(b)
    if (kept && !useOptStore.getState().result) useOptStore.setState({ result: kept })
    const { OptimizationPanel } = await import('../components/editors/OptimizationPanel')
    const el = document.createElement('div')
    document.body.appendChild(el)
    const root = createRoot(el)
    act(() => root.render(<OptimizationPanel />))
    const apply = [...el.querySelectorAll('button')].find((x) => x.textContent?.includes('Apply as new revision'))
    if (apply) act(() => apply.click())
    act(() => root.unmount())
    el.remove()
    expect(useProjectStore.getState().project.metadata.name).toBe('B')
    expect(useProjectStore.getState().project.system.surfaces[2].thickness).toBe(40) // not A's optimised 97.25
  })

  it('the engineering report of project B leaves out the unapplied optimisation of project A', async () => {
    vi.useFakeTimers()
    const { a, b } = twoProjects()
    openProject(a)
    await finishedRunInA(a)
    vi.useRealTimers()
    const kept = useOptStore.getState().result
    openProject(b)
    if (kept && !useOptStore.getState().result) useOptStore.setState({ result: kept })
    const report = await import('../lib/report')
    const build = vi.spyOn(report, 'buildReportHtml')
    vi.spyOn(report, 'collectReportData').mockResolvedValue({ errors: [] } as never)
    const storage = await import('../lib/storage')
    vi.spyOn(storage, 'downloadText').mockImplementation(() => undefined)
    build.mockResolvedValue('<html></html>')
    const { generateReport } = await import('../actions')
    await generateReport()
    expect(build).toHaveBeenCalled()
    const opts = build.mock.calls[0][2] as { optimization: OptimizationResult | null }
    expect(opts.optimization).toBeNull() // not A's result
  })
})
