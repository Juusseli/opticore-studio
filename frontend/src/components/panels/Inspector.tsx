import { Plus, Trash2 } from 'lucide-react'
import { designSnapshot, sameDesign } from '../../store/designGuard'
import { useAllMaterials } from '../../store/catalogStore'
import { useEffect, useState } from 'react'
import { api } from '../../lib/api'
import type { CoatingCurve, CoatingDefinition, ElementsResult, Solve, SolveType } from '../../lib/types'
import { fmt } from '../../lib/format'
import { paramLabel } from '../../lib/paramLabels'
import { xyTermName } from '../../lib/xyTerms'
import { useT } from '../../lib/i18n'
import type { Surface, VariableParam } from '../../lib/types'
import { degToRad, LENGTH_TO_MM, radToDeg } from '../../lib/units'
import { useEngineStore } from '../../store/engineStore'
import { useProjectStore } from '../../store/projectStore'
import { useUiStore } from '../../store/uiStore'
import { Badge, Button, Checkbox, Field, IconButton, NumberField, Section, Select, TextField } from '../common/ui'
import { Plot } from '../common/Plot'
import { useAnalysis } from '../views/useAnalysis'
import { describeSolve, SOLVE_LABEL } from '../../lib/solves'
import { coatingOf, mediumBefore } from '../../lib/project'
import { gapSetByMounts } from '../../lib/mounts'
import { MaterialCell } from '../editors/LensDataEditor'
import { surfaceTitle } from '../editors/surfaceTitle'

const ASPH_PARAMS: VariableParam[] = ['asph_4', 'asph_6', 'asph_8', 'asph_10', 'asph_12']
const PHASE_PARAMS: VariableParam[] = ['phase_1', 'phase_2', 'phase_3', 'phase_4']

export function Inspector() {
  const t = useT()
  const selection = useProjectStore((s) => s.selection)
  const system = useProjectStore((s) => s.project.system)
  const valid = selection.filter((i) => i < system.surfaces.length)
  if (!valid.length) return <div className="p-4 text-muted">{t('ins.none')}</div>
  if (valid.length > 1) return <MultiInspector indices={valid} />
  return <SurfaceInspector i={valid[0]} />
}

