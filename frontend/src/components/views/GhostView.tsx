import { useState } from 'react'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import type { GhostResult } from '../../lib/types'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { Plot, type Trace } from '../common/Plot'
import { cx } from '../common/uiUtils'
import { FieldSelect, WavelengthSelect } from '../common/controls'
import { useAnalysisSettings } from '../common/useAnalysisSettings'
import { AnalysisFrame } from './AnalysisFrame'
import { useAnalysis } from './useAnalysis'
import { DATA } from '../../lib/palette'

const sci = (v: number | null | undefined, d = 3) => (v === null || v === undefined ? '—' : v === 0 ? '0' : v.toExponential(d - 1))

/** Two-surface ghost table (ranked) with the selected ghost's ray paths. */
export function GhostView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const ev = useEngineStore((s) => s.evaluation)
  const [st, set] = useAnalysisSettings('ghosts', { field: 0, wavelength: null as number | null }, 'Ghost settings')
  const settings = { field: Math.min(st.field, system.fields.length - 1), wavelength: st.wavelength !== null && st.wavelength >= system.wavelengths.length ? null : st.wavelength }
  const { data, error, loading, ms, refresh } = useAnalysis<GhostResult>('ghosts', settings)
  const [sel, setSel] = useState(0)
  const g = data?.ghosts[Math.min(sel, (data?.ghosts.length ?? 1) - 1)]
  const traces: Trace[] = []
  if (g) {
    const xs: (number | null)[] = []
    const ys: (number | null)[] = []
    for (const path of g.paths_zy) {
      for (const [z, y] of path) {
        xs.push(z)
        ys.push(y)
      }
      xs.push(null)
      ys.push(null)
    }
    traces.push({ type: 'scatter', mode: 'lines', x: xs, y: ys, line: { color: DATA.ghost, width: 1.2 }, hoverinfo: 'skip', name: 'ghost rays' })
  }
  const shapes = (ev?.global_vertex_z ?? []).slice(1).map((z, k) => ({ type: 'line', x0: z, x1: z, yref: 'paper', y0: 0.05, y1: 0.95, line: { width: 1, color: k + 2 === system.surfaces.length ? DATA.primary : 'rgba(128,128,128,0.55)', dash: k + 2 === system.surfaces.length ? 'solid' : 'dot' } }))
  return (
    <AnalysisFrame
      kind="ghosts"
      title={t('view.ghosts')}
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
          <FieldSelect system={system} value={settings.field} onChange={(v) => set({ field: v })} />
          <WavelengthSelect system={system} value={settings.wavelength} onChange={(v) => set({ wavelength: v })} />
        </>
      }
    >
      {data && (
        <div className="flex h-full min-h-0 flex-col">
          <div className="min-h-[150px] flex-1 overflow-auto">
            <table className="eng-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th title={t('gh.pathHint')}>{t('gh.path')}</th>
                  <th className="text-right" title={t('gh.focusHint')}>{t('gh.focus')} (mm)</th>
                  <th className="text-right" title={t('gh.rmsHint')}>RMS (mm)</th>
                  <th className="text-right" title={t('gh.energyHint')}>{t('gh.energy')}</th>
                  <th className="text-right" title={t('gh.irrHint')}>{t('gh.irr')}</th>
                  <th className="text-right">{t('gh.rays')}</th>
                </tr>
              </thead>
              <tbody>
                {data.ghosts.map((x, k) => (
                  <tr key={`${x.reflect_first}-${x.reflect_second}`} className={cx('cursor-pointer', k === sel && 'bg-accent/10')} onClick={() => setSel(k)}>
                    <td className="px-2 text-muted">{k + 1}</td>
                    <td className="px-2">
                      S{x.reflect_first} → S{x.reflect_second}
                    </td>
                    <td className="num px-2 text-right">{fmt(x.focus_from_image_mm, 5)}</td>
                    <td className="num px-2 text-right">{fmt(x.rms_radius_mm, 4)}</td>
                    <td className="num px-2 text-right">{sci(x.energy_fraction)}</td>
                    <td className={cx('num px-2 text-right', (x.relative_irradiance ?? 0) > 1e-4 && 'font-semibold text-warn')}>{sci(x.relative_irradiance)}</td>
                    <td className="num px-2 text-right text-muted">
                      {x.rays_ok}/{x.rays}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.ghosts.length === 0 && <div className="p-3 text-muted">{t('gh.none')}</div>}
            <div className="px-3 py-1.5 text-caption text-faint">
              {t('gh.main')}: {fmt(data.main.energy_fraction * 100, 5)} % · GEO {fmt(data.main.geo_radius_mm * 1000, 4)} µm · Airy {fmt(data.main.airy_radius_mm * 1000, 4)} µm. {data.pairs_skipped_no_index_step > 0 && `${data.pairs_skipped_no_index_step} ${t('gh.skipped')}`}
            </div>
          </div>
          {g && (
            <div className="h-[44%] min-h-[160px] shrink-0 border-t border-line">
              <Plot data={traces} layout={{ showlegend: false, shapes, margin: { l: 50, r: 10, t: 24, b: 36 }, title: { text: `S${g.reflect_first} → S${g.reflect_second}`, font: { size: 12 } }, xaxis: { title: { text: 'z (mm)' } }, yaxis: { title: { text: 'y (mm)' } } }} />
            </div>
          )}
        </div>
      )}
    </AnalysisFrame>
  )
}
