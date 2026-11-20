import { AlertTriangle, CheckCircle2, Command, Copy, FileText, FolderOpen, Keyboard, Pencil, Search, Settings2, ShieldCheck, Trash2, X } from 'lucide-react'
import { ElementDrawingDialog } from './ElementDrawingDialog'
import { useEffect, useMemo, useRef, useState } from 'react'
import { type CadExportOptions, confirmDiscard, deleteSelection, exportCad, exportProject, generateReport, importStlFile, importProjectFile, insertSurfaceAfterSelection, openProject, quickFocus, redo, retrace, saveProject, saveProjectAs, undo } from '../../actions'
import { fmt, timeAgo } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { newId, nowIso } from '../../lib/project'
import { storage, type StoredProject } from '../../lib/storage'
import type { SpotResult } from '../../lib/types'
import { confirmAction } from '../../store/confirmStore'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { CadOpticsDialog } from './CadOpticsDialog'
import { Badge, Button, Checkbox, Dialog, Empty, IconButton, NumberField, Select, Spinner, TextField } from '../common/ui'
import { cx } from '../common/uiUtils'
import { VIEW_IDS, viewGroup } from '../../lib/viewGroups'
import { WORKSPACES } from '../../lib/workspaces'
import { MaterialBrowser } from './MaterialBrowser'
import { StockLensDialog } from './StockLensDialog'
import { CoatingEditor } from './CoatingEditor'
import { StartScreen } from '../start/StartScreen'
import { FirstLensDialog } from '../start/FirstLensDialog'
import { OptWizard } from './OptWizard'

