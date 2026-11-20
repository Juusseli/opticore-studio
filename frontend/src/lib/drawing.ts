// ISO 10110 element drawings (ADR-030). Every number comes from the engine's element data
// (backend analysis/elements.py); this module only lays the drawing out as an A4-landscape SVG in mm.
// The drawing carries its data as JSON in <metadata>, so the values on a drawing can be read back.
import { fmt, fmtFixed } from './format'
import { DRAWING } from './palette'
import type { ElementSurfaceTolerances, LensElement } from './types'

export type DrawingT = (key: string, vars?: Record<string, string | number>) => string

/** The data a drawing states (and embeds): prescription, mechanics, material and tolerances. */
export interface DrawingMeta {
  format: 'opticore-element-drawing'
  version: 1
  element: string
  surfaces: [number, number]
  surface_ids: [string, string]
  radii_mm: [number | null, number | null]
  conics: [number, number]
  aspheric: [number[], number[]]
  center_thickness_mm: number
  clear_diameters_mm: [number, number]
  outer_diameter_mm: number
  edge_thickness_mm: number
  chamfers_mm: [number, number]
  material: string
  nd: number
  vd: number
  glass_code: string
  coatings: [string | null, string | null]
  tolerances: LensElement['tolerances']
}

export function drawingMeta(el: LensElement): DrawingMeta {
  return {
    format: 'opticore-element-drawing',
    version: 1,
    element: el.name,
    surfaces: el.surfaces,
    surface_ids: el.surface_ids,
    radii_mm: el.radii_mm,
    conics: el.conics,
    aspheric: el.aspheric,
    center_thickness_mm: el.center_thickness_mm,
    clear_diameters_mm: [2 * el.clear_semi_diameters_mm[0], 2 * el.clear_semi_diameters_mm[1]],
    outer_diameter_mm: 2 * el.rim_radius_mm,
    edge_thickness_mm: el.edge_thickness_mm,
    chamfers_mm: el.chamfers_mm,
    material: el.material.name,
    nd: el.material.nd,
    vd: el.material.vd,
    glass_code: el.material.code,
    coatings: el.coatings,
    tolerances: el.tolerances,
  }
}

const META_RE = /<metadata id="opticore-element">([\s\S]*?)<\/metadata>/

/** The data embedded in a drawing made by elementDrawingSvg (null if there is none). */
export function parseDrawingMeta(svg: string): DrawingMeta | null {
  const m = META_RE.exec(svg)
  if (!m) return null
  const json = m[1].replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
  return JSON.parse(json) as DrawingMeta
}

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/** Drawing scales (drawing mm per part mm), largest first. */
const SCALES = [10, 5, 4, 2.5, 2, 1.5, 1, 0.5, 0.4, 0.25, 0.2, 0.1, 0.05]
const scaleLabel = (s: number) => (s >= 1 ? `${fmt(s, 3)}:1` : `1:${fmt(1 / s, 3)}`)

/** Radius with its ISO sense: CX (convex) or CC (concave) as seen from outside the element. */
export function radiusText(r: number | null, side: 0 | 1): string {
  if (r === null) return 'R ∞'
  const convex = side === 0 ? r > 0 : r < 0
  return `R ${fmtFixed(Math.abs(r), 4)} ${convex ? 'CX' : 'CC'}`
}

const tolPm = (lo: number, hi: number, d = 3) => (Math.abs(lo + hi) < 1e-15 ? `± ${fmt(hi, d)}` : `${hi >= 0 ? '+' : ''}${fmt(hi, d)} / ${fmt(lo, d)}`)

function surfaceLines(el: LensElement, side: 0 | 1, t: DrawingT): string[] {
  const tol: ElementSurfaceTolerances = el.tolerances.surfaces?.[side] ?? {}
  const r = el.radii_mm[side]
  const lines = [`${radiusText(r, side)}${tol.radius ? `  ${tolPm(tol.radius[0], tol.radius[1])}` : ''}`]
  if (el.conics[side] !== 0) lines.push(`k = ${fmt(el.conics[side], 6)}`)
  if (el.aspheric[side].some((a) => a !== 0)) lines.push(t('dw.aspheric', { n: el.aspheric[side].length }))
  if (el.types[side] === 'zernike') lines.push(t('dw.zernike'))
  if (el.types[side] === 'qcon' || el.types[side] === 'qbfs') lines.push(t('dw.qtype', { kind: el.types[side] === 'qcon' ? 'Qcon' : 'Qbfs' }))
  if (el.types[side] === 'xy_polynomial') lines.push(t('dw.xy'))
  if (el.types[side] === 'odd_asphere') lines.push(t('dw.odd'))
  lines.push(`Øe ${fmtFixed(2 * el.clear_semi_diameters_mm[side], 2)}`)
  const c = el.chamfers_mm[side]
  lines.push(c > 0 ? `${t('dw.chamfer')} ${fmt(c, 3)} × 45°` : `${t('dw.chamfer')} —`)
  lines.push(tol.iso_3 ?? `3/ ${t('dw.notSpecified')}`)
  if (tol.zernike_um?.length) lines.push(tol.zernike_um.map((z) => `Z${z.term} ± ${fmt(z.max, 3)} µm`).join(', '))
  lines.push(tol.iso_4 ?? `4/ ${t('dw.notSpecified')}`)
  if (tol.decenter_mm) lines.push(`${t('dw.decenter')} ± ${fmt(tol.decenter_mm, 3)}`)
  lines.push(`${t('dw.coating')}: ${el.coatings[side] ?? '—'}`)
  if (el.cemented_surfaces.includes(el.surfaces[side])) lines.push(t('dw.cemented'))
  return lines
}

