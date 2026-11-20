import { useEffect, useMemo, useState } from 'react'
import { fieldColor, fmt, wavelengthColor } from '../../lib/format'
import { useT } from '../../lib/i18n'
import type { ChromaticResult, FieldResult, LongitudinalResult, ParaxialResult, Project, RayFanResult, SeidelResult, SpotResult, ThroughputResult } from '../../lib/types'
import { useProjectStore } from '../../store/projectStore'
import { Plot, type Trace } from '../common/Plot'
import { Button, NumberField, Select } from '../common/ui'
import { cx } from '../common/uiUtils'
import { spotGrid } from '../../lib/plotLayout'
import { useAnalysisSettings } from '../common/useAnalysisSettings'
import { Label, Row } from '../common/controls'
import { AnalysisFrame } from './AnalysisFrame'
import { useAnalysis } from './useAnalysis'
import { DATA } from '../../lib/palette'

const DEFAULTS = {
  spot: { pattern: 'hexapolar' as const, density: 6, reference: 'centroid' as const },
  fan: { samples: 41 },
  field: { samples: 21 },
}

function useSettings<K extends keyof typeof DEFAULTS>(key: K) {
  return useAnalysisSettings(key, DEFAULTS[key] as NonNullable<Project['analysis_settings'][K]>)
}

function fieldLabel(v: [number, number], type: string) {
  return `${fmt(v[1], 4)}${type === 'angle' ? '°' : ' mm'}`
}

