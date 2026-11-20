import * as THREE from 'three'
import { describe, expect, it } from 'vitest'
import type { CadAsset, Evaluation, SurfaceGeometry } from '../../../lib/types'
import { edgeBand, elementGeometry, fitView, frameMatrix, mirrorBlank, mirrorSide, niceStep, sceneBounds, stopRing } from './geometry'

const I3 = [
  [1, 0, 0],
  [0, 1, 0],
  [0, 0, 1],
]

function surf(z: number, over: Partial<SurfaceGeometry> = {}): SurfaceGeometry {
  return { index: 0, id: 's' + z, type: 'standard', semi_diameter: 10, origin: [0, 0, z], matrix: I3, profile: [], curvature: 0, conic: 0, aspheric: [], is_mirror: false, is_stop: false, ...over } as SurfaceGeometry
}

function evalOf(surfaces: SurfaceGeometry[]): Evaluation {
  return { surfaces } as unknown as Evaluation
}

describe('3D drawing geometry', () => {
  it('frameMatrix maps local to global (rotation then origin)', () => {
    // 90 deg about x: local +z -> global -y
    const s = surf(5, { origin: [1, 2, 3], matrix: [[1, 0, 0], [0, 0, -1], [0, 1, 0]] })
    const p = new THREE.Vector3(0, 0, 1).applyMatrix4(frameMatrix(s))
    expect(p.x).toBeCloseTo(1, 12)
    expect(p.y).toBeCloseTo(1, 12)
    expect(p.z).toBeCloseTo(3, 12)
  })

  it('element mesh spans the two surfaces and reports the centre thickness', () => {
    const R = 50
    const e = elementGeometry(surf(0, { curvature: 1 / R }), surf(6, { curvature: -1 / R }))!
    expect(e.thickness).toBeCloseTo(6, 12)
    e.geo.computeBoundingBox()
    const b = e.geo.boundingBox!
    expect(b.max.x).toBeCloseTo(10, 6)
    expect(b.min.y).toBeCloseTo(-10, 6)
    // biconvex: the vertices are the extreme points along z
    expect(b.min.z).toBeCloseTo(0, 6)
    expect(b.max.z).toBeCloseTo(6, 6)
  })

  it('no element without an aperture', () => {
    expect(elementGeometry(surf(0, { semi_diameter: 0 }), surf(5, { semi_diameter: 0 }))).toBeNull()
  })

  it('mirror blank lies behind the reflecting side', () => {
    const s = surf(0, { is_mirror: true })
    const back = mirrorBlank(s, 1)!
    back.computeBoundingBox()
    expect(back.boundingBox!.min.z).toBeGreaterThanOrEqual(-1e-6)
    expect(back.boundingBox!.max.z).toBeCloseTo(1.6, 5) // max(1.5, 0.16 h); Float32 vertices
    const front = mirrorBlank(s, -1)!
    front.computeBoundingBox()
    expect(front.boundingBox!.max.z).toBeLessThanOrEqual(1e-6)
  })

  it('mirrorSide follows the incoming light in the mirror frame', () => {
    const ev = evalOf([surf(0), surf(100, { is_mirror: true })])
    expect(mirrorSide(ev, 1)).toBe(1)
    const flipped = evalOf([surf(0), surf(100, { is_mirror: true, matrix: [[1, 0, 0], [0, -1, 0], [0, 0, -1]] })])
    expect(mirrorSide(flipped, 1)).toBe(-1)
  })

  it('stop ring sits outside the clear aperture', () => {
    const g = stopRing(surf(0, { semi_diameter: 4 }))!
    g.computeBoundingBox()
    expect(g.boundingBox!.max.x).toBeCloseTo(4 * 1.45 + 1, 5)
  })

  it('scene bounds include optics and, optionally, placed CAD models', () => {
    const ev = evalOf([surf(0), surf(40), { ...surf(60), type: 'coordinate_break', semi_diameter: 1000 } as SurfaceGeometry])
    const cad = [{ visible: true, bbox_min: [0, 0, 0], bbox_max: [1, 1, 1], transform: { translate: [0, 0, 200], rotate_deg: [0, 0, 0] } }] as unknown as CadAsset[]
    const optics = sceneBounds(ev, cad, false)
    expect(optics.max.z).toBeCloseTo(40, 12) // coordinate breaks are not drawn
    expect(optics.max.y).toBeCloseTo(10, 12)
    expect(sceneBounds(ev, cad, true).max.z).toBeCloseTo(201, 12)
  })

  it('niceStep rounds to 1-2-5 decades', () => {
    expect(niceStep(0.13)).toBeCloseTo(0.1, 12)
    expect(niceStep(2.4)).toBe(2)
    expect(niceStep(4)).toBe(5)
    expect(niceStep(80)).toBe(100)
  })

  it('fitView frames every box corner (perspective distance, orthographic extents)', () => {
    const box = new THREE.Box3(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1))
    // 90 deg vertical fov: the near face (z = 1) must be 1 unit wide at distance d - 1
    const f = fitView(box, new THREE.Vector3(0, 0, 1), 90, 1, 1)
    expect(f.distance).toBeCloseTo(2, 12)
    expect(f.halfW).toBeCloseTo(1, 12)
    expect(f.halfH).toBeCloseTo(1, 12)
    // a long system seen from the side needs its length across, not a bounding sphere
    const rod = new THREE.Box3(new THREE.Vector3(-1, -1, -50), new THREE.Vector3(1, 1, 50))
    const side = fitView(rod, new THREE.Vector3(-1, 0, 0), 90, 2, 1)
    expect(side.halfW).toBeCloseTo(50, 12)
    expect(side.distance).toBeCloseTo(50 / 2 + 1, 12)
    expect(side.distance).toBeLessThan(rod.getBoundingSphere(new THREE.Sphere()).radius * Math.SQRT2)
  })

  it('edge band covers the cylindrical rim between the two surfaces', () => {
    const g = edgeBand(surf(0, { curvature: 1 / 50 }), surf(6, { curvature: -1 / 50 }))!
    g.computeBoundingBox()
    const zr = 50 - Math.sqrt(50 * 50 - 100)
    expect(g.boundingBox!.min.z).toBeCloseTo(zr, 4)
    expect(g.boundingBox!.max.z).toBeCloseTo(6 - zr, 4)
    expect(g.boundingBox!.max.x).toBeCloseTo(10 * 1.002, 4)
  })
})
