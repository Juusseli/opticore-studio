import { Copy, Layers, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { CONFIG_PARAMS, configParamKey, isFieldConfigParam, isSystemConfigParam } from '../../lib/configs'
import { useT } from '../../lib/i18n'
import type { ConfigParameter, ConfigValue } from '../../lib/types'
import { LENGTH_TO_MM } from '../../lib/units'
import { useProjectStore } from '../../store/projectStore'
import { Button, IconButton, NumberField, Select, TextField } from '../common/ui'
import { cx } from '../common/uiUtils'
import { MaterialCell } from './LensDataEditor'
import { surfaceTitle } from './surfaceTitle'

/** Configuration editor: one row per controlled parameter, one column per configuration. */
export function ConfigEditor() {
  const t = useT()
  const sys = useProjectStore((s) => s.project.system)
  const st = useProjectStore.getState
  const mc = sys.multi_config
  const n = sys.surfaces.length
  const [param, setParam] = useState<ConfigParameter>('thickness')
  const surfaceChoices = sys.surfaces
    .map((s, i) => ({ s, i }))
    .filter(({ s, i }) => {
      if (isSystemConfigParam(param) || isFieldConfigParam(param)) return false
      const isCb = s.type === 'coordinate_break'
      if (param.startsWith('decenter') || param.startsWith('tilt')) return isCb
      if (param === 'thickness') return i < n - 1 && !isCb
      if (param === 'material') return i > 0 && i < n - 1 && !isCb
      return i > 0 && i < n - 1 && !isCb
    })
    .map(({ s, i }) => ({ value: s.id, label: `${i}: ${surfaceTitle(s, i, n)}` }))
  const [surface, setSurface] = useState<string>('')
  const surfaceId = isSystemConfigParam(param) || isFieldConfigParam(param) ? null : surfaceChoices.some((o) => o.value === surface) ? surface : (surfaceChoices[0]?.value ?? '')
  // field parameters (vignetting factors) name a field instead of a surface
  const fieldChoices = sys.fields.map((_, i) => ({ value: String(i), label: t('mc.field', { n: i + 1 }) }))
  const [fieldSel, setFieldSel] = useState('1')
  const fieldIndex = Math.min(Number(fieldSel), sys.fields.length - 1)

  if (!mc) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <Layers size={22} className="text-faint" />
        <div className="max-w-[520px] text-muted">{t('mc.intro')}</div>
        <Button variant="primary" onClick={() => st().enableConfigurations()}>
          <Plus size={14} /> {t('mc.enable')}
        </Button>
      </div>
    )
  }

  const rowLabel = (sid: string | null, field?: number | null) => {
    if (field !== null && field !== undefined) return t('mc.field', { n: field + 1 })
    const i = sys.surfaces.findIndex((s) => s.id === sid)
    return sid === null ? t('mc.system') : i < 0 ? '?' : `${i}: ${surfaceTitle(sys.surfaces[i], i, n)}`
  }

  const cell = (row: number, k: number, p: ConfigParameter, v: ConfigValue) => {
    const set = (x: ConfigValue) => st().setConfigValue(row, k, x)
    if (p === 'material') return <MaterialCell value={String(v ?? '')} onCommit={(x) => set(x)} />
    const isLen = p === 'thickness' || p === 'radius' || p === 'semi_diameter' || p.startsWith('decenter')
    if (p === 'temperature') return <NumberField cell value={v === null ? null : Number(v)} min={-273} max={1000} onCommit={(x) => x !== null && set(x)} />
    if (p === 'pressure') return <NumberField cell value={v === null ? null : Number(v)} min={0} max={100} onCommit={(x) => x !== null && set(x)} />
    if (isFieldConfigParam(p)) {
      const dec = p === 'vdx' || p === 'vdy'
      return <NumberField cell value={v === null ? null : Number(v)} min={dec ? -1 : 0} max={dec ? 1 : 0.999} onCommit={(x) => x !== null && set(x)} />
    }
    const allowInf = p === 'radius' || (p === 'thickness' && sys.surfaces.findIndex((s) => s.id === mc.operands[row].surface_id) === 0)
    return <NumberField cell value={v === null ? null : Number(v)} allowInfinity={allowInf} min={p === 'semi_diameter' || p === 'aperture_value' ? 0 : undefined} units={isLen ? LENGTH_TO_MM : undefined} onCommit={(x) => set(x)} />
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-1.5 border-b border-line p-2">
        <Button size="sm" onClick={() => st().addConfiguration()} title={t('mc.addHint')}>
          <Copy size={12} /> {t('mc.add')}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => st().removeConfiguration(mc.active)} disabled={mc.names.length <= 1}>
          <Trash2 size={12} /> {t('mc.deleteActive')}
        </Button>
        <div className="mx-2 h-4 w-px bg-line" />
        <Select className="h-6 w-[170px] text-small" ariaLabel={t('mc.parameter')} value={param} options={CONFIG_PARAMS.map((p) => ({ value: p, label: t(configParamKey(p)) }))} onChange={setParam} />
        {isFieldConfigParam(param) ? (
          <Select className="h-6 w-[170px] text-small" ariaLabel={t('c.field')} value={String(fieldIndex)} options={fieldChoices} onChange={setFieldSel} />
        ) : (
          !isSystemConfigParam(param) && <Select className="h-6 w-[170px] text-small" ariaLabel={t('opt.surface')} value={surfaceId ?? ''} options={surfaceChoices} onChange={setSurface} />
        )}
        <Button
          size="sm"
          onClick={() => st().addConfigOperand(param, surfaceId, isFieldConfigParam(param) ? fieldIndex : undefined)}
          disabled={!isSystemConfigParam(param) && !isFieldConfigParam(param) && !surfaceId}
          title={param === 'temperature' || param === 'pressure' ? t('mc.envHint') : isFieldConfigParam(param) ? t('sys.vigHint') : undefined}
        >
          <Plus size={12} /> {t('mc.addRow')}
        </Button>
        <div className="flex-1" />
        <Button size="sm" variant="ghost" onClick={() => st().disableConfigurations()} title={t('mc.disableHint')}>
          {t('mc.disable')}
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="eng-table">
          <thead>
            <tr>
              <th className="w-8">#</th>
              <th className="w-[150px]">{t('mc.parameter')}</th>
              <th className="w-[170px]">{t('opt.surface')}</th>
              {mc.names.map((name, k) => (
                <th key={k} className={cx('min-w-[130px]', k === mc.active && 'bg-accent/10')}>
                  <div className="flex items-center gap-1">
                    <input type="radio" name="active-config" className="accent-[var(--c-accent)]" checked={k === mc.active} onChange={() => st().setActiveConfiguration(k)} aria-label={name} title={t('mc.activate')} />
                    <TextField cell value={name} onCommit={(v) => st().renameConfiguration(k, v)} />
                  </div>
                </th>
              ))}
              <th></th>
            </tr>
          </thead>
          <tbody>
            {mc.operands.map((op, r) => (
              <tr key={`${op.parameter}-${op.surface_id}-${op.field ?? ''}`}>
                <td className="px-2 text-muted">{r + 1}</td>
                <td className="px-2">{t(configParamKey(op.parameter))}</td>
                <td className="px-2 text-muted">{rowLabel(op.surface_id, op.field)}</td>
                {op.values.map((v, k) => (
                  <td key={k} className={cx(k === mc.active && 'bg-accent/5')}>
                    {cell(r, k, op.parameter, v)}
                  </td>
                ))}
                <td className="px-1">
                  <IconButton size="sm" tone="danger" title={t('c.remove')} onClick={() => st().removeConfigOperand(r)}>
                    <Trash2 size={12} />
                  </IconButton>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {mc.operands.length === 0 && <div className="p-3 text-muted">{t('mc.empty')}</div>}
        <div className="px-3 py-2 text-caption leading-relaxed text-faint">{t('mc.help')}</div>
      </div>
    </div>
  )
}
