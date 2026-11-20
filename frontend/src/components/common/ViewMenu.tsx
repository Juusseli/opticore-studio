import { Check, ChevronDown, ChevronRight, Search } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useT } from '../../lib/i18n'
import { filterViews, type ViewGroup, type ViewKind, viewShortcut } from '../../lib/viewGroups'
import { cx } from './uiUtils'

const WIDTH = 290

/** Grouped, searchable list of the analysis views in a popover below `anchor`, kept inside the window.
 * `groups`: the workspace's groups, listed first; the others open under "More analyses" (a search covers all). */
export function ViewMenu({ anchor, current, groups: offered, onPick, onClose }: { anchor: DOMRect; current?: ViewKind; groups?: ViewGroup[]; onPick: (v: ViewKind) => void; onClose: () => void }) {
  const t = useT()
  const [q, setQ] = useState('')
  const [k, setK] = useState(0)
  const all = filterViews(
    q,
    (v) => t('view.' + v),
    (g) => t('vg.' + g),
  )
  const hiddenCount = offered ? all.filter((g) => !offered.includes(g.group)).reduce((n, g) => n + g.views.length, 0) : 0
  // the current view's group is always shown, so the tick is never hidden
  const [more, setMore] = useState(() => !!(offered && current && !all.some((g) => offered.includes(g.group) && g.views.includes(current))))
  const groups = !offered || q.trim() || more ? all : all.filter((g) => offered.includes(g.group))
  const list = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const flat = groups.flatMap((g) => g.views)
  const left = Math.max(8, Math.min(anchor.left, window.innerWidth - WIDTH - 8))
  const top = Math.min(anchor.bottom + 4, window.innerHeight - 160)
  const maxHeight = window.innerHeight - top - 10

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) onClose()
    }
    window.addEventListener('mousedown', h)
    window.addEventListener('blur', onClose)
    return () => {
      window.removeEventListener('mousedown', h)
      window.removeEventListener('blur', onClose)
    }
  }, [onClose])
  useLayoutEffect(() => {
    const el = list.current?.querySelector<HTMLElement>(`[data-k="${k}"]`)
    const c = list.current
    if (!el || !c) return
    // keep the active row visible without scrolling the page
    if (el.offsetTop < c.scrollTop) c.scrollTop = el.offsetTop - 28
    else if (el.offsetTop + el.offsetHeight > c.scrollTop + c.clientHeight) c.scrollTop = el.offsetTop + el.offsetHeight - c.clientHeight
  }, [k])

  const pick = (v: ViewKind) => {
    onClose()
    onPick(v)
  }
  const indexOf = new Map(flat.map((v, n) => [v, n]))
  return (
    <div
      ref={box}
      role="dialog"
      aria-label={t('tb.analyze')}
      className="fade-in fixed z-[90] flex flex-col overflow-hidden rounded-lg border border-line-strong bg-elev shadow-[var(--shadow)]"
      style={{ left, top, width: WIDTH, maxHeight }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-line px-2.5">
        <Search size={14} className="text-faint" />
        <input
          autoFocus
          aria-label={t('view.search')}
          className="h-full flex-1 bg-transparent text-body outline-none"
          placeholder={t('view.search')}
          value={q}
          onChange={(e) => {
            setQ(e.target.value)
            setK(0)
          }}
          onKeyDown={(e) => {
            e.stopPropagation()
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              setK(Math.min(k + 1, flat.length - 1))
            } else if (e.key === 'ArrowUp') {
              e.preventDefault()
              setK(Math.max(k - 1, 0))
            } else if (e.key === 'Enter' && flat[k]) pick(flat[k])
            else if (e.key === 'Escape') onClose()
          }}
        />
      </div>
      <div ref={list} role="listbox" aria-label={t('tb.analyze')} className="relative min-h-0 flex-1 overflow-y-auto py-1">
        {groups.map((g) => (
          <div key={g.group} role="group" aria-label={t('vg.' + g.group)}>
            <div className="px-3 pt-1.5 pb-0.5 text-caption font-semibold tracking-wide text-faint uppercase">{t('vg.' + g.group)}</div>
            {g.views.map((v) => {
              const idx = indexOf.get(v) ?? 0
              const sc = viewShortcut(v)
              return (
                <button
                  key={v}
                  role="option"
                  aria-selected={v === current}
                  data-k={idx}
                  className={cx('flex h-7 w-full items-center gap-2 px-3 text-left text-body', idx === k ? 'bg-select' : 'hover:bg-hover')}
                  onMouseEnter={() => setK(idx)}
                  onClick={() => pick(v)}
                >
                  <span className="flex w-3.5 justify-center text-accent">{v === current && <Check size={12} />}</span>
                  <span className="flex-1 truncate">{t('view.' + v)}</span>
                  {sc && <span className="text-caption text-faint">{sc}</span>}
                </button>
              )
            })}
          </div>
        ))}
        {flat.length === 0 && <div className="px-3 py-3 text-body text-muted">{t('view.noMatch')}</div>}
        {offered && !q.trim() && hiddenCount > 0 && (
          <button className="mt-1 flex h-7 w-full items-center gap-2 border-t border-line px-3 text-left text-body text-muted hover:bg-hover hover:text-fg" onClick={() => setMore(!more)} aria-expanded={more}>
            <ChevronRight size={12} className={cx('transition-transform', more && 'rotate-90')} />
            {more ? t('view.fewer') : t('view.more', { n: hiddenCount })}
          </button>
        )}
      </div>
    </div>
  )
}

/** Pane header control: the current view's name; opens the grouped view menu. */
export function ViewPicker({ value, onChange, label, groups }: { value: ViewKind; onChange: (v: ViewKind) => void; label: string; groups?: ViewGroup[] }) {
  const t = useT()
  const [anchor, setAnchor] = useState<DOMRect | null>(null)
  return (
    <>
      <button
        aria-haspopup="dialog"
        aria-expanded={!!anchor}
        aria-label={`${label}: ${t('view.' + value)}`}
        title={t('view.pick')}
        className={cx('flex h-6 min-w-0 items-center gap-1 rounded-md border border-transparent px-1.5 text-body font-medium hover:border-line hover:bg-hover', anchor && 'border-line bg-hover')}
        onClick={(e) => setAnchor(anchor ? null : (e.currentTarget as HTMLElement).getBoundingClientRect())}
      >
        <span className="truncate">{t('view.' + value)}</span>
        <ChevronDown size={12} className="shrink-0 text-muted" />
      </button>
      {anchor && <ViewMenu anchor={anchor} current={value} groups={groups} onPick={onChange} onClose={() => setAnchor(null)} />}
    </>
  )
}
