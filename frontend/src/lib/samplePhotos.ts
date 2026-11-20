// Built-in photos for the live image (frontend/public/samples, credits in CREDITS.md there). They travel to the engine
// like a user's photo; settings name them by id.
import { photoFromFile } from './photo'
import type { PhotoData } from './types'

export const SAMPLE_PHOTOS = {
  eiffel: { file: 'samples/eiffel-tower.jpg', credit: 'Jebulon, CC0 (Wikimedia Commons)' },
  pillars: { file: 'samples/pillars-of-creation.jpg', credit: 'NASA, Jeff Hester and Paul Scowen (Arizona State University), Hubble 1995' },
} as const

export type SamplePhotoId = keyof typeof SAMPLE_PHOTOS

export const isSamplePhoto = (s: unknown): s is SamplePhotoId => typeof s === 'string' && Object.prototype.hasOwnProperty.call(SAMPLE_PHOTOS, s)

const cache = new Map<SamplePhotoId, Promise<PhotoData>>()

/** The sample photo as sRGB bytes (fetched and decoded once per session). */
export function loadSamplePhoto(id: SamplePhotoId): Promise<PhotoData> {
  let p = cache.get(id)
  if (!p) {
    p = fetch(import.meta.env.BASE_URL + SAMPLE_PHOTOS[id].file)
      .then((r) => {
        if (!r.ok) throw new Error(`Sample photo ${SAMPLE_PHOTOS[id].file}: HTTP ${r.status}`)
        return r.blob()
      })
      .then((b) => photoFromFile(b))
    p.catch(() => cache.delete(id))
    cache.set(id, p)
  }
  return p
}
