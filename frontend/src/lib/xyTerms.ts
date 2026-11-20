// XY-polynomial term order (backend qpoly.xy_exponents): by total degree, falling power of x within a degree.
const SUP: Record<string, string> = { '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹' }

/** (power of x, power of y) of XY terms 1..count. */
export function xyExponents(count: number): [number, number][] {
  const out: [number, number][] = []
  for (let d = 1; out.length < count; d++) for (let px = d; px >= 0 && out.length < count; px--) out.push([px, d - px])
  return out
}

/** Monomial name of XY term k (1-based), e.g. 3 -> x², 4 -> xy. */
export function xyTermName(k: number): string {
  const [i, j] = xyExponents(k)[k - 1]
  const f = (v: string, n: number) => (n === 0 ? '' : n === 1 ? v : `${v}${String(n).replace(/\d/g, (c) => SUP[c])}`)
  return f('x', i) + f('y', j)
}
