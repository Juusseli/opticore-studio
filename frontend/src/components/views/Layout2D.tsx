import { isRunning, useOptStore } from '../../store/optStore'
import { Box, Maximize2, Palette, Ruler, Tag, ZoomIn, ZoomOut } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fieldColor, fmt, wavelengthColor } from '../../lib/format'
import { useT } from '../../lib/i18n'
import type { Evaluation, OpticalSystem, SurfaceGeometry, NonSeqResult } from '../../lib/types'
import { useEngineStore } from '../../store/engineStore'
import { selectDetectors, selectSources, useProjectStore } from '../../store/projectStore'
import { framePoint, placePoint, surfaceFrames } from '../../lib/placement'
import { useUiStore } from '../../store/uiStore'
import { Badge, IconButton } from '../common/ui'
import { ViewState } from './ViewState'
import { sagXY } from '../../lib/sag'
import { fitView, needsRefit } from '../../lib/framing'
import { api } from '../../lib/api'
import type { CadSectionResult } from '../../lib/types'
import { useMeasureStore } from '../../store/measureStore'
import { DATA } from '../../lib/palette'

type V3 = [number, number, number]

function toGlobal(s: SurfaceGeometry, y: number, z: number): V3 {
  const m = s.matrix
  const o = s.origin
  return [o[0] + m[0][1] * y + m[0][2] * z, o[1] + m[1][1] * y + m[1][2] * z, o[2] + m[2][1] * y + m[2][2] * z]
}

/** Sag of the y-z section at local height y (signed: Zernike surfaces need not be symmetric). */
const sagAt = (s: SurfaceGeometry, y: number) => sagXY(s, 0, y)

