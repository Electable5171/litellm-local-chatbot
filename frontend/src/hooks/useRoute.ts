import { useCallback, useEffect, useState } from 'react'

const CHAT = '#/c/'
const STATS = '#/stats'

export type View = 'chat' | 'stats'
interface Route {
  /** The open conversation; null is a new chat. */
  id: string | null
  view: View
}

/** The page is part of the address (#/c/<id> or #/stats), so reload and back/forward work. */
function read(): Route {
  const hash = window.location.hash
  if (hash === STATS) return { id: null, view: 'stats' }
  if (!hash.startsWith(CHAT)) return { id: null, view: 'chat' }
  const id = decodeURIComponent(hash.slice(CHAT.length))
  return { id: id === '' ? null : id, view: 'chat' }
}

export function useRoute() {
  const [route, setRoute] = useState(read)
  useEffect(() => {
    const onChange = () => setRoute(read())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  const go = useCallback((hash: string, next: Route) => {
    if (window.location.hash !== hash) window.location.hash = hash
    setRoute(next)
  }, [])
  const open = useCallback(
    (id: string | null) => go(id === null ? '#/' : `${CHAT}${encodeURIComponent(id)}`, { id, view: 'chat' }),
    [go],
  )
  const openStats = useCallback(() => go(STATS, { id: null, view: 'stats' }), [go])
  return { id: route.id, view: route.view, open, openStats }
}
