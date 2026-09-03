import React, { useDeferredValue, useEffect, useMemo, useState } from 'react'
import { api, PRODUCER_META } from '../api.js'
import { fmtPct } from '../format.js'
import { EmptyState, ErrorBox, Spinner, pctToFraction } from '../ui.jsx'
import SignalTable from '../SignalTable.jsx'
import { SignalInspector } from '../SignalDetail.jsx'

const PAGE = 75

// Design turn 4a, "query bar": nothing to the left of the data. Filters are
// one band under the header, whatever is active restates itself as a chip you
// can dismiss, prev/next becomes one tall scroll region, and the modal becomes
// an inspector docked beside the table -- no overlay, no scroll lock, the
// table stays live behind it.
const EXPLORE_COLS = [
  'when', 'producer', 'ticker_plain', 'call', 'metric',
  'entry', 'ret_1d', 'ret_5d', 'ret_20d', 'since',
  'spark', 'status',
]
const EXPLORE_GROUPS = [
  { label: 'Signal', span: 5 },
  { label: 'Price', span: 1 },
  { label: 'Returns', span: 4 },
  { label: 'Tracking', span: 2 },
]

const OUTCOMES = [
  ['', 'any outcome'],
  ['up', 'up since signal'],
  ['down', 'down since signal'],
  ['flat', 'flat since signal'],
  ['pending', 'pending next close'],
  ['corporate_action_unresolved', 'corporate-action flagged'],
  ['no_px', 'no price coverage'],
]

