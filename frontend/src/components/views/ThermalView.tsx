import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { DATA } from '../../lib/palette'
import type { ThermalResult } from '../../lib/types'
import { Label, Row, Stat } from '../common/controls'
import { Plot, type Trace } from '../common/Plot'
import { NumberField, Select } from '../common/ui'
import { useAnalysisSettings } from '../common/useAnalysisSettings'
import { AnalysisFrame } from './AnalysisFrame'
import { useAnalysis } from './useAnalysis'

const DEFAULTS = { variable: 'temperature' as 'temperature' | 'pressure', t0: -20, t1: 60, p0: 0, p1: 1, steps: 9, density: 6 }

/** Focus shift, EFL and RMS spot across a temperature or pressure range (engine: analysis/thermal.py). */
export function ThermalView() {
  const t = useT()
  const [st, set] = useAnalysisSettings('thermal', DEFAULTS)
  const temp = st.variable === 'temperature'
  const settings = { variable: st.variable, start: temp ? st.t0 : st.p0, stop: temp ? st.t1 : st.p1, steps: st.steps, density: st.density }
  const { data, error, loading, ms, refresh } = useAnalysis<ThermalResult>('thermal', settings)
  const unit = temp ? '°C' : 'atm'
  const perUnit = temp ? 'K' : 'atm'
  const ok = data ? data.rows.filter((r) => r.error === undefined && r.best_focus_mm !== null && r.best_focus_mm !== undefined) : []
  const x = ok.map((r) => r.value)
  const dof = data?.reference?.depth_of_focus_mm ?? null
  // the depth of focus about the best focus at the system's own temperature: the band the thermal shift must stay in
  const focus0 = (data?.reference?.best_focus_mm ?? 0) * 1e3
  const ref = data?.reference?.value ?? null
  const spread = data?.focus_spread_mm ?? null
  const ratio = spread !== null && dof ? spread / (2 * dof) : null
  const axisX = { title: { text: t(temp ? 'ax.temperature' : 'ax.pressure') } }
  const refLine = ref !== null ? [{ type: 'line', x0: ref, x1: ref, yref: 'paper', y0: 0, y1: 1, line: { color: DATA.marker, width: 1, dash: 'dot' } }] : []

  const focusTraces: Trace[] = [
    { type: 'scatter', mode: 'lines+markers', x, y: ok.map((r) => (r.best_focus_mm ?? 0) * 1e3), name: t('th.bestFocus'), line: { color: DATA.primary, width: 2 }, marker: { size: 5 }, hovertemplate: `%{x:.4g} ${unit}: %{y:.4g} µm<extra></extra>` },
  ]
  const focusShapes =
    dof !== null && x.length
      ? [{ type: 'rect', xref: 'paper', x0: 0, x1: 1, y0: focus0 - dof * 1e3, y1: focus0 + dof * 1e3, fillcolor: DATA.fill, line: { width: 0 }, layer: 'below' }, ...refLine]
      : refLine
  const rmsTraces: Trace[] = [
    { type: 'scatter', mode: 'lines+markers', x, y: ok.map((r) => r.rms_um ?? null), name: t('th.rmsImage'), line: { color: DATA.primary, width: 2 }, marker: { size: 5 } },
    { type: 'scatter', mode: 'lines', x, y: ok.map((r) => r.rms_best_um ?? null), name: t('th.rmsBest'), line: { color: DATA.secondary, width: 1.6, dash: 'dash' } },
  ]
  const efl0 = data?.reference?.efl_mm ?? null
  const eflTraces: Trace[] = [
    { type: 'scatter', mode: 'lines+markers', x, y: ok.map((r) => (efl0 !== null && r.efl_mm !== undefined ? (r.efl_mm - efl0) * 1e3 : null)), name: t('th.eflChange'), line: { color: DATA.tertiary, width: 2 }, marker: { size: 5 } },
  ]
  const plots: { key: string; data: Trace[]; y: string; shapes: unknown[] }[] = [
    { key: 'focus', data: focusTraces, y: t('ax.bestFocus'), shapes: focusShapes },
    { key: 'rms', data: rmsTraces, y: t('ax.rmsUm'), shapes: refLine },
    { key: 'efl', data: eflTraces, y: t('ax.eflChange'), shapes: refLine },
  ]

  return (
    <AnalysisFrame
      kind="thermal"
      title={t('view.thermal')}
      loading={loading}
      error={error}
      hasData={!!data}
      ms={ms}
      method={data?.method}
      onRefresh={refresh}
      settings={settings}
      result={data}
      controls={
        <>
          <Select<'temperature' | 'pressure'>
            className="h-6 w-32 text-small"
            ariaLabel={t('th.variable')}
            value={st.variable}
            options={[
              { value: 'temperature', label: t('th.temperature') },
              { value: 'pressure', label: t('th.pressure') },
            ]}
            onChange={(v) => set({ variable: v })}
          />
          <Label hint={t('th.rangeHint')}>{t('th.range', { unit })}</Label>
          <NumberField className="h-6 w-16" ariaLabel={`${t('th.from')} (${unit})`} value={temp ? st.t0 : st.p0} min={temp ? -273 : 0} max={1000} onCommit={(v) => v !== null && set(temp ? { t0: v } : { p0: v })} />
          <span className="text-small text-faint">…</span>
          <NumberField className="h-6 w-16" ariaLabel={`${t('th.to')} (${unit})`} value={temp ? st.t1 : st.p1} min={temp ? -273 : 0} max={1000} onCommit={(v) => v !== null && set(temp ? { t1: v } : { p1: v })} />
        </>
      }
      more={
        <>
          <Row label={t('th.steps')} hint={t('th.stepsHint')}>
            <NumberField className="h-6 w-20" ariaLabel={t('th.steps')} value={st.steps} integer min={2} max={41} onCommit={(v) => set({ steps: v ?? 9 })} />
          </Row>
          <Row label={t('an.density')} hint={t('an.densityHint')}>
            <NumberField className="h-6 w-20" ariaLabel={t('an.density')} value={st.density} integer min={2} max={20} onCommit={(v) => set({ density: v ?? 6 })} />
          </Row>
        </>
      }
    >
      {data && (
        <div className="flex h-full min-h-0 flex-col">
          {data.notes.length > 0 && <div className="shrink-0 border-b border-line px-3 py-1.5 text-small text-warn">{data.notes.join(' ')}</div>}
          <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
            <Stat label={t('th.focusSlope', { u: perUnit })} value={fmt((data.slopes_per_unit.best_focus_mm ?? NaN) * 1e3, 3)} unit={`µm/${perUnit}`} />
            <Stat label={t('th.spread')} value={fmt((spread ?? NaN) * 1e3, 3)} unit="µm" tone={ratio === null ? undefined : ratio > 1 ? 'warn' : 'ok'} />
            <Stat label={t('th.dof')} value={dof === null ? '—' : `±${fmt(dof * 1e3, 3)}`} unit="µm" />
            <Stat label={t('th.eflSlope', { u: perUnit })} value={fmt((data.slopes_per_unit.efl_mm ?? NaN) * 1e3, 3)} unit={`µm/${perUnit}`} />
            <Stat label={t('th.at', { v: ref === null ? '—' : fmt(ref, 4), unit })} value={data.reference ? fmt(data.reference.efl_mm, 7) : '—'} unit="mm EFL" />
          </div>
          {ratio !== null && <div className={`shrink-0 px-3 py-1 text-small ${ratio > 1 ? 'text-warn' : 'text-muted'}`}>{t(ratio > 1 ? 'th.verdictOut' : 'th.verdictIn', { r: fmt(ratio, 2) })}</div>}
          <div className="grid min-h-0 flex-1 auto-rows-[minmax(220px,1fr)] grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-px overflow-auto bg-line">
            {plots.map((p) => (
              <div key={p.key} className="min-h-0 bg-panel">
                <Plot data={p.data} layout={{ xaxis: axisX, yaxis: { title: { text: p.y } }, shapes: p.shapes, margin: { l: 60, r: 14, t: 26, b: 44 }, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom', font: { size: 10 } } }} />
              </div>
            ))}
          </div>
        </div>
      )}
    </AnalysisFrame>
  )
}
