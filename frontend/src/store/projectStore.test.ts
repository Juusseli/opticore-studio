import { beforeEach, describe, expect, it } from 'vitest'
import { blankProject, defaultDetector, defaultSource } from '../lib/project'
import { isDirty, useProjectStore } from './projectStore'

const st = () => useProjectStore.getState()

describe('project store: modelling operations and undo/redo', () => {
  beforeEach(() => {
    st().setProject(blankProject('Test'))
  })

  it('records edits and undoes/redoes them exactly', () => {
    const before = JSON.stringify(st().project.system)
    st().updateSurface(1, { radius: 42 }, 'R1')
    expect(st().project.system.surfaces[1].radius).toBe(42)
    expect(isDirty(st())).toBe(true)
    st().undo()
    expect(JSON.stringify(st().project.system)).toBe(before)
    expect(isDirty(st())).toBe(false)
    st().redo()
    expect(st().project.system.surfaces[1].radius).toBe(42)
  })

  it('deleting a surface drops its tolerances and compensators; undo restores them', () => {
    const sf = st().project.system.surfaces
    const a = sf[1].id
    const b = sf[2].id
    st().updateProject((p) => {
      p.tolerancing.tolerances.push({ id: 't1', type: 'radius', surface_id: a, surface_id_end: null, min: -0.1, max: 0.1, enabled: true })
      p.tolerancing.tolerances.push({ id: 't2', type: 'element_tilt_x', surface_id: a, surface_id_end: b, min: -0.1, max: 0.1, enabled: true })
      p.tolerancing.tolerances.push({ id: 't3', type: 'thickness', surface_id: b, surface_id_end: null, min: -0.1, max: 0.1, enabled: true })
      p.tolerancing.compensators.push({ surface_id: b, parameter: 'thickness', range: 2, enabled: true })
    }, 'tols')
    st().deleteSurfaces([2])
    expect(st().project.tolerancing.tolerances.map((x) => x.id)).toEqual(['t1'])
    expect(st().project.tolerancing.compensators).toHaveLength(0)
    st().undo()
    expect(st().project.tolerancing.tolerances).toHaveLength(3)
    expect(st().project.tolerancing.compensators).toHaveLength(1)
  })

  it('sources and detectors anchored to a deleted surface follow the surface that takes its place', () => {
    st().insertSurface(2)
    const sf = st().project.system.surfaces
    const [a, b, img] = [sf[2].id, sf[3].id, sf[sf.length - 1].id]
    st().updateProject((p) => {
      p.sources = [defaultSource({ placement: { position: [0, 0, 1], rotation_deg: [0, 0, 0], anchor: a } }), defaultSource({ placement: { position: [0, 0, 0], rotation_deg: [0, 0, 0], anchor: null } })]
      p.detectors = [defaultDetector({ placement: { position: [0, 0, 0], rotation_deg: [0, 0, 0], anchor: b } })]
    }, 'ns')
    // a and b in a row: both go to the first surface kept after them (the image here)
    st().deleteSurfaces([2, 3])
    expect(st().project.sources!.map((x) => x.placement.anchor)).toEqual([img, null])
    expect(st().project.detectors![0].placement.anchor).toBe(img)
    expect(st().project.sources![0].placement.position).toEqual([0, 0, 1])
    st().undo()
    expect(st().project.sources![0].placement.anchor).toBe(a)
    expect(st().project.detectors![0].placement.anchor).toBe(b)
    // one surface: the next one
    st().deleteSurfaces([2])
    expect(st().project.sources![0].placement.anchor).toBe(b)
  })

  it('a solve removes the matching optimisation variable and deleting a pickup source clears the pickup', () => {
    const sf = st().project.system.surfaces
    st().toggleVariable(sf[2].id, 'thickness')
    expect(st().project.optimization.variables).toHaveLength(1)
    st().setSolve(2, 'thickness', { type: 'marginal_height', target: 0, surface_id: null, scale: 1, offset: 0, zone: 1 })
    expect(st().project.system.surfaces[2].thickness_solve?.type).toBe('marginal_height')
    expect(st().project.optimization.variables).toHaveLength(0)
    st().insertSurface(2)
    const src = st().project.system.surfaces[2].id
    st().setSolve(3, 'curvature', { type: 'pickup', target: 0, surface_id: src, scale: -1, offset: 0, zone: 1 })
    st().deleteSurfaces([2])
    expect(st().project.system.surfaces[2].curvature_solve).toBeNull()
    st().undo()
    expect(st().project.system.surfaces[3].curvature_solve?.surface_id).toBe(src)
  })

  it('multi-configuration editing, per-configuration variables and removal remapping', () => {
    const sf = st().project.system.surfaces
    const bf = sf[2].id
    st().enableConfigurations()
    st().addConfigOperand('thickness', bf)
    const mc = () => st().project.system.multi_config!
    expect(mc().operands[0].values).toEqual([sf[2].thickness, sf[2].thickness])
    st().setConfigValue(0, 1, 123)
    st().addConfiguration() // copies the active (first) configuration
    expect(mc().names).toHaveLength(3)
    expect(mc().active).toBe(2)
    expect(mc().operands[0].values).toEqual([sf[2].thickness, 123, sf[2].thickness])
    // V toggle on a configuration-controlled parameter creates a per-configuration variable
    st().setActiveConfiguration(1)
    st().toggleVariable(bf, 'thickness')
    expect(st().project.optimization.variables[0].configuration).toBe(1)
    st().setOptimization({ ...st().project.optimization, operands: [{ type: 'rms_spot', target: 0, weight: 1, field: null, wavelength: null, surface_id: null, rings: 3, reference: 'centroid', enabled: true, configuration: 2 }] })
    st().removeConfiguration(0)
    expect(mc().names).toHaveLength(2)
    expect(st().project.optimization.variables[0].configuration).toBe(0) // remapped 1 -> 0
    expect(st().project.optimization.operands[0].configuration).toBe(1) // remapped 2 -> 1
    st().removeConfiguration(0) // deletes the configuration the variable belongs to
    expect(st().project.optimization.variables).toHaveLength(0)
    // single configuration again: the active values become the design
    st().setConfigValue(0, 0, 77)
    st().disableConfigurations()
    expect(st().project.system.multi_config).toBeNull()
    expect(st().project.system.surfaces[2].thickness).toBe(77)
    expect(st().project.optimization.operands[0].configuration).toBeNull()
  })

  it('field vignetting factors per configuration: rows, active-value editing, field removal and single configuration', () => {
    st().setFields([{ x: 0, y: 0, weight: 1 }, { x: 0, y: 10, weight: 1 }, { x: 0, y: 20, weight: 1, vcy: 0.1 }])
    st().enableConfigurations() // two configurations
    st().addConfigOperand('vcy', null, 2) // seeded with the field's own value
    st().addConfigOperand('vdy', null, 1)
    st().addConfigOperand('vdy', null, 1) // a second row for the same field and factor is not added
    const mc = () => st().project.system.multi_config!
    expect(mc().operands.map((o) => [o.parameter, o.field, o.surface_id])).toEqual([['vcy', 2, null], ['vdy', 1, null]])
    expect(mc().operands[0].values).toEqual([0.1, 0.1])
    st().setConfigValue(0, 1, 0.3)
    // removing field 1 drops its rows and renumbers the later fields' rows
    st().removeField(1)
    expect(mc().operands.map((o) => [o.parameter, o.field])).toEqual([['vcy', 1]])
    // temperature and pressure rows too: single configuration keeps the active configuration's values
    st().addConfigOperand('temperature', null)
    st().addConfigOperand('pressure', null)
    const ti = mc().operands.findIndex((o) => o.parameter === 'temperature')
    const pi = mc().operands.findIndex((o) => o.parameter === 'pressure')
    st().setConfigValue(ti, 1, 45)
    st().setConfigValue(pi, 1, 0.8)
    st().setActiveConfiguration(1)
    st().disableConfigurations()
    expect(st().project.system.fields[1].vcy).toBe(0.3)
    expect(st().project.system.temperature_c).toBe(45)
    expect(st().project.system.pressure_atm).toBe(0.8)
  })

  it('CAD models are added, edited and removed with undo', () => {
    const asset = {
      id: 'cad1', name: 'housing', source_filename: 'housing.stl', format: 'stl' as const, units: 'mm', imported: '',
      mesh: { positions_b64: '', indices_b64: '', vertices: 0, triangles: 0 },
      bbox_min: [0, 0, 0] as [number, number, number], bbox_max: [1, 1, 1] as [number, number, number],
      surface_area_mm2: 6, volume_mm3: 1, closed: true, diagnostics: [],
      transform: { translate: [0, 0, 0] as [number, number, number], rotate_deg: [0, 0, 0] as [number, number, number] },
      visible: true, color: '#999999', opacity: 0.5,
    }
    st().addCadAsset(asset)
    st().updateCadAsset('cad1', { visible: false }, 'hide')
    expect(st().project.cad_assets[0].visible).toBe(false)
    st().removeCadAsset('cad1')
    expect(st().project.cad_assets).toHaveLength(0)
    st().undo()
    st().undo()
    expect(st().project.cad_assets[0].visible).toBe(true)
    // the optical system is untouched by CAD edits
    expect(st().project.system.surfaces).toHaveLength(blankProject('x').system.surfaces.length)
  })

  it('ignores no-op edits (no history entry)', () => {
    const r = st().project.system.surfaces[1].radius
    st().updateSurface(1, { radius: r }, 'noop')
    expect(st().past).toHaveLength(0)
  })

  it('a new edit clears the redo stack', () => {
    st().updateSurface(1, { radius: 42 })
    st().undo()
    expect(st().future).toHaveLength(1)
    st().updateSurface(1, { radius: 43 })
    expect(st().future).toHaveLength(0)
  })

  it('never inserts before the object or deletes object/image surfaces', () => {
    const n = st().project.system.surfaces.length
    st().insertSurface(0)
    expect(st().project.system.surfaces).toHaveLength(n + 1)
    expect(st().project.system.surfaces[0].label).toBe('Object')
    st().deleteSurfaces([0, st().project.system.surfaces.length - 1])
    expect(st().project.system.surfaces).toHaveLength(n + 1)
  })

  it('keeps at least object, one surface and image', () => {
    st().deleteSurfaces([1, 2])
    expect(st().project.system.surfaces.length).toBeGreaterThanOrEqual(3)
  })

  it('removes optimisation variables of deleted surfaces', () => {
    const id = st().project.system.surfaces[2].id
    st().toggleVariable(id, 'curvature')
    expect(st().project.optimization.variables).toHaveLength(1)
    st().deleteSurfaces([2])
    expect(st().project.optimization.variables).toHaveLength(0)
  })

  it('moves surfaces and keeps a single aperture stop', () => {
    st().insertLens(3)
    const idMoved = st().project.system.surfaces[3].id
    st().moveSurface(3, 1)
    expect(st().project.system.surfaces[1].id).toBe(idMoved)
    st().setStop(2)
    expect(st().project.system.surfaces.filter((s) => s.is_stop)).toHaveLength(1)
    expect(st().project.system.surfaces[2].is_stop).toBe(true)
  })

  it('replaceSystem keeps the previous design as a revision and is undoable', () => {
    const original = JSON.stringify(st().project.system)
    const next = JSON.parse(original)
    next.surfaces[1].radius = 77
    st().replaceSystem(next, 'Apply optimization')
    expect(st().project.system.surfaces[1].radius).toBe(77)
    expect(st().project.revisions).toHaveLength(1)
    expect(JSON.stringify(st().project.revisions[0].system)).toBe(original)
    st().undo()
    expect(JSON.stringify(st().project.system)).toBe(original)
  })

  it('restores a revision while saving the current state first', () => {
    st().addRevision('v1')
    const id = st().project.revisions[0].id
    st().updateSurface(1, { radius: 12 })
    st().restoreRevision(id)
    expect(st().project.system.surfaces[1].radius).toBe(100)
    expect(st().project.revisions).toHaveLength(2)
  })

  it('inserting a lens never splits an existing glass element', () => {
    // blank project: 0 obj, 1 front (N-BK7), 2 back (AIR), 3 image
    st().insertLens(2) // right after the glass surface 1 -> must go after surface 2
    const m = st().project.system.surfaces.map((x) => x.material)
    expect(m).toEqual(['AIR', 'N-BK7', 'AIR', 'N-BK7', 'AIR', 'AIR'])
  })

  it('removing a field remaps operand field indices and disables orphaned operands', () => {
    st().setFields([0, 1, 2, 3].map((y) => ({ x: 0, y, weight: 1 })))
    const op = (field: number) => ({ type: 'rms_spot' as const, target: 0, weight: 1, field, wavelength: null, surface_id: null, rings: 4, reference: 'centroid' as const, enabled: true })
    st().setOptimization({ ...st().project.optimization, operands: [op(0), op(1), op(3)] })
    st().removeField(1)
    const ops = st().project.optimization.operands
    expect(ops.map((o) => o.field)).toEqual([0, null, 2])
    expect(ops.map((o) => o.enabled)).toEqual([true, false, true])
    expect(st().project.system.fields.map((f) => f.y)).toEqual([0, 2, 3])
  })

  it('removing a wavelength keeps the primary pointing at the same wavelength', () => {
    st().setWavelengths([{ value: 0.45, weight: 1 }, { value: 0.55, weight: 1 }, { value: 0.65, weight: 1 }], 2)
    st().removeWavelength(0)
    expect(st().project.system.primary_wavelength).toBe(1)
    expect(st().project.system.wavelengths[1].value).toBe(0.65)
  })

  it('turning the stop surface into a coordinate break clears the stop', () => {
    st().setStop(1)
    st().updateSurface(1, { type: 'coordinate_break' })
    expect(st().project.system.surfaces[1].is_stop).toBe(false)
  })

  it('selection modes', () => {
    st().select(1)
    st().select(3, 'range')
    expect(new Set(st().selection)).toEqual(new Set([1, 2, 3]))
    st().select(2, 'toggle')
    expect(st().selection).not.toContain(2)
  })

  it('wavelength edits keep a valid primary index', () => {
    st().setWavelengths([{ value: 0.55, weight: 1 }], 2)
    expect(st().project.system.primary_wavelength).toBe(0)
  })
})
