// Manufacturer glass catalogues from the refractiveindex.info database (CC0), downloaded on request.
// The browser fetches the maker's YAML pages from GitHub, the engine converts them (/materials/rii) and
// the catalogue is kept in IndexedDB like an AGF import (ADR-015, ADR-018). OptiCore ships no glass data.

export const RII_REPO = 'polyanskiy/refractiveindex.info-database'
const RAW = (ref: string, path: string) => `https://raw.githubusercontent.com/${RII_REPO}/${ref}/database/${path}`

export interface RiiMaker {
  /** folder under database/data/specs, e.g. "schott" */
  id: string
  /** catalogue name, e.g. "SCHOTT" */
  name: string
  /** data paths relative to database/data, e.g. "specs/schott/optical/N-BK7.yml" */
  paths: string[]
  /** sub-shelves, e.g. ["optical", "infrared"] */
  groups: string[]
}

/** Makers and their pages listed in the database index (catalog-nk.yml). Pure; tested in rii.test.ts. */
export function parseRiiIndex(text: string): RiiMaker[] {
  const by = new Map<string, Set<string>>()
  for (const m of text.matchAll(/^\s*data:\s*(specs\/([A-Za-z0-9_-]+)\/[^\s#]+\.ya?ml)\s*$/gm)) {
    const [, path, maker] = m
    if (!by.has(maker)) by.set(maker, new Set())
    by.get(maker)!.add(path)
  }
  return [...by.entries()]
    .map(([id, set]) => {
      const paths = [...set].sort()
      const groups = [...new Set(paths.map((p) => p.split('/').slice(2, -1).join('/') || '·'))].sort()
      return { id, name: id.toUpperCase(), paths, groups }
    })
    .sort((a, b) => b.paths.length - a.paths.length || a.id.localeCompare(b.id))
}

/** The database commit to read (recorded with the catalogue); falls back to the default branch. */
export async function riiRevision(signal?: AbortSignal): Promise<string> {
  try {
    const r = await fetch(`https://api.github.com/repos/${RII_REPO}/commits/main`, { signal, headers: { Accept: 'application/vnd.github.sha' } })
    const sha = (await r.text()).trim()
    if (r.ok && /^[0-9a-f]{40}$/.test(sha)) return sha
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
  }
  return 'main'
}

export async function fetchRiiIndex(ref: string, signal?: AbortSignal): Promise<RiiMaker[]> {
  const r = await fetch(RAW(ref, 'catalog-nk.yml'), { signal })
  if (!r.ok) throw new Error(`refractiveindex.info index: HTTP ${r.status}`)
  return parseRiiIndex(await r.text())
}

/** Downloads the maker's pages (a few at a time); onProgress(done, total). Failed pages are returned separately. */
export async function fetchRiiPages(
  ref: string,
  paths: string[],
  onProgress: (done: number, total: number) => void,
  signal?: AbortSignal,
  concurrency = 12,
): Promise<{ files: { path: string; content: string }[]; failed: string[] }> {
  const files: { path: string; content: string }[] = []
  const failed: string[] = []
  let next = 0
  let done = 0
  const worker = async () => {
    while (next < paths.length) {
      const path = paths[next++]
      try {
        const r = await fetch(RAW(ref, `data/${path}`), { signal })
        if (!r.ok) throw new Error(String(r.status))
        files.push({ path, content: await r.text() })
      } catch (e) {
        if ((e as Error).name === 'AbortError') throw e
        failed.push(path)
      }
      onProgress(++done, paths.length)
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, paths.length) }, worker))
  files.sort((a, b) => a.path.localeCompare(b.path))
  return { files, failed }
}
