import {
  BarChart3,
  Box,
  ChevronDown,
  Command,
  Crosshair,
  Download,
  FileCog,
  FilePlus2,
  FileText,
  Flashlight,
  FlaskConical,
  FolderOpen,
  HelpCircle,
  Info,
  Keyboard,
  Languages,
  Moon,
  PanelsTopLeft,
  Redo2,
  Save,
  SaveAll,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Undo2,
  Upload,
  Waypoints,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import { exportProject, generateReport, importProjectFile, quickFocus, retrace, saveProject } from '../../actions'
import { useT } from '../../lib/i18n'
import { useProjectStore } from '../../store/projectStore'
import { useEngineStore } from '../../store/engineStore'
import { useUiStore } from '../../store/uiStore'
import { ContextMenu, IconButton, Tooltip } from '../common/ui'
import { cx } from '../common/uiUtils'
import { ViewMenu } from '../common/ViewMenu'
import { workspace } from '../../lib/workspaces'

function Sep() {
  return <div className="mx-1 h-5 w-px shrink-0 bg-line" />
}

/** Toolbar command. `label`: the visible text (short); `title`: the full name for the tooltip and screen readers.
 * Primary commands show their label from 1280 px, the others from 1700 px. */
function ToolButton({
  icon,
  label,
  title,
  onClick,
  active,
  disabled,
  shortcut,
  primary,
  menu,
  labelFrom,
}: {
  icon: React.ReactNode
  label: string
  title?: string
  onClick: (e: React.MouseEvent) => void
  active?: boolean
  disabled?: boolean
  shortcut?: string
  primary?: boolean
  /** opens a menu: chevron and aria-haspopup */
  menu?: boolean
  /** overrides when the label shows (a Tailwind min-width class) */
  labelFrom?: string
}) {
  const name = title ?? label
  return (
    <Tooltip text={shortcut ? `${name}  (${shortcut})` : name}>
      <button
        disabled={disabled}
        onClick={onClick}
        aria-label={name}
        aria-haspopup={menu ? 'menu' : undefined}
        className={cx(
          'flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2 text-body whitespace-nowrap text-muted transition-colors hover:bg-hover hover:text-fg disabled:pointer-events-none disabled:opacity-35',
          primary && 'text-fg',
          active && 'bg-accent-soft text-accent hover:text-accent',
        )}
      >
        {icon}
        <span className={cx('hidden', labelFrom ?? (primary ? 'min-[1280px]:inline' : 'min-[1700px]:inline'))}>{label}</span>
        {menu && <ChevronDown size={12} className="-ml-0.5 text-faint" />}
      </button>
    </Tooltip>
  )
}

const menuAt = (e: React.MouseEvent, align: 'left' | 'right' = 'left') => {
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  return { x: align === 'left' ? r.left : r.right - 240, y: r.bottom + 4 }
}

export function TopToolbar() {
  const t = useT()
  const ui = useUiStore()
  const canUndo = useProjectStore((s) => s.past.length > 0)
  const canRedo = useProjectStore((s) => s.future.length > 0)
  const undoLabel = useProjectStore((s) => s.past[s.past.length - 1]?.label)
  const redoLabel = useProjectStore((s) => s.future[0]?.label)
  const backend = useEngineStore((s) => s.backend)
  const evaluating = useEngineStore((s) => s.evaluating)
  const [menu, setMenu] = useState<{ x: number; y: number; kind: 'file' | 'help' } | null>(null)
  const [analyze, setAnalyze] = useState<DOMRect | null>(null)
  const offline = backend !== 'online'

  return (
    <div className="flex h-11 shrink-0 items-center gap-0.5 border-b border-line bg-panel px-2" role="toolbar" aria-label="OptiCore Studio">
      <div className="mr-1.5 flex shrink-0 items-center gap-2 pr-1">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-sky-400 to-indigo-500 shadow">
          <Waypoints size={16} className="text-white" />
        </div>
        <div className="hidden leading-tight min-[1100px]:block">
          <div className="text-title font-semibold tracking-tight">OptiCore Studio</div>
          <div className="text-caption text-faint">{t('app.tagline')}</div>
        </div>
      </div>
      <Sep />
      <ToolButton primary icon={<FilePlus2 size={16} />} label={t('tb.newShort')} title={t('tb.new')} onClick={() => ui.openDialog('start')} shortcut="Ctrl+N" />
      <ToolButton primary icon={<FolderOpen size={16} />} label={t('tb.openShort')} title={t('tb.open')} onClick={() => ui.openDialog('projects')} shortcut="Ctrl+O" />
      <ToolButton primary icon={<Save size={16} />} label={t('tb.save')} onClick={() => saveProject()} shortcut="Ctrl+S" />
      <ToolButton icon={<FileCog size={16} />} label={t('tb.file')} title={t('tb.fileMenu')} labelFrom="min-[1360px]:inline" menu onClick={(e) => setMenu({ ...menuAt(e), kind: 'file' })} />
      <Sep />
      <IconButton title={`${t('tb.undo')}${undoLabel ? ': ' + undoLabel : ''} (Ctrl+Z)`} disabled={!canUndo} onClick={() => useProjectStore.getState().undo()}>
        <Undo2 size={16} />
      </IconButton>
      <IconButton title={`${t('tb.redo')}${redoLabel ? ': ' + redoLabel : ''} (Ctrl+Y)`} disabled={!canRedo} onClick={() => useProjectStore.getState().redo()}>
        <Redo2 size={16} />
      </IconButton>
      <Sep />
      <ToolButton icon={<Zap size={16} className={evaluating ? 'text-accent' : ''} />} label={t('tb.traceShort')} title={t('tb.trace')} onClick={() => retrace()} shortcut="F5" disabled={backend === 'offline'} />
      <ToolButton primary menu icon={<BarChart3 size={16} />} label={t('tb.analyze')} title={t('tb.analyzeHint')} onClick={(e) => setAnalyze(analyze ? null : (e.currentTarget as HTMLElement).getBoundingClientRect())} />
      <ToolButton primary icon={<Crosshair size={16} />} label={t('tb.focus')} title={t('tb.focusHint')} onClick={() => quickFocus()} disabled={offline} />
      <ToolButton primary icon={<Sparkles size={16} />} label={t('tb.optimize')} title={t('tb.optimizeHint')} onClick={() => ui.set({ bottomTab: 'optimization', bottomOpen: true })} />
      <ToolButton icon={<FlaskConical size={16} />} label={t('tb.materials')} onClick={() => ui.openDialog('materials')} shortcut="Ctrl+M" />
      <ToolButton icon={<SlidersHorizontal size={16} />} label={t('tb.settingsShort')} title={t('tb.settings')} onClick={() => ui.set({ bottomTab: 'system', bottomOpen: true })} />
      <div className="min-w-2 flex-1" />
      <Tooltip text={`${t('tb.palette')} (Ctrl+K)`}>
        <button
          aria-label={t('tb.palette')}
          className="flex h-7 shrink-0 items-center gap-2 rounded-md border border-line bg-panel-2 px-2 text-small text-muted hover:border-line-strong hover:text-fg"
          onClick={() => ui.openDialog('palette')}
        >
          <Command size={14} />
          <span className="hidden min-[1600px]:inline">{t('tb.palette')}</span>
          <span className="kbd hidden min-[1440px]:inline">Ctrl K</span>
        </button>
      </Tooltip>
      <Sep />
      <IconButton title={t('tb.rays')} active={ui.showRays} aria-pressed={ui.showRays} onClick={() => ui.set({ showRays: !ui.showRays })}>
        <Flashlight size={16} />
      </IconButton>
      <IconButton title={t('tb.theme')} onClick={() => ui.setTheme(ui.theme === 'dark' ? 'light' : 'dark')}>
        {ui.theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
      </IconButton>
      <Tooltip text={t('tb.language')}>
        <button aria-label={t('tb.language')} className="flex h-7 shrink-0 items-center gap-1 rounded-md px-1.5 text-small font-semibold text-muted hover:bg-hover hover:text-fg" onClick={() => ui.setLang(ui.lang === 'en' ? 'fi' : 'en')}>
          <Languages size={14} />
          {ui.lang.toUpperCase()}
        </button>
      </Tooltip>
      <ToolButton icon={<HelpCircle size={16} />} label={t('tb.help')} menu onClick={(e) => setMenu({ ...menuAt(e, 'right'), kind: 'help' })} />

      {analyze && <ViewMenu anchor={analyze} groups={workspace(ui.workspace).groups} current={ui.split && ui.focusedPane === 'right' ? ui.rightView : ui.leftView} onPick={(v) => ui.showView(v)} onClose={() => setAnalyze(null)} />}
      {menu?.kind === 'file' && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          onClose={() => setMenu(null)}
          items={[
            { label: t('tb.saveAs'), icon: <SaveAll size={14} />, onClick: () => ui.openDialog('saveAs'), shortcut: 'Ctrl+Shift+S' },
            { label: t('tb.import'), icon: <Upload size={14} />, onClick: () => void importProjectFile() },
            { label: t('tb.export'), icon: <Download size={14} />, onClick: () => void exportProject(), shortcut: 'Ctrl+E' },
            'sep',
            { label: t('tb.report'), icon: <FileText size={14} />, onClick: () => void generateReport(), disabled: offline },
            { label: t('tb.cadExport'), icon: <Box size={14} />, onClick: () => ui.openDialog('cadExport'), disabled: offline },
            'sep',
            { label: t('tb.project'), icon: <Info size={14} />, onClick: () => ui.openDialog('projectInfo') },
          ]}
        />
      )}
      {menu?.kind === 'help' && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          onClose={() => setMenu(null)}
          items={[
            { label: t('start.open'), icon: <PanelsTopLeft size={14} />, onClick: () => ui.openDialog('start'), shortcut: 'Ctrl+N' },
            { label: t('tb.shortcuts'), icon: <Keyboard size={14} />, onClick: () => ui.openDialog('shortcuts'), shortcut: '?' },
            { label: t('tb.preferences'), icon: <Settings2 size={14} />, onClick: () => ui.openDialog('preferences') },
            'sep',
            { label: t('tb.about'), icon: <Info size={14} />, onClick: () => ui.openDialog('about') },
          ]}
        />
      )}
    </div>
  )
}
