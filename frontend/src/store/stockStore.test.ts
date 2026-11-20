import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { insertStockLens } from '../actions'
import { filterStock } from '../components/dialogs/stockFilter'
import { stockBuildSpec, stockGlasses, type DsSettings } from '../components/views/designSpace'
import { api } from '../lib/api'
import { blankProject } from '../lib/project'
import { storage } from '../lib/storage'
import type { MaterialRecord, StockLensInfo } from '../lib/types'
import { useProjectStore } from './projectStore'
import { GENERIC_ID, lensesFor, toStockLens, useStockStore } from './stockStore'

const st = () => useProjectStore.getState()

const lens = (part: string, efl: number, materials: string[], extra: Partial<StockLensInfo> = {}): StockLensInfo => ({
  part,
  vendor: 'Acme',
  catalog: 'Mine',
  kind: materials.length === 2 ? 'achromat' : 'plano_convex',
  radii: materials.length === 2 ? [60, -45, -130] : [51.7, null],
  thicknesses: materials.length === 2 ? [4, 2.5] : [4],
  materials,
  diameter: 25.4,
  clear: 22.86,
  key: `Mine:${part}`,
  paraxial: { efl, bfd: efl - 2, ffd: -efl, rear_principal: -2, front_principal: 0, length: 4 },
  ...extra,
})

