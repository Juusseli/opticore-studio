import { useState } from 'react'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import type { NonSeqResult, NsPathRow } from '../../lib/types'
import { useEngineStore } from '../../store/engineStore'
import { useUiStore } from '../../store/uiStore'
import { Plot, type Trace } from '../common/Plot'
import { Button, Checkbox, NumberField, Select } from '../common/ui'
import { cx } from '../common/uiUtils'
import { FieldSelect, Row, WavelengthSelect } from '../common/controls'
import { Swatch } from '../common/LightReadout'
import { colourText } from '../common/colourText'
import { AnalysisFrame } from './AnalysisFrame'
import { type NsQuantity, useNonSeqSettings } from './nonseqSettings'
import { useAnalysis } from './useAnalysis'
import { COLORMAPS, DATA } from '../../lib/palette'

const pct = (v: number) => `${fmt(v * 100, 5)} %`
const watts = (v: number) => `${fmt(v, 5)} W`
/** Relative standard error as "± x %" (— without a value). */
const relErr = (sigma: number, value: number) => {
  if (!(value > 0)) return '—'
  const r = (sigma / value) * 100
  return `± ${r >= 10 ? Math.round(r) : r >= 0.01 ? r.toPrecision(2) : '<0.01'} %`
}

/** Non-sequential trace of the lens system (as solids) together with the CAD models that have an optical role.
 * Light comes from the project's sources (or the sequential system field); it is received by the project's
 * detectors (or a disc on the image surface). */
