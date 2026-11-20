// In-app confirmations (instead of window.confirm): one request at a time, answered with an action id.
import { create } from 'zustand'

export interface ConfirmAction {
  id: string
  label: string
  variant?: 'primary' | 'danger' | 'default'
}

export interface ConfirmRequest {
  title: string
  message: string
  /** buttons in display order; the focused one is `focus` (default: the last) */
  actions: ConfirmAction[]
  /** returned on Esc, the close button or a backdrop click */
  cancelId: string
  focus?: string
  tone?: 'warn' | 'danger'
}

interface ConfirmState {
  req: (ConfirmRequest & { resolve: (id: string) => void }) | null
  ask: (r: ConfirmRequest) => Promise<string>
  answer: (id: string) => void
}

export const useConfirmStore = create<ConfirmState>((set, get) => ({
  req: null,
  ask: (r) =>
    new Promise<string>((resolve) => {
      // a new question supersedes an unanswered one, which counts as cancelled
      const prev = get().req
      if (prev) prev.resolve(prev.cancelId)
      set({ req: { ...r, resolve } })
    }),
  answer: (id) => {
    const r = get().req
    if (!r) return
    set({ req: null })
    r.resolve(id)
  },
}))

export const isConfirmOpen = () => useConfirmStore.getState().req !== null

/** Yes/no confirmation of a named action (e.g. a delete). Resolves true for the action, false for cancel. */
export async function confirmAction(o: { title: string; message: string; confirmLabel: string; cancelLabel: string; danger?: boolean }): Promise<boolean> {
  const id = await useConfirmStore.getState().ask({
    title: o.title,
    message: o.message,
    actions: [
      { id: 'cancel', label: o.cancelLabel },
      { id: 'ok', label: o.confirmLabel, variant: o.danger ? 'danger' : 'primary' },
    ],
    cancelId: 'cancel',
    // destructive actions start on Cancel, so Enter does not delete
    focus: o.danger ? 'cancel' : 'ok',
    tone: o.danger ? 'danger' : undefined,
  })
  return id === 'ok'
}

export type UnsavedAnswer = 'save' | 'discard' | 'cancel'

/** Save / Don't save / Cancel for unsaved changes. */
export async function askUnsaved(labels: { title: string; message: string; save: string; dontSave: string; cancel: string }): Promise<UnsavedAnswer> {
  const id = await useConfirmStore.getState().ask({
    title: labels.title,
    message: labels.message,
    actions: [
      { id: 'cancel', label: labels.cancel },
      { id: 'discard', label: labels.dontSave },
      { id: 'save', label: labels.save, variant: 'primary' },
    ],
    cancelId: 'cancel',
    focus: 'save',
    tone: 'warn',
  })
  return id as UnsavedAnswer
}
