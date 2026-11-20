import { Play, Square, X } from 'lucide-react'
import { FIBRE2D_DEFAULTS, FIBRE2D_MAX_CELLS, fibre2dCells } from '../../lib/fibre'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { COLORMAPS } from '../../lib/palette'
import type { Fibre2dSettings, Fibre2dShape } from '../../lib/types'
import { useEngineStore } from '../../store/engineStore'
import { fibre2dKey, useFibre2dStore } from '../../store/fibre2dStore'
import { useProjectStore } from '../../store/projectStore'
import { Label, Pair, Stat } from '../common/controls'
import { Plot } from '../common/Plot'
import { Badge, Button, Checkbox, IconButton, NumberField, Select } from '../common/ui'
import { useAnalysisSettings } from '../common/useAnalysisSettings'
import { useMaterialNames } from '../editors/materialNames'
import { AnalysisFrame } from './AnalysisFrame'
import { Notes } from './WaveViews'

const UM: Record<string, number> = { um: 1, µm: 1, nm: 1e-3, mm: 1e3 }
type View = Fibre2dSettings & { show?: 'intensity' | 'index' }

/** Index (or library material) of a region: a material selector with a fixed index as its first choice. */
function IndexInput({ n, material, names, onChange, label }: { n: number | null | undefined; material: string | null | undefined; names: string[]; onChange: (p: { n?: number | null; material?: string | null }) => void; label: string }) {
  const t = useT()
  return (
    <span className="inline-flex items-center gap-1">
      <Select className="h-6 w-28 text-small" ariaLabel={label} value={material ?? ''} options={[{ value: '', label: t('f2.fixedIndex') }, ...names.map((x) => ({ value: x, label: x }))]} onChange={(v) => onChange({ material: v || null })} />
      {!material && <NumberField className="h-6 w-16" ariaLabel={`${label} n`} value={n ?? null} min={0.01} onCommit={(v) => v && onChange({ n: v })} />}
    </span>
  )
}

function ShapeRow({ s, names, onChange, onRemove }: { s: Fibre2dShape; names: string[]; onChange: (p: Partial<Fibre2dShape>) => void; onRemove: () => void }) {
  const t = useT()
  const num = (key: keyof Fibre2dShape, aria: string, min?: number) => (
    <NumberField cell className="h-6 w-full" ariaLabel={aria} value={(s[key] as number | undefined) ?? 0} min={min} onCommit={(v) => onChange({ [key]: v ?? 0 } as Partial<Fibre2dShape>)} />
  )
  return (
    <tr>
      <td className="px-1">
        <Select
          cell
          className="h-6 w-full text-small"
          ariaLabel={t('f2.kind')}
          value={s.kind}
          options={[
            { value: 'circle', label: t('f2.circle') },
            { value: 'ellipse', label: t('f2.ellipse') },
            { value: 'rect', label: t('f2.rect') },
          ]}
          onChange={(v) => onChange(v === 'circle' ? { kind: v, r: s.r || s.rx || 1 } : v === 'ellipse' ? { kind: v, rx: s.rx || s.r || 1, ry: s.ry || s.r || 1 } : { kind: v, w: s.w || 2 * (s.r ?? 1), h: s.h || 2 * (s.r ?? 1) })}
        />
      </td>
      <td className="px-1">{num('x', 'x')}</td>
      <td className="px-1">{num('y', 'y')}</td>
      <td className="px-1">{s.kind === 'circle' ? num('r', 'r', 0) : s.kind === 'ellipse' ? num('rx', 'rx', 0) : num('w', 'w', 0)}</td>
      <td className="px-1">{s.kind === 'ellipse' ? num('ry', 'ry', 0) : s.kind === 'rect' ? num('h', 'h', 0) : <span className="text-faint">—</span>}</td>
      <td className="px-1">{s.kind === 'circle' ? <span className="text-faint">—</span> : num('angle_deg', t('f2.angle'))}</td>
      <td className="px-1">
        <IndexInput n={s.n} material={s.material} names={names} label={t('f2.regionIndex')} onChange={(p) => onChange(p)} />
      </td>
      <td className="px-1">
        <IconButton size="sm" tone="danger" title={t('f2.removeShape')} onClick={onRemove}>
          <X size={12} />
        </IconButton>
      </td>
    </tr>
  )
}

