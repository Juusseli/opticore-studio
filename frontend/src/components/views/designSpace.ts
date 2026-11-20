import type { DesignMetricKey, DesignTopology, MaterialRecord, Project, StockMatchSpec, StockSpec } from '../../lib/types'
import { GENERIC_ID } from '../../store/stockStore'

export const DS_METRICS: DesignMetricKey[] = ['rms_spot_um', 'rms_spot_max_um', 'mtf', 'length_mm', 'mass_g', 'glass_cost', 'abs_distortion_pct', 'tolerance_rss_um', 'elements', 'parts', 'price', 'merit']

export type DsSettings = {
  focal_length: number
  f_number: number
  half_field_deg: number
  max_length: number | null
  topologies: DesignTopology[]
  candidates: number
  mtf_frequency: number
  tolerances: boolean
  seed: number
  /** 'builtin' | 'project' | 'cat:<catalogue id>' */
  pool: string
  infeasible: boolean
  /** lens forms or stock lenses */
  mode: 'forms' | 'stock'
  stock_task: 'build' | 'match'
  conjugate: 'infinite' | 'finite'
  object_distance: number
  magnification: number
  object_na: number
  object_height: number
  lens_counts: number[]
  /** allowed glasses of the stock lenses (null = all) */
  stock_glasses: string[] | null
  /** stock catalogues: 'generic' and imported catalogue ids */
  stock_catalogs: string[]
  min_gap: number
  tolerance_pct: number
  per_element: number
  stock_candidates: number
}

/** The engine specification of a stock lens build from the view settings. */
export function stockBuildSpec(st: DsSettings, project: Project): StockSpec {
  return {
    conjugate: st.conjugate,
    focal_length: st.focal_length,
    f_number: st.f_number,
    half_field_deg: Math.min(st.half_field_deg, 30),
    object_distance: st.object_distance,
    magnification: st.magnification,
    object_na: st.object_na,
    object_height: st.object_height,
    wavelengths: project.system.wavelengths.map((w) => w.value),
    primary: project.system.primary_wavelength,
    max_length: st.max_length,
    lens_counts: st.lens_counts.length ? st.lens_counts : [1, 2],
    materials: st.stock_glasses,
    generic: st.stock_catalogs.includes(GENERIC_ID),
    min_gap: st.min_gap,
    tolerance: st.tolerance_pct / 100,
    candidates: st.stock_candidates,
    prescreen: 1500,
    mtf_frequency: st.mtf_frequency,
    tolerances: st.tolerances,
    seed: st.seed,
  }
}

export function stockMatchSpec(st: DsSettings): StockMatchSpec {
  return {
    materials: st.stock_glasses,
    generic: st.stock_catalogs.includes(GENERIC_ID),
    per_element: st.per_element,
    min_gap: st.min_gap,
    candidates: st.stock_candidates,
    prescreen: 600,
    mtf_frequency: st.mtf_frequency,
    tolerances: st.tolerances,
    seed: st.seed,
  }
}

/** Starting specification from the open design: its focal length, F/# and field (or 100 mm, F/5, 2°). */
export function specFromDesign(project: Project, paraxial: { efl: number | null; image_space_fnum: number | null } | null): Pick<DsSettings, 'focal_length' | 'f_number' | 'half_field_deg'> {
  const sys = project.system
  const efl = paraxial?.efl
  const fn = paraxial?.image_space_fnum
  const atInf = sys.surfaces[0]?.thickness === null
  const hf = sys.field_type === 'angle' && atInf ? Math.max(0, ...sys.fields.map((f) => Math.hypot(f.x, f.y))) : null
  const round = (v: number, d: number) => Number(v.toPrecision(d))
  return {
    focal_length: efl && efl > 0 && Number.isFinite(efl) ? round(efl, 4) : 100,
    f_number: fn && fn > 0 && Number.isFinite(fn) ? round(fn, 3) : 5,
    half_field_deg: hf !== null && hf <= 40 ? round(hf, 3) : 2,
  }
}

/** The glass pool of a run: null (the built-in glasses) or explicit names, and the records the engine needs. */
export function glassPool(pool: string, project: Project, builtinGlasses: string[], catalogs: { id: string; records: MaterialRecord[] }[]): { glasses: string[] | null; custom: MaterialRecord[] } {
  const own = project.custom_materials
  if (pool === 'project') {
    const extra = own.filter((m) => !m.category || m.category === 'glass').map((m) => m.name)
    return { glasses: [...new Set([...builtinGlasses, ...extra])], custom: own }
  }
  if (pool.startsWith('cat:')) {
    const cat = catalogs.find((c) => 'cat:' + c.id === pool)
    if (cat) {
      const recs = cat.records.filter((r) => r.status !== 'obsolete' && !r.excluded && (!r.category || r.category === 'glass'))
      const names = new Set(recs.map((r) => r.name.toUpperCase()))
      return { glasses: recs.map((r) => r.name), custom: [...recs, ...own.filter((m) => !names.has(m.name.toUpperCase()))] }
    }
  }
  return { glasses: null, custom: own }
}

/** Glasses of the chosen stock catalogues (upper case, sorted). */
export function stockGlasses(catalogIds: string[], generic: { materials: string[] }[] | null, catalogs: { id: string; lenses: { materials: string[] }[] }[]): string[] {
  const lenses = [...(catalogIds.includes(GENERIC_ID) ? (generic ?? []) : []), ...catalogs.filter((c) => catalogIds.includes(c.id)).flatMap((c) => c.lenses)]
  return [...new Set(lenses.flatMap((l) => l.materials.map((m) => m.toUpperCase())))].sort()
}