export function NonSeqView() {
  const t = useT()
  const ev = useEngineStore((s) => s.evaluation)
  const [detSel, setDetSel] = useState(0)
  const { st, set, settings, ownSources, ownDetectors, projSources, projDetectors, scatters, system } = useNonSeqSettings()
  const { data, error, loading, ms, refresh } = useAnalysis<NonSeqResult>('nonseq', settings)
  const e = data?.energy
  const det = data?.detector ?? null
  const dets = data?.detectors ?? []
  const dsel = dets.length ? dets[Math.min(detSel, dets.length - 1)] : null
  const logz = (m: number[][]) => (st.log ? m.map((r) => r.map((v) => (v > 0 ? Math.log10(v) : null))) : m)
  const R = det?.radius_mm ?? 1
  const ax = det ? Array.from({ length: det.pixels }, (_, k) => -R + ((k + 0.5) * 2 * R) / det.pixels) : []
  const axX = dsel ? Array.from({ length: dsel.pixels[0] }, (_, k) => -dsel.half_extent_mm[0] + ((k + 0.5) * 2 * dsel.half_extent_mm[0]) / dsel.pixels[0]) : []
  const axY = dsel ? Array.from({ length: dsel.pixels[1] }, (_, k) => -dsel.half_extent_mm[1] + ((k + 0.5) * 2 * dsel.half_extent_mm[1]) / dsel.pixels[1]) : []
  const P = data?.total_power_w ?? 1
  const evName = (ev: string) => (ev.startsWith('S:') ? `${t('ns.evScatter')} ${ev.slice(2)}` : ev.startsWith('R:') ? `${t('ns.evReflect')} ${ev.slice(2)}` : ev)
  const pathName = (p: string) => (p === 'direct' ? t('ns.direct') : p.split(' → ').map(evName).join(' → '))
  // path table of the selected analytic detector, else the image-surface disc (power as fractions of the emitted power)
  const pathRows: { rows: NsPathRow[]; total: number; name: string } | null = dsel
    ? { rows: dsel.paths ?? [], total: dsel.power_w, name: dsel.name }
    : det && det.paths
      ? { rows: det.paths.map((r) => ({ ...r, power_w: (r.power ?? 0) * P, sigma_w: (r.sigma ?? 0) * P })), total: e ? e.detected * P : 0, name: t('ns.imageDetector') }
      : null
  const impOptions = [
    { value: 'none', label: t('ns.impOff') },
    ...(ownDetectors ? projDetectors.filter((d) => d.enabled).map((d) => ({ value: `det:${d.id}`, label: d.name })) : [{ value: 'legacy', label: t('ns.imageDetector') }]),
    ...system.surfaces.slice(1).map((s, k) => ({ value: `sid:${s.id}`, label: `${t('ns.impSurface')} ${k + 1}${s.comment ? ` (${s.comment})` : ''}` })),
  ]
  const impSetting = data?.settings?.importance ?? null
  const pathTraces: Trace[] = []
  if (data) {
    for (const [kind, color, name] of [
      ['direct', DATA.direct, 'direct'],
      ['ghost', DATA.ghost, 'after ghost reflections'],
      ['scatter', DATA.scatter, 'scattered'],
    ] as const) {
      const xs: (number | null)[] = []
      const ys: (number | null)[] = []
      const cls = (q: NonSeqResult['paths'][number]) => ((q.scatters ?? 0) > 0 ? 'scatter' : q.reflections > 0 ? 'ghost' : 'direct')
      for (const p of data.paths.filter((q) => cls(q) === kind)) {
        for (const pt of p.points) {
          xs.push(pt[2])
          ys.push(pt[1])
        }
        xs.push(null)
        ys.push(null)
      }
      pathTraces.push({ type: 'scatter', mode: 'lines', x: xs, y: ys, name, line: { color, width: 1 }, hoverinfo: 'skip' })
    }
  }
  const vertexLines = (ev?.global_vertex_z ?? []).slice(1).map((zz) => ({ type: 'line', x0: zz, x1: zz, yref: 'paper', y0: 0.05, y1: 0.95, line: { width: 1, color: 'rgba(128,128,128,0.4)', dash: 'dot' } }))
  // photometry: shown when some detector receives visible light
  const visible = dets.some((d) => (d.photometry?.luminous_flux_lm ?? 0) > 0)
  const quantity: NsQuantity = visible ? (st.quantity ?? 'irradiance') : 'irradiance'
  const ph = dsel?.photometry
  const map = detectorMap(dsel, quantity, st.log, axX, axY, t)
  return (
    <AnalysisFrame
      kind="nonseq"
      title={t('view.nonseq')}
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
          {ownSources ? (
            <Button size="sm" variant="ghost" onClick={() => useUiStore.getState().set({ bottomTab: 'sources', bottomOpen: true })} title={t('ns.editSources')}>
              {t('ns.sourcesBtn')} ({projSources.filter((x) => x.enabled).length}/{projDetectors.filter((x) => x.enabled).length})
            </Button>
          ) : (
            <>
              <FieldSelect system={system} value={settings.field} onChange={(v) => set({ field: v })} />
              <WavelengthSelect system={system} value={settings.wavelength} onChange={(v) => set({ wavelength: v })} />
            </>
          )}
          {visible && (
            <Select<NsQuantity>
              className="h-6 w-32 text-small"
              ariaLabel={t('ns.quantity')}
              title={t('ns.quantityHint')}
              value={quantity}
              options={[
                { value: 'irradiance', label: t('ns.q.irradiance') },
                { value: 'illuminance', label: t('ns.q.illuminance') },
                { value: 'colour', label: t('ns.q.colour') },
              ]}
              onChange={(v) => set({ quantity: v })}
            />
          )}
        </>
      }
      more={
        <>
          {!ownSources && (
            <>
              <Button variant="link" className="w-full" onClick={() => useUiStore.getState().set({ bottomTab: 'sources', bottomOpen: true })} title={t('ns.editSources')}>
                {t('ns.sourcesBtn')} ({projSources.filter((x) => x.enabled).length}/{projDetectors.filter((x) => x.enabled).length}) ›
              </Button>
              <Row label={t('ns.rays')} hint={t('ns.raysHint')}>
                <NumberField className="h-6 w-20" ariaLabel={t('ns.rays')} value={st.rays} integer min={4} max={20000} onCommit={(v) => set({ rays: v ?? 400 })} />
              </Row>
              <Row label={t('ns.overfill')} hint={t('ns.overfillHint')}>
                <NumberField className="h-6 w-20" ariaLabel={t('ns.overfill')} value={st.overfill} min={0.05} max={10} onCommit={(v) => set({ overfill: v ?? 1.2 })} />
              </Row>
            </>
          )}
          <Row label={t('ns.timeLimit')} hint={t('ns.timeLimitHint')}>
            <NumberField className="h-6 w-20" optional ariaLabel={t('ns.timeLimit')} value={st.max_seconds} placeholder={t('ns.noLimit')} min={1} max={3600} onCommit={(v) => set({ max_seconds: v })} />
          </Row>
          <span className="w-full">
            <Checkbox checked={st.log} onChange={(v) => set({ log: v })} label={<span className="text-small text-muted">{t('an.log')}</span>} />
          </span>
          <span className="w-full" title={t('ns.splitHint')}>
            <Checkbox checked={st.split} onChange={(v) => set({ split: v })} label={<span className="text-small text-muted">{t('ns.split')}</span>} />
          </span>
          <span className="w-full" title={t('ns.systemHint')}>
            <Checkbox checked={st.include_system} onChange={(v) => set({ include_system: v })} label={<span className="text-small text-muted">{t('ns.system')}</span>} />
          </span>
          {(scatters || ownSources) && (
            <>
              <Row label={t('ns.seed')} hint={t('ns.seedHint')}>
                <NumberField className="h-6 w-24" ariaLabel={t('ns.seed')} value={st.seed} integer min={0} max={2147483647} onCommit={(v) => set({ seed: v ?? 1 })} />
              </Row>
            </>
          )}
          {scatters && (
            <>
              <Row label={t('ns.impTarget')} hint={t('ns.impTargetHint')}>
                <Select className="h-6 w-40" ariaLabel={t('ns.impTarget')} value={impOptions.some((o) => o.value === st.imp_target) ? st.imp_target : 'none'} options={impOptions} onChange={(v) => set({ imp_target: v })} />
              </Row>
              {settings.importance && (
                <Row label={t('ns.impRays')} hint={t('ns.impRaysHint')}>
                  <NumberField className="h-6 w-20" ariaLabel={t('ns.impRays')} value={st.imp_rays} integer min={1} max={64} onCommit={(v) => set({ imp_rays: v ?? 4 })} />
                </Row>
              )}
            </>
          )}
        </>
      }
    >
      {data && e && (
        <div className="grid h-full min-h-0 auto-rows-[minmax(240px,1fr)] grid-cols-[repeat(auto-fit,minmax(280px,1fr))] gap-px overflow-auto bg-line">
          <div className="min-h-0 overflow-auto bg-panel">
            <table className="eng-table wrap-first">
              <tbody>
                <tr>
                  <th className="px-2 text-left">{t('ns.detected')}</th>
                  <td className="num px-2 text-right font-semibold">
                    {pct(e.detected)}
                    {det && det.power_sigma > 0 && (
                      <span className="ml-1 font-normal text-muted" title={t('ns.sigmaHint')}>
                        {relErr(det.power_sigma, e.detected)}
                      </span>
                    )}
                  </td>
                </tr>
                <tr>
                  <td className="px-2 pl-5 text-muted">{t('ns.direct')}</td>
                  <td className="num px-2 text-right">{pct(e.detected_direct)}</td>
                </tr>
                <tr>
                  <td className="px-2 pl-5 text-muted">{t('ns.stray')}</td>
                  <td className={`num px-2 text-right ${e.detected_after_reflections > 1e-3 ? 'text-warn' : ''}`}>{pct(e.detected_after_reflections)}</td>
                </tr>
                {(e.scattered ?? 0) > 0 && (
                  <tr>
                    <td className="px-2 pl-5 text-muted">{t('ns.afterScatter')}</td>
                    <td className={`num px-2 text-right ${e.detected_after_scatter > 1e-3 ? 'text-warn' : ''}`}>{pct(e.detected_after_scatter)}</td>
                  </tr>
                )}
                {Object.entries(e.absorbed).map(([k, v]) => (
                  <tr key={k}>
                    <td className="px-2">
                      {t('ns.absorbed')}: {k}
                    </td>
                    <td className="num px-2 text-right">{pct(v)}</td>
                  </tr>
                ))}
                <tr>
                  <td className="px-2">{t('ns.escaped')}</td>
                  <td className="num px-2 text-right">{pct(e.escaped)}</td>
                </tr>
                <tr>
                  <td className="px-2">{t('ns.bulk')}</td>
                  <td className="num px-2 text-right">{pct(e.bulk_absorption)}</td>
                </tr>
                {(e.coating_absorption ?? 0) > 0 && (
                  <tr>
                    <td className="px-2">{t('ns.coatingAbs')}</td>
                    <td className="num px-2 text-right">{pct(e.coating_absorption)}</td>
                  </tr>
                )}
                {(e.detector_rejected ?? 0) > 0 && (
                  <tr>
                    <td className="px-2">{t('ns.detRejected')}</td>
                    <td className="num px-2 text-right">{pct(e.detector_rejected ?? 0)}</td>
                  </tr>
                )}
                {(e.detector_back ?? 0) > 0 && (
                  <tr>
                    <td className="px-2">{t('ns.detBack')}</td>
                    <td className="num px-2 text-right">{pct(e.detector_back ?? 0)}</td>
                  </tr>
                )}
                <tr>
                  <td className="px-2 text-muted">{t('ns.discarded')}</td>
                  <td className="num px-2 text-right text-muted">{pct(e.discarded_reflections + e.truncated)}</td>
                </tr>
                <tr>
                  <th className="px-2 text-left">{t('ns.total')}</th>
                  <td className="num px-2 text-right">{pct(e.total)}</td>
                </tr>
                <tr>
                  <td className="px-2 text-muted">{t('ns.emitted')}</td>
                  <td className="num px-2 text-right text-muted">{watts(P)}</td>
                </tr>
                {(e.scattered ?? 0) > 0 && (
                  <tr>
                    <td className="px-2 text-muted" title={t('ns.scatteredHint')}>
                      {t('ns.scattered')}
                    </td>
                    <td className="num px-2 text-right text-muted">{pct(e.scattered)}</td>
                  </tr>
                )}
                {impSetting && (
                  <tr>
                    <td className="px-2 text-muted" title={t('ns.impBalanceHint')}>
                      {t('ns.impBalance')}
                    </td>
                    <td className="num px-2 text-right text-muted">
                      +{pct(e.importance_added ?? 0)} / −{pct(e.importance_dropped ?? 0)}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            <div className="space-y-1 px-3 py-2 text-small text-muted">
              <div>
                {data.source.rays} {t('ns.sourceRays')} · {data.events} {t('ns.events')} · {data.elapsed_s.toFixed(2)} s
              </div>
              {impSetting && (
                <div>
                  {t('ns.impOn')}: {impSetting.target} · {impSetting.rays} {t('ns.impPerEvent')}
                </div>
              )}
              {det && det.direct_rms_mm !== null && <div>RMS (direct): {fmt(det.direct_rms_mm * 1000, 5)} µm</div>}
              {ownSources &&
                data.sources.map((x) => (
                  <div key={x.name} className="text-faint">
                    {x.name}: {x.rays} {t('ns.sourceRays')} · {watts(x.power_w)}
                  </div>
                ))}
              {data.objects
                .filter((o) => o.role !== 'detector')
                .map((o) => (
                  <div key={o.name} className="text-faint">
                    {o.name}: {o.role}
                    {o.material ? ` (${o.material})` : ''}
                    {o.coating ? ` · ${o.coating}` : ''}
                    {o.scatter ? ` · ${o.scatter.model} ${fmt(o.scatter.fraction * 100, 3)} %${o.scatter.model === 'gaussian' ? ` σ ${fmt(o.scatter.sigma_deg, 3)}°` : ''}${o.scatter.model === 'abg' ? ` A ${fmt(o.scatter.A ?? 0, 3)} B ${fmt(o.scatter.B ?? 0, 3)} g ${fmt(o.scatter.g ?? 0, 3)}` : ''}${o.scatter.model === 'harvey' ? ` b₀ ${fmt(o.scatter.b0 ?? 0, 3)} l ${fmt(o.scatter.l ?? 0, 3)} s ${fmt(o.scatter.s ?? 0, 3)}` : ''}` : ''}
                    {!o.exact && ' · faceted'}
                  </div>
                ))}
              {data.notes.map((n) => (
                <div key={n} className="text-warn">
                  {n}
                </div>
              ))}
            </div>
          </div>
          {dets.length > 0 && (
            <div className="min-h-0 overflow-auto bg-panel">
              <table className="eng-table">
                <thead>
                  <tr>
                    <th>{t('det.detector')}</th>
                    <th className="text-right">{t('ns.power')}</th>
                    <th className="text-right" title={t('ns.sigmaHint')}>
                      ±σ
                    </th>
                    <th className="text-right">%</th>
                    {visible && (
                      <th className="text-right" title={t('ns.lumenHint')}>
                        lm
                      </th>
                    )}
                    <th className="text-right" title={t('ns.strayHint')}>
                      {t('ns.strayShort')}
                    </th>
                    <th className="text-right" title={t('ns.width2sHint')}>
                      2σ x / y (µm)
                    </th>
                    <th className="text-right">{t('ns.centroid')} (mm)</th>
                  </tr>
                </thead>
                <tbody>
                  {dets.map((d, k) => (
                    <tr key={d.id} className={cx('cursor-pointer', k === Math.min(detSel, dets.length - 1) && 'selected')} onClick={() => setDetSel(k)}>
                      <td className="px-2 font-medium">
                        {d.name} {d.mode === 'monitor' && <span className="text-caption text-faint">({t('det.monitor')})</span>}
                      </td>
                      <td className="num px-2 text-right">{watts(d.power_w)}</td>
                      <td className="num px-2 text-right text-muted">{relErr(d.power_sigma_w ?? 0, d.power_w)}</td>
                      <td className="num px-2 text-right font-semibold">{fmt(d.fraction * 100, 5)}</td>
                      {visible && (
                        <td className="num px-2 text-right">
                          <span className="inline-flex items-center justify-end gap-1">
                            <Swatch rgb={d.photometry?.srgb} />
                            {d.photometry ? fmt(d.photometry.luminous_flux_lm, 5) : '—'}
                          </span>
                        </td>
                      )}
                      <td className="num px-2 text-right">{d.power_w > 0 ? `${fmt(((d.stray_w ?? 0) / d.power_w) * 100, 4)} %` : '—'}</td>
                      <td className="num px-2 text-right">{d.width_2sigma_mm ? `${fmt(d.width_2sigma_mm[0] * 1000, 4)} / ${fmt(d.width_2sigma_mm[1] * 1000, 4)}` : '—'}</td>
                      <td className="num px-2 text-right">{d.centroid_mm ? `${fmt(d.centroid_mm[0], 4)}, ${fmt(d.centroid_mm[1], 4)}` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {dsel && (
                <div className="space-y-0.5 px-3 py-2 text-small text-muted">
                  <div>
                    {dsel.name}: {dsel.hits} {t('ns.hits')}
                    {dsel.peak_irradiance_w_mm2 !== null && ` · ${t('ns.peak')} ${fmt(dsel.peak_irradiance_w_mm2, 4)} W/mm²`}
                    {dsel.rms_radius_mm !== null && ` · RMS ${fmt(dsel.rms_radius_mm * 1000, 4)} µm`}
                  </div>
                  {ph && ph.luminous_flux_lm > 0 && (
                    <>
                      <div className="text-fg">
                        {t('ns.luminousFlux')} {fmt(ph.luminous_flux_lm, 5)} lm {relErr(ph.luminous_flux_sigma_lm, ph.luminous_flux_lm)}
                        {ph.average_illuminance_lux !== null && ` · ${t('ns.avgIllum')} ${fmt(ph.average_illuminance_lux, 5)} lx`}
                        {` · ${t('ns.peak')} ${fmt(ph.peak_illuminance_lux, 4)} lx`}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <Swatch rgb={ph.srgb} />
                        <span className="num">{colourText(ph, t)}</span>
                      </div>
                    </>
                  )}
                  {dsel.rejected_angle_w > 0 && (
                    <div className="text-warn">
                      {t('ns.detRejected')}: {watts(dsel.rejected_angle_w)} ({fmt((dsel.rejected_angle_w / P) * 100, 4)} %)
                    </div>
                  )}
                  {dsel.blocked_back_w > 0 && (
                    <div>
                      {t('ns.detBack')}: {watts(dsel.blocked_back_w)}
                    </div>
                  )}
                  {Object.keys(dsel.by_source_w).length > 1 &&
                    Object.entries(dsel.by_source_w).map(([k, v]) => (
                      <div key={k} className="text-faint">
                        {k}: {watts(v)}
                      </div>
                    ))}
                  {Object.keys(dsel.by_wavelength_w).length > 1 &&
                    Object.entries(dsel.by_wavelength_w).map(([k, v]) => (
                      <div key={k} className="text-faint">
                        {fmt(Number(k) * 1000, 5)} nm: {watts(v)}
                      </div>
                    ))}
                </div>
              )}
            </div>
          )}
          {pathRows && pathRows.rows.length > 0 && (
            <div className="min-h-0 overflow-auto bg-panel">
              <div className="px-3 pt-1.5 text-small font-medium">
                {t('ns.pathTable')} — {pathRows.name}
              </div>
              <table className="eng-table">
                <thead>
                  <tr>
                    <th>{t('ns.path')}</th>
                    <th className="text-right">{t('ns.power')}</th>
                    <th className="text-right" title={t('ns.sigmaHint')}>
                      ±σ
                    </th>
                    <th className="text-right" title={t('ns.pathShareHint')}>
                      %
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {pathRows.rows.map((r) => (
                    <tr key={r.path} title={`${r.hits} ${t('ns.hits')}`}>
                      <td className="min-w-[140px] whitespace-normal px-2">
                        {pathName(r.path)}
                      </td>
                      <td className="num px-2 text-right">{watts(r.power_w)}</td>
                      <td className="num px-2 text-right text-muted">{relErr(r.sigma_w, r.power_w)}</td>
                      <td className="num px-2 text-right font-semibold">{pathRows.total > 0 ? fmt((r.power_w / pathRows.total) * 100, 4) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {dsel && (
            <div className="min-h-0 bg-panel">
              <Plot
                square={dsel.half_extent_mm[0] === dsel.half_extent_mm[1]}
                data={map.data}
                layout={{
                  margin: { l: 48, r: 8, t: 22, b: 34 },
                  title: { text: `${map.title} — ${dsel.name}`, font: { size: 11 } },
                  xaxis: { title: { text: 'x (mm)' }, range: [-dsel.half_extent_mm[0], dsel.half_extent_mm[0]] },
                  // explicit ranges: an image trace would otherwise put its first row at the top
                  yaxis: { title: { text: 'y (mm)' }, range: [-dsel.half_extent_mm[1], dsel.half_extent_mm[1]] },
                }}
              />
            </div>
          )}
          {dsel && dsel.hits > 0 && (
            <div className="min-h-0 bg-panel">
              <Plot
                data={[{ type: 'bar', x: dsel.angle_hist.bin_deg.map((b) => b + 0.5), y: dsel.angle_hist.power_w, marker: { color: DATA.primary }, hovertemplate: '%{x:.1f}°: %{y:.4g} W<extra></extra>' }]}
                layout={{ margin: { l: 52, r: 8, t: 22, b: 34 }, title: { text: t('ns.angleHist'), font: { size: 11 } }, bargap: 0.05, xaxis: { title: { text: t('ns.incidence') } }, yaxis: { title: { text: 'W / °' } } }}
              />
            </div>
          )}
          {det && (
            <div className="min-h-0 bg-panel">
              <Plot
                square
                data={[{ type: 'heatmap', x: ax, y: ax, z: logz(det.irradiance), colorscale: COLORMAPS.sequential, colorbar: { title: { text: st.log ? 'log₁₀ E' : 'E' }, thickness: 10 }, hovertemplate: 'x %{x:.3f} y %{y:.3f} mm<br>%{z:.3g}<extra></extra>' }]}
                layout={{ margin: { l: 44, r: 8, t: 22, b: 34 }, title: { text: t('ns.irradiance'), font: { size: 11 } }, xaxis: { title: { text: 'x (mm)' } }, yaxis: { title: { text: 'y (mm)' } } }}
              />
            </div>
          )}
          <div className="min-h-0 bg-panel">
            <Plot data={pathTraces} layout={{ margin: { l: 44, r: 8, t: 22, b: 34 }, shapes: vertexLines, showlegend: true, legend: { orientation: 'h', y: 1.12, font: { size: 10 } }, xaxis: { title: { text: 'z (mm)' } }, yaxis: { title: { text: 'y (mm)' } } }} />
          </div>
        </div>
      )}
    </AnalysisFrame>
  )
}

type DetResult = NonSeqResult['detectors'][number]

/** The selected detector's map: irradiance (W/mm²), illuminance (lux) or its true colour (sRGB image, the pixel's
 *  chromaticity and illuminance on hover). Rows run along y in every case. */
function detectorMap(d: DetResult | null, q: NsQuantity, log: boolean, axX: number[], axY: number[], t: ReturnType<typeof useT>): { data: Trace[]; title: string } {
  if (!d) return { data: [], title: '' }
  const logz = (m: number[][]) => (log ? m.map((r) => r.map((v) => (v > 0 ? Math.log10(v) : null))) : m)
  const ph = d.photometry
  if (q === 'colour' && ph?.colour_image) {
    const [X, Y, Z] = ph.xyz_w_mm2
    const text = Y.map((row, i) =>
      row.map((y, j) => {
        const s = X[i][j] + y + Z[i][j]
        return s > 0 ? `x ${(X[i][j] / s).toFixed(4)}, y ${(y / s).toFixed(4)}<br>${fmt(ph.illuminance_lux[i][j], 4)} lx` : '—'
      }),
    )
    const dx = axX.length > 1 ? axX[1] - axX[0] : 1
    const dy = axY.length > 1 ? axY[1] - axY[0] : 1
    return { title: t('ns.q.colour'), data: [{ type: 'image', z: ph.colour_image, x0: axX[0], dx, y0: axY[0], dy, text, hovertemplate: 'x %{x:.4g} y %{y:.4g} mm<br>%{text}<extra></extra>' }] }
  }
  if (q === 'illuminance' && ph) {
    return {
      title: t('ns.q.illuminance'),
      data: [{ type: 'heatmap', x: axX, y: axY, z: logz(ph.illuminance_lux), colorscale: COLORMAPS.sequential, colorbar: { title: { text: log ? 'log₁₀ lx' : 'lx' }, thickness: 10 }, hovertemplate: 'x %{x:.4f} y %{y:.4f} mm<br>%{z:.4g} lx<extra></extra>' }],
    }
  }
  return {
    title: t('ns.irradianceOf'),
    data: [{ type: 'heatmap', x: axX, y: axY, z: logz(d.irradiance), colorscale: COLORMAPS.sequential, colorbar: { title: { text: log ? 'log₁₀ W/mm²' : 'W/mm²' }, thickness: 10 }, hovertemplate: 'x %{x:.4f} y %{y:.4f} mm<br>%{z:.4g}<extra></extra>' }],
  }
}
