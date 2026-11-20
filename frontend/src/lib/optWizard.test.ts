import { describe, expect, it } from 'vitest'
import { buildWizardSpec, DEFAULT_WIZARD, wizardTargets } from './optWizard'
import { blankProject } from './project'
import type { OpticalSystem } from './types'

const blank = () => blankProject()

/** obj · L1 front (N-BK7) · L1 back (air gap) · L2 front (F2) · L2 back (image distance) · img, plus a plane surface */
function twoLenses(): OpticalSystem {
  const p = blankProject()
  const s = p.system
  const [obj, a, b, img] = s.surfaces
  const c = { ...a, id: 'c', radius: null, material: 'F2', thickness: 3, is_stop: false }
  const d = { ...b, id: 'd', radius: -60, thickness: 80 }
  return { ...s, surfaces: [obj, { ...a, id: 'a' }, { ...b, id: 'b', thickness: 4 }, c, d, img] }
}

describe('optimisation wizard', () => {
  it('a blank singlet: radii and image distance, RMS spot, EFL kept, edge thickness', () => {
    const p = blank()
    const spec = buildWizardSpec(p.system, p.optimization, { ...DEFAULT_WIZARD, eflTarget: 100 })
    const ids = p.system.surfaces.map((s) => s.id)
    expect(spec.variables.map((v) => [ids.indexOf(v.surface_id), v.parameter])).toEqual([
      [1, 'curvature'],
      [2, 'curvature'],
      [2, 'thickness'],
    ])
    expect(spec.variables.every((v) => v.enabled)).toBe(true)
    expect(spec.operands.map((o) => o.type)).toEqual(['rms_spot', 'efl', 'min_edge_thickness'])
    expect(spec.operands[0]).toMatchObject({ target: 0, reference: 'centroid', field: null, wavelength: null })
    expect(spec.operands[1].target).toBe(100)
    expect(spec.operands[2]).toMatchObject({ target: 1, surface_id: ids[1] })
    // the rest of the spec (algorithm, evaluations) is kept
    expect(spec.algorithm).toBe(p.optimization.algorithm)
  })

  it('sorts surfaces into radii, plane surfaces, glass, air gaps and the image distance', () => {
    const s = twoLenses()
    expect(wizardTargets(s)).toEqual({ radii: ['a', 'b', 'd'], plane: ['c'], glass: ['a', 'c'], air: ['b'], image: 'd' })
    const spec = buildWizardSpec(s, blank().optimization, { ...DEFAULT_WIZARD, glassThickness: true, keepPlane: false, minCentre: 2, maxCentre: 8, objective: 'rms_wavefront' })
    const v = Object.fromEntries(spec.variables.map((x) => [`${x.surface_id}:${x.parameter}`, x]))
    expect(Object.keys(v).sort()).toEqual(['a:curvature', 'a:thickness', 'b:curvature', 'b:thickness', 'c:curvature', 'c:thickness', 'd:curvature', 'd:thickness'])
    // centre thicknesses: hard bounds on the glass thickness variables only
    expect([v['a:thickness'].min, v['a:thickness'].max, v['c:thickness'].min]).toEqual([2, 8, 2])
    // the lens-to-lens air gap keeps the air-gap minimum at its centre too (a hard bound)
    expect(v['b:thickness'].min).toBe(0.1)
    expect(spec.operands[0].type).toBe('rms_wavefront')
    // edge thickness on both glasses, air edge on the air gap
    expect(spec.operands.filter((o) => o.type === 'min_edge_thickness').map((o) => [o.surface_id, o.target])).toEqual([
      ['a', 1],
      ['c', 1],
      ['b', 0.1],
    ])
  })

  it('leaves solves, coordinate breaks and ideal lenses alone, and can add instead of replace', () => {
    const s = twoLenses()
    s.surfaces[2] = { ...s.surfaces[2], thickness_solve: { type: 'marginal_height', value: 0 } as never }
    s.surfaces[4] = { ...s.surfaces[4], curvature_solve: { type: 'marginal_angle', value: 0 } as never }
    const t = wizardTargets(s)
    expect(t.air).toEqual([])
    expect(t.radii).not.toContain('d')
    const p = blank()
    const first = buildWizardSpec(p.system, p.optimization, DEFAULT_WIZARD)
    const again = buildWizardSpec(p.system, first, { ...DEFAULT_WIZARD, mode: 'add', eflTarget: 50 })
    expect(again.variables.length).toBe(first.variables.length) // no duplicates
    expect(again.operands.map((o) => o.type)).toEqual([...first.operands.map((o) => o.type), 'efl'])
  })
})
