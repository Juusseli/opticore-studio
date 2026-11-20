import { useEffect, useState } from 'react'
import { api } from '../../lib/api'
import type { Project, SystemOutline } from '../../lib/types'
import { useEngineStore } from '../../store/engineStore'

const cache = new Map<string, SystemOutline | null>()

/** Outline of a stored project, fetched from the engine once per saved state (null: offline or not traceable). */
export function useProjectOutline(project: Project, key: string): SystemOutline | null {
  const backend = useEngineStore((s) => s.backend)
  const [fetched, setFetched] = useState<{ key: string; outline: SystemOutline | null } | null>(null)
  useEffect(() => {
    if (cache.has(key) || backend !== 'online') return
    const ctrl = new AbortController()
    api
      .outline({ system: project.system, custom_materials: project.custom_materials }, ctrl.signal)
      .then((o) => {
        cache.set(key, o)
        setFetched({ key, outline: o })
      })
      .catch((e) => {
        if ((e as Error).name !== 'AbortError') cache.set(key, null)
      })
    return () => ctrl.abort()
  }, [key, backend, project])
  return cache.get(key) ?? (fetched?.key === key ? fetched.outline : null)
}
