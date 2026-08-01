// All requests are relative ("api/...") so the app works at the root of
// :8010 directly and behind the /signal-dashboard/ nginx prefix unchanged.
export async function api(path, params, options = {}) {
  let url = 'api/' + path.replace(/^\//, '')
  if (params) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
    ).toString()
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

export const PRODUCER_META = {
  lstm: { label: 'LSTM', color: '#5b9cf6', metric: 'adj_prob' },
  intrinsic: { label: 'Intrinsic', color: '#3ecf8e', metric: 'discount' },
  foundry: { label: 'Foundry', color: '#f6c453', metric: 'score' },
}
