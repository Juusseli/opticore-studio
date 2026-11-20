import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NumberField } from '../components/common/ui'
import { useEngineStore } from '../store/engineStore'
import { usePhotoStore } from '../store/photoStore'
import { useProjectStore } from '../store/projectStore'
import { api } from './api'
import { base64ToBytes, bytesToBase64, fitSize, photoId, rgbaToRgb, rgbToRgba } from './photo'
import { blankProject } from './project'
import { isSamplePhoto } from './samplePhotos'

// the built-in photos are fetched and decoded by the browser; here a fixed 2 x 2 image stands in for them
vi.mock('./samplePhotos', async (orig) => ({ ...(await orig<typeof import('./samplePhotos')>()), loadSamplePhoto: vi.fn(async () => ({ width: 2, height: 2, data: 'AAAAAAAAAAAAAAAA' })) }))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const st = () => useProjectStore.getState()

describe('photo helpers', () => {
  it('round-trips bytes through base64 and RGB through RGBA', () => {
    const u8 = Uint8Array.from({ length: 100000 }, (_, i) => (i * 7) % 256)
    expect(base64ToBytes(bytesToBase64(u8))).toEqual(u8)
    const rgb = Uint8Array.from([255, 0, 0, 0, 255, 0, 0, 0, 255, 9, 8, 7])
    const rgba = rgbToRgba(rgb, 2, 2)
    expect([...rgba.slice(0, 8)]).toEqual([255, 0, 0, 255, 0, 255, 0, 255])
    expect(rgbaToRgb(rgba, 2, 2)).toEqual(rgb)
  })

  it('scales down to the longest side and names a photo by its content', () => {
    expect(fitSize(4000, 3000)).toEqual([640, 480])
    expect(fitSize(300, 200)).toEqual([300, 200])
    expect(fitSize(1000, 10, 640)).toEqual([640, 6])
    const a = { width: 2, height: 1, data: bytesToBase64(Uint8Array.from([1, 2, 3, 4, 5, 6])) }
    expect(photoId(a)).toBe(photoId({ ...a }))
    expect(photoId(a)).not.toBe(photoId({ ...a, data: bytesToBase64(Uint8Array.from([1, 2, 3, 4, 5, 7])) }))
  })
})

describe('gestures', () => {
  beforeEach(() => st().setProject(blankProject('Gesture')))

  it('make the commits of one drag a single undo step', () => {
    const before = st().project.system.surfaces[1].radius
    const depth = st().past.length
    st().beginGesture()
    for (const r of [101, 102, 105, 110]) st().updateSurface(1, { radius: r }, 'Surface 1 radius')
    st().endGesture()
    expect(st().project.system.surfaces[1].radius).toBe(110)
    expect(st().past.length).toBe(depth + 1)
    st().undo()
    expect(st().project.system.surfaces[1].radius).toBe(before)
    // after the gesture, commits are separate steps again
    st().updateSurface(1, { radius: 90 }, 'a')
    st().updateSurface(1, { radius: 80 }, 'b')
    expect(st().past.length).toBe(depth + 2)
  })
})

describe('NumberField scrubbing', () => {
  let el: HTMLDivElement
  beforeEach(() => {
    st().setProject(blankProject('Scrub'))
    el = document.createElement('div')
    document.body.appendChild(el)
  })
  afterEach(() => el.remove())

  it('drags the value sideways in one undo step; a click without a drag focuses for typing', () => {
    const root = createRoot(el)
    const commit = vi.fn((v: number | null) => st().updateSurface(1, { radius: v }, 'Surface 1 radius'))
    const render = () => root.render(<NumberField ariaLabel="radius" scrub value={st().project.system.surfaces[1].radius} onCommit={commit} />)
    act(render)
    const input = el.querySelector('input')!
    expect(input.className).toContain('cursor-ew-resize')
    const depth = st().past.length
    act(() => {
      input.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0, clientX: 100 }))
      window.dispatchEvent(new MouseEvent('mousemove', { clientX: 153 }))
      window.dispatchEvent(new MouseEvent('mousemove', { clientX: 203 }))
      window.dispatchEvent(new MouseEvent('mouseup', { clientX: 203 }))
    })
    // 0.2 % of 100 per pixel, after a 3 px dead zone: 100 + 100 * 0.2 = 120
    expect(st().project.system.surfaces[1].radius).toBeCloseTo(120, 9)
    expect(st().past.length).toBe(depth + 1)
    act(render)
    act(() => {
      input.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0, clientX: 50 }))
      window.dispatchEvent(new MouseEvent('mouseup', { clientX: 51 }))
    })
    expect(document.activeElement).toBe(input)
    act(() => root.unmount())
  })
})

describe('live image request', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    useEngineStore.setState({ analyses: {} })
  })

  it('sends the photo from the browser store, never through the settings', async () => {
    st().setProject(blankProject('Photo'))
    const photo = { width: 2, height: 2, data: bytesToBase64(new Uint8Array(12)) }
    usePhotoStore.setState({ photo, id: photoId(photo), name: 'x.png', loaded: true })
    const call = vi.spyOn(api, 'liveImage').mockResolvedValue({ quality: 'preview' } as never)
    await useEngineStore.getState().runAnalysis('liveimage', { scene: 'photo', photo_id: photoId(photo), zoom: 1, center: [0, 0], quality: 'preview', width: 64 }, true)
    const body = call.mock.calls[0][0]
    expect(body.photo).toEqual(photo)
    expect('photo_id' in body || 'scene' in body).toBe(false)
    // a test scene is sent by name, without the photo
    await useEngineStore.getState().runAnalysis('liveimage', { scene: 'bars', photo_id: null, zoom: 2, center: [1, 1], quality: 'full', width: 64 }, true)
    expect(call.mock.calls[1][0]).toMatchObject({ scene: 'bars', zoom: 2 })
    expect(call.mock.calls[1][0].photo).toBeUndefined()
    // a photo of another browser is not sent
    usePhotoStore.setState({ photo: null, id: null })
    await useEngineStore.getState().runAnalysis('liveimage', { scene: 'photo', photo_id: 'gone', zoom: 1, center: [0, 0], quality: 'preview', width: 64 }, true)
    expect(call).toHaveBeenCalledTimes(2)
    expect(useEngineStore.getState().analyses.liveimage?.error).toMatch(/not loaded/)
  })

  it('sends a built-in photo as it sends a photo of the user', async () => {
    expect(isSamplePhoto('eiffel') && isSamplePhoto('pillars')).toBe(true)
    expect(isSamplePhoto('siemens') || isSamplePhoto('photo') || isSamplePhoto('toString')).toBe(false)
    st().setProject(blankProject('Sample'))
    const call = vi.spyOn(api, 'liveImage').mockResolvedValue({ quality: 'preview' } as never)
    await useEngineStore.getState().runAnalysis('liveimage', { scene: 'eiffel', photo_id: null, zoom: 1, center: [0, 0], quality: 'preview', width: 64 }, true)
    const body = call.mock.calls[0][0]
    expect(body.photo).toEqual({ width: 2, height: 2, data: 'AAAAAAAAAAAAAAAA' })
    expect('scene' in body).toBe(false)
  })
})
