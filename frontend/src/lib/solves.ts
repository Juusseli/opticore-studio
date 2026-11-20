import { fmt } from './format'
import type { OpticalSystem, Solve, SolveType } from './types'

export const SOLVE_LABEL: Record<SolveType, string> = {
  marginal_height: 'Marginal-ray height',
  chief_height: 'Chief-ray height',
  pickup: 'Pickup',
  marginal_angle: 'Marginal-ray angle',
  chief_angle: 'Chief-ray angle',
  f_number: 'F-number',
}

export function describeSolve(sv: Solve, kind: 'thickness' | 'curvature', sys?: OpticalSystem): string {
  if (sv.type === 'pickup') {
    const k = sys ? sys.surfaces.findIndex((x) => x.id === sv.surface_id) : -1
    const src = k >= 0 ? `surface ${k}` : 'source'
    return kind === 'thickness' ? `Pickup: ${fmt(sv.scale, 6)} × t(${src}) + ${fmt(sv.offset, 6)} mm` : `Pickup: R = ${fmt(sv.scale, 6)} × R(${src})`
  }
  if (sv.type === 'f_number') return `F-number solve: image-space F/# ${fmt(sv.target, 6)} (paraxial marginal ray)`
  if (sv.type === 'marginal_height' || sv.type === 'chief_height') return `${SOLVE_LABEL[sv.type]} solve: ${fmt(sv.target, 6)} mm at the next surface${sv.type === 'marginal_height' && sv.zone !== 1 ? ` (zone ${fmt(sv.zone, 4)})` : ''} (paraxial)`
  return `${SOLVE_LABEL[sv.type]} solve: slope ${fmt(sv.target, 6)} after the surface (paraxial)`
}
