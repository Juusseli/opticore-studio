// An engine result belongs to the design it was computed for. Requests that write their answer into the project
// take a snapshot first and write only if the snapshot still holds when the answer arrives: not into another
// project opened meanwhile, and not over edits made meanwhile (which the answer knows nothing about).
import { useProjectStore } from './projectStore'

export interface DesignSnapshot {
  id: string
  system: string
}

export function designSnapshot(): DesignSnapshot {
  const p = useProjectStore.getState().project
  return { id: p.id, system: JSON.stringify(p.system) }
}

/** The same project with the same optical system. */
export function sameDesign(s: DesignSnapshot): boolean {
  const p = useProjectStore.getState().project
  return p.id === s.id && JSON.stringify(p.system) === s.system
}

/** The same project (its system may have been edited). */
export function sameProject(s: DesignSnapshot): boolean {
  return useProjectStore.getState().project.id === s.id
}
