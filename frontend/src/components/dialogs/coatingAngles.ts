/** "30, 45" ⇄ [30, 45] (angles of incidence 0…89°, at most six). */
export function parseAngles(text: string): number[] | null {
  const v = text
    .split(/[\s,;]+/)
    .filter(Boolean)
    .map(Number)
  if (v.some((x) => !Number.isFinite(x) || x < 0 || x >= 90)) return null
  return [...new Set(v)].sort((a, b) => a - b).slice(0, 6)
}
