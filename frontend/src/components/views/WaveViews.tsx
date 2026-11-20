import { Play, Square, Wand2, X } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { resolvePlacement, surfaceFrames } from '../../lib/placement'
import type { FibreSettings } from '../../lib/fibre'
import type { FdtdSettings, FdtdShape, ImportedField, PopMode, PopResult, PopSource } from '../../lib/types'
import { LENGTH_TO_MM } from '../../lib/units'
import { useEngineStore } from '../../store/engineStore'
import { fdtdKey, useFdtdStore } from '../../store/fdtdStore'
import { selectDetectors, selectSources, useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { Handle } from '../common/Handle'
import { Plot, type Trace } from '../common/Plot'
import { Badge, Button, Checkbox, IconButton, NumberField, Select } from '../common/ui'
import { Label, Row, Stat, WavelengthSelect } from '../common/controls'
import { useAnalysisSettings } from '../common/useAnalysisSettings'
import { AnalysisFrame } from './AnalysisFrame'
import { useAnalysis } from './useAnalysis'
import { COLORMAPS, DATA } from '../../lib/palette'

const UM: Record<string, number> = { um: 1, µm: 1, nm: 1e-3, mm: 1e3 }

export function Notes({ notes }: { notes: string[] }) {
  if (!notes.length) return null
  return (
    <div className="space-y-0.5 border-t border-line px-3 py-1.5 text-small text-warn">
      {notes.map((n, i) => (
        <div key={i}>• {n}</div>
      ))}
    </div>
  )
}

// ================================================================== physical-optics propagation
type PopSettings = {
  source: PopSource
  wavelength: number | null
  target_offset: number
  grid: number
  out_grid: number
  out_window: number | null
  receive: 'none' | 'gaussian' | 'fibre'
  mode_waist: number
  mode_fibre: { core_radius_um: number; na: number; n_clad: number }
  detector_radius: number | null
  show: 'irradiance' | 'phase'
  view: 'target' | 'side'
  side_norm: boolean
  side_log: boolean
  /** 'pop': ray transfer through the lenses; 'bpm': the wave propagated inside the glass */
  method: 'pop' | 'bpm'
  bpm_step_um: number | null
  /** a field handed over from the rotationally symmetric FDTD (source kind 'field') */
  field_source: ImportedField | null
}
const POP_DEFAULTS: PopSettings = {
  source: { kind: 'gaussian', waist_x: 0.0052, waist_z: 0 },
  wavelength: null,
  target_offset: 0,
  grid: 128,
  out_grid: 128,
  out_window: null,
  receive: 'none',
  mode_waist: 0.0052,
  mode_fibre: { core_radius_um: 4.1, na: 0.12, n_clad: 1.444 },
  detector_radius: null,
  show: 'irradiance',
  view: 'target',
  side_norm: true,
  side_log: false,
  method: 'pop',
  bpm_step_um: null,
  field_source: null,
}

const POP_DEFAULTS_INFINITE: PopSettings = { ...POP_DEFAULTS, source: { kind: 'pupil' } }

export function PopView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const sources = useProjectStore(selectSources)
  const detectors = useProjectStore(selectDetectors)
  const ev = useEngineStore((s) => s.evaluation)
  const infinite = system.surfaces[0].thickness === null
  // an imaging lens (object at infinity) sees a beam that fills its pupil; a fibre system a fibre-sized waist
  const [st, set] = useAnalysisSettings<PopSettings>('pop', infinite ? POP_DEFAULTS_INFINITE : POP_DEFAULTS)
  const src = st.source
  const mode: PopMode | null = st.receive === 'gaussian' ? { kind: 'gaussian', waist: st.mode_waist } : st.receive === 'fibre' ? { kind: 'fibre', ...st.mode_fibre } : null
  const fieldSrc = st.field_source
  const kind = (src.kind === 'field' && !fieldSrc) || (src.kind === 'pupil' && !infinite) ? 'gaussian' : src.kind
  const settings = {
    source:
      kind === 'pupil'
        ? { kind: 'pupil' }
        : kind === 'fibre'
        ? { kind: 'fibre', core_radius_um: src.core_radius_um ?? 4.1, na: src.na ?? 0.12, n_clad: src.n_clad ?? 1.444 }
        : kind === 'tophat'
          ? { kind: 'tophat', radius: src.radius ?? 0.01 }
          : kind === 'field' && fieldSrc
            ? { kind: 'field', ...fieldSrc }
            : { kind: 'gaussian', waist_x: src.waist_x ?? 0.0052, waist_z: src.waist_z ?? 0 },
    method: st.method,
    ...(st.method === 'bpm' && st.bpm_step_um ? { bpm_step_um: st.bpm_step_um } : {}),
    wavelength: st.wavelength !== null && st.wavelength >= system.wavelengths.length ? null : st.wavelength,
    target_offset: st.target_offset,
    grid: st.grid,
    out_grid: st.out_grid,
    out_window: st.out_window,
    target_mode: mode,
    detector_radius: st.detector_radius,
    side_view: st.view === 'side',
  }
  const { data, error, loading, ms, refresh } = useAnalysis<PopResult>('pop', settings)
  const setSrc = (patch: Partial<PopSource>) => set({ source: { ...src, ...patch } })

  // take the beam from the project's first Gaussian emitter and the radius of its first detector
  const gaussSrc = sources.find((s) => s.enabled && (s.kind === 'gaussian_beam' || (s.kind === 'emitter' && s.spatial === 'gaussian')))
  const det = detectors.find((d) => d.enabled && d.shape === 'circle')
  const fromProject = () => {
    const patch: Partial<PopSettings> = {}
    if (gaussSrc) {
      // waist at the source plane if the source sits on the object surface (anchored) or at its z
      let zw = 0
      if (ev && gaussSrc.placement) {
        const fr = surfaceFrames(ev.surfaces)
        const zs = resolvePlacement(gaussSrc.placement, fr).t[2]
        const zObj = ev.surfaces[0].origin[2]
        zw = zs - zObj
      }
      patch.source =
        gaussSrc.kind === 'gaussian_beam'
          ? // a Gaussian beam source: its waist, which may lie ahead of or behind the source plane
            { kind: 'gaussian', waist_x: gaussSrc.beam_waist_x ?? 0.5, waist_y: gaussSrc.beam_waist_y ?? 0.5, waist_z: zw + (gaussSrc.beam_waist_z ?? 0) }
          : { kind: 'gaussian', waist_x: gaussSrc.gaussian_wx, waist_y: gaussSrc.gaussian_wy, waist_z: zw }
    }
    if (det) patch.detector_radius = det.size_x
    set(patch, 'POP settings from the project source and detector')
  }

  const tg = data?.target
  const cx = tg ? (tg.centroid_mm[0] ?? 0) : 0
  const cy = tg ? (tg.centroid_mm[1] ?? 0) : 0
  const cells = (axis: number[], n: number) => axis.filter((_, i) => i % Math.max(1, Math.round(axis.length / n)) === 0).slice(0, n)
  const xs = useMemo(() => (tg ? (tg.map_x ?? cells(tg.x, tg.irradiance[0].length)).map((v) => (v - cx) * 1000) : []), [tg, cx])
  const ys = useMemo(() => (tg ? (tg.map_y ?? cells(tg.y, tg.irradiance.length)).map((v) => (v - cy) * 1000) : []), [tg, cy])
  const xFull = tg ? tg.x.map((v) => (v - cx) * 1000) : []
  const yFull = tg ? tg.y.map((v) => (v - cy) * 1000) : []
  const shapes: Trace[] = []
  if (tg?.detector_radius) {
    const r = tg.detector_radius * 1000
    shapes.push({ type: 'circle', x0: -r - cx * 1000, x1: r - cx * 1000, y0: -r - cy * 1000, y1: r - cy * 1000, line: { color: DATA.target, width: 1.5, dash: 'dot' } })
  }
  return (
    <AnalysisFrame
      kind="pop"
      title={t('view.pop')}
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
            ariaLabel={t('pop.source')}
            title={t('pop.sourceHint')}
            value={kind}
            options={[
              ...(infinite ? [{ value: 'pupil' as const, label: t('pop.pupil') }] : []),
              { value: 'gaussian', label: t('pop.gaussian') },
              ...(infinite ? [] : [{ value: 'fibre' as const, label: t('pop.fibre') }]),
              { value: 'tophat', label: t('pop.tophat') },
              ...(fieldSrc && !infinite ? [{ value: 'field' as const, label: t('pop.fieldSrc') }] : []),
            ]}
            onChange={(v) => setSrc({ kind: v })}
          />
          <WavelengthSelect system={system} value={settings.wavelength} onChange={(v) => set({ wavelength: v })} />
        </>
      }
      more={
        <>
          <Row label={t('pop.view')}>
            <Select
              className="h-6 w-40 text-small"
              ariaLabel={t('pop.view')}
              value={st.view}
              options={[
                { value: 'target', label: t('pop.viewTarget') },
                { value: 'side', label: t('pop.viewSide') },
              ]}
              onChange={(v) => set({ view: v })}
            />
          </Row>
          <Row label={t('pop.method')} hint={t('pop.methodHint')}>
            <Select
              className="h-6 w-40 text-small"
              ariaLabel={t('pop.method')}
              value={st.method}
              options={[
                { value: 'pop', label: t('pop.methodPop') },
                { value: 'bpm', label: t('pop.methodBpm') },
              ]}
              onChange={(v) => set({ method: v })}
            />
          </Row>
          {kind === 'field' && fieldSrc && (
            <>
              <Label hint={t('pop.fieldOffsetHint')}>{t('pop.fieldOffset')}</Label>
              <NumberField className="h-6 w-20" value={fieldSrc.plane_offset_mm} min={0} units={LENGTH_TO_MM} onCommit={(v) => set({ field_source: { ...fieldSrc, plane_offset_mm: v ?? 0 } })} />
              <span className="text-caption text-faint" title={`λ ${fieldSrc.wavelength_um} µm, n ${fieldSrc.n_medium}`}>
                {t('pop.fieldInfo', { o: fieldSrc.origin ?? 'FDTD', n: fieldSrc.r_um.length, p: fmt(fieldSrc.power * 100, 4) })}
              </span>
            </>
          )}
          {src.kind === 'gaussian' && (
            <>
              <Label hint={t('pop.waistHint')}>w₀</Label>
              <NumberField className="h-6 w-20" value={src.waist_x ?? 0.0052} min={1e-6} units={LENGTH_TO_MM} onCommit={(v) => v && setSrc({ waist_x: v, waist_y: v })} />
              <Label hint={infinite ? t('pop.waistZInfHint') : t('pop.waistZHint')}>{t('pop.waistZ')}</Label>
              <NumberField className="h-6 w-16" value={src.waist_z ?? 0} units={LENGTH_TO_MM} onCommit={(v) => setSrc({ waist_z: v ?? 0 })} />
            </>
          )}
          {src.kind === 'fibre' && (
            <>
              <Label hint={t('fm.coreHint')}>a (µm)</Label>
              <NumberField className="h-6 w-14" value={src.core_radius_um ?? 4.1} min={0.01} onCommit={(v) => v && setSrc({ core_radius_um: v })} />
              <Label>NA</Label>
              <NumberField className="h-6 w-14" value={src.na ?? 0.12} min={1e-4} onCommit={(v) => v && setSrc({ na: v })} />
              <Label>n clad</Label>
              <NumberField className="h-6 w-16" value={src.n_clad ?? 1.444} min={1} onCommit={(v) => v && setSrc({ n_clad: v })} />
            </>
          )}
          {src.kind === 'tophat' && (
            <>
              <Label>{t('pop.radius')}</Label>
              <NumberField className="h-6 w-20" value={src.radius ?? 0.01} min={1e-6} units={LENGTH_TO_MM} onCommit={(v) => v && setSrc({ radius: v })} />
            </>
          )}
          {st.method === 'bpm' && (
            <>
              <Label hint={t('pop.bpmStepHint')}>{t('pop.bpmStep')}</Label>
              <NumberField className="h-6 w-16" optional value={st.bpm_step_um} min={0.05} max={50} units={UM} placeholder="λ" onCommit={(v) => set({ bpm_step_um: v })} />
            </>
          )}
          <Label hint={t('pop.offsetHint')}>{t('pop.offset')}</Label>
          <NumberField className="h-6 w-16" value={st.target_offset} units={LENGTH_TO_MM} onCommit={(v) => set({ target_offset: v ?? 0 })} />
          <Label hint={t('pop.receiveHint')}>{t('pop.receive')}</Label>
          <Select
            className="h-6 w-28 text-small"
            ariaLabel={t('pop.receive')}
            value={st.receive}
            options={[
              { value: 'none', label: '—' },
              { value: 'gaussian', label: t('pop.gaussian') },
              { value: 'fibre', label: t('pop.fibre') },
            ]}
            onChange={(v) => set({ receive: v })}
          />
          {st.receive === 'gaussian' && <NumberField className="h-6 w-20" value={st.mode_waist} min={1e-6} units={LENGTH_TO_MM} ariaLabel="mode waist" onCommit={(v) => v && set({ mode_waist: v })} />}
          {st.receive === 'fibre' && (
            <>
              <NumberField className="h-6 w-14" value={st.mode_fibre.core_radius_um} min={0.01} ariaLabel="core radius um" onCommit={(v) => v && set({ mode_fibre: { ...st.mode_fibre, core_radius_um: v } })} />
              <NumberField className="h-6 w-14" value={st.mode_fibre.na} min={1e-4} ariaLabel="NA" onCommit={(v) => v && set({ mode_fibre: { ...st.mode_fibre, na: v } })} />
            </>
          )}
          <Label hint={t('pop.detectorHint')}>{t('pop.detector')}</Label>
          <NumberField className="h-6 w-16" optional value={st.detector_radius} min={1e-6} units={LENGTH_TO_MM} placeholder="—" onCommit={(v) => set({ detector_radius: v })} />
          <Select className="h-6 w-16 text-small" ariaLabel={t('pop.grid')} value={st.grid} options={[64, 128, 256, 384].map((g) => ({ value: g, label: `${g}²` }))} onChange={(v) => set({ grid: v })} />
          {(gaussSrc || det) && (
            <Button size="sm" onClick={fromProject} title={t('pop.fromProjectHint')}>
              <Wand2 size={12} /> {t('pop.fromProject')}
            </Button>
          )}
        </>
      }
    >
      {data && tg && (
        <div className="flex h-full min-h-0 flex-col">
          <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
            <Stat label={t('pop.power')} value={fmt(tg.power * 100, 5)} unit={(tg.power_outside_window ?? 0) > 1e-4 ? `% (+${fmt((tg.power_outside_window ?? 0) * 100, 3)} % ${t('pop.windowOut')})` : '%'} />
            {tg.power_in_radius !== undefined && <Stat label={t('pop.inRadius', { r: fmt((tg.detector_radius ?? 0) * 1000, 4) })} value={fmt(tg.power_in_radius * 100, 5)} unit="%" />}
            <Stat label="D4σ x" value={fmt(tg.d4sigma_mm[0] * 1000, 5)} unit="µm" />
            <Stat label="D4σ y" value={fmt(tg.d4sigma_mm[1] * 1000, 5)} unit="µm" />
            <Stat label={t('pop.geometric')} value={fmt(data.geometric_d4sigma_mm * 1000, 5)} unit="µm" />
            {data.coupling && <Stat label={t('pop.coupling')} value={`${fmt(data.coupling.efficiency * 100, 5)} %`} unit={data.coupling.efficiency_db !== null ? `${fmt(data.coupling.efficiency_db, 4)} dB` : ''} tone={data.coupling.efficiency > 0.9 ? 'ok' : undefined} />}
            <Stat label={t('pop.peak')} value={tg.peak_irradiance.toExponential(3)} unit="1/mm²" />
          </div>
          {st.view === 'side' && data.side ? (
            <PopSide side={data.side} norm={st.side_norm} log={st.side_log} set={set} />
          ) : (
          <div className="grid min-h-0 flex-1 grid-cols-[minmax(280px,1.2fr)_minmax(240px,1fr)] gap-px bg-line">
            <div className="flex min-h-[240px] flex-col bg-panel">
              <div className="flex shrink-0 items-center gap-2 px-2 pt-1 text-small text-muted">
                <Select className="h-6 w-28 text-small" ariaLabel={t('pop.show')} value={st.show} options={[{ value: 'irradiance', label: t('pop.irradiance') }, { value: 'phase', label: t('pop.phase') }]} onChange={(v) => set({ show: v })} />
                <span>
                  z = {fmt(tg.z, 6)} mm ({t('pop.fromImage')} {fmt(tg.offset_from_image, 4)} mm)
                </span>
              </div>
              <div className="min-h-0 flex-1">
                <Plot
                  square
                  data={[
                    {
                      type: 'heatmap',
                      x: xs,
                      y: ys,
                      z: st.show === 'phase' ? tg.phase : tg.irradiance,
                      colorscale: st.show === 'phase' ? COLORMAPS.cyclic : COLORMAPS.sequential,
                      colorbar: { title: { text: st.show === 'phase' ? 'rad' : '1/mm²', side: 'right' }, thickness: 12 },
                      hovertemplate: 'x %{x:.2f} µm<br>y %{y:.2f} µm<br>%{z:.4g}<extra></extra>',
                    },
                  ]}
                  layout={{ margin: { l: 50, r: 10, t: 6, b: 36 }, shapes, xaxis: { title: { text: t('pop.xFromCentroid') } }, yaxis: { title: { text: 'y (µm)' } } }}
                />
              </div>
            </div>
            <div className="flex min-h-0 flex-col bg-panel">
              <div className="min-h-[180px] flex-1">
                <Plot
                  data={[
                    { type: 'scatter', mode: 'lines', x: xFull, y: tg.profile_x, name: 'x', line: { color: DATA.primary, width: 1.6 } },
                    { type: 'scatter', mode: 'lines', x: yFull, y: tg.profile_y, name: 'y', line: { color: DATA.secondary, width: 1.4, dash: 'dot' } },
                  ]}
                  layout={{ margin: { l: 56, r: 10, t: 8, b: 36 }, legend: { orientation: 'h', y: 1.1 }, xaxis: { title: { text: 'µm' } }, yaxis: { title: { text: t('pop.irradiance') } } }}
                />
              </div>
              <div className="shrink-0 space-y-0.5 border-t border-line px-3 py-1.5 text-small text-muted">
                <div>
                  {t('pop.entry')}: {data.entry.method} · {data.entry.grid}² · {fmt(data.entry.power * 100, 5)} %
                </div>
                <div>
                  {t('pop.exit')}: {data.exit.propagation} · {fmt(data.exit.power * 100, 5)} %
                </div>
                <div className="text-faint">
                  {data.time_s.toFixed(2)} s · λ {fmt(data.wavelength_um * 1000, 6)} nm
                </div>
              </div>
            </div>
          </div>
          )}
          <Notes notes={data.notes} />
        </div>
      )}
    </AnalysisFrame>
  )
}

