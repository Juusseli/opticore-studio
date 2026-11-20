import { ArrowLeftToLine, ArrowRightToLine, Plus, Thermometer, Trash2 } from 'lucide-react'
import { useMemo } from 'react'
import { HOUSING_MATERIALS, housingPreset } from '../../lib/environment'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { axialPositions, cadParts, parentChoices } from '../../lib/mounts'
import { newId } from '../../lib/project'
import type { MountPart, MountReport } from '../../lib/types'
import { useProjectStore } from '../../store/projectStore'
import { useAnalysis } from '../views/useAnalysis'
import { Button, Empty, IconButton, NumberField, Select, TextField } from '../common/ui'
import { surfaceTitle } from './surfaceTitle'

const NONE = '—'

/** Mount tree of the environment model: parts, seats and element temperatures (engine: environment.py). */
export function MountsPanel() {
  const t = useT()
  const project = useProjectStore((s) => s.project)
  const update = useProjectStore((s) => s.updateProject)
  const sys = project.system
  const mounts = sys.mounts ?? []
  const n = sys.surfaces.length
  const report = useAnalysis<MountReport>('mounts', {}).data
  const cad = useMemo(() => cadParts(project), [project])
  const z = axialPositions(sys)

  if (!sys.environment_enabled) {
    return (
      <Empty>
        <div className="flex max-w-[560px] flex-col items-center gap-3 text-center">
          <Thermometer size={22} className="text-faint" />
          <div className="text-muted">{t('mt.off')}</div>
          <Button variant="primary" onClick={() => update((p) => void (p.system.environment_enabled = true), 'Environment model on')}>
            {t('mt.turnOn')}
          </Button>
        </div>
      </Empty>
    )
  }

  const setPart = (id: string, patch: Partial<MountPart>, label: string) =>
    update((p) => {
      const m = (p.system.mounts ?? []).find((x) => x.id === id)
      if (m) Object.assign(m, patch)
    }, label)
  const addPart = () =>
    update((p) => {
      const list = (p.system.mounts ??= [])
      list.push({ id: newId(), name: `${t('mt.part')} ${list.length + 1}`, cte: p.system.housing_cte ?? 23.6, temperature_c: null, parent: null, datum_z: 0, cad_asset_id: null, cad_node_id: null })
    }, 'Add mount part')
  const removePart = (id: string) =>
    update((p) => {
      const list = p.system.mounts ?? []
      const gone = list.find((m) => m.id === id)
      p.system.mounts = list.filter((m) => m.id !== id).map((m) => (m.parent === id ? { ...m, parent: gone?.parent ?? null } : m))
      for (const s of p.system.surfaces) if (s.seat_part === id) s.seat_part = null
    }, 'Remove mount part')
  const setSeat = (i: number, part: string | null) => update((p) => void (p.system.surfaces[i].seat_part = part), part ? 'Seat surface' : 'Unseat surface')
  const cadOf = (m: MountPart) => cad.find((c) => c.assetId === m.cad_asset_id && c.nodeId === (m.cad_node_id ?? ''))
  const shiftOf = (id: string) => report?.parts.find((x) => x.id === id)?.datum_shift_mm
  const seatShift = (i: number) => report?.seats.find((x) => x.surface === i)?.shift_mm
  const nameOf = (id: string | null) => (id ? (mounts.find((m) => m.id === id)?.name ?? '?') : t('mt.reference'))
  const seatable = sys.surfaces.map((s, i) => ({ s, i })).filter(({ s, i }) => i > 0 && s.type !== 'coordinate_break' && s.material.toUpperCase() !== 'MIRROR')
  const glassStarts = sys.surfaces.map((s, i) => ({ s, i })).filter(({ s, i }) => i > 0 && i < n - 1 && !['AIR', 'VACUUM', 'MIRROR'].includes(s.material.toUpperCase()) && s.type !== 'coordinate_break')
  const partOptions = [{ value: '', label: NONE }, ...mounts.map((m) => ({ value: m.id, label: m.name || m.id }))]

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(620px,1.6fr)_minmax(340px,1fr)] gap-px overflow-auto bg-line">
      {/* parts */}
      <div className="flex min-h-0 flex-col bg-panel">
        <div className="flex shrink-0 items-center gap-2 border-b border-line px-2 py-1.5">
          <div className="text-small font-semibold tracking-wide text-muted uppercase">{t('mt.parts')}</div>
          <Button size="sm" onClick={addPart}>
            <Plus size={12} /> {t('mt.addPart')}
          </Button>
          <div className="min-w-0 flex-1 truncate text-caption text-faint" title={t('mt.help')}>
            {t('mt.help')}
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {mounts.length === 0 ? (
            <div className="p-3 text-small text-muted">{t('mt.noParts')}</div>
          ) : (
            <table className="eng-table min-w-[900px] table-fixed [&_th]:overflow-hidden [&_th]:text-ellipsis">
              <thead>
                <tr>
                  <th className="w-[130px]">{t('mt.name')}</th>
                  <th className="w-[130px]" title={t('mt.materialHint')}>{t('lde.material')}</th>
                  <th className="w-[80px]" title={t('mt.cteHint')}>{t('mt.cte')}</th>
                  <th className="w-[80px]" title={t('mt.tempHint')}>{t('mt.temp')}</th>
                  <th className="w-[120px]" title={t('mt.parentHint')}>{t('mt.parent')}</th>
                  <th className="w-[120px]" title={t('mt.datumHint')}>{t('mt.datum')}</th>
                  <th title={t('mt.cadHint')}>{t('mt.cad')}</th>
                  <th className="w-[84px] text-right" title={t('mt.datumShiftHint')}>{t('mt.datumShift')}</th>
                  <th className="w-[30px]"></th>
                </tr>
              </thead>
              <tbody>
                {mounts.map((m) => {
                  const c = cadOf(m)
                  const shift = shiftOf(m.id)
                  return (
                    <tr key={m.id}>
                      <td>
                        <TextField cell value={m.name} onCommit={(v) => setPart(m.id, { name: v }, 'Rename mount part')} />
                      </td>
                      <td>
                        <Select
                          cell
                          value={housingPreset(m.cte)}
                          options={[...HOUSING_MATERIALS.map((x) => ({ value: x.id, label: t('env.mat.' + x.id) })), { value: 'custom', label: t('env.mat.custom') }]}
                          onChange={(v) => {
                            const x = HOUSING_MATERIALS.find((y) => y.id === v)
                            if (x) setPart(m.id, { cte: x.cte }, 'Mount part material')
                          }}
                        />
                      </td>
                      <td>
                        <NumberField cell value={m.cte} min={-50} max={500} onCommit={(v) => v !== null && setPart(m.id, { cte: v }, 'Mount part expansion')} />
                      </td>
                      <td>
                        <NumberField cell optional value={m.temperature_c} placeholder={fmt(sys.temperature_c, 4)} min={-273} max={1000} onCommit={(v) => setPart(m.id, { temperature_c: v }, 'Mount part temperature')} />
                      </td>
                      <td>
                        <Select cell value={m.parent ?? ''} options={[{ value: '', label: t('mt.reference') }, ...parentChoices(mounts, m.id).map((x) => ({ value: x.id, label: x.name || x.id }))]} onChange={(v) => setPart(m.id, { parent: v || null }, 'Mount part parent')} />
                      </td>
                      <td>
                        <div className="flex items-center">
                          <NumberField cell value={m.datum_z} onCommit={(v) => v !== null && setPart(m.id, { datum_z: v }, 'Mount part datum')} />
                          {c && (
                            <>
                              <IconButton size="sm" title={t('mt.datumFront', { z: fmt(c.zMin, 5) })} onClick={() => setPart(m.id, { datum_z: c.zMin }, 'Mount datum from CAD')}>
                                <ArrowLeftToLine size={12} />
                              </IconButton>
                              <IconButton size="sm" title={t('mt.datumBack', { z: fmt(c.zMax, 5) })} onClick={() => setPart(m.id, { datum_z: c.zMax }, 'Mount datum from CAD')}>
                                <ArrowRightToLine size={12} />
                              </IconButton>
                            </>
                          )}
                        </div>
                      </td>
                      <td>
                        <Select
                          cell
                          value={c ? `${c.assetId}|${c.nodeId}` : ''}
                          options={[{ value: '', label: cad.length ? NONE : t('mt.noCad') }, ...cad.map((x) => ({ value: `${x.assetId}|${x.nodeId}`, label: `${x.label} (z ${fmt(x.zMin, 4)}…${fmt(x.zMax, 4)})` }))]}
                          onChange={(v) => {
                            const [a, nd] = v ? v.split('|') : [null, null]
                            setPart(m.id, { cad_asset_id: a, cad_node_id: a ? nd || null : null }, 'Link mount part to CAD')
                          }}
                        />
                      </td>
                      <td className="num px-2 text-right">{shift === undefined ? '—' : fmt(shift * 1e3, 4)}</td>
                      <td className="px-1">
                        <IconButton size="sm" tone="danger" title={t('c.remove')} onClick={() => removePart(m.id)}>
                          <Trash2 size={12} />
                        </IconButton>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* seats and element temperatures */}
      <div className="flex min-h-0 flex-col overflow-auto bg-panel">
        <div className="shrink-0 border-b border-line px-2 py-1.5 text-small font-semibold tracking-wide text-muted uppercase">{t('mt.seats')}</div>
        <table className="eng-table">
          <thead>
            <tr>
              <th>{t('c.surface')}</th>
              <th title={t('mt.heldByHint')}>{t('mt.heldBy')}</th>
              <th className="text-right" title={t('mt.zHint')}>{t('mt.z')}</th>
              <th className="text-right" title={t('mt.shiftHint')}>{t('mt.shift')}</th>
            </tr>
          </thead>
          <tbody>
            {seatable.map(({ s, i }) => {
              const sh = seatShift(i)
              return (
                <tr key={s.id}>
                  <td className="px-2">
                    {i}: {surfaceTitle(s, i, n)}
                  </td>
                  <td>
                    <Select cell value={s.seat_part ?? ''} options={partOptions} onChange={(v) => setSeat(i, v || null)} />
                  </td>
                  <td className="num px-2 text-right">{fmt(z[i], 6)}</td>
                  <td className="num px-2 text-right">{s.seat_part ? (sh === undefined ? '—' : fmt(sh * 1e3, 4)) : ''}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <div className="mt-2 shrink-0 border-y border-line px-2 py-1.5 text-small font-semibold tracking-wide text-muted uppercase">{t('mt.elements')}</div>
        <table className="eng-table">
          <thead>
            <tr>
              <th>{t('mt.element')}</th>
              <th className="w-[120px]" title={t('mt.elemTempHint')}>{t('mt.temp')}</th>
            </tr>
          </thead>
          <tbody>
            {glassStarts.map(({ s, i }) => (
              <tr key={s.id}>
                <td className="px-2">
                  {i}: {surfaceTitle(s, i, n)} <span className="text-faint">{s.material}</span>
                </td>
                <td>
                  <NumberField cell optional value={s.element_temperature_c ?? null} placeholder={fmt(sys.temperature_c, 4)} min={-273} max={1000} onCommit={(v) => update((p) => void (p.system.surfaces[i].element_temperature_c = v), 'Element temperature')} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {report && report.diagnostics.length > 0 && <div className="m-2 rounded bg-warn/10 px-2 py-1 text-small text-warn">{report.diagnostics.map((d) => d.message).join(' ')}</div>}
        <div className="px-2 py-2 text-caption leading-snug text-faint">{t('mt.note', { name: nameOf(null) })}</div>
      </div>
    </div>
  )
}
