import { Plus, RotateCcw, X } from 'lucide-react'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import type { OperandType, OpticalSystem, SweepResult, VariableParam } from '../../lib/types'
import { useProjectStore } from '../../store/projectStore'
import { Plot, type Trace } from '../common/Plot'
import { Button, Checkbox, IconButton, NumberField, Select } from '../common/ui'
import { surfaceTitle } from '../editors/surfaceTitle'
import { AnalysisFrame } from './AnalysisFrame'
import { useAnalysis } from './useAnalysis'
import { COLORMAPS, DATA } from '../../lib/palette'

type SweepParam = { surface_id: string; parameter: VariableParam; configuration: number | null; start: number; stop: number; steps: number }
type SweepMetric = { type: OperandType; frequency?: number | null }
export type SweepSettings = { parameters: SweepParam[]; metrics: SweepMetric[]; show: number }

// labels are i18n keys, translated in the view
const PARAMS: { value: VariableParam; key: string }[] = [
  { value: 'curvature', key: 'lde.radius' },
  { value: 'thickness', key: 'par.thickness' },
  { value: 'conic', key: 'par.conic' },
  { value: 'decenter_x', key: 'par.decenter_x' },
  { value: 'decenter_y', key: 'par.decenter_y' },
  { value: 'tilt_x', key: 'par.tilt_x' },
  { value: 'tilt_y', key: 'par.tilt_y' },
]

const METRICS: { type: OperandType; key: string; frequency?: number }[] = [
  { type: 'rms_spot', key: 'sw.m.rms_spot' },
  { type: 'rms_wavefront', key: 'sw.m.rms_wavefront' },
  { type: 'efl', key: 'sw.m.efl' },
  { type: 'bfl', key: 'sw.m.bfl' },
  { type: 'working_fnum', key: 'sw.m.working_fnum' },
  { type: 'distortion', key: 'sw.m.distortion' },
  { type: 'axial_color', key: 'sw.m.axial_color' },
  { type: 'throughput', key: 'sw.m.throughput' },
  { type: 'mtf', key: 'sw.m.mtf', frequency: 50 },
]

function currentValue(sys: OpticalSystem, sid: string, p: VariableParam): number | null {
  const s = sys.surfaces.find((x) => x.id === sid)
  if (!s) return null
  if (p === 'curvature') return s.radius
  if (p === 'thickness') return s.thickness
  if (p === 'conic') return s.conic
  return (s as unknown as Record<string, number>)[p] ?? 0
}

function defaultRange(sys: OpticalSystem, sid: string, p: VariableParam): [number, number] {
  const v = currentValue(sys, sid, p)
  if (p === 'curvature') return v === null ? [500, 1000] : [v * 0.9, v * 1.1]
  if (p === 'thickness') {
    const t = v ?? 0
    const d = Math.max(1, Math.abs(t) * 0.05)
    return [t - d, t + d]
  }
  if (p === 'conic') return [(v ?? 0) - 0.5, (v ?? 0) + 0.5]
  if (p.startsWith('tilt')) return [-1, 1]
  return [-0.5, 0.5]
}

function defaultSweep(sys: OpticalSystem): SweepSettings {
  const n = sys.surfaces.length
  const bf = sys.surfaces[n - 2]
  const [a, b] = defaultRange(sys, bf.id, 'thickness')
  return { parameters: [{ surface_id: bf.id, parameter: 'thickness', configuration: null, start: a, stop: b, steps: 21 }], metrics: [{ type: 'rms_spot' }, { type: 'efl' }], show: 0 }
}

