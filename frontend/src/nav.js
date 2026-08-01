import { useEffect, useState } from 'react'

// Tiny hash router so every view is deep-linkable and back/forward work:
// #/  #/explore  #/analytics  #/runs  #/scores/lstm/2026-07-02
// #/ticker/GAMB  #/day/2026-07-02
export function parseHash() {
  const raw = (window.location.hash || '#/').replace(/^#\/?/, '')
  const [path, queryString = ''] = raw.split('?', 2)
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent)
  return {
    page: parts[0] || 'overview',
    args: parts.slice(1),
    query: Object.fromEntries(new URLSearchParams(queryString)),
  }
}

export function useRoute() {
  const [r, setR] = useState(parseHash)
  useEffect(() => {
    const f = () => setR(parseHash())
    window.addEventListener('hashchange', f)
    return () => window.removeEventListener('hashchange', f)
  }, [])
  return r
}

export const href = (...parts) => '#/' + parts.map(encodeURIComponent).join('/')

export const navigate = (...parts) => { window.location.hash = href(...parts) }
