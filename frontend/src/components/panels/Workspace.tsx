import { ImageSimulationView, RelativeIlluminationView } from '../views/ImagingViews'
import { VectorPsfView } from '../views/VectorPsfView'
import { AdvisorView } from '../views/AdvisorView'
import { DesignSpaceView } from '../views/DesignSpaceView'
import { LiveImageView } from '../views/LiveImageView'
import { Fibre2dView } from '../views/Fibre2dView'
import { RcwaView } from '../views/RcwaView'
import { InterferogramView } from '../views/InterferogramView'
import { SpectrometerView } from '../views/SpectrometerView'
import { FibreModesView } from '../views/FibreModesView'
import { FdtdView, PopView } from '../views/WaveViews'
import { Handle } from '../common/Handle'
export { Handle }
import { Columns2, Square } from 'lucide-react'
import { lazy, Suspense, useRef } from 'react'
import { useT } from '../../lib/i18n'
import { isDirty, useProjectStore } from '../../store/projectStore'
import { useEngineStore } from '../../store/engineStore'
import { isRunning, useOptStore } from '../../store/optStore'
import { type BottomTab, useUiStore, type ViewKind } from '../../store/uiStore'
import { Badge, IconButton, Spinner, Tabs } from '../common/ui'
import { cx } from '../common/uiUtils'
import { workspace } from '../../lib/workspaces'
import { ViewPicker } from '../common/ViewMenu'
import { LensDataEditor } from '../editors/LensDataEditor'
import { MeritEditor } from '../editors/MeritEditor'
import { TolerancePanel } from '../editors/TolerancePanel'
import { ConfigEditor } from '../editors/ConfigEditor'
import { CadPanel } from '../editors/CadPanel'
import { SourcesPanel } from '../editors/SourcesPanel'
import { MountsPanel } from '../editors/MountsPanel'
import { SweepView } from '../views/SweepView'
import { ThermalView } from '../views/ThermalView'
import { GhostView } from '../views/GhostView'
import { NonSeqView } from '../views/NonSeqView'
import { isTolRunning, useTolStore } from '../../store/tolStore'
import { OptimizationPanel } from '../editors/OptimizationPanel'
import { SystemEditor } from '../editors/SystemEditor'
import { ChromaticView, FieldView, LongitudinalView, RayFanView, SpotView, SystemDataView } from '../views/AnalysisViews'
import { GaussianView, HuygensView, MtfView, PolarizationView, OpdFanView, PsfView, WavefrontView } from '../views/PhysicalOpticsViews'
import { DispersionView } from '../dialogs/MaterialBrowser'
import { Layout2D } from '../views/Layout2D'
import { CoatingsView } from '../views/CoatingsView'
import { ConsolePanel, MessagesPanel } from './BottomPanels'
import { ErrorBoundary } from '../common/ErrorBoundary'

const Viewport3D = lazy(() => import('../views/Viewport3D').then((m) => ({ default: m.Viewport3D })))

function ViewBody({ v }: { v: ViewKind }) {
  switch (v) {
    case 'layout2d':
      return <Layout2D />
    case 'layout3d':
      return (
        <Suspense
          fallback={
            <div className="flex h-full items-center justify-center">
              <Spinner />
            </div>
          }
        >
          <Viewport3D />
        </Suspense>
      )
    case 'spot':
      return <SpotView />
    case 'rayfan':
      return <RayFanView />
    case 'opdfan':
      return <OpdFanView />
    case 'wavefront':
      return <WavefrontView />
    case 'interferogram':
      return <InterferogramView />
    case 'spectrometer':
      return <SpectrometerView />
    case 'psf':
      return <PsfView />
    case 'huygens':
      return <HuygensView />
    case 'coatings':
      return <CoatingsView />
    case 'gaussian':
      return <GaussianView />
    case 'pop':
      return <PopView />
    case 'fibermodes':
      return <FibreModesView />
    case 'fiber2d':
      return <Fibre2dView />
    case 'rcwa':
      return <RcwaView />
    case 'fdtd':
      return <FdtdView />
    case 'polarization':
      return <PolarizationView />
    case 'sweep':
      return <SweepView />
    case 'designspace':
      return <DesignSpaceView />
    case 'ghosts':
      return <GhostView />
    case 'nonseq':
      return <NonSeqView />
    case 'mtf':
      return <MtfView />
    case 'relillum':
      return <RelativeIlluminationView />
    case 'imagesim':
      return <ImageSimulationView />
    case 'liveimage':
      return <LiveImageView />
    case 'vectorpsf':
      return <VectorPsfView />
    case 'field':
      return <FieldView />
    case 'longitudinal':
      return <LongitudinalView />
    case 'chromatic':
      return <ChromaticView />
    case 'advisor':
      return <AdvisorView />
    case 'systemdata':
      return <SystemDataView />
    case 'thermal':
      return <ThermalView />
    case 'dispersion':
      return <DispersionView />
  }
}

