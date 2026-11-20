// Application commands shared by the toolbar, command palette, shortcuts and menus.
import { useCatalogStore } from './store/catalogStore'
import { api } from './lib/api'
import { translate } from './lib/i18n'
import { focusReport } from './lib/focusReport'
import { quickFocusSetup } from './lib/quickFocus'
import { pruneReferences } from './lib/references'
import { designSnapshot, sameDesign } from './store/designGuard'
import { useDesignSpaceStore } from './store/designSpaceStore'
import { useFdtdStore } from './store/fdtdStore'
import { useFibre2dStore } from './store/fibre2dStore'
import { blankProject, cloneSystem, defaultSurface, FILE_EXTENSION, newId, normalizeProject, nowIso, parseProjectFile, ProjectFileError, serializeProject } from './lib/project'
import { buildReportHtml, collectReportData } from './lib/report'
import { discardTarget } from './lib/startup'
import { DEFAULT_CAD_COLOR } from './lib/palette'
import { ALL_VIEWS, type ViewKind } from './lib/viewGroups'
import { downloadText, pickFile, storage } from './lib/storage'
import type { GlassCatalog, MaterialRecord, Project, StockLens } from './lib/types'
import { askUnsaved } from './store/confirmStore'
import { useEngineStore } from './store/engineStore'
import { useOptStore } from './store/optStore'
import { toStockLens } from './store/stockStore'
import { isDirty, useProjectStore } from './store/projectStore'
import { tolKey, useTolStore } from './store/tolStore'
import { useUiStore } from './store/uiStore'

const t = (k: string, v?: Record<string, string | number>) => translate(useUiStore.getState().lang, k, v)
const toast = (kind: 'info' | 'success' | 'warning' | 'error', text: string) => useUiStore.getState().toast(kind, text)
const log = (level: 'info' | 'warning' | 'error' | 'success', text: string) => useEngineStore.getState().log_(level, text)

/** Before replacing the open project: Save / Don't save / Cancel when it has unsaved changes.
 * Resolves true when it is fine to continue (saved, or the changes are to be dropped). */
export async function confirmDiscard(save: () => Promise<boolean> = saveProject): Promise<boolean> {
  const st = useProjectStore.getState()
  if (!isDirty(st)) return true
  const answer = await askUnsaved({
    title: t('cf.unsavedTitle'),
    message: t('cf.unsavedText', { name: st.project.metadata.name }),
    save: t('c.save'),
    dontSave: t('cf.dontSave'),
    cancel: t('c.cancel'),
  })
  if (answer === 'cancel') return false
  if (answer === 'discard') return true
  return save()
}

export function openProject(p: Project, opts: { inLibrary?: boolean; saved?: boolean } = {}) {
  useProjectStore.getState().setProject(normalizeProject(p), { saved: opts.saved ?? true, inLibrary: opts.inLibrary })
  // recovered work is no longer the open project, and hints about the previous one are stale
  if (useUiStore.getState().recovery || useUiStore.getState().nextHint) useUiStore.getState().set({ recovery: null, nextHint: null })
  // old results belong to the previous project (analyses, and the evaluation behind the layout, the surface profiles
  // and the messages); the token makes every view recompute even if the new project's system happens to be identical
  // (no system change would trigger it). An evaluation of the previous project still in flight is dropped
  // (engineStore.evaluate checks its key).
  useEngineStore.setState((s) => ({ analyses: {}, preview: null, evaluation: null, evalError: null, evalKey: '', retraceToken: s.retraceToken + 1 }))
  // runs and results of the previous project must not reach this one (preview, apply, report)
  useOptStore.getState().abandon()
  useDesignSpaceStore.getState().reset()
  useFdtdStore.getState().reset()
  useFibre2dStore.getState().reset()
  log('info', `Opened project "${p.metadata.name}"`)
}

/** A design space candidate as a new unsaved project, or as a new revision of the open one (one undo step:
 *  the prescription, its optimisation set-up and the catalogue glasses it uses). Returns true when it was opened. */
