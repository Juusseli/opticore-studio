import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { COLORMAPS, CYCLIC, DATA, DIVERGING, fieldColor, INFERNO, resolveDeep, SERIES } from './palette'

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f)
    if (statSync(p).isDirectory()) return f === '__fixtures__' ? [] : sources(p)
    return /\.(ts|tsx)$/.test(f) && !/\.test\./.test(f) ? [p] : []
  })
}

const css = readFileSync(join(process.cwd(), 'src', 'index.css'), 'utf-8')
/** Custom properties of one block of index.css (':root {' for dark, ":root[data-theme='light'] {" for light). */
function tokens(head: string): Record<string, string> {
  const i = css.indexOf(head)
  const body = css.slice(i + head.length, css.indexOf('}', i))
  return Object.fromEntries([...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]))
}
function contrast(a: string, b: string): number {
  const lum = (h: string) => {
    const c = [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
  }
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}

describe('colour', () => {
  it('no hex colour literals outside the token file (index.css) and the palette (lib/palette.ts)', () => {
    const bad = sources(join(process.cwd(), 'src'))
      .filter((f) => !/[\\/]lib[\\/]palette\.ts$/.test(f))
      .flatMap((f) => [...readFileSync(f, 'utf-8').matchAll(/['"`=]#[0-9a-fA-F]{3,8}\b|\$\{?#[0-9a-fA-F]{6}/g)].map((m) => `${f.split(/[\\/]/).pop()}: ${m[0]}`))
    expect(bad).toEqual([])
  })

  it('uses perceptually uniform, diverging and cyclic maps, never jet or hot', () => {
    const all = sources(join(process.cwd(), 'src'))
      .map((f) => readFileSync(f, 'utf-8'))
      .join('\n')
    expect(all).not.toMatch(/colorscale: *'(Jet|Rainbow|Hot|Portland|Picnic|Electric)'/)
    expect(INFERNO[0][1]).toBe('#000004')
    expect(DIVERGING[5]).toEqual([0.5, '#f7f7f7']) // white at zero
    expect(CYCLIC[0][1]).toBe(CYCLIC[CYCLIC.length - 1][1]) // a cyclic map closes
    expect(COLORMAPS.sequential).toBe(INFERNO)
  })

  it('data colours exist in both themes and stand out from the panel (≥ 3:1)', () => {
    const dark = tokens(':root {')
    const light = tokens(":root[data-theme='light'] {")
    for (const [theme, bg] of [
      [dark, dark['--c-panel']],
      [light, light['--c-panel']],
    ] as const) {
      for (let i = 1; i <= 8; i++) {
        const c = theme[`--d-${i}`]
        expect(c, `--d-${i}`).toMatch(/^#[0-9a-f]{6}$/)
        expect(contrast(c, bg), `--d-${i} ${c} on ${bg}`).toBeGreaterThanOrEqual(3)
      }
    }
    for (const role of Object.values(DATA)) expect(css).toContain(/^var\((--[\w-]+)\)$/.exec(role)![1])
    expect(fieldColor(0)).toBe(SERIES[0])
    expect(fieldColor(9)).toBe(SERIES[1])
  })

  it('text tokens meet 4.5:1 (WCAG AA) where they are used, and keep their hierarchy', () => {
    // a translucent token (selection) over the panel, as rendered
    const over = (rgba: string, base: string) => {
      const [r, g, b, a] = /rgba\(([^)]+)\)/.exec(rgba)![1].split(',').map(Number)
      const bc = [1, 3, 5].map((k) => parseInt(base.slice(k, k + 2), 16))
      return '#' + [r, g, b].map((v, k) => Math.round(a * v + (1 - a) * bc[k]).toString(16).padStart(2, '0')).join('')
    }
    for (const [name, th] of [
      ['dark', tokens(':root {')],
      ['light', tokens(":root[data-theme='light'] {")],
    ] as const) {
      const resting = ['--c-panel', '--c-panel-2', '--c-elev', '--c-input'].map((k) => th[k])
      const all = [...resting, th['--c-bg'], th['--c-hover'], over(th['--c-select'], th['--c-panel'])]
      const check = (fg: string, on: string[]) => {
        for (const bg of on) expect(contrast(th[fg], bg), `${name} ${fg} ${th[fg]} on ${bg}`).toBeGreaterThanOrEqual(4.5)
      }
      // primary and secondary text: everywhere, also on hovered and selected rows
      check('--c-text', all)
      check('--c-muted', all)
      // tertiary text (units, captions, timings): on the surfaces text rests on
      check('--c-faint', name === 'dark' ? [...resting, th['--c-bg']] : resting)
      // status and link colours used as text
      for (const fg of ['--c-accent', '--c-ok', '--c-warn', '--c-danger']) check(fg, resting)
      // white labels on primary buttons and active toggles
      expect(contrast('#ffffff', th['--c-accent-strong']), `${name} white on accent-strong`).toBeGreaterThanOrEqual(4.5)
      // the hierarchy stays visible: text > muted > faint
      const p = th['--c-panel']
      expect(contrast(th['--c-text'], p)).toBeGreaterThan(contrast(th['--c-muted'], p) + 2)
      expect(contrast(th['--c-muted'], p)).toBeGreaterThan(contrast(th['--c-faint'], p) + 1)
    }
  })

  it('resolves colour tokens for Plotly and leaves data arrays alone', () => {
    document.documentElement.style.setProperty('--d-1', '#123456')
    const z = [
      [1, 2],
      [3, 4],
    ]
    const out = resolveDeep({ line: { color: 'var(--d-1)' }, x: [1, 2, 3], z, name: 'var', marker: { color: ['var(--d-1)', 'red'] } })
    expect(out.line.color).toBe('#123456')
    expect(out.marker.color).toEqual(['#123456', 'red'])
    expect(out.z).toBe(z)
    expect(out.name).toBe('var')
  })
})