/** The field along the system: |U|^2 on the meridional cut, lens surfaces and the propagation regions. */
function PopSide({ side, norm, log, set }: { side: NonNullable<PopResult['side']>; norm: boolean; log: boolean; set: (p: Partial<PopSettings>) => void }) {
  const t = useT()
  const ev = useEngineStore((s) => s.evaluation)
  const z = useMemo(() => {
    let M = side.irradiance
    if (norm) {
      const peak = side.z.map((_, j) => Math.max(1e-300, ...M.map((r) => r[j])))
      M = M.map((r) => r.map((v, j) => v / peak[j]))
    }
    if (log) M = M.map((r) => r.map((v) => Math.log10(Math.max(v, norm ? 1e-6 : 1e-12))))
    return M
  }, [side, norm, log])
  const shapes: Trace[] = []
  // lens surfaces (axial systems: z = vertex + sag) within the shown height
  const yMax = side.y[side.y.length - 1]
  for (const s of ev?.surfaces.slice(1, -1) ?? []) {
    if (!s.profile.length || s.type === 'coordinate_break') continue
    const pts = s.profile.filter(([y]) => Math.abs(y) <= yMax * 1.02).map(([y, zl]) => `${s.origin[2] + zl},${y}`)
    if (pts.length > 1) shapes.push({ type: 'path', path: 'M' + pts.join(' L'), line: { color: 'rgba(160,200,255,0.75)', width: 1.2 } })
  }
  const marks = [side.entry_z, side.exit_z]
  for (const zz of marks) shapes.push({ type: 'line', x0: zz, x1: zz, yref: 'paper', y0: 0, y1: 1, line: { color: 'rgba(255,255,255,0.35)', width: 1, dash: 'dot' } })
  shapes.push({ type: 'line', x0: side.target_z, x1: side.target_z, yref: 'paper', y0: 0, y1: 1, line: { color: DATA.target, width: 1.5 } })
  const annotations = side.regions.map((r) => ({ x: (r.z0 + r.z1) / 2, y: 1, xref: 'x', yref: 'paper', yanchor: 'bottom', showarrow: false, text: r.kind === 'geometric' ? t('pop.regionGeo') : t('pop.regionWave'), font: { size: 10, color: r.kind === 'geometric' ? DATA.secondary : DATA.primary }, hovertext: r.method }))
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-3 px-2 pt-1 text-small text-muted">
        <Checkbox checked={norm} onChange={(v) => set({ side_norm: v })} label={<span title={t('pop.sideNormHint')}>{t('pop.sideNorm')}</span>} />
        <Checkbox checked={log} onChange={(v) => set({ side_log: v })} label={<span>log</span>} />
        <span className="text-faint">{t('pop.sideHint')}</span>
        <span className="num text-faint">{side.time_s.toFixed(2)} s</span>
      </div>
      <div className="min-h-[220px] flex-1">
        <Plot
          data={[
            {
              type: 'heatmap',
              x: side.z,
              y: side.y,
              z,
              colorscale: COLORMAPS.sequential,
              colorbar: { title: { text: log ? 'log₁₀' : norm ? t('pop.relative') : '1/mm²', side: 'right' }, thickness: 12 },
              hovertemplate: 'z %{x:.4f} mm<br>y %{y:.4f} mm<br>%{z:.4g}<extra></extra>',
            },
          ]}
          layout={{ margin: { l: 56, r: 10, t: 22, b: 38 }, shapes, annotations, xaxis: { title: { text: t('pop.sideZ') } }, yaxis: { title: { text: 'y (mm)' } } }}
        />
      </div>
      <div className="shrink-0 space-y-0.5 border-t border-line px-3 py-1 text-caption text-muted">
        {side.regions.map((r, i) => (
          <div key={i}>
            <span className={r.kind === 'geometric' ? 'text-warn' : 'text-accent'}>■</span> {fmt(r.z0, 4)} … {fmt(r.z1, 4)} mm: {r.method}
          </div>
        ))}
      </div>
    </div>
  )
}

