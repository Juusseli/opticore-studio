import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchRiiPages, parseRiiIndex } from './rii'

const INDEX = `- DIVIDER: "Glasses"
- SHELF: specs
  content:
    - BOOK: schott
      content:
        - PAGE: N-BK7
          name: "N-BK7"
          data: specs/schott/optical/N-BK7.yml
        - PAGE: N-SF11
          data: specs/schott/optical/N-SF11.yml
        - PAGE: IRG2
          data: specs/schott/infrared/IRG2.yml
    - BOOK: ohara
      content:
        - PAGE: S-BAL35
          data: specs/ohara/optical/S-BAL35.yml
        - PAGE: dup
          data: specs/schott/optical/N-BK7.yml
- SHELF: main
  content:
        - PAGE: Malitson
          data: main/SiO2/nk/Malitson.yml
    - BOOK: corning
          data: specs/corning/EagleXG.yml
`

describe('refractiveindex.info catalogue installer', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists the makers under specs/ with their pages, shelves and no duplicates', () => {
    const m = parseRiiIndex(INDEX)
    expect(m.map((x) => [x.id, x.name, x.paths.length])).toEqual([
      ['schott', 'SCHOTT', 3],
      ['corning', 'CORNING', 1],
      ['ohara', 'OHARA', 1],
    ])
    expect(m[0].paths).toEqual(['specs/schott/infrared/IRG2.yml', 'specs/schott/optical/N-BK7.yml', 'specs/schott/optical/N-SF11.yml'])
    expect(m[0].groups).toEqual(['infrared', 'optical'])
    expect(m[1].groups).toEqual(['·'])
  })

  it('downloads the pages at the pinned revision, reports progress and failed pages', async () => {
    const urls: string[] = []
    vi.stubGlobal('fetch', async (url: string) => {
      urls.push(url)
      return url.endsWith('B.yml') ? new Response('x', { status: 404 }) : new Response(`page ${url.split('/').pop()}`)
    })
    const seen: number[] = []
    const r = await fetchRiiPages('abc123', ['specs/m/optical/C.yml', 'specs/m/optical/A.yml', 'specs/m/optical/B.yml'], (d) => seen.push(d), undefined, 2)
    expect(r.files).toEqual([
      { path: 'specs/m/optical/A.yml', content: 'page A.yml' },
      { path: 'specs/m/optical/C.yml', content: 'page C.yml' },
    ])
    expect(r.failed).toEqual(['specs/m/optical/B.yml'])
    expect(seen.sort()).toEqual([1, 2, 3])
    expect(urls[0]).toBe('https://raw.githubusercontent.com/polyanskiy/refractiveindex.info-database/abc123/database/data/specs/m/optical/C.yml')
  })
})
