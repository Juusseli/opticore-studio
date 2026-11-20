import { Lock, LockOpen, Play, Plus, Scale, Square, Trash2, Wand2 } from 'lucide-react'
import { OPERAND_INFO } from './operands'
import { designSnapshot, sameDesign } from '../../store/designGuard'
import { useMemo, useState } from 'react'
import { api } from '../../lib/api'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { newId } from '../../lib/project'
import { CRITERIA, DEFAULT_LIMIT, supportsTolerance, TERMS, TYPES, UNIT } from '../../lib/tolerance'
import type { Compensator, OpticalSystem, SensitivityRow, Tolerance, ToleranceAllocation, ToleranceLimit, ToleranceSpec, ToleranceType } from '../../lib/types'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { isTolRunning, tolKey, useTolStore } from '../../store/tolStore'
import { useUiStore } from '../../store/uiStore'
import { Label, MoreSettings, Row, Stat } from '../common/controls'
import { Plot } from '../common/Plot'
import { Badge, Button, Checkbox, IconButton, NumberField, Select, Spinner } from '../common/ui'
import { surfaceTitle } from './surfaceTitle'
import { DATA } from '../../lib/palette'

function surfaceLabel(sys: OpticalSystem, id: string | null) {
  const i = sys.surfaces.findIndex((s) => s.id === id)
  return i < 0 ? '?' : `${i}: ${surfaceTitle(sys.surfaces[i], i, sys.surfaces.length)}`
}

function useUnitLabel() {
  const t = useT()
  return (u: string) => (u === 'deg' ? '°' : u === 'um' ? 'µm' : u === 'fringes' ? t('tol.u.fringes') : u)
}

function useTypeLabel() {
  const t = useT()
  return (type: ToleranceType, term?: number | null) => `${t(`tt.${type}`)}${type === 'zernike_form' && term ? ` Z${term}` : ''}`
}

