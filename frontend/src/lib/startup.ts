// What the application opens at launch, and how the start screen groups the templates.
import type { StoredProject } from './storage'
import type { Project, SampleCategory, SampleInfo } from './types'

export interface StartupInput {
  showAtStartup: boolean
  autosave: { project: Project; dirty: boolean; at: string } | undefined
  /** saved projects, most recent first */
  library: StoredProject[]
}

export type StartupPlan =
  /** unsaved work: opened as it was left (unsaved) and always offered on the start screen */
  | { open: 'recovery'; project: Project; at: string; inLibrary: boolean; showStart: true }
  /** the project that was open last, or the most recently saved one */
  | { open: 'last'; project: Project; inLibrary: boolean; showStart: boolean }
  /** nothing to reopen: the tutorial sample */
  | { open: 'sample'; showStart: boolean }

export function startupPlan({ showAtStartup, autosave, library }: StartupInput): StartupPlan {
  const inLibrary = (id: string) => library.some((p) => p.id === id)
  if (autosave?.project && autosave.dirty) return { open: 'recovery', project: autosave.project, at: autosave.at, inLibrary: inLibrary(autosave.project.id), showStart: true }
  // a clean autosave is the project that was open when the app was closed
  if (autosave?.project) return { open: 'last', project: autosave.project, inLibrary: inLibrary(autosave.project.id), showStart: showAtStartup }
  if (library.length) return { open: 'last', project: library[0].project, inLibrary: true, showStart: showAtStartup }
  return { open: 'sample', showStart: showAtStartup }
}

/** What "Discard changes" reopens: the saved version of the recovered project, else the last saved project. */
export function discardTarget(projectId: string, library: StoredProject[]): StoredProject | null {
  return library.find((p) => p.id === projectId) ?? library[0] ?? null
}

export const CATEGORY_ORDER: SampleCategory[] = ['liveimage', 'imaging', 'fibre', 'lighting', 'gratings', 'mirrors', 'multiconfig']

/** Templates in start-screen groups (fixed group order, engine order within a group, empty groups left out;
 * a sample without a known group counts as an imaging lens). */
export function groupTemplates(samples: SampleInfo[]): { category: SampleCategory; samples: SampleInfo[] }[] {
  const cat = (s: SampleInfo): SampleCategory => (s.category && CATEGORY_ORDER.includes(s.category) ? s.category : 'imaging')
  return CATEGORY_ORDER.map((category) => ({ category, samples: samples.filter((s) => cat(s) === category) })).filter((g) => g.samples.length > 0)
}
