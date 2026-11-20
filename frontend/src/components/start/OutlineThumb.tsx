import { fieldColor } from '../../lib/format'
import type { SystemOutline } from '../../lib/types'

const STROKE: Record<SystemOutline['items'][number]['kind'], string> = {
  glass: 'var(--c-glass-edge)',
  surface: 'var(--c-glass-edge)',
  mirror: 'var(--c-text)',
  stop: 'var(--c-accent)',
  image: 'var(--c-muted)',
  object: 'var(--c-muted)',
  ideal: 'var(--c-ok)',
}

/** Lens-profile thumbnail drawn from the engine's outline (exact profiles and real rays, y up). */
export function OutlineThumb({ outline, className }: { outline: SystemOutline; className?: string }) {
  const [z0, z1, y0, y1] = outline.bbox
  const w = Math.max(z1 - z0, 1e-6)
  const h = Math.max(y1 - y0, 1e-6)
  const pad = 0.06 * Math.max(w, h)
  const d = (pts: [number, number][]) => pts.map(([z, y], i) => `${i ? 'L' : 'M'}${z.toPrecision(6)},${(-y).toPrecision(6)}`).join('')
  return (
    <svg className={className} viewBox={`${z0 - pad} ${-y1 - pad} ${w + 2 * pad} ${h + 2 * pad}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      {outline.items.map((it, i) =>
        it.kind === 'glass' ? (
          <path key={i} d={d(it.points) + 'Z'} fill="var(--c-glass)" stroke={STROKE.glass} strokeWidth={1} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        ) : (
          <path
            key={i}
            d={d(it.points)}
            fill="none"
            stroke={STROKE[it.kind]}
            strokeOpacity={it.kind === 'mirror' ? 0.75 : 1}
            strokeWidth={it.kind === 'mirror' || it.kind === 'stop' ? 1.8 : 1}
            strokeDasharray={it.kind === 'image' || it.kind === 'object' ? '3 2' : undefined}
            vectorEffect="non-scaling-stroke"
          />
        ),
      )}
      {outline.rays.map((r, i) => (
        <path key={'r' + i} d={d(r.points)} fill="none" stroke={fieldColor(r.field)} strokeOpacity={r.ok ? 0.85 : 0.4} strokeDasharray={r.ok ? undefined : '2 2'} strokeWidth={0.9} vectorEffect="non-scaling-stroke" />
      ))}
    </svg>
  )
}
