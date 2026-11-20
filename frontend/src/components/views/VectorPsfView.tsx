import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { COLORMAPS, DATA } from '../../lib/palette'
import type { VectorPsfResult } from '../../lib/types'
import { useAllMaterials } from '../../store/catalogStore'
import { useProjectStore } from '../../store/projectStore'
import { FieldSelect, Row, Stat, WavelengthSelect } from '../common/controls'
import { Plot } from '../common/Plot'
import { Checkbox, NumberField, Select } from '../common/ui'
import { useAnalysisSettings } from '../common/useAnalysisSettings'
import { AnalysisFrame } from './AnalysisFrame'
import { useAnalysis } from './useAnalysis'

type VInput = 'x' | 'y' | '45' | '-45' | 'rcp' | 'lcp' | 'radial' | 'azimuthal'
type VMap = 'total' | 'x' | 'y' | 'z' | 'section'
const DEFAULTS = { field: 0, wavelength: null as number | null, input: 'x' as VInput, map: 'total' as VMap, rings: 40, grid: 81, half_width_um: null as number | null, defocus_um: 0, crystal_modes: 'sum' as 'sum' | 'prescription', gaussian_fill: null as number | null, log: false }
const INPUTS: VInput[] = ['x', 'y', '45', '-45', 'rcp', 'lcp', 'radial', 'azimuthal']

