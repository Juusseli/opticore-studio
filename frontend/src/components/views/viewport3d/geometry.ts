import * as THREE from 'three'
import { isNonRotational, sagR, sagXY } from '../../../lib/sag'
import type { CadAsset, Evaluation, SurfaceGeometry } from '../../../lib/types'

/** Drawing geometry of the optical system (the engine computes all optical results). */

const sag = sagR

/** Closed element mesh on a polar grid (needed when a surface is not rotationally symmetric). */
function polarElement(front: SurfaceGeometry, back: SurfaceGeometry, t: number, h: number): THREE.BufferGeometry {
  const R = 24
  const M = 128
  const pos: number[] = []
  const idx: number[] = []
  const cap = (s: SurfaceGeometry, z0: number, flip: boolean) => {
    const base = pos.length / 3
    pos.push(0, 0, z0 + sagXY(s, 0, 0))
    for (let i = 1; i <= R; i++) {
      const r = (h * i) / R
      for (let j = 0; j < M; j++) {
        const a = (2 * Math.PI * j) / M
        const x = r * Math.cos(a)
        const y = r * Math.sin(a)
        pos.push(x, y, z0 + sagXY(s, x, y))
      }
    }
    const v = (i: number, j: number) => (i === 0 ? base : base + 1 + (i - 1) * M + (j % M))
    for (let j = 0; j < M; j++) {
      if (flip) idx.push(v(0, 0), v(1, j + 1), v(1, j))
      else idx.push(v(0, 0), v(1, j), v(1, j + 1))
    }
    for (let i = 1; i < R; i++)
      for (let j = 0; j < M; j++) {
        const a = v(i, j)
        const b = v(i, j + 1)
        const c = v(i + 1, j)
        const d = v(i + 1, j + 1)
        if (flip) idx.push(a, d, c, a, b, d)
        else idx.push(a, c, d, a, d, b)
      }
    return (j: number) => v(R, j)
  }
  const fr = cap(front, 0, true)
  const br = cap(back, t, false)
  for (let j = 0; j < M; j++) idx.push(fr(j), fr(j + 1), br(j), fr(j + 1), br(j + 1), br(j))
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setIndex(idx)
  return g
}

/** Matrix taking surface-local coordinates to global coordinates. */
export function frameMatrix(s: SurfaceGeometry): THREE.Matrix4 {
  const m = s.matrix
  const o = s.origin
  return new THREE.Matrix4().set(m[0][0], m[0][1], m[0][2], o[0], m[1][0], m[1][1], m[1][2], o[1], m[2][0], m[2][1], m[2][2], o[2], 0, 0, 0, 1)
}

// LatheGeometry revolves (r, y) about +Y. Rotating +90 deg about X maps lathe y -> local +z
// (the optical axis), so profile points are written as (r, sag(r)).
const LATHE_TO_LOCAL = new THREE.Matrix4().makeRotationX(Math.PI / 2)

function lathe(pts: THREE.Vector2[], frame: THREE.Matrix4, segments = 160): THREE.BufferGeometry {
  const g = new THREE.LatheGeometry(pts, segments)
  g.applyMatrix4(LATHE_TO_LOCAL)
  g.applyMatrix4(frame)
  g.computeVertexNormals()
  return g
}

/** Closed lens element between two surfaces; also returns its centre thickness (mm). */
export function elementGeometry(front: SurfaceGeometry, back: SurfaceGeometry): { geo: THREE.BufferGeometry; thickness: number } | null {
  const hf = front.semi_diameter
  const hb = back.semi_diameter
  if (hf <= 0 && hb <= 0) return null
  const hm = Math.max(hf, hb)
  const inv = frameMatrix(front).invert()
  const backOrigin = new THREE.Vector3(...back.origin).applyMatrix4(inv)
  const t = backOrigin.z
  if (isNonRotational(front) || isNonRotational(back)) {
    const g = polarElement(front, back, t, hm)
    g.applyMatrix4(frameMatrix(front))
    g.computeVertexNormals()
    return { geo: g, thickness: Math.abs(t) }
  }
  const N = 64
  const pts: THREE.Vector2[] = []
  for (let k = 0; k <= N; k++) {
    const r = (hf * k) / N
    pts.push(new THREE.Vector2(r, sag(front, r)))
  }
  if (hf < hm) pts.push(new THREE.Vector2(hm, sag(front, hf)))
  if (hb < hm) pts.push(new THREE.Vector2(hm, t + sag(back, hb)))
  for (let k = N; k >= 0; k--) {
    const r = (hb * k) / N
    pts.push(new THREE.Vector2(r, t + sag(back, r)))
  }
  return { geo: lathe(pts, frameMatrix(front)), thickness: Math.abs(t) }
}

