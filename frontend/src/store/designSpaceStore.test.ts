import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { openDesignCandidate } from '../actions'
import { glassPool, specFromDesign } from '../components/views/designSpace'
import { api } from '../lib/api'
import { blankProject } from '../lib/project'
import type { DesignCandidate, DesignSpaceSnapshot, DesignSpaceSpec, MaterialRecord } from '../lib/types'
import { useDesignSpaceStore } from './designSpaceStore'
import { useProjectStore } from './projectStore'

const ds = () => useDesignSpaceStore.getState()
const st = () => useProjectStore.getState()

const cand = (index: number, rms: number, length: number): DesignCandidate => ({
  index,
  topology: 'cemented_doublet',
  glasses: ['N-BK7', 'F2'],
  variant: 0,
  title: `Cemented doublet ${index}`,
  status: 'finished',
  feasible: true,
  violations: [],
  metrics: {
    rms_spot_um: rms,
    rms_spot_max_um: rms,
    rms_spot_fields_um: [rms],
    mtf: 0.5,
    mtf_fields: [0.5],
    length_mm: length,
    mass_g: 5,
    glass_cost: null,
    distortion_pct: 0,
    abs_distortion_pct: 0,
    tolerance_rss_um: null,
    elements: 2,
    efl_mm: 100,
    fnum: 5,
    airy_radius_um: 3.6,
    rays_ok: true,
  },
})

const snap = (p: Partial<DesignSpaceSnapshot>): DesignSpaceSnapshot => ({
  id: 'j',
  state: 'running',
  total: 3,
  done: 0,
  failed: 0,
  elapsed_s: 1,
  error: null,
  since: 0,
  candidates: [],
  objectives: ['rms_spot_um', 'length_mm', 'mass_g'],
  pareto: [],
  topologies: ['cemented_doublet'],
  ...p,
})

const SPEC = { focal_length: 100, f_number: 5 } as DesignSpaceSpec

describe('design space map', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    st().setProject(blankProject('Map'))
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    useDesignSpaceStore.setState({ job: null, candidates: {}, order: [], pareto: [], objectives: [], front: 'default', selected: null })
  })

  it('collects the candidates as they finish, asking only for new ones, and keeps them after a cancel', async () => {
    vi.spyOn(api, 'designSpaceStart').mockResolvedValue({ job_id: 'j', total: 3 })
    const status = vi
      .spyOn(api, 'designSpaceStatus')
      .mockResolvedValueOnce(snap({ done: 2, candidates: [cand(2, 5, 100), cand(0, 9, 90)], pareto: [2, 0] }))
      .mockResolvedValueOnce(snap({ state: 'cancelled', done: 2, since: 2, candidates: [], pareto: [2, 0] }))
    const cancel = vi.spyOn(api, 'designSpaceCancel').mockResolvedValue({ ok: true })
    await ds().start(SPEC, [])
    await vi.advanceTimersByTimeAsync(400)
    expect(status).toHaveBeenLastCalledWith('j', 0, undefined)
    expect(ds().order).toEqual([2, 0])
    await ds().cancel()
    expect(cancel).toHaveBeenCalledWith('j')
    await vi.advanceTimersByTimeAsync(800)
    expect(status).toHaveBeenLastCalledWith('j', 2, undefined)
    expect(ds().job?.state).toBe('cancelled')
    expect(Object.keys(ds().candidates)).toHaveLength(2)
    expect(ds().pareto).toEqual([2, 0])
  })

  it('asks the engine for the front over the two axes when chosen', async () => {
    useDesignSpaceStore.setState({ job: { id: 'j', state: 'finished', total: 1, done: 1, failed: 0, elapsed_s: 1 }, order: [0], candidates: { 0: cand(0, 5, 100) } })
    const status = vi.spyOn(api, 'designSpaceStatus').mockResolvedValue(snap({ state: 'finished', done: 1, since: 1, objectives: ['length_mm', 'mtf'], pareto: [0] }))
    ds().setAxes({ x: 'length_mm', y: 'mtf' })
    expect(status).not.toHaveBeenCalled() // the default front does not depend on the axes
    ds().setFront('axes')
    await vi.advanceTimersByTimeAsync(0)
    expect(status).toHaveBeenLastCalledWith('j', 1, ['length_mm', 'mtf'])
    expect(ds().objectives).toEqual(['length_mm', 'mtf'])
  })

  it('applies a design as a new revision in one undo step', async () => {
    const p0 = st().project
    const next = { ...blankProject('Doublet').system, name: 'From the map' }
    vi.spyOn(api, 'designSpaceCandidate').mockResolvedValue({
      index: 4,
      title: 'Cemented doublet N-BK7/F2',
      metrics: cand(4, 5, 100).metrics!,
      project: {
        metadata: { name: 'Cemented doublet N-BK7/F2', description: '' },
        system: next,
        optimization: { ...p0.optimization, max_evaluations: 500 },
        custom_materials: [{ name: 'MY-GLASS', formula: 'sellmeier', coefficients: [1, 0.01, 0, 0, 0, 0] } as MaterialRecord],
      },
    })
    expect(await openDesignCandidate('j', 4, 'revision')).toBe(true)
    const p = st().project
    expect(p.system.name).toBe('From the map')
    expect(p.revisions.at(-1)?.label).toBe('Before design space: Cemented doublet N-BK7/F2')
    expect(p.custom_materials.map((m) => m.name)).toEqual(['MY-GLASS'])
    expect(p.optimization.max_evaluations).toBe(500)
    st().undo()
    expect(st().project.system).toEqual(p0.system)
    expect(st().project.revisions).toEqual(p0.revisions)
  })

  it('takes the specification from the design and builds the glass pool', () => {
    const p = blankProject('Spec')
    p.system.fields = [{ ...p.system.fields[0], y: 0 }, { ...p.system.fields[0], y: 7.5 }]
    expect(specFromDesign(p, { efl: 49.98765, image_space_fnum: 2.83456 })).toEqual({ focal_length: 49.99, f_number: 2.83, half_field_deg: 7.5 })
    expect(specFromDesign(p, null)).toEqual({ focal_length: 100, f_number: 5, half_field_deg: 7.5 })
    const own = [{ name: 'MY-GLASS', category: 'glass' } as MaterialRecord]
    const proj = { ...p, custom_materials: own }
    expect(glassPool('builtin', proj, ['N-BK7', 'F2'], [])).toEqual({ glasses: null, custom: own })
    expect(glassPool('project', proj, ['N-BK7', 'F2'], []).glasses).toEqual(['N-BK7', 'F2', 'MY-GLASS'])
    const cat = { id: 'X', records: [{ name: 'A', status: 'standard' }, { name: 'B', status: 'obsolete' }, { name: 'C', excluded: true }, { name: 'MY-GLASS', status: 'preferred' }] as MaterialRecord[] }
    const pool = glassPool('cat:X', proj, ['N-BK7'], [cat])
    expect(pool.glasses).toEqual(['A', 'MY-GLASS'])
    expect(pool.custom.map((m) => m.name)).toEqual(['A', 'MY-GLASS']) // the catalogue's record wins over the project's
  })
})