// ------------------------------------------------------------------ spot
export function SpotView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const [st, setSettings] = useSettings('spot')
  const { data, error, loading, ms, refresh } = useAnalysis<SpotResult>('spot', st)
  const nf = data?.fields.length ?? 0
  // the grid element comes and goes with the result: observe whichever element is mounted (callback ref)
  const [gridEl, setGridEl] = useState<HTMLDivElement | null>(null)
  const [box, setBox] = useState({ w: 900, h: 400 })
  useEffect(() => {
    if (!gridEl) return
    const measure = () => setBox((b) => (b.w === gridEl.clientWidth && b.h === gridEl.clientHeight ? b : { w: gridEl.clientWidth, h: gridEl.clientHeight }))
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(gridEl)
    return () => ro.disconnect()
  }, [gridEl])
  // the column count that gives the largest square cells; in a small pane the cells keep a minimum size and scroll
  const { cols, rowHeight } = spotGrid(nf, box.w, box.h)
  const plots = useMemo(() => {
    if (!data) return []
    // common scale across fields so spots are comparable
    let maxR = 0
    for (const f of data.fields) for (const w of f.per_wavelength) for (const p of w.points_um) maxR = Math.max(maxR, Math.abs(p[0]), Math.abs(p[1]))
    if (data.airy_radius_um) maxR = Math.max(maxR, data.airy_radius_um)
    const lim = maxR * 1.12 || 1
    return data.fields.map((f) => {
      const traces: Trace[] = f.per_wavelength.map((w) => ({
        type: 'scattergl',
        mode: 'markers',
        x: w.points_um.map((p) => p[0]),
        y: w.points_um.map((p) => p[1]),
        name: `${fmt(system.wavelengths[w.wavelength]?.value * 1000, 5)} nm`,
        marker: { size: 3.2, color: wavelengthColor(system.wavelengths[w.wavelength]?.value ?? 0.55) },
        hovertemplate: 'x %{x:.3f} µm<br>y %{y:.3f} µm<extra></extra>',
        showlegend: false,
      }))
      if (data.airy_radius_um) {
        const a = Array.from({ length: 121 }, (_, k) => (2 * Math.PI * k) / 120)
        traces.push({ type: 'scatter', mode: 'lines', x: a.map((q) => data.airy_radius_um! * Math.cos(q)), y: a.map((q) => data.airy_radius_um! * Math.sin(q)), name: 'Airy', line: { color: 'rgba(160,170,190,0.7)', width: 1, dash: 'dot' }, hoverinfo: 'skip', showlegend: false })
      }
      return { f, traces, lim }
    })
  }, [data, system.wavelengths])

  return (
    <AnalysisFrame
      kind="spot"
      title={t('view.spot')}
      loading={loading}
      error={error}
      hasData={!!data}
      ms={ms}
      method={data ? `${data.method}; ${data.settings.rays_per_wavelength} ${t('an.rays')}/λ (${data.settings.pattern}, density ${data.settings.density})` : undefined}
      onRefresh={refresh}
      settings={st}
      result={data}
      controls={
        <>
          <Label hint={t('an.patternHint')}>{t('an.pattern')}</Label>
          <Select cell={false} className="h-6 w-[104px] text-small" ariaLabel={t('an.pattern')} value={st.pattern} options={[{ value: 'hexapolar', label: t('sp.hexapolar') }, { value: 'square', label: t('sp.square') }, { value: 'dithered', label: t('sp.dithered') }]} onChange={(v) => setSettings({ pattern: v })} />
          <Label hint={t('an.densityHint')}>{t('an.density')}</Label>
          <NumberField className="h-6 w-14" ariaLabel={t('an.density')} value={st.density} integer min={1} max={64} onCommit={(v) => setSettings({ density: v ?? 6 })} />
        </>
      }
      more={
        <Row label={t('an.reference')} hint={t('an.referenceHint')}>
          <Select className="h-6 w-[120px] text-small" ariaLabel={t('an.reference')} value={st.reference} options={[{ value: 'centroid', label: t('an.centroid') }, { value: 'chief', label: t('an.chief') }]} onChange={(v) => setSettings({ reference: v })} />
        </Row>
      }
    >
      <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-line px-2.5 py-1 text-caption text-muted">
        {system.wavelengths.map((w, i) => (
          <span key={i} className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: wavelengthColor(w.value) }} />
            {fmt(w.value * 1000, 5)} nm
          </span>
        ))}
        {data?.airy_radius_um ? <span className="flex items-center gap-1"><span className="inline-block h-0 w-4 border-t border-dotted border-muted" />{t('an.airy')} {fmt(data.airy_radius_um, 4)} µm ({t('sp.airyBasis')})</span> : null}
        <span className="ml-auto">{t('sp.relative', { ref: st.reference === 'chief' ? t('an.chief') : t('an.centroid') })}</span>
      </div>
      <div ref={setGridEl} className={cx('grid min-h-0 flex-1 gap-px bg-line', rowHeight !== null && 'content-start overflow-y-auto')} style={{ gridTemplateColumns: `repeat(${Math.max(cols, 1)}, minmax(0,1fr))`, gridAutoRows: rowHeight ? `${rowHeight}px` : 'minmax(0,1fr)' }}>
        {plots.map(({ f, traces, lim }) => (
          <div key={f.field} className="flex min-h-0 flex-col bg-panel">
            <div className="flex flex-wrap items-center gap-x-2 px-2.5 pt-1.5 text-small">
              <span className="font-semibold whitespace-nowrap">
                <span className="mr-1.5 inline-block h-2 w-2 rounded-full align-middle" style={{ background: fieldColor(f.field) }} aria-hidden />
                {t('an.field')} {f.field + 1} <span className="font-normal text-muted">{fieldLabel(f.field_value, system.field_type)}</span>
              </span>
              <span className="ml-auto num whitespace-nowrap">
                RMS <b>{fmt(f.rms_radius_um, 4)}</b> · GEO {fmt(f.geo_radius_um, 4)} µm
              </span>
            </div>
            <div className="min-h-0 flex-1 overflow-hidden">
              <Plot
                square
                data={traces}
                layout={{
                  margin: { l: 46, r: 10, t: 6, b: 34 },
                  xaxis: { range: [-lim, lim], title: { text: 'x (µm)' }, zeroline: true },
                  yaxis: { range: [-lim, lim], title: { text: 'y (µm)' }, zeroline: true },
                  showlegend: false,
                }}
              />
            </div>
            <div className="truncate px-2.5 pb-1 text-caption text-faint num" title={`${t('an.reference')} (${f.reference_xy?.[0]}, ${f.reference_xy?.[1]}) mm`}>
              {t('sp.refY')} {fmt(f.reference_xy?.[1], 6)} mm · {f.per_wavelength.reduce((a, w) => a + w.n_ok, 0)}/{f.per_wavelength.reduce((a, w) => a + w.n_rays, 0)} {t('an.rays')}
            </div>
          </div>
        ))}
        {/* empty slots of the last row take the panel colour, not the grid-line colour */}
        {Array.from({ length: (Math.max(cols, 1) - (plots.length % Math.max(cols, 1))) % Math.max(cols, 1) }, (_, k) => (
          <div key={`empty-${k}`} className="bg-panel" />
        ))}
      </div>
      </div>
    </AnalysisFrame>
  )
}

