import { Pin, RefreshCw, Zap } from 'lucide-react'
import { type ReactNode, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { type FoldState, nextFold } from '../../lib/barFold'
import { useT } from '../../lib/i18n'
import { newId, nowIso } from '../../lib/project'
import type { AnalysisKind } from '../../lib/types'
import { useEngineStore } from '../../store/engineStore'
import { isRunning, useOptStore } from '../../store/optStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { Badge, IconButton, Spinner } from '../common/ui'
import { MoreSettings } from '../common/controls'
import { ViewState } from './ViewState'

/** Common chrome for analysis views: settings bar, method/sampling footer, pin & refresh. */
export function AnalysisFrame({
  kind,
  title,
  controls,
  more,
  actions,
  onDemand,
  alwaysShow,
  children,
  loading,
  error,
  hasData,
  ms,
  method,
  onRefresh,
  settings,
  result,
}: {
  kind: AnalysisKind
  title: string
  controls?: ReactNode
  /** secondary settings, behind "More settings ▾" so the bar never wraps */
  more?: ReactNode
  /** run controls of an on-demand analysis (replace the refresh button) */
  actions?: ReactNode
  /** computed on request (e.g. FDTD): no live-update toggle */
  onDemand?: boolean
  /** show the body without a result (it has its own empty state or editors) */
  alwaysShow?: boolean
  children: ReactNode
  loading: boolean
  error: string | null
  hasData: boolean
  ms: number | null
  method?: string
  onRefresh: () => void
  settings: Record<string, unknown>
  result: unknown
}) {
  const t = useT()
  // primary settings fold into the settings popover when the pane is too narrow for them (lib/barFold)
  const row = useRef<HTMLDivElement>(null)
  const [fold, setFold] = useState<FoldState>({ folded: false, need: 0 })
  const foldRef = useRef(fold)
  const measure = useCallback(() => {
    const el = row.current
    if (!el) return
    const n = nextFold(foldRef.current, el.scrollWidth, el.clientWidth)
    if (n.folded !== foldRef.current.folded) {
      foldRef.current = n
      setFold(n)
    }
  }, [])
  useLayoutEffect(() => {
    foldRef.current = fold
    measure()
  })
  useEffect(() => {
    const el = row.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [measure])
  const folded = fold.folded && !!controls
  const live = useUiStore((s) => s.liveAnalysis)
  const setUi = useUiStore((s) => s.set)
  const updateProject = useProjectStore((s) => s.updateProject)
  const toast = useUiStore((s) => s.toast)
  const notApplicable = useEngineStore((s) => s.analyses[kind]?.code === 'NOT_APPLICABLE')
  // the views follow an optimisation preview: say so, the numbers are not those of the project's design
  const previewing = useEngineStore((s) => !!s.preview)
  const optRunning = useOptStore(isRunning)
  const pin = () => {
    if (!result) return
    updateProject((p) => {
      const saved = (p.analysis_settings.saved ??= [])
      saved.push({ id: newId(), type: kind, label: `${title} — ${new Date().toLocaleString()}`, timestamp: nowIso(), settings, result })
      if (saved.length > 30) saved.splice(0, saved.length - 30)
    }, `Pin ${title}`)
    toast('success', `${title}: snapshot saved to project`)
  }
  return (
    <div className="@container flex h-full min-h-0 flex-col">
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-line px-2">
        {/* one row: the primary settings; the rest sit under More settings */}
        <div ref={row} className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden [&>*]:shrink-0">
          {!folded && controls}
        </div>
        {(more || folded) && (
          <MoreSettings label={folded ? t('an.settings') : undefined}>
            {folded && controls}
            {folded && more && <div className="h-px w-full bg-line" />}
            {more}
          </MoreSettings>
        )}
        {previewing && (
          <span className="shrink-0" title={t(optRunning ? 'opt.preview' : 'opt.previewResult')}>
            <Badge tone="warn">{t(optRunning ? 'opt.previewShort' : 'opt.previewResultShort')}</Badge>
          </span>
        )}
        {loading && <Spinner size={12} />}
        {ms !== null && !loading && <span className="num hidden text-caption whitespace-nowrap text-faint @xl:inline">{ms.toFixed(0)} ms</span>}
        {!onDemand && (
          <IconButton title={t('an.liveHint')} active={live} aria-pressed={live} className="h-6 w-6" onClick={() => setUi({ liveAnalysis: !live })}>
            <Zap size={14} />
          </IconButton>
        )}
        <IconButton title={t('an.pin')} className="h-6 w-6" onClick={pin} disabled={!result}>
          <Pin size={14} />
        </IconButton>
        {actions ?? (
          <IconButton title={t('an.refresh')} className="h-6 w-6" onClick={onRefresh}>
            <RefreshCw size={14} />
          </IconButton>
        )}
      </div>
      <div className="relative min-h-0 flex-1">{hasData || alwaysShow ? children : <ViewState kind={kind} error={error} loading={loading || !error} onRetry={onRefresh} notApplicable={notApplicable} />}</div>
      {method && (
        <div className="flex h-6 min-w-0 shrink-0 items-center gap-2 overflow-hidden border-t border-line px-2.5 text-caption text-faint">
          <span className="min-w-0 flex-1 truncate" title={method}>
            {t('an.method')}: {method}
          </span>
          {error && hasData && <span className="text-danger">· {error}</span>}
        </div>
      )}
    </div>
  )
}
