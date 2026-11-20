import { ImagePlus, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { canonicalJson } from '../../lib/canonical'
import { PITCHES, sensorZoom } from '../../lib/liveZoom'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { base64ToBytes, photoFromFile, rgbToRgba } from '../../lib/photo'
import { isSamplePhoto, SAMPLE_PHOTOS, type SamplePhotoId } from '../../lib/samplePhotos'
import type { LiveImageResult } from '../../lib/types'
import { usePhotoStore } from '../../store/photoStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { Checkbox, IconButton, Select, Tooltip, Badge, Button } from '../common/ui'
import { Row, Stat } from '../common/controls'
import { useAnalysisSettings } from '../common/useAnalysisSettings'
import { AnalysisFrame } from './AnalysisFrame'
import { useAnalysis } from './useAnalysis'

type Scene = 'siemens' | 'bars' | 'grid' | 'checker' | 'edge' | SamplePhotoId | 'photo'
const SCENES: Scene[] = ['siemens', 'bars', 'grid', 'checker', 'edge']
const SAMPLES = Object.keys(SAMPLE_PHOTOS) as SamplePhotoId[]
const ZOOMS = [1, 2, 4, 8, 16, 32]
const WIDTHS = [256, 384, 512, 640]
const PREVIEW_WIDTH = 192
const DEFAULTS = { scene: 'siemens' as Scene, zoom: 1, center: [0, 0] as [number, number], width: 384, refine: true, pitch: null as number | null }
const REGIONS: { id: 'centre' | 'edge' | 'corner'; c: [number, number] }[] = [
  { id: 'centre', c: [0, 0] },
  { id: 'edge', c: [1, 0] },
  { id: 'corner', c: [1, 1] },
]

/** An sRGB image (RGB bytes, rows from the top) on a canvas filling its box. */
function RgbCanvas({ b64, width, height, pixelated, label, className, style }: { b64: string; width: number; height: number; pixelated: boolean; label: string; className?: string; style?: React.CSSProperties }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current
    if (!c) return
    const rgb = base64ToBytes(b64)
    if (rgb.length !== width * height * 3) return
    c.width = width
    c.height = height
    c.getContext('2d')?.putImageData(new ImageData(rgbToRgba(rgb, width, height), width, height), 0, 0)
  }, [b64, width, height])
  return <canvas ref={ref} role="img" aria-label={label} className={className} style={{ ...style, imageRendering: pixelated ? 'pixelated' : 'auto' }} />
}