function materialLines(el: LensElement, t: DrawingT): string[] {
  const m = el.material
  const tl = el.tolerances
  return [
    `${m.name}${m.catalog ? ` (${m.catalog})` : ''}`,
    `nd = ${fmtFixed(m.nd, 5)}${tl.nd ? ` ± ${fmt(tl.nd, 3)}` : ''}`,
    `νd = ${fmtFixed(m.vd, 2)}${tl.vd ? ` ± ${fmt(tl.vd, 3)}` : ''}`,
    `${t('dw.glassCode')} ${m.code}`,
    `0/ —   1/ —   2/ —`,
    el.mass_g !== null ? `${t('dw.mass')} ${fmt(el.mass_g, 4)} g` : `${t('dw.mass')} —`,
  ]
}

/** A4-landscape ISO 10110 drawing of one lens element as an SVG document (units mm). */
export function elementDrawingSvg(el: LensElement, o: { project: string; date: string; t: DrawingT }): string {
  const { t } = o
  const W = 297
  const H = 210
  const zs = el.outline.map((p) => p[1])
  const zmin = Math.min(...zs)
  const zmax = Math.max(...zs)
  const R = el.rim_radius_mm
  // the section fits 150 × 74 mm, leaving room above for the title and the radius labels
  const scale = SCALES.find((s) => (zmax - zmin) * s <= 150 && 2 * R * s <= 74) ?? SCALES[SCALES.length - 1]
  const cx = 105
  const cy = 66
  const X = (z: number) => cx + (z - (zmin + zmax) / 2) * scale
  const Y = (r: number) => cy - r * scale
  const half = el.outline.map(([r, z]) => `${X(z).toFixed(3)},${Y(r).toFixed(3)}`)
  const mirror = [...el.outline].reverse().map(([r, z]) => `${X(z).toFixed(3)},${Y(-r).toFixed(3)}`)
  const section = [...half, ...mirror].join(' ')
  const xL = X(zmin)
  const xR = X(zmax)
  const yTop = Y(R)
  const yBot = Y(-R)
  const parts: string[] = []
  const line = (x1: number, y1: number, x2: number, y2: number, w = 0.25, color: string = DRAWING.line, extra = '') =>
    parts.push(`<line x1="${x1.toFixed(3)}" y1="${y1.toFixed(3)}" x2="${x2.toFixed(3)}" y2="${y2.toFixed(3)}" stroke="${color}" stroke-width="${w}"${extra}/>`)
  const text = (x: number, y: number, s: string, size = 2.5, anchor = 'start', extra = '') =>
    parts.push(`<text x="${x.toFixed(3)}" y="${y.toFixed(3)}" font-size="${size}" text-anchor="${anchor}" fill="${DRAWING.line}"${extra}>${esc(s)}</text>`)
  const dim = (x1: number, y1: number, x2: number, y2: number) =>
    parts.push(`<line x1="${x1.toFixed(3)}" y1="${y1.toFixed(3)}" x2="${x2.toFixed(3)}" y2="${y2.toFixed(3)}" stroke="${DRAWING.dim}" stroke-width="0.18" marker-start="url(#dw-arrow)" marker-end="url(#dw-arrow)"/>`)

  // frame
  parts.push(`<rect x="10" y="10" width="${W - 20}" height="${H - 20}" fill="none" stroke="${DRAWING.frame}" stroke-width="0.5"/>`)
  // section (hatched glass) and axis
  parts.push(`<polygon points="${section}" fill="url(#dw-hatch)" stroke="${DRAWING.line}" stroke-width="0.5" stroke-linejoin="round"/>`)
  line(xL - 8, cy, xR + 8, cy, 0.18, DRAWING.axis, ' stroke-dasharray="6 1.5 1 1.5"')
  // centre thickness (along the axis, below the section)
  const x0 = X(0)
  const x1 = X(el.center_thickness_mm)
  const yd = yBot + 9
  line(x0, cy + 1, x0, yd + 1.5, 0.13, DRAWING.thin)
  line(x1, cy + 1, x1, yd + 1.5, 0.13, DRAWING.thin)
  dim(x0, yd, x1, yd)
  const ct = el.tolerances.center_thickness
  text((x0 + x1) / 2, yd - 1.2, `${fmtFixed(el.center_thickness_mm, 3)}${ct ? ` ${tolPm(ct[0], ct[1])}` : ''}`, 2.5, 'middle')
  // outer diameter (right)
  const xd = xR + 10
  line(xR + 1, yTop, xd + 1.5, yTop, 0.13, DRAWING.thin)
  line(xR + 1, yBot, xd + 1.5, yBot, 0.13, DRAWING.thin)
  dim(xd, yTop, xd, yBot)
  text(xd - 1.2, cy, `Ø ${fmtFixed(2 * R, 2)}`, 2.5, 'middle', ` transform="rotate(-90 ${(xd - 1.2).toFixed(3)} ${cy.toFixed(3)})"`)
  // radii labels with leaders
  for (const side of [0, 1] as const) {
    const pt = el.outline[side === 0 ? Math.floor(el.outline.length * 0.18) : Math.floor(el.outline.length * 0.82)]
    const px = X(pt[1])
    const py = Y(pt[0])
    const tx = side === 0 ? xL - 14 : xR + 4
    const ty = yTop - 4
    line(px, py, side === 0 ? tx + 12 : tx, ty + 1, 0.13, DRAWING.thin)
    text(side === 0 ? tx + 12 : tx, ty, `${radiusText(el.radii_mm[side], side)}`, 2.5, side === 0 ? 'end' : 'start')
  }
  text(cx, 17, `${el.name}  (S${el.surfaces[0]}–S${el.surfaces[1]})`, 3.5, 'middle', ' font-weight="600"')

  // three-column table: left surface | material | right surface
  const ty0 = 124
  const cols = [
    { x: 12, w: 88, title: t('dw.left'), lines: surfaceLines(el, 0, t) },
    { x: 100, w: 97, title: t('dw.material'), lines: materialLines(el, t) },
    { x: 197, w: 88, title: t('dw.right'), lines: surfaceLines(el, 1, t) },
  ]
  const rows = Math.max(...cols.map((c) => c.lines.length))
  const th = 6 + rows * 4.2 + 2
  for (const c of cols) {
    parts.push(`<rect x="${c.x}" y="${ty0}" width="${c.w}" height="${th.toFixed(2)}" fill="none" stroke="${DRAWING.frame}" stroke-width="0.35"/>`)
    line(c.x, ty0 + 6, c.x + c.w, ty0 + 6, 0.25, DRAWING.frame)
    text(c.x + c.w / 2, ty0 + 4.2, c.title, 2.8, 'middle', ' font-weight="600"')
    c.lines.forEach((l, k) => text(c.x + 2, ty0 + 6 + 4.2 * (k + 1) - 0.8, l, 2.5))
  }
  // general data under the table
  const gy = ty0 + th + 5
  const tw = el.tolerances.test_wavelength_nm
  const general = [
    `${t('dw.ct')} ${fmtFixed(el.center_thickness_mm, 3)}${ct ? ` ${tolPm(ct[0], ct[1])}` : ''} · ${t('dw.outer')} Ø ${fmtFixed(2 * R, 2)} · ${t('dw.edge')} ${fmtFixed(el.edge_thickness_mm, 3)}`,
    `${t('dw.fringes', { nm: fmt(tw ?? 546.07, 6) })}${el.tolerances.decenter_mm ? ` · ${t('dw.decenter')} ± ${fmt(el.tolerances.decenter_mm, 3)}` : ''}`,
  ]
  general.forEach((g, k) => text(12, gy + 4.2 * k, g, 2.5))
  // title block
  const bx = 177
  const by = 182
  parts.push(`<rect x="${bx}" y="${by}" width="${W - 10 - bx}" height="${H - 10 - by}" fill="none" stroke="${DRAWING.frame}" stroke-width="0.5"/>`)
  line(bx, by + 9, W - 10, by + 9, 0.25, DRAWING.frame)
  text(bx + 2, by + 4, o.project, 2.8, 'start', ' font-weight="600"')
  text(bx + 2, by + 7.6, `${el.name} · ${el.material.name}`, 2.5)
  text(bx + 2, by + 13.5, `${t('dw.scale')} ${scaleLabel(scale)} · ${t('dw.units')}`, 2.3)
  text(bx + 2, by + 16.8, `OptiCore Studio · ${o.date}`, 2.3, 'start', ` fill="${DRAWING.muted}"`)

  const defs = `<defs>
<pattern id="dw-hatch" width="2.5" height="2.5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="2.5" height="2.5" fill="${DRAWING.fill}"/><line x1="0" y1="0" x2="0" y2="2.5" stroke="${DRAWING.hatch}" stroke-width="0.18"/></pattern>
<marker id="dw-arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0,1 L10,5 L0,9 z" fill="${DRAWING.dim}"/></marker>
</defs>`
  const meta = `<metadata id="opticore-element">${esc(JSON.stringify(drawingMeta(el)))}</metadata>`
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}mm" height="${H}mm" font-family="Helvetica, Arial, sans-serif" data-element="${esc(el.name)}">
<title>${esc(`${o.project} – ${el.name} (${el.material.name})`)}</title>
${meta}
${defs}
<rect width="${W}" height="${H}" fill="${DRAWING.paper}"/>
${parts.join('\n')}
</svg>`
}
