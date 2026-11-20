import { fieldColor, fmt, wavelengthColor } from '../../lib/format'
import { useT } from '../../lib/i18n'
import type { GaussianResult, HuygensResult, MtfResult, PolarizationResult, OpdFanResult, Project, PsfResult, WavefrontResult } from '../../lib/types'
import { useProjectStore } from '../../store/projectStore'
import { Plot, type Trace } from '../common/Plot'
import { LENGTH_TO_MM } from '../../lib/units'
import { Checkbox, NumberField, Select } from '../common/ui'
import { FieldSelect, Label, Row, Stat, WavelengthSelect } from '../common/controls'
import { useAnalysisSettings } from '../common/useAnalysisSettings'
import { AnalysisFrame } from './AnalysisFrame'
import { useAnalysis } from './useAnalysis'
import { COLORMAPS, DATA } from '../../lib/palette'

type Key = 'wavefront' | 'psf' | 'huygens' | 'mtf' | 'gaussian' | 'polarization'
const DEFAULTS = {
  wavefront: { field: 0, wavelength: null, grid: 64 },
  psf: { field: 0, wavelength: null, grid: 64, pad: 4, log: false },
  huygens: { field: 0, wavelength: null, pupil_samples: 64, image_samples: 65, image_delta_um: null, defocus_mm: 0, transmission: false, log: false },
  mtf: { kind: 'diffraction' as const, max_frequency: null, samples: 64, sensor: true },
  gaussian: { waist_radius: 1, waist_distance: 0, wavelength: null, m2: 1 },
  polarization: { field: 0, wavelength: null, grid: 15, input: 'x' as const, map: 'diattenuation' as const, crystal_modes: 'sum' as 'sum' | 'prescription' },
}

function useSettings<K extends Key>(key: K) {
  return useAnalysisSettings(key, DEFAULTS[key] as NonNullable<Project['analysis_settings'][K]>)
}

