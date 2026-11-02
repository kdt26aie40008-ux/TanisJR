import { useEffect, useState } from 'react'

function current(): string {
  return window.location.hash.replace(/^#\/?/, '') || 'chat'
}

/** 依存を増やさないための最小限のハッシュルーティング。 */
export function useHashRoute(): [string, (route: string) => void] {
  const [route, setRoute] = useState(current)
  useEffect(() => {
    const onChange = () => setRoute(current())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return [route, (next: string) => (window.location.hash = `/${next}`)]
}
