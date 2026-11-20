import { describe, expect, it } from 'vitest'
import { detectorSummary, sourceSummary } from '../components/editors/sourceSummary'
import { blankProject, defaultDetector, defaultSource, normalizeProject, nsBody } from './project'
import { eulerXYZ, placePoint, reanchor, resolvePlacement, rotationMatrix, surfaceFrames } from './placement'

describe('non-sequential sources and detectors', () => {
  it('defaults match the engine defaults (point Lambertian 1 W; circle r 1 mm, absorbing, one-sided)', () => {
    const s = defaultSource()
    expect([s.kind, s.shape, s.angular, s.power_w, s.rays, s.half_angle_deg]).toEqual(['emitter', 'point', 'lambertian', 1, 2000, 90])
    const d = defaultDetector()
    expect([d.shape, d.size_x, d.mode, d.two_sided, d.acceptance_deg, d.pixels]).toEqual(['circle', 1, 'absorb', false, 90, 64])
    expect(defaultSource().id).not.toBe(s.id)
  })

  it('summaries describe shape, angular law, power, size and acceptance', () => {
    expect(sourceSummary(defaultSource({ shape: 'disk', size_x: 0.005, spatial: 'gaussian', angular: 'gaussian', gaussian_x_deg: 5, gaussian_y_deg: 5, power_w: 0.005 }))).toBe('disk r 0.005 (gauss) · gauss 5° · 0.005 W')
    expect(sourceSummary(defaultSource({ angular: 'cone', half_angle_deg: 12.7 }))).toBe('point · cone 12.7° · 1 W')
    expect(sourceSummary(defaultSource({ kind: 'system_field', field: 1 }))).toBe('system field F2 · 1 W')
    expect(detectorSummary(defaultDetector({ size_x: 0.15, acceptance_deg: 12 }))).toBe('Ø 0.3 mm · ≤ 12° · absorb')
    expect(detectorSummary(defaultDetector({ shape: 'rectangle', size_x: 2, size_y: 1, mode: 'monitor', two_sided: true }))).toBe('2×1 mm · monitor · 2-sided')
  })

  it('older projects get empty source and detector lists', () => {
    const raw = JSON.parse(JSON.stringify(blankProject()))
    delete raw.sources
    delete raw.detectors
    const n = normalizeProject(raw)
    expect(n.sources).toEqual([])
    expect(n.detectors).toEqual([])
  })

  it('anchored placements follow the surface frame and re-anchoring keeps the global pose', () => {
    // surface "b": vertex at z = 15, rotated 30 deg about x (coordinate break before it)
    const c = Math.cos(Math.PI / 6)
    const sn = Math.sin(Math.PI / 6)
    const frames = surfaceFrames([
      { id: 'obj', origin: [0, 0, -10], matrix: [[1, 0, 0], [0, 1, 0], [0, 0, 1]] },
      { id: 'b', origin: [0, 0, 15], matrix: [[1, 0, 0], [0, c, -sn], [0, sn, c]] },
    ])
    expect(placePoint({ position: [0, 0, 0], rotation_deg: [0, 0, 0], anchor: 'obj' }, [0, 0, 0], frames)).toEqual([0, 0, -10])
    const p = { position: [0.5, 0, 2] as [number, number, number], rotation_deg: [10, 20, 5] as [number, number, number], anchor: 'b' }
    const g = resolvePlacement(p, frames)
    expect(g.t[2]).toBeCloseTo(15 + 2 * c, 12)
    expect(g.t[1]).toBeCloseTo(-2 * sn, 12)
    // an unknown anchor (no evaluation yet) draws in the global frame
    expect(resolvePlacement({ ...p, anchor: 'zz' }, frames).t).toEqual([0.5, 0, 2])
    // re-anchoring to the global frame or to another surface keeps the global pose
    for (const a of [null, 'obj']) {
      const q = reanchor(p, a, frames)
      expect(q.anchor).toBe(a)
      const h = resolvePlacement(q, frames)
      for (let i = 0; i < 3; i++) {
        expect(h.t[i]).toBeCloseTo(g.t[i], 9)
        for (let j = 0; j < 3; j++) expect(h.R[i][j]).toBeCloseTo(g.R[i][j], 9)
      }
    }
    const e = eulerXYZ(rotationMatrix([12, -35, 70]))
    e.forEach((x, i) => expect(x).toBeCloseTo([12, -35, 70][i], 9))
  })

  it('engine requests carry the sources and detectors only when the project has them', () => {
    const p = blankProject()
    expect(nsBody(p)).toEqual({})
    p.detectors = [defaultDetector()]
    expect(nsBody(p)).toEqual({ sources: [], detectors: p.detectors })
  })
})
