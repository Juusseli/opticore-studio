import { Lightbulb, Sparkles, Square } from 'lucide-react'
import { useMemo } from 'react'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { DATA, SERIES } from '../../lib/palette'
import type { AberrationClass, AdvisorDiagnosis, AdvisorFinding, AdvisorSuggestion, OpticalSystem } from '../../lib/types'
import { advKey, applySuggestion, isAdvRunning, useAdvisorStore } from '../../store/advisorStore'
import { useProjectStore } from '../../store/projectStore'
import { Badge, Button, Tooltip } from '../common/ui'
import { cx } from '../common/uiUtils'
import { describeMove, fieldLabel, findingText, pct } from './advisorText'
import { AnalysisFrame } from './AnalysisFrame'
import { useAnalysis } from './useAnalysis'

const BAR_CLASSES = ['defocus', 'spherical', 'coma', 'astigmatism', 'trefoil', 'higher', 'residual'] as const
/** Bar colours of the aberration classes: defocus (a focus error, not blur) in grey, the unfitted residual as a fill. */
const CLASS_COLOR: Record<(typeof BAR_CLASSES)[number], string> = {
  defocus: SERIES[7],
  spherical: SERIES[0],
  coma: SERIES[1],
  astigmatism: SERIES[2],
  trefoil: SERIES[3],
  higher: SERIES[4],
  residual: DATA.reference,
}
/** Which third-order sum names the surfaces behind a finding. */
const CAUSE_OF: Partial<Record<AberrationClass, 'spherical' | 'coma' | 'astigmatism'>> = { spherical: 'spherical', coma: 'coma', astigmatism: 'astigmatism' }

function causeKey(f: AdvisorFinding): keyof AdvisorDiagnosis['attribution'] | null {
  if (f.kind === 'aberration') return CAUSE_OF[f.class] ?? null
  if (f.kind === 'field_curvature' || f.kind === 'axial_colour' || f.kind === 'lateral_colour' || f.kind === 'distortion') return f.kind
  return null
}

function SurfaceChip({ surface, share }: { surface: number; share: number }) {
  const t = useT()
  const select = useProjectStore((s) => s.select)
  const hint = t('adv.chipHint', { s: surface, p: pct(share) })
  return (
    <Tooltip text={hint}>
      <button type="button" aria-label={hint} className="num inline-flex h-5 items-center gap-1 rounded bg-hover px-1.5 text-small text-fg hover:bg-accent-soft hover:text-accent" onClick={() => select(surface)}>
        S{surface}
        <span className="text-faint">{fmt(share * 100, 2)} %</span>
      </button>
    </Tooltip>
  )
}