export async function openDesignCandidate(jobId: string, index: number, mode: 'project' | 'revision'): Promise<boolean> {
  const c = await api.designSpaceCandidate(jobId, index)
  const cp = c.project
  if (mode === 'project') {
    if (!(await confirmDiscard())) return false
    const b = blankProject(cp.metadata.name)
    openProject(
      {
        ...b,
        metadata: { ...b.metadata, name: cp.metadata.name, description: cp.metadata.description },
        system: cp.system,
        optimization: { ...b.optimization, ...cp.optimization },
        custom_materials: cp.custom_materials,
      },
      { saved: false },
    )
    return true
  }
  useProjectStore.getState().commit(`Design space: ${c.title}`, (p) => {
    p.revisions.push({ id: newId(), timestamp: nowIso(), label: `Before design space: ${c.title}`, system: cloneSystem(p.system) })
    if (p.revisions.length > 50) p.revisions.splice(0, p.revisions.length - 50)
    p.system = cloneSystem(cp.system)
    p.optimization = { ...p.optimization, ...cp.optimization }
    for (const r of cp.custom_materials) if (!p.custom_materials.some((m) => m.name.toUpperCase() === r.name.toUpperCase())) p.custom_materials.push(r)
    for (const n of pruneReferences(p)) log('warning', n)
  })
  log('info', `Design space candidate "${c.title}" applied as a new revision`)
  return true
}

/** A stock lens inserted before surface `at` (never inside an element), either way round, followed by an air
 *  gap: one undo step. Its glasses that come from a stock catalogue's glass records are copied into the project. */
export async function insertStockLens(lens: StockLens, reversed: boolean, at: number, gapAfter: number, glassRecords: MaterialRecord[] = []): Promise<number> {
  const design = designSnapshot()
  const r = await api.stockSurfaces({ lens: toStockLens(lens), reversed, gap_after: gapAfter })
  // `at` indexes the design the lens was chosen for
  if (!sameDesign(design)) {
    toast('warning', t('c.staleDesign'))
    return -1
  }
  const st = useProjectStore.getState()
  const surfs = st.project.system.surfaces
  const n = surfs.length
  let pos = Math.max(1, Math.min(at, n - 1))
  const glass = (m: string) => !['AIR', 'MIRROR', 'VACUUM', ''].includes(m.toUpperCase())
  while (pos < n - 1 && pos > 0 && glass(surfs[pos - 1].material) && surfs[pos - 1].type !== 'coordinate_break') pos++
  const used = new Set(lens.materials.map((m) => m.toUpperCase()))
  st.commit(`Insert stock lens ${lens.part}`, (p) => {
    p.system.surfaces.splice(pos, 0, ...r.surfaces.map((s) => defaultSurface({ ...s, id: newId() })))
    for (const rec of glassRecords) {
      if (used.has(rec.name.toUpperCase()) && !p.custom_materials.some((m) => m.name.toUpperCase() === rec.name.toUpperCase())) p.custom_materials.push(rec)
    }
  })
  useProjectStore.setState({ selection: r.surfaces.map((_, k) => pos + k) })
  log('info', `Inserted stock lens ${lens.part}${reversed ? ' (reversed)' : ''} at surface ${pos}`)
  return pos
}

/** Returns false when the user kept the current project. */
export async function newBlankProject(): Promise<boolean> {
  if (!(await confirmDiscard())) return false
  openProject(blankProject(), { saved: false })
  return true
}

/** A new, unsaved project from an engine sample. Returns true when it was opened. */
export async function newFromTemplate(sampleId: string): Promise<boolean> {
  if (!(await confirmDiscard())) return false
  try {
    const p = await api.sample(sampleId)
    const fresh: Project = { ...normalizeProject(p), id: newId(), revisions: [], checksum: null }
    fresh.metadata = { ...fresh.metadata, created: nowIso(), modified: nowIso() }
    openProject(fresh, { saved: false })
    // a template can name the view it is about (the live-image examples)
    const view = fresh.ui?.open_view
    if (typeof view === 'string' && (ALL_VIEWS as readonly string[]).includes(view)) useUiStore.getState().showView(view as ViewKind)
    return true
  } catch (e) {
    toast('error', (e as Error).message)
    return false
  }
}

/** Start screen "Discard changes": reopen the saved version of the recovered project (or the last saved
 * project, else the tutorial sample) and drop the recovered autosave. */
export async function discardRecovery(): Promise<void> {
  const rec = useUiStore.getState().recovery
  if (!rec) return
  let library: Awaited<ReturnType<typeof storage.listProjects>> = []
  try {
    library = await storage.listProjects()
  } catch {
    /* storage unavailable */
  }
  const target = discardTarget(rec.projectId, library)
  if (target) openProject(target.project, { inLibrary: true })
  else {
    try {
      openProject(await api.sample('achromat-start'), { saved: true })
    } catch {
      openProject(blankProject(), { saved: true })
    }
  }
  useUiStore.getState().set({ recovery: null })
  await storage.clearAutosave().catch(() => undefined)
  log('info', `Discarded the unsaved changes to "${rec.name}"`)
}

