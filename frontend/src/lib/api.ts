import type { RcwaRequest } from './rcwa'
import type {
  SourcePose,
  DesignSummary,
  DesignComparison,
  SpectrumRequest,
  AdvisorDiagnosis,
  AdvisorSnapshot,
  StockLens,
  StockLensInfo,
  StockMatchSpec,
  StockSpec,
  DesignCandidateProject,
  DesignMetricKey,
  DesignSpaceSnapshot,
  DesignSpaceSpec,
  LiveImageResult,
  PhotoData,
  DetectorSpec,
  FdtdSettings,
  FdtdSnapshot,
  FibreDispersionResult,
  FibreModesResult,
  FibreRequest,
  RcwaResult,
  Fibre2dSettings,
  Fibre2dSnapshot,
  PopResult,
  LightSource,
  GlassCatalog,
  ChromaticResult,
  Evaluation,
  FieldResult,
  JobSnapshot,
  TradeoffSnapshot,
  LongitudinalResult,
  MaterialRecord,
  MaterialSummary,
  CoatingCurve,
  CoatingAnalysis, CoatingExample, CoatingFit, CoatingMeasurement,
  CoatingAnalysisParams,
  CadAsset,
  CadClearanceResult,
  CadMeasureResult,
  CadPartRef,
  CadSectionResult,
  CoatingAngular,
  CoatingPerformance,
  SurfaceCoatingContext,
  CoatingDesignSpec,
  CoatingEvaluation,
  CoatingMonteCarlo,
  CoatingOptimizeResult,
  CoatingRecipe,
  CoatingTemplateKind,
  HuygensResult,
  CoatingDefinition,
  CoatingSummary,
  OpticalSystem,
  OptimizationResult,
  OptimizationSpec,
  OperandBreakdown,
  OpdFanResult,
  MtfResult,
  ParaxialResult,
  PsfResult,
  ThroughputResult,
  GaussianResult,
  PolarizationResult,
  VectorPsfResult,
  VignettingResult,
  SweepResult,
  GhostResult,
  NonSeqResult,
  StlImportResult,
  CadExportResult,
  CadImportResult,
  RecognizedElement,
  ToleranceSnapshot,
  ToleranceSpec,
  Surface,
  ElementsResult,
  ImageSimResult,
  RelativeIlluminationResult,
  WavefrontResult,
  InterferogramResult,
  SpectrometerResult,
  Project,
  RayFanResult,
  SampleInfo,
  SpotResult,
  SystemOutline,
  FocusResult,
  ThermalResult,
  MountReport,
} from './types'

export const API_BASE = '/api/v1'

export class ApiError extends Error {
  code: string
  status: number
  details: unknown
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response
  try {
    res = await fetch(API_BASE + path, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, 'NETWORK_ERROR', 'Cannot reach the OptiCore engine. Is it running? (Start OptiCore.bat starts it and names its port)')
  }
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    throw new ApiError(res.status, 'BAD_RESPONSE', `Invalid response from engine (${res.status})`)
  }
  if (!res.ok) {
    const err = (data as { error?: { code: string; message: string; details?: unknown } })?.error
    if (err) throw new ApiError(res.status, err.code, err.message, err.details)
    throw new ApiError(res.status, 'HTTP_ERROR', `Engine returned HTTP ${res.status}`)
  }
  return data as T
}

interface SysBody {
  system: OpticalSystem
  custom_materials: MaterialRecord[]
  /** light sources and detectors (detector operands of the merit function) */
  sources?: LightSource[]
  detectors?: DetectorSpec[]
}

