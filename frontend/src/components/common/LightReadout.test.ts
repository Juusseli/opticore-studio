import { describe, expect, it } from 'vitest'
import { translate } from '../../lib/i18n'
import type { DetectorPhotometry, LightQuantities } from '../../lib/types'
import { colourText } from './colourText'

const t = ((k: string, v?: Record<string, string | number>) => translate('en', k, v)) as Parameters<typeof colourText>[1]

const base: LightQuantities = {
  power_w: 1,
  luminous_flux_lm: 300,
  scotopic_flux_lm: 500,
  luminous_efficacy_lm_per_w: 300,
  XYZ_w: [0.4, 0.44, 0.4],
  chromaticity: { x: 0.3252, y: 0.3451, u_prime: 0.2, v_prime: 0.48 },
  cct_k: 5820,
  duv: 0.0054,
  srgb: [255, 250, 240],
  notes: [],
}

describe('light read-out', () => {
  it('gives chromaticity, CCT and Duv, with standard errors for a detector', () => {
    expect(colourText(base, t)).toBe('x 0.3252, y 0.3451 · CCT 5820 K (Duv +0.0054)')
    const det = { ...base, chromaticity_sigma: { x: 0.0007, y: 0.001 }, cct_sigma_k: 34, duv_sigma: 0.0005 } as DetectorPhotometry
    expect(colourText(det, t)).toBe('x 0.3252 ± 0.0007, y 0.3451 ± 0.001 · CCT 5820 ± 34 K (Duv +0.0054 ± 0.0005)')
  })

  it('says when there is no CCT or no visible light', () => {
    expect(colourText({ ...base, cct_k: null, duv: 0.1 }, t)).toContain('no CCT')
    expect(colourText({ ...base, chromaticity: null, notes: ['No visible light'] }, t)).toBe('No visible light')
  })
})
