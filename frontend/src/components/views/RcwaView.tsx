import { ArrowDown, ArrowUp, Plus, X } from 'lucide-react'
import { useState } from 'react'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { COLORMAPS, DATA, SERIES } from '../../lib/palette'
import {
  crossedFrom,
  formatOrders2d,
  isCrossed,
  MAX_ORDERS_2D,
  newLayer,
  newShape,
  orders2d,
  parseOrders,
  parseOrders2d,
  RCWA_DEFAULTS,
  type RcwaLayer,
  type RcwaLayerKind,
  type RcwaMedium,
  type RcwaRequest,
  type RcwaShape,
} from '../../lib/rcwa'
import type { RcwaResult, RcwaShapeDraw } from '../../lib/types'
import { Label, Pair, Stat } from '../common/controls'
import { Plot, type Trace } from '../common/Plot'
import { Button, IconButton, NumberField, Select, TextField } from '../common/ui'
import { useAnalysisSettings } from '../common/useAnalysisSettings'
import { useMaterialNames } from '../editors/materialNames'
import { AnalysisFrame } from './AnalysisFrame'
import { useAnalysis } from './useAnalysis'
import { Notes } from './WaveViews'

const UM: Record<string, number> = { um: 1, µm: 1, nm: 1e-3, mm: 1e3 }
const RELIEF: RcwaLayerKind[] = ['sinusoidal', 'sawtooth', 'trapezoid']
const KINDS_1D: RcwaLayerKind[] = ['uniform', 'lamellar', 'sinusoidal', 'sawtooth', 'trapezoid']

/** A medium: a library material, or a fixed index n with extinction k. */
function MediumInput({ m, names, onChange, label, lossless }: { m: RcwaMedium | null; names: string[]; onChange: (m: RcwaMedium) => void; label: string; lossless?: boolean }) {
  const t = useT()
  const v = m ?? { n: 1, k: 0, material: null }
  return (
    <span className="inline-flex items-center gap-1">
      <Select
        cell
        className="h-6 w-28 text-small"
        ariaLabel={label}
        value={v.material ?? ''}
        options={[{ value: '', label: t('rc.fixedIndex') }, ...names.map((x) => ({ value: x, label: x }))]}
        onChange={(x) => onChange(x ? { n: null, k: v.k, material: x } : { n: v.n ?? 1.5, k: v.k, material: null })}
      />
      {!v.material && <NumberField cell className="h-6 w-14" ariaLabel={`${label} n`} value={v.n} min={0.01} max={100} onCommit={(x) => x && onChange({ ...v, n: x })} />}
      {!lossless && <NumberField cell className="h-6 w-12" ariaLabel={`${label} k`} title={t('rc.kHint')} value={v.k} min={0} max={100} onCommit={(x) => onChange({ ...v, k: x ?? 0 })} />}
    </span>
  )
}

