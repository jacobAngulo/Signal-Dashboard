import React, { useDeferredValue, useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { fmtNum, fmtPct, fmtPx, signCls } from '../format.js'
import { href } from '../nav.js'
import {
  Card, DateLink, EmptyState, ErrorBox, PageHeader, PerfTag, Spinner, Stat,
  Tag, TickerLink,
} from '../ui.jsx'
import SignalDetail from '../SignalDetail.jsx'

const WINDOW_LABELS = {
  '1d': '1 day', '1w': '1 week', '1m': '1 month',
  '3m': '3 months', '6m': '6 months', '1y': '1 year',
}

const PAGE = 100

// Columns shown before "all columns". The rest stay one toggle away rather
// than off the page: everything the score file publishes about a candidate is
// reachable here, which is the point of the tab.
const ESSENTIAL = [
  'date', 'ticker', 'horizon', 'adj_prob', 'volume_ratio_20', 'volatility',
  'close', 'last_px', 'ret_1d', 'ret_5d', 'ret_since', 'exit_state',
  'exit_return', 'status_perf',
]

// Vectors whose buckets map onto a filter this page already has, so clicking a
// row in the summary can narrow the table. Grouping by anything else still
// summarises, it just doesn't pretend to offer a drill-down.
const DRILLABLE = ['horizon', 'status_perf', 'attention_status', 'selected', 'date']

const num = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v))
const Ret = ({ v }) => <span className={signCls(num(v))}>{fmtPct(num(v))}</span>

const COLUMNS = [
  { key: 'date', label: 'Day', render: (r) => <DateLink d={r.date} /> },
  { key: 'ticker', label: 'Ticker', render: (r) => (
    <span className="candidate-ticker">
      <TickerLink t={r.ticker} />
      {r.selected && <Tag kind="ok" title="Final daily decision">★</Tag>}
    </span>
  ) },
  { key: 'horizon', label: 'Horizon', render: (r) => WINDOW_LABELS[r.horizon] || r.horizon },
  { key: 'adj_prob', label: 'Adj prob', align: 'right', render: (r) => fmtPct(num(r.adj_prob), 2) },
  { key: 'pred_prob', label: 'Pred prob', align: 'right', render: (r) => fmtPct(num(r.pred_prob), 2) },
  { key: 'pred_std', label: 'Pred std', align: 'right', render: (r) => fmtNum(r.pred_std) },
  { key: 'volatility', label: 'Volatility', align: 'right', render: (r) => fmtNum(r.volatility) },
  // Three decimals, not two: this ratio runs from ~0.01 to ~2, and rounding to
  // two collapsed most of the column to "0.01".
  { key: 'volume_ratio_20', label: 'Vol ratio', align: 'right', render: (r) => fmtNum(r.volume_ratio_20) },
  { key: 'attention_status', label: 'Attention', render: (r) => r.attention_status || '–' },
  { key: 'attention_horizon_sessions', label: 'Att. sessions', align: 'right',
    render: (r) => (r.attention_horizon_sessions ?? '–') },
  { key: 'price_basis', label: 'Price basis',
    render: (r) => <span className="small muted">{r.price_basis || '–'}</span> },
  { key: 'close', label: 'Signal px', align: 'right', render: (r) => fmtPx(r.close) },
  { key: 'entry_px', label: 'Entry px', align: 'right', render: (r) => fmtPx(r.entry_px) },
  { key: 'last_px', label: 'Last px', align: 'right', render: (r) => fmtPx(r.last_px) },
  { key: 'ret_1d', label: '1d', align: 'right', render: (r) => <Ret v={r.ret_1d} /> },
  { key: 'ret_5d', label: '5d', align: 'right', render: (r) => <Ret v={r.ret_5d} /> },
  { key: 'ret_20d', label: '20d', align: 'right', render: (r) => <Ret v={r.ret_20d} /> },
  { key: 'ret_since', label: 'Since', align: 'right', render: (r) => <Ret v={r.ret_since} /> },
  { key: 'window_label', label: 'Window', render: (r) => (
    <span title={r.window_note || undefined}>{r.window_label || '–'}</span>
  ) },
  { key: 'window_sessions', label: 'Sessions', align: 'right',
    render: (r) => (r.window_sessions ?? '–') },
  // The model's own exit: it said "hold for this window", so did that pay?
  { key: 'exit_state', label: 'Exit', render: (r) => {
    if (!r.exit_state) return <span className="muted" title={r.exit_note || undefined}>–</span>
    if (r.exit_state === 'open') {
      return (
        <Tag kind="muted" title={r.exit_note || undefined}>
          open{r.sessions_elapsed != null && r.window_sessions
            ? ` ${r.sessions_elapsed}/${r.window_sessions}` : ''}
        </Tag>
      )
    }
    return <Tag kind="ok" title={r.exit_note || undefined}>closed</Tag>
  } },
  { key: 'exit_return', label: 'At exit', align: 'right',
    render: (r) => <Ret v={r.exit_return} /> },
  { key: 'exit_date', label: 'Exit date', render: (r) => r.exit_date || '–' },
  { key: 'status_perf', label: 'Status', render: (r) => (
    <PerfTag status={r.status_perf} stale={r.px_stale} asOf={r.last_date}
             actionWarning={r.has_action_warning} statusBasis={r.status_basis} />
  ) },
  { key: 'as_of_close_date', label: 'As of', render: (r) => r.as_of_close_date || '–' },
]

