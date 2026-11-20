// Stock lenses: browse the generic library and imported vendor catalogues, import vendor ZMX files or CSV,
// and insert a lens into the design (one undo step). Paraxial numbers come from the engine.
import { Boxes, FileUp, Plus, Trash2, Upload } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { insertStockLens } from '../../actions'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { pickFile, pickFiles } from '../../lib/storage'
import type { StockKind } from '../../lib/types'
import { useProjectStore } from '../../store/projectStore'
import { GENERIC_ID, useStockStore } from '../../store/stockStore'
import { useUiStore } from '../../store/uiStore'
import { Badge, Button, Checkbox, Dialog, Empty, NumberField, Select, Spinner } from '../common/ui'
import { cx } from '../common/uiUtils'
import { filterStock, type StockFilter } from './stockFilter'

const KINDS: StockKind[] = ['plano_convex', 'biconvex', 'best_form', 'meniscus', 'plano_concave', 'biconcave', 'achromat', 'other']
const SHOWN = 600
const toast = (kind: 'success' | 'warning' | 'error', text: string) => useUiStore.getState().toast(kind, text)

function toBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf)
  let bin = ''
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(bin)
}

export function StockLensDialog() {
  const t = useT()
  const close = useUiStore((s) => s.closeDialog)
  const arg = useUiStore((s) => s.dialogArg) as { at?: number } | null
  const { generic, catalogs, loadGeneric, importZmx, importCsv, remove } = useStockStore()
  const surfaces = useProjectStore((s) => s.project.system.surfaces)
  const selection = useProjectStore((s) => s.selection)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState<StockFilter>({ q: '', kind: 'all', glass: '', diameter: 0, catalog: 'all', fmin: null, fmax: null })
  const [picked, setPicked] = useState<string | null>(null)
  const [reversed, setReversed] = useState(false)
  const [gap, setGap] = useState(5)
  const [at, setAt] = useState(() => Math.max(1, Math.min(arg?.at ?? (selection[0] ?? 0) + 1, surfaces.length - 1)))
  const [catName, setCatName] = useState('My lenses')
  const [vendor, setVendor] = useState('')
  const [report, setReport] = useState<string[]>([])

  useEffect(() => {
    loadGeneric().catch((e: Error) => setError(e.message))
  }, [loadGeneric])

  const all = useMemo(
    () => [...(generic ?? []).map((lens) => ({ lens, catalogId: GENERIC_ID })), ...catalogs.flatMap((c) => c.lenses.map((lens) => ({ lens, catalogId: c.id })))],
    [generic, catalogs],
  )
  const glasses = useMemo(() => [...new Set(all.flatMap((x) => x.lens.materials.map((m) => m.toUpperCase())))].sort(), [all])
  const diameters = useMemo(() => [...new Set(all.map((x) => x.lens.diameter))].sort((a, b) => a - b), [all])
  const shown = filterStock(all, filter)
  const sel = all.find((x) => `${x.catalogId}:${x.lens.part}` === picked)
  const catalogFor = (id: string) => catalogs.find((c) => c.id === id)

  const doImportZmx = async () => {
    const files = await pickFiles('.zmx,.ZMX')
    if (!files.length) return
    setBusy(true)
    setError(null)
    try {
      const payload = await Promise.all(files.map(async (f) => ({ name: f.name, base64: toBase64(await f.arrayBuffer()) })))
      const r = await importZmx(payload, catName.trim() || 'My lenses', vendor.trim())
      setReport([t('st.imported', { n: r.added, name: r.catalog.name }), ...r.failed.map((f) => `${f.filename}: ${f.error}`)])
      toast(r.failed.length ? 'warning' : 'success', t('st.imported', { n: r.added, name: r.catalog.name }))
      setFilter((f) => ({ ...f, catalog: r.catalog.id }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const doImportCsv = async () => {
    const f = await pickFile('.csv,.CSV,.txt')
    if (!f) return
    setBusy(true)
    setError(null)
    try {
      const r = await importCsv(await f.text(), catName.trim() || 'My lenses')
      setReport([t('st.imported', { n: r.added, name: r.catalog.name }), ...r.errors])
      setFilter((x) => ({ ...x, catalog: r.catalog.id }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const insert = async () => {
    if (!sel) return
    const cat = catalogFor(sel.catalogId)
    try {
      if ((await insertStockLens(sel.lens, reversed, at, gap, cat?.custom_materials ?? [])) < 0) return // the design changed meanwhile
      toast('success', t('st.inserted', { part: sel.lens.part }))
      close()
    } catch (e) {
      setError((e as Error).message)
    }
  }
  const kindLabel = (k?: StockKind) => t(`st.kind.${k ?? 'other'}`)

  return (
    <Dialog title={t('st.title')} onClose={close} width={1240} icon={<Boxes size={16} className="text-accent" />}>
      <div className="grid h-[74vh] grid-cols-[minmax(520px,1.3fr)_minmax(380px,1fr)]">
        {/* list */}
        <div className="flex min-h-0 flex-col border-r border-line">
          <div className="flex flex-wrap items-center gap-2 border-b border-line p-2">
            <input
              autoFocus
              className="field-input min-w-0 flex-1"
              aria-label={t('st.search')}
              placeholder={t('st.search')}
              value={filter.q}
              onChange={(e) => setFilter({ ...filter, q: e.target.value })}
              onKeyDown={(e) => e.stopPropagation()}
            />
            <Select
              className="h-6 w-40 text-small"
              ariaLabel={t('st.catalog')}
              value={filter.catalog}
              options={[{ value: 'all', label: t('st.allCatalogs') }, { value: GENERIC_ID, label: `${t('st.generic')} (${generic?.length ?? 0})` }, ...catalogs.map((c) => ({ value: c.id, label: `${c.name} (${c.lenses.length})` }))]}
              onChange={(v) => setFilter({ ...filter, catalog: v })}
            />
          </div>
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-2 py-1.5 text-small">
            <Select<StockKind | 'all'>
              className="h-6 w-36 text-small"
              ariaLabel={t('st.kind')}
              value={filter.kind}
              options={[{ value: 'all', label: t('st.allKinds') }, ...KINDS.map((k) => ({ value: k, label: kindLabel(k) }))]}
              onChange={(v) => setFilter({ ...filter, kind: v })}
            />
            <Select
              className="h-6 w-32 text-small"
              ariaLabel={t('st.glass')}
              value={filter.glass}
              options={[{ value: '', label: t('st.allGlasses') }, ...glasses.map((g) => ({ value: g, label: g }))]}
              onChange={(v) => setFilter({ ...filter, glass: v })}
            />
            <Select<number>
              className="h-6 w-24 text-small"
              ariaLabel={t('st.diameter')}
              value={filter.diameter}
              options={[{ value: 0, label: t('st.allDiameters') }, ...diameters.map((d) => ({ value: d, label: `Ø ${fmt(d, 4)}` }))]}
              onChange={(v) => setFilter({ ...filter, diameter: v })}
            />
            <span className="text-muted">f (mm)</span>
            <NumberField className="h-6 w-16" ariaLabel={t('st.fmin')} optional placeholder={t('st.min')} value={filter.fmin} onCommit={(v) => setFilter({ ...filter, fmin: v })} />
            <NumberField className="h-6 w-16" ariaLabel={t('st.fmax')} optional placeholder={t('st.max')} value={filter.fmax} onCommit={(v) => setFilter({ ...filter, fmax: v })} />
            <span className="flex-1" />
            <span className="text-faint">
              {shown.length} / {all.length}
            </span>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {generic === null && !error ? (
              <div className="flex h-full items-center justify-center">
                <Spinner size={16} />
              </div>
            ) : (
              <table className="eng-table">
                <thead>
                  <tr>
                    <th>{t('st.part')}</th>
                    <th>{t('st.kind')}</th>
                    <th className="text-right">f (mm)</th>
                    <th className="text-right">Ø (mm)</th>
                    <th>{t('st.glass')}</th>
                    <th className="text-right">{t('st.price')}</th>
                    <th>{t('st.catalog')}</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.slice(0, SHOWN).map(({ lens: l, catalogId }) => {
                    const key = `${catalogId}:${l.part}`
                    return (
                      <tr key={key} className={cx('cursor-pointer', picked === key && 'selected')} onClick={() => setPicked(key)}>
                        <td className="px-2 font-medium whitespace-nowrap">{l.part}</td>
                        <td className="px-2 text-muted">{kindLabel(l.kind)}</td>
                        <td className="num px-2 text-right">{l.paraxial.efl === null ? '—' : fmt(l.paraxial.efl, 5)}</td>
                        <td className="num px-2 text-right">{fmt(l.diameter, 4)}</td>
                        <td className="px-2 whitespace-nowrap">{l.materials.join(' / ')}</td>
                        <td className="num px-2 text-right">{l.price == null ? '—' : `${fmt(l.price, 5)} ${l.currency ?? ''}`}</td>
                        <td className="px-2 text-muted">{catalogId === GENERIC_ID ? t('st.generic') : (catalogFor(catalogId)?.name ?? '')}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
            {shown.length > SHOWN && <div className="p-2 text-caption text-faint">{t('st.more', { n: shown.length - SHOWN })}</div>}
          </div>
        </div>

        {/* details, insert, catalogues */}
        <div className="flex min-h-0 flex-col gap-3 overflow-auto p-3">
          {error && <div className="text-small text-danger">{error}</div>}
          {sel ? (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <span className="text-title font-semibold">{sel.lens.part}</span>
                {sel.catalogId === GENERIC_ID ? <Badge tone="accent">{t('st.generic')}</Badge> : <Badge>{catalogFor(sel.catalogId)?.name}</Badge>}
              </div>
              <div className="text-caption text-muted">
                {kindLabel(sel.lens.kind)}
                {sel.lens.vendor ? ` · ${sel.lens.vendor}` : ''}
                {sel.lens.source ? ` · ${sel.lens.source}` : ''}
              </div>
              {sel.catalogId === GENERIC_ID && <div className="text-caption text-faint">{t('st.genericNote')}</div>}
              <table className="eng-table">
                <thead>
                  <tr>
                    <th>{t('st.surface')}</th>
                    <th className="text-right">R (mm)</th>
                    <th className="text-right">{t('st.thickness')}</th>
                    <th>{t('st.glass')}</th>
                  </tr>
                </thead>
                <tbody>
                  {sel.lens.radii.map((r, i) => (
                    <tr key={i}>
                      <td className="px-2">{i + 1}</td>
                      <td className="num px-2 text-right">{r === null ? '∞' : fmt(r, 6)}</td>
                      <td className="num px-2 text-right">{i < sel.lens.thicknesses.length ? fmt(sel.lens.thicknesses[i], 5) : ''}</td>
                      <td className="px-2">{sel.lens.materials[i] ?? ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-small">
                <span className="text-muted">EFL (d)</span>
                <span className="num text-right">{sel.lens.paraxial.efl === null ? '—' : `${fmt(sel.lens.paraxial.efl, 6)} mm`}</span>
                <span className="text-muted">{t('st.bfd')}</span>
                <span className="num text-right">{sel.lens.paraxial.bfd === null ? '—' : `${fmt(sel.lens.paraxial.bfd, 6)} mm`}</span>
                <span className="text-muted">{t('st.clear')}</span>
                <span className="num text-right">{fmt(sel.lens.clear, 4)} mm</span>
                <span className="text-muted">{t('st.diameter')}</span>
                <span className="num text-right">{fmt(sel.lens.diameter, 4)} mm</span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2 rounded border border-line p-2">
                <span className="text-small text-muted">{t('st.insertBefore')}</span>
                <Select<number>
                  className="h-6 w-44 text-small"
                  ariaLabel={t('st.insertBefore')}
                  value={at}
                  options={surfaces.slice(1).map((s, k) => ({ value: k + 1, label: `${k + 1} ${s.label || ''}`.trim() }))}
                  onChange={setAt}
                />
                <Checkbox checked={reversed} onChange={setReversed} label={<span className="text-small">{t('st.reversed')}</span>} title={t('st.reversedHint')} />
                <span className="text-small text-muted">{t('st.gapAfter')}</span>
                <NumberField className="h-6 w-16" ariaLabel={t('st.gapAfter')} value={gap} min={0} onCommit={(v) => setGap(v ?? 0)} />
                <Button size="sm" variant="primary" onClick={() => void insert()} title={t('st.insertHint')}>
                  <Plus size={12} /> {t('st.insert')}
                </Button>
              </div>
            </div>
          ) : (
            <Empty>{t('st.pick')}</Empty>
          )}

          <div className="mt-2 flex flex-col gap-2 border-t border-line pt-3">
            <span className="text-small font-semibold">{t('st.catalogs')}</span>
            <div className="flex items-center justify-between text-small">
              <span>
                {t('st.generic')} <span className="text-faint">({generic?.length ?? 0})</span>
              </span>
              <span className="text-caption text-faint">{t('st.builtIn')}</span>
            </div>
            {catalogs.map((c) => (
              <div key={c.id} className="flex items-center justify-between gap-2 text-small">
                <span className="min-w-0 truncate">
                  {c.name} <span className="text-faint">({c.lenses.length}{c.vendor ? ` · ${c.vendor}` : ''})</span>
                </span>
                <Button size="sm" variant="ghost" onClick={() => void remove(c.id)} title={t('st.removeHint', { name: c.name })} aria-label={t('st.removeHint', { name: c.name })}>
                  <Trash2 size={12} />
                </Button>
              </div>
            ))}
            <div className="grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-1.5 text-small">
              <span className="text-muted">{t('st.importInto')}</span>
              <input className="field-input h-6" aria-label={t('st.importInto')} value={catName} onChange={(e) => setCatName(e.target.value)} onKeyDown={(e) => e.stopPropagation()} />
              <span className="text-muted">{t('st.vendor')}</span>
              <input className="field-input h-6" aria-label={t('st.vendor')} value={vendor} onChange={(e) => setVendor(e.target.value)} onKeyDown={(e) => e.stopPropagation()} />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" disabled={busy} onClick={() => void doImportZmx()} title={t('st.importZmxHint')}>
                <FileUp size={12} /> {t('st.importZmx')}
              </Button>
              <Button size="sm" disabled={busy} onClick={() => void doImportCsv()} title={t('st.importCsvHint')}>
                <Upload size={12} /> CSV
              </Button>
              {busy && <Spinner size={12} />}
            </div>
            <div className="text-caption text-faint">{t('st.vendorNote')}</div>
            {report.length > 0 && (
              <ul className="max-h-32 overflow-auto text-caption text-muted">
                {report.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </Dialog>
  )
}
