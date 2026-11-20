import { beforeEach, describe, expect, it } from 'vitest'
import { describeMove, findingText } from '../components/views/advisorText'
import { translate } from '../lib/i18n'
import { blankProject } from '../lib/project'
import type { AdvisorSuggestion } from '../lib/types'
import { advKey, applySuggestion } from './advisorStore'
import { useProjectStore } from './projectStore'

const st = () => useProjectStore.getState()
const t = (k: string, v?: Record<string, string | number>) => translate('en', k, v)

const bend = (): AdvisorSuggestion => {
  const s = st().project.system.surfaces
  return {
    kind: 'bend',
    surfaces: [1, 2],
    t: 0.002,
    merit_before: 0.02,
    merit_after: 0.015,
    gain: 0.25,
    patch: [
      { surface_id: s[1].id, key: 'radius', value: 83.3333 },
      { surface_id: s[2].id, key: 'radius', value: -125 },
    ],
    rms_spot_before_um: [20, 30],
    rms_spot_after_um: [15, 25],
  }
}

describe('design advisor', () => {
  beforeEach(() => st().setProject(blankProject('Advisor')))

  it('applies a suggestion as one undoable edit', () => {
    const before = JSON.stringify(st().project.system)
    expect(applySuggestion(bend(), 'Advisor: bend')).toBe(true)
    expect(st().project.system.surfaces.slice(1, 3).map((s) => s.radius)).toEqual([83.3333, -125])
    expect(st().lastAction).toBe('Advisor: bend')
    st().undo()
    expect(JSON.stringify(st().project.system)).toBe(before)
  })

  it('refuses a suggestion whose surfaces are gone', () => {
    const sg = bend()
    st().deleteSurfaces([2])
    const before = JSON.stringify(st().project.system)
    expect(applySuggestion(sg, 'x')).toBe(false)
    expect(JSON.stringify(st().project.system)).toBe(before)
  })

  it('keys results by the design and the merit function (an applied change or new operand makes them stale)', () => {
    const k0 = advKey(st().project)
    applySuggestion(bend(), 'bend')
    const k1 = advKey(st().project)
    expect(k1).not.toBe(k0)
    st().undo()
    expect(advKey(st().project)).toBe(k0)
    st().updateProject((p) => void p.optimization.operands.push({ id: 'o1', type: 'rms_spot', target: 0, weight: 1, enabled: true } as never), 'op')
    expect(advKey(st().project)).not.toBe(k0)
  })

  it('words findings and moves from the engine numbers', () => {
    const sys = st().project.system
    expect(findingText(t, { kind: 'aberration', field: 1, class: 'coma', share: 0.623, rms_waves: 0.31, blur_rms_waves: 0.4 }, sys)).toBe('F2 (3°): the blur at the best focus is mainly coma (62.3 %, 0.31 waves RMS).')
    expect(findingText(t, { kind: 'distortion', percent: -2.5 }, sys)).toBe('Barrel distortion 2.5 % at the edge of the field.')
    expect(findingText(t, { kind: 'focus', defocus_mm: -0.5, rms_um: 40, rms_best_um: 12, share: null }, sys)).toBe('The image surface is 0.5 mm from the best focus (change of the image distance -0.5 mm): RMS spot 40 µm now, 12 µm at the best focus.')
    expect(describeMove(t, bend())).toBe('Bend the lens S1–S2 (same power)')
    expect(describeMove(t, { ...bend(), kind: 'refocus', surface: 2, t: 0.25 })).toBe('Refocus: image distance +0.25 mm')
    expect(describeMove(t, { ...bend(), kind: 'glass', surface: 1, from: 'N-BK7', to: 'N-K5' })).toBe('Glass after S1: N-BK7 → N-K5, refocused')
  })
})