function SurfaceInspector({ i }: { i: number }) {
  const t = useT()
  // the coating designer is an advanced module: not offered in the Design workspace
  const advanced = useUiStore((st) => st.workspace !== 'design')
  const system = useProjectStore((s) => s.project.system)
  const variables = useProjectStore((s) => s.project.optimization.variables)
  const update = useProjectStore((s) => s.updateSurface)
  const st = useProjectStore.getState
  const ev = useEngineStore((s) => s.evaluation)
  const materials = useAllMaterials()
  const [angleUnit, setAngleUnit] = useState<'deg' | 'rad'>('deg')
  const s = system.surfaces[i]
  const n = system.surfaces.length
  const isObj = i === 0
  const isImg = i === n - 1
  const isCb = s.type === 'coordinate_break'
  const u = (patch: Partial<Surface>, label: string) => update(i, patch, label)
  const mat = materials.find((m) => m.name === s.material)
  const geom = ev?.surfaces[i]
  const nPrim = ev?.indices?.[system.primary_wavelength]?.[i]
  const edge = ev?.edge_thickness?.[i]
  const solved = ev?.solved?.find((x) => x.surface === i)
  const nBefore = i > 0 ? ev?.indices?.[system.primary_wavelength]?.[i - 1] : undefined
  const coatings = useEngineStore((s) => s.coatings)
  const customCoatings = system.custom_coatings ?? []
  const isMirror = s.material.toUpperCase() === 'MIRROR'
  const allCoatingNames = [...coatings.map((c) => c.name), ...customCoatings.map((c) => c.name.toUpperCase())]

  const angle = (v: number) => (angleUnit === 'deg' ? v : degToRad(v))
  const angleIn = (v: number) => (angleUnit === 'deg' ? v : radToDeg(v))

  const varOf = (p: VariableParam) => variables.find((v) => v.surface_id === s.id && v.parameter === p)
  const setVar = (p: VariableParam, patch: Partial<{ min: number | null; max: number | null; enabled: boolean }>) =>
    st().updateProject((pr) => {
      const v = pr.optimization.variables.find((x) => x.surface_id === s.id && x.parameter === p)
      if (v) Object.assign(v, patch)
    }, 'Edit variable bounds')

  const isIdeal = s.type === 'ideal'
  // a surface of a lens element (glass on one side): mechanics and the element drawing (elements.py)
  const gas = (m: string) => ['AIR', 'VACUUM', 'MIRROR', ''].includes(m.toUpperCase())
  const lensSurface = !isObj && !isImg && !isCb && !isIdeal && !isMirror && (!gas(s.material) || !gas(mediumBefore(system, i)))
  const baseRows: VariableParam[] = isIdeal ? ['ideal_power', 'thickness'] : isCb ? ['decenter_x', 'decenter_y', 'tilt_x', 'tilt_y', 'tilt_z'] : ['curvature', 'thickness', 'conic', ...(s.type === 'biconic' ? (['curvature_x', 'conic_x'] as VariableParam[]) : []), ...(s.type === 'even_asphere' ? ASPH_PARAMS.slice(0, Math.max(1, s.aspheric.length)) : []), ...(s.type === 'zernike' ? [...ASPH_PARAMS.slice(0, s.aspheric.length), ...s.zernike_coefficients.map((_, k) => `zern_${k + 1}` as VariableParam).filter((_, k) => k > 0)] : []), ...(s.type === 'qcon' || s.type === 'qbfs' ? (s.q_coefficients ?? []).map((_, k) => `q_${k + 1}` as VariableParam) : []), ...(s.type === 'xy_polynomial' ? [...ASPH_PARAMS.slice(0, s.aspheric.length), ...(s.xy_coefficients ?? []).map((_, k) => `xy_${k + 1}` as VariableParam)] : []), ...(s.type === 'odd_asphere' ? (s.odd_coefficients ?? []).map((_, k) => `odd_${k + 1}` as VariableParam) : []), ...(isObj || isImg ? [] : PHASE_PARAMS.slice(0, s.phase_coefficients.length)), ...(!isObj && !isImg && s.grating_frequency !== 0 ? (['grating_frequency'] as VariableParam[]) : []), ...(coatingOf(system, s.coating) ? (['coating_scale', ...coatingOf(system, s.coating)!.layers.map((_, k) => `coat_layer_${k + 1}` as VariableParam)] as VariableParam[]) : [])]
  // environment model: the spacer behind an air gap, or a mirror's substrate (engine: environment.py)
  const envOn = !!system.environment_enabled
  const mountApplies = envOn && !isObj && !isImg && !isCb && !isIdeal && (isMirror || ['AIR', 'VACUUM'].includes(s.material.toUpperCase()))
  const startsGlass = envOn && !isObj && !isImg && !isCb && !isIdeal && !isMirror && !['AIR', 'VACUUM'].includes(s.material.toUpperCase())
  const seatable = envOn && !isObj && !isCb && !isMirror && (system.mounts?.length ?? 0) > 0
  // the mount tree sets this gap (the next element is seated): its spacer expansion is unused
  const gapByMounts = mountApplies && !isMirror && gapSetByMounts(system, i)
  const varRows: VariableParam[] = mountApplies && (!gapByMounts || varOf('mount_cte')) ? [...baseRows, 'mount_cte'] : baseRows

  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="border-b border-line px-3 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-title font-semibold">{surfaceTitle(s, i, n)}</span>
          <Badge>#{i}</Badge>
          {s.is_stop && <Badge tone="accent">{t('sb.stop')}</Badge>}
          {s.material === 'MIRROR' && <Badge>{t('ins.mirrorBadge')}</Badge>}
        </div>
        <div className="mt-0.5 text-small text-faint">{isObj ? t('ins.objectSurface') : isImg ? t('ins.imageSurface') : t('lde.' + s.type)}</div>
      </div>

      <Section title={t('ins.geometry')}>
        {!isObj && !isImg && (
          <Field label={t('lde.type')}>
            <Select
              className="w-full"
              value={s.type}
              options={[
                { value: 'standard', label: t('lde.standard') },
                { value: 'even_asphere', label: t('lde.even_asphere') },
                { value: 'odd_asphere', label: t('lde.odd_asphere') },
                { value: 'biconic', label: t('lde.biconic') },
                { value: 'zernike', label: t('lde.zernike') },
                { value: 'qcon', label: t('lde.qcon') },
                { value: 'qbfs', label: t('lde.qbfs') },
                { value: 'xy_polynomial', label: t('lde.xy_polynomial') },
                { value: 'ideal', label: t('lde.ideal') },
                { value: 'coordinate_break', label: t('lde.coordinate_break') },
              ]}
              onChange={(v) => u(v === 'ideal' ? { type: v, material: mediumBefore(system, i), coating: '' } : { type: v }, `Surface ${i} type`)}
            />
          </Field>
        )}
        <Field label={t('lde.label')}>
          <TextField className="w-full" value={s.label} onCommit={(v) => u({ label: v }, 'Label')} />
        </Field>
        {isIdeal && (
          <>
            <Field label={`${t('ins.focalLength')} (mm)`} hint={t('ins.focalLengthHint')}>
              <NumberField className="w-full" scrub value={s.focal_length} allowInfinity units={LENGTH_TO_MM} onCommit={(v) => u({ focal_length: v }, `Surface ${i} focal length`)} />
            </Field>
            <Field label={`${t('ins.idealConjugate')} (mm)`} hint={t('ins.idealConjugateHint')}>
              <NumberField className="w-full" value={s.ideal_object_distance} allowInfinity units={LENGTH_TO_MM} onCommit={(v) => u({ ideal_object_distance: v }, `Surface ${i} ideal-lens OPD conjugate`)} />
            </Field>
            <div className="px-3 pb-1 text-caption leading-snug text-faint">{t('ins.idealNote')}</div>
          </>
        )}
        {!isCb && !isIdeal && (
          <>
            <Field label={`${t('lde.radius')} (mm)`} hint="Radius of curvature. Positive: centre of curvature on the +z side of the vertex. 'inf' = plane.">
              {s.curvature_solve ? (
                <span className="num italic text-muted">
                  {solved?.radius === null || solved?.radius === undefined ? (solved ? 'Infinity' : '—') : fmt(solved.radius, 10)} ({t('ins.solve')})
                </span>
              ) : (
                <NumberField className="w-full" scrub value={s.radius} allowInfinity units={LENGTH_TO_MM} onCommit={(v) => u({ radius: v }, `Surface ${i} radius`)} />
              )}
            </Field>
            {!s.curvature_solve && (
              <Field label={`${t('ins.curvature')} (1/mm)`} hint="c = 1/R. Editing curvature updates the radius.">
                <NumberField className="w-full" value={s.radius === null ? 0 : 1 / s.radius} format={(v) => fmt(v, 9)} onCommit={(v) => u({ radius: !v ? null : 1 / v }, `Surface ${i} curvature`)} />
              </Field>
            )}
            <Field label={t('lde.conic')} hint="k = 0 sphere, −1 paraboloid, < −1 hyperboloid, −1…0 prolate ellipsoid, > 0 oblate ellipsoid.">
              <NumberField className="w-full" scrub scrubStep={0.01} value={s.conic} onCommit={(v) => u({ conic: v ?? 0 }, `Surface ${i} conic`)} />
            </Field>
            {s.type === 'biconic' && (
              <>
                <Field label={`${t('ins.radiusX')} (mm)`} hint="Radius of the x-z section. The radius above is the y-z (tangential) section, which the paraxial data use. 'inf' = flat in x (cylinder lens).">
                  <NumberField className="w-full" scrub value={s.radius_x} allowInfinity units={LENGTH_TO_MM} onCommit={(v) => u({ radius_x: v }, `Surface ${i} radius X`)} />
                </Field>
                <Field label={t('ins.conicX')} hint="Conic constant of the x-z section.">
                  <NumberField className="w-full" scrub scrubStep={0.01} value={s.conic_x} onCommit={(v) => u({ conic_x: v ?? 0 }, `Surface ${i} conic X`)} />
                </Field>
              </>
            )}
          </>
        )}
        {!isImg && (
          <Field label={`${t('lde.thickness')} (mm)`} hint="Signed distance to the next vertex along the local z axis. After a mirror light travels towards −z, so thicknesses are negative.">
            {s.thickness_solve ? (
              <span className="num italic text-muted">
                {solved?.thickness !== undefined && solved?.thickness !== null ? fmt(solved.thickness, 10) : '—'} ({t('ins.solve')})
              </span>
            ) : (
              <NumberField className="w-full" scrub value={s.thickness} allowInfinity={isObj} units={LENGTH_TO_MM} onCommit={(v) => u({ thickness: v }, `Surface ${i} thickness`)} />
            )}
          </Field>
        )}
        {geom && (
          <Field label={t('ins.globalVertex')}>
            <span className="num text-muted">
              ({fmt(geom.origin[0], 5)}, {fmt(geom.origin[1], 5)}, {fmt(geom.origin[2], 6)})
            </span>
          </Field>
        )}
        {edge !== null && edge !== undefined && !isCb && !isImg && !isObj && (
          <Field label={t('ins.edgeThickness')} hint="Axial distance between this surface and the next at the larger semi-diameter.">
            <span className={`num ${edge < 0 ? 'text-danger' : 'text-muted'}`}>{fmt(edge, 6)} mm</span>
          </Field>
        )}
      </Section>

      {!isObj && !isImg && (
        <Section title={t('ins.solves')}>
          {!isCb && !isIdeal && <SolveEditor i={i} kind="curvature" />}
          <SolveEditor i={i} kind="thickness" />
          <div className="px-3 pb-2 text-caption leading-snug text-faint">{t('ins.solvesHelp')}</div>
        </Section>
      )}

      {!isCb && !isImg && (
        <Section title={t('ins.material')}>
          <Field label={t('lde.material')} hint="Medium after this surface. MIRROR reflects (the medium is unchanged).">
            <div className="w-full">
              <MaterialCell cell={false} value={s.material} onCommit={(v) => u({ material: v }, `Surface ${i} material`)} />
            </div>
          </Field>
          <Field label="n (primary)">
            <span className="num text-muted">{s.material === 'MIRROR' ? '—' : fmt(nPrim, 8)}</span>
          </Field>
          {mat && (
            <>
              <Field label={t('ins.nd')}>
                <span className="num text-muted">{fmt(mat.nd, 7)}</span>
              </Field>
              <Field label={t('ins.abbe')}>
                <span className="num text-muted">{fmt(mat.vd, 5)}</span>
              </Field>
              <div className="px-3 text-caption leading-snug text-faint">{mat.source}</div>
            </>
          )}
        </Section>
      )}

      {!isCb && (
        <Section title={t('ins.aperture')}>
          <Field label={t('ins.mode')} hint="Automatic: computed to pass all fields/wavelengths without clipping. Fixed: rays outside are vignetted.">
            <Select className="w-full" value={s.semi_diameter_mode} options={[{ value: 'auto', label: t('lde.auto') }, { value: 'fixed', label: t('lde.fixed') }]} onChange={(v) => u({ semi_diameter_mode: v, semi_diameter: v === 'fixed' ? Number((ev?.semi_diameters[i] ?? s.semi_diameter).toPrecision(6)) : s.semi_diameter }, 'Aperture mode')} />
          </Field>
          <Field label={`${t('lde.semidia')} (mm)`}>
            {s.semi_diameter_mode === 'fixed' ? (
              <NumberField className="w-full" scrub value={s.semi_diameter} min={0} units={LENGTH_TO_MM} onCommit={(v) => u({ semi_diameter: v ?? 0 }, 'Semi-diameter')} />
            ) : (
              <span className="num text-muted">{fmt(ev?.semi_diameters[i], 7)} (auto)</span>
            )}
          </Field>
          {!isObj && !isImg && (
            <Field label={t('lde.stop')}>
              <Checkbox checked={s.is_stop} onChange={(v) => (v ? st().setStop(i) : u({ is_stop: false }, 'Clear stop'))} label={<span className="text-muted">{t('ins.apertureStop')}</span>} />
            </Field>
          )}
          {!isObj && !isImg && (
            <Field label={t('ins.obscuration')} hint={t('ins.obscurationHint')}>
              <NumberField className="w-full" optional value={s.obscuration ?? null} placeholder={t('ins.obscurationNone')} min={0} units={LENGTH_TO_MM} onCommit={(v) => u({ obscuration: v === null || v <= 0 ? null : v }, 'Central obscuration')} />
            </Field>
          )}
        </Section>
      )}

      {lensSurface && <MechanicsSection i={i} />}
      {!isObj && !isImg && !isCb && !!mat?.extraordinary && <CrystalSection i={i} />}

      {!isCb && !isObj && !isImg && !isIdeal && (
        <Section
          title={t('ins.coating')}
          right={
            <span className="flex gap-2">
              {advanced && (
                <Button variant="link" title={t('cd.designForHint')} onClick={() => useUiStore.getState().openDialog('coatingDesigner', { surfaces: [i] })}>
                  {t('cd.designFor')}
                </Button>
              )}
              <Button variant="link" onClick={() => useUiStore.getState().openDialog('coatings')}>
                {t('coat.edit')}
              </Button>
            </span>
          }
        >
          <Field label={t('ins.coating')} hint={isMirror ? 'Thin-film stack on a metal (or other) mirror substrate. The mirror then reflects R = (Rs + Rp)/2 of the stack in throughput and polarisation analyses; uncoated mirrors are ideal (R = 1).' : 'Thin-film stack on this interface. Replaces the bare-surface Fresnel loss in throughput, polarisation and ghost analyses and the throughput operand (transfer-matrix method; layers may be dispersive or absorbing).'}>
            <Select
              className="w-full"
              value={s.coating.toUpperCase()}
              options={[
                { value: '', label: t('ins.uncoated') },
                ...coatings.map((c) => ({ value: c.name, label: c.name })),
                ...customCoatings.map((c) => ({ value: c.name.toUpperCase(), label: `${c.name.toUpperCase()} (${t('coat.project')})${isMirror && c.substrate_index === null ? ' — no substrate' : ''}` })),
                ...(s.coating && !allCoatingNames.includes(s.coating.toUpperCase()) ? [{ value: s.coating.toUpperCase(), label: `${s.coating} (unknown)` }] : []),
              ]}
              onChange={(v) => u({ coating: v }, 'Coating')}
            />
          </Field>
          {s.coating && (
            <CoatingPreview
              name={s.coating.toUpperCase()}
              definition={customCoatings.find((c) => c.name.toUpperCase() === s.coating.toUpperCase())}
              mirror={isMirror}
              incident={isMirror ? Math.max(1, nBefore ?? 1) : 1}
              substrate={Math.max(nBefore ?? 1, nPrim ?? 1)}
              wavelength={system.wavelengths[system.primary_wavelength]?.value}
              description={coatings.find((c) => c.name === s.coating.toUpperCase())?.description}
            />
          )}
        </Section>
      )}

      {!isCb && !isObj && !isImg && !isIdeal && (
        <Section title={t('ins.diffractive')} defaultOpen={s.grating_frequency !== 0 || s.phase_coefficients.some((a) => a !== 0)}>
          <Field label={t('ins.diffOrder')} hint="Diffraction order m used by the grating equation n₂d₂ₜ = n₁d₁ₜ + mλ∇φ/2π (efficiency assumed 100 % in this order).">
            <NumberField className="w-full" value={s.diffraction_order} integer min={-50} max={50} onCommit={(v) => u({ diffraction_order: v ?? 1 }, `Surface ${i} diffraction order`)} />
          </Field>
          <Field label={`${t('ins.grating')} (l/mm)`} hint={t('ins.gratingHint')}>
            <NumberField className="w-full" value={s.grating_frequency} onCommit={(v) => u({ grating_frequency: v ?? 0 }, `Surface ${i} grating frequency`)} />
          </Field>
          <Field label={`${t('ins.phaseNorm')} (mm)`} hint={t('ins.phaseNormHint')}>
            <NumberField className="w-full" value={s.phase_norm_radius} min={1e-6} units={LENGTH_TO_MM} onCommit={(v) => u({ phase_norm_radius: v ?? 1 }, `Surface ${i} phase normalisation radius`)} />
          </Field>
          {s.phase_coefficients.map((a, k) => (
            <Field key={k} label={`A${k + 1} (rad)`} hint={k === 0 ? t('ins.phaseA1Hint') : t('ins.phaseTermHint', { p: 2 * (k + 1) })}>
              <NumberField className="w-full" value={a} onCommit={(v) => u({ phase_coefficients: s.phase_coefficients.map((x, j) => (j === k ? (v ?? 0) : x)) }, `Surface ${i} phase A${k + 1}`)} />
              <IconButton size="sm" tone="danger" title={t('ins.removeTerm', { term: `A${k + 1}` })} onClick={() => u({ phase_coefficients: s.phase_coefficients.filter((_, j) => j !== k) }, 'Remove phase term')}>
                <Trash2 size={12} />
              </IconButton>
            </Field>
          ))}
          <div className="flex items-center justify-between px-3 pb-2">
            <span className="text-caption text-faint">{t('ins.doeHelp')}</span>
            <Button size="sm" variant="ghost" onClick={() => u({ phase_coefficients: [...s.phase_coefficients, 0] }, 'Add phase term')} disabled={s.phase_coefficients.length >= 8}>
              <Plus size={12} /> A{s.phase_coefficients.length + 1}
            </Button>
          </div>
        </Section>
      )}

      {s.type === 'zernike' && <ZernikeSection i={i} />}
      {(s.type === 'qcon' || s.type === 'qbfs') && <QSection i={i} />}
      {s.type === 'xy_polynomial' && <XYSection i={i} />}
      {s.type === 'odd_asphere' && <OddSection i={i} />}
      {advanced && !isObj && !isImg && !isCb && !isMirror && <PolarizingSection i={i} />}

      {(s.type === 'even_asphere' || s.type === 'zernike' || s.type === 'xy_polynomial') && (
        <Section title={t('ins.asphere')} right={<Button size="sm" variant="ghost" aria-label={t('ins.addTerm')} title={t('ins.addTerm')} onClick={() => u({ aspheric: [...s.aspheric, 0] }, 'Add aspheric term')} disabled={s.aspheric.length >= 8}><Plus size={12} /></Button>}>
          {s.aspheric.length === 0 && <div className="px-3 text-small text-faint">{t('ins.asphEmpty')}</div>}
          {s.type === 'even_asphere' && !isObj && !isImg && <ConvertToQ i={i} />}
          {s.aspheric.map((a, k) => (
            <Field key={k} label={`A${2 * k + 4} (mm^${-(2 * k + 3)})`}>
              <NumberField className="w-full" value={a} format={(v) => (v === null ? '' : v === 0 ? '0' : v.toExponential(6))} onCommit={(v) => u({ aspheric: s.aspheric.map((x, j) => (j === k ? (v ?? 0) : x)) }, `A${2 * k + 4}`)} />
              <IconButton size="sm" tone="danger" title={t('ins.removeTerm', { term: `A${2 * k + 4}` })} onClick={() => u({ aspheric: s.aspheric.filter((_, j) => j !== k) }, 'Remove aspheric term')}>
                <Trash2 size={12} />
              </IconButton>
            </Field>
          ))}
        </Section>
      )}

      {isCb && (
        <Section title={t('ins.cb')}>
          <Field label={t('ins.angleUnit')}>
            <Select className="w-full" value={angleUnit} options={[{ value: 'deg', label: t('ins.degrees') }, { value: 'rad', label: t('ins.radians') }]} onChange={setAngleUnit} />
          </Field>
          <Field label={`${t('ins.decenterX')} (mm)`}>
            <NumberField className="w-full" scrub value={s.decenter_x} units={LENGTH_TO_MM} onCommit={(v) => u({ decenter_x: v ?? 0 }, 'Decenter X')} />
          </Field>
          <Field label={`${t('ins.decenterY')} (mm)`}>
            <NumberField className="w-full" scrub value={s.decenter_y} units={LENGTH_TO_MM} onCommit={(v) => u({ decenter_y: v ?? 0 }, 'Decenter Y')} />
          </Field>
          {(['tilt_x', 'tilt_y', 'tilt_z'] as const).map((k) => (
            <Field key={k} label={`${t('ins.tilt')} ${k.slice(-1).toUpperCase()} (${angleUnit})`} hint={t('ins.tiltHint')}>
              <NumberField className="w-full" scrub scrubStep={0.05} value={angle(s[k])} format={(v) => (v === null ? '' : fmt(v, 10))} onCommit={(v) => u({ [k]: angleIn(v ?? 0) } as Partial<Surface>, `Tilt ${k}`)} />
            </Field>
          ))}
          <Field label={t('ins.order')}>
            <Select className="w-full" value={s.cb_order} options={[{ value: 0, label: t('ins.order0') }, { value: 1, label: t('ins.order1') }]} onChange={(v) => u({ cb_order: v }, 'CB order')} />
          </Field>
          <div className="px-3 pt-1 text-caption leading-snug text-faint">{t('ins.cbNote')}</div>
        </Section>
      )}

      {(mountApplies || startsGlass || seatable) && (
        <Section title={t('ins.mount')}>
          {seatable && (
            <Field label={t('mt.heldBy')} hint={t('mt.heldByHint')}>
              <Select className="w-full" ariaLabel={t('mt.heldBy')} value={s.seat_part ?? ''} options={[{ value: '', label: '—' }, ...(system.mounts ?? []).map((m) => ({ value: m.id, label: m.name || m.id }))]} onChange={(v) => u({ seat_part: v || null }, v ? 'Seat surface' : 'Unseat surface')} />
            </Field>
          )}
          {startsGlass && (
            <Field label={t('mt.elemTemp')} hint={t('mt.elemTempHint')}>
              <NumberField className="w-full" optional ariaLabel={t('mt.elemTemp')} value={s.element_temperature_c ?? null} placeholder={fmt(system.temperature_c, 4)} min={-273} max={1000} onCommit={(v) => u({ element_temperature_c: v }, 'Element temperature')} />
            </Field>
          )}
          {mountApplies && (
          <Field label={isMirror ? t('ins.substrateCte') : t('ins.spacerCte')} hint={isMirror ? t('ins.substrateHint') : t('ins.spacerHint')}>
            <NumberField
              className="w-full"
              optional
              disabled={gapByMounts}
              ariaLabel={isMirror ? t('ins.substrateCte') : t('ins.spacerCte')}
              value={gapByMounts ? null : (s.mount_cte ?? null)}
              placeholder={gapByMounts ? t('mt.gapByMounts') : t('ins.housingValue', { v: fmt(system.housing_cte ?? 23.6, 4) })}
              min={-50}
              max={500}
              onCommit={(v) => u({ mount_cte: v }, isMirror ? 'Substrate expansion' : 'Spacer expansion')}
            />
          </Field>
          )}
        </Section>
      )}

      {!isObj && !isImg && (
        <Section title={t('ins.optim')}>
          {varRows.map((p) => {
            const v = varOf(p)
            return (
              <div key={p} className="grid grid-cols-[22px_minmax(80px,1.3fr)_1fr_1fr] items-center gap-1 px-3 py-0.5">
                <input type="checkbox" className="accent-[var(--c-accent)]" checked={!!v} onChange={() => st().toggleVariable(s.id, p)} aria-label={t('ins.varToggle', { p: paramLabel(p, t) })} />
                <span className="truncate text-small text-muted" title={paramLabel(p, t)}>
                  {paramLabel(p, t)}
                </span>
                <NumberField className="h-6" ariaLabel={`${paramLabel(p, t)} ${t('opt.min')}`} value={v?.min ?? null} allowInfinity placeholder={t('opt.min')} disabled={!v} format={(x) => (x === null ? '−∞' : String(x))} onCommit={(x) => setVar(p, { min: x })} />
                <NumberField className="h-6" ariaLabel={`${paramLabel(p, t)} ${t('opt.max')}`} value={v?.max ?? null} allowInfinity placeholder={t('opt.max')} disabled={!v} format={(x) => (x === null ? '+∞' : String(x))} onCommit={(x) => setVar(p, { max: x })} />
              </div>
            )
          })}
          <div className="px-3 pt-1 text-caption text-faint">{t('ins.curvNote')}</div>
        </Section>
      )}

      <Section title={t('ins.comment')} defaultOpen={!!s.comment}>
        <div className="px-3">
          <TextField className="w-full" value={s.comment} onCommit={(v) => u({ comment: v }, 'Comment')} />
        </div>
      </Section>
    </div>
  )
}

