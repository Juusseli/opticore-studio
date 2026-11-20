import { fmt } from '../../lib/format'
import type { OpticalSystem } from '../../lib/types'

interface TreeNode {
  label: string
  detail?: string
  surfaces: number[]
  kind: 'object' | 'lens' | 'mirror' | 'stop' | 'cb' | 'surface' | 'image'
}

/** Group surfaces into elements: consecutive surfaces bounding glass form one lens (cemented groups merge). */
export function assemblyTree(s: OpticalSystem, t: (k: string) => string = (k) => k): TreeNode[] {
  const out: TreeNode[] = []
  const n = s.surfaces.length
  const glass = (m: string) => !['AIR', 'MIRROR', 'VACUUM'].includes(m)
  out.push({ label: t('sb.object'), detail: s.surfaces[0].thickness === null ? '∞' : `${fmt(s.surfaces[0].thickness, 5)} mm`, surfaces: [0], kind: 'object' })
  let i = 1
  let lens = 0
  while (i < n - 1) {
    const sf = s.surfaces[i]
    if (sf.type !== 'coordinate_break' && glass(sf.material)) {
      const group = [i]
      const mats = [sf.material]
      let j = i + 1
      while (j < n - 1 && s.surfaces[j].type !== 'coordinate_break' && glass(s.surfaces[j].material)) {
        group.push(j)
        mats.push(s.surfaces[j].material)
        j++
      }
      if (j < n) group.push(j)
      lens++
      out.push({ label: `${mats.length > 1 ? t('sb.cemented') : t('sb.lens')} ${lens}`, detail: mats.join(' / '), surfaces: group, kind: 'lens' })
      i = j + 1
      continue
    }
    if (sf.material === 'MIRROR') out.push({ label: sf.label || `${t('sb.mirror')} ${i}`, detail: sf.radius === null ? t('sb.plane') : `R ${fmt(sf.radius, 5)}`, surfaces: [i], kind: 'mirror' })
    else if (sf.type === 'coordinate_break') out.push({ label: sf.label || `${t('sb.cb')} ${i}`, detail: `tilt ${fmt(sf.tilt_x, 3)}/${fmt(sf.tilt_y, 3)}/${fmt(sf.tilt_z, 3)}°`, surfaces: [i], kind: 'cb' })
    else if (sf.is_stop) out.push({ label: sf.label || t('sb.stop'), detail: `${t('c.surface')} ${i}`, surfaces: [i], kind: 'stop' })
    else out.push({ label: sf.label || `${t('c.surface')} ${i}`, detail: sf.radius === null ? t('sb.plane') : `R ${fmt(sf.radius, 5)}`, surfaces: [i], kind: 'surface' })
    i++
  }
  out.push({ label: t('sb.image'), detail: `${t('c.surface')} ${n - 1}`, surfaces: [n - 1], kind: 'image' })
  return out
}
