import type PlotlyType from 'plotly.js-dist-min'
import { useEffect, useRef, useState } from 'react'
import { resolveDeep } from '../../lib/palette'
import { useUiStore } from '../../store/uiStore'

/** Loose trace record; Plotly validates attributes at runtime. */
export type Trace = Record<string, unknown>
type Data = Trace[]
type Layout = Record<string, unknown>

function themeColors() {
  const cs = getComputedStyle(document.documentElement)
  const v = (n: string) => cs.getPropertyValue(n).trim()
  return { text: v('--c-text'), muted: v('--c-muted'), grid: v('--c-border'), panel: v('--c-panel'), axis: v('--c-border-strong'), accent: v('--c-accent') }
}

// Plotly (~3 MB) is loaded on first use so the workspace shell starts quickly.
let plotlyPromise: Promise<typeof PlotlyType> | null = null
function loadPlotly() {
  plotlyPromise ??= import('plotly.js-dist-min').then((m) => (m as unknown as { default: typeof PlotlyType }).default ?? (m as unknown as typeof PlotlyType))
  return plotlyPromise
}

/** A point event: the point's `customdata` and the mouse event (for positioning a card). */
export type PointHandler = (customdata: unknown, ev: MouseEvent) => void

export function Plot({
  data,
  layout,
  className,
  square,
  onPointClick,
  onPointHover,
  onPointUnhover,
}: {
  data: Data
  layout?: Layout
  className?: string
  square?: boolean
  onPointClick?: PointHandler
  onPointHover?: PointHandler
  onPointUnhover?: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const theme = useUiStore((s) => s.theme)
  const [Plotly, setPlotly] = useState<typeof PlotlyType | null>(null)
  const revision = useRef(0)
  // point events: the handlers live in a ref so the Plotly listeners are attached once per plot
  const handlers = useRef({ onPointClick, onPointHover, onPointUnhover })
  useEffect(() => {
    handlers.current = { onPointClick, onPointHover, onPointUnhover }
  })
  const listening = useRef(false)
  useEffect(() => {
    let alive = true
    loadPlotly().then((p) => alive && setPlotly(() => p))
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    const el = ref.current
    if (!el || !Plotly) return
    const c = themeColors()
    const axis = {
      gridcolor: c.grid,
      zerolinecolor: c.axis,
      linecolor: c.axis,
      tickfont: { size: 10.5, color: c.muted },
      title: { font: { size: 11, color: c.muted } },
      showspikes: true,
      spikethickness: 1,
      spikedash: 'dot',
      spikecolor: c.muted,
      spikemode: 'across',
    }
    const base: Layout = {
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: 'Inter Variable, Inter, Segoe UI, system-ui, sans-serif', size: 11, color: c.text },
      margin: { l: 56, r: 16, t: 26, b: 42 },
      legend: { font: { size: 10.5 }, bgcolor: 'rgba(0,0,0,0)', orientation: 'h', y: -0.18 },
      hoverlabel: { font: { size: 11 } },
      hovermode: 'closest',
      autosize: true,
    }
    // colour tokens (lib/palette.ts) become the current theme's colours
    const merged: Layout = { ...base, ...resolveDeep(layout ?? {}) }
    for (const k of Object.keys(merged)) {
      if (/^[xy]axis\d*$/.test(k)) {
        ;(merged as Record<string, unknown>)[k] = { ...axis, ...((merged as Record<string, Record<string, unknown>>)[k] ?? {}), title: { ...axis.title, ...(((merged as Record<string, Record<string, Record<string, unknown>>>)[k] ?? {}).title ?? {}) } }
      }
    }
    if (!merged.xaxis) merged.xaxis = axis
    if (!merged.yaxis) merged.yaxis = axis
    if (square) {
      // equal scale without stretching the data range: shrink the plot domain instead
      ;(merged.yaxis as Record<string, unknown>).scaleanchor = 'x'
      ;(merged.yaxis as Record<string, unknown>).constrain = 'domain'
      ;(merged.xaxis as Record<string, unknown>).constrain = 'domain'
    }
    // the data arrays usually keep their identity between redraws (cached results): without a new revision
    // Plotly.react skips the recalculation when only names or titles change (a language switch) and the
    // autorange falls back to its empty default (-1…6)
    merged.datarevision = ++revision.current
    Plotly.react(el, resolveDeep(data) as unknown as Plotly.Data[], merged as unknown as Partial<Plotly.Layout>, { displaylogo: false, responsive: true, modeBarButtonsToRemove: ['lasso2d', 'select2d', 'sendChartToCloud' as never], plotlyServerURL: '', toImageButtonOptions: { format: 'png', scale: 2 } })
    if (!listening.current) {
      // the event emitter exists once the element has been plotted
      type Ev = { points?: { customdata?: unknown }[]; event?: MouseEvent }
      const gd = el as unknown as { on: (name: string, fn: (e: Ev) => void) => void }
      const point = (e: Ev) => (e.points && e.points.length ? e.points[0].customdata : undefined)
      gd.on('plotly_click', (e) => {
        const c = point(e)
        if (c !== undefined && e.event) handlers.current.onPointClick?.(c, e.event)
      })
      gd.on('plotly_hover', (e) => {
        const c = point(e)
        if (c !== undefined && e.event) handlers.current.onPointHover?.(c, e.event)
      })
      gd.on('plotly_unhover', () => handlers.current.onPointUnhover?.())
      listening.current = true
    }
  }, [data, layout, theme, square, Plotly])

  useEffect(() => {
    const el = ref.current
    if (!el || !Plotly) return
    const ro = new ResizeObserver(() => {
      if (el.offsetParent !== null) Plotly.Plots.resize(el)
    })
    ro.observe(el)
    return () => {
      ro.disconnect()
      Plotly.purge(el)
      listening.current = false
    }
  }, [Plotly])

  return <div ref={ref} className={className ?? 'h-full w-full'} />
}
