import React, { useEffect, useMemo, useState } from 'react'
import { api, PRODUCER_META } from '../api.js'
import { fmtPct, fmtPx, fmtTs } from '../format.js'
import {
  ErrorBox, ExitRules, ProducerTag, Spinner, SymbolLinks, Tag, pctToFraction,
} from '../ui.jsx'
import { chartWindow, MetricLane, PriceChart } from '../charts.jsx'
import SignalTable from '../SignalTable.jsx'
import SignalDetail from '../SignalDetail.jsx'
import { C } from '../theme.js'

// Design turn 7a, "aligned canvas": price and every model score share one
// x-axis and one window, so a score crossing its threshold lines up with the
// bar it fired on. The seven-stat row becomes price identity plus four, the
// sixteen chart buttons become one control line, and the insights card is
// dissolved into a standing rail. Selecting a ledger row drops a cursor into
// every lane -- the chart is the detail view.
const TICKER_COLS = [
  'when', 'producer', 'call', 'metric', 'entry',
  'ret_1d', 'ret_5d', 'ret_20d', 'since', 'since_bar', 'sim', 'status',
]

const INTERVALS = [
  ['1Day', '1 day'],
  ['1Hour', '1 hour'],
  ['15Min', '15 min'],
  ['5Min', '5 min'],
  ['1Min', '1 min'],
]

const WINDOWS = [
  ['1D', '1D', 1],
  ['5D', '5D', 5],
  ['1M', '1M', 31],
  ['3M', '3M', 93],
  ['6M', '6M', 186],
  ['1Y', '1Y', 366],
  ['ALL', 'All', Infinity],
]

const MAX_INTERVAL_DAYS = { '1Min': 7, '5Min': 31, '15Min': 93, '1Hour': 366, '1Day': Infinity }

// The score at which each daily producer starts publishing. Foundry is
// event-driven and has no standing threshold, so its lane draws without one.
const THRESHOLDS = { lstm: 0.2, intrinsic: 0.8 }