/** Live colour image through the lens with a before/after divider (engine: analysis/liveimage.py). */
export function LiveImageView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const custom = useProjectStore((s) => s.project.custom_materials)
  const [st, set] = useAnalysisSettings('liveimage', DEFAULTS)
  const photo = usePhotoStore((s) => s.photo)
  const photoId = usePhotoStore((s) => s.id)
  const photoName = usePhotoStore((s) => s.name)
  const toast = useUiStore((s) => s.toast)
  useEffect(() => void usePhotoStore.getState().load(), [])
  const noPhoto = st.scene === 'photo' && !photo
  const scene: Scene = noPhoto ? 'siemens' : st.scene
  const base = { scene, photo_id: scene === 'photo' ? photoId : null, zoom: st.zoom, center: st.center }
  const baseKey = canonicalJson(base)
  // a fast preview after every change, the full-quality image when the design rests
  const [quality, setQuality] = useState<'preview' | 'full'>('preview')
  useEffect(() => setQuality('preview'), [system, custom, baseKey, st.width])
  const settings = { ...base, quality, width: quality === 'preview' ? Math.min(PREVIEW_WIDTH, st.width) : st.width }
  const { data, error, loading, ms, refresh } = useAnalysis<LiveImageResult>('liveimage', settings)
  useEffect(() => {
    if (!st.refine || quality !== 'preview' || loading || !data || data.quality !== 'preview') return
    const h = window.setTimeout(() => setQuality('full'), 500)
    return () => window.clearTimeout(h)
  }, [data, quality, loading, st.refine])

  // the image box: the largest rectangle of the image's aspect in the pane
  const [box, setBox] = useState({ w: 0, h: 0 })
  const ro = useRef<ResizeObserver | null>(null)
  const area = useCallback((el: HTMLDivElement | null) => {
    ro.current?.disconnect()
    ro.current = null
    if (!el) return
    const measure = () => setBox({ w: el.clientWidth, h: el.clientHeight })
    measure()
    ro.current = new ResizeObserver(measure)
    ro.current.observe(el)
  }, [])
  const [split, setSplit] = useState(0.5)
  const [drag, setDrag] = useState<{ dx: number; dy: number } | null>(null)
  const file = useRef<HTMLInputElement>(null)

  const choosePhoto = async (f: File | undefined) => {
    if (!f) return
    try {
      const p = await photoFromFile(f)
      await usePhotoStore.getState().set(p, f.name)
      set({ scene: 'photo' })
    } catch (e) {
      toast('error', t('live.photoFailed', { e: (e as Error).message }))
    }
  }

  // "1 pixel = 1 sensor pixel": the zoom at which the image's pixels are the sensor's (the system's sensor model, or a
  // chosen pitch); kept when the resolution changes
  const sensorPitch = system.sensor?.pixel_pitch_um ?? null
  const pitches = sensorPitch !== null && !PITCHES.includes(sensorPitch) ? [sensorPitch, ...PITCHES] : PITCHES
  const frameW = data?.frame_mm?.[0] ?? null
  useEffect(() => {
    if (st.pitch === null || frameW === null) return
    const z = sensorZoom(frameW, st.width, st.pitch)
    if (Math.abs(z - st.zoom) > 1e-9) set({ zoom: z })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [st.pitch, st.width, frameW])
  const W = data?.width_px ?? 4
  const H = data?.height_px ?? 3
  const scale = box.w > 0 && box.h > 0 ? Math.min(box.w / W, box.h / H) : 0
  const dw = W * scale
  const dh = H * scale
  const pixelated = scale >= 1.5
  const region = REGIONS.find((r) => r.c[0] === st.center[0] && r.c[1] === st.center[1])?.id ?? 'custom'

  // pan the zoomed region by dragging the image (the divider has its own handle)
  const startPan = (e: React.MouseEvent) => {
    if (!data || st.zoom <= 1 || e.button !== 0) return
    e.preventDefault()
    const x0 = e.clientX
    const y0 = e.clientY
    const move = (ev: MouseEvent) => setDrag({ dx: ev.clientX - x0, dy: ev.clientY - y0 })
    const up = (ev: MouseEvent) => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
      setDrag(null)
      const dx = ev.clientX - x0
      const dy = ev.clientY - y0
      if (Math.hypot(dx, dy) < 3 || dw <= 0) return
      const [fw, fh] = data.frame_mm
      const [rw, rh] = data.region_mm.size
      const mmPerPx = rw / dw
      const cx = fw > rw ? st.center[0] - (dx * mmPerPx) / ((fw - rw) / 2) : 0
      const cy = fh > rh ? st.center[1] + (dy * mmPerPx) / ((fh - rh) / 2) : 0
      const clamp = (v: number) => Math.round(Math.min(1, Math.max(-1, v)) * 1000) / 1000
      set({ center: [clamp(cx), clamp(cy)] })
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }
  const startSplit = (e: React.PointerEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const el = (e.currentTarget as HTMLElement).parentElement
    if (!el) return
    const r = el.getBoundingClientRect()
    const move = (ev: PointerEvent) => setSplit(Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)))
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const sceneOptions = [
    ...SCENES.map((v) => ({ value: v, label: t(`sim.scene.${v}`) })),
    ...SAMPLES.map((v) => ({ value: v as Scene, label: t(`live.scene.${v}`) })),
    ...(photo ? [{ value: 'photo' as Scene, label: t('live.scene.photo') }] : []),
  ]
  const nm = (v: number) => fmt(v * 1000, 4)
  const corner = data?.corner
  return (
    <>
      {/* outside the settings bar, which unmounts its controls when it folds into a popover */}
      <input ref={file} type="file" accept="image/*" className="hidden" aria-label={t('live.usePhoto')} onChange={(e) => void choosePhoto(e.target.files?.[0]).finally(() => (e.target.value = ''))} />
      <AnalysisFrame
        kind="liveimage"
        title={t('view.liveimage')}
        loading={loading}
        error={error}
        hasData={!!data}
        ms={ms}
        method={data?.method}
        onRefresh={refresh}
        settings={settings}
        result={data ? { ...data, images: undefined } : null}
        controls={
          <>
            <Select<Scene> className="h-6 w-32 text-small" ariaLabel={t('live.scene')} value={scene} options={sceneOptions} onChange={(v) => set({ scene: v })} />
            <Select<number>
              className="h-6 w-24 text-small"
              ariaLabel={t('live.zoom')}
              value={st.zoom}
              options={[...ZOOMS.map((z) => ({ value: z, label: z === 1 ? t('live.fit') : `${z}×` })), ...(ZOOMS.includes(st.zoom) ? [] : [{ value: st.zoom, label: `${fmt(st.zoom, 3)}×` }])]}
              onChange={(v) => set({ zoom: v, pitch: null })}
            />
            <Select<number>
              className="h-6 w-32 text-small"
              ariaLabel={t('live.sensorPixel')}
              title={t('live.sensorPixelHint')}
              value={st.pitch ?? 0}
              options={[{ value: 0, label: t('live.sensorPixelOff') }, ...pitches.map((p) => ({ value: p, label: `${t('live.sensorPixelOn', { p: fmt(p, 3) })}${p === sensorPitch ? ' ★' : ''}` }))]}
              onChange={(v) => set(v ? { pitch: v } : { pitch: null, zoom: 1, center: [0, 0] })}
            />
            {st.zoom > 1 && (
              <Select<string>
                className="h-6 w-28 text-small"
                ariaLabel={t('live.region')}
                value={region}
                options={[...REGIONS.map((r) => ({ value: r.id, label: t(`live.region.${r.id}`) })), ...(region === 'custom' ? [{ value: 'custom', label: t('live.region.custom') }] : [])]}
                onChange={(v) => {
                  const r = REGIONS.find((x) => x.id === v)
                  if (r) set({ center: r.c })
                }}
              />
            )}
            <Tooltip text={t('live.usePhotoHint')}>
              <Button size="sm" onClick={() => file.current?.click()}>
                <ImagePlus size={12} /> {t('live.usePhoto')}
              </Button>
            </Tooltip>
          </>
        }
        more={
          <>
            <Row label={t('live.resolution')} hint={t('live.resolutionHint')}>
              <Select<number> className="h-6 w-20 text-small" ariaLabel={t('live.resolution')} value={st.width} options={WIDTHS.map((w) => ({ value: w, label: String(w) }))} onChange={(v) => set({ width: v })} />
            </Row>
            <Row label={t('live.refine')} hint={t('live.refineHint')}>
              <Checkbox checked={st.refine} ariaLabel={t('live.refine')} onChange={(v) => set({ refine: v })} />
            </Row>
            {photo && (
              <Row label={t('live.photo')} hint={photoName ?? undefined}>
                <span className="flex items-center gap-1">
                  <span className="max-w-32 truncate text-small text-muted">{photoName}</span>
                  <IconButton size="sm" tone="danger" title={t('live.removePhoto')} onClick={() => void usePhotoStore.getState().clear()}>
                    <Trash2 size={12} />
                  </IconButton>
                </span>
              </Row>
            )}
          </>
        }
      >
        {data && (
          <div className="flex h-full min-h-0 flex-col">
            <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
              <Stat label={t('live.pixel')} value={fmt(data.pixel_um, 3)} unit="µm" />
              <Stat label={t('live.channels')} value={data.channels_um.map(nm).join(' · ')} unit="nm" />
              {corner && corner.lateral_colour_um !== null && <Stat label={t('live.latColour')} value={fmt(corner.lateral_colour_um, 3)} unit={`µm · ${fmt(corner.lateral_colour_px, 2)} px`} />}
              {corner && <Stat label={t('live.distortion')} value={`${fmt(corner.distortion_percent, 3)} %`} />}
              {corner && <Stat label={t('live.ri')} value={`${fmt(corner.relative_illumination * 100, 3)} %`} />}
              <div className="flex items-center px-3">
                <Badge tone={data.quality === 'full' ? 'ok' : 'default'}>{t(data.quality === 'full' ? 'live.full' : 'live.preview')}</Badge>
              </div>
            </div>
            {noPhoto && <div className="shrink-0 border-b border-line px-3 py-1 text-small text-warn">{t('live.noPhoto')}</div>}
            {data.notes.map((n) => (
              <div key={n} className="shrink-0 px-3 py-1 text-small text-warn">
                {n}
              </div>
            ))}
            <div ref={area} className="relative min-h-0 flex-1 overflow-hidden bg-black">
              {scale > 0 && (
                <div
                  className={st.zoom > 1 ? 'absolute cursor-grab active:cursor-grabbing' : 'absolute'}
                  style={{ width: dw, height: dh, left: (box.w - dw) / 2, top: (box.h - dh) / 2, transform: drag ? `translate(${drag.dx}px, ${drag.dy}px)` : undefined }}
                  onMouseDown={startPan}
                  onDoubleClick={() => st.zoom > 1 && set({ center: [0, 0] })}
                  title={st.zoom > 1 ? t('live.panHint') : undefined}
                >
                  <RgbCanvas b64={data.images.lens} width={W} height={H} pixelated={pixelated} label={t('live.lens')} className="absolute inset-0 h-full w-full" />
                  <RgbCanvas b64={data.images.ideal} width={W} height={H} pixelated={pixelated} label={t('live.ideal')} className="absolute inset-0 h-full w-full" style={{ clipPath: `inset(0 ${(1 - split) * 100}% 0 0)` }} />
                  <span className="pointer-events-none absolute top-1 left-1 rounded bg-black/60 px-1.5 text-caption text-white">{t('live.ideal')}</span>
                  <span className="pointer-events-none absolute top-1 right-1 rounded bg-black/60 px-1.5 text-caption text-white">{t('live.lens')}</span>
                  <div
                    role="slider"
                    tabIndex={0}
                    aria-label={t('live.split')}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.round(split * 100)}
                    className="absolute top-0 bottom-0 w-4 -translate-x-1/2 cursor-ew-resize focus-visible:outline-none"
                    style={{ left: `${split * 100}%` }}
                    onPointerDown={startSplit}
                    onMouseDown={(e) => e.stopPropagation()}
                    onKeyDown={(e) => {
                      if (e.key === 'ArrowLeft') setSplit((v) => Math.max(0, v - 0.05))
                      else if (e.key === 'ArrowRight') setSplit((v) => Math.min(1, v + 0.05))
                    }}
                  >
                    <div className="mx-auto h-full w-0.5 bg-white/80 shadow" />
                    <div className="absolute top-1/2 left-1/2 h-6 w-3 -translate-x-1/2 -translate-y-1/2 rounded border border-black/40 bg-white/90" />
                  </div>
                </div>
              )}
            </div>
            {isSamplePhoto(scene) && <div className="shrink-0 px-3 pt-1 text-caption text-muted">{t('live.credit', { c: SAMPLE_PHOTOS[scene].credit })}</div>}
            <div className="shrink-0 px-3 py-1 text-caption text-faint">{t('live.scrubTip')}</div>
          </div>
        )}
      </AnalysisFrame>
    </>
  )
}
