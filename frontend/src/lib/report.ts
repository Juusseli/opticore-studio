/**
 * Automated engineering report: a self-contained HTML document (inline CSS
 * and SVG charts, no external resources) generated from engine results.
 * Every number in the report comes from the engine; this module only formats.
 */
import { REPORT } from './palette'
import { api } from './api'
import { projectChecksum } from './canonical'
import { activeOverride } from './configs'
import { fmt } from './format'
import { describeSolve } from './solves'
import { elementDrawingSvg } from './drawing'
import { translate } from './i18n'
import { xyTermName } from './xyTerms'
import type { ElementsResult, Evaluation, FieldResult, MtfResult, OptimizationResult, Project, SpotResult, ThroughputResult, ToleranceResult } from './types'

export interface ReportExtras {
  engineVersion: string | null
  optimization?: OptimizationResult | null
  tolerance?: ToleranceResult | null
}

export interface ReportData {
  evaluation: Evaluation
  spot: SpotResult
  mtf: MtfResult | null
  field: FieldResult | null
  throughput: ThroughputResult | null
  /** lens elements as parts, for the ISO 10110 drawings (absent or null: no drawings) */
  elements?: ElementsResult | null
  errors: string[]
}

const esc = (s: unknown) =>
  String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')

const F = (v: number | null | undefined, d = 6) => esc(fmt(v ?? null, d))

const FIELD_COLORS = REPORT.series

function wavelengthColor(um: number): string {
  // simple visible-spectrum approximation for chart colours only
  const l = um * 1000
  let r = 0
  let g = 0
  let b = 0
  if (l < 440) [r, g, b] = [(440 - l) / 60, 0, 1]
  else if (l < 490) [r, g, b] = [0, (l - 440) / 50, 1]
  else if (l < 510) [r, g, b] = [0, 1, (510 - l) / 20]
  else if (l < 580) [r, g, b] = [(l - 510) / 70, 1, 0]
  else if (l < 645) [r, g, b] = [1, (645 - l) / 65, 0]
  else [r, g, b] = [1, 0, 0]
  const c = (x: number) => Math.round(Math.max(0, Math.min(1, x)) * 200)
  return `rgb(${c(r)},${c(g)},${c(b)})`
}

/** Fetch every analysis the report needs (one consistent snapshot of the design). */
export async function collectReportData(p: Project): Promise<ReportData> {
  const body = { system: p.system, custom_materials: p.custom_materials }
  const errors: string[] = []
  const evaluation = await api.evaluate(body)
  const spot = await api.spot({ ...body, pattern: 'hexapolar', density: 6, reference: 'centroid' })
  const opt = async <T>(name: string, f: () => Promise<T>): Promise<T | null> => {
    try {
      return await f()
    } catch (e) {
      errors.push(`${name}: ${(e as Error).message}`)
      return null
    }
  }
  const mtf = await opt('MTF', () => api.mtf({ ...body, kind: 'diffraction', max_frequency: null, samples: 32 }))
  const field = await opt('Field curvature / distortion', () => api.field({ ...body, samples: 11 }))
  const throughput = await opt('Throughput', () => api.throughput(body))
  const elements = await opt('Element drawings', () => api.elements({ ...body, tolerancing: p.tolerancing }))
  return { evaluation, spot, mtf, field, throughput, elements, errors }
}

// ------------------------------------------------------------------ SVG helpers
type Series = { x: number[]; y: (number | null)[]; color: string; dash?: boolean; label: string }

