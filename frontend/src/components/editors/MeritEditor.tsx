import { Calculator, Plus, Trash2, Wand2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../lib/api'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { variableValue } from '../../lib/project'
import { paramLabel } from '../../lib/paramLabels'
import type { Operand, OperandBreakdown, OperandType, VariableParam } from '../../lib/types'
import { useEngineStore } from '../../store/engineStore'
import { useUiStore } from '../../store/uiStore'
import { useAllMaterials, useCatalogStore } from '../../store/catalogStore'
import { type GlassPoint, nearestGlasses } from '../../lib/glassCatalog'
import { defaultBounds, selectDetectors, selectSources, useProjectStore } from '../../store/projectStore'
import { nsBody } from '../../lib/project'
import { DEFAULT_CONSTRAINTS, exactMode, isActiveOperand, operandRole } from '../../lib/constraints'
import { Badge, Button, Checkbox, Dialog, IconButton, NumberField, Select, Spinner } from '../common/ui'
import { defaultOperand, OPERAND_INFO } from './operands'

/** operands whose 'all wavelengths' (null) means all of them, weighted; the others use the primary wavelength */
const ALL_WAVELENGTHS: OperandType[] = ['rms_spot', 'rms_wavefront', 'throughput', 'surface_reflectance']
/** operands whose 'all fields' (null) means the largest field */
const LARGEST_FIELD: OperandType[] = ['max_lateral_color', 'min_relative_illumination', 'max_cra']

export function MeritEditor() {
  const t = useT()
  const project = useProjectStore((s) => s.project)
  const detectors = useProjectStore(selectDetectors)
  const sources = useProjectStore(selectSources)
  const setOpt = useProjectStore((s) => s.setOptimization)
  const backend = useEngineStore((s) => s.backend)
  const opt = project.optimization
  const sys = project.system
  const mc = sys.multi_config
  const [merit, setMerit] = useState<{ merit: number; operands: OperandBreakdown[]; constraint_mode?: 'exact' | 'penalty' } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // only the latest request may show its answer (an older, slower one would show numbers of an earlier set-up)
  const evalSeq = useRef(0)
  const evaluate = async () => {
    const seq = ++evalSeq.current
    if (!opt.operands.some((o) => o.enabled)) {
      setMerit(null)
      return
    }
    setBusy(true)
    try {
      const r = await api.merit({ system: sys, custom_materials: project.custom_materials, ...nsBody(project), optimization: { ...opt, variables: opt.variables } })
      if (seq !== evalSeq.current) return
      setMerit(r)
      setErr(null)
    } catch (e) {
      if (seq !== evalSeq.current) return
      setErr((e as Error).message)
      setMerit(null)
    } finally {
      if (seq === evalSeq.current) setBusy(false)
    }
  }
  // live evaluation of the merit function on system/operand changes
  useEffect(() => {
    if (backend !== 'online') return
    const h = setTimeout(evaluate, 300)
    return () => clearTimeout(h)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sys, opt.operands, opt.constraints, backend, sources, detectors])

  const setOperand = (i: number, patch: Partial<Operand>) => setOpt({ ...opt, operands: opt.operands.map((o, k) => (k === i ? { ...o, ...patch } : o)) })
  // the engine's active operands, in order (lib/constraints.ts): the breakdown follows this numbering
  const enabledOps = opt.operands.map((o, i) => ({ o, i })).filter((x) => isActiveOperand(x.o))
  const totalContrib = merit ? merit.operands.reduce((a, b) => a + (b.contribution ?? 0), 0) : 0
  // exact limits (lib/constraints.ts): the merit function holds the goals, the limits are met to tolerance
  const exact = exactMode(opt)
  const limitRows = merit?.constraint_mode === 'exact' ? merit.operands.filter((b) => b.role === 'constraint') : []

  const surfaceOptions = [{ value: '', label: '—' }, ...sys.surfaces.slice(1, -1).map((s, k) => ({ value: s.id, label: `${k + 1} ${s.label}` }))]

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-8 shrink-0 items-center gap-1.5 border-b border-line px-2">
        <Button size="sm" variant="subtle" onClick={() => useUiStore.getState().openDialog('optWizard')} title={t('ow.hint')}>
          <Wand2 size={12} /> {t('ow.short')}
        </Button>
        <Button size="sm" onClick={() => setOpt({ ...opt, operands: [...opt.operands, defaultOperand('efl')] }, 'Add operand')}>
          <Plus size={12} /> {t('opt.addOperand')}
        </Button>
        <Button
          size="sm"
          onClick={() => {
            const ops = [defaultOperand('rms_spot')]
            setOpt({ ...opt, operands: [...ops, ...opt.operands.filter((o) => o.type !== 'rms_spot')] }, 'Default merit function')
          }}
        >
          <Wand2 size={12} /> {t('opt.defaultMerit')}
        </Button>
        <Button size="sm" onClick={evaluate} disabled={backend !== 'online'}>
          <Calculator size={12} /> {t('opt.evaluate')}
        </Button>
        <span className="ml-1 text-small text-muted" title={t('mf.limitsHint')}>
          {t('mf.limits')}
        </span>
        <Select className="h-6 w-28 text-small" ariaLabel={t('mf.limits')} title={t('mf.limitsHint')} value={opt.constraints ?? 'exact'} options={[{ value: 'exact', label: t('mf.limits.exact') }, { value: 'penalty', label: t('mf.limits.penalty') }]} onChange={(v) => setOpt({ ...opt, constraints: v }, 'Limits mode')} />
        {busy && <Spinner size={12} />}
        <div className="flex-1" />
        {limitRows.length > 0 && <Badge tone={limitRows.every((b) => b.met) ? 'ok' : 'warn'}>{t('mf.limitsMet', { n: limitRows.filter((b) => b.met).length, m: limitRows.length })}</Badge>}
        <span className="text-small text-muted">{limitRows.length > 0 ? t('mf.goalsMerit') : t('opt.meritValue')}</span>
        <span className="num text-title font-semibold">{merit ? fmt(merit.merit, 7) : '—'}</span>
        {err && <Badge tone="danger">{err.slice(0, 80)}</Badge>}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="eng-table">
          <thead>
            <tr>
              <th className="w-8">#</th>
              <th className="w-10">{t('opt.enabled')}</th>
              <th className="w-[210px]">{t('opt.type')}</th>
              <th className="w-[120px]" title={t('mf.roleHint')}>{t('mf.role')}</th>
              <th className="w-[110px]">{t('opt.target')}</th>
              <th className="w-[80px]">{t('opt.weight')}</th>
              <th className="w-[110px]">{t('c.field')}</th>
              <th className="w-[120px]">{t('c.wavelength')}</th>
              <th className="w-[130px]">{t('opt.surface')}</th>
              {mc && <th className="w-[120px]">{t('mc.config')}</th>}
              <th className="w-[70px]" title={t('mf.ringsHint')}>{t('mf.rings')}</th>
              <th className="w-[150px]" title={t('mf.extraHint')}>{t('mf.extra')}</th>
              <th className="w-[120px] text-right">{t('opt.value')}</th>
              <th className="w-[120px] text-right">{t('opt.contribution')}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {opt.operands.map((o, i) => {
              const info = OPERAND_INFO[o.type]
              const bIdx = enabledOps.findIndex((x) => x.i === i)
              const b = bIdx >= 0 ? merit?.operands[bIdx] : undefined
              const pct = b && totalContrib > 0 ? ((b.contribution ?? 0) / totalContrib) * 100 : null
              const role = operandRole(o, opt)
              return (
                <tr key={i} title={t(`op.${o.type}.desc`)}>
                  <td className="px-2 text-muted">{i + 1}</td>
                  <td className="text-center">
                    <Checkbox checked={o.enabled} ariaLabel={`${i + 1}: ${t('opt.enabled')}`} onChange={(v) => setOperand(i, { enabled: v })} />
                  </td>
                  <td>
                    <Select cell ariaLabel={`${i + 1}: ${t('opt.type')}`} value={o.type} options={(Object.keys(OPERAND_INFO) as OperandType[]).map((k) => ({ value: k, label: t(`op.${k}`) }))} onChange={(v) => setOperand(i, { type: v, target: v === 'efl' ? 100 : v === 'fnum' || v === 'working_fnum' ? 5 : v === 'mtf' || v === 'detector_power' || v === 'max_distortion' || v === 'max_lateral_color' ? 1 : v === 'detector_size' ? 0.1 : v === 'min_relative_illumination' ? 0.5 : v === 'max_cra' ? 30 : 0, frequency: v === 'mtf' ? (o.frequency ?? 50) : o.frequency, detector_id: OPERAND_INFO[v].needsDetector ? (o.detector_id ?? detectors[0]?.id ?? null) : o.detector_id })} />
                  </td>
                  <td>
                    {exact ? (
                      <Select
                        cell
                        ariaLabel={`${i + 1}: ${t('mf.role')}`}
                        title={t('mf.roleHint')}
                        value={o.role ?? 'auto'}
                        options={[
                          { value: 'auto', label: t('mf.role.auto', { r: t(`mf.role.${DEFAULT_CONSTRAINTS.includes(o.type) ? 'constraint' : 'objective'}`) }) },
                          { value: 'objective', label: t('mf.role.objective') },
                          { value: 'constraint', label: t('mf.role.constraint') },
                        ]}
                        onChange={(v) => setOperand(i, { role: v })}
                      />
                    ) : (
                      <span className="px-2 text-faint" title={t('mf.limitsHint')}>
                        {t('mf.role.objective')}
                      </span>
                    )}
                  </td>
                  <td>
                    <NumberField cell value={o.target} onCommit={(v) => setOperand(i, { target: v ?? 0 })} />
                  </td>
                  <td>
                    {role === 'constraint' ? (
                      <span className="px-2 text-faint" title={t('mf.weightUnused')}>
                        —
                      </span>
                    ) : (
                      <NumberField cell value={o.weight} min={0} onCommit={(v) => setOperand(i, { weight: v ?? 0 })} />
                    )}
                  </td>
                  <td>
                    {info.usesField ? (
                      <Select cell value={o.field ?? -1} options={[{ value: -1, label: LARGEST_FIELD.includes(o.type) ? t('mf.largestField') : t('c.all') }, ...sys.fields.map((f, k) => ({ value: k, label: `F${k + 1} (${fmt(f.y, 4)})` }))]} onChange={(v) => setOperand(i, { field: v < 0 ? null : v })} />
                    ) : (
                      <span className="px-2 text-faint">—</span>
                    )}
                  </td>
                  <td>
                    {info.usesWavelength ? (
                      <Select cell value={o.wavelength ?? -1} options={[{ value: -1, label: ALL_WAVELENGTHS.includes(o.type) ? t('c.all') : t('mf.primaryWl') }, ...sys.wavelengths.map((w, k) => ({ value: k, label: `${fmt(w.value * 1000, 5)} nm` }))]} onChange={(v) => setOperand(i, { wavelength: v < 0 ? null : v })} />
                    ) : (
                      <span className="px-2 text-faint">—</span>
                    )}
                  </td>
                  <td>
                    {info.needsSurface ? (
                      <Select cell value={o.surface_id ?? ''} options={surfaceOptions} onChange={(v) => setOperand(i, { surface_id: v || null })} />
                    ) : info.needsDetector ? (
                      <Select cell ariaLabel={t('opt.detector')} value={o.detector_id ?? ''} options={[{ value: '', label: detectors.length ? '—' : t('opt.noDetectors') }, ...detectors.map((d) => ({ value: d.id, label: d.name }))]} onChange={(v) => setOperand(i, { detector_id: v || null })} />
                    ) : (
                      <span className="px-2 text-faint">—</span>
                    )}
                  </td>
                  {mc && (
                    <td>
                      <Select cell value={o.configuration ?? -1} options={[{ value: -1, label: t('mc.activeShort') }, ...mc.names.map((nm, k) => ({ value: k, label: `${k + 1}: ${nm}` }))]} onChange={(v) => setOperand(i, { configuration: v < 0 ? null : v })} />
                    </td>
                  )}
                  <td>{o.type === 'rms_spot' || o.type === 'rms_wavefront' ? <NumberField cell value={o.rings} integer min={1} max={20} onCommit={(v) => setOperand(i, { rings: v ?? 4 })} /> : <span className="px-2 text-faint">—</span>}</td>
                  <td>
                    {info.needsFrequency ? (
                      <div className="flex items-center">
                        <NumberField cell value={o.frequency ?? null} allowInfinity format={(v) => (v === null ? '' : String(v))} placeholder="cyc/mm" min={0.001} onCommit={(v) => setOperand(i, { frequency: v })} />
                        <Select cell value={o.direction ?? 'average'} options={[{ value: 'average', label: 'avg' }, { value: 'tangential', label: 'T' }, { value: 'sagittal', label: 'S' }]} onChange={(v) => setOperand(i, { direction: v })} />
                      </div>
                    ) : o.type === 'rms_spot' || o.type === 'rms_wavefront' ? (
                      <Select cell ariaLabel={t('mf.reference')} title={t('mf.referenceHint')} value={o.reference} options={[{ value: 'centroid', label: t('ow.ref.centroid') }, { value: 'chief', label: t('ow.ref.chief') }]} onChange={(v) => setOperand(i, { reference: v })} />
                    ) : o.type === 'detector_size' ? (
                      <Select cell ariaLabel={t('opt.axis')} value={o.direction ?? 'average'} options={[{ value: 'average', label: 'x, y avg' }, { value: 'sagittal', label: 'x' }, { value: 'tangential', label: 'y' }]} onChange={(v) => setOperand(i, { direction: v })} />
                    ) : (
                      <span className="px-2 text-faint">—</span>
                    )}
                  </td>
                  <td className="num px-2 text-right">
                    {b?.fixed && (b.contribution ?? 0) > 0 && (
                      <span className="mr-1.5" title={t('mf.fixedHint')}>
                        <Badge tone="warn">{t('mf.fixed')}</Badge>
                      </span>
                    )}
                    {b?.error ? <span className="text-danger" title={b.error}>{b.error.slice(0, 30)}</span> : b ? `${fmt(b.value ?? null, 6)} ${b.unit ?? info.unit}` : '—'}
                  </td>
                  <td className="px-2 text-right">
                    {b?.role === 'constraint' ? (
                      <Badge tone={b.met ? 'ok' : 'danger'}>{b.met ? `✓ ${t('mf.met')}` : `✗ ${t('mf.unmet')}`}</Badge>
                    ) : pct !== null && (
                      <div className="flex items-center justify-end gap-1.5">
                        <div className="h-1.5 w-14 overflow-hidden rounded bg-hover">
                          <div className="h-full bg-accent" style={{ width: `${Math.min(100, pct)}%` }} />
                        </div>
                        <span className="num w-12 text-right">{pct.toFixed(1)}</span>
                      </div>
                    )}
                  </td>
                  <td className="px-1">
                    <IconButton size="sm" tone="danger" title={t('c.remove')} onClick={() => setOpt({ ...opt, operands: opt.operands.filter((_, k) => k !== i) }, 'Remove operand')}>
                      <Trash2 size={12} />
                    </IconButton>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {opt.operands.length === 0 && (
          <div className="flex flex-col items-start gap-2 p-4 text-muted">
            <div>{t('mf.empty')}</div>
            <Button size="sm" variant="primary" onClick={() => setOpt({ ...opt, operands: [defaultOperand('rms_spot')] }, 'Default merit function')}>
              <Wand2 size={12} /> {t('mf.addRmsSpot')}
            </Button>
          </div>
        )}
        <div className="px-3 py-2 text-caption leading-relaxed text-faint">{t('mf.note')}</div>
      </div>
    </div>
  )
}

export function VariablesTable() {
  const t = useT()
  const project = useProjectStore((s) => s.project)
  const setOpt = useProjectStore((s) => s.setOptimization)
  const opt = project.optimization
  const sys = project.system
  const params: VariableParam[] = [...(sys.environment_enabled ? (['mount_cte'] as VariableParam[]) : []), 'curvature', 'curvature_x', 'thickness', 'conic', 'conic_x', 'asph_4', 'asph_6', 'asph_8', 'decenter_x', 'decenter_y', 'tilt_x', 'tilt_y', 'tilt_z', 'phase_1', 'phase_2', 'phase_3', 'phase_4', 'grating_frequency', 'coating_scale', 'coat_layer_1', 'coat_layer_2', 'coat_layer_3', 'coat_layer_4']
  const setVar = (i: number, patch: Partial<(typeof opt.variables)[number]>) => setOpt({ ...opt, variables: opt.variables.map((v, k) => (k === i ? { ...v, ...patch } : v)) }, 'Edit variable')
  return (
    <table className="eng-table">
      <thead>
        <tr>
          <th className="w-10">{t('opt.enabled')}</th>
          <th>{t('opt.surface')}</th>
          <th>{t('opt.parameter')}</th>
          <th>{t('c.value')}</th>
          <th>{t('opt.min')}</th>
          <th>{t('opt.max')}</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {opt.variables.map((v, i) => {
          const si = sys.surfaces.findIndex((s) => s.id === v.surface_id)
          const s = sys.surfaces[si]
          const value = !s ? NaN : variableValue(sys, v.surface_id, v.parameter, v.configuration)
          // accessible names of the row's controls: "S1 Curvature min", …
          const row = `S${si} ${paramLabel(v.parameter, t)}`
          return (
            <tr key={i}>
              <td className="text-center">
                <Checkbox checked={v.enabled} ariaLabel={`${row}: ${t('opt.enabled')}`} onChange={(x) => setVar(i, { enabled: x })} />
              </td>
              <td className="px-2">
                {si} {s?.label}
                {v.configuration !== undefined && v.configuration !== null && <span className="ml-1 rounded bg-warn/15 px-1 text-caption font-semibold text-warn">C{v.configuration + 1}</span>}
              </td>
              {v.parameter === 'material' ? (
                <>
                  <td className="px-2" title={t('opt.glassSubHint')}>
                    {t('lde.material')}
                  </td>
                  <td className="num px-2">{s?.material ?? '—'}</td>
                  <td colSpan={2}>
                    <CandidatesCell value={v.candidates ?? null} current={s?.material} onChange={(c) => setVar(i, { candidates: c })} />
                  </td>
                </>
              ) : (
                <>
                  <td>
                    <Select cell ariaLabel={`S${si} ${t('opt.parameter')}`} value={v.parameter} options={params.map((p) => ({ value: p, label: paramLabel(p, t) }))} onChange={(p) => setVar(i, { parameter: p, min: defaultBounds(sys, v.surface_id, p).min, max: defaultBounds(sys, v.surface_id, p).max })} />
                  </td>
                  <td className="num px-2">{fmt(value, 8)}</td>
                  <td>
                    <NumberField cell ariaLabel={`${row} ${t('opt.min')}`} value={v.min} allowInfinity format={(x) => (x === null ? '−∞' : String(x))} onCommit={(x) => setVar(i, { min: x })} />
                  </td>
                  <td>
                    <NumberField cell ariaLabel={`${row} ${t('opt.max')}`} value={v.max} allowInfinity format={(x) => (x === null ? '+∞' : String(x))} onCommit={(x) => setVar(i, { max: x })} />
                  </td>
                </>
              )}
              <td className="px-1">
                <IconButton size="sm" tone="danger" title={t('c.remove')} onClick={() => setOpt({ ...opt, variables: opt.variables.filter((_, k) => k !== i) }, 'Remove variable')}>
                  <Trash2 size={12} />
                </IconButton>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

/** Candidate glasses of a material variable (null = every built-in glass covering the system wavelengths).
 * Imported catalogue glasses can be chosen too; "nearest" picks the closest glasses on the nd-Vd map. */
function CandidatesCell({ value, onChange, current }: { value: string[] | null; onChange: (c: string[] | null) => void; current?: string }) {
  const t = useT()
  const all = useAllMaterials()
  const catalogs = useCatalogStore((st) => st.catalogs)
  const custom = useProjectStore((st) => st.project.custom_materials)
  const [open, setOpen] = useState(false)
  const [sel, setSel] = useState<Set<string>>(new Set(value ?? []))
  const [source, setSource] = useState<string>('all')
  const [hideObsolete, setHideObsolete] = useState(true)
  const [q, setQ] = useState('')
  const [nNear, setNNear] = useState(12)
  const glasses = useMemo(() => {
    const names = new Set(custom.map((m) => m.name.toUpperCase()))
    const list: GlassPoint[] = [
      ...custom.map((m) => ({ name: m.name.toUpperCase(), nd: null, vd: null, catalog: 'project' })),
      ...all.filter((m) => m.category === 'glass' && !names.has(m.name)).map((m) => ({ name: m.name, nd: m.nd, vd: m.vd, status: m.status, verified: m.verified, catalog: m.catalog ?? 'built-in' })),
    ]
    // project glasses: take nd/vd from the library entry of the same name when there is one
    for (const g of list) if (g.nd === null) Object.assign(g, (({ nd, vd, status }) => ({ nd, vd, status }))(all.find((m) => m.name === g.name) ?? { nd: null, vd: null, status: undefined }))
    return list
  }, [all, custom])
  const shown = glasses.filter((g) => (source === 'all' || g.catalog === source) && (!hideObsolete || g.status !== 'obsolete' || sel.has(g.name)) && (!q || g.name.toLowerCase().includes(q.toLowerCase())))
  const cur = glasses.find((g) => g.name === (current ?? '').toUpperCase())
  const nearest = () => {
    if (!cur || cur.nd === null || cur.vd === null) return
    const pool = source === 'all' ? glasses : glasses.filter((g) => g.catalog === source)
    const near = nearestGlasses({ nd: cur.nd, vd: cur.vd }, pool, nNear + 1, { includeObsolete: !hideObsolete })
    setSel(new Set([...sel, cur.name, ...near]))
  }
  return (
    <>
      <Button
        variant="link"
        className="w-full truncate px-2 text-left"
        onClick={() => {
          setSel(new Set(value ?? []))
          setOpen(true)
        }}
      >
        {value === null ? t('opt.allGlasses') : `${value.length} ${t('opt.candidates')}`}
      </Button>
      {open && (
        <Dialog
          title={t('opt.candidateGlasses')}
          onClose={() => setOpen(false)}
          width={620}
          footer={
            <>
              <Button
                variant="ghost"
                onClick={() => {
                  onChange(null)
                  setOpen(false)
                }}
              >
                {t('opt.allGlasses')}
              </Button>
              <div className="flex-1" />
              <span className="text-small text-muted">
                {sel.size} {t('opt.selected')}
              </span>
              <Button
                variant="primary"
                disabled={sel.size < 2}
                onClick={() => {
                  onChange([...sel])
                  setOpen(false)
                }}
              >
                {t('c.ok')}
              </Button>
            </>
          }
        >
          <div className="mb-2 flex flex-wrap items-center gap-2 text-small">
            <input className="field-input h-6 w-36" placeholder={t('opt.searchGlass')} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.stopPropagation()} />
            <Select
              className="h-6 w-40 text-small"
              ariaLabel={t('mat.sourceFilter')}
              value={source}
              options={[{ value: 'all', label: t('mat.srcAll') }, { value: 'built-in', label: t('mat.srcBuiltin') }, ...(custom.length ? [{ value: 'project', label: t('mat.srcProject') }] : []), ...catalogs.map((c) => ({ value: c.name, label: c.name }))]}
              onChange={setSource}
            />
            <Checkbox checked={hideObsolete} onChange={setHideObsolete} label={t('mat.stNoObsolete')} />
          </div>
          <div className="mb-2 flex flex-wrap items-center gap-2 text-small">
            <Button size="sm" disabled={!cur || cur.nd === null} onClick={nearest} title={t('opt.nearestHint')}>
              {t('opt.nearest')}
            </Button>
            <NumberField className="h-6 w-14" value={nNear} min={1} max={200} onCommit={(v) => v !== null && setNNear(Math.round(v))} ariaLabel={t('opt.nearest')} />
            <span className="text-muted">{cur ? t('opt.nearestTo', { name: cur.name }) : ''}</span>
            <span className="flex-1" />
            <Button size="sm" variant="ghost" onClick={() => setSel(new Set([...sel, ...shown.map((g) => g.name)]))}>
              {t('opt.selectShown')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSel(new Set())}>
              {t('opt.clearSel')}
            </Button>
          </div>
          <div className="grid max-h-[340px] grid-cols-3 gap-x-3 gap-y-1 overflow-auto p-1">
            {shown.slice(0, 900).map((g) => (
              <Checkbox
                key={g.name}
                checked={sel.has(g.name)}
                onChange={(on) => {
                  const n = new Set(sel)
                  if (on) n.add(g.name)
                  else n.delete(g.name)
                  setSel(n)
                }}
                title={g.nd !== null ? `nd ${fmt(g.nd, 6)} · Vd ${fmt(g.vd, 4)}${g.catalog ? ` · ${g.catalog}` : ''}` : undefined}
                label={<span className={`num text-small ${g.status === 'obsolete' ? 'text-faint' : ''}`}>{g.name}</span>}
              />
            ))}
          </div>
          {shown.length > 900 && <div className="mt-1 text-small text-faint">{t('mat.refine', { n: shown.length - 900 })}</div>}
          <div className="mt-2 text-caption text-faint">{t('opt.candidatesHelp')}</div>
        </Dialog>
      )}
    </>
  )
}