// ------------------------------------------------------------------ OPD fan
export function OpdFanView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const st = { samples: 41 }
  const { data, error, loading, ms, refresh } = useAnalysis<OpdFanResult>('opdfan', st)
  return (
    <AnalysisFrame kind="opdfan" title={t('view.opdfan')} loading={loading} error={error} hasData={!!data} ms={ms} method={data?.method} onRefresh={refresh} settings={st} result={data}>
      <div className="h-full overflow-auto">
        {data?.fields.map((f) => (
          <div key={f.field} className="grid h-58 grid-cols-2 gap-px border-b border-line">
            {(['tangential', 'sagittal'] as const).map((kind) => (
              <div key={kind} className="flex min-h-0 flex-col">
                <div className="px-2.5 pt-1.5 text-small">
                  <span className="font-semibold">
                <span className="mr-1.5 inline-block h-2 w-2 rounded-full align-middle" style={{ background: fieldColor(f.field) }} aria-hidden />
                    {t('an.field')} {f.field + 1}
                  </span>{' '}
                  <span className="text-muted">
                    {fmt(f.field_value[1], 4)}
                    {system.field_type === 'angle' ? '°' : ' mm'} · {kind === 'tangential' ? `${t('an.tangential')} W(P_y)` : `${t('an.sagittal')} W(P_x)`}
                  </span>
                </div>
                <div className="min-h-0 flex-1">
                  <Plot
                    data={f.per_wavelength.map((w) => ({
                      type: 'scatter',
                      mode: 'lines',
                      x: data.pupil,
                      y: kind === 'tangential' ? w.tangential_waves : w.sagittal_waves,
                      name: `${fmt(system.wavelengths[w.wavelength]?.value * 1000, 5)} nm`,
                      line: { color: wavelengthColor(system.wavelengths[w.wavelength]?.value ?? 0.55), width: 1.6 },
                      hovertemplate: 'P %{x:.3f}<br>%{y:.4f} waves<extra></extra>',
                      showlegend: false,
                    }))}
                    layout={{ margin: { l: 52, r: 10, t: 6, b: 30 }, xaxis: { range: [-1, 1], title: { text: kind === 'tangential' ? 'P_y' : 'P_x' } }, yaxis: { title: { text: t('an.waves') } }, hovermode: 'x unified' }}
                  />
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </AnalysisFrame>
  )
}

// ------------------------------------------------------------------ wavefront map
export function WavefrontView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const [st, set] = useSettings('wavefront')
  const settings = { field: Math.min(st.field, system.fields.length - 1), wavelength: st.wavelength !== null && st.wavelength >= system.wavelengths.length ? null : st.wavelength, grid: st.grid, zernike_terms: 37 }
  const { data, error, loading, ms, refresh } = useAnalysis<WavefrontResult>('wavefront', settings)
  return (
    <AnalysisFrame
      kind="wavefront"
      title={t('view.wavefront')}
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
      more={
        <>
          <Label hint={t('an.gridHint')}>{t('an.grid')}</Label>
          <NumberField className="h-6 w-14" ariaLabel={t('an.grid')} value={st.grid} integer min={16} max={256} onCommit={(v) => set({ grid: v ?? 64 })} />
        </>
      }
    >
      {data && (
        <div className="grid h-full min-h-0 auto-rows-[minmax(280px,1fr)] grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-px overflow-auto bg-line">
          <div className="flex min-h-0 flex-col bg-panel">
            <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
              <Stat label={t('an.pv')} value={fmt(data.pv_waves, 4)} unit={t('an.waves')} />
              <Stat label={t('an.rmsWave')} value={fmt(data.rms_waves, 4)} unit={t('an.waves')} />
              <Stat label={t('an.marechal')} value={fmt(data.strehl_marechal, 4)} />
              <Stat label="λ" value={fmt(data.wavelength_um * 1000, 6)} unit="nm" />
            </div>
            <div className="min-h-0 flex-1">
              <Plot
                square
                data={[
                  {
                    type: 'heatmap',
                    x: data.x,
                    y: data.y,
                    z: data.map_waves,
                    // signed OPD: diverging, blue behind and red ahead of the reference sphere, centred on zero
                    colorscale: COLORMAPS.diverging,
                    zmid: 0,
                    colorbar: { title: { text: t('an.waves'), side: 'right' }, thickness: 12 },
                    hovertemplate: 'Px %{x:.3f}<br>Py %{y:.3f}<br>W %{z:.4f} waves<extra></extra>',
                  },
                ]}
                layout={{ margin: { l: 46, r: 10, t: 8, b: 36 }, xaxis: { title: { text: 'P_x' }, range: [-1, 1] }, yaxis: { title: { text: 'P_y' }, range: [-1, 1] } }}
              />
            </div>
          </div>
          <div className="overflow-auto bg-panel">
            <div className="px-3 pt-2 pb-1 text-small font-semibold tracking-wide text-muted uppercase">{t('an.zernike')}</div>
            <table className="eng-table">
              <thead>
                <tr>
                  <th>Z</th>
                  <th>n, m</th>
                  <th></th>
                  <th className="text-right">{t('an.waves')}</th>
                </tr>
              </thead>
              <tbody>
                {data.zernike.terms.map((z) => (
                  <tr key={z.index} className={Math.abs(z.value) < 1e-4 ? 'opacity-50' : ''}>
                    <td className="num px-2">{z.index}</td>
                    <td className="num px-2 text-muted">
                      {z.n}, {z.m}
                    </td>
                    <td className="px-2 text-muted">{z.name}</td>
                    <td className="num px-2 text-right">{z.value.toExponential(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="px-3 py-2 text-caption text-faint">
              {data.zernike.convention}. Fit residual RMS {fmt(data.zernike.fit_residual_rms_waves, 3)} waves. Valid pupil fraction {fmt(data.valid_fraction * 100, 4)}%. Reference sphere R = {fmt(data.reference.reference_radius_mm, 6)} mm.
            </div>
          </div>
        </div>
      )}
    </AnalysisFrame>
  )
}

// ------------------------------------------------------------------ PSF
export function PsfView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const [st, set] = useSettings('psf')
  const settings = { field: Math.min(st.field, system.fields.length - 1), wavelength: st.wavelength !== null && st.wavelength >= system.wavelengths.length ? null : st.wavelength, grid: st.grid, pad: st.pad }
  const { data, error, loading, ms, refresh } = useAnalysis<PsfResult>('psf', settings)
  const z = data ? (st.log ? data.psf.map((r) => r.map((v) => Math.log10(Math.max(v, 1e-6)))) : data.psf) : []
  const mid = data ? Math.floor(data.y_um.length / 2) : 0
  return (
    <AnalysisFrame
      kind="psf"
      title={t('view.psf')}
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
      more={
        <>
          <span className="w-full">
            <Checkbox checked={st.log} onChange={(v) => set({ log: v })} label={<span className="text-small text-muted">{t('an.log')}</span>} />
          </span>
          <Label hint={t('an.gridHint')}>{t('an.grid')}</Label>
          <NumberField className="h-6 w-14" ariaLabel={t('an.grid')} value={st.grid} integer min={16} max={256} onCommit={(v) => set({ grid: v ?? 64 })} />
          <Label hint={t('an.padHint')}>{t('an.pad')}</Label>
          <NumberField className="h-6 w-12" ariaLabel={t('an.pad')} value={st.pad} integer min={2} max={8} onCommit={(v) => set({ pad: v ?? 4 })} />
        </>
      }
    >
      {data && (
        <div className="grid h-full min-h-0 auto-rows-[minmax(300px,1fr)] grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-px overflow-auto bg-line">
          <div className="flex min-h-0 flex-col bg-panel">
            <div className="flex shrink-0 divide-x divide-line border-b border-line">
              <Stat label={t('an.strehl')} value={fmt(data.strehl, 4)} />
              <Stat label={t('an.airy')} value={fmt(data.airy_radius_um, 4)} unit="µm" />
              <Stat label="F/# (work)" value={fmt(data.working_fnum, 5)} />
              <Stat label="Δx" value={fmt(data.dx_um, 4)} unit="µm" />
            </div>
            <div className="min-h-0 flex-1">
              <Plot
                square
                data={[
                  {
                    type: 'heatmap',
                    x: data.x_um,
                    y: data.y_um,
                    z,
                    colorscale: COLORMAPS.sequentialAlt,
                    colorbar: { title: { text: st.log ? 'log₁₀ I' : 'I / I₀', side: 'right' }, thickness: 12 },
                    hovertemplate: 'x %{x:.2f} µm<br>y %{y:.2f} µm<br>%{z:.4f}<extra></extra>',
                  },
                  {
                    type: 'scatter',
                    mode: 'lines',
                    x: Array.from({ length: 121 }, (_, k) => data.airy_radius_um * Math.cos((2 * Math.PI * k) / 120)),
                    y: Array.from({ length: 121 }, (_, k) => data.airy_radius_um * Math.sin((2 * Math.PI * k) / 120)),
                    line: { color: 'rgba(255,255,255,0.6)', width: 1, dash: 'dot' },
                    hoverinfo: 'skip',
                    showlegend: false,
                  },
                ]}
                layout={{ margin: { l: 50, r: 10, t: 8, b: 36 }, xaxis: { title: { text: 'x (µm)' } }, yaxis: { title: { text: 'y (µm)' } }, showlegend: false }}
              />
            </div>
          </div>
          <div className="grid min-h-0 grid-rows-2 gap-px bg-line">
            <div className="bg-panel">
              <Plot
                data={
                  [
                    { type: 'scatter', mode: 'lines', x: data.x_um, y: data.psf[mid], name: 'x section', line: { color: DATA.primary, width: 1.6 } },
                    { type: 'scatter', mode: 'lines', x: data.y_um, y: data.psf.map((r) => r[mid]), name: 'y section', line: { color: DATA.secondary, width: 1.6, dash: 'dash' } },
                  ] as Trace[]
                }
                layout={{ margin: { l: 48, r: 10, t: 22, b: 34 }, title: { text: t('ax.crossSections'), font: { size: 11 } }, xaxis: { title: { text: 'µm' } }, yaxis: { title: { text: 'I / I₀' }, type: st.log ? 'log' : 'linear' }, legend: { orientation: 'h', y: 1.12, x: 1, xanchor: 'right' } }}
              />
            </div>
            <div className="bg-panel">
              <Plot
                data={[{ type: 'scatter', mode: 'lines', x: data.encircled_energy.radius_um, y: data.encircled_energy.fraction, line: { color: DATA.tertiary, width: 1.8 }, name: t('an.encircled'), hovertemplate: 'r %{x:.2f} µm<br>%{y:.4f}<extra></extra>' }]}
                layout={{
                  margin: { l: 48, r: 10, t: 22, b: 34 },
                  title: { text: t('an.encircled'), font: { size: 11 } },
                  xaxis: { title: { text: t('ax.radiusUm') } },
                  yaxis: { range: [0, 1.02] },
                  shapes: [{ type: 'line', x0: data.airy_radius_um, x1: data.airy_radius_um, yref: 'paper', y0: 0, y1: 1, line: { width: 1, dash: 'dot', color: DATA.reference } }],
                  showlegend: false,
                }}
              />
            </div>
          </div>
        </div>
      )}
    </AnalysisFrame>
  )
}

// ------------------------------------------------------------------ Huygens PSF
export function HuygensView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const [st, set] = useSettings('huygens')
  const settings = {
    field: Math.min(st.field, system.fields.length - 1),
    wavelength: st.wavelength !== null && st.wavelength >= system.wavelengths.length ? null : st.wavelength,
    pupil_samples: st.pupil_samples,
    image_samples: st.image_samples,
    image_delta_um: st.image_delta_um,
    defocus_mm: st.defocus_mm,
    transmission: st.transmission,
  }
  const { data, error, loading, ms, refresh } = useAnalysis<HuygensResult>('huygens', settings)
  const z = data ? (st.log ? data.psf.map((r) => r.map((v) => Math.log10(Math.max(v, 1e-6)))) : data.psf) : []
  const mid = data ? Math.floor(data.y_um.length / 2) : 0
  const airy = data?.airy_radius_um ?? null
  return (
    <AnalysisFrame
      kind="huygens"
      title={t('view.huygens')}
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
      more={
        <>
          <span className="w-full">
            <Checkbox checked={st.log} onChange={(v) => set({ log: v })} label={<span className="text-small text-muted">{t('an.log')}</span>} />
          </span>
          <Label hint={t('hy.pupilHint')}>{t('hy.pupil')}</Label>
          <NumberField className="h-6 w-14" ariaLabel={t('hy.pupil')} value={st.pupil_samples} integer min={16} max={256} onCommit={(v) => set({ pupil_samples: v ?? 64 })} />
          <Label>{t('hy.image')}</Label>
          <NumberField className="h-6 w-14" ariaLabel={t('hy.image')} value={st.image_samples} integer min={16} max={256} onCommit={(v) => set({ image_samples: v ?? 65 })} />
          <Label hint={t('hy.deltaHint')}>Δ (µm)</Label>
          <NumberField className="h-6 w-16" ariaLabel="Δ (µm)" value={st.image_delta_um} allowInfinity format={(v) => (v === null ? 'auto' : String(v))} placeholder="auto" min={1e-4} max={1e4} title={t('hy.deltaHint')} onCommit={(v) => set({ image_delta_um: v })} />
          <Label hint={t('hy.defocusHint')}>{t('hy.defocus')} (mm)</Label>
          <NumberField className="h-6 w-16" ariaLabel={t('hy.defocus')} value={st.defocus_mm} units={LENGTH_TO_MM} onCommit={(v) => set({ defocus_mm: v ?? 0 })} />
          <Checkbox checked={st.transmission} onChange={(v) => set({ transmission: v })} label={t('hy.trans')} title={t('hy.transHint')} />
        </>
      }
    >
      {data && (
        <div className="grid h-full min-h-0 auto-rows-[minmax(300px,1fr)] grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-px overflow-auto bg-line">
          <div className="flex min-h-0 flex-col bg-panel">
            <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
              <Stat label={t('an.strehl')} value={fmt(data.strehl, 4)} />
              {airy !== null && <Stat label={t('an.airy')} value={fmt(airy, 4)} unit="µm" />}
              <Stat label={t('hy.peak')} value={`${fmt(data.peak_um[0], 3)}, ${fmt(data.peak_um[1], 3)}`} unit="µm" />
              <Stat label="Δ" value={fmt(data.sampling.image_delta_um, 4)} unit="µm" />
              <Stat label={t('hy.rays')} value={String(data.sampling.rays)} />
            </div>
            {data.warnings.map((w) => (
              <div key={w} className="border-b border-line px-3 py-1 text-small text-warn">
                {w}
              </div>
            ))}
            <div className="min-h-0 flex-1">
              <Plot
                square
                data={[
                  {
                    type: 'heatmap',
                    x: data.x_um,
                    y: data.y_um,
                    z,
                    colorscale: COLORMAPS.sequentialAlt,
                    colorbar: { title: { text: st.log ? 'log₁₀ I' : 'I / I₀', side: 'right' }, thickness: 12 },
                    hovertemplate: 'x %{x:.2f} µm<br>y %{y:.2f} µm<br>%{z:.4f}<extra></extra>',
                  },
                  ...(airy !== null
                    ? [
                        {
                          type: 'scatter' as const,
                          mode: 'lines' as const,
                          x: Array.from({ length: 121 }, (_, k) => airy * Math.cos((2 * Math.PI * k) / 120)),
                          y: Array.from({ length: 121 }, (_, k) => airy * Math.sin((2 * Math.PI * k) / 120)),
                          line: { color: 'rgba(255,255,255,0.6)', width: 1, dash: 'dot' as const },
                          hoverinfo: 'skip' as const,
                          showlegend: false,
                        },
                      ]
                    : []),
                ]}
                layout={{ margin: { l: 50, r: 10, t: 8, b: 36 }, xaxis: { title: { text: t('ax.xFromChief') } }, yaxis: { title: { text: 'y (µm)' } }, showlegend: false }}
              />
            </div>
          </div>
          <div className="grid min-h-0 grid-rows-2 gap-px bg-line">
            <div className="bg-panel">
              <Plot
                data={
                  [
                    { type: 'scatter', mode: 'lines', x: data.x_um, y: data.psf[mid], name: 'x section', line: { color: DATA.primary, width: 1.6 } },
                    { type: 'scatter', mode: 'lines', x: data.y_um, y: data.psf.map((r) => r[mid]), name: 'y section', line: { color: DATA.secondary, width: 1.6, dash: 'dash' } },
                  ] as Trace[]
                }
                layout={{ margin: { l: 48, r: 10, t: 22, b: 34 }, title: { text: t('ax.crossSections'), font: { size: 11 } }, xaxis: { title: { text: 'µm' } }, yaxis: { title: { text: 'I / I₀' }, type: st.log ? 'log' : 'linear' }, legend: { orientation: 'h', y: 1.12, x: 1, xanchor: 'right' } }}
              />
            </div>
            <div className="bg-panel">
              <Plot
                data={[{ type: 'scatter', mode: 'lines', x: data.encircled_energy.radius_um, y: data.encircled_energy.fraction, line: { color: DATA.tertiary, width: 1.8 }, name: t('an.encircled'), hovertemplate: 'r %{x:.2f} µm<br>%{y:.4f}<extra></extra>' }]}
                layout={{
                  margin: { l: 48, r: 10, t: 22, b: 34 },
                  title: { text: `${t('an.encircled')} (${t('hy.inWindow')})`, font: { size: 11 } },
                  xaxis: { title: { text: t('ax.radiusUm') } },
                  yaxis: { range: [0, 1.02] },
                  shapes: airy !== null ? [{ type: 'line', x0: airy, x1: airy, yref: 'paper', y0: 0, y1: 1, line: { width: 1, dash: 'dot', color: DATA.reference } }] : [],
                  showlegend: false,
                }}
              />
            </div>
          </div>
        </div>
      )}
    </AnalysisFrame>
  )
}

// ------------------------------------------------------------------ MTF
export function MtfView() {
  const t = useT()
  const [st, set] = useSettings('mtf')
  const settings = { kind: st.kind, max_frequency: st.max_frequency, samples: st.samples, grid: 64, pad: 4 }
  const { data, error, loading, ms, refresh } = useAnalysis<MtfResult>('mtf', settings)
  return (
    <AnalysisFrame
      kind="mtf"
      title={t('view.mtf')}
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
          <Select className="h-6 w-28 text-small" ariaLabel={t('an.kind')} value={st.kind} options={[{ value: 'diffraction', label: t('an.diffraction') }, { value: 'geometric', label: t('an.geometric') }]} onChange={(v) => set({ kind: v })} />
        </>
      }
      more={
        <>
          <Row label={`${t('an.maxFreq')} (cyc/mm)`} hint={t('an.maxFreqHint')}>
            <NumberField className="h-6 w-24" ariaLabel={t('an.maxFreq')} value={st.max_frequency} allowInfinity format={(v) => (v === null ? t('an.cutoff') : String(v))} placeholder={t('an.cutoff')} min={1} onCommit={(v) => set({ max_frequency: v })} />
          </Row>
          {data?.sensor && (
            <Row label={t('an.withSensor')} hint={t('an.withSensorHint')}>
              <Checkbox checked={st.sensor !== false} ariaLabel={t('an.withSensor')} onChange={(v) => set({ sensor: v })} />
            </Row>
          )}
        </>
      }
    >
      {data && (
        // below a minimum size the plot scrolls instead of squashing (laptop split panes)
        <div className="h-full overflow-auto">
          <div className="h-full min-h-60 min-w-80">
            <Plot
              data={[
                ...data.fields.flatMap((f) => [
                  { type: 'scatter', mode: 'lines', x: data.frequency_cyc_per_mm, y: f.tangential, name: `F${f.field + 1} T`, line: { color: fieldColor(f.field), width: 1.8 } },
                  { type: 'scatter', mode: 'lines', x: data.frequency_cyc_per_mm, y: f.sagittal, name: `F${f.field + 1} S`, line: { color: fieldColor(f.field), width: 1.8, dash: 'dash' } },
                ]),
                ...(data.kind === 'diffraction' ? [{ type: 'scatter', mode: 'lines', x: data.frequency_cyc_per_mm, y: data.diffraction_limit, name: t('an.diffLimit'), line: { color: DATA.reference, width: 1.4, dash: 'dot' } }] : []),
                ...(data.sensor && st.sensor !== false
                  ? [
                      { type: 'scatter', mode: 'lines', x: data.frequency_cyc_per_mm, y: data.sensor.pixel_mtf, name: t('an.pixelMtf'), line: { color: DATA.secondary, width: 1.4, dash: 'dashdot' } },
                      ...data.sensor.fields.map((f) => ({ type: 'scatter', mode: 'lines', x: data.frequency_cyc_per_mm, y: f.tangential.map((v, k) => 0.5 * (v + f.sagittal[k])), name: t('an.systemMtf', { f: f.field + 1 }), line: { color: fieldColor(f.field), width: 2.6, dash: 'dot' } })),
                    ]
                  : []),
              ]}
              layout={{ xaxis: { title: { text: t('ax.spatialFreq') } }, yaxis: { title: { text: t('ax.modulation') }, range: [0, 1.02] }, hovermode: 'x unified', margin: { l: 56, r: 16, t: 34, b: 46 }, legend: { orientation: 'h', x: 0, y: 1.01, yanchor: 'bottom', font: { size: 10 } }, shapes: data.sensor && st.sensor !== false ? [{ type: 'line', x0: data.sensor.nyquist_cyc_per_mm, x1: data.sensor.nyquist_cyc_per_mm, yref: 'paper', y0: 0, y1: 1, line: { color: DATA.marker, width: 1.2, dash: 'dash' } }] : [] }}
            />
          </div>
        </div>
      )}
    </AnalysisFrame>
  )
}

// ------------------------------------------------------------------ Gaussian beam
export function GaussianView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const [st, set] = useSettings('gaussian')
  const settings = { waist_radius: st.waist_radius, waist_distance: st.waist_distance, wavelength: st.wavelength !== null && st.wavelength >= system.wavelengths.length ? null : st.wavelength, m2: st.m2 }
  const { data, error, loading, ms, refresh } = useAnalysis<GaussianResult>('gaussian', settings)
  const n = system.surfaces.length
  const z = data?.curve.z ?? []
  const w = data?.curve.w ?? []
  const neg = w.map((v) => (v === null ? null : -v))
  const img = data?.image
  const zImg = data ? data.surface_z[n - 1] : 0
  const waistZ = data && img ? data.surface_z[n - 2] + img.waist_from_last_surface : null
  const surfLines = data
    ? data.surface_z.slice(1).map((zz, k) => ({ type: 'line', x0: zz, x1: zz, yref: 'paper', y0: 0, y1: 1, line: { width: 1, dash: k + 1 === n - 1 ? 'solid' : 'dot', color: k + 1 === n - 1 ? DATA.marker : 'rgba(128,128,128,0.6)' } }))
    : []
  const traces: Trace[] = [
    { type: 'scatter', mode: 'lines', x: z, y: w, name: '+w', line: { color: DATA.primary, width: 1.8 }, hovertemplate: 'z %{x:.4f} mm<br>w %{y:.6f} mm<extra></extra>' },
    { type: 'scatter', mode: 'lines', x: z, y: neg, name: '−w', line: { color: DATA.primary, width: 1.8 }, fill: 'tonexty', fillcolor: DATA.fill, hoverinfo: 'skip' },
  ]
  if (waistZ !== null && img) traces.push({ type: 'scatter', mode: 'markers', x: [waistZ], y: [0], name: 'image waist', marker: { color: DATA.marker, size: 8, symbol: 'diamond' }, hovertemplate: `waist ${fmt(img.waist_radius * 1000, 5)} µm<extra></extra>` })
  return (
    <AnalysisFrame
      kind="gaussian"
      title={t('view.gaussian')}
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
          <Label hint={t('gb.waistHint')}>w₀ (mm)</Label>
          <NumberField className="h-6 w-20" ariaLabel="w₀ (mm)" value={st.waist_radius} min={1e-6} units={LENGTH_TO_MM} onCommit={(v) => set({ waist_radius: v ?? 1 })} />
          <WavelengthSelect system={system} value={settings.wavelength} onChange={(v) => set({ wavelength: v })} />
        </>
      }
      more={
        <>
          <Label hint={t('gb.distanceHint')}>{t('gb.distance')}</Label>
          <NumberField className="h-6 w-20" ariaLabel={t('gb.distance')} value={st.waist_distance} units={LENGTH_TO_MM} onCommit={(v) => set({ waist_distance: v ?? 0 })} />
          <Label hint={t('gb.m2Hint')}>M²</Label>
          <NumberField className="h-6 w-14" ariaLabel="M²" value={st.m2} min={1} max={1000} onCommit={(v) => set({ m2: v ?? 1 })} />
        </>
      }
    >
      {data && img && (
        <div className="flex h-full min-h-0 flex-col">
          <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
            <Stat label={t('gb.waist')} value={fmt(img.waist_radius * 1000, 5)} unit="µm" />
            <Stat label={t('gb.waistPos')} value={fmt(img.waist_from_image_surface, 6)} unit="mm" />
            <Stat label="z_R" value={fmt(img.rayleigh_range, 5)} unit="mm" />
            <Stat label="θ (½)" value={fmt(img.divergence_half_angle_mrad, 5)} unit="mrad" />
            <Stat label={t('gb.atImage')} value={fmt(img.w_at_image_surface * 1000, 5)} unit="µm" />
          </div>
          <div className="min-h-[200px] flex-1">
            <Plot
              data={traces}
              layout={{ showlegend: false, shapes: surfLines, xaxis: { title: { text: `Unfolded axial position from surface 1 (mm) · image surface at ${fmt(zImg, 6)}` } }, yaxis: { title: { text: t('ax.beamRadius') }, zeroline: true } }}
            />
          </div>
          <div className="max-h-[38%] shrink-0 overflow-auto border-t border-line">
            <table className="eng-table">
              <thead>
                <tr>
                  <th>{t('c.surface')}</th>
                  <th className="text-right">w (mm)</th>
                  <th className="text-right">R in (mm)</th>
                  <th className="text-right">R out (mm)</th>
                  <th className="text-right">{t('gb.clip')}</th>
                </tr>
              </thead>
              <tbody>
                {data.surfaces.map((r) => (
                  <tr key={r.surface}>
                    <td className="px-2">{r.surface === n - 1 ? 'Image' : r.surface}</td>
                    <td className="num px-2 text-right">{fmt(r.w, 6)}</td>
                    <td className="num px-2 text-right">{r.R_in === null ? '∞' : fmt(r.R_in, 6)}</td>
                    <td className="num px-2 text-right">{r.R_out === null ? '∞' : fmt(r.R_out, 6)}</td>
                    <td className={`num px-2 text-right ${r.clip_transmission !== undefined && r.clip_transmission < 0.99 ? 'text-warn' : ''}`}>{r.clip_transmission === undefined ? '—' : `${fmt(r.clip_transmission * 100, 6)} %`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.notes.map((x) => (
              <div key={x} className="px-3 py-0.5 text-small text-warn">
                {x}
              </div>
            ))}
            <div className="px-3 py-1.5 text-caption text-faint">{t('gb.help')}</div>
          </div>
        </div>
      )}
    </AnalysisFrame>
  )
}

// ------------------------------------------------------------------ polarisation pupil
const POL_MAPS = {
  transmission: { label: 'Transmission', unit: '', key: 'transmission' },
  diattenuation: { label: 'Diattenuation', unit: '', key: 'diattenuation' },
  retardance: { label: 'Retardance', unit: 'waves', key: 'retardance_waves' },
  rotation: { label: 'Basis rotation', unit: '°', key: 'rotation_deg' },
} as const

/** Round-off (|v| below 1e-9 of a normalised quantity) shown as 0. */
const clean = (v: number) => (Math.abs(v) < 1e-9 ? 0 : v)

export function PolarizationView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const [st, set] = useSettings('polarization')
  const settings = { field: Math.min(st.field, system.fields.length - 1), wavelength: st.wavelength !== null && st.wavelength >= system.wavelengths.length ? null : st.wavelength, grid: st.grid, input: st.input, crystal_modes: st.crystal_modes ?? 'sum' }
  const { data, error, loading, ms, refresh } = useAnalysis<PolarizationResult>('polarization', settings)
  const crystals = data?.crystals ?? []
  const mapInfo = POL_MAPS[st.map]
  const g = data?.grid ?? 0
  const axis = Array.from({ length: g }, (_, k) => -1 + (2 * k) / Math.max(1, g - 1))
  const z: (number | null)[][] = axis.map(() => axis.map(() => null))
  if (data) {
    const vals = data[mapInfo.key] as (number | null)[]
    data.px.forEach((x, k) => {
      const ix = Math.round(((x + 1) / 2) * (g - 1))
      const iy = Math.round(((data.py[k] + 1) / 2) * (g - 1))
      z[iy][ix] = vals[k]
    })
  }
  const traces: Trace[] = data ? [{ type: 'heatmap', x: axis, y: axis, z, colorscale: COLORMAPS.sequentialAlt, colorbar: { title: { text: mapInfo.unit || mapInfo.label }, thickness: 12 }, hovertemplate: `px %{x:.2f} py %{y:.2f}<br>${mapInfo.label} %{z:.4g}<extra></extra>` }] : []
  if (data?.ellipse) {
    const ex: (number | null)[] = []
    const ey: (number | null)[] = []
    const imax = Math.max(1e-30, ...data.transmission.filter((v): v is number => v !== null))
    const cell = 2 / Math.max(1, g - 1)
    data.px.forEach((x0, k) => {
      const az = data.ellipse!.azimuth_rad[k]
      const chi = data.ellipse!.ellipticity_rad[k]
      const I = data.transmission[k]
      if (az === null || chi === null || I === null) return
      const r = 0.42 * cell * Math.sqrt(I / imax)
      const a = Math.cos(chi) * r
      const b = Math.sin(chi) * r
      for (let s = 0; s <= 24; s++) {
        const tt = (2 * Math.PI * s) / 24
        ex.push(x0 + a * Math.cos(tt) * Math.cos(az) - b * Math.sin(tt) * Math.sin(az))
        ey.push(data.py[k] + a * Math.cos(tt) * Math.sin(az) + b * Math.sin(tt) * Math.cos(az))
      }
      ex.push(null)
      ey.push(null)
    })
    traces.push({ type: 'scatter', mode: 'lines', x: ex, y: ey, line: { color: DATA.overlay, width: 1.2 }, hoverinfo: 'skip', name: 'output polarisation' })
  }
  const sm = data?.summary
  return (
    <AnalysisFrame
      kind="polarization"
      title={t('view.polarization')}
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
          <Select
            className="h-6 w-28 text-small"
            ariaLabel={t('pol.input')}
            value={st.input}
            options={[
              { value: 'x', label: 'Linear X' },
              { value: 'y', label: 'Linear Y' },
              { value: '45', label: 'Linear +45°' },
              { value: '-45', label: 'Linear −45°' },
              { value: 'rcp', label: 'Circular R' },
              { value: 'lcp', label: 'Circular L' },
              { value: 'unpolarized', label: 'Unpolarised' },
            ]}
            onChange={(v) => set({ input: v as typeof st.input })}
          />
          <Select className="h-6 w-32 text-small" ariaLabel={t('pol.map')} value={st.map} options={(Object.keys(POL_MAPS) as (keyof typeof POL_MAPS)[]).map((k) => ({ value: k, label: POL_MAPS[k].label }))} onChange={(v) => set({ map: v as typeof st.map })} />
        </>
      }
      more={
        <>
          <FieldSelect system={system} value={settings.field} onChange={(v) => set({ field: v })} />
          <WavelengthSelect system={system} value={settings.wavelength} onChange={(v) => set({ wavelength: v })} />
          <Label hint={t('an.gridHint')}>{t('an.grid')}</Label>
          <NumberField className="h-6 w-12" ariaLabel={t('an.grid')} value={st.grid} integer min={3} max={65} onCommit={(v) => set({ grid: v ?? 15 })} />
          {crystals.length > 0 && (
            <Row label={t('pol.crystalModes')} hint={t('pol.crystalModesHint')}>
              <Select className="h-6 w-36 text-small" ariaLabel={t('pol.crystalModes')} value={settings.crystal_modes} options={[{ value: 'sum', label: t('pol.cm.sum') }, { value: 'prescription', label: t('pol.cm.prescription') }]} onChange={(v) => set({ crystal_modes: v as 'sum' | 'prescription' })} />
            </Row>
          )}
        </>
      }
    >
      {data && sm && (
        <div className="flex h-full min-h-0 flex-col">
          <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
            <Stat label={t('pol.tInput')} value={fmt(sm.input_transmission === null ? null : sm.input_transmission * 100, 5)} unit="%" />
            <Stat label={t('pol.tUnpol')} value={fmt(sm.unpolarized_transmission === null ? null : sm.unpolarized_transmission * 100, 5)} unit="%" />
            <Stat label={t('pol.maxD')} value={fmt(sm.max_diattenuation, 4)} />
            <Stat label={t('pol.rmsRet')} value={fmt(sm.rms_retardance_waves, 4)} unit="waves" />
            <Stat label={t('pol.maxRot')} value={fmt(sm.max_rotation_deg, 4)} unit="°" />
          </div>
          <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_auto] max-[900px]:grid-cols-1">
            <div className="min-h-[220px]">
              <Plot square data={traces} layout={{ showlegend: false, xaxis: { title: { text: t('ax.pupilX') }, range: [-1.08, 1.08] }, yaxis: { title: { text: t('ax.pupilY') }, range: [-1.08, 1.08] } }} />
            </div>
            {sm.mueller && (
              <div className="min-w-0 overflow-auto border-l border-line px-3 py-2 text-small max-[900px]:border-t max-[900px]:border-l-0">
                <div className="mb-1 font-medium" title={t('pol.muellerHint')}>
                  {t('pol.mueller')}
                </div>
                <table className="num">
                  <tbody>
                    {sm.mueller.map((row, r) => (
                      <tr key={r}>
                        {row.map((v, c) => (
                          <td key={c} className="px-1.5 py-0.5 text-right">
                            {fmt(clean(sm.mueller![0][0] > 0 ? v / sm.mueller![0][0] : v), 4)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="mt-1.5 grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-muted">
                  <span title={t('pol.diHint')}>{t('pol.di')}</span>
                  <span className="num text-fg">{fmt(sm.depolarization_index ?? null, 5)}</span>
                  {sm.output_stokes && (
                    <>
                      <span>{t('pol.stokesOut')}</span>
                      <span className="num text-fg">{sm.output_stokes.slice(1).map((v) => fmt(clean(v), 4)).join(', ')}</span>
                    </>
                  )}
                  {sm.output_dop !== undefined && sm.output_dop !== null && (
                    <>
                      <span>{t('pol.dop')}</span>
                      <span className="num text-fg">{fmt(sm.output_dop, 5)}</span>
                    </>
                  )}
                </div>
                {crystals.length > 0 && (
                  <div className="mt-2 space-y-0.5 text-caption text-muted">
                    {crystals.map((c) => (
                      <div key={c.surface}>
                        {t('c.surface')} {c.surface}: {c.material} · n<sub>o</sub> {fmt(c.no, 6)} · n<sub>e</sub> {fmt(c.ne, 6)} · {settings.crystal_modes === 'sum' ? t('pol.cm.sum') : t(`ins.wave.${c.mode}`)}
                      </div>
                    ))}
                    {settings.crystal_modes === 'sum' && (sm.wave_separation_mm ?? 0) > 1e-4 && (
                      <div className="text-warn">
                        {t('pol.separation')}: {fmt(sm.wave_separation_mm ?? 0, 4)} mm
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
          <div className="shrink-0 border-t border-line px-3 py-1 text-caption text-faint">{t('pol.help')}</div>
        </div>
      )}
    </AnalysisFrame>
  )
}
