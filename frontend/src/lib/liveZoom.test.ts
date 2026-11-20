import { describe, expect, it } from 'vitest'
import { sensorZoom } from './liveZoom'

describe('live image sensor pixels', () => {
  it('zooms so that one image pixel is one sensor pixel', () => {
    // a 5.6 mm wide frame rendered 384 px wide: 14.58 µm pixels; at 1.75 µm the region is 672 µm wide
    expect(sensorZoom(5.6, 384, 1.75)).toBeCloseTo(8.333, 3)
    expect((5.6 * 1000) / sensorZoom(5.6, 384, 1.75) / 384).toBeCloseTo(1.75, 3)
    // coarser than the fitted pixel: the whole frame; finer than the engine allows: its 256x
    expect(sensorZoom(5.6, 384, 20)).toBe(1)
    expect(sensorZoom(5000, 384, 0.1)).toBe(256)
    expect(sensorZoom(0, 384, 1.4)).toBe(1)
  })
})
