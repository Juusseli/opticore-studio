import { describe, expect, it } from 'vitest'
import { buildWizardSpec, craLimit, DEFAULT_WIZARD, distortionLimit, edgeElements, lateralLimit, lensGaps, riLimit, scaledConstraints, trackLimit } from './optWizard'
import { blankProject } from './project'
import type { OpticalSystem } from './types'

/** A small camera lens: stop at the first vertex, two lenses, an IR filter plate, the image distance. */
function camera(): OpticalSystem {
  const p = blankProject()
  const [obj, a, b, img] = p.system.surfaces
  const sf = (id: string, radius: number | null, thickness: number, material: string) => ({ ...a, id, radius, thickness, material, is_stop: false })
  return {
    ...p.system,
    surfaces: [
      obj,
      { ...sf('stop', null, 0, 'AIR'), is_stop: true },
      sf('l1', 2.0, 1.2, 'N-BK7'),
      sf('l1b', 30, 0.9, 'AIR'),
      sf('l2', -2.2, 0.75, 'F2'),
      sf('l2b', -6.4, 0.1, 'AIR'),
      sf('ir', null, 0.4, 'N-BK7'),
      { ...b, id: 'irb', radius: null, thickness: 0.7 },
      img,
    ],
  }
}

describe('optimisation wizard: defaults scaled to the lens', () => {
  it('leaves plane-parallel plates out of the edge targets and the stop gap out of the lens gaps', () => {
    const s = camera()
    expect(edgeElements(s)).toEqual(['l1', 'l2'])
    expect(lensGaps(s)).toEqual(['l1b', 'l2b'])
    const spec = buildWizardSpec(s, blankProject().optimization, DEFAULT_WIZARD)
    const edges = spec.operands.filter((o) => o.type === 'min_edge_thickness').map((o) => o.surface_id)
    expect(edges).not.toContain('ir')
    // the stop may sit at the lens vertex: its gap keeps the plain [0, …] bound
    expect(spec.variables.find((v) => v.surface_id === 'stop')?.min).toBe(0)
  })

  it('scales the defaults to the smallest lens and never asks for more than the design has', () => {
    const s = camera()
    const i = (id: string) => s.surfaces.findIndex((x) => x.id === id)
    const sd = s.surfaces.map(() => 1.5)
    sd[i('l1')] = 1.0
    sd[i('l1b')] = 1.1 // smallest lens: Ø 2.2 mm
    const edge = s.surfaces.map(() => null as number | null)
    edge[i('l1')] = 0.86
    edge[i('l2')] = 2.4
    edge[i('l1b')] = 0.54
    edge[i('l2b')] = 0.38
    const c = scaledConstraints(s, { semiDiameters: sd, edgeThickness: edge })
    expect(c.minEdge).toBe(0.22) // 10 % of Ø 2.2 (the thinnest edge now is 0.86)
    expect(c.minCentre).toBe(0.33) // 15 % of Ø 2.2
    expect(c.minAirEdge).toBe(0.044) // 2 % of Ø 2.2
    // a thin edge now caps the default just inside it
    edge[i('l1')] = 0.15
    expect(scaledConstraints(s, { semiDiameters: sd, edgeThickness: edge }).minEdge).toBe(0.13)
    // big lenses: the classic 1 mm edge; the centre and the air gap capped by this design's 0.75 mm lens and 0.1 mm gap
    const big = scaledConstraints(s, { semiDiameters: s.surfaces.map(() => 15), edgeThickness: s.surfaces.map(() => 5) })
    expect([big.minEdge, big.minCentre, big.minAirEdge]).toEqual([1, 0.75, 0.09])
    // without an evaluation the fixed defaults stay
    expect(scaledConstraints(s, null).minEdge).toBe(DEFAULT_WIZARD.minEdge)
  })

  it('builds the goals: a spot of a given size, a beam on a detector, and the distortion and length limits', () => {
    const s = camera()
    const spot = buildWizardSpec(s, blankProject().optimization, { ...DEFAULT_WIZARD, objective: 'spot_size', spotTarget: 25, reference: 'chief', maxDistortion: 3.2, maxTrack: 6.7 })
    expect(spot.operands[0]).toMatchObject({ type: 'rms_spot', target: 0.025, reference: 'chief' })
    expect(spot.operands.find((o) => o.type === 'max_distortion')?.target).toBe(3.2)
    expect(spot.operands.find((o) => o.type === 'max_total_track')?.target).toBe(6.7)
    const beam = buildWizardSpec(s, blankProject().optimization, { ...DEFAULT_WIZARD, objective: 'beam_size', beamTarget: 150, detectorId: 'det' })
    expect(beam.operands.slice(0, 2)).toMatchObject([
      { type: 'detector_size', target: 0.15, detector_id: 'det' },
      { type: 'detector_power', target: 1, weight: 0.1, detector_id: 'det' },
    ])
    // without a detector there is no goal operand
    expect(buildWizardSpec(s, blankProject().optimization, { ...DEFAULT_WIZARD, objective: 'beam_size', detectorId: null }).operands.some((o) => o.type.startsWith('detector'))).toBe(false)
  })

  it('holds lateral colour, corner illumination and the chief-ray angle', () => {
    const spec = buildWizardSpec(camera(), blankProject().optimization, { ...DEFAULT_WIZARD, maxLateralUm: 1.2, minRiPct: 45, maxCraDeg: 28.5 })
    const by = (t: string) => spec.operands.find((o) => o.type === t)
    expect(by('max_lateral_color')).toMatchObject({ target: 1.2, field: null })
    expect(by('min_relative_illumination')?.target).toBeCloseTo(0.45, 12)
    expect(by('max_cra')?.target).toBe(28.5)
    expect(buildWizardSpec(camera(), blankProject().optimization, DEFAULT_WIZARD).operands.some((o) => ['max_lateral_color', 'min_relative_illumination', 'max_cra'].includes(o.type))).toBe(false)
    expect(lateralLimit(-0.8993)).toBe(0.9)
    expect(lateralLimit(0.01)).toBe(0.1)
    expect(riLimit(0.5311)).toBe(53)
    expect(craLimit(27.771)).toBe(27.8)
  })

  it('rounds the limits just outside the current values', () => {
    expect(distortionLimit(3.1928)).toBe(3.2)
    expect(distortionLimit(-0.31)).toBe(0.4)
    expect(distortionLimit(0.02)).toBe(0.1)
    expect(distortionLimit(2)).toBe(2)
    expect(trackLimit(6.6986)).toBe(6.7)
  })
})