function MultiInspector({ indices }: { indices: number[] }) {
  const t = useT()
  // the coating designer is an advanced module: not offered in the Design workspace
  const advanced = useUiStore((st) => st.workspace !== 'design')
  const system = useProjectStore((s) => s.project.system)
  const updateMany = useProjectStore((s) => s.updateSurfaces)
  const n = system.surfaces.length
  const inner = indices.filter((i) => i > 0 && i < n - 1)
  const surfs = inner.map((i) => system.surfaces[i])
  const common = <K extends keyof Surface>(k: K): Surface[K] | null => (surfs.length && surfs.every((s) => s[k] === surfs[0][k]) ? surfs[0][k] : null)
  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="border-b border-line px-3 py-2.5 text-title font-semibold">{t('ins.multi', { n: indices.length })}</div>
      {inner.length === 0 ? (
        <div className="p-3 text-muted">{t('ins.noBatch')}</div>
      ) : (
        <Section title={t('ins.batch')}>
          <Field label={t('lde.material')}>
            <div className="w-full">
              <MaterialCell cell={false} value={common('material') ?? ''} onCommit={(v) => updateMany(inner, { material: v }, `Set material on ${inner.length} surfaces`)} />
            </div>
          </Field>
          <Field label={t('ins.mode')}>
            <Select className="w-full" value={common('semi_diameter_mode') ?? 'auto'} options={[{ value: 'auto', label: t('lde.auto') }, { value: 'fixed', label: t('lde.fixed') }]} onChange={(v) => updateMany(inner, { semi_diameter_mode: v }, 'Batch aperture mode')} />
          </Field>
          <Field label={`${t('lde.semidia')} (mm)`}>
            <NumberField className="w-full" value={common('semi_diameter')} placeholder={t('ins.mixed')} format={(v) => (v === null ? '' : String(v))} min={0} onCommit={(v) => updateMany(inner, { semi_diameter: v ?? 0, semi_diameter_mode: 'fixed' }, 'Batch semi-diameter')} />
          </Field>
          <Field label={t('lde.conic')}>
            <NumberField className="w-full" value={common('conic')} placeholder={t('ins.mixed')} format={(v) => (v === null ? '' : String(v))} onCommit={(v) => updateMany(inner, { conic: v ?? 0 }, 'Batch conic')} />
          </Field>
          {advanced && (
            <div className="px-3 pt-2">
              <Button size="sm" onClick={() => useUiStore.getState().openDialog('coatingDesigner', { surfaces: inner.filter((i) => system.surfaces[i].type !== 'coordinate_break') })} title={t('cd.designForHint')}>
                {t('cd.designForN', { n: inner.filter((i) => system.surfaces[i].type !== 'coordinate_break').length })}
              </Button>
            </div>
          )}
          <div className="px-3 pt-2">
            <Button size="sm" variant="danger" onClick={() => useProjectStore.getState().deleteSurfaces(inner)}>
              <Trash2 size={12} /> {t('lde.delete')}
            </Button>
          </div>
        </Section>
      )}
    </div>
  )
}

