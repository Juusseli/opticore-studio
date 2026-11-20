import { describe, expect, it } from 'vitest'
import { renameCoating } from '../../lib/references'
import { blankProject } from '../../lib/project'
import { uniqueCoatingName } from './coatingNames'

describe('coating editor helpers', () => {
  it('makes unique upper-case names', () => {
    expect(uniqueCoatingName('my ar', [])).toBe('MY AR')
    expect(uniqueCoatingName('AR', ['AR', 'AR_2'])).toBe('AR_3')
    expect(uniqueCoatingName('  ', [])).toBe('COATING')
  })
  it('renames surface references case-insensitively', () => {
    const p = blankProject('c')
    p.system.surfaces[0].coating = 'old'
    p.system.surfaces[1].coating = 'OLD '
    p.system.surfaces[2].coating = 'other'
    expect(renameCoating(p, 'OLD', 'NEW')).toBe(2)
    expect(p.system.surfaces.map((x) => x.coating)).toEqual(['NEW', 'NEW', 'other', ''])
  })
})
