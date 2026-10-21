import { useCallback, useEffect, useState } from 'react'

const PREFIX = '#/c/'

/** The open conversation is part of the page address (#/c/<id>), so reload and back/forward work. */
function read(): string | null {
  const hash = window.location.hash
  if (!hash.startsWith(PREFIX)) return null
  const id = decodeURIComponent(hash.slice(PREFIX.length))
  return id === '' ? null : id
}

export function useRoute(): [string | null, (id: string | null) => void] {
  const [id, setId] = useState(read)
  useEffect(() => {
    const onChange = () => setId(read())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  const open = useCallback((next: string | null) => {
    const hash = next === null ? '#/' : `${PREFIX}${encodeURIComponent(next)}`
    if (window.location.hash !== hash) window.location.hash = hash
    setId(next)
  }, [])
  return [id, open]
}
