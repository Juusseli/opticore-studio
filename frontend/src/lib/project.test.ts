import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { applyMaterials, applyVariableValues, blankProject, mediumBefore, normalizeProject, parseProjectFile, ProjectFileError, serializeProject, variableValue } from './project'

const fixture = (name: string) => readFileSync(resolve(process.cwd(), 'src/lib/__fixtures__', name), 'utf-8')

describe('project files', () => {
  it('round-trips through serialize/parse with a valid checksum', async () => {
    const p = blankProject('Round trip')
    p.system.surfaces[1].radius = 51.68
    const text = await serializeProject(p)
    const parsed = await parseProjectFile(text)
    expect(parsed.checksumOk).toBe(true)
    expect(parsed.notes).toEqual([])
    expect(parsed.project.system).toEqual(p.system)
    expect(parsed.project.metadata.name).toBe('Round trip')
  })

  it('accepts files written by the Python backend', async () => {
    const parsed = await parseProjectFile(fixture('achromat.opticore'))
    expect(parsed.checksumOk).toBe(true)
    expect(parsed.project.system.surfaces).toHaveLength(5)
  })

  it('detects modification through the checksum', async () => {
    const obj = JSON.parse(fixture('achromat.opticore'))
    obj.system.surfaces[1].radius = 10
    const parsed = await parseProjectFile(JSON.stringify(obj))
    expect(parsed.checksumOk).toBe(false)
    expect(parsed.notes[0]).toMatch(/Checksum mismatch/)
  })

  it('rejects foreign, future and malformed files', async () => {
    await expect(parseProjectFile('not json')).rejects.toBeInstanceOf(ProjectFileError)
    await expect(parseProjectFile('{"format":"zemax"}')).rejects.toThrow(/Not an OptiCore project/)
    await expect(parseProjectFile('{"format":"opticore-project","schema_version":99}')).rejects.toThrow(/newer than supported/)
  })

  it('normalizes partial projects with defaults', () => {
    const p = blankProject()
    const partial = { ...p, revisions: undefined, saved_optimizations: undefined } as unknown as typeof p
    const n = normalizeProject(partial)
    expect(n.revisions).toEqual([])
    expect(n.saved_optimizations).toEqual([])
    const old = { ...p, system: { ...p.system, custom_coatings: undefined } } as unknown as typeof p
    expect(normalizeProject(old).system.custom_coatings).toEqual([])
    expect(blankProject().system.custom_coatings).toEqual([])
  })

  it('applies optimiser variable values like the backend', () => {
    const p = blankProject()
    const id1 = p.system.surfaces[1].id
    const id2 = p.system.surfaces[2].id
    const out = applyVariableValues(
      p.system,
      [
        { surface_id: id1, parameter: 'curvature' },
        { surface_id: id2, parameter: 'thickness' },
      ],
      [0.02, 80],
    )
    expect(out.surfaces[1].radius).toBeCloseTo(50, 12)
    expect(out.surfaces[2].thickness).toBe(80)
    expect(variableValue(out, id1, 'curvature')).toBeCloseTo(0.02, 15)
    expect(p.system.surfaces[1].radius).toBe(100) // original untouched
    const plane = applyVariableValues(p.system, [{ surface_id: id1, parameter: 'curvature' }], [0])
    expect(plane.surfaces[1].radius).toBeNull()
  })
  it('maps biconic and diffractive variables onto their surface fields', () => {
    const p = blankProject()
    const id = p.system.surfaces[2].id
    const out = applyVariableValues(
      p.system,
      [
        { surface_id: id, parameter: 'curvature_x' },
        { surface_id: id, parameter: 'phase_2' },
        { surface_id: id, parameter: 'grating_frequency' },
      ],
      [-0.01, -12.5, 300],
    )
    const s = out.surfaces[2]
    expect(s.radius_x).toBeCloseTo(-100, 12)
    expect(s.phase_coefficients).toEqual([0, -12.5])
    expect(s.grating_frequency).toBe(300)
    expect(Object.keys(s)).not.toContain('phase_2')
    expect(Object.keys(s)).not.toContain('curvature_x')
    expect(variableValue(out, id, 'curvature_x')).toBeCloseTo(-0.01, 15)
    expect(variableValue(out, id, 'phase_2')).toBe(-12.5)
    expect(variableValue(out, id, 'phase_3')).toBe(0)
    expect(p.system.surfaces[2].phase_coefficients).toEqual([])
  })
  it('maps coating variables onto the project coating (scale relative to the original)', () => {
    const p = blankProject()
    p.system.custom_coatings = [{ name: 'AR', description: '', layers: [{ material: '', index: 1.38, extinction: 0, thickness_nm: 100 }, { material: '', index: 2.1, extinction: 0, thickness_nm: 50 }], substrate_index: null, substrate_extinction: 0 }]
    p.system.surfaces[1].coating = 'ar'
    const id = p.system.surfaces[1].id
    const scaled = applyVariableValues(p.system, [{ surface_id: id, parameter: 'coating_scale' }], [1.1])
    expect(scaled.custom_coatings![0].layers.map((l) => l.thickness_nm)).toEqual([110.00000000000001, 55.00000000000001])
    const one = applyVariableValues(p.system, [{ surface_id: id, parameter: 'coat_layer_2' }], [42])
    expect(one.custom_coatings![0].layers[1].thickness_nm).toBe(42)
    expect(p.system.custom_coatings[0].layers[1].thickness_nm).toBe(50)
    expect(variableValue(p.system, id, 'coat_layer_1')).toBe(100)
    expect(variableValue(p.system, id, 'coating_scale')).toBe(1)
  })
  it('applies per-configuration variable values to the configuration table', () => {
    const p = blankProject('mc')
    const id = p.system.surfaces[1].id
    p.system.multi_config = { names: ['a', 'b'], active: 0, operands: [{ parameter: 'radius', surface_id: id, values: [50, null] }] }
    const out = applyVariableValues(p.system, [{ surface_id: id, parameter: 'curvature', configuration: 1 }], [0.04])
    expect(out.multi_config!.operands[0].values).toEqual([50, 25])
    expect(p.system.multi_config.operands[0].values).toEqual([50, null])
    expect(variableValue(out, id, 'curvature', 1)).toBeCloseTo(0.04, 15)
    expect(variableValue(p.system, id, 'curvature', 1)).toBe(0)
  })
  it('applies glass substitution results and ignores material variables in value vectors', () => {
    const p = blankProject('g')
    const id = p.system.surfaces[1].id
    const out = applyMaterials(applyVariableValues(p.system, [{ surface_id: id, parameter: 'material' }, { surface_id: id, parameter: 'conic' }], [NaN, -1]), [{ surface_id: id, final: 'N-SF5' }])
    expect(out.surfaces[1].material).toBe('N-SF5')
    expect(out.surfaces[1].conic).toBe(-1)
    expect(p.system.surfaces[1].material).not.toBe('N-SF5')
    expect(applyMaterials(p.system, { [id]: 'F2' }).surfaces[1].material).toBe('F2')
  })
})