// ------------------------------------------------------------------ ray fan
export function RayFanView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const [st, setSettings] = useSettings('fan')
  const { data, error, loading, ms, refresh } = useAnalysis<RayFanResult>('rayfan', st)
  return (
    <AnalysisFrame
      kind="rayfan"
      title={t('view.rayfan')}
      loading={loading}
      error={error}
      hasData={!!data}
      ms={ms}
      method={data?.method}
      onRefresh={refresh}
      settings={st}
      result={data}
      controls={
        <>
          <Label hint={t('an.samplesHint')}>{t('an.samples')}</Label>
          <NumberField className="h-6 w-14" ariaLabel={t('an.samples')} value={st.samples} integer min={3} max={401} onCommit={(v) => setSettings({ samples: v ?? 41 })} />
        </>
      }
    >
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
                    {fieldLabel(f.field_value, system.field_type)} · {kind === 'tangential' ? `${t('an.tangential')} ${alongY(f.direction) ? 'e_y(P_y)' : 'e_T(P_T)'}` : `${t('an.sagittal')} ${alongY(f.direction) ? 'e_x(P_x)' : 'e_S(P_S)'}`}
                  </span>
                </div>
                <div className="min-h-0 flex-1">
                  <Plot
                    data={f.per_wavelength.map((w) => ({
                      type: 'scatter',
                      mode: 'lines',
                      x: data.pupil,
                      y: kind === 'tangential' ? w.tangential_ey_um : w.sagittal_ex_um,
                      name: `${fmt(system.wavelengths[w.wavelength]?.value * 1000, 5)} nm`,
                      line: { color: wavelengthColor(system.wavelengths[w.wavelength]?.value ?? 0.55), width: 1.6 },
                      connectgaps: false,
                      hovertemplate: 'P %{x:.3f}<br>%{y:.4f} µm<extra></extra>',
                      showlegend: f.field === 0 && kind === 'tangential',
                    }))}
                    layout={{ margin: { l: 52, r: 10, t: 6, b: 30 }, xaxis: { range: [-1, 1], title: { text: alongY(f.direction) ? (kind === 'tangential' ? 'P_y' : 'P_x') : kind === 'tangential' ? 'P_T' : 'P_S' } }, yaxis: { title: { text: 'µm' } }, legend: { orientation: 'h', y: 1, yanchor: 'bottom' }, hovermode: 'x unified' }}
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

/** Fans of a field along +y (or without a direction from an older engine) keep the x/y names; other azimuths use
 * tangential (T: along the field) and sagittal (S: across it). */
const alongY = (d?: [number, number]) => !d || (Math.abs(d[0]) < 1e-12 && d[1] > 0)

// ------------------------------------------------------------------ field curvature & distortion
export function FieldView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const [st, setSettings] = useSettings('field')
  const { data, error, loading, ms, refresh } = useAnalysis<FieldResult>('field', st)
  const unit = system.field_type === 'angle' ? '°' : 'mm'
  return (
    <AnalysisFrame
      kind="field"
      title={t('view.field')}
      loading={loading}
      error={error}
      hasData={!!data}
      ms={ms}
      method={data?.method}
      onRefresh={refresh}
      settings={st}
      result={data}
      controls={
        <>
          <span className="text-small text-muted">{t('an.samples')}</span>
          <NumberField className="h-6 w-14" value={st.samples} integer min={2} max={201} onCommit={(v) => setSettings({ samples: v ?? 21 })} />
        </>
      }
    >
      {data && (
        <div className="grid h-full grid-cols-2 gap-px bg-line">
          <div className="bg-panel">
            <Plot
              data={data.per_wavelength.flatMap((w) => {
                const c = wavelengthColor(system.wavelengths[w.wavelength]?.value ?? 0.55)
                const nm = fmt(system.wavelengths[w.wavelength]?.value * 1000, 5)
                return [
                  { type: 'scatter', mode: 'lines', x: w.tangential_mm, y: data.field_values, name: `T ${nm}`, line: { color: c, width: 1.6 }, hovertemplate: 'T %{x:.5f} mm<extra></extra>' },
                  { type: 'scatter', mode: 'lines', x: w.sagittal_mm, y: data.field_values, name: `S ${nm}`, line: { color: c, width: 1.6, dash: 'dash' }, hovertemplate: 'S %{x:.5f} mm<extra></extra>' },
                ] as Trace[]
              })}
              layout={{ title: { text: t('ax.fieldCurvature'), font: { size: 11.5 } }, xaxis: { title: { text: t('ax.focusShift') } }, yaxis: { title: { text: `Field (${unit})` }, rangemode: 'tozero' }, margin: { l: 56, r: 12, t: 30, b: 60 } }}
            />
          </div>
          <div className="bg-panel">
            <Plot
              data={data.per_wavelength.map((w) => ({
                type: 'scatter',
                mode: 'lines',
                x: w.distortion_percent,
                y: data.field_values,
                name: `${fmt(system.wavelengths[w.wavelength]?.value * 1000, 5)} nm`,
                line: { color: wavelengthColor(system.wavelengths[w.wavelength]?.value ?? 0.55), width: 1.6 },
                hovertemplate: '%{x:.5f} %<extra></extra>',
              }))}
              layout={{ title: { text: t('an.distortion'), font: { size: 11.5 } }, xaxis: { title: { text: t('ax.distortion') } }, yaxis: { title: { text: `Field (${unit})` }, rangemode: 'tozero' }, margin: { l: 56, r: 12, t: 30, b: 60 } }}
            />
          </div>
        </div>
      )}
    </AnalysisFrame>
  )
}

