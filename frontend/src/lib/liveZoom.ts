// Live image "1 pixel = 1 sensor pixel": the display zoom at which the rendered image's pixels have the sensor's pitch.
// Display geometry only (the engine renders the region it is asked for; no optics here).

/** Common phone and machine-vision pixel pitches (µm). */
export const PITCHES = [1.0, 1.12, 1.4, 1.75, 2.2, 3.45, 5.5]

/** Zoom so that `widthPx` image pixels across the shown region are `pitchUm` each: the frame width over the region
 * width, clamped to the engine's 1…256 and rounded to four significant digits. A pitch coarser than the fitted frame's
 * own pixel gives the whole frame (1). */
export function sensorZoom(frameWidthMm: number, widthPx: number, pitchUm: number): number {
  if (!(frameWidthMm > 0 && widthPx > 0 && pitchUm > 0)) return 1
  const z = (frameWidthMm * 1000) / (widthPx * pitchUm)
  return Math.min(256, Math.max(1, +z.toPrecision(4)))
}
