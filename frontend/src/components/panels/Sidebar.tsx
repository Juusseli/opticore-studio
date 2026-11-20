import { activeOverride } from '../../lib/configs'
import { Aperture, Box, Circle, CircleDot, Disc, FileText, History, Layers, Pin, Radio, Rainbow, ScanLine, Target, Trash2, TrendingDown, Variable as VarIcon } from 'lucide-react'
import { useAllMaterials } from '../../store/catalogStore'
import { fmt, timeAgo, wavelengthColor } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { paramLabel } from '../../lib/paramLabels'
import { saveProject } from '../../actions'
import { useEngineStore } from '../../store/engineStore'
import { isDirty, useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { type SidebarSection, workspace } from '../../lib/workspaces'
import { SystemCard } from './SystemCard'
import { Badge, Button, IconButton, Section } from '../common/ui'
import { cx } from '../common/uiUtils'
import { assemblyTree } from './assemblyTree'

const ICONS = { object: Target, lens: Disc, mirror: Circle, stop: Aperture, cb: Layers, surface: CircleDot, image: Target }

export function Sidebar() {
  const t = useT()
  const project = useProjectStore((s) => s.project)
  const dirty = useProjectStore(isDirty)
  const selection = useProjectStore((s) => s.selection)
  const select = useProjectStore((s) => s.select)
  const st = useProjectStore.getState
  const ui = useUiStore()
  const materials = useAllMaterials()
  const ev = useEngineStore((s) => s.evaluation)
  const sys = project.system
  const tree = assemblyTree(sys, t)
  const pd = ev?.paraxial[String(sys.primary_wavelength)]
  const used = [...new Set(sys.surfaces.map((s) => s.material).filter((m) => !['AIR', 'MIRROR', 'VACUUM'].includes(m)))]
  const saved = project.analysis_settings.saved ?? []
  // sections of the active workspace
  const sections = workspace(ui.workspace).sections
  const show = (k: SidebarSection) => sections.includes(k)

  return (
    <div className="flex h-full min-h-0 flex-col overflow-auto">
      <div className="cursor-pointer border-b border-line px-3 py-2.5 hover:bg-hover" onClick={() => ui.openDialog('projectInfo')}>
        <div className="flex items-center gap-1.5">
          <FileText size={14} className="text-accent" />
          <span className="truncate text-body font-semibold">{project.metadata.name}</span>
          {dirty && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-warn" title={t('st.unsaved')} />}
        </div>
        <div className="mt-0.5 truncate text-small text-faint">{project.metadata.description || sys.name}</div>
      </div>

      <SystemCard />

      {show('assembly') && (
        <Section title={t('sb.assembly')}>
          {tree.map((node, k) => {
            const Icon = ICONS[node.kind]
            const sel = node.surfaces.some((i) => selection.includes(i))
            return (
              <div key={k}>
                <div
                  className={cx('flex h-6 cursor-pointer items-center gap-2 px-3 text-body hover:bg-hover', sel && node.surfaces.length === 1 && 'bg-select')}
                  onClick={(e) => {
                    if (node.surfaces.length === 1) select(node.surfaces[0], e.ctrlKey ? 'toggle' : 'single')
                    else useProjectStore.setState({ selection: node.surfaces })
                  }}
                >
                  <Icon size={14} className={node.kind === 'lens' ? 'text-accent' : node.kind === 'stop' ? 'text-accent' : 'text-muted'} />
                  <span className="truncate">{node.label}</span>
                  <span className="ml-auto truncate text-caption text-faint">{node.detail}</span>
                </div>
                {node.kind === 'lens' &&
                  node.surfaces.map((i) => (
                    <div key={i} className={cx('flex h-6 cursor-pointer items-center gap-2 pr-3 pl-8 text-small text-muted hover:bg-hover', selection.includes(i) && 'bg-select text-fg')} onClick={(e) => select(i, e.ctrlKey ? 'toggle' : 'single')}>
                      <span className="num w-5 text-faint">{i}</span>
                      <span className="truncate">{sys.surfaces[i].label || 'surface'}</span>
                      {sys.surfaces[i].is_stop && <Badge tone="accent">STO</Badge>}
                      <span className="ml-auto num text-caption text-faint">{sys.surfaces[i].radius === null ? '∞' : fmt(sys.surfaces[i].radius, 5)}</span>
                    </div>
                  ))}
              </div>
            )
          })}
        </Section>
      )}

      {show('configs') && sys.multi_config && (
        <Section title={`${t('sb.configs')} (${sys.multi_config.names.length})`}>
          {sys.multi_config.names.map((name, k) => (
            <div
              key={k}
              className={cx('flex h-6 cursor-pointer items-center gap-2 px-3 text-small hover:bg-hover', k === sys.multi_config!.active ? 'text-fg' : 'text-muted')}
              onClick={() => st().setActiveConfiguration(k)}
              title={t('mc.activate')}
            >
              <span className={cx('h-2 w-2 shrink-0 rounded-full border', k === sys.multi_config!.active ? 'border-accent bg-accent' : 'border-faint')} />
              <span className="truncate">{name}</span>
              <span className="ml-auto num text-caption text-faint">{k + 1}</span>
            </div>
          ))}
          <Button variant="link" className="px-3 py-0.5" onClick={() => ui.set({ bottomTab: 'configs', bottomOpen: true })}>
            {t('mc.open')}
          </Button>
        </Section>
      )}

      {show('aperture') && (
        <Section title={t('sb.aperture')}>
          <div className="cursor-pointer space-y-0.5 px-3 text-small hover:text-fg" onClick={() => ui.set({ bottomTab: 'system', bottomOpen: true })}>
            <div className="flex justify-between text-muted">
              <span>{t('sys.' + sys.aperture.type)}</span>
              <span className="num text-fg">{fmt(Number(activeOverride(sys, null, 'aperture_value')?.value ?? sys.aperture.value), 6)}</span>
            </div>
            {pd && (
              <>
                <div className="flex justify-between text-muted">
                  <span>EFL</span>
                  <span className="num">{fmt(pd.efl, 6)} mm</span>
                </div>
                <div className="flex justify-between text-muted">
                  <span>F/#</span>
                  <span className="num">{fmt(pd.image_space_fnum, 4)}</span>
                </div>
              </>
            )}
          </div>
        </Section>
      )}

      {show('fields') && (
        <Section title={`${t('sb.fields')} (${sys.fields.length})`}>
          {sys.fields.map((f, i) => (
            <div key={i} className="flex h-6 cursor-pointer items-center gap-2 px-3 text-small text-muted hover:bg-hover" onClick={() => ui.set({ bottomTab: 'system', bottomOpen: true })}>
              <span className="num w-6 text-faint">F{i + 1}</span>
              <span className="num">
                {fmt(f.x, 4)}, {fmt(f.y, 4)} {sys.field_type === 'angle' ? '°' : 'mm'}
              </span>
              <span className="ml-auto text-faint">w {fmt(f.weight, 3)}</span>
            </div>
          ))}
        </Section>
      )}

      {show('wavelengths') && (
        <Section title={`${t('sb.wavelengths')} (${sys.wavelengths.length})`}>
          {sys.wavelengths.map((w, i) => (
            <div key={i} className="flex h-6 cursor-pointer items-center gap-2 px-3 text-small text-muted hover:bg-hover" onClick={() => ui.set({ bottomTab: 'system', bottomOpen: true })}>
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: wavelengthColor(w.value) }} />
              <span className="num">{fmt(w.value * 1000, 6)} nm</span>
              {i === sys.primary_wavelength && <Badge tone="accent">primary</Badge>}
              <span className="ml-auto text-faint">w {fmt(w.weight, 3)}</span>
            </div>
          ))}
        </Section>
      )}

      {show('materials') && (
        <Section title={`${t('sb.materials')} (${used.length})`} right={<Button variant="link" onClick={() => ui.openDialog('materials')}>{t('tb.materials')}</Button>}>
          {used.map((m) => {
            const info = materials.find((x) => x.name === m)
            const custom = project.custom_materials.some((c) => c.name.toUpperCase() === m)
            return (
              <div key={m} className="flex h-6 items-center gap-2 px-3 text-small text-muted">
                <Rainbow size={12} className="text-faint" />
                <span className="text-fg">{m}</span>
                {custom && <Badge tone="accent">project</Badge>}
                <span className="ml-auto num text-faint">{info ? `nd ${fmt(info.nd, 6)} · Vd ${fmt(info.vd, 4)}` : custom || !materials.length ? '' : <span className="text-danger">unknown</span>}</span>
              </div>
            )
          })}
        </Section>
      )}

      {show('cad') && project.cad_assets.length > 0 && (
        <Section title={`${t('sb.cad')} (${project.cad_assets.length})`}>
          {project.cad_assets.map((a) => (
            <div key={a.id} className="flex h-6 cursor-pointer items-center gap-2 px-3 text-small text-muted hover:bg-hover" onClick={() => ui.set({ bottomTab: 'cad', bottomOpen: true })} title={a.source_filename}>
              <Box size={12} className={a.visible ? 'text-accent' : 'text-faint'} />
              <span className="truncate">{a.name}</span>
              <span className="ml-auto num text-caption text-faint">{a.mesh.triangles.toLocaleString()} ▲</span>
            </div>
          ))}
        </Section>
      )}

      {show('sources') && (
        <Section title={`${t('sb.sources')} (${(project.sources?.length ?? 0) + (project.detectors?.length ?? 0)})`} defaultOpen={(project.sources?.length ?? 0) + (project.detectors?.length ?? 0) > 0}>
          {(project.sources?.length ?? 0) + (project.detectors?.length ?? 0) === 0 && (
            <div className="px-3 text-small leading-snug text-faint">
              {t('sb.noSources')}{' '}
              <Button variant="link" onClick={() => ui.set({ bottomTab: 'sources', bottomOpen: true })}>
                {t('sb.addSource')}
              </Button>
            </div>
          )}
          {[...(project.sources ?? []).map((s) => ({ s, src: true })), ...(project.detectors ?? []).map((s) => ({ s, src: false }))].map(({ s, src }) => (
            <div key={s.id} className="flex h-6 cursor-pointer items-center gap-2 px-3 text-small text-muted hover:bg-hover" onClick={() => ui.set({ bottomTab: 'sources', bottomOpen: true })}>
              {src ? <Radio size={12} className={s.enabled ? 'text-warn' : 'text-faint'} /> : <ScanLine size={12} className={s.enabled ? 'text-ok' : 'text-faint'} />}
              <span className="truncate">{s.name}</span>
            </div>
          ))}
        </Section>
      )}

      {show('variables') && (
        <Section title={`${t('sb.variables')} (${project.optimization.variables.length})`} defaultOpen={project.optimization.variables.length > 0}>
          {project.optimization.variables.length === 0 && (
            <div className="px-3 text-small leading-snug text-faint">
              {t('sb.noVariables')}{' '}
              <Button variant="link" onClick={() => ui.openDialog('optWizard')}>
                {t('ow.title')}…
              </Button>
            </div>
          )}
          {project.optimization.variables.map((v, k) => {
            const i = sys.surfaces.findIndex((s) => s.id === v.surface_id)
            return (
              <div key={k} className="flex h-6 cursor-pointer items-center gap-2 px-3 text-small text-muted hover:bg-hover" onClick={() => i >= 0 && select(i)}>
                <VarIcon size={12} className={v.enabled ? 'text-accent' : 'text-faint'} />
                <span>
                  S{i} {paramLabel(v.parameter, t)}
                  {v.configuration !== undefined && v.configuration !== null ? ` · C${v.configuration + 1}` : ''}
                </span>
                <span className="ml-auto num text-caption text-faint">
                  [{v.min ?? '−∞'}, {v.max ?? '∞'}]
                </span>
              </div>
            )
          })}
        </Section>
      )}

      {show('revisions') && (
        <Section title={`${t('sb.revisions')} (${project.revisions.length})`} defaultOpen={false}>
          {project.revisions.length === 0 && (
            <div className="px-3 text-small leading-snug text-faint">
              {t('sb.noRevisions')}{' '}
              <Button variant="link" onClick={() => void saveProject()}>
                {t('sb.saveNow')}
              </Button>
            </div>
          )}
          {[...project.revisions].reverse().map((r) => (
            <div key={r.id} className="group flex h-6 items-center gap-2 px-3 text-small text-muted hover:bg-hover">
              <History size={12} className="shrink-0 text-faint" />
              <span className="truncate" title={r.label}>
                {r.label}
              </span>
              <span className="ml-auto shrink-0 text-caption text-faint">{timeAgo(r.timestamp)}</span>
              <Button variant="link" className="hidden group-hover:inline-flex" onClick={() => st().restoreRevision(r.id)}>
                {t('sb.restore')}
              </Button>
              <IconButton size="sm" tone="danger" title={t('c.delete')} className="hidden group-hover:inline-flex" onClick={() => st().deleteRevision(r.id)}>
                <Trash2 size={12} />
              </IconButton>
            </div>
          ))}
        </Section>
      )}

      {show('saved') && (
        <Section title={`${t('sb.savedAnalyses')} (${saved.length})`} defaultOpen={false}>
          {saved.length === 0 && <div className="px-3 text-small text-faint">{t('sb.noSaved')}</div>}
          {[...saved].reverse().map((a) => (
            <div key={a.id} className="group flex h-6 cursor-pointer items-center gap-2 px-3 text-small text-muted hover:bg-hover" onClick={() => ui.openDialog('about', { savedAnalysis: a.id })}>
              <Pin size={12} className="shrink-0 text-faint" />
              <span className="truncate">{a.label}</span>
              <IconButton
                size="sm"
                tone="danger"
                title={t('c.delete')}
                className="ml-auto hidden group-hover:inline-flex"
                onClick={(e) => {
                  e.stopPropagation()
                  st().updateProject((p) => {
                    p.analysis_settings.saved = (p.analysis_settings.saved ?? []).filter((x) => x.id !== a.id)
                  }, 'Delete saved analysis')
                }}
              >
                <Trash2 size={12} />
              </IconButton>
            </div>
          ))}
        </Section>
      )}

      {show('optRuns') && (
        <Section title={`${t('sb.optRuns')} (${project.saved_optimizations.length})`} defaultOpen={false}>
          {[...project.saved_optimizations].reverse().map((o) => (
            <div key={o.id} className="flex h-6 items-center gap-2 px-3 text-small text-muted">
              <TrendingDown size={12} className="text-ok" />
              <span className="num">
                {fmt(o.initial_merit, 4)} → {fmt(o.final_merit, 4)}
              </span>
              <span className="ml-auto text-caption text-faint">
                {o.algorithm} · {timeAgo(o.timestamp)}
              </span>
            </div>
          ))}
        </Section>
      )}
    </div>
  )
}
