import type { Operand, OperandType } from '../../lib/types'

export const OPERAND_INFO: Record<OperandType, { label: string; unit: string; desc: string; needsSurface?: boolean; needsDetector?: boolean; usesField?: boolean; usesWavelength?: boolean; needsFrequency?: boolean }> = {
  rms_spot: { label: 'RMS spot radius', unit: 'mm', desc: 'Real-ray RMS spot radius integrated over the pupil with Gaussian quadrature (rings x arms), weighted by field and wavelength weights. Target 0 minimises; a target > 0 asks for a spot of that RMS radius.', usesField: true, usesWavelength: true },
  throughput: { label: 'Energy throughput', unit: '', desc: 'Fraction of entrance-pupil power reaching the image: vignetting, Fresnel / coating surface losses and bulk absorption (target 1 maximises).', usesField: true, usesWavelength: true },
  rms_wavefront: { label: 'RMS wavefront error', unit: 'waves', desc: 'Pupil-area RMS of the real-ray OPD in waves: one wavelength, or all (weighted) against the primary chief ray so that lateral and axial colour count; piston removed, and tilt with the centroid reference.', usesField: true, usesWavelength: true },
  mtf: { label: 'Diffraction MTF at frequency', unit: '', desc: 'FFT-based diffraction MTF (polychromatic) at the given spatial frequency for one field or the field-weighted mean of all; tangential, sagittal or their average. Target 1 with a weight maximises contrast.', usesField: true, needsFrequency: true },
  efl: { label: 'Effective focal length', unit: 'mm', desc: 'Paraxial EFL at the chosen (or primary) wavelength.', usesWavelength: true },
  bfl: { label: 'Back focal length', unit: 'mm', desc: 'Paraxial distance from the last surface to the rear focus.', usesWavelength: true },
  fnum: { label: 'Image-space F/#', unit: '', desc: 'EFL / EPD (paraxial).', usesWavelength: true },
  working_fnum: { label: 'Working F/#', unit: '', desc: '1 / (2 n′ |u′|) of the paraxial marginal ray.', usesWavelength: true },
  total_track: { label: 'Total track', unit: 'mm', desc: 'Sum of thicknesses from surface 1 to the image.' },
  magnification: { label: 'Paraxial magnification', unit: '', desc: 'Finite conjugates only.', usesWavelength: true },
  axial_color: { label: 'Axial colour (F−C)', unit: 'mm', desc: 'Difference of paraxial image distances between the F and C lines.' },
  distortion: { label: 'Distortion at max field', unit: '%', desc: 'Real chief ray vs paraxial height on the image surface.' },
  max_distortion: { label: 'Maximum distortion', unit: '%', desc: 'Penalises |distortion| at the largest field above the target (one-sided).' },
  max_lateral_color: { label: 'Maximum lateral colour', unit: 'µm', desc: 'Penalises |lateral colour| (shortest minus longest wavelength chief ray) above the target (one-sided).', usesField: true },
  min_relative_illumination: { label: 'Minimum relative illumination', unit: '', desc: 'Penalises relative illumination below the target (fraction of the axis, one-sided).', usesField: true },
  max_cra: { label: 'Maximum chief-ray angle', unit: '°', desc: 'Penalises the chief-ray angle on the image above the target (one-sided).', usesField: true },
  min_thickness: { label: 'Minimum thickness', unit: 'mm', desc: 'Penalises thickness below the target (one-sided).', needsSurface: true },
  max_thickness: { label: 'Maximum thickness', unit: 'mm', desc: 'Penalises thickness above the target (one-sided).', needsSurface: true },
  min_edge_thickness: { label: 'Minimum edge thickness', unit: 'mm', desc: 'Edge thickness between this and the next surface at the larger semi-diameter (one-sided).', needsSurface: true },
  max_total_track: { label: 'Maximum total track', unit: 'mm', desc: 'Penalises total track above the target (one-sided).' },
  detector_size: { label: 'Beam diameter on detector (D4σ)', unit: 'mm', desc: 'Second-moment beam diameter D4σ = 4σ in the plane of a detector (the 1/e² diameter of a Gaussian beam, the diameter of a uniform disc), from the project light sources by the direct-path trace (seeded, through the lens surfaces; no ghosts). x, y or their average. Targets accept units, e.g. 150 um.', needsDetector: true },
  detector_power: { label: 'Power on detector', unit: '', desc: 'Fraction of the emitted source power the detector accepts (direct path: Fresnel or coating losses, absorption, apertures, acceptance angle). Target 1 maximises; it changes in steps of about 1/rays, so combine it with the beam diameter or use the global algorithm.', needsDetector: true },
  surface_reflectance: { label: 'Surface reflectance', unit: '', desc: 'Unpolarised reflectance of the surface (coating or bare Fresnel; mirrors: their coating) averaged over the rays that reach it (pupil quadrature, all or one field / wavelength). Target 0 suppresses ghosts; use coating variables to optimise the coating in the system.', needsSurface: true, usesField: true, usesWavelength: true },
}

export function defaultOperand(type: OperandType = 'rms_spot'): Operand {
  return { type, target: 0, weight: 1, field: null, wavelength: null, surface_id: null, rings: 4, reference: 'centroid', frequency: null, direction: 'average', enabled: true }
}
