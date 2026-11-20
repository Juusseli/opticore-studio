import { aimAngles, localDirection, placementAngles } from '../../lib/placement'
import type { Placement } from '../../lib/types'

export type DirMode = 'angles' | 'vector' | 'aim'

export const r9 = (x: number) => Math.round(x * 1e9) / 1e9 + 0

/** The direction of a placement as a new placement: from angles, a direction vector or an aim point (one edit). */
export function withDirection(p: Placement, mode: DirMode, v?: [number, number, number]): Placement {
  if (mode === 'aim') return { ...p, aim: v ?? (p.aim ? p.aim : (p.position.map((x, k) => r9(x + 10 * localDirection(p)[k])) as [number, number, number])) }
  if (mode === 'vector' && v) {
    const a = aimAngles(v)
    return a ? { ...p, rotation_deg: [r9(a[0]), r9(a[1]), p.rotation_deg[2]], aim: null } : p
  }
  // angles: keep the current orientation, without the aim point
  return { ...p, rotation_deg: placementAngles(p).map(r9) as [number, number, number], aim: null }
}
