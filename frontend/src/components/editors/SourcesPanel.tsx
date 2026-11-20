import { Copy, ExternalLink, Plus, Radio, ScanLine, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { Label } from '../common/controls'
import { LightLine } from '../common/LightReadout'
import { defaultDetector, defaultSource, newId } from '../../lib/project'
import type { DetectorSpec, LightSource, Placement, Project, SourceAngular, SourcePose, SourceShape, SpectrumRequest } from '../../lib/types'
import { LENGTH_TO_MM } from '../../lib/units'
import { framePoint, localDirection, reanchor, resolvePlacement, surfaceFrames, toFrame } from '../../lib/placement'
import { api } from '../../lib/api'
import { useEngineStore } from '../../store/engineStore'
import { selectDetectors, selectSources, useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { Badge, Button, Checkbox, IconButton, NumberField, Select, Spinner, TextField } from '../common/ui'
import { cx } from '../common/uiUtils'
import { useNonSeqSettings } from '../views/nonseqSettings'
import { useAnalysis } from '../views/useAnalysis'
import type { NonSeqResult } from '../../lib/types'
import { type DirMode, r9, withDirection } from './placementDirection'
import { detectorSummary, sourceSummary } from './sourceSummary'

type Sel = { kind: 'source' | 'detector'; id: string } | null

const DEG = Math.PI / 180

/** Editor of the project's non-sequential light sources and detectors (general building blocks). */
export function SourcesPanel() {
  const t = useT()
  const sources = useProjectStore(selectSources)
  const detectors = useProjectStore(selectDetectors)
  const update = useProjectStore((s) => s.updateProject)
  const [sel, setSel] = useState<Sel>(null)
  const cur = sel?.kind === 'source' ? sources.find((s) => s.id === sel.id) : sel?.kind === 'detector' ? detectors.find((d) => d.id === sel.id) : undefined

  const edit = (label: string, fn: (p: Project) => void) =>
    update((p) => {
      p.sources = p.sources ?? []
      p.detectors = p.detectors ?? []
      fn(p)
    }, label)
  const addSource = () => {
    const s = defaultSource({ name: `Source ${sources.length + 1}` })
    edit('Add source', (p) => void p.sources!.push(s))
    setSel({ kind: 'source', id: s.id })
  }
  const addDetector = () => {
    const d = defaultDetector({ name: `Detector ${detectors.length + 1}`, placement: { position: [0, 0, 10], rotation_deg: [0, 0, 0] } })
    edit('Add detector', (p) => void p.detectors!.push(d))
    setSel({ kind: 'detector', id: d.id })
  }

  const Row = ({ kind, item, summary }: { kind: 'source' | 'detector'; item: LightSource | DetectorSpec; summary: string }) => (
    <div className={cx('group flex cursor-pointer items-center gap-1.5 rounded px-1.5 py-1 hover:bg-hover', sel?.id === item.id && 'bg-accent-soft')} onClick={() => setSel({ kind, id: item.id })}>
      <input
        type="checkbox"
        className="accent-[var(--c-accent)]"
        checked={item.enabled}
        title={t('src.enabled')}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => edit(`${e.target.checked ? 'Enable' : 'Disable'} ${item.name}`, (p) => void ((kind === 'source' ? p.sources! : p.detectors!).find((x) => x.id === item.id)!.enabled = e.target.checked))}
      />
      <div className="min-w-0 flex-1">
        <div className={cx('truncate text-body font-medium', !item.enabled && 'text-faint')}>{item.name}</div>
        <div className="truncate text-caption text-faint">{summary}</div>
      </div>
      <IconButton
        size="sm"
        title={t('src.duplicate')}
        className="invisible group-hover:visible"
        onClick={(e) => {
          e.stopPropagation()
          const copy = { ...structuredClone(item), id: newId(), name: `${item.name} copy` }
          edit(`Duplicate ${item.name}`, (p) => void (kind === 'source' ? p.sources!.push(copy as LightSource) : p.detectors!.push(copy as DetectorSpec)))
          setSel({ kind, id: copy.id })
        }}
      >
        <Copy size={12} />
      </IconButton>
      <IconButton
        size="sm"
        tone="danger"
        title={t('src.delete')}
        className="invisible group-hover:visible"
        onClick={(e) => {
          e.stopPropagation()
          edit(`Delete ${item.name}`, (p) => {
            if (kind === 'source') p.sources = p.sources!.filter((x) => x.id !== item.id)
            else {
              p.detectors = p.detectors!.filter((x) => x.id !== item.id)
              // operands measured on it have nothing to measure: disabled (their set-up is kept for undo or reuse)
              for (const o of p.optimization.operands) if (o.detector_id === item.id) o.enabled = false
            }
          })
          if (sel?.id === item.id) setSel(null)
        }}
      >
        <Trash2 size={12} />
      </IconButton>
    </div>
  )

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(260px,320px)_1fr] gap-px bg-line">
      <div className="flex min-h-0 flex-col overflow-auto bg-panel p-2">
        {(sources.length > 0 || detectors.length > 0) && <LiveResult />}
        <div className="mb-1 flex items-center gap-1.5 text-small font-semibold tracking-wide text-muted uppercase">
          <Radio size={12} /> {t('src.sources')} ({sources.length})<span className="flex-1" />
          <Button size="sm" onClick={addSource}>
            <Plus size={12} /> {t('src.add')}
          </Button>
        </div>
        {sources.length === 0 && <div className="px-1.5 pb-2 text-small leading-relaxed text-faint">{t('src.none')}</div>}
        {sources.map((s) => (
          <Row key={s.id} kind="source" item={s} summary={sourceSummary(s)} />
        ))}
        <div className="mt-3 mb-1 flex items-center gap-1.5 text-small font-semibold tracking-wide text-muted uppercase">
          <ScanLine size={12} /> {t('src.detectors')} ({detectors.length})<span className="flex-1" />
          <Button size="sm" onClick={addDetector}>
            <Plus size={12} /> {t('src.add')}
          </Button>
        </div>
        {detectors.length === 0 && <div className="px-1.5 pb-2 text-small leading-relaxed text-faint">{t('det.none')}</div>}
        {detectors.map((d) => (
          <Row key={d.id} kind="detector" item={d} summary={detectorSummary(d)} />
        ))}
        <div className="mt-auto pt-3 text-caption leading-relaxed text-faint">{t('src.help')}</div>
      </div>
      <div className="min-h-0 overflow-auto bg-panel">
        {!cur ? (
          <div className="flex h-full items-center justify-center p-6 text-center text-body text-muted">{t('src.pick')}</div>
        ) : sel?.kind === 'source' ? (
          <SourceForm s={cur as LightSource} set={(label, patch) => edit(label, (p) => void Object.assign(p.sources!.find((x) => x.id === cur.id)!, patch))} />
        ) : (
          <DetectorForm d={cur as DetectorSpec} set={(label, patch) => edit(label, (p) => void Object.assign(p.detectors!.find((x) => x.id === cur.id)!, patch))} />
        )}
      </div>
    </div>
  )
}

