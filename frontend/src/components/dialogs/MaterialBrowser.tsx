import { AlertTriangle, BookOpen, Download, FlaskConical, Library, Pencil, Plus, Trash2, Upload } from 'lucide-react'
import { materialUsers } from '../../lib/references'
import { useEffect, useMemo, useState } from 'react'
import { confirmAction } from '../../store/confirmStore'
import { importAgfFile } from '../../actions'
import { api } from '../../lib/api'
import { fmt } from '../../lib/format'
import { recordsFor } from '../../lib/glassCatalog'
import { useT } from '../../lib/i18n'
import { pickFile } from '../../lib/storage'
import type { GlassCatalog, MaterialRecord, MaterialSummary } from '../../lib/types'
import { useCatalogStore } from '../../store/catalogStore'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { Plot } from '../common/Plot'
import { Badge, Button, Checkbox, Dialog, IconButton, NumberField, Select, TextField } from '../common/ui'
import { cx } from '../common/uiUtils'
import { Label } from '../common/controls'
import { RiiInstaller } from './RiiInstaller'
import { DATA } from '../../lib/palette'

const FORMULAS: { value: MaterialRecord['formula']; label: string; hint: string }[] = [
  { value: 'sellmeier', label: 'Sellmeier', hint: 'B1, C1, B2, C2, … with C in µm²: n² − 1 = Σ B λ²/(λ² − C)' },
  { value: 'sellmeier_sq', label: 'Sellmeier (C in µm)', hint: 'B1, C1, … with n² − 1 = Σ B λ²/(λ² − C²)' },
  { value: 'schott', label: 'Schott', hint: 'A0 … A5: n² = A0 + A1λ² + A2λ⁻² + A3λ⁻⁴ + A4λ⁻⁶ + A5λ⁻⁸' },
  { value: 'extended', label: 'Extended', hint: 'A0 … A7: n² = A0 + A1λ² + A2λ⁻² + A3λ⁻⁴ + A4λ⁻⁶ + A5λ⁻⁸ + A6λ⁻¹⁰ + A7λ⁻¹²' },
  { value: 'extended2', label: 'Extended 2', hint: 'A0 … A7: n² = A0 + A1λ² + A2λ⁻² + A3λ⁻⁴ + A4λ⁻⁶ + A5λ⁻⁸ + A6λ⁴ + A7λ⁶' },
  { value: 'extended3', label: 'Extended 3', hint: 'A0 … A8: n² = A0 + A1λ² + A2λ⁴ + A3λ⁻² + A4λ⁻⁴ + A5λ⁻⁶ + A6λ⁻⁸ + A7λ⁻¹⁰ + A8λ⁻¹²' },
  { value: 'sellmeier2', label: 'Sellmeier 2', hint: 'A, B1, λ1, B2, λ2: n² − 1 = A + B1λ²/(λ² − λ1²) + B2/(λ² − λ2²)' },
  { value: 'sellmeier4', label: 'Sellmeier 4', hint: 'A, B, C, D, E: n² = A + Bλ²/(λ² − C) + Dλ²/(λ² − E)' },
  { value: 'herzberger', label: 'Herzberger', hint: 'A … F: n = A + BL + CL² + Dλ² + Eλ⁴ + Fλ⁶, L = 1/(λ² − 0.028)' },
  { value: 'conrady', label: 'Conrady', hint: 'n0, A, B: n = n0 + A/λ + B/λ^3.5' },
  { value: 'handbook1', label: 'Handbook 1', hint: 'A, B, C, D: n² = A + B/(λ² − C) − Dλ²' },
  { value: 'handbook2', label: 'Handbook 2', hint: 'A, B, C, D: n² = A + Bλ²/(λ² − C) − Dλ²' },
  { value: 'cauchy', label: 'Cauchy', hint: 'A, B, C: n = A + B/λ² + C/λ⁴' },
  { value: 'polynomial', label: 'Polynomial', hint: 'A, c1, e1, c2, e2, …: n² = A + Σ c λ^e (refractiveindex.info formula 3)' },
  { value: 'constant', label: 'Constant', hint: 'n' },
  { value: 'tabulated', label: 'Tabulated (measured)', hint: 'λ (µm), n pairs — monotone cubic interpolation' },
]

type SourceFilter = 'all' | 'builtin' | 'project' | `cat:${string}`
type StatusFilter = 'all' | 'no-obsolete' | 'preferred'
type Row = MaterialSummary & { project: boolean }

function StatusBadge({ s }: { s?: string }) {
  const t = useT()
  if (!s || s === 'standard') return null
  const tone = s === 'preferred' ? 'ok' : s === 'obsolete' ? 'danger' : 'default'
  return <Badge tone={tone}>{t(`mat.status.${s}`)}</Badge>
}

