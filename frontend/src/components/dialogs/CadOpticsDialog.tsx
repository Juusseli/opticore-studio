import { Wand2 } from 'lucide-react'
import { designSnapshot, sameDesign } from '../../store/designGuard'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../../lib/api'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import type { CadAsset, RecognizedElement } from '../../lib/types'
import { LENGTH_TO_MM } from '../../lib/units'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { Badge, Button, Checkbox, Dialog, NumberField, Select, Spinner } from '../common/ui'
import { MaterialCell } from '../editors/LensDataEditor'
import { surfaceTitle } from '../editors/surfaceTitle'

const faceText = (f: RecognizedElement['front']) =>
  f.type === 'plane' ? 'plane' : `${f.type} R ${fmt(f.radius, 7)}${f.conic ? ` k ${fmt(f.conic, 5)}` : ''}${f.aspheric.length ? ` +A${4}…` : ''}`

/** Convert a recognised CAD lens/mirror into optical surfaces of the sequential system. */
export function CadOpticsDialog() {
  const t = useT()
  const close = useUiStore((s) => s.closeDialog)
  const toast = useUiStore((s) => s.toast)
  const arg = useUiStore((s) => s.dialogArg) as { assetId: string } | null
  const project = useProjectStore((s) => s.project)
  const asset = project.cad_assets.find((a) => a.id === arg?.assetId) as CadAsset | undefined
  const sys = project.system
  const n = sys.surfaces.length
  const [rec, setRec] = useState<{ elements: RecognizedElement[]; skipped: { name: string; reason: string }[] } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [sel, setSel] = useState<Set<number>>(new Set())
  const [mats, setMats] = useState<Record<number, string>>({})
  const [role, setRole] = useState<'lens' | 'mirror'>('lens')
  const [placement, setPlacement] = useState<'cad' | 'axis'>('cad')
  const [after, setAfter] = useState(Math.max(0, n - 2))
  const [gap, setGap] = useState(5)
  const [hide, setHide] = useState(true)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!asset) return
    let alive = true
    api
      .cadRecognize(asset)
      .then((r) => {
        if (!alive) return
        setRec(r)
        setSel(new Set(r.elements.map((_, k) => k)))
      })
      .catch((e) => alive && setErr((e as Error).message))
    return () => {
      alive = false
    }
  }, [asset])

  const afterOpts = useMemo(() => sys.surfaces.slice(0, n - 1).map((s, i) => ({ value: i, label: `${i}: ${surfaceTitle(s, i, n)}` })), [sys.surfaces, n])
  if (!asset) return null

  const insert = async () => {
    if (!rec) return
    setBusy(true)
    setErr(null)
    const idx = [...sel].sort((a, b) => a - b)
    try {
      const snap = designSnapshot()
      const r = await api.cadInsert({
        system: sys,
        custom_materials: project.custom_materials,
        asset,
        elements: idx,
        role,
        materials: idx.map((k) => mats[k] ?? 'N-BK7'),
        after,
        placement,
        gap,
        reflect_face: 'front',
      })
      if (!sameDesign(snap)) {
        toast('warning', t('c.staleDesign'))
        return
      }
      const st = useProjectStore.getState()
      st.replaceSystem(r.system, `Insert optics from ${asset.name}`, `Before inserting ${asset.name}`)
      if (hide) st.updateCadAsset(asset.id, { visible: false }, 'Hide converted CAD model')
      for (const note of r.report.notes) useEngineStore.getState().log_('info', note)
      useEngineStore.getState().log_('success', `${asset.name}: ${r.report.count} surface(s) inserted after surface ${after} (${placement === 'cad' ? 'CAD placement' : `on axis, gap ${gap} mm`})`)
      toast('success', `${r.report.count} ${t('cado.inserted')}`)
      st.select(r.report.first_index)
      close()
    } catch (e) {
      setErr((e as Error).message)
    }
    setBusy(false)
  }

  return (
    <Dialog
      title={`${t('cado.title')}: ${asset.name}`}
      icon={<Wand2 size={16} className="text-accent" />}
      onClose={close}
      width={760}
      footer={
        <>
          <Button onClick={close}>{t('c.cancel')}</Button>
          <Button variant="primary" disabled={!rec || sel.size === 0 || busy || (role === 'mirror' && sel.size !== 1)} onClick={insert}>
            {busy ? <Spinner size={12} /> : null} {t('cado.insert')}
          </Button>
        </>
      }
    >
      <div className="space-y-3 p-4">
        {!rec && !err && (
          <div className="flex items-center gap-2 text-muted">
            <Spinner size={14} /> {t('cado.analysing')}
          </div>
        )}
        {rec && (
          <>
            <table className="eng-table">
              <thead>
                <tr>
                  <th className="w-8"></th>
                  <th>{t('cad.name')}</th>
                  <th>{t('cado.front')}</th>
                  <th>{t('cado.back')}</th>
                  <th className="text-right">{t('lde.thickness')}</th>
                  <th className="text-right">Ø (mm)</th>
                  {role === 'lens' && <th className="w-[130px]">{t('lde.material')}</th>}
                </tr>
              </thead>
              <tbody>
                {rec.elements.map((e, k) => (
                  <tr key={k}>
                    <td className="text-center">
                      <Checkbox
                        checked={sel.has(k)}
                        onChange={(v) => {
                          const s = new Set(sel)
                          if (v) s.add(k)
                          else s.delete(k)
                          setSel(s)
                        }}
                      />
                    </td>
                    <td className="px-2">{e.name}</td>
                    <td className="num px-2" title={e.front.exact ? 'exact' : `fitted: rms ${e.front.fit_rms_mm.toExponential(1)} mm, max ${e.front.fit_max_mm.toExponential(1)} mm`}>
                      {faceText(e.front)} {!e.front.exact && <Badge tone="warn">fit</Badge>}
                    </td>
                    <td className="num px-2" title={e.back.exact ? 'exact' : `fitted: rms ${e.back.fit_rms_mm.toExponential(1)} mm, max ${e.back.fit_max_mm.toExponential(1)} mm`}>
                      {faceText(e.back)} {!e.back.exact && <Badge tone="warn">fit</Badge>}
                    </td>
                    <td className="num px-2 text-right">{fmt(e.thickness, 7)}</td>
                    <td className="num px-2 text-right">{fmt(2 * Math.max(e.front.semi_diameter, e.back.semi_diameter), 5)}</td>
                    {role === 'lens' && (
                      <td>
                        <MaterialCell value={mats[k] ?? 'N-BK7'} onCommit={(v) => setMats({ ...mats, [k]: v })} />
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            {rec.elements.length === 0 && <div className="text-muted">{t('cado.none')}</div>}
            {rec.skipped.map((s) => (
              <div key={s.name} className="text-small text-warn">
                {s.name}: {s.reason}
              </div>
            ))}
            <div className="grid grid-cols-[150px_1fr] items-center gap-2">
              <span className="text-muted">{t('cado.role')}</span>
              <Select
                className="w-[260px]"
                value={role}
                options={[
                  { value: 'lens', label: t('cado.asLens') },
                  { value: 'mirror', label: t('cado.asMirror') },
                ]}
                onChange={setRole}
              />
              <span className="text-muted">{t('cado.placement')}</span>
              <Select
                className="w-[260px]"
                value={placement}
                options={[
                  { value: 'cad', label: t('cado.atCad') },
                  { value: 'axis', label: t('cado.onAxis') },
                ]}
                onChange={setPlacement}
              />
              <span className="text-muted">{t('cado.after')}</span>
              <Select className="w-[260px]" value={after} options={afterOpts} onChange={setAfter} />
              {placement === 'axis' && (
                <>
                  <span className="text-muted">{t('cado.gap')}</span>
                  <NumberField className="w-28" value={gap} units={LENGTH_TO_MM} onCommit={(v) => setGap(v ?? 0)} />
                </>
              )}
            </div>
            <Checkbox checked={hide} onChange={setHide} label={<span className="text-muted">{t('cado.hide')}</span>} />
          </>
        )}
        {err && <div className="text-body text-danger">{err}</div>}
        <div className="text-caption leading-snug text-faint">{t('cado.help')}</div>
      </div>
    </Dialog>
  )
}
