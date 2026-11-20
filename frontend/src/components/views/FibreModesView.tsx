import { Plus, X } from 'lucide-react'
import { fmt } from '../../lib/format'
import { DEFAULT_LAYERS, FIBRE_DEFAULTS, fibreRequest, layersProblem, type FibreSettings } from '../../lib/fibre'
import { useT } from '../../lib/i18n'
import { DATA, SERIES } from '../../lib/palette'
import type { FibreDispersionResult, FibreModesResult, FibreRequest } from '../../lib/types'
import { useProjectStore } from '../../store/projectStore'
import { Label, Pair, Stat } from '../common/controls'
import { Plot, type Trace } from '../common/Plot'
import { Badge, Button, Checkbox, IconButton, NumberField, Select } from '../common/ui'
import { useAnalysisSettings } from '../common/useAnalysisSettings'
import { useMaterialNames } from '../editors/materialNames'
import { AnalysisFrame } from './AnalysisFrame'
import { useAnalysis } from './useAnalysis'
import { Notes } from './WaveViews'

const UM: Record<string, number> = { um: 1, µm: 1, nm: 1e-3, mm: 1e3 }

export function FibreModesView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const names = useMaterialNames().filter((n) => !['AIR', 'MIRROR', 'VACUUM'].includes(n))
  const [st, set] = useAnalysisSettings<FibreSettings>('fibermodes', FIBRE_DEFAULTS)
  const sysLam = system.wavelengths[system.primary_wavelength]?.value ?? 1.55
  const lam = st.wavelength_um ?? sysLam
  const req = fibreRequest(st, sysLam)
  const layered = st.profile_kind === 'layers'
  const problem = layered ? layersProblem(st.layers) : null
  const { data: raw, error, loading, ms, refresh } = useAnalysis<FibreModesResult>('fibermodes', req as unknown as Record<string, unknown>)
  // an earlier result must not stand for a ring table the engine cannot solve
  const data = problem ? null : raw
  const rMax = data ? Math.max(...data.index_profile.r_um) : 0
  const traces: Trace[] = [
    ...(data?.profiles ?? []).map((p, i) => ({ type: 'scatter', mode: 'lines', x: p.r_um, y: p.field, name: p.name, line: { color: SERIES[i % 8], width: i === 0 ? 2.2 : 1.4 }, hovertemplate: `${p.name}<br>r %{x:.3f} µm<br>E %{y:.4f}<extra></extra>` })),
    ...(data
      ? [{ type: 'scatter', mode: 'lines', x: data.index_profile.r_um, y: data.index_profile.n.map((n) => n - data.n_clad), name: 'Δn', yaxis: 'y2', line: { color: DATA.reference, width: 1.2, dash: 'dot' }, hovertemplate: 'r %{x:.3f} µm<br>Δn %{y:.5f}<extra></extra>' }]
      : []),
  ]
  const lp = data ? new Map(data.lp_modes.map((m) => [m.name, m])) : new Map()
  const setRing = (i: number, j: 0 | 1, v: number) => set({ layers: st.layers.map((r, k) => (k === i ? ((j === 0 ? [v, r[1]] : [r[0], v]) as [number, number]) : r)) }, 'Fibre ring')
  return (
    <AnalysisFrame
      kind="fibermodes"
      title={t('view.fibermodes')}
      loading={loading}
      error={error}
      hasData={!!data}
      ms={ms}
      method={data?.method}
      onRefresh={refresh}
      settings={req as unknown as Record<string, unknown>}
      result={data}
      alwaysShow={layered}
      controls={
        <>
          <Select
            className="h-6 w-32 text-small"
            ariaLabel={t('fm.profile')}
            title={t('fm.profileHint')}
            value={st.profile_kind}
            options={[
              { value: 'step', label: t('fm.step') },
              { value: 'graded', label: t('fm.graded') },
              { value: 'layers', label: t('fm.layers') },
            ]}
            onChange={(v) => set(v === 'layers' && !st.layers.length ? { profile_kind: v, layers: DEFAULT_LAYERS } : { profile_kind: v }, 'Fibre profile')}
          />
          <Pair>
            <Label hint={t('fm.lambdaHint')}>λ (µm)</Label>
            <NumberField className="h-6 w-16" ariaLabel={t('c.wavelength')} value={lam} min={0.05} max={100} units={UM} onCommit={(v) => set({ wavelength_um: v })} />
          </Pair>
          {!layered && (
            <>
              <Pair>
                <Label hint={`${t('fm.core')}: ${t('fm.coreHint')}`}>a (µm)</Label>
                <NumberField className="h-6 w-16" ariaLabel={t('fm.core')} value={st.core_radius_um} min={0.01} max={5000} units={UM} onCommit={(v) => v && set({ core_radius_um: v })} />
              </Pair>
              <Pair>
              <Select
                className="h-6 w-16 text-small"
                ariaLabel={t('fm.contrast')}
                title={t('fm.contrastHint')}
                value={st.spec}
                options={[
                  { value: 'na', label: 'NA' },
                  { value: 'n_core', label: t('fm.nCore') },
                  { value: 'dn', label: 'Δn' },
                ]}
                onChange={(v) => set({ spec: v })}
              />
              {st.spec === 'na' ? (
                <NumberField className="h-6 w-16" ariaLabel="NA" value={st.na} min={1e-4} max={1.5} onCommit={(v) => v && set({ na: v })} />
              ) : st.spec === 'n_core' ? (
                <NumberField className="h-6 w-20" ariaLabel={t('fm.nCore')} value={st.n_core} min={1} onCommit={(v) => v && set({ n_core: v })} />
              ) : (
                <NumberField className="h-6 w-20" ariaLabel="Δn" title={t('fm.dnHint')} value={st.dn} min={1e-6} max={0.99} onCommit={(v) => v && set({ dn: v })} />
              )}
              </Pair>
            </>
          )}
          {st.profile_kind === 'graded' && (
            <Pair>
              <Label hint={t('fm.alphaHint')}>α</Label>
              <NumberField className="h-6 w-12" ariaLabel="α" value={st.alpha} min={0.1} max={100} onCommit={(v) => v && set({ alpha: v })} />
            </Pair>
          )}
        </>
      }
      more={
        <>
          <Pair>
            <Label hint={t('fm.cladHint')}>{t('fm.clad')}</Label>
            <Select className="h-6 w-36 text-small" ariaLabel={t('fm.clad')} value={st.clad_material} options={[{ value: '', label: t('fm.cladIndex') }, ...names.map((n) => ({ value: n, label: n }))]} onChange={(v) => set({ clad_material: v })} />
            {!st.clad_material && <NumberField className="h-6 w-20" ariaLabel="n clad" value={st.n_clad} min={1} onCommit={(v) => v && set({ n_clad: v })} />}
          </Pair>
          {st.profile_kind === 'step' && <Checkbox checked={st.vector} onChange={(v) => set({ vector: v })} label={t('fm.vector')} />}
          <Checkbox checked={st.dispersion} onChange={(v) => set({ dispersion: v })} label={t('fm.dispersion')} title={t('fm.dispHint')} />
          {st.dispersion && (
            <>
              <Pair>
                <Label hint={t('fm.bandHint')}>{t('fm.band')}</Label>
                <NumberField className="h-6 w-14" ariaLabel={`${t('fm.band')} min`} value={st.disp_min_um} min={0.05} max={100} units={UM} onCommit={(v) => v && set({ disp_min_um: v })} />
                <NumberField className="h-6 w-14" ariaLabel={`${t('fm.band')} max`} value={st.disp_max_um} min={0.05} max={100} units={UM} onCommit={(v) => v && set({ disp_max_um: v })} />
              </Pair>
              <Pair>
                <Label>{t('fm.points')}</Label>
                <NumberField className="h-6 w-12" ariaLabel={t('fm.points')} value={st.disp_points} min={3} max={201} integer onCommit={(v) => v && set({ disp_points: Math.round(v) })} />
              </Pair>
            </>
          )}
        </>
      }
    >
      <div className="flex h-full min-h-0 flex-col overflow-y-auto">
        {layered && (
          <div className="flex max-h-[150px] shrink-0 flex-col border-b border-line">
            <div className="flex shrink-0 items-center gap-2 bg-panel px-2 py-1">
              <span className="text-small font-semibold tracking-wide text-muted uppercase">{t('fm.rings')}</span>
              <Button size="sm" onClick={() => set({ layers: [...st.layers, [(st.layers.at(-1)?.[0] ?? 0) + 2, 0]] }, 'Add fibre ring')}>
                <Plus size={12} /> {t('fm.addRing')}
              </Button>
              {problem ? <Badge tone="danger">{t(`fm.prob.${problem}`)}</Badge> : <span className="truncate text-caption text-faint">{t('fm.ringsHint')}</span>}
            </div>
            <div className="min-h-0 overflow-auto">
              <table className="eng-table">
                <thead>
                  <tr>
                    <th className="w-8">#</th>
                    <th className="text-right">{t('fm.ringR')}</th>
                    <th className="text-right">{t('fm.ringDn')}</th>
                    <th className="w-8" />
                  </tr>
                </thead>
                <tbody>
                  {st.layers.map(([r, d], i) => (
                    <tr key={i}>
                      <td className="px-2 text-muted">{i + 1}</td>
                      <td className="px-1">
                        <NumberField cell className="h-6 w-full" ariaLabel={`${t('fm.ringR')} ${i + 1}`} value={r} min={1e-3} max={5000} onCommit={(v) => v && setRing(i, 0, v)} />
                      </td>
                      <td className="px-1">
                        <NumberField cell className="h-6 w-full" ariaLabel={`${t('fm.ringDn')} ${i + 1}`} value={d} min={-0.99} max={0.99} onCommit={(v) => setRing(i, 1, v ?? 0)} />
                      </td>
                      <td className="px-1">
                        <IconButton size="sm" tone="danger" title={t('fm.removeRing')} onClick={() => set({ layers: st.layers.filter((_, k) => k !== i) }, 'Remove fibre ring')}>
                          <X size={12} />
                        </IconButton>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {layered && !data && error && !problem && <div className="p-3 text-body text-danger">{error}</div>}
        {data && (
          <>
            <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
              <Stat label="V" value={fmt(data.v_number, 5)} />
              <Stat label={t('fm.singleMode')} value={data.single_mode ? t('c.yes') : `${t('c.no')} (${data.lp_modes.length} LP)`} tone={data.single_mode ? 'ok' : 'warn'} />
              <Stat label="λc (LP11)" value={data.cutoff_wavelength_um !== null ? fmt(data.cutoff_wavelength_um * 1000, 5) : t('fm.noCutoff')} unit={data.cutoff_wavelength_um !== null ? 'nm' : undefined} />
              <Stat label="NA" value={fmt(data.na, 4)} />
              <Stat label="n_eff (LP01)" value={fmt(data.lp01.neff, 8)} />
              <Stat label={t('fm.mfdP2')} value={fmt(data.lp01.mfd_petermann2, 4)} unit="µm" />
              <Stat label={t('fm.aeff')} value={fmt(data.lp01.effective_area_um2, 4)} unit="µm²" />
              <Stat label={t('fm.coreFrac')} value={fmt(data.lp01.core_power_fraction * 100, 4)} unit="%" />
              {data.lp01.gaussian_waist !== undefined && <Stat label={t('fm.mfdGauss')} value={fmt(2 * data.lp01.gaussian_waist, 4)} unit="µm" />}
              {data.lp01.gaussian_overlap !== undefined && <Stat label={t('fm.gaussOverlap')} value={fmt(data.lp01.gaussian_overlap * 100, 4)} unit="%" />}
              <Stat label={t('fm.modes')} value={String(data.mode_count)} />
            </div>
            <div className="grid min-h-[190px] flex-1 grid-cols-[minmax(260px,1.3fr)_minmax(200px,1fr)] gap-px bg-line">
              <div className="min-h-[190px] bg-panel">
                <Plot
                  data={traces}
                  layout={{
                    margin: { l: 50, r: 58, t: 24, b: 38 },
                    legend: { orientation: 'h', x: 0, y: 1.01, yanchor: 'bottom' },
                    shapes: [{ type: 'line', x0: data.core_radius_um, x1: data.core_radius_um, yref: 'paper', y0: 0, y1: 1, line: { width: 1, dash: 'dot', color: 'rgba(128,128,128,0.7)' } }],
                    xaxis: { title: { text: t('fm.radius') }, range: [0, rMax] },
                    yaxis: { title: { text: t('fm.field') }, zeroline: true },
                    yaxis2: { title: { text: t('fm.indexAxis') }, overlaying: 'y', side: 'right', showgrid: false, zeroline: false, nticks: 4, tickformat: '.4f' },
                  }}
                />
              </div>
              <div className="min-h-0 overflow-auto bg-panel">
                <table className="eng-table">
                  <thead>
                    <tr>
                      <th>{t('fm.mode')}</th>
                      <th className="text-right">n_eff</th>
                      <th className="text-right">b</th>
                      <th className="text-right">×</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.lp_modes.slice(0, 200).map((m) => (
                      <tr key={m.name}>
                        <td className="px-2 font-medium">{m.name}</td>
                        <td className="num px-2 text-right">{fmt(m.neff, 9)}</td>
                        <td className="num px-2 text-right">{fmt(m.b ?? 0, 4)}</td>
                        <td className="num px-2 text-right">{m.degeneracy}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {data.vector_modes.length > 0 && (
                  <>
                    <div className="px-3 pt-2 pb-1 text-small font-semibold tracking-wide text-muted uppercase">{t('fm.vectorModes')}</div>
                    <table className="eng-table">
                      <thead>
                        <tr>
                          <th>{t('fm.mode')}</th>
                          <th className="text-right">n_eff</th>
                          <th className="text-right">{t('fm.lpGroup')}</th>
                          <th className="text-right">Δn_eff</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.vector_modes.slice(0, 200).map((m) => {
                          // HE(nu,m) belongs to LP(nu-1,m), EH(nu,m) to LP(nu+1,m), TE/TM(0,m) to LP(1,m)
                          const l = m.kind === 'HE' ? (m.nu ?? 1) - 1 : m.kind === 'EH' ? (m.nu ?? 0) + 1 : 1
                          const g = lp.get(`LP${l}${m.m}`)
                          return (
                            <tr key={m.name}>
                              <td className="px-2 font-medium">{m.name}</td>
                              <td className="num px-2 text-right">{fmt(m.neff, 9)}</td>
                              <td className="px-2 text-right text-muted">{g ? g.name : '—'}</td>
                              <td className="num px-2 text-right text-muted">{g ? (m.neff - g.neff).toExponential(2) : '—'}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </>
                )}
              </div>
            </div>
            <Notes notes={data.notes} />
          </>
        )}
        {st.dispersion && !problem && <DispersionPanel req={req} st={st} lam={lam} />}
      </div>
    </AnalysisFrame>
  )
}

/** n_eff, group index and chromatic dispersion of LP01 over the band (recomputed when the fibre or band changes). */
function DispersionPanel({ req, st, lam }: { req: FibreRequest; st: FibreSettings; lam: number }) {
  const t = useT()
  const body = { ...req, wl_min_um: st.disp_min_um, wl_max_um: st.disp_max_um, points: st.disp_points }
  const { data, error, loading } = useAnalysis<FibreDispersionResult>('fiberdisp', body as unknown as Record<string, unknown>, 400)
  const rows = data?.rows ?? []
  // values at the operating wavelength, interpolated between the computed rows
  let at: { D: number; ng: number } | null = null
  for (let i = 0; i + 1 < rows.length; i++) {
    const a = rows[i]
    const b = rows[i + 1]
    if (lam >= a.wavelength_um && lam <= b.wavelength_um) {
      const f = (lam - a.wavelength_um) / (b.wavelength_um - a.wavelength_um)
      at = { D: a.D_ps_nm_km + f * (b.D_ps_nm_km - a.D_ps_nm_km), ng: a.group_index + f * (b.group_index - a.group_index) }
    }
  }
  const x = rows.map((r) => r.wavelength_um)
  const traces: Trace[] = [
    { type: 'scatter', mode: 'lines', x, y: rows.map((r) => r.D_ps_nm_km), name: t('fm.Dtotal'), line: { color: DATA.primary, width: 2 }, hovertemplate: 'λ %{x:.4f} µm<br>D %{y:.4f} ps/(nm·km)<extra></extra>' },
    { type: 'scatter', mode: 'lines', x, y: rows.map((r) => r.D_material_ps_nm_km), name: t('fm.Dmat'), line: { color: DATA.secondary, width: 1.4, dash: 'dash' }, hovertemplate: 'λ %{x:.4f} µm<br>D_M %{y:.4f}<extra></extra>' },
    { type: 'scatter', mode: 'lines', x, y: rows.map((r) => r.D_waveguide_ps_nm_km), name: t('fm.Dwg'), line: { color: DATA.tertiary, width: 1.4, dash: 'dot' }, hovertemplate: 'λ %{x:.4f} µm<br>D_W %{y:.4f}<extra></extra>' },
  ]
  return (
    <div className="flex h-[46%] min-h-[190px] shrink-0 flex-col border-t border-line">
      <div className="flex shrink-0 flex-wrap items-center divide-x divide-line border-b border-line">
        <span className="px-3 text-small font-semibold tracking-wide text-muted uppercase">
          {t('fm.dispersion')} · {data?.mode ?? 'LP01'}
        </span>
        <Stat label={t('fm.lambda0')} value={data?.zero_dispersion_um ? fmt(data.zero_dispersion_um * 1000, 5) : '—'} unit={data?.zero_dispersion_um ? 'nm' : undefined} />
        <Stat label={t('fm.Dat')} value={at ? fmt(at.D, 4) : '—'} unit={at ? 'ps/(nm·km)' : undefined} />
        <Stat label={t('fm.ng')} value={at ? fmt(at.ng, 7) : '—'} />
        {loading && <span className="px-3 text-caption text-faint">{t('an.computing')}</span>}
      </div>
      <div className="relative min-h-0 flex-1 bg-panel">
        {error ? (
          <div className="p-3 text-body text-danger">{error}</div>
        ) : rows.length ? (
          <Plot
            data={traces}
            layout={{
              margin: { l: 56, r: 12, t: 24, b: 38 },
              legend: { orientation: 'h', x: 0, y: 1.01, yanchor: 'bottom' },
              xaxis: { title: { text: 'λ (µm)' } },
              yaxis: { title: { text: t('fm.dispAxis') }, zeroline: true },
              shapes: [{ type: 'line', x0: lam, x1: lam, yref: 'paper', y0: 0, y1: 1, line: { width: 1, dash: 'dot', color: DATA.marker } }],
            }}
          />
        ) : null}
      </div>
      {data && <Notes notes={data.notes} />}
    </div>
  )
}
