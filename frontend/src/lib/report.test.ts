import { describe, expect, it } from 'vitest'
import { projectChecksum } from './canonical'
import { blankProject } from './project'
import { buildReportHtml, type ReportData } from './report'
import type { Evaluation, SpotResult } from './types'

function fakeData(n: number): ReportData {
  const evaluation = {
    paraxial: { '1': { efl: 100.0001, bfl: 95.5, image_space_fnum: 5, working_fnum: 5.01, image_space_na: 0.0995, paraxial_magnification: null, entrance_pupil_diameter: 20, entrance_pupil_position: 0, exit_pupil_diameter: 19.8, exit_pupil_position: -3, total_track: 105 } },
    surfaces: [],
    rays: [],
    semi_diameters: Array.from({ length: n }, () => 10),
    indices: [Array.from({ length: n }, () => 1.5), Array.from({ length: n }, () => 1.5168), Array.from({ length: n }, () => 1.5)],
    diagnostics: [{ level: 'warning', code: 'TEST_WARN', message: 'A <warning>', surface: 1 }],
    solved: [{ surface: 2, thickness: 96.123456, radius: null, thickness_solve: true, curvature_solve: false }],
  } as unknown as Evaluation
  const spot = {
    fields: [{ field: 0, field_value: [0, 0], reference_xy: [0, 0], chief_xy: [0, 0], centroid_xy: [0, 0], rms_radius_um: 12.34, geo_radius_um: 30.1, per_wavelength: [{ wavelength: 1, points_um: [[1, 2], [-3, 4]], n_rays: 2, n_ok: 2, status: {}, rms_um: 1, geo_um: 1 }] }],
    airy_radius_um: 3.58,
    settings: { pattern: 'hexapolar', density: 6, reference: 'centroid', rays_per_wavelength: 127 },
    units: {},
    method: 'spot method',
  } as unknown as SpotResult
  return { evaluation, spot, mtf: { frequency_cyc_per_mm: [0, 50, 100], fields: [{ field: 0, tangential: [1, 0.6, 0.2], sagittal: [1, 0.62, 0.25] }], diffraction_limit: [1, 0.7, 0.4], cutoff_cyc_per_mm: [340], kind: 'diffraction', units: {}, method: 'mtf method' }, field: null, throughput: null, errors: ['Throughput: engine offline'] }
}

describe('engineering report', () => {
  it('is self-contained, escapes user text and identifies the design by checksum', async () => {
    const p = blankProject('Lens <script>alert(1)</script> & co')
    p.metadata.description = '"quoted" <b>desc</b>'
    p.system.surfaces[2].thickness_solve = { type: 'marginal_height', target: 0, surface_id: null, scale: 1, offset: 0, zone: 1 }
    p.system.primary_wavelength = 1
    const html = await buildReportHtml(p, fakeData(p.system.surfaces.length), { engineVersion: '0.1.0' })
    expect(html).not.toContain('<script>')
    expect(html).toContain('Lens &lt;script&gt;alert(1)&lt;/script&gt; &amp; co')
    expect(html).toContain('&quot;quoted&quot; &lt;b&gt;desc&lt;/b&gt;')
    // no external resources: no src/href to other origins, no stylesheet links
    expect(html).not.toMatch(/<(script|link|img)\b/i)
    expect(html).not.toMatch(/(src|href)=["']https?:/i)
    const checksum = await projectChecksum(JSON.parse(JSON.stringify({ ...p, checksum: null })))
    expect(html).toContain(checksum)
    // sections and values present
    for (const s of ['System summary', 'Prescription', 'Spot diagrams', 'MTF (diffraction)', 'Diagnostics']) expect(html).toContain(s)
    expect(html).toContain('96.123456') // solved thickness shown, not the stored value
    expect(html).toContain('Marginal-ray height solve')
    expect(html).toContain('A &lt;warning&gt;')
    expect(html).toContain('Throughput: engine offline')
    expect(html).toContain('<svg')
  })
})
