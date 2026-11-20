import { act, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ErrorBoundary } from './ErrorBoundary'
import { resetStoredLayout } from './storedLayout'

// React needs this flag to run act() outside a test renderer
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function Boom(): never {
  throw new Error('kaboom')
}

/** An effect that returns a Promise, as `useEffect(() => el.scrollIntoView())` does in current Chromium. */
function PromiseEffect() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  useEffect((() => Promise.resolve()) as any, [])
  return <div>promise effect</div>
}

function mount(node: React.ReactNode) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const root = createRoot(el)
  act(() => root.render(node))
  return { el, root }
}

describe('ErrorBoundary', () => {
  afterEach(() => vi.restoreAllMocks())

  it('contains a crash in one panel and keeps its siblings rendered', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const { el, root } = mount(
      <div>
        <span>sibling</span>
        <ErrorBoundary name="Console">
          <Boom />
        </ErrorBoundary>
      </div>,
    )
    expect(el.textContent).toContain('sibling')
    expect(el.textContent).toContain('Console')
    expect(el.textContent).toContain('kaboom')
    act(() => root.unmount())
  })

  it('catches the failure of an effect that returned a Promise when the panel is replaced', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const { el, root } = mount(
      <div>
        <span>sibling</span>
        <ErrorBoundary name="Console">
          <PromiseEffect />
        </ErrorBoundary>
      </div>,
    )
    expect(el.textContent).toContain('promise effect')
    // replacing the panel calls its "clean-up" (a Promise), which throws inside React; the boundary
    // around it (it stays mounted, as around every view and bottom tab) shows the error instead of a blank app
    act(() =>
      root.render(
        <div>
          <span>sibling</span>
          <ErrorBoundary name="Console">
            <span>other tab</span>
          </ErrorBoundary>
        </div>,
      ),
    )
    expect(el.textContent).toContain('sibling')
    expect(el.textContent).toContain('destroy is not a function')
    act(() => root.unmount())
  })

  it('resetStoredLayout removes only the workspace layout keys', () => {
    localStorage.setItem('opticore.ui', '{"bottomTab":"console"}')
    localStorage.setItem('opticore.view3d', '{}')
    localStorage.setItem('opticore.other', 'keep')
    resetStoredLayout()
    expect(localStorage.getItem('opticore.ui')).toBeNull()
    expect(localStorage.getItem('opticore.view3d')).toBeNull()
    expect(localStorage.getItem('opticore.other')).toBe('keep')
  })
})