export const api = {
  health: () => request<{ status: string; engine_version: string; schema_version: number }>('GET', '/health'),
  materials: () => request<{ materials: MaterialSummary[] }>('GET', '/materials'),
  toleranceDefault: (b: SysBody, grade: 'commercial' | 'precision' | 'high_precision') => request<{ tolerance: ToleranceSpec }>('POST', '/tolerance/default', { ...b, grade }),
  toleranceStart: (b: SysBody & { tolerance: ToleranceSpec; optimization?: OptimizationSpec; allocate?: boolean }) => request<{ job_id: string }>('POST', '/tolerance/start', b),
  toleranceStatus: (id: string) => request<ToleranceSnapshot>('GET', `/tolerance/${id}`),
  toleranceCancel: (id: string) => request<{ ok: boolean }>('POST', `/tolerance/${id}/cancel`),
  advisor: (b: SysBody, signal?: AbortSignal) => request<AdvisorDiagnosis>('POST', '/analysis/advisor', b, signal),
  liveImage: (b: SysBody & { scene?: string; photo?: PhotoData; width?: number; quality?: 'preview' | 'full'; zoom?: number; center?: [number, number]; channels_um?: number[] | null; channel?: string }, signal?: AbortSignal) =>
    request<LiveImageResult>('POST', '/analysis/live-image', b, signal),
  advisorStart: (b: SysBody & { optimization?: OptimizationSpec }) => request<{ job_id: string }>('POST', '/advisor/start', b),
  advisorStatus: (id: string) => request<AdvisorSnapshot>('GET', `/advisor/${id}`),
  advisorCancel: (id: string) => request<{ ok: boolean }>('POST', `/advisor/${id}/cancel`),
  designSpaceStart: (b: { spec: DesignSpaceSpec; custom_materials: MaterialRecord[] }) => request<{ job_id: string; total: number }>('POST', '/design-space/start', b),
  designSpaceStatus: (id: string, since: number, objectives?: DesignMetricKey[]) =>
    request<DesignSpaceSnapshot>('GET', `/design-space/${id}?since=${since}${objectives?.length ? `&objectives=${objectives.join(',')}` : ''}`),
  designSpaceCandidate: (id: string, index: number) => request<DesignCandidateProject>('GET', `/design-space/${id}/candidates/${index}`),
  designSpaceCancel: (id: string) => request<{ ok: boolean }>('POST', `/design-space/${id}/cancel`),
  sourcesSpectrum: (b: SpectrumRequest) => request<{ wavelengths: { value: number; weight: number }[]; info: Record<string, unknown> }>('POST', '/sources/spectrum', b),
  sourcesDescribe: (b: SysBody & { sources: LightSource[]; detectors: DetectorSpec[] }, signal?: AbortSignal) =>
    request<{ sources: SourcePose[]; detectors: SourcePose[] }>('POST', '/sources/describe', b, signal),
  stockGeneric: () => request<{ catalog: string; lenses: StockLensInfo[] }>('GET', '/stock/generic'),
  stockDescribe: (b: { lenses: StockLens[]; custom_materials: MaterialRecord[] }) => request<{ lenses: StockLensInfo[]; missing_glasses: string[] }>('POST', '/stock/describe', b),
  stockImportZmx: (b: { files: { filename: string; content_base64: string }[]; catalog: string; vendor: string; catalog_materials: MaterialRecord[] }) =>
    request<{ catalog: string; lenses: StockLensInfo[]; custom_materials: MaterialRecord[]; files: { filename: string; ok: boolean; part?: string; error?: string; diagnostics?: { status: string; message: string }[] }[] }>(
      'POST',
      '/stock/import/zmx',
      b,
    ),
  stockImportCsv: (b: { content: string; catalog: string; custom_materials: MaterialRecord[] }) =>
    request<{ catalog: string; lenses: StockLensInfo[]; diagnostics: { message: string; line: number }[]; missing_glasses: string[] }>('POST', '/stock/import/csv', b),
  stockSurfaces: (b: { lens: StockLens; reversed: boolean; gap_after: number }) => request<{ surfaces: Partial<Surface>[] }>('POST', '/stock/surfaces', b),
  stockBuildStart: (b: { spec: StockSpec; lenses: StockLens[]; custom_materials: MaterialRecord[] }) => request<{ job_id: string; total: number }>('POST', '/stock/build/start', b),
  stockMatchStart: (b: SysBody & { spec: StockMatchSpec; optimization?: OptimizationSpec; lenses: StockLens[] }) => request<{ job_id: string; total: number }>('POST', '/stock/match/start', b),
  coatings: () => request<{ coatings: CoatingSummary[] }>('GET', '/coatings'),
  cdEvaluate: (b: { design: CoatingDesignSpec; custom_materials: MaterialRecord[]; lambda_min_nm?: number | null; lambda_max_nm?: number | null; samples?: number; angle_deg?: number }, signal?: AbortSignal) =>
    request<CoatingEvaluation>('POST', '/coating-design/evaluate', b, signal),
  cdTemplate: (b: { design: CoatingDesignSpec; custom_materials: MaterialRecord[]; kind: CoatingTemplateKind; high: string; low: string; pairs: number; lambda0_nm?: number | null; edge_nm?: number | null; band_min_nm?: number | null; band_max_nm?: number | null; cavities?: number }) =>
    request<{ design: CoatingDesignSpec; notes: string[] }>('POST', '/coating-design/template', b),
  cdOptimize: (b: { design: CoatingDesignSpec; custom_materials: MaterialRecord[]; method: 'refine' | 'needle'; max_needles?: number; time_limit_s?: number }) =>
    request<CoatingOptimizeResult>('POST', '/coating-design/optimize', b),
  cdMonteCarlo: (b: { design: CoatingDesignSpec; custom_materials: MaterialRecord[]; sigma_rel: number; sigma_abs_nm: number; runs: number; seed: number }) =>
    request<CoatingMonteCarlo>('POST', '/coating-design/montecarlo', b),
  cdRecipe: (b: { design: CoatingDesignSpec; custom_materials: MaterialRecord[]; monitor_wavelength_nm: number; monitor: 'T' | 'R'; monitor_back_side: 'none' | 'uncoated' }) =>
    request<CoatingRecipe>('POST', '/coating-design/recipe', b),
  cdAngular: (b: { design: CoatingDesignSpec; custom_materials: MaterialRecord[]; wavelengths_nm: number[]; angle_max_deg?: number; angles?: number }) =>
    request<CoatingAngular>('POST', '/coating-design/angular', b),
  cdFromCoating: (b: { coating?: CoatingDefinition; builtin?: string; base?: CoatingDesignSpec | null }) => request<{ design: CoatingDesignSpec }>('POST', '/coating-design/from-coating', b),
  cdAnalyze: (b: CoatingAnalysisParams & { design: CoatingDesignSpec; custom_materials: MaterialRecord[] }, signal?: AbortSignal) => request<CoatingAnalysis>('POST', '/coating-design/analyze', b, signal),
  coatingExamples: () => request<{ examples: CoatingExample[] }>('GET', '/coating-examples'),
  cdFormula: (b: { design: CoatingDesignSpec; custom_materials: MaterialRecord[]; formula: string }) => request<{ design: CoatingDesignSpec; formula: string; layer_count: number }>('POST', '/coating-design/formula', b),
  cdFit: (b: { design: CoatingDesignSpec; custom_materials: MaterialRecord[]; measurements: CoatingMeasurement[]; mode: CoatingFit['mode']; max_error?: number; fit_index?: boolean; fit_dispersion?: boolean; fit_absorption?: boolean; fit_substrate?: boolean; search?: 'local' | 'global'; index_range?: number; time_limit_s?: number }) => request<CoatingFit>('POST', '/coating-design/fit', b),
  coatingsAnalyze: (
    b: CoatingAnalysisParams & { name?: string; definition?: CoatingDefinition; custom_materials?: MaterialRecord[]; mirror?: boolean; incident_index?: number; substrate_material?: string; substrate_index?: number; substrate_extinction?: number; back_side?: boolean },
    signal?: AbortSignal,
  ) => request<CoatingAnalysis>('POST', '/coatings/analyze', b, signal),
  surfaceContext: (b: SysBody & { surface: number }) => request<SurfaceCoatingContext>('POST', '/analysis/surface-context', b),
  coatingPerformance: (b: SysBody & Record<string, unknown>, signal?: AbortSignal) => request<CoatingPerformance>('POST', '/analysis/coatings', b, signal),
  cdExportCoating: (b: { design: CoatingDesignSpec; custom_materials: MaterialRecord[]; name: string }) => request<CoatingDefinition>('POST', '/coating-design/export-coating', b),
  coatingCurve: (o: { name?: string; definition?: CoatingDefinition; substrate_index?: number; lambda_min?: number; lambda_max?: number; angle_deg?: number; mirror?: boolean; incident_index?: number; samples?: number; custom_materials?: MaterialRecord[] }) =>
    request<CoatingCurve>('POST', '/coatings/curve', { lambda_min: 0.4, lambda_max: 0.8, angle_deg: 0, ...o }),
  materialCurves: (materials: string[], lambda_min: number, lambda_max: number, samples: number, custom_materials: MaterialRecord[]) =>
    request<{ wavelength_um: number[]; curves: { name: string; index: number[]; k?: number[] | null; in_range: boolean[]; summary?: MaterialSummary }[] }>(
      'POST',
      '/materials/curves',
      { materials, lambda_min, lambda_max, samples, custom_materials },
    ),
  resolveIndex: (materials: string[], wavelengths: number[], custom_materials: MaterialRecord[]) =>
    request<{ wavelengths: number[]; materials: Record<string, { index: number[]; warnings: string[] }> }>('POST', '/materials/resolve', {
      materials,
      wavelengths,
      custom_materials,
    }),
  validateMaterial: (rec: MaterialRecord) => request<{ material: MaterialSummary }>('POST', '/materials/validate', rec),
  firstLens: (b: { focal_length: number; f_number: number; half_field_deg: number; wavelengths: number[]; primary: number; kind: 'singlet' | 'doublet'; crown: string; flint: string; name?: string }) =>
    request<{ project: Project; notes: string[]; design: Record<string, unknown> }>('POST', '/design/first-lens', b),
  focus: (b: SysBody & { density?: number }, signal?: AbortSignal) => request<FocusResult>('POST', '/analysis/focus', b, signal),
  summary: (b: SysBody & { mtf_frequency?: number | null }, signal?: AbortSignal) => request<DesignSummary>('POST', '/analysis/summary', b, signal),
  thermal: (b: SysBody & Record<string, unknown>, signal?: AbortSignal) => request<ThermalResult>('POST', '/analysis/thermal', b, signal),
  mounts: (b: SysBody, signal?: AbortSignal) => request<MountReport>('POST', '/system/mounts', b, signal),
  elements: (b: SysBody & { tolerancing?: ToleranceSpec | null }, signal?: AbortSignal) => request<ElementsResult>('POST', '/elements', b, signal),
  relativeIllumination: (b: SysBody, signal?: AbortSignal) => request<RelativeIlluminationResult>('POST', '/analysis/relative-illumination', b, signal),
  imageSimulation: (b: SysBody, signal?: AbortSignal) => request<ImageSimResult>('POST', '/analysis/image-simulation', b, signal),
  convertQ: (b: SysBody & { surface: number; to: 'qcon' | 'qbfs'; terms?: number | null; norm_radius?: number | null }) =>
    request<{ surface: Partial<Surface>; residual_rms_mm: number; residual_max_mm: number; norm_radius_mm: number }>('POST', '/surface/convert-q', b),
  outline: (b: SysBody, signal?: AbortSignal) => request<SystemOutline>('POST', '/system/outline', b, signal),
  evaluate: (b: SysBody, signal?: AbortSignal) => request<Evaluation>('POST', '/system/evaluate', { ...b, layout_rays: 7, ring_rays: 8 }, signal),
  spot: (b: SysBody & { pattern: string; density: number; reference: string }, signal?: AbortSignal) => request<SpotResult>('POST', '/analysis/spot', b, signal),
  rayfan: (b: SysBody & { samples: number }, signal?: AbortSignal) => request<RayFanResult>('POST', '/analysis/rayfan', b, signal),
  field: (b: SysBody & { samples: number }, signal?: AbortSignal) => request<FieldResult>('POST', '/analysis/field', b, signal),
  longitudinal: (b: SysBody & { samples: number }, signal?: AbortSignal) => request<LongitudinalResult>('POST', '/analysis/longitudinal', b, signal),
  chromatic: (b: SysBody & { samples: number }, signal?: AbortSignal) => request<ChromaticResult>('POST', '/analysis/chromatic', b, signal),
  paraxial: (b: SysBody, signal?: AbortSignal) => request<ParaxialResult>('POST', '/analysis/paraxial', b, signal),
  opdfan: (b: SysBody & { samples: number }, signal?: AbortSignal) => request<OpdFanResult>('POST', '/analysis/opdfan', b, signal),
  wavefront: (b: SysBody & Record<string, unknown>, signal?: AbortSignal) => request<WavefrontResult>('POST', '/analysis/wavefront', b, signal),
  interferogram: (b: SysBody & Record<string, unknown>, signal?: AbortSignal) => request<InterferogramResult>('POST', '/analysis/interferogram', b, signal),
  spectrometer: (b: SysBody & Record<string, unknown>, signal?: AbortSignal) => request<SpectrometerResult>('POST', '/analysis/spectrometer', b, signal),
  psf: (b: SysBody & Record<string, unknown>, signal?: AbortSignal) => request<PsfResult>('POST', '/analysis/psf', b, signal),
  huygens: (b: SysBody & Record<string, unknown>, signal?: AbortSignal) => request<HuygensResult>('POST', '/analysis/huygens', b, signal),
  mtf: (b: SysBody & Record<string, unknown>, signal?: AbortSignal) => request<MtfResult>('POST', '/analysis/mtf', b, signal),
  throughput: (b: SysBody, signal?: AbortSignal) => request<ThroughputResult>('POST', '/analysis/throughput', b, signal),
  nonseq: (b: SysBody, signal?: AbortSignal) => request<NonSeqResult>('POST', '/analysis/nonseq', b, signal),
  ghosts: (b: SysBody, signal?: AbortSignal) => request<GhostResult>('POST', '/analysis/ghosts', b, signal),
  sweep: (b: SysBody, signal?: AbortSignal) => request<SweepResult>('POST', '/analysis/sweep', b, signal),
  polarization: (b: SysBody, signal?: AbortSignal) => request<PolarizationResult>('POST', '/analysis/polarization', b, signal),
  vectorPsf: (b: SysBody, signal?: AbortSignal) => request<VectorPsfResult>('POST', '/analysis/vector-psf', b, signal),
  vignetting: (b: SysBody) => request<VignettingResult>('POST', '/system/vignetting', b),
  gaussian: (b: SysBody, signal?: AbortSignal) => request<GaussianResult>('POST', '/analysis/gaussian', b, signal),
  merit: (b: SysBody & { optimization: OptimizationSpec }, signal?: AbortSignal) =>
    request<{ merit: number; operands: OperandBreakdown[]; variables: { surface_id: string; parameter: string; value: number }[] }>('POST', '/optimize/merit', b, signal),
  optimizeStart: (b: SysBody & { optimization: OptimizationSpec }) => request<{ job_id: string }>('POST', '/optimize/start', b),
  optimizeCompare: (b: { before: OpticalSystem; after: OpticalSystem; custom_materials: MaterialRecord[] }, signal?: AbortSignal) => request<DesignComparison>('POST', '/optimize/compare', b, signal),
  optimizeStatus: (id: string) => request<JobSnapshot>('GET', `/optimize/${id}`),
  tradeoffStart: (b: SysBody & { optimization: OptimizationSpec; base: OpticalSystem; operand: number; targets?: number[] | null; budget?: number }) => request<{ job_id: string; targets: number[] }>('POST', '/optimize/tradeoff/start', b),
  tradeoffStatus: (id: string) => request<TradeoffSnapshot>('GET', `/optimize/tradeoff/${id}`),
  tradeoffPoint: (id: string, index: number) => request<OptimizationResult>('GET', `/optimize/tradeoff/${id}/points/${index}`),
  tradeoffCancel: (id: string) => request<{ ok: boolean }>('POST', `/optimize/tradeoff/${id}/cancel`),
  optimizeCancel: (id: string) => request<{ ok: boolean }>('POST', `/optimize/${id}/cancel`),
  optimizePause: (id: string, paused: boolean) => request<{ ok: boolean }>('POST', `/optimize/${id}/pause`, { paused }),
  samples: () => request<{ samples: SampleInfo[] }>('GET', '/samples'),
  sample: (id: string) => request<Project>('GET', `/samples/${id}`),
  cadRecognize: (asset: CadAsset) => request<{ elements: RecognizedElement[]; skipped: { name: string; reason: string }[] }>('POST', '/cad/recognize', { asset }),
  cadInsert: (b: SysBody & { asset: CadAsset; elements: number[]; role: 'lens' | 'mirror'; materials: string[]; after: number; placement: 'cad' | 'axis'; gap: number; reflect_face: 'front' | 'back' }) =>
    request<{ system: OpticalSystem; report: { inserted: string[]; notes: string[]; first_index: number; count: number }; elements: RecognizedElement[] }>('POST', '/cad/insert', b),
  importCad: (filename: string, data_base64: string) => request<CadImportResult>('POST', '/import/cad', { filename, data_base64 }),
  cadMeasure: (assets: CadAsset[], picks: { asset_id: string; part_id: string | null; point: [number, number, number] }[]) => request<CadMeasureResult>('POST', '/cad/measure', { assets, picks }),
  cadClearance: (assets: CadAsset[], a: CadPartRef, b: CadPartRef) => request<CadClearanceResult>('POST', '/cad/clearance', { assets, a, b }),
  cadSection: (assets: CadAsset[], signal?: AbortSignal) => request<CadSectionResult>('POST', '/cad/section', { assets }, signal),
  exportCad: (b: SysBody & { format: 'step' | 'iges'; cad_assets: CadAsset[]; rim_margin: number; include_stop: boolean; include_image: boolean; include_rays: boolean; include_cad: boolean; include_mechanics?: boolean }) =>
    request<CadExportResult>('POST', '/export/cad', b),
  importStl: (filename: string, data_base64: string, units: string) => request<StlImportResult>('POST', '/import/stl', { filename, data_base64: data_base64, units }),
  importZmx: (filename: string, content_base64: string, catalog_materials: MaterialRecord[] = []) =>
    request<{ project: Project; diagnostics: { status: string; message: string; surface: number | null; line: number | null }[] }>('POST', '/import/zmx', { filename, content_base64, catalog_materials }),
  importAgf: (filename: string, content_base64: string) =>
    request<Omit<GlassCatalog, 'id' | 'imported_at' | 'name'> & { catalog: string }>('POST', '/materials/agf', { filename, content_base64 }),
  importRii: (catalog: string, files: { path: string; content: string }[]) =>
    request<Omit<GlassCatalog, 'id' | 'imported_at' | 'name'> & { catalog: string }>('POST', '/materials/rii', { catalog, files }),
  fiberModes: (b: FibreRequest & { custom_materials?: MaterialRecord[] }, signal?: AbortSignal) => request<FibreModesResult>('POST', '/wave/fiber_modes', b, signal),
  fiberDispersion: (b: FibreRequest & { wl_min_um: number; wl_max_um: number; points: number; l?: number; m?: number; custom_materials?: MaterialRecord[] }, signal?: AbortSignal) =>
    request<FibreDispersionResult>('POST', '/wave/fiber_dispersion', b, signal),
  rcwa: (b: RcwaRequest & { custom_materials?: MaterialRecord[] }, signal?: AbortSignal) => request<RcwaResult>('POST', '/wave/rcwa', b, signal),
  fiber2dStart: (b: Fibre2dSettings & { wavelength_um: number; custom_materials: MaterialRecord[] }) => request<{ job_id: string }>('POST', '/wave/fiber2d/start', b),
  fiber2dStatus: (id: string) => request<Fibre2dSnapshot>('GET', `/wave/fiber2d/${id}`),
  fiber2dCancel: (id: string) => request<{ cancelled: boolean }>('POST', `/wave/fiber2d/${id}/cancel`),
  pop: (b: SysBody, signal?: AbortSignal) => request<PopResult>('POST', '/analysis/pop', b, signal),
  fdtdStart: (b: FdtdSettings & { custom_materials: MaterialRecord[] }) => request<{ job_id: string }>('POST', '/wave/fdtd/start', b),
  fdtdStatus: (id: string) => request<FdtdSnapshot>('GET', `/wave/fdtd/${id}`),
  fdtdCancel: (id: string) => request<{ cancelled: boolean }>('POST', `/wave/fdtd/${id}/cancel`),
  validateProject: (p: unknown) => request<{ valid: boolean; notes: string[]; project: Project }>('POST', '/project/validate', p),
}
