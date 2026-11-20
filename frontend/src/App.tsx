import { PanelBottom, PanelLeft, PanelRight, X } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef } from 'react'
import { deleteSelection, exportProject, insertSurfaceAfterSelection, openProject, redo, retrace, saveProject, undo } from './actions'
import { ConfirmHost } from './components/common/ConfirmHost'
import { IconButton } from './components/common/ui'
import { DialogHost, Toasts } from './components/dialogs/Dialogs'
import { Inspector } from './components/panels/Inspector'
import { Sidebar } from './components/panels/Sidebar'
import { TopToolbar } from './components/panels/TopToolbar'
import { WorkspaceBar } from './components/panels/WorkspaceBar'
import { BottomPanel, CenterWorkspace, Handle, StatusBar } from './components/panels/Workspace'
import { CoatingStudio } from './components/dialogs/CoatingDesigner'
import { workspace as workspaceDef } from './lib/workspaces'
import { api } from './lib/api'
import { useT } from './lib/i18n'
import { normalizeProject } from './lib/project'
import { startupPlan } from './lib/startup'
import { VIEW_IDS } from './lib/viewGroups'
import { storage } from './lib/storage'
import { inspectorAsOverlay, maxBottomHeight, useWindowWidth } from './lib/viewport'
import { useCatalogStore } from './store/catalogStore'
import { useStockStore } from './store/stockStore'
import { isConfirmOpen } from './store/confirmStore'
import { useEngineStore } from './store/engineStore'
import { isDirty, projectKey, useProjectStore } from './store/projectStore'
import { useUiStore } from './store/uiStore'

function isTyping(e: KeyboardEvent) {
  const el = e.target as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

/** Autosave stays off until the launch has read the previous autosave and opened a project. */
let booted = false

function useBoot() {
  useEffect(() => {
    const eng = useEngineStore.getState()
    let cancelled = false
    ;(async () => {
      // read what was left before anything can overwrite it
      const [autosave, library] = await Promise.all([storage.getAutosave().catch(() => undefined), storage.listProjects().catch(() => [])])
      await eng.checkBackend()
      await eng.loadMaterials()
      await useCatalogStore.getState().load()
      void useStockStore.getState().load()
      if (cancelled) return
      const ui = useUiStore.getState()
      const plan = startupPlan({ showAtStartup: ui.showStartAtStartup, autosave, library })
      if (plan.open === 'recovery') {
        // unsaved work is reopened as it was left (still unsaved) and offered on the start screen
        const p = normalizeProject(plan.project)
        openProject(p, { saved: false, inLibrary: plan.inLibrary })
        ui.set({ recovery: { name: p.metadata.name, at: plan.at, projectId: p.id, inLibrary: plan.inLibrary } })
      } else if (plan.open === 'last') {
        openProject(plan.project, { inLibrary: plan.inLibrary })
      } else {
        try {
          openProject(await api.sample('achromat-start'), { saved: true })
        } catch {
          /* offline: keep the blank project */
        }
      }
      booted = true
      if (plan.showStart && !useUiStore.getState().dialog) useUiStore.getState().openDialog('start')
    })()
    const h = window.setInterval(() => useEngineStore.getState().checkBackend(), 8000)
    return () => {
      cancelled = true
      window.clearInterval(h)
    }
  }, [])
}

function useLiveEvaluation() {
  const system = useProjectStore((s) => s.project.system)
  const custom = useProjectStore((s) => s.project.custom_materials)
  const preview = useEngineStore((s) => s.preview)
  const backend = useEngineStore((s) => s.backend)
  useEffect(() => {
    if (backend === 'offline') return
    const h = window.setTimeout(() => useEngineStore.getState().evaluate(), preview ? 60 : 110)
    return () => window.clearTimeout(h)
  }, [system, custom, preview, backend])
}

function useAutosave() {
  const project = useProjectStore((s) => s.project)
  const last = useRef('')
  useEffect(() => {
    const h = window.setTimeout(() => {
      const st = useProjectStore.getState()
      // never overwrite the previous autosave before the launch has read it
      if (!booted) return
      const key = projectKey(st.project)
      if (key === last.current) return
      last.current = key
      storage.setAutosave(st.project, isDirty(st)).catch(() => undefined)
    }, 1200)
    return () => window.clearTimeout(h)
  }, [project])
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => {
      if (isDirty(useProjectStore.getState())) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', h)
    return () => window.removeEventListener('beforeunload', h)
  }, [])
}

