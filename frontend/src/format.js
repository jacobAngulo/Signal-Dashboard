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

// All timestamps display in Pacific time (Jacob's local tz — the host VM is
// elsewhere, so never rely on the machine's local zone).
export const TZ = 'America/Los_Angeles'

export const fmtTs = (ts) => {
  if (!ts) return '–'
  try {
    return new Date(ts).toLocaleString('en-US', {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
      timeZone: TZ, timeZoneName: 'short',
    })
  } catch { return ts }
}

// Time of day only ("7:14 AM") — pair with a date shown elsewhere in the row.
export const fmtTime = (ts) => {
  if (!ts) return '–'
  try {
    return new Date(ts).toLocaleTimeString('en-US', {
      hour: 'numeric', minute: '2-digit', timeZone: TZ,
    })
  } catch { return ts }
}

// "Jul 7, 5:30 PM" — for event timestamps whose calendar day can differ from
// the row's trade date. Date-only values (no publish time known) pass through.
export const fmtDayTime = (ts) => {
  if (!ts) return '–'
  if (String(ts).length === 10) return ts
  try {
    return new Date(ts).toLocaleString('en-US', {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: TZ,
    })
  } catch { return ts }
}

// Compact age for freshness readouts: "4m", "3h", "2d".
export const fmtAgo = (ts) => {
  if (!ts) return '–'
  const ms = Date.now() - new Date(ts).getTime()
  if (!isFinite(ms)) return '–'
  const m = Math.max(0, Math.round(ms / 60000))
  if (m < 60) return `${m}m`
  const h = Math.round(m / 60)
  if (h < 48) return `${h}h`
  return `${Math.round(h / 24)}d`
}

export const signCls = (v) =>
  v === null || v === undefined ? 'muted' : v > 0 ? 'pos' : v < 0 ? 'neg' : 'muted'
