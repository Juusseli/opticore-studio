import { useRef } from 'react'
import { cx } from './uiUtils'

/** A resize handle. Pointer capture keeps the drag on the handle even over the 3D canvas or a plot;
 * deltas are incremental, so callers read the current size from the store (not from a render). */
export function Handle({ dir, onDrag }: { dir: 'h' | 'v'; onDrag: (d: number) => void }) {
  const last = useRef<{ x: number; y: number } | null>(null)
  const end = (e: React.PointerEvent<HTMLDivElement>) => {
    last.current = null
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }
  return (
    <div
      role="separator"
      aria-orientation={dir === 'h' ? 'vertical' : 'horizontal'}
      onPointerDown={(e) => {
        if (e.button !== 0) return
        e.preventDefault()
        e.currentTarget.setPointerCapture(e.pointerId)
        last.current = { x: e.clientX, y: e.clientY }
        document.body.style.cursor = dir === 'h' ? 'col-resize' : 'row-resize'
        document.body.style.userSelect = 'none'
      }}
      onPointerMove={(e) => {
        if (!last.current) return
        const d = dir === 'h' ? e.clientX - last.current.x : e.clientY - last.current.y
        last.current = { x: e.clientX, y: e.clientY }
        if (d) onDrag(d)
      }}
      onPointerUp={end}
      onPointerCancel={end}
      className={cx('group relative z-10 shrink-0 touch-none bg-line transition-colors hover:bg-accent/60', dir === 'h' ? 'resize-h w-px' : 'resize-v h-px')}
    >
      <div className={cx('absolute', dir === 'h' ? 'inset-y-0 -left-[3px] -right-[3px]' : 'inset-x-0 -top-[3px] -bottom-[3px]')} />
    </div>
  )
}
