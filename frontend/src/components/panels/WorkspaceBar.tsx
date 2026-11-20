import { Box, Crosshair, FileText, FlaskConical, Gauge, Layers, Lightbulb, ListPlus, PanelRight, PenTool, Plus, RotateCcw, Sparkles, Waves, Zap, BarChart3, Wand2, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { generateReport, importProjectFile, insertSurfaceAfterSelection, quickFocus, retrace } from '../../actions'
import { useT } from '../../lib/i18n'
import { inspectorAsOverlay, useWindowWidth } from '../../lib/viewport'
import { type ContextCommand, workspace, WORKSPACES, type WorkspaceId } from '../../lib/workspaces'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { Button, IconButton, Tooltip } from '../common/ui'
import { cx } from '../common/uiUtils'

const WS_ICON: Record<WorkspaceId, ReactNode> = {
  design: <PenTool size={14} />,
  analyze: <BarChart3 size={14} />,
  optimize: <Sparkles size={14} />,
  tolerance: <Gauge size={14} />,
  illumination: <Lightbulb size={14} />,
  wave: <Waves size={14} />,
  coatings: <Layers size={14} />,
}

/** Context commands of the workspaces: existing actions, nothing workspace-specific is computed here. */
function useCommands(): Record<ContextCommand, { icon: ReactNode; label: string; hint?: string; run: () => void; engine?: boolean }> {
  const t = useT()
  const ui = useUiStore.getState
  return {
    optWizard: { icon: <Wand2 size={14} />, label: t('ow.short'), run: () => ui().openDialog('optWizard') },
    insertSurface: { icon: <ListPlus size={14} />, label: t('lde.insertAfter'), hint: 'Insert', run: insertSurfaceAfterSelection },
    insertLens: { icon: <Plus size={14} />, label: t('lde.insertLens'), run: () => useProjectStore.getState().insertLens((useProjectStore.getState().selection[0] ?? 0) + 1) },
    materials: { icon: <FlaskConical size={14} />, label: t('tb.materials'), hint: 'Ctrl+M', run: () => ui().openDialog('materials') },
    coatings: { icon: <Layers size={14} />, label: t('coat.title'), run: () => ui().openDialog('coatings') },
    retrace: { icon: <Zap size={14} />, label: t('tb.traceShort'), hint: 'F5', run: retrace, engine: true },
    report: { icon: <FileText size={14} />, label: t('ws.report'), run: () => void generateReport(), engine: true },
    quickFocus: { icon: <Crosshair size={14} />, label: t('tb.focus'), run: () => void quickFocus(), engine: true },
    importCad: { icon: <Box size={14} />, label: t('ws.importCad'), run: () => void importProjectFile(null, '.step,.stp,.iges,.igs,.stl'), engine: true },
    coatingDesigner: { icon: <Wand2 size={14} />, label: t('cd.title'), run: () => ui().openDialog('coatingDesigner') },
  }
}

/** Workspace tabs under the toolbar, with the workspace's context commands and Reset layout. */
export function WorkspaceBar() {
  const t = useT()
  const active = useUiStore((s) => s.workspace)
  const nextHint = useUiStore((s) => s.nextHint)
  const setWorkspace = useUiStore((s) => s.setWorkspace)
  const resetLayout = useUiStore((s) => s.resetLayout)
  const online = useEngineStore((s) => s.backend === 'online')
  const commands = useCommands()
  // below 1440 px the Inspector is an overlay; its toggle sits here, where it is easy to find
  const overlay = inspectorAsOverlay(useWindowWidth())
  const inspectorOverlay = useUiStore((s) => s.inspectorOverlay)
  return (
    <div className="flex h-8 shrink-0 items-stretch gap-2 border-b border-line bg-panel-2 px-2">
      <div role="tablist" aria-label={t('ws.title')} className="flex items-stretch">
        {WORKSPACES.map((w) => (
          <Tooltip key={w.id} text={t(`ws.${w.id}Hint`)}>
            <button
              role="tab"
              aria-selected={active === w.id}
              onClick={() => setWorkspace(w.id)}
              className={cx('relative flex h-full items-center gap-1.5 px-2.5 text-body whitespace-nowrap transition-colors', active === w.id ? 'font-medium text-fg' : 'text-muted hover:bg-hover hover:text-fg')}
            >
              {active === w.id && <span className="absolute inset-x-1.5 bottom-0 h-0.5 rounded-full bg-accent" />}
              <span className={active === w.id ? 'text-accent' : ''}>{WS_ICON[w.id]}</span>
              {t(`ws.${w.id}`)}
            </button>
          </Tooltip>
        ))}
      </div>
      <div className="min-w-2 flex-1" />
      {nextHint === 'optimise' && (
        <div className="flex min-w-0 items-center gap-1.5 self-center rounded-md border border-accent/40 bg-accent-soft px-2 py-0.5 text-small" role="status">
          <span className="truncate text-fg">{t('fl.nextOptimise')}</span>
          <Button variant="link" className="shrink-0 font-medium" onClick={() => setWorkspace('optimize')}>
            {t('tb.optimize')} ›
          </Button>
          <IconButton size="sm" title={t('c.close')} onClick={() => useUiStore.getState().set({ nextHint: null })}>
            <X size={12} />
          </IconButton>
        </div>
      )}
      <div className="flex items-center gap-0.5" role="group" aria-label={t('ws.commands', { name: t(`ws.${active}`) })}>
        {workspace(active).commands.map((id) => {
          const c = commands[id]
          const name = c.hint ? `${c.label} (${c.hint})` : c.label
          return (
            <Tooltip key={id} text={name}>
              <button
                aria-label={c.label}
                disabled={c.engine && !online}
                onClick={c.run}
                className="flex h-6 items-center gap-1.5 rounded-md px-1.5 text-small whitespace-nowrap text-muted hover:bg-hover hover:text-fg disabled:pointer-events-none disabled:opacity-35"
              >
                {c.icon}
                <span className="hidden min-[1500px]:inline">{c.label}</span>
              </button>
            </Tooltip>
          )
        })}
        <div className="mx-1 h-4 w-px bg-line" />
        <Tooltip text={t('ws.resetHint')}>
          <button aria-label={t('ws.reset')} onClick={resetLayout} className="flex h-6 items-center gap-1.5 rounded-md px-1.5 text-small whitespace-nowrap text-muted hover:bg-hover hover:text-fg">
            <RotateCcw size={14} />
            <span className="hidden min-[1280px]:inline">{t('ws.reset')}</span>
          </button>
        </Tooltip>
        {overlay && (
          <IconButton title={`${t('ins.title')} (Ctrl+I)`} active={inspectorOverlay} aria-pressed={inspectorOverlay} className="h-6 w-6" onClick={() => useUiStore.getState().set({ inspectorOverlay: !inspectorOverlay })}>
            <PanelRight size={14} />
          </IconButton>
        )}
      </div>
    </div>
  )
}
