import { AlertTriangle, Info, PlugZap, RefreshCw } from 'lucide-react'
import { useT } from '../../lib/i18n'
import { useEngineStore } from '../../store/engineStore'
import { useUiStore } from '../../store/uiStore'
import { Button, Empty, Spinner } from '../common/ui'

/** The engine is not reachable: what still works, and (folded away) how a developer starts it. */
export function OfflineNotice() {
  const t = useT()
  return (
    <Empty icon={<PlugZap size={26} className="text-warn" />}>
      <div className="font-semibold text-fg">{t('st.offline')}</div>
      <div>{t('an.offline')}</div>
      <details className="mt-3 text-left text-small text-faint">
        <summary className="cursor-pointer text-center select-none hover:text-muted">{t('an.offlineDev')}</summary>
        <div className="mt-1.5 rounded border border-line bg-panel-2 px-2 py-1.5 leading-relaxed">
          {t('an.offlineDevText')}
          <div className="mt-1 num break-all text-muted">scripts\dev.ps1</div>
          <div className="num break-all text-muted">backend\.venv\Scripts\python -m uvicorn opticore.api.main:app --app-dir backend --port 8000</div>
        </div>
      </details>
    </Empty>
  )
}

/** Placeholder shown while a view has no result: why, and what to do about it. */
export function ViewState({ kind, error, loading, onRetry, notApplicable }: { kind: string; error?: string | null; loading?: boolean; onRetry?: () => void; notApplicable?: boolean }) {
  const t = useT()
  const backend = useEngineStore((s) => s.backend)
  const evalError = useEngineStore((s) => s.evalError)
  const live = useUiStore((s) => s.liveAnalysis)
  if (backend === 'offline') return <OfflineNotice />
  const err = error ?? (kind === 'layout' ? evalError?.message : null)
  // a documented limitation of the analysis for this kind of system: say so plainly, nothing to retry
  if (err && notApplicable)
    return (
      <Empty icon={<Info size={24} className="text-muted" />}>
        <div className="font-semibold text-fg">{t('an.notApplicable')}</div>
        <div className="whitespace-pre-wrap">{err}</div>
      </Empty>
    )
  if (err)
    return (
      <Empty icon={<AlertTriangle size={24} className="text-danger" />}>
        <div className="font-semibold text-fg">{t(kind === 'layout' ? 'an.traceFailed' : 'an.analysisFailed')}</div>
        <div className="whitespace-pre-wrap">{err}</div>
        <div className="mt-1 text-small text-faint">{t(kind === 'layout' ? 'an.traceFailedHint' : 'an.failedHint')}</div>
        {onRetry && (
          <Button size="sm" className="mt-2" onClick={onRetry}>
            <RefreshCw size={12} /> {t('an.retry')}
          </Button>
        )}
      </Empty>
    )
  if (loading !== false || backend === 'unknown')
    return (
      <Empty icon={<Spinner size={18} />}>
        <span>{backend === 'unknown' ? t('st.connecting') : kind === 'layout' ? t('an.tracing') : t('an.computing')}</span>
      </Empty>
    )
  // nothing computed and nothing running: live updates are off
  return (
    <Empty>
      <div>{live ? t('an.waiting') : t('an.notComputed')}</div>
      {onRetry && (
        <Button size="sm" variant="primary" className="mt-2" onClick={onRetry}>
          <RefreshCw size={12} /> {t('an.computeNow')}
        </Button>
      )}
    </Empty>
  )
}
