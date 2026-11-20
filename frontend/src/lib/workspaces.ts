// Workspaces (as in Fusion and Blender): each is a task with its own panes, bottom tabs, sidebar sections,
// analysis groups and a few context commands. The user's adjustments are remembered per workspace.
import type { ViewGroup, ViewKind } from './viewGroups'
import { defaultBottomHeight } from './viewport'

export type WorkspaceId = 'design' | 'analyze' | 'optimize' | 'tolerance' | 'illumination' | 'wave' | 'coatings'
export type BottomTab = 'lde' | 'system' | 'mounts' | 'merit' | 'optimization' | 'tolerancing' | 'configs' | 'cad' | 'sources' | 'messages' | 'console'
export type SidebarSection = 'assembly' | 'configs' | 'aperture' | 'fields' | 'wavelengths' | 'materials' | 'cad' | 'sources' | 'variables' | 'revisions' | 'saved' | 'optRuns'
export type ContextCommand = 'optWizard' | 'insertSurface' | 'insertLens' | 'materials' | 'coatings' | 'retrace' | 'report' | 'quickFocus' | 'importCad' | 'coatingDesigner'

/** The part of the window layout that belongs to a workspace (panel widths stay global). */
export interface WorkspaceLayout {
  split: boolean
  splitRatio: number
  leftView: ViewKind
  rightView: ViewKind
  bottomTab: BottomTab
  bottomOpen: boolean
  bottomHeight: number
  sidebarOpen: boolean
  inspectorOpen: boolean
}

export const LAYOUT_KEYS = ['split', 'splitRatio', 'leftView', 'rightView', 'bottomTab', 'bottomOpen', 'bottomHeight', 'sidebarOpen', 'inspectorOpen'] as const

export interface WorkspaceDef {
  id: WorkspaceId
  /** bottom tabs, in order (Lens Data, Validation and Console are everywhere) */
  tabs: BottomTab[]
  /** analysis groups the view menus offer first; the rest sit under "More analyses" */
  groups: ViewGroup[]
  sections: SidebarSection[]
  commands: ContextCommand[]
  layout: WorkspaceLayout
  /** a studio replaces the analysis panes with its own full-width workspace (the coating studio) */
  studio?: 'coatings'
}

const base = { splitRatio: 0.55, bottomOpen: true, bottomHeight: 300, sidebarOpen: true, inspectorOpen: true, split: true }

