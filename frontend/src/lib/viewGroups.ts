// The analysis views and their groups: one definition for the pane selectors, the Analyze menu,
// the command palette and the Ctrl+1…9 shortcuts.

export const ALL_VIEWS = [
  'layout2d',
  'layout3d',
  'spot',
  'rayfan',
  'opdfan',
  'wavefront',
  'interferogram',
  'psf',
  'huygens',
  'vectorpsf',
  'coatings',
  'mtf',
  'relillum',
  'imagesim',
  'liveimage',
  'field',
  'longitudinal',
  'chromatic',
  'spectrometer',
  'advisor',
  'systemdata',
  'thermal',
  'dispersion',
  'gaussian',
  'polarization',
  'sweep',
  'ghosts',
  'nonseq',
  'fibermodes',
  'fiber2d',
  'rcwa',
  'pop',
  'fdtd',
  'designspace',
] as const

export type ViewKind = (typeof ALL_VIEWS)[number]

export type ViewGroup = 'layout' | 'geometric' | 'image' | 'system' | 'beams' | 'illumination' | 'tools'

/** Groups in menu order. Labels: `vg.<group>` (group) and `view.<kind>` (view). */
export const VIEW_GROUPS: { group: ViewGroup; views: ViewKind[] }[] = [
  { group: 'layout', views: ['layout2d', 'layout3d'] },
  { group: 'geometric', views: ['spot', 'rayfan', 'opdfan', 'field', 'longitudinal', 'chromatic'] },
  { group: 'image', views: ['wavefront', 'interferogram', 'psf', 'huygens', 'vectorpsf', 'mtf', 'relillum', 'imagesim', 'liveimage'] },
  { group: 'system', views: ['advisor', 'systemdata', 'thermal', 'dispersion', 'spectrometer', 'coatings', 'polarization'] },
  { group: 'beams', views: ['gaussian', 'pop', 'fibermodes', 'fiber2d', 'rcwa', 'fdtd'] },
  { group: 'illumination', views: ['nonseq', 'ghosts'] },
  { group: 'tools', views: ['sweep', 'designspace'] },
]

/** Every view in menu order; Ctrl+n shows the n-th. */
export const VIEW_IDS: ViewKind[] = VIEW_GROUPS.flatMap((g) => g.views)

export function viewGroup(v: ViewKind): ViewGroup {
  return VIEW_GROUPS.find((g) => g.views.includes(v))!.group
}

/** Ctrl+n shortcut of a view (the first nine in menu order), or null. */
export function viewShortcut(v: ViewKind): string | null {
  const i = VIEW_IDS.indexOf(v)
  return i >= 0 && i < 9 ? `Ctrl+${i + 1}` : null
}

/** Views whose group or name matches every word of the query (case-insensitive), grouped, in menu order. */
export function filterViews(query: string, label: (v: ViewKind) => string, groupLabel: (g: ViewGroup) => string): { group: ViewGroup; views: ViewKind[] }[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  return VIEW_GROUPS.map((g) => ({
    group: g.group,
    views: g.views.filter((v) => {
      const text = `${label(v)} ${groupLabel(g.group)} ${v}`.toLowerCase()
      return words.every((w) => text.includes(w))
    }),
  })).filter((g) => g.views.length > 0)
}
