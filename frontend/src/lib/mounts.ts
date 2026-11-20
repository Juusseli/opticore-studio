// Mount tree helpers for the Mounts tab (engine: backend environment.py, ADR-028). Only geometry bookkeeping:
// where a CAD part lies along the optical axis, and which parts may be a part's parent.
import type { CadAsset, CadTreeNode, MountPart, OpticalSystem, Project } from './types'

export interface CadPartRef {
  assetId: string
  nodeId: string
  label: string
  /** axial extent of the part's bounding box in the optical frame (mm) */
  zMin: number
  zMax: number
}

/** R = Rx(rx) Ry(ry) Rz(rz) (degrees; the placement convention of CadTransform). */
function rotation(r: [number, number, number]): number[][] {
  const [a, b, c] = r.map((d) => (d * Math.PI) / 180)
  const rx = [
    [1, 0, 0],
    [0, Math.cos(a), -Math.sin(a)],
    [0, Math.sin(a), Math.cos(a)],
  ]
  const ry = [
    [Math.cos(b), 0, Math.sin(b)],
    [0, 1, 0],
    [-Math.sin(b), 0, Math.cos(b)],
  ]
  const rz = [
    [Math.cos(c), -Math.sin(c), 0],
    [Math.sin(c), Math.cos(c), 0],
    [0, 0, 1],
  ]
  const mul = (p: number[][], q: number[][]) => p.map((row) => q[0].map((_, j) => row.reduce((s, v, k) => s + v * q[k][j], 0)))
  return mul(mul(rx, ry), rz)
}

/** Axial (z) range of a box in asset coordinates after the asset's placement. */
export function axialRange(asset: Pick<CadAsset, 'transform'>, bmin: [number, number, number], bmax: [number, number, number]): [number, number] {
  const R = rotation(asset.transform.rotate_deg)
  const tz = asset.transform.translate[2]
  let lo = Infinity
  let hi = -Infinity
  for (const x of [bmin[0], bmax[0]])
    for (const y of [bmin[1], bmax[1]])
      for (const z of [bmin[2], bmax[2]]) {
        const gz = R[2][0] * x + R[2][1] * y + R[2][2] * z + tz
        lo = Math.min(lo, gz)
        hi = Math.max(hi, gz)
      }
  return [lo, hi]
}

/** Every part (leaf) of every CAD model, and single-body models, with their axial extents. */
export function cadParts(project: Pick<Project, 'cad_assets'>): CadPartRef[] {
  const out: CadPartRef[] = []
  for (const a of project.cad_assets) {
    const walk = (nodes: CadTreeNode[], path: string) => {
      for (const n of nodes) {
        const label = path ? `${path} / ${n.name}` : n.name
        if (n.kind === 'part' || !n.children.length) {
          const [zMin, zMax] = axialRange(a, n.bbox_min, n.bbox_max)
          out.push({ assetId: a.id, nodeId: n.id, label: `${a.name}: ${label}`, zMin, zMax })
        } else walk(n.children, label)
      }
    }
    if (a.tree && a.tree.length) walk(a.tree, '')
    else {
      const [zMin, zMax] = axialRange(a, a.bbox_min as [number, number, number], a.bbox_max as [number, number, number])
      out.push({ assetId: a.id, nodeId: '', label: a.name, zMin, zMax })
    }
  }
  return out
}

/** Parts that may become `id`'s parent: every part except itself and its descendants (no cycles). */
export function parentChoices(mounts: MountPart[], id: string): MountPart[] {
  const below = new Set<string>([id])
  let grew = true
  while (grew) {
    grew = false
    for (const m of mounts)
      if (m.parent && below.has(m.parent) && !below.has(m.id)) {
        below.add(m.id)
        grew = true
      }
  }
  return mounts.filter((m) => !below.has(m.id))
}

/** Nominal axial position of each surface vertex from surface 1 (the mount coordinate). */
export function axialPositions(sys: OpticalSystem): number[] {
  const z = [0]
  for (let i = 1; i < sys.surfaces.length; i++) z.push(i === 1 ? 0 : z[i - 1] + (sys.surfaces[i - 1].thickness ?? 0))
  return z
}

const glassMedium = (m: string) => !['', 'AIR', 'VACUUM', 'MIRROR'].includes(m.trim().toUpperCase())

/** Whether the mount tree sets the gap after surface i: the element that follows it is seated, so the gap's
 *  own spacer expansion is unused (engine: environment.mount_layout). Never with mirrors or coordinate breaks,
 *  where the seats are ignored. */
export function gapSetByMounts(sys: OpticalSystem, i: number): boolean {
  const s = sys.surfaces
  if (s.some((x) => x.type === 'coordinate_break' || x.material.trim().toUpperCase() === 'MIRROR')) return false
  for (let k = i + 1; k < s.length; k++) {
    if (s[k].seat_part) return true
    if (!glassMedium(s[k].material)) return false // the element ends at surface k
  }
  return false
}
