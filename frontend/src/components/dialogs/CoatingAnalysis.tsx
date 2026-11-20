import { useEffect, useMemo, useRef, useState } from 'react'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { DATA, SERIES } from '../../lib/palette'
import type { CoatingAdmittance, CoatingAnalysis, CoatingAnalysisParams, CoatingColour, CoatingIlluminant } from '../../lib/types'
import { Stat } from '../common/controls'
import { Plot, type Trace } from '../common/Plot'
import { Checkbox, NumberField, Select, Spinner, Tabs, TextField } from '../common/ui'
import { cx } from '../common/uiUtils'
import { parseAngles } from './coatingAngles'

export type CoatingTab = 'spectrum' | 'angle' | 'phase' | 'colour' | 'field' | 'admittance' | 'profile'
const ALL_TABS: CoatingTab[] = ['spectrum', 'angle', 'phase', 'colour', 'field', 'admittance', 'profile']
const NM: Record<string, number> = { nm: 1, um: 1000, µm: 1000 }

export interface CoatingAnalysisDefaults {
  range: [number, number]
  reference?: number | null
  band?: [number, number] | null
  angle?: number
}

/** Percent; near 100 % enough digits to resolve 1 − v (a mirror's 99.9988 % rather than 100 %). */
const pct = (v: number | null | undefined, d = 4) => {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  const near = v > 0.99 && v < 1 ? Math.min(10, Math.floor(-Math.log10(1 - v)) + 2) : 0
  return `${fmt(v * 100, Math.max(d, near))} %`
}

function TitledStat({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div title={title}>
      <Stat label={label} value={value} />
    </div>
  )
}

function Swatch({ c, label }: { c: CoatingColour; label: string }) {
  const t = useT()
  const rgb = `rgb(${c.srgb.map((v) => Math.round(Math.max(0, Math.min(1, v)) * 255)).join(',')})`
  return (
    <div className="flex items-start gap-3 rounded border border-line p-3">
      <div className="h-16 w-16 shrink-0 rounded border border-line" style={{ background: rgb }} aria-label={`${label} colour`} />
      <div className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-small">
        <span className="col-span-2 font-semibold">{label}</span>
        <span className="text-muted">{t('ca.luminous')}</span>
        <span className="num">{pct(c.Y, 4)}</span>
        <span className="text-muted">x, y</span>
        <span className="num">{c.x === null ? '—' : `${fmt(c.x, 4)}, ${fmt(c.y ?? 0, 4)}`}</span>
        <span className="text-muted">L* a* b*</span>
        <span className="num">{`${fmt(c.L, 4)}  ${fmt(c.a, 3)}  ${fmt(c.b, 3)}`}</span>
      </div>
    </div>
  )
}