/** Detector powers of the current design, recomputed live (the same cached analysis as the
 * Non-Sequential view), so changing a source or detector shows its effect right here. */
function LiveResult() {
  const t = useT()
  const { settings } = useNonSeqSettings()
  const { data, error, loading } = useAnalysis<NonSeqResult>('nonseq', settings)
  const dets = data?.detectors ?? []
  return (
    <div className="mb-2 rounded-md border border-line bg-panel-2 p-2 text-small">
      <div className="mb-1 flex items-center gap-1.5 text-caption font-semibold tracking-wide text-muted uppercase">
        {t('src.result')}
        {loading && (
          <span className="flex items-center gap-1 font-normal normal-case text-accent">
            <Spinner size={12} /> {t('src.computing')}
          </span>
        )}
        <span className="flex-1" />
        <Button variant="link" onClick={() => useUiStore.getState().showView('nonseq')} title={t('src.openViewHint')}>
          <ExternalLink size={12} /> {t('src.openView')}
        </Button>
      </div>
      {error && <div className="text-danger">{error}</div>}
      {!error && dets.length === 0 && !loading && <div className="text-faint">{t('src.noDetResult')}</div>}
      <div className={cx(loading && 'opacity-50')}>
        {dets.map((d) => (
          <div key={d.id} className="flex items-baseline gap-2">
            <span className="min-w-0 flex-1 truncate">{d.name}</span>
            <b className="num">{fmt(d.fraction * 100, 4)} %</b>
            <span className="num text-faint">{fmt(d.power_w, 4)} W</span>
          </div>
        ))}
        {data && <div className="mt-0.5 text-caption text-faint">{t('src.resultNote', { rays: data.source.rays, s: data.elapsed_s.toFixed(1) })}</div>}
      </div>
    </div>
  )
}

function Grid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-[150px_1fr] items-center gap-x-3 gap-y-1.5 px-3 py-2 text-body">{children}</div>
}

function Head({ children }: { children: React.ReactNode }) {
  return <div className="col-span-2 mt-2 border-b border-line pb-0.5 text-caption font-semibold tracking-wide text-muted uppercase first:mt-0">{children}</div>
}

function Vec3({ value, onCommit, units, label }: { value: [number, number, number]; onCommit: (v: [number, number, number]) => void; units?: Record<string, number>; label: string }) {
  return (
    <div className="flex gap-1">
      {(['x', 'y', 'z'] as const).map((ax, k) => (
        <NumberField
          key={ax}
          className="h-6 w-24"
          value={value[k]}
          units={units}
          ariaLabel={`${label} ${ax}`}
          onCommit={(v) => {
            const n = [...value] as [number, number, number]
            n[k] = v ?? 0
            onCommit(n)
          }}
        />
      ))}
    </div>
  )
}

