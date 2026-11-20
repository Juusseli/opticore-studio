import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { en, fi, translate } from './i18n'

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f)
    if (statSync(p).isDirectory()) return f === '__fixtures__' ? [] : sources(p)
    return /\.(ts|tsx)$/.test(f) && !/\.test\./.test(f) ? [p] : []
  })
}

describe('localisation', () => {
  it('English and Finnish dictionaries have the same keys', () => {
    expect(Object.keys(fi).sort()).toEqual(Object.keys(en).sort())
  })

  it('every literal key used in the UI exists', () => {
    const root = join(process.cwd(), 'src')
    const missing = new Set<string>()
    for (const file of sources(root)) {
      const text = readFileSync(file, 'utf-8')
      for (const m of text.matchAll(/\bt\('([a-z]+\.[A-Za-z0-9_]+)'/g)) if (!(m[1] in en)) missing.add(`${m[1]} (${file.split(/[\\/]/).pop()})`)
    }
    expect([...missing]).toEqual([])
  })

  it('substitutes variables', () => {
    expect(translate('en', 'ins.multi', { n: 3 })).toBe('3 surfaces selected — batch edit')
    expect(translate('fi', 'ins.multi', { n: 3 })).toContain('3 pintaa')
  })
})
