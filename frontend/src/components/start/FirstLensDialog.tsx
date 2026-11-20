import { Check, ChevronLeft, ChevronRight, Sparkles } from 'lucide-react'
import { useMemo, useState } from 'react'
import { openFirstLens } from '../../actions'
import { api } from '../../lib/api'
import { useT } from '../../lib/i18n'
import { DEFAULT_FIRST_LENS, type FirstLensSpec, stepValid, WAVELENGTH_PRESETS, type WavelengthPreset } from '../../lib/firstLens'
import { useEngineStore } from '../../store/engineStore'
import { useUiStore } from '../../store/uiStore'
import { Button, Dialog, NumberField, Select, Spinner } from '../common/ui'
import { cx } from '../common/uiUtils'

const STEPS = ['fl.stepLens', 'fl.stepWavelengths', 'fl.stepGlass'] as const

export function FirstLensDialog() {
  const t = useT()
  const close = useUiStore((s) => s.closeDialog)
  const materials = useEngineStore((s) => s.materials)
  const online = useEngineStore((s) => s.backend === 'online')
  const [step, setStep] = useState(0)
  const [spec, setSpec] = useState<FirstLensSpec>(DEFAULT_FIRST_LENS)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = (p: Partial<FirstLensSpec>) => {
    setSpec((s) => ({ ...s, ...p }))
    setError(null)
  }
  const glasses = useMemo(
    () =>
      materials
        .filter((m) => (m.category ?? 'glass') === 'glass' && m.nd !== null && m.vd !== null)
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((m) => ({ value: m.name, label: `${m.name}  ·  nd ${m.nd!.toFixed(4)}  ·  Vd ${m.vd!.toFixed(1)}` })),
    [materials],
  )
  const mono = WAVELENGTH_PRESETS[spec.preset].values.length === 1
  const create = async () => {
    setBusy(true)
    setError(null)
    try {
      const w = WAVELENGTH_PRESETS[spec.preset]
      const r = await api.firstLens({
        focal_length: spec.focal_length,
        f_number: spec.f_number,
        half_field_deg: spec.half_field_deg,
        wavelengths: [...w.values],
        primary: w.primary,
        kind: spec.kind,
        crown: spec.crown,
        flint: spec.flint,
        name: t(spec.kind === 'singlet' ? 'fl.nameSinglet' : 'fl.nameDoublet', { f: spec.focal_length, n: spec.f_number }),
      })
      close()
      await openFirstLens(r.project)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const last = step === STEPS.length - 1
  return (
    <Dialog
      title={t('fl.title')}
      onClose={close}
      width={560}
      icon={<Sparkles size={16} className="text-accent" />}
      footer={
        <>
          {error && <span className="mr-auto max-w-[300px] truncate text-small text-danger" title={error}>{error}</span>}
          {!online && <span className="mr-auto text-small text-warn">{t('start.needsEngine')}</span>}
          <Button onClick={() => (step ? setStep(step - 1) : close())}>
            {step ? (
              <>
                <ChevronLeft size={14} /> {t('fl.back')}
              </>
            ) : (
              t('c.cancel')
            )}
          </Button>
          {last ? (
            <Button variant="primary" disabled={busy || !online || !stepValid(step, spec)} onClick={create}>
              {busy ? <Spinner size={12} /> : <Check size={14} />} {t('fl.create')}
            </Button>
          ) : (
            <Button variant="primary" disabled={!stepValid(step, spec)} onClick={() => setStep(step + 1)}>
              {t('fl.next')} <ChevronRight size={14} />
            </Button>
          )}
        </>
      }
    >
      <ol className="flex border-b border-line bg-panel-2 px-4 text-body" aria-label={t('fl.title')}>
        {STEPS.map((k, i) => (
          <li key={k} className={cx('flex items-center gap-1.5 py-2 pr-5', i === step ? 'font-semibold text-fg' : i < step ? 'text-ok' : 'text-faint')} aria-current={i === step ? 'step' : undefined}>
            <span className={cx('flex h-4 w-4 items-center justify-center rounded-full text-caption', i === step ? 'bg-accent-strong text-white' : i < step ? 'bg-ok/20' : 'bg-hover text-muted')}>{i < step ? '✓' : i + 1}</span>
            {t(k)}
          </li>
        ))}
      </ol>
      <div className="space-y-3 p-4">
        {step === 0 && (
          <>
            <p className="text-body leading-relaxed text-muted">{t('fl.introLens')}</p>
            <div className="grid grid-cols-[170px_1fr] items-center gap-x-3 gap-y-2">
              <label className="text-muted" htmlFor="fl-f">{t('fl.focal')}</label>
              <NumberField className="w-28" ariaLabel={t('fl.focal')} value={spec.focal_length} min={0.1} max={100000} onCommit={(v) => set({ focal_length: v ?? 100 })} />
              <label className="text-muted">{t('fl.fnum')}</label>
              <span className="flex items-center gap-2">
                <NumberField className="w-28" ariaLabel={t('fl.fnum')} value={spec.f_number} min={0.5} max={1000} onCommit={(v) => set({ f_number: v ?? 5 })} />
                <span className="text-small text-faint">{t('fl.epd', { d: +(spec.focal_length / spec.f_number).toPrecision(4) })}</span>
              </span>
              <label className="text-muted">{t('fl.field')}</label>
              <NumberField className="w-28" ariaLabel={t('fl.field')} value={spec.half_field_deg} min={0} max={60} onCommit={(v) => set({ half_field_deg: v ?? 0 })} />
            </div>
          </>
        )}
        {step === 1 && (
          <>
            <p className="text-body leading-relaxed text-muted">{t('fl.introWl')}</p>
            <div role="radiogroup" aria-label={t('fl.stepWavelengths')} className="grid gap-2">
              {(Object.keys(WAVELENGTH_PRESETS) as WavelengthPreset[]).map((k) => (
                <button key={k} role="radio" aria-checked={spec.preset === k} onClick={() => set({ preset: k, kind: WAVELENGTH_PRESETS[k].values.length === 1 ? 'singlet' : spec.kind })} className={cx('rounded-lg border px-3 py-2 text-left', spec.preset === k ? 'border-accent bg-accent-soft' : 'border-line hover:border-line-strong')}>
                  <div className="text-body font-medium">{t('fl.wl.' + k)}</div>
                  <div className="num text-small text-muted">{WAVELENGTH_PRESETS[k].values.map((v) => (v * 1000).toFixed(1)).join(' · ')} nm</div>
                </button>
              ))}
            </div>
          </>
        )}
        {step === 2 && (
          <>
            <p className="text-body leading-relaxed text-muted">{t('fl.introGlass')}</p>
            <div role="radiogroup" aria-label={t('fl.kind')} className="grid grid-cols-2 gap-2">
              {(['singlet', 'doublet'] as const).map((k) => (
                <button
                  key={k}
                  role="radio"
                  aria-checked={spec.kind === k}
                  disabled={k === 'doublet' && mono}
                  onClick={() => set({ kind: k })}
                  className={cx('rounded-lg border px-3 py-2 text-left disabled:opacity-40', spec.kind === k ? 'border-accent bg-accent-soft' : 'border-line hover:border-line-strong')}
                >
                  <div className="text-body font-medium">{t('fl.kind.' + k)}</div>
                  <div className="text-small leading-snug text-muted">{t(k === 'doublet' && mono ? 'fl.kindMono' : 'fl.kindHint.' + k)}</div>
                </button>
              ))}
            </div>
            <div className="grid grid-cols-[170px_1fr] items-center gap-x-3 gap-y-2">
              <span className="text-muted">{t(spec.kind === 'doublet' ? 'fl.crown' : 'fl.glass')}</span>
              <Select className="w-full" ariaLabel={t(spec.kind === 'doublet' ? 'fl.crown' : 'fl.glass')} value={spec.crown} options={glasses.length ? glasses : [{ value: spec.crown, label: spec.crown }]} onChange={(v) => set({ crown: v })} />
              {spec.kind === 'doublet' && (
                <>
                  <span className="text-muted">{t('fl.flint')}</span>
                  <Select className="w-full" ariaLabel={t('fl.flint')} value={spec.flint} options={glasses.length ? glasses : [{ value: spec.flint, label: spec.flint }]} onChange={(v) => set({ flint: v })} />
                </>
              )}
            </div>
            <p className="text-small leading-relaxed text-faint">{t('fl.after')}</p>
          </>
        )}
      </div>
    </Dialog>
  )
}
