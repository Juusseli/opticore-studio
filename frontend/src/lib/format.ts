export function fmt(v: number | null | undefined, digits = 6): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  if (!Number.isFinite(v)) return v > 0 ? '∞' : '-∞'
  if (v === 0) return '0'
  const a = Math.abs(v)
  if (a >= 1e6 || a < 1e-4) return v.toExponential(Math.max(1, digits - 2))
  // significant digits, trimmed
  const s = v.toPrecision(digits)
  return s.includes('e') ? s : s.replace(/(\.\d*?[1-9])0+$/, '$1').replace(/\.0+$/, '')
}

export function fmtFixed(v: number | null | undefined, decimals = 4): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  if (!Number.isFinite(v)) return v > 0 ? '∞' : '-∞'
  return v.toFixed(decimals)
}

export function fmtRadius(r: number | null): string {
  return r === null ? 'Infinity' : fmt(r, 8)
}

/** Approximate sRGB colour of a vacuum wavelength (um) for plotting. */
export function wavelengthColor(um: number, alpha = 1): string {
  const nm = um * 1000
  let r = 0,
    g = 0,
    b = 0
  if (nm >= 380 && nm < 440) {
    r = -(nm - 440) / 60
    b = 1
  } else if (nm < 490) {
    g = (nm - 440) / 50
    b = 1
  } else if (nm < 510) {
    g = 1
    b = -(nm - 510) / 20
  } else if (nm < 580) {
    r = (nm - 510) / 70
    g = 1
  } else if (nm < 645) {
    r = 1
    g = -(nm - 645) / 65
  } else if (nm <= 780) {
    r = 1
  } else {
    // IR: draw dark red / UV: violet
    return nm > 780 ? `rgba(160,40,40,${alpha})` : `rgba(120,60,200,${alpha})`
  }
  if (nm < 380) return `rgba(120,60,200,${alpha})`
  const f = nm < 420 ? 0.3 + (0.7 * (nm - 380)) / 40 : nm > 700 ? 0.3 + (0.7 * (780 - nm)) / 80 : 1
  const c = (x: number) => Math.round(255 * Math.pow(x * f, 0.8))
  return `rgba(${c(r)},${c(g)},${c(b)},${alpha})`
}

/** Field colours come from the palette (colour-blind safe, the same in every view). */
export { fieldColor } from './palette'

export function timeAgo(iso: string, now = Date.now()): string {
  const t = new Date(iso).getTime()
  const s = Math.round((now - t) / 1000)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.round(s / 60)} min`
  if (s < 86400) return `${Math.round(s / 3600)} h`
  return new Date(iso).toLocaleDateString()
}
