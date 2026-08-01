import React, { useMemo, useState, useEffect } from 'react'
import { api } from '../api.js'
import { fmtPct } from '../format.js'
import { href } from '../nav.js'
import { Card, DateLink, EmptyState, ErrorBox, PageHeader, Spinner, Stat, Tag, TickerLink } from '../ui.jsx'
import SignalDetail from '../SignalDetail.jsx'

const WINDOW_LABELS = {
  '1d': '1 day', '1w': '1 week', '1m': '1 month',
  '3m': '3 months', '6m': '6 months', '1y': '1 year',
}

const CELL_LIMIT = 5

// The score exporter records every above-threshold ticker candidate, but only
// its strongest model head. The daily decision file then selects one global
// ticker+horizon winner from those candidates.
export default function LstmWindows() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [windowFilter, setWindowFilter] = useState('')
  const [ticker, setTicker] = useState('')
  const [showAll, setShowAll] = useState(false)
  const [expanded, setExpanded] = useState({})
  const [sel, setSel] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    api('lstm/windows', null, { signal: controller.signal })
      .then((next) => { setData(next); setErr(null) })
      .catch((nextErr) => { if (nextErr.name !== 'AbortError') setErr(nextErr) })
    return () => controller.abort()
  }, [])

  const filtered = useMemo(() => {
    if (!data) return []
    const query = ticker.trim().toUpperCase()
    const filtering = Boolean(query || windowFilter)
    return data.days.map((day) => {
      const signals = {}
      for (const window of data.windows) {
        if (windowFilter && window !== windowFilter) continue
        const matches = (day.signals[window] || []).filter((signal) =>
          !query || signal.ticker.includes(query))
        if (matches.length) signals[window] = matches
      }
      return {
        ...day,
        signals,
        total: Object.values(signals).reduce((n, rows) => n + rows.length, 0),
      }
    }).filter((day) => !filtering || day.total)
  }, [data, ticker, windowFilter])

  if (err) return <><PageHeader title="LSTM signals" /><ErrorBox err={err} /></>
  if (!data) return <><PageHeader title="LSTM signals" /><Spinner /></>

  const windows = windowFilter ? [windowFilter] : data.windows
  const visibleDays = showAll ? filtered : filtered.slice(0, 20)
  const total = filtered.reduce((n, day) => n + day.total, 0)
  const scored = Object.values(data.scored_counts).reduce((n, count) => n + count, 0)
  const dominant = data.windows.reduce((best, window) =>
    (data.counts[window] || 0) > (data.counts[best] || 0) ? window : best, data.windows[0])
  const latestScored = data.days.find((day) => day.scored > 0)

  return (
    <div>
      <PageHeader
        eyebrow="Model output audit"
        title="LSTM candidates by best horizon"
        description="See every published above-threshold candidate, grouped by the horizon that scored highest for that ticker."
        meta="The model evaluates four horizons, but its score files retain only each ticker’s strongest head; ★ marks the single final daily pick."
        actions={latestScored && <a className="btn" href={href('scores', 'lstm', latestScored.date)}>Latest raw scores</a>}
      />

      <Card className="window-summary-card">
        <div className="stat-row">
          <Stat label="BUY candidates" value={Object.values(data.counts).reduce((n, count) => n + count, 0)} />
          <Stat label="scored ticker-days" value={scored} />
          <Stat label="candidate days" value={data.days.filter((day) => day.total > 0).length} />
          <Stat label="most frequent" value={WINDOW_LABELS[dominant] || dominant}
                sub={`${data.counts[dominant] || 0} candidates`} />
          {data.windows.map((window) => (
            <Stat key={window} label={WINDOW_LABELS[window] || window}
                  value={data.counts[window] || 0}
                  sub={`best for ${data.scored_counts[window] || 0}`} />
          ))}
        </div>
      </Card>

      <Card>
        <div className="filter-row window-filters">
          <label>Window
            <select value={windowFilter} onChange={(e) => setWindowFilter(e.target.value)}>
              <option value="">all windows</option>
              {data.windows.map((window) => (
                <option key={window} value={window}>{WINDOW_LABELS[window] || window}</option>
              ))}
            </select>
          </label>
          <label>Ticker
            <input value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="Search ticker…" />
          </label>
          <span className="muted" style={{ marginLeft: 'auto' }}>{total} matching candidate{total === 1 ? '' : 's'}</span>
        </div>
      </Card>

      {!filtered.length ? (
        <Card><EmptyState title="No matching LSTM candidates" detail="Clear the ticker or horizon filter to widen the view." /></Card>
      ) : (
        <Card>
          <div className="table-wrap window-table-wrap">
            <table className="window-table">
              <caption className="sr-only">LSTM BUY candidates grouped by trading day and each ticker's best horizon</caption>
              <thead>
                <tr>
                  <th scope="col">Trading day</th>
                  {windows.map((window) => (
                    <th scope="col" key={window}>
                      {WINDOW_LABELS[window] || window}
                      <span className="th-sub">{data.counts[window] || 0} total</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibleDays.map((day) => (
                  <tr key={day.date}>
                    <th scope="row" className="window-date">
                      <DateLink d={day.date} />
                      <span className="muted small">{day.total} candidate{day.total === 1 ? '' : 's'}</span>
                      <span className="muted small">{day.scored} scored</span>
                    </th>
                    {windows.map((window) => (
                      <td key={window} className="window-cell">
                        <WindowCell
                          signals={day.signals[window] || []}
                          bestCount={day.best_horizon_counts[window] || 0}
                          expanded={Boolean(expanded[`${day.date}:${window}`]) || Boolean(ticker.trim())}
                          onToggle={() => setExpanded((current) => ({
                            ...current,
                            [`${day.date}:${window}`]: !current[`${day.date}:${window}`],
                          }))}
                          onSelect={setSel}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {filtered.length > 20 && (
            <div className="center card-footer">
              <button type="button" className="btn" onClick={() => setShowAll(!showAll)}>
                {showAll ? 'Show latest 20 days' : `Show all ${filtered.length} days`}
              </button>
            </div>
          )}
        </Card>
      )}
      <SignalDetail signal={sel} onClose={() => setSel(null)} />
    </div>
  )
}

function WindowCell({ signals, bestCount, expanded, onToggle, onSelect }) {
  const visible = expanded ? signals : signals.slice(0, CELL_LIMIT)
  return (
    <div>
      <div className="window-cell-meta muted small">
        {signals.length} candidate{signals.length === 1 ? '' : 's'} · best for {bestCount}
      </div>
      {visible.map((signal) => (
        <div className={`window-signal${signal.selected ? ' selected' : ''}`} key={signal.id}>
          <span>
            <TickerLink t={signal.ticker} />{' '}
            {signal.selected && <Tag kind="ok" title="Final daily decision">★ pick</Tag>}
          </span>
          <button type="button" className="probability-btn" onClick={() => onSelect(signal)}
                  aria-label={`Open ${signal.ticker} candidate, adjusted probability ${fmtPct(signal.adj_prob)}`}>
            {fmtPct(signal.adj_prob)}
          </button>
        </div>
      ))}
      {!signals.length && <span className="muted">No candidate</span>}
      {signals.length > CELL_LIMIT && (
        <button type="button" className="text-btn window-more" onClick={onToggle}>
          {expanded ? 'show fewer' : `+${signals.length - CELL_LIMIT} more`}
        </button>
      )}
    </div>
  )
}
