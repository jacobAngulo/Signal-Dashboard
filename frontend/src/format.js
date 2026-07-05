export const fmtPct = (v, digits = 1) =>
  v === null || v === undefined ? '–' : `${(v * 100).toFixed(digits)}%`

export const fmtNum = (v, digits = 3) =>
  v === null || v === undefined ? '–' : Number(v).toFixed(digits)

export const fmtPx = (v) => {
  if (v === null || v === undefined) return '–'
  const n = Number(v)
  return '$' + n.toFixed(n < 1 ? 4 : 2)
}

export const fmtMoney = (v) => {
  if (v === null || v === undefined) return '–'
  const sign = v < 0 ? '-' : ''
  return `${sign}$${Math.abs(v).toFixed(2)}`
}

export const fmtDate = (d) => d || '–'

export const fmtTs = (ts) => {
  if (!ts) return '–'
  try {
    return new Date(ts).toLocaleString('en-US', {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
      timeZone: 'America/New_York', timeZoneName: 'short',
    })
  } catch { return ts }
}

export const signCls = (v) =>
  v === null || v === undefined ? 'muted' : v > 0 ? 'pos' : v < 0 ? 'neg' : 'muted'
