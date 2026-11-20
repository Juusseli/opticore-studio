// Read-outs of the light's photometric and colorimetric quantities (engine photometry/): luminous flux, colour
// swatch, chromaticity, correlated colour temperature. Used by the light sources editor and the Non-Sequential view.
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import type { LightQuantities } from '../../lib/types'
import { colourText } from './colourText'

export function Swatch({ rgb, title }: { rgb: [number, number, number] | null | undefined; title?: string }) {
  if (!rgb) return null
  return <span className="inline-block h-3 w-3 shrink-0 rounded border border-line align-[-2px]" style={{ background: `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})` }} title={title} aria-hidden />
}

/** One line: swatch, luminous flux (and efficacy), colour. */
export function LightLine({ q }: { q: LightQuantities | null | undefined }) {
  const t = useT()
  if (!q) return <span className="text-faint">—</span>
  if (!q.chromaticity) return <span className="text-muted">{q.notes[0]}</span>
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1.5 text-small">
      <Swatch rgb={q.srgb} />
      <span className="num">
        {fmt(q.luminous_flux_lm, 5)} lm{q.luminous_efficacy_lm_per_w !== null && ` (${fmt(q.luminous_efficacy_lm_per_w, 4)} lm/W)`}
      </span>
      <span className="num text-muted">{colourText(q, t)}</span>
    </span>
  )
}
