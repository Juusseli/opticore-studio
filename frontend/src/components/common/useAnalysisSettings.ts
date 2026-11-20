// Settings of an analysis view, stored in the project (analysis_settings[key]) so they are saved with it.
import type { Project } from '../../lib/types'
import { useProjectStore } from '../../store/projectStore'

/** [settings with defaults filled in, setter]. Every change is one undoable step. */
export function useAnalysisSettings<T extends object>(key: string, defaults: T, label = `Analysis settings (${key})`) {
  const stored = useProjectStore((s) => s.project.analysis_settings[key]) as Partial<T> | undefined
  const update = useProjectStore((s) => s.updateProject)
  const st = { ...defaults, ...(stored ?? {}) } as T
  const set = (patch: Partial<T>, undoLabel = label) =>
    update((p: Project) => {
      p.analysis_settings[key] = { ...defaults, ...((p.analysis_settings[key] as object) ?? {}), ...patch }
    }, undoLabel)
  return [st, set] as const
}
