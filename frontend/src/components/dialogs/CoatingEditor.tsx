import { ArrowDown, ArrowUp, Copy, Layers, Plus, Search, Sparkles, Trash2 } from 'lucide-react'
import { coatingUsers, renameCoating } from '../../lib/references'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../../lib/api'
import type { CoatingAnalysisParams } from '../../lib/types'
import { fmt } from '../../lib/format'
import { targetText } from '../../lib/coatingDesign'
import { hasKey, useT } from '../../lib/i18n'
import type { CoatingDefinition, CoatingLayer, CoatingSummary } from '../../lib/types'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { Badge, Button, Checkbox, Dialog, IconButton, NumberField, Select, TextField } from '../common/ui'
import { cx } from '../common/uiUtils'
import { CoatingAnalysisPanel, type CoatingAnalysisDefaults } from './CoatingAnalysis'
import { uniqueCoatingName } from './coatingNames'

const blankLayer = (): CoatingLayer => ({ material: '', index: 1.38, extinction: 0, thickness_nm: 100 })

export function CoatingEditor() {
  const t = useT()
  const close = useUiStore((s) => s.closeDialog)
  const toast = useUiStore((s) => s.toast)
  const builtins = useEngineStore((s) => s.coatings)
  const materials = useEngineStore((s) => s.materials)
  const project = useProjectStore((s) => s.project)
  const updateProject = useProjectStore((s) => s.updateProject)
  const selection = useProjectStore((s) => s.selection)
  const custom = useMemo(() => project.system.custom_coatings ?? [], [project.system.custom_coatings])
  const surfaces = project.system.surfaces

  const [selected, setSelected] = useState<string | null>(custom[0]?.name.toUpperCase() ?? builtins[0]?.name ?? null)
  const [query, setQuery] = useState('')
  const q = query.trim().toUpperCase()
  const matches = (c: { name: string; description: string; category?: string }) => !q || c.name.includes(q) || c.description.toUpperCase().includes(q) || (c.category ?? '').toUpperCase().includes(q)
  const categories = useMemo(() => {
    const m = new Map<string, CoatingSummary[]>()
    for (const c of builtins) {
      const k = c.category || t('coat.builtin')
      m.set(k, [...(m.get(k) ?? []), c])
    }
    return [...m.entries()]
  }, [builtins, t])
  const [draft, setDraft] = useState<CoatingDefinition | null>(null)
  const [origName, setOrigName] = useState<string | null>(null) // name of the stored coating being edited (null: new)

  const takenNames = useMemo(() => [...builtins.map((c) => c.name), ...custom.map((c) => c.name.toUpperCase())], [builtins, custom])
  const matOptions = useMemo(
    () => [{ value: '', label: t('coat.fixedIndex') }, ...[...project.custom_materials.map((m) => m.name.toUpperCase()), ...materials.map((m) => m.name)].filter((v, i, a) => a.indexOf(v) === i).map((m) => ({ value: m, label: m }))],
    [materials, project.custom_materials, t],
  )

  const edit = (c: CoatingDefinition, stored: string | null) => {
    setDraft(structuredClone(c))
    setOrigName(stored)
    setSelected(stored)
  }
  const select = (name: string) => {
    const c = custom.find((x) => x.name.toUpperCase() === name)
    setSelected(name)
    if (c) edit(c, name)
    else {
      setDraft(null)
      setOrigName(null)
    }
  }
  useEffect(() => {
    if (selected && !draft) {
      const c = custom.find((x) => x.name.toUpperCase() === selected)
      if (c) edit(c, selected)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const builtinSel = builtins.find((c) => c.name === selected)
  const shown: CoatingDefinition | null = draft ?? (builtinSel ? { name: builtinSel.name, description: builtinSel.description, layers: builtinSel.layers, substrate_index: builtinSel.substrate_index, substrate_extinction: builtinSel.substrate_extinction } : null)
  const usedBy = (name: string) => coatingUsers(project, name).surfaces

  const newCoating = () =>
    edit({ name: uniqueCoatingName('MY_COATING', takenNames), description: '', layers: [blankLayer()], substrate_index: null, substrate_extinction: 0 }, null)
  const duplicate = () => shown && edit({ ...structuredClone(shown), name: uniqueCoatingName(`${shown.name}_COPY`, takenNames) }, null)

  const nameError = (() => {
    if (!draft) return null
    const n = draft.name.trim().toUpperCase()
    if (!n) return t('coat.nameRequired')
    if (n.length > 40) return 'max. 40'
    if (n === 'NONE' || n === 'UNCOATED' || builtins.some((c) => c.name === n)) return t('coat.nameReserved')
    if (custom.some((c) => c.name.toUpperCase() === n && n !== origName)) return t('coat.nameTaken')
    return null
  })()

  const save = () => {
    if (!draft || nameError) return
    const rec: CoatingDefinition = { ...draft, name: draft.name.trim().toUpperCase() }
    let renamed = 0
    updateProject((p) => {
      const list = (p.system.custom_coatings ??= [])
      const k = origName ? list.findIndex((c) => c.name.toUpperCase() === origName) : -1
      if (k >= 0) list[k] = rec
      else list.push(rec)
      if (origName && origName !== rec.name) renamed = renameCoating(p, origName, rec.name)
    }, `Save coating ${rec.name}`)
    setOrigName(rec.name)
    setSelected(rec.name)
    setDraft(structuredClone(rec))
    toast('success', renamed ? `${rec.name} saved; ${renamed} surface reference(s) renamed` : `${rec.name} saved to the project`)
  }
  const remove = (name: string) => {
    const used = coatingUsers(project, name)
    if (used.surfaces.length || used.cad.length)
      return toast('error', `${name} is used on ${[used.surfaces.length ? `surface(s) ${used.surfaces.join(', ')}` : '', used.cad.length ? `CAD model(s) ${used.cad.join(', ')}` : ''].filter(Boolean).join(' and ')}; assign another coating there first`)
    updateProject((p) => {
      p.system.custom_coatings = (p.system.custom_coatings ?? []).filter((c) => c.name.toUpperCase() !== name)
    }, `Delete coating ${name}`)
    setDraft(null)
    setOrigName(null)
    setSelected(builtins[0]?.name ?? null)
  }
  const assignable = selection.filter((i) => i > 0 && i < surfaces.length - 1 && surfaces[i].type !== 'coordinate_break')
  const assign = () => {
    if (!shown) return
    const name = shown.name.toUpperCase()
    updateProject((p) => {
      for (const i of assignable) p.system.surfaces[i].coating = name
    }, `Assign coating ${name}`)
    toast('success', `${name} → ${assignable.length} surface(s)`)
  }

  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify(custom.find((c) => c.name.toUpperCase() === origName) ?? null)
  const setLayer = (k: number, patch: Partial<CoatingLayer>) => draft && setDraft({ ...draft, layers: draft.layers.map((L, j) => (j === k ? { ...L, ...patch } : L)) })
  const moveLayer = (k: number, d: -1 | 1) => {
    if (!draft) return
    const L = [...draft.layers]
    const j = k + d
    if (j < 0 || j >= L.length) return
    ;[L[k], L[j]] = [L[j], L[k]]
    setDraft({ ...draft, layers: L })
  }
  const [designWl, setDesignWl] = useState(0.55)

  return (
    <Dialog title={t('coat.title')} onClose={close} width={1320} icon={<Layers size={16} className="text-accent" />}>
      <div className="grid h-[88vh] grid-cols-[260px_minmax(0,1fr)]">
        {/* list */}
        <div className="flex min-h-0 flex-col border-r border-line">
          <div className="flex items-center gap-2 border-b border-line p-2">
            <Button size="sm" onClick={newCoating}>
              <Plus size={14} /> {t('coat.new')}
            </Button>
            <Button size="sm" onClick={duplicate} disabled={!shown}>
              <Copy size={14} /> {t('coat.duplicate')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => useUiStore.getState().openDialog('coatingDesigner')} title={t('cd.title')}>
              <Sparkles size={14} />
            </Button>
          </div>
          <div className="flex items-center gap-1.5 border-b border-line px-2 py-1.5">
            <Search size={14} className="shrink-0 text-faint" />
            <TextField className="h-6 flex-1" value={query} placeholder={t('coat.search')} onCommit={setQuery} ariaLabel={t('coat.search')} />
          </div>
          <div className="min-h-0 flex-1 overflow-auto py-1">
            <div className="px-3 pb-1 pt-2 text-caption font-semibold uppercase tracking-wide text-faint">{t('coat.project')}</div>
            {custom.length === 0 && <div className="px-3 py-1 text-small text-faint">{t('coat.noneYet')}</div>}
            {custom.filter((c) => matches({ name: c.name.toUpperCase(), description: c.description })).map((c) => {
              const nm = c.name.toUpperCase()
              return (
                <button key={nm} className={cx('flex w-full items-center gap-2 px-3 py-1 text-left text-body hover:bg-hover', selected === nm && 'bg-select')} onClick={() => select(nm)}>
                  <span className="flex-1 truncate font-medium">{nm}</span>
                  {c.substrate_index !== null && <Badge>mirror</Badge>}
                  <span className="num text-caption text-faint">{c.layers.length}L</span>
                </button>
              )
            })}
            {categories.map(([cat, list]) => {
              const shownList = list.filter(matches)
              if (!shownList.length) return null
              return (
                <div key={cat}>
                  <div className="px-3 pb-1 pt-3 text-caption font-semibold uppercase tracking-wide text-faint">{hasKey(`coat.cat.${cat}`) ? t(`coat.cat.${cat}`) : cat}</div>
                  {shownList.map((c) => (
                    <button key={c.name} className={cx('flex w-full items-center gap-2 px-3 py-1 text-left text-body hover:bg-hover', selected === c.name && 'bg-select')} onClick={() => select(c.name)} title={c.description}>
                      <span className="flex-1 truncate">{c.name}</span>
                      {c.angle_deg ? <span className="num text-caption text-faint">{fmt(c.angle_deg, 3)}°</span> : null}
                      <span className="num text-caption text-faint">{c.layers.length}L</span>
                    </button>
                  ))}
                </div>
              )
            })}
          </div>
          <div className="border-t border-line p-2 text-caption leading-relaxed text-faint">{t('coat.help')}</div>
        </div>

        {/* detail */}
        {shown ? (
          <div className="flex min-h-0 flex-col">
            <div className="flex flex-wrap items-center gap-2 border-b border-line p-2">
              {draft ? (
                <>
                  <TextField className="w-56" value={draft.name} onCommit={(v) => setDraft({ ...draft, name: v.toUpperCase() })} ariaLabel={t('coat.name')} />
                  {nameError && <span className="text-small text-danger">{nameError}</span>}
                  <TextField className="min-w-[200px] flex-1" value={draft.description} placeholder={t('coat.description')} onCommit={(v) => setDraft({ ...draft, description: v })} ariaLabel={t('coat.description')} />
                </>
              ) : (
                <>
                  <span className="text-title font-semibold">{shown.name}</span>
                  <Badge>{builtinSel?.category && hasKey(`coat.cat.${builtinSel.category}`) ? t(`coat.cat.${builtinSel.category}`) : builtinSel?.category || t('coat.builtin')}</Badge>
                  <span className="min-w-0 flex-1 truncate text-small text-muted" title={shown.description}>
                    {shown.description}
                  </span>
                </>
              )}
              <div className="flex-1" />
              {usedBy(shown.name).length > 0 && <span className="text-small text-muted">{t('coat.usedOn')} {usedBy(shown.name).join(', ')}</span>}
              <Button size="sm" disabled={!assignable.length || (!!draft && dirty)} onClick={assign} title={dirty ? t('coat.saveFirst') : undefined}>
                {t('mat.assign')} ({assignable.length})
              </Button>
              <Button size="sm" variant="ghost" onClick={() => useUiStore.getState().openDialog('coatingDesigner', { coating: shown.name })} disabled={!!draft && dirty} title={dirty ? t('coat.saveFirst') : t('coat.openInDesignerHint')}>
                <Sparkles size={14} /> {t('coat.openInDesigner')}
              </Button>
              {draft && origName && (
                <Button size="sm" variant="ghost" onClick={() => remove(origName)} title={t('coat.delete')}>
                  <Trash2 size={14} />
                </Button>
              )}
              {draft && (
                <Button size="sm" variant="primary" disabled={!!nameError || !dirty} onClick={save}>
                  {t('coat.save')}
                </Button>
              )}
            </div>

            {builtinSel && (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-3 py-1.5 text-small">
                {builtinSel.design_nm ? (
                  <span>
                    <span className="text-muted">λ₀ </span>
                    <span className="num">{fmt(builtinSel.design_nm, 5)} nm</span>
                  </span>
                ) : null}
                {builtinSel.band_nm ? (
                  <span>
                    <span className="text-muted">{t('coat.band')} </span>
                    <span className="num">
                      {fmt(builtinSel.band_nm[0], 5)}–{fmt(builtinSel.band_nm[1], 5)} nm
                    </span>
                  </span>
                ) : null}
                <span>
                  <span className="text-muted">θ </span>
                  <span className="num">{fmt(builtinSel.angle_deg ?? 0, 3)}°</span>
                </span>
                <span>
                  <span className="text-muted">{t('coat.designedOn')} </span>
                  <span className="num">
                    n₀ {fmt(builtinSel.incident_index ?? 1, 5)} → {builtinSel.design_substrate_material ? `${builtinSel.design_substrate_material} (n ${fmt(builtinSel.design_substrate_index ?? 1.52, 5)})` : `n ${fmt(builtinSel.design_substrate_index ?? 1.52, 5)}`}
                  </span>
                </span>
                {(builtinSel.spec ?? []).length > 0 && (
                  <span className="min-w-0 truncate text-muted" title={t('coat.specHint')}>
                    {t('coat.spec')}:{' '}
                    {(builtinSel.spec ?? [])
                      .map(targetText)
                      .join('; ')}
                  </span>
                )}
              </div>
            )}
            <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,0.65fr)_minmax(0,1.7fr)]">
              {/* layers */}
              <div className="min-h-0 overflow-auto">
                <table className="eng-table">
                  <thead>
                    <tr>
                      <th className="w-8 text-right">#</th>
                      <th>{t('coat.material')}</th>
                      <th className="text-right">n</th>
                      <th className="text-right">k</th>
                      <th className="text-right">{t('coat.thickness')} (nm)</th>
                      <th className="text-right" title={t('coat.qwHint')}>
                        n·d / λ₀
                      </th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td className="px-2 text-right text-faint">0</td>
                      <td className="px-2 text-faint" colSpan={6}>
                        {t('coat.incident')}
                      </td>
                    </tr>
                    {shown.layers.map((L, k) => (
                      <tr key={k}>
                        <td className="num px-2 text-right text-muted">{k + 1}</td>
                        <td className="px-1">{draft ? <Select cell value={L.material} options={matOptions} onChange={(v) => setLayer(k, { material: v })} ariaLabel={`Layer ${k + 1} material`} /> : <span className="px-1">{L.material || (L as CoatingLayer & { label?: string }).label || t('coat.fixedIndex')}</span>}</td>
                        <td className="px-1 text-right">
                          {L.material ? <span className="px-1 text-faint">n(λ)</span> : draft ? <NumberField cell value={L.index} min={0.01} max={10} onCommit={(v) => setLayer(k, { index: v ?? 1 })} ariaLabel={`Layer ${k + 1} index`} /> : <span className="num px-1">{fmt(L.index, 5)}</span>}
                        </td>
                        <td className="px-1 text-right">{draft ? <NumberField cell value={L.extinction} min={0} max={100} onCommit={(v) => setLayer(k, { extinction: v ?? 0 })} ariaLabel={`Layer ${k + 1} extinction`} /> : <span className="num px-1">{fmt(L.extinction, 4)}</span>}</td>
                        <td className="px-1 text-right">{draft ? <NumberField cell value={L.thickness_nm} min={0} max={1e6} onCommit={(v) => setLayer(k, { thickness_nm: v ?? 0 })} ariaLabel={`Layer ${k + 1} thickness`} /> : <span className="num px-1">{fmt(L.thickness_nm, 6)}</span>}</td>
                        <td className="num px-2 text-right text-muted" title={t('coat.qwHint')}>
                          {L.material ? '—' : fmt((L.index * L.thickness_nm) / (designWl * 1000), 4)}
                        </td>
                        <td className="whitespace-nowrap px-1 text-right">
                          {draft && (
                            <>
                              {!L.material && (
                                <Button variant="link" className="px-1 text-caption" title={t('coat.qwHint')} onClick={() => setLayer(k, { thickness_nm: (designWl * 1000) / (4 * L.index) })}>
                                  λ/4
                                </Button>
                              )}
                              <IconButton size="sm" title={t('c.moveUp')} disabled={k === 0} onClick={() => moveLayer(k, -1)}>
                                <ArrowUp size={12} />
                              </IconButton>
                              <IconButton size="sm" title={t('c.moveDown')} disabled={k === shown.layers.length - 1} onClick={() => moveLayer(k, 1)}>
                                <ArrowDown size={12} />
                              </IconButton>
                              <IconButton size="sm" tone="danger" title={t('c.remove')} onClick={() => setDraft({ ...draft, layers: draft.layers.filter((_, j) => j !== k) })}>
                                <Trash2 size={12} />
                              </IconButton>
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                    <tr>
                      <td className="px-2 text-right text-faint">Σ</td>
                      <td className="px-2 text-faint" colSpan={3}>
                        {t('coat.totalLayers', { n: shown.layers.length })}
                      </td>
                      <td className="num px-2 text-right text-faint">{fmt(shown.layers.reduce((a, L) => a + L.thickness_nm, 0), 6)}</td>
                      <td colSpan={2} />
                    </tr>
                    <tr>
                      <td className="px-2 text-right text-faint">S</td>
                      <td className="px-2 text-faint" colSpan={6}>
                        {t('coat.substrateRow')}
                        {shown.substrate_index !== null && ` · ${t('coat.mirrorSubstrate')} (${t('coat.onMirrors')}): N = ${fmt(shown.substrate_index, 5)} − ${fmt(shown.substrate_extinction, 5)}i`}
                      </td>
                    </tr>
                  </tbody>
                </table>
                {draft && (
                  <div className="flex flex-wrap items-center gap-3 px-3 py-2 text-small">
                    <Button size="sm" variant="ghost" onClick={() => setDraft({ ...draft, layers: [...draft.layers, blankLayer()] })} disabled={draft.layers.length >= 200}>
                      <Plus size={12} /> {t('coat.addLayer')}
                    </Button>
                    <span className="text-muted">λ₀</span>
                    <NumberField className="h-6 w-20" value={designWl} min={0.1} max={30} units={{ nm: 1e-3, um: 1, µm: 1 }} onCommit={(v) => v !== null && setDesignWl(v)} ariaLabel={t('coat.designWl')} />
                    <span className="text-muted">µm</span>
                    <div className="flex-1" />
                    <Checkbox
                      checked={draft.substrate_index !== null}
                      onChange={(v) => setDraft({ ...draft, substrate_index: v ? 1.0 : null, substrate_extinction: v ? draft.substrate_extinction || 5 : 0 })}
                      label={<span className="text-muted">{t('coat.useOnMirrors')}</span>}
                    />
                    {draft.substrate_index !== null && (
                      <>
                        <span className="text-muted">n</span>
                        <NumberField className="h-6 w-20" value={draft.substrate_index} min={0.001} max={100} onCommit={(v) => setDraft({ ...draft, substrate_index: v ?? 1 })} ariaLabel="Mirror substrate n" />
                        <span className="text-muted">k</span>
                        <NumberField className="h-6 w-20" value={draft.substrate_extinction} min={0} max={100} onCommit={(v) => setDraft({ ...draft, substrate_extinction: v ?? 0 })} ariaLabel="Mirror substrate k" />
                      </>
                    )}
                  </div>
                )}
              </div>
              <CoatingAnalysisArea coating={shown} builtin={draft ? null : (builtinSel ?? null)} />
            </div>
          </div>
        ) : (
          <div className="grid place-items-center text-faint">{t('coat.noneYet')}</div>
        )}
      </div>
    </Dialog>
  )
}

/** The analyses of the shown coating on a chosen substrate (shared engine: backend coatanalysis.py). */
function CoatingAnalysisArea({ coating, builtin }: { coating: CoatingDefinition; builtin: CoatingSummary | null }) {
  const t = useT()
  const customMaterials = useProjectStore((s) => s.project.custom_materials)
  const materials = useEngineStore((s) => s.materials)
  const glassNames = useMemo(() => [...new Set([...customMaterials.map((m) => m.name.toUpperCase()), ...materials.filter((m) => m.name !== 'MIRROR' && m.name !== 'AIR' && m.name !== 'VACUUM').map((m) => m.name)])], [customMaterials, materials])
  // metals are offered too: a metal substrate makes the analysis that of a bare-metal mirror with the coating
  const [incident, setIncident] = useState(builtin?.incident_index ?? 1.0)
  const [subMaterial, setSubMaterial] = useState(builtin?.design_substrate_material ?? '')
  const [subIndex, setSubIndex] = useState(builtin?.design_substrate_index ?? 1.52)
  const [mirror, setMirror] = useState(false)
  const [back, setBack] = useState(false)
  const canMirror = coating.substrate_index !== null
  const asMirror = mirror && canMirror
  // a built-in brings its design setting; a project coating keeps the last one
  useEffect(() => {
    if (builtin) {
      setIncident(builtin.incident_index ?? 1.0)
      setSubIndex(builtin.design_substrate_index ?? 1.52)
      setSubMaterial(builtin.design_substrate_material ?? '')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [builtin?.name])
  const defaults: CoatingAnalysisDefaults = useMemo(() => {
    if (builtin?.band_nm) {
      const [a, b] = builtin.band_nm
      const m = 0.15 * (b - a)
      return { range: [Math.max(200, Math.round(a - m)), Math.round(b + m)], reference: builtin.design_nm ?? null, band: builtin.band_nm, angle: builtin.angle_deg ?? 0 }
    }
    if (builtin?.design_nm) return { range: [Math.round(builtin.design_nm * 0.6), Math.round(builtin.design_nm * 1.6)], reference: builtin.design_nm, band: null, angle: builtin.angle_deg ?? 0 }
    return { range: [400, 800], reference: null, band: null, angle: 0 }
  }, [builtin])
  const src = builtin ? { name: coating.name } : { definition: coating }
  const depKey = JSON.stringify([src, incident, subMaterial, subIndex, asMirror, back, customMaterials.length])
  const fetcher = (p: CoatingAnalysisParams, signal: AbortSignal) =>
    api.coatingsAnalyze({ ...src, ...p, custom_materials: customMaterials, mirror: asMirror, incident_index: incident, substrate_material: subMaterial, substrate_index: subIndex, back_side: back && !asMirror }, signal)
  const toolbar = (
    <>
      <span className="ml-2 text-muted" title={t('coat.incidentHint')}>
        n₀
      </span>
      <NumberField className="h-6 w-14" value={incident} min={1} max={3.999} onCommit={(v) => setIncident(v ?? 1)} ariaLabel={t('coat.incidentHint')} />
      {!asMirror && (
        <>
          <span className="ml-2 text-muted">{t('coat.substrate')}</span>
          <Select className="h-6 w-32 text-small" value={subMaterial} ariaLabel={t('coat.substrate')} options={[{ value: '', label: t('coat.fixedIndex') }, ...glassNames.map((g) => ({ value: g, label: g }))]} onChange={setSubMaterial} />
          {!subMaterial && <NumberField className="h-6 w-14" value={subIndex} min={1.0001} max={9.999} onCommit={(v) => setSubIndex(v ?? 1.52)} ariaLabel={`${t('coat.substrate')} n`} />}
          <Checkbox checked={back} onChange={setBack} label={<span className="whitespace-nowrap text-muted" title={t('coat.backHint')}>{t('coat.back')}</span>} />
        </>
      )}
      <Checkbox checked={asMirror} onChange={setMirror} label={<span className={cx('whitespace-nowrap text-muted', !canMirror && 'opacity-50')} title={canMirror ? t('coat.asMirrorHint') : t('coat.noSubstrate')}>{t('coat.asMirror')}</span>} />
    </>
  )
  return (
    <div className="flex min-h-0 flex-col border-t border-line">
      <CoatingAnalysisPanel fetcher={fetcher} depKey={depKey} defaults={defaults} opaque={asMirror} toolbar={toolbar} />
    </div>
  )
}