export default function Explore({ query = {} }) {
  const [pages, setPages] = useState([])
  const [meta, setMeta] = useState(null)
  const [err, setErr] = useState(null)
  const [loading, setLoading] = useState(true)
  const [sel, setSel] = useState(null)

  const [producer, setProducer] = useState(query.producer || '')
  const [from, setFrom] = useState(query.from || '')
  const [to, setTo] = useState(query.to || '')
  const [buysOnly, setBuysOnly] = useState(query.buys !== '0')
  const [ticker, setTicker] = useState(query.ticker || '')
  const deferredTicker = useDeferredValue(ticker)
  const [status, setStatus] = useState(query.status || '')
  const [minMetric, setMinMetric] = useState(query.min || '')
  const [offset, setOffset] = useState(0)

  // TB-46: stop-loss / take-profit historical simulation. `stopPct`/`targetPct`
  // are whole-percent strings ("5") so the input never makes Jacob type a
  // decimal -- pctToFraction converts to the 0-1 fraction the API wants.
  const [stopPct, setStopPct] = useState(query.stop || '')
  const [targetPct, setTargetPct] = useState(query.target || '')
  const [exitWindow, setExitWindow] = useState(query.win || '20')
  const [trailing, setTrailing] = useState(query.trail === '1')

  const filterKey = [producer, from, to, buysOnly, deferredTicker, status, minMetric,
                     stopPct, targetPct, exitWindow, trailing].join('|')
  // A filter change restarts the scroll region at the top, not at whatever
  // depth the previous slice happened to be scrolled to.
  useEffect(() => { setOffset(0); setPages([]) }, [filterKey])

  useEffect(() => {
    const params = new URLSearchParams()
    if (producer) params.set('producer', producer)
    if (from) params.set('from', from)
    if (to) params.set('to', to)
    if (!buysOnly) params.set('buys', '0')
    if (ticker) params.set('ticker', ticker)
    if (status) params.set('status', status)
    if (producer && minMetric) params.set('min', minMetric)
    if (stopPct) params.set('stop', stopPct)
    if (targetPct) params.set('target', targetPct)
    if (exitWindow && exitWindow !== '20') params.set('win', exitWindow)
    if (trailing) params.set('trail', '1')
    history.replaceState(null, '', `#/explore${params.size ? `?${params}` : ''}`)
  }, [producer, from, to, buysOnly, ticker, status, minMetric,
      stopPct, targetPct, exitWindow, trailing])

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
      stop_pct: pctToFraction(stopPct),
      target_pct: pctToFraction(targetPct),
      exit_window: exitWindow || 20,
      trailing,
    }, { signal: controller.signal })
      .then((next) => {
        setMeta(next)
        setPages((prev) => (next.offset === 0 ? [next.signals] : [...prev, next.signals]))
        setErr(null)
      })
      .catch((nextErr) => { if (nextErr.name !== 'AbortError') setErr(nextErr) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [filterKey, offset])

  const rows = useMemo(() => pages.flat(), [pages])
  const total = meta?.total ?? 0
  const more = rows.length < total

  // Infinite scroll: ask for the next page while there is still a screenful
  // of rows below the fold, so the scroll never actually stops.
  const onScroll = (e) => {
    if (loading || !more) return
    const el = e.currentTarget
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 600) setOffset(rows.length)
  }

  const reset = () => {
    setProducer(''); setFrom(''); setTo(''); setBuysOnly(true)
    setTicker(''); setStatus(''); setMinMetric('')
    setStopPct(''); setTargetPct(''); setExitWindow('20'); setTrailing(false)
  }

  const chips = [
    producer && { key: 'producer', label: PRODUCER_META[producer]?.label || producer, clear: () => setProducer('') },
    ticker && { key: 'ticker', label: `ticker ~ ${ticker}`, clear: () => setTicker('') },
    from && { key: 'from', label: `from ${from}`, clear: () => setFrom('') },
    to && { key: 'to', label: `to ${to}`, clear: () => setTo('') },
    status && { key: 'status', label: OUTCOMES.find(([v]) => v === status)?.[1] || status, clear: () => setStatus('') },
    producer && minMetric && {
      key: 'min', label: `${PRODUCER_META[producer]?.metric} ≥ ${minMetric}`, clear: () => setMinMetric(''),
    },
    !buysOnly && { key: 'buys', label: 'all decisions', clear: () => setBuysOnly(true) },
    stopPct && { key: 'stop', label: `${trailing ? 'trailing ' : ''}stop ${stopPct}%`, clear: () => setStopPct('') },
    targetPct && { key: 'target', label: `target ${targetPct}%`, clear: () => setTargetPct('') },
    exitWindow !== '20' && { key: 'win', label: `max hold ${exitWindow}d`, clear: () => setExitWindow('20') },
  ].filter(Boolean)

  const summary = meta?.summary || {}
  const sim = summary.sim
  const metricName = producer ? PRODUCER_META[producer]?.metric : null
  const rule = pctToFraction(stopPct) != null || pctToFraction(targetPct) != null
    ? {
        stop: pctToFraction(stopPct) ?? null,
        target: pctToFraction(targetPct) ?? null,
        window: Number(exitWindow) || 20,
        trailing,
      }
    : null

  return (
    <div className="explore">
      <div className="ledger-head explore-head">
        <div>
          <h1 tabIndex="-1">
            {total.toLocaleString()} signals <span className="muted">match</span>
          </h1>
          <div className="ledger-meta">
            {[
              producer ? PRODUCER_META[producer]?.label : 'all producers',
              buysOnly ? 'buy only' : 'all decisions',
              from || to ? `${from || '…'} → ${to || '…'}` : 'all dates',
              ticker ? `ticker ~ ${ticker}` : null,
              producer && minMetric ? `${metricName} ≥ ${minMetric}` : null,
              rule ? `exits: ${trailing ? 'trailing ' : ''}stop ${stopPct || '—'}% / target ${targetPct || '—'}% / ${exitWindow}d hold` : null,
            ].filter(Boolean).join(' · ')}
          </div>
        </div>
        <div className="slice-stats" aria-live="polite">
          <SliceStat label="win rate 1d" v={summary.wr_1d == null ? '–' : fmtPct(summary.wr_1d, 0)} />
          <SliceStat label="win rate 5d" v={summary.wr_5d == null ? '–' : fmtPct(summary.wr_5d, 0)} />
          <SliceStat label="avg 5d" v={summary.avg_5d == null ? '–' : fmtPct(summary.avg_5d)}
                     cls={summary.avg_5d > 0 ? 'pos' : summary.avg_5d < 0 ? 'neg' : ''} />
          <SliceStat label="avg since" v={summary.avg_since == null ? '–' : fmtPct(summary.avg_since)}
                     cls={summary.avg_since > 0 ? 'pos' : summary.avg_since < 0 ? 'neg' : ''} />
          {sim && (
            <div className="slice-rules">
              <div className="stat-label">closed by rule</div>
              <div className="rule-counts">
                <span>stop <b className="neg">{sim.counts.stop}</b></span>
                <span>target <b className="pos">{sim.counts.target}</b></span>
                <span>max hold <b>{sim.counts.held}</b></span>
                <span className="muted">open {sim.counts.open}</span>
                {sim.n_blocked > 0 && <span className="muted">CA-blocked {sim.n_blocked}</span>}
              </div>
              <div className="stat-sub">
                every return above is scored at its rule exit, not the last close
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="query-bar">
        <Field label="Producer">
          <div className="seg" role="group" aria-label="Producer">
            {[['', 'All'], ...Object.entries(PRODUCER_META).map(([k, m]) => [k, m.label])]
              .map(([value, label]) => (
                <button key={value || 'all'} type="button"
                        className={`seg-btn ${producer === value ? 'active' : ''}`}
                        aria-pressed={producer === value}
                        onClick={() => setProducer(value)}>{label}</button>
              ))}
          </div>
        </Field>
        <Field label="Ticker contains">
          <input value={ticker} onChange={(e) => setTicker(e.target.value)}
                 placeholder="e.g. NVDA" style={{ width: 120 }} aria-label="Ticker contains" />
        </Field>
        <Field label="Trade date range">
          <div className="date-range">
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From" />
            <span className="muted">→</span>
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="To" />
          </div>
        </Field>
        <Field label="Outcome">
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Outcome"
                  style={{ width: 178 }}>
            {OUTCOMES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            {!buysOnly && <option value="no_action">not a BUY</option>}
          </select>
        </Field>
        <Field label={`Min ${metricName || 'metric'}`}>
          <input type="number" step="0.01" value={minMetric} disabled={!producer}
                 onChange={(e) => setMinMetric(e.target.value)} style={{ width: 84 }}
                 aria-label="Minimum metric"
                 title={producer ? undefined : 'choose a producer first — the three metrics are not comparable'}
                 placeholder={producer ? '0.25' : 'producer?'} />
        </Field>

        <div className="query-rules">
          <div className="stat-label">Exit rules — scored into every return</div>
          <div className="rule-inputs">
            <label>{trailing ? 'trailing stop' : 'stop'}
              <span className="unit"><input type="number" step="0.5" min="0" value={stopPct}
                     onChange={(e) => setStopPct(e.target.value)} /><span>%</span></span>
            </label>
            <label>target
              <span className="unit"><input type="number" step="0.5" min="0" value={targetPct}
                     onChange={(e) => setTargetPct(e.target.value)} /><span>%</span></span>
            </label>
            <label>max hold
              <span className="unit"><input type="number" step="1" min="1" max="252" value={exitWindow}
                     onChange={(e) => setExitWindow(e.target.value)} /><span>d</span></span>
            </label>
            <label className="check">
              <input type="checkbox" checked={trailing} onChange={(e) => setTrailing(e.target.checked)} />
              trailing
            </label>
          </div>
        </div>

        <label className="check query-check">
          <input type="checkbox" checked={buysOnly} onChange={(e) => setBuysOnly(e.target.checked)} />
          BUY only
        </label>

        <div className="query-actions">
          <span className="muted small">{chips.length} filter{chips.length === 1 ? '' : 's'} active</span>
          <button type="button" className="btn" onClick={reset} disabled={!chips.length}>Clear all</button>
        </div>
      </div>

      {chips.length > 0 && (
        <div className="chips">
          <span className="stat-label">Applied</span>
          {chips.map((c) => (
            <span key={c.key} className="chip">
              {c.label}
              <button type="button" onClick={c.clear} aria-label={`Remove filter ${c.label}`}>×</button>
            </span>
          ))}
          <span className="muted small">— the link is shareable, filters live in the URL</span>
        </div>
      )}

      {err && <ErrorBox err={err} />}

      <div className="explore-body">
        <div className="explore-results" aria-busy={loading}>
          {!meta && loading ? <Spinner /> : rows.length ? (
            <SignalTable rows={rows} cols={EXPLORE_COLS} groups={EXPLORE_GROUPS}
                         sparkWidth={122} maxHeight="72vh" onScroll={onScroll}
                         className={loading ? 'is-loading' : ''}
                         onSelect={setSel} onRow={setSel} selectedId={sel?.id}
                         footer={
                           <span className="muted small">
                             {more
                               ? `${loading ? 'loading next ' + PAGE + ' · ' : ''}${rows.length.toLocaleString()} of ${total.toLocaleString()} loaded — keep scrolling`
                               : `all ${total.toLocaleString()} loaded`}
                           </span>
                         } />
          ) : (
            <EmptyState title="No signals match"
                        detail="Try widening the date range or dismissing one of the chips."
                        action={<button type="button" className="btn" onClick={reset}>Clear all</button>} />
          )}
        </div>
        {sel && <SignalInspector signal={sel} rule={rule} onClose={() => setSel(null)} />}
      </div>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div className="query-field">
      <div className="stat-label">{label}</div>
      {children}
    </div>
  )
}

function SliceStat({ label, v, cls }) {
  return (
    <div className="slice-stat">
      <div className="stat-label">{label}</div>
      <div className={`mini-stat-v ${cls || ''}`}>{v}</div>
    </div>
  )
}
