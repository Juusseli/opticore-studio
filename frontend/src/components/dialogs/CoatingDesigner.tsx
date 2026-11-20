import { Download, FileUp, FlaskConical, Layers, Library, Lock, Plus, Save, Search, Sparkles, Trash2, Unlock, Wand2, X } from 'lucide-react'
import { designSnapshot, sameDesign, sameProject } from '../../store/designGuard'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../lib/api'
import { COLOUR_Q, defaultCoatingDesign, defaultTarget, hasOf, isFraction, parseSpectrum, QUANTITIES, quantityUnits, recipeToCsv, removeThinLayers, retarget, shown as shownValue, stored as storedValue, targetText } from '../../lib/coatingDesign'
import { fmt } from '../../lib/format'
import { hasKey, useT } from '../../lib/i18n'
import { downloadText } from '../../lib/storage'
import { coatingOf } from '../../lib/project'
import type { CoatingAngular, CoatingDefinition, CoatingExample, CoatingFit, CoatingIlluminant, CoatingMeasurement, SurfaceCoatingContext, MaterialRecord, CoatingDesignSpec, CoatingEvaluation, CoatingMonteCarlo, CoatingOptimizeResult, CoatingQuantity, CoatingRecipe, CoatingTarget, CoatingTemplateKind, PaletteMaterial } from '../../lib/types'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { Plot, type Trace } from '../common/Plot'
import { Badge, Button, Checkbox, IconButton, NumberField, Select, Spinner, Tabs, TextField } from '../common/ui'
import { cx } from '../common/uiUtils'
import { uniqueCoatingName } from './coatingNames'
import { COLORMAPS, DATA, SERIES } from '../../lib/palette'
import { useWindowWidth } from '../../lib/viewport'
import { CoatingAnalysisPanel } from './CoatingAnalysis'

const TEMPLATES: { value: CoatingTemplateKind; label: string; needs: ('lambda0' | 'edge' | 'band' | 'pairs' | 'cavities')[] }[] = [
  { value: 'ar_broadband', label: 'Broadband antireflection', needs: ['band'] },
  { value: 'v_coat', label: 'V-coat (single-wavelength AR)', needs: ['lambda0'] },
  { value: 'hr', label: 'High reflector (quarter-wave stack)', needs: ['lambda0', 'pairs', 'band'] },
  { value: 'longpass', label: 'Long-pass edge filter', needs: ['edge', 'pairs'] },
  { value: 'shortpass', label: 'Short-pass edge filter', needs: ['edge', 'pairs'] },
  { value: 'bandpass', label: 'Band-pass (Fabry–Perot)', needs: ['lambda0', 'pairs', 'cavities', 'band'] },
  { value: 'notch', label: 'Notch / band-block', needs: ['lambda0', 'pairs', 'band'] },
  { value: 'beamsplitter', label: '50/50 beam splitter (45°)', needs: ['lambda0', 'band'] },
  { value: 'enhanced_mirror', label: 'Enhanced metal mirror ((LH)ᴺ on metal)', needs: ['lambda0', 'pairs', 'band'] },
  { value: 'protected_mirror', label: 'Protected metal mirror (λ/2 overcoat)', needs: ['lambda0', 'band'] },
]

/** Window width from which the library rail sits beside the designer instead of over it. */
const RAIL_SIDE_BY_SIDE = 1600

const pct = (v: number | null | undefined, d = 4) => (v === null || v === undefined || !Number.isFinite(v) ? '—' : `${fmt(v * 100, d)} %`)

/** The coating studio (workspace "Thin films"): a library of coatings and surfaces beside the thin-film designer
 * (setup, palette, start design and targets | spectrum and analyses | layers and optimisation). */