function useShortcuts() {
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      // an open confirmation takes the keyboard (ConfirmHost)
      if (isConfirmOpen()) return
      const ui = useUiStore.getState()
      const ctrl = e.ctrlKey || e.metaKey
      const k = e.key.toLowerCase()
      if (ctrl && k === 'k') return e.preventDefault(), ui.openDialog(ui.dialog === 'palette' ? null : 'palette')
      if (ui.dialog) return
      if (ctrl && k === 's' && e.shiftKey) return e.preventDefault(), ui.openDialog('saveAs')
      if (ctrl && k === 's') return e.preventDefault(), void saveProject()
      if (ctrl && k === 'o') return e.preventDefault(), ui.openDialog('projects')
      if (ctrl && k === 'n') return e.preventDefault(), ui.openDialog('start')
      if (ctrl && k === 'e') return e.preventDefault(), void exportProject()
      if (ctrl && k === 'm') return e.preventDefault(), ui.openDialog('materials')
      if (ctrl && k === 'b') return e.preventDefault(), ui.set({ sidebarOpen: !ui.sidebarOpen })
      if (ctrl && k === 'j') return e.preventDefault(), ui.set({ bottomOpen: !ui.bottomOpen })
      if (ctrl && k === 'i') return e.preventDefault(), ui.set(inspectorAsOverlay(window.innerWidth) ? { inspectorOverlay: !ui.inspectorOverlay } : { inspectorOpen: !ui.inspectorOpen })
      if (ctrl && /^[1-9]$/.test(e.key)) {
        e.preventDefault()
        const v = VIEW_IDS[parseInt(e.key, 10) - 1]
        if (v) ui.set(ui.focusedPane === 'right' && ui.split ? { rightView: v } : { leftView: v, focusedPane: 'left' })
        return
      }
      if (e.key === 'F5') return e.preventDefault(), retrace()
      if (isTyping(e)) return
      if (e.key === 'Escape' && ui.inspectorOverlay) return ui.set({ inspectorOverlay: false })
      if (ctrl && k === 'z' && !e.shiftKey) return e.preventDefault(), undo()
      if ((ctrl && k === 'y') || (ctrl && k === 'z' && e.shiftKey)) return e.preventDefault(), redo()
      if (ctrl && k === 'a') return e.preventDefault(), useProjectStore.getState().selectAll()
      if (e.key === 'Insert') return e.preventDefault(), insertSurfaceAfterSelection()
      if (e.key === 'Delete') return e.preventDefault(), deleteSelection()
      if (e.key === '?') return ui.openDialog('shortcuts')
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        const st = useProjectStore.getState()
        const n = st.project.system.surfaces.length
        const cur = st.selection[0] ?? 0
        const next = Math.max(0, Math.min(n - 1, cur + (e.key === 'ArrowDown' ? 1 : -1)))
        e.preventDefault()
        st.select(next, e.shiftKey ? 'range' : 'single')
      }
    }
    // capture phase: application shortcuts work even while an input has focus
    // (inputs stop propagation for editing keys; isTyping() guards those here)
    window.addEventListener('keydown', h, true)
    return () => window.removeEventListener('keydown', h, true)
  }, [])
}

