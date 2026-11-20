import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import type { CoatingPerformance } from '../../lib/types'
import { useUiStore } from '../../store/uiStore'
import { Plot, type Trace } from '../common/Plot'
import { Button, Checkbox, Select } from '../common/ui'
import { useAnalysisSettings } from '../common/useAnalysisSettings'
import { AnalysisFrame } from './AnalysisFrame'
import { useAnalysis } from './useAnalysis'
import { DATA, SERIES } from '../../lib/palette'

type Settings = { angle: 'normal' | 'mean' | 'max'; quantity: 'R' | 'T'; log: boolean; include_uncoated: boolean }
const DEFAULTS: Settings = { angle: 'mean', quantity: 'R', log: false, include_uncoated: true }
const COLORS = SERIES

/** Coatings of the system: each coated (and bare) surface's R or T vs wavelength at its real ray angles, and the system transmission spectrum. */
export function CoatingsView() {
  const t = useT()
  const [st, set] = useAnalysisSettings('coatings_view', DEFAULTS, 'Coatings view settings')
  const { data, error, loading, ms, refresh } = useAnalysis<CoatingPerformance>('coatings', { samples: 161, include_uncoated: st.include_uncoated })
  const traces: Trace[] = []
  if (data) {
    data.surfaces.forEach((r, k) => {
      const ys = (st.quantity === 'R' ? r.R : r.T)[st.angle]
      traces.push({
        type: 'scatter',
        mode: 'lines',
        x: data.lambda_nm,
        y: ys.map((v) => Math.max(v * 100, st.log ? 1e-6 : -1)),
        name: `S${r.surface}${r.coating ? ` ${r.coating}` : r.mirror ? ' mirror (ideal)' : ' bare'}`,
        line: { color: COLORS[k % COLORS.length], width: r.coating ? 1.8 : 1, dash: r.coating ? 'solid' : 'dot' },
        hovertemplate: `S${r.surface}: %{y:.4f} %<br>%{x:.1f} nm<extra></extra>`,
      })
    })
  }
  const lines = (data?.system_wavelengths_nm ?? []).map((w) => ({ type: 'line', x0: w, x1: w, yref: 'paper', y0: 0, y1: 1, line: { width: 1, dash: 'dot', color: 'rgba(133,147,165,0.6)' } }))
  return (
    <AnalysisFrame
      kind="coatings"
      title={t('view.coatings')}
      loading={loading}
      error={error}
      hasData={!!data}
      ms={ms}
      method={data?.method}
      onRefresh={refresh}
      settings={{ include_uncoated: st.include_uncoated }}
      result={data}
      controls={
        <>
          <Select className="h-6 w-14 text-small" ariaLabel={t('cv.quantity')} value={st.quantity} options={[{ value: 'R', label: 'R' }, { value: 'T', label: 'T' }]} onChange={(v) => set({ quantity: v })} />
          <Select
            className="h-6 w-[150px] text-small"
            ariaLabel={t('cv.angle')}
            value={st.angle}
            options={[
              { value: 'mean', label: t('cv.meanAngle') },
              { value: 'max', label: t('cv.maxAngle') },
              { value: 'normal', label: t('cv.normal') },
            ]}
            onChange={(v) => set({ angle: v })}
          />
        </>
      }
      more={
        <>
          <span className="w-full">
            <Checkbox checked={st.log} onChange={(v) => set({ log: v })} label={<span className="text-small text-muted">{t('an.log')}</span>} />
          </span>
          <span className="w-full">
            <Checkbox checked={st.include_uncoated} onChange={(v) => set({ include_uncoated: v })} label={<span className="text-small text-muted">{t('cv.bare')}</span>} />
          </span>
        </>
      }
    >
      {data && (
        <div className="grid h-full min-h-0 grid-rows-[minmax(0,1.4fr)_minmax(0,1fr)] gap-px bg-line">
          <div className="grid min-h-0 grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] gap-px">
            <div className="min-h-0 bg-panel">
              <Plot
                data={traces}
                layout={{
                  margin: { l: 50, r: 10, t: 22, b: 36 },
                  title: { text: `${st.quantity} ${t('cv.perSurface')} (${st.angle === 'normal' ? '0°' : st.angle === 'mean' ? t('cv.meanAngle') : t('cv.maxAngle')})`, font: { size: 11 } },
                  xaxis: { title: { text: 'λ (nm)' } },
                  yaxis: st.log ? { title: { text: `${st.quantity} (%)` }, type: 'log' } : { title: { text: `${st.quantity} (%)` }, rangemode: 'tozero' },
                  shapes: lines,
                  legend: { orientation: 'h', y: 1.14, font: { size: 10 } },
                }}
              />
            </div>
            <div className="min-h-0 bg-panel">
              <Plot
                data={[{ type: 'scatter', mode: 'lines', x: data.lambda_nm, y: data.system_transmission_estimate.map((v) => v * 100), line: { color: DATA.tertiary, width: 2 }, name: 'T', hovertemplate: '%{x:.1f} nm<br>T %{y:.3f} %<extra></extra>' }]}
                layout={{ margin: { l: 50, r: 10, t: 22, b: 36 }, title: { text: t('cv.system'), font: { size: 11 } }, xaxis: { title: { text: 'λ (nm)' } }, yaxis: { title: { text: 'T (%)' } }, shapes: lines, showlegend: false }}
              />
            </div>
          </div>
          <div className="min-h-0 overflow-auto bg-panel">
            <table className="eng-table">
              <thead>
                <tr>
                  <th className="text-right">{t('cv.surface')}</th>
                  <th>{t('ins.coating')}</th>
                  <th>{t('cv.media')}</th>
                  <th className="text-right">θ min</th>
                  <th className="text-right">θ {t('cv.mean')}</th>
                  <th className="text-right">θ max</th>
                  <th className="text-right">R {t('cv.atPrimary')}</th>
                  <th className="text-right">{t('cv.bandMax')}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.surfaces.map((r) => {
                  const prim = data.system_wavelengths_nm.length ? data.system_wavelengths_nm.reduce((a, b) => a + b, 0) / data.system_wavelengths_nm.length : data.lambda_nm[Math.floor(data.lambda_nm.length / 2)]
                  const k = data.lambda_nm.reduce((b, x, j) => (Math.abs(x - prim) < Math.abs(data.lambda_nm[b] - prim) ? j : b), 0)
                  const lo = Math.min(...data.system_wavelengths_nm)
                  const hi = Math.max(...data.system_wavelengths_nm)
                  const inBand = r.R.mean.filter((_, j) => data.lambda_nm[j] >= lo && data.lambda_nm[j] <= hi)
                  return (
                    <tr key={r.surface}>
                      <td className="num px-2 text-right">{r.surface}</td>
                      <td className="px-2">{r.coating ?? (r.mirror ? <span className="text-faint">ideal mirror</span> : <span className="text-faint">bare</span>)}</td>
                      <td className="px-2 text-muted">{r.mirror ? `${r.media[0]} | mirror` : r.media.join(' | ')}</td>
                      <td className="num px-2 text-right">{fmt(r.angles_deg.min, 3)}°</td>
                      <td className="num px-2 text-right">{fmt(r.angles_deg.mean, 3)}°</td>
                      <td className="num px-2 text-right">{fmt(r.angles_deg.max, 3)}°</td>
                      <td className="num px-2 text-right">{fmt(r.R.mean[k] * 100, 4)} %</td>
                      <td className="num px-2 text-right">{inBand.length ? `${fmt(Math.max(...inBand) * 100, 4)} %` : '—'}</td>
                      <td className="px-1">
                        <Button variant="link" onClick={() => useUiStore.getState().openDialog('coatingDesigner', { surfaces: [r.surface] })}>
                          {t('cd.designFor')}
                        </Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <div className="px-3 py-1 text-caption text-faint">{t('cv.note')}</div>
          </div>
        </div>
      )}
    </AnalysisFrame>
  )
}