export async function saveProject(): Promise<boolean> {
  const st = useProjectStore.getState()
  try {
    // every explicit save records a revision snapshot of the optical system
    st.addRevision(`Saved ${new Date().toLocaleString()}`)
    const p = useProjectStore.getState().project
    await storage.putProject(p)
    // the copy written is saved: an edit made meanwhile stays unsaved, and another project opened meanwhile is untouched
    useProjectStore.getState().markSaved(true, p)
    await storage.setAutosave(p, false)
    toast('success', `${t('pm.saved')}: ${p.metadata.name}`)
    log('success', `Saved "${p.metadata.name}" to browser storage`)
    return true
  } catch (e) {
    toast('error', `Save failed: ${(e as Error).message}`)
    return false
  }
}

export async function saveProjectAs(name: string, description?: string) {
  const st = useProjectStore.getState()
  st.updateProject((p) => {
    p.id = newId()
    p.metadata.name = name
    if (description !== undefined) p.metadata.description = description
    p.metadata.created = nowIso()
  }, 'Save as')
  await saveProject()
}

export async function exportProject() {
  const p = useProjectStore.getState().project
  const text = await serializeProject(p)
  const safe = p.metadata.name.replace(/[^\w.-]+/g, '_').slice(0, 80) || 'project'
  downloadText(safe + FILE_EXTENSION, text)
  log('info', `Exported ${safe}${FILE_EXTENSION} (${(text.length / 1024).toFixed(1)} kB, SHA-256 checksum)`)
}

function toBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf)
  let bin = ''
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(bin)
}

/** Import a glass catalogue (AGF) into the browser's catalogue library. Returns the catalogue, or null. */
export async function importAgfFile(): Promise<GlassCatalog | null> {
  const f = await pickFile('.agf,.AGF')
  if (!f) return null
  try {
    const cat = await useCatalogStore.getState().importFile(f.name, toBase64(await f.arrayBuffer()))
    const flagged = cat.records.filter((r) => r.verified === false).length
    const skipped = cat.diagnostics.filter((d) => d.level === 'error').length
    log(flagged || skipped ? 'warning' : 'success', `Glass catalogue ${cat.name}: ${cat.records.length} glasses imported` + (flagged ? `, ${flagged} flagged` : '') + (skipped ? `, ${skipped} errors` : ''))
    toast(flagged || skipped ? 'warning' : 'success', `${cat.name}: ${cat.records.length} glasses`)
    return cat
  } catch (e) {
    toast('error', `Catalogue import failed: ${(e as Error).message}`)
    log('error', `Catalogue import of ${f.name} failed: ${(e as Error).message}`)
    return null
  }
}

/** Generate a self-contained HTML engineering report of the current design and download it. */
export async function generateReport() {
  const p = useProjectStore.getState().project
  try {
    log('info', 'Generating engineering report…')
    const data = await collectReportData(p)
    const tol = useTolStore.getState()
    const html = await buildReportHtml(p, data, {
      engineVersion: useEngineStore.getState().engineVersion,
      // a result waiting to be applied belongs in the report only of the project it was computed for
      optimization: useOptStore.getState().projectId === p.id ? useOptStore.getState().result : null,
      tolerance: tol.result && tol.resultKey === tolKey() ? tol.result : null,
    })
    const safe = p.metadata.name.replace(/[^\w.-]+/g, '_').slice(0, 80) || 'project'
    downloadText(`${safe}_report.html`, html, 'text/html')
    log('success', `Report ${safe}_report.html generated (${(html.length / 1024).toFixed(0)} kB)${data.errors.length ? `; skipped: ${data.errors.join('; ')}` : ''}`)
    toast('success', 'Engineering report downloaded')
  } catch (e) {
    log('error', `Report failed: ${(e as Error).message}`)
    toast('error', `Report failed: ${(e as Error).message}`)
  }
}

