/** Clears the stored workspace layout (panel sizes, open tabs and views); projects are not affected. */
export function resetStoredLayout() {
  try {
    for (const k of ['opticore.ui', 'opticore.view3d']) localStorage.removeItem(k)
  } catch {
    /* storage may be unavailable */
  }
}
