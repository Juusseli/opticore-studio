import { isValidElement, type ReactNode } from 'react'

export function cx(...c: (string | false | null | undefined)[]): string {
  return c.filter(Boolean).join(' ')
}

/** Accessible name of a table-cell control that has no label of its own: the column header and the row's
 *  first identifying cell, e.g. "Target 2" or "Max (mm) S3". */
export function cellName(el: HTMLElement): string | null {
  const td = el.closest('td')
  const tr = td?.parentElement as HTMLTableRowElement | null
  const table = el.closest('table')
  if (!td || !tr || !table) return null
  let col = 0
  for (const c of Array.from(tr.cells)) {
    if (c === td) break
    col += c.colSpan
  }
  let header = ''
  const head = table.tHead?.rows[0]
  if (head) {
    let k = 0
    for (const c of Array.from(head.cells)) {
      if (col < k + c.colSpan) {
        header = (c.getAttribute('aria-label') || c.getAttribute('title')?.split(':')[0] || c.textContent || '').trim()
        if (c.textContent?.trim()) header = c.textContent.trim()
        break
      }
      k += c.colSpan
    }
  }
  if (!header) return null
  let row = ''
  for (const c of Array.from(tr.cells)) {
    if (c === td) break
    const tx = (c.querySelector('input,select') as HTMLInputElement | null)?.value || c.textContent || ''
    if (tx.trim()) {
      row = tx.trim().slice(0, 24)
      break
    }
  }
  return row ? `${header} ${row}` : header
}

/** Up to 10 significant digits without trailing zeros (display only). */
export function compactNumber(v: number): string {
  if (!Number.isFinite(v)) return String(v)
  if (v === 0) return '0'
  const a = Math.abs(v)
  if (a >= 1e10 || a < 1e-6) return v.toExponential(6).replace(/\.?0+e/, 'e')
  const s = v.toPrecision(10)
  return s.includes('e') ? s : s.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '')
}

/** Plain text of a React node (for accessible names of controls whose visible label is markup). */
export function textOf(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textOf).join('')
  if (isValidElement(node)) return textOf((node.props as { children?: ReactNode }).children)
  return ''
}