/** Normal-incidence reflectance of the selected coating on the denser adjacent medium (or on its own mirror substrate). */
function CoatingPreview({ name, definition, mirror, incident, substrate, wavelength, description }: { name: string; definition?: CoatingDefinition; mirror: boolean; incident: number; substrate: number; wavelength?: number; description?: string }) {
  const customMaterials = useProjectStore((s) => s.project.custom_materials)
  const [curve, setCurve] = useState<CoatingCurve | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const defKey = definition ? JSON.stringify(definition) : ''
  useEffect(() => {
    let alive = true
    const lo = Math.min(0.4, (wavelength ?? 0.55) * 0.8)
    const hi = Math.max(0.8, (wavelength ?? 0.55) * 1.2)
    if (mirror && (!definition || definition.substrate_index === null)) {
      setCurve(null)
      setErr(definition ? 'This coating has no mirror substrate (n, k); the mirror stays ideal.' : 'Built-in coatings have no mirror substrate; the mirror stays ideal.')
      return
    }
    api
      .coatingCurve({ name, definition, substrate_index: substrate, lambda_min: lo, lambda_max: hi, mirror, incident_index: incident, custom_materials: customMaterials })
      .then((c) => alive && (setCurve(c), setErr(null)))
      .catch((e) => alive && setErr((e as Error).message))
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, defKey, mirror, incident, substrate, wavelength, customMaterials])
  if (err) return <div className="px-3 py-1 text-small text-danger">{err}</div>
  if (!curve) return null
  let atWl: number | null = null
  if (wavelength !== undefined) {
    const k = curve.wavelength_um.reduce((b, x, j) => (Math.abs(x - wavelength) < Math.abs(curve.wavelength_um[b] - wavelength) ? j : b), 0)
    atWl = curve.reflectance[k]
  }
  return (
    <>
      {description && <div className="px-3 pb-1 text-caption leading-snug text-faint">{description}</div>}
      <Field label="R (0°, primary λ)">
        <span className="num text-muted">{atWl === null ? '—' : `${fmt(atWl * 100, 4)} %`}</span>
      </Field>
      <div className="h-32 px-2">
          <Plot
            data={[{ x: curve.wavelength_um.map((x) => x * 1000), y: curve.reflectance.map((r) => r * 100), type: 'scatter', mode: 'lines', name: 'R', hovertemplate: '%{x:.0f} nm: %{y:.3f} %<extra></extra>' }]}
            layout={{ margin: { l: 36, r: 6, t: 6, b: 26 }, showlegend: false, xaxis: { title: { text: 'λ (nm)' } }, yaxis: { title: { text: 'R (%)' }, rangemode: 'tozero' } }}
          />
      </div>
      <div className="px-3 pb-2 text-caption text-faint">
        {curve.mirror ? `Mirror substrate N = ${fmt(curve.substrate_index, 5)} − ${fmt(curve.substrate_extinction, 5)}i, incident medium n = ${fmt(incident, 6)}` : `Substrate n = ${fmt(substrate, 6)} (denser adjacent medium, primary λ)`}, normal incidence, unpolarised.
      </div>
    </>
  )
}

