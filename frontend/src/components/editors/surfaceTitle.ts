import type { Surface } from '../../lib/types'

export function surfaceTitle(s: Surface, i: number, n: number): string {
  if (i === 0) return 'Object'
  if (i === n - 1) return 'Image'
  return s.label || `Surface ${i}`
}
