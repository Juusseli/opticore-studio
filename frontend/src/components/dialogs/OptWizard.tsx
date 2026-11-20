import { Wand2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import { useT } from '../../lib/i18n'
import { buildWizardSpec, craLimit, DEFAULT_WIZARD, distortionLimit, edgeElements, lateralLimit, lensGaps, riLimit, scaledConstraints, trackLimit, type WizardChoices, type WizardObjective, wizardTargets } from '../../lib/optWizard'
import type { DesignSummary } from '../../lib/types'
import { fmt } from '../../lib/format'
import { useEngineStore } from '../../store/engineStore'
import { selectDetectors, selectSources, useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { Button, Checkbox, Dialog, NumberField, Select } from '../common/ui'
import { cx } from '../common/uiUtils'

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset className="flex flex-col items-start gap-1.5">
      <legend className="mb-1.5 text-small font-semibold tracking-wide text-muted uppercase">{title}</legend>
      {children}
    </fieldset>
  )
}

/** Optimisation wizard: variables, merit function and constraints from a few choices, applied as one undoable step. */
export function OptWizard() {
  const t = useT()
  const close = useUiStore((s) => s.closeDialog)
  const project = useProjectStore((s) => s.project)
  const updateProject = useProjectStore((s) => s.updateProject)
  const sources = useProjectStore(selectSources)
  const detectors = useProjectStore(selectDetectors)
  const evaluation = useEngineStore((s) => s.evaluation)
  const sys = project.system
  const para = evaluation?.paraxial[String(sys.primary_wavelength)]
  const efl = para?.efl ?? null
  const track = para?.total_track ?? null
  const state = evaluation ? { semiDiameters: evaluation.semi_diameters, edgeThickness: evaluation.edge_thickness } : null
  const beamDetectors = sources.some((s) => s.enabled) ? detectors.filter((d) => d.enabled) : []
  const offAxis = sys.fields.some((f) => f.x !== 0 || f.y !== 0)
  const [c, setC] = useState<WizardChoices>(() => ({
    ...DEFAULT_WIZARD,
    ...scaledConstraints(sys, state),
    eflTarget: efl !== null && Number.isFinite(efl) ? +efl.toPrecision(6) : null,
    detectorId: beamDetectors[0]?.id ?? null,
  }))
  const [fieldW, setFieldW] = useState(sys.fields.map((f) => f.weight))
  const [wlW, setWlW] = useState(sys.wavelengths.map((w) => w.weight))
  // the design's numbers now (engine summary): the default limits keep distortion and lateral colour from growing
  const [now0, setNow0] = useState<DesignSummary | null>(null)
  const touched = useRef(new Set<string>())
  const touch = (k: string) => touched.current.add(k)
  const distNow = now0?.distortion_pct ?? null
  const latNow = now0?.lateral_colour_um ?? null
  const riNow = now0?.relative_illumination ?? null
  const craNow = now0?.cra_deg ?? null
  const holds = (x: WizardChoices, s: DesignSummary | null): Partial<WizardChoices> => {
    const imaging = x.objective === 'rms_spot' || x.objective === 'rms_wavefront'
    const p: Partial<WizardChoices> = {}
    if (!touched.current.has('dist')) p.maxDistortion = imaging && s?.distortion_pct != null ? distortionLimit(s.distortion_pct) : null
    if (!touched.current.has('lat')) p.maxLateralUm = imaging && s?.lateral_colour_um != null ? lateralLimit(s.lateral_colour_um) : null
    return p
  }
  useEffect(() => {
    if (!offAxis) return
    const ac = new AbortController()
    api
      .summary({ system: sys, custom_materials: project.custom_materials }, ac.signal)
      .then((r) => {
        setNow0(r)
        setC((x) => ({ ...x, ...holds(x, r) }))
      })
      .catch(() => undefined)
    return () => ac.abort()
    // the design does not change while the dialog is open
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const set = (p: Partial<WizardChoices>) => setC((x) => ({ ...x, ...p }))
  // the sharpest image keeps the focal length and the distortion by default; a spot or beam of a given size is set
  // by the power and the focus, so there they are free unless the user ticked them
  const setGoal = (o: WizardObjective) => {
    const imaging = o === 'rms_spot' || o === 'rms_wavefront'
    const p: Partial<WizardChoices> = { objective: o, ...holds({ ...c, objective: o }, now0) }
    if (!touched.current.has('efl')) p.eflTarget = imaging && efl !== null && Number.isFinite(efl) ? +efl.toPrecision(6) : null
    set(p)
  }
  const imgId = sys.surfaces[sys.surfaces.length - 1]?.id
  const det = beamDetectors.find((d) => d.id === c.detectorId)
  const detLoose = c.objective === 'beam_size' && det && det.placement.anchor !== imgId
  const tg = wizardTargets(sys)
  const preview = buildWizardSpec(sys, project.optimization, c)
  const nv = preview.variables.length - (c.mode === 'add' ? project.optimization.variables.length : 0)
  const no = preview.operands.length - (c.mode === 'add' ? project.optimization.operands.length : 0)
  const noGoal = c.objective === 'beam_size' && !c.detectorId
  const apply = () => {
    updateProject((p) => {
      p.system.fields = p.system.fields.map((f, i) => ({ ...f, weight: fieldW[i] ?? f.weight }))
      p.system.wavelengths = p.system.wavelengths.map((w, i) => ({ ...w, weight: wlW[i] ?? w.weight }))
      p.optimization = buildWizardSpec(p.system, p.optimization, c)
    }, t('ow.undo'))
    close()
    useUiStore.getState().set({ bottomTab: 'optimization', bottomOpen: true })
  }
  const count = (n: number) => <span className="text-faint">({n})</span>
  // what the design has now (engine evaluation), next to each constraint
  const idx = (id: string) => sys.surfaces.findIndex((x) => x.id === id)
  const minOf = (xs: (number | null | undefined)[]) => {
    const v = xs.filter((x): x is number => x !== null && x !== undefined && Number.isFinite(x))
    return v.length ? Math.min(...v) : null
  }
  const now = {
    centre: minOf(edgeElements(sys).map((id) => sys.surfaces[idx(id)].thickness)),
    edge: evaluation ? minOf(edgeElements(sys).map((id) => evaluation.edge_thickness[idx(id)])) : null,
    gap: evaluation ? minOf(lensGaps(sys).flatMap((id) => [evaluation.edge_thickness[idx(id)], sys.surfaces[idx(id)].thickness])) : null,
  }
  const nowLabel = (v: number | null, unit = 'mm') => (v === null ? null : <span className="num text-faint">{t('ow.now', { v: `${fmt(v, 3)} ${unit}` })}</span>)
  const goals: WizardObjective[] = ['rms_spot', 'rms_wavefront', 'spot_size', 'beam_size']
  return (
    <Dialog
      title={t('ow.title')}
      onClose={close}
      width={780}
      icon={<Wand2 size={16} className="text-accent" />}
      footer={
        <>
          <span className={cx('mr-auto text-small', nv && !noGoal ? 'text-muted' : 'text-warn')}>{noGoal ? t('ow.noDetector') : nv ? t('ow.summary', { v: nv, o: no }) : t('ow.noVars')}</span>
          <Button onClick={close}>{t('c.cancel')}</Button>
          <Button variant="primary" disabled={!nv || noGoal} onClick={apply}>
            {t('ow.apply')}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-x-6 gap-y-4 p-4 text-body">
        <Group title={t('ow.change')}>
          <Checkbox checked={c.radii} onChange={(v) => set({ radii: v })} label={<>{t('ow.radii')} {count(tg.radii.length + (c.keepPlane ? 0 : tg.plane.length))}</>} />
          {tg.plane.length > 0 && (
            <div className="pl-5">
              <Checkbox checked={c.keepPlane} onChange={(v) => set({ keepPlane: v })} label={t('ow.keepPlane', { n: tg.plane.length })} />
            </div>
          )}
          <Checkbox checked={c.airGaps} onChange={(v) => set({ airGaps: v })} label={<>{t('ow.airGaps')} {count(tg.air.length)}</>} />
          <Checkbox checked={c.glassThickness} onChange={(v) => set({ glassThickness: v })} label={<>{t('ow.glassThickness')} {count(tg.glass.length)}</>} />
          <Checkbox checked={c.imageDistance} onChange={(v) => set({ imageDistance: v })} label={<>{t('ow.imageDistance')} {count(tg.image ? 1 : 0)}</>} />
        </Group>

        <Group title={t('ow.minimise')}>
          <div role="radiogroup" aria-label={t('ow.minimise')} className="flex w-full flex-col gap-1">
            {goals.map((o) => {
              const off = o === 'beam_size' && !beamDetectors.length
              return (
                <div key={o} className="flex flex-col gap-1">
                  <label className={cx('flex min-h-6 items-center gap-1.5', off ? 'cursor-not-allowed text-faint' : 'cursor-pointer')} title={off ? t('ow.noDetector') : t(`ow.${o}Hint`)}>
                    <input type="radio" name="ow-objective" disabled={off} checked={c.objective === o} onChange={() => setGoal(o)} className="accent-[var(--c-accent)]" />
                    {t('ow.' + o)}
                  </label>
                  {o === 'spot_size' && c.objective === o && (
                    <div className="flex items-center gap-2 pl-5">
                      <NumberField className="h-6 w-16" ariaLabel={t('ow.spotTarget')} value={c.spotTarget} min={0.001} onCommit={(v) => set({ spotTarget: v ?? c.spotTarget })} />
                      <span className="text-faint">µm</span>
                    </div>
                  )}
                  {o === 'beam_size' && c.objective === o && (
                    <div className="flex items-center gap-2 pl-5">
                      <NumberField className="h-6 w-16" ariaLabel={t('ow.beamTarget')} value={c.beamTarget} min={0.001} onCommit={(v) => set({ beamTarget: v ?? c.beamTarget })} />
                      <span className="text-faint">µm</span>
                      <Select className="h-6 max-w-44 text-small" ariaLabel={t('ow.detector')} title={t('ow.detector')} value={c.detectorId ?? ''} options={beamDetectors.map((d) => ({ value: d.id, label: d.name }))} onChange={(v) => set({ detectorId: v || null })} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
          {c.objective !== 'beam_size' && (
            <div role="radiogroup" aria-label={t('ow.reference')} className="flex items-center gap-3">
              <span className="text-muted">{t('ow.reference')}</span>
              {(['centroid', 'chief'] as const).map((r) => (
                <label key={r} className="flex cursor-pointer items-center gap-1.5">
                  <input type="radio" name="ow-ref" checked={c.reference === r} onChange={() => set({ reference: r })} className="accent-[var(--c-accent)]" />
                  {t('ow.ref.' + r)}
                </label>
              ))}
            </div>
          )}
          <div className="text-small leading-snug text-faint">{t(`ow.${c.objective}Hint`)}</div>
          {detLoose && <div className="rounded bg-warn/10 px-2 py-1 text-small leading-snug text-warn">{t('ow.detectorLoose', { name: det.name })}</div>}
          {c.objective !== 'beam_size' && (
            <div className="grid w-full grid-cols-2 gap-3 pt-1">
              <div>
                <div className="mb-1 text-small text-muted">{t('ow.fieldWeights')}</div>
                {sys.fields.map((f, i) => (
                  <div key={i} className="flex items-center gap-2 py-0.5">
                    <span className="num w-16 truncate text-muted">
                      F{i + 1} {fmt(f.y, 4)}
                      {sys.field_type === 'angle' ? '°' : ''}
                    </span>
                    <NumberField className="h-6 w-14" ariaLabel={`${t('ow.fieldWeights')} F${i + 1}`} value={fieldW[i]} min={0} onCommit={(v) => setFieldW(fieldW.map((x, k) => (k === i ? (v ?? 1) : x)))} />
                  </div>
                ))}
              </div>
              <div>
                <div className="mb-1 text-small text-muted">{t('ow.wlWeights')}</div>
                {sys.wavelengths.map((w, i) => (
                  <div key={i} className="flex items-center gap-2 py-0.5">
                    <span className="num w-16 truncate text-muted">{fmt(w.value * 1000, 5)} nm</span>
                    <NumberField className="h-6 w-14" ariaLabel={`${t('ow.wlWeights')} ${fmt(w.value * 1000, 5)} nm`} value={wlW[i]} min={0} onCommit={(v) => setWlW(wlW.map((x, k) => (k === i ? (v ?? 1) : x)))} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </Group>

        <Group title={t('ow.constraints')}>
          <div className="grid w-full grid-cols-[1fr_auto_auto] items-center gap-x-3 gap-y-1.5">
            <span className="text-muted">{t('ow.minCentre')}</span>
            <NumberField optional className="h-6 w-20" ariaLabel={t('ow.minCentre')} placeholder="—" value={c.minCentre} min={0} onCommit={(v) => set({ minCentre: v })} />
            {nowLabel(now.centre) ?? <span />}
            <span className="text-muted">{t('ow.maxCentre')}</span>
            <NumberField optional className="h-6 w-20" ariaLabel={t('ow.maxCentre')} placeholder="—" value={c.maxCentre} min={0} onCommit={(v) => set({ maxCentre: v })} />
            <span />
            <span className="text-muted">{t('ow.minEdge')}</span>
            <NumberField optional className="h-6 w-20" ariaLabel={t('ow.minEdge')} placeholder="—" value={c.minEdge} min={0} onCommit={(v) => set({ minEdge: v })} />
            {nowLabel(now.edge) ?? <span />}
            {c.airGaps && tg.air.length > 0 && (
              <>
                <span className="text-muted">{t('ow.minAirEdge')}</span>
                <NumberField optional className="h-6 w-20" ariaLabel={t('ow.minAirEdge')} placeholder="—" value={c.minAirEdge} min={0} onCommit={(v) => set({ minAirEdge: v })} />
                {nowLabel(now.gap) ?? <span />}
              </>
            )}
          </div>
          <div className="flex items-center gap-2 pt-1">
            <Checkbox
              checked={c.eflTarget !== null}
              onChange={(v) => {
                touch('efl')
                set({ eflTarget: v ? (efl !== null && Number.isFinite(efl) ? +efl.toPrecision(6) : 100) : null })
              }}
              label={t('ow.efl')}
            />
            {c.eflTarget !== null && (
              <NumberField
                className="h-6 w-24"
                ariaLabel={t('ow.efl')}
                value={c.eflTarget}
                onCommit={(v) => {
                  touch('efl')
                  set({ eflTarget: v })
                }}
              />
            )}
            <span className="text-faint">mm</span>
          </div>
          {offAxis && (
            <div className="flex flex-wrap items-center gap-2" title={t('ow.maxDistortionHint')}>
              <Checkbox
                checked={c.maxDistortion !== null}
                onChange={(v) => {
                  touch('dist')
                  set({ maxDistortion: v ? distortionLimit(distNow ?? 1) : null })
                }}
                label={t('ow.maxDistortion')}
              />
              {c.maxDistortion !== null && (
                <NumberField
                  className="h-6 w-16"
                  ariaLabel={t('ow.maxDistortion')}
                  value={c.maxDistortion}
                  min={0}
                  onCommit={(v) => {
                    touch('dist')
                    set({ maxDistortion: v })
                  }}
                />
              )}
              <span className="text-faint">%</span>
              {distNow !== null && nowLabel(distNow, '%')}
            </div>
          )}
          {offAxis && sys.wavelengths.length > 1 && (
            <div className="flex flex-wrap items-center gap-2" title={t('ow.maxLateralHint')}>
              <Checkbox
                checked={c.maxLateralUm !== null}
                onChange={(v) => {
                  touch('lat')
                  set({ maxLateralUm: v ? lateralLimit(latNow ?? 1) : null })
                }}
                label={t('ow.maxLateral')}
              />
              {c.maxLateralUm !== null && (
                <NumberField
                  className="h-6 w-16"
                  ariaLabel={t('ow.maxLateral')}
                  value={c.maxLateralUm}
                  min={0}
                  onCommit={(v) => {
                    touch('lat')
                    set({ maxLateralUm: v })
                  }}
                />
              )}
              <span className="text-faint">µm</span>
              {latNow !== null && nowLabel(Math.abs(latNow), 'µm')}
            </div>
          )}
          {offAxis && (
            <div className="flex flex-wrap items-center gap-2" title={t('ow.minRiHint')}>
              <Checkbox checked={c.minRiPct !== null} onChange={(v) => set({ minRiPct: v ? riLimit(riNow ?? 0.5) : null })} label={t('ow.minRi')} />
              {c.minRiPct !== null && <NumberField className="h-6 w-16" ariaLabel={t('ow.minRi')} value={c.minRiPct} min={0} max={100} onCommit={(v) => set({ minRiPct: v })} />}
              <span className="text-faint">%</span>
              {riNow !== null && nowLabel(riNow * 100, '%')}
            </div>
          )}
          {offAxis && (
            <div className="flex flex-wrap items-center gap-2" title={t('ow.maxCraHint')}>
              <Checkbox checked={c.maxCraDeg !== null} onChange={(v) => set({ maxCraDeg: v ? craLimit(craNow ?? 30) : null })} label={t('ow.maxCra')} />
              {c.maxCraDeg !== null && <NumberField className="h-6 w-16" ariaLabel={t('ow.maxCra')} value={c.maxCraDeg} min={0} max={90} onCommit={(v) => set({ maxCraDeg: v })} />}
              <span className="text-faint">°</span>
              {craNow !== null && nowLabel(craNow, '°')}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Checkbox checked={c.maxTrack !== null} onChange={(v) => set({ maxTrack: v ? (track !== null && Number.isFinite(track) ? trackLimit(track) : 100) : null })} label={t('ow.maxTrack')} />
            {c.maxTrack !== null && <NumberField className="h-6 w-20" ariaLabel={t('ow.maxTrack')} value={c.maxTrack} min={0} onCommit={(v) => set({ maxTrack: v })} />}
            <span className="text-faint">mm</span>
            {track !== null && Number.isFinite(track) && nowLabel(track)}
          </div>
          <div className="text-small leading-snug text-faint">{t('ow.constraintsHint')}</div>
        </Group>

        <Group title={t('ow.existing')}>
          <div role="radiogroup" aria-label={t('ow.existing')} className="space-y-1">
            {(['replace', 'add'] as const).map((m) => (
              <label key={m} className="flex cursor-pointer items-center gap-1.5">
                <input type="radio" name="ow-mode" checked={c.mode === m} onChange={() => set({ mode: m })} className="accent-[var(--c-accent)]" />
                {t('ow.mode.' + m, { v: project.optimization.variables.length, o: project.optimization.operands.length })}
              </label>
            ))}
          </div>
          <div className="text-small leading-snug text-faint">{t('ow.after')}</div>
        </Group>
      </div>
    </Dialog>
  )
}
