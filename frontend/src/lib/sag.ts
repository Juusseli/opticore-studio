import type { SurfaceGeometry } from './types'

/**
 * Surface sags for drawing only (the engine computes all optical results).
 * Rotational conic/asphere, biconic sections, and Zernike surfaces from the
 * exact monomial polynomial the engine sends with the surface geometry.
 */

function conicSag(c: number, k: number, aspheric: number[], r2: number): number {
  const root = 1 - (1 + k) * c * c * r2
  let z = c === 0 ? 0 : (c * r2) / (1 + Math.sqrt(Math.max(root, 0)))
  let rp = r2 * r2
  for (const a of aspheric) {
    z += a * rp
    rp *= r2
  }
  return z
}

/** Evaluate sum c[i][j] u^i v^j (Horner in both variables). */
export function polyval2d(u: number, v: number, c: number[][]): number {
  let out = 0
  for (let i = c.length - 1; i >= 0; i--) {
    const row = c[i]
    let s = 0
    for (let j = row.length - 1; j >= 0; j--) s = s * v + row[j]
    out = out * u + s
  }
  return out
}

export const isBiconic = (s: SurfaceGeometry) => s.type === 'biconic' && (s.curvature_x !== s.curvature || s.conic_x !== s.conic)
export const isZernike = (s: SurfaceGeometry) => !!s.zernike
/** Needs a polar mesh (not a lathe). */
export const isNonRotational = (s: SurfaceGeometry) => isBiconic(s) || isZernike(s)

/** Q-type asphere (backend qpoly.py): Qcon conic + u⁴ S(u²); Qbfs sphere + u²(1−u²) S(u²) / √(1 − c²r²). */
function qSag(q: NonNullable<SurfaceGeometry['qpoly']>, r2: number): number {
  const x = r2 / (q.norm_radius * q.norm_radius)
  let S = 0
  for (let j = q.series.length - 1; j >= 0; j--) S = S * x + q.series[j]
  if (q.kind === 'qcon') return conicSag(q.base_curvature, q.conic, [], r2) + x * x * S
  const root = Math.sqrt(Math.max(1 - q.base_curvature * q.base_curvature * r2, 1e-300))
  return conicSag(q.base_curvature, 0, [], r2) + (x * (1 - x) * S) / root
}

/** Odd asphere (backend surfaces.OddShape): conic + Σ beta_i r^i. */
function oddSag(o: NonNullable<SurfaceGeometry['odd']>, r2: number): number {
  const r = Math.sqrt(Math.max(r2, 0))
  let z = conicSag(o.base_curvature, o.conic, [], r2)
  let rp = r
  for (const b of o.coefficients) {
    z += b * rp
    rp *= r
  }
  return z
}

/** Rotational sag at radius h (for rotationally symmetric surfaces). */
export function sagR(s: SurfaceGeometry, h: number): number {
  if (s.qpoly) return qSag(s.qpoly, h * h)
  if (s.odd) return oddSag(s.odd, h * h)
  if (s.zernike) return sagXY(s, 0, h)
  return conicSag(s.curvature, s.conic, s.aspheric, h * h)
}

/** Sag at local (x, y). */
export function sagXY(s: SurfaceGeometry, x: number, y: number): number {
  if (s.qpoly) return qSag(s.qpoly, x * x + y * y)
  if (s.odd) return oddSag(s.odd, x * x + y * y)
  const z = s.zernike
  if (z) {
    const R = z.norm_radius
    return conicSag(z.base_curvature, s.conic, s.aspheric, x * x + y * y) + polyval2d(x / R, y / R, z.poly)
  }
  if (!isBiconic(s)) return conicSag(s.curvature, s.conic, s.aspheric, x * x + y * y)
  const cx = s.curvature_x ?? s.curvature
  const kx = s.conic_x ?? s.conic
  const cy = s.curvature
  const q = 1 - (1 + kx) * cx * cx * x * x - (1 + s.conic) * cy * cy * y * y
  return (cx * x * x + cy * y * y) / (1 + Math.sqrt(Math.max(q, 0)))
}