// ------------------------------------------------------------------ project manager
export function ProjectManager() {
  const t = useT()
  const close = useUiStore((s) => s.closeDialog)
  const toast = useUiStore((s) => s.toast)
  const currentId = useProjectStore((s) => s.project.id)
  const [items, setItems] = useState<StoredProject[] | null>(null)
  const [renaming, setRenaming] = useState<string | null>(null)
  const reload = () =>
    storage
      .listProjects()
      .then(setItems)
      .catch((e) => {
        setItems([])
        toast('error', t('pm.storageError', { msg: e.message }))
      })
  useEffect(() => {
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return (
    <Dialog title={t('pm.title')} onClose={close} width={820} icon={<FolderOpen size={16} className="text-accent" />} footer={<><Button onClick={() => importProjectFile().then(close)}>{t('tb.import')}</Button><Button onClick={close}>{t('c.close')}</Button></>}>
      <div className="p-3">
        <div className="mb-2 text-small font-semibold tracking-wide text-muted uppercase">{t('pm.local')}</div>
        {!items ? (
          <Spinner />
        ) : items.length === 0 ? (
          <Empty>{t('pm.empty')}</Empty>
        ) : (
          <table className="eng-table">
            <thead>
              <tr>
                <th>{t('c.name')}</th>
                <th>{t('pm.savedAt')}</th>
                <th>{t('pm.surfaces')}</th>
                <th>{t('pm.revisions')}</th>
                <th className="text-right">{t('c.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id} className={it.id === currentId ? 'selected' : ''}>
                  <td className="px-2">
                    {renaming === it.id ? (
                      <TextField
                        value={it.name}
                        onCommit={async (v) => {
                          const p = { ...it.project, metadata: { ...it.project.metadata, name: v, modified: nowIso() } }
                          await storage.putProject(p)
                          if (it.id === currentId) useProjectStore.getState().setMetadata({ name: v })
                          setRenaming(null)
                          reload()
                        }}
                      />
                    ) : (
                      <span className="flex items-center gap-1.5 font-medium">
                        <FileText size={14} className="text-accent" />
                        {it.name}
                        {it.id === currentId && <Badge tone="accent">{t('pm.isOpen')}</Badge>}
                      </span>
                    )}
                  </td>
                  <td className="px-2 text-muted">{timeAgo(it.savedAt)}</td>
                  <td className="num px-2 text-muted">{it.project.system.surfaces.length}</td>
                  <td className="num px-2 text-muted">{it.project.revisions.length}</td>
                  <td className="px-2 text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        size="sm"
                        variant="primary"
                        onClick={async () => {
                          // reopening the open project reloads its saved copy: unsaved changes need the same question
                          if (!(await confirmDiscard())) return
                          openProject(it.project, { inLibrary: true })
                          close()
                        }}
                      >
                        {t('pm.open')}
                      </Button>
                      <Button size="sm" title={t('pm.rename')} onClick={() => setRenaming(it.id)}>
                        <Pencil size={12} />
                      </Button>
                      <Button
                        size="sm"
                        title={t('pm.duplicate')}
                        onClick={async () => {
                          const p = { ...it.project, id: newId(), metadata: { ...it.project.metadata, name: t('pm.copyName', { name: it.name }), created: nowIso(), modified: nowIso() } }
                          await storage.putProject(p)
                          reload()
                        }}
                      >
                        <Copy size={12} />
                      </Button>
                      <Button
                        size="sm"
                        variant="danger"
                        title={t('pm.delete')}
                        onClick={async () => {
                          if (!(await confirmAction({ title: t('pm.deleteTitle'), message: t('pm.confirmDelete', { name: it.name }), confirmLabel: t('c.delete'), cancelLabel: t('c.cancel'), danger: true }))) return
                          await storage.deleteProject(it.id)
                          if (it.id === currentId) useProjectStore.setState({ storedInLibrary: false })
                          reload()
                        }}
                      >
                        <Trash2 size={12} />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="flex items-center gap-2 border-t border-line px-3 py-2.5 text-small text-muted">
        <span className="flex-1">{t('pm.newHint')}</span>
        <Button size="sm" onClick={() => useUiStore.getState().openDialog('start')}>
          {t('start.open')}
        </Button>
      </div>
    </Dialog>
  )
}

export function SaveAsDialog() {
  const t = useT()
  const close = useUiStore((s) => s.closeDialog)
  const meta = useProjectStore((s) => s.project.metadata)
  const [name, setName] = useState(meta.name)
  const [desc, setDesc] = useState(meta.description)
  return (
    <Dialog
      title={t('pm.saveAsTitle')}
      onClose={close}
      width={480}
      footer={
        <>
          <Button onClick={close}>{t('c.cancel')}</Button>
          <Button
            variant="primary"
            disabled={!name.trim()}
            onClick={async () => {
              await saveProjectAs(name.trim(), desc)
              close()
            }}
          >
            {t('c.save')}
          </Button>
        </>
      }
    >
      <div className="space-y-2 p-4">
        <label className="block">
          <div className="mb-1 text-muted">{t('pm.projectName')}</div>
          <input autoFocus className="field-input w-full" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.stopPropagation()} />
        </label>
        <label className="block">
          <div className="mb-1 text-muted">{t('pm.description')}</div>
          <textarea className="field-input h-20 w-full py-1" value={desc} onChange={(e) => setDesc(e.target.value)} onKeyDown={(e) => e.stopPropagation()} />
        </label>
        <div className="text-small text-faint">{t('pm.saveAsHelp')}</div>
      </div>
    </Dialog>
  )
}

export function ProjectInfoDialog() {
  const t = useT()
  const close = useUiStore((s) => s.closeDialog)
  const project = useProjectStore((s) => s.project)
  const setMeta = useProjectStore((s) => s.setMetadata)
  const m = project.metadata
  return (
    <Dialog title={t('tb.project')} onClose={close} width={560} footer={<><Button onClick={() => exportProject()}>{t('tb.export')}</Button><Button variant="primary" onClick={close}>{t('c.ok')}</Button></>}>
      <div className="grid grid-cols-[120px_1fr] items-center gap-2 p-4">
        <span className="text-muted">{t('pm.projectName')}</span>
        <TextField ariaLabel={t('pm.projectName')} value={m.name} onCommit={(v) => setMeta({ name: v })} />
        <span className="text-muted">{t('pm.description')}</span>
        <TextField ariaLabel={t('pm.description')} value={m.description} onCommit={(v) => setMeta({ description: v })} />
        <span className="text-muted">{t('pm.author')}</span>
        <TextField ariaLabel={t('pm.author')} value={m.author} onCommit={(v) => setMeta({ author: v })} />
        <span className="text-muted">{t('pm.tags')}</span>
        <TextField ariaLabel={t('pm.tags')} value={m.tags.join(', ')} onCommit={(v) => setMeta({ tags: v.split(',').map((x) => x.trim()).filter(Boolean) })} />
        <span className="text-muted">{t('pm.created')}</span>
        <span className="num text-muted">{new Date(m.created).toLocaleString()}</span>
        <span className="text-muted">{t('pm.modified')}</span>
        <span className="num text-muted">{new Date(m.modified).toLocaleString()}</span>
        <span className="text-muted">{t('pm.projectId')}</span>
        <span className="num text-muted">{project.id}</span>
        <span className="text-muted">{t('pm.schema')}</span>
        <span className="num text-muted">
          {project.format} v{project.schema_version}
        </span>
        <span className="text-muted">{t('pm.provenance')}</span>
        <span className="text-muted">{project.provenance.created_with}</span>
        {project.provenance.warnings.length > 0 && (
          <>
            <span className="text-muted">{t('pm.importWarnings')}</span>
            <div className="text-warn">{project.provenance.warnings.join('; ')}</div>
          </>
        )}
      </div>
    </Dialog>
  )
}

export function PreferencesDialog() {
  const t = useT()
  const ui = useUiStore()
  return (
    <Dialog title={t('pref.title')} onClose={ui.closeDialog} width={480} icon={<Settings2 size={16} className="text-accent" />} footer={<Button variant="primary" onClick={ui.closeDialog}>{t('c.close')}</Button>}>
      <div className="space-y-4 p-4">
        <div>
          <div className="mb-2 text-small font-semibold tracking-wide text-muted uppercase">{t('pref.appearance')}</div>
          <div className="grid grid-cols-[120px_1fr] items-center gap-2">
            <span className="text-muted">{t('pref.theme')}</span>
            <Select
              className="w-44"
              ariaLabel={t('pref.theme')}
              value={ui.theme}
              options={[
                { value: 'dark', label: t('pref.dark') },
                { value: 'light', label: t('pref.light') },
              ]}
              onChange={ui.setTheme}
            />
            <span className="text-muted">{t('pref.language')}</span>
            <Select
              className="w-44"
              ariaLabel={t('pref.language')}
              value={ui.lang}
              options={[
                { value: 'en', label: 'English' },
                { value: 'fi', label: 'Suomi' },
              ]}
              onChange={ui.setLang}
            />
          </div>
        </div>
        <div>
          <div className="mb-2 text-small font-semibold tracking-wide text-muted uppercase">{t('pref.startup')}</div>
          <Checkbox checked={ui.showStartAtStartup} onChange={(v) => ui.set({ showStartAtStartup: v })} label={t('start.showAtStartup')} />
          <div className="mt-1 pl-5 text-small leading-snug text-faint">{t('pref.startupHint')}</div>
        </div>
        <div>
          <div className="mb-2 text-small font-semibold tracking-wide text-muted uppercase">{t('pref.analyses')}</div>
          <Checkbox checked={ui.liveAnalysis} onChange={(v) => ui.set({ liveAnalysis: v })} label={t('pref.live')} />
        </div>
        <div className="text-small text-faint">{t('pref.note')}</div>
      </div>
    </Dialog>
  )
}

// ------------------------------------------------------------------ command palette
interface PaletteItem {
  id: string
  group: string
  label: string
  /** extra search words, not shown */
  keywords?: string
  hint?: string
  run: () => void
}

export function CommandPalette() {
  const t = useT()
  const ui = useUiStore()
  const system = useProjectStore((s) => s.project.system)
  const select = useProjectStore((s) => s.select)
  const [q, setQ] = useState('')
  const [k, setK] = useState(0)
  const list = useRef<HTMLDivElement>(null)
  const items: PaletteItem[] = useMemo(() => {
    const cmds: PaletteItem[] = [
      { id: 'new', group: t('pal.commands'), label: t('tb.new'), hint: 'Ctrl+N', run: () => ui.openDialog('start') },
      { id: 'start', group: t('pal.commands'), label: t('start.open'), run: () => ui.openDialog('start') },
      { id: 'firstLens', group: t('pal.commands'), label: t('fl.title'), run: () => ui.openDialog('firstLens') },
      { id: 'optWizard', group: t('pal.commands'), label: t('ow.title'), run: () => ui.openDialog('optWizard') },
      { id: 'prefs', group: t('pal.commands'), label: t('pref.title'), run: () => ui.openDialog('preferences') },
      { id: 'open', group: t('pal.commands'), label: t('tb.open'), hint: 'Ctrl+O', run: () => ui.openDialog('projects') },
      { id: 'save', group: t('pal.commands'), label: t('tb.save'), hint: 'Ctrl+S', run: () => saveProject() },
      { id: 'saveas', group: t('pal.commands'), label: t('tb.saveAs'), hint: 'Ctrl+Shift+S', run: () => ui.openDialog('saveAs') },
      { id: 'export', group: t('pal.commands'), label: t('tb.export'), hint: 'Ctrl+E', run: () => exportProject() },
      { id: 'report', group: t('pal.commands'), label: t('tb.report'), run: () => generateReport() },
      { id: 'cadExport', group: t('pal.commands'), label: t('tb.cadExport'), run: () => ui.openDialog('cadExport') },
      { id: 'import', group: t('pal.commands'), label: t('tb.import'), run: () => importProjectFile() },
      { id: 'undo', group: t('pal.commands'), label: t('tb.undo'), hint: 'Ctrl+Z', run: undo },
      { id: 'redo', group: t('pal.commands'), label: t('tb.redo'), hint: 'Ctrl+Y', run: redo },
      { id: 'ins', group: t('pal.commands'), label: t('lde.insertAfter'), hint: 'Ins', run: insertSurfaceAfterSelection },
      { id: 'del', group: t('pal.commands'), label: t('lde.delete'), hint: 'Del', run: deleteSelection },
      { id: 'focus', group: t('pal.commands'), label: t('tb.focus'), run: quickFocus },
      { id: 'trace', group: t('pal.commands'), label: t('tb.trace'), hint: 'F5', run: retrace },
      { id: 'opt', group: t('pal.commands'), label: t('tb.optimize'), run: () => ui.set({ bottomTab: 'optimization', bottomOpen: true }) },
      { id: 'mat', group: t('pal.commands'), label: t('tb.materials'), hint: 'Ctrl+M', run: () => ui.openDialog('materials') },
      { id: 'stock', group: t('pal.commands'), label: t('st.open'), keywords: 'stock catalogue lens vendor thorlabs edmund insert', run: () => ui.openDialog('stockLenses') },
      { id: 'coat', group: t('pal.commands'), label: t('coat.title'), run: () => ui.openDialog('coatings') },
      { id: 'coatdes', group: t('pal.commands'), label: t('cd.title'), run: () => ui.openDialog('coatingDesigner') },
      { id: 'theme', group: t('pal.commands'), label: t('tb.theme'), run: () => ui.setTheme(ui.theme === 'dark' ? 'light' : 'dark') },
      { id: 'lang', group: t('pal.commands'), label: t('tb.language'), run: () => ui.setLang(ui.lang === 'en' ? 'fi' : 'en') },
      { id: 'keys', group: t('pal.commands'), label: t('tb.shortcuts'), hint: '?', run: () => ui.openDialog('shortcuts') },
      ...WORKSPACES.map((w) => ({ id: 'ws-' + w.id, group: t('pal.commands'), label: `${t('ws.title')}: ${t('ws.' + w.id)}`, run: () => ui.setWorkspace(w.id) })),
      { id: 'ws-reset', group: t('pal.commands'), label: t('ws.reset'), run: () => ui.resetLayout() },
      ...VIEW_IDS.map((v) => ({ id: 'view-' + v, group: t('pal.commands'), label: `${t('vg.' + viewGroup(v))} › ${t('view.' + v)}`, keywords: t('tb.analyze'), run: () => ui.showView(v) })),
      ...(['lde', 'system', 'configs', 'merit', 'optimization', 'tolerancing', 'cad', 'sources', 'messages', 'console'] as const).map((b) => ({ id: 'tab-' + b, group: t('pal.commands'), label: t('bt.' + b), run: () => ui.set({ bottomTab: b, bottomOpen: true }) })),
    ]
    const params: PaletteItem[] = system.surfaces.flatMap((s, i) => {
      const go = () => {
        select(i)
        ui.set({ bottomTab: 'lde', bottomOpen: true })
      }
      const base = `${i} ${s.label || ''}`.trim()
      return [
        { id: `p${i}r`, group: t('pal.parameters'), label: `S${base} · radius = ${s.radius === null ? '∞' : fmt(s.radius, 7)}`, run: go },
        { id: `p${i}t`, group: t('pal.parameters'), label: `S${base} · thickness = ${s.thickness === null ? '∞' : fmt(s.thickness, 7)}`, run: go },
        { id: `p${i}m`, group: t('pal.parameters'), label: `S${base} · material = ${s.material}`, run: go },
        ...(s.conic ? [{ id: `p${i}k`, group: t('pal.parameters'), label: `S${base} · conic = ${fmt(s.conic, 6)}`, run: go }] : []),
      ]
    })
    return [...cmds, ...params]
  }, [system, t, ui, select])
  const words = q.toLowerCase().split(/\s+/).filter(Boolean)
  const filtered = items.filter((it) => words.every((w) => `${it.label} ${it.group} ${it.keywords ?? ''}`.toLowerCase().includes(w))).slice(0, 60)
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === 'Escape' && ui.closeDialog()
    window.addEventListener('keydown', h, true)
    return () => window.removeEventListener('keydown', h, true)
  }, [ui])
  useEffect(() => {
    list.current?.querySelector(`[data-k="${k}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [k])
  const run = (it: PaletteItem) => {
    ui.closeDialog()
    setTimeout(it.run, 0)
  }
  return (
    <div className="fixed inset-0 z-50 flex justify-center bg-black/35 pt-[12vh]" onMouseDown={ui.closeDialog}>
      <div className="fade-in flex h-fit max-h-[60vh] w-full max-w-[620px] flex-col overflow-hidden rounded-lg border border-line-strong bg-panel shadow-[var(--shadow)]" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-line px-3">
          <Search size={16} className="text-muted" />
          <input
            autoFocus
            className="h-11 flex-1 bg-transparent text-title outline-none"
            aria-label={t('tb.palette')}
            placeholder={t('pal.placeholder')}
            value={q}
            onChange={(e) => {
              setQ(e.target.value)
              setK(0) // a new query starts at its first match
            }}
            onKeyDown={(e) => {
              e.stopPropagation()
              if (e.key === 'ArrowDown') {
                e.preventDefault()
                setK(Math.min(k + 1, filtered.length - 1))
              } else if (e.key === 'ArrowUp') {
                e.preventDefault()
                setK(Math.max(k - 1, 0))
              } else if (e.key === 'Enter' && filtered[k]) run(filtered[k])
              else if (e.key === 'Escape') ui.closeDialog()
            }}
          />
          <span className="kbd">Esc</span>
        </div>
        <div ref={list} className="min-h-0 flex-1 overflow-auto py-1">
          {filtered.map((it, i) => (
            <button key={it.id} data-k={i} className={cx('flex h-8 w-full items-center gap-3 px-3 text-left text-body', i === k ? 'bg-select' : 'hover:bg-hover')} onMouseEnter={() => setK(i)} onClick={() => run(it)}>
              {it.group === t('pal.commands') ? <Command size={14} className="text-faint" /> : <Search size={14} className="text-faint" />}
              <span className="flex-1 truncate">{it.label}</span>
              {it.hint && <span className="kbd">{it.hint}</span>}
            </button>
          ))}
          {filtered.length === 0 && <div className="p-4 text-muted">{t('pal.noMatch')}</div>}
        </div>
      </div>
    </div>
  )
}

export function ShortcutsDialog() {
  const t = useT()
  const close = useUiStore((s) => s.closeDialog)
  const rows: [string, string][] = [
    ['Ctrl+K', t('tb.palette')],
    ['Ctrl+N', t('start.open')],
    ['Ctrl+O', t('tb.open')],
    ['Ctrl+S', t('tb.save')],
    ['Ctrl+Shift+S', t('tb.saveAs')],
    ['Ctrl+E', t('tb.export')],
    ['Ctrl+Z', t('tb.undo')],
    ['Ctrl+Y / Ctrl+Shift+Z', t('tb.redo')],
    ['Ctrl+M', t('tb.materials')],
    ['F5', t('tb.trace')],
    ['Insert', t('lde.insertAfter')],
    ['Delete', t('lde.delete')],
    ['↑ / ↓', t('sc.prevNext')],
    ['Ctrl+A', t('sc.selectAll')],
    ['Ctrl+1 … Ctrl+9', t('sc.views')],
    ['Ctrl+B / Ctrl+J / Ctrl+I', t('sc.panels')],
    ['?', t('tb.shortcuts')],
    ['Enter / Esc', t('sc.cell')],
  ]
  return (
    <Dialog title={t('tb.shortcuts')} onClose={close} width={520} icon={<Keyboard size={16} className="text-accent" />}>
      <table className="eng-table">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td className="w-[200px] px-3">
                <span className="kbd">{k}</span>
              </td>
              <td className="px-3">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Dialog>
  )
}

export function AboutDialog() {
  const t = useT()
  const close = useUiStore((s) => s.closeDialog)
  const version = useEngineStore((s) => s.engineVersion)
  return (
    <Dialog title={t('tb.about')} onClose={close} width={640} icon={<ShieldCheck size={16} className="text-accent" />}>
      <div className="space-y-3 p-4 leading-relaxed">
        <div>
          <div className="text-title font-semibold">OptiCore Studio</div>
          <div className="text-muted">{t('ab.subtitle', { engine: version ?? t('st.offline') })}</div>
        </div>
        <div>
          <div className="mb-1 font-semibold">{t('ab.numbers')}</div>
          <ul className="list-disc space-y-1 pl-5 text-muted">
            {(['ab.rays', 'ab.paraxial', 'ab.diffraction', 'ab.physics', 'ab.wave', 'ab.materials'] as const).map((k) => (
              <li key={k}>{t(k)}</li>
            ))}
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">{t('ab.limits')}</div>
          <div className="text-muted">{t('ab.limitsText')}</div>
        </div>
        <div>
          <div className="mb-1 font-semibold">{t('ab.validation')}</div>
          <div className="text-muted">{t('ab.validationText')}</div>
        </div>
      </div>
    </Dialog>
  )
}

const NONE_SAVED: import('../../lib/types').SavedAnalysis[] = []

export function SavedAnalysisDialog() {
  const t = useT()
  const close = useUiStore((s) => s.closeDialog)
  const arg = useUiStore((s) => s.dialogArg) as { savedAnalysis?: string } | null
  const saved = useProjectStore((s) => s.project.analysis_settings.saved) ?? NONE_SAVED
  const a = saved.find((x) => x.id === arg?.savedAnalysis)
  if (!a) return null
  const spot = a.type === 'spot' ? (a.result as SpotResult) : null
  return (
    <Dialog title={a.label} onClose={close} width={640} footer={<Button onClick={() => {
      const blob = new Blob([JSON.stringify(a, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const el = document.createElement('a')
      el.href = url
      el.download = `${a.type}-${a.id}.json`
      el.click()
      URL.revokeObjectURL(url)
    }}>{t('sa.exportJson')}</Button>}>
      <div className="p-4">
        <div className="mb-2 text-muted">
          {t('sa.snapshot', { type: a.type, time: new Date(a.timestamp).toLocaleString() })} <span className="num">{JSON.stringify(a.settings)}</span>
        </div>
        {spot ? (
          <table className="eng-table">
            <thead>
              <tr>
                <th>{t('c.field')}</th>
                <th className="text-right">RMS (µm)</th>
                <th className="text-right">GEO (µm)</th>
                <th className="text-right">{t('sa.rays')}</th>
              </tr>
            </thead>
            <tbody>
              {spot.fields.map((f) => (
                <tr key={f.field}>
                  <td className="px-2">F{f.field + 1}</td>
                  <td className="num px-2 text-right">{fmt(f.rms_radius_um, 5)}</td>
                  <td className="num px-2 text-right">{fmt(f.geo_radius_um, 5)}</td>
                  <td className="num px-2 text-right">{f.per_wavelength.reduce((s, w) => s + w.n_ok, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <pre className="max-h-[50vh] overflow-auto rounded bg-panel-2 p-2 num text-small">{JSON.stringify(a.result, null, 1).slice(0, 20000)}</pre>
        )}
      </div>
    </Dialog>
  )
}

const STATUS_TONE: Record<string, 'ok' | 'warn' | 'danger' | 'default' | 'accent'> = {
  imported: 'ok',
  partial: 'warn',
  conversion: 'accent',
  unsupported: 'danger',
  missing_material: 'danger',
  info: 'default',
}

export function CadExportDialog() {
  const t = useT()
  const close = useUiStore((s) => s.closeDialog)
  const toast = useUiStore((s) => s.toast)
  const nCad = useProjectStore((s) => s.project.cad_assets.length)
  const [opts, setOpts] = useState<CadExportOptions>({ format: 'step', rim_margin: 0, include_stop: true, include_image: true, include_rays: true, include_cad: true, include_mechanics: false })
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<Awaited<ReturnType<typeof exportCad>> | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const set = (p: Partial<CadExportOptions>) => setOpts({ ...opts, ...p })
  return (
    <Dialog
      title={t('cadx.title')}
      onClose={close}
      width={560}
      footer={
        <>
          <Button onClick={close}>{done ? t('c.ok') : t('c.cancel')}</Button>
          <Button
            variant="primary"
            disabled={busy}
            onClick={async () => {
              setBusy(true)
              setErr(null)
              try {
                const r = await exportCad(opts)
                setDone(r)
                toast('success', `${r.name} ${t('cadx.saved')}`)
              } catch (e) {
                setErr((e as Error).message)
              }
              setBusy(false)
            }}
          >
            {busy ? <Spinner size={12} /> : null} {t('cadx.export')}
          </Button>
        </>
      }
    >
      <div className="space-y-2 p-4">
        <div className="grid grid-cols-[130px_1fr] items-center gap-2">
          <span className="text-muted">{t('cadx.format')}</span>
          <Select
            ariaLabel={t('cadx.format')}
            value={opts.format}
            options={[
              { value: 'step', label: 'STEP AP214 (.step)' },
              { value: 'iges', label: 'IGES 5.3 B-rep (.igs)' },
            ]}
            onChange={(v) => set({ format: v })}
          />
          <span className="text-muted">{t('cadx.rim')}</span>
          <NumberField className="w-28" ariaLabel={t('cadx.rim')} value={opts.rim_margin} min={0} max={100} onCommit={(v) => set({ rim_margin: v ?? 0 })} />
        </div>
        <div className="flex flex-col items-start gap-1.5 pt-1">
          <Checkbox checked={opts.include_stop} onChange={(v) => set({ include_stop: v })} label={t('cadx.stop')} />
          <Checkbox checked={opts.include_image} onChange={(v) => set({ include_image: v })} label={t('cadx.image')} />
          <Checkbox checked={opts.include_rays} onChange={(v) => set({ include_rays: v })} label={t('cadx.rays')} />
          <Checkbox checked={opts.include_cad} onChange={(v) => set({ include_cad: v })} label={`${t('cadx.cad')} (${nCad})`} />
          <span title={t('cadx.mechanicsHint')}>
            <Checkbox checked={opts.include_mechanics} onChange={(v) => set({ include_mechanics: v })} label={t('cadx.mechanics')} />
          </span>
        </div>
        <div className="text-small leading-snug text-faint">{t('cadx.help')}</div>
        {err && <div className="text-body text-danger">{err}</div>}
        {done && (
          <div className="rounded border border-line p-2 text-small">
            <div className="mb-1 font-semibold">{done.name}</div>
            {done.report.solids.map((s) => (
              <div key={s.name} className="num flex justify-between text-muted">
                <span>{s.name}</span>
                <span>
                  {s.front}/{s.back} · Ø {fmt(2 * s.rim_radius_mm, 5)} mm · {fmt(s.volume_mm3, 6)} mm³
                </span>
              </div>
            ))}
            {done.report.mechanics?.spacers.map((s, k) => (
              <div key={`sp${k}`} className="num flex justify-between text-muted">
                <span>{t('cadx.spacer', { k: k + 1, a: s.between[0], b: s.between[1] })}</span>
                <span>
                  {fmt(s.length_mm, 4)} mm · {fmt(s.volume_mm3, 6)} mm³
                </span>
              </div>
            ))}
            {done.report.mechanics?.barrel && (
              <div className="num flex justify-between text-muted">
                <span>{t('cadx.barrel')}</span>
                <span>
                  Ø {fmt(2 * done.report.mechanics.barrel.inner_radius_mm, 5)}/{fmt(2 * done.report.mechanics.barrel.outer_radius_mm, 5)} mm · {fmt(done.report.mechanics.barrel.volume_mm3, 6)} mm³
                </span>
              </div>
            )}
            {done.report.skipped.map((s) => (
              <div key={s.surfaces.join('-')} className="text-warn">
                S{s.surfaces.join('-')}: {s.reason}
              </div>
            ))}
            {done.report.notes.map((n) => (
              <div key={n} className="text-faint">
                {n}
              </div>
            ))}
          </div>
        )}
      </div>
    </Dialog>
  )
}

export function StlImportDialog() {
  const t = useT()
  const close = useUiStore((s) => s.closeDialog)
  const arg = useUiStore((s) => s.dialogArg) as { file: File } | null
  const [units, setUnits] = useState('mm')
  const [busy, setBusy] = useState(false)
  if (!arg) return null
  return (
    <Dialog
      title={`${t('cad.importTitle')}: ${arg.file.name}`}
      onClose={close}
      width={460}
      footer={
        <>
          <Button onClick={close}>{t('c.cancel')}</Button>
          <Button
            variant="primary"
            disabled={busy}
            onClick={async () => {
              setBusy(true)
              const ok = await importStlFile(arg.file, units)
              setBusy(false)
              if (ok) close()
            }}
          >
            {busy ? <Spinner size={12} /> : null} {t('cad.import')}
          </Button>
        </>
      }
    >
      <div className="space-y-2 p-4">
        <div className="text-muted">{t('cad.unitsQ')}</div>
        <Select
          className="w-[200px]"
          value={units}
          options={[
            { value: 'mm', label: 'millimetres (mm)' },
            { value: 'cm', label: 'centimetres (cm)' },
            { value: 'm', label: 'metres (m)' },
            { value: 'in', label: 'inches (in)' },
            { value: 'um', label: 'micrometres (µm)' },
          ]}
          onChange={setUnits}
        />
        <div className="text-small leading-snug text-faint">{t('cad.note')}</div>
      </div>
    </Dialog>
  )
}

export function ImportReportDialog() {
  const t = useT()
  const close = useUiStore((s) => s.closeDialog)
  const arg = useUiStore((s) => s.dialogArg) as { filename: string; diagnostics: { status: string; message: string; surface: number | null; line: number | null }[] } | null
  if (!arg) return null
  const counts = arg.diagnostics.reduce<Record<string, number>>((a, d) => ((a[d.status] = (a[d.status] ?? 0) + 1), a), {})
  return (
    <Dialog title={`${t('imp.title')}: ${arg.filename}`} onClose={close} width={760} footer={<Button variant="primary" onClick={close}>{t('c.ok')}</Button>}>
      <div className="flex flex-wrap gap-2 border-b border-line p-3">
        {Object.entries(counts).map(([k, v]) => (
          <Badge key={k} tone={STATUS_TONE[k] ?? 'default'}>
            {t('imp.' + k)}: {v}
          </Badge>
        ))}
      </div>
      <table className="eng-table">
        <thead>
          <tr>
            <th className="w-[130px]">{t('msg.level')}</th>
            <th className="w-[60px]">{t('c.surface')}</th>
            <th className="w-[60px]">{t('imp.line')}</th>
            <th>{t('msg.message')}</th>
          </tr>
        </thead>
        <tbody>
          {arg.diagnostics.map((d, i) => (
            <tr key={i}>
              <td className="px-2">
                <Badge tone={STATUS_TONE[d.status] ?? 'default'}>{t('imp.' + d.status)}</Badge>
              </td>
              <td className="num px-2">{d.surface ?? '—'}</td>
              <td className="num px-2 text-muted">{d.line ?? '—'}</td>
              <td className="px-2 whitespace-normal">{d.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="p-3 text-small leading-relaxed text-faint">{t('imp.workflow')}</div>
    </Dialog>
  )
}

export function Toasts() {
  const t = useT()
  const toasts = useUiStore((s) => s.toasts)
  const dismiss = useUiStore((s) => s.dismissToast)
  return (
    <div className="pointer-events-none fixed right-4 bottom-9 z-[95] flex w-[380px] flex-col gap-2">
      {toasts.map((x) => (
        <div key={x.id} className="fade-in pointer-events-auto flex items-start gap-2 rounded-lg border border-line-strong bg-elev px-3 py-2 shadow-[var(--shadow)]">
          {x.kind === 'success' ? <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-ok" /> : x.kind === 'error' ? <AlertTriangle size={16} className="mt-0.5 shrink-0 text-danger" /> : x.kind === 'warning' ? <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn" /> : <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-accent" />}
          <div className="flex-1 text-body leading-snug">{x.text}</div>
          <IconButton size="sm" title={t('c.dismiss')} onClick={() => dismiss(x.id)}>
            <X size={14} />
          </IconButton>
        </div>
      ))}
    </div>
  )
}

export function DialogHost() {
  const dialog = useUiStore((s) => s.dialog)
  const arg = useUiStore((s) => s.dialogArg) as { savedAnalysis?: string } | null
  switch (dialog) {
    case 'stockLenses':
      return <StockLensDialog />
    case 'materials':
      return <MaterialBrowser />
    case 'coatings':
      return <CoatingEditor />
    case 'projects':
      return <ProjectManager />
    case 'start':
      return <StartScreen />
    case 'firstLens':
      return <FirstLensDialog />
    case 'optWizard':
      return <OptWizard />
    case 'preferences':
      return <PreferencesDialog />
    case 'saveAs':
      return <SaveAsDialog />
    case 'projectInfo':
      return <ProjectInfoDialog />
    case 'palette':
      return <CommandPalette />
    case 'shortcuts':
      return <ShortcutsDialog />
    case 'about':
      return arg?.savedAnalysis ? <SavedAnalysisDialog /> : <AboutDialog />
    case 'importReport':
      return <ImportReportDialog />
    case 'stlImport':
      return <StlImportDialog />
    case 'cadExport':
      return <CadExportDialog />
    case 'cadOptics':
      return <CadOpticsDialog />
    case 'elementDrawing':
      return <ElementDrawingDialog />
    default:
      return null
  }
}
