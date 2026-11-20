// Human names of optimisation variables (the parameter ids are internal).
import type { VariableParam } from './types'
import { xyTermName } from './xyTerms'

const SUP: Record<string, string> = { '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹' }
const sup = (n: number) => String(n).replace(/\d/g, (d) => SUP[d])

/** Translated label of a variable parameter; `t` is the i18n function. */
export function paramLabel(p: VariableParam | string, t: (k: string, v?: Record<string, string | number>) => string): string {
  let m = /^asph_(\d+)$/.exec(p)
  if (m) return t('par.asph', { r: `r${sup(Number(m[1]))}` })
  m = /^zern_(\d+)$/.exec(p)
  if (m) return t('par.zern', { k: m[1] })
  m = /^q_(\d+)$/.exec(p)
  if (m) return t('par.q', { k: Number(m[1]) - 1 })
  m = /^xy_(\d+)$/.exec(p)
  if (m) return t('par.xy', { term: xyTermName(Number(m[1])) })
  m = /^odd_(\d+)$/.exec(p)
  if (m) return t('par.odd', { r: `r${Number(m[1]) === 1 ? '' : sup(Number(m[1]))}` })
  m = /^phase_(\d+)$/.exec(p)
  if (m) return t('par.phase', { k: m[1] })
  m = /^coat_layer_(\d+)$/.exec(p)
  if (m) return t('par.coatLayer', { k: m[1] })
  const key = `par.${p}`
  const s = t(key)
  return s === key ? p : s
}
