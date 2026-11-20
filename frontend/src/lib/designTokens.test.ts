import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f)
    if (statSync(p).isDirectory()) return f === '__fixtures__' ? [] : sources(p)
    return /\.(ts|tsx)$/.test(f) && !/\.test\./.test(f) ? [p] : []
  })
}

const files = sources(join(process.cwd(), 'src'))
const scan = (re: RegExp) =>
  files.flatMap((f) => {
    const text = readFileSync(f, 'utf-8')
    return [...text.matchAll(re)].map((m) => `${f.split(/[\\/]/).slice(-2).join('/')}: ${m[0]}`)
  })

describe('design tokens (docs/UI_DESIGN.md, Design tokens)', () => {
  it('uses the four named text sizes, not arbitrary pixel sizes', () => {
    expect(scan(/\btext-\[\d+(\.\d+)?px\]/g)).toEqual([])
  })

  it('has no arbitrary pixel heights (controls are h-6 / h-7, layout sizes use the spacing scale)', () => {
    expect(scan(/(?<![\w-])h-\[\d+(\.\d+)?px\]/g)).toEqual([])
  })

  it('draws UI icons at 12, 14 or 16 px (larger sizes are illustrations)', () => {
    const bad = scan(/size=\{(\d+)\}/g).filter((x) => {
      const n = Number(/\{(\d+)\}/.exec(x)![1])
      return n < 18 && ![12, 14, 16].includes(n)
    })
    expect(bad).toEqual([])
  })

  it('rounds corners at 4, 6 or 8 px', () => {
    expect(scan(/\brounded-(xl|2xl|3xl|sm)\b/g)).toEqual([])
  })
})
