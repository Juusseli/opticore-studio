// Shared controls and folding analysis bars (docs/UI_DESIGN.md, Components).
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { nextFold, UNFOLD_SLACK } from './barFold'

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f)
    if (statSync(p).isDirectory()) return sources(p)
    return /\.(ts|tsx)$/.test(f) && !/\.test\./.test(f) ? [p] : []
  })
}

const components = sources(join(process.cwd(), 'src', 'components'))
const scan = (re: RegExp, skip: (f: string) => boolean = () => false) =>
  components
    .filter((f) => !skip(f))
    .flatMap((f) => [...readFileSync(f, 'utf-8').matchAll(re)].map((m) => `${f.split(/[\\/]/).slice(-2).join('/')}: ${m[0].slice(0, 80)}`))

describe('analysis bar folding', () => {
  it('stays unfolded while the primary settings fit', () => {
    expect(nextFold({ folded: false, need: 0 }, 300, 300)).toEqual({ folded: false, need: 0 })
    expect(nextFold({ folded: false, need: 0 }, 301, 300)).toEqual({ folded: false, need: 0 }) // sub-pixel rounding
  })

  it('folds when they overflow and remembers the width they needed', () => {
    expect(nextFold({ folded: false, need: 0 }, 432, 244)).toEqual({ folded: true, need: 432 })
  })

  it('unfolds only with room to spare, so it cannot flap', () => {
    const s = { folded: true, need: 432 }
    expect(nextFold(s, 0, 432)).toBe(s)
    expect(nextFold(s, 0, 432 + UNFOLD_SLACK - 1)).toBe(s)
    expect(nextFold(s, 0, 432 + UNFOLD_SLACK)).toEqual({ folded: false, need: 432 })
  })

  it('does nothing while hidden (zero widths)', () => {
    expect(nextFold({ folded: false, need: 0 }, 0, 0).folded).toBe(false)
    expect(nextFold({ folded: true, need: 300 }, 0, 0).folded).toBe(true)
  })
})

describe('shared controls', () => {
  it('defines Label, Stat, Row and the field / wavelength pickers once (components/common/controls)', () => {
    expect(scan(/^(export )?function (L|Label|Stat|Row|WavelengthSelect|FieldSelect|useStored)\b/gm, (f) => /common[\\/]controls\.tsx$/.test(f))).toEqual([])
  })

  it('keeps analysis view settings behind useAnalysisSettings (undoable, saved with the project)', () => {
    // allowed: the hook itself, saved analyses, the specification table, the coating design and the sweep (validated against the system)
    const bad = scan(/analysis_settings(\.\w+|\[\w+\])\s*(=|\?\?=)(?!=)/g).filter((x) => !/useAnalysisSettings\.ts|\.saved|\.specs|\.coating_design|\.sweep/.test(x))
    expect(bad).toEqual([])
  })

  it('names buttons in the user language (no English literal aria-labels)', () => {
    expect(scan(/aria-label="[a-z][^"]*"/g)).toEqual([])
  })

  it('uses IconButton for row actions instead of bare styled buttons', () => {
    expect(scan(/<button\s+className="(px-[\d.]+ )?text-(faint|muted) hover:text-(fg|danger)[^"]*"/g)).toEqual([])
  })

  it('keeps units out of uppercase headings (CSS uppercase turns µm into ΜM and mm into MM)', () => {
    expect(scan(/uppercase[^\n]*>[^<{\n]*(µ|\bmm\b|\bnm\b)/g)).toEqual([])
  })

  it('does not colour text with data colours (they are 3:1 for marks, text needs 4.5:1)', () => {
    expect(scan(/style=\{\{ color: (fieldColor|wavelengthColor|SERIES|DATA)\b/g)).toEqual([])
  })

  it('has no field or wavelength select built by hand in a view', () => {
    expect(scan(/label: 'primary'/g)).toEqual([])
  })
})
