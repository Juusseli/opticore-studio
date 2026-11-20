import { GripVertical, Plus } from 'lucide-react'
import { useState } from 'react'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import type { Solve, SurfaceType, VariableParam } from '../../lib/types'
import { activeOverride } from '../../lib/configs'
import { describeSolve } from '../../lib/solves'
import { mediumBefore } from '../../lib/project'
import { LENGTH_TO_MM } from '../../lib/units'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { Badge, Button, ContextMenu, NumberField, Select, TextField, Tooltip } from '../common/ui'
import { cx } from '../common/uiUtils'
import { RESERVED, useMaterialNames } from './materialNames'

/** Cell wrapper for a parameter set per configuration: edits change the active configuration's value. */
function ConfigCell({ children }: { children: React.ReactNode }) {
  const name = useProjectStore((s) => s.project.system.multi_config?.names[s.project.system.multi_config.active] ?? '')
  return (
    <Tooltip text={`Set per configuration: editing changes "${name}" (configuration editor)`}>
      <span className="flex h-full min-w-0 flex-1 items-center">
        <span className="min-w-0 flex-1">{children}</span>
        <span className="mr-1 rounded bg-warn/15 px-1 text-caption font-semibold text-warn">C</span>
      </span>
    </Tooltip>
  )
}

/** Read-only cell for a parameter controlled by a solve: shows the engine-resolved value. */
function SolvedCell({ value, solve, kind }: { value: number | null; solve: Solve; kind: 'thickness' | 'curvature' }) {
  const sys = useProjectStore((s) => s.project.system)
  return (
    <Tooltip text={`${describeSolve(solve, kind, sys)}. Edit or remove it in the inspector.`}>
      <span className="flex h-full min-w-0 flex-1 items-center justify-between gap-1 px-2">
        <span className="num truncate italic text-muted">{value === null ? 'Infinity' : fmt(value, 8)}</span>
        <span className="rounded bg-accent/15 px-1 text-caption font-semibold text-accent">{solve.type === 'pickup' ? 'P' : 'S'}</span>
      </span>
    </Tooltip>
  )
}

function VarToggle({ surfaceId, param }: { surfaceId: string; param: VariableParam }) {
  const t = useT()
  const on = useProjectStore((s) => s.project.optimization.variables.some((v) => v.surface_id === surfaceId && v.parameter === param))
  const toggle = useProjectStore((s) => s.toggleVariable)
  return (
    <Tooltip text={t('lde.variable')}>
      <button
        onClick={(e) => {
          e.stopPropagation()
          toggle(surfaceId, param)
        }}
        className={cx('mr-1 h-5 w-5 shrink-0 rounded text-caption font-bold transition-colors', on ? 'bg-accent-strong text-white' : 'text-faint hover:bg-hover hover:text-muted')}
        aria-pressed={on}
        aria-label={`${t('lde.variable')}: ${param}`}
      >
        V
      </button>
    </Tooltip>
  )
}

export function MaterialCell({ value, onCommit, cell = true }: { value: string; onCommit: (v: string) => void; cell?: boolean }) {
  const t = useT()
  const names = useMaterialNames()
  const [text, setText] = useState<string | null>(null)
  const shown = text ?? value
  const catalogLoaded = useEngineStore((s) => s.materials.length > 0)
  // until the catalogue is loaded, do not flag names as invalid
  const valid = !catalogLoaded || names.includes(shown.trim().toUpperCase()) || shown.trim() === ''
  const listId = 'materials-datalist'
  return (
    <>
      <Tooltip text={valid ? undefined : t('lde.unknownMaterial', { name: shown })}>
        <input
          list={listId}
          aria-label={t('lde.material')}
          className={cx(cell ? 'cell-input' : 'field-input', !valid && 'invalid')}
          value={shown}
          // the browser filters the suggestion list by the typed text: start empty (the current
          // material as the placeholder) so that every material is offered; leaving it empty keeps it
          placeholder={value}
          onChange={(e) => setText(e.target.value)}
          onFocus={() => setText('')}
          onBlur={() => {
            const v = (text ?? '').trim().toUpperCase()
            if (v && valid && v !== value) onCommit(v)
            setText(null)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
            if (e.key === 'Escape') {
              setText(null)
              ;(e.target as HTMLInputElement).blur()
            }
            e.stopPropagation()
          }}
        />
      </Tooltip>
      <datalist id={listId}>
        {names.map((n) => (
          <option key={n} value={n} />
        ))}
      </datalist>
    </>
  )
}

