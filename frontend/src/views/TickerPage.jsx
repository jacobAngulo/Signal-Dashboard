import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
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

  return (
    <div>
      <div className="crumb">
        <a className="dlink" href="#/" onClick={(e) => { e.preventDefault(); history.back() }}>← back</a>
        <span className="crumb-title">{data.ticker}</span>
        {s.producers.map((p) => <ProducerTag key={p} producer={p} />)}
      </div>

      <Card>
        <div className="stat-row">
          <Stat label="last px" value={last ? fmtPx(last.px) : '–'} sub={last?.date} />
          <Stat label="BUY signals" value={s.n_signals}
                sub={s.first_signal ? `${s.first_signal} → ${s.last_signal}` : null} />
          <Stat label="5d win rate" value={s.ret_5d.win_rate === null ? '–' : fmtPct(s.ret_5d.win_rate, 0)}
                sub={s.ret_5d.n ? `n=${s.ret_5d.n}` : null} />
          <Stat label="5d avg" value={s.ret_5d.avg === null ? '–' : fmtPct(s.ret_5d.avg)}
                cls={s.ret_5d.avg > 0 ? 'pos' : s.ret_5d.avg < 0 ? 'neg' : ''} />
          <Stat label="scored days" value={Math.max(data.history.lstm.length, data.history.intrinsic.length)} />
        </div>
      </Card>

      <Card title="Price — every BUY signal marked">
        <PriceChart series={data.series} signals={markers} height={280} />
      </Card>

      <div className="grid-2">
        <Card title="LSTM adj. probability over time">
          <HistoryChart history={data.history.lstm} producer="lstm" threshold={0.2} />
        </Card>
        <Card title="Intrinsic discount over time">
          <HistoryChart history={data.history.intrinsic} producer="intrinsic" threshold={0.8} />
        </Card>
      </div>

      <Card title={`Signals for ${data.ticker}`}>
        <SignalTable rows={data.signals} onRow={setSel} hide={['ticker', 'spark']}
                     empty="Never signaled — only present in score files" />
      </Card>

      <SignalDetail signal={sel} onClose={() => setSel(null)} />
    </div>
  )
}
