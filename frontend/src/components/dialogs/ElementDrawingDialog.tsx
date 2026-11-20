import { Download, Printer } from 'lucide-react'
import { useMemo, useState } from 'react'
import { elementDrawingSvg } from '../../lib/drawing'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import type { ElementsResult } from '../../lib/types'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { useAnalysis } from '../views/useAnalysis'
import { Button, Dialog, Select, Spinner } from '../common/ui'

/** ISO 10110 drawings of the lens elements (engine: analysis/elements.py; layout: lib/drawing.ts). */
export function ElementDrawingDialog() {
  const t = useT()
  const close = useUiStore((s) => s.closeDialog)
  const arg = useUiStore((s) => s.dialogArg) as { surfaceId?: string } | null
  const project = useProjectStore((s) => s.project)
  const { data, error, loading } = useAnalysis<ElementsResult>('elements', { tolerancing: project.tolerancing })
  const els = data?.elements ?? []
  const initial = Math.max(0, els.findIndex((e) => arg?.surfaceId && e.surface_ids.includes(arg.surfaceId)))
  const [pick, setPick] = useState<number | null>(null)
  const k = Math.min(pick ?? initial, Math.max(0, els.length - 1))
  const el = els[k]
  const [today] = useState(() => new Date().toISOString().slice(0, 10)) // the drawing's date, fixed while the dialog is open
  const svg = useMemo(() => (el ? elementDrawingSvg(el, { project: project.metadata.name, date: today, t }) : ''), [el, project.metadata.name, today, t])
  const fileName = el ? `${project.metadata.name.replace(/[^\w.-]+/g, '_').slice(0, 60) || 'project'}_${el.name}.svg` : 'element.svg'

  const download = () => {
    const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }))
    const a = document.createElement('a')
    a.href = url
    a.download = fileName
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const print = () => {
    const w = window.open('', '_blank')
    if (!w) return
    w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${fileName}</title><style>@page{size:A4 landscape;margin:0}html,body{margin:0}svg{width:297mm;height:210mm;display:block}</style></head><body>${svg}</body></html>`)
    w.document.close()
    w.focus()
    w.print()
  }

  return (
    <Dialog
      title={t('dwd.title')}
      onClose={close}
      width={1000}
      footer={
        <>
          <Button onClick={download} disabled={!el}>
            <Download size={14} /> {t('dwd.download')}
          </Button>
          <Button onClick={print} disabled={!el}>
            <Printer size={14} /> {t('dwd.print')}
          </Button>
          <Button variant="primary" onClick={close}>
            {t('c.ok')}
          </Button>
        </>
      }
    >
      <div className="space-y-2 p-3">
        <div className="flex items-center gap-2">
          <span className="text-small text-muted">{t('dwd.element')}</span>
          <Select<number>
            className="h-6 w-[260px] text-small"
            ariaLabel={t('dwd.element')}
            value={k}
            options={els.map((e, i) => ({ value: i, label: `${e.name} · ${e.material.name} · S${e.surfaces[0]}–S${e.surfaces[1]}` }))}
            onChange={setPick}
          />
          {loading && <Spinner size={12} />}
          {el && (
            <span className="num text-small text-muted">
              Ø {fmt(2 * el.rim_radius_mm, 5)} mm · {fmt(el.volume_mm3, 5)} mm³{el.mass_g !== null ? ` · ${fmt(el.mass_g, 4)} g` : ''}
            </span>
          )}
        </div>
        {error && <div className="text-small text-danger">{error}</div>}
        {data && !els.length && <div className="text-muted">{t('dwd.none')}</div>}
        {el && (
          <>
            {/* the drawing is paper: white in both themes */}
            <div className="overflow-auto rounded border border-line" dangerouslySetInnerHTML={{ __html: svg.replace(/width="297mm" height="210mm"/, 'width="100%"') }} />
            {[...el.notes, ...(data?.skipped ?? []).map((s) => `S${s.surfaces.join('–')}: ${s.reason}`)].map((n) => (
              <div key={n} className="text-small text-warn">
                {n}
              </div>
            ))}
          </>
        )}
        <div className="text-caption leading-snug text-faint">{t('dwd.note')}</div>
      </div>
    </Dialog>
  )
}