export function MaterialBrowser() {
  const t = useT()
  const close = useUiStore((s) => s.closeDialog)
  const toast = useUiStore((s) => s.toast)
  const builtin = useEngineStore((s) => s.materials)
  const catalogs = useCatalogStore((s) => s.catalogs)
  const index = useCatalogStore((s) => s.index)
  const custom = useProjectStore((s) => s.project.custom_materials)
  const selection = useProjectStore((s) => s.selection)
  const nSurf = useProjectStore((s) => s.project.system.surfaces.length)
  const updateSurfaces = useProjectStore((s) => s.updateSurfaces)
  const updateProject = useProjectStore((s) => s.updateProject)
  const [q, setQ] = useState('')
  const [source, setSource] = useState<SourceFilter>('all')
  const [status, setStatus] = useState<StatusFilter>('no-obsolete')
  const [picked, setPicked] = useState<string[]>(['N-BK7', 'F2'])
  const [range, setRange] = useState<[number, number]>([0.4, 0.8])
  const [fetchedCurves, setCurves] = useState<Awaited<ReturnType<typeof api.materialCurves>> | null>(null)
  const curves = picked.length ? fetchedCurves : null // nothing picked: no plot, whatever was fetched last
  const [probe, setProbe] = useState(0.5875618)
  const [probeOut, setProbeOut] = useState<Record<string, number>>({})
  const [editing, setEditing] = useState<MaterialRecord | null>(null)
  const [report, setReport] = useState<GlassCatalog | null>(null)
  const [installer, setInstaller] = useState(false)
  const [customSummaries, setCustomSummaries] = useState<MaterialSummary[]>([])
  const [error, setError] = useState<string | null>(null)

  // summaries for custom materials (validated by the engine)
  useEffect(() => {
    let alive = true
    Promise.all(custom.map((c) => api.validateMaterial(c).then((r) => r.material).catch(() => null))).then((r) => alive && setCustomSummaries(r.filter(Boolean) as MaterialSummary[]))
    return () => {
      alive = false
    }
  }, [custom])

  // project materials first, then built-in, then the addressable catalogue glasses
  const all = useMemo<Row[]>(() => {
    const names = new Set(customSummaries.map((c) => c.name))
    const cat = [...index.byName.values()].map((g) => g.summary).filter((s) => !names.has(s.name))
    return [
      ...customSummaries.map((c) => ({ ...c, builtin: false, project: true })),
      ...builtin.filter((c) => !names.has(c.name)).map((c) => ({ ...c, project: false })),
      ...cat.map((c) => ({ ...c, project: false })),
    ]
  }, [builtin, customSummaries, index])

  const filtered = useMemo(() => {
    const s = q.toLowerCase()
    return all.filter((m) => {
      if (source === 'builtin' && !m.builtin) return false
      if (source === 'project' && !m.project) return false
      if (source.startsWith('cat:') && m.catalog !== source.slice(4)) return false
      if (status === 'no-obsolete' && m.status === 'obsolete' && !picked.includes(m.name)) return false
      if (status === 'preferred' && m.status !== 'preferred' && !picked.includes(m.name)) return false
      return !s || m.name.toLowerCase().includes(s) || (m.family ?? '').toLowerCase().includes(s) || (m.source ?? '').toLowerCase().includes(s) || (m.category ?? '').toLowerCase().includes(s)
    })
  }, [all, q, source, status, picked])

  // catalogue glasses are not in the project yet: their definitions go with the request
  const requestMaterials = useMemo(() => [...custom, ...recordsFor(picked, index, custom)], [custom, picked, index])

  useEffect(() => {
    if (!picked.length) return
    const h = setTimeout(() => {
      api
        .materialCurves(picked, range[0], range[1], 161, requestMaterials)
        .then((r) => {
          setCurves(r)
          setError(null)
        })
        .catch((e) => setError(e.message))
      api
        .resolveIndex(picked, [probe], requestMaterials)
        .then((r) => setProbeOut(Object.fromEntries(Object.entries(r.materials).map(([k, v]) => [k, v.index[0]]))))
        .catch(() => setProbeOut({}))
    }, 120)
    return () => clearTimeout(h)
  }, [picked, range, probe, requestMaterials])

  const toggle = (name: string) => setPicked((p) => (p.includes(name) ? p.filter((x) => x !== name) : [...p, name].slice(-8)))
  const assignable = selection.filter((i) => i > 0 && i < nSurf - 1)
  const single = picked.length === 1 ? all.find((m) => m.name === picked[0]) : undefined

  const saveCustom = async (rec: MaterialRecord) => {
    try {
      await api.validateMaterial(rec)
      updateProject((p) => {
        const i = p.custom_materials.findIndex((m) => m.name.toUpperCase() === rec.name.toUpperCase())
        if (i >= 0) p.custom_materials[i] = rec
        else p.custom_materials.push(rec)
      }, `Save material ${rec.name}`)
      setEditing(null)
      setPicked((p) => [...new Set([...p, rec.name.toUpperCase()])])
      toast('success', `Material ${rec.name} saved to project`)
    } catch (e) {
      toast('error', (e as Error).message)
    }
  }

  const importCsv = async () => {
    const f = await pickFile('.csv,.txt')
    if (!f) return
    const text = await f.text()
    const rows: number[][] = []
    for (const line of text.split(/\r?\n/)) {
      const parts = line.split(/[,;\t ]+/).filter(Boolean).map(Number)
      if (parts.length >= 2 && parts.every(Number.isFinite)) rows.push([parts[0] > 50 ? parts[0] / 1000 : parts[0], parts[1]])
    }
    if (rows.length < 2) return toast('error', 'CSV needs at least two numeric rows: wavelength (µm or nm), index')
    setEditing({ name: f.name.replace(/\.[^.]+$/, '').toUpperCase().replace(/[^A-Z0-9_-]/g, '_'), formula: 'tabulated', coefficients: [], table: rows, family: 'MEASURED', category: 'user', source: `Imported from ${f.name}` })
  }

  const importAgf = async () => {
    const cat = await importAgfFile()
    if (!cat) return
    setSource(`cat:${cat.name}`)
    setInstaller(false)
    setReport(cat)
  }

  const glassMap = filtered.filter((m) => m.vd && m.nd)
  const SHOWN = 1500

  return (
    <Dialog title={t('mat.title')} onClose={close} width={1240} icon={<FlaskConical size={16} className="text-accent" />}>
      <div className="grid h-[74vh] grid-cols-[minmax(470px,1fr)_minmax(470px,1.1fr)]">
        {/* list */}
        <div className="flex min-h-0 flex-col border-r border-line">
          <div className="flex items-center gap-2 border-b border-line p-2">
            <input autoFocus className="field-input min-w-0 flex-1" aria-label={t('mat.search')} placeholder={t('mat.search')} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.stopPropagation()} />
            <Button size="sm" onClick={() => setEditing({ name: 'MYGLASS', formula: 'sellmeier', coefficients: [1.0, 0.006, 0.2, 0.02, 1.0, 100], lambda_min: 0.4, lambda_max: 2.5, family: 'USER', category: 'glass', source: 'User-defined' })}>
              <Plus size={14} /> {t('mat.new')}
            </Button>
            <Button size="sm" onClick={importCsv} title={t('mat.importCsv')}>
              <Upload size={14} /> CSV
            </Button>
            <Button size="sm" onClick={importAgf} title={t('mat.importAgfHint')}>
              <Library size={14} /> AGF
            </Button>
            <Button
              size="sm"
              onClick={() => {
                setEditing(null)
                setReport(null)
                setInstaller(true)
              }}
              title={t('rii.buttonHint')}
            >
              <Download size={14} /> {t('rii.button')}
            </Button>
          </div>
          <div className="flex items-center gap-2 border-b border-line px-2 py-1.5 text-small">
            <Select<SourceFilter>
              className="h-6 w-44 text-small"
              ariaLabel={t('mat.sourceFilter')}
              value={source}
              options={[
                { value: 'all', label: t('mat.srcAll') },
                { value: 'builtin', label: t('mat.srcBuiltin') },
                { value: 'project', label: t('mat.srcProject') },
                ...catalogs.map((c) => ({ value: `cat:${c.name}` as SourceFilter, label: `${c.name} (${c.records.length})` })),
              ]}
              onChange={setSource}
            />
            <Select<StatusFilter>
              className="h-6 w-40 text-small"
              ariaLabel={t('mat.statusFilter')}
              value={status}
              options={[
                { value: 'all', label: t('mat.stAll') },
                { value: 'no-obsolete', label: t('mat.stNoObsolete') },
                { value: 'preferred', label: t('mat.stPreferred') },
              ]}
              onChange={setStatus}
            />
            <span className="flex-1" />
            <span className="text-faint">
              {filtered.length} / {all.length}
            </span>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            <table className="eng-table">
              <thead>
                <tr>
                  <th className="w-6"></th>
                  <th>{t('mat.name')}</th>
                  <th>{t('mat.family')}</th>
                  <th className="text-right">nd</th>
                  <th className="pr-4 text-right">Vd</th>
                  <th>{t('mat.formula')}</th>
                  <th>{t('mat.range')}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.slice(0, SHOWN).map((m) => (
                  <tr key={m.name} className={cx('cursor-pointer', picked.includes(m.name) && 'selected', m.status === 'obsolete' && 'opacity-60')} onClick={() => toggle(m.name)} title={m.source}>
                    <td className="px-2">
                      <input type="checkbox" readOnly checked={picked.includes(m.name)} aria-label={`${t('mat.compare')}: ${m.name}`} className="accent-[var(--c-accent)]" />
                    </td>
                    <td className="px-2 font-medium whitespace-nowrap">
                      {m.name} {m.project && <Badge tone="accent">{t('mat.project')}</Badge>} <StatusBadge s={m.status} />{' '}
                      {m.verified === false && (
                        <span className="text-warn" title={t('mat.unverified')}>
                          <AlertTriangle size={12} className="inline" />
                        </span>
                      )}
                    </td>
                    <td className="px-2 text-muted">{m.family}</td>
                    <td className="num px-2 text-right">{fmt(m.nd, 6)}</td>
                    <td className="num py-0 pr-4 pl-2 text-right">{fmt(m.vd, 4)}</td>
                    <td className="px-2 text-muted">{m.formula}</td>
                    <td className="num px-2 text-muted">
                      {fmt(m.lambda_min, 3)}–{m.lambda_max === null || m.lambda_max === undefined ? '∞' : fmt(m.lambda_max, 3)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filtered.length > SHOWN && <div className="p-2 text-center text-small text-faint">{t('mat.refine', { n: filtered.length - SHOWN })}</div>}
          </div>
          {/* catalogues */}
          <div className="border-t border-line p-2 text-small">
            <div className="mb-1 flex items-center gap-1.5 font-semibold text-muted">
              <BookOpen size={12} /> {t('mat.catalogs')}
            </div>
            {catalogs.length === 0 ? (
              <div className="leading-relaxed text-faint">{t('mat.noCatalogs')}</div>
            ) : (
              <div className="max-h-24 space-y-0.5 overflow-auto">
                {catalogs.map((c) => {
                  const flagged = c.records.filter((r) => r.verified === false).length
                  const shadow = index.shadowed.filter((x) => x.catalog === c.name).length
                  return (
                    <div key={c.id} className="flex items-center gap-2">
                      <Button variant="link" className="font-medium" onClick={() => setSource(`cat:${c.name}`)}>
                        {c.name}
                      </Button>
                      <span className="text-faint">
                        {c.records.length} {t('mat.glasses')} · {new Date(c.imported_at).toLocaleDateString()}
                        {flagged ? ` · ${flagged} ${t('mat.flagged')}` : ''}
                        {shadow ? ` · ${shadow} ${t('mat.shadowed')}` : ''}
                      </span>
                      <span className="flex-1" />
                      <Button
                        variant="link"
                        onClick={() => {
                          setInstaller(false)
                          setReport(c)
                        }}
                      >
                        {t('mat.report')}
                      </Button>
                      <IconButton
                        size="sm"
                        tone="danger"
                        title={t('mat.deleteCatalog')}
                        onClick={async () => {
                          if (await confirmAction({ title: t('mat.deleteCatalogTitle'), message: t('mat.deleteCatalogConfirm', { name: c.name }), confirmLabel: t('c.delete'), cancelLabel: t('c.cancel'), danger: true })) {
                            void useCatalogStore.getState().remove(c.id)
                            if (source === `cat:${c.name}`) setSource('all')
                            if (report?.id === c.id) setReport(null)
                          }
                        }}
                      >
                        <Trash2 size={12} />
                      </IconButton>
                    </div>
                  )
                })}
              </div>
            )}
            <div className="mt-1 leading-relaxed text-faint">{t('mat.dataNote')}</div>
          </div>
        </div>

        {/* detail */}
        <div className="flex min-h-0 flex-col">
          {editing ? (
            <MaterialEditor rec={editing} onCancel={() => setEditing(null)} onSave={saveCustom} />
          ) : installer ? (
            <RiiInstaller onClose={() => setInstaller(false)} onInstalled={(c) => setSource(`cat:${c}`)} />
          ) : report ? (
            <CatalogReport cat={report} shadowed={index.shadowed.filter((x) => x.catalog === report.name)} onClose={() => setReport(null)} />
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2 border-b border-line p-2 text-small">
                <span className="text-muted">λ</span>
                <NumberField className="h-6 w-16" ariaLabel="λ min (µm)" value={range[0]} min={0.1} max={30} onCommit={(v) => v !== null && setRange([v, Math.max(v + 0.01, range[1])])} />
                <span className="text-muted">–</span>
                <NumberField className="h-6 w-16" ariaLabel="λ max (µm)" value={range[1]} min={0.11} max={30} onCommit={(v) => v !== null && setRange([Math.min(range[0], v - 0.01), v])} />
                <span className="text-muted">µm</span>
                <span className="ml-3 text-muted">{t('mat.inspect')}</span>
                <NumberField className="h-6 w-24" ariaLabel={t('mat.inspect')} value={probe} min={0.1} max={30} units={{ nm: 1e-3, um: 1, µm: 1 }} onCommit={(v) => v !== null && setProbe(v)} />
                <span className="text-muted">µm</span>
                <div className="flex-1" />
                <Button
                  size="sm"
                  variant="primary"
                  disabled={!assignable.length || picked.length !== 1}
                  onClick={() => {
                    updateSurfaces(assignable, { material: picked[0] }, `Assign ${picked[0]}`)
                    toast('success', `${picked[0]} → ${assignable.length} surface(s)`)
                  }}
                >
                  {t('mat.assign')} ({assignable.length})
                </Button>
              </div>
              {error && <div className="p-2 text-danger">{error}</div>}
              <div className="min-h-0 flex-[1.2]">
                {curves && (
                  <Plot
                    data={[
                      ...curves.curves.map((c) => ({ type: 'scatter' as const, mode: 'lines' as const, x: curves.wavelength_um, y: c.index, name: c.name, hovertemplate: `${c.name}<br>λ %{x:.4f} µm<br>n %{y:.6f}<extra></extra>` })),
                      // the extinction coefficient of films and metals (N = n − ik) on the right axis
                      ...curves.curves
                        .filter((c) => c.k)
                        .map((c) => ({ type: 'scatter' as const, mode: 'lines' as const, x: curves.wavelength_um, y: c.k!, name: `${c.name} k`, yaxis: 'y2', line: { dash: 'dot' as const }, hovertemplate: `${c.name}<br>λ %{x:.4f} µm<br>k %{y:.4g}<extra></extra>` })),
                    ]}
                    layout={{
                      title: { text: t('mat.dispersionCurve'), font: { size: 11.5 } },
                      xaxis: { title: { text: t('ax.wavelengthUm') } },
                      yaxis: { title: { text: t('ax.index') } },
                      ...(curves.curves.some((c) => c.k) ? { yaxis2: { title: { text: 'k' }, overlaying: 'y', side: 'right', showgrid: false, rangemode: 'tozero' } } : {}),
                      margin: { l: 60, r: curves.curves.some((c) => c.k) ? 48 : 12, t: 30, b: 70 },
                    }}
                  />
                )}
              </div>
              <div className="grid min-h-0 flex-1 grid-cols-2 border-t border-line">
                <div className="min-h-0">
                  <Plot
                    data={[
                      {
                        type: glassMap.length > 600 ? 'scattergl' : 'scatter',
                        mode: 'markers',
                        x: glassMap.map((m) => m.vd!),
                        y: glassMap.map((m) => m.nd!),
                        text: glassMap.map((m) => `${m.name}${m.catalog ? ` (${m.catalog})` : ''}`),
                        marker: { size: glassMap.map((m) => (picked.includes(m.name) ? 9 : 5)), color: glassMap.map((m) => (picked.includes(m.name) ? DATA.selection : m.status === 'preferred' ? 'var(--c-ok)' : m.status === 'obsolete' ? 'var(--c-faint)' : 'var(--c-muted)')) },
                        hovertemplate: '%{text}<br>Vd %{x:.2f}<br>nd %{y:.5f}<extra></extra>',
                        name: 'glass',
                      },
                    ]}
                    layout={{ title: { text: t('mat.glassMap'), font: { size: 11.5 } }, xaxis: { title: { text: 'Vd' }, autorange: 'reversed' }, yaxis: { title: { text: 'nd' } }, showlegend: false, margin: { l: 52, r: 10, t: 28, b: 38 } }}
                  />
                </div>
                <div className="min-h-0 overflow-auto border-l border-line">
                  <table className="eng-table">
                    <thead>
                      <tr>
                        <th>{t('mat.name')}</th>
                        <th className="text-right">n({fmt(probe, 6)} µm)</th>
                        <th className="text-right">nF − nC</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {picked.map((n) => {
                        const s = all.find((m) => m.name === n)
                        const out = s && (probe < (s.lambda_min ?? 0) || (s.lambda_max !== null && s.lambda_max !== undefined && probe > s.lambda_max))
                        return (
                          <tr key={n}>
                            <td className="px-2 font-medium" title={s?.source}>
                              {n}
                            </td>
                            <td className={cx('num px-2 text-right', out && 'text-warn')} title={out ? 'Outside the data range: extrapolated' : undefined}>
                              {fmt(probeOut[n], 8)}
                              {out ? ' ⚠' : ''}
                            </td>
                            <td className="num px-2 text-right">{fmt(s?.nF_minus_nC, 5)}</td>
                            <td className="px-1 text-right whitespace-nowrap">
                              {s && s.project && (
                                <>
                                  <IconButton size="sm" title={t('c.edit')} onClick={() => setEditing(custom.find((c) => c.name.toUpperCase() === n) ?? null)}>
                                    <Pencil size={12} />
                                  </IconButton>
                                  <IconButton
                                    size="sm"
                                    tone="danger"
                                    title={t('mat.delete')}
                                    onClick={() => {
                                      // a material still in use would make every analysis fail ('unknown material')
                                      const users = materialUsers(useProjectStore.getState().project, n)
                                      if (users.length) return useUiStore.getState().toast('error', t('mat.inUse', { name: n, list: users.join(', ') }))
                                      updateProject((p) => {
                                        p.custom_materials = p.custom_materials.filter((c) => c.name.toUpperCase() !== n)
                                      }, `Delete material ${n}`)
                                    }}
                                  >
                                    <Trash2 size={12} />
                                  </IconButton>
                                </>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                  {single && <GlassCard m={single} />}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </Dialog>
  )
}

/** Catalogue data of one glass (only what the record carries). */
function GlassCard({ m }: { m: MaterialSummary }) {
  const t = useT()
  const rows: [string, string][] = []
  if (m.catalog) rows.push([t('mat.catalog'), m.catalog])
  if (m.status) rows.push([t('mat.statusLabel'), t(`mat.status.${m.status}`)])
  if (m.mil) rows.push(['MIL / code', m.mil])
  if (m.extraordinary) rows.push([t('mat.uniaxial'), `nₒ ${fmt(m.nd, 6)} · nₑ ${fmt(m.extraordinary.ne_d ?? null, 6)} (d)`])
  if (m.nd_ref !== null && m.nd_ref !== undefined) rows.push([t('mat.ndRef'), `${fmt(m.nd_ref, 6)} (Δ ${fmt((m.nd ?? NaN) - m.nd_ref, 2)})`])
  if (m.vd_ref !== null && m.vd_ref !== undefined) rows.push([t('mat.vdRef'), `${fmt(m.vd_ref, 4)} (Δ ${fmt((m.vd ?? NaN) - m.vd_ref, 2)})`])
  if (m.density !== undefined) rows.push([t('mat.density'), `${fmt(m.density, 4)} g/cm³`])
  if (m.tce_m30_70 !== undefined) rows.push(['TCE (−30…70 °C)', `${fmt(m.tce_m30_70, 3)} ×10⁻⁶/K`])
  if (m.dpgf !== undefined) rows.push(['ΔPg,F', fmt(m.dpgf, 4)])
  if (m.relative_cost !== undefined) rows.push([t('mat.cost'), fmt(m.relative_cost, 3)])
  rows.push([t('mat.thermal'), m.has_thermal_model ? t('mat.thermalYes') : '—'])
  if (m.comment) rows.push([t('mat.comment'), m.comment])
  const it = m.internal_transmission ?? []
  return (
    <div className="border-t border-line p-2 text-small">
      <div className="mb-1 flex items-center gap-1.5 font-semibold">
        {m.name} <StatusBadge s={m.status} />
      </div>
      {m.verified === false && <div className="mb-1 rounded bg-warn/10 px-1.5 py-1 text-warn">{t('mat.unverified')}</div>}
      <div className="grid grid-cols-[110px_1fr] gap-x-2 gap-y-0.5">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <span className="text-muted">{k}</span>
            <span className="num">{v}</span>
          </div>
        ))}
      </div>
      {it.length > 0 && (
        <details className="mt-1">
          <summary className="cursor-pointer text-muted">
            {t('mat.internalT')} ({it.length})
          </summary>
          <table className="eng-table mt-1">
            <thead>
              <tr>
                <th className="text-right">λ (µm)</th>
                <th className="text-right">τᵢ</th>
                <th className="text-right">{t('mat.thickness')} (mm)</th>
              </tr>
            </thead>
            <tbody>
              {[...it]
                .sort((a, b) => a[0] - b[0])
                .map((r, k) => (
                  <tr key={k}>
                    <td className="num px-2 text-right">{fmt(r[0], 4)}</td>
                    <td className="num px-2 text-right">{fmt(r[1], 4)}</td>
                    <td className="num px-2 text-right">{fmt(r[2], 3)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
          <div className="mt-1 text-faint">{t('mat.internalTNote')}</div>
        </details>
      )}
    </div>
  )
}

function CatalogReport({ cat, shadowed, onClose }: { cat: GlassCatalog; shadowed: { name: string; by: string }[]; onClose: () => void }) {
  const t = useT()
  const counts: Record<string, number> = {}
  for (const r of cat.records) counts[r.status ?? 'standard'] = (counts[r.status ?? 'standard'] ?? 0) + 1
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b border-line px-3 py-2">
        <Library size={14} className="text-accent" />
        <span className="text-body font-semibold">
          {cat.name} — {t('mat.importReport')}
        </span>
        <span className="flex-1" />
        <Button size="sm" onClick={onClose}>
          {t('c.close')}
        </Button>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-auto p-3 text-small">
        <div className="text-muted">
          {cat.filename} · {new Date(cat.imported_at).toLocaleString()} · {cat.records.length} {t('mat.glasses')} (
          {Object.entries(counts)
            .map(([k, n]) => `${n} ${t(`mat.status.${k}`).toLowerCase()}`)
            .join(', ')}
          )
        </div>
        {cat.comments.length > 0 && <div className="rounded border border-line bg-panel-2 p-2 whitespace-pre-wrap text-faint">{cat.comments.join('\n')}</div>}
        {shadowed.length > 0 && (
          <div className="rounded bg-warn/10 px-2 py-1 text-warn">
            {t('mat.shadowedNote')}: {shadowed.map((s) => `${s.name} (${s.by})`).join(', ')}
          </div>
        )}
        <table className="eng-table">
          <tbody>
            {cat.diagnostics.map((d, k) => (
              <tr key={k}>
                <td className={cx('px-2 font-semibold whitespace-nowrap', d.level === 'error' ? 'text-danger' : d.level === 'warning' ? 'text-warn' : 'text-ok')}>{d.level}</td>
                <td className="px-2 font-medium whitespace-nowrap">{d.glass ?? ''}</td>
                <td className="px-2">{d.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function MaterialEditor({ rec, onCancel, onSave }: { rec: MaterialRecord; onCancel: () => void; onSave: (r: MaterialRecord) => void }) {
  const t = useT()
  const [r, setR] = useState<MaterialRecord>(rec)
  const [coefText, setCoefText] = useState(rec.formula === 'tabulated' ? (rec.table ?? []).map((x) => x.join(', ')).join('\n') : rec.coefficients.join(', '))
  const [summary, setSummary] = useState<MaterialSummary | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const build = (): MaterialRecord | null => {
    const out: MaterialRecord = { ...r, name: r.name.trim().toUpperCase() }
    if (r.formula === 'tabulated') {
      const rows = coefText
        .split(/\n/)
        .map((l) => l.split(/[,;\s]+/).filter(Boolean).map(Number))
        .filter((x) => x.length >= 2)
      if (rows.some((x) => x.some((v) => !Number.isFinite(v)))) return null
      out.table = rows.map((x) => [x[0], x[1]])
      out.coefficients = []
    } else {
      const c = coefText.split(/[,;\s]+/).filter(Boolean).map(Number)
      if (c.some((v) => !Number.isFinite(v))) return null
      out.coefficients = c
      out.table = null
    }
    return out
  }

  useEffect(() => {
    const b = build()
    if (!b) return setErr(t('mat.coefNumbers'))
    const h = setTimeout(() => {
      api
        .validateMaterial(b)
        .then((x) => {
          setSummary(x.material)
          setErr(null)
        })
        .catch((e) => {
          setSummary(null)
          setErr(e.message)
        })
    }, 200)
    return () => clearTimeout(h)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [r, coefText])

  const hint = FORMULAS.find((f) => f.value === r.formula)?.hint
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-line px-3 py-2 text-body font-semibold">{t('mat.custom')}</div>
      <div className="min-h-0 flex-1 space-y-2 overflow-auto p-3">
        <div className="grid grid-cols-[120px_1fr] items-center gap-2">
          <span className="text-muted">{t('mat.name')}</span>
          <TextField ariaLabel={t('mat.name')} value={r.name} onCommit={(v) => setR({ ...r, name: v })} />
          <span className="text-muted">{t('mat.formula')}</span>
          <Select ariaLabel={t('mat.formula')} value={r.formula} options={FORMULAS.map((f) => ({ value: f.value, label: f.label }))} onChange={(v) => setR({ ...r, formula: v })} />
          <span className="text-muted">{t('mat.lambdaRange')}</span>
          <div className="flex gap-1">
            <NumberField className="w-24" ariaLabel={`${t('mat.lambdaRange')}: min`} value={r.lambda_min ?? 0} min={0} onCommit={(v) => setR({ ...r, lambda_min: v ?? 0 })} />
            <NumberField className="w-24" ariaLabel={`${t('mat.lambdaRange')}: max`} value={r.lambda_max ?? null} allowInfinity onCommit={(v) => setR({ ...r, lambda_max: v })} />
          </div>
          <span className="text-muted">{t('mat.absorption')}</span>
          <NumberField className="w-24" ariaLabel={t('mat.absorption')} value={r.absorption_per_mm ?? 0} min={0} onCommit={(v) => setR({ ...r, absorption_per_mm: v ?? 0 })} />
          <span className="text-muted">{t('mat.source')}</span>
          <TextField ariaLabel={t('mat.source')} value={r.source ?? ''} onCommit={(v) => setR({ ...r, source: v })} />
        </div>
        <div>
          <div className="mb-1 text-muted">
            {t('mat.coefficients')} <span className="text-small text-faint">— {hint}</span>
          </div>
          <textarea className="field-input num h-36 w-full py-1" value={coefText} onChange={(e) => setCoefText(e.target.value)} onKeyDown={(e) => e.stopPropagation()} />
        </div>
        {/* thermal data used by the environment model (engine: environment.py) */}
        <div className="space-y-1.5 rounded-md border border-line p-2">
          <div className="text-small font-semibold text-muted">{t('mat.thermalData')}</div>
          <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-2">
            <Label form hint={t('mat.cteHint')}>{t('mat.cte')}</Label>
            <NumberField className="w-24" optional ariaLabel={t('mat.cte')} value={r.tce_m30_70 ?? null} min={-50} max={500} onCommit={(v) => setR({ ...r, tce_m30_70: v ?? undefined })} />
          </div>
          <span title={t('mat.dndtHint')}>
            <Checkbox
              checked={!!r.thermal}
              onChange={(on) => setR({ ...r, thermal: on ? { D0: 0, D1: 0, D2: 0, E0: 0, E1: 0, lambda_tk: 0.2, T0: 20 } : null })}
              label={<span className="text-small">{t('mat.dndt')}</span>}
            />
          </span>
          {r.thermal && (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-x-3 gap-y-1">
              {(['D0', 'D1', 'D2', 'E0', 'E1', 'lambda_tk', 'T0'] as const).map((k) => (
                <label key={k} className="flex items-center justify-between gap-2 text-small">
                  <span className="text-muted">{k === 'lambda_tk' ? 'λTK (µm)' : k === 'T0' ? 'T0 (°C)' : k}</span>
                  <NumberField className="w-24" ariaLabel={k} value={r.thermal![k]} onCommit={(v) => v !== null && setR({ ...r, thermal: { ...r.thermal!, [k]: v } })} />
                </label>
              ))}
            </div>
          )}
        </div>
        {err && <div className="rounded bg-danger/10 px-2 py-1 text-danger">{err}</div>}
        {summary && (
          <div className="grid grid-cols-3 gap-2 rounded-md border border-line p-2 num text-small">
            <div>nd {fmt(summary.nd, 7)}</div>
            <div>Vd {fmt(summary.vd, 5)}</div>
            <div>nF−nC {fmt(summary.nF_minus_nC, 5)}</div>
          </div>
        )}
      </div>
      <div className="flex justify-end gap-2 border-t border-line p-2">
        <Button onClick={onCancel}>{t('c.cancel')}</Button>
        <Button variant="primary" disabled={!!err || !summary} onClick={() => build() && onSave(build()!)}>
          {t('mat.saveCustom')}
        </Button>
      </div>
    </div>
  )
}

export function DispersionView() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const custom = useProjectStore((s) => s.project.custom_materials)
  const [curves, setCurves] = useState<Awaited<ReturnType<typeof api.materialCurves>> | null>(null)
  const mats = [...new Set(system.surfaces.map((s) => s.material).filter((m) => !['AIR', 'MIRROR', 'VACUUM'].includes(m)))]
  const lo = Math.max(0.2, Math.min(...system.wavelengths.map((w) => w.value)) - 0.05)
  const hi = Math.max(...system.wavelengths.map((w) => w.value)) + 0.05
  const key = mats.join(',') + lo + hi + JSON.stringify(custom)
  useEffect(() => {
    if (!mats.length) return setCurves(null)
    api
      .materialCurves(mats, lo, hi, 161, custom)
      .then(setCurves)
      .catch(() => setCurves(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  if (!mats.length) return <div className="p-6 text-muted">No glass in the system.</div>
  return (
    <div className="h-full">
      {curves && (
        <Plot
          data={[
            ...curves.curves.map((c) => ({ type: 'scatter' as const, mode: 'lines' as const, x: curves.wavelength_um, y: c.index, name: c.name, hovertemplate: `${c.name} n=%{y:.6f} @ %{x:.4f} µm<extra></extra>` })),
          ]}
          layout={{
            xaxis: { title: { text: t('ax.wavelengthUm') } },
            yaxis: { title: { text: 'n' } },
            shapes: system.wavelengths.map((w) => ({ type: 'line', x0: w.value, x1: w.value, yref: 'paper', y0: 0, y1: 1, line: { width: 1, dash: 'dot', color: DATA.reference } })),
          }}
        />
      )}
    </div>
  )
}