function LayerRow({
  L,
  i,
  n,
  names,
  crossed,
  selected,
  set,
  remove,
  move,
  select,
  cell,
}: {
  L: RcwaLayer
  i: number
  n: number
  names: string[]
  crossed: boolean
  selected: boolean
  set: (p: Partial<RcwaLayer>) => void
  remove: () => void
  move: (d: number) => void
  select: () => void
  cell: [number, number]
}) {
  const t = useT()
  const relief = RELIEF.includes(L.kind)
  const kinds: RcwaLayerKind[] = crossed ? [...KINDS_1D, 'pattern'] : KINDS_1D
  const onKind = (k: RcwaLayerKind) => {
    if (k === 'uniform') set({ kind: k, groove: null })
    else if (k === 'pattern') {
      set({ kind: k, groove: L.groove ?? { n: 1, k: 0, material: null }, shapes: L.shapes?.length ? L.shapes : [newShape(cell[0], cell[1])] })
      select()
    } else set({ kind: k, groove: L.groove ?? { n: 1, k: 0, material: null } })
  }
  return (
    <tr className={selected && crossed ? 'bg-accent-soft' : undefined} onClick={crossed ? select : undefined}>
      <td className="px-1 text-muted">{i + 1}</td>
      <td className="px-1">
        <Select<RcwaLayerKind> cell className="h-6 w-32 text-small" ariaLabel={t('rc.kind')} value={L.kind} options={kinds.map((k) => ({ value: k, label: t(`rc.k.${k}`) }))} onChange={onKind} />
      </td>
      <td className="px-1">
        <NumberField cell className="h-6 w-16" ariaLabel={t('rc.thickness')} value={L.thickness_um} min={0} max={1000} units={UM} onCommit={(v) => set({ thickness_um: v ?? 0 })} />
      </td>
      <td className="px-1">
        {L.kind === 'lamellar' ? (
          <NumberField cell className="h-6 w-14" ariaLabel={t('rc.fill')} value={L.fill} min={0} max={1} onCommit={(v) => set({ fill: v ?? 0.5 })} />
        ) : L.kind === 'trapezoid' ? (
          <span className="inline-flex gap-1">
            <NumberField cell className="h-6 w-12" ariaLabel={t('rc.fillTop')} title={t('rc.fillTop')} value={L.fill_top} min={0} max={1} onCommit={(v) => set({ fill_top: v ?? 0.5 })} />
            <NumberField cell className="h-6 w-12" ariaLabel={t('rc.fillBottom')} title={t('rc.fillBottom')} value={L.fill_bottom} min={0} max={1} onCommit={(v) => set({ fill_bottom: v ?? 0.5 })} />
          </span>
        ) : L.kind === 'pattern' ? (
          <Button size="sm" title={t('rc.shapesHint')} onClick={select}>
            {t('rc.shapesN', { n: L.shapes?.length ?? 0 })}
          </Button>
        ) : (
          <span className="text-faint">—</span>
        )}
      </td>
      <td className="px-1">{relief ? <NumberField cell className="h-6 w-12" ariaLabel={t('rc.slices')} value={L.slices} min={1} max={200} integer onCommit={(v) => set({ slices: Math.round(v ?? 10) })} /> : <span className="text-faint">—</span>}</td>
      <td className="px-1">
        <MediumInput m={L.ridge} names={names} label={L.kind === 'uniform' ? t('rc.medium') : t('rc.ridge')} onChange={(m) => set({ ridge: m })} />
      </td>
      <td className="px-1">{L.kind === 'uniform' ? <span className="text-faint">—</span> : <MediumInput m={L.groove} names={names} label={t('rc.groove')} onChange={(m) => set({ groove: m })} />}</td>
      <td className="px-1 whitespace-nowrap">
        <IconButton size="sm" title={t('rc.up')} disabled={i === 0} onClick={() => move(-1)}>
          <ArrowUp size={12} />
        </IconButton>
        <IconButton size="sm" title={t('rc.down')} disabled={i === n - 1} onClick={() => move(1)}>
          <ArrowDown size={12} />
        </IconButton>
        <IconButton size="sm" tone="danger" title={t('rc.remove')} onClick={remove}>
          <X size={12} />
        </IconButton>
      </td>
    </tr>
  )
}

