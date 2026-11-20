import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { DATA } from '../../lib/palette'
import type { ImageSimResult, RelativeIlluminationResult } from '../../lib/types'
import { useProjectStore } from '../../store/projectStore'
import { Label, Row, Stat } from '../common/controls'
import { Plot } from '../common/Plot'
import { Checkbox, NumberField, Select } from '../common/ui'
import { useAnalysisSettings } from '../common/useAnalysisSettings'
import { AnalysisFrame } from './AnalysisFrame'
import { useAnalysis } from './useAnalysis'

const RI_DEFAULTS = { points: 11, rings: 8, transmission: true }

/** Relative illumination from real rays (engine: analysis/imaging.py, energy form). */
export function RelativeIlluminationView() {
  const t = useT()
  const [st, set] = useAnalysisSettings('relillum', RI_DEFAULTS)
  const settings = { points: st.points, rings: st.rings, transmission: st.transmission }
  const { data, error, loading, ms, refresh } = useAnalysis<RelativeIlluminationResult>('relillum', settings)
  const last = data ? data.relative_illumination.length - 1 : 0
  return (
    <AnalysisFrame
      kind="relillum"
      title={t('view.relillum')}
      loading={loading}
      error={error}
      hasData={!!data}
      ms={ms}
      method={data?.method}
      onRefresh={refresh}
      settings={settings}
      result={data}
      controls={
        <Label hint={t('ri.transmissionHint')}>
          <Checkbox checked={st.transmission} ariaLabel={t('ri.transmission')} onChange={(v) => set({ transmission: v })} label={t('ri.transmission')} />
        </Label>
      }
      more={
        <>
          <Row label={t('ri.points')} hint={t('ri.pointsHint')}>
            <NumberField className="h-6 w-20" ariaLabel={t('ri.points')} value={st.points} integer min={2} max={101} onCommit={(v) => set({ points: v ?? 11 })} />
          </Row>
          <Row label={t('tol.rings')} hint={t('tol.ringsHint')}>
            <NumberField className="h-6 w-20" ariaLabel={t('tol.rings')} value={st.rings} integer min={2} max={20} onCommit={(v) => set({ rings: v ?? 8 })} />
          </Row>
        </>
      }
    >
      {data && (
        <div className="flex h-full min-h-0 flex-col">
          <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
            <Stat label={t('ri.atEdge')} value={`${fmt(data.relative_illumination[last] * 100, 4)} %`} />
            <Stat label={t('ri.vignetting')} value={`${fmt(Math.max(0, 1 - Math.min(...data.unvignetted_fraction)) < 1e-9 ? 0 : (1 - Math.min(...data.unvignetted_fraction)) * 100, 3)} %`} />
            <Stat label={t('ri.edgeHeight')} value={fmt(Math.abs(data.image_heights_mm[last]), 5)} unit="mm" />
          </div>
          <div className="min-h-[220px] flex-1">
            <Plot
              data={[
                { type: 'scatter', mode: 'lines+markers', x: data.field_values, y: data.relative_illumination, name: t('ri.ri'), line: { color: DATA.primary, width: 2 }, marker: { size: 5 } },
                { type: 'scatter', mode: 'lines', x: data.field_values, y: data.unvignetted_fraction, name: t('ri.unvignetted'), line: { color: DATA.secondary, width: 1.4, dash: 'dash' } },
              ]}
              layout={{ xaxis: { title: { text: `${t('ax.field')} (${data.field_unit === 'deg' ? '°' : 'mm'})` } }, yaxis: { title: { text: t('ri.ri') }, rangemode: 'tozero' }, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom', font: { size: 10 } }, margin: { l: 56, r: 14, t: 26, b: 44 } }}
            />
          </div>
        </div>
      )}
    </AnalysisFrame>
  )
}

const SIM_DEFAULTS = { scene: 'siemens' as 'siemens' | 'bars' | 'grid' | 'checker' | 'edge', crop_px: 256, grid: 5, oversample: 3, exposure: 0.7, noise: true, seed: 1, show: 'sensor' as 'sensor' | 'optics' | 'ideal' }

/** One sensor image (uint16, rows from the top) drawn on a canvas, scaled to fit with square pixels. */
function SensorImage({ b64, width, height, label }: { b64: string; width: number; height: number; label: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current
    if (!c) return
    const bin = atob(b64)
    const u8 = new Uint8Array(bin.length)
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i)
    const v = new Uint16Array(u8.buffer)
    const img = new ImageData(width, height)
    for (let i = 0; i < width * height; i++) {
      const g = v[i] >> 8 // linear signal, 8-bit display
      img.data[4 * i] = g
      img.data[4 * i + 1] = g
      img.data[4 * i + 2] = g
      img.data[4 * i + 3] = 255
    }
    c.width = width
    c.height = height
    c.getContext('2d')?.putImageData(img, 0, 0)
  }, [b64, width, height])
  return <canvas ref={ref} role="img" aria-label={label} className="block max-h-full max-w-full object-contain [image-rendering:pixelated]" style={{ aspectRatio: `${width} / ${height}` }} />
}