function lineChart(series: Series[], opts: { w?: number; h?: number; xlabel: string; ylabel: string; ymin?: number; ymax?: number }): string {
  const w = opts.w ?? 560
  const h = opts.h ?? 260
  const m = { l: 56, r: 12, t: 12, b: 40 }
  const xs = series.flatMap((s) => s.x)
  const ys = series.flatMap((s) => s.y.filter((v): v is number => v !== null && Number.isFinite(v)))
  if (!xs.length || !ys.length) return '<p class="muted">No data.</p>'
  const x0 = Math.min(...xs)
  const x1 = Math.max(...xs)
  let y0 = opts.ymin ?? Math.min(...ys)
  let y1 = opts.ymax ?? Math.max(...ys)
  if (y1 === y0) {
    y0 -= 1
    y1 += 1
  }
  const X = (v: number) => m.l + ((v - x0) / (x1 - x0 || 1)) * (w - m.l - m.r)
  const Y = (v: number) => h - m.b - ((v - y0) / (y1 - y0)) * (h - m.t - m.b)
  const ticks = (a: number, b: number, n = 5) => Array.from({ length: n + 1 }, (_, k) => a + ((b - a) * k) / n)
  let svg = `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" class="chart">`
  for (const tx of ticks(x0, x1)) svg += `<line x1="${X(tx)}" x2="${X(tx)}" y1="${m.t}" y2="${h - m.b}" class="grid"/><text x="${X(tx)}" y="${h - m.b + 14}" text-anchor="middle">${esc(fmt(tx, 3))}</text>`
  for (const ty of ticks(y0, y1)) svg += `<line x1="${m.l}" x2="${w - m.r}" y1="${Y(ty)}" y2="${Y(ty)}" class="grid"/><text x="${m.l - 6}" y="${Y(ty) + 3}" text-anchor="end">${esc(fmt(ty, 3))}</text>`
  svg += `<rect x="${m.l}" y="${m.t}" width="${w - m.l - m.r}" height="${h - m.t - m.b}" class="frame"/>`
  for (const s of series) {
    let d = ''
    let pen = false
    s.x.forEach((xv, k) => {
      const yv = s.y[k]
      if (yv === null || !Number.isFinite(yv)) {
        pen = false
        return
      }
      d += `${pen ? 'L' : 'M'}${X(xv).toFixed(2)},${Y(yv).toFixed(2)}`
      pen = true
    })
    svg += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="1.6"${s.dash ? ' stroke-dasharray="5 3"' : ''}/>`
  }
  svg += `<text x="${(m.l + w - m.r) / 2}" y="${h - 6}" text-anchor="middle" class="axis">${esc(opts.xlabel)}</text>`
  svg += `<text x="14" y="${(m.t + h - m.b) / 2}" text-anchor="middle" transform="rotate(-90 14 ${(m.t + h - m.b) / 2})" class="axis">${esc(opts.ylabel)}</text>`
  svg += '</svg>'
  const legend = series.map((s) => `<span class="lg"><i style="background:${s.color}${s.dash ? ';opacity:.55' : ''}"></i>${esc(s.label)}</span>`).join('')
  return `${svg}<div class="legend">${legend}</div>`
}

function spotChart(f: SpotResult['fields'][number], system: Project['system'], airy: number | null): string {
  const pts = f.per_wavelength.flatMap((w) => w.points_um.map(([x, y]) => ({ x, y, w: w.wavelength })))
  const all = f.per_wavelength.flatMap((w) => w.points_um)
  const r = Math.max(airy ?? 0, ...all.map(([x, y]) => Math.hypot(x, y))) * 1.08 || 1
  const s = 170
  const c = s / 2
  const k = (c - 8) / r
  let svg = `<svg viewBox="0 0 ${s} ${s}" width="${s}" height="${s}" class="chart"><rect x="0.5" y="0.5" width="${s - 1}" height="${s - 1}" class="frame"/>`
  svg += `<line x1="${c}" x2="${c}" y1="4" y2="${s - 4}" class="grid"/><line y1="${c}" y2="${c}" x1="4" x2="${s - 4}" class="grid"/>`
  if (airy) svg += `<circle cx="${c}" cy="${c}" r="${airy * k}" fill="none" stroke="${REPORT.faint}" stroke-dasharray="3 2"/>`
  for (const p of pts) svg += `<circle cx="${(c + p.x * k).toFixed(1)}" cy="${(c - p.y * k).toFixed(1)}" r="1.1" fill="${wavelengthColor(system.wavelengths[p.w]?.value ?? 0.55)}"/>`
  svg += `<text x="6" y="${s - 6}" class="small">±${esc(fmt(r, 3))} µm</text></svg>`
  return svg
}

function layoutSvg(ev: Evaluation): string {
  const pts: [number, number][] = []
  const surf: string[] = []
  for (const s of ev.surfaces) {
    if (s.type === 'coordinate_break' || s.profile.length < 2) continue
    const m = s.matrix
    const o = s.origin
    const line = s.profile.map(([y, z]) => [o[2] + m[2][1] * y + m[2][2] * z, o[1] + m[1][1] * y + m[1][2] * z] as [number, number])
    pts.push(...line)
    surf.push(line.map((p) => p.join(',')).join(' '))
  }
  const rays = ev.rays.map((r) => ({ f: r.field, pts: r.points.filter((p) => p.every(Number.isFinite)).map((p) => [p[2], p[1]] as [number, number]) }))
  for (const r of rays) pts.push(...r.pts)
  if (!pts.length) return ''
  const z0 = Math.min(...pts.map((p) => p[0]))
  const z1 = Math.max(...pts.map((p) => p[0]))
  const y0 = Math.min(...pts.map((p) => p[1]))
  const y1 = Math.max(...pts.map((p) => p[1]))
  const w = 760
  const sc = (w - 20) / Math.max(z1 - z0, 1e-9)
  const h = Math.max(120, Math.min(420, (y1 - y0) * sc + 20))
  const s2 = Math.min(sc, (h - 20) / Math.max(y1 - y0, 1e-9))
  const X = (z: number) => 10 + (z - z0) * s2
  const Y = (y: number) => h / 2 - (y - (y0 + y1) / 2) * s2
  let svg = `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" class="chart"><line x1="0" x2="${w}" y1="${Y(0)}" y2="${Y(0)}" class="grid"/>`
  for (const r of rays) svg += `<polyline points="${r.pts.map(([z, y]) => `${X(z).toFixed(1)},${Y(y).toFixed(1)}`).join(' ')}" fill="none" stroke="${FIELD_COLORS[r.f % FIELD_COLORS.length]}" stroke-width="0.7" opacity="0.8"/>`
  for (const s of surf)
    svg += `<polyline points="${s
      .split(' ')
      .map((p) => {
        const [z, y] = p.split(',').map(Number)
        return `${X(z).toFixed(1)},${Y(y).toFixed(1)}`
      })
      .join(' ')}" fill="none" stroke="${REPORT.text}" stroke-width="1.4"/>`
  svg += `<text x="${w - 8}" y="${h - 6}" text-anchor="end" class="small">${esc(fmt(z1 - z0, 4))} mm overall (y-z section)</text></svg>`
  return svg
}

// ------------------------------------------------------------------ report
export async function buildReportHtml(p: Project, d: ReportData, x: ReportExtras): Promise<string> {
  const sys = p.system
  const ev = d.evaluation
  const pw = sys.primary_wavelength
  const pd = ev.paraxial[String(pw)]
  const n = sys.surfaces.length
  const checksum = await projectChecksum(JSON.parse(JSON.stringify({ ...p, checksum: null })))
  const now = new Date()
  const mc = sys.multi_config
  const fieldUnit = sys.field_type === 'angle' ? '°' : 'mm'
  const sections: string[] = []

  sections.push(`<h2>1. System summary</h2>
<table class="kv">
<tr><th>Effective focal length</th><td>${F(pd?.efl)} mm</td><th>Back focal length</th><td>${F(pd?.bfl)} mm</td></tr>
<tr><th>Image-space F/#</th><td>${F(pd?.image_space_fnum, 5)}</td><th>Working F/#</th><td>${F(pd?.working_fnum, 5)}</td></tr>
<tr><th>Image-space NA</th><td>${F(pd?.image_space_na, 5)}</td><th>Paraxial magnification</th><td>${F(pd?.paraxial_magnification, 6)}</td></tr>
<tr><th>Entrance pupil</th><td>${sys.object_space_telecentric ? 'at infinity (object-space telecentric)' : `Ø ${F(pd?.entrance_pupil_diameter)} mm at ${F(pd?.entrance_pupil_position)} mm`}</td><th>Exit pupil</th><td>${pd?.exit_pupil_diameter ? `Ø ${F(pd.exit_pupil_diameter)} mm at ${F(pd.exit_pupil_position)} mm` : '—'}</td></tr>
<tr><th>Total track</th><td>${F(pd?.total_track)} mm</td><th>Aperture</th><td>${esc(sys.aperture.type)} = ${F(sys.aperture.value)}</td></tr>
<tr><th>Wavelengths (µm)</th><td>${sys.wavelengths.map((w, k) => `${F(w.value, 7)}${k === pw ? ' (primary)' : ''}`).join(', ')}</td><th>Fields (${esc(sys.field_type.replace(/_/g, ' '))}, ${fieldUnit})</th><td>${sys.fields.map((f) => `(${F(f.x, 4)}, ${F(f.y, 4)})`).join(', ')}</td></tr>
<tr><th>Ray aiming</th><td>${esc(sys.ray_aiming)}</td><th>Configuration</th><td>${mc ? `${esc(mc.names[mc.active])} (${mc.active + 1} of ${mc.names.length})` : 'single'}</td></tr>
</table>
<p class="note">First-order quantities are paraxial (y-nu trace) at the primary wavelength; image-quality figures below are exact real-ray or diffraction results as stated.</p>`)

  sections.push(`<h2>2. Layout</h2>${layoutSvg(ev)}`)

  const rows = sys.surfaces
    .map((s, i) => {
      const solved = ev.solved?.find((v) => v.surface === i)
      const oR = activeOverride(sys, s.id, 'radius')
      const oT = activeOverride(sys, s.id, 'thickness')
      const oM = activeOverride(sys, s.id, 'material')
      const radius = s.curvature_solve ? solved?.radius : oR ? (oR.value as number | null) : s.radius
      const thick = s.thickness_solve ? solved?.thickness : oT ? (oT.value as number | null) : s.thickness
      const mat = oM ? String(oM.value) : s.material
      const notes = [
        s.is_stop ? 'stop' : '',
        s.curvature_solve ? describeSolve(s.curvature_solve, 'curvature', sys) : '',
        s.thickness_solve ? describeSolve(s.thickness_solve, 'thickness', sys) : '',
        oR || oT || oM ? 'set per configuration' : '',
        s.coating && s.type !== 'ideal' ? `coating ${s.coating}` : '',
        s.type === 'ideal' ? `ideal lens f = ${s.focal_length === null ? '∞' : fmt(s.focal_length, 8)} mm (OPD exact for an object at ${s.ideal_object_distance === null ? 'infinity' : fmt(s.ideal_object_distance, 6) + ' mm'})` : '',
        s.type === 'coordinate_break' ? `decenter (${fmt(s.decenter_x, 4)}, ${fmt(s.decenter_y, 4)}) mm, tilt (${fmt(s.tilt_x, 4)}, ${fmt(s.tilt_y, 4)}, ${fmt(s.tilt_z, 4)})°` : '',
        (s.type === 'even_asphere' || s.type === 'zernike') && s.aspheric.length ? `A4… ${s.aspheric.map((a) => a.toExponential(4)).join(', ')}` : '',
        s.type === 'zernike' && s.zernike_coefficients.some((a) => a !== 0) ? `Zernike (Fringe, R = ${fmt(s.zernike_norm_radius, 6)} mm) ${s.zernike_coefficients.map((a, k) => (a !== 0 ? `Z${k + 1} ${a.toExponential(4)}` : '')).filter(Boolean).join(', ')}` : '',
        (s.type === 'qcon' || s.type === 'qbfs') && (s.q_coefficients ?? []).length ? `${s.type === 'qcon' ? 'Qcon' : 'Qbfs'} (r_n = ${fmt(s.q_norm_radius ?? 10, 6)} mm) ${(s.q_coefficients ?? []).map((a, k) => `a${k} ${a.toExponential(4)}`).join(', ')}` : '',
        s.type === 'odd_asphere' && (s.odd_coefficients ?? []).some((a) => a !== 0) ? `Odd asphere ${(s.odd_coefficients ?? []).map((a, k) => (a !== 0 ? `β${k + 1} ${a.toExponential(4)}` : '')).filter(Boolean).join(', ')}` : '',
        s.type === 'xy_polynomial' && (s.xy_coefficients ?? []).some((a) => a !== 0) ? `XY polynomial (R = ${fmt(s.xy_norm_radius ?? 10, 6)} mm) ${(s.xy_coefficients ?? []).map((a, k) => (a !== 0 ? `${xyTermName(k + 1)} ${a.toExponential(4)}` : '')).filter(Boolean).join(', ')}` : '',
      ].filter(Boolean)
      const nIdx = ev.indices?.[pw]?.[i]
      return `<tr><td>${i === 0 ? 'OBJ' : i === n - 1 ? 'IMG' : i}</td><td>${esc(s.label)}</td><td>${esc(s.type)}</td><td class="num">${s.type === 'ideal' ? '—' : radius === null || radius === undefined ? '∞' : F(radius, 8)}</td><td class="num">${thick === null || thick === undefined ? '∞' : F(thick, 8)}</td><td>${esc(mat)}</td><td class="num">${i === n - 1 || s.type === 'coordinate_break' ? '' : F(nIdx, 7)}</td><td class="num">${F(ev.semi_diameters[i], 6)}${s.semi_diameter_mode === 'fixed' ? ' (fixed)' : ''}</td><td class="num">${F(s.conic, 5)}</td><td class="small">${esc(notes.join('; '))}</td></tr>`
    })
    .join('')
  sections.push(`<h2>3. Prescription</h2>
<table class="grid"><thead><tr><th>#</th><th>Label</th><th>Type</th><th>Radius (mm)</th><th>Thickness (mm)</th><th>Material</th><th>n (primary)</th><th>Semi-diameter (mm)</th><th>Conic</th><th>Notes</th></tr></thead><tbody>${rows}</tbody></table>
<p class="note">Sign convention: radius &gt; 0 has its centre of curvature on the +z side; thicknesses after a mirror are negative.${ev.solved?.length ? ' Solved values are shown as resolved by the engine.' : ''}</p>`)

  const spot = d.spot
  sections.push(`<h2>4. Spot diagrams</h2>
<div class="spots">${spot.fields.map((f, k) => `<figure>${spotChart(f, sys, spot.airy_radius_um)}<figcaption>F${k + 1} (${F(f.field_value[0], 4)}, ${F(f.field_value[1], 4)}) ${fieldUnit}<br>RMS ${F(f.rms_radius_um, 5)} µm · GEO ${F(f.geo_radius_um, 5)} µm</figcaption></figure>`).join('')}</div>
<p class="note">${esc(spot.method)}. Dashed circle: Airy radius ${F(spot.airy_radius_um, 4)} µm. Rays per wavelength: ${spot.settings.rays_per_wavelength}.</p>`)

  if (d.mtf) {
    const m = d.mtf
    const series: Series[] = [{ x: m.frequency_cyc_per_mm, y: m.diffraction_limit, color: REPORT.muted, dash: true, label: 'diffraction limit' }]
    m.fields.forEach((f, k) => {
      const c = FIELD_COLORS[k % FIELD_COLORS.length]
      series.push({ x: m.frequency_cyc_per_mm, y: f.tangential, color: c, label: `F${k + 1} T` })
      series.push({ x: m.frequency_cyc_per_mm, y: f.sagittal, color: c, dash: true, label: `F${k + 1} S` })
    })
    sections.push(`<h2>5. MTF (${esc(m.kind)})</h2>${lineChart(series, { xlabel: 'Spatial frequency (cycles/mm)', ylabel: 'Modulation', ymin: 0, ymax: 1 })}<p class="note">${esc(m.method)}</p>`)
  }

  if (d.field) {
    const fr = d.field
    const wp = fr.per_wavelength.find((w) => w.wavelength === pw) ?? fr.per_wavelength[0]
    const series: Series[] = fr.per_wavelength.flatMap((w) => [
      { x: fr.field_values, y: w.tangential_mm, color: wavelengthColor(sys.wavelengths[w.wavelength]?.value ?? 0.55), label: `T ${fmt((sys.wavelengths[w.wavelength]?.value ?? 0) * 1000, 4)} nm` },
      { x: fr.field_values, y: w.sagittal_mm, color: wavelengthColor(sys.wavelengths[w.wavelength]?.value ?? 0.55), dash: true, label: `S ${fmt((sys.wavelengths[w.wavelength]?.value ?? 0) * 1000, 4)} nm` },
    ])
    const last = wp.distortion_percent[wp.distortion_percent.length - 1]
    sections.push(`<h2>6. Field curvature and distortion</h2>${lineChart(series, { xlabel: `Field (${fieldUnit})`, ylabel: 'Focus shift (mm)' })}<p>Distortion at full field (primary wavelength): <b>${F(last, 5)} %</b>.</p><p class="note">${esc(fr.method)}</p>`)
  }

  if (d.throughput) {
    const tp = d.throughput
    sections.push(`<h2>7. Energy throughput</h2><p>Weighted mean transmission: <b>${F(tp.weighted_mean_total * 100, 5)} %</b> of the power entering the entrance pupil.</p>
<table class="grid"><thead><tr><th>Field</th>${sys.wavelengths.map((w) => `<th>${F(w.value * 1000, 5)} nm</th>`).join('')}</tr></thead><tbody>${tp.fields.map((f, k) => `<tr><td>F${k + 1}</td>${f.per_wavelength.map((w) => `<td class="num">${F(w.total * 100, 5)} %</td>`).join('')}</tr>`).join('')}</tbody></table><p class="note">${esc(tp.method)}</p>`)
  }

  const o = x.optimization
  if (o) {
    sections.push(`<h2>8. Latest optimisation (not yet applied)</h2><p>${esc(o.algorithm)} · ${esc(o.status)} · merit ${F(o.initial_merit, 6)} → <b>${F(o.final_merit, 6)}</b> (${F(o.improvement_percent, 3)} % better, ${o.evaluations} evaluations)</p>`)
  }
  if (p.saved_optimizations.length) {
    sections.push(`<h3>Optimisation history</h3><table class="grid"><thead><tr><th>Date</th><th>Algorithm</th><th>Merit before</th><th>Merit after</th><th>Evaluations</th><th>Status</th></tr></thead><tbody>${p.saved_optimizations
      .slice(-10)
      .map((r) => `<tr><td>${esc(new Date(r.timestamp).toLocaleString())}</td><td>${esc(r.algorithm)}</td><td class="num">${F(r.initial_merit, 6)}</td><td class="num">${F(r.final_merit, 6)}</td><td class="num">${r.evaluations}</td><td>${esc(r.status)}${r.applied ? ' (applied)' : ''}</td></tr>`)
      .join('')}</tbody></table>`)
  }

  const tr = x.tolerance
  if (tr) {
    const st = tr.monte_carlo.statistics
    const up = (tr.sense ?? 1) > 0
    const yl = tr.yield
    const al = tr.allocation
    const yieldText = yl ? ` Yield against the specification ${up ? '≤' : '≥'} ${F(yl.limit, 5)}: <b>${F(yl.fraction * 100, 3)} %</b> (${yl.passed} of ${yl.trials}; 95 % Wilson interval ${F(yl.ci95[0] * 100, 3)}–${F(yl.ci95[1] * 100, 3)} %).` : ''
    const allocText = al ? ` The tolerances were allocated to the specification (equal shares of the budget; all at their limits ${F(al.predicted, 5)}); the Monte Carlo run used the allocated limits.` : ''
    sections.push(`<h2>9. Tolerance analysis</h2><p>Criterion ${esc(tr.criterion)} (${esc(tr.unit)}): nominal <b>${F(tr.nominal, 5)}</b>, RSS estimate <b>${F(tr.rss_estimate, 5)}</b>; Monte Carlo ${tr.monte_carlo.trials} trials: mean ${F(st.mean ?? null, 5)}, 90 % ${up ? '≤' : '≥'} ${F((up ? st.p90 : st.p10) ?? null, 5)}, 98 % ${up ? '≤' : '≥'} ${F((up ? st.p98 : st.p2) ?? null, 5)}.${yieldText}${allocText}</p>
<table class="grid"><thead><tr><th>Tolerance</th><th>Surface</th><th>Limits</th><th>Δ at min</th><th>Δ at max</th></tr></thead><tbody>${tr.sensitivity
      .slice(0, 12)
      .map((r) => {
        const si = sys.surfaces.findIndex((s) => s.id === r.surface_id)
        const dd = (v: number | null) => (v === null || tr.nominal === null ? '—' : F(v - tr.nominal, 4))
        return `<tr><td>${esc(r.type)}${r.term ? ` Z${r.term}` : ''}</td><td>${si}</td><td class="num">${F(r.min, 4)} / ${F(r.max, 4)} ${esc(r.unit)}</td><td class="num">${dd(r.at_min)}</td><td class="num">${dd(r.at_max)}</td></tr>`
      })
      .join('')}</tbody></table><p class="note">${esc(tr.method)}</p>`)
  }

  const els = d.elements?.elements ?? []
  if (els.length) {
    const tEn = (k: string, v?: Record<string, string | number>) => translate('en', k, v)
    const date = now.toISOString().slice(0, 10)
    const mass = d.elements?.total_mass_g
    sections.push(
      `<h2>9. Element drawings (ISO 10110)</h2><p>${els.length} lens element(s)${mass ? `, ${F(mass, 4)} g of glass` : ''}; values from the design at 20 °C and the enabled tolerances; unspecified indications are shown as —.</p>${els
        .map((el) => `<figure class="drawing">${elementDrawingSvg(el, { project: p.metadata.name, date, t: tEn }).replace('width="297mm" height="210mm"', 'width="100%"')}</figure>`)
        .join('')}`,
    )
  }

  const diags = ev.diagnostics.filter((g) => g.level !== 'info')
  sections.push(`<h2>10. Diagnostics</h2>${diags.length ? `<ul>${diags.map((g) => `<li><b>${esc(g.level)}</b> ${esc(g.code)}${g.surface !== null && g.surface !== undefined ? ` (surface ${g.surface})` : ''}: ${esc(g.message)}</li>`).join('')}</ul>` : '<p>No warnings or errors.</p>'}${d.errors.length ? `<p class="warn">Analyses that could not be computed: ${d.errors.map(esc).join('; ')}</p>` : ''}`)

  const css = `body{font:13px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;color:${REPORT.text};margin:32px auto;max-width:960px;padding:0 20px}
h1{font-size:22px;margin:0}h2{font-size:16px;margin:28px 0 8px;border-bottom:1px solid ${REPORT.rule};padding-bottom:4px}h3{font-size:14px}
table{border-collapse:collapse;width:100%;margin:6px 0}th,td{padding:3px 6px;text-align:left;vertical-align:top}
table.grid th{background:${REPORT.header};border-bottom:1px solid ${REPORT.rule};font-weight:600}table.grid td{border-bottom:1px solid ${REPORT.grid}}
table.kv th{color:${REPORT.muted};font-weight:500;width:18%}.num{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.note,.muted,.small{color:${REPORT.faint};font-size:11.5px}.warn{color:${REPORT.warn}}.meta{color:${REPORT.muted};margin:4px 0 0}
svg.chart{font-size:10px;fill:${REPORT.body};max-width:100%;height:auto}svg .grid{stroke:${REPORT.grid}}svg .frame{fill:none;stroke:${REPORT.frame}}svg .axis{font-size:11px}
.legend{display:flex;flex-wrap:wrap;gap:10px;font-size:11px;color:${REPORT.muted};margin:2px 0 6px}.lg i{display:inline-block;width:14px;height:3px;margin-right:4px;vertical-align:middle}
.spots{display:flex;flex-wrap:wrap;gap:14px}figure{margin:0}figure.drawing{margin:10px 0;border:1px solid ${REPORT.rule};break-inside:avoid}figcaption{font-size:11px;color:${REPORT.muted};text-align:center}
@media print{body{margin:0}h2{break-after:avoid}figure,svg{break-inside:avoid}}`
  // number the sections that are actually present (optional sections may be missing)
  let k = 0
  const numbered = sections.map((sec) => sec.replace(/<h2>\d+\. /, () => `<h2>${++k}. `))
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${esc(p.metadata.name)} — OptiCore engineering report</title><style>${css}</style></head><body>
<h1>${esc(p.metadata.name)}</h1>
<p class="meta">${esc(p.metadata.description)}</p>
<p class="meta">Engineering report generated ${esc(now.toLocaleString())} by OptiCore Studio (engine ${esc(x.engineVersion ?? '?')}, project schema v${p.schema_version}). Project SHA-256: <code>${esc(checksum)}</code>${p.metadata.author ? ` · Author: ${esc(p.metadata.author)}` : ''}</p>
${numbered.join('\n')}
<p class="note" style="margin-top:28px">All values were computed by the OptiCore engine for the design state identified by the checksum above. Geometric results are exact sequential ray traces; first-order data are paraxial; MTF is scalar diffraction (FFT). See the method notes under each section for assumptions and sampling.</p>
</body></html>`
}
