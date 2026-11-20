import { AlertTriangle, RotateCcw } from 'lucide-react'
import { Component, type ErrorInfo, type ReactNode } from 'react'
import { useT } from '../../lib/i18n'
import { useEngineStore } from '../../store/engineStore'
import { resetStoredLayout } from './storedLayout'
import { Button } from './ui'

interface Props {
  /** shown in the fallback and in the console log, e.g. the view name */
  name: string
  children: ReactNode
  /** whole-application boundary: offers to reset the stored layout and reload */
  root?: boolean
  /** a change (e.g. another view or tab chosen) clears the error. The boundary itself stays mounted,
   * so errors from tearing down the previous content are still caught here. */
  resetKey?: string
}

interface State {
  error: Error | null
  /** the reset key the current content belongs to */
  resetKey?: string
}

/** Keeps a crashing view or panel from taking the whole application down.
 * The fallback names the failing part and offers to retry; the project itself is untouched. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, resetKey: this.props.resetKey }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey !== state.resetKey ? { error: null, resetKey: props.resetKey } : null
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[${this.props.name}]`, error, info.componentStack)
    try {
      useEngineStore.getState().log_('error', `${this.props.name}: ${error.message}`)
    } catch {
      /* logging must never throw */
    }
  }

  render() {
    if (!this.state.error) return this.props.children
    return <Fallback name={this.props.name} error={this.state.error} root={this.props.root} onRetry={() => this.setState({ error: null })} />
  }
}

function Fallback({ name, error, root, onRetry }: { name: string; error: Error; root?: boolean; onRetry: () => void }) {
  const t = useT()
  return (
    <div className={root ? 'flex h-screen items-center justify-center bg-bg p-6 text-fg' : 'flex h-full min-h-[120px] items-center justify-center p-4'}>
      <div className="max-w-md rounded-lg border border-line bg-panel p-4 text-body shadow-lg">
        <div className="mb-2 flex items-center gap-2 font-semibold text-danger">
          <AlertTriangle size={16} />
          {t('err.title')} {name}
        </div>
        <div className="mb-2 text-muted">{root ? t('err.rootHint') : t('err.hint')}</div>
        <pre className="mb-3 max-h-32 overflow-auto rounded bg-panel-2 p-2 text-small whitespace-pre-wrap text-faint">{error.message}</pre>
        <div className="flex gap-2">
          <Button size="sm" onClick={onRetry}>
            <RotateCcw size={12} />
            {t('err.retry')}
          </Button>
          {root && (
            <Button
              size="sm"
              onClick={() => {
                resetStoredLayout()
                location.reload()
              }}
            >
              {t('err.resetLayout')}
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
