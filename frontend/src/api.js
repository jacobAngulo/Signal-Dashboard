import { token } from './theme.js'

// All requests are relative ("api/...") so the app works at the root of
// :8010 directly and behind the /signal-dashboard/ nginx prefix unchanged.
export async function api(path, params, options = {}) {
  let url = 'api/' + path.replace(/^\//, '')
  if (params) {
    const search = new URLSearchParams()
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === '') continue
      // An array becomes a repeated parameter rather than one comma-joined
      // value: FastAPI reads `?where=a&where=b` as a list, and joining them
      // would hand the server a single clause containing a comma.
      if (Array.isArray(value)) {
        for (const item of value) {
          if (item === undefined || item === null || item === '') continue
          search.append(key, item)
        }
      } else {
        search.append(key, value)
      }
    }
    const qs = search.toString()
    if (qs) url += '?' + qs
  }
  let res
  try {
    res = await fetch(url, options)
  } catch (cause) {
    if (cause?.name === 'AbortError') throw cause
    const err = new Error('Dashboard API could not be reached. Try again in a moment.')
    err.cause = cause
    throw err
  }
  // A session that expired while the app was open turns every subsequent fetch
  // into a 401. Surfacing that as thirteen identical error panels tells the user
  // nothing, so send them to the login page instead. 'login' is relative for the
  // same reason 'api/' above is: it has to resolve under the /signal-dashboard/
  // prefix and at the root without knowing which one it is.
  if (res.status === 401) {
    window.location.assign('login')
    // Never settles -- the navigation is already underway, and resolving would
    // let callers render an error state during the redirect.
    return new Promise(() => {})
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (body?.detail) detail = body.detail
    } catch {
      // Keep the concise status fallback when the response is not JSON.
    }
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  return res.json()
}

// One hue per producer, held apart by hue angle rather than by brightness:
// blue LSTM, violet Intrinsic, cyan Foundry. `color` is the line/mark hue and
// `text` the brighter on-canvas variant; both come from styles.css via theme.js
// so the charts and the stylesheet cannot drift.
// `color` is the mark hue, `text` the brighter on-canvas variant. Both are
// getters: styles.css is imported after the component tree, so a token read at
// module-evaluation time would land before the stylesheet applied.
const producer = (label, metric, hue) => ({
  label,
  metric,
  get color() { return token(`--${hue}`) },
  get text() { return token(`--${hue}-text`) },
})

export const PRODUCER_META = {
  lstm: producer('LSTM', 'adj_prob', 'lstm'),
  intrinsic: producer('Intrinsic', 'discount', 'intrinsic'),
  foundry: producer('Foundry', 'score', 'foundry'),
}
