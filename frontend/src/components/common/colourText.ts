import { fmt } from '../../lib/format'
import type { useT } from '../../lib/i18n'
import type { DetectorPhotometry, LightQuantities } from '../../lib/types'

/** ± part of a value with its standard error (nothing when there is none). */
const pm = (sigma: number | null | undefined, digits: number) => (sigma ? ` ± ${fmt(sigma, digits)}` : '')

/** "x 0.3252, y 0.3451 · 5820 K (Duv +0.0054)" with standard errors when given. */
export function colourText(q: LightQuantities | DetectorPhotometry, t: ReturnType<typeof useT>): string {
  if (!q.chromaticity) return q.notes[0] ?? '—'
  const s = 'chromaticity_sigma' in q ? q : null
  const xy = `x ${fmt(q.chromaticity.x, 4)}${pm(s?.chromaticity_sigma?.x, 2)}, y ${fmt(q.chromaticity.y, 4)}${pm(s?.chromaticity_sigma?.y, 2)}`
  const duv = q.duv !== null ? `Duv ${q.duv >= 0 ? '+' : ''}${fmt(q.duv, 3)}${pm(s?.duv_sigma, 2)}` : ''
  const cct = q.cct_k !== null ? `${t('light.cct')} ${fmt(q.cct_k, 5)}${pm(s?.cct_sigma_k, 2)} K` : t('light.noCct')
  return `${xy} · ${cct}${duv ? ` (${duv})` : ''}`
}
