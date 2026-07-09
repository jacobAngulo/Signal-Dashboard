import React, { useEffect, useState } from 'react'
import { api, PRODUCER_META } from '../api.js'
import { fmtPct, fmtPx } from '../format.js'
import { Card, ErrorBox, ProducerTag, Spinner, Stat } from '../ui.jsx'
import { HistoryChart, PriceChart } from '../charts.jsx'
import SignalTable from '../SignalTable.jsx'
import SignalDetail from '../SignalDetail.jsx'

// Everything the producers know about one ticker.
export default function TickerPage({ ticker }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [sel, setSel] = useState(null)

  useEffect(() => {
    setData(null); setErr(null)
    api(`ticker/${ticker}`).then(setData).catch(setErr)
  }, [ticker])

  if (err) return <ErrorBox err={err} />
  if (!data) return <Spinner />

  const s = data.stats
  const markers = data.signals.filter((x) => x.decision === 'BUY')
    .map((x) => ({ date: x.date, producer: x.producer }))
  const last = data.series[data.series.length - 1]
  const stale = data.last_scored && data.latest_run && data.last_scored < data.latest_run
  const historyEntries = Object.entries(data.history || {}).filter(([, rows]) => rows?.length)
  const scoredDays = Math.max(0, ...historyEntries.map(([, rows]) => rows.length))
  const thresholds = { lstm: 0.2, intrinsic: 0.8 }

  return (
    <div>
      <div className="crumb">
        <a className="dlink" href="#/" onClick={(e) => { e.preventDefault(); history.back() }}>← back</a>
        <span className="crumb-title">{data.ticker}</span>
        {s.producers.map((p) => <ProducerTag key={p} producer={p} />)}
      </div>

      {stale && (
        <div className="stale-banner">
          <b>Not scored since {data.last_scored}.</b>{' '}
          {data.ticker} dropped out of the producers&apos; universe after that date, so
          the price line, &ldquo;since&rdquo; returns and up/down status on this page are
          frozen as of {data.last_scored} — not current. Latest producer run: {data.latest_run}.
        </div>
      )}

      <Card>
        <div className="stat-row">
          <Stat label="last px" value={last ? fmtPx(last.px) : '–'} sub={last?.date} />
          <Stat label="BUY signals" value={s.n_signals}
                sub={s.first_signal ? `${s.first_signal} → ${s.last_signal}` : null} />
          <Stat label="5d win rate" value={s.ret_5d.win_rate === null ? '–' : fmtPct(s.ret_5d.win_rate, 0)}
                sub={s.ret_5d.n ? `n=${s.ret_5d.n}` : null} />
          <Stat label="5d avg" value={s.ret_5d.avg === null ? '–' : fmtPct(s.ret_5d.avg)}
                cls={s.ret_5d.avg > 0 ? 'pos' : s.ret_5d.avg < 0 ? 'neg' : ''} />
          <Stat label="scored days" value={scoredDays} />
        </div>
      </Card>

      <Card title="Price — every BUY signal marked"
            right={<span className="muted small">producer pre-close snapshots (~12:15–12:30 PT), not official closes</span>}>
        <PriceChart series={data.series} signals={markers} height={280} />
      </Card>

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

      <Card title={`Signals for ${data.ticker}`}>
        <SignalTable rows={data.signals} onRow={setSel} hide={['ticker', 'spark']}
                     empty="Never signaled — only present in score files" />
      </Card>

      <SignalDetail signal={sel} onClose={() => setSel(null)} />
    </div>
  )
}
