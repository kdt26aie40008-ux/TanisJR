// アプリの画面（HTML・JS・CSS・フォント・アイコン）だけをキャッシュする。
// /api/ で始まる通信（会話・記憶・設定などの個人データ）はキャッシュしない。
const CACHE = 'twin-shell-v1'

self.addEventListener('install', () => self.skipWaiting())

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return

  // ファイル名にハッシュが付いたもの（/assets/）は内容が変わらないので、キャッシュを優先する
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.match(event.request).then(
        (hit) =>
          hit ||
          fetch(event.request).then((res) => {
            if (res.ok) {
              const copy = res.clone()
              caches.open(CACHE).then((c) => c.put(event.request, copy))
            }
            return res
          }),
      ),
    )
    return
  }

  // 画面本体は常に最新を取りに行き、サーバーが止まっているときだけキャッシュを使う
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          const copy = res.clone()
          caches.open(CACHE).then((c) => c.put('/', copy))
          return res
        })
        .catch(() => caches.match('/')),
    )
  }
})
