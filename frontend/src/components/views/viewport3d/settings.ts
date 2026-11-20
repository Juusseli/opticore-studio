import { useState } from 'react'
import { loadPref, savePref } from '../../../lib/storage'

/** 3D view preferences (per viewer, stored in the browser; not part of the project). */
export interface View3DSettings {
  projection: 'perspective' | 'orthographic'
  /** high: physical glass, ambient occlusion, bloom, soft contact shadows; fast: light materials, no post-processing */
  quality: 'high' | 'fast'
  rayWidth: number // px
  ground: boolean
  clip: { on: boolean; axis: 'x' | 'y' | 'z'; offset: number; flip: boolean }
}

export const VIEW3D_DEFAULTS: View3DSettings = {
  projection: 'perspective',
  quality: 'high',
  rayWidth: 1.6,
  ground: true,
  clip: { on: false, axis: 'x', offset: 0, flip: false },
}

export function useView3DSettings() {
  const [s, setS] = useState<View3DSettings>(() => {
    const v = loadPref<Partial<View3DSettings>>('view3d', {})
    return { ...VIEW3D_DEFAULTS, ...v, clip: { ...VIEW3D_DEFAULTS.clip, ...(v.clip ?? {}) } }
  })
  const set = (patch: Partial<View3DSettings>) =>
    setS((cur) => {
      const next = { ...cur, ...patch, clip: { ...cur.clip, ...(patch.clip ?? {}) } }
      savePref('view3d', next)
      return next
    })
  return [s, set] as const
}