const THICKNESS_SOLVES: SolveType[] = ['marginal_height', 'chief_height', 'pickup']
const CURVATURE_SOLVES: SolveType[] = ['marginal_angle', 'chief_angle', 'f_number', 'pickup']

function SolveEditor({ i, kind }: { i: number; kind: 'thickness' | 'curvature' }) {
  const t = useT()
  const system = useProjectStore((s) => s.project.system)
  const setSolve = useProjectStore((s) => s.setSolve)
  const s = system.surfaces[i]
  const sv = kind === 'thickness' ? s.thickness_solve : s.curvature_solve
  const n = system.surfaces.length
  const types = kind === 'thickness' ? THICKNESS_SOLVES : CURVATURE_SOLVES
  const sources = system.surfaces
    .map((x, k) => ({ x, k }))
    .filter(({ x, k }) => k !== i && k > 0 && k < n - 1 && (kind === 'thickness' ? x.thickness !== null : x.type !== 'coordinate_break'))
    .map(({ x, k }) => ({ value: x.id, label: `${k}: ${surfaceTitle(x, k, n)}` }))
  const make = (type: SolveType): Solve => ({
    type,
    target: type === 'f_number' ? 5 : 0,
    surface_id: type === 'pickup' ? (sources[0]?.value ?? null) : null,
    scale: type === 'pickup' && kind === 'curvature' ? -1 : 1,
    offset: 0,
    zone: 1,
  })
  const patch = (p: Partial<Solve>) => sv && setSolve(i, kind, { ...sv, ...p })
  const label = kind === 'thickness' ? t('lde.thickness') : t('lde.radius')
  return (
    <>
      <Field label={`${label} ${t('ins.solve')}`} hint={sv ? describeSolve(sv, kind, system) : 'Fixed value (no solve)'}>
        <Select
          className="w-full"
          value={sv?.type ?? ''}
          options={[{ value: '', label: t('ins.noSolve') }, ...types.map((v) => ({ value: v, label: SOLVE_LABEL[v] }))]}
          onChange={(v) => setSolve(i, kind, v ? make(v as SolveType) : null)}
        />
      </Field>
      {sv && sv.type !== 'pickup' && (
        <Field label={sv.type === 'f_number' ? 'F/#' : sv.type.endsWith('height') ? `${t('ins.target')} (mm)` : `${t('ins.target')} (slope)`}>
          <NumberField className="w-full" value={sv.target} min={sv.type === 'f_number' ? 1e-6 : undefined} onCommit={(v) => patch({ target: v ?? 0 })} />
        </Field>
      )}
      {sv?.type === 'marginal_height' && (
        <Field label={t('ins.zone')} hint="Pupil zone of the marginal ray (1 = full aperture). Paraxial rays scale linearly, so the zone only matters for a non-zero target height.">
          <NumberField className="w-full" value={sv.zone} min={1e-6} max={1} onCommit={(v) => patch({ zone: v ?? 1 })} />
        </Field>
      )}
      {sv?.type === 'pickup' && (
        <>
          <Field label={t('ins.source')}>
            <Select className="w-full" value={sv.surface_id ?? ''} options={sources} onChange={(v) => patch({ surface_id: v })} />
          </Field>
          <Field label={t('ins.scale')}>
            <NumberField className="w-full" value={sv.scale} onCommit={(v) => patch({ scale: v ?? 1 })} />
          </Field>
          {kind === 'thickness' && (
            <Field label={`${t('ins.offset')} (mm)`}>
              <NumberField className="w-full" value={sv.offset} units={LENGTH_TO_MM} onCommit={(v) => patch({ offset: v ?? 0 })} />
            </Field>
          )}
        </>
      )}
    </>
  )
}

