import { describe, expect, it } from 'vitest'
import { applyVariableValues, blankProject, variableValue } from './project'
import { isNonRotational, polyval2d, sagR, sagXY } from './sag'
import type { SurfaceGeometry } from './types'

const geom = (p: Partial<SurfaceGeometry>): SurfaceGeometry => ({
  index: 1,
  id: 's',
  type: 'standard',
  semi_diameter: 5,
  origin: [0, 0, 0],
  matrix: [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
  ],
  profile: [],
  curvature: 0,
  conic: 0,
  aspheric: [],
  is_mirror: false,
  is_stop: false,
  ...p,
})

describe('drawing sags', () => {
  it('evaluates 2D power series', () => {
    // 1 + 2u + 3v^2 + 4uv
    const c = [
      [1, 0, 3],
      [2, 4, 0],
    ]
    expect(polyval2d(0.5, -2, c)).toBeCloseTo(1 + 1 + 12 - 4, 14)
  })
  it('draws Zernike surfaces from the engine polynomial', () => {
    // Z5 astigmatism, A = 0.03, R = 6: poly (u^2 - v^2) * 0.03 on a sphere base
    const s = geom({ type: 'zernike', curvature: 0.02, conic: 0, zernike: { base_curvature: 0.02, norm_radius: 6, poly: [[0, 0, -0.03], [0, 0, 0], [0.03, 0, 0]] } })
    const base = (r2: number) => (0.02 * r2) / (1 + Math.sqrt(1 - 0.0004 * r2))
    expect(sagXY(s, 3, 0)).toBeCloseTo(base(9) + 0.03 * 0.25, 14)
    expect(sagXY(s, 0, 3)).toBeCloseTo(base(9) - 0.03 * 0.25, 14)
    expect(sagR(s, 3)).toBeCloseTo(sagXY(s, 0, 3), 15) // y-z section
    expect(isNonRotational(s)).toBe(true)
    expect(isNonRotational(geom({}))).toBe(false)
  })
  it('maps Zernike optimisation variables onto the coefficient list', () => {
    const p = blankProject()
    const id = p.system.surfaces[1].id
    const out = applyVariableValues(p.system, [{ surface_id: id, parameter: 'zern_9' }], [-0.002])
    expect(out.surfaces[1].zernike_coefficients).toEqual([0, 0, 0, 0, 0, 0, 0, 0, -0.002])
    expect(variableValue(out, id, 'zern_9')).toBe(-0.002)
    expect(variableValue(out, id, 'zern_4')).toBe(0)
    expect(Object.keys(out.surfaces[1])).not.toContain('zern_9')
  })
})