/** Ground (frosted) cylindrical edge of a rotationally symmetric element, drawn just outside the glass. */
export function edgeBand(front: SurfaceGeometry, back: SurfaceGeometry): THREE.BufferGeometry | null {
  const hf = front.semi_diameter
  const hb = back.semi_diameter
  if (hf <= 0 || hb <= 0 || isNonRotational(front) || isNonRotational(back)) return null
  const hm = Math.max(hf, hb) * 1.002
  const t = new THREE.Vector3(...back.origin).applyMatrix4(frameMatrix(front).invert()).z
  const z0 = sag(front, hf)
  const z1 = t + sag(back, hb)
  if (Math.abs(z1 - z0) < 1e-6) return null
  return lathe([new THREE.Vector2(hm, z0), new THREE.Vector2(hm, z1)], frameMatrix(front), 160)
}

/** The surface itself (mirror coating, image plane). */
export function surfaceDisk(s: SurfaceGeometry): THREE.BufferGeometry | null {
  if (s.semi_diameter <= 0) return null
  if (isNonRotational(s)) {
    const g = polarElement(s, s, 0, s.semi_diameter)
    g.applyMatrix4(frameMatrix(s))
    g.computeVertexNormals()
    return g
  }
  const N = 48
  const pts: THREE.Vector2[] = []
  for (let k = 0; k <= N; k++) {
    const r = (s.semi_diameter * k) / N
    pts.push(new THREE.Vector2(r, sag(s, r)))
  }
  return lathe(pts, frameMatrix(s))
}

/** Mirror blank behind the reflecting surface: rim cylinder and flat back, on the side away from the incoming light. */
export function mirrorBlank(s: SurfaceGeometry, side: 1 | -1): THREE.BufferGeometry | null {
  const h = s.semi_diameter
  if (h <= 0) return null
  const d = Math.max(1.5, 0.16 * h) * side
  const zr = sag(s, h)
  const zb = side > 0 ? Math.max(0, zr) + d : Math.min(0, zr) + d
  const pts = [new THREE.Vector2(h, zr), new THREE.Vector2(h, zb), new THREE.Vector2(0, zb)]
  if (side < 0) pts.reverse()
  return lathe(pts, frameMatrix(s), 128)
}

/** Iris ring of the aperture stop (outside the clear aperture). */
export function stopRing(s: SurfaceGeometry): THREE.BufferGeometry | null {
  const r0 = s.semi_diameter
  if (r0 <= 0) return null
  const g = new THREE.RingGeometry(r0, r0 * 1.45 + 1, 128, 1)
  g.applyMatrix4(frameMatrix(s))
  return g
}

export function rimGeometry(s: SurfaceGeometry): THREE.BufferGeometry {
  const pts: THREE.Vector3[] = []
  for (let k = 0; k <= 160; k++) {
    const a = (2 * Math.PI * k) / 160
    const x = s.semi_diameter * Math.cos(a)
    const y = s.semi_diameter * Math.sin(a)
    pts.push(new THREE.Vector3(x, y, sagXY(s, x, y)))
  }
  const g = new THREE.BufferGeometry().setFromPoints(pts)
  g.applyMatrix4(frameMatrix(s))
  return g
}

export function b64ToBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out.buffer
}

const DEG = Math.PI / 180

/** Placement matrix of a CAD model (p_global = T Rx Ry Rz p, as the engine). */
export function assetMatrix(a: CadAsset): THREE.Matrix4 {
  const r = a.transform.rotate_deg
  const m = new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(r[0] * DEG, r[1] * DEG, r[2] * DEG, 'XYZ'))
  m.setPosition(...a.transform.translate)
  return m
}

type P3 = [number, number, number]

/** Drawn ray polylines in global coordinates. Rays from an object at infinity start a short
 * distance (15 % of the track, at least 10 mm) before the first surface, along their start direction. */
export function rayPolylines(ev: Evaluation, infinite: boolean): { field: number; pts: P3[] }[] {
  const zs = ev.global_vertex_z ?? [0]
  const len = zs.length ? Math.max(...zs) - Math.min(...zs) : 0
  const L = Math.max(10, len * 0.15)
  const out: { field: number; pts: P3[] }[] = []
  for (const r of ev.rays3d ?? []) {
    let pts = r.points
    if (pts.length < 2 && !(infinite && pts.length >= 1)) continue
    if (infinite) {
      const p = pts[1] ?? pts[0]
      const d = r.start_dir
      pts = [[p[0] - d[0] * L, p[1] - d[1] * L, p[2] - d[2] * L], ...pts.slice(1)]
    }
    out.push({ field: r.field, pts })
  }
  return out
}

/** Bounding box of the drawn optics (surfaces, stop iris, rays) and optionally of the visible CAD models, in global coordinates. */
export function sceneBounds(ev: Evaluation, cad: CadAsset[], withCad: boolean, infinite = false): THREE.Box3 {
  const box = new THREE.Box3()
  for (const s of ev.surfaces) {
    if (s.type === 'coordinate_break') continue
    const m = frameMatrix(s)
    const h = s.is_stop && s.semi_diameter > 0 ? s.semi_diameter * 1.45 + 1 : Math.max(s.semi_diameter, 0.5)
    for (const [x, y] of [
      [h, 0],
      [-h, 0],
      [0, h],
      [0, -h],
      [0, 0],
    ])
      box.expandByPoint(new THREE.Vector3(x, y, 0).applyMatrix4(m))
  }
  for (const r of rayPolylines(ev, infinite)) for (const p of r.pts) box.expandByPoint(new THREE.Vector3(p[0], p[1], p[2]))
  if (withCad)
    for (const a of cad) {
      if (!a.visible) continue
      const m = assetMatrix(a)
      for (const cx of [a.bbox_min[0], a.bbox_max[0]])
        for (const cy of [a.bbox_min[1], a.bbox_max[1]]) for (const cz of [a.bbox_min[2], a.bbox_max[2]]) box.expandByPoint(new THREE.Vector3(cx, cy, cz).applyMatrix4(m))
    }
  if (box.isEmpty()) box.set(new THREE.Vector3(-10, -10, -10), new THREE.Vector3(10, 10, 10))
  return box
}

