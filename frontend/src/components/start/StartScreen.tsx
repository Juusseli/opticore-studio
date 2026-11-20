import { FilePlus2, FileUp, FolderOpen, History, Import, Layers, LifeBuoy, Sparkles, Waypoints, X } from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'
import { confirmDiscard, discardRecovery, importProjectFile, newBlankProject, newFromTemplate, openProject } from '../../actions'
import { api } from '../../lib/api'
import { timeAgo } from '../../lib/format'
import { hasKey, useT } from '../../lib/i18n'
import { groupTemplates } from '../../lib/startup'
import { storage, type StoredProject } from '../../lib/storage'
import type { SampleInfo } from '../../lib/types'
import { useEngineStore } from '../../store/engineStore'
import { isDirty, useProjectStore } from '../../store/projectStore'
import { isConfirmOpen } from '../../store/confirmStore'
import { useUiStore } from '../../store/uiStore'
import { Button, Checkbox, IconButton, Spinner, Tooltip } from '../common/ui'
import { cx } from '../common/uiUtils'
import { OutlineThumb } from './OutlineThumb'
import { useProjectOutline } from './useProjectOutline'

const RECENT = 6

/** Built-in coatings shown on the start screen (one of each kind). */
const FEATURED_COATINGS = ['BBAR_VIS', 'VCOAT_1064', 'HR_1064', 'DM_800', 'LP_550', 'BP_532', 'NOTCH_532', 'PBS_MACNEILLE']

function Heading({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-2 flex items-center gap-2 text-small font-semibold tracking-wide text-muted uppercase">
      <span className="flex-1">{children}</span>
      {right}
    </div>
  )
}

function Action({ icon, label, hint, onClick, disabled }: { icon: ReactNode; label: string; hint: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button disabled={disabled} onClick={onClick} aria-label={label} title={hint} className="flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-hover disabled:pointer-events-none disabled:opacity-40">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent">{icon}</span>
      <span className="min-w-0">
        <span className="block text-body font-medium">{label}</span>
        <span className="block truncate text-small text-muted">{hint}</span>
      </span>
    </button>
  )
}

function RecentRow({ item, current, onOpen }: { item: StoredProject; current: boolean; onOpen: () => void }) {
  const t = useT()
  const outline = useProjectOutline(item.project, `${item.id}@${item.savedAt}`)
  return (
    <button onClick={onOpen} aria-label={`${t('pm.open')}: ${item.name}`} title={`${t('pm.open')}: ${item.name}`} className={cx('flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-hover', current && 'bg-select')}>
      <span className="flex h-9 w-16 shrink-0 items-center justify-center overflow-hidden rounded-md border border-line bg-panel-2">{outline ? <OutlineThumb outline={outline} className="h-full w-full" /> : <FolderOpen size={14} className="text-faint" />}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-body font-medium">{item.name}</span>
        <span className="block truncate text-small text-muted">
          {timeAgo(item.savedAt)} · {t('start.surfaces', { n: item.project.system.surfaces.length - 2 })}
        </span>
      </span>
    </button>
  )
}

function TemplateCard({ s, busy, disabled, onPick }: { s: SampleInfo; busy: boolean; disabled: boolean; onPick: () => void }) {
  const t = useT()
  const name = hasKey(`tpl.${s.id}.name`) ? t(`tpl.${s.id}.name`) : s.name
  const purpose = hasKey(`tpl.${s.id}.purpose`) ? t(`tpl.${s.id}.purpose`) : s.description
  return (
    <Tooltip text={s.description}>
      <button
        disabled={disabled}
        onClick={onPick}
        aria-label={`${t('start.templates')}: ${name}`}
        className="group flex w-full flex-col overflow-hidden rounded-lg border border-line bg-panel text-left transition-colors hover:border-accent disabled:opacity-60"
      >
        <span className="relative flex h-19 w-full items-center justify-center border-b border-line bg-panel-2 px-2 py-1.5 group-hover:bg-accent-soft">
          {s.outline ? <OutlineThumb outline={s.outline} className="h-full w-full" /> : <Waypoints size={18} className="text-faint" />}
          {busy && (
            <span className="absolute inset-0 flex items-center justify-center bg-panel/60">
              <Spinner />
            </span>
          )}
        </span>
        <span className="block px-2.5 pt-2 text-body font-semibold">{name}</span>
        <span className="line-clamp-2 block px-2.5 pt-0.5 pb-2 text-small leading-snug text-muted">{purpose}</span>
      </button>
    </Tooltip>
  )
}

