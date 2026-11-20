// Settings of the Fibre Modes view (analysis_settings.fibermodes) and the requests built from them. The engine's
// library examples (backend samples.py: fibre_settings, fibre_request) store the same shape and are checked with the
// same mapping, so a change here must be made there too.
import type { Fibre2dSettings, FibreProfileKind, FibreRequest } from './types'

export type FibreSpec = 'na' | 'n_core' | 'dn'

export interface FibreSettings {
  /** null: the system's primary wavelength */
  wavelength_um: number | null
  core_radius_um: number
  spec: FibreSpec
  na: number
  n_core: number
  dn: number
  n_clad: number
  /** '' : the constant n_clad */
  clad_material: string
  vector: boolean
  profile_kind: FibreProfileKind
  alpha: number
  layers: [number, number][]
  dispersion: boolean
  disp_min_um: number
  disp_max_um: number
  disp_points: number
}

export const FIBRE_DEFAULTS: FibreSettings = {
  wavelength_um: null,
  core_radius_um: 4.1,
  spec: 'na',
  na: 0.12,
  n_core: 1.4557,
  dn: 0.005,
  n_clad: 1.444,
  clad_material: 'FUSED_SILICA',
  vector: true,
  profile_kind: 'step',
  alpha: 2,
  layers: [],
  dispersion: false,
  disp_min_um: 1.2,
  disp_max_um: 1.65,
  disp_points: 46,
}

/** A W profile to start a layered design from (core, depressed ring, raised ring). */
export const DEFAULT_LAYERS: [number, number][] = [
  [4, 0.0055],
  [7, -0.0025],
  [9, 0.001],
]

export function fibreRequest(st: FibreSettings, systemWavelength: number): FibreRequest {
  const out: FibreRequest = {
    wavelength_um: st.wavelength_um || systemWavelength,
    core_radius_um: st.core_radius_um,
    vector: st.vector,
    profile_kind: st.profile_kind,
    alpha: st.alpha,
    layers: st.layers,
  }
  out[st.spec] = st[st.spec]
  if (st.clad_material) out.clad_material = st.clad_material
  else out.n_clad = st.n_clad
  return out
}

/** Why a ring table is not a guiding profile (the engine's checks), or null. */
export function layersProblem(layers: [number, number][]): 'empty' | 'order' | 'noCore' | null {
  if (!layers.length) return 'empty'
  for (let i = 0; i < layers.length; i++) if (!(layers[i][0] > (i ? layers[i - 1][0] : 0))) return 'order'
  if (!layers.some(([, d]) => d > 0)) return 'noCore'
  return null
}

/** The six-hole microstructured fibre benchmark (White et al. 2002) as the cross-section view's starting point. */
export const FIBRE2D_DEFAULTS: Fibre2dSettings = {
  wavelength_um: null,
  n_background: 1.45,
  background_material: null,
  lattice: { pitch_um: 6.75, d_um: 5, rings: 1, n_hole: 1, hole_material: null, missing_centre: true },
  shapes: [],
  window_um: 10.5,
  mesh_um: 0.1,
  pml_um: 3,
  polarisation: 'x',
  count: 4,
  n_guess: null,
  refine: false,
}

/** Cells across the solved half window with the absorbing layer, for a given window (the engine refuses more than
 *  700; without a window or mesh the engine picks 100 cells across its own window). */
export function fibre2dCells(s: Fibre2dSettings): number | null {
  if (!s.window_um) return null
  const h = s.mesh_um ?? s.window_um / 100
  return Math.ceil((s.window_um + s.pml_um) / h)
}

export const FIBRE2D_MAX_CELLS = 700