/** Side of a mirror the light comes from, in its local frame (+1: light travels towards local +z). */
export function mirrorSide(ev: Evaluation, i: number): 1 | -1 {
  const s = ev.surfaces[i]
  for (let k = i - 1; k >= 0; k--) {
    const p = ev.surfaces[k]
    if (p.type === 'coordinate_break') continue
    const d = new THREE.Vector3(...s.origin).sub(new THREE.Vector3(...p.origin))
    if (d.lengthSq() < 1e-12) continue
    const local = d.applyMatrix4(new THREE.Matrix4().extractRotation(frameMatrix(s)).invert())
    return local.z >= 0 ? 1 : -1
  }
  return 1
}

export function niceStep(raw: number): number {
  const p = Math.pow(10, Math.floor(Math.log10(raw)))
  const f = raw / p
  return (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * p
}

/** Camera framing of a box seen along `dir` (unit vector from the target towards the camera):
 * the perspective distance and the orthographic half extents that fit every box corner
 * (tighter than a bounding sphere for long, thin optical systems). */
export function fitView(box: THREE.Box3, dir: THREE.Vector3, vfovDeg: number, aspect: number, margin = 1.08): { center: THREE.Vector3; distance: number; halfW: number; halfH: number } {
  const c = box.getCenter(new THREE.Vector3())
  const f = dir.clone().normalize()
  const up = Math.abs(f.y) > 0.999 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(0, 1, 0)
  const r = new THREE.Vector3().crossVectors(up, f).normalize()
  const u = new THREE.Vector3().crossVectors(f, r)
  const tanV = Math.tan((vfovDeg * Math.PI) / 360) / margin
  const tanH = tanV * aspect
  let distance = 0
  let halfW = 1e-6
  let halfH = 1e-6
  let zmax = 0
  for (const x of [box.min.x, box.max.x])
    for (const y of [box.min.y, box.max.y])
      for (const z of [box.min.z, box.max.z]) {
        const q = new THREE.Vector3(x, y, z).sub(c)
        const qx = Math.abs(q.dot(r))
        const qy = Math.abs(q.dot(u))
        const qz = q.dot(f)
        distance = Math.max(distance, qx / tanH + qz, qy / tanV + qz)
        halfW = Math.max(halfW, qx)
        halfH = Math.max(halfH, qy)
        zmax = Math.max(zmax, qz)
      }
  // keep the camera outside the box
  distance = Math.max(distance, zmax * 1.05 + 1e-3)
  return { center: c, distance, halfW: halfW * margin, halfH: halfH * margin }
}

/** Ground grid in the x-z plane (y = 0) as line segments with a radial alpha fade (RGBA vertex colours).
 * Minor lines every `cell`, major lines every `major` cells; at most `maxHalf` cells either side of the centre. */
export function groundGrid(cx: number, cz: number, cell: number, halfExtent: number, minor: THREE.Color, majorColor: THREE.Color, major = 5, maxHalf = 80): THREE.BufferGeometry {
  const n = Math.max(1, Math.min(maxHalf, Math.ceil(halfExtent / cell)))
  // snap to the grid so lines stay put while the centre moves
  const x0 = Math.round(cx / cell) * cell
  const z0 = Math.round(cz / cell) * cell
  const R = n * cell
  const pos: number[] = []
  const col: number[] = []
  const alpha = (x: number, z: number) => {
    const d = Math.hypot(x - x0, z - z0) / R
    return d >= 1 ? 0 : Math.pow(1 - d * d, 1.6)
  }
  const seg = (ax: number, az: number, bx: number, bz: number, c: THREE.Color, w: number) => {
    pos.push(ax, 0, az, bx, 0, bz)
    col.push(c.r, c.g, c.b, alpha(ax, az) * w, c.r, c.g, c.b, alpha(bx, bz) * w)
  }
  for (let i = -n; i <= n; i++) {
    const isMajor = i % major === 0
    const c = isMajor ? majorColor : minor
    const w = isMajor ? 1 : 0.7
    for (let k = -n; k < n; k++) {
      // a line along z at x = x0 + i cell, split into cells so the fade is smooth
      seg(x0 + i * cell, z0 + k * cell, x0 + i * cell, z0 + (k + 1) * cell, c, w)
      seg(x0 + k * cell, z0 + i * cell, x0 + (k + 1) * cell, z0 + i * cell, c, w)
    }
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 4))
  return g
}