function Pane({ side }: { side: 'left' | 'right' }) {
  const t = useT()
  const view = useUiStore((s) => (side === 'left' ? s.leftView : s.rightView))
  const ws = useUiStore((s) => s.workspace)
  const setUi = useUiStore((s) => s.set)
  const focused = useUiStore((s) => s.focusedPane === side)
  return (
    <div className={cx('flex min-h-0 min-w-0 flex-1 flex-col bg-panel', focused && 'ring-1 ring-accent/25 ring-inset')} onMouseDown={() => setUi({ focusedPane: side })}>
      <div className="flex h-8 shrink-0 items-center gap-1 border-b border-line bg-panel-2 px-1.5">
        <ViewPicker value={view} groups={workspace(ws).groups} label={t(side === 'left' ? 'view.leftPane' : 'view.rightPane')} onChange={(v) => setUi(side === 'left' ? { leftView: v, focusedPane: 'left' } : { rightView: v, focusedPane: 'right' })} />
        <div className="flex-1" />
        {side === 'right' && (
          <IconButton title={t('view.single')} onClick={() => setUi({ split: false })}>
            <Square size={14} />
          </IconButton>
        )}
      </div>
      <div className="relative min-h-0 flex-1">
        <ErrorBoundary resetKey={view} name={t('view.' + view)}>
          <ViewBody v={view} />
        </ErrorBoundary>
      </div>
    </div>
  )
}

export function CenterWorkspace() {
  const t = useT()
  const split = useUiStore((s) => s.split)
  const ratio = useUiStore((s) => s.splitRatio)
  const setUi = useUiStore((s) => s.set)
  const wrap = useRef<HTMLDivElement>(null)
  return (
    <div ref={wrap} className="relative flex min-h-0 min-w-0 flex-1">
      <div className="flex min-h-0 min-w-0 flex-col" style={{ flex: split ? `${ratio} 1 0` : '1 1 0' }}>
        <Pane side="left" />
      </div>
      {split && (
        <>
          <Handle dir="h" onDrag={(dx) => setUi({ splitRatio: Math.min(0.85, Math.max(0.15, useUiStore.getState().splitRatio + dx / (wrap.current?.clientWidth || 1000))) })} />
          <div className="flex min-h-0 min-w-0 flex-col" style={{ flex: `${1 - ratio} 1 0` }}>
            <Pane side="right" />
          </div>
        </>
      )}
      {!split && (
        <div className="absolute top-1 right-1.5 z-10">
          <IconButton title={t('view.split')} onClick={() => setUi({ split: true })}>
            <Columns2 size={14} />
          </IconButton>
        </div>
      )}
    </div>
  )
}

