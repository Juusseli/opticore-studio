import type { CadAsset, CadOptical, CadTreeNode } from './types'

/** Depth-first walk of an assembly tree with the ancestor path of each node (including itself). */
export function walkTree(nodes: CadTreeNode[], fn: (n: CadTreeNode, path: string[]) => void, path: string[] = []): void {
  for (const n of nodes) {
    const p = [...path, n.id]
    fn(n, p)
    walkTree(n.children, fn, p)
  }
}

export function findNode(nodes: CadTreeNode[], id: string): CadTreeNode | null {
  let hit: CadTreeNode | null = null
  walkTree(nodes, (n) => {
    if (n.id === id) hit = n
  })
  return hit
}

/** A node is hidden when it or any ancestor is in `hidden`. */
export const isHiddenPath = (path: string[], hidden: string[]) => path.some((id) => hidden.includes(id))

/** Triangle ranges [start, count] of the visible parts (contiguous ranges merged). */
export function visibleRanges(nodes: CadTreeNode[], hidden: string[], total: number): [number, number][] {
  if (!nodes.length) return total > 0 ? [[0, total]] : []
  const out: [number, number][] = []
  walkTree(nodes, (n, path) => {
    if (n.kind !== 'part' || n.tri_count === 0 || isHiddenPath(path, hidden)) return
    const last = out[out.length - 1]
    if (last && last[0] + last[1] === n.tri_start) last[1] += n.tri_count
    else out.push([n.tri_start, n.tri_count])
  })
  return out
}

/** Part (leaf) that owns triangle `tri` of the display mesh. */
export function partAtTriangle(nodes: CadTreeNode[], tri: number): CadTreeNode | null {
  let hit: CadTreeNode | null = null
  walkTree(nodes, (n) => {
    if (n.kind === 'part' && tri >= n.tri_start && tri < n.tri_start + n.tri_count) hit = n
  })
  return hit
}

/** Optical settings of a node: the nearest override on its path, else the asset's own. */
export function effectiveOptical(a: CadAsset, path: string[]): CadOptical & { inherited: boolean; from: string | null } {
  const roles = a.part_roles ?? {}
  for (let k = path.length - 1; k >= 0; k--) {
    const o = roles[path[k]]
    if (o) return { ...(a.optical ?? { role: 'none', material: null }), ...o, inherited: k !== path.length - 1, from: path[k] }
  }
  return { ...(a.optical ?? { role: 'none', material: null }), inherited: true, from: null }
}

export const countParts = (nodes: CadTreeNode[]) => {
  let k = 0
  walkTree(nodes, (n) => void (n.kind === 'part' && k++))
  return k
}