/** Analyses of one coating setting (the coating editor and the coating designer share it). */
export function CoatingAnalysisPanel({
  fetcher,
  depKey,
  defaults,
  tabs = ALL_TABS,
  opaque = false,
  toolbar,
}: {
  fetcher: (p: CoatingAnalysisParams, signal: AbortSignal) => Promise<CoatingAnalysis>
  depKey: string
  defaults: CoatingAnalysisDefaults
  tabs?: CoatingTab[]
  opaque?: boolean
  toolbar?: React.ReactNode
}) {
  const t = useT()
  const defKey = JSON.stringify(defaults)
  const [range, setRange] = useState<[number, number]>(defaults.range)
  const [angle, setAngle] = useState(defaults.angle ?? 0)
  const [angles, setAngles] = useState<number[]>([])
  const [reference, setReference] = useState<number | null>(defaults.reference ?? null)
  const [band, setBand] = useState<[number, number] | null>(defaults.band ?? null)
  const [pol, setPol] = useState<'s' | 'p'>('s')
  const [illuminant, setIlluminant] = useState<CoatingIlluminant>('D65')
  const [observer, setObserver] = useState<'2' | '10'>('2')
  const [fieldMap, setFieldMap] = useState(false)
  const [tab, setTab] = useState<CoatingTab>(tabs[0])
  const [showA, setShowA] = useState(false)
  const [sp, setSp] = useState(false)
  const [ymode, setYmode] = useState<'pct' | 'log' | 'od'>('pct')
  const [phaseQ, setPhaseQ] = useState<'phase' | 'gd' | 'gdd' | 'ellipso'>('gdd')
  const [side, setSide] = useState<'r' | 't'>('r')
  const [data, setData] = useState<CoatingAnalysis | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // a new coating (or design target) brings its own range, band and angle
  const first = useRef(true)
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    setRange(defaults.range)
    setReference(defaults.reference ?? null)
    setBand(defaults.band ?? null)
    setAngle(defaults.angle ?? 0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defKey])
  const params: CoatingAnalysisParams = useMemo(
    () => ({ lambda_min_nm: range[0], lambda_max_nm: range[1], samples: 401, angle_deg: angle, angles_deg: angles, reference_nm: reference, band_nm: band, field_pol: pol, illuminant, observer }),
    [range, angle, angles, reference, band, pol, illuminant, observer],
  )
  const pkey = JSON.stringify(params)
  useEffect(() => {
    const ctrl = new AbortController()
    setBusy(true)
    const h = setTimeout(() => {
      fetcher(params, ctrl.signal)
        .then((d) => {
          setData(d)
          setErr(null)
        })
        .catch((e) => {
          if (!ctrl.signal.aborted) {
            setErr((e as Error).message)
            setData(null)
          }
        })
        .finally(() => !ctrl.signal.aborted && setBusy(false))
    }, 200)
    return () => {
      clearTimeout(h)
      ctrl.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [depKey, pkey])

  const x = data?.lambda_nm ?? []
  const Y = (a: (number | null)[]) => a.map((v) => (v === null ? null : ymode === 'od' ? -Math.log10(Math.max(v, 1e-12)) : ymode === 'log' ? Math.max(v * 100, 1e-8) : v * 100))
  const bandShape = band ? [{ type: 'rect', xref: 'x', yref: 'paper', x0: band[0], x1: band[1], y0: 0, y1: 1, fillcolor: DATA.fill, opacity: 0.35, line: { width: 0 }, layer: 'below' }] : []
  const refLine = data ? [{ type: 'line', xref: 'x', yref: 'paper', x0: data.reference_nm, x1: data.reference_nm, y0: 0, y1: 1, line: { color: DATA.marker, width: 1, dash: 'dot' } }] : []

  const spectrumTraces: Trace[] = []
  if (data) {
    const s = data.spectrum
    if (ymode === 'od') spectrumTraces.push({ type: 'scatter', mode: 'lines', x, y: Y(s.T), name: 'OD (T)', line: { color: DATA.primary, width: 1.8 } })
    else {
      if (!opaque) spectrumTraces.push({ type: 'scatter', mode: 'lines', x, y: Y(s.T), name: 'T', line: { color: DATA.primary, width: 1.8 } })
      spectrumTraces.push({ type: 'scatter', mode: 'lines', x, y: Y(s.R), name: 'R', line: { color: DATA.secondary, width: 1.8 } })
      if (showA) spectrumTraces.push({ type: 'scatter', mode: 'lines', x, y: Y(s.A), name: 'A', line: { color: DATA.quaternary, width: 1.4 } })
      if (sp) {
        spectrumTraces.push({ type: 'scatter', mode: 'lines', x, y: Y(s.Rs), name: 'Rs', line: { color: DATA.secondary, width: 1, dash: 'dot' } })
        spectrumTraces.push({ type: 'scatter', mode: 'lines', x, y: Y(s.Rp), name: 'Rp', line: { color: DATA.secondary, width: 1, dash: 'dash' } })
        if (!opaque) {
          spectrumTraces.push({ type: 'scatter', mode: 'lines', x, y: Y(s.Ts), name: 'Ts', line: { color: DATA.primary, width: 1, dash: 'dot' } })
          spectrumTraces.push({ type: 'scatter', mode: 'lines', x, y: Y(s.Tp), name: 'Tp', line: { color: DATA.primary, width: 1, dash: 'dash' } })
        }
      }
    }
    data.angles.forEach((a, i) => {
      const q = opaque || ymode === 'od' ? (ymode === 'od' ? a.T : a.R) : a.R
      spectrumTraces.push({ type: 'scatter', mode: 'lines', x, y: Y(q), name: `${opaque ? 'R' : ymode === 'od' ? 'OD' : 'R'} ${fmt(a.angle_deg, 3)}°`, line: { color: SERIES[(i + 2) % 8], width: 1.2, dash: 'dashdot' } })
    })
  }

  const ph = data?.phase
  const phaseTraces: Trace[] = []
  if (ph) {
    if (phaseQ === 'ellipso') {
      phaseTraces.push({ type: 'scatter', mode: 'lines', x, y: ph.psi ?? [], name: 'ψ', line: { color: SERIES[0], width: 1.6 } })
      phaseTraces.push({ type: 'scatter', mode: 'lines', x, y: ph.delta ?? [], name: 'Δ', line: { color: SERIES[1], width: 1.6 }, yaxis: 'y2' })
    } else {
      const pre = phaseQ === 'phase' ? 'phase_' : phaseQ === 'gd' ? 'gd_' : 'gdd_'
      for (const p of ['s', 'p'] as const) {
        const k = `${pre}${side}${p}` as keyof typeof ph
        const v = ph[k]
        if (v) phaseTraces.push({ type: 'scatter', mode: 'lines', x, y: v, name: `${side}${p}`, line: { color: p === 's' ? SERIES[0] : SERIES[1], width: 1.6, dash: p === 'p' ? 'dash' : 'solid' } })
      }
    }
  }
  const phaseAxis = phaseQ === 'phase' ? t('ca.phaseDeg') : phaseQ === 'gd' ? 'GD (fs)' : phaseQ === 'gdd' ? 'GDD (fs²)' : 'ψ (°)'

  // field: layer bands shaded by index, |E|² on top
  const f = data?.field
  const pr = data?.profile
  const fieldShapes = f && pr ? pr.layers.map((L, i) => ({ type: 'rect', xref: 'x', yref: 'paper', x0: L.z0, x1: L.z1, y0: 0, y1: 1, fillcolor: i % 2 ? DATA.fill : DATA.reference, opacity: Math.min(0.5, 0.12 + 0.12 * (L.n - 1)), line: { width: 0 }, layer: 'below' })) : []
  const zProf: number[] = []
  const nProf: number[] = []
  if (pr) {
    const pad = Math.max(pr.total_nm * 0.08, (data?.reference_nm ?? 500) * 0.1)
    zProf.push(-pad, 0)
    nProf.push(pr.incident_n, pr.incident_n)
    for (const L of pr.layers) {
      zProf.push(L.z0, L.z1)
      nProf.push(L.n, L.n)
    }
    zProf.push(pr.total_nm, pr.total_nm + pad)
    nProf.push(pr.substrate_n, pr.substrate_n)
  }
  const absorbing = !!f && f.layer_absorptance.some((a) => a > 1e-7)

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-line px-2 py-1.5 text-small">
        <span className="text-muted">λ</span>
        <NumberField className="h-6 w-16" value={range[0]} min={60} max={50000} units={NM} onCommit={(v) => v !== null && setRange([v, Math.max(v + 1, range[1])])} ariaLabel={t('ca.lambdaMin')} />
        <span className="text-muted">–</span>
        <NumberField className="h-6 w-16" value={range[1]} min={61} max={50000} units={NM} onCommit={(v) => v !== null && setRange([Math.min(range[0], v - 1), v])} ariaLabel={t('ca.lambdaMax')} />
        <span className="text-muted">nm</span>
        <span className="ml-2 text-muted" title={t('ca.angleHint')}>
          θ
        </span>
        <NumberField className="h-6 w-12" value={angle} min={0} max={89.9} onCommit={(v) => setAngle(v ?? 0)} ariaLabel={t('ca.angle')} />
        <span className="text-muted">°</span>
        <span className="ml-2 text-muted" title={t('ca.anglesHint')}>
          {t('ca.alsoAt')}
        </span>
        <TextField
          className="h-6 w-20"
          value={angles.join(', ')}
          placeholder="30, 45"
          ariaLabel={t('ca.anglesHint')}
          onCommit={(v) => {
            const a = parseAngles(v)
            if (a) setAngles(a)
          }}
        />
        <span className="text-muted">°</span>
        <span className="ml-2 text-muted" title={t('ca.referenceHint')}>
          λ<sub>ref</sub>
        </span>
        <NumberField className="h-6 w-16" value={reference ?? data?.reference_nm ?? null} min={60} max={50000} units={NM} onCommit={(v) => setReference(v)} ariaLabel={t('ca.referenceHint')} />
        <span className="ml-2 text-muted" title={t('ca.bandHint')}>
          {t('ca.band')}
        </span>
        <NumberField className="h-6 w-14" optional placeholder="—" value={band?.[0] ?? null} min={60} max={50000} units={NM} onCommit={(v) => setBand(v === null ? null : [v, Math.max(v + 1, band?.[1] ?? v + 100)])} ariaLabel={`${t('ca.band')} min`} />
        <span className="text-muted">–</span>
        <NumberField className="h-6 w-14" optional placeholder="—" value={band?.[1] ?? null} min={61} max={50000} units={NM} onCommit={(v) => setBand(v === null ? null : [Math.min(band?.[0] ?? v - 100, v - 1), v])} ariaLabel={`${t('ca.band')} max`} />
        {toolbar}
        <span className="flex-1" />
        {busy && <Spinner />}
      </div>
      <Tabs value={tab} onChange={setTab} tabs={tabs.map((k) => ({ id: k, label: t(`ca.tab.${k}`) }))} />
      {err && <div className="px-3 py-1 text-small text-danger">{err}</div>}
      {data && (
        <div className="min-h-0 flex-1 overflow-auto">
          {tab === 'spectrum' && (
            <div className="flex h-full min-h-[300px] flex-col">
              <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
                <Stat label={`R @ ${fmt(data.reference_nm, 5)} nm`} value={pct(data.at_reference.R)} />
                {!opaque && <Stat label={`T @ ${fmt(data.reference_nm, 5)} nm`} value={pct(data.at_reference.T)} />}
                {data.at_reference.A > 1e-6 && <Stat label="A" value={pct(data.at_reference.A)} />}
                {data.band && (
                  <>
                    <TitledStat label={`R ${t('ca.inBand')}`} value={`${pct(data.band.R.mean, 4)} (${pct(data.band.R.min, 4)}…${pct(data.band.R.max, 4)})`} title={t('ca.bandStatHint')} />
                    {!opaque && <TitledStat label={`T ${t('ca.inBand')}`} value={`${pct(data.band.T.mean, 4)} (${pct(data.band.T.min, 4)}…${pct(data.band.T.max, 4)})`} title={t('ca.bandStatHint')} />}
                  </>
                )}
                <TitledStat label="Rv" value={pct(data.colour.Rv, 3)} title={t('ca.luminousHint')} />
                {!opaque && <TitledStat label="Tv" value={pct(data.colour.Tv, 3)} title={t('ca.luminousHint')} />}
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-3 px-3 py-1 text-small">
                <Checkbox checked={showA} onChange={setShowA} label={<span className="whitespace-nowrap text-muted">A</span>} />
                <Checkbox checked={sp} onChange={setSp} label={<span className="whitespace-nowrap text-muted">{t('ca.sp')}</span>} />
                <Select
                  className="h-6 w-32 text-small"
                  value={ymode}
                  ariaLabel={t('ca.scale')}
                  options={[
                    { value: 'pct', label: '%' },
                    { value: 'log', label: t('ca.log') },
                    { value: 'od', label: t('ca.od') },
                  ]}
                  onChange={setYmode}
                />
              </div>
              <div className="min-h-0 flex-1">
                <Plot
                  data={spectrumTraces}
                  layout={{
                    margin: { l: 52, r: 12, t: 8, b: 40 },
                    hovermode: 'x unified',
                    shapes: [...bandShape, ...refLine],
                    xaxis: { title: { text: 'λ (nm)' } },
                    yaxis: ymode === 'pct' ? { title: { text: '%' }, range: [-2, 102] } : ymode === 'log' ? { title: { text: '% (log)' }, type: 'log' } : { title: { text: 'OD = −log₁₀ T' }, rangemode: 'tozero' },
                    legend: { orientation: 'h', y: 1.06, font: { size: 10 } },
                  }}
                />
              </div>
            </div>
          )}
          {tab === 'angle' && (
            <div className="flex h-full min-h-[300px] flex-col">
              <div className="px-3 py-1 text-small text-muted">{t('ca.angleTitle', { nm: fmt(data.angle_curve.wavelength_nm, 5) })}</div>
              <div className="min-h-0 flex-1">
                <Plot
                  data={[
                    { type: 'scatter', mode: 'lines', x: data.angle_curve.angles_deg, y: data.angle_curve.R.map((v) => v * 100), name: 'R', line: { color: DATA.secondary, width: 1.8 } },
                    { type: 'scatter', mode: 'lines', x: data.angle_curve.angles_deg, y: data.angle_curve.Rs.map((v) => v * 100), name: 'Rs', line: { color: DATA.secondary, width: 1, dash: 'dot' } },
                    { type: 'scatter', mode: 'lines', x: data.angle_curve.angles_deg, y: data.angle_curve.Rp.map((v) => v * 100), name: 'Rp', line: { color: DATA.secondary, width: 1, dash: 'dash' } },
                    ...(opaque
                      ? []
                      : ([
                          { type: 'scatter', mode: 'lines', x: data.angle_curve.angles_deg, y: data.angle_curve.T.map((v) => v * 100), name: 'T', line: { color: DATA.primary, width: 1.8 } },
                          { type: 'scatter', mode: 'lines', x: data.angle_curve.angles_deg, y: data.angle_curve.Ts.map((v) => v * 100), name: 'Ts', line: { color: DATA.primary, width: 1, dash: 'dot' } },
                          { type: 'scatter', mode: 'lines', x: data.angle_curve.angles_deg, y: data.angle_curve.Tp.map((v) => v * 100), name: 'Tp', line: { color: DATA.primary, width: 1, dash: 'dash' } },
                        ] as Trace[])),
                  ]}
                  layout={{ margin: { l: 52, r: 12, t: 8, b: 40 }, hovermode: 'x unified', xaxis: { title: { text: t('ca.angleAxis') }, range: [0, 89] }, yaxis: { title: { text: '%' }, range: [-2, 102] }, legend: { orientation: 'h', y: 1.06, font: { size: 10 } } }}
                />
              </div>
            </div>
          )}
          {tab === 'phase' && (
            <div className="flex h-full min-h-[300px] flex-col">
              <div className="flex shrink-0 flex-wrap items-center gap-3 px-3 py-1 text-small">
                <Select
                  className="h-6 w-44 text-small"
                  value={phaseQ}
                  ariaLabel={t('ca.phaseQuantity')}
                  options={[
                    { value: 'gdd', label: t('ca.gdd') },
                    { value: 'gd', label: t('ca.gd') },
                    { value: 'phase', label: t('ca.phase') },
                    { value: 'ellipso', label: t('ca.ellipso') },
                  ]}
                  onChange={setPhaseQ}
                />
                {phaseQ !== 'ellipso' && (
                  <Select
                    className="h-6 w-36 text-small"
                    value={side}
                    ariaLabel={t('ca.side')}
                    options={[
                      { value: 'r', label: t('ca.onReflection') },
                      ...(opaque ? [] : [{ value: 't' as const, label: t('ca.onTransmission') }]),
                    ]}
                    onChange={setSide}
                  />
                )}
                <span className="min-w-0 text-caption text-faint">{t('ca.phaseHint', { min: fmt((data.phase_min_power ?? 1e-3) * 100, 3) })}</span>
              </div>
              <div className="min-h-0 flex-1">
                <Plot
                  data={phaseTraces}
                  layout={{
                    margin: { l: 58, r: phaseQ === 'ellipso' ? 52 : 12, t: 8, b: 40 },
                    hovermode: 'x unified',
                    shapes: refLine,
                    xaxis: { title: { text: 'λ (nm)' } },
                    yaxis: { title: { text: phaseAxis } },
                    ...(phaseQ === 'ellipso' ? { yaxis2: { title: { text: 'Δ (°)' }, overlaying: 'y', side: 'right' } } : {}),
                    legend: { orientation: 'h', y: 1.06, font: { size: 10 } },
                  }}
                />
              </div>
            </div>
          )}
          {tab === 'colour' && (
            <div className="flex flex-col gap-3 p-3">
              <div className="flex flex-wrap items-center gap-2 text-small">
                <span className="text-muted">{t('ca.illuminant')}</span>
                <Select className="h-6 w-20 text-small" value={illuminant} ariaLabel={t('ca.illuminant')} options={['D65', 'D50', 'D55', 'D75', 'A', 'C', 'F2', 'F7', 'F11'].map((x) => ({ value: x, label: x }))} onChange={(v) => setIlluminant(v as CoatingIlluminant)} />
                <span className="ml-2 text-muted">{t('ca.observer')}</span>
                <Select className="h-6 w-20 text-small" value={observer} ariaLabel={t('ca.observer')} options={[{ value: '2', label: '2°' }, { value: '10', label: '10°' }]} onChange={(v) => setObserver(v as '2' | '10')} />
              </div>
              <div className="grid grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-3">
                <Swatch c={data.colour.R} label={t('ca.reflected')} />
                {!opaque && <Swatch c={data.colour.T} label={t('ca.transmitted')} />}
              </div>
              <div className="text-caption text-faint">{t('ca.colourHint2', { angle: fmt(data.angle_deg, 3), illuminant: data.colour.illuminant, observer: data.colour.observer })}</div>
            </div>
          )}
          {tab === 'field' && f && (
            <div className="flex h-full min-h-[320px] flex-col">
              <div className="flex shrink-0 flex-wrap items-center gap-3 px-3 py-1 text-small">
                <Select
                  className="h-6 w-20 text-small"
                  value={pol}
                  ariaLabel={t('ca.pol')}
                  options={[
                    { value: 's', label: 's' },
                    { value: 'p', label: 'p' },
                  ]}
                  onChange={setPol}
                />
                <Checkbox checked={fieldMap} onChange={setFieldMap} label={<span className="whitespace-nowrap text-muted" title={t('ca.fieldMapHint')}>{t('ca.fieldMap')}</span>} />
                <span className="text-caption text-faint">{fieldMap && data.field_map ? t('ca.fieldMapHint') : t('ca.fieldHint', { nm: fmt(f.wavelength_nm, 5), angle: fmt(f.angle_deg, 3) })}</span>
              </div>
              {fieldMap && data.field_map ? (
                <div className="min-h-0 flex-1">
                  <Plot
                    data={[{ type: 'heatmap', x: data.field_map.z_nm, y: data.field_map.wavelength_nm, z: data.field_map.e2, colorscale: 'Viridis', colorbar: { title: { text: '|E|²' }, thickness: 10 }, hovertemplate: 'z %{x:.1f} nm<br>λ %{y:.1f} nm<br>|E|² %{z:.4f}<extra></extra>' }]}
                    layout={{
                      margin: { l: 56, r: 12, t: 8, b: 40 },
                      shapes: data.field_map.boundaries_nm.map((zb) => ({ type: 'line', xref: 'x', yref: 'paper', x0: zb, x1: zb, y0: 0, y1: 1, line: { color: 'rgba(255,255,255,0.35)', width: 0.6 } })),
                      xaxis: { title: { text: t('ca.depthAxis') } },
                      yaxis: { title: { text: 'λ (nm)' } },
                    }}
                  />
                </div>
              ) : (
              <div className={cx('min-h-0', absorbing ? 'flex-[2]' : 'flex-1')}>
                <Plot
                  data={[
                    { type: 'scatter', mode: 'lines', x: f.z_nm, y: f.e2, name: '|E|²', line: { color: DATA.primary, width: 1.6 }, hovertemplate: 'z %{x:.1f} nm<br>|E|² %{y:.4f}<extra></extra>' },
                    { type: 'scatter', mode: 'lines', x: zProf, y: nProf, name: 'n', yaxis: 'y2', line: { shape: 'hv', color: DATA.reference, width: 1 }, hovertemplate: 'n %{y:.4f}<extra></extra>' },
                  ]}
                  layout={{
                    margin: { l: 52, r: 48, t: 8, b: 40 },
                    shapes: fieldShapes,
                    xaxis: { title: { text: t('ca.depthAxis') } },
                    yaxis: { title: { text: '|E|² / |E₀|²' }, rangemode: 'tozero' },
                    yaxis2: { title: { text: 'n' }, overlaying: 'y', side: 'right', rangemode: 'tozero', showgrid: false },
                    legend: { orientation: 'h', y: 1.06, font: { size: 10 } },
                  }}
                />
              </div>
              )}
              {absorbing && !fieldMap && (
                <div className="min-h-0 flex-1 overflow-auto border-t border-line">
                  <table className="eng-table">
                    <thead>
                      <tr>
                        <th className="w-10 text-right">#</th>
                        <th>{t('coat.material')}</th>
                        <th className="text-right">{t('ca.absorbed')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {f.layer_absorptance.map((a, i) => (
                        <tr key={i}>
                          <td className="num px-2 text-right text-muted">{i + 1}</td>
                          <td className="px-2">{f.labels[i]}</td>
                          <td className="num px-2 text-right">{pct(a, 4)}</td>
                        </tr>
                      ))}
                      {f.substrate_absorptance > 0 && (
                        <tr>
                          <td className="px-2 text-right text-muted">S</td>
                          <td className="px-2">{t('ca.substrate')}</td>
                          <td className="num px-2 text-right">{pct(f.substrate_absorptance, 4)}</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
          {tab === 'admittance' && data.admittance && <AdmittanceView a={data.admittance[pol]} pol={pol} setPol={setPol} />}
          {tab === 'profile' && pr && (
            <div className="flex h-full min-h-[320px] flex-col">
              <div className="min-h-[180px] flex-1">
                <Plot
                  data={[{ type: 'scatter', mode: 'lines', x: zProf, y: nProf, line: { shape: 'hv', color: DATA.reference, width: 1.4 }, fill: 'tozeroy', fillcolor: DATA.fill, hovertemplate: 'z %{x:.1f} nm<br>n %{y:.4f}<extra></extra>' }]}
                  layout={{ margin: { l: 52, r: 12, t: 8, b: 40 }, xaxis: { title: { text: t('ca.depthAxis') } }, yaxis: { title: { text: `n @ ${fmt(pr.wavelength_nm, 5)} nm` }, rangemode: 'tozero' }, showlegend: false }}
                />
              </div>
              <div className="max-h-[45%] overflow-auto border-t border-line">
                <table className="eng-table">
                  <thead>
                    <tr>
                      <th className="w-10 text-right">#</th>
                      <th>{t('coat.material')}</th>
                      <th className="text-right">n</th>
                      <th className="text-right">k</th>
                      <th className="text-right">d (nm)</th>
                      <th className="text-right" title={t('ca.qwotHint')}>
                        QWOT
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {pr.layers.map((L, i) => (
                      <tr key={i}>
                        <td className="num px-2 text-right text-muted">{i + 1}</td>
                        <td className="px-2">{L.label}</td>
                        <td className="num px-2 text-right">{fmt(L.n, 5)}</td>
                        <td className="num px-2 text-right">{fmt(L.k, 4)}</td>
                        <td className="num px-2 text-right">{fmt(L.thickness_nm, 6)}</td>
                        <td className="num px-2 text-right">{fmt(L.qwot, 4)}</td>
                      </tr>
                    ))}
                    <tr>
                      <td className="px-2 text-right text-faint">Σ</td>
                      <td className="px-2 text-faint">{t('ca.total', { n: pr.layers.length })}</td>
                      <td colSpan={2} />
                      <td className="num px-2 text-right font-semibold">{fmt(pr.total_nm, 6)}</td>
                      <td />
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
      {data && (
        <div className="border-t border-line px-3 py-1 text-caption text-faint" title={data.method}>
          {[...data.notes, data.method].join(' · ')}
        </div>
      )}
    </div>
  )
}

/** Admittance diagram: the running admittance Y = C/B from the substrate outwards, one arc per layer, with
 * iso-reflectance circles (engine coatanalysis.admittance_locus). */
function AdmittanceView({ a, pol, setPol }: { a: CoatingAdmittance; pol: 's' | 'p'; setPol: (p: 's' | 'p') => void }) {
  const t = useT()
  const labels = [...new Set(a.arcs.map((x) => x.label))]
  const colour = (label: string) => SERIES[labels.indexOf(label) % SERIES.length]
  const seen = new Set<string>()
  const traces: Trace[] = a.arcs.map((arc, i) => {
    const first = !seen.has(arc.label)
    seen.add(arc.label)
    return {
      type: 'scatter',
      mode: 'lines',
      x: arc.re,
      y: arc.im,
      name: arc.label,
      legendgroup: arc.label,
      showlegend: first,
      line: { color: colour(arc.label), width: 2 },
      hovertemplate: `${t('cd.layer')} ${a.arcs.length - i} (${arc.label}, ${fmt(arc.thickness_nm, 5)} nm)<br>Y = %{x:.4f} %{y:+.4f}i<extra></extra>`,
    }
  })
  traces.push({ type: 'scatter', mode: 'markers', x: [a.substrate[0]], y: [a.substrate[1]], name: t('ca.substrate'), marker: { symbol: 'square', size: 9, color: DATA.reference } })
  traces.push({ type: 'scatter', mode: 'markers', x: [a.end[0]], y: [a.end[1]], name: t('ca.admEnd'), marker: { symbol: 'circle', size: 10, color: DATA.marker } })
  traces.push({ type: 'scatter', mode: 'markers', x: [a.eta0[0]], y: [a.eta0[1]], name: 'η₀', marker: { symbol: 'diamond', size: 9, color: DATA.secondary } })
  const xs = [a.substrate[0], a.end[0], a.eta0[0], ...a.arcs.flatMap((x) => x.re)]
  const ys = [a.substrate[1], a.end[1], ...a.arcs.flatMap((x) => x.im)]
  const pad = 0.08 * Math.max(1e-6, Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys))
  const shapes = a.iso_R.map((c) => ({ type: 'circle', xref: 'x', yref: 'y', x0: c.centre - c.radius, x1: c.centre + c.radius, y0: -c.radius, y1: c.radius, line: { color: DATA.reference, width: 0.8, dash: 'dot' }, layer: 'below' }))
  const notes = a.iso_R.map((c) => ({ x: c.centre + c.radius, y: 0, xref: 'x', yref: 'y', text: `${fmt(c.R * 100, 3)} %`, showarrow: false, font: { size: 9 }, xanchor: 'left', yanchor: 'bottom' }))
  return (
    <div className="flex h-full min-h-[320px] flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-3 px-3 py-1 text-small">
        <Select
          className="h-6 w-20 text-small"
          value={pol}
          ariaLabel={t('ca.pol')}
          options={[
            { value: 's', label: 's' },
            { value: 'p', label: 'p' },
          ]}
          onChange={setPol}
        />
        <span className="text-muted">
          R = {fmt(a.R * 100, 5)} % · arg r = {fmt(a.phase_r_deg, 4)}°
        </span>
        <span className="min-w-0 text-caption text-faint">{t('ca.admHint', { nm: fmt(a.wavelength_nm, 5), angle: fmt(a.angle_deg, 3) })}</span>
      </div>
      <div className="min-h-0 flex-1">
        <Plot
          data={traces}
          layout={{
            margin: { l: 56, r: 12, t: 8, b: 40 },
            shapes,
            annotations: notes,
            xaxis: { title: { text: 'Re Y' }, range: [Math.min(...xs) - pad, Math.max(...xs) + pad], zeroline: false },
            yaxis: { title: { text: 'Im Y' }, range: [Math.min(...ys, 0) - pad, Math.max(...ys, 0) + pad], scaleanchor: 'x', scaleratio: 1, zeroline: true },
            legend: { orientation: 'h', y: 1.06, font: { size: 10 } },
          }}
        />
      </div>
    </div>
  )
}
