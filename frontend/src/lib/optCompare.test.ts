import { describe, expect, it } from 'vitest'
import { focusReport } from './focusReport'
import { compareRows, flagged, goalChanges } from './optCompare'
import type { DesignComparison, DesignSummary, FocusResult, OptimizationResult } from './types'

const summary = (p: Partial<DesignSummary>): DesignSummary => ({
  rms_spot_um: [13.4, 15.3],
  airy_radius_um: 2.5,
  mtf: [
    [0.03, 0.03],
    [0.02, 0.6],
  ],
  mtf_frequency: 110,
  efl_mm: 5.555,
  working_fnum: 3.5,
  total_track_mm: 6.7,
  field: 30.4,
  field_unit: 'deg',
  image_height_mm: 3.5,
  distortion_pct: 3.19,
  lateral_colour_um: -0.9,
  axial_colour_um: 24,
  relative_illumination: 0.53,
  cra_deg: 27.8,
  min_glass_edge_mm: 0.86,
  min_glass_edge_surface: 'c1',
  min_air_edge_mm: 0.2,
  min_air_edge_surface: 'c6',
  max_field_index: 1,
  missing: {},
  ...p,
})

describe('optimisation before / after comparison', () => {
  const c: DesignComparison = {
    before: summary({}),
    after: summary({ rms_spot_um: [2.7, 5.4], mtf: [[0.48, 0.48], [0.5, 0.56]], distortion_pct: 9.83, lateral_colour_um: 2.33, field: 28.7, axial_colour_um: null }),
    flags: [
      { key: 'distortion_pct', kind: 'worse', field: null, before: 3.19, after: 9.83 },
      { key: 'lateral_colour_um', kind: 'worse', field: null, before: -0.9, after: 2.33 },
      { key: 'field', kind: 'changed', field: null, before: 30.4, after: 28.7 },
    ],
  }

  it('lists spots and MTF per field, then the system numbers, with the engine flags', () => {
    const rows = compareRows(c)
    expect(rows.map((r) => r.id).slice(0, 4)).toEqual(['rms0', 'rms1', 'mtf0', 'mtf1'])
    expect(rows[0]).toMatchObject({ before: '13.4', after: '2.7', delta: '−79.9 %', flag: null })
    expect(rows[3]).toMatchObject({ before: '0.02 / 0.6', after: '0.5 / 0.56', delta: '+0.22' })
    const dist = rows.find((r) => r.key === 'distortion_pct')
    expect(dist).toMatchObject({ after: '9.83', delta: '+6.64', flag: 'worse' })
    expect(rows.find((r) => r.key === 'field')?.flag).toBe('changed')
    // a number only one design has is still listed
    expect(rows.find((r) => r.key === 'axial_colour_um')).toMatchObject({ before: '24', after: '—', delta: '—' })
    expect(flagged(c, 'worse')).toEqual(['distortion_pct', 'lateral_colour_um'])
    expect(flagged(c, 'changed')).toEqual(['field'])
  })

  it('reports how the image-quality operands moved, apart from the whole merit function', () => {
    const r = {
      operands_before: [
        { type: 'rms_spot', value: 12.18, target: 0, weight: 1, unit: 'um' },
        { type: 'min_edge_thickness', value: 0.4, target: 1, weight: 1 },
      ],
      operands_after: [
        { type: 'rms_spot', value: 52.46, target: 0, weight: 1, unit: 'um' },
        { type: 'min_edge_thickness', value: 0.4, target: 1, weight: 1 },
      ],
    } as unknown as OptimizationResult
    expect(goalChanges(r)).toEqual([{ type: 'rms_spot', before: 12.18, after: 52.46, unit: 'um', better: false }])
    // a spot of a given size: closer to the target is better (the target is in mm, the value in µm)
    const sized = { operands_before: [{ type: 'rms_spot', value: 40, target: 0.02, weight: 1, unit: 'um' }], operands_after: [{ type: 'rms_spot', value: 21, target: 0.02, weight: 1, unit: 'um' }] } as unknown as OptimizationResult
    expect(goalChanges(sized)[0].better).toBe(true)
  })

  it('names the fields Quick focus made worse', () => {
    const f = (rms: number[]) => ({ per_field: rms.map((r, k) => ({ field: k, rms_um: r, rms_best_um: null, n_rays: 100 })) }) as unknown as FocusResult
    const rep = focusReport(f([3.88, 23.6, 13.1]), f([13.4, 15.3, 9.68]))
    expect(rep.fields).toEqual(['F1 3.88 → 13.4', 'F2 23.6 → 15.3', 'F3 13.1 → 9.68'])
    expect(rep.worse).toEqual([0])
    expect(focusReport(null, f([1])).fields).toEqual([])
  })
})