/** Common names of the first Fringe Zernike terms. */
const ZERNIKE_NAMES = ['piston', 'tilt x', 'tilt y', 'defocus', 'astigmatism 0°', 'astigmatism 45°', 'coma x', 'coma y', 'spherical', 'trefoil x', 'trefoil y', 'sec. astigmatism 0°', 'sec. astigmatism 45°', 'sec. coma x', 'sec. coma y', 'sec. spherical']

function ZernikeSection({ i }: { i: number }) {
  const t = useT()
  const s = useProjectStore((st) => st.project.system.surfaces[i])
  const update = useProjectStore((st) => st.updateSurface)
  const u = (patch: Partial<Surface>, label: string) => update(i, patch, label)
  const zc = s.zernike_coefficients
  return (
    <Section
      title={t('ins.zernike')}
      right={
        <Button size="sm" variant="ghost" onClick={() => u({ zernike_coefficients: [...zc, 0] }, 'Add Zernike term')} disabled={zc.length >= 37}>
          <Plus size={12} />
        </Button>
      }
    >
      <Field label={`${t('ins.zernNorm')} (mm)`} hint="Normalisation radius R: the terms use ρ = r/R. Keep R ≥ the clear semi-diameter (beyond R the polynomial is extrapolated).">
        <NumberField className="w-full" value={s.zernike_norm_radius} min={1e-6} units={LENGTH_TO_MM} onCommit={(v) => u({ zernike_norm_radius: v ?? 10 }, `Surface ${i} Zernike radius`)} />
      </Field>
      {zc.length === 0 && <div className="px-3 pb-1 text-small text-faint">{t('ins.zernHelp')}</div>}
      {zc.map((a, k) => (
        <Field key={k} label={`Z${k + 1} (mm)`} hint={`Fringe Z${k + 1}${ZERNIKE_NAMES[k] ? ` (${ZERNIKE_NAMES[k]})` : ''}, peak-normalised; sag adds A·[Z(x/R, y/R) − Z(0, 0)].${k === 0 ? ' Piston has no effect (the vertex stays at the origin).' : ''}${k === 1 || k === 2 ? ' Tilt terms tilt the vertex: paraxial data then assume an untilted vertex.' : ''}`}>
          <NumberField className="w-full" value={a} format={(v) => (v === null ? '' : v === 0 ? '0' : v.toExponential(6))} onCommit={(v) => u({ zernike_coefficients: zc.map((x, j) => (j === k ? (v ?? 0) : x)) }, `Z${k + 1}`)} />
          <IconButton size="sm" tone="danger" title={`Remove Z${k + 1}`} onClick={() => u({ zernike_coefficients: zc.filter((_, j) => j !== k) }, 'Remove Zernike term')}>
            <Trash2 size={12} />
          </IconButton>
        </Field>
      ))}
      <div className="px-3 pb-2 text-caption leading-snug text-faint">{t('ins.zernNote')}</div>
    </Section>
  )
}

