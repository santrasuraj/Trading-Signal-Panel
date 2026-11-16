// Desktop notifications for fired alerts and FYERS order updates: through the service worker when the app is installed
// or open (public/sw.js shows it even with the window in the background, and a click opens the right page), else the
// page's own Notification. Nothing happens until the user allows notifications (askPermission).

export type NotifyState = 'granted' | 'denied' | 'default' | 'unsupported'

export function notifyState(): NotifyState {
  return typeof Notification === 'undefined' ? 'unsupported' : (Notification.permission as NotifyState)
}

export async function askPermission(): Promise<NotifyState> {
  if (typeof Notification === 'undefined') return 'unsupported'
  try { return (await Notification.requestPermission()) as NotifyState } catch { return notifyState() }
}

export async function notify(title: string, body: string, path = '/', tag?: string): Promise<void> {
  if (notifyState() !== 'granted') return
  try {
    const reg = typeof navigator !== 'undefined' && 'serviceWorker' in navigator ? await navigator.serviceWorker.getRegistration() : undefined
    if (reg) { await reg.showNotification(title, { body, tag, icon: '/icon-192.png', data: { path } }); return }
    new Notification(title, { body, tag, icon: '/icon-192.png' })
  } catch { /* notifications unavailable */ }
}

/** Register the service worker (production build only: Vite's dev server serves sources, not /assets). */
export function registerServiceWorker(): void {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator) || !import.meta.env.PROD) return
  window.addEventListener('load', () => { void navigator.serviceWorker.register('/sw.js').catch(() => undefined) })
}