describe('ideal lens helpers', () => {
  it('mediumBefore follows the medium through mirrors and coordinate breaks', () => {
    const p = blankProject()
    const sys = p.system
    expect(mediumBefore(sys, 1)).toBe(sys.surfaces[0].material.toUpperCase())
    expect(mediumBefore(sys, 2)).toBe(sys.surfaces[1].material.toUpperCase())
    sys.surfaces[2].material = 'MIRROR'
    expect(mediumBefore(sys, 3)).toBe(sys.surfaces[1].material.toUpperCase())
  })

  it('ideal_power maps to the focal length (zero power = no focal length)', () => {
    const p = blankProject()
    const s1 = p.system.surfaces[1]
    s1.type = 'ideal'
    s1.focal_length = 50
    expect(variableValue(p.system, s1.id, 'ideal_power')).toBeCloseTo(0.02, 15)
    const out = applyVariableValues(p.system, [{ surface_id: s1.id, parameter: 'ideal_power' }], [0.008])
    expect(out.surfaces[1].focal_length).toBeCloseTo(125, 12)
    expect(applyVariableValues(p.system, [{ surface_id: s1.id, parameter: 'ideal_power' }], [0]).surfaces[1].focal_length).toBeNull()
  })

  it('normalizeProject fills the new surface fields of older files', () => {
    const p = blankProject()
    const raw = JSON.parse(JSON.stringify(p))
    for (const s of raw.system.surfaces) {
      delete s.focal_length
      delete s.ideal_object_distance
    }
    const n = normalizeProject(raw)
    expect(n.system.surfaces[1].focal_length).toBe(100)
    expect(n.system.surfaces[1].ideal_object_distance).toBeNull()
  })
})
