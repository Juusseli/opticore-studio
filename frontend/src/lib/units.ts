// Engineering input parsing. Lens units are millimetres; inputs may carry a
// unit suffix which is converted exactly (e.g. "1 in" -> 25.4, "500um" -> 0.5).

export const LENGTH_TO_MM: Record<string, number> = {
  nm: 1e-6,
  um: 1e-3,
  'µm': 1e-3,
  mm: 1,
  cm: 10,
  m: 1000,
  in: 25.4,
  '"': 25.4,
}

export const WAVELENGTH_TO_UM: Record<string, number> = { nm: 1e-3, um: 1, 'µm': 1, mm: 1e3 }
export const ANGLE_TO_DEG: Record<string, number> = { deg: 1, '°': 1, rad: 180 / Math.PI, mrad: 0.18 / Math.PI }

/** Scale by a unit factor. Power-of-ten factors shift the decimal exponent of the
 *  shortest round-trip representation, so "587.5618 nm" becomes exactly 0.5875618 µm
 *  (plain multiplication by 1e-3 would give 0.5875617999999999). */
export function scaleExact(v: number, factor: number): number {
  const k = Math.log10(factor)
  if (Math.abs(k - Math.round(k)) < 1e-12) {
    const [mant, ex = '0'] = String(v).split('e')
    return parseFloat(`${mant}e${parseInt(ex, 10) + Math.round(k)}`)
  }
  return v * factor
}

export type ParseResult = { ok: true; value: number | null } | { ok: false; error: string }

const INF_WORDS = new Set(['inf', 'infinity', '∞', 'infinite', 'ääretön'])

/**
 * Parse a numeric engineering entry.
 * @param allowInfinity  accept inf / infinity / ∞ (returns null)
 * @param units          map of accepted unit suffixes to the internal unit
 */
export function parseEngineering(
  text: string,
  opts: { allowInfinity?: boolean; units?: Record<string, number>; min?: number; max?: number; integer?: boolean } = {},
): ParseResult {
  const s = text.trim().replace(',', '.').replace(/\s+/g, '')
  if (s === '') return { ok: false, error: 'Value required' }
  if (INF_WORDS.has(s.toLowerCase())) {
    return opts.allowInfinity ? { ok: true, value: null } : { ok: false, error: 'Infinity is not allowed here' }
  }
  const m = /^([+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)(.*)$/i.exec(s)
  if (!m) return { ok: false, error: `'${text}' is not a number` }
  let v = parseFloat(m[1])
  const unit = m[2]
  if (unit) {
    const f = opts.units?.[unit] ?? opts.units?.[unit.toLowerCase()]
    if (f === undefined) return { ok: false, error: `Unknown unit '${unit}'` }
    v = scaleExact(v, f)
  }
  if (!Number.isFinite(v)) return { ok: false, error: 'Value is not finite' }
  if (opts.integer && !Number.isInteger(v)) return { ok: false, error: 'Integer required' }
  if (opts.min !== undefined && v < opts.min) return { ok: false, error: `Must be ≥ ${opts.min}` }
  if (opts.max !== undefined && v > opts.max) return { ok: false, error: `Must be ≤ ${opts.max}` }
  return { ok: true, value: v }
}

export const degToRad = (d: number) => (d * Math.PI) / 180
export const radToDeg = (r: number) => (r * 180) / Math.PI
