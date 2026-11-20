import { ChevronDown, X } from 'lucide-react'
import { type ButtonHTMLAttributes, type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { visibleTabs } from '../../lib/tabOverflow'
import { parseEngineering, type ParseResult } from '../../lib/units'
import { isConfirmOpen } from '../../store/confirmStore'
import { useProjectStore } from '../../store/projectStore'
import { useT } from '../../lib/i18n'
import { cellName, compactNumber, cx, textOf } from './uiUtils'

type Variant = 'default' | 'primary' | 'ghost' | 'danger' | 'subtle' | 'link'

export function Button({
  variant = 'default',
  size = 'md',
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: 'sm' | 'md' }) {
  if (variant === 'link')
    return (
      <button className={cx('inline-flex items-center gap-1 text-small font-normal tracking-normal text-accent normal-case select-none hover:underline disabled:opacity-40 disabled:pointer-events-none', className)} {...rest}>
        {children}
      </button>
    )
  const base = 'inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors select-none disabled:opacity-40 disabled:pointer-events-none whitespace-nowrap'
  const sz = size === 'sm' ? 'h-6 px-2 text-small' : 'h-7 px-2.5 text-body'
  const v: Record<Exclude<Variant, 'link'>, string> = {
    default: 'bg-elev border border-line hover:bg-hover hover:border-line-strong text-fg',
    primary: 'bg-accent-strong hover:bg-accent-strong/85 text-white border border-transparent shadow-sm',
    ghost: 'hover:bg-hover text-fg',
    subtle: 'bg-accent-soft text-accent hover:brightness-110',
    danger: 'bg-transparent border border-line text-danger hover:bg-danger/10',
  }
  return (
    <button className={cx(base, sz, v[variant], className)} {...rest}>
      {children}
    </button>
  )
}

/** An icon-only button, named by `title`. `size="sm"` is the compact row action of tables and lists: 20 px,
 *  a native tooltip (no wrapper, so layout classes such as `ml-auto` or `invisible group-hover:visible`
 *  apply to the button itself), and `tone="danger"` for remove/delete. */
export function IconButton({
  title,
  active,
  size = 'md',
  tone,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { title: string; active?: boolean; size?: 'sm' | 'md'; tone?: 'danger' }) {
  if (size === 'sm')
    return (
      <button
        type="button"
        aria-label={title}
        title={title}
        className={cx(
          'inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-faint transition-colors hover:bg-hover disabled:opacity-30 disabled:pointer-events-none',
          tone === 'danger' ? 'hover:text-danger' : 'hover:text-fg',
          active && 'text-accent hover:text-accent',
          className,
        )}
        {...rest}
      >
        {children}
      </button>
    )
  return (
    <Tooltip text={title}>
      <button
        aria-label={title}
        className={cx(
          'inline-flex h-7 w-7 items-center justify-center rounded-md text-muted transition-colors hover:bg-hover hover:text-fg disabled:opacity-35 disabled:pointer-events-none',
          active && 'bg-accent-soft text-accent hover:text-accent',
          className,
        )}
        {...rest}
      >
        {children}
      </button>
    </Tooltip>
  )
}

export function Tooltip({ text, children, side = 'bottom' }: { text: ReactNode; children: ReactNode; side?: 'bottom' | 'top' | 'right' }) {
  const [show, setShow] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  if (!text) return <>{children}</>
  const pos = side === 'bottom' ? 'top-full mt-1.5 left-1/2 -translate-x-1/2' : side === 'top' ? 'bottom-full mb-1.5 left-1/2 -translate-x-1/2' : 'left-full ml-2 top-1/2 -translate-y-1/2'
  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => {
        timer.current = window.setTimeout(() => setShow(true), 450)
      }}
      onMouseLeave={() => {
        window.clearTimeout(timer.current)
        setShow(false)
      }}
      onMouseDown={() => {
        window.clearTimeout(timer.current)
        setShow(false)
      }}
    >
      {children}
      {show && (
        <span className={cx('pointer-events-none absolute z-[100] w-max max-w-[300px] rounded-md border border-line-strong bg-elev px-2 py-1 text-small leading-snug text-fg shadow-lg fade-in', pos)}>
          {text}
        </span>
      )}
    </span>
  )
}

