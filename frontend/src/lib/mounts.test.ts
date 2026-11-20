// Mount tree helpers (ADR-028): CAD part extents along the axis and parent choices.
import { describe, expect, it } from 'vitest'
import { axialPositions, axialRange, cadParts, gapSetByMounts, parentChoices } from './mounts'
import { blankProject } from './project'
import type { CadAsset, MountPart } from './types'

const part = (id: string, parent: string | null): MountPart => ({ id, name: id, cte: 23.6, temperature_c: null, parent, datum_z: 0, cad_asset_id: null, cad_node_id: null })

describe('mount helpers', () => {
  it('finds the axial extent of a placed CAD box', () => {
    const a = { transform: { translate: [0, 0, 50] as [number, number, number], rotate_deg: [0, 0, 0] as [number, number, number] } }
    expect(axialRange(a, [-5, -5, 0], [5, 5, 30])).toEqual([50, 80])
    // turned 90° about y: the box's x extent lies along the axis (z = -x)
    const r = axialRange({ transform: { translate: [0, 0, 10], rotate_deg: [0, 90, 0] } }, [0, -1, -1], [20, 1, 1])
    expect(r[0]).toBeCloseTo(-10, 9)
    expect(r[1]).toBeCloseTo(10, 9)
  })

  it('lists the leaf parts of assemblies with their extents', () => {
    const asset = {
      id: 'a1',
      name: 'Barrel',
      transform: { translate: [0, 0, 0], rotate_deg: [0, 0, 0] },
      bbox_min: [0, 0, 0],
      bbox_max: [1, 1, 1],
      tree: [
        { id: 'r', name: 'Assy', kind: 'assembly', children: [{ id: 'p1', name: 'Tube', kind: 'part', children: [], bbox_min: [-10, -10, 5], bbox_max: [10, 10, 97], solids: 1, volume_mm3: null, area_mm2: 0, tri_start: 0, tri_count: 0, color: null }], bbox_min: [0, 0, 0], bbox_max: [0, 0, 0], solids: 1, volume_mm3: null, area_mm2: 0, tri_start: 0, tri_count: 0, color: null },
      ],
    } as unknown as CadAsset
    const parts = cadParts({ cad_assets: [asset] })
    expect(parts).toEqual([{ assetId: 'a1', nodeId: 'p1', label: 'Barrel: Assy / Tube', zMin: 5, zMax: 97 }])
  })

  it('offers no parent that would make a cycle', () => {
    const ms = [part('housing', null), part('cell', 'housing'), part('ring', 'cell'), part('other', null)]
    expect(parentChoices(ms, 'cell').map((m) => m.id)).toEqual(['housing', 'other'])
    expect(parentChoices(ms, 'housing').map((m) => m.id)).toEqual(['other'])
  })

  it('measures vertex positions from surface 1', () => {
    const p = blankProject()
    const z = axialPositions(p.system)
    expect(z[1]).toBe(0)
    expect(z[2]).toBe(p.system.surfaces[1].thickness)
    expect(z[3]).toBe((p.system.surfaces[1].thickness ?? 0) + (p.system.surfaces[2].thickness ?? 0))
  })

  it('knows which gaps the mounts set', () => {
    const p = blankProject()
    const sys = p.system
    // blank project: object, lens front (glass), lens back (air), image
    expect(sys.surfaces.length).toBe(4)
    expect(gapSetByMounts(sys, 2)).toBe(false)
    sys.surfaces[3].seat_part = 'holder'
    expect(gapSetByMounts(sys, 2)).toBe(true)
    // the lens is one element: seating its back surface sets the gap in front of it
    sys.surfaces[2].seat_part = 'cell'
    expect(gapSetByMounts(sys, 0)).toBe(true)
    // seats are ignored with a mirror
    sys.surfaces[2].material = 'MIRROR'
    expect(gapSetByMounts(sys, 2)).toBe(false)
  })
})
