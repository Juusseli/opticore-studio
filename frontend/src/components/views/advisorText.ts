import { fmt } from '../../lib/format'
import type { useT } from '../../lib/i18n'
import type { AdvisorFinding, AdvisorSuggestion, OpticalSystem } from '../../lib/types'

type Translate = ReturnType<typeof useT>

const signed = (v: number, d = 4) => `${v > 0 ? '+' : ''}${fmt(v, d)}`
export const pct = (v: number) => fmt(v * 100, 3)

export function fieldLabel(system: OpticalSystem, i: number): string {
  const f = system.fields[i]
  return f ? `F${i + 1} (${fmt(f.y, 4)}${system.field_type === 'angle' ? '°' : ' mm'})` : `F${i + 1}`
}

/** One sentence per finding (the numbers come from the engine; only the wording is here). */
export function findingText(t: Translate, f: AdvisorFinding, system: OpticalSystem): string {
  switch (f.kind) {
    case 'focus':
      // best_defocus_mm is the change of the image distance (along the image surface normal), so it reads the same after mirrors
      return t('adv.f.focus', { d: fmt(Math.abs(f.defocus_mm), 4), s: signed(f.defocus_mm), a: fmt(f.rms_um, 3), b: fmt(f.rms_best_um, 3) })
    case 'field_curvature':
      return t('adv.f.field_curvature', { w: fmt(f.rms_waves, 3), f: fieldLabel(system, f.field) })
    case 'aberration':
      return t('adv.f.aberration', { f: fieldLabel(system, f.field), c: t('adv.c.' + f.class), p: pct(f.share), w: fmt(f.rms_waves, 3) })
    case 'axial_colour':
      return t('adv.f.axial_colour', { v: fmt(f.value_um, 3), r: fmt(f.ratio, 2) })
    case 'lateral_colour':
      return t('adv.f.lateral_colour', { v: fmt(f.value_um, 3), f: fieldLabel(system, f.field), r: fmt(f.ratio, 2) })
    case 'distortion':
      return t(f.percent < 0 ? 'adv.f.barrel' : 'adv.f.pincushion', { p: fmt(Math.abs(f.percent), 3) })
    case 'diffraction_limited':
      return t('adv.f.diffraction_limited')
  }
}

/** Short name of a finding (System card). */
export function findingShort(t: Translate, f: AdvisorFinding): string {
  if (f.kind === 'aberration') return t('adv.c.' + f.class)
  return t('adv.s.' + f.kind)
}

export function describeMove(t: Translate, sg: AdvisorSuggestion): string {
  const s = sg.surface ?? 0
  switch (sg.kind) {
    case 'refocus':
      return t('adv.mv.refocus', { d: signed(sg.t) })
    case 'bend': {
      const g = sg.surfaces ?? []
      return t('adv.mv.bend', { s: g.length ? `S${g[0]}–S${g[g.length - 1]}` : '' })
    }
    case 'curvature':
      return t('adv.mv.curvature', { s })
    case 'stop':
      return t('adv.mv.stop', { d: signed(sg.t) })
    case 'gap':
      return t('adv.mv.gap', { s, d: signed(sg.t) })
    case 'thickness':
      return t('adv.mv.thickness', { s, d: signed(sg.t) })
    case 'conic':
      return t('adv.mv.conic', { s })
    case 'glass':
      return t('adv.mv.glass', { s, a: sg.from ?? '', b: sg.to ?? '' })
  }
}
