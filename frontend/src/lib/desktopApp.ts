/** The desktop application (backend opticore/desktop.py) ends when its last window has been closed. The page tells
 * the engine it is open with a heartbeat, and says goodbye when it is closed; a reload sends a new heartbeat in time.
 * Outside the desktop application (development, tests) the endpoint does not exist and nothing more is sent. */
const HEARTBEAT_MS = 10_000

export function startDesktopHeartbeat(): void {
  const beat = () => fetch('/api/v1/app/heartbeat', { method: 'POST' }).then((r) => r.ok)
  beat()
    .then((desktop) => {
      if (!desktop) return
      window.setInterval(() => void beat().catch(() => undefined), HEARTBEAT_MS)
      window.addEventListener('pagehide', () => navigator.sendBeacon('/api/v1/app/bye'))
    })
    .catch(() => undefined)
}
