import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it } from 'vitest'
import { useUiStore } from '../../store/uiStore'
import { textOf } from '../common/uiUtils'
import { TopToolbar } from './TopToolbar'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function render() {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const root = createRoot(el)
  act(() => root.render(<TopToolbar />))
  return { el, root }
}

const nameOf = (b: Element) => b.getAttribute('aria-label') || b.textContent?.trim() || ''
const iconOf = (b: Element) => [...(b.querySelector('svg')?.classList ?? [])].find((c) => c.startsWith('lucide-')) ?? ''

describe('toolbar', () => {
  for (const lang of ['en', 'fi'] as const) {
    it(`names every button and gives each command its own icon (${lang})`, () => {
      act(() => useUiStore.getState().setLang(lang))
      const { el, root } = render()
      const buttons = [...el.querySelectorAll('button')]
      expect(buttons.length).toBeGreaterThanOrEqual(15)
      for (const b of buttons) expect(nameOf(b), b.outerHTML.slice(0, 120)).not.toBe('')
      const names = buttons.map(nameOf)
      expect(new Set(names).size).toBe(names.length)
      const icons = buttons.map(iconOf).filter(Boolean)
      expect(icons.length).toBe(buttons.length)
      expect(new Set(icons).size).toBe(icons.length)
      act(() => root.unmount())
      el.remove()
    })
  }

  it('labels the primary commands from 1280 px and keeps secondary file commands in the File menu', () => {
    act(() => useUiStore.getState().setLang('en'))
    const { el, root } = render()
    const primary = [...el.querySelectorAll('button span.min-\\[1280px\\]\\:inline')].map((s) => s.textContent)
    expect(primary).toEqual(['New', 'Open', 'Save', 'Analyze', 'Quick focus', 'Optimize'])
    const names = [...el.querySelectorAll('button')].map(nameOf)
    for (const moved of ['Save as…', 'Export .opticore (Ctrl+E)', 'Engineering report (HTML)', 'Export CAD (STEP/IGES)']) expect(names).not.toContain(moved)
    act(() => root.unmount())
    el.remove()
  })
})

describe('textOf', () => {
  it('reads the text of nested markup', () => {
    expect(textOf(<span className="x">Live update</span>)).toBe('Live update')
    expect(textOf(['a', <b key="b">b</b>, 3])).toBe('ab3')
    expect(textOf(null)).toBe('')
  })
})