export function CoatingStudio() {
  const t = useT()
  const toast = useUiStore((s) => s.toast)
  const project = useProjectStore((s) => s.project)
  const update = useProjectStore((s) => s.updateProject)
  const materials = useEngineStore((s) => s.materials)
  const stored = project.analysis_settings.coating_design as CoatingDesignSpec | undefined
  const design: CoatingDesignSpec = stored ?? defaultCoatingDesign()
  const custom = project.custom_materials
  const setDesign = (fn: (d: CoatingDesignSpec) => void, label: string) =>
    update((p) => {
      const d = structuredClone((p.analysis_settings.coating_design as CoatingDesignSpec | undefined) ?? defaultCoatingDesign())
      fn(d)
      p.analysis_settings.coating_design = d
    }, label)

  const matNames = useMemo(() => [...new Set([...custom.map((m) => m.name.toUpperCase()), ...materials.map((m) => m.name)])], [custom, materials])
  const builtins = useEngineStore((s) => s.coatings)
  const projectCoatings = project.system.custom_coatings ?? []
  const arg = useUiStore((s) => s.coatingArg) as { surfaces?: number[]; coating?: string } | null
  const [forSurfaces, setForSurfaces] = useState<number[]>([])
  const [ctx, setCtx] = useState<SurfaceCoatingContext[]>([])
  const replaceDesign = (d: CoatingDesignSpec, label: string) => update((p) => void (p.analysis_settings.coating_design = structuredClone(d)), label)

  const openCoating = async (name: string) => {
    const cd = coatingOf(project.system, name)
    const b = cd ? undefined : builtins.find((c) => c.name === name.trim().toUpperCase())
    if (b) {
      // a built-in: under the conditions it was designed for, its specification as the targets
      try {
        const r = await api.cdFromCoating({ builtin: b.name, base: design })
        replaceDesign(r.design, `Open built-in coating ${b.name} in the designer`)
        setViewAngle(targetAngle(r.design))
        toast('info', t('cd.openedBuiltin', { name: b.name }))
      } catch (e) {
        toast('error', (e as Error).message)
      }
      return
    }
    if (!cd) return
    try {
      const r = await api.cdFromCoating({ coating: cd, base: design })
      replaceDesign(r.design, `Open coating ${cd.name} in the designer`)
      if (!cd.design) toast('info', t('cd.rebuilt'))
    } catch (e) {
      toast('error', (e as Error).message)
    }
  }

  const designForSurfaces = async (surfaces: number[]) => {
    const sys = useProjectStore.getState().project.system
    try {
      const cs = await Promise.all(surfaces.map((j) => api.surfaceContext({ system: sys, custom_materials: custom, surface: j })))
      setForSurfaces(surfaces)
      setCtx(cs)
      const c0 = cs[0]
      const existing = coatingOf(sys, c0.coating)
      if (existing) {
        const r = await api.cdFromCoating({ coating: existing, base: design })
        replaceDesign(r.design, `Open coating ${existing.name} for surface ${surfaces.join(', ')}`)
        return
      }
      const [b0, b1] = c0.wavelength_band_nm[1] - c0.wavelength_band_nm[0] < 1 ? [c0.primary_nm * 0.9, c0.primary_nm * 1.1] : c0.wavelength_band_nm
      const mean = Math.max(...cs.map((c) => c.angles_deg?.mean ?? 0))
      const p95 = Math.max(...cs.map((c) => c.angles_deg?.p95 ?? 0))
      const d = defaultCoatingDesign()
      d.name = `S${surfaces.join('-')} coating`
      d.incident = c0.incident
      d.design_wavelength_nm = Math.round(Math.sqrt(b0 * b1))
      const tg = (q: 'R', kind: '<=' | '>=', value: number, angle: number, weight = 1) => ({ ...defaultTarget(d.design_wavelength_nm), quantity: q, kind, value, angle_deg: Math.round(angle * 10) / 10, lambda_min_nm: Math.round(b0), lambda_max_nm: Math.round(b1), weight })
      if (c0.is_mirror) {
        d.substrate_index = 1.0
        d.substrate_extinction = 6.0
        d.targets = [tg('R', '>=', 0.95, mean), tg('R', '>=', 0.9, p95, 0.5)]
      } else {
        d.substrate = c0.substrate ?? 'N-BK7'
        d.targets = [tg('R', '<=', 0.005, mean), tg('R', '<=', 0.015, p95, 0.5)]
      }
      replaceDesign(d, `New coating design for surface ${surfaces.join(', ')}`)
    } catch (e) {
      toast('error', (e as Error).message)
    }
  }

  // a coating or surfaces handed over by another view (editor, inspector, Coatings view): open once, then clear
  const handled = useRef<unknown>(null)
  useEffect(() => {
    // once per hand-over (an effect may run twice for one render in development)
    if (!arg || handled.current === arg) return
    handled.current = arg
    useUiStore.getState().set({ coatingArg: null })
    if (arg.coating) void openCoating(arg.coating)
    else if (arg.surfaces?.length) void designForSurfaces(arg.surfaces)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [arg])
  // the library rail sits beside the designer from 1600 px; on narrower windows it floats over it and closes after a pick
  const railFloats = useWindowWidth() < RAIL_SIDE_BY_SIDE
  const [rail, setRail] = useState(() => typeof window === 'undefined' || window.innerWidth >= RAIL_SIDE_BY_SIDE)
  const pick = (fn: () => void) => {
    fn()
    if (railFloats) setRail(false)
  }

  const sourceExists = !!design.source_coating && !!coatingOf(project.system, design.source_coating)
  const saveToProject = async (mode: 'new' | 'update') => {
    if (!design.layers.length) return
    try {
      const taken = [...builtins.map((c) => c.name), ...projectCoatings.map((c) => c.name.toUpperCase())]
      const name = mode === 'update' && design.source_coating ? design.source_coating.toUpperCase() : uniqueCoatingName(design.name, taken)
      const snap = designSnapshot()
      const cd: CoatingDefinition = await api.cdExportCoating({ design, custom_materials: custom, name })
      if (!sameProject(snap)) return toast('warning', t('c.staleProject'))
      // the surfaces it was designed for, by index: only while the surface list is the one it was opened with
      if (forSurfaces.length && !sameDesign(snap)) return toast('warning', t('c.staleDesign'))
      update((p) => {
        const list = (p.system.custom_coatings ??= [])
        const k = list.findIndex((c) => c.name.trim().toUpperCase() === cd.name)
        if (k >= 0) list[k] = cd
        else list.push(cd)
        for (const j of forSurfaces) if (p.system.surfaces[j]) p.system.surfaces[j].coating = cd.name
        const d = p.analysis_settings.coating_design as CoatingDesignSpec | undefined
        if (d) d.source_coating = cd.name
      }, mode === 'update' ? `Update coating ${cd.name}` : `Save coating ${cd.name}`)
      toast('success', `${cd.name} ${t('cd.savedCoating')}${forSurfaces.length ? ` · ${t('cd.assignedTo')} ${forSurfaces.join(', ')}` : ''}`)
    } catch (e) {
      toast('error', (e as Error).message)
    }
  }
  const key = JSON.stringify(design)
  const [ev, setEv] = useState<CoatingEvaluation | null>(null)
  const [evErr, setEvErr] = useState<string | null>(null)
  const [viewAngle, setViewAngle] = useState(0)
  useEffect(() => {
    const ctrl = new AbortController()
    const h = setTimeout(() => {
      api
        .cdEvaluate({ design, custom_materials: custom, angle_deg: viewAngle }, ctrl.signal)
        .then((r) => (setEv(r), setEvErr(null)))
        .catch((e) => (e as Error).name !== 'AbortError' && setEvErr((e as Error).message))
    }, 180)
    return () => {
      clearTimeout(h)
      ctrl.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, custom, viewAngle])

  const [tab, setTab] = useState<'spectrum' | 'targets' | 'angle' | 'analysis' | 'measure' | 'tolerance' | 'recipe'>('spectrum')
  const [busy, setBusy] = useState<string | null>(null)
  const [opt, setOpt] = useState<CoatingOptimizeResult | null>(null)
  const [timeLimit, setTimeLimit] = useState(30)

  const runOpt = async (method: 'refine' | 'needle') => {
    if (!design.targets.length) return toast('error', t('cd.needTargets'))
    if (!design.layers.length) return toast('error', t('cd.needLayers'))
    setBusy(method)
    try {
      const r = await api.cdOptimize({ design, custom_materials: custom, method, time_limit_s: timeLimit })
      setOpt(r)
      if (r.final_merit < r.initial_merit) {
        setDesign((d) => {
          d.layers = r.design.layers
        }, method === 'needle' ? 'Needle optimisation of the coating' : 'Refine the coating')
        toast('success', `${t('cd.merit')} ${fmt(r.initial_merit * 100, 4)} → ${fmt(r.final_merit * 100, 4)} % · ${r.design.layers.length} ${t('cd.layersShort')} (${t('cd.undoHint')})`)
      } else toast('info', t('cd.noImprovement'))
    } catch (e) {
      toast('error', (e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="relative flex min-h-0 min-w-0 flex-1 bg-panel">
      {rail && (
        <CoatingLibraryRail
          floating={railFloats}
          onClose={() => setRail(false)}
          onExample={(ex) =>
            pick(() => {
              replaceDesign(ex.design, `Open the example ${ex.name}`)
              setViewAngle(ex.design.targets[0]?.angle_deg ?? 0)
              toast('info', `${ex.name}: ${t('cs.exampleOpened')}`)
            })
          }
          current={(design.source_coating || design.name || '').toUpperCase()}
          onOpen={(n) => pick(() => void openCoating(n))}
          onSurface={(i) => pick(() => void designForSurfaces([i]))}
        />
      )}
      <div className="grid min-h-0 min-w-0 flex-1 grid-cols-[300px_minmax(0,1fr)_340px]">
        <div className="min-h-0 overflow-auto border-r border-line">
          <div className="space-y-1 border-b border-line p-2">
            <div className="flex items-center gap-1">
              <IconButton title={t('cs.libraryHint')} active={rail} aria-pressed={rail} onClick={() => setRail(!rail)}>
                <Library size={14} />
              </IconButton>
              <span className="text-small text-muted">{t('cd.openDesign')}</span>
              <span className="min-w-0 flex-1">
                <Select
                  className="w-full"
                  ariaLabel={t('cd.openDesign')}
                  value={sourceExists ? design.source_coating!.toUpperCase() : ''}
                  options={[{ value: '', label: t('cd.workingDesign') }, ...projectCoatings.map((c) => ({ value: c.name.toUpperCase(), label: `${c.name.toUpperCase()}${c.design ? '' : ' (layers only)'}` }))]}
                  onChange={(v) => (v ? void openCoating(v) : setDesign((d) => void (d.source_coating = ''), 'Detach the design from its coating'))}
                />
              </span>
            </div>
            {forSurfaces.length > 0 && (
              <div className="rounded border border-accent/40 bg-accent/5 px-2 py-1 text-small leading-snug text-muted">
                <b className="text-fg">{t('cd.forSurfaces')} {forSurfaces.join(', ')}</b>
                {ctx.map((c) => (
                  <div key={c.surface}>
                    S{c.surface}: {c.is_mirror ? t('cd.mirrorIn') : `${c.incident} | ${c.substrate}`} {c.angles_deg ? `· ${fmt(c.angles_deg.min, 3)}–${fmt(c.angles_deg.max, 3)}° (${t('cd.meanAngle')} ${fmt(c.angles_deg.mean, 3)}°, ${c.angles_in_medium})` : ''}
                    {c.light_from === 'substrate' ? ` · ${t('cd.fromGlass')}` : ''}
                    {c.tir_fraction ? ` · TIR ${fmt(c.tir_fraction * 100, 3)} %` : ''}
                  </div>
                ))}
                {ctx.some((c) => c.substrate !== ctx[0].substrate || c.incident !== ctx[0].incident) && <div className="text-warn">{t('cd.mixedMedia')}</div>}
                {ctx.some((c) => c.is_mirror) && design.substrate_index !== null && design.substrate_index !== undefined && <div className="text-warn">{t('cd.metalPlaceholder')}</div>}
              </div>
            )}
          </div>
          <SetupPanel design={design} setDesign={setDesign} matNames={matNames} />
          <TemplatePanel design={design} setDesign={setDesign} custom={custom} />
          <TargetsPanel design={design} setDesign={setDesign} ev={ev} />
        </div>

        <div className="flex min-h-0 flex-col">
          <Tabs
            value={tab}
            onChange={setTab}
            tabs={[
              { id: 'spectrum', label: t('cd.tabSpectrum') },
              { id: 'targets', label: t('cs.tabTargets') },
              { id: 'angle', label: t('cd.tabAngle') },
              { id: 'analysis', label: t('cd.tabAnalysis') },
              { id: 'measure', label: t('cs.tabMeasure') },
              { id: 'tolerance', label: t('cd.tabTolerance') },
              { id: 'recipe', label: t('cd.tabRecipe') },
            ]}
            right={
              ev && (
                <span className="text-small text-muted">
                  {ev.layer_count} {t('cd.layersShort')} · {fmt(ev.total_thickness_nm, 5)} nm{ev.merit !== null && ` · ${t('cd.merit')} ${fmt(ev.merit * 100, 4)} %`}
                </span>
              )
            }
          />
          {evErr && <div className="border-b border-line px-3 py-1 text-small text-danger">{evErr}</div>}
          {ev?.warnings.map((w) => (
            <div key={w} className="border-b border-line px-3 py-1 text-small text-warn">
              {w}
            </div>
          ))}
          <div className="min-h-0 flex-1">
            {tab === 'spectrum' && <SpectrumTab design={design} ev={ev} angle={viewAngle} setAngle={setViewAngle} />}
            {tab === 'angle' && <AngleTab design={design} />}
            {tab === 'targets' && <TargetsTab design={design} ev={ev} />}
            {tab === 'analysis' && <AnalysisTab design={design} />}
            {tab === 'measure' && <MeasureTab design={design} setDesign={setDesign} />}
            {tab === 'tolerance' && <ToleranceTab design={design} />}
            {tab === 'recipe' && <RecipeTab design={design} />}
          </div>
        </div>

        <div className="flex min-h-0 flex-col border-l border-line">
          <div className="flex flex-wrap items-center gap-1.5 border-b border-line p-2">
            <Button size="sm" variant="primary" disabled={!!busy} onClick={() => runOpt('refine')} title={t('cd.refineHint')}>
              {busy === 'refine' ? <Spinner size={12} /> : <Wand2 size={12} />} {t('cd.refine')}
            </Button>
            <Button size="sm" disabled={!!busy} onClick={() => runOpt('needle')} title={t('cd.needleHint')}>
              {busy === 'needle' ? <Spinner size={12} /> : <Sparkles size={12} />} {t('cd.needle')}
            </Button>
            <span className="text-small text-muted" title={t('cd.timeHint')}>
              ≤
            </span>
            <NumberField className="h-6 w-12" value={timeLimit} min={1} max={300} onCommit={(v) => setTimeLimit(v ?? 30)} ariaLabel={t('cd.timeHint')} />
            <span className="text-small text-muted">s</span>
          </div>
          <div className="flex flex-wrap items-center gap-1.5 border-b border-line p-2">
            {sourceExists && (
              <Button size="sm" variant="primary" disabled={!design.layers.length} onClick={() => saveToProject('update')} title={t('cd.updateHint')}>
                <Save size={12} /> {t('cd.update')} {design.source_coating!.toUpperCase()}
              </Button>
            )}
            <Button size="sm" variant={sourceExists ? 'default' : 'primary'} disabled={!design.layers.length} onClick={() => saveToProject('new')} title={t('cd.saveCoatingHint')}>
              <Save size={12} /> {sourceExists ? t('cd.saveNew') : t('cd.saveCoating')}
            </Button>
            {forSurfaces.length > 0 && <span className="text-caption text-faint">→ {t('cd.assignedTo')} {forSurfaces.join(', ')}</span>}
          </div>
          {opt && (
            <div className="border-b border-line px-3 py-1.5 text-small text-muted">
              {opt.history.map((h) => `${h.step} ${fmt(h.merit * 100, 3)} % (${h.layers})`).join(' → ')}
              <div className="text-faint">
                {opt.status} · {opt.elapsed_s.toFixed(1)} s
              </div>
            </div>
          )}
          <LayersPanel design={design} setDesign={setDesign} ev={ev} />
        </div>
      </div>
    </div>
  )
}

/** Library of the studio: project coatings, the built-in library by category, and the system's surfaces. */
function CoatingLibraryRail({ current, onOpen, onSurface, onExample, floating, onClose }: { current: string; onOpen: (name: string) => void; onSurface: (surface: number) => void; onExample: (ex: CoatingExample) => void; floating: boolean; onClose: () => void }) {
  const t = useT()
  const builtins = useEngineStore((s) => s.coatings)
  const [examples, setExamples] = useState<CoatingExample[]>([])
  useEffect(() => {
    api
      .coatingExamples()
      .then((r) => setExamples(r.examples))
      .catch(() => setExamples([]))
  }, [])
  const system = useProjectStore((s) => s.project.system)
  const projectCoatings = system.custom_coatings ?? []
  const [q, setQ] = useState('')
  const match = (name: string, desc = '') => !q.trim() || `${name} ${desc}`.toLowerCase().includes(q.trim().toLowerCase())
  const cats = new Map<string, typeof builtins>()
  for (const b of builtins) if (b.builtin) cats.set(b.category || 'Other', [...(cats.get(b.category || 'Other') ?? []), b])
  const surfaces = system.surfaces.map((sf, i) => ({ sf, i })).filter(({ sf, i }) => i > 0 && i < system.surfaces.length - 1 && sf.type !== 'coordinate_break' && sf.type !== 'ideal')
  const head = (text: string) => <div className="px-3 pt-3 pb-1 text-caption font-semibold tracking-wide text-faint uppercase">{text}</div>
  const row = (key: string, name: string, onClick: () => void, right: React.ReactNode, title?: string) => (
    <button key={key} className={cx('flex w-full items-center gap-2 px-3 py-1 text-left text-body hover:bg-hover', current === name.toUpperCase() && 'bg-select')} onClick={onClick} title={title}>
      <span className="min-w-0 flex-1 truncate">{name}</span>
      {right}
    </button>
  )
  return (
    <aside
      className={cx('flex w-[230px] shrink-0 flex-col border-r border-line bg-panel-2', floating && 'fade-in absolute inset-y-0 left-0 z-30 w-[260px] border-line-strong shadow-[var(--shadow)]')}
      aria-label={t('cs.library')}
      onKeyDown={(e) => floating && e.key === 'Escape' && onClose()}
    >
      <div className="flex items-center gap-1.5 border-b border-line px-2 py-1.5">
        <Search size={14} className="shrink-0 text-faint" />
        <TextField className="h-6 flex-1" value={q} placeholder={t('coat.search')} onCommit={setQ} ariaLabel={t('coat.search')} />
        {floating && (
          <IconButton title={`${t('c.close')} (Esc)`} onClick={onClose}>
            <X size={14} />
          </IconButton>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-auto pb-2">
        {head(t('coat.project'))}
        {projectCoatings.length === 0 && <div className="px-3 py-1 text-small text-faint">{t('coat.noneYet')}</div>}
        {projectCoatings.filter((c) => match(c.name, c.description)).map((c) => row(`p-${c.name}`, c.name.toUpperCase(), () => onOpen(c.name), <span className="num text-caption text-faint">{c.layers.length}L</span>, c.description))}
        {examples.length > 0 && head(t('cs.examples'))}
        {examples
          .filter((ex) => match(ex.name, ex.description))
          .map((ex) => (
            <button key={`e-${ex.id}`} className="flex w-full items-center gap-2 px-3 py-1 text-left text-body hover:bg-hover" onClick={() => onExample(ex)} title={ex.description}>
              <span className="min-w-0 flex-1 truncate">{ex.name}</span>
              {ex.contest_mf != null && <span className="num text-caption text-faint">MF {fmt(ex.contest_mf, 3)}</span>}
            </button>
          ))}
        {head(t('cs.surfaces'))}
        {surfaces.map(({ sf, i }) => (
          <button key={`s-${i}`} className="flex w-full items-center gap-2 px-3 py-1 text-left text-body hover:bg-hover" onClick={() => onSurface(i)} title={t('cd.designForHint')}>
            <span className="num w-7 shrink-0 text-caption text-faint">S{i}</span>
            <span className="min-w-0 flex-1 truncate">{sf.label || sf.material || '—'}</span>
            <span className={cx('truncate text-caption', sf.coating ? 'text-muted' : 'text-faint')}>{sf.coating || t('cs.uncoated')}</span>
          </button>
        ))}
        {[...cats.entries()].map(([cat, list]) => {
          const rows = list.filter((c) => match(c.name, c.description))
          if (!rows.length) return null
          return (
            <div key={cat}>
              {head(hasKey(`coat.cat.${cat}`) ? t(`coat.cat.${cat}`) : cat)}
              {rows.map((c) => row(`b-${c.name}`, c.name, () => onOpen(c.name), <span className="num text-caption text-faint">{c.angle_deg ? `${fmt(c.angle_deg, 3)}° · ` : ''}{c.layers.length}L</span>, c.description))}
            </div>
          )
        })}
      </div>
      <div className="border-t border-line p-2 text-caption leading-relaxed text-faint">{t('cs.libraryHelp')}</div>
    </aside>
  )
}

type SetDesign = (fn: (d: CoatingDesignSpec) => void, label: string) => void

function FormRow({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    // a <label>, so the row's (first) control is named by its label
    <label className="grid grid-cols-[104px_minmax(0,1fr)] items-center gap-2 px-3 py-0.5" title={hint}>
      <span className="truncate text-small text-muted">{label}</span>
      <span className="flex min-w-0 items-center gap-1">{children}</span>
    </label>
  )
}

function Head({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-t border-line bg-panel-2 px-3 py-1 text-caption font-semibold uppercase tracking-wide text-faint">
      <span>{children}</span>
      {right}
    </div>
  )
}

function SetupPanel({ design, setDesign, matNames }: { design: CoatingDesignSpec; setDesign: SetDesign; matNames: string[] }) {
  const t = useT()
  const metals = new Set(useEngineStore((s) => s.materials).filter((m) => m.category === 'metal').map((m) => m.name))
  const media = [{ value: 'AIR', label: 'AIR' }, ...matNames.filter((m) => !metals.has(m)).map((m) => ({ value: m, label: m }))]
  const setPal = (k: number, patch: Partial<PaletteMaterial>, label: string) => setDesign((d) => void Object.assign(d.palette[k], patch), label)
  const fixedSub = design.substrate_index !== null && design.substrate_index !== undefined
  const fixedInc = design.incident_index !== null && design.incident_index !== undefined
  return (
    <>
      <Head>{t('cd.setup')}</Head>
      <div className="py-1">
        <FormRow label={t('cd.name')}>
          <TextField className="w-full" value={design.name} onCommit={(v) => setDesign((d) => void (d.name = v || 'Coating design'), 'Coating design name')} />
        </FormRow>
        <FormRow label={t('cd.incident')}>
          <Select
            className="w-full"
            value={fixedInc ? '__fixed__' : design.incident.toUpperCase()}
            options={[...media, { value: '__fixed__', label: t('cd.fixedIncident') }]}
            onChange={(v) =>
              setDesign((d) => {
                if (v === '__fixed__') d.incident_index = d.incident_index ?? 1.5
                else {
                  d.incident = v
                  d.incident_index = null
                }
              }, 'Coating incident medium')
            }
          />
        </FormRow>
        {fixedInc && (
          <FormRow label="n₀" hint={t('cd.fixedIncidentHint')}>
            <NumberField className="w-full" value={design.incident_index ?? 1.5} min={1} max={10} ariaLabel="incident n" onCommit={(v) => setDesign((d) => void (d.incident_index = v ?? 1.5), 'Coating incident index')} />
          </FormRow>
        )}
        <FormRow label={t('cd.substrate')}>
          <Select
            className="w-full"
            value={fixedSub ? '__fixed__' : design.substrate.toUpperCase()}
            options={[...matNames.map((m) => ({ value: m, label: m })), { value: '__fixed__', label: t('cd.fixedSubstrate') }]}
            onChange={(v) =>
              setDesign((d) => {
                if (v === '__fixed__') {
                  d.substrate_index = d.substrate_index ?? 1.0
                  d.substrate_extinction = d.substrate_extinction || 6.0
                } else {
                  d.substrate = v
                  d.substrate_index = null
                  d.substrate_extinction = 0
                }
              }, 'Coating substrate')
            }
          />
        </FormRow>
        {fixedSub && (
          <FormRow label="n, k" hint={t('cd.fixedSubstrateHint')}>
            <NumberField className="w-full" value={design.substrate_index ?? 1} min={0.001} max={100} ariaLabel="substrate n" onCommit={(v) => setDesign((d) => void (d.substrate_index = v ?? 1), 'Coating substrate n')} />
            <NumberField className="w-full" value={design.substrate_extinction ?? 0} min={0} max={100} ariaLabel="substrate k" onCommit={(v) => setDesign((d) => void (d.substrate_extinction = v ?? 0), 'Coating substrate k')} />
          </FormRow>
        )}
        <FormRow label={t('cd.backSide')} hint={t('cd.backSideHint')}>
          <Select
            className="w-full"
            value={design.back_side}
            ariaLabel={t('cd.backSide')}
            options={[
              { value: 'none', label: t('cs.back.none') },
              { value: 'uncoated', label: t('cs.back.uncoated') },
              { value: 'coated', label: t('cs.back.coated') },
            ]}
            onChange={(v) =>
              setDesign((d) => {
                d.back_side = v as CoatingDesignSpec['back_side']
                if (v === 'coated' && !(d.back_layers ?? []).length && !d.back_same_as_front) d.back_same_as_front = true
              }, 'Coating back side')
            }
          />
        </FormRow>
        {design.back_side !== 'none' && (
          <FormRow label={t('cs.thickness')} hint={t('cs.thicknessHint')}>
            <NumberField
              className="w-full"
              optional
              placeholder="—"
              value={design.substrate_thickness_mm ?? null}
              min={0.001}
              max={1000}
              ariaLabel={t('cs.thickness')}
              onCommit={(v) => setDesign((d) => void (d.substrate_thickness_mm = v), 'Substrate thickness')}
            />
            <span className="text-small text-muted">mm</span>
          </FormRow>
        )}
        {design.back_side === 'coated' && <BackSideRow design={design} setDesign={setDesign} />}
        {!!design.substrate_offset && (
          <FormRow label="Δn" hint={t('cs.substrateOffsetHint')}>
            <NumberField className="w-full" value={design.substrate_offset ?? 0} min={-1} max={1} ariaLabel={t('cs.substrateOffsetHint')} onCommit={(v) => setDesign((d) => void (d.substrate_offset = v ?? 0), 'Substrate index correction')} />
          </FormRow>
        )}
        <FormRow label={`${t('cd.lambda0')} (nm)`} hint={t('cd.lambda0Hint')}>
          <NumberField className="w-full" value={design.design_wavelength_nm} min={100} max={50000} onCommit={(v) => setDesign((d) => void (d.design_wavelength_nm = v ?? 550), 'Coating design wavelength')} />
        </FormRow>
        <FormRow label={`${t('cd.thickRange')} (nm)`} hint={t('cd.thickRangeHint')}>
          <NumberField className="w-full" value={design.min_thickness_nm} min={0} max={1000} onCommit={(v) => setDesign((d) => void (d.min_thickness_nm = v ?? 0), 'Coating minimum thickness')} />
          <span className="text-faint">–</span>
          <NumberField className="w-full" value={design.max_thickness_nm} min={1} max={100000} onCommit={(v) => setDesign((d) => void (d.max_thickness_nm = v ?? 2000), 'Coating maximum thickness')} />
        </FormRow>
      </div>
      <Head
        right={
          <Button
            variant="link"
            disabled={design.palette.length >= 8}
            onClick={() =>
              setDesign((d) => {
                const used = new Set(d.palette.map((p) => p.key))
                const k = ['M', 'N', 'P', 'Q', 'X', 'Y', 'Z', 'W'].find((c) => !used.has(c)) ?? `M${d.palette.length}`
                d.palette.push({ key: k, label: '', material: '', index: 1.8, extinction: 0, tooling: 1, rate_nm_s: 0.5 })
              }, 'Add coating material')
            }
          >
            + {t('cd.addMaterial')}
          </Button>
        }
      >
        {t('cd.palette')}
      </Head>
      <div className="space-y-1 py-1">
        {design.palette.map((p, k) => {
          const used = design.layers.some((L) => L.material === p.key)
          return (
            <div key={k} className="mx-2 rounded border border-line/70 p-1.5">
              <div className="flex items-center gap-1">
                <span className="w-9">
                  <TextField
                    cell
                    value={p.key}
                    ariaLabel="material key"
                    onCommit={(v) => {
                      const nk = v.trim().slice(0, 12)
                      if (!nk || design.palette.some((x, j) => j !== k && x.key === nk)) return
                      setDesign((d) => {
                        for (const L of d.layers) if (L.material === d.palette[k].key) L.material = nk
                        d.palette[k].key = nk
                      }, 'Rename coating material')
                    }}
                  />
                </span>
                <span className="min-w-0 flex-1">
                  <Select cell value={p.material} ariaLabel="material source" options={[{ value: '', label: t('coat.fixedIndex') }, ...matNames.map((m) => ({ value: m, label: m }))]} onChange={(v) => setPal(k, { material: v }, 'Coating material source')} />
                </span>
                <IconButton size="sm" tone="danger" title={used ? t('cd.materialInUse') : t('c.remove')} disabled={used || design.palette.length <= 1} onClick={() => setDesign((d) => void d.palette.splice(k, 1), 'Remove coating material')}>
                  <Trash2 size={12} />
                </IconButton>
              </div>
              <div className="mt-1 grid grid-cols-4 gap-1 text-caption text-faint">
                <label title={p.material ? t('cd.nFromMaterial') : 'n'}>
                  n
                  {p.material ? <div className="py-0.5 text-muted">n(λ)</div> : <NumberField cell value={p.index} min={0.01} max={10} ariaLabel="index" onCommit={(v) => setPal(k, { index: v ?? 1.46 }, 'Coating material index')} />}
                </label>
                <label title="k (N = n − ik)">
                  k
                  <NumberField cell value={p.extinction} min={0} max={50} ariaLabel="extinction" onCommit={(v) => setPal(k, { extinction: v ?? 0 }, 'Coating material extinction')} />
                </label>
                <label title={t('cd.toolingHint')}>
                  {t('cd.tooling')}
                  <NumberField cell value={p.tooling} min={0.01} max={10} ariaLabel="tooling" onCommit={(v) => setPal(k, { tooling: v ?? 1 }, 'Coating tooling factor')} />
                </label>
                <label title={t('cd.rateHint')}>
                  nm/s
                  <NumberField cell value={p.rate_nm_s} min={0.001} max={100} ariaLabel="rate" onCommit={(v) => setPal(k, { rate_nm_s: v ?? 0.5 }, 'Coating deposition rate')} />
                </label>
              </div>
              {(!!p.index_offset || !!p.index_offset_b) && (
                <div className="mt-1 grid grid-cols-4 gap-1 text-caption text-faint" title={t('cs.offsetHint')}>
                  <label>
                    Δn
                    <NumberField cell value={p.index_offset ?? 0} min={-1} max={1} ariaLabel="index offset" onCommit={(v) => setPal(k, { index_offset: v ?? 0 }, 'Coating index correction')} />
                  </label>
                  <label>
                    ΔB µm²
                    <NumberField cell value={p.index_offset_b ?? 0} min={-1} max={1} ariaLabel="dispersion offset" onCommit={(v) => setPal(k, { index_offset_b: v ?? 0 }, 'Coating dispersion correction')} />
                  </label>
                  <span className="col-span-2 self-end text-faint">{t('cs.fromFit')}</span>
                </div>
              )}
            </div>
          )
        })}
        <div className="px-3 text-caption leading-snug text-faint">{t('cd.paletteNote')}</div>
      </div>
    </>
  )
}

function TemplatePanel({ design, setDesign, custom }: { design: CoatingDesignSpec; setDesign: SetDesign; custom: MaterialRecord[] }) {
  const t = useT()
  const toast = useUiStore((s) => s.toast)
  const keys = design.palette.map((p) => p.key)
  const [kind, setKind] = useState<CoatingTemplateKind>('longpass')
  const [high, setHigh] = useState(keys[0] ?? 'H')
  const [low, setLow] = useState(keys[1] ?? keys[0] ?? 'L')
  const [pairs, setPairs] = useState(10)
  const [cavities, setCavities] = useState(1)
  const [lam0, setLam0] = useState(design.design_wavelength_nm)
  const [edge, setEdge] = useState(600)
  const tMin = design.targets.length ? Math.min(...design.targets.map((x) => x.lambda_min_nm)) : 450
  const tMax = design.targets.length ? Math.max(...design.targets.map((x) => x.lambda_max_nm)) : 650
  const [bmin, setBmin] = useState(Math.round(tMin))
  const [bmax, setBmax] = useState(Math.round(tMax))
  const [keep, setKeep] = useState(design.targets.length > 0)
  const [busy, setBusy] = useState(false)
  const needs = TEMPLATES.find((x) => x.value === kind)!.needs
  const generate = async () => {
    setBusy(true)
    try {
      const r = await api.cdTemplate({
        design,
        custom_materials: custom,
        kind,
        high,
        low,
        pairs,
        cavities,
        lambda0_nm: needs.includes('lambda0') ? lam0 : null,
        edge_nm: needs.includes('edge') ? edge : null,
        band_min_nm: needs.includes('band') && kind !== 'bandpass' ? bmin : kind === 'bandpass' ? lam0 - (bmax - bmin) / 2 : null,
        band_max_nm: needs.includes('band') && kind !== 'bandpass' ? bmax : kind === 'bandpass' ? lam0 + (bmax - bmin) / 2 : null,
      })
      setDesign((d) => {
        d.layers = r.design.layers
        if (!(keep && d.targets.length)) {
          d.targets = r.design.targets
          d.design_wavelength_nm = r.design.design_wavelength_nm
        }
      }, `Coating start design: ${kind}`)
      toast('success', `${TEMPLATES.find((x) => x.value === kind)!.label}: ${r.design.layers.length} ${t('cd.layersShort')}. ${r.notes.join(' ')}`)
    } catch (e) {
      toast('error', (e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const kOpts = keys.map((k) => ({ value: k, label: k }))
  return (
    <>
      <Head>{t('cd.start')}</Head>
      <div className="py-1">
        <FormRow label={t('cd.kind')}>
          <Select className="w-full" value={kind} options={TEMPLATES.map((x) => ({ value: x.value, label: x.label }))} onChange={setKind} />
        </FormRow>
        <FormRow label={t('cd.highLow')}>
          <Select className="w-full" value={keys.includes(high) ? high : keys[0]} options={kOpts} onChange={setHigh} ariaLabel="high-index material" />
          <Select className="w-full" value={keys.includes(low) ? low : (keys[1] ?? keys[0])} options={kOpts} onChange={setLow} ariaLabel="low-index material" />
        </FormRow>
        {needs.includes('lambda0') && (
          <FormRow label={kind === 'bandpass' ? `${t('cd.centre')} (nm)` : `λ₀ (nm)`}>
            <NumberField className="w-full" value={lam0} min={100} max={50000} onCommit={(v) => setLam0(v ?? 550)} />
          </FormRow>
        )}
        {needs.includes('edge') && (
          <FormRow label={`${t('cd.edge')} (nm)`} hint={t('cd.edgeHint')}>
            <NumberField className="w-full" value={edge} min={100} max={50000} onCommit={(v) => setEdge(v ?? 600)} />
          </FormRow>
        )}
        {needs.includes('band') && (
          <FormRow label={kind === 'bandpass' ? `${t('cd.bandwidth')} (nm)` : `${t('cd.band')} (nm)`} hint={kind === 'bandpass' ? t('cd.bandwidthHint') : undefined}>
            {kind === 'bandpass' ? (
              <NumberField className="w-full" value={bmax - bmin} min={0.1} max={10000} onCommit={(v) => (setBmin(0), setBmax(v ?? 10))} />
            ) : (
              <>
                <NumberField className="w-full" value={bmin} min={100} max={50000} onCommit={(v) => setBmin(v ?? 450)} />
                <span className="text-faint">–</span>
                <NumberField className="w-full" value={bmax} min={100} max={50000} onCommit={(v) => setBmax(v ?? 650)} />
              </>
            )}
          </FormRow>
        )}
        {needs.includes('pairs') && (
          <FormRow label={kind === 'longpass' || kind === 'shortpass' ? t('cd.periods') : t('cd.pairs')}>
            <NumberField className="w-full" value={pairs} integer min={1} max={60} onCommit={(v) => setPairs(v ?? 10)} />
            {needs.includes('cavities') && (
              <>
                <span className="text-small text-muted">{t('cd.cavities')}</span>
                <NumberField className="w-full" value={cavities} integer min={1} max={5} onCommit={(v) => setCavities(v ?? 1)} />
              </>
            )}
          </FormRow>
        )}
        <div className="flex items-center justify-end gap-2 px-3 pt-1">
          {design.targets.length > 0 && <Checkbox checked={keep} onChange={setKeep} label={<span className="text-small text-muted">{t('cd.keepTargets')}</span>} />}
          <Button size="sm" onClick={generate} disabled={busy || keys.length < 2}>
            {busy ? <Spinner size={12} /> : <FlaskConical size={12} />} {t('cd.generate')}
          </Button>
        </div>
        <div className="px-3 pt-1 text-caption leading-snug text-faint">{t('cd.startNote')}</div>
      </div>
    </>
  )
}

function TargetsPanel({ design, setDesign, ev }: { design: CoatingDesignSpec; setDesign: SetDesign; ev: CoatingEvaluation | null }) {
  const t = useT()
  const setT = (k: number, patch: Partial<CoatingTarget>, label = 'Edit coating target') => setDesign((d) => void Object.assign(d.targets[k], patch), label)
  return (
    <>
      <Head right={<Button variant="link" onClick={() => setDesign((d) => void d.targets.push(defaultTarget(d.design_wavelength_nm)), 'Add coating target')}>+ {t('cd.addTarget')}</Button>}>
        {t('cd.targets')} ({design.targets.length})
      </Head>
      <div className="space-y-1 py-1">
        {design.targets.length === 0 && <div className="px-3 text-small text-faint">{t('cd.noTargets')}</div>}
        {design.targets.map((tg, k) => {
          const b = ev?.targets[k]
          const q = tg.quantity
          const frac = isFraction(q)
          const colour = COLOUR_Q.includes(q)
          const u = quantityUnits(q)
          return (
            <div key={k} className={cx('mx-2 rounded border p-1.5', b ? (b.met ? 'border-ok/50' : 'border-warn/60') : 'border-line/70')}>
              <div className="flex items-center gap-1">
                <span className="w-[72px]" title={t(`cs.q.${q}`)}>
                  <Select cell value={q} ariaLabel="quantity" options={QUANTITIES.map((x) => ({ value: x, label: hasKey(`cs.qShort.${x}`) ? t(`cs.qShort.${x}`) : x }))} onChange={(v) => setDesign((d) => void (d.targets[k] = retarget(d.targets[k], v as CoatingQuantity)), 'Change coating target quantity')} />
                </span>
                {hasOf(q) && (
                  <span className="w-11" title={t('cs.ofHint')}>
                    <Select cell value={tg.of ?? 'R'} ariaLabel={t('cs.ofHint')} options={[{ value: 'R', label: 'R' }, { value: 'T', label: 'T' }]} onChange={(v) => setT(k, { of: v as 'R' | 'T' })} />
                  </span>
                )}
                <span className="w-11">
                  <Select cell value={tg.kind} ariaLabel="comparison" options={[{ value: '>=', label: '≥' }, { value: '<=', label: '≤' }, { value: '=', label: '=' }]} onChange={(v) => setT(k, { kind: v })} />
                </span>
                {tg.table?.length ? (
                  <span className="text-caption text-faint" title={t('cs.tableHint')}>
                    {t('cs.tableShort')}
                  </span>
                ) : (
                  <>
                    <span className="w-16">
                      <NumberField cell value={shownValue(q, tg.value)} min={frac ? 0 : -1e6} max={frac ? 100 : 1e6} ariaLabel={`target ${u}`} onCommit={(v) => setT(k, { value: storedValue(q, v ?? 0) })} />
                    </span>
                    <span className="text-caption text-faint">{u}</span>
                  </>
                )}
                <span className="flex-1" />
                {b && <Badge tone={b.met ? 'ok' : 'warn'}>{b.met ? t('cd.met') : `${fmt(shownValue(q, b.max_violation), 3)}${u ? ` ${u}` : ''}`}</Badge>}
                {!colour && <TableImport onTable={(table) => setT(k, { table }, 'Coating target from a table')} fraction={frac} />}
                <IconButton size="sm" tone="danger" title={t('c.remove')} onClick={() => setDesign((d) => void d.targets.splice(k, 1), 'Remove coating target')}>
                  <Trash2 size={12} />
                </IconButton>
              </div>
              {tg.table?.length ? (
                <div className="mt-1 flex items-center gap-1 text-caption text-faint">
                  <span className="min-w-0 flex-1 truncate" title={t('cs.tableHint')}>
                    {t('cs.tablePoints', { n: tg.table.length })} · {fmt(tg.table[0][0], 5)}–{fmt(tg.table[tg.table.length - 1][0], 5)} nm
                  </span>
                  <Button variant="link" onClick={() => setT(k, { table: null }, 'Coating target: no table')}>
                    {t('cs.tableRemove')}
                  </Button>
                </div>
              ) : colour ? (
                <div className="mt-1 flex items-center gap-1 text-caption text-faint">
                  <span className="min-w-0 flex-1 truncate">{t('cs.colourRange2')}</span>
                  <span className="w-14">
                    <Select cell value={tg.illuminant ?? 'D65'} ariaLabel={t('ca.illuminant')} options={['D65', 'D50', 'D55', 'D75', 'A', 'C', 'F2', 'F7', 'F11'].map((x) => ({ value: x, label: x }))} onChange={(v) => setT(k, { illuminant: v as CoatingIlluminant })} />
                  </span>
                  <span className="w-12">
                    <Select cell value={tg.observer ?? '2'} ariaLabel={t('ca.observer')} options={[{ value: '2', label: '2°' }, { value: '10', label: '10°' }]} onChange={(v) => setT(k, { observer: v as '2' | '10' })} />
                  </span>
                </div>
              ) : (
                <div className="mt-1 grid grid-cols-[1fr_auto_1fr] items-center gap-1">
                  <NumberField cell value={tg.lambda_min_nm} min={50} max={50000} ariaLabel="lambda min" onCommit={(v) => setT(k, { lambda_min_nm: v ?? 400, lambda_max_nm: Math.max(v ?? 400, tg.lambda_max_nm) })} />
                  <span className="text-caption text-faint">– nm –</span>
                  <NumberField cell value={tg.lambda_max_nm} min={50} max={50000} ariaLabel="lambda max" onCommit={(v) => setT(k, { lambda_max_nm: v ?? 700, lambda_min_nm: Math.min(v ?? 700, tg.lambda_min_nm) })} />
                </div>
              )}
              <div className="mt-1 grid grid-cols-5 gap-1 text-caption text-faint">
                <label title={t('cd.angleHint')}>
                  °
                  <NumberField cell value={tg.angle_deg} min={0} max={89.9} ariaLabel="angle" onCommit={(v) => setT(k, { angle_deg: v ?? 0 })} />
                </label>
                <label>
                  pol
                  <Select cell value={tg.polarization} ariaLabel="polarisation" options={[{ value: 'avg', label: 'avg' }, { value: 's', label: 's' }, { value: 'p', label: 'p' }]} onChange={(v) => setT(k, { polarization: v })} />
                </label>
                <label title={t('cd.tolHint')}>
                  ±{u}
                  <NumberField cell value={shownValue(q, tg.tolerance)} min={0} max={frac ? 100 : 1e6} ariaLabel="tolerance" onCommit={(v) => setT(k, { tolerance: storedValue(q, v ?? 0) })} />
                </label>
                <label title={t('cd.weightHint')}>
                  w
                  <NumberField cell value={tg.weight} min={0} max={1e6} ariaLabel="weight" onCommit={(v) => setT(k, { weight: v ?? 1 })} />
                </label>
                <label title={tg.table?.length ? t('cs.tableHint') : t('cd.pointsHint')}>
                  pts
                  {tg.table?.length ? <div className="num py-0.5 text-body text-muted">{tg.table.length}</div> : <NumberField cell value={tg.points} integer min={1} max={801} ariaLabel="points" onCommit={(v) => setT(k, { points: v ?? 41 })} />}
                </label>
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}

function LayersPanel({ design, setDesign, ev }: { design: CoatingDesignSpec; setDesign: SetDesign; ev: CoatingEvaluation | null }) {
  const t = useT()
  const keys = design.palette.map((p) => p.key)
  const [thin, setThin] = useState(5)
  const custom = useProjectStore((s) => s.project.custom_materials)
  const toast = useUiStore((s) => s.toast)
  const applyFormula = async (formula: string) => {
    if (!formula.trim() || formula.trim() === (ev?.formula ?? '')) return
    try {
      const r = await api.cdFormula({ design, custom_materials: custom, formula })
      setDesign((d) => void (d.layers = r.design.layers), `Layers from the formula ${r.formula}`)
      toast('success', `${r.layer_count} ${t('cd.layersShort')}: ${r.formula}`)
    } catch (e) {
      toast('error', (e as Error).message)
    }
  }
  const addLayer = (at: number) =>
    setDesign((d) => {
      const prev = d.layers[at - 1]?.material
      const k = d.palette.find((p) => p.key !== prev)?.key ?? d.palette[0].key
      const pal = d.palette.find((p) => p.key === k)!
      d.layers.splice(at, 0, { material: k, thickness_nm: Math.round(d.design_wavelength_nm / (4 * (pal.material ? 1.6 : pal.index))), locked: false })
    }, 'Add coating layer')
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Head right={<span className="normal-case">{t('cd.depositionOrder')}</span>}>
        <Layers size={12} className="mr-1 inline" />
        {t('cd.layers')} ({design.layers.length})
      </Head>
      <div className="flex items-center gap-1.5 border-b border-line px-2 py-1.5" title={t('cs.formulaHint')}>
        <span className="text-small text-muted">{t('cs.formula')}</span>
        <TextField className="h-6 min-w-0 flex-1 font-mono text-small" value={ev?.formula ?? ''} placeholder="(HL)^7 H" onCommit={(v) => void applyFormula(v)} ariaLabel={t('cs.formula')} />
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="eng-table">
          <thead>
            <tr>
              <th className="w-8 text-right">#</th>
              <th>{t('coat.material')}</th>
              <th className="text-right">nm</th>
              <th className="text-right" title={t('cd.qwotHint')}>
                QWOT
              </th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="px-2 text-right text-faint">—</td>
              <td colSpan={4} className="px-2 text-small text-faint">
                {design.substrate_index != null ? `N = ${fmt(design.substrate_index, 6)}${design.substrate_extinction ? ` − ${fmt(design.substrate_extinction, 4)}i` : ''}` : design.substrate} ({t('cd.substrate').toLowerCase()})
              </td>
            </tr>
            {design.layers.map((L, i) => (
              <tr key={i}>
                <td className="num px-2 text-right text-muted">{i + 1}</td>
                <td className="px-1">
                  <Select cell value={L.material} ariaLabel={`${t('cd.layer')} ${i + 1}: ${t('coat.material')}`} options={keys.map((k) => ({ value: k, label: k }))} onChange={(v) => setDesign((d) => void (d.layers[i].material = v), 'Coating layer material')} />
                </td>
                <td className="px-1 text-right">
                  <NumberField cell value={L.thickness_nm} min={0} max={100000} format={(v) => (v === null ? '' : v.toFixed(2))} ariaLabel={`${t('cd.layer')} ${i + 1}: ${t('cd.thickness')}`} onCommit={(v) => setDesign((d) => void (d.layers[i].thickness_nm = v ?? 0), 'Coating layer thickness')} />
                </td>
                <td className="num px-2 text-right text-muted">{ev?.layers[i] ? fmt(ev.layers[i].qwot, 4) : '—'}</td>
                <td className="whitespace-nowrap px-1 text-right">
                  <IconButton size="sm" active={L.locked} aria-pressed={L.locked} title={t('cd.lockHint')} onClick={() => setDesign((d) => void (d.layers[i].locked = !d.layers[i].locked), 'Lock coating layer')}>
                    {L.locked ? <Lock size={12} /> : <Unlock size={12} />}
                  </IconButton>
                  <IconButton size="sm" title={t('cd.insertAbove')} onClick={() => addLayer(i + 1)}>
                    <Plus size={12} />
                  </IconButton>
                  <IconButton size="sm" tone="danger" title={t('c.remove')} onClick={() => setDesign((d) => void d.layers.splice(i, 1), 'Remove coating layer')}>
                    <Trash2 size={12} />
                  </IconButton>
                </td>
              </tr>
            ))}
            <tr>
              <td className="px-2 text-right text-faint">—</td>
              <td colSpan={4} className="px-2 text-small text-faint">
                {design.incident_index != null ? `n ${fmt(design.incident_index, 6)}` : design.incident} ({t('cd.incident').toLowerCase()})
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 border-t border-line p-2">
        <Button size="sm" variant="ghost" onClick={() => addLayer(design.layers.length)}>
          <Plus size={12} /> {t('cd.addLayer')}
        </Button>
        <span className="flex-1" />
        <Button size="sm" variant="ghost" title={t('cd.removeThinHint')} onClick={() => setDesign((d) => void (d.layers = removeThinLayers(d.layers, thin)), 'Remove thin coating layers')}>
          {t('cd.removeThin')}
        </Button>
        <NumberField className="h-6 w-12" value={thin} min={0} max={100} onCommit={(v) => setThin(v ?? 5)} ariaLabel="thin layer limit" />
        <span className="text-small text-muted">nm</span>
      </div>
    </div>
  )
}

function SpectrumTab({ design, ev, angle, setAngle }: { design: CoatingDesignSpec; ev: CoatingEvaluation | null; angle: number; setAngle: (v: number) => void }) {
  const t = useT()
  const [showA, setShowA] = useState(false)
  // polarised R/T/A targets: show the s and p curves they are compared with
  const polarised = design.targets.some((g) => g.polarization !== 'avg' && ['R', 'T', 'A'].includes(g.quantity))
  const [sp, setSp] = useState(polarised)
  const [wasPolarised, setWasPolarised] = useState(polarised)
  if (polarised !== wasPolarised) {
    setWasPolarised(polarised)
    if (polarised) setSp(true)
  }
  const [ymode, setYmode] = useState<'pct' | 'log' | 'od'>('pct')
  if (!ev) return <div className="flex h-full items-center justify-center text-faint">{design.layers.length ? <Spinner /> : t('cd.empty')}</div>
  const x = ev.lambda_nm
  // optical density OD = -log10(fraction): blocking depth of a filter
  const Y = (a: number[]) => (ymode === 'od' ? a.map((v) => -Math.log10(Math.max(v, 1e-12))) : a.map((v) => (ymode === 'log' ? Math.max(v * 100, 1e-8) : v * 100)))
  const traces: Trace[] = [
    { type: 'scatter', mode: 'lines', x, y: Y(ev.spectrum.T), name: ymode === 'od' ? 'OD (T)' : 'T', line: { color: DATA.primary, width: 1.8 } },
  ]
  if (ymode !== 'od') traces.push({ type: 'scatter', mode: 'lines', x, y: Y(ev.spectrum.R), name: 'R', line: { color: DATA.secondary, width: 1.8 } })
  if (showA && ymode !== 'od') traces.push({ type: 'scatter', mode: 'lines', x, y: Y(ev.spectrum.A), name: 'A', line: { color: DATA.quaternary, width: 1.4 } })
  if (sp && angle > 0) {
    traces.push({ type: 'scatter', mode: 'lines', x, y: Y(ev.spectrum.Ts), name: 'Ts', line: { color: DATA.primary, width: 1, dash: 'dot' } })
    traces.push({ type: 'scatter', mode: 'lines', x, y: Y(ev.spectrum.Tp), name: 'Tp', line: { color: DATA.primary, width: 1, dash: 'dash' } })
    if (ymode !== 'od') {
      traces.push({ type: 'scatter', mode: 'lines', x, y: Y(ev.spectrum.Rs), name: 'Rs', line: { color: DATA.secondary, width: 1, dash: 'dot' } })
      traces.push({ type: 'scatter', mode: 'lines', x, y: Y(ev.spectrum.Rp), name: 'Rp', line: { color: DATA.secondary, width: 1, dash: 'dash' } })
    }
  }
  design.targets.forEach((tg, k) => {
    const b = ev.targets[k]
    if (!b || !['R', 'T', 'A'].includes(tg.quantity) || (ymode === 'od' && tg.quantity !== 'T')) return
    const same = Math.abs(tg.angle_deg - angle) < 1e-9
    traces.push({
      type: 'scatter',
      mode: b.lambda_nm.length === 1 ? 'markers' : 'lines',
      x: b.lambda_nm,
      y: Y(b.target),
      name: `${tg.quantity}${tg.polarization === 'avg' ? '' : tg.polarization} ${tg.kind} ${tg.table?.length ? t('cs.tableShort') : `${fmt(tg.value * 100, 4)} %`}${tg.angle_deg ? ` @${fmt(tg.angle_deg, 3)}°` : ''}`,
      line: { color: tg.quantity === 'T' ? DATA.primary : tg.quantity === 'R' ? DATA.secondary : DATA.quaternary, width: 3, dash: tg.kind === '=' ? 'solid' : 'dot' },
      marker: { size: 8, symbol: 'diamond' },
      opacity: same ? 0.55 : 0.25,
      hovertemplate: `target ${tg.quantity} ${tg.kind} %{y:.3f} %<br>%{x:.1f} nm<extra></extra>`,
    })
  })
  // refractive-index profile (deposition order: substrate at z < 0)
  const zs: number[] = []
  const ns: number[] = []
  zs.push(-0.08 * Math.max(ev.total_thickness_nm, 1), 0)
  const nSub = ev.substrate_n_design
  ns.push(nSub, nSub)
  for (const L of ev.layers) {
    zs.push(L.cumulative_nm - L.thickness_nm, L.cumulative_nm)
    ns.push(L.n_design, L.n_design)
  }
  zs.push(ev.total_thickness_nm, ev.total_thickness_nm * 1.08 + 1)
  ns.push(ev.incident_n_design, ev.incident_n_design)
  return (
    <div className="grid h-full grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,2.2fr)_minmax(0,1fr)]">
      <div className="flex min-h-0 flex-col">
        <div className="flex items-center gap-2 px-3 py-1 text-small text-muted">
          <span>{t('cd.viewAngle')}</span>
          <NumberField className="h-6 w-14" value={angle} min={0} max={89.9} onCommit={(v) => setAngle(v ?? 0)} ariaLabel={t('cd.viewAngle')} />
          <span>°</span>
          <Checkbox checked={showA} onChange={setShowA} label={<span className="whitespace-nowrap text-small text-muted">A</span>} />
          <Checkbox checked={sp} onChange={setSp} label={<span className="whitespace-nowrap text-small text-muted">s / p</span>} />
          <Select className="h-6 w-[120px] text-small" value={ymode} ariaLabel="vertical axis" options={[{ value: 'pct', label: '%' }, { value: 'log', label: t('cd.logScale') }, { value: 'od', label: t('cd.odScale') }]} onChange={setYmode} />
          <span className="min-w-0 flex-1 truncate text-right text-faint" title={ev.method}>
            {ev.method}
          </span>
        </div>
        <div className="min-h-0 flex-1">
          <Plot data={traces} layout={{ margin: { l: 48, r: 10, t: 8, b: 38 }, hovermode: 'x unified', xaxis: { title: { text: 'λ (nm)' } }, yaxis: ymode === 'pct' ? { title: { text: '%' }, range: [-2, 102] } : ymode === 'log' ? { title: { text: '% (log)' }, type: 'log' } : { title: { text: 'OD = −log₁₀ T' }, rangemode: 'tozero' }, legend: { orientation: 'h', y: 1.06, font: { size: 10 } } }} />
        </div>
      </div>
      <div className="min-h-0 border-t border-line">
        {ev.layers.length === 0 ? (
          <div className="flex h-full items-center justify-center text-small text-faint">{t('cd.noLayersProfile')}</div>
        ) : (
        <Plot
          data={[{ type: 'scatter', mode: 'lines', x: zs, y: ns, line: { shape: 'hv', color: DATA.reference, width: 1.4 }, fill: 'tozeroy', fillcolor: DATA.fill, hovertemplate: 'z %{x:.1f} nm<br>n %{y:.4f}<extra></extra>' }]}
          layout={{ margin: { l: 48, r: 10, t: 22, b: 34 }, title: { text: `${t('cd.profile')} (λ₀ = ${fmt(design.design_wavelength_nm, 5)} nm; ${t('cd.substrateLeft')})`, font: { size: 11 } }, xaxis: { title: { text: t('cd.depthAxis') } }, yaxis: { title: { text: 'n' }, rangemode: 'tozero' }, showlegend: false }}
        />
        )}
      </div>
    </div>
  )
}

/** Import a tabulated target curve (λ nm and value per line; fractions given in % are recognised). */
function TableImport({ onTable, fraction }: { onTable: (t: [number, number][]) => void; fraction: boolean }) {
  const t = useT()
  const toast = useUiStore((s) => s.toast)
  const ref = useRef<HTMLInputElement>(null)
  return (
    <>
      <IconButton size="sm" title={t('cs.tableImport')} onClick={() => ref.current?.click()}>
        <FileUp size={12} />
      </IconButton>
      <input
        ref={ref}
        type="file"
        accept=".csv,.txt,.dat,text/plain"
        className="hidden"
        onChange={async (e) => {
          const f = e.target.files?.[0]
          e.target.value = ''
          if (!f) return
          const raw = parseSpectrum(await f.text(), false)
          const pct = fraction && raw.value.some((v) => v > 1.0001)
          const rows = raw.lambda_nm.map((w, i) => [w, pct ? raw.value[i] / 100 : raw.value[i]] as [number, number]).sort((a, b) => a[0] - b[0])
          if (rows.length < 1) return toast('error', t('cs.needData'))
          onTable(rows)
          toast('success', `${t('cs.tablePoints', { n: rows.length })}${pct ? ' (%)' : ''}`)
        }}
      />
    </>
  )
}

/** The back-side coating as a stack formula (from the back face's outer medium to the substrate). */
function BackSideRow({ design, setDesign }: { design: CoatingDesignSpec; setDesign: SetDesign }) {
  const t = useT()
  const custom = useProjectStore((s) => s.project.custom_materials)
  const toast = useUiStore((s) => s.toast)
  const [formula, setFormula] = useState('')
  useEffect(() => {
    const ctrl = new AbortController()
    api
      .cdEvaluate({ design: { ...design, layers: design.back_layers ?? [], back_side: 'none', targets: [] }, custom_materials: custom, samples: 2 }, ctrl.signal)
      .then((r) => setFormula(r.formula ?? ''))
      .catch(() => undefined)
    return () => ctrl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(design.back_layers), JSON.stringify(design.palette), design.design_wavelength_nm])
  const apply = async (f: string) => {
    if (!f.trim() || f.trim() === formula) return
    try {
      const r = await api.cdFormula({ design, custom_materials: custom, formula: f })
      setDesign((d) => void (d.back_layers = r.design.layers), `Back-side layers from the formula ${r.formula}`)
    } catch (e) {
      toast('error', (e as Error).message)
    }
  }
  const linked = !!design.back_same_as_front
  return (
    <>
      <FormRow label={t('cs.backLink')} hint={t('cs.backLinkHint')}>
        <Checkbox checked={linked} onChange={(v) => setDesign((d) => void (d.back_same_as_front = v), v ? 'Back side linked to the front' : 'Back side with its own layers')} label={<span className="text-small text-muted">{t('cs.backLinkLabel')}</span>} />
      </FormRow>
      {!linked && (
        <FormRow label={t('cs.backFormula')} hint={t('cs.backFormulaHint')}>
          <TextField className="min-w-0 flex-1 font-mono text-small" value={formula} placeholder="L" onCommit={(v) => void apply(v)} ariaLabel={t('cs.backFormula')} />
          <Button size="sm" variant="ghost" title={t('cs.sameAsFrontHint')} onClick={() => setDesign((d) => void (d.back_layers = structuredClone(d.layers)), 'Back side: the front layers')}>
            {t('cs.sameAsFront')}
          </Button>
        </FormRow>
      )}
    </>
  )
}

/** Every target with what the design achieves; phase and colour quantities against their target band. */
function TargetsTab({ design, ev }: { design: CoatingDesignSpec; ev: CoatingEvaluation | null }) {
  const t = useT()
  if (!design.targets.length) return <div className="flex h-full items-center justify-center text-faint">{t('cd.noTargets')}</div>
  if (!ev) return <div className="flex h-full items-center justify-center"><Spinner /></div>
  return (
    <div className="h-full overflow-auto p-3">
      <table className="eng-table mb-3">
        <thead>
          <tr>
            <th className="w-8 text-right">#</th>
            <th>{t('cs.target')}</th>
            <th className="text-right">{t('cs.achieved')}</th>
            <th className="text-right">{t('cs.violation')}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {design.targets.map((tg, k) => {
            const b = ev.targets[k]
            const u = quantityUnits(tg.quantity)
            const v = (x: number) => `${fmt(shownValue(tg.quantity, x), 4)}${u ? ` ${u}` : ''}`
            return (
              <tr key={k}>
                <td className="num px-2 text-right text-muted">{k + 1}</td>
                <td className="px-2 text-small" title={t(`cs.q.${tg.quantity}`)}>{targetText(tg)}</td>
                <td className="num px-2 text-right">{b ? (b.value.length === 1 ? v(b.value[0]) : `${v(b.min)} … ${v(b.max)}`) : '—'}</td>
                <td className="num px-2 text-right">{b ? v(b.max_violation) : '—'}</td>
                <td className="px-2">{b && <Badge tone={b.met ? 'ok' : 'warn'}>{b.met ? t('cd.met') : t('cs.notMet')}</Badge>}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(360px,1fr))] gap-3">
        {design.targets.map((tg, k) => {
          const b = ev.targets[k]
          if (!b || b.lambda_nm.length < 2 || isFraction(tg.quantity)) return null
          const u = quantityUnits(tg.quantity)
          const lo = b.target.map((x) => x - tg.tolerance)
          const hi = b.target.map((x) => x + tg.tolerance)
          const band: Trace[] = tg.kind === '='
            ? [
                { type: 'scatter', mode: 'lines', x: b.lambda_nm, y: lo, line: { width: 0 }, hoverinfo: 'skip', showlegend: false },
                { type: 'scatter', mode: 'lines', x: b.lambda_nm, y: hi, line: { width: 0 }, fill: 'tonexty', fillcolor: DATA.fill, name: t('cs.targetBand'), hoverinfo: 'skip' },
              ]
            : [{ type: 'scatter', mode: 'lines', x: b.lambda_nm, y: tg.kind === '>=' ? lo : hi, line: { color: DATA.reference, dash: 'dot', width: 1.5 }, name: `${tg.kind === '>=' ? '≥' : '≤'} ${t('cs.target').toLowerCase()}` }]
          return (
            <div key={k} className="h-56 rounded border border-line">
              <Plot
                data={[...band, { type: 'scatter', mode: 'lines+markers', x: b.lambda_nm, y: b.value, marker: { size: 4 }, line: { color: b.met ? DATA.primary : DATA.secondary, width: 1.8 }, name: `${tg.quantity}${hasOf(tg.quantity) ? `(${tg.of ?? 'R'})` : ''}` }]}
                layout={{ margin: { l: 52, r: 8, t: 24, b: 34 }, title: { text: `${k + 1}: ${targetText(tg)}`, font: { size: 10 } }, xaxis: { title: { text: 'λ (nm)' } }, yaxis: { title: { text: `${tg.quantity}${u ? ` (${u})` : ''}` } }, showlegend: false }}
              />
            </div>
          )
        })}
      </div>
      <div className="mt-2 text-caption leading-relaxed text-faint">{t('cs.scaleHint')}</div>
    </div>
  )
}

/** Reverse engineering: fit the design's thicknesses to a measured R or T spectrum. */
function MeasureTab({ design, setDesign }: { design: CoatingDesignSpec; setDesign: SetDesign }) {
  const t = useT()
  const toast = useUiStore((s) => s.toast)
  const custom = useProjectStore((s) => s.project.custom_materials)
  const [text, setText] = useState('')
  const [percent, setPercent] = useState(true)
  const [quantity, setQuantity] = useState<'R' | 'T'>('T')
  const [pol, setPol] = useState<'avg' | 's' | 'p'>('avg')
  const [angle, setAngle] = useState(0)
  const [mode, setMode] = useState<CoatingFit['mode']>('scale')
  const [fitIndex, setFitIndex] = useState(false)
  const [fitDisp, setFitDisp] = useState(false)
  const [fitAbs, setFitAbs] = useState(false)
  const [fitSub, setFitSub] = useState(false)
  const [search, setSearch] = useState<'local' | 'global'>('local')
  const [indexRange, setIndexRange] = useState(0.1)
  const [maxErr, setMaxErr] = useState(20)
  const [busy, setBusy] = useState(false)
  const [fit, setFit] = useState<CoatingFit | null>(null)
  const parsed = useMemo(() => parseSpectrum(text, percent), [text, percent])
  const file = useRef<HTMLInputElement>(null)
  const run = async () => {
    if (parsed.lambda_nm.length < 3) return toast('error', t('cs.needData'))
    setBusy(true)
    try {
      const m: CoatingMeasurement = { quantity, polarization: pol, angle_deg: angle, lambda_nm: parsed.lambda_nm, value: parsed.value }
      setFit(await api.cdFit({ design, custom_materials: custom, measurements: [m], mode, max_error: maxErr / 100, fit_index: fitIndex, fit_dispersion: fitDisp, fit_absorption: fitAbs, fit_substrate: fitSub, search, index_range: indexRange, time_limit_s: search === 'global' ? 120 : 30 }))
    } catch (e) {
      toast('error', (e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const apply = () => {
    if (!fit) return
    setDesign((d) => {
      d.layers = fit.fitted_design.layers
      d.palette = fit.fitted_design.palette
      d.substrate_offset = fit.fitted_design.substrate_offset ?? 0
    }, 'Apply the fitted (as-built) thicknesses and indices')
    setFit(null)
    toast('success', t('cs.applied'))
  }
  const c = fit?.curves[0]
  return (
    <div className="grid h-full grid-cols-[minmax(230px,300px)_minmax(0,1fr)]">
      <div className="min-h-0 space-y-2 overflow-auto border-r border-line p-3 text-small">
        <div className="leading-snug text-muted">{t('cs.measureIntro')}</div>
        <textarea
          aria-label={t('cs.measuredData')}
          className="field-input h-40 w-full resize-y font-mono text-small"
          placeholder={'# λ (nm)   T (%)\n400  91.2\n410  91.6\n…'}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="flex items-center gap-2">
          <Button size="sm" variant="ghost" onClick={() => file.current?.click()}>
            <FileUp size={12} /> {t('cs.importCsv')}
          </Button>
          <input
            ref={file}
            type="file"
            accept=".csv,.txt,.dat,text/plain"
            className="hidden"
            onChange={async (e) => {
              const f = e.target.files?.[0]
              if (f) setText(await f.text())
              e.target.value = ''
            }}
          />
          <span className="text-faint">{parsed.lambda_nm.length} {t('cs.points')}{parsed.skipped ? ` · ${parsed.skipped} ${t('cs.skipped')}` : ''}</span>
        </div>
        <Checkbox checked={percent} onChange={setPercent} label={<span className="text-muted">{t('cs.inPercent')}</span>} />
        <div className="grid grid-cols-[88px_minmax(0,1fr)] items-center gap-1.5">
          <span className="text-muted">{t('cs.measured')}</span>
          <Select value={quantity} ariaLabel={t('cs.measured')} options={[{ value: 'T', label: 'T' }, { value: 'R', label: 'R' }]} onChange={(v) => setQuantity(v as 'R' | 'T')} />
          <span className="text-muted">{t('ca.pol')}</span>
          <Select value={pol} ariaLabel={t('ca.pol')} options={[{ value: 'avg', label: 'avg' }, { value: 's', label: 's' }, { value: 'p', label: 'p' }]} onChange={(v) => setPol(v as 'avg' | 's' | 'p')} />
          <span className="text-muted">{t('ca.angle')}</span>
          <NumberField value={angle} min={0} max={89.9} ariaLabel={t('ca.angle')} onCommit={(v) => setAngle(v ?? 0)} />
          <span className="text-muted">{t('cs.fitMode')}</span>
          <Select value={mode} ariaLabel={t('cs.fitMode')} options={[{ value: 'scale', label: t('cs.mode.scale') }, { value: 'layers', label: t('cs.mode.layers') }, { value: 'scale_layers', label: t('cs.mode.scale_layers') }, { value: 'none', label: t('cs.mode.none') }]} onChange={(v) => setMode(v as CoatingFit['mode'])} />
          <span className="text-muted" title={t('cs.maxErrorHint')}>{t('cs.maxError')}</span>
          <NumberField value={maxErr} min={1} max={80} ariaLabel={t('cs.maxError')} onCommit={(v) => setMaxErr(v ?? 20)} />
        </div>
        <div className="space-y-0.5" title={t('cs.indexFitHint')}>
          <div className="text-muted">{t('cs.indexFit')}</div>
          <Checkbox checked={fitIndex} onChange={setFitIndex} label={<span className="text-muted">{t('cs.fitIndex')}</span>} />
          <Checkbox checked={fitDisp} onChange={setFitDisp} label={<span className="text-muted">{t('cs.fitDispersion')}</span>} />
          <Checkbox checked={fitAbs} onChange={setFitAbs} label={<span className="text-muted">{t('cs.fitAbsorption')}</span>} />
          <Checkbox checked={fitSub} onChange={setFitSub} label={<span className="text-muted">{t('cs.fitSubstrate')}</span>} />
        </div>
        <div className="grid grid-cols-[88px_minmax(0,1fr)] items-center gap-1.5" title={t('cs.searchHint')}>
          <span className="text-muted">{t('cs.search')}</span>
          <Select value={search} ariaLabel={t('cs.search')} options={[{ value: 'local', label: t('cs.searchLocal') }, { value: 'global', label: t('cs.searchGlobal') }]} onChange={(v) => setSearch(v as 'local' | 'global')} />
          {search === 'global' && (
            <>
              <span className="text-muted" title={t('cs.indexRangeHint')}>± Δn</span>
              <NumberField value={indexRange} min={0.001} max={0.5} ariaLabel={t('cs.indexRangeHint')} onCommit={(v) => setIndexRange(v ?? 0.1)} />
            </>
          )}
        </div>
        <Button variant="primary" size="sm" disabled={busy || !design.layers.length} onClick={() => void run()}>
          {busy ? <Spinner size={12} /> : <Wand2 size={12} />} {t('cs.fit')}
        </Button>
        {fit && (
          <div className="space-y-1.5 border-t border-line pt-2">
            <div>
              RMS {fmt(fit.rms_before * 100, 3)} % → <b>{fmt(fit.rms_after * 100, 3)} %</b>
            </div>
            <table className="eng-table">
              <thead>
                <tr>
                  <th>{t('cs.variable')}</th>
                  <th className="text-right">{t('cs.error')}</th>
                  <th className="text-right">±1σ</th>
                </tr>
              </thead>
              <tbody>
                {fit.variables.map((v) => {
                  const rel = !v.kind || v.kind === 'scale' || v.kind === 'layer'
                  const show = (x: number) => (rel ? `${fmt(x * 100, 4)} %` : `${fmt(x, 4)}${v.units ? ` ${v.units}` : ''}`)
                  return (
                    <tr key={v.name}>
                      <td className="px-2">{v.name === 'scale' ? t('cs.mode.scale') : v.name.replace('layer', t('cd.layer')).replace('substrate', t('cd.substrate').toLowerCase())}</td>
                      <td className="num px-2 text-right">{show(v.error)}</td>
                      <td className="num px-2 text-right">{Number.isFinite(v.sigma) ? show(v.sigma) : '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {fit.warnings.map((w) => (
              <div key={w} className="text-warn">{w}</div>
            ))}
            <Button size="sm" variant="primary" onClick={apply} title={t('cs.applyHint')}>
              <Save size={12} /> {t('cs.apply')}
            </Button>
            <div className="text-caption text-faint">{fit.method} · {fit.status} · {fit.elapsed_s.toFixed(1)} s</div>
          </div>
        )}
      </div>
      <div className="min-h-0">
        {c ? (
          <Plot
            data={[
              { type: 'scatter', mode: 'markers', x: c.lambda_nm, y: c.measured.map((v) => v * 100), name: t('cs.measured'), marker: { size: 4, color: DATA.reference } },
              { type: 'scatter', mode: 'lines', x: c.lambda_nm, y: c.design.map((v) => v * 100), name: t('cs.designCurve'), line: { color: DATA.secondary, width: 1.4, dash: 'dash' } },
              { type: 'scatter', mode: 'lines', x: c.lambda_nm, y: c.fitted.map((v) => v * 100), name: t('cs.fittedCurve'), line: { color: DATA.primary, width: 2 } },
            ]}
            layout={{ margin: { l: 52, r: 10, t: 10, b: 40 }, hovermode: 'x unified', xaxis: { title: { text: 'λ (nm)' } }, yaxis: { title: { text: `${c.quantity} (%)` } }, legend: { orientation: 'h', y: 1.06, font: { size: 10 } } }}
          />
        ) : parsed.lambda_nm.length >= 2 ? (
          <Plot
            data={[{ type: 'scatter', mode: 'markers', x: parsed.lambda_nm, y: parsed.value.map((v) => v * 100), name: t('cs.measured'), marker: { size: 4, color: DATA.reference } }]}
            layout={{ margin: { l: 52, r: 10, t: 10, b: 40 }, xaxis: { title: { text: 'λ (nm)' } }, yaxis: { title: { text: `${quantity} (%)` } }, showlegend: false }}
          />
        ) : (
          <div className="flex h-full items-center justify-center px-8 text-center text-small text-faint">{t('cs.measureEmpty')}</div>
        )}
      </div>
    </div>
  )
}

/** The angle of incidence all targets share (0 when they differ or there are none). */
function targetAngle(d: CoatingDesignSpec): number {
  const a = d.targets.map((g) => g.angle_deg)
  return a.length && a.every((x) => Math.abs(x - a[0]) < 1e-9) ? a[0] : 0
}

/** Phase and GDD, colour, field and profile of the working design (the shared coating analyses). */
function AnalysisTab({ design }: { design: CoatingDesignSpec }) {
  const t = useT()
  const custom = useProjectStore((s) => s.project.custom_materials)
  if (!design.layers.length) return <div className="flex h-full items-center justify-center text-faint">{t('cd.empty')}</div>
  const lams = design.targets.flatMap((g) => [g.lambda_min_nm, g.lambda_max_nm])
  const lo = lams.length ? Math.min(...lams) : design.design_wavelength_nm * 0.7
  const hi = lams.length ? Math.max(...lams) : design.design_wavelength_nm * 1.4
  const pad = Math.max(10, 0.1 * (hi - lo))
  const defaults = { range: [Math.max(100, Math.round(lo - pad)), Math.round(hi + pad)] as [number, number], reference: design.design_wavelength_nm, band: null, angle: targetAngle(design) }
  return (
    <CoatingAnalysisPanel
      fetcher={(p, signal) => api.cdAnalyze({ design, custom_materials: custom, ...p }, signal)}
      depKey={JSON.stringify([design, custom.length])}
      defaults={defaults}
      tabs={['phase', 'admittance', 'colour', 'field', 'profile', 'spectrum', 'angle']}
      opaque={design.substrate_index != null && (design.substrate_extinction ?? 0) > 0}
    />
  )
}

function ToleranceTab({ design }: { design: CoatingDesignSpec }) {
  const t = useT()
  const custom = useProjectStore((s) => s.project.custom_materials)
  const toast = useUiStore((s) => s.toast)
  const [rel, setRel] = useState(1)
  const [abs, setAbs] = useState(0)
  const [runs, setRuns] = useState(200)
  const [seed, setSeed] = useState(1)
  const [mc, setMc] = useState<CoatingMonteCarlo | null>(null)
  const [busy, setBusy] = useState(false)
  const run = async () => {
    setBusy(true)
    try {
      setMc(await api.cdMonteCarlo({ design, custom_materials: custom, sigma_rel: rel / 100, sigma_abs_nm: abs, runs, seed }))
    } catch (e) {
      toast('error', (e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-1.5 text-small text-muted">
        <span title={t('cd.sigRelHint')}>σ (%)</span>
        <NumberField className="h-6 w-14" value={rel} min={0} max={50} onCommit={(v) => setRel(v ?? 1)} ariaLabel="relative thickness error" />
        <span title={t('cd.sigAbsHint')}>σ (nm)</span>
        <NumberField className="h-6 w-14" value={abs} min={0} max={100} onCommit={(v) => setAbs(v ?? 0)} ariaLabel="absolute thickness error" />
        <span>{t('cd.runs')}</span>
        <NumberField className="h-6 w-16" value={runs} integer min={1} max={5000} onCommit={(v) => setRuns(v ?? 200)} />
        <span>{t('ns.seed')}</span>
        <NumberField className="h-6 w-14" value={seed} integer min={0} max={2147483647} onCommit={(v) => setSeed(v ?? 1)} />
        <Button size="sm" variant="primary" onClick={run} disabled={busy || !design.layers.length}>
          {busy ? <Spinner size={12} /> : null} {t('cd.runMc')}
        </Button>
        {mc?.yield !== null && mc?.yield !== undefined && (
          <span className="ml-2">
            {t('cd.yield')}: <b className="text-fg">{fmt(mc.yield * 100, 4)} %</b> · {t('cd.merit')} {fmt((mc.merit?.nominal ?? 0) * 100, 3)} → {t('cd.mean')} {fmt((mc.merit?.mean ?? 0) * 100, 3)} / p95 {fmt((mc.merit?.p95 ?? 0) * 100, 3)} %
          </span>
        )}
      </div>
      <div className="min-h-0 flex-1">
        {mc ? (
          <Plot
            data={[
              { type: 'scatter', mode: 'lines', x: mc.lambda_nm, y: mc.p95.map((v) => v * 100), line: { width: 0 }, showlegend: false, hoverinfo: 'skip' },
              { type: 'scatter', mode: 'lines', x: mc.lambda_nm, y: mc.p05.map((v) => v * 100), fill: 'tonexty', fillcolor: DATA.fill, line: { width: 0 }, name: '5–95 %' },
              { type: 'scatter', mode: 'lines', x: mc.lambda_nm, y: mc.p50.map((v) => v * 100), line: { color: DATA.primary, width: 1, dash: 'dot' }, name: 'median' },
              { type: 'scatter', mode: 'lines', x: mc.lambda_nm, y: mc.nominal.map((v) => v * 100), line: { color: 'var(--c-text)', width: 1.6 }, name: t('cd.nominal') },
            ]}
            layout={{ margin: { l: 48, r: 10, t: 10, b: 38 }, xaxis: { title: { text: 'λ (nm)' } }, yaxis: { title: { text: `${mc.quantity} (%)` }, range: [-2, 102] }, legend: { orientation: 'h', y: 1.06, font: { size: 10 } } }}
          />
        ) : (
          <div className="flex h-full items-center justify-center px-6 text-center text-body text-faint">{t('cd.mcHelp')}</div>
        )}
      </div>
      {mc && <div className="border-t border-line px-3 py-1 text-caption text-faint">{mc.method}</div>}
    </div>
  )
}

function RecipeTab({ design }: { design: CoatingDesignSpec }) {
  const t = useT()
  const custom = useProjectStore((s) => s.project.custom_materials)
  const [lm, setLm] = useState(design.design_wavelength_nm)
  const [mon, setMon] = useState<'T' | 'R'>('T')
  const [plate, setPlate] = useState(true)
  const [r, setR] = useState<CoatingRecipe | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const key = JSON.stringify(design)
  useEffect(() => {
    if (!design.layers.length) return setR(null)
    let alive = true
    const h = setTimeout(() => {
      api
        .cdRecipe({ design, custom_materials: custom, monitor_wavelength_nm: lm, monitor: mon, monitor_back_side: plate ? 'uncoated' : 'none' })
        .then((x) => alive && (setR(x), setErr(null)))
        .catch((e) => alive && setErr((e as Error).message))
    }, 200)
    return () => {
      alive = false
      clearTimeout(h)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, custom, lm, mon, plate])
  const fileBase = design.name.replace(/[^A-Za-z0-9_-]+/g, '_') || 'coating'

  const colors = [DATA.primary, DATA.secondary]
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-1.5 text-small text-muted">
        <span title={t('cd.monitorHint')}>{t('cd.monitor')}</span>
        <NumberField className="h-6 w-16" value={lm} min={100} max={50000} onCommit={(v) => setLm(v ?? design.design_wavelength_nm)} ariaLabel="monitor wavelength" />
        <span>nm</span>
        <Select className="h-6 w-14 text-small" value={mon} options={[{ value: 'T', label: 'T' }, { value: 'R', label: 'R' }]} onChange={setMon} />
        <Checkbox checked={plate} onChange={setPlate} label={<span className="text-small text-muted">{t('cd.throughPlate')}</span>} />
        <span className="flex-1" />
        <Button size="sm" disabled={!r} onClick={() => r && downloadText(`${fileBase}_recipe.csv`, recipeToCsv(r), 'text/csv')}>
          <Download size={12} /> CSV
        </Button>
        <Button size="sm" disabled={!r} onClick={() => r && downloadText(`${fileBase}_recipe.json`, JSON.stringify({ recipe: r, design }, null, 2))}>
          <Download size={12} /> JSON
        </Button>
      </div>
      {err && <div className="px-3 py-1 text-small text-danger">{err}</div>}
      {r?.warnings.map((w) => (
        <div key={w} className="px-3 py-1 text-small text-warn">
          {w}
        </div>
      ))}
      {!r ? (
        <div className="flex flex-1 items-center justify-center text-faint">{design.layers.length ? <Spinner /> : t('cd.empty')}</div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <div className="min-h-0">
            <Plot
              data={r.curves.map((c, k) => ({
                type: 'scatter' as const,
                mode: 'lines' as const,
                x: c.thickness_nm,
                y: c.signal.map((v) => v * 100),
                line: { color: colors[design.palette.findIndex((p) => p.key === r.layers[k].material) % 2] ?? DATA.primary, width: 1.6 },
                name: `${c.layer} ${r.layers[k].material}`,
                showlegend: false,
                hovertemplate: `layer ${c.layer} (${r.layers[k].material})<br>%{x:.1f} nm deposited<br>${r.monitor} %{y:.3f} %<extra></extra>`,
              }))}
              layout={{ margin: { l: 48, r: 10, t: 22, b: 36 }, title: { text: `${t('cd.monitorCurve')} ${r.monitor} @ ${fmt(r.monitor_wavelength_nm, 5)} nm`, font: { size: 11 } }, xaxis: { title: { text: t('cd.deposited') } }, yaxis: { title: { text: `${r.monitor} (%)` } } }}
            />
          </div>
          <div className="min-h-0 overflow-auto border-t border-line">
            <table className="eng-table">
              <thead>
                <tr>
                  <th className="text-right">#</th>
                  <th>{t('coat.material')}</th>
                  <th className="text-right">nm</th>
                  <th className="text-right" title={t('cd.qwotHint')}>
                    QWOT λ₀
                  </th>
                  <th className="text-right" title={t('cd.qwotMonHint')}>
                    QWOT λm
                  </th>
                  <th className="text-right">
                    {r.monitor} {t('cd.start2')}
                  </th>
                  <th className="text-right">
                    {r.monitor} {t('cd.end')}
                  </th>
                  <th className="text-right" title={t('cd.tpHint')}>
                    TP
                  </th>
                  <th>{t('cd.termination')}</th>
                  <th className="text-right" title={t('cd.crystalHint')}>
                    {t('cd.crystal')} kÅ
                  </th>
                  <th className="text-right">{t('cd.time')}</th>
                </tr>
              </thead>
              <tbody>
                {r.layers.map((x) => (
                  <tr key={x.layer}>
                    <td className="num px-2 text-right">{x.layer}</td>
                    <td className="px-2">{x.material}</td>
                    <td className="num px-2 text-right">{fmt(x.thickness_nm, 6)}</td>
                    <td className="num px-2 text-right">{fmt(x.qwot_design, 4)}</td>
                    <td className="num px-2 text-right">{fmt(x.qwot_monitor, 4)}</td>
                    <td className="num px-2 text-right">{pct(x.monitor_start)}</td>
                    <td className="num px-2 text-right font-semibold">{pct(x.monitor_end)}</td>
                    <td className="num px-2 text-right">{x.turning_points}</td>
                    <td className={cx('px-2', x.termination === 'turning point' ? 'text-ok' : 'text-muted')}>{x.termination === 'turning point' ? t('cd.atTp') : t('cd.atLevel')}</td>
                    <td className="num px-2 text-right">{fmt(x.crystal_kA, 5)}</td>
                    <td className="num px-2 text-right">{x.time_s < 120 ? `${fmt(x.time_s, 4)} s` : `${fmt(x.time_s / 60, 4)} min`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="space-y-0.5 px-3 py-2 text-caption text-faint">
              <div>
                {t('cd.total')}: {fmt(r.total_thickness_nm, 6)} nm · {fmt(r.total_time_s / 60, 4)} min
              </div>
              {r.notes.map((n) => (
                <div key={n}>{n}</div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function AngleTab({ design }: { design: CoatingDesignSpec }) {
  const t = useT()
  const custom = useProjectStore((s) => s.project.custom_materials)
  const [text, setText] = useState(String(Math.round(design.design_wavelength_nm)))
  const [qty, setQty] = useState<'R' | 'T' | 'A'>('R')
  const [maxA, setMaxA] = useState(85)
  const [mapQ, setMapQ] = useState<'R' | 'T'>('R')
  const [a, setA] = useState<CoatingAngular | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const lams = text
    .split(/[,;\s]+/)
    .map(Number)
    .filter((v) => Number.isFinite(v) && v > 50)
    .slice(0, 8)
  const key = JSON.stringify([design, lams, maxA])
  useEffect(() => {
    if (!design.layers.length && design.substrate_index == null && !design.substrate) return
    let alive = true
    const h = setTimeout(() => {
      api
        .cdAngular({ design, custom_materials: custom, wavelengths_nm: lams, angle_max_deg: maxA, angles: 91 })
        .then((r) => alive && (setA(r), setErr(null)))
        .catch((e) => alive && setErr((e as Error).message))
    }, 200)
    return () => {
      alive = false
      clearTimeout(h)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, custom])
  const palette = SERIES
  const traces: Trace[] = []
  a?.curves.forEach((c, k) => {
    const col = palette[k % palette.length]
    traces.push({ type: 'scatter', mode: 'lines', x: a.angles_deg, y: c[qty].map((v) => v * 100), name: `${fmt(c.wavelength_nm, 5)} nm`, line: { color: col, width: 1.8 } })
    traces.push({ type: 'scatter', mode: 'lines', x: a.angles_deg, y: c[`${qty === 'A' ? 'R' : qty}s` as 'Rs'].map((v) => v * 100), name: `${qty === 'A' ? 'R' : qty}s`, line: { color: col, width: 1, dash: 'dot' }, showlegend: k === 0 })
    traces.push({ type: 'scatter', mode: 'lines', x: a.angles_deg, y: c[`${qty === 'A' ? 'R' : qty}p` as 'Rp'].map((v) => v * 100), name: `${qty === 'A' ? 'R' : qty}p`, line: { color: col, width: 1, dash: 'dash' }, showlegend: k === 0 })
  })
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-1.5 text-small text-muted">
        <span>λ (nm)</span>
        <input className="field-input h-6 w-44" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.stopPropagation()} aria-label={t('cd.wavelengthsList')} title={t('cd.wavelengthsList')} />
        <Select className="h-6 w-14 text-small" value={qty} options={[{ value: 'R', label: 'R' }, { value: 'T', label: 'T' }, { value: 'A', label: 'A' }]} onChange={setQty} />
        <span>θ ≤</span>
        <NumberField className="h-6 w-12" value={maxA} min={1} max={89.9} onCommit={(v) => setMaxA(v ?? 85)} ariaLabel="maximum angle" />
        <span>°</span>
        <span className="flex-1" />
        <span>{t('cd.mapOf')}</span>
        <Select className="h-6 w-14 text-small" value={mapQ} options={[{ value: 'R', label: 'R' }, { value: 'T', label: 'T' }]} onChange={setMapQ} />
      </div>
      {err && <div className="px-3 py-1 text-small text-danger">{err}</div>}
      {!a ? (
        <div className="flex flex-1 items-center justify-center text-faint">{t('cd.empty')}</div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="min-h-0">
            <Plot
              data={traces}
              layout={{ margin: { l: 48, r: 10, t: 10, b: 36 }, xaxis: { title: { text: `θ (°) — ${t('cd.inIncident')}` } }, yaxis: { title: { text: `${qty} (%)` }, range: [-2, 102] }, legend: { orientation: 'h', y: 1.08, font: { size: 10 } } }}
            />
          </div>
          <div className="min-h-0 border-t border-line">
            <Plot
              data={[
                {
                  type: 'heatmap',
                  x: a.map.lambda_nm,
                  y: a.map.angles_deg,
                  z: (mapQ === 'R' ? a.map.R : a.map.T).map((r) => r.map((v) => v * 100)),
                  colorscale: COLORMAPS.sequentialAlt,
                  zmin: 0,
                  zmax: 100,
                  colorbar: { title: { text: `${mapQ} %` }, thickness: 10 },
                  hovertemplate: 'λ %{x:.1f} nm<br>θ %{y:.1f}°<br>%{z:.3f} %<extra></extra>',
                },
              ]}
              layout={{ margin: { l: 48, r: 10, t: 22, b: 36 }, title: { text: `${mapQ}(λ, θ)`, font: { size: 11 } }, xaxis: { title: { text: 'λ (nm)' } }, yaxis: { title: { text: 'θ (°)' } } }}
            />
          </div>
        </div>
      )}
      {a?.opaque_substrate && <div className="border-t border-line px-3 py-1 text-caption text-faint">{t('cd.opaqueNote')}</div>}
    </div>
  )
}
