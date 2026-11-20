import { describe, expect, it } from 'vitest'
import { showViewPatch } from '../store/uiStore'
import { en, fi } from './i18n'
import { ALL_VIEWS, filterViews, VIEW_GROUPS, VIEW_IDS, viewGroup, viewShortcut } from './viewGroups'

describe('analysis view groups', () => {
  it('every ViewKind lies in exactly one group, and groups hold only known views', () => {
    for (const v of ALL_VIEWS) expect(VIEW_GROUPS.filter((g) => g.views.includes(v)).length, v).toBe(1)
    const listed = VIEW_GROUPS.flatMap((g) => g.views)
    expect(new Set(listed).size).toBe(listed.length)
    expect([...listed].sort()).toEqual([...ALL_VIEWS].sort())
    expect(VIEW_IDS).toEqual(listed)
  })

  it('follows the plan: basics first, advanced modules in their own groups', () => {
    expect(viewGroup('layout2d')).toBe('layout')
    expect(viewGroup('spot')).toBe('geometric')
    expect(viewGroup('mtf')).toBe('image')
    expect(viewGroup('systemdata')).toBe('system')
    expect(viewGroup('fdtd')).toBe('beams')
    expect(viewGroup('nonseq')).toBe('illumination')
    expect(viewGroup('sweep')).toBe('tools')
    expect(viewShortcut('layout2d')).toBe('Ctrl+1')
    expect(viewShortcut('spot')).toBe('Ctrl+3')
    expect(viewShortcut('fdtd')).toBeNull()
  })

  it('every view and group has an English and a Finnish label', () => {
    for (const v of ALL_VIEWS) {
      expect(en['view.' + v], v).toBeTruthy()
      expect(fi['view.' + v], v).toBeTruthy()
    }
    for (const g of VIEW_GROUPS) {
      expect(en['vg.' + g.group], g.group).toBeTruthy()
      expect(fi['vg.' + g.group], g.group).toBeTruthy()
    }
  })

  it('search matches view names and group names, every word', () => {
    const label = (v: string) => en['view.' + v]
    const group = (g: string) => en['vg.' + g]
    expect(filterViews('mtf', label, group)).toEqual([{ group: 'image', views: ['mtf'] }])
    expect(filterViews('wave optics', label, group).map((g) => g.group)).toEqual(['beams'])
    expect(filterViews('psf', label, group)[0].views).toEqual(['psf', 'huygens', 'vectorpsf'])
    expect(filterViews('', label, group).flatMap((g) => g.views)).toEqual(VIEW_IDS)
    expect(filterViews('nothing like this', label, group)).toEqual([])
  })
})

describe('showView', () => {
  const base = { split: true, leftView: 'layout2d' as const, rightView: 'spot' as const, focusedPane: 'right' as const }

  it('opens in the focused pane', () => {
    expect(showViewPatch(base, 'mtf')).toEqual({ rightView: 'mtf' })
    expect(showViewPatch({ ...base, focusedPane: 'left' }, 'mtf')).toEqual({ leftView: 'mtf', focusedPane: 'left' })
    expect(showViewPatch({ ...base, split: false }, 'mtf')).toEqual({ leftView: 'mtf', focusedPane: 'left' })
  })

  it('only focuses a view that is already on screen', () => {
    expect(showViewPatch(base, 'layout2d')).toEqual({ focusedPane: 'left' })
    expect(showViewPatch({ ...base, focusedPane: 'left' }, 'spot')).toEqual({ focusedPane: 'right' })
    // the hidden right pane does not count
    expect(showViewPatch({ ...base, split: false }, 'spot')).toEqual({ leftView: 'spot', focusedPane: 'left' })
  })
})