export function Dialog({
  title,
  onClose,
  children,
  footer,
  width = 640,
  icon,
  dismissable = true,
}: {
  title: ReactNode
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  width?: number
  icon?: ReactNode
  /** false: no close button, Escape and backdrop clicks do nothing (an explicit choice in the footer is required) */
  dismissable?: boolean
}) {
  const t = useT()
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && dismissable && !isConfirmOpen()) onClose()
    }
    window.addEventListener('keydown', h, true)
    return () => window.removeEventListener('keydown', h, true)
  }, [onClose, dismissable])
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-[2px]" onMouseDown={dismissable ? onClose : undefined}>
      <div
        role="dialog"
        aria-modal="true"
        className="fade-in flex max-h-[88vh] w-full flex-col overflow-hidden rounded-lg border border-line-strong bg-panel shadow-[var(--shadow)]"
        style={{ maxWidth: width }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-line px-4">
          {icon}
          <div className="flex-1 text-title font-semibold">{title}</div>
          {dismissable && (
            <IconButton title={t('c.close')} onClick={onClose}>
              <X size={16} />
            </IconButton>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-auto">{children}</div>
        {footer && <div className="flex shrink-0 items-center justify-end gap-2 border-t border-line bg-panel-2 px-4 py-2.5">{footer}</div>}
      </div>
    </div>
  )
}

/** Names a cell control from its table (see cellName) unless it was given an aria-label. */
function useCellName(ref: { current: HTMLElement | null }, cell: boolean | undefined, ariaLabel: string | undefined) {
  useLayoutEffect(() => {
    const el = ref.current
    if (!cell || ariaLabel || !el) return
    const n = cellName(el)
    if (n && el.getAttribute('aria-label') !== n) el.setAttribute('aria-label', n)
  })
}

/** Engineering number input: commits on Enter/blur, validates, supports unit suffixes and ∞. */
export function NumberField({
  value,
  onCommit,
  allowInfinity,
  units,
  min,
  max,
  integer,
  className,
  cell,
  placeholder,
  title,
  format,
  disabled,
  ariaLabel,
  optional,
  scrub,
  scrubStep,
}: {
  value: number | null
  onCommit: (v: number | null) => void
  /** drag sideways to change the value (Shift: ten times finer); one drag is one undo step */
  scrub?: boolean
  /** value change per pixel (default 0.2 % of the starting value, at least 0.005) */
  scrubStep?: number
  allowInfinity?: boolean
  /** null means "not set": shown empty (with the placeholder), and clearing the field commits null */
  optional?: boolean
  units?: Record<string, number>
  min?: number
  max?: number
  integer?: boolean
  className?: string
  cell?: boolean
  placeholder?: string
  title?: string
  format?: (v: number | null) => string
  disabled?: boolean
  ariaLabel?: string
}) {
  // idle: compact display (10 significant digits); editing: full precision
  const none = optional ? '' : 'Infinity'
  const show = (v: number | null) => (format ? format(v) : v === null ? none : compactNumber(v))
  const full = (v: number | null) => (v === null ? none : String(v))
  const parse = (s: string): ParseResult => (optional && s.trim() === '' ? { ok: true, value: null } : parseEngineering(s, { allowInfinity, units, min, max, integer }))
  const [text, setText] = useState(show(value))
  const [error, setError] = useState<string | null>(null)
  const [focused, setFocused] = useState(false)
  const cancelled = useRef(false)
  const edited = useRef(false)
  const self = useRef<HTMLInputElement>(null)
  const t = useT()
  useCellName(self, cell, ariaLabel)
  const canScrub = !!scrub && !disabled && value !== null && Number.isFinite(value)
  // scrubbing: mouse down on the idle field, drag sideways; a click without a drag edits the text as usual
  const scrubDown = (e: React.MouseEvent<HTMLInputElement>) => {
    if (!canScrub || focused || e.button !== 0 || value === null) return
    e.preventDefault() // no focus yet (the row's own mousedown handlers still run)
    const x0 = e.clientX
    const v0 = value
    const base = scrubStep ?? Math.max(Math.abs(v0) * 0.002, 0.005)
    const el = self.current
    let moved = false
    let last = v0
    let pending: number | null = null
    let frame = 0
    const flush = () => {
      frame = 0
      if (pending !== null && pending !== last) {
        last = pending
        onCommit(pending)
      }
      pending = null
    }
    const move = (ev: MouseEvent) => {
      const dx = ev.clientX - x0
      if (!moved && Math.abs(dx) < 3) return
      if (!moved) {
        moved = true
        useProjectStore.getState().beginGesture()
        document.body.style.cursor = 'ew-resize'
      }
      let v = v0 + (dx - Math.sign(dx) * 3) * base * (ev.shiftKey ? 0.1 : 1)
      if (integer) v = Math.round(v)
      if (min !== undefined) v = Math.max(min, v)
      if (max !== undefined) v = Math.min(max, v)
      pending = Number(v.toPrecision(10))
      if (!frame) frame = requestAnimationFrame(flush)
    }
    const up = () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
      if (frame) cancelAnimationFrame(frame)
      flush()
      if (moved) {
        useProjectStore.getState().endGesture()
        document.body.style.cursor = ''
      } else el?.focus()
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }
  useEffect(() => {
    if (!focused) {
      setText(show(value))
      setError(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, focused])
  const commit = () => {
    if (!edited.current) return true // never commit a value the user did not type
    const r: ParseResult = parse(text)
    if (!r.ok) {
      setError(r.error)
      return false
    }
    setError(null)
    edited.current = false
    if (r.value !== value) onCommit(r.value)
    setText(show(r.value))
    return true
  }
  const input = (
    <input
      ref={self}
      aria-label={ariaLabel}
      disabled={disabled}
      className={cx(cell ? 'cell-input num' : 'field-input num', error && 'invalid', canScrub && !focused && 'cursor-ew-resize', className)}
      value={text}
      placeholder={placeholder}
      title={canScrub && !focused && !title && !error ? t('c.scrubHint') : undefined}
      onMouseDown={scrubDown}
      onChange={(e) => {
        edited.current = true
        setText(e.target.value)
        if (error) setError(null)
      }}
      onFocus={(e) => {
        setFocused(true)
        edited.current = false
        if (!format) setText(full(value))
        const el = e.target
        requestAnimationFrame(() => el.select())
      }}
      onBlur={() => {
        // the single commit point (Enter blurs after validating)
        if (!cancelled.current) commit()
        cancelled.current = false
        setFocused(false)
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          const r = parse(text)
          if (r.ok) (e.target as HTMLInputElement).blur()
          else setError(r.error)
        } else if (e.key === 'Escape') {
          cancelled.current = true
          setText(show(value))
          setError(null)
          ;(e.target as HTMLInputElement).blur()
        }
        e.stopPropagation()
      }}
    />
  )
  if (error || title) return <Tooltip text={error ?? title}>{input}</Tooltip>
  return input
}

export function TextField({
  value,
  onCommit,
  className,
  cell,
  placeholder,
  ariaLabel,
}: {
  value: string
  onCommit: (v: string) => void
  className?: string
  cell?: boolean
  placeholder?: string
  ariaLabel?: string
}) {
  const [text, setText] = useState(value)
  // a new value from outside replaces the text being edited
  const [base, setBase] = useState(value)
  if (value !== base) {
    setBase(value)
    setText(value)
  }
  const self = useRef<HTMLInputElement>(null)
  useCellName(self, cell, ariaLabel)
  return (
    <input
      ref={self}
      aria-label={ariaLabel}
      className={cx(cell ? 'cell-input' : 'field-input', className)}
      value={text}
      placeholder={placeholder}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => text !== value && onCommit(text)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
        if (e.key === 'Escape') {
          setText(value)
          ;(e.target as HTMLInputElement).blur()
        }
        e.stopPropagation()
      }}
    />
  )
}

