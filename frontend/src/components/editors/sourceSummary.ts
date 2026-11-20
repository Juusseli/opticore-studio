import { fmt } from '../../lib/format'
import type { DetectorSpec, LightSource } from '../../lib/types'

/** One-line description of a source (shape, angular law, power). */
export function sourceSummary(s: LightSource): string {
  if (s.kind === 'system_field') return `system field F${s.field + 1} · ${fmt(s.power_w, 4)} W`
  if (s.kind === 'gaussian_beam') {
    const wx = s.beam_waist_x ?? 0.5
    const wy = s.beam_waist_y ?? 0.5
    const m2 = s.beam_m2 ?? 1
    return `Gaussian beam w₀ ${fmt(wx, 4)}${wy !== wx ? `×${fmt(wy, 4)}` : ''} mm${m2 !== 1 ? ` · M² ${fmt(m2, 3)}` : ''} · ${fmt(s.power_w, 4)} W`
  }
  const shape = s.shape === 'point' ? 'point' : s.shape === 'disk' ? `disk r ${fmt(s.size_x, 4)}` : s.shape === 'rectangle' ? `rect ${fmt(s.size_x, 4)}×${fmt(s.size_y, 4)}` : s.shape === 'sphere' ? `sphere r ${fmt(s.size_x, 4)}` : `box ${fmt(s.size_x, 3)}×${fmt(s.size_y, 3)}×${fmt(s.size_z, 3)}`
  const ang =
    s.angular === 'cone'
      ? `cone ${fmt(s.half_angle_deg, 4)}°`
      : s.angular === 'gaussian'
        ? `gauss ${fmt(s.gaussian_x_deg, 3)}°${s.gaussian_y_deg !== s.gaussian_x_deg ? `×${fmt(s.gaussian_y_deg, 3)}°` : ''}`
        : s.angular === 'cosine_power'
          ? `cos^${fmt(s.cos_power, 3)}`
          : s.angular
  return `${shape}${s.spatial === 'gaussian' && (s.shape === 'disk' || s.shape === 'rectangle') ? ' (gauss)' : ''} · ${ang} · ${fmt(s.power_w, 4)} W`
}

export function detectorSummary(d: DetectorSpec): string {
  const size = d.shape === 'circle' ? `Ø ${fmt(2 * d.size_x, 4)}` : `${fmt(d.size_x, 4)}×${fmt(d.size_y, 4)}`
  return `${size} mm${d.acceptance_deg < 90 ? ` · ≤ ${fmt(d.acceptance_deg, 4)}°` : ''} · ${d.mode}${d.two_sided ? ' · 2-sided' : ''}`
}
