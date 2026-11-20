import { Html, Line } from '@react-three/drei'
import { useMemo } from 'react'
import * as THREE from 'three'
import { type Frames, framePoint, resolvePlacement } from '../../../lib/placement'
import { DATA, resolveColor } from '../../../lib/palette'
import type { DetectorSpec, LightSource, NonSeqResult, Placement } from '../../../lib/types'

type V3 = [number, number, number]
const DEG = Math.PI / 180

/** Group transform of a placement (anchored placements follow their surface's vertex frame). */
function placementProps(p: Placement, frames?: Frames) {
  const { R, t } = resolvePlacement(p, frames)
  const m = new THREE.Matrix4().set(R[0][0], R[0][1], R[0][2], t[0], R[1][0], R[1][1], R[1][2], t[1], R[2][0], R[2][1], R[2][2], t[2], 0, 0, 0, 1)
  return { matrix: m, matrixAutoUpdate: false }
}

function circle(r: number, n = 64): V3[] {
  return Array.from({ length: n + 1 }, (_, k) => [r * Math.cos((2 * Math.PI * k) / n), r * Math.sin((2 * Math.PI * k) / n), 0] as V3)
}

function rect(w: number, h: number): V3[] {
  return [
    [-w / 2, -h / 2, 0],
    [w / 2, -h / 2, 0],
    [w / 2, h / 2, 0],
    [-w / 2, h / 2, 0],
    [-w / 2, -h / 2, 0],
  ]
}

/** Cone of half-angle theta about +z drawn as 8 generator lines of length L (pairs of points). */
function coneLines(theta: number, L: number): V3[] {
  const out: V3[] = []
  const r = L * Math.sin(theta)
  const z = L * Math.cos(theta)
  for (let k = 0; k < 8; k++) {
    const a = (2 * Math.PI * k) / 8
    out.push([0, 0, 0], [r * Math.cos(a), r * Math.sin(a), z])
  }
  return out
}

function sourceCone(s: LightSource): number | null {
  if (s.kind === 'gaussian_beam') return 0
  switch (s.angular) {
    case 'collimated':
      return 0
    case 'isotropic':
      return null
    case 'cone':
      return s.half_angle_deg * DEG
    case 'gaussian':
      return Math.min(s.half_angle_deg, Math.max(s.gaussian_x_deg, s.gaussian_y_deg)) * DEG
    default:
      // Lambertian / cos^n / table: half-intensity angle of a Lambertian, unless truncated
      return Math.min(s.half_angle_deg, 60) * DEG
  }
}

/** Ray paths of the last non-sequential analysis, by class (direct / after ghost reflections / scattered). */
function NsPaths({ paths }: { paths: NonSeqResult['paths'] }) {
  const groups = useMemo(() => {
    const g: Record<'direct' | 'ghost' | 'scatter', V3[]> = { direct: [], ghost: [], scatter: [] }
    for (const p of paths) {
      const k = (p.scatters ?? 0) > 0 ? 'scatter' : p.reflections > 0 ? 'ghost' : 'direct'
      for (let i = 0; i + 1 < p.points.length; i++) g[k].push(p.points[i] as V3, p.points[i + 1] as V3)
    }
    return g
  }, [paths])
  const col = { direct: resolveColor(DATA.direct), ghost: resolveColor(DATA.ghost), scatter: resolveColor(DATA.scatter) }
  return (
    <>
      {(Object.keys(groups) as (keyof typeof groups)[]).map((k) => (groups[k].length ? <Line key={k} points={groups[k]} segments color={col[k]} lineWidth={1.2} transparent opacity={0.85} toneMapped={false} /> : null))}
    </>
  )
}

/** Non-sequential light sources (orange) and detectors (green) placed in the optical frame, plus the
 * ray paths of the last non-sequential analysis when the project has its own sources. */
export function NsGlyphs({ sources, detectors, scale, paths, frames }: { sources: LightSource[]; detectors: DetectorSpec[]; scale: number; paths?: NonSeqResult['paths'] | null; frames?: Frames }) {
  const L = Math.max(scale * 0.08, 0.5)
  return (
    <>
      {paths && paths.length > 0 && <NsPaths paths={paths} />}
      {sources
        .filter((s) => s.kind !== 'system_field')
        .map((s) => (
          <SourceGlyph key={s.id} s={s} L={L} frames={frames} />
        ))}
      {sources
        .filter((s) => s.kind !== 'system_field' && s.placement.aim)
        .map((s) => (
          <AimLine key={'aim' + s.id} s={s} L={L} frames={frames} />
        ))}
      {detectors.map((d) => (
        <DetectorGlyph key={d.id} d={d} L={L} frames={frames} />
      ))}
    </>
  )
}