/** Half-angle (degrees) with the equivalent numerical aperture in air, NA = sin(theta). */
function AngleNa({ deg, onCommit, max = 90, label }: { deg: number; onCommit: (deg: number) => void; max?: number; label: string }) {
  const t = useT()
  return (
    <div className="flex items-center gap-1.5">
      <NumberField className="h-6 w-20" value={deg} min={1e-6} max={max} ariaLabel={label} onCommit={(v) => v !== null && onCommit(Math.min(max, Math.max(1e-6, v)))} />
      <span className="text-muted">°</span>
      <span className="ml-2 text-faint">{t('src.naAir')}</span>
      <NumberField className="h-6 w-20" value={Math.sin(deg * DEG)} format={(v) => (v === null ? '' : fmt(v, 5))} min={1e-9} max={1} ariaLabel={`${label} NA`} onCommit={(v) => v !== null && v > 0 && v <= 1 && onCommit(Math.asin(v) / DEG)} />
    </div>
  )
}

function PlacementRows({ p, set, receiver }: { p: Placement; set: (label: string, p: Placement) => void; receiver?: boolean }) {
  const t = useT()
  const surfaces = useProjectStore((s) => s.project.system.surfaces)
  const ev = useEngineStore((s) => s.evaluation)
  const frames = ev ? surfaceFrames(ev.surfaces) : undefined
  const n = surfaces.length
  const anchor = p.anchor && surfaces.some((s) => s.id === p.anchor) ? p.anchor : ''
  const [chosen, setChosen] = useState<DirMode>('angles')
  const mode: DirMode = p.aim ? 'aim' : chosen === 'aim' ? 'angles' : chosen
  const dLocal = localDirection(p)
  const R = resolvePlacement(p, frames).R
  const dGlobal: [number, number, number] = [R[0][2], R[1][2], R[2][2]]
  const axisAngle = (Math.acos(Math.max(-1, Math.min(1, dGlobal[2]))) * 180) / Math.PI
  const surfaceLabel = (i: number, lbl: string) => `${i === 0 ? 'OBJ' : i === n - 1 ? 'IMG' : i}${lbl ? ` · ${lbl}` : ''}`
  return (
    <>
      <Label form hint={t('src.anchorHint')}>{t('src.anchor')}</Label>
      <Select
        className="h-6 w-56"
        ariaLabel={t('src.anchor')}
        value={anchor}
        options={[{ value: '', label: t('src.anchorGlobal') }, ...surfaces.map((s, i) => ({ value: s.id, label: surfaceLabel(i, s.label) }))]}
        onChange={(v) => set('Placement reference', reanchor(p, v || null, frames))}
      />
      <Label form hint={t('src.positionHint')}>{t('src.position')} (mm)</Label>
      <Vec3 value={p.position} units={LENGTH_TO_MM} label="position" onCommit={(v) => set('Position', { ...p, position: v })} />
      <Label form hint={t('src.directionHint')}>{t('src.direction')}</Label>
      <Select<DirMode>
        className="h-6 w-56"
        ariaLabel={t('src.directionMode')}
        value={mode}
        options={[
          { value: 'angles', label: t('src.dir.angles') },
          { value: 'vector', label: t('src.dir.vector') },
          { value: 'aim', label: t('src.dir.aim') },
        ]}
        onChange={(v) => {
          setChosen(v)
          if (v === 'aim' && !p.aim) set('Aim at a point', withDirection(p, 'aim'))
          else if (v !== 'aim' && p.aim) set('Direction by angles', withDirection(p, 'angles'))
        }}
      />
      {mode === 'angles' && (
        <>
          <Label form hint={t('src.rotationHint')}>{t('src.rotation')} (°)</Label>
          <Vec3 value={p.rotation_deg} label="rotation" onCommit={(v) => set('Rotation', { ...p, rotation_deg: v })} />
        </>
      )}
      {mode === 'vector' && (
        <>
          <Label form hint={t('src.vectorHint')}>{t('src.vector')}</Label>
          <Vec3 value={dLocal.map((x) => Math.round(x * 1e6) / 1e6 + 0) as [number, number, number]} label="direction" onCommit={(v) => set('Direction', withDirection(p, 'vector', v))} />
        </>
      )}
      {mode === 'aim' && p.aim && (
        <>
          <Label form hint={t(receiver ? 'src.aimHintDetector' : 'src.aimHint')}>{t('src.aimPoint')} (mm)</Label>
          <Vec3 value={p.aim} units={LENGTH_TO_MM} label="aim" onCommit={(v) => set('Aim point', { ...p, aim: v })} />
          <Label form hint={t('src.aimAtHint')}>{t('src.aimAt')}</Label>
          <Select
            className="h-6 w-56"
            ariaLabel={t('src.aimAt')}
            value=""
            options={[{ value: '', label: t('src.aimAtPick') }, ...surfaces.map((s, i) => ({ value: s.id, label: surfaceLabel(i, s.label) }))]}
            onChange={(sid) => {
              const f = frames?.get(sid)
              if (f) set('Aim at a surface', { ...p, aim: toFrame(p, f.origin, frames).map(r9) as [number, number, number] })
            }}
          />
          <Label form hint={t('src.rollHint')}>{t('src.roll')} (°)</Label>
          <NumberField className="h-6 w-24" value={p.rotation_deg[2]} ariaLabel={t('src.roll')} onCommit={(v) => set('Roll', { ...p, rotation_deg: [p.rotation_deg[0], p.rotation_deg[1], v ?? 0] })} />
        </>
      )}
      <span />
      <div className="text-small text-muted" title={t('src.pointsHint')}>
        {t(receiver ? 'src.receives' : 'src.points', { x: fmt(dGlobal[0], 4), y: fmt(dGlobal[1], 4), z: fmt(dGlobal[2], 4), a: fmt(axisAngle, 4) })}
        {p.aim && frames && (() => {
          const g = framePoint(p, p.aim, frames)
          const c = resolvePlacement(p, frames).t
          return ` · ${t('src.aimDistance', { d: fmt(Math.hypot(g[0] - c[0], g[1] - c[1], g[2] - c[2]), 5) })}`
        })()}
      </div>
    </>
  )
}