export default function App() {
  const t = useT()
  const ui = useUiStore()
  useBoot()
  useLiveEvaluation()
  useAutosave()
  useShortcuts()
  // a layout effect: it runs before any passive effect of the children, so plots and the 3D scene that read
  // the colour tokens on a theme change see the new theme (a passive effect here would run after theirs)
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = ui.theme
    document.documentElement.lang = ui.lang
  }, [ui.theme, ui.lang])
  const name = useProjectStore((s) => s.project.metadata.name)
  const dirty = useProjectStore(isDirty)
  // below 1440 px the Inspector floats over the analysis area (docs/UI_DESIGN.md, Laptop layout)
  const overlay = inspectorAsOverlay(useWindowWidth())
  const showInspector = (on: boolean) => ui.set(overlay ? { inspectorOverlay: on } : { inspectorOpen: on })
  useEffect(() => {
    document.title = `${dirty ? '● ' : ''}${name} — OptiCore Studio`
  }, [name, dirty])

  return (
    <div className="flex h-full flex-col">
      <TopToolbar />
      <WorkspaceBar />
      <div className="flex min-h-0 flex-1">
        {ui.sidebarOpen && (
          <>
            <aside className="flex min-h-0 shrink-0 flex-col bg-panel" style={{ width: ui.sidebarWidth }}>
              <div className="flex h-8 shrink-0 items-center border-b border-line bg-panel-2 px-3 text-small font-semibold tracking-wide text-muted uppercase">
                <span className="flex-1">{t('sb.project')}</span>
                <IconButton title={`${t('pn.hideSidebar')} (Ctrl+B)`} onClick={() => ui.set({ sidebarOpen: false })}>
                  <PanelLeft size={14} />
                </IconButton>
              </div>
              <div className="min-h-0 flex-1">
                <Sidebar />
              </div>
            </aside>
            <Handle dir="h" onDrag={(dx) => ui.set({ sidebarWidth: Math.min(480, Math.max(180, useUiStore.getState().sidebarWidth + dx)) })} />
          </>
        )}
        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="relative flex min-h-0 flex-1">
            {workspaceDef(ui.workspace).studio === 'coatings' ? <CoatingStudio /> : <CenterWorkspace />}
            {overlay && ui.inspectorOverlay && (
              <aside
                role="complementary"
                aria-label={t('ins.title')}
                className="fade-in absolute top-0 right-0 bottom-0 z-30 flex min-h-0 max-w-[85%] flex-col border-l border-line-strong bg-panel shadow-[var(--shadow)]"
                style={{ width: ui.inspectorWidth }}
              >
                <div className="flex h-8 shrink-0 items-center border-b border-line bg-panel-2 px-3 text-small font-semibold tracking-wide text-muted uppercase">
                  <span className="flex-1">{t('ins.title')}</span>
                  <IconButton title={`${t('c.close')} (Esc)`} onClick={() => showInspector(false)}>
                    <X size={14} />
                  </IconButton>
                </div>
                <div className="min-h-0 flex-1">
                  <Inspector />
                </div>
              </aside>
            )}
          </div>
          {ui.bottomOpen && (
            <>
              <Handle dir="v" onDrag={(dy) => ui.set({ bottomHeight: Math.min(maxBottomHeight(window.innerHeight), Math.max(140, useUiStore.getState().bottomHeight - dy)) })} />
              <div className="flex shrink-0 flex-col" style={{ height: ui.bottomHeight }}>
                <BottomPanel />
              </div>
            </>
          )}
        </main>
        {ui.inspectorOpen && !overlay && (
          <>
            <Handle dir="h" onDrag={(dx) => ui.set({ inspectorWidth: Math.min(520, Math.max(240, useUiStore.getState().inspectorWidth - dx)) })} />
            <aside className="flex min-h-0 shrink-0 flex-col bg-panel" style={{ width: ui.inspectorWidth }}>
              <div className="flex h-8 shrink-0 items-center border-b border-line bg-panel-2 px-3 text-small font-semibold tracking-wide text-muted uppercase">
                <span className="flex-1">{t('ins.title')}</span>
                <IconButton title={`${t('pn.hideInspector')} (Ctrl+I)`} onClick={() => ui.set({ inspectorOpen: false })}>
                  <PanelRight size={14} />
                </IconButton>
              </div>
              <div className="min-h-0 flex-1">
                <Inspector />
              </div>
            </aside>
          </>
        )}
      </div>
      <div className="relative">
        <div className="absolute -top-7 left-2 z-10 flex gap-1">
          {!ui.sidebarOpen && (
            <IconButton title={`${t('pn.showSidebar')} (Ctrl+B)`} onClick={() => ui.set({ sidebarOpen: true })}>
              <PanelLeft size={14} />
            </IconButton>
          )}
          {!ui.bottomOpen && (
            <IconButton title={`${t('pn.showBottom')} (Ctrl+J)`} onClick={() => ui.set({ bottomOpen: true })}>
              <PanelBottom size={14} />
            </IconButton>
          )}
          {/* below 1440 px the Inspector's toggle is in the workspace bar */}
          {!overlay && !ui.inspectorOpen && (
            <IconButton title={`${t('pn.showInspector')} (Ctrl+I)`} onClick={() => showInspector(true)}>
              <PanelRight size={14} />
            </IconButton>
          )}
        </div>
      </div>
      <StatusBar />
      <DialogHost />
      <ConfirmHost />
      <Toasts />
    </div>
  )
}
