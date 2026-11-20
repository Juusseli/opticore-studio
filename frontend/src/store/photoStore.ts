import { create } from 'zustand'
import { photoId } from '../lib/photo'
import { storage } from '../lib/storage'
import type { PhotoData } from '../lib/types'

/** The live image's photo, kept in this browser (IndexedDB) and never written into a project. */
interface PhotoState {
  photo: PhotoData | null
  id: string | null
  name: string | null
  loaded: boolean
  load: () => Promise<void>
  set: (photo: PhotoData, name: string) => Promise<void>
  clear: () => Promise<void>
}

export const usePhotoStore = create<PhotoState>((set, get) => ({
  photo: null,
  id: null,
  name: null,
  loaded: false,

  load: async () => {
    if (get().loaded) return
    try {
      const r = await storage.getPhoto()
      if (r && !get().photo) set({ photo: r.photo, id: photoId(r.photo), name: r.name })
    } catch {
      // no IndexedDB (private window): the photo lasts for this session only
    }
    set({ loaded: true })
  },
  set: async (photo, name) => {
    set({ photo, id: photoId(photo), name, loaded: true })
    try {
      await storage.setPhoto(photo, name)
    } catch {
      // kept in memory only
    }
  },
  clear: async () => {
    set({ photo: null, id: null, name: null })
    try {
      await storage.clearPhoto()
    } catch {
      // nothing stored
    }
  },
}))
