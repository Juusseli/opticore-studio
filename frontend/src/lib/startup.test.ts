import { describe, expect, it } from 'vitest'
import { en, fi } from './i18n'
import { blankProject } from './project'
import { CATEGORY_ORDER, discardTarget, groupTemplates, startupPlan } from './startup'
import type { StoredProject } from './storage'
import type { Project, SampleInfo } from './types'

const proj = (id: string, name = id): Project => ({ ...blankProject(), id, metadata: { ...blankProject().metadata, name } })
const stored = (id: string, savedAt: string): StoredProject => ({ id, name: id, savedAt, project: proj(id) })

describe('startup plan', () => {
  const library = [stored('b', '2026-10-12T10:00:00Z'), stored('a', '2026-10-11T10:00:00Z')]

  it('a fresh profile opens the tutorial sample on the start screen', () => {
    expect(startupPlan({ showAtStartup: true, autosave: undefined, library: [] })).toEqual({ open: 'sample', showStart: true })
  })

  it('unsaved work is reopened and always offered on the start screen', () => {
    const autosave = { project: proj('a'), dirty: true, at: '2026-10-12T11:00:00Z' }
    for (const showAtStartup of [true, false]) {
      const plan = startupPlan({ showAtStartup, autosave, library })
      expect(plan.open).toBe('recovery')
      expect(plan.showStart).toBe(true)
      expect(plan.open === 'recovery' && plan.inLibrary).toBe(true)
    }
    const never = startupPlan({ showAtStartup: false, autosave: { ...autosave, project: proj('new') }, library })
    expect(never.open === 'recovery' && never.inLibrary).toBe(false)
  })

  it('with "Show at startup" unticked the last project opens directly', () => {
    // the clean autosave is the project that was open last, even if another one was saved later
    const plan = startupPlan({ showAtStartup: false, autosave: { project: proj('a'), dirty: false, at: '' }, library })
    expect(plan).toMatchObject({ open: 'last', inLibrary: true, showStart: false })
    expect(plan.open === 'last' && plan.project.id).toBe('a')
    // no autosave: the most recently saved project
    const fromLib = startupPlan({ showAtStartup: false, autosave: undefined, library })
    expect(fromLib.open === 'last' && fromLib.project.id).toBe('b')
    expect(fromLib.showStart).toBe(false)
    expect(startupPlan({ showAtStartup: true, autosave: undefined, library }).showStart).toBe(true)
  })

  it('discarding reopens the saved version, else the last saved project', () => {
    expect(discardTarget('a', library)?.id).toBe('a')
    expect(discardTarget('never-saved', library)?.id).toBe('b')
    expect(discardTarget('x', [])).toBeNull()
  })
})

describe('template groups', () => {
  const s = (id: string, category?: string): SampleInfo => ({ id, name: id, description: '', category: category as SampleInfo['category'] })

  it('groups in a fixed order, keeps the engine order and drops empty groups', () => {
    const g = groupTemplates([s('m', 'mirrors'), s('a', 'imaging'), s('f', 'fibre'), s('b', 'imaging'), s('x', 'unknown'), s('y')])
    expect(g.map((x) => x.category)).toEqual(['imaging', 'fibre', 'mirrors'])
    expect(g[0].samples.map((x) => x.id)).toEqual(['a', 'b', 'x', 'y'])
  })

  it('every group and template text exists in both languages', () => {
    for (const c of CATEGORY_ORDER) {
      expect(en[`start.cat.${c}`]).toBeTruthy()
      expect(fi[`start.cat.${c}`]).toBeTruthy()
    }
    const names = Object.keys(en).filter((k) => /^tpl\..+\.name$/.test(k))
    expect(names.length).toBeGreaterThanOrEqual(11)
    for (const k of names) {
      const purpose = k.replace(/\.name$/, '.purpose')
      expect(en[purpose], purpose).toBeTruthy()
      expect(fi[k], k).toBeTruthy()
      expect(fi[purpose], purpose).toBeTruthy()
    }
  })
})