// ================================================================== FDTD
const FDTD_DEFAULT: FdtdSettings = {
  wavelength_um: 1.0,
  polarization: 's',
  size_z_um: 8,
  size_y_um: 0.2,
  n_background: 1.0,
  source: 'plane',
  waist_um: 2,
  focus_z_um: 0,
  focus_y_um: 0,
  tilt_deg: 0,
  points_per_wavelength: 30,
  reference: true,
  shapes: [{ kind: 'rectangle', name: 'Glass slab', n: 1.5, k: 0, z0: 3, z1: 3.8, y0: -50, y1: 50 }],
}

function arcLens(zFlat: number, thickness: number, R: number, half: number, n: number): FdtdShape {
  // plano-convex: flat face at zFlat, the convex face towards -z with radius R, aperture +-half
  const pts: [number, number][] = [[zFlat, -half]]
  const sag = (y: number) => R - Math.sqrt(R * R - y * y)
  for (let k = 0; k <= 40; k++) {
    const y = -half + (2 * half * k) / 40
    pts.push([zFlat - thickness + sag(y), y])
  }
  pts.push([zFlat, half])
  return { kind: 'polygon', name: 'Microlens', n, k: 0, points: pts }
}

const PRESETS: { id: string; settings: () => FdtdSettings }[] = [
  { id: 'slab', settings: () => FDTD_DEFAULT },
  {
    id: 'ar',
    settings: () => ({ ...FDTD_DEFAULT, size_z_um: 6, shapes: [{ kind: 'rectangle', name: 'Glass', n: 1.5, z0: 3, z1: 100, y0: -50, y1: 50 }, { kind: 'rectangle', name: 'MgF2 quarter wave', n: 1.38, z0: 3 - 1 / (4 * 1.38), z1: 3, y0: -50, y1: 50 }] }),
  },
  {
    id: 'lens',
    settings: () => ({ ...FDTD_DEFAULT, size_z_um: 24, size_y_um: 16, source: 'gaussian', waist_um: 3.5, focus_z_um: 1.2, tilt_deg: 0, points_per_wavelength: 16, reference: false, shapes: [arcLens(6, 2, 6, 4, 1.5)] }),
  },
  {
    id: 'tir',
    settings: () => ({ ...FDTD_DEFAULT, size_z_um: 8, size_y_um: 18, n_background: 1.5, source: 'gaussian', waist_um: 2.5, focus_z_um: 4, tilt_deg: 50, points_per_wavelength: 14, shapes: [{ kind: 'rectangle', name: 'Air', n: 1.0, z0: 4, z1: 100, y0: -100, y1: 100 }] }),
  },
  {
    id: 'waveguide',
    settings: () => ({ ...FDTD_DEFAULT, size_z_um: 20, size_y_um: 8, n_background: 1.45, source: 'gaussian', waist_um: 0.9, focus_z_um: 1.2, points_per_wavelength: 16, reference: false, shapes: [{ kind: 'rectangle', name: 'Core', n: 1.5, z0: -5, z1: 100, y0: -0.6, y1: 0.6 }] }),
  },
  {
    id: 'grating',
    settings: () => ({ ...FDTD_DEFAULT, size_z_um: 8, size_y_um: 2, shapes: [{ kind: 'rectangle', name: 'Substrate', n: 1.5, z0: 4, z1: 100, y0: -50, y1: 50 }, { kind: 'rectangle', name: 'Tooth', n: 1.5, z0: 3.4, z1: 4, y0: -0.5, y1: 0.5 }] }),
  },
  {
    id: 'spp',
    // gold at 633 nm (n + ik = 0.197 + 3.09i) below y = -0.6 µm, air above: the plasmon launched at its own profile
    settings: () => ({ ...FDTD_DEFAULT, wavelength_um: 0.633, polarization: 'p', size_z_um: 4, size_y_um: 1.9, source: 'spp', spp_y_um: -0.6, reference: false, shapes: [{ kind: 'rectangle', name: 'Gold', n: 0.197, k: 3.09, z0: -50, z1: 50, y0: -5, y1: -0.6 }] }),
  },
]

