import React, { useEffect, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, PRODUCER_META } from '../api.js'
import { fmtPct } from '../format.js'
import { Card, DateLink, ErrorBox, Pct, PerfTag, ProducerTag, Spinner, Stat, Table, TickerLink } from '../ui.jsx'
import { DistHist, PerfScatter, TOOLTIP_STYLE } from '../charts.jsx'

const C = { lstm: PRODUCER_META.lstm.color, intrinsic: PRODUCER_META.intrinsic.color }

export default function Analytics() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')

  useEffect(() => {
    setData(null)
    api('analytics', { date_from: from, date_to: to }).then(setData).catch(setErr)
  }, [from, to])

  if (err) return <ErrorBox err={err} />
  if (!data) return <Spinner />

  return (
    <div>
      <Card>
        <div className="filter-row">
          <span className="muted">window</span>
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          <span className="muted">to</span>
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          <span className="muted" style={{ marginLeft: 'auto' }}>
            returns are close-to-close from producer score files
          </span>
        </div>
      </Card>

      <div className="grid-2">
        {Object.entries(data.by_producer).map(([name, p]) => (
          <Card key={name} title={<span><ProducerTag producer={name} /> <span className="muted">signal performance</span></span>}>
            <div className="stat-row">
              <Stat label="signals" value={p.n_signals}
                    sub={`${p.n_up} up · ${p.n_down} down · ${p.n_pending} pending`} />
              {['1d', '5d', '20d'].map((h) => (
                <Stat key={h} label={`win ${h}`}
                      value={p.horizons[h].win_rate === null ? '–' : fmtPct(p.horizons[h].win_rate, 0)}
                      sub={`avg ${fmtPct(p.horizons[h].avg)} · n=${p.horizons[h].n}`}
                      cls={p.horizons[h].avg > 0 ? 'pos' : p.horizons[h].avg < 0 ? 'neg' : ''} />
              ))}
              <Stat label="since signal"
                    value={p.since.win_rate === null ? '–' : fmtPct(p.since.win_rate, 0)}
                    sub={p.since.avg === null ? null : `avg ${fmtPct(p.since.avg)}`}
                    cls={p.since.avg > 0 ? 'pos' : p.since.avg < 0 ? 'neg' : ''} />
            </div>
          </Card>
        ))}
      </div>

      <div className="grid-2">
        <Card title="LSTM: signal strength (adj_prob) vs outcome"
              right={<span className="muted small">each dot is a signal · click to open the ticker</span>}>
          <PerfScatter points={data.scatter} producer="lstm" />
        </Card>
        <Card title="Intrinsic: signal strength (discount) vs outcome"
              right={<span className="muted small">each dot is a signal · click to open the ticker</span>}>
          <PerfScatter points={data.scatter} producer="intrinsic" />
        </Card>
      </div>

      <Card title="Cumulative return — every BUY at close, equal weight, 1-day hold">
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={data.cumulative}>
            <CartesianGrid stroke="#222b3a" vertical={false} />
            <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={30} />
            <YAxis tick={{ fontSize: 10 }} width={46} domain={['auto', 'auto']}
                   tickFormatter={(v) => `${((v - 1) * 100).toFixed(0)}%`} />
            <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => fmtPct(v - 1)} />
            <Legend />
            <ReferenceLine y={1} stroke="#556" />
            <Line dataKey="lstm" name="LSTM" stroke={C.lstm} dot={false} connectNulls />
            <Line dataKey="intrinsic" name="Intrinsic" stroke={C.intrinsic} dot={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </Card>

      <div className="grid-2">
        <Card title="Where LSTM signals sit in the scored universe (adj_prob)">
          <DistHist bins={data.histograms.lstm} color={C.lstm} />
        </Card>
        <Card title="Where Intrinsic signals sit in the scored universe (discount)">
          <DistHist bins={data.histograms.intrinsic} color={C.intrinsic} />
        </Card>
      </div>

      <div className="grid-2">
        <Card title="BUY signals per day">
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data.timeline}>
              <CartesianGrid stroke="#222b3a" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={30} />
              <YAxis allowDecimals={false} tick={{ fontSize: 10 }} width={26} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Legend />
              <Bar dataKey="lstm_buys" name="LSTM" stackId="a" fill={C.lstm} />
              <Bar dataKey="intrinsic_buys" name="Intrinsic" stackId="a" fill={C.intrinsic} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card title="5-day performance by signal weekday">
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data.weekday}>
              <CartesianGrid stroke="#222b3a" vertical={false} />
              <XAxis dataKey="day" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 10 }} width={40} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
              <Tooltip contentStyle={TOOLTIP_STYLE}
                       formatter={(v, n, item) => [`${(v * 100).toFixed(1)}% (n=${item.payload.n})`, n]} />
              <ReferenceLine y={0} stroke="#556" />
              <Bar dataKey="avg" name="avg 5d return" fill="#8ab4f8" />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <div className="grid-2">
        <BucketCard title="LSTM: fwd return by adj_prob quartile" buckets={data.buckets.lstm} color={C.lstm} />
        <BucketCard title="Intrinsic: fwd return by discount quartile" buckets={data.buckets.intrinsic} color={C.intrinsic} />
      </div>

      <div className="grid-2">
        <LeaderCard title="Best signals (since signal)" rows={data.best} />
        <LeaderCard title="Worst signals (since signal)" rows={data.worst} />
      </div>
    </div>
  )
}

function BucketCard({ title, buckets, color }) {
  if (!buckets?.length) return <Card title={title}><div className="muted">not enough signals to bucket yet</div></Card>
  const chart = buckets.map((b) => ({
    label: b.label, n: b.n, avg5: b.ret_5d?.avg, win5: b.ret_5d?.win_rate,
  }))
  return (
    <Card title={title} right={<span className="muted small">avg 5-day fwd return</span>}>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={chart}>
          <CartesianGrid stroke="#222b3a" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 9 }} interval={0} />
          <YAxis tick={{ fontSize: 10 }} width={40} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
          <Tooltip contentStyle={TOOLTIP_STYLE}
                   formatter={(v, n, item) => [`${(v * 100).toFixed(1)}% (n=${item.payload.n}, win ${item.payload.win5 === null ? '–' : (item.payload.win5 * 100).toFixed(0)}%)`, 'avg 5d']} />
          <ReferenceLine y={0} stroke="#556" />
          <Bar dataKey="avg5" fill={color} />
        </BarChart>
      </ResponsiveContainer>
    </Card>
  )
}

function LeaderCard({ title, rows }) {
  return (
    <Card title={title}>
      <Table
        rows={rows}
        columns={[
          { key: 'date', label: 'Date', render: (r) => <DateLink d={r.date} /> },
          { key: 'producer', label: 'Producer', render: (r) => <ProducerTag producer={r.producer} /> },
          { key: 'ticker', label: 'Ticker', render: (r) => <TickerLink t={r.ticker} /> },
          { key: 'ret_since', label: 'Since', align: 'right', render: (r) => <Pct v={r.ret_since} /> },
          { key: 'status_perf', label: 'Status', render: (r) => <PerfTag status={r.status_perf} /> },
        ]}
      />
    </Card>
  )
}