/** Mechanics of a lens surface: where it ends, its chamfer, the element's rim, edge and mass, its drawing. */
function MechanicsSection({ i }: { i: number }) {
  const t = useT()
  const project = useProjectStore((s) => s.project)
  const update = useProjectStore((s) => s.updateSurface)
  const s = project.system.surfaces[i]
  const els = useAnalysis<ElementsResult>('elements', { tolerancing: project.tolerancing }).data?.elements ?? []
  const el = els.find((e) => e.surface_ids.includes(s.id))
  return (
    <Section
      title={t('ins.mechanics')}
      right={
        <Button variant="link" title={t('dwd.openHint')} onClick={() => useUiStore.getState().openDialog('elementDrawing', { surfaceId: s.id })}>
          {t('dwd.open')}
        </Button>
      }
    >
      <Field label={t('ins.mechSd')} hint={t('ins.mechSdHint')}>
        <NumberField className="w-full" optional ariaLabel={t('ins.mechSd')} value={s.mech_semi_diameter ?? null} placeholder={t('ins.mechSdClear')} min={0} units={LENGTH_TO_MM} onCommit={(v) => update(i, { mech_semi_diameter: v }, 'Mechanical semi-diameter')} />
      </Field>
      <Field label={t('ins.chamfer')} hint={t('ins.chamferHint')}>
        <NumberField className="w-full" ariaLabel={t('ins.chamfer')} value={s.chamfer ?? 0} min={0} max={50} units={LENGTH_TO_MM} onCommit={(v) => update(i, { chamfer: v ?? 0 }, 'Chamfer')} />
      </Field>
      {el && (
        <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 num text-small text-muted">
          <span>{t('ins.rim')}</span>
          <span className="text-fg">{fmt(2 * el.rim_radius_mm, 5)} mm</span>
          <span>{t('ins.edge')}</span>
          <span className="text-fg">{fmt(el.edge_thickness_mm, 5)} mm</span>
          <span>{t('ins.mass')}</span>
          <span className="text-fg">{el.mass_g === null ? '—' : `${fmt(el.mass_g, 4)} g`}</span>
        </div>
      )}
      {el?.notes.map((nt) => (
        <div key={nt} className="text-small text-warn">
          {nt}
        </div>
      ))}
    </Section>
  )
}

/** Odd-asphere coefficients beta_1.. on r^1, r^2, ... (engine: surfaces.OddShape). */
function OddSection({ i }: { i: number }) {
  const t = useT()
  const s = useProjectStore((st) => st.project.system.surfaces[i])
  const update = useProjectStore((st) => st.updateSurface)
  const b = s.odd_coefficients ?? []
  const set = (next: number[], label: string) => update(i, { odd_coefficients: next }, label)
  const sup = (n: number) => String(n).replace(/\d/g, (d) => '⁰¹²³⁴⁵⁶⁷⁸⁹'[Number(d)])
  return (
    <Section
      title={t('ins.oddTerms')}
      right={
        <Button size="sm" variant="ghost" aria-label={t('ins.addTerm')} title={t('ins.addTerm')} onClick={() => set([...b, 0], 'Add odd-asphere term')} disabled={b.length >= 16}>
          <Plus size={12} />
        </Button>
      }
    >
      {b.length === 0 && <div className="px-3 pb-1 text-small text-faint">{t('ins.oddHelp')}</div>}
      {b.map((v, k) => (
        <Field key={k} label={`β${k + 1} · r${k === 0 ? '' : sup(k + 1)}`} hint={t('ins.oddTermHint', { i: k + 1, u: k === 0 ? '' : `mm${sup(-k).replace('-', '⁻')}` })}>
          <NumberField className="w-full" ariaLabel={`β${k + 1}`} value={v} format={(x) => (x === null ? '' : x === 0 ? '0' : x.toExponential(6))} onCommit={(x) => set(b.map((y, j) => (j === k ? (x ?? 0) : y)), `β${k + 1}`)} />
          <IconButton size="sm" tone="danger" title={t('ins.removeTerm', { term: `β${k + 1}` })} disabled={k !== b.length - 1} onClick={() => set(b.slice(0, -1), 'Remove odd-asphere term')}>
            <Trash2 size={12} />
          </IconButton>
        </Field>
      ))}
    </Section>
  )
}

/** Uniaxial crystal after this surface: optic axis in the surface frame and the traced wave (engine: birefringence.py). */
function CrystalSection({ i }: { i: number }) {
  const t = useT()
  const s = useProjectStore((st) => st.project.system.surfaces[i])
  const update = useProjectStore((st) => st.updateSurface)
  const axis = s.crystal_axis ?? [0, 0, 1]
  const setAxis = (k: number, v: number | null) => {
    const a = [...axis] as [number, number, number]
    a[k] = v ?? 0
    if (Math.hypot(...a) < 1e-12) return
    update(i, { crystal_axis: a }, 'Crystal axis')
  }
  return (
    <Section title={t('ins.crystal')}>
      <Field label={t('ins.crystalAxis')} hint={t('ins.crystalAxisHint')}>
        <div className="grid w-full grid-cols-3 gap-1">
          {(['x', 'y', 'z'] as const).map((c, k) => (
            <NumberField key={c} className="w-full" ariaLabel={`${t('ins.crystalAxis')} ${c}`} value={axis[k]} onCommit={(v) => setAxis(k, v)} />
          ))}
        </div>
      </Field>
      <Field label={t('ins.wave')} hint={t('ins.waveHint')}>
        <Select
          className="w-full"
          ariaLabel={t('ins.wave')}
          value={s.crystal_mode ?? 'ordinary'}
          options={[
            { value: 'ordinary', label: t('ins.wave.ordinary') },
            { value: 'extraordinary', label: t('ins.wave.extraordinary') },
          ]}
          onChange={(v) => update(i, { crystal_mode: v as 'ordinary' | 'extraordinary' }, 'Crystal wave')}
        />
      </Field>
    </Section>
  )
}

/** Ideal polariser or retarder at this surface (polarisation analyses; engine: polarization.py). */
function PolarizingSection({ i }: { i: number }) {
  const t = useT()
  const s = useProjectStore((st) => st.project.system.surfaces[i])
  const update = useProjectStore((st) => st.updateSurface)
  const el = s.jones ?? null
  return (
    <Section title={t('ins.polarizing')} defaultOpen={!!el}>
      <Field label={t('ins.polElement')} hint={t('ins.polElementHint')}>
        <Select
          className="w-full"
          ariaLabel={t('ins.polElement')}
          value={el?.kind ?? 'none'}
          options={[
            { value: 'none', label: t('ins.pol.none') },
            { value: 'polarizer', label: t('ins.pol.polarizer') },
            { value: 'retarder', label: t('ins.pol.retarder') },
          ]}
          onChange={(v) => update(i, { jones: v === 'none' ? null : { kind: v as 'polarizer' | 'retarder', angle_deg: el?.angle_deg ?? 0, retardance_waves: el?.retardance_waves ?? 0.25 } }, 'Polarising element')}
        />
      </Field>
      {el && (
        <Field label={el.kind === 'polarizer' ? t('ins.polAxis') : t('ins.fastAxis')} hint={t('ins.polAxisHint')}>
          <NumberField className="w-full" ariaLabel={t('ins.polAxis')} value={el.angle_deg} min={-360} max={360} onCommit={(v) => update(i, { jones: { ...el, angle_deg: v ?? 0 } }, 'Polarising element axis')} />
        </Field>
      )}
      {el?.kind === 'retarder' && (
        <Field label={t('ins.retardance')} hint={t('ins.retardanceHint')}>
          <NumberField className="w-full" ariaLabel={t('ins.retardance')} value={el.retardance_waves} min={-10} max={10} onCommit={(v) => update(i, { jones: { ...el, retardance_waves: v ?? 0.25 } }, 'Retardance')} />
        </Field>
      )}
      {el && <div className="px-3 text-caption text-faint">{t('ins.polNote')}</div>}
    </Section>
  )
}

