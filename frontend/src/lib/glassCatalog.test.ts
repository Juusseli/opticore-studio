import { beforeEach, describe, expect, it } from 'vitest'
import { registerCatalogIndex, useProjectStore } from '../store/projectStore'
import { buildCatalogIndex, embedCatalogGlasses, nearestGlasses, recordsFor, usedMaterialNames } from './glassCatalog'
import { blankProject } from './project'
import type { GlassCatalog, MaterialRecord } from './types'

function rec(name: string, catalog: string, nd = 1.5, vd = 60, status: MaterialRecord['status'] = 'standard'): MaterialRecord {
  return { name, formula: 'constant', coefficients: [nd], family: catalog, category: 'glass', catalog, status, nd_ref: nd, vd_ref: vd }
}

function cat(name: string, recs: MaterialRecord[]): GlassCatalog {
  return {
    id: name,
    name,
    filename: name + '.agf',
    imported_at: '2026-10-11T00:00:00Z',
    comments: [],
    records: recs,
    summaries: recs.map((r) => ({ ...r, nd: r.nd_ref ?? null, vd: r.vd_ref ?? null, nF_minus_nC: null, has_thermal_model: false, builtin: false })),
    diagnostics: [],
  }
}

const A = cat('ALPHA', [rec('A-1', 'ALPHA', 1.5, 60), rec('N-BK7', 'ALPHA'), rec('SHARED', 'ALPHA', 1.6, 40)])
const B = cat('BETA', [rec('B-1', 'BETA', 1.72, 29), rec('SHARED', 'BETA', 1.61, 41), rec('B-OLD', 'BETA', 1.51, 59, 'obsolete')])

describe('glass catalogue index', () => {
  it('resolves names with built-in and earlier-catalogue precedence and lists the shadowed ones', () => {
    const idx = buildCatalogIndex([B, A], ['N-BK7', 'F2'])
    expect([...idx.byName.keys()].sort()).toEqual(['A-1', 'B-1', 'B-OLD', 'SHARED'])
    expect(idx.byName.get('SHARED')!.catalog).toBe('ALPHA') // catalogues in name order
    expect(idx.shadowed).toEqual([
      { name: 'N-BK7', catalog: 'ALPHA', by: 'built-in' },
      { name: 'SHARED', catalog: 'BETA', by: 'ALPHA' },
    ])
  })

  it('collects every material a project refers to', () => {
    const p = blankProject()
    p.system.surfaces[1].material = 'b-1'
    p.system.multi_config = { names: ['a', 'b'], active: 0, operands: [{ parameter: 'material', surface_id: p.system.surfaces[1].id, values: ['B-1', 'A-1'] }] }
    p.system.custom_coatings = [{ name: 'C', description: '', layers: [{ material: 'shared', index: 1.4, extinction: 0, thickness_nm: 100 }], substrate_index: null, substrate_extinction: 0 }]
    const used = usedMaterialNames(p)
    expect(used.has('B-1') && used.has('A-1') && used.has('SHARED')).toBe(true)
    expect(used.has('AIR')).toBe(false)
  })

  it('embeds used catalogue glasses once, leaves built-in and existing custom materials alone', () => {
    const idx = buildCatalogIndex([A, B], ['N-BK7'])
    const p = blankProject()
    p.system.surfaces[1].material = 'B-1'
    p.custom_materials.push({ ...rec('A-1', 'MINE', 1.9, 20) })
    p.system.surfaces[2].material = 'A-1'
    expect(embedCatalogGlasses(p, idx)).toEqual(['B-1'])
    expect(p.custom_materials.map((m) => m.name)).toEqual(['A-1', 'B-1'])
    expect(p.custom_materials[0].family).toBe('MINE') // the project's own definition wins
    expect(embedCatalogGlasses(p, idx)).toEqual([])
    // the stored copy is independent of the catalogue object
    p.custom_materials[1].coefficients[0] = 9
    expect(idx.byName.get('B-1')!.record.coefficients[0]).toBe(1.72)
  })

  it('recordsFor returns only catalogue definitions the request is missing', () => {
    const idx = buildCatalogIndex([A, B], ['N-BK7'])
    expect(recordsFor(['b-1', 'N-BK7', 'A-1', 'B-1', 'NOPE'], idx, [rec('A-1', 'X')]).map((r) => r.name)).toEqual(['B-1'])
  })

  it('nearestGlasses ranks by distance on the glass map and skips obsolete glasses', () => {
    const pts = [
      { name: 'X', nd: 1.5, vd: 60 },
      { name: 'NEAR', nd: 1.505, vd: 59.5 },
      { name: 'OLD', nd: 1.5, vd: 60.1, status: 'obsolete' },
      { name: 'FAR', nd: 1.8, vd: 25 },
      { name: 'VDFAR', nd: 1.5, vd: 50 },
      { name: 'FLAGGED', nd: 1.5, vd: 60, verified: false },
    ]
    expect(nearestGlasses({ nd: 1.5, vd: 60 }, pts, 3)).toEqual(['X', 'NEAR', 'VDFAR'])
    expect(nearestGlasses({ nd: 1.5, vd: 60 }, pts, 2, { includeObsolete: true })).toEqual(['X', 'OLD'])
  })
})

describe('projectStore commit embeds catalogue glasses', () => {
  beforeEach(() => {
    useProjectStore.getState().setProject(blankProject('Test'))
  })
  it('a material assignment through commit copies the glass into the project; undo removes it', () => {
    const idx = buildCatalogIndex([A, B], [])
    registerCatalogIndex(() => idx)
    try {
      const st = useProjectStore.getState()
      const before = st.project.custom_materials.length
      st.updateSurface(1, { material: 'B-1' })
      const p = useProjectStore.getState().project
      expect(p.custom_materials.map((m) => m.name)).toContain('B-1')
      expect(p.custom_materials.length).toBe(before + 1)
      useProjectStore.getState().undo()
      expect(useProjectStore.getState().project.custom_materials.length).toBe(before)
    } finally {
      registerCatalogIndex(() => null)
    }
  })
})