export function Select<T extends string | number>({
  value,
  options,
  onChange,
  className,
  cell,
  ariaLabel,
  title,
}: {
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
  className?: string
  cell?: boolean
  ariaLabel?: string
  /** what the choice means (native tooltip) */
  title?: string
}) {
  const self = useRef<HTMLSelectElement>(null)
  useCellName(self, cell, ariaLabel)
  return (
    <select
      ref={self}
      aria-label={ariaLabel}
      title={title}
      className={cx(cell ? 'cell-input' : 'field-input', className)}
      value={String(value)}
      onChange={(e) => {
        const o = options.find((x) => String(x.value) === e.target.value)
        if (o) onChange(o.value)
      }}
      onKeyDown={(e) => e.stopPropagation()}
    >
      {options.map((o) => (
        <option key={String(o.value)} value={String(o.value)} className="bg-panel text-fg">
          {o.label}
        </option>
      ))}
    </select>
  )
}

export function Checkbox({ checked, onChange, label, title, ariaLabel }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; title?: string; ariaLabel?: string }) {
  const box = (
    <label className="inline-flex cursor-pointer items-center gap-1.5 select-none">
      <input type="checkbox" aria-label={ariaLabel ?? (textOf(label) || title)} className="h-3.5 w-3.5 accent-[var(--c-accent)]" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label && <span>{label}</span>}
    </label>
  )
  return title ? <Tooltip text={title}>{box}</Tooltip> : box
}