/** Forbes Q-type asphere terms a_0.. with the normalisation radius (engine: qpoly.py). */
function QSection({ i }: { i: number }) {
  const t = useT()
  const s = useProjectStore((st) => st.project.system.surfaces[i])
  const update = useProjectStore((st) => st.updateSurface)
  const u = (patch: Partial<Surface>, label: string) => update(i, patch, label)
  const qc = s.q_coefficients ?? []
  const kind = s.type === 'qcon' ? 'Qcon' : 'Qbfs'
  return (
    <Section
      title={t('ins.qterms', { kind })}
      right={
        <Button size="sm" variant="ghost" aria-label={t('ins.addTerm')} title={t('ins.addTerm')} onClick={() => u({ q_coefficients: [...qc, 0] }, 'Add Q term')} disabled={qc.length >= 30}>
          <Plus size={12} />
        </Button>
      }
    >
      <Field label={t('ins.qNorm')} hint={t('ins.qNormHint')}>
        <NumberField className="w-full" ariaLabel={t('ins.qNorm')} value={s.q_norm_radius ?? 10} min={1e-6} units={LENGTH_TO_MM} onCommit={(v) => u({ q_norm_radius: v ?? 10 }, `Surface ${i} Q radius`)} />
      </Field>
      {qc.length === 0 && <div className="px-3 pb-1 text-small text-faint">{t(s.type === 'qcon' ? 'ins.qconHelp' : 'ins.qbfsHelp')}</div>}
      {qc.map((a, k) => (
        <Field key={k} label={`a${k} (mm)`} hint={t(s.type === 'qcon' ? 'ins.qconTermHint' : 'ins.qbfsTermHint', { m: k })}>
          <NumberField className="w-full" ariaLabel={`a${k}`} value={a} format={(v) => (v === null ? '' : v === 0 ? '0' : v.toExponential(6))} onCommit={(v) => u({ q_coefficients: qc.map((x, j) => (j === k ? (v ?? 0) : x)) }, `a${k}`)} />
          <IconButton size="sm" tone="danger" title={t('ins.removeTerm', { term: `a${k}` })} onClick={() => u({ q_coefficients: qc.filter((_, j) => j !== k) }, 'Remove Q term')}>
            <Trash2 size={12} />
          </IconButton>
        </Field>
      ))}
      <div className="px-3 pb-2 text-caption leading-snug text-faint">{t('ins.qNote')}</div>
    </Section>
  )
}

/** XY-polynomial freeform terms (x, y, x², xy, y², …) with the normalisation radius. */
function XYSection({ i }: { i: number }) {
  const t = useT()
  const s = useProjectStore((st) => st.project.system.surfaces[i])
  const update = useProjectStore((st) => st.updateSurface)
  const u = (patch: Partial<Surface>, label: string) => update(i, patch, label)
  const xc = s.xy_coefficients ?? []
  return (
    <Section
      title={t('ins.xyterms')}
      right={
        <Button size="sm" variant="ghost" aria-label={t('ins.addTerm')} title={t('ins.addTerm')} onClick={() => u({ xy_coefficients: [...xc, 0] }, 'Add XY term')} disabled={xc.length >= 65}>
          <Plus size={12} />
        </Button>
      }
    >
      <Field label={t('ins.xyNorm')} hint={t('ins.xyNormHint')}>
        <NumberField className="w-full" ariaLabel={t('ins.xyNorm')} value={s.xy_norm_radius ?? 10} min={1e-6} units={LENGTH_TO_MM} onCommit={(v) => u({ xy_norm_radius: v ?? 10 }, `Surface ${i} XY radius`)} />
      </Field>
      {xc.length === 0 && <div className="px-3 pb-1 text-small text-faint">{t('ins.xyHelp')}</div>}
      {xc.map((a, k) => (
        <Field key={k} label={`${xyTermName(k + 1)} (mm)`} hint={t('ins.xyTermHint', { term: xyTermName(k + 1) })}>
          <NumberField className="w-full" ariaLabel={xyTermName(k + 1)} value={a} format={(v) => (v === null ? '' : v === 0 ? '0' : v.toExponential(6))} onCommit={(v) => u({ xy_coefficients: xc.map((x, j) => (j === k ? (v ?? 0) : x)) }, xyTermName(k + 1))} />
          <IconButton size="sm" tone="danger" title={t('ins.removeTerm', { term: xyTermName(k + 1) })} onClick={() => u({ xy_coefficients: xc.filter((_, j) => j !== k) }, 'Remove XY term')}>
            <Trash2 size={12} />
          </IconButton>
        </Field>
      ))}
      <div className="px-3 pb-2 text-caption leading-snug text-faint">{t('ins.xyNote')}</div>
    </Section>
  )
}

/** Rewrite an even asphere as Qcon (exact) or Qbfs (fitted) over its clear aperture, as one undoable edit. */
function ConvertToQ({ i }: { i: number }) {
  const t = useT()
  const project = useProjectStore((st) => st.project)
  const update = useProjectStore((st) => st.updateSurface)
  const toast = useUiStore((st) => st.toast)
  const online = useEngineStore((st) => st.backend === 'online')
  const go = async (to: 'qcon' | 'qbfs') => {
    try {
      const snap = designSnapshot()
      const r = await api.convertQ({ system: project.system, custom_materials: project.custom_materials, surface: i, to })
      if (!sameDesign(snap)) {
        toast('warning', t('c.staleDesign'))
        return
      }
      update(i, r.surface, `Convert surface ${i} to ${to === 'qcon' ? 'Qcon' : 'Qbfs'}`)
      toast('success', t('ins.converted', { kind: to === 'qcon' ? 'Qcon' : 'Qbfs', r: fmt(r.norm_radius_mm, 4), res: r.residual_max_mm.toExponential(2) }))
    } catch (e) {
      toast('error', (e as Error).message)
    }
  }
  return (
    <div className="flex flex-wrap items-center gap-2 px-3 py-1">
      <span className="text-small text-muted">{t('ins.convertTo')}</span>
      <Button variant="link" disabled={!online} title={t('ins.toQconHint')} onClick={() => void go('qcon')}>
        Qcon
      </Button>
      <Button variant="link" disabled={!online} title={t('ins.toQbfsHint')} onClick={() => void go('qbfs')}>
        Qbfs
      </Button>
    </div>
  )
}

