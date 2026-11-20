import { useMemo } from 'react'
import { useAllMaterials } from '../../store/catalogStore'
import { useProjectStore } from '../../store/projectStore'

export const RESERVED = ['AIR', 'MIRROR', 'VACUUM']

export function useMaterialNames(): string[] {
  const cat = useAllMaterials()
  const custom = useProjectStore((s) => s.project.custom_materials)
  // metals (n, k for coatings and mirror substrates) are not lens media
  return useMemo(() => [...RESERVED, ...custom.map((c) => c.name.toUpperCase()), ...cat.filter((m) => m.category !== 'metal').map((m) => m.name)].filter((v, i, a) => a.indexOf(v) === i), [cat, custom])
}
