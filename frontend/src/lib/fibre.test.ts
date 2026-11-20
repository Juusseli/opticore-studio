import { describe, expect, it } from 'vitest'
import examples from './__fixtures__/fibre_examples.json'
import { FIBRE_DEFAULTS, FIBRE2D_DEFAULTS, fibre2dCells, fibreRequest, layersProblem, type FibreSettings } from './fibre'

describe('fibre requests', () => {
  it('builds the request the engine checks for every library fibre example', () => {
    // the fixture comes from backend samples.py (python -m opticore.tools.fibre_examples --write), whose tests run
    // these requests against independent results; backend/tests/test_fibre_examples.py keeps it current
    const all = Object.entries(examples as unknown as Record<string, { settings: FibreSettings; system_wavelength_um: number; request: unknown }>)
    expect(all.length).toBeGreaterThanOrEqual(3)
    for (const [id, ex] of all) {
      expect({ ...FIBRE_DEFAULTS, ...ex.settings }, id).toEqual(ex.settings) // the stored shape is the view's shape
      expect(fibreRequest(ex.settings, ex.system_wavelength_um), id).toEqual(ex.request)
    }
  })

  it('sends one core contrast and the cladding as a material or an index', () => {
    const r = fibreRequest({ ...FIBRE_DEFAULTS, spec: 'n_core', clad_material: '', wavelength_um: 1.3 }, 1.55)
    expect(r.n_core).toBe(FIBRE_DEFAULTS.n_core)
    expect(r.na).toBeUndefined()
    expect(r.dn).toBeUndefined()
    expect(r.n_clad).toBe(FIBRE_DEFAULTS.n_clad)
    expect(r.clad_material).toBeUndefined()
    expect(r.wavelength_um).toBe(1.3)
    expect(fibreRequest(FIBRE_DEFAULTS, 1.55).wavelength_um).toBe(1.55)
  })

  it('checks a ring table as the engine does', () => {
    expect(layersProblem([])).toBe('empty')
    expect(layersProblem([[4, 0.005], [3, -0.001]])).toBe('order')
    expect(layersProblem([[4, -0.005]])).toBe('noCore')
    expect(layersProblem([[4, 0.005], [9, 0], [14, -0.005]])).toBeNull()
  })

  it('counts the cross-section mesh with the absorbing layer', () => {
    expect(fibre2dCells(FIBRE2D_DEFAULTS)).toBe(135) // (10.5 + 3) / 0.1
    expect(fibre2dCells({ ...FIBRE2D_DEFAULTS, window_um: null })).toBeNull()
  })
})
