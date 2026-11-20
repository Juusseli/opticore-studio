import { ChartLine, Check, Pause, Play, Square, Wand2, X } from 'lucide-react'
import { useState } from 'react'
import { saveProject } from '../../actions'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { applyMaterials, applyVariableValues, newId, nowIso } from '../../lib/project'
import { paramLabel } from '../../lib/paramLabels'
import { useEngineStore } from '../../store/engineStore'
import { isRunning, useOptStore } from '../../store/optStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { Plot } from '../common/Plot'
import { Badge, Button, Checkbox, IconButton, NumberField, Select, Spinner } from '../common/ui'
import { VariablesTable } from './MeritEditor'
import { DATA } from '../../lib/palette'
import { compareRows, flagged, goalChanges } from '../../lib/optCompare'
import type { ConstraintResult, DesignComparison, FieldProfile, OptimizationResult } from '../../lib/types'
import { limitsMet, priceLabel } from '../../lib/constraints'
import { OPERAND_INFO } from './operands'
import { TradeoffDialog } from './TradeoffDialog'

export function OptimizationPanel() {
  const t = useT()
  const project = useProjectStore((s) => s.project)
  const setOpt = useProjectStore((s) => s.setOptimization)
  const replaceSystem = useProjectStore((s) => s.replaceSystem)
  const updateProject = useProjectStore((s) => s.updateProject)
  const backend = useEngineStore((s) => s.backend)
  const toast = useUiStore((s) => s.toast)
  const { job, result, base, compare, compareError, error, start, pause, cancel, discard, showing, show } = useOptStore()
  const running = useOptStore(isRunning)
  const opt = project.optimization
  const enabledVars = opt.variables.filter((v) => v.enabled)

  const apply = () => {
    if (!result) return
    if (useOptStore.getState().projectId !== project.id) {
      toast('error', t('c.staleProject'))
      return
    }
    // apply only the optimised variables to the *current* design, so edits made
    // while the optimisation ran are kept
    const current = useProjectStore.getState().project.system
    const missing = result.variables.filter((v) => !current.surfaces.some((s) => s.id === v.surface_id))
    if (missing.length) {
      toast('error', 'Some optimised surfaces no longer exist; the result cannot be applied')
      return
    }
    const next = applyMaterials(applyVariableValues(current, result.variables, result.variables.map((v) => v.final)), result.materials)
    replaceSystem(next, 'Apply optimization', `Before optimization ${new Date().toLocaleString()}`)
    updateProject((p) => {
      p.saved_optimizations.push({ id: newId(), timestamp: nowIso(), algorithm: result.algorithm, initial_merit: result.initial_merit, final_merit: result.final_merit, evaluations: result.evaluations, status: result.status, variables: result.variables, applied: true })
      if (p.saved_optimizations.length > 50) p.saved_optimizations.splice(0, p.saved_optimizations.length - 50)
    }, 'Record optimization run')
    toast('success', t('opt.applied'))
    discard()
  }

  const saveAsNew = async () => {
    if (!result) return
    updateProject((p) => {
      p.id = newId()
      p.metadata.name = `${p.metadata.name} (optimized)`
      p.metadata.created = nowIso()
    }, 'Save optimized as new project')
    replaceSystem(applyMaterials(applyVariableValues(useProjectStore.getState().project.system, result.variables, result.variables.map((v) => v.final)), result.materials), 'Apply optimization (new project)')
    await saveProject()
    discard()
  }

  const history = job?.history ?? result?.history ?? []
  // exact limits: met by the best design so far (running) or by the result
  const limits = job && job.constraints ? { met: job.constraints - (job.unmet ?? 0), total: job.constraints } : limitsMet(result?.constraints)

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(380px,1fr)_minmax(420px,1.25fr)] gap-px bg-line">
      {/* left: configuration + variables */}
      <div className="flex min-h-0 flex-col bg-panel">
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-2">
          <span className="text-small text-muted">{t('opt.algorithm')}</span>
          <Select className="h-6 max-w-[300px] min-w-[140px] flex-1 text-small" ariaLabel={t('opt.algorithm')} value={opt.algorithm} options={[{ value: 'local', label: t('opt.local') }, { value: 'global', label: t('opt.global') }, { value: 'multistart', label: t('opt.multistart') }]} onChange={(v) => setOpt({ ...opt, algorithm: v }, 'Optimization algorithm')} />
          <span className="text-small text-muted">{t('opt.maxEval')}</span>
          <NumberField className="h-6 w-20 shrink-0" ariaLabel={t('opt.maxEval')} value={opt.max_evaluations} integer min={10} max={200000} onCommit={(v) => setOpt({ ...opt, max_evaluations: v ?? 2000 }, 'Max evaluations')} />
          {opt.algorithm === 'multistart' && (
            <>
              <span className="text-small text-muted">{t('opt.runs')}</span>
              <NumberField className="h-6 w-14 shrink-0" ariaLabel={t('opt.runs')} value={opt.multistart_runs} integer min={2} max={64} onCommit={(v) => setOpt({ ...opt, multistart_runs: v ?? 6 }, 'Multistart runs')} />
            </>
          )}
        </div>
        <div className="flex items-center gap-1.5 border-b border-line p-2">
          <Button onClick={() => useUiStore.getState().openDialog('optWizard')} disabled={running} title={t('ow.hint')}>
            <Wand2 size={14} /> {t('ow.short')}
          </Button>
          {!running ? (
            <Button variant="primary" onClick={start} disabled={backend !== 'online' || !enabledVars.length || !opt.operands.some((o) => o.enabled)}>
              <Play size={14} /> {t('opt.run')}
            </Button>
          ) : (
            <>
              {job?.state === 'paused' ? (
                <Button onClick={() => pause(false)}>
                  <Play size={14} /> {t('opt.resume')}
                </Button>
              ) : (
                <Button onClick={() => pause(true)}>
                  <Pause size={14} /> {t('opt.pause')}
                </Button>
              )}
              <Button variant="danger" onClick={cancel}>
                <Square size={12} /> {t('opt.cancel')}
              </Button>
              <Spinner />
            </>
          )}
          {job && <Badge tone={job.state === 'finished' ? 'ok' : job.state === 'failed' ? 'danger' : 'accent'}>{t(`opt.job.${job.state}`)}</Badge>}
          {error && <span className="truncate text-small text-danger">{error}</span>}
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          <div className="px-3 pt-2 pb-1 text-small font-semibold tracking-wide text-muted uppercase">
            {t('opt.variables')} ({enabledVars.length})
          </div>
          {opt.variables.length ? (
            <VariablesTable />
          ) : (
            <div className="flex flex-col items-start gap-2 px-3 pb-3 text-muted">
              <div>{t('opt.noVarsEmpty')}</div>
              <div className="flex gap-2">
                <Button size="sm" variant="primary" onClick={() => useUiStore.getState().openDialog('optWizard')}>
                  <Wand2 size={12} /> {t('ow.title')}…
                </Button>
                <Button size="sm" onClick={() => useUiStore.getState().set({ bottomTab: 'lde', bottomOpen: true })}>
                  {t('bt.lde')}
                </Button>
                <Button size="sm" onClick={() => useUiStore.getState().set({ bottomTab: 'merit', bottomOpen: true })}>
                  {t('bt.merit')}
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* right: progress + results */}
      <div className="flex min-h-0 flex-col bg-panel">
        <div className={`grid ${limits ? 'grid-cols-6' : 'grid-cols-5'} gap-px border-b border-line bg-line text-center`}>
          {[
            [t('opt.initial'), job?.initial_merit ?? result?.initial_merit],
            [t('opt.current'), job?.current_merit],
            [t('opt.best'), job?.best_merit ?? result?.final_merit],
            [t('opt.evaluations'), job?.evaluations ?? result?.evaluations],
            [t('opt.elapsed'), job?.elapsed_s ?? result?.elapsed_s],
          ].map(([label, v], k) => (
            <div key={k} className="bg-panel px-2 py-1.5">
              <div className="text-caption text-muted">{label as string}</div>
              <div className="num text-title font-semibold">{k === 4 ? (v !== undefined && v !== null ? `${(v as number).toFixed(1)} s` : '—') : k === 3 ? (v ?? '—') : fmt((v as number) ?? null, 6)}</div>
            </div>
          ))}
          {limits && (
            <div className="bg-panel px-2 py-1.5" title={t('mf.limitsHint')}>
              <div className="text-caption text-muted">{t('opt.limitsProgress')}</div>
              <div className={`num text-title font-semibold ${limits.met === limits.total ? 'text-ok' : 'text-warn'}`}>
                {limits.met}/{limits.total}
              </div>
            </div>
          )}
        </div>
        {result ? (
          <div className="min-h-0 flex-1 overflow-auto">
            <div className="flex flex-wrap items-center gap-2 border-b border-line p-2">
              <span title={result.message}>
                <Badge tone={result.status === 'converged' ? 'ok' : result.status === 'error' || result.status === 'infeasible' ? 'danger' : 'warn'}>{t(`opt.status.${result.status}`)}</Badge>
              </span>
              <span className="num text-body whitespace-nowrap" title={t('opt.mfHint')}>
                MF {fmt(result.initial_merit, 6)} → <b>{fmt(result.final_merit, 6)}</b> ({t(result.improvement_percent >= 0 ? 'opt.better' : 'opt.worse', { p: Math.abs(result.improvement_percent).toFixed(1) })})
              </span>
              {goalChanges(result).map((g, k) => (
                <span key={k} className={`num text-body whitespace-nowrap ${g.better ? 'text-ok' : 'text-warn'}`} title={t(`op.${g.type}.desc`)}>
                  {t(`op.${g.type}`)} {fmt(g.before, 4)} → <b>{fmt(g.after, 4)}</b> {g.unit === 'um' ? 'µm' : g.unit === 'waves' ? t('an.waves') : g.unit}
                </span>
              ))}
              <div className="flex-1" />
              <span title={t('opt.showHint')}>
                <Checkbox checked={showing === 'result'} onChange={(v) => show(v ? 'result' : 'original')} label={<span className="text-small text-muted">{t('opt.showInViews')}</span>} />
              </span>
              <div className="flex flex-wrap gap-1.5">
              <Button variant="primary" size="sm" onClick={apply}>
                <Check size={12} /> {t('opt.apply')}
              </Button>
              <Button size="sm" onClick={saveAsNew}>
                {t('opt.saveNew')}
              </Button>
              <Button size="sm" variant="ghost" onClick={discard}>
                <X size={12} /> {t('opt.discard')}
              </Button>
              </div>
            </div>
            <div className="px-3 py-1 text-small text-faint">
              {result.message}
              {result.parallel && <span title={t('opt.parallelHint')}> · {t('opt.parallel', { w: result.parallel.workers, c: result.parallel.columns, s: result.parallel.seconds.toFixed(1) })}</span>}
            </div>
            {(result.notes ?? []).map((n, k) => (
              <div key={k} className="mx-3 mb-1 rounded bg-warn/10 px-2 py-1 text-small text-warn">
                {n}
              </div>
            ))}
            {(result.objective_worse ?? []).map((o, k) => (
              <div key={`w${k}`} className="mx-3 mb-1 rounded bg-warn/10 px-2 py-1 text-small text-warn">
                {t('opt.goalWorse', { name: t(`op.${o.type}`), a: fmt(o.before, 4), b: fmt(o.after, 4) })}
              </div>
            ))}
            {(result.inert_variables ?? []).length > 0 && (
              <div className="mx-3 mb-1 rounded bg-warn/10 px-2 py-1 text-small text-warn">
                {t('opt.inert', {
                  list: (result.inert_variables ?? [])
                    .map((k) => result.variables[k])
                    .filter(Boolean)
                    .map((v) => `S${base?.surfaces.findIndex((s) => s.id === v.surface_id) ?? '?'} ${paramLabel(v.parameter, t)}`)
                    .join(', '),
                })}
              </div>
            )}
            {(result.fixed_operands ?? []).length > 0 && (
              <div className="mx-3 mb-1 rounded bg-warn/10 px-2 py-1 text-small text-warn">
                {t('opt.fixedOps', {
                  p: ((result.fixed_operands ?? []).reduce((a, o) => a + o.share, 0) * 100).toFixed(0),
                  list: (result.fixed_operands ?? []).map((o) => `${t(`op.${o.type}`)}${o.surface_id ? ` S${base?.surfaces.findIndex((s) => s.id === o.surface_id) ?? '?'}` : ''} (${fmt(o.value, 3)} / ${fmt(o.target, 3)})`).join(', '),
                })}
              </div>
            )}
            {result.constraints && result.constraints.length > 0 && <LimitsTable result={result} />}
            <div className="grid grid-cols-[repeat(auto-fit,minmax(400px,1fr))] gap-px bg-line">
              <div className="overflow-x-auto bg-panel">
                <div className="px-3 pt-2 text-small font-semibold tracking-wide text-muted uppercase">{t('opt.beforeAfter')}</div>
                <table className="eng-table">
                  <thead>
                    <tr>
                      <th>{t('opt.parameter')}</th>
                      <th className="text-right">{t('opt.before')}</th>
                      <th className="text-right">{t('opt.after')}</th>
                      <th className="text-right">{t('opt.sensitivity')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.variables.map((v, k) => {
                      const si = base?.surfaces.findIndex((s) => s.id === v.surface_id) ?? -1
                      const isCurv = v.parameter === 'curvature'
                      const show = (x: number) => (isCurv ? (Math.abs(x) < 1e-15 ? '∞' : fmt(1 / x, 7)) : fmt(x, 7))
                      return (
                        <tr key={k}>
                          <td className="px-2">
                            S{si} {isCurv ? 'R' : paramLabel(v.parameter, t)} {v.at_bound && <Badge tone="warn">{t('opt.atBound')}</Badge>}
                          </td>
                          <td className="num px-2 text-right text-muted">{show(v.initial)}</td>
                          <td className="num px-2 text-right">{show(v.final)}</td>
                          <td className="num px-2 text-right text-muted">{v.sensitivity === null ? '—' : v.sensitivity.toExponential(2)}</td>
                        </tr>
                      )
                    })}
                    {(result.materials ?? []).map((m) => {
                      const si = base?.surfaces.findIndex((s) => s.id === m.surface_id) ?? -1
                      return (
                        <tr key={m.surface_id} title={`Candidates: ${m.candidates.join(', ')}`}>
                          <td className="px-2">S{si} glass</td>
                          <td className="num px-2 text-right text-muted">{m.initial}</td>
                          <td className={`num px-2 text-right ${m.final !== m.initial ? 'font-semibold text-accent' : ''}`}>{m.final}</td>
                          <td className="num px-2 text-right text-muted">{m.candidates.length} cand.</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                <table className="eng-table mt-2">
                  <thead>
                    <tr>
                      <th>{t('opt.type')}</th>
                      <th className="text-right">{t('opt.before')}</th>
                      <th className="text-right">{t('opt.after')}</th>
                      <th className="text-right">{t('opt.target')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.operands_after.map((o, k) => (
                      <tr key={k}>
                        <td className="px-2">{o.type}</td>
                        <td className="num px-2 text-right text-muted">{fmt(result.operands_before[k]?.value ?? null, 6)}</td>
                        <td className="num px-2 text-right">{fmt(o.value ?? null, 6)}</td>
                        <td className="num px-2 text-right text-muted">{fmt(o.target, 6)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="overflow-x-auto bg-panel">
                <CompareTable compare={compare} error={compareError} />
              </div>
            </div>
            <div className="h-50">
              <MeritChart history={history} />
            </div>
          </div>
        ) : (
          <div className="min-h-0 flex-1">
            {history.length > 1 ? (
              <>
                <div className="px-3 pt-1 text-small text-muted">
                  {t('opt.phase')}: {job?.phase} {job?.state === 'running' && `· ${t('opt.preview')}`}
                </div>
                <div className="h-[calc(100%-20px)]">
                  <MeritChart history={history} />
                </div>
              </>
            ) : (
              <div className="p-4 text-body leading-relaxed text-muted">
                {enabledVars.length && opt.operands.some((o) => o.enabled) ? t('opt.ready', { v: enabledVars.length, o: opt.operands.filter((o) => o.enabled).length }) : t('opt.noVariables')}
                <div className="mt-2 text-small text-faint">{t('opt.neverOverwritten')}</div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/** The exact limits of a result: before → after, met, and the price of each active one (the merit if it were relaxed). */
function LimitsTable({ result }: { result: OptimizationResult }) {
  const t = useT()
  const base = useOptStore((s) => s.base)
  const [curve, setCurve] = useState<ConstraintResult | null>(null)
  const rows = result.constraints ?? []
  const where = (c: ConstraintResult) => {
    const si = c.surface_id ? (base?.surfaces.findIndex((s) => s.id === c.surface_id) ?? -1) : -1
    return [si >= 0 ? `S${si}` : '', c.field !== null ? `F${c.field + 1}` : '', c.configuration !== null ? `C${c.configuration + 1}` : ''].filter(Boolean).join(' ')
  }
  const unit = (c: ConstraintResult) => {
    const u = c.unit || OPERAND_INFO[c.type]?.unit || ''
    return u === 'um' ? 'µm' : u
  }
  return (
    <div className="overflow-x-auto border-b border-line">
      <div className="px-3 pt-2 text-small font-semibold tracking-wide text-muted uppercase" title={t('mf.limitsHint')}>
        {t('opt.limitsTitle')}
      </div>
      <table className="eng-table">
        <thead>
          <tr>
            <th>{t('opt.limit')}</th>
            <th className="text-right">{t('opt.target')}</th>
            <th className="text-right">{t('opt.before')}</th>
            <th className="text-right">{t('opt.after')}</th>
            <th className="text-center">{t('mf.met')}</th>
            <th className="text-right" title={t('opt.priceHint')}>
              {t('opt.price')}
            </th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const p = priceLabel(c)
            const cmp = c.kind === 'target' ? '=' : c.type.startsWith('min_') ? '≥' : '≤'
            return (
              <tr key={c.index} title={t(`op.${c.type}.desc`)}>
                <td className="px-2">
                  {t(`op.${c.type}`)} <span className="text-muted">{where(c)}</span> {c.fixed && <Badge tone="warn">{t('mf.fixed')}</Badge>}
                </td>
                <td className="num px-2 text-right text-muted">
                  {cmp} {fmt(c.target, 6)} {unit(c)}
                </td>
                <td className={`num px-2 text-right ${c.met_before ? 'text-muted' : 'text-warn'}`}>{fmt(c.before, 6)}</td>
                <td className={`num px-2 text-right ${c.met ? '' : 'font-semibold text-danger'}`}>{fmt(c.after, 6)}</td>
                <td className={`text-center ${c.met ? 'text-ok' : 'text-danger'}`}>{c.met ? '✓' : '✗'}</td>
                <td className="num px-2 text-right" title={t('opt.priceHint')}>
                  {p ? (
                    <span className={p.percent < -0.05 ? 'text-accent' : 'text-muted'}>
                      {p.approximate ? '≈ ' : ''}
                      {fmt(p.target, 5)} → MF {p.percent >= 0 ? '+' : '−'}
                      {Math.abs(p.percent).toFixed(p.percent !== 0 && Math.abs(p.percent) < 0.1 ? 3 : 1)} %
                    </span>
                  ) : (
                    <span className="text-faint">{c.met && !c.fixed ? t('opt.notLimiting') : '—'}</span>
                  )}
                </td>
                <td className="px-1 text-right">
                  {c.active && !c.fixed && (
                    <IconButton size="sm" onClick={() => setCurve(c)} title={`${t('td.open')}: ${t('td.openHint')}`}>
                      <ChartLine size={14} />
                    </IconButton>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {curve && <TradeoffDialog limit={curve} onClose={() => setCurve(null)} />}
    </div>
  )
}

/** RMS spot from the axis to the largest field, before and after (engine field_profile); the system's own fields are
 * marked, and a sampling gap of the design after is named. */
function FieldProfileChart({ before, after }: { before: FieldProfile | null; after: FieldProfile | null }) {
  const t = useT()
  if (!after) return null
  const gap = after.gap
  const at = (p: FieldProfile, f: number) => p.rms_um[p.fractions.reduce((best, x, k) => (Math.abs(x - f) < Math.abs(p.fractions[best] - f) ? k : best), 0)]
  return (
    <div className="px-3 pt-1" title={t('opt.profileHint')}>
      <div className="text-caption text-muted">{t('opt.profile')}</div>
      <div className="h-36">
        <Plot
          data={[
            ...(before ? [{ type: 'scatter' as const, mode: 'lines' as const, x: before.fractions, y: before.rms_um, name: t('opt.before'), line: { color: DATA.reference, width: 1.5, dash: 'dot' as const } }] : []),
            { type: 'scatter', mode: 'lines', x: after.fractions, y: after.rms_um, name: t('opt.after'), line: { color: DATA.primary, width: 2 } },
            { type: 'scatter', mode: 'markers', x: after.defined, y: after.defined.map((f) => at(after, f)), name: t('c.field'), marker: { color: DATA.primary, size: 7 }, showlegend: false },
            ...(gap && gap.rms_um !== null ? [{ type: 'scatter' as const, mode: 'markers' as const, x: [gap.fraction], y: [gap.rms_um], name: t('cmps.field_gap'), marker: { color: DATA.marker, size: 10, symbol: 'x' }, showlegend: false }] : []),
          ]}
          layout={{ xaxis: { title: { text: t('ax.fieldFraction') }, range: [0, 1] }, yaxis: { title: { text: 'µm' }, rangemode: 'tozero' }, margin: { l: 44, r: 8, t: 4, b: 34 }, legend: { orientation: 'h', y: 1.02, yanchor: 'bottom', x: 1, xanchor: 'right' } }}
        />
      </div>
      {gap && (
        <div className="mb-1 rounded bg-warn/10 px-2 py-1 text-small text-warn">
          {gap.rms_um === null || gap.ratio === null
            ? t('opt.gapFail', { f: Math.round(gap.fraction * 100) })
            : t('opt.gap', { f: Math.round(gap.fraction * 100), v: fmt(gap.rms_um, 3), r: gap.ratio.toFixed(1), s: fmt(gap.sampled_max_um, 3) })}
        </div>
      )}
    </div>
  )
}

function MeritChart({ history }: { history: [number, number, number][] }) {
  const t = useT()
  return (
    <Plot
      data={[
        { type: 'scattergl', mode: 'markers', x: history.map((h) => h[0]), y: history.map((h) => h[1]), name: 'evaluated', marker: { size: 3, color: 'rgba(133,147,165,0.55)' } },
        { type: 'scatter', mode: 'lines', x: history.map((h) => h[0]), y: history.map((h) => h[2]), name: 'best', line: { color: DATA.primary, width: 2, shape: 'hv' } },
      ]}
      layout={{ xaxis: { title: { text: t('ax.evaluations') } }, yaxis: { title: { text: t('ax.merit') }, type: 'log' }, margin: { l: 60, r: 12, t: 10, b: 40 }, legend: { orientation: 'h', y: 1.05, yanchor: 'bottom', x: 1, xanchor: 'right' } }}
    />
  )
}

/** Before/after numbers of the image and the system from the engine (/optimize/compare): the merit function only sees
 * its operands, so distortion, colour, the field of view, illumination and length are shown and flagged here. */
function CompareTable({ compare, error }: { compare: DesignComparison | null; error: string | null }) {
  const t = useT()
  if (!compare) return <div className="p-3">{error ? <span className="text-small text-danger">{error}</span> : <Spinner />}</div>
  const worse = flagged(compare, 'worse')
  const changed = flagged(compare, 'changed')
  const label = (key: string, field: number | null) =>
    t(`cmp.${key}`, { f: field !== null ? field + 1 : '', nu: compare.before.mtf_frequency !== null ? fmt(compare.before.mtf_frequency, 3) : '—', u: compare.before.field_unit === 'deg' ? '°' : 'mm' })
  return (
    <>
      <div className="px-3 pt-2 text-small font-semibold tracking-wide text-muted uppercase">{t('opt.compare')}</div>
      <div className="px-3 pt-1 text-small">
        {worse.length ? <div className="text-warn">{t('opt.worseList', { list: worse.map((k) => t(`cmps.${k}`)).join(', ') })}</div> : <div className="text-ok">{t('opt.noRegressions')}</div>}
        {changed.length > 0 && <div className="text-muted">{t('opt.changedList', { list: changed.map((k) => t(`cmps.${k}`)).join(', ') })}</div>}
      </div>
      <FieldProfileChart before={compare.before.field_profile ?? null} after={compare.after.field_profile ?? null} />
      <table className="eng-table">
        <thead>
          <tr>
            <th>{t('opt.quantity')}</th>
            <th className="text-right">{t('opt.before')}</th>
            <th className="text-right">{t('opt.after')}</th>
            <th className="text-right">{t('opt.change')}</th>
          </tr>
        </thead>
        <tbody>
          {compareRows(compare).map((r) => (
            <tr key={r.id} title={r.flag ? t(`opt.flag.${r.flag}`) : undefined}>
              <td className={`px-2 ${r.flag === 'worse' ? 'text-warn' : ''}`}>{label(r.key, r.field)}</td>
              <td className="num px-2 text-right text-muted">{r.before}</td>
              <td className={`num px-2 text-right ${r.flag === 'worse' ? 'font-semibold text-warn' : ''}`}>{r.after}</td>
              <td className={`num px-2 text-right ${r.flag === 'worse' ? 'text-warn' : r.flag === 'changed' ? 'text-accent' : 'text-muted'}`}>{r.delta}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}