export function LensDataEditor() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const selection = useProjectStore((s) => s.selection)
  const st = useProjectStore.getState
  const activeConf = system.multi_config?.active ?? 0
  const select = useProjectStore((s) => s.select)
  const update = useProjectStore((s) => s.updateSurface)
  const ev = useEngineStore((s) => s.evaluation)
  const [menu, setMenu] = useState<{ x: number; y: number; i: number } | null>(null)
  const [dragFrom, setDragFrom] = useState<number | null>(null)
  const [dragOver, setDragOver] = useState<number | null>(null)
  const n = system.surfaces.length
  const prim = system.primary_wavelength
  const diag = ev?.diagnostics ?? []

  const typeOptions: { value: SurfaceType; label: string }[] = [
    { value: 'standard', label: t('lde.standard') },
    { value: 'even_asphere', label: t('lde.even_asphere') },
    { value: 'odd_asphere', label: t('lde.odd_asphere') },
    { value: 'biconic', label: t('lde.biconic') },
    { value: 'zernike', label: t('lde.zernike') },
    { value: 'qcon', label: t('lde.qcon') },
    { value: 'qbfs', label: t('lde.qbfs') },
    { value: 'xy_polynomial', label: t('lde.xy_polynomial') },
    { value: 'ideal', label: t('lde.ideal') },
    { value: 'coordinate_break', label: t('lde.coordinate_break') },
  ]

  const rowDiag = (i: number) => diag.filter((d) => d.surface === i && d.level !== 'info')

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-8 shrink-0 items-center gap-1.5 border-b border-line px-2">
        <Button size="sm" onClick={() => st().insertSurface((selection[0] ?? 0) + 1)}>
          <Plus size={12} /> {t('lde.insertAfter')}
        </Button>
        <Button size="sm" onClick={() => st().insertLens((selection[0] ?? 0) + 1)}>
          <Plus size={12} /> {t('lde.insertLens')}
        </Button>
        <Button size="sm" onClick={() => useUiStore.getState().openDialog('stockLenses', { at: (selection[0] ?? 0) + 1 })} title={t('st.openHint')}>
          <Plus size={12} /> {t('st.insertStock')}
        </Button>
        <Button size="sm" variant="danger" disabled={!selection.some((i) => i > 0 && i < n - 1)} onClick={() => st().deleteSurfaces(selection)}>
          {t('lde.delete')}
        </Button>
        <div className="ml-2 truncate text-caption text-faint">{t('lde.hint')}</div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {/* fixed column widths (minimums: the table scrolls sideways below them); headers truncate, the full
            name and its meaning are in the tooltip */}
        <table className="eng-table min-w-[1010px] table-fixed [&_th]:overflow-hidden [&_th]:text-ellipsis">
          <thead>
            <tr>
              <th className="w-[22px]"></th>
              <th className="w-[44px]" title={t('lde.surfHint')}>{t('lde.surf')}</th>
              <th className="w-[104px]" title={t('lde.typeHint')}>{t('lde.type')}</th>
              <th className="w-[110px]" title={t('lde.labelHint')}>{t('lde.label')}</th>
              <th className="w-[128px]" title={`${t('lde.radius')} (mm): ${t('lde.radiusHint')}`}>{t('lde.radius')} (mm)</th>
              <th className="w-[128px]" title={`${t('lde.thickness')} (mm): ${t('lde.thicknessHint')}`}>{t('lde.thickness')} (mm)</th>
              <th className="w-[120px]" title={t('lde.materialHint')}>{t('lde.material')}</th>
              <th className="w-[84px] text-right" title={t('lde.indexHint')}>{t('lde.index')}</th>
              <th className="w-[128px]" title={`${t('lde.semidia')} (mm): ${t('lde.semidiaHint')}`}>{t('lde.semidia')} (mm)</th>
              <th className="w-[96px]" title={t('lde.conicHint')}>{t('lde.conic')}</th>
              <th className="w-[46px] text-center" title={t('lde.stopHint')}>{t('lde.stop')}</th>
              <th title={t('lde.infoHint')}>{t('lde.info')}</th>
            </tr>
          </thead>
          <tbody>
            {system.surfaces.map((s, i) => {
              const isObj = i === 0
              const isImg = i === n - 1
              const isCb = s.type === 'coordinate_break'
              const sd = ev?.semi_diameters[i]
              const nIdx = ev?.indices?.[prim]?.[i]
              const solved = ev?.solved?.find((x) => x.surface === i)
              const ovR = activeOverride(system, s.id, 'radius')
              const ovT = activeOverride(system, s.id, 'thickness')
              const ovM = activeOverride(system, s.id, 'material')
              const d = rowDiag(i)
              const sel = selection.includes(i)
              return (
                <tr
                  key={s.id}
                  className={cx(sel && 'selected', dragOver === i && dragFrom !== null && 'outline outline-1 outline-accent')}
                  onMouseDown={(e) => {
                    if ((e.target as HTMLElement).tagName === 'INPUT' || (e.target as HTMLElement).tagName === 'SELECT') {
                      if (!sel) select(i)
                      return
                    }
                    select(i, e.shiftKey ? 'range' : e.ctrlKey || e.metaKey ? 'toggle' : 'single')
                  }}
                  onContextMenu={(e) => {
                    e.preventDefault()
                    if (!sel) select(i)
                    setMenu({ x: e.clientX, y: e.clientY, i })
                  }}
                  onDragOver={(e) => {
                    if (dragFrom === null || isObj || isImg) return
                    e.preventDefault()
                    setDragOver(i)
                  }}
                  onDrop={(e) => {
                    e.preventDefault()
                    if (dragFrom !== null && !isObj && !isImg) st().moveSurface(dragFrom, i)
                    setDragFrom(null)
                    setDragOver(null)
                  }}
                >
                  <td className="text-center text-faint">
                    {!isObj && !isImg && (
                      <span
                        draggable
                        onDragStart={(e) => {
                          setDragFrom(i)
                          e.dataTransfer.effectAllowed = 'move'
                          e.dataTransfer.setData('text/plain', String(i))
                        }}
                        onDragEnd={() => {
                          setDragFrom(null)
                          setDragOver(null)
                        }}
                        className="inline-flex cursor-grab items-center"
                        title="Drag to reorder"
                      >
                        <GripVertical size={12} />
                      </span>
                    )}
                  </td>
                  <td className="px-1.5 num text-muted">{isObj ? 'OBJ' : isImg ? 'IMG' : s.is_stop ? <span className="font-bold text-accent">STO</span> : i}</td>
                  <td>{isObj || isImg ? <span className="px-2 text-muted">{t('lde.standard')}</span> : <Select cell ariaLabel={`${t('lde.type')} ${i}`} value={s.type} options={typeOptions} onChange={(v) => update(i, v === 'ideal' ? { type: v, material: mediumBefore(system, i), coating: '' } : { type: v }, `Surface ${i} type`)} />}</td>
                  <td>
                    <TextField cell ariaLabel={`${t('lde.label')} ${i}`} value={s.label} placeholder={isObj ? t('sb.object') : isImg ? t('sb.image') : ''} onCommit={(v) => update(i, { label: v }, `Surface ${i} label`)} />
                  </td>
                  {isCb ? (
                    <td colSpan={1} className="px-2 text-small text-muted num">
                      dx {fmt(s.decenter_x, 4)} dy {fmt(s.decenter_y, 4)}
                    </td>
                  ) : s.type === 'ideal' ? (
                    <td>
                      {/* ideal lens: the radius column edits the focal length */}
                      <Tooltip text={t('ins.focalLengthHint')}>
                        <div className="flex items-center">
                          <span className="ml-1 rounded bg-accent-soft px-1 text-caption font-semibold text-accent">f</span>
                          <NumberField cell scrub value={s.focal_length} allowInfinity units={LENGTH_TO_MM} ariaLabel={`${t('lde.focal')} ${i}`} onCommit={(v) => update(i, { focal_length: v }, `Surface ${i} focal length`)} />
                          <VarToggle surfaceId={s.id} param="ideal_power" />
                        </div>
                      </Tooltip>
                    </td>
                  ) : (
                    <td>
                      <div className="flex items-center">
                        {s.curvature_solve ? (
                          <SolvedCell value={solved?.radius ?? s.radius} solve={s.curvature_solve} kind="curvature" />
                        ) : ovR ? (
                          <ConfigCell>
                            <NumberField cell scrub value={ovR.value === null ? null : Number(ovR.value)} allowInfinity units={LENGTH_TO_MM} ariaLabel={`${t('lde.radius')} ${i}`} onCommit={(v) => st().setConfigValue(ovR.row, activeConf, v)} />
                          </ConfigCell>
                        ) : (
                          <NumberField cell scrub value={s.radius} allowInfinity units={LENGTH_TO_MM} ariaLabel={`${t('lde.radius')} ${i}`} onCommit={(v) => update(i, { radius: v }, `Surface ${i} radius`)} />
                        )}
                        {!isObj && !isImg && !s.curvature_solve && <VarToggle surfaceId={s.id} param="curvature" />}
                      </div>
                    </td>
                  )}
                  <td>
                    {isImg ? (
                      <span className="px-2 text-faint">—</span>
                    ) : (
                      <div className="flex items-center">
                        {s.thickness_solve ? (
                          <SolvedCell value={solved?.thickness ?? s.thickness} solve={s.thickness_solve} kind="thickness" />
                        ) : ovT ? (
                          <ConfigCell>
                            <NumberField cell scrub value={ovT.value === null ? null : Number(ovT.value)} allowInfinity={isObj} units={LENGTH_TO_MM} ariaLabel={`${t('lde.thickness')} ${i}`} onCommit={(v) => st().setConfigValue(ovT.row, activeConf, v)} />
                          </ConfigCell>
                        ) : (
                          <NumberField cell scrub value={s.thickness} allowInfinity={isObj} units={LENGTH_TO_MM} ariaLabel={`${t('lde.thickness')} ${i}`} onCommit={(v) => update(i, { thickness: v }, `Surface ${i} thickness`)} />
                        )}
                        {!(isObj && s.thickness === null) && !s.thickness_solve && <VarToggle surfaceId={s.id} param="thickness" />}
                      </div>
                    )}
                  </td>
                  <td>
                    {isImg || isCb ? (
                      <span className="px-2 text-faint">—</span>
                    ) : ovM ? (
                      <ConfigCell>
                        <MaterialCell value={String(ovM.value ?? '')} onCommit={(v) => st().setConfigValue(ovM.row, activeConf, v)} />
                      </ConfigCell>
                    ) : (
                      <div className="flex items-center">
                        <MaterialCell value={s.material} onCommit={(v) => update(i, { material: v }, `Surface ${i} material`)} />
                        {!isObj && !RESERVED.includes(s.material.toUpperCase()) && <VarToggle surfaceId={s.id} param="material" />}
                      </div>
                    )}
                  </td>
                  <td className="num px-2 text-right text-muted">{isImg || isCb ? '' : s.material === 'MIRROR' ? 'mirror' : fmt(nIdx, 7)}</td>
                  <td>
                    {isCb ? (
                      <span className="px-2 text-faint">—</span>
                    ) : (
                      <div className="flex items-center">
                        {s.semi_diameter_mode === 'auto' ? (
                          <Tooltip text="Automatic: large enough to pass all fields and wavelengths. Type a value to fix it.">
                            <NumberField cell className="italic text-muted" ariaLabel={`${t('lde.semidia')} ${i}`} value={sd ?? s.semi_diameter} min={0} units={LENGTH_TO_MM} format={(v) => (v === null ? '' : fmt(v, 6))} onCommit={(v) => update(i, { semi_diameter: v ?? 0, semi_diameter_mode: 'fixed' }, `Surface ${i} semi-diameter`)} />
                          </Tooltip>
                        ) : (
                          <NumberField cell scrub ariaLabel={`${t('lde.semidia')} ${i}`} value={s.semi_diameter} min={0} units={LENGTH_TO_MM} onCommit={(v) => update(i, { semi_diameter: v ?? 0 }, `Surface ${i} semi-diameter`)} />
                        )}
                        <button
                          className={cx('mr-1 rounded px-1 text-caption font-semibold uppercase', s.semi_diameter_mode === 'fixed' ? 'bg-warn/15 text-warn' : 'text-faint hover:text-muted')}
                          title={s.semi_diameter_mode === 'fixed' ? 'Fixed aperture: rays outside are clipped (vignetting). Click for automatic.' : 'Automatic aperture (no clipping). Click to fix at the current value.'}
                          onClick={(e) => {
                            e.stopPropagation()
                            update(i, s.semi_diameter_mode === 'fixed' ? { semi_diameter_mode: 'auto' } : { semi_diameter_mode: 'fixed', semi_diameter: Number((sd ?? s.semi_diameter).toPrecision(6)) }, `Surface ${i} aperture mode`)
                          }}
                        >
                          {s.semi_diameter_mode === 'fixed' ? 'F' : 'A'}
                        </button>
                      </div>
                    )}
                  </td>
                  <td>
                    {isCb ? (
                      <span className="px-2 text-small text-muted num">
                        tx {fmt(s.tilt_x, 4)}° ty {fmt(s.tilt_y, 4)}° tz {fmt(s.tilt_z, 4)}°
                      </span>
                    ) : (
                      <div className="flex items-center">
                        <NumberField cell scrub value={s.conic} ariaLabel={`${t('lde.conic')} ${i}`} onCommit={(v) => update(i, { conic: v ?? 0 }, `Surface ${i} conic`)} />
                        {!isObj && !isImg && <VarToggle surfaceId={s.id} param="conic" />}
                      </div>
                    )}
                  </td>
                  <td className="text-center">
                    {!isObj && !isImg && !isCb && (
                      <input type="radio" name="stop" aria-label={`${t('lde.stop')} ${i}`} className="accent-[var(--c-accent)]" checked={s.is_stop || (!system.surfaces.some((x) => x.is_stop) && i === 1)} onChange={() => st().setStop(i)} />
                    )}
                  </td>
                  <td className="px-2">
                    <div className="flex items-center gap-1">
                      {s.material === 'MIRROR' && <Badge>mirror</Badge>}
                      {s.type === 'even_asphere' && s.aspheric.some((a) => a !== 0) && <Badge tone="accent">A{4}…{2 * s.aspheric.length + 2}</Badge>}
                      {s.type === 'zernike' && s.zernike_coefficients.some((a) => a !== 0) && <Badge tone="accent">Z{s.zernike_coefficients.filter((a) => a !== 0).length}</Badge>}
                      {(s.type === 'qcon' || s.type === 'qbfs') && (s.q_coefficients ?? []).some((a) => a !== 0) && <Badge tone="accent">Q{(s.q_coefficients ?? []).length}</Badge>}
                      {s.type === 'xy_polynomial' && (s.xy_coefficients ?? []).some((a) => a !== 0) && <Badge tone="accent">XY{(s.xy_coefficients ?? []).filter((a) => a !== 0).length}</Badge>}
                      {s.type === 'odd_asphere' && (s.odd_coefficients ?? []).some((a) => a !== 0) && <Badge tone="accent">r{(s.odd_coefficients ?? []).length}</Badge>}
                      {(s.grating_frequency !== 0 || s.phase_coefficients.some((a) => a !== 0)) && <Badge tone="accent">DOE m={s.diffraction_order}</Badge>}
                      {d.map((x, k) => (
                        <Tooltip key={k} text={x.message}>
                          <Badge tone={x.level === 'error' ? 'danger' : 'warn'}>{x.code.toLowerCase().replace(/_/g, ' ')}</Badge>
                        </Tooltip>
                      ))}
                      {s.comment && <span className="truncate text-small text-faint">{s.comment}</span>}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {menu && <SurfaceMenu x={menu.x} y={menu.y} i={menu.i} onClose={() => setMenu(null)} />}
    </div>
  )
}

export function SurfaceMenu({ x, y, i, onClose }: { x: number; y: number; i: number; onClose: () => void }) {
  const t = useT()
  const st = useProjectStore.getState
  const n = useProjectStore((s) => s.project.system.surfaces.length)
  const surf = useProjectStore((s) => s.project.system.surfaces[i])
  const inner = i > 0 && i < n - 1
  return (
    <ContextMenu
      x={x}
      y={y}
      onClose={onClose}
      items={[
        { label: t('lde.insertBefore'), onClick: () => st().insertSurface(Math.max(1, i)), disabled: i === 0 },
        { label: t('lde.insertAfter'), onClick: () => st().insertSurface(i + 1), disabled: i === n - 1, shortcut: 'Ins' },
        { label: t('lde.insertLens'), onClick: () => st().insertLens(i + 1), disabled: i === n - 1 },
        { label: t('st.insertStock'), onClick: () => useUiStore.getState().openDialog('stockLenses', { at: i + 1 }), disabled: i === n - 1 },
        { label: t('lde.duplicate'), onClick: () => st().duplicateSurface(i), disabled: !inner },
        'sep',
        { label: t('lde.makeStop'), onClick: () => st().setStop(i), disabled: !inner || surf?.type === 'coordinate_break' },
        { label: t('lde.moveUp'), onClick: () => st().moveSurface(i, i - 1), disabled: i <= 1 || i >= n - 1 },
        { label: t('lde.moveDown'), onClick: () => st().moveSurface(i, i + 1), disabled: !inner || i >= n - 2 },
        'sep',
        { label: `${t('lde.variable')}: R`, onClick: () => surf && st().toggleVariable(surf.id, 'curvature'), disabled: !inner },
        { label: `${t('lde.variable')}: t`, onClick: () => surf && st().toggleVariable(surf.id, 'thickness'), disabled: i === n - 1 },
        'sep',
        { label: t('lde.delete'), onClick: () => st().deleteSurfaces(useProjectStore.getState().selection.includes(i) ? useProjectStore.getState().selection : [i]), danger: true, disabled: !inner, shortcut: 'Del' },
      ]}
    />
  )
}
