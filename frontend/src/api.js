// All requests are relative ("api/...") so the app works at the root of
// :8010 directly and behind the /signal-dashboard/ nginx prefix unchanged.
export async function api(path, params) {
  let url = 'api/' + path.replace(/^\//, '')
  if (params) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
    ).toString()
    if (qs) url += '?' + qs
  }
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

export const PRODUCER_META = {
  lstm: { label: 'LSTM', color: '#5b9cf6', metric: 'adj_prob' },
  intrinsic: { label: 'Intrinsic', color: '#3ecf8e', metric: 'discount' },
  foundry: { label: 'Foundry', color: '#f6c453', metric: 'score' },
}