export const WORKSPACES: WorkspaceDef[] = [
  {
    id: 'design',
    tabs: ['lde', 'system', 'mounts', 'messages', 'console'],
    groups: ['layout', 'geometric', 'image', 'system'],
    sections: ['assembly', 'configs', 'aperture', 'fields', 'wavelengths', 'materials', 'cad', 'revisions'],
    commands: ['insertSurface', 'insertLens', 'materials', 'coatings'],
    layout: { ...base, leftView: 'layout2d', rightView: 'spot', bottomTab: 'lde' },
  },
  {
    id: 'analyze',
    tabs: ['lde', 'system', 'mounts', 'configs', 'messages', 'console'],
    groups: ['layout', 'geometric', 'image', 'system', 'tools'],
    sections: ['assembly', 'configs', 'aperture', 'fields', 'wavelengths', 'materials', 'saved', 'revisions'],
    commands: ['retrace', 'report'],
    layout: { ...base, splitRatio: 0.45, leftView: 'layout2d', rightView: 'mtf', bottomTab: 'system' },
  },
  {
    id: 'optimize',
    tabs: ['lde', 'system', 'merit', 'optimization', 'configs', 'messages', 'console'],
    groups: ['layout', 'geometric', 'image', 'system', 'tools'],
    sections: ['assembly', 'configs', 'aperture', 'fields', 'wavelengths', 'variables', 'optRuns', 'revisions'],
    commands: ['optWizard', 'quickFocus'],
    layout: { ...base, splitRatio: 0.5, leftView: 'layout2d', rightView: 'spot', bottomTab: 'optimization' },
  },
  {
    id: 'tolerance',
    tabs: ['lde', 'system', 'tolerancing', 'merit', 'messages', 'console'],
    groups: ['layout', 'geometric', 'image', 'system'],
    sections: ['assembly', 'configs', 'aperture', 'fields', 'wavelengths', 'variables', 'revisions'],
    commands: ['report'],
    layout: { ...base, splitRatio: 0.5, leftView: 'layout2d', rightView: 'spot', bottomTab: 'tolerancing' },
  },
  {
    id: 'illumination',
    tabs: ['lde', 'system', 'sources', 'cad', 'messages', 'console'],
    groups: ['layout', 'illumination', 'system', 'geometric'],
    sections: ['assembly', 'wavelengths', 'materials', 'cad', 'sources', 'saved', 'revisions'],
    commands: ['importCad', 'coatings', 'coatingDesigner'],
    layout: { ...base, splitRatio: 0.5, leftView: 'layout3d', rightView: 'nonseq', bottomTab: 'sources' },
  },
  {
    id: 'wave',
    tabs: ['lde', 'system', 'sources', 'messages', 'console'],
    groups: ['layout', 'beams', 'image', 'system'],
    sections: ['assembly', 'aperture', 'wavelengths', 'materials', 'sources', 'saved', 'revisions'],
    commands: ['coatingDesigner'],
    layout: { ...base, splitRatio: 0.42, leftView: 'layout2d', rightView: 'pop', bottomTab: 'lde' },
  },
  {
    // thin-film coating design: the coating studio fills the centre; Lens Data and the project stay a toggle away
    id: 'coatings',
    tabs: ['lde', 'messages', 'console'],
    groups: ['system', 'layout'],
    sections: ['assembly', 'wavelengths', 'materials', 'revisions'],
    commands: ['coatings', 'materials'],
    layout: { ...base, split: false, leftView: 'coatings', rightView: 'layout2d', bottomTab: 'lde', bottomOpen: false, sidebarOpen: false, inspectorOpen: false },
    studio: 'coatings',
  },
]

export function workspace(id: WorkspaceId): WorkspaceDef {
  return WORKSPACES.find((w) => w.id === id) ?? WORKSPACES[0]
}

export function isWorkspaceId(v: unknown): v is WorkspaceId {
  return typeof v === 'string' && WORKSPACES.some((w) => w.id === v)
}

/** Where a bottom tab lives: the current workspace if it has the tab, else the first workspace that does. */
export function workspaceForTab(tab: BottomTab, current: WorkspaceId): WorkspaceId {
  if (workspace(current).tabs.includes(tab)) return current
  return WORKSPACES.find((w) => w.tabs.includes(tab))?.id ?? current
}

/** A workspace's default layout for the current window: the bottom panel is lower on a short screen. */
export function defaultLayout(id: WorkspaceId, windowHeight = typeof window === 'undefined' ? 1080 : window.innerHeight): WorkspaceLayout {
  return { ...workspace(id).layout, bottomHeight: defaultBottomHeight(windowHeight) }
}

export function pickLayout(s: WorkspaceLayout): WorkspaceLayout {
  const out = {} as Record<string, unknown>
  for (const k of LAYOUT_KEYS) out[k] = s[k]
  return out as unknown as WorkspaceLayout
}

/** The layout to show when switching from `from` (whose current state is `current`) to `to`. */
export function switchLayouts(layouts: Partial<Record<WorkspaceId, WorkspaceLayout>>, from: WorkspaceId, current: WorkspaceLayout, to: WorkspaceId): { layouts: Partial<Record<WorkspaceId, WorkspaceLayout>>; next: WorkspaceLayout } {
  const saved = { ...layouts, [from]: pickLayout(current) }
  const def = defaultLayout(to)
  const next = saved[to] ? { ...def, ...saved[to] } : def
  // a remembered bottom tab that the workspace no longer offers falls back to its default
  if (!workspace(to).tabs.includes(next.bottomTab)) next.bottomTab = workspace(to).layout.bottomTab
  return { layouts: saved, next }
}