/** A rectangle's outline clipped to the computed domain (shapes may extend into the absorbing layers). */
function clipRect(s: FdtdShape, r: { z_um: number[]; y_um: number[] }) {
  const zl = r.z_um[0]
  const zh = r.z_um[r.z_um.length - 1]
  const yl = r.y_um[0]
  const yh = r.y_um[r.y_um.length - 1]
  const c = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
  return { x0: c(Math.min(s.z0 ?? 0, s.z1 ?? 0), zl, zh), x1: c(Math.max(s.z0 ?? 0, s.z1 ?? 0), zl, zh), y0: c(Math.min(s.y0 ?? 0, s.y1 ?? 0), yl, yh), y1: c(Math.max(s.y0 ?? 0, s.y1 ?? 0), yl, yh) }
}

/** 2D model of the project's fibre end (core and cladding as a slab waveguide), launched with its
 * guided mode; the reference run is the endless fibre, so R is the power reflected back into it. */
function fibrePreset(ar: boolean): FdtdSettings {
  const p = useProjectStore.getState().project
  const pop = p.analysis_settings.pop as Partial<PopSettings> | undefined
  const fm = p.analysis_settings.fibermodes as Partial<FibreSettings> | undefined // a step profile only (the slab has a step core)
  let a = 4.1
  let na = 0.12
  let n2 = 1.444
  if (pop?.source?.kind === 'fibre') {
    a = pop.source.core_radius_um ?? a
    na = pop.source.na ?? na
    n2 = pop.source.n_clad ?? n2
  } else if (fm && (fm.profile_kind ?? 'step') === 'step') {
    a = fm.core_radius_um ?? a
    if (!fm.clad_material && fm.n_clad) n2 = fm.n_clad
    if (fm.spec === 'n_core' && fm.n_core && fm.n_core > n2) na = Math.sqrt(fm.n_core * fm.n_core - n2 * n2)
    else if (fm.spec === 'dn' && fm.dn && fm.dn > 0) na = Math.sqrt((n2 + fm.dn) ** 2 - n2 * n2)
    else if (fm.na) na = fm.na
  }
  const lam = p.system.wavelengths[p.system.primary_wavelength]?.value ?? 1.55
  const n1 = Math.sqrt(n2 * n2 + na * na) // NA = sqrt(n1^2 - n2^2)
  const zf = 12
  const L = 30
  const H = Math.max(24, 6 * a)
  const fibre = (z1: number): FdtdShape[] => [
    { kind: 'rectangle', name: 'Cladding', n: n2, k: 0, z0: -50, z1, y0: -1000, y1: 1000 },
    { kind: 'rectangle', name: 'Core', n: n1, k: 0, z0: -50, z1, y0: -a, y1: a },
  ]
  const shapes = fibre(zf)
  if (ar) {
    const c = (p.system.custom_coatings ?? []).find((x) => x.layers.length === 1 && x.layers[0].index > 1)
    const nAr = c ? c.layers[0].index : 1.38
    const tAr = c ? c.layers[0].thickness_nm / 1000 : lam / (4 * 1.38)
    shapes.push({ kind: 'rectangle', name: c ? `AR (${c.name})` : 'AR: MgF2 quarter wave', n: nAr, k: 0, z0: zf, z1: zf + tAr, y0: -1000, y1: 1000 })
  }
  return {
    ...FDTD_DEFAULT,
    wavelength_um: lam,
    size_z_um: L,
    size_y_um: H,
    n_background: 1.0,
    source: 'mode',
    mode_half_width_um: a,
    mode_n_core: n1,
    mode_n_clad: n2,
    mode_center_y_um: 0,
    source_z_um: 2,
    reflection_z_um: 5,
    transmission_z_um: L - 3,
    points_per_wavelength: 12,
    reference: true,
    shapes,
    reference_shapes: fibre(1000),
    pop_object_z_um: zf,
  }
}

