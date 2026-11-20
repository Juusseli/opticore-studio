/** Unique coating name: upper case, not clashing with built-in or other project coatings. */
export function uniqueCoatingName(base: string, taken: string[]): string {
  const b = base.trim().toUpperCase() || 'COATING'
  if (!taken.includes(b)) return b
  for (let k = 2; ; k++) if (!taken.includes(`${b}_${k}`)) return `${b}_${k}`
}
