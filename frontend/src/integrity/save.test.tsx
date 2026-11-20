import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { openProject, saveProject } from '../actions'
import { blankProject } from '../lib/project'
import { storage } from '../lib/storage'
import { useConfirmStore } from '../store/confirmStore'
import { isDirty, useProjectStore } from '../store/projectStore'
import { useUiStore } from '../store/uiStore'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}
const flush = () => act(async () => void (await new Promise((r) => setTimeout(r, 0))))

describe('saving and reopening', () => {
  beforeEach(() => useUiStore.getState().setLang('en'))
  afterEach(() => vi.restoreAllMocks())

  it('an edit made while the save is written stays marked unsaved', async () => {
    openProject(blankProject('S'))
    const d = deferred<never>()
    const put = vi.spyOn(storage, 'putProject').mockReturnValue(d.promise)
    vi.spyOn(storage, 'setAutosave').mockResolvedValue(undefined)
    const saving = saveProject()
    useProjectStore.getState().updateSurface(1, { radius: 42 }, 'edit during save')
    d.resolve({} as never)
    await saving
    expect(put.mock.calls[0][0].system.surfaces[1].radius).toBe(100)
    expect(isDirty(useProjectStore.getState())).toBe(true) // the edit is not in the stored copy
  })

  it('a project opened while a save is written stays unsaved and out of the library', async () => {
    openProject(blankProject('A'))
    const d = deferred<never>()
    vi.spyOn(storage, 'putProject').mockReturnValue(d.promise)
    vi.spyOn(storage, 'setAutosave').mockResolvedValue(undefined)
    const saving = saveProject()
    openProject(blankProject('B'), { saved: false })
    d.resolve({} as never)
    await saving
    const st = useProjectStore.getState()
    expect(st.project.metadata.name).toBe('B')
    expect(isDirty(st)).toBe(true) // B was opened unsaved
    expect(st.storedInLibrary).toBe(false) // and is not in the library
  })

  it('"Open" on the open project in the project manager does not drop its unsaved changes without asking', async () => {
    const p = blankProject('Lib')
    openProject(p, { inLibrary: true })
    useProjectStore.getState().updateSurface(1, { radius: 42 }, 'unsaved edit')
    expect(isDirty(useProjectStore.getState())).toBe(true)
    vi.spyOn(storage, 'listProjects').mockResolvedValue([{ id: p.id, name: p.metadata.name, savedAt: p.metadata.modified, project: p }])
    const ask = vi.spyOn(useConfirmStore.getState(), 'ask')
    const { ProjectManager } = await import('../components/dialogs/Dialogs')
    const el = document.createElement('div')
    document.body.appendChild(el)
    const root = createRoot(el)
    act(() => root.render(<ProjectManager />))
    await flush()
    act(() => [...el.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Open')!.click())
    await flush()
    act(() => root.unmount())
    el.remove()
    expect(ask.mock.calls.length > 0 || useProjectStore.getState().project.system.surfaces[1].radius === 42).toBe(true)
  })
})
