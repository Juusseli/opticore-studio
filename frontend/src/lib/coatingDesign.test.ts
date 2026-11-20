import { describe, expect, it } from 'vitest'
import { defaultCoatingDesign, defaultTarget, parseSpectrum, recipeToCsv, removeThinLayers, retarget, targetText } from './coatingDesign'
import type { CoatingRecipe } from './types'

describe('coating design helpers', () => {
  it('removes thin layers and merges equal neighbours, keeping locked layers', () => {
    const out = removeThinLayers(
      [
        { material: 'H', thickness_nm: 50, locked: false },
        { material: 'L', thickness_nm: 0.4, locked: false },
        { material: 'H', thickness_nm: 20, locked: false },
        { material: 'L', thickness_nm: 0.3, locked: true },
        { material: 'H', thickness_nm: 10, locked: false },
      ],
      1,
    )
    expect(out.map((l) => [l.material, l.thickness_nm, l.locked])).toEqual([
      ['H', 70, false],
      ['L', 0.3, true],
      ['H', 10, false],
    ])
  })
  it('writes the recipe as CSV in deposition order', () => {
    const r: CoatingRecipe = {
      name: 'LP, 600',
      substrate: 'N-BK7',
      incident: 'AIR',
      monitor_wavelength_nm: 633,
      monitor: 'T',
      monitor_back_side: 'uncoated',
      layers: [
        { layer: 1, material: 'H', material_name: 'H', thickness_nm: 67.3, qwot_design: 1, qwot_monitor: 1.0001, n_monitor: 2.35, cumulative_nm: 67.3, monitor_start: 0.92, monitor_end: 0.71, turning_points: 0, termination: 'turning point', crystal_nm: 56.08, crystal_kA: 0.5608, rate_nm_s: 0.3, time_s: 224.3 },
      ],
      curves: [],
      total_thickness_nm: 67.3,
      total_time_s: 224.3,
      palette: defaultCoatingDesign().palette,
      warnings: [],
      notes: [],
    }
    const csv = recipeToCsv(r).split('\n')
    expect(csv[0]).toBe('# OptiCore Studio deposition recipe: LP, 600')
    const header = csv.findIndex((l) => l.startsWith('layer,'))
    expect(csv[header]).toContain('T_start,T_end')
    expect(csv[header + 1].split(',').slice(0, 3)).toEqual(['1', 'H', '67.3'])
    expect(csv[header + 1]).toContain('turning point')
  })
})

describe('coating targets and measured spectra', () => {
  it('retargets a target to another quantity with a sensible range and value', () => {
    const t = { ...defaultTarget(800), points: 1, lambda_min_nm: 800, lambda_max_nm: 800 }
    const gdd = retarget(t, 'GDD')
    expect([gdd.quantity, gdd.of, gdd.kind, gdd.value]).toEqual(['GDD', 'R', '=', 0])
    expect(gdd.points).toBeGreaterThanOrEqual(5)
    expect(gdd.lambda_max_nm).toBeGreaterThan(gdd.lambda_min_nm)
    const rv = retarget(t, 'Rv')
    expect([rv.lambda_min_nm, rv.lambda_max_nm, rv.points, rv.kind]).toEqual([380, 780, 1, '<='])
  })

  it('writes a target with its units', () => {
    const g = { ...retarget(defaultTarget(800), 'GDD'), value: -40, tolerance: 15, lambda_min_nm: 770, lambda_max_nm: 830 }
    expect(targetText(g)).toBe('GDD(R) = -40 ±15 fs² @ 770–830 nm')
    expect(targetText({ ...defaultTarget(550), quantity: 'R', kind: '<=', value: 0.005, lambda_min_nm: 420, lambda_max_nm: 680 })).toBe('R <= 0.5 % @ 420–680 nm')
    const table: [number, number][] = [
      [450, 0.8],
      [451, 0.79],
      [1075, 0.1],
    ]
    expect(targetText({ ...defaultTarget(550), quantity: 'T', polarization: 's', kind: '=', table, lambda_min_nm: 450, lambda_max_nm: 1075, angle_deg: 10 })).toBe('Ts = [3 pts] @ 450–1075 nm, 10°')
    expect(targetText({ ...retarget(defaultTarget(550), 'b*'), kind: '<=', value: 2, tolerance: 0, illuminant: 'A', observer: '10' })).toBe('b*(R) <= 2 @ A 10°')
  })

  it('reads a pasted spectrum in percent or as fractions, skipping headers', () => {
    const r = parseSpectrum(['# lambda T', 'wavelength,T', '400, 91.5', '410;92', '420\t92.5', '', 'bad line', ''].join('\n'), true)
    expect(r.lambda_nm).toEqual([400, 410, 420])
    expect(r.value).toEqual([0.915, 0.92, 0.925])
    expect(r.skipped).toBe(2)
    expect(parseSpectrum('500 0.04', false).value).toEqual([0.04])
  })
})
