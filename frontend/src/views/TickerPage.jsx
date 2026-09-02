import React, { useEffect, useState } from 'react'
import { api, PRODUCER_META } from '../api.js'
import { fmtPct, fmtPx, fmtTs } from '../format.js'
import { Card, EmptyState, ErrorBox, ProducerTag, Spinner, Stat, SymbolLinks, Tag } from '../ui.jsx'
import { HistoryChart, PriceChart } from '../charts.jsx'
import SignalTable from '../SignalTable.jsx'
import SignalDetail from '../SignalDetail.jsx'

// Everything the producers know about one ticker.
export default function TickerPage({ ticker }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [sel, setSel] = useState(null)
  const [interval, setChartInterval] = useState('5Min')
  const [windowSize, setWindowSize] = useState('5D')
  const [chartMode, setChartMode] = useState('candles')
  const [chartData, setChartData] = useState(null)
  const [chartErr, setChartErr] = useState(null)
  const [chartLoading, setChartLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    setData(null); setErr(null)
    const load = () => api(`ticker/${ticker}`, null, { signal: controller.signal })
      .then((next) => { setData(next); setErr(null) })
      .catch((nextErr) => { if (nextErr.name !== 'AbortError') setErr(nextErr) })
    load()
    const timer = setInterval(load, 60000)
    return () => { clearInterval(timer); controller.abort() }
  }, [ticker])

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
        if (nextErr.name !== 'AbortError') {
          setChartErr(nextErr); setChartLoading(false)
        }
      })
    setChartData(null); setChartErr(null); setChartLoading(true)
    load()
    const timer = setInterval(load, 60000)
    return () => { clearInterval(timer); controller.abort() }
  }, [ticker, interval, windowSize])

  if (err) return <ErrorBox err={err} />
  if (!data) return <Spinner />

  const s = data.stats
  const intradayReady = interval !== '1Day' && chartData?.series?.length > 1
  const chartSeries = intradayReady ? chartData.series : data.series
  const chartSignals = intradayReady ? chartData.signals : data.signals
  const markers = chartSignals.map((x) => ({
    date: x.date,
    producer: x.producer,
    decision: x.decision,
    chart_time: x.chart_time,
  }))
  const last = chartSeries[chartSeries.length - 1]
  const stale = data.last_scored && data.latest_run && data.last_scored < data.latest_run
  const historyEntries = Object.entries(data.history || {}).filter(([, rows]) => rows?.length)
  const scoredDays = Math.max(0, ...historyEntries.map(([, rows]) => rows.length))
  const thresholds = { lstm: 0.2, intrinsic: 0.8 }

  return (
    <div>
      <div className="crumb">
        <a className="dlink" href="#/" onClick={(e) => {
          if (window.history.length > 1) { e.preventDefault(); window.history.back() }
        }}>← back</a>
        <h1 className="crumb-title">{data.ticker}</h1>
        {s.producers.length
          ? s.producers.map((p) => <ProducerTag key={p} producer={p} />)
          : <span className="muted small">scored, never signaled</span>}
        {data.insights?.has_action_warning && (
          <Tag kind="warn" title="Corporate-action review flag; only affected return windows are excluded">
            CA
          </Tag>
        )}
        <SymbolLinks ticker={data.ticker} />
      </div>

      {stale && (
        <div className="stale-banner">
          <b>Not scored since {data.last_scored}.</b>{' '}
          {data.ticker} dropped out of the producers&apos; universe after that date, so
          the price line, &ldquo;since&rdquo; returns and up/down status on this page are
          frozen as of {data.last_scored} — not current. Latest producer run: {data.latest_run}.
        </div>
      )}

      <Card className="ticker-stat-card">
        <div className="stat-row">
          <Stat label="latest close" value={last ? fmtPx(last.close ?? last.px) : '–'}
                sub={last?.timestamp ? fmtTs(last.timestamp) : last?.date} />
          <Stat label={intradayReady ? 'bar range' : 'day range'}
                value={last ? `${fmtPx(last.low)} – ${fmtPx(last.high)}` : '–'}
                sub={last?.open != null ? `open ${fmtPx(last.open)}` : null} />
          <Stat label={intradayReady ? 'bar volume' : 'volume'} value={formatVolume(last?.volume)}
                sub={intradayReady
                  ? `${interval} · Alpaca IEX`
                  : data.price_build_running ? 'price refresh running'
                    : `refreshes every ${Math.round((data.price_refresh_seconds || 300) / 60)}m`} />
          <Stat label="BUY signals" value={s.n_signals}
                sub={s.first_signal ? `${s.first_signal} → ${s.last_signal}` : null} />
          <Stat label="5d win rate" value={s.ret_5d.win_rate === null ? '–' : fmtPct(s.ret_5d.win_rate, 0)}
                sub={s.ret_5d.n ? `n=${s.ret_5d.n}` : null} />
          <Stat label="5d avg" value={s.ret_5d.avg === null ? '–' : fmtPct(s.ret_5d.avg)}
                cls={s.ret_5d.avg > 0 ? 'pos' : s.ret_5d.avg < 0 ? 'neg' : ''} />
          <Stat label="scored days" value={scoredDays} />
        </div>
      </Card>

      <Card className="ticker-chart-card" title="Price — signal points marked"
            right={<ChartControls interval={interval} setInterval={setChartInterval}
                                  windowSize={windowSize} setWindowSize={setWindowSize}
                                  mode={chartMode} setMode={setChartMode} />}>
        {chartErr && (
          <div className="inline-notice">
            Intraday feed is temporarily unavailable; showing daily bars. {chartErr.message}
          </div>
        )}
        {chartLoading && interval !== '1Day' ? <Spinner /> : (
          <>
            <div className="chart-source muted small">
              {intradayReady
                ? `${windowSize} window · ${interval} OHLCV through ${fmtTs(chartData.as_of)} · Alpaca IEX`
                : `${windowSize} window · daily OHLCV through ${data.price_as_of || '–'}`}
              {data.insights?.has_action_warning && ' · CA review flagged'}
            </div>
            <PriceChart series={chartSeries} signals={markers} height={380}
                        controls={false} interval={interval}
                        range={windowSize} mode={chartMode} />
          </>
        )}
      </Card>

      <InsightCard insights={data.insights} />

      <div className="grid-2">
        {historyEntries.map(([name, rows]) => {
          const meta = PRODUCER_META[name] || { label: name, metric: 'metric' }
          return (
            <Card key={name} title={`${meta.label} ${meta.metric} over time`}>
              <HistoryChart history={rows} producer={name} threshold={thresholds[name]} />
            </Card>
          )
        })}
      </div>

      {!historyEntries.length && (
        <Card><EmptyState title="No score history" detail="This ticker has no retained daily model scores." /></Card>
      )}

      <Card title={`Signals for ${data.ticker}`}>
        <SignalTable rows={data.signals} onRow={setSel} hide={['ticker', 'spark']}
                     empty="Never signaled — only present in score files" />
      </Card>

      <SignalDetail signal={sel} onClose={() => setSel(null)} />
    </div>
  )
}