function ShapeRow({ s, onChange, onRemove }: { s: FdtdShape; onChange: (p: Partial<FdtdShape>) => void; onRemove: () => void }) {
  const t = useT()
  const num = (k: keyof FdtdShape, w = 'w-14') => <NumberField cell className={w} value={(s[k] as number | undefined) ?? 0} ariaLabel={String(k)} onCommit={(v) => onChange({ [k]: v ?? 0 } as Partial<FdtdShape>)} />
  return (
    <tr>
      <td className="px-2 text-muted">{s.kind === 'rectangle' ? '▭' : s.kind === 'circle' ? '◯' : '⬠'}</td>
      <td className="px-1">
        <input className="cell-input w-28" value={s.name ?? ''} aria-label={t('c.name')} onChange={(e) => onChange({ name: e.target.value })} onKeyDown={(e) => e.stopPropagation()} />
      </td>
      <td>{num('n', 'w-16')}</td>
      <td>{num('k', 'w-14')}</td>
      {s.kind === 'rectangle' ? (
        <>
          <td>{num('z0')}</td>
          <td>{num('z1')}</td>
          <td>{num('y0')}</td>
          <td>{num('y1')}</td>
        </>
      ) : s.kind === 'circle' ? (
        <>
          <td>{num('zc')}</td>
          <td>{num('yc')}</td>
          <td>{num('r')}</td>
          <td />
        </>
      ) : (
        <td colSpan={4} className="px-2 text-faint">
          {t('fd.polygon', { n: s.points?.length ?? 0 })}
        </td>
      )}
      <td className="px-1">
        <IconButton size="sm" tone="danger" title={t('c.remove')} onClick={onRemove}>
          <X size={12} />
        </IconButton>
      </td>
    </tr>
  )
}