/** The engine's description of a source: where it points and, for a Gaussian beam, its beam parameters. */
function useSourcePose(src: LightSource): SourcePose | null {
  const system = useProjectStore((st) => st.project.system)
  const custom = useProjectStore((st) => st.project.custom_materials)
  const [pose, setPose] = useState<SourcePose | null>(null)
  const key = JSON.stringify(src) + JSON.stringify(system.surfaces.map((x) => [x.id, x.thickness, x.radius, x.decenter_x, x.decenter_y, x.tilt_x, x.tilt_y, x.tilt_z])) + JSON.stringify(system.wavelengths)
  useEffect(() => {
    const ctrl = new AbortController()
    const h = setTimeout(() => {
      api
        .sourcesDescribe({ system, custom_materials: custom, sources: [src], detectors: [] }, ctrl.signal)
        .then((r) => setPose(r.sources[0] ?? null))
        .catch(() => undefined)
    }, 200)
    return () => {
      clearTimeout(h)
      ctrl.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return pose
}

/** Fill the source's wavelengths from a spectrum computed by the engine (blackbody, Gaussian line, flat band). */
function SpectrumGenerator({ onSpectrum }: { onSpectrum: (w: { value: number; weight: number }[], label: string) => void }) {
  const t = useT()
  const [req, setReq] = useState<SpectrumRequest>({ kind: 'blackbody', temperature_k: 3000, center_um: 0.55, fwhm_um: 0.03, lambda_min_um: 0.4, lambda_max_um: 0.7, samples: 9 })
  const [err, setErr] = useState<string | null>(null)
  const run = async () => {
    setErr(null)
    try {
      const body: SpectrumRequest = req.kind === 'gaussian' ? { kind: 'gaussian', center_um: req.center_um, fwhm_um: req.fwhm_um, samples: req.samples } : req
      const r = await api.sourcesSpectrum(body)
      onSpectrum(r.wavelengths, `Source spectrum: ${req.kind}`)
    } catch (e) {
      setErr((e as Error).message)
    }
  }
  const nm = (v: number | null | undefined) => (v == null ? null : v * 1000)
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Select<SpectrumRequest['kind']>
        className="h-6 w-36"
        ariaLabel={t('src.spectrumKind')}
        value={req.kind}
        options={[
          { value: 'blackbody', label: t('src.spec.blackbody') },
          { value: 'gaussian', label: t('src.spec.gaussian') },
          { value: 'flat', label: t('src.spec.flat') },
        ]}
        onChange={(v) => setReq({ ...req, kind: v })}
      />
      {req.kind === 'blackbody' && (
        <>
          <span className="text-muted">T (K)</span>
          <NumberField className="h-6 w-20" ariaLabel="T (K)" value={req.temperature_k ?? 3000} min={1} onCommit={(v) => v && setReq({ ...req, temperature_k: v })} />
        </>
      )}
      {req.kind === 'gaussian' ? (
        <>
          <span className="text-muted">{t('src.spec.center')} (nm)</span>
          <NumberField className="h-6 w-20" ariaLabel={t('src.spec.center')} value={nm(req.center_um)} min={1} onCommit={(v) => v && setReq({ ...req, center_um: v / 1000 })} />
          <span className="text-muted">FWHM (nm)</span>
          <NumberField className="h-6 w-16" ariaLabel="FWHM" value={nm(req.fwhm_um)} min={0.001} onCommit={(v) => v && setReq({ ...req, fwhm_um: v / 1000 })} />
        </>
      ) : (
        <>
          <span className="text-muted">{t('src.spec.band')} (nm)</span>
          <NumberField className="h-6 w-16" ariaLabel={t('src.spec.bandMin')} value={nm(req.lambda_min_um)} min={1} onCommit={(v) => v && setReq({ ...req, lambda_min_um: v / 1000 })} />
          <NumberField className="h-6 w-16" ariaLabel={t('src.spec.bandMax')} value={nm(req.lambda_max_um)} min={1} onCommit={(v) => v && setReq({ ...req, lambda_max_um: v / 1000 })} />
        </>
      )}
      <span className="text-muted">{t('src.spec.samples')}</span>
      <NumberField className="h-6 w-14" ariaLabel={t('src.spec.samples')} integer value={req.samples} min={1} max={64} onCommit={(v) => v && setReq({ ...req, samples: Math.round(v) })} />
      <Button size="sm" onClick={() => void run()} title={t('src.spec.generateHint')}>
        {t('src.spec.generate')}
      </Button>
      {err && <span className="text-small text-danger">{err}</span>}
    </div>
  )
}

function parseRows(text: string, cols: number): number[][] | null {
  const rows = text
    .split(/\n/)
    .map((l) => l.split(/[,;\s]+/).filter(Boolean).map(Number))
    .filter((r) => r.length > 0)
  if (rows.some((r) => r.length < cols || r.slice(0, cols).some((v) => !Number.isFinite(v)))) return null
  return rows.map((r) => r.slice(0, cols))
}

function RowsField({ value, cols, placeholder, onCommit, invalidMsg }: { value: number[][]; cols: number; placeholder: string; onCommit: (rows: number[][]) => void; invalidMsg: string }) {
  const [text, setText] = useState<string | null>(null)
  const shown = text ?? value.map((r) => r.join('  ')).join('\n')
  const bad = text !== null && parseRows(text, cols) === null
  return (
    <div>
      <textarea
        className={cx('field-input num h-24 w-full py-1 text-small', bad && 'invalid')}
        value={shown}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.stopPropagation()}
        onBlur={() => {
          if (text === null) return
          const r = parseRows(text, cols)
          if (r) onCommit(r)
          setText(null)
        }}
      />
      {bad && <div className="text-small text-danger">{invalidMsg}</div>}
    </div>
  )
}

function SourceForm({ s, set }: { s: LightSource; set: (label: string, patch: Partial<LightSource>) => void }) {
  const t = useT()
  const system = useProjectStore((st) => st.project.system)
  const toast = useUiStore((st) => st.toast)
  const shapes: SourceShape[] = ['point', 'disk', 'rectangle', 'sphere', 'box']
  const angulars: SourceAngular[] = ['collimated', 'isotropic', 'lambertian', 'cosine_power', 'cone', 'gaussian', 'table']
  const truncates = s.angular === 'lambertian' || s.angular === 'cosine_power' || s.angular === 'gaussian'
  const lam0 = s.wavelengths[0]?.value ?? system.wavelengths[system.primary_wavelength]?.value ?? 0.55
  return (
    <Grid>
      <Head>{t('src.source')}</Head>
      <Label form>{t('src.name')}</Label>
      <TextField value={s.name} onCommit={(v) => set('Source name', { name: v || 'Source' })} />
      <Label form hint={t('src.kindHint')}>{t('src.kind')}</Label>
      <Select
        value={s.kind}
        options={[
          { value: 'emitter', label: t('src.kind.emitter') },
          { value: 'gaussian_beam', label: t('src.kind.gaussian_beam') },
          { value: 'system_field', label: t('src.kind.system_field') },
        ]}
        onChange={(v) => set('Source kind', { kind: v })}
      />
      <Label form hint={t('src.powerHint')}>{t('src.power')} (W)</Label>
      <NumberField className="h-6 w-28" value={s.power_w} min={1e-12} onCommit={(v) => v !== null && v > 0 && set('Source power', { power_w: v })} />
      <Label form hint={t('src.raysHint')}>{t('src.rays')}</Label>
      <NumberField className="h-6 w-28" value={s.rays} integer min={1} max={200000} onCommit={(v) => v !== null && set('Source rays', { rays: Math.max(1, Math.round(v)) })} />
      {s.kind === 'system_field' ? (
        <>
          <Label form>{t('src.field')}</Label>
          <Select value={Math.min(s.field, system.fields.length - 1)} options={system.fields.map((f, i) => ({ value: i, label: `F${i + 1} (${fmt(f.x, 4)}, ${fmt(f.y, 4)})` }))} onChange={(v) => set('Source field', { field: v })} />
          <Label form hint={t('ns.overfillHint')}>{t('ns.overfill')}</Label>
          <NumberField className="h-6 w-28" value={s.overfill} min={0.05} max={10} onCommit={(v) => v !== null && set('Source overfill', { overfill: v })} />
        </>
      ) : s.kind === 'gaussian_beam' ? (
        <>
          <Head>{t('src.placement')}</Head>
          <PlacementRows p={s.placement} set={(label, p) => set(`Source ${label.toLowerCase()}`, { placement: p })} />
          <GaussianBeamRows s={s} set={set} />
          <SpectrumRows s={s} set={set} />
        </>
      ) : (
        <>
          <Head>{t('src.placement')}</Head>
          <PlacementRows p={s.placement} set={(label, p) => set(`Source ${label.toLowerCase()}`, { placement: p })} />
          <Head>{t('src.emitter')}</Head>
          <Label form hint={t('src.shapeHint')}>{t('src.shape')}</Label>
          <Select value={s.shape} options={shapes.map((v) => ({ value: v, label: t(`src.shape.${v}`) }))} onChange={(v) => set('Source shape', { shape: v })} />
          {s.shape !== 'point' && (
            <>
              <Label form>{s.shape === 'disk' || s.shape === 'sphere' ? `${t('src.radius')} (mm)` : `${t('src.sizeX')} (mm)`}</Label>
              <NumberField className="h-6 w-28" value={s.size_x} min={1e-9} units={LENGTH_TO_MM} onCommit={(v) => v !== null && v > 0 && set('Source size', { size_x: v })} />
            </>
          )}
          {(s.shape === 'rectangle' || s.shape === 'box') && (
            <>
              <Label form>{t('src.sizeY')} (mm)</Label>
              <NumberField className="h-6 w-28" value={s.size_y} min={1e-9} units={LENGTH_TO_MM} onCommit={(v) => v !== null && v > 0 && set('Source size', { size_y: v })} />
            </>
          )}
          {s.shape === 'box' && (
            <>
              <Label form>{t('src.sizeZ')} (mm)</Label>
              <NumberField className="h-6 w-28" value={s.size_z} min={1e-9} units={LENGTH_TO_MM} onCommit={(v) => v !== null && v > 0 && set('Source size', { size_z: v })} />
            </>
          )}
          {(s.shape === 'disk' || s.shape === 'rectangle') && (
            <>
              <Label form hint={t('src.spatialHint')}>{t('src.spatial')}</Label>
              <Select value={s.spatial} options={[{ value: 'uniform', label: t('src.uniform') }, { value: 'gaussian', label: t('src.gaussian') }]} onChange={(v) => set('Source profile', { spatial: v })} />
              {s.spatial === 'gaussian' && (
                <>
                  <Label form hint={t('src.waistHint')}>{t('src.waist')} x / y (mm)</Label>
                  <div className="flex gap-1">
                    <NumberField className="h-6 w-24" value={s.gaussian_wx} min={1e-9} units={LENGTH_TO_MM} onCommit={(v) => v !== null && v > 0 && set('Source waist', { gaussian_wx: v })} />
                    <NumberField className="h-6 w-24" value={s.gaussian_wy} min={1e-9} units={LENGTH_TO_MM} onCommit={(v) => v !== null && v > 0 && set('Source waist', { gaussian_wy: v })} />
                  </div>
                </>
              )}
            </>
          )}
          <Head>{t('src.angularHead')}</Head>
          <Label form hint={t('src.angularHint')}>{t('src.angular')}</Label>
          <Select value={s.angular} options={angulars.map((v) => ({ value: v, label: t(`src.ang.${v}`) }))} onChange={(v) => set('Source angular law', { angular: v, ...(v === 'table' && s.table.length < 2 ? { table: [[0, 1], [90, 0]] } : {}) })} />
          {s.angular === 'cosine_power' && (
            <>
              <Label form>{t('src.cosPower')} n</Label>
              <NumberField className="h-6 w-28" value={s.cos_power} min={0} max={10000} onCommit={(v) => v !== null && set('Source cos power', { cos_power: Math.max(0, v) })} />
            </>
          )}
          {s.angular === 'gaussian' && (
            <>
              <Label form hint={t('src.divHint')}>{t('src.divergence')} x / y (°)</Label>
              <div className="flex items-center gap-1">
                <NumberField className="h-6 w-24" value={s.gaussian_x_deg} min={1e-9} max={89.9} onCommit={(v) => v !== null && v > 0 && set('Source divergence', { gaussian_x_deg: Math.min(89.9, v) })} />
                <NumberField className="h-6 w-24" value={s.gaussian_y_deg} min={1e-9} max={89.9} onCommit={(v) => v !== null && v > 0 && set('Source divergence', { gaussian_y_deg: Math.min(89.9, v) })} />
                {s.spatial === 'gaussian' && (s.shape === 'disk' || s.shape === 'rectangle') && (
                  <Button
                    size="sm"
                    variant="ghost"
                    title={t('src.fromWaistHint')}
                    onClick={() => {
                      // diffraction-limited divergence of a Gaussian waist: theta = lambda / (pi w0)
                      const th = (w: number) => Math.atan((lam0 * 1e-3) / (Math.PI * w)) / DEG
                      set('Divergence from waist', { gaussian_x_deg: th(s.gaussian_wx), gaussian_y_deg: th(s.gaussian_wy) })
                      toast('info', `θ = λ/(π w₀) at ${fmt(lam0 * 1000, 5)} nm`)
                    }}
                  >
                    {t('src.fromWaist')}
                  </Button>
                )}
              </div>
            </>
          )}
          {(s.angular === 'cone' || truncates) && (
            <>
              <Label form hint={s.angular === 'cone' ? t('src.coneHint') : t('src.truncHint')}>{s.angular === 'cone' ? t('src.halfAngle') : t('src.truncation')}</Label>
              <AngleNa deg={s.half_angle_deg} label="half angle" onCommit={(v) => set('Source half-angle', { half_angle_deg: v })} />
            </>
          )}
          {s.angular === 'table' && (
            <>
              <Label form hint={t('src.tableHint')}>{t('src.table')}</Label>
              <RowsField value={s.table} cols={2} placeholder={'0  1\n30  0.8\n60  0.3\n90  0'} invalidMsg={t('src.rowsInvalid')} onCommit={(rows) => set('Source intensity table', { table: rows })} />
            </>
          )}
          <SpectrumRows s={s} set={set} />
        </>
      )}
    </Grid>
  )
}

function SpectrumRows({ s, set }: { s: LightSource; set: (label: string, patch: Partial<LightSource>) => void }) {
  const t = useT()
  const pose = useSourcePose(s)
  return (
    <>
      <Head>{t('src.spectrum')}</Head>
      <Label form hint={t('src.spectrumHint')}>{t('src.wavelengths')}</Label>
      <RowsField
        value={s.wavelengths.map((w) => [w.value, w.weight])}
        cols={2}
        placeholder={t('src.spectrumPlaceholder')}
        invalidMsg={t('src.rowsInvalid')}
        onCommit={(rows) => set('Source spectrum', { wavelengths: rows.filter((r) => r[0] > 0).map((r) => ({ value: r[0] > 50 ? r[0] / 1000 : r[0], weight: Math.max(0, r[1]) })) })}
      />
      <Label form hint={t('src.spec.hint')}>{t('src.spec.title')}</Label>
      <SpectrumGenerator onSpectrum={(w, label) => set(label, { wavelengths: w.map((x) => ({ value: Math.round(x.value * 1e6) / 1e6, weight: Math.round(x.weight * 1e8) / 1e8 })) })} />
      <Label form hint={t('src.lightHint')}>{t('src.light')}</Label>
      <LightLine q={pose?.light} />
    </>
  )
}

/** A Gaussian beam: waist, M² and where the waist is, with the engine's beam read-outs at the first wavelength. */
function GaussianBeamRows({ s, set }: { s: LightSource; set: (label: string, patch: Partial<LightSource>) => void }) {
  const t = useT()
  const pose = useSourcePose(s)
  const b = pose?.beam
  const wx = s.beam_waist_x ?? 0.5
  const wy = s.beam_waist_y ?? 0.5
  return (
    <>
      <Head>{t('src.beam')}</Head>
      <Label form hint={t('src.beamWaistHint')}>{t('src.waist')} x / y (mm)</Label>
      <div className="flex items-center gap-1">
        <NumberField className="h-6 w-24" value={wx} min={1e-9} units={LENGTH_TO_MM} ariaLabel={`${t('src.waist')} x`} onCommit={(v) => v !== null && v > 0 && set('Beam waist', { beam_waist_x: v })} />
        <NumberField className="h-6 w-24" value={wy} min={1e-9} units={LENGTH_TO_MM} ariaLabel={`${t('src.waist')} y`} onCommit={(v) => v !== null && v > 0 && set('Beam waist', { beam_waist_y: v })} />
        {wx !== wy && (
          <Button size="sm" variant="ghost" onClick={() => set('Round beam', { beam_waist_y: wx })} title={t('src.roundHint')}>
            {t('src.round')}
          </Button>
        )}
      </div>
      <Label form hint={t('src.m2Hint')}>M²</Label>
      <NumberField className="h-6 w-24" value={s.beam_m2 ?? 1} min={1} max={1000} ariaLabel="M²" onCommit={(v) => v !== null && set('Beam quality', { beam_m2: Math.max(1, v) })} />
      <Label form hint={t('src.waistZHint')}>{t('src.waistZ')} (mm)</Label>
      <NumberField className="h-6 w-24" value={s.beam_waist_z ?? 0} units={LENGTH_TO_MM} ariaLabel={t('src.waistZ')} onCommit={(v) => set('Waist position', { beam_waist_z: v ?? 0 })} />
      {b && (
        <>
          <span className="text-muted" title={t('src.beamAtHint')}>
            {t('src.beamAt', { nm: fmt(b.wavelength_um * 1000, 5) })}
          </span>
          <table className="text-small">
            <thead className="text-caption text-muted">
              <tr>
                <th></th>
                <th className="px-2 text-right font-normal">x</th>
                <th className="px-2 text-right font-normal">y</th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  [t('src.divergenceHalf'), 'mrad', (a: typeof b.x) => fmt(a.divergence_mrad, 4)],
                  [t('src.rayleigh'), 'mm', (a: typeof b.x) => fmt(a.rayleigh_mm, 4)],
                  [t('src.radiusAtSource'), 'mm', (a: typeof b.x) => fmt(a.radius_at_source_mm, 4)],
                  [t('src.wavefrontR'), 'mm', (a: typeof b.x) => (a.wavefront_radius_mm === null ? '∞' : fmt(a.wavefront_radius_mm, 4))],
                ] as const
              ).map(([label, unit, f]) => (
                <tr key={label}>
                  <td className="pr-2 text-muted">
                    {label} ({unit})
                  </td>
                  <td className="num px-2 text-right">{f(b.x)}</td>
                  <td className="num px-2 text-right">{f(b.y)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  )
}

function DetectorForm({ d, set }: { d: DetectorSpec; set: (label: string, patch: Partial<DetectorSpec>) => void }) {
  const t = useT()
  return (
    <Grid>
      <Head>{t('det.detector')}</Head>
      <Label form>{t('src.name')}</Label>
      <TextField value={d.name} onCommit={(v) => set('Detector name', { name: v || 'Detector' })} />
      <Label form hint={t('det.modeHint')}>{t('det.mode')}</Label>
      <Select value={d.mode} options={[{ value: 'absorb', label: t('det.absorb') }, { value: 'monitor', label: t('det.monitor') }]} onChange={(v) => set('Detector mode', { mode: v })} />
      <Head>{t('src.placement')}</Head>
      <PlacementRows p={d.placement} receiver set={(label, p) => set(`Detector ${label.toLowerCase()}`, { placement: p })} />
      <Head>{t('det.area')}</Head>
      <Label form>{t('src.shape')}</Label>
      <Select value={d.shape} options={[{ value: 'circle', label: t('det.circle') }, { value: 'rectangle', label: t('det.rectangle') }]} onChange={(v) => set('Detector shape', { shape: v })} />
      {d.shape === 'circle' ? (
        <>
          <Label form>{t('src.radius')} (mm)</Label>
          <div className="flex items-center gap-2">
            <NumberField className="h-6 w-28" value={d.size_x} min={1e-9} units={LENGTH_TO_MM} onCommit={(v) => v !== null && v > 0 && set('Detector radius', { size_x: v })} />
            <span className="text-faint">Ø {fmt(2 * d.size_x, 5)} mm</span>
          </div>
        </>
      ) : (
        <>
          <Label form>{t('src.sizeX')} / {t('src.sizeY')} (mm)</Label>
          <div className="flex gap-1">
            <NumberField className="h-6 w-24" value={d.size_x} min={1e-9} units={LENGTH_TO_MM} onCommit={(v) => v !== null && v > 0 && set('Detector size', { size_x: v })} />
            <NumberField className="h-6 w-24" value={d.size_y} min={1e-9} units={LENGTH_TO_MM} onCommit={(v) => v !== null && v > 0 && set('Detector size', { size_y: v })} />
          </div>
        </>
      )}
      <Label form hint={t('det.acceptanceHint')}>{t('det.acceptance')}</Label>
      <AngleNa deg={d.acceptance_deg} label="acceptance" onCommit={(v) => set('Detector acceptance', { acceptance_deg: v })} />
      <Label form hint={t('det.twoSidedHint')}>{t('det.twoSided')}</Label>
      <Checkbox checked={d.two_sided} onChange={(v) => set('Detector sides', { two_sided: v })} />
      <Label form>{t('det.pixels')}</Label>
      <NumberField className="h-6 w-28" value={d.pixels} integer min={4} max={512} onCommit={(v) => v !== null && set('Detector pixels', { pixels: Math.min(512, Math.max(4, Math.round(v))) })} />
      <div className="col-span-2 pt-1">
        <Badge>{detectorSummary(d)}</Badge>
      </div>
    </Grid>
  )
}
