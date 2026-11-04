/** アプリとしてインストールする（PWA）ための、ブラウザーのインストール案内の受け取り口。 */

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

let deferred: InstallPromptEvent | null = null
const listeners = new Set<() => void>()

/** ページ読み込み直後に一度だけ呼ぶ（案内イベントは早い段階で1回しか来ないため） */
export function captureInstallPrompt(): void {
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault()
    deferred = e as InstallPromptEvent
    listeners.forEach((l) => l())
  })
  window.addEventListener('appinstalled', () => {
    deferred = null
    listeners.forEach((l) => l())
  })
}

export function canInstall(): boolean {
  return deferred !== null
}

export function isStandalone(): boolean {
  return window.matchMedia?.('(display-mode: standalone)').matches ?? false
}

export async function promptInstall(): Promise<boolean> {
  if (!deferred) return false
  const event = deferred
  deferred = null
  await event.prompt()
  const { outcome } = await event.userChoice
  listeners.forEach((l) => l())
  return outcome === 'accepted'
}

export function onInstallChange(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** アプリの画面（HTML・JS・CSS）だけをキャッシュするサービスワーカーを登録する */
export function registerServiceWorker(): void {
  if (!('serviceWorker' in navigator) || import.meta.env.DEV) return
  navigator.serviceWorker.register('/sw.js').catch(() => undefined)
}
