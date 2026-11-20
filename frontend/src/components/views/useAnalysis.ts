import { useEffect, useMemo, useRef } from 'react'
import { canonicalJson } from '../../lib/canonical'
import type { AnalysisKind } from '../../lib/types'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'

/** Subscribe a view to a backend analysis; recomputes (debounced by `delay` ms) when the system or settings change.
 *  Secondary read-outs use a longer delay so they do not compete with the views a user is dragging a value for. */
export function useAnalysis<T>(kind: AnalysisKind, settings: Record<string, unknown>, delay = 140) {
  const system = useProjectStore((s) => s.project.system)
  const custom = useProjectStore((s) => s.project.custom_materials)
  const preview = useEngineStore((s) => s.preview)
  const live = useUiStore((s) => s.liveAnalysis)
  const backend = useEngineStore((s) => s.backend)
  const state = useEngineStore((s) => s.analyses[kind])
  const run = useEngineStore((s) => s.runAnalysis)
  const retraceToken = useEngineStore((s) => s.retraceToken)
  const settingsKey = canonicalJson(settings)
  const sysKey = useMemo(() => canonicalJson({ s: preview ?? system, m: custom }), [preview, system, custom])

  useEffect(() => {
    if (backend === 'offline') return
    if (!live && state?.data) return
    const h = window.setTimeout(() => run(kind, JSON.parse(settingsKey)), delay)
    return () => window.clearTimeout(h)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sysKey, settingsKey, live, backend, kind, delay])

  // "Re-trace rays": recompute this view now (forced), whatever its live-update setting
  const seenToken = useRef(retraceToken)
  useEffect(() => {
    if (retraceToken === seenToken.current) return
    seenToken.current = retraceToken
    if (backend !== 'offline') run(kind, JSON.parse(settingsKey), true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [retraceToken])

  return {
    data: (state?.data ?? null) as T | null,
    error: state?.error ?? null,
    loading: !!state?.loading,
    ms: state?.ms ?? null,
    refresh: () => run(kind, JSON.parse(settingsKey), true),
  }
}
