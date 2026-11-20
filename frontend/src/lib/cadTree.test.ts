import { describe, expect, it } from 'vitest'
import { countParts, effectiveOptical, findNode, partAtTriangle, visibleRanges } from './cadTree'
import type { CadAsset, CadTreeNode } from './types'

const node = (id: string, kind: 'assembly' | 'part', tri_start: number, tri_count: number, children: CadTreeNode[] = []): CadTreeNode => ({
  id,
  name: id,
  kind,
  tri_start,
  tri_count,
  color: null,
  children,
  solids: 1,
  volume_mm3: 1,
  area_mm2: 1,
  bbox_min: [0, 0, 0],
  bbox_max: [1, 1, 1],
})

// top (1) = plate (1.1: 0..12) + posts (1.2) = post (1.2.1: 12..40) + post (1.2.2: 40..68)
const tree = [node('1', 'assembly', 0, 68, [node('1.1', 'part', 0, 12), node('1.2', 'assembly', 12, 56, [node('1.2.1', 'part', 12, 28), node('1.2.2', 'part', 40, 28)])])]

describe('CAD assembly tree helpers', () => {
  it('merges visible triangle ranges and drops hidden subtrees', () => {
    expect(visibleRanges(tree, [], 68)).toEqual([[0, 68]])
    expect(visibleRanges(tree, ['1.2.1'], 68)).toEqual([
      [0, 12],
      [40, 28],
    ])
    expect(visibleRanges(tree, ['1.2'], 68)).toEqual([[0, 12]])
    expect(visibleRanges([], [], 30)).toEqual([[0, 30]]) // no structure (STL): the whole mesh
  })
  it('finds the part under a picked triangle', () => {
    expect(partAtTriangle(tree, 0)?.id).toBe('1.1')
    expect(partAtTriangle(tree, 39)?.id).toBe('1.2.1')
    expect(partAtTriangle(tree, 40)?.id).toBe('1.2.2')
    expect(partAtTriangle(tree, 68)).toBeNull()
    expect(findNode(tree, '1.2')?.kind).toBe('assembly')
    expect(countParts(tree)).toBe(3)
  })
  it('inherits optical role overrides down the tree', () => {
    const a = { optical: { role: 'absorber', material: null }, part_roles: { '1.2': { role: 'mirror', material: null } } } as unknown as CadAsset
    expect(effectiveOptical(a, ['1', '1.2', '1.2.1']).role).toBe('mirror')
    expect(effectiveOptical(a, ['1', '1.2', '1.2.1']).from).toBe('1.2')
    expect(effectiveOptical(a, ['1', '1.1']).role).toBe('absorber')
    expect(effectiveOptical(a, ['1', '1.2']).inherited).toBe(false)
  })
})