/** Import a STEP/IGES file into the current project's CAD models (exact B-rep kept for re-export). */
export async function importCadFile(f: File): Promise<boolean> {
  try {
    log('info', `Importing ${f.name}…`)
    const projectId = useProjectStore.getState().project.id
    const r = await api.importCad(f.name, toBase64(await f.arrayBuffer()))
    if (useProjectStore.getState().project.id !== projectId) {
      toast('warning', t('c.staleProject'))
      log('warning', `Import of ${f.name} discarded: another project was opened while it ran`)
      return false
    }
    useProjectStore.getState().addCadAsset({
      id: newId(),
      name: r.name,
      source_filename: f.name,
      format: r.format as 'step' | 'iges',
      units: 'mm',
      imported: nowIso(),
      mesh: { positions_b64: r.positions_b64, indices_b64: r.indices_b64, vertices: r.vertices, triangles: r.triangles },
      bbox_min: r.bbox_min,
      bbox_max: r.bbox_max,
      surface_area_mm2: r.surface_area_mm2,
      volume_mm3: r.volume_mm3,
      closed: r.closed,
      diagnostics: r.diagnostics,
      bodies: r.bodies,
      source_b64: r.source_b64,
      mesh_deflection_mm: r.mesh_deflection_mm,
      tree: r.tree ?? [],
      hidden_parts: [],
      part_roles: {},
      transform: { translate: [0, 0, 0], rotate_deg: [0, 0, 0] },
      visible: true,
      color: DEFAULT_CAD_COLOR,
      opacity: 0.55,
    })
    log('success', `Imported ${f.name}: ${r.parts && r.parts > r.bodies.length ? `${r.parts} parts in ${r.bodies.length} top-level node(s)` : `${r.bodies.length} bod${r.bodies.length === 1 ? 'y' : 'ies'}`}, ${r.size.map((v) => v.toPrecision(5)).join(' × ')} mm${r.volume_mm3 !== null ? `, ${r.volume_mm3.toPrecision(6)} mm³` : ''}`)
    toast('success', `${f.name}: ${r.bodies.length} bod${r.bodies.length === 1 ? 'y' : 'ies'} imported`)
    useUiStore.getState().set({ bottomTab: 'cad', bottomOpen: true })
    return true
  } catch (e) {
    toast('error', `CAD import failed: ${(e as Error).message}`)
    log('error', `CAD import failed: ${(e as Error).message}`)
    return false
  }
}

export interface CadExportOptions {
  format: 'step' | 'iges'
  rim_margin: number
  include_stop: boolean
  include_image: boolean
  include_rays: boolean
  include_cad: boolean
  /** spacers, cells and a simple barrel around the elements */
  include_mechanics: boolean
}