const TAB_CLASS = 'relative flex shrink-0 items-center gap-1.5 px-3 text-body whitespace-nowrap transition-colors'
/** room kept for the "+N ▾" overflow button (px) */
const TABS_MORE_W = 56

/** A tab strip. Tabs that do not fit go into a "+N ▾" menu; the active tab always stays in the strip. */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  right,
  className,
}: {
  tabs: { id: T; label: ReactNode; icon?: ReactNode; badge?: ReactNode }[]
  value: T
  onChange: (t: T) => void
  right?: ReactNode
  className?: string
}) {
  const t = useT()
  const strip = useRef<HTMLDivElement>(null)
  const ruler = useRef<HTMLDivElement>(null)
  // indices of the tabs in the strip; null: all of them
  const [shown, setShown] = useState<number[] | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  const active = tabs.findIndex((x) => x.id === value)
  const fit = useRef(() => {})
  const doFit = () => {
    const el = strip.current
    const m = ruler.current
    if (!el || !m) return
    const widths = [...m.children].map((c) => (c as HTMLElement).getBoundingClientRect().width)
    // not laid out (hidden, or a test without layout): show all
    const next = !el.clientWidth || widths.every((w) => !w) ? null : visibleTabs(widths, el.clientWidth, active, TABS_MORE_W)
    const all = !next || next.length === tabs.length
    setShown((prev) => (all ? null : prev && prev.join() === next!.join() ? prev : next))
  }
  useLayoutEffect(() => {
    fit.current = doFit
    doFit()
  })
  useEffect(() => {
    if (typeof ResizeObserver === 'undefined' || !strip.current) return
    const ro = new ResizeObserver(() => fit.current())
    ro.observe(strip.current)
    return () => ro.disconnect()
  }, [])
  const tab = (x: (typeof tabs)[number], measure = false) => (
    <button
      key={x.id}
      role={measure ? undefined : 'tab'}
      aria-selected={measure ? undefined : value === x.id}
      tabIndex={measure ? -1 : undefined}
      onClick={measure ? undefined : () => onChange(x.id)}
      className={cx(TAB_CLASS, value === x.id ? 'bg-panel text-fg' : 'text-muted hover:bg-hover hover:text-fg')}
    >
      {value === x.id && <span className="absolute inset-x-0 top-0 h-0.5 bg-accent" />}
      {x.icon}
      {x.label}
      {x.badge}
    </button>
  )
  const hidden = shown ? tabs.map((_, i) => i).filter((i) => !shown.includes(i)) : []
  return (
    <div className={cx('relative flex h-8 shrink-0 items-stretch border-b border-line bg-panel-2', className)} role="tablist">
      {/* invisible copy that measures every tab, including the ones in the menu */}
      <div ref={ruler} aria-hidden inert className="pointer-events-none invisible absolute top-0 left-0 flex h-0 w-max overflow-hidden">
        {tabs.map((x) => tab(x, true))}
      </div>
      <div ref={strip} className="flex min-w-0 flex-1 items-stretch overflow-hidden">
        {(shown ?? tabs.map((_, i) => i)).map((i) => tab(tabs[i]))}
        {hidden.length > 0 && (
          <button
            aria-haspopup="menu"
            aria-expanded={!!menu}
            aria-label={t('c.moreTabs', { n: hidden.length })}
            title={hidden.map((i) => textOf(tabs[i].label)).join(', ')}
            onClick={(e) => {
              const r = e.currentTarget.getBoundingClientRect()
              setMenu(menu ? null : { x: r.left, y: r.bottom + 2 })
            }}
            className="flex shrink-0 items-center gap-1 px-2.5 text-body whitespace-nowrap text-muted hover:bg-hover hover:text-fg"
          >
            +{hidden.length}
            <ChevronDown size={12} />
          </button>
        )}
      </div>
      {right && <div className="flex items-center gap-1 px-2">{right}</div>}
      {menu && <ContextMenu x={menu.x} y={menu.y} items={hidden.map((i) => ({ label: textOf(tabs[i].label), icon: tabs[i].icon, onClick: () => onChange(tabs[i].id) }))} onClose={() => setMenu(null)} />}
    </div>
  )
}

