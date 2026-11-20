// ISO 10110 element drawings round-trip their prescription (ADR-030).
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { elementDrawingSvg, parseDrawingMeta, radiusText } from './drawing'
import { translate } from './i18n'
import type { ElementsResult, Project } from './types'

const fixture = (name: string) => readFileSync(resolve(process.cwd(), 'src/lib/__fixtures__', name), 'utf-8')
const data = JSON.parse(fixture('elements_achromat.json')) as ElementsResult // engine output for the achromat sample
const project = JSON.parse(fixture('achromat.opticore')) as Project
const t = (k: string, v?: Record<string, string | number>) => translate('en', k, v)
const svgOf = (k: number) => elementDrawingSvg(data.elements[k], { project: 'Achromat', date: '2026-10-13', t })

describe('element drawings', () => {
  it('draws every element of the doublet', () => {
    expect(data.elements.map((e) => e.material.name)).toEqual(['N-BK7', 'F2'])
    for (let k = 0; k < data.elements.length; k++) {
      const svg = svgOf(k)
      expect(svg.startsWith('<svg')).toBe(true)
      expect(svg).toContain('viewBox="0 0 297 210"')
    }
  })

  it('round-trips the prescription values of each element', () => {
    const s = project.system.surfaces
    for (let k = 0; k < data.elements.length; k++) {
      const meta = parseDrawingMeta(svgOf(k))!
      const [a, b] = meta.surfaces
      expect(meta.surface_ids).toEqual([s[a].id, s[b].id])
      expect(meta.radii_mm).toEqual([s[a].radius, s[b].radius])
      expect(meta.center_thickness_mm).toBe(s[a].thickness)
      expect(meta.material).toBe(s[a].material)
      expect(meta.conics).toEqual([s[a].conic, s[b].conic])
      expect(meta.clear_diameters_mm[0]).toBe(2 * data.elements[k].clear_semi_diameters_mm[0])
    }
  })

  it('states the values in ISO 10110 form', () => {
    const svg = svgOf(0)
    const r1 = project.system.surfaces[1].radius!
    expect(svg).toContain(`R ${r1.toFixed(4)} CX`) // front, centre of curvature behind it: convex
    expect(svg).toContain(`R ${Math.abs(project.system.surfaces[2].radius!).toFixed(4)} CX`) // back of the crown lens
    expect(svg).toContain('6.000 ± 0.05') // centre thickness and its tolerance
    expect(svg).toContain('3/3(1)') // power 3 fringes, irregularity 1 fringe
    expect(svg).toContain("4/1'") // tilt 1 arc minute
    expect(svg).toContain('nd = 1.51680 ± 0.0005')
    expect(svg).toContain('Glass code 517642')
    expect(svgOf(1)).toContain(`R ${Math.abs(project.system.surfaces[2].radius!).toFixed(4)} CC`) // the flint's front is concave
    expect(radiusText(null, 0)).toBe('R ∞')
  })

  it('escapes text and keeps the embedded data parseable', () => {
    const el = { ...data.elements[0], material: { ...data.elements[0].material, name: 'A<B&C' } }
    const svg = elementDrawingSvg(el, { project: 'x & <y>', date: 'd', t })
    expect(svg).not.toContain('<y>')
    expect(parseDrawingMeta(svg)!.material).toBe('A<B&C')
  })
})