/** Image of a test scene through the system onto the sensor (engine: analysis/imaging.py). */
export function ImageSimulationView() {
  const t = useT()
  const sensor = useProjectStore((s) => s.project.system.sensor ?? null)
  const [st, set] = useAnalysisSettings('imagesim', SIM_DEFAULTS)
  const settings = { scene: st.scene, crop_px: st.crop_px, grid: st.grid, oversample: st.oversample, exposure: st.exposure, noise: st.noise, seed: st.seed }
  const { data, error, loading, ms, refresh } = useAnalysis<ImageSimResult>('imagesim', settings)
  // the image box appears with the first result: observe it through a callback ref
  const [w, setW] = useState(0)
  const observer = useRef<ResizeObserver | null>(null)
  const box = useCallback((el: HTMLDivElement | null) => {
    observer.current?.disconnect()
    observer.current = null
    if (!el) return
    setW(el.clientWidth)
    observer.current = new ResizeObserver(() => setW(el.clientWidth))
    observer.current.observe(el)
  }, [])
  const corner = useMemo(() => {
    if (!data) return null
    const rr = data.distortion.r_real_mm
    const ri = data.distortion.r_ideal_mm
    const k = rr.length - 1
    return k > 0 ? { dist: (rr[k] / ri[k] - 1) * 100, r: rr[k] } : null
  }, [data])
  const scenes = (['siemens', 'bars', 'grid', 'checker', 'edge'] as const).map((v) => ({ value: v, label: t(`sim.scene.${v}`) }))
  const shows = (['sensor', 'optics', 'ideal'] as const).map((v) => ({ value: v, label: t(`sim.show.${v}`) }))
  return (
    <AnalysisFrame
      kind="imagesim"
      title={t('view.imagesim')}
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
          <Select className="h-6 w-32 text-small" ariaLabel={t('sim.scene')} value={st.scene} options={scenes} onChange={(v) => set({ scene: v })} />
          <Select className="h-6 w-32 text-small" ariaLabel={t('sim.show')} value={st.show} options={shows} onChange={(v) => set({ show: v })} />
          <Checkbox checked={st.noise} ariaLabel={t('sim.noise')} onChange={(v) => set({ noise: v })} label={t('sim.noise')} />
        </>
      }
      more={
        <>
          <Row label={t('sim.crop')} hint={t('sim.cropHint')}>
            <NumberField className="h-6 w-20" ariaLabel={t('sim.crop')} value={st.crop_px} integer min={16} max={512} onCommit={(v) => set({ crop_px: v ?? 256 })} />
          </Row>
          <Row label={t('sim.grid')} hint={t('sim.gridHint')}>
            <NumberField className="h-6 w-20" ariaLabel={t('sim.grid')} value={st.grid} integer min={1} max={9} onCommit={(v) => set({ grid: v ?? 5 })} />
          </Row>
          <Row label={t('sim.oversample')} hint={t('sim.oversampleHint')}>
            <Select<number> className="h-6 w-20 text-small" ariaLabel={t('sim.oversample')} value={st.oversample} options={[1, 3, 5, 7].map((v) => ({ value: v, label: String(v) }))} onChange={(v) => set({ oversample: v })} />
          </Row>
          <Row label={t('sim.exposure')} hint={t('sim.exposureHint')}>
            <NumberField className="h-6 w-20" ariaLabel={t('sim.exposure')} value={st.exposure * 100} min={1} max={100} onCommit={(v) => set({ exposure: (v ?? 70) / 100 })} />
          </Row>
          <Row label={t('ns.seed')}>
            <NumberField className="h-6 w-20" ariaLabel={t('ns.seed')} value={st.seed} integer min={0} onCommit={(v) => set({ seed: v ?? 1 })} />
          </Row>
        </>
      }
    >
      {data && (
        <div className="flex h-full min-h-0 flex-col">
          <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
            <Stat label={t('sim.sensor')} value={`${data.width_px} × ${data.height_px}`} unit={`px · ${fmt(data.pixel_pitch_um, 4)} µm`} />
            <Stat label={t('sim.nyquist')} value={fmt(data.nyquist_cyc_per_mm, 4)} unit="cyc/mm" />
            {corner && <Stat label={t('sim.distortion')} value={`${fmt(corner.dist, 3)} %`} />}
            <Stat label={t('sim.ri')} value={`${fmt((data.relative_illumination.relative_illumination.at(-1) ?? 1) * 100, 4)} %`} />
          </div>
          {!sensor && <div className="shrink-0 border-b border-line px-3 py-1 text-small text-warn">{t('sim.noSensor')}</div>}
          {data.notes.filter((n) => !n.startsWith('No sensor')).map((n) => (
            <div key={n} className="shrink-0 px-3 py-1 text-small text-warn">
              {n}
            </div>
          ))}
          <div ref={box} className="flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-black p-2">
            {w > 0 && <SensorImage b64={data.images[st.show]} width={data.width_px} height={data.height_px} label={`${t(`sim.show.${st.show}`)}: ${t(`sim.scene.${st.scene}`)}`} />}
          </div>
          <div className="shrink-0 px-3 py-1 text-caption text-faint">{t('sim.displayNote')}</div>
        </div>
      )}
    </AnalysisFrame>
  )
}