/** Debye–Wolf vector PSF from the real rays (engine: analysis/vectorpsf.py). */
export function VectorPsfView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const [st, set] = useAnalysisSettings('vectorpsf', DEFAULTS)
  const settings = {
    field: Math.min(st.field, system.fields.length - 1),
    wavelength: st.wavelength !== null && st.wavelength >= system.wavelengths.length ? null : st.wavelength,
    input: st.input,
    rings: st.rings,
    grid: st.grid,
    half_width_um: st.half_width_um,
    defocus_um: st.defocus_um,
    section: st.map === 'section',
    crystal_modes: st.crystal_modes,
    gaussian_fill: st.gaussian_fill,
  }
  const { data, error, loading, ms, refresh } = useAnalysis<VectorPsfResult>('vectorpsf', settings)
  const materials = useAllMaterials()
  const hasCrystal = system.surfaces.some((s) => !!materials.find((m) => m.name === s.material)?.extraordinary)
  const logz = (m: number[][]) => (st.log ? m.map((r) => r.map((v) => (v > 0 ? Math.log10(v) : null))) : m)
  const maps = (['total', 'x', 'y', 'z', 'section'] as VMap[]).map((v) => ({ value: v, label: t(`vpsf.map.${v}`) }))
  const z = data ? (st.map === 'section' ? data.section?.intensity ?? null : st.map === 'total' ? data.intensity : data.components[st.map]) : null
  const ef = data?.energy_fraction
  return (
    <AnalysisFrame
      kind="vectorpsf"
      title={t('view.vectorpsf')}
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
          <Select className="h-6 w-32 text-small" ariaLabel={t('pol.input')} value={st.input} options={INPUTS.map((v) => ({ value: v, label: t(`vpsf.in.${v}`) }))} onChange={(v) => set({ input: v as VInput })} />
          <Select className="h-6 w-36 text-small" ariaLabel={t('vpsf.map')} value={st.map} options={maps} onChange={(v) => set({ map: v as VMap })} />
        </>
      }
      more={
        <>
          <FieldSelect system={system} value={settings.field} onChange={(v) => set({ field: v })} />
          <WavelengthSelect system={system} value={settings.wavelength} onChange={(v) => set({ wavelength: v })} />
          <Row label={t('vpsf.defocus')} hint={t('vpsf.defocusHint')}>
            <NumberField className="h-6 w-20" ariaLabel={t('vpsf.defocus')} value={st.defocus_um} min={-1e4} max={1e4} onCommit={(v) => set({ defocus_um: v ?? 0 })} />
          </Row>
          <Row label={t('vpsf.halfWidth')} hint={t('vpsf.halfWidthHint')}>
            <NumberField className="h-6 w-20" optional ariaLabel={t('vpsf.halfWidth')} value={st.half_width_um} placeholder={t('vpsf.auto')} min={1e-3} max={1e4} onCommit={(v) => set({ half_width_um: v })} />
          </Row>
          <Row label={t('vpsf.fill')} hint={t('vpsf.fillHint')}>
            <NumberField className="h-6 w-20" optional ariaLabel={t('vpsf.fill')} value={st.gaussian_fill} placeholder={t('vpsf.uniform')} min={0.05} max={10} onCommit={(v) => set({ gaussian_fill: v })} />
          </Row>
          <Row label={t('vpsf.rings')} hint={t('vpsf.ringsHint')}>
            <NumberField className="h-6 w-20" ariaLabel={t('vpsf.rings')} value={st.rings} integer min={8} max={96} onCommit={(v) => set({ rings: v ?? 40 })} />
          </Row>
          <Row label={t('an.grid')} hint={t('vpsf.gridHint')}>
            <NumberField className="h-6 w-20" ariaLabel={t('an.grid')} value={st.grid} integer min={21} max={161} onCommit={(v) => set({ grid: v ?? 81 })} />
          </Row>
          {hasCrystal && (
            <Row label={t('pol.crystalModes')} hint={t('pol.crystalModesHint')}>
              <Select className="h-6 w-36 text-small" ariaLabel={t('pol.crystalModes')} value={st.crystal_modes} options={[{ value: 'sum', label: t('pol.cm.sum') }, { value: 'prescription', label: t('pol.cm.prescription') }]} onChange={(v) => set({ crystal_modes: v as 'sum' | 'prescription' })} />
            </Row>
          )}
          <span className="w-full">
            <Checkbox checked={st.log} onChange={(v) => set({ log: v })} label={<span className="text-small text-muted">{t('an.log')}</span>} />
          </span>
        </>
      }
    >
      {data && ef && (
        <div className="flex h-full min-h-0 flex-col">
          <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
            <Stat label="NA" value={fmt(data.na, 4)} />
            <Stat label={t('vpsf.fwhmX')} value={fmt(data.fwhm_x_um, 4)} unit={`µm (${fmt(data.fwhm_x_waves, 3)} λ)`} />
            <Stat label={t('vpsf.fwhmY')} value={fmt(data.fwhm_y_um, 4)} unit={`µm (${fmt(data.fwhm_y_waves, 3)} λ)`} />
            <Stat label={t('vpsf.area')} value={fmt(data.half_max_area_waves2, 3)} unit="λ²" />
            <Stat label={t('vpsf.ez')} value={fmt(ef.z * 100, 3)} unit="%" />
            <Stat label="Strehl" value={fmt(data.strehl, 4)} />
          </div>
          <div className="grid min-h-0 flex-1 grid-cols-[repeat(auto-fit,minmax(280px,1fr))] gap-px bg-line">
            <div className="min-h-[240px] bg-panel">
              {z && (
                <Plot
                  square={st.map !== 'section'}
                  data={[
                    {
                      type: 'heatmap',
                      x: st.map === 'section' ? data.section!.x_um : data.x_um,
                      y: st.map === 'section' ? data.section!.z_um : data.x_um,
                      z: logz(z),
                      colorscale: COLORMAPS.sequential,
                      colorbar: { title: { text: st.log ? 'log₁₀ |E|²' : '|E|²' }, thickness: 10 },
                      hovertemplate: `x %{x:.3f} µm<br>${st.map === 'section' ? 'z' : 'y'} %{y:.3f} µm<br>%{z:.4g}<extra></extra>`,
                    },
                  ]}
                  layout={{ margin: { l: 52, r: 8, t: 22, b: 40 }, title: { text: maps.find((m) => m.value === st.map)?.label ?? '', font: { size: 11 } }, xaxis: { title: { text: 'x (µm)' } }, yaxis: { title: { text: st.map === 'section' ? 'z (µm)' : 'y (µm)' } } }}
                />
              )}
            </div>
            <div className="min-h-[240px] bg-panel">
              <Plot
                data={[
                  { type: 'scatter', mode: 'lines', x: data.profile_x.x_um, y: data.profile_x.total, name: `${t('vpsf.total')} (x)`, line: { color: DATA.primary, width: 2 } },
                  { type: 'scatter', mode: 'lines', x: data.profile_y.x_um, y: data.profile_y.total, name: `${t('vpsf.total')} (y)`, line: { color: DATA.secondary, width: 2, dash: 'dash' } },
                  { type: 'scatter', mode: 'lines', x: data.profile_x.x_um, y: data.profile_x.z, name: '|Ez|² (x)', line: { color: DATA.tertiary, width: 1.4 } },
                ]}
                layout={{ margin: { l: 52, r: 8, t: 26, b: 40 }, xaxis: { title: { text: `${t('vpsf.position')} — ${t('vpsf.profiles')}` } }, yaxis: { title: { text: '|E|²' }, rangemode: 'tozero' }, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom', font: { size: 10 } } }}
              />
            </div>
          </div>
          <div className="shrink-0 border-t border-line px-3 py-1 text-caption text-faint">
            {t('vpsf.energy')}: x {fmt(ef.x * 100, 3)} % · y {fmt(ef.y * 100, 3)} % · z {fmt(ef.z * 100, 3)} % · {t('vpsf.airy')} {fmt(data.scalar_airy_fwhm_um, 4)} µm · {data.samples} {t('vpsf.rays')}
            {data.vignetted_fraction > 1e-6 && ` · ${t('vpsf.vignetted')} ${fmt(data.vignetted_fraction * 100, 3)} %`}
          </div>
        </div>
      )}
    </AnalysisFrame>
  )
}
