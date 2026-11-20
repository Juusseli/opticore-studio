import { AlertTriangle, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { useT } from '../../lib/i18n'
import { useConfirmStore } from '../../store/confirmStore'
import { Button, IconButton } from './ui'

/** Renders the open confirmation above every dialog. Esc, × and a backdrop click cancel. */
export function ConfirmHost() {
  const t = useT()
  const req = useConfirmStore((s) => s.req)
  const answer = useConfirmStore((s) => s.answer)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!req) return
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopImmediatePropagation()
        answer(req.cancelId)
      }
    }
    // the dialogs underneath ignore Esc while a confirmation is open (isConfirmOpen)
    document.addEventListener('keydown', h, true)
    box.current?.querySelector<HTMLButtonElement>(`[data-action="${req.focus ?? req.actions[req.actions.length - 1].id}"]`)?.focus()
    return () => document.removeEventListener('keydown', h, true)
  }, [req, answer])
  if (!req) return null
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/45 p-4" onMouseDown={() => answer(req.cancelId)}>
      <div
        ref={box}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-text"
        className="fade-in w-full max-w-[460px] overflow-hidden rounded-lg border border-line-strong bg-panel shadow-[var(--shadow)]"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 px-4 pt-4 pb-3">
          <AlertTriangle size={18} className={req.tone === 'danger' ? 'mt-0.5 shrink-0 text-danger' : 'mt-0.5 shrink-0 text-warn'} />
          <div className="min-w-0 flex-1">
            <div id="confirm-title" className="text-title font-semibold">
              {req.title}
            </div>
            <div id="confirm-text" className="mt-1 text-body leading-relaxed whitespace-pre-wrap text-muted">
              {req.message}
            </div>
          </div>
          <IconButton title={t('c.cancel')} onClick={() => answer(req.cancelId)}>
            <X size={14} />
          </IconButton>
        </div>
        <div className="flex justify-end gap-2 border-t border-line bg-panel-2 px-4 py-2.5">
          {req.actions.map((a) => (
            <Button key={a.id} data-action={a.id} variant={a.variant ?? 'default'} onClick={() => answer(a.id)}>
              {a.label}
            </Button>
          ))}
        </div>
      </div>
    </div>
  )
}
