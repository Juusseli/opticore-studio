import * as THREE from 'three'
import { type Frames, resolvePlacement } from '../../../lib/placement'
import type { DetectorSpec, LightSource } from '../../../lib/types'

/** Points that a fit-to-view should include. */
export function nsPoints(sources: LightSource[], detectors: DetectorSpec[], frames?: Frames): THREE.Vector3[] {
  const out: THREE.Vector3[] = []
  for (const s of sources) if (s.kind !== 'system_field') out.push(new THREE.Vector3(...resolvePlacement(s.placement, frames).t))
  for (const d of detectors) {
    const r = d.shape === 'circle' ? d.size_x : Math.max(d.size_x, d.size_y) / 2
    const c = new THREE.Vector3(...resolvePlacement(d.placement, frames).t)
    out.push(c.clone().addScalar(r), c.clone().addScalar(-r))
  }
  return out
}
