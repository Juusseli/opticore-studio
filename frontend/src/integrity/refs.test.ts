import { beforeEach, describe, expect, it } from 'vitest'
import { importanceOf } from '../components/views/nonseqSettings'
import { blankProject, defaultDetector, defaultSource, normalizeProject } from '../lib/project'
import { useProjectStore } from '../store/projectStore'

const st = () => useProjectStore.getState()

describe('referential integrity of index references', () => {
  beforeEach(() => st().setProject(blankProject('R')))

  it('removing a field shifts the field index of a system-field light source', () => {
    st().setFields([{ x: 0, y: 0, weight: 1 }, { x: 0, y: 2, weight: 1 }, { x: 0, y: 4, weight: 1 }])
    st().updateProject((p) => void (p.sources = [defaultSource({ kind: 'system_field', field: 2 })]), 'src')
    st().removeField(0)
    const f = st().project.system.fields
    const src = st().project.sources![0]
    expect(src.field).toBeLessThan(f.length)
    expect(f[src.field]?.y).toBe(4)
  })

  it('removing an earlier field keeps a system-field source on its own field', () => {
    st().setFields([{ x: 0, y: 0, weight: 1 }, { x: 0, y: 2, weight: 1 }, { x: 0, y: 4, weight: 1 }, { x: 0, y: 6, weight: 1 }])
    st().updateProject((p) => void (p.sources = [defaultSource({ kind: 'system_field', field: 2 })]), 'src')
    st().removeField(0)
    expect(st().project.system.fields[st().project.sources![0].field].y).toBe(4)
  })

  it('restoring a revision leaves no anchors, variables or tolerances on surfaces the revision does not have', () => {
    st().addRevision('two surfaces')
    const rev = st().project.revisions[0].id
    st().insertSurface(2)
    const x = st().project.system.surfaces[2].id
    st().updateProject((p) => {
      p.sources = [defaultSource({ placement: { position: [0, 0, 0], rotation_deg: [0, 0, 0], anchor: x } })]
      p.detectors = [defaultDetector({ placement: { position: [0, 0, 0], rotation_deg: [0, 0, 0], anchor: x } })]
      p.optimization.variables.push({ surface_id: x, parameter: 'thickness', min: 0, max: 10, enabled: true })
      p.tolerancing.tolerances.push({ id: 't', type: 'thickness', surface_id: x, surface_id_end: null, min: -0.1, max: 0.1, enabled: true })
    }, 'refs to x')
    st().restoreRevision(rev)
    const p = st().project
    const ids = new Set(p.system.surfaces.map((s) => s.id))
    expect(ids.has(x)).toBe(false)
    const dangling = [
      ...p.sources!.map((s) => s.placement.anchor),
      ...p.detectors!.map((d) => d.placement.anchor),
      ...p.optimization.variables.map((v) => v.surface_id),
      ...p.tolerancing.tolerances.map((t) => t.surface_id),
    ].filter((a) => a && !ids.has(a))
    expect(dangling).toEqual([])
  })

  it('removing a field or wavelength keeps stored analysis settings on the same field and wavelength', () => {
    st().setFields([{ x: 0, y: 0, weight: 1 }, { x: 0, y: 2, weight: 1 }, { x: 0, y: 4, weight: 1 }, { x: 0, y: 6, weight: 1 }])
    st().updateProject((p) => void (p.analysis_settings.psf = { field: 2, wavelength: 1, grid: 64, pad: 2, log: false }), 'psf settings')
    st().removeField(0)
    st().removeWavelength(0)
    const s = st().project
    const psf = s.analysis_settings.psf!
    expect(s.system.fields[psf.field].y).toBe(4) // the same field, not y = 6, which moved to its index
    expect(s.system.wavelengths[psf.wavelength!].value).toBe(0.5875618) // not 0.6562725, which moved to its index
  })

  it('the non-sequential importance target follows its surface when surfaces are inserted (by id; index targets of older projects are converted)', () => {
    const target = st().project.system.surfaces[2].id
    st().updateProject((p) => void (p.analysis_settings.nonseq = { imp_target: `sid:${target}` }), 'importance to surface 2')
    st().insertSurface(1)
    const ids = st().project.system.surfaces.map((s) => s.id)
    const imp = importanceOf((st().project.analysis_settings.nonseq as { imp_target: string }).imp_target, 4, null, ids, true)
    expect(imp?.target).toEqual({ kind: 'surface', index: ids.indexOf(target) })
    expect(ids.indexOf(target)).toBe(3)
    // a project saved with an index target opens with the id of that surface
    const old = blankProject('old')
    old.analysis_settings.nonseq = { imp_target: 'surf:2' }
    expect((normalizeProject(old).analysis_settings.nonseq as { imp_target: string }).imp_target).toBe(`sid:${old.system.surfaces[2].id}`)
  })

  it('removing a configuration leaves no sweep parameter on a configuration that no longer exists', () => {
    st().enableConfigurations()
    st().addConfiguration()
    const sid = st().project.system.surfaces[2].id
    st().updateProject((p) => {
      p.analysis_settings.sweep = { parameters: [{ surface_id: sid, parameter: 'thickness', configuration: 2, start: 90, stop: 100, steps: 5 }], metrics: [{ type: 'rms_spot' }], show: 0 }
    }, 'sweep in config 3')
    st().removeConfiguration(0)
    const c = (st().project.analysis_settings.sweep as { parameters: { configuration: number | null }[] }).parameters[0].configuration
    const n = st().project.system.multi_config!.names.length
    expect(c === null || c < n).toBe(true)
  })

  it('removing a CAD model unlinks the mount parts linked to it', () => {
    st().updateProject((p) => {
      p.cad_assets.push({ id: 'cad1', name: 'Barrel', source_filename: 'b.step', format: 'step', units: 'mm', imported: '', mesh: { positions_b64: '', indices_b64: '', vertices: 0, triangles: 0 }, bbox_min: [0, 0, 0], bbox_max: [1, 1, 1], surface_area_mm2: 1, volume_mm3: 1, closed: true, diagnostics: [], transform: { translate: [0, 0, 0], rotate_deg: [0, 0, 0] }, visible: true, color: '#888', opacity: 0.5 })
      p.system.mounts = [{ id: 'm1', name: 'Barrel', cte: 23.6, temperature_c: null, parent: null, datum_z: 0, cad_asset_id: 'cad1', cad_node_id: '1.2' }]
    }, 'mount linked to CAD')
    st().removeCadAsset('cad1')
    const assets = new Set(st().project.cad_assets.map((a) => a.id))
    expect(st().project.system.mounts!.filter((m) => m.cad_asset_id && !assets.has(m.cad_asset_id))).toEqual([])
  })

  it('moving a surface keeps the last surface of an element tolerance after its first', () => {
    st().insertSurface(3)
    const sf = st().project.system.surfaces
    st().updateProject((p) => void p.tolerancing.tolerances.push({ id: 'e', type: 'element_tilt_x', surface_id: sf[1].id, surface_id_end: sf[2].id, min: -0.1, max: 0.1, enabled: true }), 'element tol')
    st().moveSurface(1, 3)
    const pos = new Map(st().project.system.surfaces.map((s, i) => [s.id, i]))
    const t = st().project.tolerancing.tolerances[0]
    expect(pos.get(t.surface_id_end!)!).toBeGreaterThanOrEqual(pos.get(t.surface_id)!)
  })

  it('an edit arriving during a drag gets its own undo step (the drag merges only its own edits)', () => {
    st().beginGesture()
    st().updateSurface(1, { radius: 90 }, 'Drag radius')
    st().updateSurface(1, { radius: 80 }, 'Drag radius')
    st().updateProject((p) => void (p.metadata.description = 'engine answer'), 'Engine answer')
    st().updateSurface(1, { radius: 70 }, 'Drag radius')
    st().endGesture()
    expect(st().project.system.surfaces[1].radius).toBe(70)
    st().undo() // the drag's edits after the answer
    expect(st().project.metadata.description).toBe('engine answer')
    st().undo() // the answer
    expect(st().project.metadata.description).not.toBe('engine answer')
    expect(st().project.system.surfaces[1].radius).toBe(80)
  })
})
