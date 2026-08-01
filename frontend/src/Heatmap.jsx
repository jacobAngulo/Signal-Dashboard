import React, { useMemo } from 'react'
import { href } from './nav.js'

const DAY_MS = 86400000
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']

// GitHub-style calendar of runs: columns are weeks, rows Mon–Fri.
// Cell color = how many BUY signals fired; red = a producer run failed.
export default function Heatmap({ calendar }) {
  const { weeks, byDate } = useMemo(() => {
    const byDate = {}
    for (const r of calendar) {
      const cell = (byDate[r.date] ||= { date: r.date, producers: {} })
      cell.producers[r.producer] = r
    }
    const dates = Object.keys(byDate).sort()
    if (!dates.length) return { weeks: [], byDate }
    const start = new Date(dates[0] + 'T00:00:00Z')
    const end = new Date(dates[dates.length - 1] + 'T00:00:00Z')
    // back up to Monday
    const s = new Date(start.getTime() - ((start.getUTCDay() + 6) % 7) * DAY_MS)
    const weeks = []
    for (let w = new Date(s); w <= end; w = new Date(w.getTime() + 7 * DAY_MS)) {
      const days = []
      for (let d = 0; d < 5; d++) {
        const day = new Date(w.getTime() + d * DAY_MS)
        days.push(day.toISOString().slice(0, 10))
      }
      weeks.push({ label: weeks.length % 4 === 0 ? days[0].slice(5) : '', days })
    }
    return { weeks, byDate }
  }, [calendar])

  if (!weeks.length) return <div className="muted">no runs yet</div>

  // Market days are ET — same convention as the producers' trade dates.
  const todayET = new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' })

  return (
    <div className="hm">
      <div className="hm-rows">
        <div className="hm-weekdays">
          {WEEKDAYS.map((d) => <div key={d} className="hm-wd">{d}</div>)}
        </div>
        <div className="hm-grid">
          <div className="hm-labels">
            {weeks.map((w, i) => <div key={i} className="hm-label">{w.label}</div>)}
          </div>
          <div className="hm-cells">
            {weeks.map((w, i) => (
              <div key={i} className="hm-col">
                {w.days.map((d) => <Cell key={d} date={d} cell={byDate[d]} today={d === todayET} />)}
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="hm-legend muted">
        <span className="hm-cell lvl-none" /> no run
        <span className="hm-cell lvl-0" /> ran, 0 buys
        <span className="hm-cell lvl-1" /> 1 buy
        <span className="hm-cell lvl-2" /> 2+ buys
        <span className="hm-cell lvl-fail" /> failed / missing status
        <span className="hm-cell lvl-none today" /> today
        · click a day to inspect it
      </div>
    </div>
  )
}

function Cell({ date, cell, today }) {
  const todayCls = today ? ' today' : ''
  if (!cell) return <div className={`hm-cell lvl-empty${todayCls}`} title={today ? `${date} (today)` : date} />
  const runs = Object.values(cell.producers)
  const buys = runs.reduce((a, r) => a + (r.n_buy || 0), 0)
  const failed = runs.some((r) => r.status && r.status !== 'ok')
  const lvl = failed ? 'fail' : buys >= 2 ? '2' : buys === 1 ? '1' : '0'
  const tip = [today ? `${date} (today)` : date, ...runs.map((r) =>
    `${r.producer}: ${r.status || 'no status'} · ${r.n_buy} buy${r.n_buy === 1 ? '' : 's'} · ${r.n_scores ?? '?'} scores`)]
    .join('\n')
  const accessible = tip.replaceAll('\n', '. ')
  return (
    <a className={`hm-cell lvl-${lvl} clickable${todayCls}`} title={tip}
       aria-label={`Open ${accessible}`} href={href('day', date)} />
  )
}
