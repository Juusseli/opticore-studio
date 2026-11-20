// The stock lens specification of the Design space view: build a system from stock lenses for a focal length or a
// magnification, or match the open design's lens elements to stock parts. The engine does the search.
import { Boxes, Wand2 } from 'lucide-react'
import { useMemo } from 'react'
import { useT } from '../../lib/i18n'
import { GENERIC_ID, useStockStore } from '../../store/stockStore'
import { useUiStore } from '../../store/uiStore'
import { Label } from '../common/controls'
import { Button, Checkbox, NumberField, Select } from '../common/ui'
import { type DsSettings, stockGlasses } from './designSpace'

type Set = (patch: Partial<DsSettings>, label?: string) => void

export function StockSpecForm({ st, set, fromDesign }: { st: DsSettings; set: Set; fromDesign: Pick<DsSettings, 'focal_length' | 'f_number' | 'half_field_deg'> }) {
  const t = useT()
  const generic = useStockStore((s) => s.generic)
  const catalogs = useStockStore((s) => s.catalogs)
  const glasses = useMemo(() => stockGlasses(st.stock_catalogs, generic, catalogs), [st.stock_catalogs, generic, catalogs])
  const build = st.stock_task === 'build'
  const toggleCatalog = (id: string, on: boolean) => set({ stock_catalogs: on ? [...st.stock_catalogs.filter((x) => x !== id), id] : st.stock_catalogs.filter((x) => x !== id) })
  const toggleCount = (n: number, on: boolean) => set({ lens_counts: on ? [...new Set([...st.lens_counts, n])].sort() : st.lens_counts.filter((x) => x !== n) })
  const allowed = st.stock_glasses
  const toggleGlass = (g: string, on: boolean) => {
    const cur = allowed ?? glasses
    const next = on ? [...new Set([...cur, g])] : cur.filter((x) => x !== g)
    set({ stock_glasses: next.length === glasses.length && glasses.every((x) => next.includes(x)) ? null : next })
  }
  return (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="text-small font-semibold">{t('ds.spec')}</span>
        <Button size="sm" variant="link" onClick={() => useUiStore.getState().openDialog('stockLenses')} title={t('st.openHint')}>
          <Boxes size={12} /> {t('st.browse')}
        </Button>
      </div>
      <Select<'build' | 'match'>
        className="h-6 w-full text-small"
        ariaLabel={t('ds.stockTask')}
        title={t('ds.stockTaskHint')}
        value={st.stock_task}
        options={[
          { value: 'build', label: t('ds.stockBuild') },
          { value: 'match', label: t('ds.stockMatch') },
        ]}
        onChange={(v) => set({ stock_task: v })}
      />
      {build ? (
        <>
          <Select<'infinite' | 'finite'>
            className="h-6 w-full text-small"
            ariaLabel={t('ds.conjugate')}
            value={st.conjugate}
            options={[
              { value: 'infinite', label: t('ds.conjInfinite') },
              { value: 'finite', label: t('ds.conjFinite') },
            ]}
            onChange={(v) => set({ conjugate: v })}
          />
          <div className="grid grid-cols-[1fr_auto] items-center gap-x-2 gap-y-1.5">
            {st.conjugate === 'infinite' ? (
              <>
                <Label form hint={t('ds.focalHint')}>{t('ds.focal')}</Label>
                <NumberField className="h-6 w-24" ariaLabel={t('ds.focal')} value={st.focal_length} min={0.1} max={10000} onCommit={(v) => v && set({ focal_length: v })} />
                <Label form hint={t('ds.fnumHint')}>F/#</Label>
                <NumberField className="h-6 w-24" ariaLabel="F/#" value={st.f_number} min={0.5} max={200} onCommit={(v) => v && set({ f_number: v })} />
                <Label form hint={t('ds.fieldHint')}>{t('ds.field')}</Label>
                <NumberField className="h-6 w-24" ariaLabel={t('ds.field')} value={st.half_field_deg} min={0} max={30} onCommit={(v) => set({ half_field_deg: v ?? 0 })} />
              </>
            ) : (
              <>
                <Label form hint={t('ds.objDistHint')}>{t('ds.objDist')}</Label>
                <NumberField className="h-6 w-24" ariaLabel={t('ds.objDist')} value={st.object_distance} min={0.1} onCommit={(v) => v && set({ object_distance: v })} />
                <Label form hint={t('ds.magHint')}>{t('ds.mag')}</Label>
                <NumberField className="h-6 w-24" ariaLabel={t('ds.mag')} value={st.magnification} onCommit={(v) => v && set({ magnification: v })} />
                <Label form hint={t('ds.naHint')}>{t('ds.na')}</Label>
                <NumberField className="h-6 w-24" ariaLabel={t('ds.na')} value={st.object_na} min={0.001} max={0.9} onCommit={(v) => v && set({ object_na: v })} />
                <Label form hint={t('ds.objHeightHint')}>{t('ds.objHeight')}</Label>
                <NumberField className="h-6 w-24" ariaLabel={t('ds.objHeight')} value={st.object_height} min={0} onCommit={(v) => set({ object_height: v ?? 0 })} />
              </>
            )}
            <Label form hint={t(st.conjugate === 'finite' ? 'ds.maxLengthFiniteHint' : 'ds.maxLengthHint')}>{t('ds.maxLength')}</Label>
            <NumberField className="h-6 w-24" ariaLabel={t('ds.maxLength')} optional placeholder={t('ds.noLimit')} value={st.max_length} min={0.1} onCommit={(v) => set({ max_length: v && v > 0 ? v : null })} />
          </div>
          {st.conjugate === 'infinite' && (
            <Button size="sm" variant="link" onClick={() => set(fromDesign, 'Design space: specification from the design')} title={t('ds.fromDesignHint')}>
              <Wand2 size={12} /> {t('ds.fromDesign')}
            </Button>
          )}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Label form hint={t('ds.lensCountsHint')}>{t('ds.lensCounts')}</Label>
            {[1, 2, 3].map((n) => (
              <Checkbox key={n} checked={st.lens_counts.includes(n)} onChange={(v) => toggleCount(n, v)} label={<span className="text-small">{n}</span>} ariaLabel={t('ds.lensCount', { n })} />
            ))}
          </div>
        </>
      ) : (
        <div className="text-caption text-muted">{t('ds.stockMatchNote')}</div>
      )}
      <div className="flex flex-col gap-1">
        <Label form hint={t('ds.stockCatalogsHint')}>{t('ds.stockCatalogs')}</Label>
        <Checkbox checked={st.stock_catalogs.includes(GENERIC_ID)} onChange={(v) => toggleCatalog(GENERIC_ID, v)} label={<span className="text-small">{t('st.generic')} <span className="text-faint">({generic?.length ?? '…'})</span></span>} />
        {catalogs.map((c) => (
          <Checkbox key={c.id} checked={st.stock_catalogs.includes(c.id)} onChange={(v) => toggleCatalog(c.id, v)} label={<span className="text-small">{c.name} <span className="text-faint">({c.lenses.length})</span></span>} />
        ))}
      </div>
      {glasses.length > 0 && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <Label form hint={t('ds.stockGlassesHint')}>{t('ds.stockGlasses')}</Label>
            {allowed !== null && (
              <Button size="sm" variant="link" onClick={() => set({ stock_glasses: null })}>
                {t('ds.allGlasses')}
              </Button>
            )}
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {glasses.map((g) => (
              <Checkbox key={g} checked={allowed === null || allowed.includes(g)} onChange={(v) => toggleGlass(g, v)} label={<span className="text-small">{g}</span>} />
            ))}
          </div>
        </div>
      )}
      <div className="grid grid-cols-[1fr_auto] items-center gap-x-2 gap-y-1.5">
        <Label form hint={t('ds.stockCandidatesHint')}>{t('ds.candidates')}</Label>
        <NumberField className="h-6 w-24" ariaLabel={t('ds.candidates')} integer value={st.stock_candidates} min={1} max={400} onCommit={(v) => v && set({ stock_candidates: Math.round(v) })} />
        <Label form hint={t('ds.minGapHint')}>{t('ds.minGap')}</Label>
        <NumberField className="h-6 w-24" ariaLabel={t('ds.minGap')} value={st.min_gap} min={0} onCommit={(v) => set({ min_gap: v ?? 0 })} />
        {build ? (
          <>
            <Label form hint={t('ds.tolHint')}>{t('ds.tol')}</Label>
            <NumberField className="h-6 w-24" ariaLabel={t('ds.tol')} value={st.tolerance_pct} min={0.01} max={50} onCommit={(v) => v && set({ tolerance_pct: v })} />
          </>
        ) : (
          <>
            <Label form hint={t('ds.perElementHint')}>{t('ds.perElement')}</Label>
            <NumberField className="h-6 w-24" ariaLabel={t('ds.perElement')} integer value={st.per_element} min={1} max={12} onCommit={(v) => v && set({ per_element: Math.round(v) })} />
          </>
        )}
        <Label form hint={t('ds.mtfHint')}>{t('ds.mtfFreq')}</Label>
        <NumberField className="h-6 w-24" ariaLabel={t('ds.mtfFreq')} value={st.mtf_frequency} min={0.1} onCommit={(v) => v && set({ mtf_frequency: v })} />
        <Label form hint={t('ds.seedHint')}>{t('ds.seed')}</Label>
        <NumberField className="h-6 w-24" ariaLabel={t('ds.seed')} integer value={st.seed} min={0} onCommit={(v) => set({ seed: Math.round(v ?? 1) })} />
      </div>
    </>
  )
}