export default function TickerPage({ ticker }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [sel, setSel] = useState(null)
  const [detail, setDetail] = useState(null)
  const [producer, setProducer] = useState('')
  const [interval, setChartInterval] = useState('1Day')
  const [windowSize, setWindowSize] = useState('6M')
  const [chartMode, setChartMode] = useState('candles')
  const [showSignals, setShowSignals] = useState(true)
  const [showLevels, setShowLevels] = useState(true)
  const [chartData, setChartData] = useState(null)
  const [chartErr, setChartErr] = useState(null)
  const [chartLoading, setChartLoading] = useState(false)

  // TB-46: stop-loss / take-profit historical simulation, same control as
  // Explore's (see ui.jsx ExitRules) but local to this page -- no URL wiring,
  // just refetching /api/ticker/{t} with the sim params attached.
  const [stopPct, setStopPct] = useState('')
  const [targetPct, setTargetPct] = useState('')
  const [exitWindow, setExitWindow] = useState('20')
  const [trailing, setTrailing] = useState(false)
  const clearExitRule = () => { setStopPct(''); setTargetPct(''); setExitWindow('20'); setTrailing(false) }

  useEffect(() => {
    const controller = new AbortController()
    setData(null); setErr(null); setSel(null)
    const load = () => api(`ticker/${ticker}`, {
      stop_pct: pctToFraction(stopPct),
      target_pct: pctToFraction(targetPct),
      exit_window: exitWindow || 20,
      trailing,
    }, { signal: controller.signal })
      .then((next) => { setData(next); setErr(null) })
      .catch((nextErr) => { if (nextErr.name !== 'AbortError') setErr(nextErr) })
    load()
    const timer = setInterval(load, 60000)
    return () => { clearInterval(timer); controller.abort() }
  }, [ticker, stopPct, targetPct, exitWindow, trailing])

  useEffect(() => {
    if (interval === '1Day') {
      setChartData(null); setChartErr(null); setChartLoading(false)
      return undefined
    }
    const controller = new AbortController()
    const load = () => api(
      `ticker/${ticker}/chart`,
      { interval, window: windowSize },
      { signal: controller.signal },
    )
      .then((next) => { setChartData(next); setChartErr(null); setChartLoading(false) })
      .catch((nextErr) => {
        if (nextErr.name !== 'AbortError') { setChartErr(nextErr); setChartLoading(false) }
      })
    setChartData(null); setChartErr(null); setChartLoading(true)
    load()
    const timer = setInterval(load, 60000)
    return () => { clearInterval(timer); controller.abort() }
  }, [ticker, interval, windowSize])

  const intradayReady = interval !== '1Day' && chartData?.series?.length > 1
  const rawSeries = intradayReady ? chartData.series : (data?.series || [])
  // One window, computed once: the price lane and every score lane are handed
  // the identical x values, which is the whole point of the layout.
  const visible = useMemo(
    () => (intradayReady ? rawSeries : chartWindow(rawSeries, windowSize)),
    [rawSeries, windowSize, intradayReady],
  )
  const lastOfDate = useMemo(() => {
    const map = {}
    for (const point of visible) map[point.date] = point.timestamp || point.date
    return map
  }, [visible])

  const lanes = useMemo(() => {
    if (!data) return []
    return Object.entries(data.history || {})
      .filter(([, rows]) => rows?.length)
      .map(([name, rows]) => {
        const byDate = Object.fromEntries(rows.map((r) => [r.date, r.metric]))
        // Score lanes are daily; on an intraday window each score sits on that
        // session's last bar so it lands under the day it was published.
        const points = visible.map((point) => ({
          chart_x: point.timestamp || point.date,
          value: (point.timestamp || point.date) === lastOfDate[point.date]
            ? (byDate[point.date] ?? null) : null,
        }))
        const values = rows.map((r) => r.metric).filter((v) => v != null)
        const hi = Math.max(THRESHOLDS[name] ?? 0, ...values, 0)
        return {
          name, points, rows,
          threshold: THRESHOLDS[name],
          domain: [0, Number((hi * 1.1).toFixed(3)) || 1],
        }
      })
  }, [data, visible, lastOfDate])

  if (err) return <ErrorBox err={err} />
  if (!data) return <Spinner />

  const s = data.stats
  const insights = data.insights || {}
  const signals = data.signals || []
  const rows = producer ? signals.filter((r) => r.producer === producer) : signals
  const last = visible[visible.length - 1]
  const prev = visible[visible.length - 2]
  const change = last && prev ? (last.close ?? last.px) - (prev.close ?? prev.px) : null
  const changePct = change != null && prev ? change / (prev.close ?? prev.px) : null
  const stale = data.last_scored && data.latest_run && data.last_scored < data.latest_run
  const scoredDays = Math.max(0, ...lanes.map((l) => l.rows.length))

  const rule = pctToFraction(stopPct) != null || pctToFraction(targetPct) != null
    ? { stop: pctToFraction(stopPct) ?? null, target: pctToFraction(targetPct) ?? null,
        window: Number(exitWindow) || 20, trailing }
    : null

  // "At exit" is the real question a holding window asks. Prefer the rule
  // exits when a rule is on, otherwise the producer's own published exit.
  const closed = rule
    ? signals.filter((r) => r.sim_return != null)
    : signals.filter((r) => r.exit_state === 'closed' && r.exit_return != null)
  const exitReturns = closed.map((r) => (rule ? r.sim_return : r.exit_return))
  const exitWin = exitReturns.length
    ? exitReturns.filter((v) => v > 0).length / exitReturns.length : null
  const exitAvg = exitReturns.length
    ? exitReturns.reduce((a, b) => a + b, 0) / exitReturns.length : null

  const cursor = sel ? (lastOfDate[sel.date] ?? sel.date) : undefined
  const levels = showLevels && rule && sel?.entry_px != null
    ? [
        rule.stop != null && !rule.trailing && {
          y: sel.entry_px * (1 - rule.stop), color: C.pendingText, label: `stop ${fmtPct(rule.stop, 0)}`,
        },
        rule.target != null && {
          y: sel.entry_px * (1 + rule.target), color: C.up, label: `target ${fmtPct(rule.target, 0)}`,
        },
      ].filter(Boolean)
    : []

  const changeCls = changePct > 0 ? 'pos' : changePct < 0 ? 'neg' : 'muted'

  return (
    <div className="ticker-page">
      {stale && (
        <div className="stale-banner">
          <b>Not scored since {data.last_scored}.</b>{' '}
          {data.ticker} dropped out of the producers&apos; universe after that date, so
          the price line, &ldquo;since&rdquo; returns and up/down status on this page are
          frozen as of {data.last_scored} — not current. Latest producer run: {data.latest_run}.
        </div>
      )}

      <div className="ticker-body">
        <div className="ticker-main">
          <div className="ticker-id">
            <div>
              <div className="crumb">
                <a className="dlink" href="#/" onClick={(e) => {
                  if (window.history.length > 1) { e.preventDefault(); window.history.back() }
                }}>← back</a>
                <h1 className="crumb-title" tabIndex="-1">{data.ticker}</h1>
                {s.producers.length
                  ? s.producers.map((p) => <ProducerTag key={p} producer={p} />)
                  : <span className="muted small">scored, never signaled</span>}
                {insights.has_action_warning && (
                  <Tag kind="warn" title="Corporate-action review flag; only affected return windows are excluded">CA</Tag>
                )}
                <SymbolLinks ticker={data.ticker} />
              </div>
              <div className="price-id">
                <span className="price-last">{last ? fmtPx(last.close ?? last.px) : '–'}</span>
                <span className={`price-change ${changeCls}`}>
                  {change == null ? '–'
                    : `${change > 0 ? '+' : ''}${change.toFixed(2)}  ${changePct > 0 ? '+' : ''}${(changePct * 100).toFixed(2)}%`}
                </span>
                <span className="muted small">
                  {last ? `O ${fmtPx(last.open)} · H ${fmtPx(last.high)} · L ${fmtPx(last.low)} · V ${formatVolume(last.volume)}` : 'no bars'}
                  {intradayReady
                    ? ` · ${interval} bar ${fmtTs(chartData.as_of)} · Alpaca IEX`
                    : ` · daily close ${data.price_as_of || '–'}`}
                  {data.price_build_running ? ' · price refresh running' : ''}
                </span>
              </div>
            </div>
            <div className="ticker-stats">
              <IdStat label="buy signals" v={s.n_signals}
                      sub={s.first_signal ? `${s.first_signal} → ${s.last_signal}` : null} />
              <IdStat label={rule ? 'win rate at rule exit' : 'win rate at exit'}
                      v={exitWin == null ? '–' : fmtPct(exitWin, 0)}
                      sub={exitReturns.length ? `n=${exitReturns.length} closed` : 'nothing closed yet'} />
              <IdStat label={rule ? 'avg at rule exit' : 'avg at exit'}
                      v={exitAvg == null ? '–' : fmtPct(exitAvg)}
                      cls={exitAvg > 0 ? 'pos' : exitAvg < 0 ? 'neg' : ''}
                      sub={s.ret_5d.avg == null ? null : `5d basis ${fmtPct(s.ret_5d.avg)}`} />
              <IdStat label="scored days" v={scoredDays}
                      sub={data.last_scored ? `last ${data.last_scored}` : null} />
            </div>
          </div>

          <div className="lane-controls">
            <div className="seg" role="group" aria-label="Chart window">
              {WINDOWS.map(([value, label, days]) => (
                <button key={value} type="button"
                        className={`seg-btn ${windowSize === value ? 'active' : ''}`}
                        disabled={days > MAX_INTERVAL_DAYS[interval]}
                        aria-pressed={windowSize === value}
                        onClick={() => setWindowSize(value)}>{label}</button>
              ))}
            </div>
            <label className="inline-label">bar
              <select value={interval} onChange={(e) => changeInterval(
                e.target.value, windowSize, setWindowSize, setChartInterval)}>
                {INTERVALS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label className="inline-label">style
              <select value={chartMode} onChange={(e) => setChartMode(e.target.value)}>
                {['candles', 'ohlc', 'line', 'area'].map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </label>
            <label className="check">
              <input type="checkbox" checked={showSignals}
                     onChange={(e) => setShowSignals(e.target.checked)} />
              signal markers
            </label>
            <label className="check">
              <input type="checkbox" checked={showLevels} disabled={!rule}
                     onChange={(e) => setShowLevels(e.target.checked)} />
              exit levels
            </label>
            <span className="muted small lane-note">
              1m bars only reach 7d · 5m 31d · 15m 93d — the window pills grey out instead of failing
            </span>
          </div>

          {chartErr && (
            <div className="inline-notice">
              Intraday feed is temporarily unavailable; showing daily bars. {chartErr.message}
            </div>
          )}

          <div className="lane">
            <div className="lane-label">
              <div className="lane-name">price</div>
              <div className="muted small">
                {intradayReady ? `${interval} OHLCV` : 'daily OHLCV'}<br />
                through {intradayReady ? (chartData.as_of || '').slice(0, 10) : data.price_as_of || '–'}
              </div>
            </div>
            <div className="lane-plot">
              {chartLoading && interval !== '1Day' ? <Spinner /> : (
                <PriceChart series={visible} range="ALL" mode={chartMode} controls={false}
                            interval={interval} height={252}
                            signals={showSignals ? (intradayReady ? chartData.signals : signals) : []}
                            showSignals={showSignals} cursor={cursor} levels={levels} />
              )}
            </div>
          </div>

          {lanes.map((lane) => {
            const meta = PRODUCER_META[lane.name] || { label: lane.name, metric: 'metric' }
            return (
              <div className="lane" key={lane.name}>
                <div className="lane-label">
                  <div className="lane-name">{meta.label}</div>
                  <div className="muted small">
                    {meta.metric}
                    {lane.threshold != null && <><br />{lane.threshold} thr</>}
                  </div>
                </div>
                <div className="lane-plot">
                  <MetricLane points={lane.points} color={meta.color} cursor={cursor}
                              threshold={lane.threshold} domain={lane.domain} />
                </div>
              </div>
            )
          })}

          {!lanes.length && (
            <div className="muted small lane-empty">
              No retained daily model scores for {data.ticker} — nothing to lane up against the price.
            </div>
          )}
          {!data.history?.foundry?.length && (
            <div className="muted small lane-empty">
              Foundry is event-driven and publishes no daily score series, so it appears
              on the price lane as markers only.
            </div>
          )}

          <div className="ledger-head ticker-ledger-head">
            <div>
              <h2 className="ledger-title">{rows.length} signals for {data.ticker}</h2>
              <div className="ledger-meta">
                selecting a row drops the cursor into every lane above — the chart is the detail view
              </div>
            </div>
            <div className="seg" role="group" aria-label="Filter by producer">
              {['', ...s.producers]
                .map((value) => [value, value ? PRODUCER_META[value]?.label || value : 'All'])
                .map(([value, label]) => (
                  <button key={value || 'all'} type="button"
                          className={`seg-btn ${producer === value ? 'active' : ''}`}
                          aria-pressed={producer === value}
                          onClick={() => setProducer(value)}>{label}</button>
                ))}
            </div>
          </div>

          <SignalTable rows={rows} cols={TICKER_COLS}
                       onSelect={setSel} onRow={setDetail} selectedId={sel?.id}
                       empty="Never signaled — only present in score files" />
        </div>

        <aside className="ticker-rail">
          <section className="rail-card">
            <h2 className="card-title">Latest scores</h2>
            {Object.entries(insights.latest_scores || {}).length ? (
              Object.entries(insights.latest_scores).map(([name, reading]) => {
                const thr = THRESHOLDS[name]
                const over = thr != null && reading.metric != null ? reading.metric >= thr : null
                return (
                  <div className="reading" key={name}>
                    <ProducerTag producer={name} />
                    <span className="muted small">{reading.date}</span>
                    <b>{reading.metric == null ? 'no metric' : Number(reading.metric).toFixed(3)}</b>
                    <span className={`small ${over === null ? 'muted' : over ? 'pos' : 'muted'}`}>
                      {over === null ? 'no standing threshold' : over ? `≥ ${thr}` : `below ${thr}`}
                    </span>
                  </div>
                )
              })
            ) : <div className="muted small">no retained scores</div>}
          </section>

          <section className="rail-card">
            <h2 className="card-title">Exit rules</h2>
            <ExitRules
              stopPct={stopPct} setStopPct={setStopPct}
              targetPct={targetPct} setTargetPct={setTargetPct}
              exitWindow={exitWindow} setExitWindow={setExitWindow}
              trailing={trailing} setTrailing={setTrailing}
              onClear={clearExitRule}
            />
            {rule ? <RuleCounts signals={signals} /> : (
              <div className="muted small">
                no rule set — every return on this page runs to the last close.
              </div>
            )}
          </section>

          <section className="rail-card">
            <h2 className="card-title">Signal activity</h2>
            <div className="rail-quad">
              <IdStat label="calls"
                      v={`${insights.decision_counts?.BUY || 0} buy · ${insights.decision_counts?.SELL || 0} sell`}
                      sub={`${insights.decision_counts?.WATCH || 0} watch`} />
              <IdStat label="latest"
                      v={insights.latest_signal ? `${insights.latest_signal.decision} · ${insights.latest_signal.producer}` : '–'}
                      sub={insights.latest_signal?.date} />
              <IdStat label="coverage" v={`${insights.price_bars || 0} sessions`}
                      sub={insights.price_from ? `${insights.price_from} → ${insights.price_through}` : null} />
              <IdStat label="best / worst"
                      v={<BestWorst signals={signals} rule={rule} />}
                      sub={rule ? 'both rule exits' : 'since signal'} />
            </div>
          </section>

          {insights.has_action_warning && (
            <section className="rail-card rail-note">
              <Tag kind="warn" title={insights.blocked_action_ids?.join(', ')}>CA</Tag>
              <span className="muted small">
                {insights.performance_excluded_count
                  ? `${insights.performance_excluded_count} return window(s) cross an uncertain corporate-action boundary and are excluded from the averages above. Only those windows — the rest of the record stands.`
                  : 'Corporate-action review flagged; current signal returns stay on one comparable basis.'}
              </span>
            </section>
          )}
        </aside>
      </div>

      <SignalDetail signal={detail} rule={rule} onClose={() => setDetail(null)} />
    </div>
  )
}

// A bar size the current window cannot cover would 400 at the gateway, so the
// window falls back to the longest one that interval can serve.
function changeInterval(nextInterval, windowSize, setWindowSize, setChartInterval) {
  const maxDays = MAX_INTERVAL_DAYS[nextInterval]
  const selectedDays = WINDOWS.find(([value]) => value === windowSize)?.[2] || 5
  if (selectedDays > maxDays) {
    const fallback = [...WINDOWS].reverse().find(([, , days]) => days <= maxDays)?.[0] || '1D'
    setWindowSize(fallback)
  }
  setChartInterval(nextInterval)
}

function IdStat({ label, v, sub, cls }) {
  return (
    <div className="id-stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${cls || ''}`}>{v}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

function RuleCounts({ signals }) {
  const counts = { stop: 0, target: 0, held: 0, open: 0 }
  let blocked = 0
  for (const r of signals) {
    if (r.sim_blocked_reason) blocked += 1
    if (r.sim_outcome in counts) counts[r.sim_outcome] += 1
  }
  const producerExits = signals.filter((r) => r.exit_state === 'closed').length
  return (
    <>
      <div className="rule-counts">
        <span>stop <b className="neg">{counts.stop}</b></span>
        <span>target <b className="pos">{counts.target}</b></span>
        <span>max hold <b>{counts.held}</b></span>
        <span>producer exit <b>{producerExits}</b></span>
        <span className="muted">open {counts.open}</span>
        {blocked > 0 && <span className="muted">CA-blocked {blocked}</span>}
      </div>
      <div className="stat-sub">
        every return on this page is fixed at its rule exit, not the last close
      </div>
    </>
  )
}

function BestWorst({ signals, rule }) {
  const values = signals
    .map((r) => (rule ? r.sim_return : r.ret_since))
    .filter((v) => v != null)
  if (!values.length) return <span className="muted">–</span>
  return (
    <span>
      <span className="pos">{fmtPct(Math.max(...values))}</span>
      <span className="muted"> / </span>
      <span className="neg">{fmtPct(Math.min(...values))}</span>
    </span>
  )
}

function formatVolume(value) {
  if (value === null || value === undefined) return '–'
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)}K`
  return Math.round(value).toLocaleString()
}