/** Export the optical system (and the project's CAD models) as STEP or IGES and download it. */
export async function exportCad(opts: CadExportOptions) {
  const p = useProjectStore.getState().project
  const r = await api.exportCad({ system: p.system, custom_materials: p.custom_materials, cad_assets: p.cad_assets, ...opts })
  const bytes = Uint8Array.from(atob(r.data_base64), (c) => c.charCodeAt(0))
  const safe = p.metadata.name.replace(/[^\w.-]+/g, '_').slice(0, 80) || 'project'
  const name = `${safe}.${opts.format === 'step' ? 'step' : 'igs'}`
  const blob = new Blob([bytes], { type: opts.format === 'step' ? 'model/step' : 'model/iges' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  log('success', `Exported ${name}: ${r.report.solids.length} optical solid(s)${r.report.mechanics ? `, ${r.report.mechanics.spacers.length} spacer(s), ${r.report.mechanics.cells.length} cell(s)${r.report.mechanics.barrel ? ', barrel' : ''}` : ''}, ${r.report.items.length} item(s), ${(r.report.bytes / 1024).toFixed(0)} kB${r.report.skipped.length ? `; skipped ${r.report.skipped.length}` : ''}`)
  return { name, report: r.report }
}

/** Import an STL file into the current project's CAD models. */
export async function importStlFile(f: File, units: string): Promise<boolean> {
  try {
    const r = await api.importStl(f.name, toBase64(await f.arrayBuffer()), units)
    useProjectStore.getState().addCadAsset({
      id: newId(),
      name: f.name.replace(/\.stl$/i, ''),
      source_filename: f.name,
      format: 'stl',
      units,
      imported: nowIso(),
      mesh: { positions_b64: r.positions_b64, indices_b64: r.indices_b64, vertices: r.vertices, triangles: r.triangles },
      bbox_min: r.bbox_min,
      bbox_max: r.bbox_max,
      surface_area_mm2: r.surface_area_mm2,
      volume_mm3: r.volume_mm3,
      closed: r.closed,
      diagnostics: r.diagnostics,
      transform: { translate: [0, 0, 0], rotate_deg: [0, 0, 0] },
      visible: true,
      color: DEFAULT_CAD_COLOR,
      opacity: 0.55,
    })
    const warn = r.diagnostics.filter((d) => d.level === 'warning')
    log(warn.length ? 'warning' : 'success', `Imported ${f.name}: ${r.triangles.toLocaleString()} triangles (${r.format}), ${r.size.map((v) => v.toPrecision(5)).join(' × ')} mm${warn.length ? `; ${warn.map((d) => d.message).join('; ')}` : ''}`)
    toast('success', `${f.name}: ${r.triangles.toLocaleString()} triangles imported`)
    useUiStore.getState().set({ bottomTab: 'cad', bottomOpen: true })
    return true
  } catch (e) {
    toast('error', `STL import failed: ${(e as Error).message}`)
    log('error', `STL import failed: ${(e as Error).message}`)
    return false
  }
}

export async function importZmxFile(f: File): Promise<boolean> {
  try {
    // glasses missing from the built-in library are looked up in the imported catalogues
    const catalogRecords = [...useCatalogStore.getState().index.byName.values()].map((g) => g.record)
    const r = await api.importZmx(f.name, toBase64(await f.arrayBuffer()), catalogRecords)
    openProject(r.project, { saved: false })
    const bad = r.diagnostics.filter((d) => d.status !== 'imported' && d.status !== 'info').length
    log(bad ? 'warning' : 'success', `ZMX import of ${f.name}: ${r.diagnostics.length} diagnostics (${bad} need attention)`)
    useUiStore.getState().openDialog('importReport', { filename: f.name, diagnostics: r.diagnostics })
    return true
  } catch (e) {
    toast('error', `ZMX import failed: ${(e as Error).message}`)
    log('error', `ZMX import failed: ${(e as Error).message}`)
    return false
  }
}

/** Open or import a file (picked when not given). Returns true when something was opened or imported. */
export async function importProjectFile(file?: File | null, accept = '.opticore,.json,.zmx,.stl,.step,.stp,.iges,.igs,application/json'): Promise<boolean> {
  const f = file ?? (await pickFile(accept))
  if (!f) return false
  // CAD geometry is added to the current project (no discard prompt)
  if (/\.stl$/i.test(f.name)) return useUiStore.getState().openDialog('stlImport', { file: f }), true
  if (/\.(step|stp|iges|igs)$/i.test(f.name)) return importCadFile(f)
  if (!(await confirmDiscard())) return false
  if (/\.zmx$/i.test(f.name)) return importZmxFile(f)
  try {
    const text = await f.text()
    const parsed = await parseProjectFile(text)
    // full schema validation by the engine when available
    if (useEngineStore.getState().backend === 'online') {
      const v = await api.validateProject(JSON.parse(text))
      for (const n of v.notes) if (!parsed.notes.includes(n)) parsed.notes.push(n)
    }
    openProject(parsed.project, { saved: false })
    for (const n of parsed.notes) {
      toast('warning', n)
      log('warning', n)
    }
    toast('success', `${t('pm.importOk')}: ${parsed.project.metadata.name}`)
    return true
  } catch (e) {
    const msg = e instanceof ProjectFileError ? e.message : `Import failed: ${(e as Error).message}`
    toast('error', msg)
    log('error', msg)
    return false
  }
}

export function undo() {
  useProjectStore.getState().undo()
}
export function redo() {
  useProjectStore.getState().redo()
}

/** Quick focus: optimise the image distance for minimum polychromatic RMS spot (lib/quickFocus.ts). */
export async function quickFocus() {
  const st = useProjectStore.getState()
  const design = designSnapshot()
  const s = st.project.system
  const setup = quickFocusSetup(s)
  if (!setup) {
    toast('error', t('qf.failed', { e: t('qf.noDistance') }))
    return
  }
  const { t0, spec, row, configuration } = setup
  const custom = st.project.custom_materials
  try {
    // per-field RMS before and after (engine): the field-weighted mean can trade one field for the others
    const before = await api.focus({ system: s, custom_materials: custom }).catch(() => null)
    const { job_id } = await api.optimizeStart({ system: s, custom_materials: custom, optimization: spec })
    for (let i = 0; i < 400; i++) {
      await new Promise((r) => setTimeout(r, 120))
      const snap = await api.optimizeStatus(job_id)
      if (snap.state === 'finished' && snap.result) {
        const tNew = snap.result.variables[0].final
        // the focus belongs to the design it was computed for: not to another project opened meanwhile, nor to
        // this one edited meanwhile
        const cur = useProjectStore.getState()
        if (!sameDesign(design)) {
          toast('warning', t('qf.stale'))
          log('warning', 'Quick focus result discarded: the design changed while it ran')
          return
        }
        if (configuration !== null) cur.setConfigValue(row, configuration, tNew)
        else cur.updateSurface(s.surfaces.length - 2, { thickness: tNew }, 'Quick focus')
        const after = await api.focus({ system: useProjectStore.getState().project.system, custom_materials: custom }).catch(() => null)
        const rep = focusReport(before, after)
        const parts = [t('qf.done', { a: t0.toFixed(4), b: tNew.toFixed(4), r0: (snap.result.initial_merit * 1e3).toFixed(2), r1: (snap.result.final_merit * 1e3).toFixed(2) })]
        if (rep.fields.length > 1) parts.push(t('qf.fields', { list: rep.fields.join(', ') }))
        if (rep.worse.length) parts.push(t('qf.worse', { list: rep.worse.map((k) => `F${k + 1}`).join(', ') }))
        toast(rep.worse.length ? 'warning' : 'success', parts.join(' · '))
        log(rep.worse.length ? 'warning' : 'success', `Quick focus moved image surface by ${(tNew - t0).toFixed(5)} mm${rep.fields.length ? `; RMS by field (µm): ${rep.fields.join(', ')}` : ''}`)
        return
      }
      if (snap.state === 'failed' || snap.state === 'cancelled') throw new Error(snap.error ?? 'Quick focus failed')
    }
  } catch (e) {
    toast('error', t('qf.failed', { e: (e as Error).message }))
  }
}

export function insertSurfaceAfterSelection() {
  const st = useProjectStore.getState()
  const sel = st.selection[0] ?? 1
  st.insertSurface(Math.min(sel + 1, st.project.system.surfaces.length - 1))
}

export function deleteSelection() {
  const st = useProjectStore.getState()
  st.deleteSurfaces(st.selection)
}

/** Re-trace: re-evaluate the system and force every open analysis view to recompute.
 * Results are not cleared first: views keep showing the previous result until the new one arrives. */
export function retrace() {
  useEngineStore.getState().evaluate(true)
  useEngineStore.setState((s) => ({ retraceToken: s.retraceToken + 1 }))
}

/** Re-read the assembly structure of a STEP/IGES model from its stored source (models imported before
 * assemblies were supported). Keeps placement, colour and optical settings. */
export async function rebuildCadStructure(assetId: string): Promise<void> {
  const st = useProjectStore.getState()
  const a = st.project.cad_assets.find((x) => x.id === assetId)
  if (!a?.source_b64) return
  try {
    const r = await api.importCad(a.source_filename || `${a.name}.${a.format === 'iges' ? 'igs' : 'step'}`, a.source_b64)
    st.updateCadAsset(
      assetId,
      {
        mesh: { positions_b64: r.positions_b64, indices_b64: r.indices_b64, vertices: r.vertices, triangles: r.triangles },
        tree: r.tree ?? [],
        bodies: r.bodies,
        diagnostics: r.diagnostics,
        hidden_parts: [],
        part_roles: {},
      },
      `Read the assembly structure of ${a.name}`,
    )
    toast('success', `${a.name}: ${r.parts ?? r.bodies.length} part(s)`)
  } catch (e) {
    toast('error', (e as Error).message)
  }
}

/** After the engine built the lens: open it unsaved in Design with the layout and spot diagram, focus it, and point at Optimize. */
export async function openFirstLens(p: Project): Promise<boolean> {
  if (!(await confirmDiscard())) return false
  const fresh: Project = { ...normalizeProject(p), id: newId(), revisions: [], checksum: null }
  fresh.metadata = { ...fresh.metadata, created: nowIso(), modified: nowIso() }
  openProject(fresh, { saved: false })
  const ui = useUiStore.getState()
  ui.setWorkspace('design')
  useUiStore.getState().set({ split: true, leftView: 'layout2d', rightView: 'spot', bottomTab: 'lde', bottomOpen: true, nextHint: 'optimise' })
  await quickFocus()
  return true
}