export function TolerancePanel() {
  const t = useT()
  const unitLabel = useUnitLabel()
  const project = useProjectStore((s) => s.project)
  const updateProject = useProjectStore((s) => s.updateProject)
  const backend = useEngineStore((s) => s.backend)
  const toast = useUiStore((s) => s.toast)
  const { job, result, resultKey, error, start, cancel } = useTolStore()
  const running = useTolStore(isTolRunning)
  const spec = project.tolerancing
  const sys = project.system
  const n = sys.surfaces.length
  const [grade, setGrade] = useState<'commercial' | 'precision' | 'high_precision'>('precision')
  const [newType, setNewType] = useState<ToleranceType>('radius')

  const setSpec = (fn: (s: ToleranceSpec) => void, label: string) => updateProject((p) => fn(p.tolerancing), label)
  const setTol = (k: number, patch: Partial<Tolerance>) => setSpec((s) => Object.assign(s.tolerances[k], patch), 'Edit tolerance')
  const setComp = (k: number, patch: Partial<Compensator>) => setSpec((s) => Object.assign(s.compensators[k], patch), 'Edit compensator')

  const allSurf = useMemo(() => sys.surfaces.map((s, i) => ({ s, i })), [sys.surfaces])
  const optsFor = (type: ToleranceType, current?: string) =>
    allSurf.filter(({ s, i }) => supportsTolerance(type, s, i, n) || s.id === current).map(({ s, i }) => ({ value: s.id, label: `${i}: ${surfaceTitle(s, i, n)}` }))
  const groupOpts = useMemo(() => allSurf.filter(({ s, i }) => i > 0 && i < n - 1 && s.type !== 'coordinate_break').map(({ s, i }) => ({ value: s.id, label: `${i}: ${surfaceTitle(s, i, n)}` })), [allSurf, n])
  const thickOpts = useMemo(() => allSurf.filter(({ s, i }) => supportsTolerance('thickness', s, i, n)).map(({ s, i }) => ({ value: s.id, label: `${i}: ${surfaceTitle(s, i, n)}` })), [allSurf, n])
  const termOpts = TERMS.map((j) => ({ value: j, label: j <= 16 ? `Z${j} ${t(`zt.${j}`)}` : `Z${j}` }))

  const generate = async () => {
    try {
      const snap = designSnapshot()
      const r = await api.toleranceDefault({ system: sys, custom_materials: project.custom_materials }, grade)
      if (!sameDesign(snap)) {
        toast('warning', t('c.staleDesign'))
        return
      }
      setSpec((s) => {
        s.tolerances = r.tolerance.tolerances
        s.compensators = r.tolerance.compensators
      }, `Default tolerances (${grade})`)
      toast('success', t('tol.defaultsDone', { n: r.tolerance.tolerances.length, grade: t(grade === 'high_precision' ? 'tol.highPrecision' : `tol.${grade}`) }))
    } catch (e) {
      toast('error', (e as Error).message)
    }
  }

  const addTolerance = () => {
    const first = sys.surfaces.findIndex((s, i) => i > 0 && supportsTolerance(newType, s, i, n))
    if (first < 0) {
      toast('error', t('tol.noSurface'))
      return
    }
    const lim = newType === 'radius' ? Math.max(1e-4, Math.abs(sys.surfaces[first].radius ?? 0) * 0.001) : DEFAULT_LIMIT[newType]
    const end = newType.startsWith('element_') ? sys.surfaces[Math.min(first + 1, n - 2)].id : null
    setSpec((s) => s.tolerances.push({ id: newId(), type: newType, surface_id: sys.surfaces[first].id, surface_id_end: end, min: -lim, max: lim, enabled: true, term: newType === 'zernike_form' ? 5 : null, locked: false }), 'Add tolerance')
  }

  const changeType = (k: number, x: Tolerance, v: ToleranceType) => {
    const keep = supportsTolerance(v, sys.surfaces.find((s) => s.id === x.surface_id) ?? sys.surfaces[0], sys.surfaces.findIndex((s) => s.id === x.surface_id), n)
    const sid = keep ? x.surface_id : (optsFor(v)[0]?.value ?? x.surface_id)
    const unitChanged = UNIT[v] !== UNIT[x.type]
    setTol(k, {
      type: v,
      surface_id: sid,
      surface_id_end: v.startsWith('element_') ? (x.surface_id_end ?? sid) : null,
      term: v === 'zernike_form' ? (x.term ?? 5) : null,
      ...(unitChanged ? { min: -DEFAULT_LIMIT[v], max: DEFAULT_LIMIT[v] } : {}),
    })
  }

  const enabled = spec.tolerances.filter((x) => x.enabled).length
  const stale = !!result && resultKey !== tolKey()
  const progress = job && job.total > 0 ? job.done / job.total : 0
  const sense = spec.criterion === 'mtf' ? -1 : 1
  const critUnit = spec.criterion === 'rms_spot' ? 'µm' : spec.criterion === 'rms_wavefront' ? t('an.waves') : ''
  const limitLabel = critUnit ? `${t('tol.limit', { op: sense > 0 ? '≤' : '≥' })} (${critUnit})` : t('tol.limit', { op: sense > 0 ? '≤' : '≥' })
  const hasLimit = spec.limit !== null && spec.limit !== undefined

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(460px,1.15fr)_minmax(420px,1fr)] gap-px bg-line">
      <div className="flex min-h-0 flex-col bg-panel">
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-2">
          <Label hint={t('tol.criterionHint')}>{t('tol.criterion')}</Label>
          <Select className="h-6 w-[190px] text-small" ariaLabel={t('tol.criterion')} value={spec.criterion} options={CRITERIA.map((c) => ({ value: c, label: t(`tol.c.${c}`) }))} onChange={(v) => setSpec((s) => (s.criterion = v), 'Tolerance criterion')} />
          {spec.criterion === 'mtf' && (
            <>
              <Label>{t('tol.freq')}</Label>
              <NumberField className="h-6 w-16" ariaLabel={t('tol.freq')} value={spec.mtf_frequency ?? 30} min={0.001} onCommit={(v) => setSpec((s) => (s.mtf_frequency = v ?? 30), 'MTF frequency')} />
            </>
          )}
          <Label hint={t('tol.limitHint')}>{limitLabel}</Label>
          <NumberField className="h-6 w-20" optional ariaLabel={limitLabel} placeholder="—" value={spec.limit ?? null} onCommit={(v) => setSpec((s) => (s.limit = v), 'Tolerance specification')} />
          <Label>{t('tol.trials')}</Label>
          <NumberField className="h-6 w-16" ariaLabel={t('tol.trials')} value={spec.monte_carlo_trials} integer min={0} max={5000} onCommit={(v) => setSpec((s) => (s.monte_carlo_trials = v ?? 0), 'Monte Carlo trials')} />
          <MoreSettings>
            <Row label={t('tol.rings')} hint={t('tol.ringsHint')}>
              <NumberField className="h-6 w-20" ariaLabel={t('tol.rings')} value={spec.rings} integer min={1} max={12} onCommit={(v) => setSpec((s) => (s.rings = v ?? 3), 'Tolerance rings')} />
            </Row>
            <Row label={t('tol.distribution')}>
              <Select
                className="h-6 w-[170px] text-small"
                ariaLabel={t('tol.distribution')}
                value={spec.distribution}
                options={[
                  { value: 'normal', label: t('tol.normal') },
                  { value: 'uniform', label: t('tol.uniform') },
                ]}
                onChange={(v) => setSpec((s) => (s.distribution = v), 'Monte Carlo distribution')}
              />
            </Row>
            <Row label={t('ns.seed')}>
              <NumberField className="h-6 w-20" ariaLabel={t('ns.seed')} value={spec.seed} integer min={0} onCommit={(v) => setSpec((s) => (s.seed = v ?? 1), 'Monte Carlo seed')} />
            </Row>
            <Row label={t('tol.testWl')} hint={t('tol.testWlHint')}>
              <NumberField className="h-6 w-20" ariaLabel={t('tol.testWl')} value={(spec.test_wavelength_um ?? 0.54607) * 1000} min={101} max={19999} onCommit={(v) => setSpec((s) => (s.test_wavelength_um = (v ?? 546.07) / 1000), 'Fringe test wavelength')} />
            </Row>
            <Row label={t('tol.compEvals')} hint={t('tol.compEvalsHint')}>
              <NumberField className="h-6 w-20" ariaLabel={t('tol.compEvals')} value={spec.compensator_evaluations} integer min={4} max={1000} onCommit={(v) => setSpec((s) => (s.compensator_evaluations = v ?? 40), 'Compensator evaluations')} />
            </Row>
          </MoreSettings>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 border-b border-line p-2">
          {!running ? (
            <>
              <Button variant="primary" onClick={() => start()} disabled={backend !== 'online' || !enabled}>
                <Play size={14} /> {t('tol.run')}
              </Button>
              <Button onClick={() => start(true)} disabled={backend !== 'online' || !enabled || !hasLimit} title={hasLimit ? t('tol.allocateHint') : t('tol.allocateNeedsLimit')}>
                <Scale size={14} /> {t('tol.allocate')}
              </Button>
            </>
          ) : (
            <>
              <Button variant="danger" onClick={cancel}>
                <Square size={12} /> {t('opt.cancel')}
              </Button>
              <Spinner />
              <span className="num text-small text-muted">
                {job ? t(`tol.ph.${job.phase}`) : ''} {job?.done}/{job?.total}
              </span>
              <div className="h-1.5 w-28 overflow-hidden rounded bg-hover">
                <div className="h-full bg-accent transition-[width]" style={{ width: `${Math.min(1, progress) * 100}%` }} />
              </div>
            </>
          )}
          <div className="flex-1" />
          <Select
            className="h-6 w-[130px] text-small"
            ariaLabel={t('tol.grade')}
            value={grade}
            options={[
              { value: 'commercial', label: t('tol.commercial') },
              { value: 'precision', label: t('tol.precision') },
              { value: 'high_precision', label: t('tol.highPrecision') },
            ]}
            onChange={setGrade}
          />
          <Button size="sm" onClick={generate} disabled={backend !== 'online' || running} title={t('tol.generateHint')}>
            <Wand2 size={12} /> {t('tol.generate')}
          </Button>
          {error && <span className="w-full truncate text-small text-danger">{error}</span>}
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          <table className="eng-table">
            <thead>
              <tr>
                <th className="w-8">#</th>
                <th className="w-8"></th>
                <th className="w-[170px]">{t('tol.type')}</th>
                <th className="w-[150px]">{t('opt.surface')}</th>
                <th className="w-[160px]">{t('tol.to')}</th>
                <th className="w-[96px]">{t('tol.min')}</th>
                <th className="w-[96px]">{t('tol.max')}</th>
                <th className="w-12">{t('tol.unit')}</th>
                <th className="w-[56px]"></th>
              </tr>
            </thead>
            <tbody>
              {spec.tolerances.map((x, k) => (
                <tr key={x.id} title={t(`tt.${x.type}.desc`)}>
                  <td className="px-2 text-muted">{k + 1}</td>
                  <td className="text-center">
                    <Checkbox checked={x.enabled} ariaLabel={t('tol.enabledRow', { k: k + 1 })} onChange={(v) => setTol(k, { enabled: v })} />
                  </td>
                  <td>
                    <Select cell value={x.type} options={TYPES.map((v) => ({ value: v, label: t(`tt.${v}`) }))} onChange={(v) => changeType(k, x, v)} />
                  </td>
                  <td>
                    <Select cell value={x.surface_id} options={x.type === 'thickness' ? thickOpts : optsFor(x.type, x.surface_id)} onChange={(v) => setTol(k, { surface_id: v })} />
                  </td>
                  <td>
                    {x.type.startsWith('element_') ? (
                      <Select cell value={x.surface_id_end ?? ''} options={groupOpts} onChange={(v) => setTol(k, { surface_id_end: v })} />
                    ) : x.type === 'zernike_form' ? (
                      <Select<number> cell ariaLabel={`${t('tol.term')} ${k + 1}`} value={x.term ?? 5} options={termOpts} onChange={(v) => setTol(k, { term: v })} />
                    ) : (
                      <span className="px-2 text-faint">—</span>
                    )}
                  </td>
                  <td>
                    <NumberField cell value={x.min} max={x.max} onCommit={(v) => setTol(k, { min: v ?? 0 })} />
                  </td>
                  <td>
                    <NumberField cell value={x.max} min={x.min} onCommit={(v) => setTol(k, { max: v ?? 0 })} />
                  </td>
                  <td className="px-2 text-muted">{unitLabel(UNIT[x.type])}</td>
                  <td className="px-1">
                    <div className="flex items-center">
                      <IconButton size="sm" active={!!x.locked} title={x.locked ? t('tol.unlock') : t('tol.lock')} onClick={() => setTol(k, { locked: !x.locked })}>
                        {x.locked ? <Lock size={12} /> : <LockOpen size={12} />}
                      </IconButton>
                      <IconButton size="sm" tone="danger" title={t('c.remove')} onClick={() => setSpec((s) => s.tolerances.splice(k, 1), 'Remove tolerance')}>
                        <Trash2 size={12} />
                      </IconButton>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {spec.tolerances.length === 0 && <div className="p-3 text-muted">{t('tol.empty')}</div>}
          <div className="flex items-center gap-1.5 px-2 py-1.5">
            <Select className="h-6 w-[200px] text-small" ariaLabel={t('tol.newType')} value={newType} options={TYPES.map((v) => ({ value: v, label: t(`tt.${v}`) }))} onChange={setNewType} />
            <Button size="sm" onClick={addTolerance}>
              <Plus size={12} /> {t('tol.add')}
            </Button>
          </div>

          <div className="px-3 pt-2 pb-1 text-small font-semibold tracking-wide text-muted uppercase">{t('tol.compensators')}</div>
          <table className="eng-table">
            <tbody>
              {spec.compensators.map((c, k) => (
                <tr key={k} title={t('tol.compHint')}>
                  <td className="w-8 text-center">
                    <Checkbox checked={c.enabled} ariaLabel={`${t('tol.compensators')} ${k + 1}`} onChange={(v) => setComp(k, { enabled: v })} />
                  </td>
                  <td className="w-[150px]">
                    <Select
                      cell
                      ariaLabel={`${t('tol.compensators')} ${k + 1}: ${t('opt.parameter')}`}
                      value={c.parameter}
                      options={[
                        { value: 'thickness', label: t('par.thickness') },
                        { value: 'curvature', label: t('par.curvature') },
                      ]}
                      onChange={(v) => setComp(k, { parameter: v, range: v === 'curvature' ? 1e-4 : 2 })}
                    />
                  </td>
                  <td className="w-[170px]">
                    <Select cell ariaLabel={`${t('tol.compensators')} ${k + 1}: ${t('c.surface')}`} value={c.surface_id} options={c.parameter === 'thickness' ? thickOpts : groupOpts} onChange={(v) => setComp(k, { surface_id: v })} />
                  </td>
                  <td className="w-[60px] px-2 text-muted">{t('tol.range')}</td>
                  <td className="w-[100px]">
                    <NumberField cell ariaLabel={`${t('tol.compensators')} ${k + 1}: ${t('tol.range')}`} value={c.range} min={1e-12} onCommit={(v) => setComp(k, { range: v ?? 1 })} />
                  </td>
                  <td className="px-2 text-muted">{c.parameter === 'thickness' ? 'mm' : '1/mm'}</td>
                  <td className="px-1">
                    <IconButton size="sm" tone="danger" title={t('c.remove')} onClick={() => setSpec((s) => s.compensators.splice(k, 1), 'Remove compensator')}>
                      <Trash2 size={12} />
                    </IconButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-2 py-1.5">
            <Button
              size="sm"
              onClick={() => {
                const bf = thickOpts[thickOpts.length - 1] // back focus by default
                if (bf) setSpec((s) => s.compensators.push({ surface_id: bf.value, parameter: 'thickness', range: 2, enabled: true }), 'Add compensator')
              }}
            >
              <Plus size={12} /> {t('tol.addComp')}
            </Button>
          </div>
          <div className="px-3 py-2 text-caption leading-relaxed text-faint">{t('tol.help')}</div>
        </div>
      </div>

      <div className="flex min-h-0 flex-col bg-panel">
        <ToleranceResults stale={stale} liveTrials={running ? (job?.trials ?? []) : null} liveNominal={running ? (job?.nominal ?? null) : null} />
      </div>
    </div>
  )
}

/** With exact limits the merit criterion holds only the goals; the limits are reported apart (engine tolerance.py
 * `limits`): their nominal values and how many Monte Carlo trials meet each to the optimiser's tolerance. They do not
 * enter the yield. */
function LimitsOfTolerancing({ limits, sys }: { limits: ToleranceLimit[]; sys: OpticalSystem }) {
  const t = useT()
  return (
    <>
      <div className="px-3 pt-2 pb-1 text-small font-semibold tracking-wide text-muted uppercase" title={t('tol.limitsHint')}>
        {t('opt.limitsTitle')}
      </div>
      <table className="eng-table">
        <thead>
          <tr>
            <th>{t('opt.limit')}</th>
            <th className="text-right">{t('opt.target')}</th>
            <th className="text-right">{t('tol.nominal')}</th>
            <th className="text-right" title={t('tol.limitsMetHint')}>
              {t('tol.limitsMet')}
            </th>
            <th className="text-right">p10 … p90</th>
          </tr>
        </thead>
        <tbody>
          {limits.map((L) => {
            const si = L.surface_id ? sys.surfaces.findIndex((s) => s.id === L.surface_id) : -1
            const raw = L.unit || OPERAND_INFO[L.type]?.unit || ''
            const u = raw === 'um' ? 'µm' : raw
            const cmp = L.kind === 'target' ? '=' : L.type.startsWith('min_') ? '≥' : '≤'
            const st = L.monte_carlo.statistics
            return (
              <tr key={L.index} title={t(`op.${L.type}.desc`)}>
                <td className="px-2">
                  {t(`op.${L.type}`)} {si >= 0 && <span className="text-muted">S{si}</span>}
                </td>
                <td className="num px-2 text-right text-muted">
                  {cmp} {fmt(L.target, 6)} {u}
                </td>
                <td className={`num px-2 text-right ${L.met_nominal ? '' : 'text-danger'}`}>{fmt(L.nominal, 6)}</td>
                <td className={`num px-2 text-right ${L.monte_carlo.trials && L.monte_carlo.met < L.monte_carlo.trials ? 'text-warn' : ''}`}>
                  {L.monte_carlo.trials ? `${L.monte_carlo.met}/${L.monte_carlo.trials}` : '—'}
                </td>
                <td className="num px-2 text-right text-muted">{st.p10 !== undefined && st.p90 !== undefined ? `${fmt(st.p10, 5)} … ${fmt(st.p90, 5)}` : '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </>
  )
}

function ToleranceResults({ stale, liveTrials, liveNominal }: { stale: boolean; liveTrials: (number | null)[] | null; liveNominal: number | null }) {
  const t = useT()
  const result = useTolStore((s) => s.result)
  const sys = useProjectStore((s) => s.project.system)
  const criterion = useProjectStore((s) => s.project.tolerancing.criterion)
  const limit = useProjectStore((s) => s.project.tolerancing.limit ?? null)
  const unit = result?.unit === 'um' ? 'µm' : result?.unit === 'waves' ? t('an.waves') : (result?.unit ?? '')
  const sense = result?.sense ?? (criterion === 'mtf' ? -1 : 1)
  const op = sense > 0 ? '≤' : '≥'
  const values = (liveTrials ?? result?.monte_carlo.values ?? []).filter((v): v is number => v !== null)
  const nominal = liveNominal ?? result?.nominal ?? null
  const st = liveTrials ? null : result?.monte_carlo.statistics
  const y = liveTrials ? null : result?.yield
  const sorted = [...values].sort((a, b) => a - b)
  const specLimit = liveTrials ? limit : (result?.yield?.limit ?? result?.allocation?.limit ?? null)

  if (!result && !liveTrials) return <div className="flex h-full items-center justify-center p-6 text-center text-muted">{t('tol.noResult')}</div>

  const v = (x: number | null | undefined) => fmt(x ?? null, 5)
  const xTitle = `${t(`tol.c.${result?.criterion ?? criterion}`)}`
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto">
      <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
        <Stat label={t('tol.nominal')} value={v(nominal)} unit={unit} />
        <Stat label={t('tol.rss')} value={v(liveTrials ? null : result?.rss_estimate)} unit={unit} />
        <Stat label={t('tol.mcMean')} value={v(st?.mean)} unit={unit} />
        <Stat label={t('tol.pct', { p: 90, op })} value={v(sense > 0 ? st?.p90 : st?.p10)} unit={unit} />
        <Stat label={t('tol.pct', { p: 98, op })} value={v(sense > 0 ? st?.p98 : st?.p2)} unit={unit} />
        {y && (
          <div title={t('tol.yieldHint')}>
            <Stat label={t('tol.yield')} value={`${fmt(y.fraction * 100, 3)} %`} unit={t('tol.yieldCi', { lo: fmt(y.ci95[0] * 100, 3), hi: fmt(y.ci95[1] * 100, 3) })} />
          </div>
        )}
      </div>
      {stale && <div className="border-b border-line bg-warn/10 px-3 py-1 text-small text-warn">{t('tol.stale')}</div>}
      {result?.status === 'cancelled' && !liveTrials && <div className="border-b border-line px-3 py-1 text-small text-warn">{t('tol.cancelled', { n: result.monte_carlo.trials, m: result.monte_carlo.requested })}</div>}
      {values.length > 0 && (
        <div className="h-55 shrink-0 border-b border-line">
          <Plot
            data={[
              { x: values, type: 'histogram', name: t('ax.trials'), marker: { color: DATA.primary, opacity: 0.6 }, nbinsx: Math.min(40, Math.max(8, Math.round(Math.sqrt(values.length) * 2))) },
              { x: sorted, y: sorted.map((_, k) => ((k + 1) / sorted.length) * 100), type: 'scatter', mode: 'lines', name: t('ax.cumulative'), yaxis: 'y2', line: { width: 2, color: DATA.secondary } },
            ]}
            layout={{
              margin: { l: 44, r: 44, t: 10, b: 34 },
              showlegend: false,
              bargap: 0.05,
              xaxis: { title: { text: unit && !xTitle.includes(unit) ? `${xTitle} (${unit})` : xTitle } },
              yaxis: { title: { text: t('ax.trials') } },
              yaxis2: { overlaying: 'y', side: 'right', range: [0, 100], title: { text: t('ax.cumulative') }, showgrid: false },
              shapes: [
                ...(nominal !== null ? [{ type: 'line', x0: nominal, x1: nominal, yref: 'paper', y0: 0, y1: 1, line: { dash: 'dot', width: 1.5, color: DATA.marker } }] : []),
                ...(specLimit !== null ? [{ type: 'line', x0: specLimit, x1: specLimit, yref: 'paper', y0: 0, y1: 1, line: { dash: 'dash', width: 1.5, color: DATA.tertiary } }] : []),
              ],
            }}
          />
        </div>
      )}
      {result && !liveTrials && (
        <>
          {result.allocation && <AllocationTable a={result.allocation} unit={unit} stale={stale} sys={sys} />}
          {result.limits && result.limits.length > 0 && <LimitsOfTolerancing limits={result.limits} sys={sys} />}
          <div className="px-3 pt-2 pb-1 text-small font-semibold tracking-wide text-muted uppercase">{t('tol.sensitivity')}</div>
          <SensitivityTable rows={result.sensitivity} nominal={result.nominal} unit={unit} sys={sys} />
          {st && (
            <div className="num px-3 py-2 text-small text-muted">
              {t('tol.mcLine', { n: result.monte_carlo.trials, dist: t(result.monte_carlo.distribution === 'uniform' ? 'tol.uniform' : 'tol.normal'), seed: result.monte_carlo.seed, min: v(st.min), p10: v(st.p10), p50: v(st.p50), p90: v(st.p90), max: v(st.max), std: fmt(st.std ?? null, 4), unit })}
              {result.monte_carlo.failures > 0 && <span className="text-warn"> · {t('tol.mcFailed', { n: result.monte_carlo.failures })}</span>}
            </div>
          )}
          {result.notes.map((nt) => (
            <div key={nt} className="px-3 text-small text-warn">
              {nt}
            </div>
          ))}
          <div className="px-3 py-2 text-caption leading-relaxed text-faint">
            {t('an.method')}: {result.method}. {t('tol.evalLine', { n: result.evaluations, s: result.elapsed_s.toFixed(1) })}
          </div>
        </>
      )}
    </div>
  )
}

function AllocationTable({ a, unit, stale, sys }: { a: ToleranceAllocation; unit: string; stale: boolean; sys: OpticalSystem }) {
  const t = useT()
  const unitLabel = useUnitLabel()
  const typeLabel = useTypeLabel()
  const updateProject = useProjectStore((s) => s.updateProject)
  const toast = useUiStore((s) => s.toast)
  const free = a.rows.filter((r) => !r.locked)
  const lim = (lo: number, hi: number) => (lo === -hi ? `±${fmt(hi, 3)}` : `${fmt(lo, 3)} / ${fmt(hi, 3)}`)
  const apply = () => {
    updateProject((p) => {
      for (const r of free) {
        const x = p.tolerancing.tolerances.find((tt) => tt.id === r.id)
        if (x) {
          x.min = r.new_min
          x.max = r.new_max
        }
      }
    }, 'Apply allocated tolerances')
    toast('success', t('tol.applied', { n: free.length }))
  }
  const withUnit = (x: number) => `${fmt(x, 5)}${unit ? ` ${unit}` : ''}`
  return (
    <div className="border-b border-line">
      <div className="flex items-center gap-2 px-3 pt-2 pb-1">
        <div className="text-small font-semibold tracking-wide text-muted uppercase">{t('tol.alloc')}</div>
        <div className="flex-1" />
        <Button size="sm" variant="primary" onClick={apply} disabled={stale || !free.length} title={stale ? t('tol.applyStale') : undefined}>
          {t('tol.applyAlloc')}
        </Button>
      </div>
      <div className="px-3 pb-1 text-small text-muted">{t('tol.allocSummary', { n: free.length, pred: withUnit(a.predicted), limit: withUnit(a.limit) })}</div>
      <table className="eng-table">
        <thead>
          <tr>
            <th>{t('tol.tolerance')}</th>
            <th className="text-right">{t('tol.cur')}</th>
            <th className="text-right">{t('tol.new')}</th>
            <th className="text-right">{t('tol.factor')}</th>
            <th className="text-right">{t('tol.share')}</th>
          </tr>
        </thead>
        <tbody>
          {a.rows.map((r) => (
            <tr key={r.id} title={surfaceLabel(sys, r.surface_id)}>
              <td className="px-2 whitespace-nowrap">
                {typeLabel(r.type, r.term)} <span className="text-muted">· {surfaceLabel(sys, r.surface_id).split(':')[0]}</span>
              </td>
              <td className="num px-2 text-right whitespace-nowrap text-muted">
                {lim(r.min, r.max)} {unitLabel(r.unit)}
              </td>
              <td className="num px-2 text-right whitespace-nowrap">
                {lim(r.new_min, r.new_max)} {unitLabel(r.unit)}
              </td>
              <td className="num px-2 text-right whitespace-nowrap">
                {r.locked ? <Badge>{t('tol.locked')}</Badge> : r.capped === 'max' ? <Badge>{t('tol.cappedMax')}</Badge> : r.capped === 'min' ? <Badge tone="warn">{t('tol.cappedMin')}</Badge> : `×${fmt(r.factor, 3)}`}
              </td>
              <td className="num px-2 text-right">{r.share === null ? '—' : fmt(r.share * 100, 3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SensitivityTable({ rows, nominal, unit, sys }: { rows: SensitivityRow[]; nominal: number | null; unit: string; sys: OpticalSystem }) {
  const t = useT()
  const unitLabel = useUnitLabel()
  const typeLabel = useTypeLabel()
  const max = Math.max(1e-30, ...rows.map((r) => (Number.isFinite(r.worst_change) ? r.worst_change : 0)))
  const d = (v: number | null) => (v === null || nominal === null ? '—' : `${v - nominal >= 0 ? '+' : ''}${fmt(v - nominal, 4)}`)
  const u = unit ? ` (${unit})` : ''
  return (
    <table className="eng-table">
      <thead>
        <tr>
          <th>{t('tol.tolerance')}</th>
          <th>{t('c.surface')}</th>
          <th className="text-right">{t('tol.limits')}</th>
          <th className="text-right">
            {t('tol.atMin')}
            {u}
          </th>
          <th className="text-right">
            {t('tol.atMax')}
            {u}
          </th>
          <th className="w-[90px]">{t('tol.worst')}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id} title={t('tol.rowHint', { min: fmt(r.at_min_uncompensated, 5), max: fmt(r.at_max_uncompensated, 5), unit, comp: r.at_max_compensators.map((c) => fmt(c, 4)).join(', ') || '—' })}>
            <td className="px-2">{typeLabel(r.type, r.term)}</td>
            <td className="px-2 text-muted">
              {surfaceLabel(sys, r.surface_id)}
              {r.surface_id_end && r.surface_id_end !== r.surface_id ? ` → ${surfaceLabel(sys, r.surface_id_end).split(':')[0]}` : ''}
            </td>
            <td className="num px-2 text-right text-muted">
              {fmt(r.min, 3)} / {fmt(r.max, 3)} {unitLabel(r.unit)}
            </td>
            <td className="num px-2 text-right">{d(r.at_min)}</td>
            <td className="num px-2 text-right">{d(r.at_max)}</td>
            <td className="px-2">
              {Number.isFinite(r.worst_change) ? (
                <div className="h-1.5 w-full overflow-hidden rounded bg-hover">
                  <div className="h-full bg-accent" style={{ width: `${(r.worst_change / max) * 100}%` }} />
                </div>
              ) : (
                <Badge tone="danger">{t('tol.failed')}</Badge>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