export function SweepView() {
  const t = useT()
  const params = PARAMS.map((x) => ({ value: x.value, label: t(x.key) }))
  const metrics = METRICS.map((x) => ({ type: x.type, label: t(x.key), frequency: x.frequency }))
  const system = useProjectStore((s) => s.project.system)
  const stored = useProjectStore((s) => s.project.analysis_settings.sweep) as SweepSettings | undefined
  const update = useProjectStore((s) => s.updateProject)
  const n = system.surfaces.length
  const valid = stored && stored.parameters.every((p) => system.surfaces.some((s) => s.id === p.surface_id)) ? stored : defaultSweep(system)
  const st = valid
  const set = (patch: Partial<SweepSettings>) => update((p) => void (p.analysis_settings.sweep = { ...st, ...patch }), 'Sweep settings')
  const setParam = (k: number, patch: Partial<SweepParam>) => set({ parameters: st.parameters.map((p, j) => (j === k ? { ...p, ...patch } : p)) })
  const settings = {
    parameters: st.parameters.map((p) => ({ ...p })),
    metrics: st.metrics.map((m) => ({ type: m.type, rings: 3, ...(m.frequency ? { frequency: m.frequency } : {}) })),
  }
  const { data, error, loading, ms, refresh } = useAnalysis<SweepResult>('sweep', settings)
  const surfOpts = system.surfaces
    .map((s, i) => ({ s, i }))
    .filter(({ i }) => i > 0 && i < n - 1)
    .map(({ s, i }) => ({ value: s.id, label: `${i}: ${surfaceTitle(s, i, n)}` }))
  const mc = system.multi_config

  const paramRow = (p: SweepParam, k: number) => (
    <div key={k} className="flex flex-wrap items-center gap-1.5">
      <span className="w-5 text-small font-semibold text-muted">{k === 0 ? 'X' : 'Y'}</span>
      <Select className="h-6 w-[150px] text-small" ariaLabel={t('c.surface')} value={p.surface_id} options={surfOpts} onChange={(v) => { const [a, b] = defaultRange(system, v, p.parameter); setParam(k, { surface_id: v, start: a, stop: b }) }} />
      <Select className="h-6 w-[110px] text-small" ariaLabel={t('opt.parameter')} value={p.parameter} options={params} onChange={(v) => { const [a, b] = defaultRange(system, p.surface_id, v); setParam(k, { parameter: v, start: a, stop: b }) }} />
      {mc && <Select className="h-6 w-[110px] text-small" value={p.configuration ?? -1} ariaLabel={t('mc.config')} options={[{ value: -1, label: t('sw.base') }, ...mc.names.map((nm, j) => ({ value: j, label: `C${j + 1}: ${nm}` }))]} onChange={(v) => setParam(k, { configuration: v < 0 ? null : v })} />}
      <NumberField className="h-6 w-20" value={p.start} onCommit={(v) => setParam(k, { start: v ?? p.start })} />
      <span className="text-faint">→</span>
      <NumberField className="h-6 w-20" value={p.stop} onCommit={(v) => setParam(k, { stop: v ?? p.stop })} />
      <NumberField className="h-6 w-12" value={p.steps} integer min={2} max={k === 0 && st.parameters.length === 1 ? 401 : 51} onCommit={(v) => setParam(k, { steps: v ?? 21 })} />
      <span className="text-caption text-faint">{p.parameter === 'curvature' ? 'R mm' : p.parameter.startsWith('tilt') ? '°' : p.parameter === 'conic' ? '' : 'mm'} · {t('sw.now')} {fmt(currentValue(system, p.surface_id, p.parameter), 6)}</span>
      <IconButton size="sm" title={t('sw.reset')} onClick={() => { const [a, b] = defaultRange(system, p.surface_id, p.parameter); setParam(k, { start: a, stop: b }) }}>
        <RotateCcw size={12} />
      </IconButton>
      {k === 1 && (
        <IconButton size="sm" tone="danger" title={t('sw.remove')} onClick={() => set({ parameters: st.parameters.slice(0, 1) })}>
          <X size={12} />
        </IconButton>
      )}
    </div>
  )

  const metricLabel = (type: OperandType) => metrics.find((m) => m.type === type)?.label ?? type
  const twoD = data && data.axes.length === 2
  const plots: { title: string; traces: Trace[]; layout: Record<string, unknown> }[] = []
  if (data && !twoD) {
    const p = data.parameters[0]
    data.metrics.forEach((m) => {
      const vals = m.values as (number | null)[]
      plots.push({
        title: `${metricLabel(m.type as OperandType)}${m.unit ? ` (${m.unit === 'um' ? 'µm' : m.unit})` : ''}`,
        traces: [
          { type: 'scatter', mode: 'lines+markers', x: data.axes[0], y: vals, marker: { size: 4 }, line: { width: 1.8, color: DATA.primary }, hovertemplate: '%{x:.6g} → %{y:.6g}<extra></extra>' },
          ...(p.current !== null ? [{ type: 'scatter', mode: 'markers', x: [p.current], y: [m.nominal], marker: { size: 9, color: DATA.marker, symbol: 'diamond' }, hovertemplate: `${t('sw.current')}<extra></extra>` }] : []),
        ],
        layout: { showlegend: false, margin: { l: 56, r: 12, t: 26, b: 40 }, title: { text: `${metricLabel(m.type as OperandType)}${m.unit ? ` (${m.unit === 'um' ? 'µm' : m.unit})` : ''}`, font: { size: 12 } }, xaxis: { title: { text: `${params.find((x) => x.value === p.parameter)?.label} S${system.surfaces.findIndex((s) => s.id === p.surface_id)} (${p.parameter === 'curvature' ? 'R, mm' : p.unit})` } } },
      })
    })
  }
  const showIdx = Math.min(st.show, (data?.metrics.length ?? 1) - 1)
  return (
    <AnalysisFrame kind="sweep" title={t('view.sweep')} loading={loading} error={error} hasData={!!data} ms={ms} method={data?.method} onRefresh={refresh} settings={settings} result={data}>
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex shrink-0 flex-col gap-1 border-b border-line px-2.5 py-1.5">
          {st.parameters.map(paramRow)}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {st.parameters.length === 1 && (
              <Button size="sm" variant="ghost" onClick={() => { const sid = surfOpts[0]?.value; if (!sid) return; const [a, b] = defaultRange(system, sid, 'curvature'); set({ parameters: [...st.parameters, { surface_id: sid, parameter: 'curvature', configuration: null, start: a, stop: b, steps: 11 }] }) }}>
                <Plus size={12} /> {t('sw.addY')}
              </Button>
            )}
            {metrics.map((m) => (
              <Checkbox
                key={m.type}
                checked={st.metrics.some((x) => x.type === m.type)}
                onChange={(on) => set({ metrics: on ? [...st.metrics, { type: m.type, frequency: m.frequency ?? null }] : st.metrics.filter((x) => x.type !== m.type) })}
                label={<span className="text-small text-muted">{m.label}</span>}
              />
            ))}
            {twoD && data && <Select className="h-6 w-[150px] text-small" value={showIdx} options={data.metrics.map((m, k) => ({ value: k, label: metricLabel(m.type as OperandType) }))} onChange={(v) => set({ show: v })} />}
          </div>
          {data && data.errors.length > 0 && <div className="truncate text-small text-warn" title={data.errors.join('\n')}>{data.errors[0]}</div>}
        </div>
        {data && !twoD && (
          <div className="grid min-h-0 flex-1 auto-rows-[minmax(220px,1fr)] grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-px overflow-auto bg-line">
            {plots.map((p) => (
              <div key={p.title} className="min-h-0 bg-panel">
                <Plot data={p.traces} layout={p.layout} />
              </div>
            ))}
          </div>
        )}
        {data && twoD && (
          <div className="min-h-0 flex-1">
            <Plot
              data={[
                {
                  type: 'contour',
                  x: data.axes[0],
                  y: data.axes[1],
                  z: transpose(data.metrics[showIdx].values as (number | null)[][]),
                  colorscale: COLORMAPS.sequentialAlt,
                  contours: { coloring: 'heatmap', showlabels: true, labelfont: { size: 9, color: DATA.overlay } },
                  colorbar: { title: { text: data.metrics[showIdx].unit === 'um' ? 'µm' : data.metrics[showIdx].unit }, thickness: 12 },
                  hovertemplate: 'x %{x:.6g}<br>y %{y:.6g}<br>%{z:.6g}<extra></extra>',
                },
                { type: 'scatter', mode: 'markers', x: [data.parameters[0].current], y: [data.parameters[1].current], marker: { size: 10, color: DATA.marker, symbol: 'diamond' }, hovertemplate: `${t('sw.current')}<extra></extra>` },
              ]}
              layout={{
                showlegend: false,
                xaxis: { title: { text: `${params.find((x) => x.value === data.parameters[0].parameter)?.label} S${system.surfaces.findIndex((s) => s.id === data.parameters[0].surface_id)}` } },
                yaxis: { title: { text: `${params.find((x) => x.value === data.parameters[1].parameter)?.label} S${system.surfaces.findIndex((s) => s.id === data.parameters[1].surface_id)}` } },
              }}
            />
          </div>
        )}
        {data && <div className="shrink-0 border-t border-line px-3 py-1 text-caption text-faint">{data.points} {t('sw.points')} · {data.elapsed_s.toFixed(2)} s · {t('sw.help')}</div>}
      </div>
    </AnalysisFrame>
  )
}

function transpose(a: (number | null)[][]): (number | null)[][] {
  return a[0].map((_, j) => a.map((r) => r[j]))
}
