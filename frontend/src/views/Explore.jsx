import React, { useDeferredValue, useEffect, useState } from 'react'
import { api, PRODUCER_META } from '../api.js'
import { fmtPct } from '../format.js'
import { Card, EmptyState, ErrorBox, Spinner } from '../ui.jsx'
import SignalTable from '../SignalTable.jsx'
import SignalDetail from '../SignalDetail.jsx'

const PAGE = 75

// The dig-in surface: server-filtered, paged signals plus a summary of the
// complete slice. Keeping only one page of sparks makes WATCH-heavy days sane.
export default function Explore({ query = {} }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [loading, setLoading] = useState(true)
  const [sel, setSel] = useState(null)
  const [filtersOpen, setFiltersOpen] = useState(true)

  const [producer, setProducer] = useState(query.producer || '')
  const [from, setFrom] = useState(query.from || '')
  const [to, setTo] = useState(query.to || '')
  const [buysOnly, setBuysOnly] = useState(query.buys !== '0')
  const [ticker, setTicker] = useState(query.ticker || '')
  const deferredTicker = useDeferredValue(ticker)
  const [status, setStatus] = useState(query.status || '')
  const [minMetric, setMinMetric] = useState(query.min || '')
  const [offset, setOffset] = useState(0)

  useEffect(() => { setOffset(0) }, [producer, from, to, buysOnly, deferredTicker, status, minMetric])

  useEffect(() => {
    const params = new URLSearchParams()
    if (producer) params.set('producer', producer)
    if (from) params.set('from', from)
    if (to) params.set('to', to)
    if (!buysOnly) params.set('buys', '0')
    if (ticker) params.set('ticker', ticker)
    if (status) params.set('status', status)
    if (producer && minMetric) params.set('min', minMetric)
    history.replaceState(null, '', `#/explore${params.size ? `?${params}` : ''}`)
  }, [producer, from, to, buysOnly, ticker, status, minMetric])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    api('signals', {
      producer,
      date_from: from,
      date_to: to,
      buys_only: buysOnly,
      q: deferredTicker,
      status,
      min_metric: producer ? minMetric : '',
      limit: PAGE,
      offset,
      spark: true,
    }, { signal: controller.signal })
      .then((next) => { setData(next); setErr(null) })
      .catch((nextErr) => { if (nextErr.name !== 'AbortError') setErr(nextErr) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [producer, from, to, buysOnly, deferredTicker, status, minMetric, offset])

  const reset = () => {
    setProducer(''); setFrom(''); setTo(''); setBuysOnly(true)
    setTicker(''); setStatus(''); setMinMetric(''); setOffset(0)
  }
  const activeFilters = [producer, from, to, ticker, status, producer && minMetric, !buysOnly]
    .filter(Boolean).length
  const summary = data?.summary || {}
  const metricName = producer ? PRODUCER_META[producer]?.metric : null
  const shownFrom = data?.total ? offset + 1 : 0
  const shownTo = data ? Math.min(offset + data.signals.length, data.total) : 0

  return (
    <div>
      <h1 className="sr-only">Explore signals</h1>

      <div className="rail-layout">
        <aside>
          <Card
            title={<span>Filters {activeFilters > 0 && <span className="filter-count">{activeFilters}</span>}</span>}
            right={<button type="button" className="text-btn" onClick={() => setFiltersOpen(!filtersOpen)}>
              {filtersOpen ? 'hide' : 'show'}
            </button>}
          >
            {filtersOpen && <div className="filter-col">
              <label>Producer
                <select value={producer} onChange={(e) => setProducer(e.target.value)}>
                  <option value="">all producers</option>
                  {Object.entries(PRODUCER_META).map(([name, meta]) => (
                    <option key={name} value={name}>{meta.label}</option>
                  ))}
                </select>
              </label>
              <label>Ticker contains
                <input value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="e.g. NVDA" />
              </label>
              <div className="filter-date-grid">
                <label>From
                  <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
                </label>
                <label>To
                  <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
                </label>
              </div>
              <label>Performance
                <select value={status} onChange={(e) => setStatus(e.target.value)}>
                  <option value="">any outcome</option>
                  <option value="up">up since signal</option>
                  <option value="down">down since signal</option>
                  <option value="flat">flat since signal</option>
                  <option value="pending">pending next close</option>
                  <option value="corporate_action_unresolved">corporate-action flagged</option>
                  <option value="no_px">no price coverage</option>
                  {!buysOnly && <option value="no_action">not a BUY</option>}
                </select>
              </label>
              <label className={!producer ? 'disabled-control' : ''}>
                Minimum {metricName || 'metric'}
                <input type="number" step="0.01" value={minMetric} disabled={!producer}
                       onChange={(e) => setMinMetric(e.target.value)}
                       placeholder={producer ? 'e.g. 0.25' : 'choose a producer first'} />
              </label>
              <label className="check">
                <input type="checkbox" checked={buysOnly} onChange={(e) => setBuysOnly(e.target.checked)} />
                BUY decisions only
              </label>
              <button type="button" className="btn full-btn" onClick={reset} disabled={!activeFilters}>Clear filters</button>
            </div>}
          </Card>

          <Card title="Slice performance" className={loading ? 'refetching' : ''}>
            <div className="kv-grid">
              <span>signals</span><b>{summary.n ?? '–'}</b>
              <span>win rate 1d</span><b>{summary.wr_1d == null ? '–' : fmtPct(summary.wr_1d, 0)}</b>
              <span>win rate 5d</span><b>{summary.wr_5d == null ? '–' : fmtPct(summary.wr_5d, 0)}</b>
              <span>avg 5d</span><b className={summary.avg_5d > 0 ? 'pos' : summary.avg_5d < 0 ? 'neg' : ''}>{summary.avg_5d == null ? '–' : fmtPct(summary.avg_5d)}</b>
              <span>avg since</span><b className={summary.avg_since > 0 ? 'pos' : summary.avg_since < 0 ? 'neg' : ''}>{summary.avg_since == null ? '–' : fmtPct(summary.avg_since)}</b>
            </div>
            <div className="muted small">computed over the full filtered slice</div>
          </Card>
        </aside>

        <div className="results-panel" aria-busy={loading}>
          {err && <ErrorBox err={err} />}
          {!data ? <Spinner /> : (
            <Card
              className={loading ? 'refetching' : ''}
              title={`${data.total.toLocaleString()} signals`}
              right={<span className="muted small" aria-live="polite">
                {shownFrom}–{shownTo} · click View for details
              </span>}
            >
              {data.signals.length ? (
                <SignalTable rows={data.signals} onRow={setSel} maxHeight="72vh" />
              ) : (
                <EmptyState title="No signals match"
                            detail="Try widening the date range or clearing one of the filters."
                            action={<button type="button" className="btn" onClick={reset}>Clear filters</button>} />
              )}
              {data.total > PAGE && (
                <div className="pagination" aria-label="Signal pages">
                  <button type="button" className="btn" disabled={offset === 0}
                          onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Previous</button>
                  <span className="muted">Page {Math.floor(offset / PAGE) + 1} of {Math.ceil(data.total / PAGE)}</span>
                  <button type="button" className="btn" disabled={offset + PAGE >= data.total}
                          onClick={() => setOffset(offset + PAGE)}>Next →</button>
                </div>
              )}
            </Card>
          )}
        </div>
        <SignalDetail signal={sel} onClose={() => setSel(null)} />
      </div>
    </div>
  )
}
