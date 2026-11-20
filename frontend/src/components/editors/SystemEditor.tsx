import { useState } from 'react'
import { designSnapshot, sameDesign } from '../../store/designGuard'
import { Plus, Trash2 } from 'lucide-react'
import { fmt, wavelengthColor } from '../../lib/format'
import { useT } from '../../lib/i18n'
import type { ApertureType, FieldType, OpticalSystem } from '../../lib/types'
import { LENGTH_TO_MM, WAVELENGTH_TO_UM } from '../../lib/units'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { Button, Checkbox, IconButton, NumberField, Select, Tooltip } from '../common/ui'
import { useUiStore } from '../../store/uiStore'
import { effectiveEnvironment, HOUSING_MATERIALS, housingPreset, T_REF, DEFAULT_HOUSING_CTE } from '../../lib/environment'
import { Label } from '../common/controls'
import { api } from '../../lib/api'
import { systemBody } from '../../store/engineStore'
import { activeOverride, clearVignetting, fieldConfigRow, isFieldConfigParam, setConfigVignetting } from '../../lib/configs'

export function SystemEditor() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const st = useProjectStore.getState
  const mc = system.multi_config
  const hasVig = system.fields.some((f) => !!(f.vdx || f.vdy || f.vcx || f.vcy)) || !!mc?.operands.some((o) => isFieldConfigParam(o.parameter))
  const apCell = systemCell(system, t('mc.controlled'), 'aperture_value', system.aperture.value, (v) => st().updateSystem({ aperture: { ...system.aperture, value: v } }, 'Aperture value'))
  // a vignetting factor in the configuration table: the cell shows and edits the active configuration's value
  const vigCell = (i: number, key: 'vdx' | 'vdy' | 'vcx' | 'vcy') => {
    const row = fieldConfigRow(system, i, key)
    return row >= 0 && mc ? { value: Number(mc.operands[row].values[mc.active] ?? 0), set: (v: number) => st().setConfigValue(row, mc.active, v) } : null
  }
  const [vigBusy, setVigBusy] = useState(false)
  // vignetting factors from the fixed apertures (engine: analysis/vignetting.py), applied as one undoable edit
  const setVignetting = async () => {
    setVigBusy(true)
    try {
      const project = useProjectStore.getState().project
      const snap = designSnapshot()
      const pmc = project.system.multi_config
      // with configurations (a zoom vignettes differently at each position) every configuration gets its own factors,
      // written into the configuration table; otherwise the fields' own factors
      const configs = pmc && pmc.names.length > 1 ? pmc.names.map((_, k) => k) : [null]
      const results: Awaited<ReturnType<typeof api.vignetting>>[] = []
      for (const k of configs) {
        const s = k === null ? project.system : { ...project.system, multi_config: { ...pmc!, active: k } }
        results.push(await api.vignetting(systemBody(s, project.custom_materials)))
      }
      if (!sameDesign(snap)) {
        useUiStore.getState().toast('warning', t('c.staleDesign'))
        return
      }
      const failed = [...new Set(results.flatMap((r) => r.fields.map((f, k) => (f.ok ? null : k + 1)).filter((k): k is number => k !== null)))]
      if (configs[0] === null) {
        const r = results[0]
        st().setFields(project.system.fields.map((f, k) => ({ ...f, vdx: r.fields[k].vdx, vdy: r.fields[k].vdy, vcx: r.fields[k].vcx, vcy: r.fields[k].vcy })))
      } else {
        st().updateProject((p) => setConfigVignetting(p.system, results.map((r) => r.fields)), 'Set vignetting (every configuration)')
      }
      if (failed.length) useUiStore.getState().toast('warning', t('sys.vigFailed').replace('{f}', failed.join(', ')))
      else if (!results.some((r) => r.fields.some((f) => f.vdx || f.vdy || f.vcx || f.vcy))) useUiStore.getState().toast('info', t('sys.vigNone'))
    } catch (e) {
      useUiStore.getState().toast('error', (e as Error).message)
    } finally {
      setVigBusy(false)
    }
  }
  const ev = useEngineStore((s) => s.evaluation)
  const pd = ev?.paraxial[String(system.primary_wavelength)]
  const obj = system.surfaces[0]
  const infinite = obj.thickness === null

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(290px,1fr)_minmax(260px,0.85fr)_minmax(300px,1fr)] gap-px overflow-auto bg-line">
      {/* aperture & conjugates */}
      <div className="space-y-2 overflow-auto bg-panel p-3">
        <div className="text-small font-semibold tracking-wide text-muted uppercase">{t('sys.aperture')}</div>
        <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-2">
          <span className="text-muted">{t('sys.apertureType')}</span>
          <Select
            ariaLabel={t('sys.apertureType')}
            value={system.aperture.type}
            options={(['epd', 'image_fnum', 'object_na'] as ApertureType[]).map((a) => ({ value: a, label: t('sys.' + a) }))}
            onChange={(v) => {
              if (v === 'object_na' && infinite) return alertFinite()
              if (v !== 'object_na' && system.object_space_telecentric) return useUiStore.getState().toast('warning', t('sys.telecentricNeedsNa'))
              st().updateSystem({ aperture: { type: v, value: v === 'epd' ? (pd?.entrance_pupil_diameter ?? 10) : v === 'image_fnum' ? (pd?.image_space_fnum ?? 5) : Math.min(0.5, pd?.object_space_na ?? 0.1) } }, 'Aperture type')
            }}
          />
          <span className="text-muted">{t('sys.value')}</span>
          <span title={apCell.title} className={apCell.className}>
            <NumberField ariaLabel={t('sys.value')} value={apCell.value} min={1e-9} units={system.aperture.type === 'epd' ? LENGTH_TO_MM : undefined} onCommit={(v) => apCell.commit(v ?? 1)} />
          </span>
          <span className="text-muted">{t('sys.objectDistance')}</span>
          <div className="flex gap-1">
            <Select ariaLabel={t('sys.objectDistance')} value={infinite ? 'inf' : 'fin'} options={[{ value: 'inf', label: t('sys.infinite') }, { value: 'fin', label: t('sys.finite') }]} onChange={(v) => {
              if (v === 'inf') {
                st().commit('Object at infinity', (p) => {
                  p.system.surfaces[0].thickness = null
                  if (p.system.field_type === 'object_height') p.system.field_type = 'angle'
                  if (p.system.aperture.type === 'object_na') p.system.aperture = { type: 'epd', value: 10 }
                  p.system.object_space_telecentric = false
                })
              } else st().updateSurface(0, { thickness: 200 }, 'Finite object distance')
            }} />
            {!infinite && <NumberField ariaLabel={t('sys.objectDistance')} value={obj.thickness} units={LENGTH_TO_MM} onCommit={(v) => st().updateSurface(0, { thickness: v }, 'Object distance')} />}
          </div>
          <span className="text-muted">{t('sys.rayAiming')}</span>
          <Select ariaLabel={t('sys.rayAiming')} value={system.ray_aiming} options={[{ value: 'paraxial', label: t('sys.paraxialAim') }, { value: 'real', label: t('sys.realAim') }]} onChange={(v) => st().updateSystem({ ray_aiming: v }, 'Ray aiming')} />
          <span className="text-muted">{t('sys.telecentric')}</span>
          <Tooltip text={infinite ? t('sys.telecentricNeedsFinite') : t('sys.telecentricHint')}>
            <span>
              <Checkbox
                checked={!!system.object_space_telecentric}
                onChange={(on) => {
                  if (on && (infinite || (obj.thickness ?? 0) <= 0)) return alertFinite()
                  st().commit(on ? 'Object-space telecentric' : 'Object-space telecentric off', (p) => {
                    p.system.object_space_telecentric = on
                    if (on) {
                      if (p.system.aperture.type !== 'object_na') p.system.aperture = { type: 'object_na', value: Math.min(0.5, pd?.object_space_na ?? 0.05) }
                      if (p.system.field_type === 'angle') {
                        p.system.field_type = 'object_height'
                        p.system.fields = p.system.fields.map((f) => ({ ...f, x: 0, y: 0 }))
                      }
                    }
                  })
                }}
                label={<span className="text-muted">{t('sys.telecentricShort')}</span>}
              />
            </span>
          </Tooltip>
        </div>
        {pd && (
          <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 rounded-md border border-line p-2 num text-small text-muted">
            <span>EFL {fmt(pd.efl, 7)} mm</span>
            <span>F/# {fmt(pd.image_space_fnum, 5)}</span>
            <span>EPD {fmt(pd.entrance_pupil_diameter, 6)} mm</span>
            <span>Work F/# {fmt(pd.working_fnum, 5)}</span>
            <span>BFL {fmt(pd.bfl, 7)} mm</span>
            <span>NA′ {fmt(pd.image_space_na, 5)}</span>
          </div>
        )}
        <EnvironmentSection />
        <GlassSection />
        <SensorSection />
      </div>

      {/* fields */}
      <div className="flex min-h-0 flex-col bg-panel">
        <div className="flex items-center gap-2 px-3 pt-3 pb-2">
          <div className="flex-1 text-small font-semibold tracking-wide text-muted uppercase">{t('sys.fields')}</div>
          <Select
            className="h-6 w-[150px]"
            ariaLabel={t('sys.fieldType')}
            value={system.field_type}
            options={(['angle', 'object_height', 'image_height', 'paraxial_image_height'] as FieldType[]).map((f) => ({ value: f, label: t('sys.' + f) }))}
            onChange={(v) => {
              if (v === 'object_height' && infinite) return alertFinite()
              if (v === 'angle' && system.object_space_telecentric) return useUiStore.getState().toast('warning', t('sys.telecentricNoAngle'))
              st().updateSystem({ field_type: v }, 'Field type')
            }}
          />
          <Tooltip text={t('sys.setVigHint')}>
            <Button size="sm" variant="ghost" disabled={vigBusy} onClick={setVignetting}>
              {t('sys.setVig')}
            </Button>
          </Tooltip>
          {hasVig && (
            <Button size="sm" variant="ghost" title={t('sys.clearVigHint')} onClick={() => st().updateProject((p) => clearVignetting(p.system), 'Clear vignetting')}>
              {t('sys.clearVig')}
            </Button>
          )}
          <Button size="sm" aria-label={t('sys.addField')} title={t('sys.addField')} disabled={system.fields.length >= 25} onClick={() => st().setFields([...system.fields, { x: 0, y: (system.fields[system.fields.length - 1]?.y ?? 0) + 1, weight: 1 }])}>
            <Plus size={12} />
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          <table className="eng-table">
            <thead>
              <tr>
                <th>#</th>
                <th>X ({system.field_type === 'angle' ? '°' : 'mm'})</th>
                <th>Y ({system.field_type === 'angle' ? '°' : 'mm'})</th>
                <th>{t('sys.weight')}</th>
                {hasVig &&
                  (['vdx', 'vdy', 'vcx', 'vcy'] as const).map((k) => (
                    <th key={k} title={t('sys.vigHint')}>
                      {k.toUpperCase()}
                    </th>
                  ))}
                <th></th>
              </tr>
            </thead>
            <tbody>
              {system.fields.map((f, i) => (
                <tr key={i}>
                  <td className="px-2 text-muted">{i + 1}</td>
                  <td>
                    <NumberField cell ariaLabel={`F${i + 1} X`} value={f.x} onCommit={(v) => st().setFields(system.fields.map((x, k) => (k === i ? { ...x, x: v ?? 0 } : x)))} />
                  </td>
                  <td>
                    <NumberField cell ariaLabel={`F${i + 1} Y`} value={f.y} onCommit={(v) => st().setFields(system.fields.map((x, k) => (k === i ? { ...x, y: v ?? 0 } : x)))} />
                  </td>
                  <td>
                    <NumberField cell ariaLabel={`F${i + 1} ${t('sys.weight')}`} value={f.weight} min={0} onCommit={(v) => st().setFields(system.fields.map((x, k) => (k === i ? { ...x, weight: v ?? 1 } : x)))} />
                  </td>
                  {hasVig &&
                    (['vdx', 'vdy', 'vcx', 'vcy'] as const).map((key) => {
                      const c = vigCell(i, key)
                      return (
                        <td key={key} className={c ? 'min-w-[64px] bg-accent/5' : 'min-w-[64px]'} title={c ? t('mc.controlled') : undefined}>
                          <NumberField
                            cell
                            ariaLabel={`F${i + 1} ${key.toUpperCase()}`}
                            value={c ? c.value : (f[key] ?? 0)}
                            min={key.startsWith('vc') ? 0 : -1}
                            max={key.startsWith('vc') ? 0.999 : 1}
                            onCommit={(v) => (c ? c.set(v ?? 0) : st().setFields(system.fields.map((x, k) => (k === i ? { ...x, [key]: v ?? 0 } : x))))}
                          />
                        </td>
                      )
                    })}
                  <td className="px-1">
                    <IconButton size="sm" tone="danger" title={t('c.remove')} disabled={system.fields.length <= 1} onClick={() => st().removeField(i)}>
                      <Trash2 size={12} />
                    </IconButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* wavelengths */}
      <div className="flex min-h-0 flex-col bg-panel">
        <div className="flex items-center gap-1.5 px-3 pt-3 pb-2">
          <div className="flex-1 text-small font-semibold tracking-wide text-muted uppercase">{t('sys.wavelengths')}</div>
          {/* presets replace the list (one undoable step) */}
          <Select<'' | 'fdc' | 'visible' | 'hene'>
            className="h-6 w-[140px]"
            ariaLabel={t('sys.presets')}
            title={t('sys.presetsHint')}
            value=""
            options={[
              { value: '', label: t('sys.presets') },
              { value: 'fdc', label: t('sys.presetFdC') },
              { value: 'visible', label: t('sys.presetVisible') },
              { value: 'hene', label: t('sys.presetHeNe') },
            ]}
            onChange={(v) => {
              if (v === 'fdc') st().setWavelengths([{ value: 0.4861327, weight: 1 }, { value: 0.5875618, weight: 1 }, { value: 0.6562725, weight: 1 }], 1)
              else if (v === 'visible') st().setWavelengths([0.45, 0.5, 0.55, 0.6, 0.65].map((x) => ({ value: x, weight: 1 })), 2)
              else if (v === 'hene') st().setWavelengths([{ value: 0.6328, weight: 1 }], 0)
            }}
          />
          <Button size="sm" aria-label={t('sys.addWavelength')} title={t('sys.addWavelength')} disabled={system.wavelengths.length >= 24} onClick={() => st().setWavelengths([...system.wavelengths, { value: 0.55, weight: 1 }])}>
            <Plus size={12} />
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          <table className="eng-table">
            <thead>
              <tr>
                <th>#</th>
                <th></th>
                <th>λ (µm)</th>
                <th>{t('sys.weight')}</th>
                <th className="text-center">{t('sys.primary')}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {system.wavelengths.map((w, i) => (
                <tr key={i}>
                  <td className="px-2 text-muted">{i + 1}</td>
                  <td className="px-1">
                    <span className="inline-block h-3 w-3 rounded-full" style={{ background: wavelengthColor(w.value) }} />
                  </td>
                  <td>
                    <NumberField cell ariaLabel={`λ${i + 1}`} value={w.value} min={0.1} max={30} units={WAVELENGTH_TO_UM} title={t('sys.wlInputHint')} onCommit={(v) => st().setWavelengths(system.wavelengths.map((x, k) => (k === i ? { ...x, value: v ?? 0.55 } : x)))} />
                  </td>
                  <td>
                    <NumberField cell ariaLabel={`λ${i + 1} ${t('sys.weight')}`} value={w.weight} min={0} onCommit={(v) => st().setWavelengths(system.wavelengths.map((x, k) => (k === i ? { ...x, weight: v ?? 1 } : x)))} />
                  </td>
                  <td className="text-center">
                    <input type="radio" name="primary-wl" className="accent-[var(--c-accent)]" checked={system.primary_wavelength === i} onChange={() => st().setWavelengths(system.wavelengths, i)} aria-label={`${t('sys.primary')} ${i + 1}`} />
                  </td>
                  <td className="px-1">
                    <IconButton
                      size="sm"
                      tone="danger"
                      title={t('c.remove')}
                      disabled={system.wavelengths.length <= 1}
                      onClick={() => st().removeWavelength(i)}
                    >
                      <Trash2 size={12} />
                    </IconButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-3 py-2 text-caption text-faint">Vacuum wavelengths; catalogue indices are relative to air (AIR = 1). Values outside a material's data range are flagged as extrapolated.</div>
        </div>
      </div>
    </div>
  )
}

/** A system parameter in the configuration table (aperture value, temperature, pressure): the field shows and edits the
 * active configuration's value, as the Lens Data Editor does for surface parameters. */
function systemCell(system: OpticalSystem, title: string, param: 'aperture_value' | 'temperature' | 'pressure', base: number, commit: (v: number) => void) {
  const o = activeOverride(system, null, param)
  const mc = system.multi_config
  return o && mc
    ? { value: Number(o.value), commit: (v: number) => useProjectStore.getState().setConfigValue(o.row, mc.active, v), title, className: 'bg-accent/5' }
    : { value: base, commit, title: undefined, className: undefined }
}

function alertFinite() {
  window.alert('This option requires a finite object distance. Set the object distance to Finite first.')
}

/** Environment model: temperature, pressure and the housing that carries the lens (engine: environment.py). */
function EnvironmentSection() {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const st = useProjectStore.getState
  const envNow = effectiveEnvironment(system)
  const on = envNow.enabled
  const cte = system.housing_cte ?? DEFAULT_HOUSING_CTE
  const preset = housingPreset(cte)
  const tCell = systemCell(system, t('mc.controlled'), 'temperature', system.temperature_c, (v) => st().updateSystem({ temperature_c: v }, 'Temperature'))
  const pCell = systemCell(system, t('mc.controlled'), 'pressure', system.pressure_atm ?? 1, (v) => st().updateSystem({ pressure_atm: v }, 'Pressure'))
  return (
    <div className="mt-3 space-y-2 border-t border-line pt-3">
      <div className="text-small font-semibold tracking-wide text-muted uppercase">{t('env.title')}</div>
      <span title={t('env.enableHint')}>
        <Checkbox checked={on} onChange={(v) => st().updateSystem({ environment_enabled: v }, v ? 'Environment model on' : 'Environment model off')} label={<span>{t('env.enable')}</span>} />
      </span>
      {on && (
        <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-2">
          <Label form hint={t('env.temperatureHint', { ref: T_REF })}>{t('env.temperature')}</Label>
          <span title={tCell.title} className={tCell.className}>
            <NumberField ariaLabel={t('env.temperature')} value={tCell.value} min={-273} max={1000} onCommit={(v) => v !== null && tCell.commit(v)} />
          </span>
          <Label form hint={t('env.pressureHint')}>{t('env.pressure')}</Label>
          <span title={pCell.title} className={pCell.className}>
            <NumberField ariaLabel={t('env.pressure')} value={pCell.value} min={0} max={100} onCommit={(v) => v !== null && pCell.commit(v)} />
          </span>
          <Label form hint={t('env.housingHint')}>{t('env.housing')}</Label>
          <div className="flex min-w-0 gap-1">
            <Select
              className="min-w-0 flex-1"
              ariaLabel={t('env.housing')}
              value={preset}
              options={[...HOUSING_MATERIALS.map((m) => ({ value: m.id, label: t('env.mat.' + m.id) })), { value: 'custom', label: t('env.mat.custom') }]}
              onChange={(v) => {
                const m = HOUSING_MATERIALS.find((x) => x.id === v)
                if (m) st().updateSystem({ housing_cte: m.cte }, 'Housing material')
              }}
            />
            <NumberField className="w-20 shrink-0" ariaLabel={t('env.housingCte')} title={t('env.housingCte')} value={cte} min={-50} max={500} onCommit={(v) => v !== null && st().updateSystem({ housing_cte: v }, 'Housing expansion')} />
          </div>
          {envNow.perConfig && (
            <span className="col-span-2 text-small text-muted">{t('env.perConfig', { t: fmt(envNow.temperature, 4), p: fmt(envNow.pressure, 4) })}</span>
          )}
        </div>
      )}
    </div>
  )
}

/** Glass absorption: the catalogue internal transmittance per wavelength (opt-in; engine: system.medium_absorption). */
function GlassSection() {
  const t = useT()
  const on = useProjectStore((s) => !!s.project.system.catalog_absorption)
  const st = useProjectStore.getState
  return (
    <div className="mt-3 space-y-2 border-t border-line pt-3">
      <div className="text-small font-semibold tracking-wide text-muted uppercase">{t('sys.glass')}</div>
      <span title={t('sys.catAbsHint')}>
        <Checkbox checked={on} onChange={(v) => st().updateSystem({ catalog_absorption: v }, v ? 'Catalogue absorption on' : 'Catalogue absorption off')} label={<span>{t('sys.catAbs')}</span>} />
      </span>
    </div>
  )
}

const DEFAULT_SENSOR = { pixel_pitch_um: 3.45, fill_factor: 1, width_px: 640, height_px: 480, full_well_e: 10000, read_noise_e: 5, bit_depth: 12 }

/** The image sensor (engine: analysis/imaging.py): pixel MTF in the MTF analysis and the image simulation. */
function SensorSection() {
  const t = useT()
  const sensor = useProjectStore((s) => s.project.system.sensor ?? null)
  const st = useProjectStore.getState
  const put = (patch: Partial<typeof DEFAULT_SENSOR>, label: string) => st().updateSystem({ sensor: { ...(sensor ?? DEFAULT_SENSOR), ...patch } }, label)
  return (
    <div className="mt-3 space-y-2 border-t border-line pt-3">
      <div className="text-small font-semibold tracking-wide text-muted uppercase">{t('sys.sensor')}</div>
      <span title={t('sys.sensorHint')}>
        <Checkbox checked={!!sensor} onChange={(v) => st().updateSystem({ sensor: v ? DEFAULT_SENSOR : null }, v ? 'Sensor on' : 'Sensor off')} label={<span>{t('sys.sensorOn')}</span>} />
      </span>
      {sensor && (
        <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-2">
          <Label form hint={t('sys.pitchHint')}>{t('sys.pitch')}</Label>
          <NumberField ariaLabel={t('sys.pitch')} value={sensor.pixel_pitch_um} min={0.1} max={100} onCommit={(v) => v !== null && put({ pixel_pitch_um: v }, 'Pixel pitch')} />
          <Label form hint={t('sys.fillHint')}>{t('sys.fill')}</Label>
          <NumberField ariaLabel={t('sys.fill')} value={sensor.fill_factor * 100} min={1} max={100} onCommit={(v) => v !== null && put({ fill_factor: v / 100 }, 'Fill factor')} />
          <Label form>{t('sys.pixels')}</Label>
          <div className="flex min-w-0 items-center gap-1">
            <NumberField className="w-20" ariaLabel={t('sys.widthPx')} value={sensor.width_px} integer min={8} max={16384} onCommit={(v) => v !== null && put({ width_px: v }, 'Sensor width')} />
            <span className="text-faint">×</span>
            <NumberField className="w-20" ariaLabel={t('sys.heightPx')} value={sensor.height_px} integer min={8} max={16384} onCommit={(v) => v !== null && put({ height_px: v }, 'Sensor height')} />
          </div>
          <Label form hint={t('sys.fullWellHint')}>{t('sys.fullWell')}</Label>
          <NumberField ariaLabel={t('sys.fullWell')} value={sensor.full_well_e} min={1} max={1e7} onCommit={(v) => v !== null && put({ full_well_e: v }, 'Full well')} />
          <Label form>{t('sys.readNoise')}</Label>
          <NumberField ariaLabel={t('sys.readNoise')} value={sensor.read_noise_e} min={0} max={1e4} onCommit={(v) => v !== null && put({ read_noise_e: v }, 'Read noise')} />
          <Label form>{t('sys.bitDepth')}</Label>
          <NumberField ariaLabel={t('sys.bitDepth')} value={sensor.bit_depth} integer min={1} max={16} onCommit={(v) => v !== null && put({ bit_depth: v }, 'Bit depth')} />
          <span className="col-span-2 num text-small text-muted">
            {t('sys.sensorSize', { w: fmt((sensor.width_px * sensor.pixel_pitch_um) / 1000, 4), h: fmt((sensor.height_px * sensor.pixel_pitch_um) / 1000, 4) })}
          </span>
        </div>
      )}
    </div>
  )
}

