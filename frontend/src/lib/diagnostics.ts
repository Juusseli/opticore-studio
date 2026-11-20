// Plain-language causes and fixes for the engine's diagnostic codes (texts: dg.<CODE>.cause / .fix in i18n).
import type { Diagnostic } from './types'

/** Fix actions offered next to a message: go to the surface, or open the editor that changes the cause. */
export type FixAction = 'surface' | 'system' | 'materials' | 'coatings' | 'configs' | 'lde' | 'mounts'

export const DIAG_FIXES: Record<string, FixAction[]> = {
  ASPHERE_IGNORED: ['surface'],
  BICONIC_PARAXIAL: ['surface'],
  CB_BEFORE_STOP: ['system'],
  CB_MATERIAL_IGNORED: ['surface'],
  COATING_IGNORED: ['surface', 'coatings'],
  COATING_MATERIAL: ['coatings'],
  COATING_NAME: ['coatings'],
  COATING_RANGE: ['coatings', 'system'],
  COATING_SUBSTRATE_IGNORED: ['coatings'],
  CONFIG_INVALID: ['configs'],
  DOE_ACTIVE: ['surface'],
  ENVIRONMENT: ['system'],
  DOE_IGNORED: ['surface'],
  FIELD_AFOCAL: ['system'],
  FIELD_SCALE: ['system'],
  FIELD_UNREACHABLE: ['system'],
  GRATING_PARAXIAL: ['surface'],
  IDEAL_DOE_IGNORED: ['surface'],
  IDEAL_LENS: ['surface'],
  IDEAL_MEDIA: ['surface'],
  IDEAL_SHAPE_IGNORED: ['surface'],
  MIRROR_COATING: ['coatings'],
  MOUNT_COLLISION: ['mounts'],
  MOUNT_OVERCONSTRAINED: ['mounts'],
  MOUNT_UNSUPPORTED: ['mounts'],
  NEGATIVE_EDGE_THICKNESS: ['surface'],
  NONPOSITIVE_GLASS_THICKNESS: ['surface'],
  NON_AXIAL: ['surface'],
  PARAXIAL_AIMING: ['system'],
  PARAXIAL_FAILED: ['lde'],
  RAY_FAILED: ['surface', 'system'],
  SD_EXCEEDS_SURFACE: ['surface'],
  SOLVE_ACTIVE: ['surface'],
  SOLVE_FAILED: ['surface'],
  SOLVE_INVALID: ['surface'],
  SOLVE_NOT_CONVERGED: ['surface'],
  TELECENTRIC: ['system'],
  THERMAL_NO_CTE: ['materials', 'system'],
  THERMAL_NO_DNDT: ['materials', 'system'],
  THERMAL_RANGE: ['system'],
  TELECENTRIC_EP: ['system'],
  TELECENTRIC_STOP: ['surface', 'system'],
  UNKNOWN_COATING: ['coatings', 'surface'],
  UNKNOWN_MATERIAL: ['materials', 'surface'],
  WAVELENGTH_EXTRAPOLATED: ['system', 'materials'],
  TRANSMITTANCE_EXTRAPOLATED: ['system', 'materials'],
  ZERNIKE_EXTRAPOLATED: ['surface'],
  ZERNIKE_IGNORED: ['surface'],
  ZERNIKE_PARAXIAL: ['surface'],
  ZERNIKE_TILT: ['surface'],
  XY_PARAXIAL: ['surface'],
  XY_TILT: ['surface'],
  Q_EXTRAPOLATED: ['surface'],
  QBFS_CONIC_IGNORED: ['surface'],
  BIREFRINGENT: ['surface'],
  BIREFRINGENT_SPACE: ['surface'],
  BIREFRINGENT_SURFACE: ['surface'],
  BIREFRINGENT_COATING: ['surface'],
  JONES_IGNORED: ['surface'],
  JONES_CRYSTAL: ['surface'],
  POLARIZING_ELEMENT: ['surface'],
  ZERO_APERTURE: ['surface'],
  OBSCURATION: ['surface'],
  OBSCURATION_IGNORED: ['surface'],
  ODD_ASPHERE_PARAXIAL: ['surface'],
  ODD_ASPHERE_CONE: ['surface'],
}

/** Ray-failure kinds, recognised from the engine's status text in the RAY_FAILED message. */
const RAY_KINDS: [string, string][] = [
  ['ray misses surface', 'miss'],
  ['total internal reflection', 'tir'],
  ['clipped by aperture', 'clip'],
  ['outside surface definition domain', 'domain'],
  ['intersection did not converge', 'converge'],
  ['diffraction order is evanescent', 'evanescent'],
  ['blocked by central obscuration', 'obscured'],
]

/** i18n keys of the cause and fix of a diagnostic (unknown codes fall back to a generic text). */
export function explainKeys(d: Pick<Diagnostic, 'code' | 'message'>): { cause: string; fix: string } {
  if (d.code === 'RAY_FAILED') {
    const kind = RAY_KINDS.find(([txt]) => d.message.includes(txt))?.[1] ?? 'miss'
    return { cause: `dg.RAY_FAILED.${kind}.cause`, fix: `dg.RAY_FAILED.${kind}.fix` }
  }
  if (d.code in DIAG_FIXES) return { cause: `dg.${d.code}.cause`, fix: `dg.${d.code}.fix` }
  return { cause: 'dg.unknown.cause', fix: 'dg.unknown.fix' }
}

export function fixActions(d: Pick<Diagnostic, 'code' | 'surface'>): FixAction[] {
  return (DIAG_FIXES[d.code] ?? ['lde']).filter((a) => a !== 'surface' || d.surface !== null)
}

/** All i18n keys the explanations use (for the coverage test). */
export function explanationKeys(): string[] {
  const keys = Object.keys(DIAG_FIXES)
    .filter((c) => c !== 'RAY_FAILED')
    .flatMap((c) => [`dg.${c}.cause`, `dg.${c}.fix`])
  for (const [, k] of RAY_KINDS) keys.push(`dg.RAY_FAILED.${k}.cause`, `dg.RAY_FAILED.${k}.fix`)
  return [...keys, 'dg.unknown.cause', 'dg.unknown.fix']
}
