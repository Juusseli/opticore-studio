import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { DATA, SERIES } from '../../lib/palette'
import type { SpectrometerResult } from '../../lib/types'
import { useProjectStore } from '../../store/projectStore'
import { FieldSelect, Label, Pair, Stat } from '../common/controls'
import { Plot, type Trace } from '../common/Plot'
import { NumberField } from '../common/ui'
import { useAnalysisSettings } from '../common/useAnalysisSettings'
import { AnalysisFrame } from './AnalysisFrame'
import { SPECTROMETER_DEFAULTS, type SpectrometerSettings } from './spectrometerSettings'
import { useAnalysis } from './useAnalysis'
import { Notes } from './WaveViews'

const UM: Record<string, number> = { um: 1, µm: 1, nm: 1e-3 }

function Chart({ title, traces, y, log }: { title: string; traces: Trace[]; y: string; log?: boolean }) {
  return (
    <div className="flex min-h-0 flex-col bg-panel">
      <div className="shrink-0 px-3 pt-1.5 text-small font-semibold tracking-wide text-muted uppercase">{title}</div>
      <div className="min-h-0 flex-1">
        <Plot data={traces} layout={{ margin: { l: 58, r: 10, t: 6, b: 36 }, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, xaxis: { title: { text: 'λ (nm)' } }, yaxis: { title: { text: y }, type: log ? 'log' : 'linear' } }} />
      </div>
    </div>
  )
}

export function SpectrometerView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const [st, set] = useAnalysisSettings<SpectrometerSettings>('spectrometer', SPECTROMETER_DEFAULTS)
  const settings: SpectrometerSettings = { ...SPECTROMETER_DEFAULTS, ...st, field: Math.min(st.field ?? 0, system.fields.length - 1) }
  const { data, error, loading, ms, refresh } = useAnalysis<SpectrometerResult>('spectrometer', settings as unknown as Record<string, unknown>)
  const nm = data ? data.wavelength_um.map((x) => x * 1000) : []
  const mid = data ? Math.floor(data.wavelength_um.length / 2) : 0
  const g = data?.grating
  const resGeo = data?.resolution_nm ?? []
  return (
    <AnalysisFrame
      kind="spectrometer"
      title={t('view.spectrometer')}
      loading={loading}
      error={error}
      hasData={!!data}
      ms={ms}
      method={data?.method}
      onRefresh={refresh}
      settings={settings as unknown as Record<string, unknown>}
      result={data}
      controls={
        <>
          <FieldSelect system={system} value={settings.field} onChange={(v) => set({ field: v })} />
          <Pair>
            <Label hint={t('sp.rangeHint')}>λ (µm)</Label>
            <NumberField className="h-6 w-16" ariaLabel={t('sp.from')} value={settings.wl_min_um} min={0.01} max={100} units={UM} onCommit={(v) => set({ wl_min_um: v })} />
            <span className="text-muted">–</span>
            <NumberField className="h-6 w-16" ariaLabel={t('sp.to')} value={settings.wl_max_um} min={0.01} max={100} units={UM} onCommit={(v) => set({ wl_max_um: v })} />
          </Pair>
        </>
      }
      more={
        <>
          <Pair>
            <Label hint={t('sp.pointsHint')}>{t('sp.points')}</Label>
            <NumberField className="h-6 w-14" ariaLabel={t('sp.points')} value={settings.points} integer min={3} max={201} onCommit={(v) => set({ points: Math.round(v ?? 41) })} />
          </Pair>
          <Pair>
            <Label hint={t('sp.densityHint')}>{t('sp.density')}</Label>
            <NumberField className="h-6 w-12" ariaLabel={t('sp.density')} value={settings.density} integer min={2} max={12} onCommit={(v) => set({ density: Math.round(v ?? 6) })} />
          </Pair>
        </>
      }
    >
      {data && (
        <div className="flex h-full min-h-0 flex-col overflow-y-auto">
          <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
            <Stat label={t('sp.span')} value={fmt(data.span_mm, 5)} unit="mm" />
            <Stat label={t('sp.dispersion')} value={fmt(Math.abs(data.dispersion_mm_per_nm[mid] ?? 0), 5)} unit={`mm/nm @ ${fmt(nm[mid], 5)} nm`} />
            <Stat label={t('sp.reciprocal')} value={fmt(Math.abs(data.reciprocal_nm_per_mm[mid] ?? 0), 5)} unit="nm/mm" />
            <Stat label={t('sp.resolution')} value={resGeo[mid] !== null && resGeo[mid] !== undefined ? fmt(resGeo[mid]!, 4) : t('sp.diffraction')} unit={resGeo[mid] ? 'nm' : undefined} />
            {g && <Stat label={t('sp.gratingR')} value={fmt(g.resolving_power[mid] ?? 0, 6)} unit={`${fmt(g.resolution_nm[mid] ?? 0, 4)} nm`} />}
          </div>
          <div className="grid min-h-[240px] flex-1 auto-rows-[minmax(240px,1fr)] grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-px bg-line">
            <Chart
              title={t('sp.calibration')}
              y={t('sp.position')}
              traces={[{ type: 'scatter', mode: 'lines+markers', name: t('sp.position'), x: nm, y: data.position_mm, line: { color: DATA.primary, width: 1.8 }, marker: { size: 4 }, hovertemplate: '%{x:.2f} nm<br>%{y:.5f} mm<extra></extra>' }]}
            />
            <Chart
              title={t('sp.dispersionTitle')}
              y="mm/nm"
              traces={[{ type: 'scatter', mode: 'lines', name: 'dy/dλ', x: nm, y: data.dispersion_mm_per_nm.map((v) => (v === null ? null : Math.abs(v))), line: { color: SERIES[1], width: 1.8 }, hovertemplate: '%{x:.2f} nm<br>%{y:.6f} mm/nm<extra></extra>' }]}
            />
            <Chart
              title={t('sp.resolutionTitle')}
              y="Δλ (nm)"
              log
              traces={[
                ...(resGeo.some((v) => v !== null) ? [{ type: 'scatter', mode: 'lines', name: t('sp.geometric'), x: nm, y: resGeo, line: { color: SERIES[2], width: 1.8 } } as Trace] : []),
                ...(g ? [{ type: 'scatter', mode: 'lines', name: t('sp.gratingLimit', { m: g.order, n: fmt(g.lines_per_mm, 5) }), x: nm, y: g.resolution_nm, line: { color: SERIES[3], width: 1.4, dash: 'dash' } } as Trace] : []),
              ]}
            />
          </div>
          <Notes notes={data.notes} />
        </div>
      )}
    </AnalysisFrame>
  )
}