export function Fibre2dView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const custom = useProjectStore((s) => s.project.custom_materials)
  const names = useMaterialNames().filter((n) => n !== 'MIRROR')
  const [st, set] = useAnalysisSettings<View>('fiber2d', FIBRE2D_DEFAULTS)
  const { show = 'intensity', ...cfg } = st
  const sysLam = system.wavelengths[system.primary_wavelength]?.value ?? 1.55
  const spec = { ...cfg, wavelength_um: cfg.wavelength_um ?? sysLam }
  const { job, result, resultKey, error, start, cancel } = useFibre2dStore()
  const backend = useEngineStore((s) => s.backend)
  const running = job?.state === 'running' || job?.state === 'queued'
  const stale = !!result && resultKey !== fibre2dKey(spec)
  // the lattice alone is symmetric about both axes (the engine then solves a quadrant); other shapes may not be
  const cells = cfg.shapes.length === 0 ? fibre2dCells(cfg) : null
  const lat = cfg.lattice
  const setLat = (p: Partial<NonNullable<Fibre2dSettings['lattice']>>) => lat && set({ lattice: { ...lat, ...p } })
  const setShape = (i: number, p: Partial<Fibre2dShape>) => set({ shapes: cfg.shapes.map((s, k) => (k === i ? { ...s, ...p } : s)) }, 'Fibre cross-section shape')
  const best = result && result.best !== null ? result.modes[result.best] : null
  const f = result?.fields
  return (
    <AnalysisFrame
      kind="fiber2d"
      title={t('view.fiber2d')}
      loading={false}
      error={null}
      hasData={!!result}
      ms={null}
      method={result?.method}
      onRefresh={() => void start(spec, custom)}
      settings={spec as unknown as Record<string, unknown>}
      result={null}
      onDemand
      alwaysShow
      controls={
        <>
          <Pair>
            <Label hint={t('fm.lambdaHint')}>λ (µm)</Label>
            <NumberField className="h-6 w-16" ariaLabel={t('c.wavelength')} value={spec.wavelength_um} min={0.05} max={100} units={UM} onCommit={(v) => set({ wavelength_um: v })} />
          </Pair>
          <Pair>
            <Label hint={t('f2.backgroundHint')}>{t('f2.background')}</Label>
            <IndexInput n={cfg.n_background} material={cfg.background_material} names={names} label={t('f2.background')} onChange={(p) => set({ ...(p.n !== undefined ? { n_background: p.n } : {}), ...(p.material !== undefined ? { background_material: p.material } : {}) })} />
          </Pair>
          <Checkbox
            checked={!!lat}
            onChange={(v) => set({ lattice: v ? (FIBRE2D_DEFAULTS.lattice ?? null) : null })}
            label={<span title={t('f2.latticeHint')}>{t('f2.lattice')}</span>}
          />
          {lat && (
            <>
              <Pair>
                <Label hint={t('f2.pitchHint')}>Λ</Label>
                <NumberField className="h-6 w-14" ariaLabel={t('f2.pitch')} value={lat.pitch_um} min={0.01} units={UM} onCommit={(v) => v && setLat({ pitch_um: v })} />
              </Pair>
              <Pair>
                <Label hint={t('f2.dHint')}>d</Label>
                <NumberField className="h-6 w-14" ariaLabel={t('f2.d')} value={lat.d_um} min={0.001} units={UM} onCommit={(v) => v && setLat({ d_um: v })} />
              </Pair>
              <Pair>
                <Label hint={t('f2.ringsHint')}>{t('f2.rings')}</Label>
                <NumberField className="h-6 w-10" ariaLabel={t('f2.rings')} value={lat.rings} min={1} max={8} integer onCommit={(v) => v && setLat({ rings: Math.round(v) })} />
              </Pair>
            </>
          )}
        </>
      }
      more={
        <>
          {lat && (
            <>
              <Pair>
                <Label hint={t('f2.holeHint')}>{t('f2.hole')}</Label>
                <IndexInput n={lat.n_hole} material={lat.hole_material} names={names} label={t('f2.hole')} onChange={(p) => setLat({ ...(p.n !== undefined ? { n_hole: p.n } : {}), ...(p.material !== undefined ? { hole_material: p.material } : {}) })} />
              </Pair>
              <Checkbox checked={lat.missing_centre} onChange={(v) => setLat({ missing_centre: v })} label={t('f2.solidCore')} />
            </>
          )}
          <Pair>
            <Label hint={t('f2.windowHint')}>{t('f2.window')}</Label>
            <NumberField className="h-6 w-14" ariaLabel={t('f2.window')} value={cfg.window_um} min={0.1} max={2000} optional placeholder="auto" units={UM} onCommit={(v) => set({ window_um: v })} />
          </Pair>
          <Pair>
            <Label hint={t('f2.meshHint')}>h</Label>
            <NumberField className="h-6 w-14" ariaLabel={t('f2.mesh')} value={cfg.mesh_um} min={0.001} optional placeholder="auto" units={UM} onCommit={(v) => set({ mesh_um: v })} />
          </Pair>
          <Pair>
            <Label hint={t('f2.pmlHint')}>PML</Label>
            <NumberField className="h-6 w-12" ariaLabel="PML" value={cfg.pml_um} min={0} units={UM} onCommit={(v) => set({ pml_um: v ?? 0 })} />
          </Pair>
          <Select className="h-6 w-20 text-small" ariaLabel={t('f2.pol')} title={t('f2.polHint')} value={cfg.polarisation} options={[{ value: 'x', label: 'Ex' }, { value: 'y', label: 'Ey' }]} onChange={(v) => set({ polarisation: v })} />
          <Pair>
            <Label hint={t('f2.countHint')}>{t('f2.count')}</Label>
            <NumberField className="h-6 w-10" ariaLabel={t('f2.count')} value={cfg.count} min={1} max={30} integer onCommit={(v) => v && set({ count: Math.round(v) })} />
          </Pair>
          <Pair>
            <Label hint={t('f2.guessHint')}>n₀</Label>
            <NumberField className="h-6 w-20" ariaLabel={t('f2.guess')} value={cfg.n_guess} min={0.01} optional placeholder="auto" onCommit={(v) => set({ n_guess: v })} />
          </Pair>
          <Checkbox checked={cfg.refine} onChange={(v) => set({ refine: v })} label={<span title={t('f2.refineHint')}>{t('f2.refine')}</span>} />
          {cells !== null && (
            <span className={`num text-caption ${cells > FIBRE2D_MAX_CELLS ? 'text-danger' : 'text-faint'}`}>
              {cells}² {t('fd.cells')}
            </span>
          )}
        </>
      }
      actions={
        running ? (
          <>
            <div className="h-1.5 w-24 shrink-0 overflow-hidden rounded bg-hover" role="progressbar" aria-valuenow={Math.round((job?.progress ?? 0) * 100)} aria-valuemin={0} aria-valuemax={100}>
              <div className="h-full bg-accent transition-[width]" style={{ width: `${(job?.progress ?? 0) * 100}%` }} />
            </div>
            <span className="num text-caption whitespace-nowrap text-muted">{job ? `${job.elapsed_s.toFixed(0)} s` : ''}</span>
            <Button size="sm" onClick={() => void cancel()}>
              <Square size={12} /> {t('c.cancel')}
            </Button>
          </>
        ) : (
          <Button size="sm" variant="primary" disabled={backend !== 'online' || (cells !== null && cells > FIBRE2D_MAX_CELLS)} onClick={() => void start(spec, custom)} title={t('f2.runHint')}>
            <Play size={12} /> {t('fd.run')}
          </Button>
        )
      }
    >
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="relative min-h-0 flex-1">
          {result ? (
            <div className="flex h-full min-h-0 flex-col">
              <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
                {best && <Stat label="n_eff" value={fmt(best.neff, 10)} />}
                {best && <Stat label={t('f2.loss')} value={fmt(best.loss_db_per_m, 4)} unit="dB/m" />}
                {best && <Stat label="κ" value={best.kappa.toExponential(3)} />}
                {best && <Stat label={t('fm.aeff')} value={fmt(best.effective_area_um2, 4)} unit="µm²" />}
                {best && <Stat label={t('fm.coreFrac')} value={fmt(best.core_fraction * 100, 4)} unit="%" />}
                <Stat label={t('f2.meshStat')} value={fmt(result.mesh.h_um * 1000, 4)} unit={`nm · ${result.mesh.cells}² · ${result.mesh.refined ? t('f2.richardson') : t('f2.oneMesh')}`} />
                <div className="flex items-center gap-2 px-3">
                  <Select className="h-6 w-28 text-small" ariaLabel={t('fd.show')} value={show} options={[{ value: 'intensity', label: '|E_t|²' }, { value: 'index', label: t('fd.index') }]} onChange={(v) => set({ show: v } as Partial<View>)} />
                  {stale && <Badge tone="warn">{t('fd.stale')}</Badge>}
                </div>
              </div>
              <div className="grid min-h-0 flex-1 grid-cols-[minmax(260px,1.4fr)_minmax(220px,1fr)] gap-px bg-line">
                <div className="min-h-[220px] bg-panel">
                  {f && (
                    <Plot
                      square
                      data={[
                        {
                          type: 'heatmap',
                          x: f.x_um,
                          y: f.x_um,
                          z: show === 'index' ? f.index : f.intensity,
                          colorscale: show === 'index' ? COLORMAPS.greys : COLORMAPS.sequential,
                          colorbar: { thickness: 12 },
                          hovertemplate: 'x %{x:.3f} µm<br>y %{y:.3f} µm<br>%{z:.4g}<extra></extra>',
                        },
                      ]}
                      layout={{ margin: { l: 50, r: 10, t: 6, b: 36 }, xaxis: { title: { text: 'x (µm)' } }, yaxis: { title: { text: 'y (µm)' } } }}
                    />
                  )}
                </div>
                <div className="min-h-0 overflow-auto bg-panel">
                  <table className="eng-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th className="text-right">n_eff</th>
                        <th className="text-right">{t('f2.loss')} (dB/m)</th>
                        <th className="text-right">{t('fm.coreFrac')}</th>
                        <th className="text-right">A_eff (µm²)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.modes.map((m, i) => (
                        <tr key={i} className={i === result.best ? 'bg-accent-soft' : undefined}>
                          <td className="px-2 text-muted">{i + 1}</td>
                          <td className="num px-2 text-right">{fmt(m.neff, 10)}</td>
                          <td className="num px-2 text-right">{fmt(m.loss_db_per_m, 4)}</td>
                          <td className="num px-2 text-right">{fmt(m.core_fraction * 100, 3)} %</td>
                          <td className="num px-2 text-right">{fmt(m.effective_area_um2, 4)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <Notes notes={result.notes} />
            </div>
          ) : (
            <div className="flex h-full items-center justify-center p-6 text-center text-body text-muted">{error ? <span className="text-danger">{error}</span> : running ? t('f2.running') : t('f2.empty')}</div>
          )}
          {error && result && <div className="absolute right-2 bottom-2 rounded bg-danger/15 px-2 py-1 text-small text-danger">{error}</div>}
        </div>
        <div className="flex max-h-[170px] shrink-0 flex-col border-t border-line">
          <div className="flex shrink-0 items-center gap-2 bg-panel px-2 py-1">
            <span className="text-small font-semibold tracking-wide text-muted uppercase">{t('f2.shapes')}</span>
            <Button size="sm" onClick={() => set({ shapes: [...cfg.shapes, { kind: 'circle', x: 0, y: 0, r: 1, n: 1.46, material: null }] }, 'Add fibre cross-section circle')}>
              + ◯
            </Button>
            <Button size="sm" onClick={() => set({ shapes: [...cfg.shapes, { kind: 'rect', x: 0, y: 0, w: 2, h: 1, angle_deg: 0, n: 1.46, material: null }] }, 'Add fibre cross-section rectangle')}>
              + ▭
            </Button>
            <span className="truncate text-caption text-faint">{t('f2.shapesHint')}</span>
          </div>
          {cfg.shapes.length > 0 && (
            <div className="min-h-0 overflow-auto">
              <table className="eng-table">
                <thead>
                  <tr>
                    <th>{t('f2.kind')}</th>
                    <th>x (µm)</th>
                    <th>y (µm)</th>
                    <th>r / rx / w</th>
                    <th>ry / h</th>
                    <th>{t('f2.angle')}</th>
                    <th>{t('f2.regionIndex')}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {cfg.shapes.map((s, i) => (
                    <ShapeRow key={i} s={s} names={names} onChange={(p) => setShape(i, p)} onRemove={() => set({ shapes: cfg.shapes.filter((_, k) => k !== i) }, 'Remove fibre cross-section shape')} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </AnalysisFrame>
  )
}
