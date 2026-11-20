// The colour palette. Together with the UI tokens in index.css this is the only place colours are written
// out (a test checks it). Data colours are CSS tokens (--d-*, dark and light values in index.css): SVG and
// CSS use them as they are, Plot resolves them for Plotly, and the 3D view uses resolveColor().

/** Okabe & Ito (2008): the colour-blind-safe qualitative palette the data colours are built from. */
export const OKABE_ITO = { orange: '#E69F00', sky: '#56B4E9', green: '#009E73', yellow: '#F0E442', blue: '#0072B2', vermillion: '#D55E00', purple: '#CC79A7', grey: '#999999' } as const

/** Series colours in order (fields, curves, profiles): blue, orange, green, purple, vermillion, yellow, blue 2, grey. */
export const SERIES = Array.from({ length: 8 }, (_, i) => `var(--d-${i + 1})`)

/** Data roles, the same in every plot and in the 2D and 3D views. */
export const DATA = {
  primary: SERIES[0],
  secondary: SERIES[1],
  tertiary: SERIES[2],
  quaternary: SERIES[3],
  /** reference lines: diffraction limit, nominal value, Airy circle */
  reference: 'var(--d-ref)',
  /** the current value, a waist, a highlighted point */
  marker: 'var(--d-mark)',
  /** a target: detector circle, target plane, aim */
  target: 'var(--d-target)',
  /** non-sequential light sources and detectors */
  source: 'var(--d-source)',
  detector: 'var(--d-detector)',
  /** non-sequential ray paths: direct, after ghost reflections, scattered */
  direct: 'var(--d-direct)',
  ghost: 'var(--d-ghost)',
  scatter: 'var(--d-scatter)',
  /** measurements in the 3D view */
  measure: 'var(--d-measure)',
  /** the selection and the stop (the UI accent) */
  selection: 'var(--c-accent)',
  /** marks drawn on top of a colour map (contours, polarisation ellipses) */
  overlay: 'var(--d-overlay)',
  /** translucent fill under or between primary curves (bands, beam envelopes) */
  fill: 'var(--d-fill)',
} as const

/** Colour of field n (0-based): the same in plots, legends and the 2D/3D rays. */
export function fieldColor(i: number): string {
  return SERIES[((i % SERIES.length) + SERIES.length) % SERIES.length]
}

const VAR = /^var\((--[\w-]+)\)$/

/** The current value of a colour token ('var(--x)'), for Plotly and Three.js, which need real colours. */
export function resolveColor(c: string): string {
  const m = VAR.exec(c)
  if (!m || typeof document === 'undefined') return c
  const v = getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim()
  return v || c
}

/** Resolve every colour token in a Plotly data/layout structure (numeric arrays are left alone quickly). */
export function resolveDeep<T>(v: T): T {
  if (typeof v === 'string') return (VAR.test(v) ? resolveColor(v) : v) as T
  if (Array.isArray(v)) {
    if (v.length && typeof v[0] === 'number') return v
    if (v.length && Array.isArray(v[0]) && typeof (v[0] as unknown[])[0] === 'number') return v
    return v.map(resolveDeep) as T
  }
  if (v && typeof v === 'object') {
    const out: Record<string, unknown> = {}
    for (const [k, x] of Object.entries(v as Record<string, unknown>)) out[k] = resolveDeep(x)
    return out as T
  }
  return v
}

// ------------------------------------------------------------------ colour maps (no jet)
type Scale = [number, string][]
/** Perceptually uniform sequential map for irradiance, |E|², PSF (matplotlib inferno, deciles). */
export const INFERNO: Scale = [
  [0, '#000004'],
  [0.1, '#160b39'],
  [0.2, '#420a68'],
  [0.3, '#6a176e'],
  [0.4, '#932667'],
  [0.5, '#bc3754'],
  [0.6, '#dd513a'],
  [0.7, '#f37819'],
  [0.8, '#fca50a'],
  [0.9, '#f6d746'],
  [1, '#fcffa4'],
]
/** Diverging map for signed quantities (OPD, field), blue negative, red positive; use with zmid: 0 (ColorBrewer RdBu). */
export const DIVERGING: Scale = [
  [0, '#053061'],
  [0.1, '#2166ac'],
  [0.2, '#4393c3'],
  [0.3, '#92c5de'],
  [0.4, '#d1e5f0'],
  [0.5, '#f7f7f7'],
  [0.6, '#fddbc7'],
  [0.7, '#f4a582'],
  [0.8, '#d6604d'],
  [0.9, '#b2182b'],
  [1, '#67001f'],
]
/** Cyclic map for phase (light – blue – dark – red – light; the ends match). */
export const CYCLIC: Scale = [
  [0, '#e2d9e2'],
  [0.125, '#9ab6c8'],
  [0.25, '#5f80b9'],
  [0.375, '#4b3d97'],
  [0.5, '#2f1436'],
  [0.625, '#6a1d4f'],
  [0.75, '#b34a54'],
  [0.875, '#d9988a'],
  [1, '#e2d9e2'],
]
export const COLORMAPS = {
  /** irradiance, intensity, PSF */
  sequential: INFERNO,
  /** a second sequential map where two maps sit side by side (Plotly's viridis) */
  sequentialAlt: 'Viridis',
  /** signed values, centred on zero */
  diverging: DIVERGING,
  /** phase */
  cyclic: CYCLIC,
  /** refractive index maps */
  greys: 'Greys',
} as const

