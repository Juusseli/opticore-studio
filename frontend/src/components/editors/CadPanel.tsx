import { Box, ChevronDown, ChevronRight, Download, Eye, EyeOff, Layers, Trash2, Upload, Wand2 } from 'lucide-react'
import { Fragment, type ReactElement, useState } from 'react'
import { useUiStore } from '../../store/uiStore'
import { importProjectFile, rebuildCadStructure } from '../../actions'
import { countParts, effectiveOptical, isHiddenPath } from '../../lib/cadTree'
import { useMeasureStore } from '../../store/measureStore'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import type { CadAsset, CadOptical, CadScatter, CadTreeNode } from '../../lib/types'
import { LENGTH_TO_MM } from '../../lib/units'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { Badge, Button, IconButton, NumberField, Select, TextField, Tooltip } from '../common/ui'
import { cx } from '../common/uiUtils'
import { MaterialCell } from './LensDataEditor'

/** Imported CAD models: placement, appearance and optical roles (bodies with a role take part in the
 * non-sequential trace). */
export function CadPanel() {
  const t = useT()
  const assets = useProjectStore((s) => s.project.cad_assets)
  const st = useProjectStore.getState
  const set = (id: string, patch: Partial<CadAsset>, label: string) => st().updateCadAsset(id, patch, label)
  const setT = (a: CadAsset, key: 'translate' | 'rotate_deg', k: number, v: number) => {
    const arr = [...a.transform[key]] as [number, number, number]
    arr[k] = v
    set(a.id, { transform: { ...a.transform, [key]: arr } }, key === 'translate' ? 'Move CAD model' : 'Rotate CAD model')
  }
  const [open, setOpen] = useState<string[]>([])
  const toggleOpen = (id: string) => setOpen((o) => (o.includes(id) ? o.filter((x) => x !== id) : [...o, id]))
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-line p-2">
        <Button size="sm" onClick={() => importProjectFile()}>
          <Upload size={12} /> {t('cad.importAny')}
        </Button>
        <Button size="sm" onClick={() => useUiStore.getState().openDialog('cadExport')}>
          <Download size={12} /> {t('tb.cadExport')}
        </Button>
        <span className="text-small text-faint">{t('cad.note')}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {assets.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-muted">
            <Box size={22} className="text-faint" />
            <div className="max-w-[520px]">{t('cad.empty')}</div>
          </div>
        ) : (
          <table className="eng-table">
            <thead>
              <tr>
                <th className="w-8"></th>
                <th className="w-[150px]">{t('cad.name')}</th>
                <th className="text-right">{t('cad.triangles')}</th>
                <th className="text-right">{t('cad.size')} (mm)</th>
                <th className="text-right">{t('cad.area')} (mm²)</th>
                <th className="text-right">{t('cad.volume')} (mm³)</th>
                <th>{t('cad.translate')} x / y / z (mm)</th>
                <th>{t('cad.rotate')} x / y / z (°)</th>
                <th className="w-[220px]">{t('cad.role')}</th>
                <th className="w-[70px]">{t('cad.look')}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {assets.map((a) => {
                const size = a.bbox_max.map((v, k) => v - a.bbox_min[k])
                const warn = a.diagnostics.filter((d) => d.level === 'warning')
                const expanded = open.includes(a.id)
                return (
                  <Fragment key={a.id}>
                  <tr>
                    <td className="whitespace-nowrap text-center">
                      <IconButton size="sm" title={t('cad.structure')} onClick={() => toggleOpen(a.id)}>
                        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      </IconButton>
                      <IconButton size="sm" title={a.visible ? t('c.hide') : t('c.show')} onClick={() => set(a.id, { visible: !a.visible }, a.visible ? 'Hide CAD model' : 'Show CAD model')}>
                        {a.visible ? <Eye size={14} /> : <EyeOff size={14} />}
                      </IconButton>
                    </td>
                    <td>
                      <div className="flex items-center">
                        <TextField cell value={a.name} onCommit={(v) => v.trim() && set(a.id, { name: v.trim() }, 'Rename CAD model')} />
                        <Tooltip text={a.format === 'stl' ? 'STL mesh' : `${a.format.toUpperCase()} B-rep (exact geometry kept for export)${a.bodies?.length ? `\n${a.bodies.map((b) => `${b.name}: ${b.solids ? `${b.volume_mm3?.toPrecision(6)} mm³` : 'surfaces'}`).join('\n')}` : ''}`}>
                          <span className="mr-1">
                            <Badge tone={a.format === 'stl' ? 'default' : 'accent'}>
                              {a.format.toUpperCase()}
                              {a.bodies && a.bodies.length > 1 ? ` ·${a.bodies.length}` : ''}
                            </Badge>
                          </span>
                        </Tooltip>
                      </div>
                    </td>
                    <td className="num px-2 text-right">{a.mesh.triangles.toLocaleString()}</td>
                    <td className="num px-2 text-right">{size.map((v) => fmt(v, 5)).join(' × ')}</td>
                    <td className="num px-2 text-right">{fmt(a.surface_area_mm2, 6)}</td>
                    <td className="num px-2 text-right">
                      {a.volume_mm3 === null ? (
                        <Tooltip text={t('cad.openMesh')}>
                          <span className="text-faint">open</span>
                        </Tooltip>
                      ) : (
                        fmt(a.volume_mm3, 6)
                      )}
                    </td>
                    <td>
                      <div className="flex">
                        {[0, 1, 2].map((k) => (
                          <NumberField key={k} cell value={a.transform.translate[k]} units={LENGTH_TO_MM} onCommit={(v) => setT(a, 'translate', k, v ?? 0)} />
                        ))}
                      </div>
                    </td>
                    <td>
                      <div className="flex">
                        {[0, 1, 2].map((k) => (
                          <NumberField key={k} cell value={a.transform.rotate_deg[k]} onCommit={(v) => setT(a, 'rotate_deg', k, v ?? 0)} />
                        ))}
                      </div>
                    </td>
                    <td>
                      <div className="flex items-center">
                        <Select
                          cell
                          value={a.optical?.role ?? 'none'}
                          options={[
                            { value: 'none', label: t('cad.roleNone') },
                            { value: 'absorber', label: t('cad.roleAbsorber') },
                            { value: 'mirror', label: t('cad.roleMirror') },
                            { value: 'refractive', label: t('cad.roleRefractive') },
                          ]}
                          onChange={(v) => set(a.id, { optical: { ...a.optical, role: v as CadOptical['role'], material: v === 'refractive' ? (a.optical?.material ?? 'N-BK7') : null } }, 'CAD optical role')}
                        />
                        {a.optical?.role === 'refractive' && <MaterialCell value={a.optical.material ?? 'N-BK7'} onCommit={(m) => set(a.id, { optical: { ...a.optical!, role: 'refractive', material: m } }, 'CAD material')} />}
                      </div>
                      {a.optical && a.optical.role !== 'none' && <SurfaceOptics a={a} onChange={(o, label) => set(a.id, { optical: o }, label)} />}
                    </td>
                    <td>
                      <div className="flex items-center gap-1 px-1">
                        <input type="color" className="h-5 w-6 cursor-pointer rounded border border-line bg-transparent" value={a.color} onChange={(e) => set(a.id, { color: e.target.value }, 'CAD model colour')} aria-label={t('c.colour')} />
                        <NumberField cell value={a.opacity} min={0.05} max={1} onCommit={(v) => set(a.id, { opacity: v ?? 0.55 }, 'CAD model opacity')} />
                      </div>
                    </td>
                    <td className="px-1">
                      <div className="flex items-center gap-1">
                        {warn.length > 0 && (
                          <Tooltip text={warn.map((d) => d.message).join('\n')}>
                            <span>
                              <Badge tone="warn">{warn.length}</Badge>
                            </span>
                          </Tooltip>
                        )}
                        {a.format !== 'stl' ? (
                          <Button size="sm" variant="ghost" title={t('cado.button')} onClick={() => useUiStore.getState().openDialog('cadOptics', { assetId: a.id })}>
                            <Wand2 size={12} /> {t('cado.short')}
                          </Button>
                        ) : (
                          <Tooltip text={t('cado.stlNo')}>
                            <span className="px-1 text-caption text-faint">—</span>
                          </Tooltip>
                        )}
                        <IconButton size="sm" tone="danger" title={t('c.remove')} onClick={() => st().removeCadAsset(a.id)}>
                          <Trash2 size={12} />
                        </IconButton>
                      </div>
                    </td>
                  </tr>
                  {expanded && (
                    <tr>
                      <td colSpan={11} className="bg-panel-2/60 p-0">
                        <CadTreePanel a={a} />
                      </td>
                    </tr>
                  )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        )}
        {assets.length > 0 && <div className="px-3 py-2 text-caption leading-relaxed text-faint">{t('cad.help')} {t('cado.panelHelp')}</div>}
      </div>
    </div>
  )
}

const NO_SCATTER: CadScatter = { model: 'none', fraction: 0, sigma_deg: 5 }
const NO_COATINGS: NonNullable<import('../../lib/types').OpticalSystem['custom_coatings']> = []

/** Coating (mirror / refractive bodies) and surface scatter model of a CAD body. */
function SurfaceOptics({ a, onChange }: { a: CadAsset; onChange: (o: CadOptical, label: string) => void }) {
  const t = useT()
  const builtins = useEngineStore((s) => s.coatings)
  const custom = useProjectStore((s) => s.project.system.custom_coatings) ?? NO_COATINGS
  const o = a.optical!
  const sc = { ...NO_SCATTER, ...(o.scatter ?? {}) }
  const coat = (o.coating ?? '').toUpperCase()
  const names = [...builtins.map((c) => c.name), ...custom.map((c) => c.name.toUpperCase())]
  const fracHint = o.role === 'absorber' ? t('cad.scatterAbs') : o.role === 'mirror' ? t('cad.scatterMirror') : t('cad.scatterRefr')
  return (
    <div className="flex flex-wrap items-center gap-x-1 border-t border-line/50 py-0.5">
      {o.role !== 'absorber' && (
        <Tooltip text={t('cad.coatingHint')}>
          <span className="w-[96px]">
            <Select
              cell
              value={coat}
              ariaLabel="CAD coating"
              options={[{ value: '', label: t('ins.uncoated') }, ...names.map((n) => ({ value: n, label: n })), ...(coat && !names.includes(coat) ? [{ value: coat, label: `${coat} (unknown)` }] : [])]}
              onChange={(v) => onChange({ ...o, coating: v }, 'CAD coating')}
            />
          </span>
        </Tooltip>
      )}
      <Tooltip text={t('cad.scatterHint')}>
        <span className="w-[96px]">
          <Select
            cell
            value={sc.model}
            ariaLabel="CAD scatter model"
            options={[
              { value: 'none', label: t('cad.noScatter') },
              { value: 'lambertian', label: 'Lambertian' },
              { value: 'gaussian', label: 'Gaussian' },
              { value: 'abg', label: 'ABg' },
              { value: 'harvey', label: 'Harvey–Shack' },
            ]}
            onChange={(v) => onChange({ ...o, scatter: { ...sc, model: v, fraction: v !== 'none' && sc.fraction === 0 ? (o.role === 'absorber' ? 0.05 : 0.01) : sc.fraction } }, 'CAD scatter model')}
          />
        </span>
      </Tooltip>
      {sc.model !== 'none' && (
        <>
          <Tooltip text={sc.model === 'abg' || sc.model === 'harvey' ? `${fracHint}. ${t('cad.tisHint')}` : fracHint}>
            <span className="w-[52px]">
              <NumberField cell value={sc.fraction} min={0} max={1} ariaLabel="scatter fraction" onCommit={(v) => onChange({ ...o, scatter: { ...sc, fraction: v ?? 0 } }, 'CAD scatter fraction')} />
            </span>
          </Tooltip>
          {sc.model === 'gaussian' && (
            <Tooltip text={t('cad.sigmaHint')}>
              <span className="flex w-[60px] items-center">
                <NumberField cell value={sc.sigma_deg} min={0.001} max={90} ariaLabel="scatter width" onCommit={(v) => onChange({ ...o, scatter: { ...sc, sigma_deg: v ?? 5 } }, 'CAD scatter width')} />
                <span className="text-caption text-faint">°</span>
              </span>
            </Tooltip>
          )}
          {sc.model === 'abg' && (
            <span className="flex items-center gap-x-1">
              <BsdfParam label="B" hint={t('cad.abgB')} value={sc.abg_b ?? 1e-3} min={1e-12} max={10} onCommit={(v) => onChange({ ...o, scatter: { ...sc, abg_b: v } }, 'CAD scatter ABg B')} />
              <BsdfParam label="g" hint={t('cad.abgG')} value={sc.abg_g ?? 2} min={0} max={4} onCommit={(v) => onChange({ ...o, scatter: { ...sc, abg_g: v } }, 'CAD scatter ABg g')} />
            </span>
          )}
          {sc.model === 'harvey' && (
            <span className="flex items-center gap-x-1">
              <BsdfParam label="l" hint={t('cad.harveyL')} value={sc.harvey_l ?? 0.01} min={1e-6} max={1} onCommit={(v) => onChange({ ...o, scatter: { ...sc, harvey_l: v } }, 'CAD scatter Harvey l')} />
              <BsdfParam label="s" hint={t('cad.harveyS')} value={sc.harvey_s ?? -2} min={-6} max={-0.01} onCommit={(v) => onChange({ ...o, scatter: { ...sc, harvey_s: v } }, 'CAD scatter Harvey s')} />
            </span>
          )}
        </>
      )}
    </div>
  )
}

/** A labelled BSDF parameter cell (empty input restores the engine default). */
function BsdfParam({ label, hint, value, min, max, onCommit }: { label: string; hint: string; value: number; min: number; max: number; onCommit: (v: number | null) => void }) {
  return (
    <Tooltip text={hint}>
      <span className="flex w-[64px] items-center gap-0.5">
        <span className="text-caption text-faint">{label}</span>
        <NumberField cell value={value} min={min} max={max} ariaLabel={`scatter ${label}`} onCommit={onCommit} />
      </span>
    </Tooltip>
  )
}

const ROLE_LABEL: Record<string, string> = { none: 'none', absorber: 'absorber', mirror: 'mirror', refractive: 'refractive' }

/** Assembly structure of a CAD model: visibility, selection (highlight in 3D), properties and per-part optical roles. */
function CadTreePanel({ a }: { a: CadAsset }) {
  const t = useT()
  const st = useProjectStore.getState
  const selected = useMeasureStore((s) => s.selected)
  const select = useMeasureStore((s) => s.select)
  const [collapsed, setCollapsed] = useState<string[]>([])
  const hidden = a.hidden_parts ?? []
  if (!a.tree?.length) {
    return (
      <div className="flex items-center gap-2 px-6 py-2 text-small text-muted">
        {a.format === 'stl' ? (
          t('cad.stlNoStructure')
        ) : (
          <>
            <span>{t('cad.noStructure')}</span>
            <Button size="sm" onClick={() => rebuildCadStructure(a.id)} disabled={!a.source_b64}>
              <Layers size={12} /> {t('cad.readStructure')}
            </Button>
          </>
        )}
      </div>
    )
  }
  const toggleHidden = (id: string) =>
    st().updateCadAsset(a.id, { hidden_parts: hidden.includes(id) ? hidden.filter((x) => x !== id) : [...hidden, id] }, hidden.includes(id) ? 'Show CAD part' : 'Hide CAD part')
  const setRole = (id: string, role: string, material: string | null = null) => {
    const roles = { ...(a.part_roles ?? {}) }
    if (role === 'inherit') delete roles[id]
    else roles[id] = { ...(roles[id] ?? {}), role: role as CadOptical['role'], material: role === 'refractive' ? (material ?? roles[id]?.material ?? 'N-BK7') : null }
    st().updateCadAsset(a.id, { part_roles: roles }, 'CAD part optical role')
  }
  const rows: ReactElement[] = []
  const render = (n: CadTreeNode, path: string[], depth: number) => {
    const isHidden = isHiddenPath(path, hidden)
    const own = (a.part_roles ?? {})[n.id]
    const eff = effectiveOptical(a, path)
    const sel = selected?.asset_id === a.id && selected.part_id === n.id
    const isCollapsed = collapsed.includes(n.id)
    rows.push(
      <div key={n.id} className={cx('flex items-center gap-1.5 py-0.5 pr-3 text-small', sel && 'bg-select', isHidden && 'opacity-50')} style={{ paddingLeft: 12 + depth * 16 }}>
        {n.kind === 'assembly' ? (
          <IconButton size="sm" title={isCollapsed ? t('c.expand') : t('c.collapse')} aria-expanded={!isCollapsed} onClick={() => setCollapsed((c) => (c.includes(n.id) ? c.filter((x) => x !== n.id) : [...c, n.id]))}>
            {isCollapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
          </IconButton>
        ) : (
          <span className="w-[11px]" />
        )}
        <IconButton size="sm" title={hidden.includes(n.id) ? t('c.show') : t('c.hide')} onClick={() => toggleHidden(n.id)}>
          {hidden.includes(n.id) ? <EyeOff size={12} /> : <Eye size={12} />}
        </IconButton>
        {n.color && <span className="inline-block h-2.5 w-2.5 rounded border border-line" style={{ background: n.color }} />}
        <button className={cx('min-w-0 flex-1 truncate text-left hover:text-accent', sel && 'text-accent')} title={`${n.name} (${n.id})`} onClick={() => select(sel ? null : { asset_id: a.id, part_id: n.id })}>
          {n.name}
        </button>
        <Badge tone={n.kind === 'assembly' ? 'accent' : 'default'}>{n.kind === 'assembly' ? `${countParts(n.children)} ${t('cad.partsShort')}` : t('cad.part')}</Badge>
        <span className="num w-24 text-right text-faint" title={t('cad.volume')}>
          {n.volume_mm3 === null ? (n.solids ? '—' : 'surfaces') : `${fmt(n.volume_mm3, 5)} mm³`}
        </span>
        <span className="num w-28 text-right text-faint" title={t('cad.size')}>
          {n.bbox_max.map((v, k) => fmt(v - n.bbox_min[k], 3)).join('×')}
        </span>
        <span className="w-[104px]">
          <Select
            cell
            value={own ? own.role : 'inherit'}
            ariaLabel="part optical role"
            options={[
              { value: 'inherit', label: `↳ ${ROLE_LABEL[eff.role] ?? eff.role}` },
              { value: 'none', label: t('cad.roleNone') },
              { value: 'absorber', label: t('cad.roleAbsorber') },
              { value: 'mirror', label: t('cad.roleMirror') },
              { value: 'refractive', label: t('cad.roleRefractive') },
            ]}
            onChange={(v) => setRole(n.id, v)}
          />
        </span>
        <span className="w-24">{own?.role === 'refractive' && <MaterialCell value={own.material ?? 'N-BK7'} onCommit={(m) => setRole(n.id, 'refractive', m)} />}</span>
      </div>,
    )
    if (n.kind === 'assembly' && !isCollapsed) for (const c of n.children) render(c, [...path, c.id], depth + 1)
  }
  for (const r of a.tree) render(r, [r.id], 0)
  return (
    <div className="max-h-[320px] overflow-auto border-y border-line py-1">
      <div className="flex items-center gap-2 px-3 pb-1 text-caption text-faint">
        <span>{t('cad.treeHelp')}</span>
      </div>
      {rows}
    </div>
  )
}
