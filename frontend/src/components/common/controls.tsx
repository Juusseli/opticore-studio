// Shared controls of the analysis views: labels with hints, read-outs, field and wavelength pickers and the
// "More settings" popover that keeps each analysis bar to its few primary settings.
import { ChevronDown, SlidersHorizontal } from 'lucide-react'
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import type { OpticalSystem } from '../../lib/types'
import { Select, Tooltip } from './ui'
import { cx } from './uiUtils'

/** A label and its control(s), kept on one line when an analysis bar or its settings popover wraps. */
export function Pair({ children }: { children: ReactNode }) {
  return <span className="inline-flex items-center gap-1.5">{children}</span>
}

/** A control label; with a hint it gets a dotted underline and a help cursor (the visible hint affordance).
 *  `form`: a label in a two-column form (body size, may wrap) instead of a compact bar label. */
export function Label({ children, hint, form }: { children: ReactNode; hint?: string; form?: boolean }) {
  const base = form ? 'text-body text-muted' : 'text-small whitespace-nowrap text-muted'
  return hint ? (
    <Tooltip text={hint}>
      <span className={cx(base, 'cursor-help underline decoration-dotted decoration-from-font underline-offset-2')}>{children}</span>
    </Tooltip>
  ) : (
    <span className={base}>{children}</span>
  )
}

/** One labelled setting on its own line of a settings popover. */
export function Row({ label, hint, children }: { label: ReactNode; hint?: string; children: ReactNode }) {
  return (
    <div className="flex w-full items-center justify-between gap-3">
      <Label hint={hint}>{label}</Label>
      {children}
    </div>
  )
}

/** A labelled read-out: value and unit, optionally toned (ok / warn). */
export function Stat({ label, value, unit, tone }: { label: string; value: string; unit?: string; tone?: 'ok' | 'warn' }) {
  return (
    <div className="px-3 py-1.5">
      <div className="text-caption text-muted">{label}</div>
      <div className={cx('num text-title font-semibold', tone === 'warn' && 'text-warn', tone === 'ok' && 'text-ok')}>
        {value} {unit && <span className="text-caption font-normal text-faint">{unit}</span>}
      </div>
    </div>
  )
}

/** The system's wavelengths (null = the primary one). */
export function WavelengthSelect({ system, value, onChange, className }: { system: OpticalSystem; value: number | null; onChange: (v: number | null) => void; className?: string }) {
  const t = useT()
  return (
    <Select
      className={cx('h-6 w-28 shrink-0 text-small', className)}
      ariaLabel={t('c.wavelength')}
      value={value === null ? -1 : Math.min(value, system.wavelengths.length - 1)}
      options={[{ value: -1, label: t('an.primaryWl') }, ...system.wavelengths.map((w, i) => ({ value: i, label: `${fmt(w.value * 1000, 5)} nm` }))]}
      onChange={(v) => onChange(v < 0 ? null : v)}
    />
  )
}

/** The system's fields, with their values and units. */
export function FieldSelect({ system, value, onChange, className }: { system: OpticalSystem; value: number; onChange: (v: number) => void; className?: string }) {
  const t = useT()
  return (
    <Select
      className={cx('h-6 w-28 shrink-0 text-small', className)}
      ariaLabel={t('c.field')}
      value={Math.min(value, system.fields.length - 1)}
      options={system.fields.map((f, i) => ({ value: i, label: `F${i + 1} (${fmt(f.y, 4)}${system.field_type === 'angle' ? '°' : ' mm'})` }))}
      onChange={onChange}
    />
  )
}

const POP_W = 360

/** "More settings ▾": the secondary settings of an analysis in a popover (stays open while editing).
 *  `compact`: an icon-only trigger for floating toolbars (the 3D view). */
export function MoreSettings({ children, compact, label }: { children: ReactNode; compact?: boolean; label?: string }) {
  const t = useT()
  const name = label ?? t('an.more')
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  const btn = useRef<HTMLButtonElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const place = () => {
    const r = btn.current?.getBoundingClientRect()
    if (!r) return
    setPos({ left: Math.max(8, Math.min(r.right - POP_W, window.innerWidth - POP_W - 8)), top: Math.min(r.bottom + 4, window.innerHeight - 120) })
  }
  useLayoutEffect(() => {
    if (!pos) return
    const h = (e: MouseEvent) => {
      const n = e.target as Node
      if (!box.current?.contains(n) && !btn.current?.contains(n)) setPos(null)
    }
    const k = (e: KeyboardEvent) => e.key === 'Escape' && setPos(null)
    window.addEventListener('mousedown', h)
    window.addEventListener('keydown', k)
    return () => {
      window.removeEventListener('mousedown', h)
      window.removeEventListener('keydown', k)
    }
  }, [pos])
  useEffect(() => {
    if (!pos) return
    const r = () => setPos(null)
    window.addEventListener('resize', r)
    return () => window.removeEventListener('resize', r)
  }, [pos])
  return (
    <>
      <button
        ref={btn}
        aria-haspopup="dialog"
        aria-expanded={!!pos}
        aria-label={name}
        title={t('an.moreHint')}
        className={
          compact
            ? cx('inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted transition-colors hover:bg-hover hover:text-fg', pos && 'bg-accent-soft text-accent')
            : cx('flex h-6 shrink-0 items-center gap-1 rounded-md border border-line px-1.5 text-small whitespace-nowrap text-muted hover:border-line-strong hover:text-fg @xl:px-2', pos && 'border-line-strong bg-hover text-fg')
        }
        onClick={() => (pos ? setPos(null) : place())}
      >
        <SlidersHorizontal size={compact ? 14 : 12} />
        {/* in a narrow analysis pane (container below 36rem) only the icon shows */}
        {!compact && <span className="hidden @xl:inline">{name}</span>}
        {!compact && <ChevronDown size={12} className="hidden @xl:block" />}
      </button>
      {pos &&
        createPortal(
          <div
            ref={box}
            role="dialog"
            aria-label={name}
            className="fade-in fixed z-[80] max-h-[70vh] overflow-auto rounded-lg border border-line-strong bg-elev p-3 shadow-[var(--shadow)]"
            style={{ left: pos.left, top: pos.top, width: POP_W }}
          >
            <div className="flex flex-wrap items-center gap-x-2 gap-y-2">{children}</div>
          </div>,
          document.body,
        )}
    </>
  )
}
