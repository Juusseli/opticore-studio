import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { confirmDiscard } from '../actions'
import { ConfirmHost } from '../components/common/ConfirmHost'
import { blankProject } from '../lib/project'
import { askUnsaved, confirmAction, isConfirmOpen, useConfirmStore } from './confirmStore'
import { useProjectStore } from './projectStore'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const labels = { title: 'T', message: 'M', save: 'Save', dontSave: "Don't save", cancel: 'Cancel' }
const answer = (id: string) => act(() => useConfirmStore.getState().answer(id))

afterEach(() => {
  const r = useConfirmStore.getState().req
  if (r) useConfirmStore.getState().answer(r.cancelId)
})

describe('confirmation requests', () => {
  it('resolve with the chosen action', async () => {
    const p = confirmAction({ title: 'Delete project', message: 'Delete "A"?', confirmLabel: 'Delete', cancelLabel: 'Cancel', danger: true })
    expect(isConfirmOpen()).toBe(true)
    const req = useConfirmStore.getState().req!
    expect(req.actions.map((a) => a.id)).toEqual(['cancel', 'ok'])
    expect(req.focus).toBe('cancel') // Enter does not delete
    answer('ok')
    await expect(p).resolves.toBe(true)
    expect(isConfirmOpen()).toBe(false)
    const q = confirmAction({ title: 't', message: 'm', confirmLabel: 'OK', cancelLabel: 'Cancel' })
    answer('cancel')
    await expect(q).resolves.toBe(false)
  })

  it('a new question cancels an unanswered one', async () => {
    const first = askUnsaved(labels)
    const second = askUnsaved(labels)
    await expect(first).resolves.toBe('cancel')
    answer('save')
    await expect(second).resolves.toBe('save')
  })

  it('the host answers with the clicked button, and Esc cancels', async () => {
    const el = document.createElement('div')
    document.body.appendChild(el)
    const root = createRoot(el)
    act(() => root.render(<ConfirmHost />))
    let p = askUnsaved(labels)
    await act(async () => undefined)
    const dialog = el.querySelector('[role=alertdialog]')!
    expect(dialog.textContent).toContain('M')
    expect(document.activeElement?.textContent).toBe('Save')
    act(() => (el.querySelector('[data-action=discard]') as HTMLButtonElement).click())
    await expect(p).resolves.toBe('discard')
    p = askUnsaved(labels)
    await act(async () => undefined)
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    })
    await expect(p).resolves.toBe('cancel')
    expect(el.querySelector('[role=alertdialog]')).toBeNull()
    act(() => root.unmount())
    el.remove()
  })
})

describe('unsaved changes before replacing the project', () => {
  it('does not ask when nothing is unsaved', async () => {
    useProjectStore.getState().setProject(blankProject(), { saved: true })
    await expect(confirmDiscard()).resolves.toBe(true)
    expect(isConfirmOpen()).toBe(false)
  })

  it('Save saves first, Don\'t save continues, Cancel stays', async () => {
    useProjectStore.getState().setProject(blankProject(), { saved: false })
    const save = vi.fn(async () => true)
    let p = confirmDiscard(save)
    await Promise.resolve()
    expect(useConfirmStore.getState().req?.actions.map((a) => a.id)).toEqual(['cancel', 'discard', 'save'])
    answer('save')
    await expect(p).resolves.toBe(true)
    expect(save).toHaveBeenCalledTimes(1)

    const failing = vi.fn(async () => false)
    p = confirmDiscard(failing)
    await Promise.resolve()
    answer('save')
    await expect(p).resolves.toBe(false) // a failed save keeps the project open

    p = confirmDiscard(save)
    await Promise.resolve()
    answer('discard')
    await expect(p).resolves.toBe(true)
    p = confirmDiscard(save)
    await Promise.resolve()
    answer('cancel')
    await expect(p).resolves.toBe(false)
    expect(save).toHaveBeenCalledTimes(1)
  })
})