// ------------------------------------------------------------------ longitudinal
export function LongitudinalView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const st = { samples: 31 }
  const { data, error, loading, ms, refresh } = useAnalysis<LongitudinalResult>('longitudinal', st)
  return (
    <AnalysisFrame kind="longitudinal" title={t('view.longitudinal')} loading={loading} error={error} hasData={!!data} ms={ms} method={data?.method} onRefresh={refresh} settings={st} result={data}>
      {data && (
        <Plot
          data={data.per_wavelength.map((w) => ({
            type: 'scatter',
            mode: 'lines',
            x: w.focus_mm,
            y: data.pupil,
            name: `${fmt(system.wavelengths[w.wavelength]?.value * 1000, 5)} nm`,
            line: { color: wavelengthColor(system.wavelengths[w.wavelength]?.value ?? 0.55), width: 1.8 },
            hovertemplate: 'z %{x:.5f} mm<br>P %{y:.3f}<extra></extra>',
          }))}
          layout={{ xaxis: { title: { text: t('ax.axialIntercept') } }, yaxis: { title: { text: t('ax.pupilHeight') }, range: [0, 1.02] } }}
        />
      )}
    </AnalysisFrame>
  )
}

// ------------------------------------------------------------------ chromatic focal shift
export function ChromaticView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const lmin = Math.min(...system.wavelengths.map((w) => w.value), 0.45)
  const lmax = Math.max(...system.wavelengths.map((w) => w.value), 0.7)
  const st = { samples: 81, lambda_min: Math.round(lmin * 1000) / 1000, lambda_max: Math.round(lmax * 1000) / 1000 }
  const { data, error, loading, ms, refresh } = useAnalysis<ChromaticResult>('chromatic', st)
  return (
    <AnalysisFrame kind="chromatic" title={t('view.chromatic')} loading={loading} error={error} hasData={!!data} ms={ms} method={data?.method} onRefresh={refresh} settings={st} result={data}>
      {data && (
        <Plot
          data={[
            { type: 'scatter', mode: 'lines', x: data.focal_shift_um, y: data.wavelength_um, line: { color: DATA.primary, width: 2 }, name: 'Focal shift', hovertemplate: '%{x:.3f} µm @ %{y:.4f} µm<extra></extra>' },
            ...system.wavelengths.map((w) => ({
              type: 'scatter' as const,
              mode: 'markers' as const,
              x: [interp(data.wavelength_um, data.focal_shift_um, w.value)],
              y: [w.value],
              marker: { color: wavelengthColor(w.value), size: 8 },
              name: `${fmt(w.value * 1000, 5)} nm`,
            })),
          ]}
          layout={{ xaxis: { title: { text: t('ax.focalShiftUm') } }, yaxis: { title: { text: t('ax.wavelengthUm') } } }}
        />
      )}
    </AnalysisFrame>
  )
}

function interp(xs: number[], ys: number[], x: number): number {
  for (let i = 0; i + 1 < xs.length; i++) if (x >= xs[i] && x <= xs[i + 1]) return ys[i] + ((ys[i + 1] - ys[i]) * (x - xs[i])) / (xs[i + 1] - xs[i])
  return NaN
}

