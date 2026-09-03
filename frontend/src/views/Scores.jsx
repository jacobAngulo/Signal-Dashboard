import React, { useDeferredValue, useEffect, useMemo, useState } from 'react'
import { api, PRODUCER_META } from '../api.js'
import { fmtNum } from '../format.js'
import { href } from '../nav.js'
import { Card, EmptyState, ErrorBox, Spinner, TickerLink } from '../ui.jsx'

const PAGE = 100
const ESSENTIAL_COLUMNS = {
  lstm: ['ticker', 'status', 'best_horizon', 'best_adj_prob', 'best_pred_prob', 'best_pred_std', 'close', 'volume_ratio_20', 'attention_status', 'as_of_close_date'],
  intrinsic: ['ticker', 'status', 'discount_to_intrinsic', 'price', 'intrinsic_value', 'market_cap', 'shadow_status', 'as_of_close_date'],
  foundry: ['ticker', 'decision', 'signal_score', 'event_type', 'sentiment', 'confidence', 'source', 'title', 'published_at'],
}
const humanize = (value) => value.replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())

// Server-sorted/paginated browser over daily score files. Decision-driving
// columns are the default; provenance remains one toggle away.
export default function Scores({ producer: p0, date: d0 }) {
  const [producer, setProducer] = useState(p0 || 'lstm')
  const [date, setDate] = useState(d0 || '')
  const [q, setQ] = useState('')
  const deferredQ = useDeferredValue(q)
  const [sort, setSort] = useState(null)
  const [dir, setDir] = useState('desc')
  const [offset, setOffset] = useState(0)
  const [showAll, setShowAll] = useState(false)
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => { setSort(null); setOffset(0); setShowAll(false) }, [producer])
  useEffect(() => { setOffset(0) }, [date, deferredQ])

  useEffect(() => {
    const controller = new AbortController()
    setErr(null)
    setLoading(true)
    const load = async () => {
      if (!date) {
        const runs = await api('runs', null, { signal: controller.signal })
        const mine = runs.runs.filter((r) => r.producer === producer && r.has_scores)
        if (!mine.length) throw new Error(`No score files are available for ${PRODUCER_META[producer]?.label || producer}.`)
        setDate(mine[0].date)
        return
      }
      const next = await api(`scores/${producer}/${date}`,
        { sort, dir, limit: PAGE, offset, q: deferredQ },
        { signal: controller.signal })
      setData(next)
      history.replaceState(null, '', href('scores', producer, date))
    }
    load()
      .catch((nextErr) => { if (nextErr.name !== 'AbortError') setErr(nextErr) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [producer, date, sort, dir, offset, deferredQ])

  const columns = useMemo(() => {
    if (!data) return []
    if (showAll) return data.columns
    const essential = (ESSENTIAL_COLUMNS[producer] || []).filter((column) => data.columns.includes(column))
    return essential.length ? essential : data.columns.slice(0, 10)
  }, [data, producer, showAll])

  const clickCol = (column) => {
    if (sort === column) setDir(dir === 'asc' ? 'desc' : 'asc')
    else { setSort(column); setDir('desc') }
    setOffset(0)
  }
  const changeProducer = (next) => {
    setProducer(next); setDate(''); setData(null)
  }
  const shownFrom = data?.total ? offset + 1 : 0
  const shownTo = data ? Math.min(offset + PAGE, data.total) : 0

  return (
    <div className="scores-page">
      <h1 className="sr-only">Raw score browser</h1>

      <Card>
        <div className="filter-row score-controls">
          <label>Producer
            <select value={producer} onChange={(e) => changeProducer(e.target.value)}>
              {Object.entries(PRODUCER_META).map(([name, meta]) => (
                <option key={name} value={name}>{meta.label}</option>
              ))}
            </select>
          </label>
          <label>Score date
            <select value={date} onChange={(e) => setDate(e.target.value)} disabled={!date}>
              {(data?.dates || (date ? [date] : [])).slice().reverse().map((day) => (
                <option key={day} value={day}>{day}</option>
              ))}
            </select>
          </label>
          <label>Find ticker
            <input placeholder="e.g. NVDA" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <label className="check column-toggle">
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
            Show all {data?.columns.length || ''} fields
          </label>
          {data && <span className="result-range muted" aria-live="polite">{shownFrom}–{shownTo} of {data.total.toLocaleString()}</span>}
        </div>
      </Card>

      {err && <ErrorBox err={err} />}
      {!data ? <Spinner /> : (
        <Card className={`scores-results${loading ? ' refetching' : ''}`}>
          {data.rows.length ? (
            <div className="table-wrap score-table-wrap" aria-busy={loading}>
              <table>
                <thead>
                  <tr>
                    {columns.map((column) => (
                      <th key={column} scope="col"
                          aria-sort={sort === column ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                          className={sort === column ? 'sorted' : ''}>
                        <button type="button" className="sort-button" onClick={() => clickCol(column)}>
                          {humanize(column)}<span aria-hidden="true">{sort === column ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}</span>
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row, i) => (
                    <tr key={row.ticker || i}>
                      {columns.map((column) => (
                        <td key={column}>
                          {column === 'ticker' && row[column]
                            ? <TickerLink t={String(row[column]).toUpperCase()} bold={false} />
                            : typeof row[column] === 'number' ? fmtNum(row[column], 4)
                              : row[column] == null || row[column] === '' ? '–' : String(row[column])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="No score rows match" detail={`No tickers contain “${deferredQ}” on this score date.`} />
          )}
          {data.total > PAGE && (
            <div className="pagination" aria-label="Score pages">
              <button type="button" className="btn" disabled={offset === 0}
                      aria-label="Previous score page"
                      onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Previous</button>
              <span className="muted">Page {Math.floor(offset / PAGE) + 1} of {Math.ceil(data.total / PAGE)}</span>
              <button type="button" className="btn" disabled={offset + PAGE >= data.total}
                      aria-label="Next score page"
                      onClick={() => setOffset(offset + PAGE)}>Next →</button>
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
