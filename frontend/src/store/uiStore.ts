import { create } from 'zustand'
import { loadPref, savePref } from '../lib/storage'
import type { ViewKind } from '../lib/viewGroups'
import { defaultBottomHeight } from '../lib/viewport'
import { type BottomTab, defaultLayout, isWorkspaceId, pickLayout, switchLayouts, workspace, workspaceForTab, type WorkspaceId, type WorkspaceLayout } from '../lib/workspaces'

export type { BottomTab, ViewKind, WorkspaceId }
export type Theme = 'dark' | 'light'
export type Lang = 'en' | 'fi'
export type Dialog = null | 'start' | 'firstLens' | 'optWizard' | 'preferences' | 'materials' | 'projects' | 'palette' | 'shortcuts' | 'about' | 'projectInfo' | 'saveAs' | 'importReport' | 'stlImport' | 'cadExport' | 'cadOptics' | 'coatings' | 'coatingDesigner' | 'elementDrawing' | 'stockLenses'

export interface Toast {
  id: number
  kind: 'info' | 'success' | 'warning' | 'error'
  text: string
}

interface UiState {
  theme: Theme
  lang: Lang
  sidebarWidth: number
  inspectorWidth: number
  bottomHeight: number
  sidebarOpen: boolean
  inspectorOpen: boolean
  /** below 1440 px the Inspector floats over the analysis area; open or closed (not stored) */
  inspectorOverlay: boolean
  bottomOpen: boolean
  split: boolean
  splitRatio: number
  leftView: ViewKind
  rightView: ViewKind
  bottomTab: BottomTab
  dialog: Dialog
  dialogArg: unknown
  /** what the coating studio opens next ({ coating } or { surfaces }); consumed by the studio */
  coatingArg: unknown
  liveAnalysis: boolean
  showRays: boolean
  toasts: Toast[]
  focusedPane: 'left' | 'right'
  /** open the start screen at launch (per browser; on for a first run) */
  showStartAtStartup: boolean
  /** unsaved work found at launch and opened as the current project, offered on the start screen */
  recovery: { name: string; at: string; projectId: string; inLibrary: boolean } | null
  /** the active workspace and the remembered layouts of the others */
  workspace: WorkspaceId
  layouts: Partial<Record<WorkspaceId, WorkspaceLayout>>
  /** a one-line "what next" hint in the workspace bar (after the guided First lens) */
  nextHint: 'optimise' | null

  /** a bottom tab that the active workspace does not offer switches to the workspace that does */
  set: (patch: Partial<UiState>) => void
  setWorkspace: (w: WorkspaceId) => void
  /** back to the active workspace's default panes, views and tabs */
  resetLayout: () => void
  setTheme: (t: Theme) => void
  setLang: (l: Lang) => void
  openDialog: (d: Dialog, arg?: unknown) => void
  closeDialog: () => void
  showView: (v: ViewKind) => void
  toast: (kind: Toast['kind'], text: string) => void
  dismissToast: (id: number) => void
}

/** Where a view opens: a view already on screen just gets the focus; otherwise it replaces the view in
 * the focused pane (the only pane when the workspace is not split). */
export function showViewPatch(s: Pick<UiState, 'split' | 'leftView' | 'rightView' | 'focusedPane'>, v: ViewKind): Partial<UiState> {
  if (s.leftView === v) return { focusedPane: 'left' }
  if (s.split && s.rightView === v) return { focusedPane: 'right' }
  if (s.split && s.focusedPane === 'right') return { rightView: v }
  return { leftView: v, focusedPane: 'left' }
}

let toastId = 1
const persisted = ['theme', 'lang', 'sidebarWidth', 'inspectorWidth', 'bottomHeight', 'sidebarOpen', 'inspectorOpen', 'bottomOpen', 'split', 'splitRatio', 'leftView', 'rightView', 'bottomTab', 'liveAnalysis', 'showRays', 'showStartAtStartup', 'workspace', 'layouts'] as const

const saved = loadPref<Partial<UiState>>('ui', {})
if (saved.workspace !== undefined && !isWorkspaceId(saved.workspace)) delete saved.workspace
// layouts stored before workspaces existed continue in the workspace that has their bottom tab
if (saved.workspace === undefined && saved.bottomTab) saved.workspace = workspaceForTab(saved.bottomTab, 'design')
if (saved.bottomTab && !workspace(saved.workspace ?? 'design').tabs.includes(saved.bottomTab)) saved.bottomTab = workspace(saved.workspace ?? 'design').layout.bottomTab

export const useUiStore = create<UiState>((set, get) => ({
  theme: 'dark',
  lang: 'en',
  sidebarWidth: 260,
  inspectorWidth: 310,
  bottomHeight: defaultBottomHeight(typeof window === 'undefined' ? 1080 : window.innerHeight),
  sidebarOpen: true,
  inspectorOpen: true,
  inspectorOverlay: false,
  bottomOpen: true,
  split: true,
  splitRatio: 0.55,
  leftView: 'layout2d',
  rightView: 'spot',
  bottomTab: 'lde',
  dialog: null,
  dialogArg: null,
  coatingArg: null,
  liveAnalysis: true,
  showRays: true,
  toasts: [],
  // analyses opened from menus land in the focused pane; the right pane holds them by default
  focusedPane: 'right',
  showStartAtStartup: true,
  recovery: null,
  workspace: 'design',
  layouts: {},
  nextHint: null,
  ...saved,

  set: (patch) => {
    const s = get()
    if (patch.bottomTab && patch.workspace === undefined) {
      const w = workspaceForTab(patch.bottomTab, s.workspace)
      if (w !== s.workspace) {
        const { layouts, next } = switchLayouts(s.layouts, s.workspace, pickLayout(s), w)
        return set({ ...next, layouts, workspace: w, ...(w === 'optimize' ? { nextHint: null } : {}), ...patch })
      }
    }
    set(patch)
  },
  setWorkspace: (w) => {
    const s = get()
    if (w === s.workspace) return
    const { layouts, next } = switchLayouts(s.layouts, s.workspace, pickLayout(s), w)
    // the "next: optimise" hint has done its job once the user is in Optimize
    set({ ...next, layouts, workspace: w, focusedPane: next.split ? 'right' : 'left', ...(w === 'optimize' ? { nextHint: null } : {}) })
  },
  resetLayout: () => {
    const s = get()
    const layouts = { ...s.layouts }
    delete layouts[s.workspace]
    const def = defaultLayout(s.workspace)
    set({ ...def, layouts, focusedPane: def.split ? 'right' : 'left' })
  },
  setTheme: (theme) => set({ theme }),
  setLang: (lang) => set({ lang }),
  openDialog: (dialog, arg) => {
    // the coating designer is a workspace (the coating studio), not a dialog
    if (dialog === 'coatingDesigner') {
      set({ dialog: null, dialogArg: null, coatingArg: arg ?? null })
      get().setWorkspace('coatings')
      return
    }
    set({ dialog, dialogArg: arg ?? null })
  },
  closeDialog: () => set({ dialog: null, dialogArg: null }),
  showView: (v) => set(showViewPatch(get(), v)),
  toast: (kind, text) => {
    const id = toastId++
    set({ toasts: [...get().toasts, { id, kind, text }] })
    setTimeout(() => get().dismissToast(id), kind === 'error' ? 8000 : 4000)
  },
  dismissToast: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}))

useUiStore.subscribe((s) => {
  const out: Record<string, unknown> = {}
  for (const k of persisted) out[k] = s[k]
  savePref('ui', out)
})
