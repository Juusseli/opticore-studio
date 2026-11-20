// Canonical JSON (sorted keys, no whitespace, ECMAScript number formatting).
// Must produce byte-identical output to backend/opticore/project.py:canonical_json.

export function canonicalJson(value: unknown): string {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'number') return Number.isFinite(value) ? JSON.stringify(value) : 'null'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'string') return JSON.stringify(value)
  if (Array.isArray(value)) return '[' + value.map((v) => canonicalJson(v)).join(',') + ']'
  if (typeof value === 'object') {
    const obj = value as Record<string, unknown>
    const keys = Object.keys(obj)
      .filter((k) => obj[k] !== undefined)
      .sort()
    return '{' + keys.map((k) => JSON.stringify(k) + ':' + canonicalJson(obj[k])).join(',') + '}'
  }
  throw new TypeError('Not JSON-serialisable')
}

export async function sha256Hex(text: string): Promise<string> {
  const data = new TextEncoder().encode(text)
  const digest = await crypto.subtle.digest('SHA-256', data)
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

export async function projectChecksum(project: Record<string, unknown>): Promise<string> {
  const body: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(project)) if (k !== 'checksum') body[k] = v
  return sha256Hex(canonicalJson(body))
}
