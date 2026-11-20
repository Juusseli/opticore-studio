import { Crosshair, Lightbulb } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { quickFocus } from '../../actions'
import { api } from '../../lib/api'
import { canonicalJson } from '../../lib/canonical'
import { type CheckItem, type CheckStatus, SPEC_IDS, type SpecId, specPass, type Specs, specValues, systemChecklist } from '../../lib/checklist'
import { effectiveEnvironment } from '../../lib/environment'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import type { AdvisorDiagnosis, Diagnostic, ElementsResult, FocusResult } from '../../lib/types'
import { systemBody, useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { useAnalysis } from '../views/useAnalysis'
import { findingShort } from '../views/advisorText'
import { NumberField, Section, Tooltip } from '../common/ui'
import { cx } from '../common/uiUtils'

const GLYPH: Record<CheckStatus, { text: string; cls: string }> = {
  ok: { text: '✓', cls: 'bg-ok/15 text-ok' },
  warn: { text: '!', cls: 'bg-warn/15 text-warn' },
  error: { text: '!', cls: 'bg-danger/15 text-danger' },
  none: { text: '–', cls: 'bg-hover text-muted' },
}

export function StatusGlyph({ status, label }: { status: CheckStatus; label: string }) {
  const g = GLYPH[status]
  return (
    <span role="img" aria-label={label} className={cx('inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-caption font-bold', g.cls)}>
      {g.text}
    </span>
  )
}

/** Debounce (ms) of the card's analyses: longer than the views', so they do not compete with a value being dragged. */
const SECONDARY_DELAY = 600

/** Current merit function value, evaluated by the engine only when it is needed (an applied optimisation exists). */
function useCurrentMerit(enabled: boolean): number | null {
  const project = useProjectStore((s) => s.project)
  const online = useEngineStore((s) => s.backend === 'online')
  const key = useMemo(() => (enabled ? canonicalJson({ s: project.system, m: project.custom_materials, o: project.optimization }) : ''), [enabled, project.system, project.custom_materials, project.optimization])
  const [res, setRes] = useState<{ key: string; merit: number } | null>(null)
  useEffect(() => {
    if (!enabled || !online) return
    const ctrl = new AbortController()
    const h = window.setTimeout(() => {
      const p = useProjectStore.getState().project
      api
        .merit({ ...systemBody(p.system, p.custom_materials), sources: p.sources, detectors: p.detectors, optimization: p.optimization }, ctrl.signal)
        .then((r) => setRes({ key, merit: r.merit }))
        .catch(() => undefined)
    }, 500)
    return () => {
      window.clearTimeout(h)
      ctrl.abort()
    }
  }, [key, enabled, online])
  return res && res.key === key ? res.merit : null
}

/** The System card at the top of the sidebar: setup checklist and the optional specification table. */
export function SystemCard() {
  const t = useT()
  const project = useProjectStore((s) => s.project)
  const select = useProjectStore((s) => s.select)
  const evaluation = useEngineStore((s) => s.evaluation)
  const evalError = useEngineStore((s) => s.evalError)
  const online = useEngineStore((s) => s.backend === 'online')
  const setUi = useUiStore((s) => s.set)
  // secondary read-outs: they wait until a drag in the editors pauses (SECONDARY_DELAY)
  const focus = useAnalysis<FocusResult>('focus', {}, SECONDARY_DELAY)
  const elements = useAnalysis<ElementsResult>('elements', { tolerancing: project.tolerancing }, SECONDARY_DELAY).data
  const sys = project.system
  const opt = project.optimization
  const runs = project.saved_optimizations
  const needMerit = runs.some((r) => r.applied) && opt.variables.some((v) => v.enabled) && opt.operands.some((o) => o.enabled)
  const merit = useCurrentMerit(needMerit)
  const env = effectiveEnvironment(sys)
  const items = systemChecklist({
    evaluation,
    evalError: evalError?.message ?? null,
    errorDiagnostics: (Array.isArray(evalError?.details) ? (evalError!.details as Diagnostic[]) : []).filter((d) => d && typeof d === 'object' && 'code' in d),
    aperture: sys.aperture,
    fields: sys.fields.length,
    wavelengths: sys.wavelengths.map((w) => w.value),
    surfaces: sys.surfaces.length - 2,
    focus: focus.data,
    optimization: opt,
    savedOptimizations: runs,
    merit,
    environment: env.enabled ? { temperature: env.temperature, pressure: env.pressure } : null,
    glass: elements ? { mass: elements.total_mass_g, cost: elements.relative_cost } : null,
  })
  const n = sys.surfaces.length

  const open = (it: CheckItem) => {
    if (it.id === 'aperture' || it.id === 'fields' || it.id === 'wavelengths' || it.id === 'environment') setUi({ bottomTab: 'system', bottomOpen: true })
    else if (it.id === 'surfaces') {
      const s = it.diagnostics?.find((d) => d.surface !== null)?.surface
      if (s !== undefined && s !== null) select(s)
      setUi({ bottomTab: it.diagnostics?.length ? 'messages' : 'lde', bottomOpen: true })
    } else if (it.id === 'focus') {
      // the image distance is the thickness of the surface before the image
      select(Math.max(0, n - 2))
      setUi({ bottomTab: 'lde', bottomOpen: true })
    } else if (it.id === 'merit') {
      // nothing set up yet: the wizard sets up both at once
      if (!opt.variables.length && !opt.operands.length) useUiStore.getState().openDialog('optWizard')
      else setUi({ bottomTab: opt.variables.length && !opt.operands.length ? 'merit' : 'optimization', bottomOpen: true })
    }
    else setUi({ bottomTab: 'optimization', bottomOpen: true })
  }
  const detail = (it: CheckItem) => {
    const v = { ...it.vars }
    if (it.id === 'focus' && typeof v.d === 'number') v.d = `${v.d > 0 ? '+' : ''}${fmt(v.d, 3)}`
    if (it.id === 'optimised' && typeof v.mf === 'number') v.mf = fmt(v.mf, 4)
    if (it.id === 'surfaces' && typeof v.g === 'number') v.g = fmt(v.g, 3)
    if (it.id === 'surfaces' && typeof v.c === 'number') v.c = fmt(v.c, 3)
    return t(it.detail, v)
  }

  return (
    <Section title={t('chk.title')}>
      <ul className="px-1.5" aria-label={t('chk.title')}>
        {items.map((it) => {
          const label = t('chk.l.' + it.id)
          const why = it.diagnostics?.length ? it.diagnostics.map((d) => d.message).join('\n') : t('chk.h.' + it.id)
          return (
            <li key={it.id} className="flex items-center">
              <Tooltip text={<span className="whitespace-pre-line">{why}</span>} side="right">
                <button className="flex h-6 w-[calc(100%)] min-w-0 items-center gap-2 rounded px-1.5 text-left text-body hover:bg-hover" onClick={() => open(it)} aria-label={`${label}: ${detail(it)}`}>
                  <StatusGlyph status={it.status} label={t('chk.s.' + it.status)} />
                  <span className="truncate">{label}</span>
                  <span className={cx('ml-auto truncate pl-2 text-small', it.status === 'warn' ? 'text-warn' : it.status === 'error' ? 'text-danger' : 'text-faint')}>{detail(it)}</span>
                </button>
              </Tooltip>
              {it.id === 'focus' && it.status === 'warn' && (
                <Tooltip text={t('tb.focusHint')}>
                  <button className="ml-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded text-accent hover:bg-hover disabled:opacity-40" aria-label={t('tb.focus')} disabled={!online} onClick={() => void quickFocus()}>
                    <Crosshair size={12} />
                  </button>
                </Tooltip>
              )}
            </li>
          )
        })}
        <AdvisorLine />
      </ul>
      <SpecTable focus={focus.data} />
    </Section>
  )
}

/** What limits the image (the design advisor's diagnosis); opens the Advisor view. */
function AdvisorLine() {
  const t = useT()
  const d = useAnalysis<AdvisorDiagnosis>('advisor', {}, SECONDARY_DELAY).data
  if (!d || !d.findings.length) return null
  const names = [...new Set(d.findings.map((f) => findingShort(t, f)))]
  const text = names.slice(0, 2).join(', ') + (names.length > 2 ? ` +${names.length - 2}` : '')
  const label = t('adv.card')
  return (
    <li className="flex items-center">
      <Tooltip text={t('adv.cardHint')} side="right">
        <button className="flex h-6 w-[calc(100%)] min-w-0 items-center gap-2 rounded px-1.5 text-left text-body hover:bg-hover" onClick={() => useUiStore.getState().showView('advisor')} aria-label={`${label}: ${names.join(', ')}`}>
          <Lightbulb size={14} className="shrink-0 text-accent" />
          <span className="truncate">{label}</span>
          <span className="ml-auto truncate pl-2 text-small text-faint">{text}</span>
        </button>
      </Tooltip>
    </li>
  )
}

const NO_SPECS: Specs = {}

function SpecTable({ focus }: { focus: FocusResult | null }) {
  const t = useT()
  // select the stored object itself: a selector that returns a new {} every time would re-render forever
  const specs = (useProjectStore((s) => s.project.analysis_settings.specs) as Specs | undefined) ?? NO_SPECS
  const primary = useProjectStore((s) => s.project.system.primary_wavelength)
  const updateProject = useProjectStore((s) => s.updateProject)
  const evaluation = useEngineStore((s) => s.evaluation)
  const [open, setOpen] = useState(Object.keys(specs).length > 0)
  const values = specValues(evaluation?.paraxial[String(primary)], focus)
  const setSpec = (id: SpecId, v: Specs[SpecId] | undefined) =>
    updateProject((p) => {
      const next: Specs = { ...((p.analysis_settings.specs ?? {}) as Specs) }
      if (v) (next as Record<string, unknown>)[id] = v
      else delete next[id]
      p.analysis_settings.specs = next
    }, t('spec.edit'))
  return (
    <div className="mt-1 px-3">
      <button className="flex items-center gap-1 text-small text-muted hover:text-fg" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className={cx('inline-block transition-transform', open && 'rotate-90')}>›</span>
        {t('spec.title')}
        {Object.keys(specs).length > 0 && <span className="text-faint">({Object.keys(specs).length})</span>}
      </button>
      {open && (
        <table className="mt-1 w-full text-small">
          <thead>
            <tr className="text-faint">
              <th className="text-left font-normal" />
              <th className="text-left font-normal">{t('spec.target')}</th>
              <th className="text-right font-normal">{t('spec.current')}</th>
              <th className="w-5" />
            </tr>
          </thead>
          <tbody>
            {SPEC_IDS.map((id) => {
              const v = values[id]
              const pass = specPass(id, specs, v)
              const s = specs[id]
              const tolerance = id === 'efl' || id === 'fnum'
              return (
                <tr key={id} className="h-6">
                  <td className="pr-1 whitespace-nowrap text-muted">{t('spec.' + id)}</td>
                  <td>
                    <span className="flex items-center gap-0.5">
                      {!tolerance && <span className="text-faint">≤</span>}
                      <NumberField
                        optional
                        className="h-5 w-[52px] px-1 text-small"
                        ariaLabel={`${t('spec.' + id)} ${t('spec.target')}`}
                        placeholder="—"
                        value={tolerance ? ((s as { target: number } | undefined)?.target ?? null) : ((s as { max: number } | undefined)?.max ?? null)}
                        onCommit={(x) => setSpec(id, x === null ? undefined : tolerance ? { target: x, tol: (s as { tol: number } | undefined)?.tol ?? (id === 'efl' ? Math.abs(x) * 0.01 : 0.1) } : { max: x })}
                      />
                      {tolerance && s && (
                        <>
                          <span className="text-faint">±</span>
                          <NumberField className="h-5 w-[40px] px-1 text-small" ariaLabel={`${t('spec.' + id)} ${t('spec.tol')}`} value={(s as { tol: number }).tol} min={0} onCommit={(x) => setSpec(id, { target: (s as { target: number }).target, tol: x ?? 0 })} />
                        </>
                      )}
                    </span>
                  </td>
                  <td className="num text-right">{v === null ? '—' : fmt(v, id === 'fnum' ? 3 : 5)}</td>
                  <td className="pl-1">{pass !== null && <StatusGlyph status={pass ? 'ok' : 'error'} label={t(pass ? 'spec.pass' : 'spec.fail')} />}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
