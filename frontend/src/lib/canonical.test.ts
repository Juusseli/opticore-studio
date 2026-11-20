import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { canonicalJson, projectChecksum } from './canonical'

const fixture = (name: string) => readFileSync(resolve(process.cwd(), 'src/lib/__fixtures__', name), 'utf-8')

describe('canonical JSON', () => {
  it('sorts keys and omits whitespace', () => {
    expect(canonicalJson({ b: [1, 2.5, null], a: { y: true, x: 'é' } })).toBe('{"a":{"x":"é","y":true},"b":[1,2.5,null]}')
  })

  it('formats numbers exactly like the Python backend (ECMAScript rules)', () => {
    const { values, python } = JSON.parse(fixture('numbers.json')) as { values: number[]; python: string[] }
    values.forEach((v, i) => expect(canonicalJson(v)).toBe(python[i]))
  })

  it('maps non-finite numbers to null', () => {
    expect(canonicalJson([NaN, Infinity])).toBe('[null,null]')
  })

  it.each(['achromat.opticore', 'fold.opticore'])('reproduces the backend SHA-256 project checksum (%s)', async (name) => {
    const obj = JSON.parse(fixture(name)) as Record<string, unknown> & { checksum: { value: string } }
    expect(await projectChecksum(obj)).toBe(obj.checksum.value)
  })
})
