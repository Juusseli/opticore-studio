import { beforeEach, describe, expect, it } from 'vitest'
import { useUiStore } from '../store/uiStore'
import { en, fi } from './i18n'
import { VIEW_GROUPS, viewGroup } from './viewGroups'
import { type BottomTab, workspace, workspaceForTab, WORKSPACES } from './workspaces'

const ALL_TABS: BottomTab[] = ['lde', 'system', 'merit', 'optimization', 'tolerancing', 'configs', 'cad', 'sources', 'messages', 'console']

describe('workspace definitions', () => {
  it('every bottom tab and analysis group belongs to some workspace', () => {
    for (const tab of ALL_TABS) expect(WORKSPACES.some((w) => w.tabs.includes(tab)), tab).toBe(true)
    for (const g of VIEW_GROUPS) expect(WORKSPACES.some((w) => w.groups.includes(g.group)), g.group).toBe(true)
    for (const w of WORKSPACES) for (const tab of ['lde', 'messages', 'console'] as const) expect(w.tabs, w.id).toContain(tab)
  })

  it('Design shows only the basics', () => {
    const d = workspace('design')
    for (const g of ['beams', 'illumination', 'tools'] as const) expect(d.groups).not.toContain(g)
    for (const tab of ['merit', 'optimization', 'tolerancing', 'cad', 'sources', 'configs'] as const) expect(d.tabs).not.toContain(tab)
    expect(d.commands).not.toContain('coatingDesigner')
    expect(d.layout.leftView).toBe('layout2d')
    expect(d.layout.rightView).toBe('spot')
  })

  it("each default layout uses the workspace's own tabs and views", () => {
    for (const w of WORKSPACES) {
      expect(w.tabs, w.id).toContain(w.layout.bottomTab)
      expect(w.groups, w.id).toContain(viewGroup(w.layout.leftView))
      expect(w.groups, w.id).toContain(viewGroup(w.layout.rightView))
      for (const k of ['', 'Hint']) {
        expect(en[`ws.${w.id}${k}`]).toBeTruthy()
        expect(fi[`ws.${w.id}${k}`]).toBeTruthy()
      }
    }
    expect(workspaceForTab('merit', 'design')).toBe('optimize')
    expect(workspaceForTab('merit', 'tolerance')).toBe('tolerance')
    expect(workspaceForTab('lde', 'wave')).toBe('wave')
  })
})

describe('switching workspaces', () => {
  beforeEach(() => {
    useUiStore.setState({ workspace: 'design', layouts: {}, ...workspace('design').layout })
  })

  it('keeps the adjustments made in each workspace', () => {
    const ui = useUiStore.getState()
    ui.set({ rightView: 'mtf', splitRatio: 0.3, bottomOpen: false })
    ui.setWorkspace('optimize')
    let s = useUiStore.getState()
    expect(s.workspace).toBe('optimize')
    expect(s.bottomTab).toBe('optimization')
    expect(s.rightView).toBe('spot')
    s.set({ leftView: 'layout3d' })
    s.setWorkspace('design')
    s = useUiStore.getState()
    expect([s.rightView, s.splitRatio, s.bottomOpen]).toEqual(['mtf', 0.3, false])
    s.setWorkspace('optimize')
    expect(useUiStore.getState().leftView).toBe('layout3d')
  })

  it('a bottom tab outside the workspace opens the workspace that has it', () => {
    useUiStore.getState().set({ bottomTab: 'merit', bottomOpen: true })
    const s = useUiStore.getState()
    expect(s.workspace).toBe('optimize')
    expect(s.bottomTab).toBe('merit')
    // a tab the workspace has does not switch
    s.set({ bottomTab: 'lde' })
    expect(useUiStore.getState().workspace).toBe('optimize')
  })

  it('the "next: optimise" hint goes away in Optimize', () => {
    useUiStore.setState({ nextHint: 'optimise' })
    useUiStore.getState().setWorkspace('analyze')
    expect(useUiStore.getState().nextHint).toBe('optimise')
    useUiStore.getState().set({ bottomTab: 'optimization' })
    expect(useUiStore.getState()).toMatchObject({ workspace: 'optimize', nextHint: null })
  })

  it('Reset layout restores the defaults of the active workspace only', () => {
    const ui = useUiStore.getState()
    ui.set({ rightView: 'psf', split: false })
    ui.setWorkspace('analyze')
    useUiStore.getState().set({ rightView: 'chromatic' })
    useUiStore.getState().resetLayout()
    let s = useUiStore.getState()
    expect(s.rightView).toBe(workspace('analyze').layout.rightView)
    s.setWorkspace('design')
    s = useUiStore.getState()
    expect([s.rightView, s.split]).toEqual(['psf', false])
  })

  it('the coating designer opens as the Thin films workspace with what it should open', () => {
    useUiStore.getState().openDialog('coatingDesigner', { coating: 'HR_1064' })
    const s = useUiStore.getState()
    expect(s.workspace).toBe('coatings')
    expect(s.dialog).toBeNull()
    expect(s.coatingArg).toEqual({ coating: 'HR_1064' })
    expect(workspace('coatings').studio).toBe('coatings')
    expect([s.sidebarOpen, s.inspectorOpen, s.bottomOpen]).toEqual([false, false, false])
  })
})