// Sorting, filtering and grouping all run on the server: the full enriched
// history is ~12k candidates, far past what is worth shipping to the browser
// just to sort it there.
export default function LstmWindows() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [loading, setLoading] = useState(true)
  const [horizon, setHorizon] = useState('')
  const [q, setQ] = useState('')
  const deferredQ = useDeferredValue(q)
  const [attention, setAttention] = useState('')
  const [perf, setPerf] = useState('')
  const [minProb, setMinProb] = useState('')
  const [minPrice, setMinPrice] = useState('')
  const [picksOnly, setPicksOnly] = useState(false)
  const [resolvedOnly, setResolvedOnly] = useState(false)
  const [dateFrom, setDateFrom] = useState('')
  const [groupBy, setGroupBy] = useState('horizon')
  const [sort, setSort] = useState('date')
  const [dir, setDir] = useState('desc')
  const [offset, setOffset] = useState(0)
  const [showAllColumns, setShowAllColumns] = useState(false)
  const [sel, setSel] = useState(null)

  useEffect(() => { setOffset(0) },
    [horizon, deferredQ, attention, perf, minProb, minPrice, picksOnly,
     resolvedOnly, dateFrom, sort, dir])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    api('lstm/windows', {
      horizon: horizon || undefined,
      q: deferredQ.trim() || undefined,
      attention_status: attention || undefined,
      status_perf: perf || undefined,
      min_prob: minProb === '' ? undefined : Number(minProb),
      min_price: minPrice === '' ? undefined : Number(minPrice),
      picks_only: picksOnly || undefined,
      resolved_only: resolvedOnly || undefined,
      date_from: dateFrom || undefined,
      group_by: groupBy,
      sort, dir, limit: PAGE, offset,
    }, { signal: controller.signal })
      .then((next) => { setData(next); setErr(null) })
      .catch((nextErr) => { if (nextErr.name !== 'AbortError') setErr(nextErr) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [horizon, deferredQ, attention, perf, minProb, minPrice, picksOnly,
      resolvedOnly, dateFrom, groupBy, sort, dir, offset])

  const columns = useMemo(
    () => (showAllColumns ? COLUMNS : COLUMNS.filter((c) => ESSENTIAL.includes(c.key))),
    [showAllColumns])

  const clickCol = (key) => {
    if (sort === key) setDir(dir === 'asc' ? 'desc' : 'asc')
    else { setSort(key); setDir('desc') }
  }

  const anyFilter = Boolean(horizon || q.trim() || attention || perf || minProb
    || minPrice || picksOnly || resolvedOnly || dateFrom)
  const clearAll = () => {
    setHorizon(''); setQ(''); setAttention(''); setPerf(''); setMinProb('')
    setMinPrice(''); setPicksOnly(false); setResolvedOnly(false); setDateFrom('')
  }

  // Narrow the table to the bucket that was clicked, or clear it if it was
  // already the active filter.
  const drillInto = (group) => {
    const key = data?.group_by
    if (key === 'horizon') setHorizon(group.key === horizon ? '' : group.key)
    else if (key === 'status_perf') setPerf(group.key === perf ? '' : group.key)
    else if (key === 'attention_status') setAttention(group.key === attention ? '' : group.key)
    else if (key === 'selected') setPicksOnly(group.key === '★ pick')
    else if (key === 'date') setDateFrom(group.key === dateFrom ? '' : group.key)
  }

  if (err) return <><PageHeader title="LSTM signals" /><ErrorBox err={err} /></>
  if (!data) return <><PageHeader title="LSTM signals" /><Spinner /></>

  const scored = Object.values(data.scored_counts).reduce((n, count) => n + count, 0)
  const dominant = data.windows.reduce((best, window) =>
    (data.counts[window] || 0) > (data.counts[best] || 0) ? window : best, data.windows[0])
  const latestScored = data.days.find((day) => day.scored > 0)
  const tier = data.price_tier || {}
  const uncovered = (tier.total || 0) - (tier.covered || 0)
  const dates = data.facets?.dates || []
  const summary = data.summary || {}
  const shownFrom = data.total ? offset + 1 : 0
  const shownTo = Math.min(offset + PAGE, data.total)
  const vector = (data.vectors || []).find((v) => v.key === data.group_by)
  const drillable = DRILLABLE.includes(data.group_by)
  // The arrow follows what the server actually sorted by, not what we asked
  // for, so a silent fallback can't leave the header claiming a false order.
  const sortedBy = data.sort || sort
  const sortedDir = data.dir || dir

  const pager = (
    <div className="table-pager">
      <button type="button" className="btn" disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Previous</button>
      <span className="muted small">
        {shownFrom.toLocaleString()}–{shownTo.toLocaleString()} of {(data.total || 0).toLocaleString()}
      </span>
      <button type="button" className="btn" disabled={shownTo >= data.total}
              onClick={() => setOffset(offset + PAGE)}>Next →</button>
    </div>
  )

  return (
    <div>
      <PageHeader
        eyebrow="Model output audit"
        title="LSTM candidates by best horizon"
        description="Every published above-threshold candidate, with the model vectors it was scored on and how it has traded since."
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

      {(tier.building || uncovered > 0 || tier.error) && (
        <Card className="tier-note">
          <p className="muted small">
            {tier.error
              ? `Candidate prices failed to load: ${tier.error}. Returns stay empty rather than estimated.`
              : tier.building
                ? `Candidate prices are still loading (${(tier.tickers || 0).toLocaleString()} tickers so far). Returns fill in as the book completes.`
                : `${uncovered.toLocaleString()} of ${(tier.total || 0).toLocaleString()} candidates in this slice have no gateway price coverage yet, so their returns are blank.`}
            {' '}Candidate returns come from a slower price tier than the final picks, so they can lag by up to half an hour.
          </p>
        </Card>
      )}

      <Card>
        <div className="filter-row candidate-filters">
          <label>Horizon
            <select value={horizon} onChange={(e) => setHorizon(e.target.value)}>
              <option value="">all horizons</option>
              {data.windows.map((window) => (
                <option key={window} value={window}>{WINDOW_LABELS[window] || window}</option>
              ))}
            </select>
          </label>
          <label>Ticker
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search ticker…" />
          </label>
          <label>Since
            <select value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}>
              <option value="">all {dates.length} days</option>
              {[5, 10, 20, 40].filter((n) => n < dates.length).map((n) => (
                <option key={n} value={dates[n - 1]}>last {n} days</option>
              ))}
            </select>
          </label>
          {(data.facets?.attention_status || []).length > 0 && (
            <label>Attention
              <select value={attention} onChange={(e) => setAttention(e.target.value)}>
                <option value="">any</option>
                {data.facets.attention_status.map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
            </label>
          )}
          <label>Performance
            <select value={perf} onChange={(e) => setPerf(e.target.value)}>
              <option value="">any</option>
              {(data.facets?.status_perf || []).map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
          <label>Min adj prob
            <input type="number" step="0.01" min="0" max="1" value={minProb}
                   onChange={(e) => setMinProb(e.target.value)} placeholder="0.00" />
          </label>
          {/* Sub-dollar tickers swing +200% / -80% and drag every average in the
              vector panel with them, so a price floor is what makes the
              grouping legible rather than a cosmetic extra. */}
          <label>Min price
            <input type="number" step="1" min="0" value={minPrice}
                   onChange={(e) => setMinPrice(e.target.value)} placeholder="$0" />
          </label>
          <label className="check">
            <input type="checkbox" checked={resolvedOnly}
                   onChange={(e) => setResolvedOnly(e.target.checked)} />
            resolved only
          </label>
          <label className="check">
            <input type="checkbox" checked={picksOnly}
                   onChange={(e) => setPicksOnly(e.target.checked)} />
            ★ picks only
          </label>
          {anyFilter && (
            <button type="button" className="text-btn" onClick={clearAll}>clear filters</button>
          )}
          <span className="muted slice-summary">
            {(data.total || 0).toLocaleString()} candidates
            {summary.wr_5d !== null && summary.wr_5d !== undefined && (
              <> · {fmtPct(summary.wr_5d, 0)} win rate 5d · avg {fmtPct(summary.avg_5d)} 5d</>
            )}
          </span>
        </div>
      </Card>

      {/* The lead panel. Rather than making you click through thirteen
          groupings one at a time to find the one that matters, every vector is
          scored by how far apart its best and worst buckets land, and the list
          is ranked by it. Pick a row to open that vector below. */}
      <Card title="Which vectors separate outcomes"
            right={<span className="muted small">ranked by 5-day spread between best and worst bucket</span>}>
        {!(data.vector_scan || []).length ? (
          <EmptyState title="Nothing to rank" detail="Widen the filters above." />
        ) : (
          <div className="table-wrap">
            <table className="vector-table">
              <caption className="sr-only">
                Model vectors ranked by how far apart their best and worst
                buckets' average five-day returns land. Select a row to break
                that vector out below.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Vector</th>
                  <th scope="col" className="right">Buckets</th>
                  <th scope="col">Best bucket</th>
                  <th scope="col" className="right">Avg 5d</th>
                  <th scope="col">Worst bucket</th>
                  <th scope="col" className="right">Avg 5d</th>
                  <th scope="col" className="right">Spread</th>
                </tr>
              </thead>
              <tbody>
                {data.vector_scan.map((v) => (
                  <tr key={v.key} className="clickable"
                      onClick={() => setGroupBy(v.key)}>
                    <th scope="row" className={v.key === data.group_by ? 'sorted' : undefined}>
                      {v.label}
                    </th>
                    <td className="right">{v.measured || '–'}</td>
                    <td className="muted bucket-label" title={v.best_label || undefined}>
                      {v.best_label || '–'}
                      {v.best_n ? <span className="bucket-n"> n={v.best_n.toLocaleString()}</span> : null}
                    </td>
                    <td className="right"><Ret v={v.best_ret_5d} /></td>
                    <td className="muted bucket-label" title={v.worst_label || undefined}>
                      {v.worst_label || '–'}
                      {v.worst_n ? <span className="bucket-n"> n={v.worst_n.toLocaleString()}</span> : null}
                    </td>
                    <td className="right"><Ret v={v.worst_ret_5d} /></td>
                    <td className="right">
                      {v.spread === null || v.spread === undefined
                        ? <span className="muted">–</span>
                        : <b>{(v.spread * 100).toFixed(1)}pp</b>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title={`Breakdown — ${vector?.label || data.group_by}`}
            right={
              <label className="inline-label">Group by
                <select value={groupBy} onChange={(e) => setGroupBy(e.target.value)}>
                  {(data.vectors || []).map((v) => (
                    <option key={v.key} value={v.key}>{v.label}</option>
                  ))}
                </select>
              </label>
            }>
        {!(data.groups || []).length ? (
          <EmptyState title="Nothing to group" detail="Widen the filters above." />
        ) : (
          <div className="table-wrap">
            <table className="vector-table">
              <caption className="sr-only">
                Candidate performance grouped by {vector?.label || data.group_by}
                {drillable ? '. Select a row to filter the candidate table to it.' : ''}
              </caption>
              <thead>
                <tr>
                  <th scope="col">{vector?.label || 'Bucket'}</th>
                  <th scope="col" className="right">Candidates</th>
                  {/* One ticker appearing eight times is not eight pieces of
                      evidence — show how many distinct names a bucket covers. */}
                  <th scope="col" className="right">Tickers</th>
                  <th scope="col" className="right">★ picks</th>
                  <th scope="col" className="right">Avg 1d</th>
                  <th scope="col" className="right">Avg 5d</th>
                  <th scope="col" className="right">Avg since</th>
                  <th scope="col" className="right">Win rate 5d</th>
                  {/* The model's own exit, not a fixed window: how many of the
                      bucket reached the horizon it asked for, and what that paid. */}
                  <th scope="col" className="right">Closed</th>
                  <th scope="col" className="right">Avg at exit</th>
                  <th scope="col" className="right">Win rate exit</th>
                </tr>
              </thead>
              <tbody>
                {data.groups.map((group) => (
                  <tr key={group.key} className={drillable ? 'clickable' : undefined}
                      onClick={drillable ? () => drillInto(group) : undefined}>
                    <th scope="row">{group.label}</th>
                    <td className="right">{group.n.toLocaleString()}</td>
                    <td className="right">{(group.tickers ?? 0).toLocaleString()}</td>
                    <td className="right">{group.picks || '–'}</td>
                    <td className="right"><Ret v={group.ret_1d} /></td>
                    <td className="right"><Ret v={group.ret_5d} /></td>
                    <td className="right"><Ret v={group.ret_since} /></td>
                    <td className="right">
                      {group.wr_5d === null || group.wr_5d === undefined
                        ? '–' : fmtPct(group.wr_5d, 0)}
                    </td>
                    <td className="right">{group.closed ? group.closed.toLocaleString() : '–'}</td>
                    <td className="right"><Ret v={group.exit_return} /></td>
                    <td className="right">
                      {group.wr_exit === null || group.wr_exit === undefined
                        ? '–' : fmtPct(group.wr_exit, 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Candidates"
        right={
          <button type="button" className="text-btn"
                  onClick={() => setShowAllColumns(!showAllColumns)}>
            {showAllColumns ? 'essential columns' : 'all columns'}
          </button>
        }>
        {!data.candidates.length ? (
          <EmptyState title="No matching LSTM candidates"
                      detail="Clear a filter to widen the view."
                      action={anyFilter && (
                        <button type="button" className="btn" onClick={clearAll}>
                          Clear filters
                        </button>
                      )} />
        ) : (
          <>
            {/* Paging controls above the table too: with 100 rows, having them
                only at the bottom means scrolling the whole page to move on. */}
            {data.total > PAGE && pager}
            <div className={`table-wrap${loading ? ' is-loading' : ''}`}>
              <table className="candidate-table">
                <caption className="sr-only">
                  LSTM BUY candidates with model vectors and forward returns
                </caption>
                <thead>
                  <tr>
                    {columns.map((c) => (
                      <th key={c.key} scope="col"
                          className={`${sortedBy === c.key ? 'sorted ' : ''}col-${c.key}${c.align === 'right' ? ' right' : ''}`}
                          aria-sort={sortedBy === c.key ? (sortedDir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                        <button type="button" className="sort-button"
                                onClick={() => clickCol(c.key)}>
                          {c.label}
                          <span aria-hidden="true">
                            {sortedBy === c.key ? (sortedDir === 'asc' ? ' ▲' : ' ▼') : ''}
                          </span>
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.candidates.map((row) => (
                    <tr key={row.id} className="clickable" onClick={() => setSel(row)}>
                      {columns.map((c) => (
                        <td key={c.key}
                            className={`col-${c.key}${c.align === 'right' ? ' right' : ''}`}>
                          {c.render ? c.render(row) : row[c.key] ?? '–'}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {pager}
          </>
        )}
      </Card>

      <SignalDetail signal={sel} onClose={() => setSel(null)} />
    </div>
  )
}