/** The shapes of one pattern layer (µm in the cell). */
function ShapesEditor({ L, i, names, cell, set }: { L: RcwaLayer; i: number; names: string[]; cell: [number, number]; set: (shapes: RcwaShape[]) => void }) {
  const t = useT()
  const shapes = L.shapes ?? []
  const put = (k: number, p: Partial<RcwaShape>) => set(shapes.map((s, j) => (j === k ? { ...s, ...p } : s)))
  return (
    <div className="flex shrink-0 flex-col border-t border-line bg-panel">
      <div className="flex items-center gap-2 px-2 py-1">
        <span className="text-small font-semibold tracking-wide text-muted uppercase">{t('rc.shapesOf', { n: i + 1 })}</span>
        <Button size="sm" disabled={shapes.length >= 64} onClick={() => set([...shapes, newShape(cell[0], cell[1], 'rectangle')])}>
          <Plus size={12} /> {t('rc.addShape')}
        </Button>
        <span className="truncate text-caption text-faint">{t('rc.shapesHint')}</span>
      </div>
      <div className="overflow-auto">
        <table className="eng-table">
          <thead>
            <tr>
              <th>#</th>
              <th>{t('rc.shape')}</th>
              <th title={t('rc.cxHint')}>x₀ (µm)</th>
              <th title={t('rc.cyHint')}>y₀ (µm)</th>
              <th title={t('rc.aHint')}>a (µm)</th>
              <th title={t('rc.bHint')}>b (µm)</th>
              <th title={t('rc.angleHint')}>∠ (°)</th>
              <th>{t('rc.medium')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {shapes.map((s, k) => (
              <tr key={k}>
                <td className="px-1 text-muted">{k + 1}</td>
                <td className="px-1">
                  <Select<RcwaShape['kind']>
                    cell
                    className="h-6 w-28 text-small"
                    ariaLabel={t('rc.shape')}
                    value={s.kind}
                    options={(['rectangle', 'ellipse'] as const).map((x) => ({ value: x, label: t(`rc.shape.${x}`) }))}
                    onChange={(x) => put(k, { kind: x })}
                  />
                </td>
                <td className="px-1">
                  <NumberField cell className="h-6 w-16" ariaLabel={t('rc.cxHint')} value={s.cx_um} min={-10000} max={10000} units={UM} onCommit={(v) => v !== null && put(k, { cx_um: v })} />
                </td>
                <td className="px-1">
                  <NumberField cell className="h-6 w-16" ariaLabel={t('rc.cyHint')} value={s.cy_um} min={-10000} max={10000} units={UM} onCommit={(v) => v !== null && put(k, { cy_um: v })} />
                </td>
                <td className="px-1">
                  <NumberField cell className="h-6 w-16" ariaLabel={t('rc.aHint')} value={s.a_um} min={1e-6} max={10000} units={UM} onCommit={(v) => v && put(k, { a_um: v })} />
                </td>
                <td className="px-1">
                  <NumberField cell className="h-6 w-16" ariaLabel={t('rc.bHint')} value={s.b_um} min={1e-6} max={10000} units={UM} onCommit={(v) => v && put(k, { b_um: v })} />
                </td>
                <td className="px-1">
                  <NumberField cell className="h-6 w-14" ariaLabel={t('rc.angleHint')} value={s.angle_deg} min={-360} max={360} onCommit={(v) => put(k, { angle_deg: v ?? 0 })} />
                </td>
                <td className="px-1">
                  <MediumInput m={s.medium ?? L.ridge} names={names} label={t('rc.medium')} onChange={(m) => put(k, { medium: m })} />
                </td>
                <td className="px-1">
                  <IconButton size="sm" tone="danger" title={t('rc.removeShape')} onClick={() => set(shapes.filter((_, j) => j !== k))}>
                    <X size={12} />
                  </IconButton>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** Grey level of an index for the structure drawing: the higher the index, the darker the fill. */
const shade = (n: number, nmax: number) => {
  const f = nmax > 1 ? Math.min(1, Math.max(0, (n - 1) / (nmax - 1))) : 0
  const g = Math.round(225 - 150 * f)
  return `rgb(${g}, ${g}, ${Math.min(255, g + 15)})`
}

function structureShapes(r: RcwaResult, periods = 2): { shapes: Record<string, unknown>[]; depth: number } {
  const L = r.structure.period_um
  const sl = r.structure.slices
  const depth = sl.length ? sl[sl.length - 1].z1 : 0
  const nmax = Math.max(1.0001, ...sl.flatMap((s) => [s.groove[0], ...(s.segments ?? []).map((g) => g[2])]))
  const shapes: Record<string, unknown>[] = []
  for (const s of sl) {
    for (let p = 0; p < periods; p++) {
      shapes.push({ type: 'rect', x0: p * L, x1: (p + 1) * L, y0: -s.z0, y1: -s.z1, line: { width: 0 }, fillcolor: shade(s.groove[0], nmax), layer: 'below' })
      for (const g of s.segments ?? []) shapes.push({ type: 'rect', x0: (p + g[0]) * L, x1: (p + g[1]) * L, y0: -s.z0, y1: -s.z1, line: { width: 0 }, fillcolor: shade(g[2], nmax), layer: 'below' })
    }
  }
  return { shapes, depth }
}

/** Outline of a shape as an SVG path in the plot's data coordinates. */
function shapePath(s: RcwaShapeDraw, dx: number, dy: number): string {
  const a = (s.angle * Math.PI) / 180
  const c = Math.cos(a)
  const si = Math.sin(a)
  const pts: [number, number][] =
    s.kind === 'rectangle'
      ? [
          [-s.a / 2, -s.b / 2],
          [s.a / 2, -s.b / 2],
          [s.a / 2, s.b / 2],
          [-s.a / 2, s.b / 2],
        ]
      : Array.from({ length: 48 }, (_, k) => [(s.a / 2) * Math.cos((2 * Math.PI * k) / 48), (s.b / 2) * Math.sin((2 * Math.PI * k) / 48)])
  return pts.map(([u, v], k) => `${k ? 'L' : 'M'} ${(s.cx + dx + u * c - v * si).toFixed(6)} ${(s.cy + dy + u * si + v * c).toFixed(6)}`).join(' ') + ' Z'
}

/** Top view of one layer of a crossed grating: two cells in x and y. */
function topView(r: RcwaResult, layer: number): Record<string, unknown>[] | null {
  const Lx = r.structure.period_um
  const Ly = r.structure.period_y_um ?? Lx
  const sl = r.structure.slices.filter((s) => s.layer === layer)
  if (!sl.length) return null
  const s = sl[Math.floor(sl.length / 2)]
  const all = r.structure.slices.flatMap((x) => [x.groove[0], ...(x.shapes ?? []).map((g) => g.n)])
  const nmax = Math.max(1.0001, ...all)
  const out: Record<string, unknown>[] = [{ type: 'rect', x0: 0, x1: 2 * Lx, y0: 0, y1: 2 * Ly, line: { width: 0 }, fillcolor: shade(s.groove[0], nmax), layer: 'below' }]
  for (const g of s.shapes ?? []) {
    for (let i = -1; i <= 2; i++) for (let j = -1; j <= 2; j++) out.push({ type: 'path', path: shapePath(g, i * Lx, j * Ly), line: { width: 0 }, fillcolor: shade(g.n, nmax), layer: 'below' })
  }
  for (const x of [Lx]) out.push({ type: 'line', x0: x, x1: x, y0: 0, y1: 2 * Ly, line: { width: 1, dash: 'dot', color: DATA.marker } })
  for (const y of [Ly]) out.push({ type: 'line', x0: 0, x1: 2 * Lx, y0: y, y1: y, line: { width: 1, dash: 'dot', color: DATA.marker } })
  return out
}

/** Efficiency maps of a crossed grating's orders (m, q): transmitted and reflected. */
function orderMaps(r: RcwaResult): Trace[] {
  const ms = [...new Set(r.orders.map((o) => o.m))].sort((a, b) => a - b)
  const qs = [...new Set(r.orders.map((o) => o.q ?? 0))].sort((a, b) => a - b)
  const grid = (key: 'T' | 'R') => qs.map((q) => ms.map((m) => r.orders.find((o) => o.m === m && (o.q ?? 0) === q)?.[key] ?? null))
  const zT = grid('T')
  const zR = grid('R')
  const zmax = Math.max(1e-12, ...r.orders.flatMap((o) => [o.T ?? 0, o.R ?? 0]))
  return [
    { type: 'heatmap', x: ms, y: qs, z: zT, xaxis: 'x', yaxis: 'y', colorscale: COLORMAPS.sequential, zmin: 0, zmax, showscale: false, hovertemplate: 'T(%{x}, %{y}) %{z:.5f}<extra></extra>' },
    { type: 'heatmap', x: ms, y: qs, z: zR, xaxis: 'x2', yaxis: 'y2', colorscale: COLORMAPS.sequential, zmin: 0, zmax, colorbar: { thickness: 8 }, hovertemplate: 'R(%{x}, %{y}) %{z:.5f}<extra></extra>' },
  ]
}

export function RcwaView() {
  const t = useT()
  const names = useMaterialNames().filter((n) => n !== 'MIRROR')
  const [st, set] = useAnalysisSettings<RcwaRequest>('rcwa', RCWA_DEFAULTS)
  const { data, error, loading, ms, refresh } = useAnalysis<RcwaResult>('rcwa', st as unknown as Record<string, unknown>, 250)
  const crossed = isCrossed(st)
  const cell: [number, number] = [st.period_um, st.period_y_um ?? st.period_um]
  const firstPattern = Math.max(0, st.layers.findIndex((L) => L.kind === 'pattern'))
  const [selRaw, setSel] = useState<number | null>(null)
  const sel = selRaw !== null && selRaw < st.layers.length ? selRaw : firstPattern
  const setLayer = (i: number, p: Partial<RcwaLayer>) => set({ layers: st.layers.map((L, k) => (k === i ? { ...L, ...p } : L)) }, 'Grating layer')
  const moveLayer = (i: number, d: number) => {
    const a = [...st.layers]
    const j = i + d
    if (j < 0 || j >= a.length) return
    ;[a[i], a[j]] = [a[j], a[i]]
    set({ layers: a }, 'Move grating layer')
    if (sel === i) setSel(j)
  }
  const sw = st.sweep
  const prop = data?.orders ?? []
  const dataCrossed = !!data?.structure.period_y_um
  const bars: Trace[] = data
    ? [
        { type: 'bar', name: 'R', x: prop.map((o) => o.m), y: prop.map((o) => o.R ?? 0), marker: { color: DATA.secondary }, hovertemplate: 'R%{x}: %{y:.5f}<extra></extra>' },
        { type: 'bar', name: 'T', x: prop.map((o) => o.m), y: prop.map((o) => o.T ?? 0), marker: { color: DATA.primary }, hovertemplate: 'T%{x}: %{y:.5f}<extra></extra>' },
      ]
    : []
  const sweepTraces: Trace[] = data?.sweep
    ? [
        ...data.sweep.orders.flatMap((m, i) => [
          { type: 'scatter', mode: 'lines', name: `T${m}`, x: data.sweep!.x, y: data.sweep!.curves[`T${m}`], line: { color: SERIES[i % 8], width: 1.8 } },
          { type: 'scatter', mode: 'lines', name: `R${m}`, x: data.sweep!.x, y: data.sweep!.curves[`R${m}`], line: { color: SERIES[i % 8], width: 1.2, dash: 'dot' } },
        ]),
      ]
    : []
  const struct = data && !dataCrossed ? structureShapes(data) : null
  const top = data && dataCrossed ? topView(data, sel) : null
  const conversion = dataCrossed && data ? Math.max(0, ...Object.values(data.zeroth).map((z) => z.t?.cross_power ?? 0)) : null
  const rows = dataCrossed ? [...prop].sort((a, b) => (b.T ?? 0) + (b.R ?? 0) - ((a.T ?? 0) + (a.R ?? 0))) : prop
  const nOrders = orders2d(st)
  const selLayer = st.layers[sel]
  return (
    <AnalysisFrame
      kind="rcwa"
      title={t('view.rcwa')}
      loading={loading}
      error={error}
      hasData={!!data}
      ms={ms}
      method={data?.method}
      onRefresh={refresh}
      settings={st as unknown as Record<string, unknown>}
      result={data}
      alwaysShow
      controls={
        <>
          <Pair>
            <Label hint={t('rc.latticeHint')}>{t('rc.lattice')}</Label>
            <Select
              className="h-6 w-28 text-small"
              ariaLabel={t('rc.lattice')}
              value={crossed ? '2d' : '1d'}
              options={[
                { value: '1d', label: t('rc.lines') },
                { value: '2d', label: t('rc.crossedOpt') },
              ]}
              onChange={(v) => set(v === '2d' ? crossedFrom(st) : { period_y_um: null }, 'Grating periodicity')}
            />
          </Pair>
          <Pair>
            <Label hint={t('rc.lambdaHint')}>λ (µm)</Label>
            <NumberField className="h-6 w-16" ariaLabel={t('c.wavelength')} value={st.wavelength_um} min={0.05} max={100} units={UM} onCommit={(v) => v && set({ wavelength_um: v })} />
          </Pair>
          <Pair>
            <Label hint={t('rc.periodHint')}>{crossed ? 'Λx (µm)' : 'Λ (µm)'}</Label>
            <NumberField className="h-6 w-16" ariaLabel={t('rc.period')} value={st.period_um} min={0.001} max={10000} units={UM} onCommit={(v) => v && set({ period_um: v })} />
          </Pair>
          {crossed && (
            <Pair>
              <Label hint={t('rc.periodYHint')}>Λy (µm)</Label>
              <NumberField className="h-6 w-16" ariaLabel={t('rc.periodY')} value={st.period_y_um ?? st.period_um} min={0.001} max={10000} units={UM} onCommit={(v) => v && set({ period_y_um: v })} />
            </Pair>
          )}
          <Pair>
            <Label hint={t('rc.thetaHint')}>θ (°)</Label>
            <NumberField className="h-6 w-14" ariaLabel={t('rc.theta')} value={st.theta_deg} min={-89.9} max={89.9} onCommit={(v) => set({ theta_deg: v ?? 0 })} />
          </Pair>
          <Select
            className="h-6 w-28 text-small"
            ariaLabel={t('rc.pol')}
            title={t('rc.polHint')}
            value={st.polarisation}
            options={[
              { value: 'TE', label: 'TE (s)' },
              { value: 'TM', label: 'TM (p)' },
              { value: 'unpolarised', label: t('rc.unpol') },
            ]}
            onChange={(v) => set({ polarisation: v })}
          />
        </>
      }
      more={
        <>
          <Pair>
            <Label hint={t('rc.harmonicsHint')}>{crossed ? t('rc.harmonicsX') : t('rc.harmonics')}</Label>
            <NumberField className="h-6 w-14" ariaLabel={t('rc.harmonics')} value={st.harmonics} min={0} max={crossed ? 40 : 150} integer onCommit={(v) => set({ harmonics: Math.round(v ?? (crossed ? 5 : 20)) })} />
          </Pair>
          {crossed && (
            <Pair>
              <Label hint={t('rc.harmonicsYHint')}>{t('rc.harmonicsY')}</Label>
              <NumberField className="h-6 w-14" ariaLabel={t('rc.harmonicsY')} value={st.harmonics_y ?? 5} min={0} max={40} integer onCommit={(v) => set({ harmonics_y: Math.round(v ?? 5) })} />
              <span className={nOrders > MAX_ORDERS_2D ? 'text-caption text-warn' : 'text-caption text-faint'} title={t('rc.ordersCountHint', { max: MAX_ORDERS_2D })}>
                {t('rc.ordersCount', { n: nOrders })}
              </span>
            </Pair>
          )}
          <Pair>
            <Label hint={t('rc.phiHint')}>φ (°)</Label>
            <NumberField className="h-6 w-14" ariaLabel={t('rc.phi')} value={st.phi_deg} min={-180} max={180} onCommit={(v) => set({ phi_deg: v ?? 0 })} />
          </Pair>
          <Pair>
            <Label hint={t('rc.incidentHint')}>{t('rc.incident')}</Label>
            <MediumInput m={st.incident} names={names} lossless label={t('rc.incident')} onChange={(m) => set({ incident: { ...m, k: 0 } })} />
          </Pair>
          <Pair>
            <Label hint={t('rc.substrateHint')}>{t('rc.substrate')}</Label>
            <MediumInput m={st.substrate} names={names} label={t('rc.substrate')} onChange={(m) => set({ substrate: m })} />
          </Pair>
          <Pair>
            <Label hint={t('rc.sweepHint')}>{t('rc.sweep')}</Label>
            <Select
              className="h-6 w-28 text-small"
              ariaLabel={t('rc.sweep')}
              value={sw?.kind ?? ''}
              options={[
                { value: '', label: t('rc.sweepOff') },
                { value: 'wavelength', label: t('rc.sweepLambda') },
                { value: 'angle', label: t('rc.sweepAngle') },
              ]}
              onChange={(v) =>
                set({
                  sweep: !v
                    ? null
                    : v === 'wavelength'
                      ? { kind: 'wavelength', start: +(st.wavelength_um * 0.8).toFixed(4), stop: +(st.wavelength_um * 1.2).toFixed(4), points: 41, orders: sw?.orders ?? [-1, 0, 1], orders_2d: sw?.orders_2d ?? [[0, 0]] }
                      : { kind: 'angle', start: 0, stop: 60, points: 41, orders: sw?.orders ?? [-1, 0, 1], orders_2d: sw?.orders_2d ?? [[0, 0]] },
                })
              }
            />
          </Pair>
          {sw && (
            <>
              <Pair>
                <NumberField className="h-6 w-16" ariaLabel={`${t('rc.sweep')} start`} value={sw.start} units={sw.kind === 'wavelength' ? UM : undefined} onCommit={(v) => v !== null && set({ sweep: { ...sw, start: v } })} />
                <span className="text-muted">–</span>
                <NumberField className="h-6 w-16" ariaLabel={`${t('rc.sweep')} stop`} value={sw.stop} units={sw.kind === 'wavelength' ? UM : undefined} onCommit={(v) => v !== null && set({ sweep: { ...sw, stop: v } })} />
              </Pair>
              <Pair>
                <Label>{t('rc.points')}</Label>
                <NumberField className="h-6 w-12" ariaLabel={t('rc.points')} value={sw.points} min={2} max={201} integer onCommit={(v) => v && set({ sweep: { ...sw, points: Math.round(v) } })} />
              </Pair>
              <Pair>
                <Label hint={crossed ? t('rc.orders2dHint') : t('rc.ordersHint')}>{t('rc.orders')}</Label>
                {crossed ? (
                  <TextField
                    className="h-6 w-28"
                    ariaLabel={t('rc.orders')}
                    value={formatOrders2d(sw.orders_2d ?? [[0, 0]])}
                    onCommit={(v) => {
                      const o = parseOrders2d(v)
                      if (o) set({ sweep: { ...sw, orders_2d: o } })
                    }}
                  />
                ) : (
                  <TextField
                    className="h-6 w-24"
                    ariaLabel={t('rc.orders')}
                    value={sw.orders.join(', ')}
                    onCommit={(v) => {
                      const o = parseOrders(v)
                      if (o) set({ sweep: { ...sw, orders: o } })
                    }}
                  />
                )}
              </Pair>
            </>
          )}
        </>
      }
    >
      <div className="flex h-full min-h-0 flex-col overflow-y-auto">
        {data && (
          <div className="flex shrink-0 flex-wrap divide-x divide-line border-b border-line">
            <Stat label="ΣR" value={fmt(data.total_R, 6)} />
            <Stat label="ΣT" value={fmt(data.total_T, 6)} />
            <Stat label={t('rc.absorbed')} value={fmt(Math.max(0, data.absorbed), 4)} />
            {data.retardance_deg !== undefined && <Stat label={t('rc.retardance')} value={fmt(data.retardance_deg, 5)} unit="°" />}
            {conversion !== null && <Stat label={t('rc.conversion')} value={conversion.toExponential(2)} />}
            {data.convergence && (
              <Stat
                label={t('rc.convergence')}
                value={data.convergence.max_change.toExponential(1)}
                unit={dataCrossed ? `${data.convergence.harmonics_low}×${data.convergence.harmonics_y_low} → ${data.harmonics}×${data.harmonics_y}` : `${data.convergence.harmonics_low} → ${data.harmonics}`}
                tone={data.convergence.max_change > 1e-3 ? 'warn' : 'ok'}
              />
            )}
          </div>
        )}
        <div className="grid min-h-[220px] flex-1 grid-cols-[minmax(260px,1fr)_minmax(260px,1fr)] gap-px bg-line">
          <div className="min-h-[220px] bg-panel">
            {data && !dataCrossed && (
              <Plot data={bars} layout={{ barmode: 'group', margin: { l: 46, r: 8, t: 24, b: 36 }, legend: { orientation: 'h', x: 0, y: 1.01, yanchor: 'bottom' }, xaxis: { title: { text: t('rc.order') }, dtick: 1 }, yaxis: { title: { text: t('rc.efficiency') }, rangemode: 'tozero' } }} />
            )}
            {data && dataCrossed && (
              <Plot
                data={orderMaps(data)}
                layout={{
                  margin: { l: 40, r: 8, t: 26, b: 36 },
                  xaxis: { domain: [0, 0.44], title: { text: 'm' }, dtick: 1, showgrid: false },
                  yaxis: { title: { text: 'q' }, dtick: 1, showgrid: false },
                  xaxis2: { domain: [0.52, 0.96], title: { text: 'm' }, dtick: 1, showgrid: false },
                  yaxis2: { anchor: 'x2', dtick: 1, showgrid: false },
                  annotations: [
                    { text: 'T', xref: 'paper', yref: 'paper', x: 0.22, y: 1.0, yanchor: 'bottom', showarrow: false },
                    { text: 'R', xref: 'paper', yref: 'paper', x: 0.74, y: 1.0, yanchor: 'bottom', showarrow: false },
                  ],
                }}
              />
            )}
          </div>
          <div className="min-h-0 overflow-auto bg-panel">
            {data && (
              <table className="eng-table">
                <thead>
                  <tr>
                    <th>m</th>
                    {dataCrossed && <th>q</th>}
                    <th className="text-right">θ_R (°)</th>
                    {dataCrossed && <th className="text-right">φ_R (°)</th>}
                    <th className="text-right">R</th>
                    <th className="text-right">θ_T (°)</th>
                    {dataCrossed && <th className="text-right">φ_T (°)</th>}
                    <th className="text-right">T</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((o) => (
                    <tr key={`${o.m},${o.q ?? 0}`}>
                      <td className="px-2 font-medium">{o.m}</td>
                      {dataCrossed && <td className="px-2 font-medium">{o.q}</td>}
                      <td className="num px-2 text-right">{o.angle_r_deg !== undefined ? fmt(o.angle_r_deg, 5) : '—'}</td>
                      {dataCrossed && <td className="num px-2 text-right">{o.azimuth_r_deg !== undefined ? fmt(o.azimuth_r_deg, 4) : '—'}</td>}
                      <td className="num px-2 text-right">{o.R !== null ? fmt(o.R, 6) : '—'}</td>
                      <td className="num px-2 text-right">{o.angle_t_deg !== undefined ? fmt(o.angle_t_deg, 5) : '—'}</td>
                      {dataCrossed && <td className="num px-2 text-right">{o.azimuth_t_deg !== undefined ? fmt(o.azimuth_t_deg, 4) : '—'}</td>}
                      <td className="num px-2 text-right">{o.T !== null ? fmt(o.T, 6) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
        {data?.sweep && (
          <div className="h-[40%] min-h-[200px] shrink-0 border-t border-line bg-panel">
            <Plot
              data={sweepTraces}
              layout={{
                margin: { l: 50, r: 8, t: 24, b: 38 },
                legend: { orientation: 'h', x: 0, y: 1.01, yanchor: 'bottom' },
                xaxis: { title: { text: data.sweep.kind === 'wavelength' ? 'λ (µm)' : 'θ (°)' } },
                yaxis: { title: { text: t('rc.efficiency') }, rangemode: 'tozero' },
                shapes: [{ type: 'line', x0: data.sweep.kind === 'wavelength' ? data.wavelength_um : data.theta_deg, x1: data.sweep.kind === 'wavelength' ? data.wavelength_um : data.theta_deg, yref: 'paper', y0: 0, y1: 1, line: { width: 1, dash: 'dot', color: DATA.marker } }],
              }}
            />
          </div>
        )}
        <div className="flex shrink-0 flex-col border-t border-line">
          <div className="flex shrink-0 items-center gap-2 bg-panel px-2 py-1">
            <span className="text-small font-semibold tracking-wide text-muted uppercase">{t('rc.layers')}</span>
            <Button size="sm" onClick={() => set({ layers: [...st.layers, newLayer(crossed ? 'pattern' : 'lamellar', cell[0], cell[1])] }, 'Add grating layer')}>
              <Plus size={12} /> {t('rc.addLayer')}
            </Button>
            <span className="truncate text-caption text-faint">{t('rc.layersHint')}</span>
          </div>
          <div className={`grid ${crossed ? 'grid-cols-[minmax(0,1fr)_220px]' : 'grid-cols-[minmax(0,1fr)_200px]'} gap-px bg-line`}>
            <div className="min-h-0 overflow-auto bg-panel">
              <table className="eng-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>{t('rc.kind')}</th>
                    <th>{t('rc.thickness')}</th>
                    <th title={t('rc.fillHint')}>{t('rc.fill')}</th>
                    <th>{t('rc.slices')}</th>
                    <th>{t('rc.ridge')}</th>
                    <th title={t('rc.grooveHint')}>{t('rc.groove')}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {st.layers.map((L, i) => (
                    <LayerRow
                      key={i}
                      L={L}
                      i={i}
                      n={st.layers.length}
                      names={names}
                      crossed={crossed}
                      selected={i === sel}
                      cell={cell}
                      set={(p) => setLayer(i, p)}
                      remove={() => set({ layers: st.layers.filter((_, k) => k !== i) }, 'Remove grating layer')}
                      move={(d) => moveLayer(i, d)}
                      select={() => setSel(i)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
            <div className="min-h-[140px] bg-panel" title={crossed ? t('rc.topViewHint', { n: sel + 1 }) : t('rc.structureHint')}>
              {struct && struct.depth > 0 && (
                <Plot
                  data={[{ type: 'scatter', x: [0, 2 * data!.structure.period_um], y: [0, -struct.depth], mode: 'markers', marker: { opacity: 0 }, hoverinfo: 'skip', showlegend: false }]}
                  layout={{ margin: { l: 38, r: 6, t: 6, b: 30 }, shapes: struct.shapes, xaxis: { title: { text: 'x (µm)' }, range: [0, 2 * data!.structure.period_um], showgrid: false }, yaxis: { title: { text: 'z (µm)' }, range: [-struct.depth, 0], showgrid: false } }}
                />
              )}
              {top && data && (
                <Plot
                  data={[{ type: 'scatter', x: [0, 2 * data.structure.period_um], y: [0, 2 * (data.structure.period_y_um ?? data.structure.period_um)], mode: 'markers', marker: { opacity: 0 }, hoverinfo: 'skip', showlegend: false }]}
                  layout={{
                    margin: { l: 38, r: 6, t: 6, b: 30 },
                    shapes: top,
                    xaxis: { title: { text: 'x (µm)' }, range: [0, 2 * data.structure.period_um], showgrid: false, zeroline: false },
                    yaxis: { title: { text: 'y (µm)' }, range: [0, 2 * (data.structure.period_y_um ?? data.structure.period_um)], showgrid: false, zeroline: false, scaleanchor: 'x' },
                  }}
                />
              )}
            </div>
          </div>
        </div>
        {crossed && selLayer?.kind === 'pattern' && <ShapesEditor L={selLayer} i={sel} names={names} cell={cell} set={(shapes) => setLayer(sel, { shapes })} />}
        {data && <Notes notes={data.notes} />}
      </div>
    </AnalysisFrame>
  )
}
