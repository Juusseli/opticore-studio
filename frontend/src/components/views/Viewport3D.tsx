import { isRunning, useOptStore } from '../../store/optStore'
import { Bvh, ContactShadows, Environment, GizmoHelper, GizmoViewcube, Html, Lightformer, Line, OrbitControls, OrthographicCamera, PerspectiveCamera } from '@react-three/drei'
import { Canvas, useThree } from '@react-three/fiber'
import { Bloom, EffectComposer, N8AO, SMAA, Vignette } from '@react-three/postprocessing'
import { ArrowLeftRight, Box as BoxIcon, Camera, Eye, Maximize2, MoveHorizontal, Ruler, Scissors, Sparkles, Trash2, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import { api } from '../../lib/api'
import { findNode, partAtTriangle, visibleRanges } from '../../lib/cadTree'
import { fieldColor, fmt } from '../../lib/format'
import { DATA, resolveColor, SCENE } from '../../lib/palette'
import { useT } from '../../lib/i18n'
import type { CadAsset, Evaluation, NonSeqResult, SurfaceGeometry } from '../../lib/types'
import { useEngineStore } from '../../store/engineStore'
import { type MeasurePick, useMeasureStore } from '../../store/measureStore'
import { selectDetectors, selectSources, useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { Badge, Checkbox, IconButton, NumberField, Select } from '../common/ui'
import { Label, MoreSettings } from '../common/controls'
import { ViewState } from './ViewState'
import { b64ToBuffer, edgeBand, elementGeometry, fitView, groundGrid, mirrorBlank, mirrorSide, niceStep, rayPolylines, rimGeometry, sceneBounds, stopRing, surfaceDisk } from './viewport3d/geometry'
import { type View3DSettings, useView3DSettings } from './viewport3d/settings'
import { NsGlyphs } from './viewport3d/NsGlyphs'
import { nsPoints } from './viewport3d/nsPoints'
import { surfaceFrames } from '../../lib/placement'

type V3 = [number, number, number]
type ViewKey = 'iso' | 'side' | 'top' | 'front' | 'fit'
const VIEW_DIRS: Record<Exclude<ViewKey, 'fit'>, V3> = {
  iso: [-0.85, 0.38, -0.36], // three-quarter view, light travelling left to right
  side: [-1, 0, 0], // y-z plane (the 2D layout)
  top: [-0.005, 1, 0], // x-z plane from above (tiny tilt keeps "up" well defined)
  front: [0, 0, -1], // along the optical axis, from the object side
}

// ---------------------------------------------------------------------------- optics
function Scene({
  ev,
  infinite,
  primary,
  selection,
  onSelect,
  dark,
  st,
  clip,
}: {
  ev: Evaluation
  infinite: boolean
  primary: number
  selection: number[]
  onSelect: (i: number, p?: THREE.Vector3) => void
  dark: boolean
  st: View3DSettings
  clip: THREE.Plane[]
}) {
  const S = SCENE[dark ? 'dark' : 'light']
  const selColor = resolveColor(DATA.selection)
  // glass index at the primary wavelength drives the refraction of the environment through the lens
  const prim = Math.max(0, Math.min((ev.indices?.length ?? 1) - 1, primary))
  const elements = useMemo(
    () =>
      ev.elements
        .map((el) => {
          const e = elementGeometry(ev.surfaces[el.front], ev.surfaces[el.back])
          const n = ev.indices?.[prim]?.[el.front] ?? 1.5
          return e ? { el, geo: e.geo, edge: edgeBand(ev.surfaces[el.front], ev.surfaces[el.back]), thickness: e.thickness, n } : null
        })
        .filter(Boolean) as {
        el: { front: number; back: number }
        geo: THREE.BufferGeometry
        edge: THREE.BufferGeometry | null
        thickness: number
        n: number
      }[],
    [ev, prim],
  )
  const mirrors = useMemo(
    () =>
      ev.surfaces
        .map((s, i) =>
          s.is_mirror
            ? {
                s,
                i,
                face: surfaceDisk(s),
                blank: mirrorBlank(s, mirrorSide(ev, i)),
              }
            : null,
        )
        .filter((x) => x && x.face) as {
        s: SurfaceGeometry
        i: number
        face: THREE.BufferGeometry
        blank: THREE.BufferGeometry | null
      }[],
    [ev],
  )
  // ideal lenses: a thin translucent disk (no physical glass)
  const ideals = useMemo(() => ev.surfaces.map((s, i) => (s.is_ideal ? { i, geo: surfaceDisk(s) } : null)).filter((x) => x?.geo) as { i: number; geo: THREE.BufferGeometry }[], [ev])
  const image = useMemo(() => {
    const i = ev.surfaces.length - 1
    const s = ev.surfaces[i]
    return s ? { i, geo: surfaceDisk(s) } : null
  }, [ev])
  const stops = useMemo(() => ev.surfaces.map((s, i) => (s.is_stop && s.type !== 'coordinate_break' ? { i, geo: stopRing(s) } : null)).filter((x) => x?.geo) as { i: number; geo: THREE.BufferGeometry }[], [ev])
  const rims = useMemo(
    () =>
      ev.surfaces.map((s, i) => ({
        i,
        s,
        geo: s.type !== 'coordinate_break' && s.semi_diameter > 0 && !(i === 0 && infinite) ? rimGeometry(s) : null,
      })),
    [ev, infinite],
  )
  const rays = useMemo(() => {
    const groups: Record<number, THREE.Vector3[]> = {}
    for (const { field, pts } of rayPolylines(ev, infinite)) {
      const arr = (groups[field] ??= [])
      for (let k = 0; k + 1 < pts.length; k++) arr.push(new THREE.Vector3(...pts[k]), new THREE.Vector3(...pts[k + 1]))
    }
    return Object.entries(groups).map(([f, pts]) => ({ field: Number(f), pts }))
  }, [ev, infinite])

  useEffect(
    () => () => {
      elements.forEach((e) => (e.geo.dispose(), e.edge?.dispose()))
      mirrors.forEach((m) => (m.face.dispose(), m.blank?.dispose()))
      image?.geo?.dispose()
      ideals.forEach((x) => x.geo.dispose())
      stops.forEach((s) => s.geo.dispose())
      rims.forEach((r) => r.geo?.dispose())
    },
    [elements, mirrors, image, stops, rims, ideals],
  )
  const high = st.quality === 'high'
  const side = clip.length ? THREE.DoubleSide : THREE.FrontSide
  return (
    <>
      {elements.map(({ el, geo, edge, thickness, n }) => {
        const sel = selection.includes(el.front) || selection.includes(el.back)
        return (
          <group key={'e' + el.front}>
            <mesh geometry={geo} onClick={(e) => (e.stopPropagation(), onSelect(el.front, e.point))} castShadow>
              {high ? (
                <meshPhysicalMaterial
                  color={sel ? S.glassSelected : S.glass}
                  transmission={1}
                  thickness={Math.max(thickness, 0.5)}
                  ior={Math.min(2.333, Math.max(1, n))}
                  roughness={0.02}
                  metalness={0}
                  specularIntensity={1}
                  envMapIntensity={1.15}
                  attenuationColor={S.glassAttenuation}
                  attenuationDistance={dark ? Math.max(thickness * 8, 20) : Math.max(thickness * 3, 8)}
                  emissive={sel ? S.glassEmissiveSelected : S.black}
                  emissiveIntensity={sel ? 0.12 : 0}
                  clippingPlanes={clip}
                  side={side}
                  // no depth: rays inside the glass stay visible and ambient occlusion ignores the glass
                  depthWrite={false}
                />
              ) : (
                <meshStandardMaterial color={sel ? S.glassFastSelected : S.glassFast} transparent opacity={0.32} roughness={0.1} side={THREE.DoubleSide} depthWrite={false} clippingPlanes={clip} />
              )}
            </mesh>
            {edge && high && (
              // ground glass edge, as on a real lens
              <mesh geometry={edge}>
                <meshPhysicalMaterial color={sel ? S.edgeSelected : S.edge} roughness={0.62} transmission={0.55} thickness={1} metalness={0} envMapIntensity={0.9} side={THREE.DoubleSide} clippingPlanes={clip} depthWrite={false} />
              </mesh>
            )}
          </group>
        )
      })}
      {mirrors.map(({ i, face, blank }) => (
        <group key={'m' + i}>
          <mesh geometry={face} onClick={(e) => (e.stopPropagation(), onSelect(i, e.point))}>
            <meshPhysicalMaterial color={selection.includes(i) ? S.mirrorSelected : S.mirror} metalness={1} roughness={0.06} envMapIntensity={1.4} clearcoat={0.3} side={THREE.DoubleSide} clippingPlanes={clip} />
          </mesh>
          {blank && (
            <mesh geometry={blank} castShadow>
              <meshStandardMaterial color={S.mirrorBack} metalness={0.2} roughness={0.55} side={THREE.DoubleSide} clippingPlanes={clip} />
            </mesh>
          )}
        </group>
      ))}
      {ideals.map(({ i, geo }) => (
        <mesh key={'id' + i} geometry={geo} onClick={(e) => (e.stopPropagation(), onSelect(i, e.point))}>
          <meshStandardMaterial color={selection.includes(i) ? selColor : S.ideal} transparent opacity={0.18} roughness={0.4} side={THREE.DoubleSide} depthWrite={false} clippingPlanes={clip} />
        </mesh>
      ))}
      {image?.geo && (
        <mesh geometry={image.geo} onClick={(e) => (e.stopPropagation(), onSelect(image.i, e.point))}>
          <meshStandardMaterial color={S.sensor} metalness={0.35} roughness={0.38} emissive={S.sensorEmissive} emissiveIntensity={0.4} side={THREE.DoubleSide} clippingPlanes={clip} />
        </mesh>
      )}
      {stops.map(({ i, geo }) => (
        <mesh key={'s' + i} geometry={geo}>
          <meshStandardMaterial color={S.iris} metalness={0.75} roughness={0.32} side={THREE.DoubleSide} clippingPlanes={clip} />
        </mesh>
      ))}
      {rims.map(({ i, s, geo }) =>
        geo ? (
          <lineLoop key={'r' + i} geometry={geo}>
            <lineBasicMaterial color={selection.includes(i) || s.is_stop ? selColor : S.outline} transparent opacity={0.8} />
          </lineLoop>
        ) : null,
      )}
      {rays.map(({ field, pts }) => (pts.length ? <Line key={'ray' + field} points={pts} segments color={resolveColor(fieldColor(field))} lineWidth={st.rayWidth} toneMapped={false} transparent opacity={0.95} /> : null))}
    </>
  )
}

// ---------------------------------------------------------------------------- CAD models
export interface CadPickEvent {
  asset: CadAsset
  partId: string | null
  point: V3
}

/** Imported CAD meshes placed in the optical global frame (display only: the engine traces the models' own geometry).
 * Hidden assembly parts are left out (geometry groups over the per-part triangle ranges);
 * the selected part is highlighted; clicks report the part under the cursor (BVH-accelerated). */
function CadMeshes({ assets, onPick, clip, high }: { assets: CadAsset[]; onPick: (e: CadPickEvent) => void; clip: THREE.Plane[]; high: boolean }) {
  const selected = useMeasureStore((s) => s.selected)
  const invalidate = useThree((s) => s.invalidate)
  const geos = useMemo(
    () =>
      assets.map((a) => {
        const g = new THREE.BufferGeometry()
        g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(b64ToBuffer(a.mesh.positions_b64)), 3))
        g.setIndex(new THREE.BufferAttribute(new Uint32Array(b64ToBuffer(a.mesh.indices_b64)), 1))
        g.computeVertexNormals()
        return { id: a.id, g }
      }),
    // geometry depends only on the mesh data, not on placement or colour
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [assets.map((a) => a.id + a.mesh.positions_b64.length + a.mesh.indices_b64.length).join('|')],
  )
  const views = useMemo(
    () =>
      assets.map((a, k) => {
        const g = geos[k]?.g
        if (!g) return null
        const tree = a.tree ?? []
        const ranges = visibleRanges(tree, a.hidden_parts ?? [], a.mesh.triangles)
        const sel = selected && selected.asset_id === a.id ? (selected.part_id ? findNode(tree, selected.part_id) : null) : null
        const hs = sel ? sel.tri_start : selected?.asset_id === a.id ? 0 : -1
        const he = sel ? sel.tri_start + sel.tri_count : selected?.asset_id === a.id ? a.mesh.triangles : -1
        const groups: { start: number; count: number; mat: number }[] = []
        for (const [st, cnt] of ranges) {
          const en = st + cnt
          const cuts = [st, Math.min(Math.max(hs, st), en), Math.min(Math.max(he, st), en), en]
          for (let q = 0; q < 3; q++) {
            const a0 = cuts[q]
            const a1 = cuts[q + 1]
            if (a1 > a0) groups.push({ start: a0, count: a1 - a0, mat: q === 1 ? 1 : 0 })
          }
        }
        const idx = g.getIndex()!.array as Uint32Array
        const sub = new Uint32Array(ranges.reduce((n, r) => n + r[1] * 3, 0))
        let o = 0
        for (const [st, cnt] of ranges) {
          sub.set(idx.subarray(st * 3, (st + cnt) * 3), o)
          o += cnt * 3
        }
        const eg = new THREE.BufferGeometry()
        eg.setAttribute('position', g.getAttribute('position'))
        eg.setIndex(new THREE.BufferAttribute(sub, 1))
        return { groups, edges: new THREE.EdgesGeometry(eg, 30), eg }
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [geos, assets.map((a) => a.id + (a.hidden_parts ?? []).join(',')).join('|'), selected?.asset_id, selected?.part_id],
  )
  const mats = useMemo(
    () =>
      assets.map((a) => [
        new THREE.MeshPhysicalMaterial({
          color: a.color,
          transparent: a.opacity < 1,
          opacity: a.opacity,
          roughness: 0.42,
          metalness: 0.35,
          clearcoat: high ? 0.25 : 0,
          envMapIntensity: 1,
          side: THREE.DoubleSide,
          depthWrite: a.opacity >= 1,
        }),
        new THREE.MeshPhysicalMaterial({
          color: resolveColor(DATA.selection),
          emissive: SCENE.dark.rayHighlight,
          emissiveIntensity: 0.6,
          transparent: true,
          opacity: Math.max(0.8, a.opacity),
          roughness: 0.3,
          metalness: 0.2,
          side: THREE.DoubleSide,
        }),
      ]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [assets.map((a) => a.id + a.color + a.opacity).join('|'), high],
  )
  // section plane on CAD materials
  useEffect(() => {
    for (const m of mats)
      for (const x of m) {
        if ((x.clippingPlanes?.length ?? 0) !== clip.length) x.needsUpdate = true // the shader depends on the number of planes
        x.clippingPlanes = clip
      }
    invalidate()
  }, [mats, clip, invalidate])
  useEffect(() => () => geos.forEach((x) => x.g.dispose()), [geos])
  useEffect(() => () => views.forEach((v) => (v?.edges.dispose(), v?.eg.dispose())), [views])
  useEffect(() => () => mats.forEach((m) => m.forEach((x) => x.dispose())), [mats])
  const deg = Math.PI / 180
  return (
    <Bvh firstHitOnly>
      {assets.map((a, k) => {
        const v = views[k]
        const gg = geos[k]?.g
        if (!a.visible || !v || !gg) return null
        return (
          <group key={a.id} position={a.transform.translate} rotation={[a.transform.rotate_deg[0] * deg, a.transform.rotate_deg[1] * deg, a.transform.rotate_deg[2] * deg, 'XYZ']}>
            <mesh
              geometry={gg}
              castShadow
              onUpdate={(m) => {
                m.geometry.clearGroups()
                for (const grp of v.groups) m.geometry.addGroup(grp.start * 3, grp.count * 3, grp.mat)
              }}
              key={v.groups.map((x) => `${x.start}:${x.count}:${x.mat}`).join(',')}
              onClick={(e) => {
                e.stopPropagation()
                const tri = e.faceIndex ?? -1
                const node = a.tree?.length ? partAtTriangle(a.tree, tri) : null
                onPick({
                  asset: a,
                  partId: node ? node.id : null,
                  point: [e.point.x, e.point.y, e.point.z],
                })
              }}
              material={mats[k]}
            />
            <lineSegments geometry={v.edges}>
              <lineBasicMaterial color={a.color} transparent opacity={Math.min(1, a.opacity * 0.6 + 0.25)} clippingPlanes={clip} />
            </lineSegments>
          </group>
        )
      })}
    </Bvh>
  )
}

/** Picked points, measured distances and clearances (lines with labels). */
function MeasureLayer({ scale, width }: { scale: number; width: number }) {
  const picks = useMeasureStore((s) => s.picks)
  const results = useMeasureStore((s) => s.results)
  const r = Math.max(scale * 0.006, 0.02)
  return (
    <>
      {picks.map((p, k) => (
        <mesh key={'p' + k} position={p.point}>
          <sphereGeometry args={[r, 16, 16]} />
          <meshBasicMaterial color={resolveColor(DATA.measure)} toneMapped={false} />
        </mesh>
      ))}
      {results.map((m) => {
        const mid: V3 = [(m.a[0] + m.b[0]) / 2, (m.a[1] + m.b[1]) / 2, (m.a[2] + m.b[2]) / 2]
        const col = resolveColor(m.kind === 'clearance' ? DATA.target : DATA.measure)
        return (
          <group key={m.id}>
            <Line points={[m.a, m.b]} color={col} lineWidth={Math.max(2, width + 0.6)} toneMapped={false} depthTest={false} />
            {[m.a, m.b].map((p, k) => (
              <mesh key={k} position={p} renderOrder={10}>
                <sphereGeometry args={[r, 16, 16]} />
                <meshBasicMaterial color={col} depthTest={false} toneMapped={false} />
              </mesh>
            ))}
            <Html position={mid} center zIndexRange={[20, 0]}>
              <div className="pointer-events-none whitespace-nowrap rounded border border-line bg-panel/90 px-1.5 py-0.5 text-small font-semibold text-fg shadow">{m.pending ? '…' : `${fmt(m.distance_mm, 6)} mm`}</div>
            </Html>
          </group>
        )
      })}
    </>
  )
}

// ---------------------------------------------------------------------------- environment and look
/** Procedural studio lighting (no downloaded HDR): soft boxes and rim lights rendered into the environment map once. */
function Studio({ dark }: { dark: boolean }) {
  const S = SCENE[dark ? 'dark' : 'light']
  return (
    <Environment resolution={256} frames={1} background={false} environmentIntensity={dark ? 0.9 : 1.05}>
      <color attach="background" args={[S.background]} />
      {/* key light from above, softboxes left/right, a ring for round highlights */}
      <Lightformer form="rect" intensity={3.2} position={[0, 6, 0]} rotation-x={Math.PI / 2} scale={[12, 6, 1]} />
      <Lightformer form="rect" intensity={1.6} position={[-6, 2, -3]} rotation-y={Math.PI / 2.4} scale={[6, 3, 1]} color={S.lightCool} />
      <Lightformer form="rect" intensity={1.2} position={[6, 1, 3]} rotation-y={-Math.PI / 2.2} scale={[5, 2.5, 1]} color={S.lightWarm} />
      <Lightformer form="ring" intensity={2} position={[0, 1, -7]} scale={3} color={S.lightWhite} />
      {/* vertical strip lights around the horizon: crisp edge highlights on glass from every viewing angle */}
      {[0, 1, 2, 3, 4, 5, 6, 7].map((k) => {
        const a = (k / 8) * Math.PI * 2 + Math.PI / 8
        return <Lightformer key={k} form="rect" intensity={k % 2 ? 1.4 : 2.2} position={[Math.cos(a) * 8, 0.5, Math.sin(a) * 8]} rotation-y={-a - Math.PI / 2} scale={[0.6, 7, 1]} color={k % 3 ? S.lightWhite : S.lightSky} />
      })}
      <Lightformer form="rect" intensity={dark ? 0.35 : 0.8} position={[0, -4, 0]} rotation-x={-Math.PI / 2} scale={[14, 14, 1]} color={S.floorLight} />
    </Environment>
  )
}

/** Vertical gradient background (works with post-processing, unlike a transparent canvas). */
function GradientBackground({ dark }: { dark: boolean }) {
  const tex = useMemo(() => {
    const c = document.createElement('canvas')
    c.width = 2
    c.height = 512
    const g = c.getContext('2d')!
    const grd = g.createLinearGradient(0, 0, 0, 512)
    const stops = SCENE[dark ? 'dark' : 'light'].backgroundStops
    grd.addColorStop(0, stops[0])
    grd.addColorStop(0.55, stops[1])
    grd.addColorStop(1, stops[2])
    g.fillStyle = grd
    g.fillRect(0, 0, 2, 512)
    const t = new THREE.CanvasTexture(c)
    t.colorSpace = THREE.SRGBColorSpace
    return t
  }, [dark])
  useEffect(() => () => tex.dispose(), [tex])
  // attached as the scene's background (restored when this unmounts)
  return <primitive attach="background" object={tex} />
}

function Effects({ scale, dark }: { scale: number; dark: boolean }) {
  return (
    <EffectComposer multisampling={0}>
      <N8AO aoRadius={Math.max(scale * 0.035, 0.5)} distanceFalloff={1} intensity={dark ? 2.2 : 2.8} halfRes quality="medium" />
      {/* bloom only on the dark background: on a light one it would wash the scene out */}
      <Bloom mipmapBlur luminanceThreshold={dark ? 0.82 : 1.5} luminanceSmoothing={0.2} intensity={dark ? 0.55 : 0} radius={0.62} />
      <SMAA />
      <Vignette offset={0.32} darkness={dark ? 0.45 : 0.22} />
    </EffectComposer>
  )
}

/** Fading line grid on the ground plane (continuous 1 px lines; smoothed by SMAA in high quality). */
function GroundGrid({ cx, cz, y, cell, half, dark }: { cx: number; cz: number; y: number; cell: number; half: number; dark: boolean }) {
  const geo = useMemo(() => groundGrid(cx, cz, cell, half, new THREE.Color(SCENE[dark ? 'dark' : 'light'].gridMinor), new THREE.Color(SCENE[dark ? 'dark' : 'light'].gridMajor)), [cx, cz, cell, half, dark])
  useEffect(() => () => geo.dispose(), [geo])
  return (
    <lineSegments geometry={geo} position={[0, y, 0]} renderOrder={-1}>
      <lineBasicMaterial vertexColors transparent depthWrite={false} toneMapped={false} />
    </lineSegments>
  )
}

// ---------------------------------------------------------------------------- camera
interface ViewRequest {
  key: ViewKey
  n: number
}

/** Perspective / orthographic cameras with standard views; the other camera follows on a switch. */
function CameraRig({ projection, request, box }: { projection: View3DSettings['projection']; request: ViewRequest; box: THREE.Box3 }) {
  const pc = useRef<THREE.PerspectiveCamera>(null)
  const oc = useRef<THREE.OrthographicCamera>(null)
  const size = useThree((s) => s.size)
  const invalidate = useThree((s) => s.invalidate)
  const controls = useThree((s) => s.controls) as unknown as OrbitControlsImpl | null
  const lastDir = useRef(new THREE.Vector3(...VIEW_DIRS.iso).normalize())

  const apply = (dir: THREE.Vector3) => {
    if (!controls) return
    const aspect = size.width / Math.max(size.height, 1)
    const p = pc.current
    const o = oc.current
    const fit = fitView(box, dir, p?.fov ?? 35, aspect)
    const c = fit.center
    const radius = box.getBoundingSphere(new THREE.Sphere()).radius || 50
    if (p) {
      const dist = fit.distance
      p.position.copy(c.clone().add(dir.clone().multiplyScalar(dist)))
      p.near = Math.max(dist / 2000, 0.01)
      p.far = (dist + radius) * 60
      p.up.set(0, 1, 0)
      p.lookAt(c)
      p.updateProjectionMatrix()
    }
    if (o) {
      const dist = radius * 6
      o.position.copy(c.clone().add(dir.clone().multiplyScalar(dist)))
      o.near = 0.01
      o.far = dist * 4
      o.zoom = Math.min(size.width / (2 * fit.halfW), size.height / (2 * fit.halfH))
      o.up.set(0, 1, 0)
      o.lookAt(c)
      o.updateProjectionMatrix()
    }
    controls.target.copy(c)
    controls.update()
    invalidate()
    lastDir.current.copy(dir)
  }

  useEffect(() => {
    const dir = request.key === 'fit' ? currentDir() : new THREE.Vector3(...VIEW_DIRS[request.key]).normalize()
    apply(dir)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request.n, controls, size.width, size.height])

  // on a projection switch keep the viewing direction
  useEffect(() => {
    apply(currentDir())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projection])

  function currentDir(): THREE.Vector3 {
    const cam = projection === 'perspective' ? oc.current : pc.current // the camera that was active before
    const tgt = controls?.target ?? box.getCenter(new THREE.Vector3())
    const active = (projection === 'perspective' ? pc.current : oc.current) ?? cam
    const src = cam && cam.position.distanceToSquared(tgt) > 1e-9 ? cam : active
    if (!src) return lastDir.current.clone()
    const d = src.position.clone().sub(tgt)
    return d.lengthSq() > 1e-12 ? d.normalize() : lastDir.current.clone()
  }

  return (
    <>
      <PerspectiveCamera ref={pc} makeDefault={projection === 'perspective'} fov={35} position={[-200, 80, -80]} />
      <OrthographicCamera ref={oc} makeDefault={projection === 'orthographic'} position={[-200, 80, -80]} />
    </>
  )
}

/** Navigation cube; smaller in narrow views. Priority 1 renders the scene and then the cube;
 * with post-processing the composer renders at priority 1 and the cube goes on top at 2. */
function ViewCube({ dark, high }: { dark: boolean; high: boolean }) {
  const w = useThree((s) => s.size.width)
  const k = w < 480 ? 0.7 : 1
  return (
    <GizmoHelper alignment="bottom-right" margin={[72 * k, 72 * k]} renderPriority={high ? 2 : 1}>
      <group scale={k}>
        <GizmoViewcube color={SCENE[dark ? 'dark' : 'light'].cube} hoverColor={resolveColor(DATA.selection)} textColor={SCENE[dark ? 'dark' : 'light'].cubeText} strokeColor={SCENE[dark ? 'dark' : 'light'].cubeStroke} opacity={0.95} />
      </group>
    </GizmoHelper>
  )
}

/** Registers a PNG snapshot function (renders the current frame). */
function Snapshot({ register }: { register: (fn: () => string) => void }) {
  const gl = useThree((s) => s.gl)
  useEffect(() => {
    register(() => gl.domElement.toDataURL('image/png'))
  }, [gl, register])
  return null
}

/** Outline (and a faint fill) of the section plane across the scene bounds. */
function ClipGuide({ axis, offset, box, on }: { axis: 'x' | 'y' | 'z'; offset: number; box: THREE.Box3; on: boolean }) {
  const { line, fill } = useMemo(() => {
    const pad = box.getSize(new THREE.Vector3()).multiplyScalar(0.06)
    const lo = box.min.clone().sub(pad)
    const hi = box.max.clone().add(pad)
    const k = axis === 'x' ? 0 : axis === 'y' ? 1 : 2
    const [a, b] = [0, 1, 2].filter((q) => q !== k)
    const corner = (u: number, v: number) => {
      const p = [0, 0, 0]
      p[k] = offset
      p[a] = u ? hi.getComponent(a) : lo.getComponent(a)
      p[b] = v ? hi.getComponent(b) : lo.getComponent(b)
      return new THREE.Vector3(...p)
    }
    const c = [corner(0, 0), corner(1, 0), corner(1, 1), corner(0, 1)]
    const fill = new THREE.BufferGeometry().setFromPoints([c[0], c[1], c[2], c[0], c[2], c[3]])
    return { line: new THREE.BufferGeometry().setFromPoints(c), fill }
  }, [axis, offset, box])
  useEffect(() => () => (line.dispose(), fill.dispose()), [line, fill])
  if (!on) return null
  return (
    <group renderOrder={5}>
      <lineLoop geometry={line}>
        <lineBasicMaterial color={resolveColor(DATA.selection)} transparent opacity={0.7} depthWrite={false} toneMapped={false} />
      </lineLoop>
      <mesh geometry={fill}>
        <meshBasicMaterial color={resolveColor(DATA.selection)} transparent opacity={0.025} side={THREE.DoubleSide} depthWrite={false} toneMapped={false} />
      </mesh>
    </group>
  )
}

// ---------------------------------------------------------------------------- view
export function Viewport3D() {
  const t = useT()
  const ev = useEngineStore((s) => s.evaluation)
  const preview = useEngineStore((s) => s.preview)
  const optRunning = useOptStore(isRunning)
  const system = useProjectStore((s) => s.project.system)
  const projectName = useProjectStore((s) => s.project.metadata.name)
  const selection = useProjectStore((s) => s.selection)
  const select = useProjectStore((s) => s.select)
  const cad = useProjectStore((s) => s.project.cad_assets)
  const theme = useUiStore((s) => s.theme)
  const toast = useUiStore((s) => s.toast)
  const mode = useMeasureStore((s) => s.mode)
  const results = useMeasureStore((s) => s.results)
  const [st, set] = useView3DSettings()
  const [request, setRequest] = useState<ViewRequest>({ key: 'iso', n: 0 })
  const snapshot = useRef<(() => string) | null>(null)
  const infinite = (preview ?? system).surfaces[0].thickness === null
  const nsSources = useProjectStore(selectSources)
  const nsDetectors = useProjectStore(selectDetectors)
  // ray paths of the last non-sequential analysis (shown with the project's own sources)
  const nsPathsData = useEngineStore((s) => (s.analyses.nonseq?.data as NonSeqResult | null | undefined)?.paths ?? null)
  const box = useMemo(() => {
    if (!ev) return new THREE.Box3()
    const b = sceneBounds(ev, cad, true, infinite)
    for (const p of nsPoints(nsSources, nsDetectors, surfaceFrames(ev.surfaces))) b.expandByPoint(p)
    return b
  }, [ev, cad, infinite, nsSources, nsDetectors])
  const opticsBox = useMemo(() => (ev ? sceneBounds(ev, cad, false, infinite) : new THREE.Box3()), [ev, cad, infinite])
  // section plane: keep the side where sign * (axis - offset) <= 0
  const { on: clipOn, axis: clipAxis, flip: clipFlip, offset: clipOffset } = st.clip
  const clip = useMemo(() => {
    if (!clipOn) return []
    const sgn = clipFlip ? 1 : -1
    const normal = new THREE.Vector3(clipAxis === 'x' ? 1 : 0, clipAxis === 'y' ? 1 : 0, clipAxis === 'z' ? 1 : 0).multiplyScalar(sgn)
    return [new THREE.Plane(normal, -sgn * clipOffset)]
  }, [clipOn, clipAxis, clipFlip, clipOffset])
  if (!ev) return <ViewState kind="layout" />
  const dark = theme === 'dark'
  const radius = box.getBoundingSphere(new THREE.Sphere()).radius || 50
  const sceneScale = Math.max(10, radius)
  const nsFrames = surfaceFrames(ev.surfaces) // anchored sources and detectors
  const groundY = opticsBox.min.y - Math.max(radius * 0.18, 2)
  const cell = niceStep(sceneScale / 12)
  const center = box.getCenter(new THREE.Vector3())
  const high = st.quality === 'high'

  const finishDistance = async (p: MeasurePick[]) => {
    const ms = useMeasureStore.getState()
    ms.clearPicks()
    const [a, b] = p
    const d = [b.point[0] - a.point[0], b.point[1] - a.point[1], b.point[2] - a.point[2]] as V3
    const id = ms.addResult({
      kind: 'distance',
      a: a.point,
      b: b.point,
      distance_mm: Math.hypot(...d),
      delta_mm: d,
      exact: false,
      labels: [a.label, b.label],
      pending: p.some((x) => x.asset_id),
    })
    const cadPicks = p.filter((x) => x.asset_id)
    if (!cadPicks.length) return
    try {
      const r = await api.cadMeasure(
        cad,
        cadPicks.map((x) => ({
          asset_id: x.asset_id,
          part_id: x.part_id,
          point: x.point,
        })),
      )
      let k = 0
      const pts = p.map((x) => (x.asset_id ? r.points[k++].point : x.point))
      const dd = [pts[1][0] - pts[0][0], pts[1][1] - pts[0][1], pts[1][2] - pts[0][2]] as V3
      ms.updateResult(id, {
        a: pts[0],
        b: pts[1],
        distance_mm: Math.hypot(...dd),
        delta_mm: dd,
        exact: p.every((x) => x.asset_id) && r.points.every((q) => q.exact),
        pending: false,
        note: r.points.some((q) => q.offset_mm > 1e-6) ? `snapped ${r.points.map((q) => fmt(q.offset_mm * 1000, 3)).join(' / ')} µm to the exact surface` : undefined,
      })
    } catch (e) {
      ms.updateResult(id, { pending: false, note: (e as Error).message })
    }
  }
  const finishClearance = async (p: MeasurePick[]) => {
    const ms = useMeasureStore.getState()
    ms.clearPicks()
    const [a, b] = p
    const id = ms.addResult({
      kind: 'clearance',
      a: a.point,
      b: b.point,
      distance_mm: NaN,
      delta_mm: [0, 0, 0],
      exact: false,
      labels: [a.label, b.label],
      pending: true,
    })
    try {
      const r = await api.cadClearance(cad, { asset_id: a.asset_id, part_id: a.part_id }, { asset_id: b.asset_id, part_id: b.part_id })
      const dd = [r.point_b[0] - r.point_a[0], r.point_b[1] - r.point_a[1], r.point_b[2] - r.point_a[2]] as V3
      ms.updateResult(id, {
        a: r.point_a,
        b: r.point_b,
        distance_mm: r.distance_mm,
        delta_mm: dd,
        exact: r.exact,
        pending: false,
        note: r.touching ? (r.interference_volume_mm3 > 0 ? `interference ${fmt(r.interference_volume_mm3, 5)} mm³` : 'touching') : undefined,
      })
    } catch (e) {
      ms.removeResult(id)
      toast('error', (e as Error).message)
    }
  }
  const onCadPick = (e: CadPickEvent) => {
    const ms = useMeasureStore.getState()
    const node = e.partId && e.asset.tree ? findNode(e.asset.tree, e.partId) : null
    const label = node ? `${e.asset.name} / ${node.name}` : e.asset.name
    if (ms.mode === 'off') {
      ms.select({ asset_id: e.asset.id, part_id: e.partId })
      return
    }
    if (ms.mode === 'clearance' && ms.picks.some((x) => x.asset_id === e.asset.id && x.part_id === e.partId)) return
    const p = ms.addPick({
      asset_id: e.asset.id,
      part_id: e.partId,
      point: e.point,
      label,
    })
    if (p.length === 2) void (ms.mode === 'distance' ? finishDistance(p) : finishClearance(p))
  }
  const onOpticPick = (i: number, pt?: THREE.Vector3) => {
    const ms = useMeasureStore.getState()
    if (ms.mode === 'off' || !pt) return select(i)
    if (ms.mode === 'clearance') return toast('info', t('meas.clearanceCadOnly'))
    const p = ms.addPick({
      asset_id: '',
      part_id: null,
      point: [pt.x, pt.y, pt.z],
      label: `S${i}`,
    })
    if (p.length === 2) void finishDistance(p)
  }
  const saveImage = () => {
    const fn = snapshot.current
    if (!fn) return
    const a = document.createElement('a')
    a.href = fn()
    a.download = `${(projectName || 'opticore').replace(/[^\w.-]+/g, '_')}-3d.png`
    document.body.appendChild(a)
    a.click()
    a.remove()
  }
  const view = (key: ViewKey) => setRequest((r) => ({ key, n: r.n + 1 }))
  const axisMin = st.clip.axis === 'x' ? box.min.x : st.clip.axis === 'y' ? box.min.y : box.min.z
  const axisMax = st.clip.axis === 'x' ? box.max.x : st.clip.axis === 'y' ? box.max.y : box.max.z

  return (
    // @container: the overlays adapt to the width of this view (it can be a narrow split pane)
    <div className="@container relative h-full w-full">
      <Canvas
        // render on demand: camera moves, damping and prop changes invalidate; an idle view costs no GPU time
        frameloop="demand"
        dpr={[1, 2]}
        shadows
        gl={{
          antialias: !high,
          preserveDrawingBuffer: true,
          powerPreference: 'high-performance',
          toneMapping: THREE.AgXToneMapping,
          toneMappingExposure: dark ? 1.05 : 0.95,
        }}
        onCreated={({ gl }) => {
          gl.localClippingEnabled = true
        }}
        onPointerMissed={() => undefined}
      >
        <GradientBackground dark={dark} />
        <Studio dark={dark} />
        <ambientLight intensity={dark ? 0.12 : 0.2} />
        <directionalLight position={[center.x - radius, center.y + radius * 2, center.z - radius]} intensity={0.8} />
        <Scene ev={ev} primary={(preview ?? system).primary_wavelength} infinite={infinite} selection={selection} onSelect={onOpticPick} dark={dark} st={st} clip={clip} />
        <CadMeshes assets={cad} onPick={onCadPick} clip={clip} high={high} />
        <MeasureLayer scale={sceneScale} width={st.rayWidth} />
        <NsGlyphs sources={nsSources} detectors={nsDetectors} scale={sceneScale} paths={nsSources.some((x) => x.enabled) ? nsPathsData : null} frames={nsFrames} />
        <ClipGuide axis={st.clip.axis} offset={st.clip.offset} box={box} on={st.clip.on} />
        {st.ground && (
          <>
            <GroundGrid cx={center.x} cz={center.z} y={groundY} cell={cell} half={radius * 3.2} dark={dark} />
            {high && <ContactShadows position={[center.x, groundY + 0.01, center.z]} scale={radius * 4} far={radius * 3} blur={2.6} opacity={dark ? 0.55 : 0.35} resolution={1024} color={SCENE[dark ? 'dark' : 'light'].shadow} />}
          </>
        )}
        <OrbitControls makeDefault enableDamping dampingFactor={0.1} zoomToCursor />
        <CameraRig projection={st.projection} request={request} box={box} />
        <Snapshot register={(fn) => (snapshot.current = fn)} />
        <ViewCube dark={dark} high={high} />
        {high && <Effects scale={sceneScale} dark={dark} />}
      </Canvas>

      <div className="absolute top-2 left-2 hidden gap-1.5 @2xl:flex">
        <Badge tone="accent">{t('view.layout3d')}</Badge>
        {preview && <Badge tone="warn">{t(optRunning ? 'opt.preview' : 'opt.previewResult')}</Badge>}
      </div>

      {/* toolbar, section plane and measurements stack in one column, so they never overlap however the toolbar wraps */}
      <div className="pointer-events-none absolute top-2 right-2 left-2 flex flex-col items-end gap-1.5 @2xl:left-28">
        <div className="pointer-events-auto flex max-w-full flex-wrap items-center justify-end gap-0.5 rounded-lg border border-line bg-panel/90 p-0.5 shadow-lg backdrop-blur">
          {/* narrow view: the standard views in a menu */}
          <Select<ViewKey | ''>
            className="h-6 w-[74px] shrink-0 text-caption @2xl:hidden"
            ariaLabel={t('v3.views')}
            value=""
            options={[{ value: '', label: t('v3.views') }, ...(['iso', 'side', 'top', 'front'] as const).map((k) => ({ value: k, label: t(`v3.view.${k}`) }))]}
            onChange={(k) => k && view(k)}
          />
          {(['iso', 'side', 'top', 'front'] as const).map((k) => (
            <button key={k} className="hidden shrink-0 rounded px-1.5 py-0.5 @2xl:block text-caption font-medium text-muted hover:bg-hover hover:text-fg" onClick={() => view(k)} title={t(`v3.view.${k}Hint`)}>
              {t(`v3.view.${k}`)}
            </button>
          ))}
          <span className="mx-0.5 h-4 w-px shrink-0 bg-line" />
          <IconButton title={t('v3.clip')} active={st.clip.on} onClick={() => set({ clip: { ...st.clip, on: !st.clip.on } })}>
            <Scissors size={14} />
          </IconButton>
          <IconButton title={t('meas.distance')} active={mode === 'distance'} onClick={() => useMeasureStore.getState().setMode(mode === 'distance' ? 'off' : 'distance')}>
            <Ruler size={14} />
          </IconButton>
          <IconButton title={t('meas.clearance')} active={mode === 'clearance'} onClick={() => useMeasureStore.getState().setMode(mode === 'clearance' ? 'off' : 'clearance')} disabled={!cad.length}>
            <MoveHorizontal size={14} />
          </IconButton>
          {results.length > 0 && (
            <IconButton title={t('meas.clear')} onClick={() => useMeasureStore.getState().clearAll()}>
              <Trash2 size={14} />
            </IconButton>
          )}
          <span className="mx-0.5 h-4 w-px bg-line" />
          <IconButton title={t('v3.snapshot')} onClick={saveImage}>
            <Camera size={14} />
          </IconButton>
          <IconButton title={t('v3.fit')} onClick={() => view('fit')}>
            <Maximize2 size={14} />
          </IconButton>
          <MoreSettings compact>
            <div className="grid w-full grid-cols-[auto_1fr] items-center gap-x-3 gap-y-2">
              <Label hint={t('v3.projectionHint')}>{t('v3.projection')}</Label>
              <Select<'perspective' | 'orthographic'>
                className="h-6 text-small"
                ariaLabel={t('v3.projection')}
                value={st.projection}
                options={[
                  { value: 'perspective', label: t('v3.perspective') },
                  { value: 'orthographic', label: t('v3.orthographic') },
                ]}
                onChange={(v) => set({ projection: v })}
              />
              <span className="col-span-2 flex items-center gap-1.5" title={t('v3.quality')}>
                <Sparkles size={12} className="text-faint" />
                <Checkbox checked={high} onChange={(v) => set({ quality: v ? 'high' : 'fast' })} label={t('v3.highQuality')} />
              </span>
              <span className="col-span-2 flex items-center gap-1.5">
                <BoxIcon size={12} className="text-faint" />
                <Checkbox checked={st.ground} onChange={(v) => set({ ground: v })} label={t('v3.ground')} />
              </span>
            </div>
          </MoreSettings>
        </div>
        {preview && (
          <div className="@2xl:hidden">
            <Badge tone="warn">{t('opt.preview')}</Badge>
          </div>
        )}
        {/* section plane controls */}
        {st.clip.on && (
          <div className="pointer-events-auto flex w-full items-center gap-2 rounded-lg border border-line bg-panel/95 px-2 py-1.5 text-small shadow-lg backdrop-blur @2xl:w-auto">
            <Scissors size={12} className="shrink-0 text-accent" />
            <span className="hidden text-muted @2xl:inline">{t('v3.clipAxis')}</span>
            <Select
              className="h-6 w-12 shrink-0 text-small"
              value={st.clip.axis}
              options={[
                { value: 'x', label: 'x' },
                { value: 'y', label: 'y' },
                { value: 'z', label: 'z' },
              ]}
              onChange={(v) => set({ clip: { ...st.clip, axis: v, offset: 0 } })}
            />
            <input
              type="range"
              className="w-0 min-w-12 flex-1 accent-[var(--c-accent)] @2xl:w-40 @2xl:flex-none"
              min={axisMin}
              max={axisMax}
              step={(axisMax - axisMin) / 400 || 0.01}
              value={Math.min(axisMax, Math.max(axisMin, st.clip.offset))}
              onChange={(e) => set({ clip: { ...st.clip, offset: Math.round(Number(e.target.value) * 1000) / 1000 } })}
              aria-label={t('v3.clipOffset')}
            />
            <NumberField className="h-6 w-16 shrink-0" value={st.clip.offset} onCommit={(v) => set({ clip: { ...st.clip, offset: v ?? 0 } })} ariaLabel={t('v3.clipOffset')} />
            <span className="text-muted">mm</span>
            <IconButton size="sm" title={t('v3.clipFlip')} aria-pressed={st.clip.flip} active={st.clip.flip} onClick={() => set({ clip: { ...st.clip, flip: !st.clip.flip } })}>
              <ArrowLeftRight size={12} />
            </IconButton>
            <IconButton size="sm" title={t('v3.clipClose')} onClick={() => set({ clip: { ...st.clip, on: false } })}>
              <X size={12} />
            </IconButton>
          </div>
        )}

        {(mode !== 'off' || results.length > 0) && (
          <div className="pointer-events-auto w-full rounded-lg border border-line @md:w-[300px] bg-panel/95 p-2 text-small shadow-lg backdrop-blur">
            {mode !== 'off' && <div className="mb-1 text-accent">{mode === 'distance' ? t('meas.hintDistance') : t('meas.hintClearance')}</div>}
            {results.map((m) => (
              <div key={m.id} className="border-t border-line py-1 first:border-t-0">
                <div className="flex items-center gap-1">
                  <span className={m.kind === 'clearance' ? 'text-ok' : 'text-warn'}>{m.kind === 'clearance' ? t('meas.clearanceShort') : t('meas.distanceShort')}</span>
                  <b className="num text-fg">{m.pending ? '…' : `${fmt(m.distance_mm, 7)} mm`}</b>
                  <span className="text-faint">{m.pending ? '' : m.exact ? t('meas.exact') : t('meas.display')}</span>
                  <span className="flex-1" />
                  <IconButton size="sm" tone="danger" title={t('c.remove')} onClick={() => useMeasureStore.getState().removeResult(m.id)}>
                    <Trash2 size={12} />
                  </IconButton>
                </div>
                {!m.pending && <div className="num text-faint">Δ {m.delta_mm.map((v) => fmt(v, 5)).join(', ')} mm</div>}
                <div className="truncate text-faint" title={m.labels.join(' → ')}>
                  {m.labels.join(' → ')}
                </div>
                {m.note && <div className="text-faint">{m.note}</div>}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* help line and ray width share the bottom row (left of the view cube), so they never overlap */}
      <div className="pointer-events-none absolute right-2 bottom-2 left-2 flex items-center gap-3 @2xl:right-[150px]">
        <div className="hidden min-w-0 flex-1 truncate pl-1 text-caption text-muted @2xl:block" title={mode === 'off' ? t('v3.help') : t('meas.footer')}>
          {mode === 'off' ? t('v3.help') : t('meas.footer')} {st.ground && `· ${t('v3.grid')} ${fmt(cell, 3)} / ${fmt(cell * 5, 3)} mm`}
        </div>
        <div className="pointer-events-auto flex shrink-0 items-center gap-1.5 rounded-md border border-line bg-panel/80 px-2 py-0.5 text-caption text-muted backdrop-blur">
          <Eye size={12} />
          <span className="whitespace-nowrap">{t('v3.rays')}</span>
          <input type="range" min={0.5} max={5} step={0.1} value={st.rayWidth} onChange={(e) => set({ rayWidth: Number(e.target.value) })} className="w-20 accent-[var(--c-accent)]" aria-label={t('v3.rays')} />
          <span className="num whitespace-nowrap">{fmt(st.rayWidth, 2)} px</span>
        </div>
      </div>
    </div>
  )
}
