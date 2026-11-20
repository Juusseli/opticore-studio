// The live image's photo: decoded and scaled down in the browser, sent to the engine as sRGB bytes. It stays in this
// browser (IndexedDB), never in a project file.
import type { PhotoData } from './types'

/** Longest side of the photo sent to the engine (pixels). */
export const PHOTO_MAX_SIDE = 640

export function bytesToBase64(u8: Uint8Array): string {
  let s = ''
  const CH = 0x8000 // String.fromCharCode takes a bounded argument list
  for (let i = 0; i < u8.length; i += CH) s += String.fromCharCode(...u8.subarray(i, i + CH))
  return btoa(s)
}

export function base64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64)
  const u8 = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i)
  return u8
}

/** RGB bytes (3 per pixel) to opaque RGBA for ImageData. */
export function rgbToRgba(rgb: Uint8Array, width: number, height: number): Uint8ClampedArray<ArrayBuffer> {
  const out = new Uint8ClampedArray(width * height * 4)
  for (let i = 0, j = 0; i < width * height; i++, j += 3) {
    out[4 * i] = rgb[j]
    out[4 * i + 1] = rgb[j + 1]
    out[4 * i + 2] = rgb[j + 2]
    out[4 * i + 3] = 255
  }
  return out
}

/** RGBA (canvas) to RGB bytes. */
export function rgbaToRgb(rgba: ArrayLike<number>, width: number, height: number): Uint8Array {
  const out = new Uint8Array(width * height * 3)
  for (let i = 0, j = 0; i < width * height; i++, j += 3) {
    out[j] = rgba[4 * i]
    out[j + 1] = rgba[4 * i + 1]
    out[j + 2] = rgba[4 * i + 2]
  }
  return out
}

/** Size that fits within maxSide on the longer side, keeping the aspect (never enlarged). */
export function fitSize(width: number, height: number, maxSide = PHOTO_MAX_SIDE): [number, number] {
  const s = Math.min(1, maxSide / Math.max(width, height))
  return [Math.max(2, Math.round(width * s)), Math.max(2, Math.round(height * s))]
}

/** A short content hash (FNV-1a) that names the photo in analysis settings, so a new photo recomputes the image. */
export function photoId(p: PhotoData): string {
  let h = 0x811c9dc5
  for (let i = 0; i < p.data.length; i++) {
    h ^= p.data.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return `${p.width}x${p.height}-${(h >>> 0).toString(16)}`
}

/** Decode an image file (or blob), scale it down and return its sRGB bytes (transparent parts become black). */
export async function photoFromFile(file: Blob, maxSide = PHOTO_MAX_SIDE): Promise<PhotoData> {
  const bmp = await createImageBitmap(file)
  const [w, h] = fitSize(bmp.width, bmp.height, maxSide)
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  const ctx = c.getContext('2d')
  if (!ctx) throw new Error('Canvas 2D is not available')
  ctx.fillStyle = 'black' // transparent parts become black
  ctx.fillRect(0, 0, w, h)
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(bmp, 0, 0, w, h)
  bmp.close()
  return { width: w, height: h, data: bytesToBase64(rgbaToRgb(ctx.getImageData(0, 0, w, h).data, w, h)) }
}
