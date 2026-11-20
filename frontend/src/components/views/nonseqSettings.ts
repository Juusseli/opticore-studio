// Settings of the non-sequential analysis, shared by the Non-Sequential view and the sources/detectors
// editor (identical settings -> the same cached analysis; the engine store runs it once).
import { selectDetectors, selectSources, useProjectStore } from '../../store/projectStore'
import type { DetectorSpec, NsImportance } from '../../lib/types'
import { useAnalysisSettings } from '../common/useAnalysisSettings'

// imp_target: 'none' | 'det:<detector id>' | 'legacy' (the image-surface disc) | 'sid:<surface id>' (a surface: by id,
// so inserting or moving surfaces keeps it; 'surf:<index>' of older projects is converted when they are opened)
// quantity: what the detector map shows (a display option, like log): irradiance W/mm², illuminance lux, true colour
export type NsQuantity = 'irradiance' | 'illuminance' | 'colour'
export type NsSettings = { field: number; wavelength: number | null; rays: number; overfill: number; split: boolean; include_system: boolean; pixels: number; detector_radius: number | null; log: boolean; seed: number; imp_target: string; imp_rays: number; max_seconds: number | null; quantity: NsQuantity }
// the time limit keeps the live view responsive on systems whose ghost trees are large (many aspheric surfaces)
export const NS_DEFAULTS: NsSettings = { field: 0, wavelength: null, rays: 400, overfill: 1.2, split: true, include_system: true, pixels: 64, detector_radius: null, log: false, seed: 1, imp_target: 'none', imp_rays: 4, max_seconds: 15, quantity: 'irradiance' }

/** The importance-sampling request for a target choice, or null when it is off or no longer valid. */
export function importanceOf(target: string, rays: number, detectors: DetectorSpec[] | null, surfaceIds: string[], scatters: boolean): NsImportance | null {
  if (!scatters || target === 'none') return null
  if (target.startsWith('det:')) {
    const id = target.slice(4)
    return detectors?.some((d) => d.id === id && d.enabled) ? { target: { kind: 'detector', id }, rays } : null
  }
  if (target === 'legacy') return detectors ? null : { target: { kind: 'legacy' }, rays }
  if (target.startsWith('sid:')) {
    const i = surfaceIds.indexOf(target.slice(4))
    return i > 0 ? { target: { kind: 'surface', index: i }, rays } : null
  }
  if (target.startsWith('surf:')) {
    const i = Number(target.slice(5))
    return Number.isInteger(i) && i > 0 && i < surfaceIds.length ? { target: { kind: 'surface', index: i }, rays } : null
  }
  return null
}

export function useNonSeqSettings() {
  const system = useProjectStore((s) => s.project.system)
  const cad = useProjectStore((s) => s.project.cad_assets)
  const projSources = useProjectStore(selectSources)
  const projDetectors = useProjectStore(selectDetectors)
  const [st, set] = useAnalysisSettings('nonseq', NS_DEFAULTS, 'Non-sequential settings')
  // general sources/detectors replace the system field and the image-surface disc when present
  const ownSources = projSources.some((x) => x.enabled)
  const ownDetectors = projDetectors.length > 0
  // light-weight description of the CAD scene so the analysis re-runs when roles or placement change
  const scene = cad.filter((a) => a.optical?.role && a.optical.role !== 'none' && a.visible).map((a) => ({ id: a.id, optical: a.optical, transform: a.transform }))
  const scatters = cad.some((a) => a.visible && a.optical && a.optical.role !== 'none' && a.optical.scatter && a.optical.scatter.model !== 'none' && a.optical.scatter.fraction > 0)
  // the log scale is a display option: keep it out of the analysis key
  const settings = {
    field: Math.min(st.field, system.fields.length - 1),
    wavelength: st.wavelength !== null && st.wavelength >= system.wavelengths.length ? null : st.wavelength,
    rays: st.rays,
    overfill: st.overfill,
    split: st.split,
    include_system: st.include_system,
    pixels: st.pixels,
    detector_radius: st.detector_radius,
    seed: st.seed,
    max_seconds: st.max_seconds,
    importance: importanceOf(st.imp_target, st.imp_rays, ownDetectors ? projDetectors : null, system.surfaces.map((s) => s.id), scatters),
    scene,
    sources: ownSources ? projSources : null,
    detectors: ownDetectors ? projDetectors : null,
  }
  return { st, set, settings, ownSources, ownDetectors, projSources, projDetectors, scatters, system }
}
