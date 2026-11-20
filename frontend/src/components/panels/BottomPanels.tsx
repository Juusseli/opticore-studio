import { AlertCircle, AlertTriangle, Info } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { quickFocus, retrace, saveProject, undo, redo } from '../../actions'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { parseEngineering, LENGTH_TO_MM } from '../../lib/units'
import type { Diagnostic, Surface } from '../../lib/types'
import { explainKeys, type FixAction, fixActions } from '../../lib/diagnostics'
import { useUiStore } from '../../store/uiStore'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { Button, Empty } from '../common/ui'
import { cx } from '../common/uiUtils'

type LevelFilter = 'all' | Diagnostic['level']

/** One message: the cause in plain words, the engine's message, the fix and the actions that apply it. */
function MessageRow({ d }: { d: Diagnostic }) {
  const t = useT()
  const select = useProjectStore((s) => s.select)
  const setUi = useUiStore((s) => s.set)
  const { cause, fix } = explainKeys(d)
  const run = (a: FixAction) => {
    if (a === 'surface' && d.surface !== null) {
      select(d.surface)
      setUi({ bottomTab: 'lde', bottomOpen: true })
    } else if (a === 'system') setUi({ bottomTab: 'system', bottomOpen: true })
    else if (a === 'configs') setUi({ bottomTab: 'configs', bottomOpen: true })
    else if (a === 'mounts') setUi({ bottomTab: 'mounts', bottomOpen: true })
    else if (a === 'lde') setUi({ bottomTab: 'lde', bottomOpen: true })
    else if (a === 'materials') useUiStore.getState().openDialog('materials')
    else if (a === 'coatings') useUiStore.getState().openDialog('coatings')
  }
  const tone = d.level === 'error' ? 'text-danger' : d.level === 'warning' ? 'text-warn' : 'text-muted'
  return (
    <li className="flex cursor-pointer gap-2.5 border-b border-line px-3 py-2 hover:bg-hover" onClick={() => d.surface !== null && select(d.surface)}>
      <span className={cx('mt-0.5 shrink-0', tone)} role="img" aria-label={t('msg.' + d.level)}>
        {d.level === 'error' ? <AlertCircle size={14} /> : d.level === 'warning' ? <AlertTriangle size={14} /> : <Info size={14} />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-body font-medium">{t(cause)}</div>
        <div className="mt-0.5 text-small text-muted">
          <span className="font-medium text-fg">{t('dg.fix')}</span> {t(fix)}
        </div>
        <div className="mt-0.5 truncate text-small text-faint" title={d.message}>
          {d.surface !== null && <span className="num mr-1.5">S{d.surface}</span>}
          {d.message}
          <span className="num ml-1.5">· {d.code}</span>
        </div>
      </div>
      <div className="flex shrink-0 flex-wrap items-start justify-end gap-1">
        {fixActions(d).map((a) => (
          <Button
            key={a}
            size="sm"
            onClick={(e) => {
              e.stopPropagation()
              run(a)
            }}
          >
            {t('dg.act.' + a, { n: d.surface ?? '' })}
          </Button>
        ))}
      </div>
    </li>
  )
}

/** Validation: the engine's diagnostics with causes and fixes (non-modal; the status bar count opens it). */
export function MessagesPanel() {
  const t = useT()
  const ev = useEngineStore((s) => s.evaluation)
  const evalError = useEngineStore((s) => s.evalError)
  const [filter, setFilter] = useState<LevelFilter>('all')
  // a failed evaluation carries its diagnostics in the error details (other details are validation errors)
  const details = Array.isArray(evalError?.details) ? (evalError!.details as Record<string, unknown>[]) : []
  const failed = details.filter((d) => d && typeof d === 'object' && 'code' in d) as unknown as Diagnostic[]
  const other = details.filter((d) => d && typeof d === 'object' && !('code' in d)) as { loc?: string[]; msg?: string; message?: string }[]
  const diags = evalError ? failed : (ev?.diagnostics ?? [])
  const count = (l: Diagnostic['level']) => diags.filter((d) => d.level === l).length
  const order = { error: 0, warning: 1, info: 2 }
  const shown = diags.filter((d) => filter === 'all' || d.level === filter).sort((a, b) => order[a.level] - order[b.level])
  return (
    <div className="flex h-full min-h-0 flex-col">
      {evalError && (
        <div className="m-2 flex shrink-0 items-start gap-2 rounded-md border border-danger/40 bg-danger/10 p-2.5 text-danger">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <div className="min-w-0">
            <div className="font-semibold">{t('dg.failed')}</div>
            <div className="text-body">{evalError.message}</div>
            {other.map((d, i) => (
              <div key={i} className="mt-1 text-small opacity-90">
                {d.loc ? d.loc.join('.') + ': ' : ''}
                {d.msg ?? d.message}
              </div>
            ))}
          </div>
        </div>
      )}
      {!diags.length ? (
        !evalError && <Empty>{t('msg.none')}</Empty>
      ) : (
        <>
          <div className="flex h-8 shrink-0 items-center gap-1 border-b border-line px-2" role="tablist" aria-label={t('bt.messages')}>
            {(['all', 'error', 'warning', 'info'] as const).map((l) => (
              <button
                key={l}
                role="tab"
                aria-selected={filter === l}
                onClick={() => setFilter(l)}
                className={cx('h-6 rounded-md px-2 text-small', filter === l ? 'bg-select text-fg' : 'text-muted hover:bg-hover hover:text-fg')}
              >
                {t(l === 'all' ? 'dg.all' : l === 'error' ? 'dg.errors' : l === 'warning' ? 'dg.warnings' : 'dg.infos')} ({l === 'all' ? diags.length : count(l)})
              </button>
            ))}
          </div>
          <ul className="min-h-0 flex-1 overflow-auto">
            {shown.map((d, i) => (
              <MessageRow key={`${d.code}-${d.surface}-${i}`} d={d} />
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

const HELP = `Commands:
  help                         this help
  efl | bfl | fnum | track     paraxial values (primary wavelength)
  select <n>                   select surface n
  set <n> <param> <value>      param: radius|thickness|conic|material|semi|label
  stop <n>                     make surface n the aperture stop
  insert <n>                   insert a surface before n
  delete <n>                   delete surface n
  focus                        quick focus (minimise RMS spot)
  trace                        re-trace rays
  undo | redo | save
  clear                        clear the console`

export function ConsolePanel() {
  const t = useT()
  const log = useEngineStore((s) => s.log)
  const add = useEngineStore((s) => s.log_)
  const clear = useEngineStore((s) => s.clearLog)
  const [cmd, setCmd] = useState('')
  const [hist, setHist] = useState<string[]>([])
  const [hi, setHi] = useState(-1)
  const box = useRef<HTMLDivElement>(null)
  // scroll only the log box (scrollIntoView would also scroll the page, and in current Chromium it returns
  // a Promise, which must not be returned from an effect)
  useEffect(() => {
    const el = box.current
    if (el) el.scrollTop = el.scrollHeight
  }, [log.length])

  const run = (line: string) => {
    const parts = line.trim().split(/\s+/)
    const c = parts[0]?.toLowerCase()
    const st = useProjectStore.getState()
    const ev = useEngineStore.getState().evaluation
    const pd = ev?.paraxial[String(st.project.system.primary_wavelength)]
    const n = st.project.system.surfaces.length
    add('info', `> ${line}`)
    const idx = (s: string) => {
      const k = parseInt(s, 10)
      if (!Number.isInteger(k) || k < 0 || k >= n) throw new Error(`Surface index must be 0…${n - 1}`)
      return k
    }
    try {
      switch (c) {
        case 'help':
          add('info', HELP)
          break
        case 'efl':
          add('success', `EFL = ${fmt(pd?.efl, 10)} mm (paraxial)`)
          break
        case 'bfl':
          add('success', `BFL = ${fmt(pd?.bfl, 10)} mm (paraxial)`)
          break
        case 'fnum':
          add('success', `F/# = ${fmt(pd?.image_space_fnum, 8)}, working F/# = ${fmt(pd?.working_fnum, 8)}`)
          break
        case 'track':
          add('success', `Total track = ${fmt(pd?.total_track, 10)} mm`)
          break
        case 'select':
          st.select(idx(parts[1]))
          break
        case 'stop':
          st.setStop(idx(parts[1]))
          break
        case 'insert':
          st.insertSurface(idx(parts[1]))
          break
        case 'delete':
          st.deleteSurfaces([idx(parts[1])])
          break
        case 'set': {
          const i = idx(parts[1])
          const p = parts[2]?.toLowerCase()
          const raw = parts.slice(3).join(' ')
          const patch: Partial<Surface> = {}
          if (p === 'material') patch.material = raw.toUpperCase()
          else if (p === 'label') patch.label = raw
          else {
            const r = parseEngineering(raw, { allowInfinity: p === 'radius' || (p === 'thickness' && i === 0), units: LENGTH_TO_MM })
            if (!r.ok) throw new Error(r.error)
            if (p === 'radius') patch.radius = r.value
            else if (p === 'thickness') patch.thickness = r.value
            else if (p === 'conic') patch.conic = r.value ?? 0
            else if (p === 'semi') {
              patch.semi_diameter = r.value ?? 0
              patch.semi_diameter_mode = 'fixed'
            } else throw new Error(`Unknown parameter '${p}'`)
          }
          st.updateSurface(i, patch, `Console: set ${i} ${p}`)
          add('success', `Surface ${i}: ${p} = ${raw}`)
          break
        }
        case 'focus':
          quickFocus()
          break
        case 'trace':
          retrace()
          break
        case 'undo':
          undo()
          break
        case 'redo':
          redo()
          break
        case 'save':
          saveProject()
          break
        case 'clear':
          clear()
          break
        case undefined:
        case '':
          break
        default:
          throw new Error(`Unknown command '${c}'. Type "help".`)
      }
    } catch (e) {
      add('error', (e as Error).message)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={box} className="min-h-0 flex-1 overflow-auto p-2 num text-small leading-relaxed">
        {log.map((l) => (
          <div key={l.id} className={cx('whitespace-pre-wrap', l.level === 'error' ? 'text-danger' : l.level === 'warning' ? 'text-warn' : l.level === 'success' ? 'text-ok' : 'text-muted')}>
            <span className="text-faint">{l.time} </span>
            {l.text}
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2 border-t border-line p-1.5">
        <span className="num text-accent">›</span>
        <input
          className="field-input num flex-1"
          aria-label={t('bt.console')}
          placeholder={t('con.placeholder')}
          value={cmd}
          onChange={(e) => setCmd(e.target.value)}
          onKeyDown={(e) => {
            e.stopPropagation()
            if (e.key === 'Enter' && cmd.trim()) {
              run(cmd)
              setHist([cmd, ...hist].slice(0, 100))
              setHi(-1)
              setCmd('')
            } else if (e.key === 'ArrowUp') {
              const k = Math.min(hi + 1, hist.length - 1)
              if (k >= 0) {
                setHi(k)
                setCmd(hist[k])
              }
              e.preventDefault()
            } else if (e.key === 'ArrowDown') {
              const k = hi - 1
              setHi(Math.max(-1, k))
              setCmd(k >= 0 ? hist[k] : '')
              e.preventDefault()
            }
          }}
        />
        <Button size="sm" variant="ghost" onClick={clear}>
          {t('con.clear')}
        </Button>
      </div>
    </div>
  )
}
