// Placement of non-sequential sources and detectors: p_global = R p_local + t with R = Rx Ry Rz
// (intrinsic XYZ, degrees), the same convention as the engine (nssources.placement_matrix) and CAD models.
// With an aim point the first two angles come from the direction to it (nssources.aim_angles) and the third
// is the roll about it.
// An anchored placement is relative to a surface's vertex frame (from the engine's evaluation):
// p_global = O + M (R p_local + t). Drawing only; the engine places the rays.
import type { Placement } from './types'

type V3 = [number, number, number]
type M3 = [V3, V3, V3]

const mul = (a: M3, b: M3): M3 => a.map((r) => [0, 1, 2].map((j) => r[0] * b[0][j] + r[1] * b[1][j] + r[2] * b[2][j])) as M3
const apply = (m: M3, v: V3): V3 => [0, 1, 2].map((i) => m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2]) as V3

export function rotationMatrix(rotDeg: V3): M3 {
  const [a, b, c] = rotDeg.map((d) => (d * Math.PI) / 180)
  const Rx: M3 = [
    [1, 0, 0],
    [0, Math.cos(a), -Math.sin(a)],
    [0, Math.sin(a), Math.cos(a)],
  ]
  const Ry: M3 = [
    [Math.cos(b), 0, Math.sin(b)],
    [0, 1, 0],
    [-Math.sin(b), 0, Math.cos(b)],
  ]
  const Rz: M3 = [
    [Math.cos(c), -Math.sin(c), 0],
    [Math.sin(c), Math.cos(c), 0],
    [0, 0, 1],
  ]
  return mul(mul(Rx, Ry), Rz)
}

/** Surface vertex frames by surface id (origin O, matrix M with the local axes as columns). */
export type Frames = Map<string, { origin: V3; matrix: M3 }>

export function surfaceFrames(surfaces: { id: string; origin: number[]; matrix: number[][] }[]): Frames {
  return new Map(surfaces.map((s) => [s.id, { origin: s.origin as V3, matrix: s.matrix as M3 }]))
}

/** Intrinsic X and Y angles (degrees) that turn the local +z axis onto d without roll (the engine's
 *  nssources.aim_angles: a = atan2(-d_y, d_z), b = asin(d_x)); null for a zero vector. */
export function aimAngles(d: V3): [number, number] | null {
  const n = Math.hypot(d[0], d[1], d[2])
  if (!(n > 1e-12)) return null
  const [x, y, z] = [d[0] / n, d[1] / n, d[2] / n]
  return [(Math.atan2(-y, z) * 180) / Math.PI, (Math.asin(Math.max(-1, Math.min(1, x))) * 180) / Math.PI]
}

/** The XYZ angles a placement uses: with an aim point, the aimed angles and the roll. */
export function placementAngles(p: Placement): V3 {
  if (p.aim) {
    const a = aimAngles([p.aim[0] - p.position[0], p.aim[1] - p.position[1], p.aim[2] - p.position[2]])
    if (a) return [a[0], a[1], p.rotation_deg[2]]
  }
  return p.rotation_deg
}

/** The emission (or reception) direction, +z of the placement, in the frame of its position. */
export function localDirection(p: Placement): V3 {
  const R = rotationMatrix(placementAngles(p))
  return [R[0][2], R[1][2], R[2][2]]
}

/** A point given in the frame of a placement's position (its anchor's, or global) in global coordinates. */
export function framePoint(p: Placement, v: V3, frames?: Frames): V3 {
  const f = p.anchor ? frames?.get(p.anchor) : undefined
  if (!f) return [...v] as V3
  const q = apply(f.matrix, v)
  return [q[0] + f.origin[0], q[1] + f.origin[1], q[2] + f.origin[2]]
}

/** A global point in the frame of a placement's position (inverse of framePoint). */
export function toFrame(p: Placement, g: V3, frames?: Frames): V3 {
  const f = p.anchor ? frames?.get(p.anchor) : undefined
  if (!f) return [...g] as V3
  const MT = [0, 1, 2].map((i) => [f.matrix[0][i], f.matrix[1][i], f.matrix[2][i]]) as M3
  return apply(MT, [g[0] - f.origin[0], g[1] - f.origin[1], g[2] - f.origin[2]])
}

/** Global rotation and translation of a placement (an anchor that is not in `frames` counts as global). */
export function resolvePlacement(p: Placement, frames?: Frames): { R: M3; t: V3 } {
  const R = rotationMatrix(placementAngles(p))
  const f = p.anchor ? frames?.get(p.anchor) : undefined
  if (!f) return { R, t: [...p.position] as V3 }
  const t = apply(f.matrix, p.position)
  return { R: mul(f.matrix, R), t: [t[0] + f.origin[0], t[1] + f.origin[1], t[2] + f.origin[2]] }
}

/** Local point -> global point. */
export function placePoint(p: Placement, local: V3, frames?: Frames): V3 {
  const { R, t } = resolvePlacement(p, frames)
  const q = apply(R, local)
  return [q[0] + t[0], q[1] + t[1], q[2] + t[2]]
}

/** Intrinsic XYZ angles (degrees) of R = Rx Ry Rz. */
export function eulerXYZ(R: M3): V3 {
  const b = Math.asin(Math.max(-1, Math.min(1, R[0][2])))
  let a: number
  let c: number
  if (Math.abs(R[0][2]) < 1 - 1e-12) {
    a = Math.atan2(-R[1][2], R[2][2])
    c = Math.atan2(-R[0][1], R[0][0])
  } else {
    a = Math.atan2(R[2][1], R[1][1]) // gimbal lock: put the whole rotation into x
    c = 0
  }
  const d = (x: number) => Math.round(((x * 180) / Math.PI) * 1e9) / 1e9 + 0
  return [d(a), d(b), d(c)]
}

/** The same global pose expressed relative to another anchor (null: global). Without the frames
 * (no evaluation yet) only the reference changes. */
export function reanchor(p: Placement, anchor: string | null, frames?: Frames): Placement {
  if (!frames || (anchor && !frames.has(anchor))) return { ...p, anchor }
  const { R, t } = resolvePlacement(p, frames)
  const aimG = p.aim ? framePoint(p, p.aim, frames) : null
  const r12 = (v: V3) => v.map((x) => Math.round(x * 1e12) / 1e12 + 0) as V3
  const f = anchor ? frames.get(anchor) : undefined
  if (!f) return { position: r12(t), rotation_deg: eulerXYZ(R), anchor: null, aim: aimG ? r12(aimG) : null }
  const MT = [0, 1, 2].map((i) => [f.matrix[0][i], f.matrix[1][i], f.matrix[2][i]]) as M3
  const local = apply(MT, [t[0] - f.origin[0], t[1] - f.origin[1], t[2] - f.origin[2]])
  const aimL = aimG ? apply(MT, [aimG[0] - f.origin[0], aimG[1] - f.origin[1], aimG[2] - f.origin[2]]) : null
  return { position: r12(local), rotation_deg: eulerXYZ(mul(MT, R)), anchor, aim: aimL ? r12(aimL) : null }
}