export function StartScreen() {
  const t = useT()
  const backend = useEngineStore((s) => s.backend)
  const coatings = useEngineStore((s) => s.coatings)
  const version = useEngineStore((s) => s.engineVersion)
  const currentId = useProjectStore((s) => s.project.id)
  const currentName = useProjectStore((s) => s.project.metadata.name)
  const dirty = useProjectStore(isDirty)
  const recovery = useUiStore((s) => s.recovery)
  const showAtStartup = useUiStore((s) => s.showStartAtStartup)
  const setUi = useUiStore((s) => s.set)
  const [samples, setSamples] = useState<SampleInfo[] | null>(null)
  const [recent, setRecent] = useState<StoredProject[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => {
    if (backend !== 'online') return
    api
      .samples()
      .then((r) => setSamples(r.samples))
      .catch(() => setSamples([]))
  }, [backend])
  useEffect(() => {
    storage
      .listProjects()
      .then(setRecent)
      .catch(() => setRecent([]))
  }, [recovery])

  /** leave the start screen for the workspace (recovered work stays open as it is) */
  const close = () => {
    setUi({ recovery: null })
    useUiStore.getState().closeDialog()
  }
  /** close after an action opened something, unless that action opened its own dialog (import report …) */
  const done = (ok: boolean) => {
    if (ok && useUiStore.getState().dialog === 'start') close()
  }
  const run = async (id: string, fn: () => Promise<boolean> | boolean) => {
    setBusy(id)
    try {
      done(await fn())
    } finally {
      setBusy(null)
    }
  }
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isConfirmOpen()) {
        e.stopPropagation()
        close()
      }
    }
    window.addEventListener('keydown', h, true)
    return () => window.removeEventListener('keydown', h, true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const groups = groupTemplates(samples ?? [])
  // the coating studio is a workspace: leave the start screen first, then switch to it
  const openCoating = (name?: string) => {
    close()
    useUiStore.getState().openDialog('coatingDesigner', name ? { coating: name } : undefined)
  }
  const featured = FEATURED_COATINGS.map((n) => coatings.find((c) => c.name === n)).filter((c): c is NonNullable<typeof c> => !!c)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-[3px]" onMouseDown={close}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="start-title"
        className="fade-in flex h-full max-h-[880px] w-full max-w-[1320px] flex-col overflow-hidden rounded-lg border border-line-strong bg-panel shadow-[var(--shadow)]"
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div className="flex h-14 shrink-0 items-center gap-3 border-b border-line px-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-sky-400 to-indigo-500 shadow">
            <Waypoints size={19} className="text-white" />
          </div>
          <div className="min-w-0 flex-1 leading-tight">
            <div id="start-title" className="text-title font-semibold tracking-tight">
              OptiCore Studio
            </div>
            <div className="text-small text-muted">{t('app.tagline')}</div>
          </div>
          <span className="flex items-center gap-1.5 text-small text-muted">
            <span className={cx('h-2 w-2 rounded-full', backend === 'online' ? 'bg-ok' : backend === 'offline' ? 'bg-danger' : 'bg-warn')} />
            {backend === 'online' ? `${t('st.online')} ${version ?? ''}` : backend === 'offline' ? t('st.offline') : t('st.connecting')}
          </span>
          <IconButton title={`${t('c.close')} (Esc)`} onClick={close}>
            <X size={16} />
          </IconButton>
        </div>

        <div className="flex min-h-0 flex-1">
          {/* left: start actions, unsaved work, recent projects */}
          <div className="flex w-[300px] shrink-0 flex-col gap-4 overflow-y-auto border-r border-line bg-panel-2 p-4">
            <div>
              <Heading>{t('start.begin')}</Heading>
              <Action icon={<Sparkles size={16} />} label={t('fl.title')} hint={backend === 'online' ? t('fl.hint') : t('start.needsEngine')} onClick={() => useUiStore.getState().openDialog('firstLens')} disabled={!!busy || backend !== 'online'} />
              <Action icon={<FilePlus2 size={16} />} label={t('pm.blank')} hint={t('pm.blankDesc')} onClick={() => run('blank', newBlankProject)} disabled={!!busy} />
              <Action icon={<FileUp size={16} />} label={t('start.openFile')} hint={t('start.openFileHint')} onClick={() => run('file', () => importProjectFile(null, '.opticore,.json,application/json'))} disabled={!!busy} />
              <Action
                icon={<Import size={16} />}
                label={t('start.importZmx')}
                hint={backend === 'online' ? t('start.importZmxHint') : t('start.needsEngine')}
                onClick={() => run('zmx', () => importProjectFile(null, '.zmx,.ZMX'))}
                disabled={!!busy || backend !== 'online'}
              />
              <Action icon={<FolderOpen size={16} />} label={t('start.library')} hint={t('start.libraryHint')} onClick={() => useUiStore.getState().openDialog('projects')} disabled={!!busy} />
              <Action icon={<Layers size={16} />} label={t('start.coatings')} hint={backend === 'online' ? t('start.coatingsHint') : t('start.needsEngine')} onClick={() => openCoating()} disabled={!!busy || backend !== 'online'} />
            </div>

            {recovery && (
              <div className="rounded-lg border border-warn/50 bg-warn/10 p-3" role="region" aria-label={t('start.resumeTitle')}>
                <div className="mb-1 flex items-center gap-1.5 text-body font-semibold">
                  <LifeBuoy size={14} className="text-warn" />
                  {t('start.resumeTitle')}
                </div>
                <div className="mb-2.5 text-small leading-snug text-muted">{t('start.resumeText', { name: recovery.name, time: timeAgo(recovery.at) })}</div>
                <div className="flex gap-2">
                  <Button variant="primary" size="sm" onClick={close}>
                    {t('start.resume')}
                  </Button>
                  <Button size="sm" onClick={() => discardRecovery()} title={recovery.inLibrary ? t('start.discardSavedHint') : t('start.discardHint')}>
                    {t('start.discard')}
                  </Button>
                </div>
              </div>
            )}

            <div className="min-h-0">
              <Heading
                right={
                  recent && recent.length > RECENT ? (
                    <Button variant="link" onClick={() => useUiStore.getState().openDialog('projects')}>
                      {t('start.allProjects', { n: recent.length })}
                    </Button>
                  ) : null
                }
              >
                <span className="inline-flex items-center gap-1.5">
                  <History size={12} />
                  {t('start.recent')}
                </span>
              </Heading>
              {!recent ? (
                <Spinner />
              ) : recent.length === 0 ? (
                <div className="text-small leading-snug text-muted">{t('start.noRecent')}</div>
              ) : (
                <div className="flex flex-col gap-0.5">
                  {recent.slice(0, RECENT).map((it) => (
                    <RecentRow
                      key={it.id}
                      item={it}
                      current={it.id === currentId}
                      onOpen={async () => {
                        if (it.id === currentId && !dirty) return close()
                        if (!(await confirmDiscard())) return
                        openProject(it.project, { inLibrary: true })
                        close()
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* right: templates */}
          <div className="min-w-0 flex-1 overflow-y-auto p-4">
            <Heading>{t('start.templates')}</Heading>
            {backend === 'offline' ? (
              <div className="rounded-lg border border-line bg-panel-2 p-3 text-body leading-relaxed text-muted">{t('start.offline')}</div>
            ) : !samples ? (
              <Spinner />
            ) : (
              groups.map((g) => (
                <section key={g.category} className="mb-4" aria-label={t('start.cat.' + g.category)}>
                  <div className="mb-1.5 text-body font-semibold text-fg">{t('start.cat.' + g.category)}</div>
                  <div className="grid grid-cols-[repeat(auto-fill,minmax(190px,1fr))] gap-2.5">
                    {g.samples.map((s) => (
                      <TemplateCard key={s.id} s={s} busy={busy === s.id} disabled={!!busy} onPick={() => run(s.id, () => newFromTemplate(s.id))} />
                    ))}
                  </div>
                </section>
              ))
            )}
            {backend === 'online' && featured.length > 0 && (
              <section className="mb-4" aria-label={t('start.coatingLib')}>
                <div className="mb-1.5 flex items-center gap-2 text-body font-semibold text-fg">
                  <Layers size={14} className="text-accent" />
                  {t('start.coatingLib')}
                  <Button variant="link" className="ml-auto font-normal" onClick={() => openCoating()}>
                    {t('start.coatings')} ›
                  </Button>
                </div>
                <div className="grid grid-cols-[repeat(auto-fill,minmax(190px,1fr))] gap-2.5">
                  {featured.map((c) => (
                    <button
                      key={c.name}
                      onClick={() => openCoating(c.name)}
                      title={c.description}
                      className="flex flex-col gap-1 rounded-lg border border-line bg-panel-2 p-2.5 text-left transition-colors hover:border-accent/60 hover:bg-hover"
                    >
                      <span className="flex items-center gap-1.5">
                        <span className="text-body font-medium">{c.name}</span>
                        <span className="num ml-auto text-caption text-faint">{c.layers.length}L</span>
                      </span>
                      <span className="text-caption text-accent">{hasKey(`coat.cat.${c.category}`) ? t(`coat.cat.${c.category}`) : c.category}</span>
                      <span className="line-clamp-2 text-small leading-snug text-muted">{c.description}</span>
                    </button>
                  ))}
                </div>
              </section>
            )}
          </div>
        </div>

        {/* footer */}
        <div className="flex h-12 shrink-0 items-center gap-3 border-t border-line bg-panel-2 px-5">
          <Checkbox checked={showAtStartup} onChange={(v) => setUi({ showStartAtStartup: v })} label={t('start.showAtStartup')} title={t('start.showAtStartupHint')} />
          <span className="text-small text-faint">{t('start.reopenHint')}</span>
          <div className="flex-1" />
          <Button variant="primary" onClick={close} title={t('start.continueHint')}>
            <span className="max-w-[320px] truncate">{t('start.continue', { name: currentName })}</span>
          </Button>
        </div>
      </div>
    </div>
  )
}