// ------------------------------------------------------------------ system data
export function SystemDataView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const st = {}
  const { data, error, loading, ms, refresh } = useAnalysis<ParaxialResult>('paraxial', st)
  const [wl, setWl] = useState(system.primary_wavelength)
  const pd = data?.per_wavelength[Math.min(wl, (data?.per_wavelength.length ?? 1) - 1)]
  const rows: [string, number | null | undefined, string, string?][] = pd
    ? [
        ['Effective focal length (EFL)', pd.efl, 'mm', 'Image-space EFL = 1/power (paraxial)'],
        ['Back focal length (BFL)', pd.bfl, 'mm', 'Last surface to paraxial rear focus'],
        ['Front focal point', pd.ffl, 'mm', 'Relative to surface 1 vertex'],
        ['Front principal plane', pd.front_principal_plane, 'mm', 'Relative to surface 1 vertex'],
        ['Rear principal plane', pd.rear_principal_plane, 'mm', 'Relative to last optical surface'],
        ['Power', pd.power, '1/mm'],
        ['Image-space F/#', pd.image_space_fnum, '', 'EFL / EPD'],
        ['Working F/#', pd.working_fnum, '', '1 / (2 n′ |u′|) from the paraxial marginal ray'],
        ['Image-space NA', pd.image_space_na, ''],
        ['Object-space NA', pd.object_space_na, ''],
        ['Entrance pupil diameter', pd.entrance_pupil_diameter, 'mm'],
        ['Entrance pupil position', pd.entrance_pupil_position, 'mm', 'Relative to surface 1 vertex'],
        ['Exit pupil diameter', pd.exit_pupil_diameter, 'mm'],
        ['Exit pupil position', pd.exit_pupil_position, 'mm', 'Relative to the image surface'],
        ['Stop semi-diameter', pd.stop_semi_diameter, 'mm'],
        ['Paraxial magnification', pd.paraxial_magnification, ''],
        ['Paraxial image distance', pd.paraxial_image_distance, 'mm', 'From last surface, signed thickness units'],
        ['Image surface defocus', pd.image_surface_defocus, 'mm', 'Last thickness − paraxial image distance'],
        ['Paraxial image height', pd.paraxial_image_height, 'mm', 'Chief ray, max field, at the paraxial image plane'],
        ['Lagrange invariant', pd.lagrange_invariant, 'mm'],
        ['Total track', pd.total_track, 'mm', 'Sum of thicknesses, surface 1 to image'],
        ['Maximum field', pd.max_field, system.field_type === 'angle' ? '°' : 'mm'],
      ]
    : []
  const seidel = data && !('error' in data.seidel) ? (data.seidel as SeidelResult) : null
  const tp = useAnalysis<ThroughputResult>('throughput', {}).data
  return (
    <AnalysisFrame
      kind="paraxial"
      title={t('view.systemdata')}
      loading={loading}
      error={error}
      hasData={!!data}
      ms={ms}
      method={data?.method}
      onRefresh={refresh}
      settings={st}
      result={data}
      controls={
        <>
          <span className="text-small text-muted">{t('c.wavelength')}</span>
          <Select className="h-6 w-[130px] text-small" value={wl} options={system.wavelengths.map((w, i) => ({ value: i, label: `${fmt(w.value * 1000, 6)} nm${i === system.primary_wavelength ? ' (primary)' : ''}` }))} onChange={setWl} />
        </>
      }
    >
      <div className="grid h-full auto-rows-min grid-cols-[repeat(auto-fit,minmax(330px,1fr))] gap-px overflow-auto bg-line">
        <div className="bg-panel">
          <div className="px-3 pt-2 pb-1 text-small font-semibold tracking-wide text-muted uppercase">{t('an.paraxial')}</div>
          {pd?.approximate && <div className="mx-3 mb-1 rounded bg-warn/10 px-2 py-1 text-small text-warn">{t('sd.cbApprox')}</div>}
          <table className="eng-table">
            <tbody>
              {rows.map(([label, v, unit, hint]) => (
                <tr key={label} title={hint}>
                  <td className="px-3 text-muted">{label}</td>
                  <td className="num px-3 text-right">{fmt(v ?? null, 8)}</td>
                  <td className="px-2 text-faint">{unit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="overflow-x-auto bg-panel">
          <div className="px-3 pt-2 pb-1 text-small font-semibold tracking-wide text-muted uppercase">{t('an.seidel')}</div>
          {seidel ? (
            <>
              <table className="eng-table">
                <thead>
                  <tr>
                    {['Surf', 'S_I sph', 'S_II coma', 'S_III astig', 'S_IV Petzval', 'S_V dist', 'C_L axial', 'C_T lateral'].map((h) => (
                      <th key={h} className="text-right first:text-left">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[...seidel.surfaces, { surface: -1, ...seidel.total }].map((r) => (
                    <tr key={r.surface} className={r.surface === -1 ? 'font-semibold' : ''}>
                      <td className="px-2">{r.surface === -1 ? 'Σ' : r.surface}</td>
                      {(['SI', 'SII', 'SIII', 'SIV', 'SV', 'CL', 'CT'] as const).map((k) => (
                        <td key={k} className="num px-2 text-right">
                          {r[k].toExponential(4)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="px-3 py-2 text-caption leading-relaxed text-faint">
                Third-order sums (mm) from paraxial marginal and chief rays (Welford formulation; wavefront W040 = S_I/8). Signs follow OptiCore's slope convention. Valid for rotationally symmetric systems; real-ray analyses are authoritative.
              </div>
            </>
          ) : (
            <div className="p-3 text-muted">{data && 'error' in data.seidel ? data.seidel.error : '—'}</div>
          )}
        </div>
        <div className="overflow-x-auto bg-panel">
          <div className="px-3 pt-2 pb-1 text-small font-semibold tracking-wide text-muted uppercase">{t('an.transmission')}</div>
          {tp ? (
            <>
              <table className="eng-table">
                <thead>
                  <tr>
                    <th>{t('c.field')}</th>
                    <th>λ (nm)</th>
                    <th className="text-right">{t('an.unvignetted')}</th>
                    <th className="text-right">{t('an.fresnelAbs')}</th>
                    <th className="text-right">{t('an.total')}</th>
                  </tr>
                </thead>
                <tbody>
                  {tp.fields.flatMap((f) =>
                    f.per_wavelength.map((w) => (
                      <tr key={`${f.field}-${w.wavelength}`}>
                        <td className="px-2">F{f.field + 1}</td>
                        <td className="num px-2">{fmt(system.wavelengths[w.wavelength]?.value * 1000, 6)}</td>
                        <td className="num px-2 text-right">{fmt(w.geometric * 100, 5)}%</td>
                        <td className="num px-2 text-right">{w.surface_losses === null ? '—' : `${fmt(w.surface_losses * 100, 5)}%`}</td>
                        <td className="num px-2 text-right font-semibold">{fmt(w.total * 100, 5)}%</td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
              <div className="px-3 pt-2 text-small text-muted">
                {t('an.weightedMean')}: <span className="num font-semibold text-fg">{fmt(tp.weighted_mean_total * 100, 5)}%</span>
              </div>
              <table className="eng-table mt-1">
                <thead>
                  <tr>
                    <th>{t('c.surface')}</th>
                    <th className="text-right">T (chief, on-axis)</th>
                    <th className="text-right">{t('an.cumulative')}</th>
                  </tr>
                </thead>
                <tbody>
                  {tp.chief_ray_surfaces.map((r) => (
                    <tr key={r.surface}>
                      <td className="px-2">
                        {r.surface}
                        {r.mirror ? (r.coating ? ` (mirror, ${r.coating})` : ' (mirror, ideal)') : r.coating ? ` (${r.coating})` : ''}
                      </td>
                      <td className="num px-2 text-right">{fmt(r.transmission * 100, 6)}%</td>
                      <td className="num px-2 text-right">{fmt(r.cumulative * 100, 6)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {tp.absorption && tp.absorption.materials.length > 0 && (
                <div className="px-3 pt-2 text-small text-muted">
                  {t('an.absorption')}: {tp.absorption.materials.map((m) => `${m.name} (${t(`an.absSource.${m.source}`)})`).join(', ')}
                </div>
              )}
              {(tp.notes ?? []).map((nt) => (
                <div key={nt} className="flex flex-wrap items-center gap-2 px-3 pt-1 text-small text-warn">
                  <span>{nt}</span>
                  <Button variant="link" onClick={() => useProjectStore.getState().updateSystem({ catalog_absorption: true }, 'Catalogue absorption on')}>
                    {t('an.useCatalog')}
                  </Button>
                </div>
              ))}
              <div className="px-3 py-2 text-caption leading-relaxed text-faint">{tp.method}.</div>
            </>
          ) : (
            <div className="p-3 text-muted">—</div>
          )}
        </div>
      </div>
    </AnalysisFrame>
  )
}
