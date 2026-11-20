// Design space map: many optimised designs of one specification over several topologies, with the
// Pareto front. Every number comes from the engine (backend designspace.py); this view only arranges them.
import { FolderPlus, GitCommitHorizontal, Play, Square, Wand2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { openDesignCandidate } from '../../actions'
import { api } from '../../lib/api'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { DATA, SERIES } from '../../lib/palette'
import { DESIGN_TOPOLOGIES, TOPOLOGY_ELEMENTS, type DesignCandidate, type DesignMetricKey, type DesignSpaceSpec, type DesignTopology, type StockTopology } from '../../lib/types'
import { useCatalogStore } from '../../store/catalogStore'
import { useDesignSpaceStore } from '../../store/designSpaceStore'
import { useEngineStore } from '../../store/engineStore'
import { GENERIC_ID, lensesFor, useStockStore } from '../../store/stockStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { Label } from '../common/controls'
import { Plot, type Trace } from '../common/Plot'
import { Button, Checkbox, NumberField, Select } from '../common/ui'
import { cx } from '../common/uiUtils'
import { useAnalysisSettings } from '../common/useAnalysisSettings'
import { OutlineThumb } from '../start/OutlineThumb'
import { AnalysisFrame } from './AnalysisFrame'
import { StockSpecForm } from './StockSpecForm'
import { DS_METRICS, type DsSettings, glassPool, specFromDesign, stockBuildSpec, stockMatchSpec } from './designSpace'

const ALL_TOPOLOGIES: (DesignTopology | StockTopology)[] = [...DESIGN_TOPOLOGIES, 'stock_1', 'stock_2', 'stock_3']
/** metrics drawn on a logarithmic axis when they span more than a factor of 20 */
const LOG_OK: DesignMetricKey[] = ['rms_spot_um', 'rms_spot_max_um', 'mass_g', 'glass_cost', 'tolerance_rss_um', 'abs_distortion_pct', 'price', 'merit']

const metricValue = (c: DesignCandidate, k: DesignMetricKey): number | null => {
  const v = c.metrics?.[k]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function MetricTable({ c, mtfFreq }: { c: DesignCandidate; mtfFreq: number }) {
  const t = useT()
  const m = c.metrics
  if (!m) return null
  const n = (v: number | null, d: number) => (v === null ? '—' : fmt(v, d))
  const rows: [string, string][] = [
    [t('ds.m.rms_spot_um'), `${n(m.rms_spot_um, 3)} (${m.rms_spot_fields_um.map((v) => n(v, 3)).join(' · ')})`],
    [t('ds.m.mtf', { f: fmt(mtfFreq, 3) }), m.mtf === null ? '—' : `${fmt(m.mtf, 3)} (${(m.mtf_fields ?? []).map((v) => fmt(v, 2)).join(' · ')})`],
    [t('ds.m.length_mm'), fmt(m.length_mm, 4)],
    [t('ds.m.mass_g'), m.mass_g === null ? '—' : fmt(m.mass_g, 3)],
    [t('ds.m.glass_cost'), m.glass_cost === null ? '—' : fmt(m.glass_cost, 3)],
    [t('ds.m.distortion'), m.distortion_pct === null ? '—' : fmt(m.distortion_pct, 3)],
    [t('ds.m.tolerance_rss_um'), m.tolerance_rss_um === null ? '—' : fmt(m.tolerance_rss_um, 3)],
    ['EFL (mm)', m.efl_mm === null ? '—' : fmt(m.efl_mm, 6)],
  ]
  if (m.magnification !== undefined && m.magnification !== null) rows.push([t('ds.m.magnification'), fmt(m.magnification, 6)])
  if (m.parts !== undefined) rows.push([t('ds.m.parts'), String(m.parts)])
  if (m.price !== undefined) rows.push([t('ds.m.price'), m.price === null ? '—' : fmt(m.price, 5)])
  if (m.merit !== undefined) rows.push([t('ds.m.merit'), fmt(m.merit, 4)])
  return (
    <table className="w-full text-small">
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <td className="pr-2 text-muted">{k}</td>
            <td className="num text-right whitespace-nowrap">{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function DesignSpaceView() {
  const t = useT()
  const project = useProjectStore((s) => s.project)
  const evaluation = useEngineStore((s) => s.evaluation)
  const backend = useEngineStore((s) => s.backend)
  const materials = useEngineStore((s) => s.materials)
  const catalogs = useCatalogStore((s) => s.catalogs)
  const stock = useStockStore()
  const ds = useDesignSpaceStore()
  const lang = useUiStore((s) => s.lang) // t() is a new function every render: memos depend on the language
  const prim = project.system.primary_wavelength
  const fromDesign = specFromDesign(project, evaluation?.paraxial[String(prim)] ?? null)
  const defaults: DsSettings = {
    ...fromDesign,
    max_length: null,
    topologies: ['singlet', 'cemented_doublet', 'air_spaced_doublet', 'triplet'],
    candidates: 100,
    mtf_frequency: 30,
    tolerances: true,
    seed: 1,
    pool: 'builtin',
    infeasible: false,
    mode: 'forms',
    stock_task: 'build',
    conjugate: 'infinite',
    object_distance: 100,
    magnification: -1,
    object_na: 0.05,
    object_height: 1,
    lens_counts: [1, 2],
    stock_glasses: null,
    stock_catalogs: [GENERIC_ID],
    min_gap: 0.5,
    tolerance_pct: 1,
    per_element: 4,
    stock_candidates: 40,
  }
  const [st, set] = useAnalysisSettings<DsSettings>('designspace', defaults, 'Design space settings')
  const running = ds.job?.state === 'running'
  const box = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null)

  const builtinGlasses = useMemo(() => materials.filter((m) => m.builtin && (!m.category || m.category === 'glass')).map((m) => m.name), [materials])
  useEffect(() => {
    if (st.mode === 'stock') void stock.loadGeneric().catch(() => undefined)
  }, [st.mode, stock])
  const run = () => {
    if (st.mode === 'stock') {
      const { lenses, custom } = lensesFor(st.stock_catalogs, stock.catalogs)
      const own = project.custom_materials
      const mats = [...own, ...custom.filter((r) => !own.some((m) => m.name.toUpperCase() === r.name.toUpperCase()))]
      if (st.stock_task === 'match')
        void ds.startWith(
          () => api.stockMatchStart({ system: project.system, custom_materials: mats, spec: stockMatchSpec(st), optimization: project.optimization, lenses }),
          'Stock lens match',
        )
      else void ds.startWith(() => api.stockBuildStart({ spec: stockBuildSpec(st, project), lenses, custom_materials: mats }), 'Stock lens build')
      return
    }
    const { glasses, custom } = glassPool(st.pool, project, builtinGlasses, catalogs)
    const spec: DesignSpaceSpec = {
      focal_length: st.focal_length,
      f_number: st.f_number,
      half_field_deg: st.half_field_deg,
      wavelengths: project.system.wavelengths.map((w) => w.value),
      primary: prim,
      max_length: st.max_length,
      max_elements: 6,
      topologies: st.topologies.length ? st.topologies : ['cemented_doublet'],
      candidates: st.candidates,
      glasses,
      mtf_frequency: st.mtf_frequency,
      tolerances: st.tolerances,
      seed: st.seed,
    }
    void ds.start(spec, custom)
  }

  const all = ds.order.map((i) => ds.candidates[i]).filter((c): c is DesignCandidate => !!c && c.status === 'finished')
  const front = new Set(ds.pareto)
  const has = (k: DesignMetricKey) => all.some((c) => metricValue(c, k) !== null)
  const axisOptions = DS_METRICS.filter((k) => k === ds.x || k === ds.y || !all.length || has(k)).map((k) => ({ value: k, label: t(`ds.m.${k}`, { f: fmt(st.mtf_frequency, 3) }) }))
  const shown = all.filter((c) => st.infeasible || c.feasible)
  const selected = ds.selected !== null ? ds.candidates[ds.selected] : undefined

  const axis = (k: DesignMetricKey) => {
    const v = shown.map((c) => metricValue(c, k)).filter((x): x is number => x !== null && x > 0)
    const log = LOG_OK.includes(k) && v.length > 1 && Math.max(...v) / Math.min(...v) > 20
    return { title: { text: t(`ds.m.${k}`, { f: fmt(st.mtf_frequency, 3) }) + (log ? ' · log' : '') }, type: log ? 'log' : 'linear', zeroline: false, showspikes: false }
  }
  const data: Trace[] = useMemo(() => {
    const traces: Trace[] = []
    const point = (c: DesignCandidate) => [metricValue(c, ds.x), metricValue(c, ds.y)] as const
    ALL_TOPOLOGIES.forEach((topo, k) => {
      const cs = shown.filter((c) => c.topology === topo && point(c)[0] !== null && point(c)[1] !== null)
      if (!cs.length) return
      const feas = cs.filter((c) => c.feasible)
      const inf = cs.filter((c) => !c.feasible)
      const name = `${t(`ds.topo.${topo}`)} (${cs.length})`
      const col = SERIES[k % SERIES.length]
      traces.push({
        type: 'scatter',
        mode: 'markers',
        name,
        legendgroup: topo,
        x: feas.map((c) => point(c)[0]),
        y: feas.map((c) => point(c)[1]),
        customdata: feas.map((c) => c.index),
        hoverinfo: 'none',
        marker: { size: feas.map((c) => (front.has(c.index) ? 11 : 7)), color: col, opacity: 0.9, line: { width: feas.map((c) => (front.has(c.index) ? 2 : 0)), color: DATA.selection } },
      })
      if (inf.length)
        traces.push({
          type: 'scatter',
          mode: 'markers',
          name: `${t(`ds.topo.${topo}`)}: ${t('ds.infeasible')}`,
          legendgroup: topo,
          showlegend: false,
          x: inf.map((c) => point(c)[0]),
          y: inf.map((c) => point(c)[1]),
          customdata: inf.map((c) => c.index),
          hoverinfo: 'none',
          marker: { size: 7, color: 'rgba(0,0,0,0)', line: { width: 1.2, color: col }, symbol: 'circle-open' },
        })
    })
    // the front over the two shown axes as a step line (the front of more objectives has no line in 2D)
    if (ds.objectives.length === 2 && ds.objectives[0] === ds.x && ds.objectives[1] === ds.y) {
      const pts = all.filter((c) => front.has(c.index)).map(point) as [number, number][]
      pts.sort((a, b) => a[0] - b[0])
      if (pts.length > 1) traces.push({ type: 'scatter', mode: 'lines', name: t('ds.front'), x: pts.map((p) => p[0]), y: pts.map((p) => p[1]), line: { color: DATA.selection, width: 1.5, shape: 'hv' }, hoverinfo: 'skip' })
    }
    if (selected && selected.status === 'finished') {
      const [x, y] = point(selected)
      if (x !== null && y !== null) traces.push({ type: 'scatter', mode: 'markers', name: t('ds.selected'), x: [x], y: [y], customdata: [selected.index], hoverinfo: 'none', marker: { size: 15, symbol: 'diamond-open', color: DATA.marker, line: { width: 2, color: DATA.marker } } })
    }
    return traces
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown.length, ds.x, ds.y, ds.pareto, ds.objectives, ds.selected, st.infeasible, lang])
  const layout = useMemo(() => ({ xaxis: axis(ds.x), yaxis: axis(ds.y), margin: { l: 60, r: 12, t: 12, b: 70 }, showlegend: true }), [shown.length, ds.x, ds.y, st.mtf_frequency, lang]) // eslint-disable-line react-hooks/exhaustive-deps

  const frontRows = all
    .filter((c) => front.has(c.index))
    .sort((a, b) => (metricValue(a, ds.objectives[0] ?? 'rms_spot_um') ?? 0) - (metricValue(b, ds.objectives[0] ?? 'rms_spot_um') ?? 0))
  const eta = running && ds.job && ds.job.done > 0 && !ds.job.phase?.match(/search|prescreen/) ? (ds.job.elapsed_s / ds.job.done) * (ds.job.total - ds.job.done) : null
  // a stock lens run searches and prescreens before its candidates exist
  const prePhase = running && (ds.job?.phase === 'search' || ds.job?.phase === 'prescreen')
  const progDone = prePhase ? (ds.job?.phase_done ?? 0) : (ds.job?.done ?? 0)
  const progTotal = prePhase ? (ds.job?.phase_total ?? 0) : (ds.job?.total ?? 0)
  const hovered = hover ? ds.candidates[hover.i] : undefined
  const objectiveNames = ds.objectives.map((k) => t(`ds.short.${k}`)).join(' · ')
  const toggleTopo = (k: DesignTopology, on: boolean) => set({ topologies: on ? DESIGN_TOPOLOGIES.filter((x) => x === k || st.topologies.includes(x)) : st.topologies.filter((x) => x !== k) })
  const poolOptions = [
    { value: 'builtin', label: t('ds.poolBuiltin', { n: builtinGlasses.length }) },
    { value: 'project', label: t('ds.poolProject') },
    ...catalogs.map((c) => ({ value: 'cat:' + c.id, label: t('ds.poolCatalog', { name: c.name, n: c.records.length }) })),
  ]

  return (
    <AnalysisFrame
      kind="designspace"
      title={t('view.designspace')}
      loading={false}
      error={ds.error}
      hasData={all.length > 0}
      ms={null}
      onRefresh={run}
      settings={st}
      result={null}
      onDemand
      alwaysShow
      method={t(st.mode === 'stock' ? 'ds.methodStock' : 'ds.method')}
      controls={
        <>
          <Label hint={t('ds.xHint')}>x</Label>
          <Select className="h-6 w-44 text-small" ariaLabel={t('ds.xAxis')} value={ds.x} options={axisOptions} onChange={(v) => ds.setAxes({ x: v })} />
          <Label hint={t('ds.yHint')}>y</Label>
          <Select className="h-6 w-44 text-small" ariaLabel={t('ds.yAxis')} value={ds.y} options={axisOptions} onChange={(v) => ds.setAxes({ y: v })} />
          <Label hint={t('ds.frontHint')}>{t('ds.front')}</Label>
          <Select
            className="h-6 w-40 text-small"
            ariaLabel={t('ds.front')}
            value={ds.front}
            options={[
              { value: 'default', label: t('ds.frontDefault') },
              { value: 'axes', label: t('ds.frontAxes') },
            ]}
            onChange={(v) => ds.setFront(v)}
          />
        </>
      }
      more={<Checkbox checked={st.infeasible} onChange={(v) => set({ infeasible: v })} label={<span className="text-small">{t('ds.showInfeasible')}</span>} title={t('ds.showInfeasibleHint')} />}
      actions={
        running ? (
          <>
            <div className="h-1.5 w-24 shrink-0 overflow-hidden rounded bg-hover" role="progressbar" aria-label={t('ds.progress')} aria-valuenow={progDone} aria-valuemin={0} aria-valuemax={progTotal}>
              <div className="h-full bg-accent transition-[width]" style={{ width: `${progTotal ? (100 * progDone) / progTotal : 0}%` }} />
            </div>
            <span className="num text-caption whitespace-nowrap text-muted">
              {prePhase ? `${t(`ds.phase.${ds.job?.phase}`)} ` : ''}
              {progDone}/{progTotal}
              {eta !== null ? ` · ${eta >= 90 ? t('ds.etaMin', { m: Math.round(eta / 60) }) : t('ds.eta', { s: Math.max(1, Math.round(eta)) })}` : ''}
            </span>
            <Button size="sm" onClick={() => void ds.cancel()} title={t('ds.cancelHint')}>
              <Square size={12} /> {t('c.cancel')}
            </Button>
          </>
        ) : (
          <Button size="sm" variant="primary" disabled={backend !== 'online' || (st.mode === 'forms' ? !st.topologies.length : !st.stock_catalogs.length)} onClick={run} title={t(st.mode === 'stock' ? 'ds.runStockHint' : 'ds.runHint')}>
            <Play size={12} /> {t('ds.run')}
          </Button>
        )
      }
    >
      <div className="grid h-full grid-cols-1 overflow-auto @3xl:grid-cols-[minmax(240px,280px)_1fr] @3xl:grid-rows-1 @3xl:overflow-hidden">
        {/* the specification */}
        <div className="flex flex-col gap-2 border-line p-3 @3xl:overflow-auto @3xl:border-r">
          <div className="flex rounded border border-line p-0.5" role="radiogroup" aria-label={t('ds.mode')}>
            {(['forms', 'stock'] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={st.mode === m}
                title={t(`ds.mode.${m}Hint`)}
                className={cx('flex-1 rounded px-2 py-0.5 text-small', st.mode === m ? 'bg-accent-soft font-medium text-accent' : 'text-muted hover:bg-hover')}
                onClick={() => set({ mode: m })}
              >
                {t(`ds.mode.${m}`)}
              </button>
            ))}
          </div>
          {st.mode === 'stock' ? (
            <StockSpecForm st={st} set={set} fromDesign={fromDesign} />
          ) : (
          <>
          <div className="flex items-center justify-between gap-2">
            <span className="text-small font-semibold">{t('ds.spec')}</span>
            <Button size="sm" variant="link" onClick={() => set(fromDesign, 'Design space: specification from the design')} title={t('ds.fromDesignHint')}>
              <Wand2 size={12} /> {t('ds.fromDesign')}
            </Button>
          </div>
          <div className="grid grid-cols-[1fr_auto] items-center gap-x-2 gap-y-1.5">
            <Label form hint={t('ds.focalHint')}>{t('ds.focal')}</Label>
            <NumberField className="h-6 w-24" ariaLabel={t('ds.focal')} value={st.focal_length} min={0.1} max={10000} onCommit={(v) => v && set({ focal_length: v })} />
            <Label form hint={t('ds.fnumHint')}>F/#</Label>
            <NumberField className="h-6 w-24" ariaLabel="F/#" value={st.f_number} min={0.7} max={100} onCommit={(v) => v && set({ f_number: v })} />
            <Label form hint={t('ds.fieldHint')}>{t('ds.field')}</Label>
            <NumberField className="h-6 w-24" ariaLabel={t('ds.field')} value={st.half_field_deg} min={0} max={40} onCommit={(v) => set({ half_field_deg: v ?? 0 })} />
            <Label form hint={t('ds.maxLengthHint')}>{t('ds.maxLength')}</Label>
            <NumberField className="h-6 w-24" ariaLabel={t('ds.maxLength')} optional placeholder={t('ds.noLimit')} value={st.max_length} min={0.1} onCommit={(v) => set({ max_length: v && v > 0 ? v : null })} />
          </div>
          <div className="text-caption text-muted" title={t('ds.wavelengthsHint')}>
            {t('ds.wavelengths')}: <span className="num">{project.system.wavelengths.map((w, i) => (i === prim ? `[${fmt(w.value * 1000, 5)}]` : fmt(w.value * 1000, 5))).join(', ')} nm</span>
          </div>
          <div className="flex flex-col gap-1">
            <Label form hint={t('ds.topologiesHint')}>{t('ds.topologies')}</Label>
            {DESIGN_TOPOLOGIES.map((k) => (
              <Checkbox
                key={k}
                checked={st.topologies.includes(k)}
                onChange={(v) => toggleTopo(k, v)}
                label={
                  <span className="text-small">
                    {t(`ds.topo.${k}`)} <span className="text-faint">· {t('ds.elements', { n: TOPOLOGY_ELEMENTS[k] })}</span>
                  </span>
                }
              />
            ))}
          </div>
          <div className="grid grid-cols-[1fr_auto] items-center gap-x-2 gap-y-1.5">
            <Label form hint={t('ds.candidatesHint')}>{t('ds.candidates')}</Label>
            <NumberField className="h-6 w-24" ariaLabel={t('ds.candidates')} integer value={st.candidates} min={1} max={600} onCommit={(v) => v && set({ candidates: Math.round(v) })} />
            <Label form hint={t('ds.mtfHint')}>{t('ds.mtfFreq')}</Label>
            <NumberField className="h-6 w-24" ariaLabel={t('ds.mtfFreq')} value={st.mtf_frequency} min={0.1} onCommit={(v) => v && set({ mtf_frequency: v })} />
            <Label form hint={t('ds.seedHint')}>{t('ds.seed')}</Label>
            <NumberField className="h-6 w-24" ariaLabel={t('ds.seed')} integer value={st.seed} min={0} onCommit={(v) => set({ seed: Math.round(v ?? 1) })} />
          </div>
          <Label form hint={t('ds.poolHint')}>{t('ds.pool')}</Label>
          <Select className="h-6 w-full text-small" ariaLabel={t('ds.pool')} value={poolOptions.some((o) => o.value === st.pool) ? st.pool : 'builtin'} options={poolOptions} onChange={(v) => set({ pool: v })} />
          <Checkbox checked={st.tolerances} onChange={(v) => set({ tolerances: v })} label={<span className="text-small">{t('ds.tolerances')}</span>} title={t('ds.tolerancesHint')} />
          </>
          )}
          {ds.job && (
            <div className="text-caption text-muted" role="status">
              {ds.job.state === 'running'
                ? t('ds.statusRunning', { d: ds.job.done, n: ds.job.total })
                : t('ds.statusDone', { n: all.length, f: all.filter((c) => c.feasible).length, p: ds.pareto.length, s: fmt(ds.job.elapsed_s, 3) })}
              {ds.job.failed > 0 && ` · ${t('ds.failed', { n: ds.job.failed })}`}
              {ds.job.state === 'cancelled' && ` · ${t('ds.cancelled')}`}
            </div>
          )}
          {ds.job?.notes?.map((n, i) => (
            <div key={i} className="text-caption text-faint">
              {n}
            </div>
          ))}
        </div>

        {/* the map, the selected design and the front */}
        <div className="flex min-h-0 flex-col @3xl:overflow-auto">
          {all.length === 0 ? (
            <div className="flex flex-1 items-center justify-center p-6 text-center text-small text-muted">{running ? t('ds.waiting') : t('ds.empty')}</div>
          ) : (
            <>
              <div ref={box} className="relative h-90 min-h-70 shrink-0 @3xl:h-[55%]" onMouseLeave={() => setHover(null)}>
                <Plot
                  data={data}
                  layout={layout}
                  onPointClick={(c) => ds.select(c as number)}
                  onPointHover={(c, ev) => setHover({ i: c as number, x: ev.clientX, y: ev.clientY })}
                  onPointUnhover={() => setHover(null)}
                />
                {hovered &&
                  hover &&
                  // in a portal: the view's container query makes it the containing block of fixed elements
                  createPortal(
                  <div
                    className="pointer-events-none fixed z-50 w-80 rounded border border-line bg-panel p-2 shadow-lg"
                    style={{
                      // beside the pointer, kept inside the window (the card is about 260 px high)
                      left: hover.x + 340 < window.innerWidth ? hover.x + 14 : hover.x - 334,
                      top: Math.max(4, Math.min(hover.y - 60, window.innerHeight - 270)),
                    }}
                  >
                    <div className="mb-1 flex items-center gap-1.5 text-small font-semibold">
                      {hovered.title}
                      {front.has(hovered.index) && <span className="rounded bg-accent/15 px-1 text-caption text-accent">{t('ds.onFront')}</span>}
                    </div>
                    {hovered.outline && <OutlineThumb outline={hovered.outline} className="mb-1 h-16 w-full" />}
                    <MetricTable c={hovered} mtfFreq={st.mtf_frequency} />
                    {!hovered.feasible && <div className="mt-1 text-caption text-warn">{(hovered.violations ?? []).map((v) => t(`ds.v.${v.kind}`)).join(' · ')}</div>}
                  </div>,
                  document.body,
                  )}
              </div>
              <div className="grid grid-cols-1 gap-3 border-t border-line p-3 @xl:grid-cols-2">
                <div className="min-w-0">
                  <div className="mb-1 text-small font-semibold">{selected ? selected.title : t('ds.selectHint')}</div>
                  {selected && selected.status === 'finished' && (
                    <>
                      {selected.outline && <OutlineThumb outline={selected.outline} className="mb-2 h-20 w-full" />}
                      <MetricTable c={selected} mtfFreq={st.mtf_frequency} />
                      {!selected.feasible && <div className="mt-1 text-caption text-warn">{(selected.violations ?? []).map((v) => t(`ds.v.${v.kind}`)).join(' · ')}</div>}
                      <div className="mt-2 flex flex-wrap gap-2">
                        <Button size="sm" variant="primary" onClick={() => ds.job && void openDesignCandidate(ds.job.id, selected.index, 'project')} title={t('ds.openProjectHint')}>
                          <FolderPlus size={12} /> {t('ds.openProject')}
                        </Button>
                        <Button size="sm" onClick={() => ds.job && void openDesignCandidate(ds.job.id, selected.index, 'revision')} title={t('ds.openRevisionHint')}>
                          <GitCommitHorizontal size={12} /> {t('ds.openRevision')}
                        </Button>
                      </div>
                    </>
                  )}
                </div>
                <div className="min-w-0">
                  <div className="mb-1 text-small font-semibold" title={t('ds.frontHint')}>
                    {t('ds.frontList', { n: frontRows.length })} <span className="font-normal text-muted">({objectiveNames})</span>
                  </div>
                  <div className="max-h-56 overflow-auto">
                    <table className="w-full text-small">
                      <thead className="text-caption text-muted">
                        <tr>
                          <th className="text-left font-normal">{t('ds.design')}</th>
                          {ds.objectives.map((k) => (
                            <th key={k} className="text-right font-normal">
                              {t(`ds.short.${k}`)}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {frontRows.map((c) => (
                          <tr key={c.index} className={cx('cursor-pointer hover:bg-hover', ds.selected === c.index && 'bg-accent/10')} onClick={() => ds.select(c.index)}>
                            <td className="truncate pr-2">
                              <button type="button" className="text-left hover:underline" onClick={() => ds.select(c.index)}>
                                {c.title}
                              </button>
                            </td>
                            {ds.objectives.map((k) => (
                              <td key={k} className="num text-right">
                                {metricValue(c, k) === null ? '—' : fmt(metricValue(c, k) as number, 3)}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </AnalysisFrame>
  )
}
