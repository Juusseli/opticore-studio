import { describe, expect, it } from 'vitest'
import { sourceSummary } from '../components/editors/sourceSummary'
import { withDirection } from '../components/editors/placementDirection'
import { aimAngles, framePoint, localDirection, placementAngles, reanchor, resolvePlacement, toFrame, type Frames } from './placement'
import { defaultSource } from './project'
import type { Placement } from './types'

const close = (a: number[], b: number[], tol = 1e-9) => a.forEach((x, i) => expect(x).toBeCloseTo(b[i], -Math.log10(tol)))

describe('placement direction and aim (G5)', () => {
  it('aims like the engine (nssources.placement_matrix)', () => {
    const p: Placement = { position: [1, 2, 3], rotation_deg: [10, 20, 30], aim: [4, -1, 13] }
    const { R } = resolvePlacement(p)
    // the engine's matrix for this placement (the first two angles are replaced by the aim)
    const engine = [
      [0.832344045554, -0.480554058759, 0.276172385369],
      [0.547638797748, 0.78982311992, -0.276172385369],
      [-0.085411574342, 0.381113153604, 0.920574617898],
    ]
    R.forEach((row, i) => close(row, engine[i], 1e-11))
    const d = [3, -3, 10].map((x) => x / Math.hypot(3, -3, 10))
    close(localDirection(p), d, 1e-12)
    expect(aimAngles([0, 0, 0])).toBeNull()
    expect(placementAngles({ position: [0, 0, 0], rotation_deg: [5, 6, 7] })).toEqual([5, 6, 7])
  })

  it('converts between angles, a direction vector and an aim point without moving the axis', () => {
    const p: Placement = { position: [0, 0, 0], rotation_deg: [0, 0, 15] }
    const v = withDirection(p, 'vector', [0, 1, 1])
    close(localDirection(v), [0, Math.SQRT1_2, Math.SQRT1_2])
    expect(v.rotation_deg[2]).toBe(15) // the roll is kept
    const a = withDirection(v, 'aim')
    expect(a.aim).not.toBeNull()
    close(localDirection(a), localDirection(v))
    close(a.aim as number[], [0, 10 * Math.SQRT1_2, 10 * Math.SQRT1_2], 1e-8) // 10 mm ahead
    const back = withDirection(a, 'angles')
    expect(back.aim).toBeNull()
    close(resolvePlacement(back).R.flat(), resolvePlacement(a).R.flat(), 1e-8)
  })

  it('keeps the aim point when the reference surface changes', () => {
    const frames: Frames = new Map([['s1', { origin: [0, 5, 40] as [number, number, number], matrix: [[1, 0, 0], [0, Math.cos(0.3), -Math.sin(0.3)], [0, Math.sin(0.3), Math.cos(0.3)]] as [[number, number, number], [number, number, number], [number, number, number]] }]])
    const p: Placement = { position: [1, 2, 3], rotation_deg: [0, 0, 20], aim: [0, 0, 60] }
    const q = reanchor(p, 's1', frames)
    close(framePoint(q, q.aim as [number, number, number], frames), [0, 0, 60])
    close(resolvePlacement(q, frames).R.flat(), resolvePlacement(p, frames).R.flat(), 1e-9)
    close(resolvePlacement(q, frames).t, resolvePlacement(p, frames).t, 1e-9)
    close(toFrame(q, framePoint(q, [1, 2, 3], frames), frames), [1, 2, 3])
  })

  it('summarises a Gaussian beam source', () => {
    expect(sourceSummary(defaultSource({ kind: 'gaussian_beam', beam_waist_x: 0.25, beam_waist_y: 0.25, beam_m2: 1.3 }))).toBe('Gaussian beam w₀ 0.25 mm · M² 1.3 · 1 W')
    expect(sourceSummary(defaultSource({ kind: 'gaussian_beam', beam_waist_x: 0.25, beam_waist_y: 0.5 }))).toBe('Gaussian beam w₀ 0.25×0.5 mm · 1 W')
  })
})
