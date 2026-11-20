import type { StockKind, StockLensInfo } from '../../lib/types'

export interface StockFilter {
  q: string
  kind: StockKind | 'all'
  glass: string
  diameter: number | 0
  catalog: string
  fmin: number | null
  fmax: number | null
}

/** Lenses passing the filter (text matches part, vendor, glass or kind; focal length range on the paraxial EFL). */
export function filterStock(lenses: { lens: StockLensInfo; catalogId: string }[], f: StockFilter): { lens: StockLensInfo; catalogId: string }[] {
  const q = f.q.trim().toLowerCase()
  return lenses.filter(({ lens: l, catalogId }) => {
    if (f.catalog !== 'all' && catalogId !== f.catalog) return false
    if (f.kind !== 'all' && l.kind !== f.kind) return false
    if (f.glass && !l.materials.some((m) => m.toUpperCase() === f.glass)) return false
    if (f.diameter && Math.abs(l.diameter - f.diameter) > 1e-6) return false
    const efl = l.paraxial.efl
    if (f.fmin !== null && (efl === null || efl < f.fmin)) return false
    if (f.fmax !== null && (efl === null || efl > f.fmax)) return false
    if (q && ![l.part, l.vendor ?? '', l.kind ?? '', ...l.materials].some((x) => x.toLowerCase().includes(q))) return false
    return true
  })
}
