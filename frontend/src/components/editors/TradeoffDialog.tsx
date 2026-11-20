import { ChartLine } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import { fmt } from '../../lib/format'
import { useT } from '../../lib/i18n'
import { DATA } from '../../lib/palette'
import { nsBody } from '../../lib/project'
import type { ConstraintResult, TradeoffSnapshot } from '../../lib/types'
import { useOptStore } from '../../store/optStore'
import { useProjectStore } from '../../store/projectStore'
import { Plot } from '../common/Plot'
import { Badge, Button, Dialog, Spinner } from '../common/ui'

/** A relative change as "+1.2 %", "−0.4 %" or "±0.0 %". */
const percent = (x: number) => {
  const v = (x * 100).toFixed(1)
  return `${Number(v) > 0 ? '+' : Number(v) < 0 ? '−' : '±'}${v.replace('-', '')} %`
}

/** Evaluations per point: the points start from the optimised design, so they need fewer than the run. */
const BUDGET = 800

/** The best merit as one limit moves (engine optimize/tradeoff.py): one exact-constraint optimisation per target on
 * the engine's process pool, the result's own point and its price (the first-order tangent) for comparison. A point
 * can be shown as the result and applied like it. */
export function TradeoffDialog({ limit, onClose }: { limit: ConstraintResult; onClose: () => void }) {
  const t = useT()
  const { result, base, spec, custom, adopt } = useOptStore()
  const project = useProjectStore((s) => s.project)
  const [snap, setSnap] = useState<TradeoffSnapshot | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  const job = useRef<string | null>(null)
  // the result this curve was made for (its point and tangent stay, even when another point is shown)
  const origin = useRef(result)

  useEffect(() => {
    const r = origin.current
    if (!r || !base || !spec) return
    let alive = true
    let timer: number | null = null
    const poll = async (id: string) => {
      try {
        const s = await api.tradeoffStatus(id)
        if (!alive) return
        setSnap(s)
        if (s.state === 'running') timer = window.setTimeout(() => poll(id), 600)
        else job.current = null
      } catch (e) {
        if (alive) setError((e as Error).message)
      }
    }
    api
      .tradeoffStart({ system: r.system, base, custom_materials: custom, ...nsBody(project), optimization: spec, operand: limit.index, budget: Math.min(spec.max_evaluations, BUDGET) })
      .then(({ job_id }) => {
        job.current = job_id
        if (alive) poll(job_id)
        else api.tradeoffCancel(job_id).catch(() => undefined)
      })
      .catch((e) => alive && setError((e as Error).message))
    return () => {
      alive = false
      if (timer) window.clearTimeout(timer)
      if (job.current) api.tradeoffCancel(job.current).catch(() => undefined)
    }
    // one curve per dialog
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const use = async (index: number) => {
    if (!snap) return
    setBusy(index)
    try {
      adopt(await api.tradeoffPoint(snap.id, index))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const r0 = origin.current
  const m0 = r0?.final_merit ?? null
  const pts = (snap?.points ?? []).filter((p) => p.status === 'finished' && p.merit !== undefined)
  const ok = pts.filter((p) => p.feasible)
  const bad = pts.filter((p) => !p.feasible)
  // the front: the best design known for each value (a bound's tighter designs meet its looser values too)
  const front = (snap?.points ?? []).filter((p) => p.envelope !== null && p.envelope !== undefined).sort((a, b) => a.target - b.target)
  const here = snap?.points.find((p) => Math.abs(p.target - limit.target) <= 1e-12 * Math.max(1, Math.abs(p.target)))
  const better = here?.envelope !== null && here?.envelope !== undefined && m0 !== null && here.envelope < m0 * 0.99 ? here : null
  const xs = snap?.targets ?? []
  const slope = limit.price?.dmerit_dtarget ?? null
  const span = xs.length ? [Math.min(...xs), Math.max(...xs)] : null
  const name = t(`op.${limit.type}`)
  const running = !snap || snap.state === 'running'

  return (
    <Dialog
      title={t('td.title', { name })}
      icon={<ChartLine size={16} />}
      onClose={onClose}
      width={760}
      footer={
        <div className="flex w-full items-center gap-2">
          {running && <Spinner size={12} />}
          <span className="text-small text-muted">{snap ? t('td.progress', { n: snap.done, m: snap.total, s: snap.elapsed_s.toFixed(0) }) : t('td.starting')}</span>
          <div className="flex-1" />
          <Button onClick={onClose}>{t('c.close')}</Button>
        </div>
      }
    >
      <div className="text-small leading-relaxed text-muted">{t('td.hint')}</div>
      {error && <div className="mt-2 rounded bg-danger/10 px-2 py-1 text-small text-danger">{error}</div>}
      {better && m0 !== null && (
        <div className="mt-2 flex items-center gap-2 rounded bg-accent/10 px-2 py-1 text-small text-accent">
          <span className="flex-1">{t('td.better', { p: ((1 - (better.envelope as number) / m0) * 100).toFixed(1) })}</span>
          <Button size="sm" variant="primary" onClick={() => use(better.envelope_from ?? better.index)} disabled={busy !== null}>
            {t('td.use')}
          </Button>
        </div>
      )}
      <div className="mt-2 h-64">
        <Plot
          data={[
            { type: 'scatter', mode: 'lines', x: front.map((p) => p.target), y: front.map((p) => p.envelope as number), name: t('td.curve'), line: { color: DATA.primary, width: 2.5, shape: snap?.kind === 'bound' ? 'hv' : 'linear' } },
            { type: 'scatter', mode: 'markers', x: ok.map((p) => p.target), y: ok.map((p) => p.merit as number), name: t('td.points'), marker: { size: 7, color: DATA.secondary } },
            ...(bad.length ? [{ type: 'scatter' as const, mode: 'markers' as const, x: bad.map((p) => p.target), y: bad.map((p) => p.merit as number), name: t('td.unmet'), marker: { size: 9, color: DATA.marker, symbol: 'x' } }] : []),
            ...(m0 !== null && slope !== null && span ? [{ type: 'scatter' as const, mode: 'lines' as const, x: span, y: span.map((x) => m0 + slope * (x - limit.target)), name: t('td.tangent'), line: { color: DATA.reference, width: 1.5, dash: 'dash' as const } }] : []),
            ...(m0 !== null ? [{ type: 'scatter' as const, mode: 'markers' as const, x: [limit.target], y: [m0], name: t('td.current'), marker: { size: 12, color: DATA.target, symbol: 'star' } }] : []),
          ]}
          layout={{ xaxis: { title: { text: `${name} (${t('opt.target')})` } }, yaxis: { title: { text: t('ax.merit') } }, margin: { l: 64, r: 12, t: 8, b: 44 }, legend: { orientation: 'h', y: 1.02, yanchor: 'bottom', x: 1, xanchor: 'right' } }}
        />
      </div>
      <table className="eng-table mt-2">
        <thead>
          <tr>
            <th className="text-right">{t('opt.target')}</th>
            <th className="text-right">MF</th>
            <th className="text-right" title={t('td.frontHint')}>
              {t('td.front')}
            </th>
            <th className="text-right">{t('opt.change')}</th>
            <th className="text-center">{t('mf.met')}</th>
            <th className="text-right">{t('opt.evaluations')}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {xs.map((x) => {
            const p = snap?.points.find((q) => q.target === x)
            const here = Math.abs(x - limit.target) <= 1e-12 * Math.max(1, Math.abs(x))
            return (
              <tr key={x} className={here ? 'bg-accent/5' : undefined}>
                <td className="num px-2 text-right">
                  {fmt(x, 6)} {here && <Badge tone="accent">{t('td.current')}</Badge>}
                </td>
                <td className="num px-2 text-right">{p?.merit !== undefined ? fmt(p.merit, 6) : p?.status === 'failed' ? <span className="text-danger" title={p.error}>{t('td.failed')}</span> : '…'}</td>
                <td className="num px-2 text-right" title={t('td.frontHint')}>
                  {p?.envelope !== null && p?.envelope !== undefined ? fmt(p.envelope, 6) : ''}
                  {p && p.envelope_from !== null && p.envelope_from !== undefined && p.envelope_from !== p.index && snap && <span className="ml-1 text-caption text-muted">({t('td.from', { v: fmt(snap.points.find((q) => q.index === p.envelope_from)?.target ?? null, 4) })})</span>}
                </td>
                <td className="num px-2 text-right text-muted">{p?.envelope !== null && p?.envelope !== undefined && m0 ? percent(p.envelope / m0 - 1) : ''}</td>
                <td className={`text-center ${p?.feasible ? 'text-ok' : 'text-danger'}`}>{p?.merit !== undefined ? (p.feasible ? '✓' : '✗') : ''}</td>
                <td className="num px-2 text-right text-muted">{p?.evaluations ?? ''}</td>
                <td className="px-1 text-right">
                  {p?.status === 'finished' && (p.envelope_from ?? null) !== null && (
                    <Button size="sm" variant="subtle" onClick={() => use(p.envelope_from as number)} disabled={busy !== null} title={t('td.useHint')}>
                      {busy === p.envelope_from ? <Spinner size={12} /> : t('td.use')}
                    </Button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </Dialog>
  )
}