describe('stock lenses', () => {
  beforeEach(() => st().setProject(blankProject('Stock')))
  afterEach(() => {
    vi.restoreAllMocks()
    useStockStore.setState({ catalogs: [], generic: null })
  })

  it('sends the engine plain lens records and only the chosen catalogues', () => {
    const a = lens('A', 100, ['N-BK7'])
    expect(Object.keys(toStockLens(a))).not.toContain('paraxial')
    expect(toStockLens(a).part).toBe('A')
    const glass = { name: 'MY-GLASS' } as MaterialRecord
    const cats = [
      { id: 'c1', name: 'One', vendor: '', imported_at: '', source: 'zmx' as const, lenses: [a], custom_materials: [glass], diagnostics: [] },
      { id: 'c2', name: 'Two', vendor: '', imported_at: '', source: 'csv' as const, lenses: [lens('B', 50, ['N-SF6'])], custom_materials: [], diagnostics: [] },
    ]
    const r = lensesFor([GENERIC_ID, 'c1'], cats)
    expect(r.lenses.map((l) => l.part)).toEqual(['A'])
    expect(r.custom).toEqual([glass])
    expect(stockGlasses([GENERIC_ID, 'c2'], [{ materials: ['N-BK7'] }], cats)).toEqual(['N-BK7', 'N-SF6'])
  })

  it('imports vendor ZMX files into a catalogue and extends it on the next import', async () => {
    vi.spyOn(storage, 'putStockCatalog').mockResolvedValue()
    vi.spyOn(api, 'stockImportZmx')
      .mockResolvedValueOnce({ catalog: 'Mine', lenses: [lens('A', 100, ['N-BK7'])], custom_materials: [], files: [{ filename: 'A.zmx', ok: true, part: 'A' }, { filename: 'bad.zmx', ok: false, error: 'No lens' }] })
      .mockResolvedValueOnce({ catalog: 'Mine', lenses: [lens('B', 50, ['N-BK7']), lens('A', 101, ['N-BK7'])], custom_materials: [], files: [] })
    const r1 = await useStockStore.getState().importZmx([{ name: 'A.zmx', base64: '' }, { name: 'bad.zmx', base64: '' }], 'Mine', 'Acme')
    expect(r1.added).toBe(1)
    expect(r1.failed).toEqual([{ filename: 'bad.zmx', error: 'No lens' }])
    const r2 = await useStockStore.getState().importZmx([{ name: 'B.zmx', base64: '' }], 'Mine', '')
    expect(r2.catalog.id).toBe(r1.catalog.id) // the same catalogue, extended
    expect(r2.catalog.lenses.map((l) => [l.part, l.paraxial.efl])).toEqual([
      ['A', 101],
      ['B', 50],
    ])
    expect(r2.catalog.vendor).toBe('Acme')
    expect(useStockStore.getState().catalogs).toHaveLength(1)
  })

  it('filters by type, glass, diameter, focal length and text', () => {
    const all = [lens('PCX-50', 50, ['N-BK7']), lens('ACH-100', 100, ['N-BAF10', 'N-SF6']), lens('PCX-200', 200, ['FUSED_SILICA'], { diameter: 50.8 })].map((l) => ({ lens: l, catalogId: 'c1' }))
    const f = { q: '', kind: 'all' as const, glass: '', diameter: 0, catalog: 'all', fmin: null, fmax: null }
    expect(filterStock(all, { ...f, kind: 'achromat' }).map((x) => x.lens.part)).toEqual(['ACH-100'])
    expect(filterStock(all, { ...f, glass: 'N-SF6' }).map((x) => x.lens.part)).toEqual(['ACH-100'])
    expect(filterStock(all, { ...f, diameter: 50.8 }).map((x) => x.lens.part)).toEqual(['PCX-200'])
    expect(filterStock(all, { ...f, fmin: 60, fmax: 150 }).map((x) => x.lens.part)).toEqual(['ACH-100'])
    expect(filterStock(all, { ...f, q: 'pcx' }).map((x) => x.lens.part)).toEqual(['PCX-50', 'PCX-200'])
    expect(filterStock(all, { ...f, catalog: GENERIC_ID })).toEqual([])
  })

  it('inserts a stock lens in one undo step, never inside an element, with the glasses it needs', async () => {
    vi.spyOn(api, 'stockSurfaces').mockResolvedValue({
      surfaces: [
        { id: 'stk0', label: 'A front', radius: 60, thickness: 4, material: 'MY-GLASS', semi_diameter: 11.43, semi_diameter_mode: 'fixed', mech_semi_diameter: 12.7 },
        { id: 'stk1', label: 'A back', radius: null, thickness: 7, material: 'AIR', semi_diameter: 11.43, semi_diameter_mode: 'fixed', mech_semi_diameter: 12.7 },
      ],
    })
    const before = JSON.stringify(st().project)
    const n0 = st().project.system.surfaces.length
    // surface 2 is inside the blank project's lens (surface 1 is followed by glass): the lens goes after it
    const pos = await insertStockLens(lens('A', 100, ['MY-GLASS']), false, 2, 7, [{ name: 'MY-GLASS', formula: 'sellmeier', coefficients: [1, 0.01, 0, 0, 0, 0] } as MaterialRecord])
    const s = st().project.system.surfaces
    expect(s).toHaveLength(n0 + 2)
    expect(pos).toBe(3)
    expect(s[pos].label).toBe('A front')
    expect(s[pos].id).not.toBe('stk0')
    expect(s[pos + 1].semi_diameter_mode).toBe('fixed')
    expect(st().project.custom_materials.map((m) => m.name)).toEqual(['MY-GLASS'])
    st().undo()
    expect(JSON.stringify(st().project)).toBe(before)
  })

  it('builds the engine specification from the view settings', () => {
    const p = blankProject('Spec')
    const sett = { focal_length: 80, f_number: 4, half_field_deg: 45, max_length: null, conjugate: 'infinite', object_distance: 100, magnification: -1, object_na: 0.05, object_height: 1, lens_counts: [], stock_glasses: ['N-BK7'], stock_catalogs: ['c1'], min_gap: 0.5, tolerance_pct: 2, stock_candidates: 30, mtf_frequency: 30, tolerances: false, seed: 3 } as unknown as DsSettings
    const spec = stockBuildSpec(sett, p)
    expect(spec.generic).toBe(false)
    expect(spec.tolerance).toBeCloseTo(0.02)
    expect(spec.half_field_deg).toBe(30) // the engine's limit for stock builds
    expect(spec.lens_counts).toEqual([1, 2])
    expect(spec.wavelengths).toEqual(p.system.wavelengths.map((w) => w.value))
  })
})