const INTERVALS = [
  ['1Min', '1m'],
  ['5Min', '5m'],
  ['15Min', '15m'],
  ['1Hour', '1h'],
  ['1Day', '1D'],
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

const MAX_INTERVAL_DAYS = {
  '1Min': 7,
  '5Min': 31,
  '15Min': 93,
  '1Hour': 366,
  '1Day': Infinity,
}

function ChartControls({
  interval, setInterval, windowSize, setWindowSize, mode, setMode,
}) {
  const changeInterval = (nextInterval) => {
    const maxDays = MAX_INTERVAL_DAYS[nextInterval]
    const selectedDays = WINDOWS.find(([value]) => value === windowSize)?.[2] || 5
    if (selectedDays > maxDays) {
      const fallback = [...WINDOWS]
        .reverse()
        .find(([, , days]) => days <= maxDays)?.[0] || '1D'
      setWindowSize(fallback)
    }
    setInterval(nextInterval)
  }
  return (
    <div className="ticker-chart-controls">
      <div className="chart-ranges" aria-label="Chart window">
        {WINDOWS.map(([value, label, days]) => (
          <button key={value} type="button"
                  className={`chart-control ${windowSize === value ? 'active' : ''}`}
                  disabled={days > MAX_INTERVAL_DAYS[interval]}
                  aria-pressed={windowSize === value}
                  onClick={() => setWindowSize(value)}>
            {label}
          </button>
        ))}
      </div>
      <div className="chart-ranges" aria-label="Time per bar">
        {INTERVALS.map(([value, label]) => (
          <button key={value} type="button"
                  className={`chart-control ${interval === value ? 'active' : ''}`}
                  aria-pressed={interval === value}
                  onClick={() => changeInterval(value)}>
            {label}
          </button>
        ))}
      </div>
      <div className="chart-ranges" aria-label="Chart style">
        {[
          ['candles', 'Candles'],
          ['ohlc', 'OHLC'],
          ['line', 'Line'],
          ['area', 'Area'],
        ].map(([value, label]) => (
          <button key={value} type="button"
                  className={`chart-control ${mode === value ? 'active' : ''}`}
                  aria-pressed={mode === value}
                  onClick={() => setMode(value)}>
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}

function formatVolume(value) {
  if (value === null || value === undefined) return '–'
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)}K`
  return Math.round(value).toLocaleString()
}

function InsightCard({ insights }) {
  if (!insights) return null
  const counts = insights.decision_counts || {}
  const latest = insights.latest_signal
  const scores = Object.entries(insights.latest_scores || {})
  return (
    <Card title="Signal insights"
          right={<span className="tag tag-ok">available</span>}>
      <div className="stat-row">
        <Stat label="signal activity"
              value={`${counts.BUY || 0} buy · ${counts.SELL || 0} sell`}
              sub={counts.WATCH ? `${counts.WATCH} watch` : 'no watch signals'} />
        <Stat label="latest signal"
              value={latest ? `${latest.decision} · ${latest.producer}` : '–'}
              sub={latest?.date} />
        <Stat label="chart coverage" value={`${insights.price_bars || 0} sessions`}
              sub={insights.price_from
                ? `${insights.price_from} → ${insights.price_through}` : null} />
      </div>
      {scores.length > 0 && (
        <div className="latest-readings">
          <span className="muted small">Latest model readings</span>
          {scores.map(([producer, reading]) => (
            <span className="reading-chip" key={producer}>
              <ProducerTag producer={producer} />{' '}
              {reading.metric == null ? 'no metric' : Number(reading.metric).toFixed(3)}
              <span className="muted"> · {reading.date}</span>
            </span>
          ))}
        </div>
      )}
      {insights.has_action_warning && (
        <div className="muted small insight-note">
          <Tag kind="warn" title={insights.blocked_action_ids?.join(', ')}>CA</Tag>
          {insights.performance_excluded_count
            ? `${insights.performance_excluded_count} signal return window(s) cross an uncertain action boundary.`
            : 'Corporate-action review flagged; current signal returns stay on one comparable basis.'}
        </div>
      )}
    </Card>
  )
}