function niceStep(raw: number): number {
  const p = Math.pow(10, Math.floor(Math.log10(raw)))
  const f = raw / p
  return (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * p
}

interface ViewBox {
  cx: number // world z at centre
  cy: number // world y at centre
  scale: number // px per mm
}

function elementPolygon(front: SurfaceGeometry, back: SurfaceGeometry): V3[] | null {
  if (front.profile.length < 2 || back.profile.length < 2) return null
  const hf = front.semi_diameter
  const hb = back.semi_diameter
  const hm = Math.max(hf, hb)
  const pts: V3[] = []
  for (const [y, z] of front.profile) pts.push(toGlobal(front, y, z))
  // top edge: step to the larger semi-diameter
  if (hf < hm) pts.push(toGlobal(front, hm, sagAt(front, hf)))
  if (hb < hm) pts.push(toGlobal(back, hm, sagAt(back, hb)))
  for (let i = back.profile.length - 1; i >= 0; i--) pts.push(toGlobal(back, back.profile[i][0], back.profile[i][1]))
  if (hb < hm) pts.push(toGlobal(back, -hm, sagAt(back, -hb)))
  if (hf < hm) pts.push(toGlobal(front, -hm, sagAt(front, -hf)))
  return pts
}

export function Layout2D() {
  const t = useT()
  const evaluation = useEngineStore((s) => s.evaluation)
  const preview = useEngineStore((s) => s.preview)
  const system = useProjectStore((s) => s.project.system)
  const selection = useProjectStore((s) => s.selection)
  const select = useProjectStore((s) => s.select)
  const showRays = useUiStore((s) => s.showRays)
  if (!evaluation) return <ViewState kind="layout" />
  return <Layout2DInner ev={evaluation} system={preview ?? system} selection={selection} onSelect={select} showRays={showRays} preview={!!preview} t={t} />
}

function Layout2DInner({
  ev,
  system,
  selection,
  onSelect,
  showRays,
  preview,
  t,
}: {
  ev: Evaluation
  system: OpticalSystem
  selection: number[]
  onSelect: (i: number, mode?: 'single' | 'toggle' | 'range') => void
  showRays: boolean
  preview: boolean
  t: (k: string) => string
}) {
  const wrap = useRef<HTMLDivElement>(null)
  const optRunning = useOptStore(isRunning)
  const [size, setSize] = useState({ w: 800, h: 400 })
  const [vb, setVb] = useState<ViewBox | null>(null)
  const [colorBy, setColorBy] = useState<'field' | 'wavelength'>('field')
  const [labels, setLabels] = useState(true)
  const [measure, setMeasure] = useState(false)
  const frames = useMemo(() => surfaceFrames(ev.surfaces), [ev]) // anchored sources and detectors
  const [m, setM] = useState<{ a: [number, number]; b: [number, number] } | null>(null)
  const [hover, setHover] = useState<number | null>(null)
  const drag = useRef<{ x: number; y: number; vb: ViewBox; moved: boolean } | null>(null)
  const openCount = useProjectStore((s) => s.openCount)
  const userView = useRef(false) // the user zoomed or panned since the last fit
  const seenOpen = useRef(-1)
  const seenSize = useRef('')
  // CAD models cut by the layout plane (global x = 0), computed by the engine from the exact geometry
  const cad = useProjectStore((s) => s.project.cad_assets)
  // non-sequential sources, detectors and the ray paths of the last non-sequential analysis
  const nsSources = useProjectStore(selectSources)
  const nsDetectors = useProjectStore(selectDetectors)
  const nsPaths = useEngineStore((s) => (s.analyses.nonseq?.data as NonSeqResult | null | undefined)?.paths ?? null)
  const ownSources = nsSources.some((x) => x.enabled)
  const selectedPart = useMeasureStore((s) => s.selected)
  const [showCad, setShowCad] = useState(true)
  const [sec, setSec] = useState<CadSectionResult | null>(null)
  const cadKey = cad.filter((a) => a.visible).map((a) => [a.id, a.mesh.triangles, JSON.stringify(a.transform), (a.hidden_parts ?? []).join(',')].join(':')).join('|')
  useEffect(() => {
    const vis = cad.filter((a) => a.visible)
    if (!showCad || !vis.length) return setSec(null)
    const ctrl = new AbortController()
    const h = setTimeout(() => {
      api
        .cadSection(vis, ctrl.signal)
        .then(setSec)
        .catch(() => setSec(null))
    }, 250)
    return () => {
      clearTimeout(h)
      ctrl.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cadKey, showCad])

  useEffect(() => {
    const el = wrap.current
    if (!el) return
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    setSize({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])

  // world bounds of geometry + rays
  const bounds = useMemo(() => {
    let zmin = Infinity,
      zmax = -Infinity,
      ymin = Infinity,
      ymax = -Infinity
    const add = (p: V3) => {
      zmin = Math.min(zmin, p[2])
      zmax = Math.max(zmax, p[2])
      ymin = Math.min(ymin, p[1])
      ymax = Math.max(ymax, p[1])
    }
    ev.surfaces.forEach((s, i) => {
      if (i === 0 && system.surfaces[0].thickness === null) return
      for (const [y, z] of s.profile) add(toGlobal(s, y, z))
      add(toGlobal(s, 0, 0))
    })
    for (const r of ev.rays) for (const p of r.points.slice(system.surfaces[0].thickness === null ? 0 : 0)) add(p)
    for (const x of nsSources) if (x.kind !== 'system_field') add(x.placement.position)
    for (const d of nsDetectors) add(d.placement.position)
    if (!Number.isFinite(zmin)) return { zmin: -10, zmax: 10, ymin: -10, ymax: 10 }
    return { zmin, zmax, ymin, ymax }
  }, [ev, system.surfaces, nsSources, nsDetectors])

  // what is framed: the geometry and rays, with the lead-in of rays from an object at infinity
  const content = useMemo(() => {
    const lead = system.surfaces[0].thickness === null ? (bounds.zmax - bounds.zmin) * 0.12 : 0
    return { ...bounds, zmin: bounds.zmin - lead }
  }, [bounds, system.surfaces])
  const fit = useCallback(() => {
    userView.current = false
    setVb(fitView(content, size.w, size.h))
  }, [content, size])

  // framing: fit when a project is opened or the pane is resized; otherwise refit only when the system
  // grows out of view or shrinks to a small part of it, and never after the user zoomed or panned
  useEffect(() => {
    const sizeKey = `${Math.round(size.w)}x${Math.round(size.h)}`
    const opened = seenOpen.current !== openCount
    const resized = seenSize.current !== sizeKey
    seenOpen.current = openCount
    seenSize.current = sizeKey
    if (!vb || opened) return fit()
    if (userView.current) return
    if (resized || needsRefit(content, vb, size.w, size.h)) fit()
  }, [fit, content, openCount, size, vb])

  if (!vb) return <div ref={wrap} className="h-full w-full" />

  const X = (z: number) => (z - vb.cx) * vb.scale + size.w / 2
  const Y = (y: number) => size.h / 2 - (y - vb.cy) * vb.scale
  const toWorld = (px: number, py: number): [number, number] => [(px - size.w / 2) / vb.scale + vb.cx, (size.h / 2 - py) / vb.scale + vb.cy]
  const path = (pts: V3[]) => pts.map((p, i) => `${i ? 'L' : 'M'}${X(p[2]).toFixed(2)},${Y(p[1]).toFixed(2)}`).join('')

  // grid
  const step = niceStep(60 / vb.scale)
  const [z0, y1] = toWorld(0, 0)
  const [z1, y0] = toWorld(size.w, size.h)
  const gridZ: number[] = []
  for (let z = Math.ceil(z0 / step) * step; z <= z1; z += step) gridZ.push(z)
  const gridY: number[] = []
  for (let y = Math.ceil(y0 / step) * step; y <= y1; y += step) gridY.push(y)

  const infinite = system.surfaces[0].thickness === null
  const lead = (bounds.zmax - bounds.zmin) * 0.12

  const onWheel = (e: React.WheelEvent) => {
    const rect = wrap.current!.getBoundingClientRect()
    const px = e.clientX - rect.left
    const py = e.clientY - rect.top
    const [wz, wy] = toWorld(px, py)
    const f = Math.exp(-e.deltaY * 0.0015)
    const scale = vb.scale * f
    userView.current = true
    setVb({ scale, cx: wz - (px - size.w / 2) / scale, cy: wy + (py - size.h / 2) / scale })
  }

  const onDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return
    const rect = wrap.current!.getBoundingClientRect()
    if (measure) {
      const w = toWorld(e.clientX - rect.left, e.clientY - rect.top)
      setM({ a: w, b: w })
      drag.current = { x: e.clientX, y: e.clientY, vb, moved: false }
      return
    }
    drag.current = { x: e.clientX, y: e.clientY, vb, moved: false }
  }
  const onMove = (e: React.MouseEvent) => {
    const d = drag.current
    if (!d) return
    if (Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) > 3) d.moved = true
    if (measure && m) {
      const rect = wrap.current!.getBoundingClientRect()
      setM({ a: m.a, b: toWorld(e.clientX - rect.left, e.clientY - rect.top) })
      return
    }
    if (!d.moved) return
    userView.current = true
    setVb({ ...d.vb, cx: d.vb.cx - (e.clientX - d.x) / d.vb.scale, cy: d.vb.cy + (e.clientY - d.y) / d.vb.scale })
  }
  const onUp = () => {
    drag.current = null
  }

  const clickSurface = (i: number, e: React.MouseEvent) => {
    if (drag.current?.moved) return
    e.stopPropagation()
    onSelect(i, e.shiftKey ? 'range' : e.ctrlKey || e.metaKey ? 'toggle' : 'single')
  }

  const wl = system.wavelengths
  const rayColor = (f: number, w: number) => (colorBy === 'field' ? fieldColor(f) : wavelengthColor(wl[w]?.value ?? 0.55))

  const scaleBarMm = niceStep(120 / vb.scale)
  const hs = hover !== null ? ev.surfaces[hover] : null

  return (
    <div ref={wrap} className="relative h-full w-full overflow-hidden select-none" onWheel={onWheel} onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp} onDoubleClick={fit} style={{ cursor: measure ? 'crosshair' : drag.current ? 'grabbing' : 'grab' }}>
      <svg width={size.w} height={size.h} className="absolute inset-0">
        {/* grid */}
        <g stroke="var(--c-grid)" strokeWidth={1}>
          {gridZ.map((z) => (
            <line key={'gz' + z} x1={X(z)} x2={X(z)} y1={0} y2={size.h} />
          ))}
          {gridY.map((y) => (
            <line key={'gy' + y} y1={Y(y)} y2={Y(y)} x1={0} x2={size.w} />
          ))}
        </g>
        <line x1={0} x2={size.w} y1={Y(0)} y2={Y(0)} stroke="var(--c-axis)" strokeDasharray="6 4" strokeWidth={1} />

        {/* lens solids */}
        {ev.elements.map((el) => {
          const poly = elementPolygon(ev.surfaces[el.front], ev.surfaces[el.back])
          if (!poly) return null
          return <path key={`el${el.front}`} d={path(poly) + 'Z'} fill="var(--c-glass)" stroke="none" />
        })}

        {/* CAD sections in the layout plane */}
        {showCad &&
          sec?.assets.map((sa) => {
            const a = cad.find((x) => x.id === sa.asset_id)
            if (!a) return null
            return sa.parts.map((pt, k) => {
              const sel = selectedPart?.asset_id === a.id && (selectedPart.part_id === null || (pt.part_id !== null && (pt.part_id === selectedPart.part_id || pt.part_id.startsWith(selectedPart.part_id + '.'))))
              return (
                <path
                  key={`cad${a.id}${k}`}
                  d={pt.polylines.map((pl) => pl.map((q, j) => `${j ? 'L' : 'M'}${X(q[2]).toFixed(2)},${Y(q[1]).toFixed(2)}`).join('')).join('')}
                  fill="none"
                  stroke={sel ? 'var(--c-accent)' : a.color}
                  strokeWidth={sel ? 2.2 : 1.3}
                  strokeOpacity={0.95}
                >
                  <title>{a.name}{pt.part_id ? ` / ${pt.part_id}` : ''}</title>
                </path>
              )
            })
          })}

        {/* rays */}
        {showRays &&
          ev.rays.map((r, k) => {
            if (r.points.length < 1) return null
            let pts = r.points
            if (infinite) {
              const p = r.points[1] ?? r.points[0]
              const d = r.start_dir
              const L = lead + Math.max(0, p[2] - bounds.zmin)
              pts = [[p[0] - d[0] * (L / Math.max(d[2], 1e-6)), p[1] - d[1] * (L / Math.max(d[2], 1e-6)), p[2] - L] as V3, ...r.points.slice(1)]
            }
            const failed = r.status !== 'ok'
            return <path key={k} d={path(pts)} fill="none" stroke={rayColor(r.field, r.wavelength)} strokeOpacity={failed ? 0.35 : 0.85} strokeDasharray={failed ? '3 3' : undefined} strokeWidth={1} />
          })}

        {/* non-sequential: ray paths of the last analysis, sources (orange) and detectors (green), projected on y-z */}
        {ownSources &&
          nsPaths?.map((p, k) => <path key={'nsp' + k} d={path(p.points as V3[])} fill="none" stroke={(p.scatters ?? 0) > 0 ? DATA.scatter : p.reflections > 0 ? DATA.ghost : DATA.direct} strokeOpacity={0.75} strokeWidth={1} />)}
        {nsSources
          .filter((x) => x.kind !== 'system_field')
          .map((x) => {
            const beam = x.kind === 'gaussian_beam'
            const half = beam ? (x.beam_waist_y ?? 0.5) : x.shape === 'point' ? 0 : x.shape === 'disk' || x.shape === 'sphere' ? x.size_x : x.size_y / 2
            const L = Math.max(14 / vb.scale, 2 * half)
            const th = beam || x.angular === 'collimated' ? 0 : x.angular === 'cone' ? x.half_angle_deg : x.angular === 'gaussian' ? Math.min(x.half_angle_deg, Math.max(x.gaussian_x_deg, x.gaussian_y_deg)) : x.angular === 'isotropic' ? 90 : Math.min(x.half_angle_deg, 60)
            const a = (th * Math.PI) / 180
            const pts = (loc: V3[]) => loc.map((q) => placePoint(x.placement, q, frames))
            const face = pts([
              [0, -half, 0],
              [0, half, 0],
            ])
            const cone = pts([
              [0, L * Math.sin(a), L * Math.cos(a)],
              [0, 0, 0],
              [0, -L * Math.sin(a), L * Math.cos(a)],
            ])
            const c = placePoint(x.placement, [0, 0, 0], frames)
            // the emission direction (local +z) as an arrow, and a line to the aim point
            const A = 1.6 * L
            const arrow = pts([
              [0, 0, 0],
              [0, 0, A],
            ])
            const head = pts([
              [L * 0.18, 0, A * 0.82],
              [0, 0, A],
              [-L * 0.18, 0, A * 0.82],
            ])
            const head2 = pts([
              [0, L * 0.18, A * 0.82],
              [0, 0, A],
              [0, -L * 0.18, A * 0.82],
            ])
            const aimG = x.placement.aim ? framePoint(x.placement, x.placement.aim, frames) : null
            return (
              <g key={'nss' + x.id} opacity={x.enabled ? 1 : 0.4}>
                <circle cx={X(c[2])} cy={Y(c[1])} r={3} fill={DATA.source} />
                {half > 0 && <path d={path(face)} stroke={DATA.source} strokeWidth={2.2} fill="none" />}
                {th > 0 && <path d={path(cone)} stroke={DATA.source} strokeWidth={1} strokeDasharray="3 2" fill="none" />}
                {th < 90 && (
                  <>
                    <path d={path(arrow)} stroke={DATA.source} strokeWidth={1.4} fill="none" />
                    <path d={path(head)} stroke={DATA.source} strokeWidth={1.4} fill="none" />
                    <path d={path(head2)} stroke={DATA.source} strokeWidth={1.4} fill="none" />
                  </>
                )}
                {aimG && (
                  <>
                    <path d={path([c, aimG])} stroke={DATA.source} strokeWidth={1} strokeDasharray="1 3" fill="none" />
                    <circle cx={X(aimG[2])} cy={Y(aimG[1])} r={2.5} fill="none" stroke={DATA.source} />
                  </>
                )}
                <text x={X(c[2])} y={Y(c[1]) - 8} fontSize={10} fill={DATA.source} textAnchor="middle">
                  {x.name}
                </text>
              </g>
            )
          })}
        {nsDetectors.map((d) => {
          const half = d.shape === 'circle' ? d.size_x : d.size_y / 2
          const face = [placePoint(d.placement, [0, -half, 0], frames), placePoint(d.placement, [0, half, 0], frames)]
          const c = placePoint(d.placement, [0, 0, 0], frames)
          const tick = Math.max(6 / vb.scale, half * 0.3)
          const back = placePoint(d.placement, [0, 0, -tick], frames)
          return (
            <g key={'nsd' + d.id} opacity={d.enabled ? 1 : 0.4}>
              <path d={path(face)} stroke={DATA.detector} strokeWidth={3} fill="none" />
              <path d={path([back, c])} stroke={DATA.detector} strokeWidth={1} fill="none" />
              <text x={X(c[2])} y={Y(Math.max(face[0][1], face[1][1])) - 6} fontSize={10} fill={DATA.detector} textAnchor="middle">
                {d.name}
              </text>
            </g>
          )
        })}

        {/* surfaces */}
        {ev.surfaces.map((s, i) => {
          if (s.type === 'coordinate_break' || s.profile.length < 2) return null
          if (i === 0 && infinite) return null
          const pts = s.profile.map(([y, z]) => toGlobal(s, y, z))
          const sel = selection.includes(i)
          const isImg = i === ev.surfaces.length - 1
          const ideal = !!s.is_ideal
          const dummy = !ideal && !s.is_mirror && !isImg && i > 0 && !ev.elements.some((e) => e.front === i || e.back === i) && !s.is_stop
          const stroke = sel ? 'var(--c-accent)' : ideal ? 'var(--c-ok)' : s.is_mirror ? 'var(--c-text)' : isImg ? 'var(--c-warn)' : 'var(--c-glass-edge)'
          const d = path(pts)
          return (
            <g key={'s' + i} onMouseDown={(e) => !measure && e.stopPropagation()} onClick={(e) => clickSurface(i, e)} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} style={{ cursor: 'pointer' }}>
              <path d={d} stroke="transparent" strokeWidth={12} fill="none" />
              <path d={d} stroke={stroke} strokeWidth={sel ? 2.4 : s.is_mirror ? 2.2 : 1.4} fill="none" strokeDasharray={dummy ? '4 3' : undefined} strokeOpacity={dummy && !sel ? 0.6 : 1} />
              {s.is_mirror && (
                <path
                  d={(() => {
                    // hatch marks behind the mirror
                    let out = ''
                    for (let k = 0; k < pts.length; k += 4) {
                      const p = pts[k]
                      out += `M${X(p[2])},${Y(p[1])}l6,-6`
                    }
                    return out
                  })()}
                  stroke={stroke}
                  strokeWidth={1}
                  strokeOpacity={0.6}
                />
              )}
              {ideal &&
                s.semi_diameter > 0 &&
                // thin-lens symbol: arrowheads pointing outwards (converging) or inwards (diverging)
                [1, -1].map((sg) => {
                  const tip = toGlobal(s, sg * s.semi_diameter, 0)
                  const inner = toGlobal(s, sg * s.semi_diameter * 0.9, 0)
                  const tx = X(tip[2])
                  const ty = Y(tip[1])
                  let ux = tx - X(inner[2])
                  let uy = ty - Y(inner[1])
                  const L = Math.hypot(ux, uy) || 1
                  ux /= L
                  uy /= L
                  const conv = (s.focal_length ?? 0) >= 0
                  const a = 7
                  const bx = conv ? tx - ux * a : tx + ux * a
                  const by = conv ? ty - uy * a : ty + uy * a
                  return <path key={'ideal' + sg} d={`M${bx - uy * a * 0.7},${by + ux * a * 0.7}L${tx},${ty}L${bx + uy * a * 0.7},${by - ux * a * 0.7}`} stroke={stroke} strokeWidth={1.6} fill="none" />
                })}
              {s.is_stop &&
                [1, -1].map((sg) => {
                  const g = toGlobal(s, sg * s.semi_diameter, sagAt(s, s.semi_diameter))
                  return <path key={sg} d={`M${X(g[2]) - 5},${Y(g[1]) - sg * 9}L${X(g[2])},${Y(g[1])}L${X(g[2]) + 5},${Y(g[1]) - sg * 9}`} stroke="var(--c-accent)" strokeWidth={1.6} fill="none" />
                })}
              {labels && (
                <text x={X(toGlobal(s, s.semi_diameter, sagAt(s, s.semi_diameter))[2])} y={Y(toGlobal(s, s.semi_diameter, sagAt(s, s.semi_diameter))[1]) - 6} fontSize={10} fill={sel ? 'var(--c-accent)' : 'var(--c-muted)'} textAnchor="middle">
                  {i}
                </text>
              )}
            </g>
          )
        })}

        {/* measurement */}
        {m && (
          <g>
            <line x1={X(m.a[0])} y1={Y(m.a[1])} x2={X(m.b[0])} y2={Y(m.b[1])} stroke="var(--c-warn)" strokeWidth={1.4} strokeDasharray="5 3" />
            <circle cx={X(m.a[0])} cy={Y(m.a[1])} r={3} fill="var(--c-warn)" />
            <circle cx={X(m.b[0])} cy={Y(m.b[1])} r={3} fill="var(--c-warn)" />
          </g>
        )}

        {/* scale bar */}
        <g transform={`translate(${16},${size.h - 18})`}>
          <line x1={0} x2={scaleBarMm * vb.scale} y1={0} y2={0} stroke="var(--c-text)" strokeWidth={2} />
          <line x1={0} x2={0} y1={-4} y2={4} stroke="var(--c-text)" />
          <line x1={scaleBarMm * vb.scale} x2={scaleBarMm * vb.scale} y1={-4} y2={4} stroke="var(--c-text)" />
          <text x={scaleBarMm * vb.scale + 6} y={4} fontSize={10.5} fill="var(--c-muted)">
            {fmt(scaleBarMm)} mm
          </text>
        </g>
      </svg>

      {/* overlay toolbar */}
      <div className="absolute top-2 right-2 flex items-center gap-0.5 rounded-lg border border-line bg-panel/90 p-0.5 shadow backdrop-blur" onMouseDown={(e) => e.stopPropagation()}>
        <IconButton
          title={t('l2.zoomIn')}
          onClick={() => {
            userView.current = true
            setVb({ ...vb, scale: vb.scale * 1.25 })
          }}
        >
          <ZoomIn size={14} />
        </IconButton>
        <IconButton
          title={t('l2.zoomOut')}
          onClick={() => {
            userView.current = true
            setVb({ ...vb, scale: vb.scale / 1.25 })
          }}
        >
          <ZoomOut size={14} />
        </IconButton>
        <IconButton title={t('l2.fit')} onClick={fit}>
          <Maximize2 size={14} />
        </IconButton>
        <IconButton title={colorBy === 'field' ? t('l2.byWavelength') : t('l2.byField')} onClick={() => setColorBy(colorBy === 'field' ? 'wavelength' : 'field')} active={colorBy === 'wavelength'}>
          <Palette size={14} />
        </IconButton>
        <IconButton title={t('l2.labels')} onClick={() => setLabels(!labels)} active={labels}>
          <Tag size={14} />
        </IconButton>
        {cad.length > 0 && (
          <IconButton title={t('cad.sectionToggle')} onClick={() => setShowCad(!showCad)} active={showCad}>
            <Box size={14} />
          </IconButton>
        )}
        <IconButton
          title={t('l2.measure')}
          active={measure}
          onClick={() => {
            setMeasure(!measure)
            setM(null)
          }}
        >
          <Ruler size={14} />
        </IconButton>
      </div>

      <div className="pointer-events-none absolute top-2 left-2 flex flex-col gap-1">
        <div className="flex items-center gap-1.5">
          <Badge tone="accent">Y–Z {t('view.layout2d')}</Badge>
          {preview && <Badge tone="warn">{t(optRunning ? 'opt.preview' : 'opt.previewResult')}</Badge>}
          {!ev.axial && <Badge>{t('l2.nonAxial')}</Badge>}
        </div>
        {m && (
          <div className="rounded-md border border-line bg-panel/90 px-2 py-1 num text-small">
            Δz {fmt(m.b[0] - m.a[0], 5)} mm · Δy {fmt(m.b[1] - m.a[1], 5)} mm · d {fmt(Math.hypot(m.b[0] - m.a[0], m.b[1] - m.a[1]), 5)} mm · {fmt((Math.atan2(m.b[1] - m.a[1], m.b[0] - m.a[0]) * 180) / Math.PI, 4)}°
          </div>
        )}
        {hs && !m && (
          <div className="rounded-md border border-line bg-panel/90 px-2 py-1 text-small">
            <span className="font-semibold">
              {t('c.surface')} {hover}
            </span>{' '}
            {system.surfaces[hover!]?.label} · R {s2r(system, hover!)} · SD {fmt(hs.semi_diameter, 5)} mm · z {fmt(hs.origin[2], 6)} mm
          </div>
        )}
      </div>
      <div className="pointer-events-none absolute bottom-2 right-3 flex gap-2 text-caption text-muted">
        {colorBy === 'field'
          ? system.fields.map((f, i) => (
              <span key={i} className="flex items-center gap-1">
                <span className="inline-block h-0.75 w-3 rounded" style={{ background: fieldColor(i) }} />
                F{i + 1} ({fmt(f.y, 4)}
                {system.field_type === 'angle' ? '°' : ' mm'})
              </span>
            ))
          : wl.map((w, i) => (
              <span key={i} className="flex items-center gap-1">
                <span className="inline-block h-0.75 w-3 rounded" style={{ background: wavelengthColor(w.value) }} />
                {fmt(w.value * 1000, 5)} nm
              </span>
            ))}
      </div>
    </div>
  )
}

function s2r(system: OpticalSystem, i: number) {
  const r = system.surfaces[i]?.radius
  return r === null || r === undefined ? '∞' : fmt(r, 6)
}
