import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { COLORMAPS } from '../../lib/palette'
import type { InterferogramResult } from '../../lib/types'
import { useProjectStore } from '../../store/projectStore'
import { FieldSelect, Label, Pair, Stat, WavelengthSelect } from '../common/controls'
import { Plot } from '../common/Plot'
import { NumberField, Select } from '../common/ui'
import { useAnalysisSettings } from '../common/useAnalysisSettings'
import { AnalysisFrame } from './AnalysisFrame'
import { INTERFEROGRAM_DEFAULTS, type InterferogramSettings } from './interferogramSettings'
import { useAnalysis } from './useAnalysis'
import { Notes } from './WaveViews'

function PupilMap({ x, y, z, scale, title, unit, zmid }: { x: number[]; y: number[]; z: (number | null)[][]; scale: unknown; title: string; unit: string; zmid?: number }) {
  return (
    <div className="flex min-h-0 flex-col bg-panel">
      <div className="shrink-0 px-3 pt-1.5 text-small font-semibold tracking-wide text-muted uppercase">{title}</div>
      <div className="min-h-0 flex-1">
        <Plot
          square
          data={[{ type: 'heatmap', x, y, z, colorscale: scale, zmid, colorbar: { thickness: 10, title: { text: unit, side: 'right' } }, hovertemplate: `Px %{x:.3f}<br>Py %{y:.3f}<br>%{z:.4f} ${unit}<extra></extra>` }]}
          layout={{ margin: { l: 42, r: 8, t: 6, b: 32 }, xaxis: { title: { text: 'P_x' }, range: [-1, 1] }, yaxis: { title: { text: 'P_y' }, range: [-1, 1] } }}
        />
      </div>
    </div>
  )
}

export function InterferogramView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const [st, set] = useAnalysisSettings<InterferogramSettings>('interferogram', INTERFEROGRAM_DEFAULTS)
  const settings: InterferogramSettings = {
    ...INTERFEROGRAM_DEFAULTS,
    ...st,
    field: Math.min(st.field ?? 0, system.fields.length - 1),
    wavelength: st.wavelength !== null && st.wavelength !== undefined && st.wavelength >= system.wavelengths.length ? null : (st.wavelength ?? null),
  }
  const { data, error, loading, ms, refresh } = useAnalysis<InterferogramResult>('interferogram', settings as unknown as Record<string, unknown>)
  return (
    <AnalysisFrame
      kind="interferogram"
      title={t('view.interferogram')}
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
          <WavelengthSelect system={system} value={settings.wavelength} onChange={(v) => set({ wavelength: v })} />
          <Select
            className="h-6 w-40 text-small"
            ariaLabel={t('if.passes')}
            title={t('if.passesHint')}
            value={String(settings.passes)}
            options={[
              { value: '1', label: t('if.single') },
              { value: '2', label: t('if.double') },
            ]}
            onChange={(v) => set({ passes: v === '2' ? 2 : 1 })}
          />
          <Pair>
            <Label hint={t('if.tiltHint')}>{t('if.tilt')}</Label>
            <NumberField className="h-6 w-12" ariaLabel={`${t('if.tilt')} x`} value={settings.tilt_x} min={-200} max={200} onCommit={(v) => set({ tilt_x: v ?? 0 })} />
            <NumberField className="h-6 w-12" ariaLabel={`${t('if.tilt')} y`} value={settings.tilt_y} min={-200} max={200} onCommit={(v) => set({ tilt_y: v ?? 0 })} />
          </Pair>
        </>
      }
      more={
        <>
          <Pair>
            <Label hint={t('an.gridHint')}>{t('an.grid')}</Label>
            <NumberField className="h-6 w-14" ariaLabel={t('an.grid')} value={settings.grid} integer min={16} max={384} onCommit={(v) => set({ grid: Math.round(v ?? 128) })} />
          </Pair>
          <Pair>
            <Label hint={t('if.visibilityHint')}>{t('if.visibility')}</Label>
            <NumberField className="h-6 w-12" ariaLabel={t('if.visibility')} value={settings.visibility} min={0.01} max={1} onCommit={(v) => set({ visibility: v ?? 1 })} />
          </Pair>
          <Pair>
            <Label hint={t('if.stepsHint')}>{t('if.steps')}</Label>
            <Select
              className="h-6 w-24 text-small"
              ariaLabel={t('if.steps')}
              value={String(settings.phase_steps)}
              options={[{ value: '0', label: t('if.noShift') }, ...[3, 4, 5, 6, 7, 8].map((n) => ({ value: String(n), label: `${n}` }))]}
              onChange={(v) => set({ phase_steps: Number(v) })}
            />
          </Pair>
        </>
      }
    >
      {data && (
        <div className="flex h-full min-h-0 flex-col overflow-y-auto">
          <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
            <Stat label={t('if.fringes')} value={fmt(data.fringes_pv, 4)} />
            <Stat label={t('an.pv')} value={fmt(data.pv_waves, 4)} unit={t('an.waves')} />
            <Stat label={t('an.rmsWave')} value={fmt(data.rms_waves, 4)} unit={t('an.waves')} />
            <Stat label="λ" value={fmt(data.wavelength_um * 1000, 6)} unit="nm" />
            <Stat label={t('if.sampling')} value={`${fmt(data.max_step_rad / Math.PI, 3)} π`} tone={data.max_step_rad > 0.9 * Math.PI ? 'warn' : 'ok'} />
            {data.recovery_rms_error_waves !== undefined && <Stat label={t('if.recovery')} value={data.recovery_rms_error_waves.toExponential(1)} unit={t('an.waves')} tone={data.recovery_rms_error_waves > 1e-3 ? 'warn' : 'ok'} />}
          </div>
          <div className="grid min-h-[260px] flex-1 auto-rows-[minmax(260px,1fr)] grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-px bg-line">
            <PupilMap x={data.x} y={data.y} z={data.intensity} scale={COLORMAPS.greys} title={t('if.interferogram')} unit="I" />
            <PupilMap x={data.x} y={data.y} z={data.wavefront_waves} scale={COLORMAPS.diverging} zmid={0} title={t('if.wavefront')} unit={t('an.waves')} />
            {data.recovered_waves && <PupilMap x={data.x} y={data.y} z={data.recovered_waves} scale={COLORMAPS.diverging} zmid={0} title={t('if.recovered', { n: data.phase_steps ?? 0 })} unit={t('an.waves')} />}
          </div>
          <Notes notes={data.notes} />
        </div>
      )}
    </AnalysisFrame>
  )
}