function Findings({ d, system }: { d: AdvisorDiagnosis; system: OpticalSystem }) {
  const t = useT()
  if (!d.findings.length) return <div className="px-3 py-1 text-small text-muted">{t('adv.noFindings')}</div>
  return (
    <ul aria-label={t('adv.limits')}>
      {d.findings.map((f, i) => {
        const ck = causeKey(f)
        const cause = ck ? d.attribution[ck] : undefined
        return (
          <li key={i} className="flex gap-2 px-3 py-1">
            <span className={cx('mt-1.5 h-2 w-2 shrink-0 rounded-full', f.kind === 'diffraction_limited' ? 'bg-ok' : 'bg-warn')} />
            <div className="min-w-0 flex-1">
              <div className="text-body leading-snug text-fg">{findingText(t, f, system)}</div>
              {cause && cause.surfaces.length > 0 && (
                <div className="mt-0.5 flex flex-wrap items-center gap-1 text-small text-muted">
                  <Tooltip text={d.attribution_note}>
                    <span>{t('adv.causes')}</span>
                  </Tooltip>
                  {cause.surfaces.map((c) => (
                    <SurfaceChip key={c.surface} surface={c.surface} share={c.share} />
                  ))}
                </div>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function FieldTable({ d, system }: { d: AdvisorDiagnosis; system: OpticalSystem }) {
  const t = useT()
  return (
    <>
      <table className="w-full text-small">
        <thead>
          <tr className="text-faint">
            <th className="px-3 text-left font-normal">{t('c.field')}</th>
            <th className="text-left font-normal">{t('adv.col.classes')}</th>
            <th className="px-2 text-right font-normal">{t('adv.col.rms')}</th>
            <th className="pr-3 text-right font-normal">{t('adv.col.spot')}</th>
          </tr>
        </thead>
        <tbody>
          {d.fields.map((f) => (
            <tr key={f.field} className="h-6">
              <td className="num px-3 whitespace-nowrap">{fieldLabel(system, f.field)}</td>
              <td className="w-full">
                {f.classes ? (
                  <div className="flex h-3 w-full min-w-24 overflow-hidden rounded bg-hover" role="img" aria-label={BAR_CLASSES.map((c) => `${t('adv.c.' + c)} ${pct(f.classes![c].share)} %`).join(', ')}>
                    {BAR_CLASSES.map((c) => (
                      <div key={c} className="h-full" title={`${t('adv.c.' + c)}: ${pct(f.classes![c].share)} % · ${fmt(f.classes![c].rms_waves, 3)} ${t('adv.waves')}`} style={{ width: `${f.classes![c].share * 100}%`, background: CLASS_COLOR[c] }} />
                    ))}
                  </div>
                ) : (
                  <span className="text-faint" title={f.note}>
                    {t('adv.noWavefront')}
                  </span>
                )}
              </td>
              <td className="num px-2 text-right whitespace-nowrap">
                {f.diffraction_limited && (
                  <span className="mr-1">
                    <Badge tone="ok">{t('adv.dl')}</Badge>
                  </span>
                )}
                {fmt(f.rms_waves, 3)}
              </td>
              <td className="num pr-3 text-right">{fmt(f.rms_spot_um, 3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 pt-1.5 text-caption text-muted">
        {BAR_CLASSES.map((c) => (
          <span key={c} className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded" style={{ background: CLASS_COLOR[c] }} />
            {t('adv.c.' + c)}
          </span>
        ))}
      </div>
      <div className="px-3 pt-1 text-caption text-faint">{t('adv.airy', { a: fmt(d.airy_radius_um, 3), w: fmt(d.wavelength_um, 4) })}</div>
    </>
  )
}

function PatchLine({ sg, system }: { sg: AdvisorSuggestion; system: OpticalSystem }) {
  const t = useT()
  const show = (key: string, v: unknown) => (v === null || v === undefined ? (key === 'radius' ? '∞' : '—') : typeof v === 'number' ? fmt(v, 6) : String(v))
  return (
    <div className="num mt-0.5 flex flex-wrap gap-x-3 text-small text-muted">
      {sg.patch.map((p, i) => {
        const idx = system.surfaces.findIndex((s) => s.id === p.surface_id)
        const cur = idx >= 0 ? (system.surfaces[idx] as unknown as Record<string, unknown>)[p.key] : undefined
        return (
          <span key={i}>
            S{idx} {t('adv.p.' + p.key)} {show(p.key, cur)} → <span className="text-fg">{show(p.key, p.value)}</span>
          </span>
        )
      })}
    </div>
  )
}

function SuggestionItem({ sg, best, system }: { sg: AdvisorSuggestion; best: number; system: OpticalSystem }) {
  const t = useT()
  const text = describeMove(t, sg)
  const after = sg.rms_spot_after_um
  const apply = () => {
    if (applySuggestion(sg, t('adv.undo', { m: text }))) void useAdvisorStore.getState().start()
  }
  return (
    <li className="border-t border-line px-3 py-2">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 text-body text-fg">{text}</span>
        <Tooltip text={t('adv.gainHint', { a: fmt(sg.merit_before, 5), b: fmt(sg.merit_after, 5) })}>
          <span className="num text-small font-semibold whitespace-nowrap text-ok">−{pct(sg.gain)} %</span>
        </Tooltip>
        <Tooltip text={t('adv.applyHint')}>
          <Button size="sm" variant="subtle" onClick={apply} aria-label={`${t('adv.apply')}: ${text}`}>
            {t('adv.apply')}
          </Button>
        </Tooltip>
      </div>
      <div className="mt-1 h-1 w-full overflow-hidden rounded bg-hover">
        <div className="h-full bg-ok/70" style={{ width: `${(100 * sg.gain) / Math.max(best, 1e-12)}%` }} />
      </div>
      <PatchLine sg={sg} system={system} />
      {after && (
        <div className="num mt-0.5 flex flex-wrap gap-x-3 text-small text-muted">
          <span>{t('adv.spot')}</span>
          {sg.rms_spot_before_um.map((b, i) => (
            <span key={i}>
              F{i + 1} {fmt(b, 3)} → <span className="text-fg">{fmt(after[i], 3)}</span>
            </span>
          ))}
        </div>
      )}
    </li>
  )
}

function Suggestions({ system }: { system: OpticalSystem }) {
  const t = useT()
  const project = useProjectStore((s) => s.project)
  const key = useMemo(() => advKey(project), [project])
  const st = useAdvisorStore()
  const running = isAdvRunning(st)
  const result = st.results[key]
  const prog = st.job?.progress
  const best = result?.suggestions[0]?.gain ?? 0
  return (
    <section aria-label={t('adv.suggestions')}>
      <div className="flex items-center gap-2 px-3 pt-3 pb-1">
        <span className="flex-1 text-small font-semibold tracking-wide text-muted uppercase">{t('adv.suggestions')}</span>
        {running ? (
          <Button size="sm" onClick={() => void st.cancel()} aria-label={t('c.cancel')} title={t('adv.cancelHint')}>
            <Square size={12} /> {t('c.cancel')}
          </Button>
        ) : (
          <Tooltip text={t('adv.findHint')}>
            <Button size="sm" variant="primary" onClick={() => void st.start()}>
              <Sparkles size={12} /> {t(result ? 'adv.again' : 'adv.find')}
            </Button>
          </Tooltip>
        )}
      </div>
      {running && (
        <div className="px-3 py-1" role="status">
          <div className="text-small text-muted">{t('adv.running', { d: prog?.done ?? 0, n: prog?.total || '…' })}</div>
          <div className="mt-1 h-1 w-full overflow-hidden rounded bg-hover">
            <div className="h-full bg-accent transition-[width]" style={{ width: `${prog && prog.total ? (100 * prog.done) / prog.total : 2}%` }} />
          </div>
        </div>
      )}
      {st.error && <div className="px-3 py-1 text-small text-danger">{st.error}</div>}
      {result ? (
        <>
          <div className="px-3 pb-1 text-small text-muted">
            {t(result.merit_kind === 'project' ? 'adv.meritProject' : 'adv.meritDefault', { m: fmt(result.merit, 5) })} · {t('adv.moves', { n: result.moves_tried, e: result.evaluations })}
            {result.status === 'cancelled' && <span className="text-warn"> · {t('adv.cancelled')}</span>}
          </div>
          {result.suggestions.length ? (
            <ul>
              {result.suggestions.map((sg, i) => (
                <SuggestionItem key={i} sg={sg} best={best} system={system} />
              ))}
            </ul>
          ) : (
            <div className="px-3 py-2 text-body text-muted">{t('adv.none')}</div>
          )}
          <div className="px-3 pt-1 text-caption leading-relaxed text-faint">{result.method}</div>
        </>
      ) : (
        !running && (
          <div className="flex gap-2 px-3 py-2 text-small leading-relaxed text-muted">
            <Lightbulb size={14} className="mt-0.5 shrink-0 text-accent" />
            <span>{t('adv.findHint')}</span>
          </div>
        )
      )}
    </section>
  )
}

/** Design advisor: what limits the image, and ranked, verified changes (engine: analysis/advisor.py). */
export function AdvisorView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const { data, error, loading, ms, refresh } = useAnalysis<AdvisorDiagnosis>('advisor', {})
  return (
    <AnalysisFrame kind="advisor" title={t('view.advisor')} loading={loading} error={error} hasData={!!data} ms={ms} method={data?.method} onRefresh={refresh} settings={{}} result={data}>
      {data && (
        <div className="h-full overflow-auto">
          <div className="grid grid-cols-1 @3xl:grid-cols-2 @3xl:divide-x @3xl:divide-line">
            <div className="min-w-0 pb-3">
              <div className="px-3 pt-3 pb-1 text-small font-semibold tracking-wide text-muted uppercase">{t('adv.limits')}</div>
              <Findings d={data} system={system} />
              <div className="px-3 pt-3 pb-1 text-small font-semibold tracking-wide text-muted uppercase">{t('adv.perField')}</div>
              <FieldTable d={data} system={system} />
            </div>
            <div className="min-w-0 border-t border-line pb-3 @3xl:border-t-0">
              <Suggestions system={system} />
            </div>
          </div>
        </div>
      )}
    </AnalysisFrame>
  )
}