export function BottomPanel() {
  const t = useT()
  const tab = useUiStore((s) => s.bottomTab)
  const ws = useUiStore((s) => s.workspace)
  const setUi = useUiStore((s) => s.set)
  const ev = useEngineStore((s) => s.evaluation)
  const evalError = useEngineStore((s) => s.evalError)
  const running = useOptStore(isRunning)
  const tolRunning = useTolStore(isTolRunning)
  const nOps = useProjectStore((s) => s.project.optimization.operands.length)
  const nConf = useProjectStore((s) => s.project.system.multi_config?.names.length ?? 0)
  const nCad = useProjectStore((s) => s.project.cad_assets.length)
  const nMounts = useProjectStore((s) => (s.project.system.environment_enabled ? (s.project.system.mounts?.length ?? 0) : 0))
  const nSrc = useProjectStore((s) => (s.project.sources?.length ?? 0) + (s.project.detectors?.length ?? 0))
  const warn = (ev?.diagnostics ?? []).filter((d) => d.level !== 'info').length + (evalError ? 1 : 0)
  const all: { id: BottomTab; label: string; badge?: React.ReactNode }[] = [
    { id: 'lde', label: t('bt.lde') },
    { id: 'system', label: t('bt.system') },
    { id: 'mounts', label: t('bt.mounts'), badge: nMounts ? <Badge>{nMounts}</Badge> : undefined },
    { id: 'configs', label: t('bt.configs'), badge: nConf ? <Badge>{nConf}</Badge> : undefined },
    { id: 'merit', label: t('bt.merit'), badge: nOps ? <Badge>{nOps}</Badge> : undefined },
    { id: 'optimization', label: t('bt.optimization'), badge: running ? <Spinner size={12} /> : undefined },
    { id: 'cad', label: t('bt.cad'), badge: nCad ? <Badge>{nCad}</Badge> : undefined },
    { id: 'sources', label: t('bt.sources'), badge: nSrc ? <Badge>{nSrc}</Badge> : undefined },
    { id: 'tolerancing', label: t('bt.tolerancing'), badge: tolRunning ? <Spinner size={12} /> : undefined },
    { id: 'messages', label: t('bt.messages'), badge: warn ? <Badge tone={evalError ? 'danger' : 'warn'}>{warn}</Badge> : undefined },
    { id: 'console', label: t('bt.console') },
  ]
  // the workspace's tabs, in its order
  const tabs = workspace(ws)
    .tabs.map((id) => all.find((x) => x.id === id))
    .filter((x): x is (typeof all)[number] => !!x)
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-panel">
      <Tabs tabs={tabs} value={tab} onChange={(v) => setUi({ bottomTab: v })} />
      <ErrorBoundary resetKey={tab} name={t('bt.' + tab)}>
        <div className="min-h-0 flex-1">
          {tab === 'lde' && <LensDataEditor />}
          {tab === 'system' && <SystemEditor />}
          {tab === 'configs' && <ConfigEditor />}
          {tab === 'merit' && <MeritEditor />}
          {tab === 'optimization' && <OptimizationPanel />}
          {tab === 'tolerancing' && <TolerancePanel />}
          {tab === 'cad' && <CadPanel />}
          {tab === 'sources' && <SourcesPanel />}
          {tab === 'mounts' && <MountsPanel />}
          {tab === 'messages' && <MessagesPanel />}
          {tab === 'console' && <ConsolePanel />}
        </div>
      </ErrorBoundary>
    </div>
  )
}

export function StatusBar() {
  const t = useT()
  const backend = useEngineStore((s) => s.backend)
  const version = useEngineStore((s) => s.engineVersion)
  const ms = useEngineStore((s) => s.evalMs)
  const evaluating = useEngineStore((s) => s.evaluating)
  const ev = useEngineStore((s) => s.evaluation)
  const dirty = useProjectStore(isDirty)
  const last = useProjectStore((s) => s.lastAction)
  const sel = useProjectStore((s) => s.selection)
  const nSurf = useProjectStore((s) => s.project.system.surfaces.length)
  const setUi = useUiStore((s) => s.set)
  const diags = ev?.diagnostics.filter((d) => d.level !== 'info').length ?? 0
  return (
    <div className="flex h-6 shrink-0 items-center gap-3 border-t border-line bg-panel-2 px-3 text-small text-muted">
      <span className="flex items-center gap-1.5">
        <span className={cx('h-2 w-2 rounded-full', backend === 'online' ? 'bg-ok' : backend === 'offline' ? 'bg-danger' : 'bg-warn')} />
        {backend === 'online' ? `${t('st.online')} ${version ?? ''}` : backend === 'offline' ? t('st.offline') : t('st.connecting')}
      </span>
      <span className="num">{evaluating ? <Spinner size={12} /> : ms !== null ? `${t('st.eval')} ${ms.toFixed(0)} ms` : ''}</span>
      <button className={cx('hover:text-fg', diags ? 'text-warn' : '')} onClick={() => setUi({ bottomTab: 'messages', bottomOpen: true })}>
        {diags} {t('st.diagnostics')}
      </button>
      <span className="truncate text-faint">{last}</span>
      <div className="flex-1" />

      <span>
        {t('c.surface')} {sel.join(', ')} / {nSurf - 1}
      </span>
      <span>{t('st.units')}</span>
      <span className={dirty ? 'text-warn' : 'text-ok'}>{dirty ? `● ${t('st.unsaved')}` : `✓ ${t('st.saved')}`}</span>
    </div>
  )
}