export function Section({ title, children, right, defaultOpen = true }: { title: ReactNode; children: ReactNode; right?: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-b border-line">
      <div className="flex h-8 cursor-pointer items-center gap-1 px-3 text-small font-semibold tracking-wide text-muted uppercase select-none hover:text-fg" onClick={() => setOpen(!open)}>
        <span className={cx('inline-block transition-transform', open ? 'rotate-90' : '')}>›</span>
        <span className="flex-1">{title}</span>
        <span onClick={(e) => e.stopPropagation()}>{right}</span>
      </div>
      {open && <div className="pb-2">{children}</div>}
    </div>
  )
}

export function Badge({ children, tone = 'default' }: { children: ReactNode; tone?: 'default' | 'warn' | 'danger' | 'ok' | 'accent' }) {
  const t = {
    default: 'bg-hover text-muted',
    warn: 'bg-warn/15 text-warn',
    danger: 'bg-danger/15 text-danger',
    ok: 'bg-ok/15 text-ok',
    accent: 'bg-accent-soft text-accent',
  }[tone]
  return <span className={cx('inline-flex h-4 items-center rounded px-1.5 text-caption font-medium', t)}>{children}</span>
}

export function Empty({ children, icon }: { children: ReactNode; icon?: ReactNode }) {
  // m-auto centres the content but lets a tall one scroll from its top (justify-center would clip it)
  return (
    <div className="flex h-full min-h-[120px] flex-col overflow-auto">
      <div className="m-auto flex flex-col items-center gap-2 p-6 text-center text-muted">
        {icon}
        <div className="max-w-[420px] text-body leading-relaxed">{children}</div>
      </div>
    </div>
  )
}

export function Spinner({ size = 14 }: { size?: number }) {
  return <span className="spin inline-block rounded-full border-2 border-accent border-t-transparent" style={{ width: size, height: size }} />
}

export function Field({ label, children, hint }: { label: ReactNode; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="grid grid-cols-[110px_1fr] items-center gap-2 px-3 py-[3px]">
      <span className="truncate text-small text-muted">
        {hint ? (
          <Tooltip text={hint} side="right">
            <span className="cursor-help border-b border-dotted border-faint">{label}</span>
          </Tooltip>
        ) : (
          label
        )}
      </span>
      <div className="flex min-w-0 items-center gap-1">{children}</div>
    </label>
  )
}

export function ContextMenu({ x, y, items, onClose }: { x: number; y: number; items: ({ label: string; onClick: () => void; danger?: boolean; disabled?: boolean; shortcut?: string; icon?: ReactNode } | 'sep')[]; onClose: () => void }) {
  useEffect(() => {
    const h = () => onClose()
    window.addEventListener('mousedown', h)
    window.addEventListener('blur', h)
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => {
      window.removeEventListener('mousedown', h)
      window.removeEventListener('blur', h)
      window.removeEventListener('keydown', k)
    }
  }, [onClose])
  const left = Math.max(4, Math.min(x, window.innerWidth - 250))
  const top = Math.max(4, Math.min(y, window.innerHeight - items.length * 28 - 20))
  const icons = items.some((it) => it !== 'sep' && it.icon)
  return (
    <div role="menu" className="fade-in fixed z-[90] max-h-[calc(100vh-8px)] min-w-[210px] overflow-y-auto rounded-lg border border-line-strong bg-elev py-1 shadow-[var(--shadow)]" style={{ left, top }} onMouseDown={(e) => e.stopPropagation()}>
      {items.map((it, i) =>
        it === 'sep' ? (
          <div key={i} className="my-1 h-px bg-line" />
        ) : (
          <button
            key={i}
            role="menuitem"
            disabled={it.disabled}
            className={cx('flex h-7 w-full items-center gap-3 px-3 text-left text-body hover:bg-hover disabled:opacity-40', it.danger && 'text-danger')}
            onClick={() => {
              it.onClick()
              onClose()
            }}
          >
            {icons && <span className="-mr-1 flex w-4 shrink-0 justify-center text-muted">{it.icon}</span>}
            <span className="flex-1">{it.label}</span>
            {it.shortcut && <span className="text-caption text-faint">{it.shortcut}</span>}
          </button>
        ),
      )}
    </div>
  )
}
