import { describe, expect, it } from 'vitest'
import { clearVignetting, fieldConfigRow, setConfigVignetting } from './configs'
import { blankProject } from './project'

const z = { vdx: 0, vdy: 0, vcx: 0, vcy: 0 }

describe('vignetting factors per configuration (a zoom vignettes differently at each position)', () => {
  it('writes one row per field and factor that is non-zero somewhere, clears the base factors, and removes all', () => {
    const p = blankProject('zoom')
    const s = p.system
    s.fields = [{ x: 0, y: 0, weight: 1 }, { x: 0, y: 10, weight: 1, vcy: 0.5 }, { x: 0, y: 20, weight: 1 }]
    s.multi_config = { names: ['wide', 'tele'], active: 0, operands: [{ parameter: 'vdy', surface_id: null, field: 2, values: [0.1, 0.1] }] }
    setConfigVignetting(s, [
      [z, { ...z, vdy: -0.05, vcy: 0.2 }, z],
      [z, { ...z, vcy: 0.1 }, z],
    ])
    expect(s.fields[1].vcy).toBeUndefined()
    expect(s.multi_config.operands[fieldConfigRow(s, 1, 'vdy')].values).toEqual([-0.05, 0])
    expect(s.multi_config.operands[fieldConfigRow(s, 1, 'vcy')].values).toEqual([0.2, 0.1])
    expect(fieldConfigRow(s, 1, 'vcx')).toBe(-1)
    expect(fieldConfigRow(s, 2, 'vdy')).toBe(-1) // zero in every configuration now: the old row is removed
    clearVignetting(s)
    expect(s.multi_config.operands).toEqual([])
  })
})
