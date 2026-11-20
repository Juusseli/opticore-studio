import { Download, Library, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useT } from '../../lib/i18n'
import { fetchRiiIndex, fetchRiiPages, RII_REPO, riiRevision, type RiiMaker } from '../../lib/rii'
import { useCatalogStore } from '../../store/catalogStore'
import { useEngineStore } from '../../store/engineStore'
import { useUiStore } from '../../store/uiStore'
import { Badge, Button } from '../common/ui'

const DEFAULT = ['schott', 'ohara', 'hoya', 'cdgm', 'hikari', 'sumita']

type Done = { name: string; glasses: number; flagged: number; failed: number; error?: string }

/** Installs manufacturer glass catalogues from the refractiveindex.info database (downloaded by this browser). */
export function RiiInstaller({ onClose, onInstalled }: { onClose: () => void; onInstalled: (catalog: string) => void }) {
  const t = useT()
  const toast = useUiStore((s) => s.toast)
  const catalogs = useCatalogStore((s) => s.catalogs)
  const [ref, setRef] = useState<string | null>(null)
  const [makers, setMakers] = useState<RiiMaker[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [picked, setPicked] = useState<string[]>(DEFAULT)
  const [progress, setProgress] = useState<{ maker: string; done: number; total: number } | null>(null)
  const [done, setDone] = useState<Done[]>([])
  const abort = useRef<AbortController | null>(null)

  useEffect(() => {
    const ac = new AbortController()
    ;(async () => {
      try {
        const r = await riiRevision(ac.signal)
        const list = await fetchRiiIndex(r, ac.signal)
        setRef(r)
        setMakers(list)
      } catch (e) {
        if ((e as Error).name !== 'AbortError') setError((e as Error).message)
      }
    })()
    return () => ac.abort()
  }, [])
  useEffect(() => () => abort.current?.abort(), [])

  const chosen = (makers ?? []).filter((m) => picked.includes(m.id))
  const total = chosen.reduce((n, m) => n + m.paths.length, 0)

  const install = async () => {
    if (!ref || !chosen.length) return
    const ac = new AbortController()
    abort.current = ac
    const out: Done[] = []
    setDone([])
    const log = useEngineStore.getState().log_
    try {
      for (const m of chosen) {
        setProgress({ maker: m.name, done: 0, total: m.paths.length })
        try {
          const { files, failed } = await fetchRiiPages(ref, m.paths, (d, n) => setProgress({ maker: m.name, done: d, total: n }), ac.signal)
          if (!files.length) throw new Error(t('rii.noFiles'))
          const note = [`refractiveindex.info database revision ${ref}, ${files.length} pages${failed.length ? `; ${failed.length} could not be downloaded: ${failed.slice(0, 10).join(', ')}${failed.length > 10 ? ', …' : ''}` : ''}`]
          const cat = await useCatalogStore.getState().importRii(m.name, files, note)
          const flagged = cat.records.filter((r) => r.verified === false).length
          out.push({ name: cat.name, glasses: cat.records.length, flagged, failed: failed.length })
          log(flagged || failed.length ? 'warning' : 'success', `Glass catalogue ${cat.name} installed from refractiveindex.info: ${cat.records.length} glasses` + (flagged ? `, ${flagged} flagged` : '') + (failed.length ? `, ${failed.length} pages not downloaded` : ''))
        } catch (e) {
          if ((e as Error).name === 'AbortError') throw e
          out.push({ name: m.name, glasses: 0, flagged: 0, failed: 0, error: (e as Error).message })
          log('error', `Glass catalogue ${m.name} from refractiveindex.info failed: ${(e as Error).message}`)
        }
        setDone([...out])
      }
      const ok = out.filter((d) => !d.error)
      toast(out.some((d) => d.error) ? 'warning' : 'success', t('rii.installed', { n: ok.reduce((n, d) => n + d.glasses, 0), c: ok.length }))
      if (ok.length === 1) onInstalled(ok[0].name)
    } catch {
      toast('info', t('rii.cancelled'))
    } finally {
      setProgress(null)
      abort.current = null
    }
  }

  const busy = progress !== null
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b border-line px-3 py-2">
        <Library size={14} className="text-accent" />
        <span className="text-body font-semibold">{t('rii.title')}</span>
        <span className="flex-1" />
        <Button size="sm" onClick={onClose} disabled={busy}>
          {t('c.close')}
        </Button>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-auto p-3 text-small">
        <div className="leading-relaxed text-muted">{t('rii.intro')}</div>
        <div className="text-faint">
          <a className="text-accent hover:underline" href={`https://github.com/${RII_REPO}`} target="_blank" rel="noreferrer">
            github.com/{RII_REPO}
          </a>{' '}
          · CC0 1.0 · {ref ? (ref === 'main' ? 'main' : ref.slice(0, 10)) : '…'}
        </div>
        {error && <div className="rounded bg-danger/10 px-2 py-1 text-danger">{t('rii.indexFailed', { msg: error })}</div>}
        {!makers && !error && <div className="text-faint">{t('rii.loading')}</div>}
        {makers && (
          <table className="eng-table">
            <thead>
              <tr>
                <th className="w-6"></th>
                <th>{t('rii.maker')}</th>
                <th className="text-right">{t('rii.count')}</th>
                <th>{t('rii.groups')}</th>
                <th>{t('rii.installedCol')}</th>
              </tr>
            </thead>
            <tbody>
              {makers.map((m) => {
                const have = catalogs.find((c) => c.id === m.name)
                const on = picked.includes(m.id)
                return (
                  <tr key={m.id} className={on ? 'selected cursor-pointer' : 'cursor-pointer'} onClick={() => !busy && setPicked((p) => (on ? p.filter((x) => x !== m.id) : [...p, m.id]))}>
                    <td className="px-2">
                      <input type="checkbox" readOnly checked={on} disabled={busy} aria-label={m.name} className="accent-[var(--c-accent)]" />
                    </td>
                    <td className="px-2 font-medium">{m.name}</td>
                    <td className="num px-2 text-right">{m.paths.length}</td>
                    <td className="px-2 text-muted">{m.groups.join(', ')}</td>
                    <td className="px-2 text-faint">
                      {have ? (
                        <>
                          <Badge tone={have.filename === 'refractiveindex.info' ? 'ok' : 'default'}>{have.filename === 'refractiveindex.info' ? 'refractiveindex.info' : 'AGF'}</Badge> {new Date(have.imported_at).toLocaleDateString()}
                        </>
                      ) : (
                        ''
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        {chosen.some((m) => catalogs.some((c) => c.id === m.name)) && <div className="rounded bg-warn/10 px-2 py-1 text-warn">{t('rii.replaces')}</div>}
        <div className="flex items-center gap-2">
          <Button variant="primary" size="sm" disabled={!ref || !chosen.length || busy} onClick={() => void install()}>
            <Download size={14} /> {t('rii.install', { n: total, c: chosen.length })}
          </Button>
          {busy && (
            <>
              <div className="h-1.5 w-40 overflow-hidden rounded bg-hover">
                <div className="h-full bg-accent transition-[width]" style={{ width: `${(100 * progress.done) / Math.max(progress.total, 1)}%` }} />
              </div>
              <span className="num text-muted">
                {progress.maker} {progress.done} / {progress.total}
              </span>
              <Button size="sm" onClick={() => abort.current?.abort()}>
                <X size={12} /> {t('c.cancel')}
              </Button>
            </>
          )}
        </div>
        {done.length > 0 && (
          <div className="space-y-0.5">
            {done.map((d) => (
              <div key={d.name} className={d.error ? 'text-danger' : d.flagged || d.failed ? 'text-warn' : 'text-ok'}>
                {d.name}: {d.error ?? t('rii.result', { n: d.glasses, f: d.flagged, x: d.failed })}
              </div>
            ))}
          </div>
        )}
        <div className="leading-relaxed text-faint">{t('rii.note')}</div>
      </div>
    </div>
  )
}