function SourceGlyph({ s, L, frames }: { s: LightSource; L: number; frames?: Frames }) {
  // three.js needs a real colour: the token's value in the current theme
  const SRC = resolveColor(DATA.source)
  const op = s.enabled ? 1 : 0.35
  const cone = sourceCone(s)
  const shape = useMemo<V3[] | null>(() => {
    if (s.kind === 'gaussian_beam') return circle(s.beam_waist_x ?? 0.5)
    if (s.shape === 'disk') return circle(s.size_x)
    if (s.shape === 'rectangle') return rect(s.size_x, s.size_y)
    return null
  }, [s.kind, s.beam_waist_x, s.shape, s.size_x, s.size_y])
  const len = Math.max(L, 2 * Math.max(s.kind === 'gaussian_beam' ? (s.beam_waist_x ?? 0.5) : s.shape === 'point' ? 0 : s.size_x, 0))
  return (
    <group {...placementProps(s.placement, frames)}>
      {s.shape === 'point' && s.kind !== 'gaussian_beam' && (
        <mesh>
          <sphereGeometry args={[L * 0.06, 16, 16]} />
          <meshBasicMaterial color={SRC} transparent opacity={op} toneMapped={false} />
        </mesh>
      )}
      {shape && <Line points={shape} color={SRC} lineWidth={1.6} transparent opacity={op} toneMapped={false} />}
      {s.shape === 'sphere' && (
        <mesh>
          <sphereGeometry args={[s.size_x, 20, 14]} />
          <meshBasicMaterial color={SRC} wireframe transparent opacity={0.35 * op} toneMapped={false} />
        </mesh>
      )}
      {s.shape === 'box' && (
        <lineSegments>
          <edgesGeometry args={[new THREE.BoxGeometry(s.size_x, s.size_y, s.size_z)]} />
          <lineBasicMaterial color={SRC} transparent opacity={op} toneMapped={false} />
        </lineSegments>
      )}
      {cone === null ? (
        // isotropic: rays in all directions
        <Line points={[[-len, 0, 0], [len, 0, 0], [0, -len, 0], [0, len, 0], [0, 0, -len], [0, 0, len]]} segments color={SRC} lineWidth={1} transparent opacity={0.7 * op} toneMapped={false} />
      ) : cone === 0 ? (
        <Line points={[[0, 0, 0], [0, 0, len * 1.5], [len * 0.12, 0, len * 1.3], [0, 0, len * 1.5], [-len * 0.12, 0, len * 1.3], [0, 0, len * 1.5]]} segments color={SRC} lineWidth={1.4} transparent opacity={op} toneMapped={false} />
      ) : (
        <>
          <Line points={coneLines(cone, len)} segments color={SRC} lineWidth={1} transparent opacity={0.7 * op} toneMapped={false} />
          {/* the axis of emission */}
          <Line points={[[0, 0, 0], [0, 0, len * 1.5], [len * 0.12, 0, len * 1.3], [0, 0, len * 1.5], [-len * 0.12, 0, len * 1.3], [0, 0, len * 1.5]]} segments color={SRC} lineWidth={1.4} transparent opacity={op} toneMapped={false} />
        </>
      )}
      <Html position={[0, 0, 0]} center style={{ pointerEvents: 'none' }} zIndexRange={[10, 0]}>
        <div className="-translate-y-4 whitespace-nowrap rounded bg-panel/80 px-1 text-caption text-warn">{s.name}</div>
      </Html>
    </group>
  )
}

/** A dotted line from a source to the point it aims at, with a small ring at the point. */
function AimLine({ s, L, frames }: { s: LightSource; L: number; frames?: Frames }) {
  const SRC = resolveColor(DATA.source)
  const c = resolvePlacement(s.placement, frames).t
  const g = framePoint(s.placement, s.placement.aim!, frames)
  const ring = useMemo(() => circle(L * 0.05, 24).map(([x, y]) => [x + g[0], y + g[1], g[2]] as V3), [L, g[0], g[1], g[2]]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      <Line points={[c, g]} color={SRC} lineWidth={1} transparent opacity={s.enabled ? 0.8 : 0.3} toneMapped={false} dashed dashSize={L * 0.04} gapSize={L * 0.06} />
      <Line points={ring} color={SRC} lineWidth={1.2} transparent opacity={s.enabled ? 0.9 : 0.3} toneMapped={false} />
    </>
  )
}

function DetectorGlyph({ d, L, frames }: { d: DetectorSpec; L: number; frames?: Frames }) {
  // three.js needs a real colour: the token's value in the current theme
  const DET = resolveColor(DATA.detector)
  const op = d.enabled ? 1 : 0.35
  const outline = useMemo(() => (d.shape === 'circle' ? circle(d.size_x) : rect(d.size_x, d.size_y)), [d.shape, d.size_x, d.size_y])
  const fill = useMemo(() => (d.shape === 'circle' ? new THREE.CircleGeometry(d.size_x, 48) : new THREE.PlaneGeometry(d.size_x, d.size_y)), [d.shape, d.size_x, d.size_y])
  const ext = d.shape === 'circle' ? d.size_x : Math.max(d.size_x, d.size_y) / 2
  const a = Math.max(L * 0.6, ext * 0.8)
  return (
    <group {...placementProps(d.placement, frames)}>
      <Line points={outline} color={DET} lineWidth={1.8} transparent opacity={op} toneMapped={false} />
      <mesh geometry={fill}>
        <meshBasicMaterial color={DET} transparent opacity={0.12 * op} side={THREE.DoubleSide} depthWrite={false} toneMapped={false} />
      </mesh>
      {/* light is received travelling along +z: arrow ending on the detector */}
      <Line points={[[0, 0, -a], [0, 0, 0], [a * 0.12, 0, -a * 0.2], [0, 0, 0], [-a * 0.12, 0, -a * 0.2], [0, 0, 0]]} segments color={DET} lineWidth={1.4} transparent opacity={op} toneMapped={false} />
      {d.acceptance_deg < 89.9 && <Line points={coneLines(d.acceptance_deg * DEG, a).map(([x, y, z]) => [x, y, -z] as V3)} segments color={DET} lineWidth={1} transparent opacity={0.45 * op} toneMapped={false} dashed dashSize={a * 0.08} gapSize={a * 0.06} />}
      <Html position={[0, 0, 0]} center style={{ pointerEvents: 'none' }} zIndexRange={[10, 0]}>
        <div className="translate-y-4 whitespace-nowrap rounded bg-panel/80 px-1 text-caption text-ok">{d.name}</div>
      </Html>
    </group>
  )
}