// ------------------------------------------------------------------ fixed data colours
/** Default display colour of an imported CAD model (stored in the project, editable). */
export const DEFAULT_CAD_COLOR = '#9aa7b4'

/** 3D scene: materials, lights and background per theme (presentation only, see ADR-014). */
export const SCENE = {
  dark: {
    background: '#0d141c',
    backgroundStops: ['#16202c', '#0c1219', '#06090d'],
    glass: '#ffffff',
    glassSelected: '#d7f0ff',
    glassAttenuation: '#d6ecff',
    glassEmissiveSelected: '#1d6fa5',
    black: '#000000',
    glassFast: '#8fc7ff',
    glassFastSelected: '#6cc8ff',
    edge: '#c9d6e2',
    edgeSelected: '#9fd8ff',
    mirror: '#eef3f8',
    mirrorSelected: '#bfe2ff',
    mirrorBack: '#3a4350',
    ideal: '#3ccf8e',
    sensor: '#1a222d',
    sensorEmissive: '#0b1d2c',
    iris: '#3a434e',
    outline: '#7f95aa',
    rayHighlight: '#0b4a73',
    lightCool: '#d8ecff',
    lightWarm: '#fff1df',
    lightWhite: '#ffffff',
    lightSky: '#dcefff',
    floorLight: '#2a3d52',
    gridMinor: '#22303f',
    gridMajor: '#36506b',
    cube: '#1c2836',
    cubeText: '#cfe2f5',
    cubeStroke: '#3a4d61',
    shadow: '#000000',
  },
  light: {
    background: '#dfe6ee',
    backgroundStops: ['#f3f6fa', '#dfe6ee', '#c6d1dd'],
    glass: '#ffffff',
    glassSelected: '#d7f0ff',
    glassAttenuation: '#a9d4f5',
    glassEmissiveSelected: '#1d6fa5',
    black: '#000000',
    glassFast: '#8fc7ff',
    glassFastSelected: '#6cc8ff',
    edge: '#e8eef4',
    edgeSelected: '#9fd8ff',
    mirror: '#eef3f8',
    mirrorSelected: '#bfe2ff',
    mirrorBack: '#8b96a3',
    ideal: '#3ccf8e',
    sensor: '#2b3644',
    sensorEmissive: '#0b1d2c',
    iris: '#4a5562',
    outline: '#47607a',
    rayHighlight: '#0b4a73',
    lightCool: '#d8ecff',
    lightWarm: '#fff1df',
    lightWhite: '#ffffff',
    lightSky: '#dcefff',
    floorLight: '#ffffff',
    gridMinor: '#b4c0cd',
    gridMajor: '#8395a9',
    cube: '#f4f7fb',
    cubeText: '#25313f',
    cubeStroke: '#9fb0c2',
    shadow: '#1b2633',
  },
} as const

/** The printable HTML report (light, standalone; it cannot use the app's CSS tokens). */
export const REPORT = {
  text: '#0f172a',
  body: '#334155',
  muted: '#475569',
  faint: '#64748b',
  rule: '#cbd5e1',
  grid: '#e2e8f0',
  frame: '#94a3b8',
  header: '#f1f5f9',
  warn: '#b45309',
  series: [OKABE_ITO.blue, OKABE_ITO.vermillion, OKABE_ITO.green, OKABE_ITO.purple, OKABE_ITO.orange, OKABE_ITO.sky, '#8a7d00', '#555555'],
} as const

/** Element drawings (ISO 10110): black on white paper in every theme. */
export const DRAWING = {
  paper: '#ffffff',
  line: '#111111',
  thin: '#333333',
  dim: '#1f2937',
  axis: '#555555',
  hatch: '#8a8a8a',
  fill: '#eef3f8',
  frame: '#111111',
  muted: '#4b5563',
} as const