export function FdtdView() {
  const t = useT()
  const custom = useProjectStore((s) => s.project.custom_materials)
  const [st, set] = useAnalysisSettings<FdtdSettings & { show?: 'intensity' | 'field' | 'index'; log?: boolean }>('fdtd', FDTD_DEFAULT)
  const { job, result, resultKey, resultSpec, error, start, cancel } = useFdtdStore()
  const backend = useEngineStore((s) => s.backend)
  const [, setPop] = useAnalysisSettings<PopSettings>('pop', POP_DEFAULTS)
  const [handoffError, setHandoffError] = useState<string | null>(null)
  const { show = 'intensity', log = false, ...spec } = st
  const axi = spec.geometry === 'axisymmetric'
  const body = useRef<HTMLDivElement>(null)
  const [structH, setStructH] = useState(190) // structure editor height (drag the divider)
  const running = job?.state === 'running' || job?.state === 'queued'
  const stale = result && resultKey !== fdtdKey(spec)
  const setShape = (i: number, p: Partial<FdtdShape>) => set({ shapes: spec.shapes.map((s, k) => (k === i ? { ...s, ...p } : s)) }, 'FDTD shape')
  const lamMin = spec.wavelength_um / Math.max(spec.n_background, ...spec.shapes.map((s) => Math.hypot(s.n ?? 1, s.k ?? 0)))
  const dx = lamMin / spec.points_per_wavelength
  const cells = Math.round(spec.size_z_um / dx + 40) * (axi ? Math.round(spec.size_y_um / 2 / dx + 20) : Math.round(spec.size_y_um / dx + (spec.source === 'plane' ? 0 : 40)))
  const exported = result?.geometry === 'axisymmetric' ? result.exported_field : undefined
  // the co-polarised field at the transmission monitor as the POP source (one undoable edit)
  const toPop = () => {
    if (!exported || stale) return // the field belongs to other settings: run again first
    const off = (exported.z_um - (spec.pop_object_z_um ?? 0)) / 1000
    if (off < 0) return setHandoffError(t('fd.toPopBehind'))
    setHandoffError(null)
    const { z_um: _z, depolarised_fraction: _d, ...f } = exported
    setPop({ field_source: { ...f, plane_offset_mm: off, origin: 'FDTD' }, source: { kind: 'field' } }, 'POP source: field from the FDTD')
    useUiStore.getState().showView('pop')
  }
  const zmap = result ? (show === 'index' ? result.index : show === 'field' ? result.field : log ? result.intensity.map((r) => r.map((v) => Math.log10(Math.max(v, 1e-12)))) : result.intensity) : null
  // outlines of the structure of the shown run (exact geometry, clipped by the plot range)
  const outlineShapes: Trace[] = (result ? (resultSpec?.shapes ?? []) : []).map((s) =>
    s.kind === 'circle'
      ? { type: 'circle', x0: (s.zc ?? 0) - (s.r ?? 0), x1: (s.zc ?? 0) + (s.r ?? 0), y0: (s.yc ?? 0) - (s.r ?? 0), y1: (s.yc ?? 0) + (s.r ?? 0), line: { color: 'rgba(255,255,255,0.6)', width: 1 } }
      : s.kind === 'polygon'
        ? { type: 'path', path: (s.points ?? []).map((q, i) => `${i ? 'L' : 'M'}${q[0]},${q[1]}`).join(' ') + ' Z', line: { color: 'rgba(255,255,255,0.6)', width: 1 } }
        : { type: 'rect', ...clipRect(s, result ?? { z_um: [0], y_um: [0] }), line: { color: 'rgba(255,255,255,0.6)', width: 1 } },
  )
  return (
    <AnalysisFrame
      kind="fdtd"
      title={t('view.fdtd')}
      loading={false}
      error={null}
      hasData={!!result}
      ms={null}
      onRefresh={() => void start(spec, custom)}
      settings={spec}
      result={null}
      onDemand
      alwaysShow
      controls={
        <>
        <Select
          className="h-6 w-36 text-small"
          ariaLabel={t('fd.example')}
          value=""
          options={[{ value: '', label: t('fd.example') }, { value: 'fibre', label: t('fd.preset.fibre') }, { value: 'fibre_ar', label: t('fd.preset.fibre_ar') }, ...PRESETS.map((p) => ({ value: p.id, label: t(`fd.preset.${p.id}`) }))]}
          onChange={(v) => {
            if (v === 'fibre' || v === 'fibre_ar') return set({ ...fibrePreset(v === 'fibre_ar') }, `FDTD example: ${v}`)
            const p = PRESETS.find((x) => x.id === v)
            if (p) set({ ...p.settings(), geometry: undefined, pop_object_z_um: undefined, reference_shapes: undefined, source_z_um: undefined, reflection_z_um: undefined, transmission_z_um: undefined }, `FDTD example: ${v}`)
          }}
        />
        <Label hint={t('fd.lambdaHint')}>λ (µm)</Label>
        <NumberField className="h-6 w-16" value={spec.wavelength_um} min={0.05} units={UM} onCommit={(v) => v && set({ wavelength_um: v })} />
        </>
      }
      more={
        <>
        <Label hint={t('fd.geometryHint')}>{t('fd.geometry')}</Label>
        <Select
          className="h-6 w-44 text-small"
          ariaLabel={t('fd.geometry')}
          value={spec.geometry ?? 'planar'}
          options={[
            { value: 'planar', label: t('fd.planar') },
            { value: 'axisymmetric', label: t('fd.axisym') },
          ]}
          onChange={(v) => set(v === 'axisymmetric' ? { geometry: v, tilt_deg: 0, focus_y_um: 0, mode_center_y_um: 0, source: spec.source === 'plane' ? 'gaussian' : spec.source } : { geometry: v })}
        />
        {axi ? (
          <span className="text-small text-muted">{t('fd.xpol')}</span>
        ) : (
          <Select className="h-6 w-24 text-small" ariaLabel={t('fd.pol')} value={spec.polarization} options={[{ value: 's', label: 's (TE)' }, { value: 'p', label: 'p (TM)' }]} onChange={(v) => set({ polarization: v })} />
        )}
        <Label hint={t('fd.domainHint')}>{axi ? 'z × Ø (µm)' : 'z × y (µm)'}</Label>
        <NumberField className="h-6 w-14" value={spec.size_z_um} min={0.1} onCommit={(v) => v && set({ size_z_um: v })} />
        <NumberField className="h-6 w-14" value={spec.size_y_um} min={0.01} onCommit={(v) => v && set({ size_y_um: v })} />
        <Label hint={t('fd.bgHint')}>n₀</Label>
        <NumberField className="h-6 w-14" value={spec.n_background} min={1} onCommit={(v) => v && set({ n_background: v })} />
        <Select
          className="h-6 w-32 text-small"
          ariaLabel={t('fd.source')}
          value={spec.source}
          options={[
            ...(axi ? [] : [{ value: 'plane' as const, label: t('fd.plane') }]),
            { value: 'gaussian', label: t('fd.gaussian') },
            { value: 'mode', label: axi ? t('fd.modeFibre') : t('fd.mode') },
            ...(axi ? [] : [{ value: 'spp' as const, label: t('fd.spp') }]),
          ]}
          onChange={(v) => set(v === 'spp' ? { source: v, polarization: 'p', reference: false } : { source: v })}
        />
        {spec.source === 'spp' && (
          <>
            <Label hint={t('fd.sppHint')}>{t('fd.sppY')}</Label>
            <NumberField className="h-6 w-14" value={spec.spp_y_um ?? 0} ariaLabel={t('fd.sppY')} onCommit={(v) => set({ spp_y_um: v ?? 0 })} />
          </>
        )}
        {spec.source === 'mode' && (
          <>
            <Label hint={axi ? t('fd.coreHint') : t('fd.modeHint')}>{axi ? 'a' : '±a'}</Label>
            <NumberField className="h-6 w-14" value={spec.mode_half_width_um ?? 1} min={0.01} onCommit={(v) => v && set({ mode_half_width_um: v })} />
            <Label>n core</Label>
            <NumberField className="h-6 w-16" value={spec.mode_n_core ?? 1.46} min={1} onCommit={(v) => v && set({ mode_n_core: v })} />
            <Label>n clad</Label>
            <NumberField className="h-6 w-16" value={spec.mode_n_clad ?? 1.45} min={1} onCommit={(v) => v && set({ mode_n_clad: v })} />
          </>
        )}
        {spec.source === 'gaussian' && (
          <>
            <Label hint={t('fd.waistHint')}>w₀</Label>
            <NumberField className="h-6 w-14" value={spec.waist_um} min={0.05} onCommit={(v) => v && set({ waist_um: v })} />
            <Label hint={t('fd.focusHint')}>{t('fd.focus')}</Label>
            <NumberField className="h-6 w-14" value={spec.focus_z_um} onCommit={(v) => set({ focus_z_um: v ?? 0 })} />
            {!axi && (
              <>
                <Label hint={t('fd.tiltHint')}>{t('fd.tilt')}</Label>
                <NumberField className="h-6 w-14" value={spec.tilt_deg} min={-80} max={80} onCommit={(v) => set({ tilt_deg: v ?? 0 })} />
              </>
            )}
          </>
        )}
        <Label hint={t('fd.ppwHint')}>{t('fd.ppw')}</Label>
        <NumberField className="h-6 w-12" value={spec.points_per_wavelength} min={6} max={80} onCommit={(v) => v && set({ points_per_wavelength: v })} />
        <Checkbox checked={spec.reference} onChange={(v) => set({ reference: v })} label={<span className="text-small text-muted" title={t('fd.referenceHint')}>R, T</span>} />
        <span className="num text-caption text-faint">≈{(cells / 1e3).toFixed(0)}k {t('fd.cells')}</span>
        </>
      }
      actions={
        running ? (
          <>
            <div className="h-1.5 w-24 shrink-0 overflow-hidden rounded bg-hover" role="progressbar" aria-valuenow={Math.round((job?.progress ?? 0) * 100)} aria-valuemin={0} aria-valuemax={100}>
              <div className="h-full bg-accent transition-[width]" style={{ width: `${(job?.progress ?? 0) * 100}%` }} />
            </div>
            <span className="num text-caption whitespace-nowrap text-muted">{job?.eta_s !== null && job?.eta_s !== undefined ? `${job.eta_s.toFixed(0)} s` : ''}</span>
            <Button size="sm" onClick={() => void cancel()}>
              <Square size={12} /> {t('c.cancel')}
            </Button>
          </>
        ) : (
          <Button size="sm" variant="primary" disabled={backend !== 'online'} onClick={() => void start(spec, custom)} title={t('fd.runHint')}>
            <Play size={12} /> {t('fd.run')}
          </Button>
        )
      }
    >
      <div ref={body} className="flex h-full min-h-0 flex-col overflow-hidden">
        <div className="relative min-h-0 flex-1 overflow-hidden">
          {result && zmap ? (
            <div className="flex h-full min-h-0 flex-col">
              <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
                {result.R !== undefined && <Stat label="R" value={fmt(result.R * 100, 5)} unit="%" />}
                {result.T !== undefined && <Stat label="T" value={fmt(result.T * 100, 5)} unit="%" />}
                {result.A !== undefined && <Stat label={t('fd.absorbed')} value={fmt(result.A * 100, 4)} unit="%" tone={result.A < -0.005 ? 'warn' : undefined} />}
                {result.propagation && (
                  <div title={t('fd.neffHint')}>
                    <Stat
                      label="n_eff"
                      value={`${fmt(result.propagation.n_eff, 6)} + ${fmt(result.propagation.kappa, 4)}i`}
                      unit={result.propagation.analytic_n_eff !== undefined ? `${t('fd.analytic')} ${fmt(result.propagation.analytic_n_eff, 6)} + ${fmt(result.propagation.analytic_kappa ?? 0, 4)}i` : undefined}
                    />
                  </div>
                )}
                {result.propagation && result.propagation.attenuation_per_um > 0 && (
                  <div title={t('fd.propLengthHint')}>
                    <Stat label={t('fd.propLength')} value={fmt(1 / result.propagation.attenuation_per_um, 4)} unit="µm" />
                  </div>
                )}
                <Stat label={t('fd.grid')} value={`${result.cells[0]} × ${result.cells[1]}`} unit={`dx ${fmt(result.dx_um * 1000, 4)} nm`} />
                <Stat label={t('fd.steps')} value={String(result.steps)} />
                <Stat label={t('fd.settled')} value={result.convergence < 1e-3 ? t('c.yes') : `${(result.convergence * 100).toFixed(2)} %`} tone={result.convergence < 0.02 ? 'ok' : 'warn'} />
                <Stat label={t('fd.time')} value={result.time_s.toFixed(1)} unit="s" />
                {exported && <Stat label={t('fd.depol')} value={fmt(exported.depolarised_fraction * 100, 3)} unit="%" tone={exported.depolarised_fraction > 0.02 ? 'warn' : undefined} />}
                {exported && (
                  <div className="flex items-center gap-1.5 px-3">
                    <Label hint={t('fd.popZHint')}>{t('fd.popZ')}</Label>
                    <NumberField className="h-6 w-14" value={spec.pop_object_z_um ?? 0} ariaLabel={t('fd.popZ')} onCommit={(v) => set({ pop_object_z_um: v ?? 0 })} />
                    <Button size="sm" onClick={toPop} disabled={!!stale} title={t('fd.toPopHint')}>
                      {t('fd.toPop')} →
                    </Button>
                    {handoffError && <span className="text-caption text-danger">{handoffError}</span>}
                  </div>
                )}
                <div className="flex items-center gap-2 px-3">
                  <Select className="h-6 w-28 text-small" ariaLabel={t('fd.show')} value={show} options={[{ value: 'intensity', label: '|E|²' }, { value: 'field', label: t('fd.fieldRe') }, { value: 'index', label: t('fd.index') }]} onChange={(v) => set({ show: v } as never)} />
                  {show === 'intensity' && <Checkbox checked={log} onChange={(v) => set({ log: v } as never)} label={<span className="text-small text-muted">log</span>} />}
                  {stale && <Badge tone="warn">{t('fd.stale')}</Badge>}
                </div>
              </div>
              <div className="min-h-0 flex-1">
                <Plot
                  square
                  data={[
                    {
                      type: 'heatmap',
                      x: result.z_um,
                      y: result.y_um,
                      z: zmap,
                      colorscale: show === 'field' ? COLORMAPS.diverging : show === 'index' ? COLORMAPS.greys : COLORMAPS.sequential,
                      zmid: show === 'field' ? 0 : undefined,
                      colorbar: { thickness: 12 },
                      hovertemplate: 'z %{x:.3f} µm<br>y %{y:.3f} µm<br>%{z:.4g}<extra></extra>',
                    },
                  ]}
                  layout={{
                    margin: { l: 50, r: 10, t: 6, b: 36 },
                    xaxis: { title: { text: 'z (µm)' }, range: [result.z_um[0], result.z_um[result.z_um.length - 1]] },
                    yaxis: { title: { text: result.geometry === 'axisymmetric' ? 'r (µm)' : 'y (µm)' }, range: [result.y_um[0], result.y_um[result.y_um.length - 1]] },
                    shapes: [
                      ...(show !== 'index' ? outlineShapes : []),
                      ...[result.monitors.source_z, ...(result.R !== undefined ? [result.monitors.reflection_z, result.monitors.transmission_z] : [])].map((z, k) => ({ type: 'line', x0: z, x1: z, yref: 'paper', y0: 0, y1: 1, line: { color: k === 0 ? DATA.source : DATA.target, width: 1, dash: 'dot' } })),
                    ],
                  }}
                />
              </div>
              <Notes notes={result.notes} />
            </div>
          ) : (
            <div className="flex h-full items-center justify-center p-6 text-center text-body text-muted">{error ? <span className="text-danger">{error}</span> : running ? t('fd.running') : t('fd.empty')}</div>
          )}
          {error && result && <div className="absolute right-2 bottom-2 rounded bg-danger/15 px-2 py-1 text-small text-danger">{error}</div>}
        </div>
        <Handle dir="v" onDrag={(dy) => setStructH((h) => Math.max(72, Math.min((body.current?.clientHeight ?? 600) - 120, h - dy)))} />
        <div className="flex min-h-0 shrink-0 flex-col" style={{ height: structH, maxHeight: '50%' }}>
          <div className="flex shrink-0 items-center gap-2 border-b border-line bg-panel px-2 py-1">
            <span className="text-small font-semibold tracking-wide text-muted uppercase">{t('fd.structure')}</span>
            <Button size="sm" onClick={() => set({ shapes: [...spec.shapes, { kind: 'rectangle', name: `Block ${spec.shapes.length + 1}`, n: 1.5, k: 0, z0: spec.size_z_um * 0.4, z1: spec.size_z_um * 0.6, y0: -spec.size_y_um / 4, y1: spec.size_y_um / 4 }] }, 'Add FDTD rectangle')}>
              + ▭
            </Button>
            <Button size="sm" onClick={() => set({ shapes: [...spec.shapes, { kind: 'circle', name: `Disc ${spec.shapes.length + 1}`, n: 1.5, k: 0, zc: spec.size_z_um / 2, yc: 0, r: Math.min(spec.size_z_um, spec.size_y_um) / 6 }] }, 'Add FDTD circle')}>
              + ◯
            </Button>
            <span className="truncate text-caption text-faint">{t('fd.structureHint')}</span>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            <table className="eng-table">
            <thead>
              <tr>
                <th className="w-6" />
                <th>{t('fd.name')}</th>
                <th>n</th>
                <th>k</th>
                <th>z₀ / z_c (µm)</th>
                <th>z₁ / y_c (µm)</th>
                <th>y₀ / r (µm)</th>
                <th>y₁ (µm)</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {spec.shapes.map((s, i) => (
                <ShapeRow key={i} s={s} onChange={(p) => setShape(i, p)} onRemove={() => set({ shapes: spec.shapes.filter((_, k) => k !== i) }, 'Remove FDTD shape')} />
              ))}
            </tbody>
            </table>
          </div>
        </div>
      </div>
    </AnalysisFrame>
  )
}
