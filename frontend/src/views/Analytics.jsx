import React, { useEffect, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, PRODUCER_META } from '../api.js'
import { fmtMoney, fmtPct } from '../format.js'
import { Card, ErrorBox, Money, Pct, ProducerTag, Spinner, Stat, StateTag, Table } from '../ui.jsx'

const C = { lstm: PRODUCER_META.lstm.color, intrinsic: PRODUCER_META.intrinsic.color }
const DARK_TOOLTIP = { backgroundColor: '#1a2130', border: '1px solid #2c3648', borderRadius: 6, fontSize: 12 }

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

  const pctAxis = (v) => `${(v * 100).toFixed(0)}%`

  return (
    <div>
      <Card>
        <div className="filter-row">
          <span className="muted">window</span>
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          <span className="muted">to</span>
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          <span className="muted" style={{ marginLeft: 'auto' }}>
            returns are close-to-close from producer score files; P&L from arena fills
          </span>
        </div>
      </Card>

      <div className="grid-2">
        {Object.entries(data.by_producer).map(([name, p]) => (
          <Card key={name} title={<span><ProducerTag producer={name} /> <span className="muted">signal performance</span></span>}>
            <div className="stat-row">
              <Stat label="signals" value={p.n_signals} sub={`${p.n_traded} traded`} />
              {['1d', '5d', '20d'].map((h) => (
                <Stat key={h} label={`win ${h}`}
                      value={p.horizons[h].win_rate === null ? '–' : fmtPct(p.horizons[h].win_rate, 0)}
                      sub={`avg ${fmtPct(p.horizons[h].avg)} · n=${p.horizons[h].n}`}
                      cls={p.horizons[h].avg > 0 ? 'pos' : p.horizons[h].avg < 0 ? 'neg' : ''} />
              ))}
              <Stat label="realized P&L" value={fmtMoney(p.realized_pnl)}
                    sub={`unrealized ${fmtMoney(p.unrealized_pnl)}`}
                    cls={p.realized_pnl > 0 ? 'pos' : p.realized_pnl < 0 ? 'neg' : ''} />
            </div>
          </Card>
        ))}
      </div>

      <div className="grid-2">
        <Card title="BUY signals per day">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={data.timeline}>
              <CartesianGrid stroke="#222b3a" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={30} />
              <YAxis allowDecimals={false} tick={{ fontSize: 10 }} width={26} />
              <Tooltip contentStyle={DARK_TOOLTIP} />
              <Legend />
              <Bar dataKey="lstm_buys" name="LSTM" stackId="a" fill={C.lstm} />
              <Bar dataKey="intrinsic_buys" name="Intrinsic" stackId="a" fill={C.intrinsic} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Cumulative return — taking every BUY at close, equal weight, 1-day hold">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={data.cumulative}>
              <CartesianGrid stroke="#222b3a" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={30} />
              <YAxis tick={{ fontSize: 10 }} width={44} domain={['auto', 'auto']}
                     tickFormatter={(v) => (v - 1) >= 0 ? `+${((v - 1) * 100).toFixed(0)}%` : `${((v - 1) * 100).toFixed(0)}%`} />
              <Tooltip contentStyle={DARK_TOOLTIP} formatter={(v) => fmtPct(v - 1)} />
              <Legend />
              <ReferenceLine y={1} stroke="#556" />
              <Line dataKey="lstm" name="LSTM" stroke={C.lstm} dot={false} connectNulls />
              <Line dataKey="intrinsic" name="Intrinsic" stroke={C.intrinsic} dot={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <div className="grid-2">
        <BucketCard title="LSTM: fwd return by adj_prob bucket" buckets={data.buckets.lstm} color={C.lstm} />
        <BucketCard title="Intrinsic: fwd return by discount bucket" buckets={data.buckets.intrinsic} color={C.intrinsic} />
      </div>

      <div className="grid-2">
        <LeaderCard title="Best signals (return since signal)" rows={data.best} />
        <LeaderCard title="Worst signals (return since signal)" rows={data.worst} />
      </div>
    </div>
  )
}

function BucketCard({ title, buckets, color }) {
  if (!buckets?.length) return <Card title={title}><div className="muted">not enough signals to bucket yet</div></Card>
  const chart = buckets.map((b) => ({
    label: b.label, n: b.n,
    avg5: b.ret_5d?.avg, win5: b.ret_5d?.win_rate,
  }))
  return (
    <Card title={title} right={<span className="muted">avg 5-day fwd return · quartile buckets</span>}>
      <ResponsiveContainer width="100%" height={190}>
        <BarChart data={chart}>
          <CartesianGrid stroke="#222b3a" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 9 }} interval={0} />
          <YAxis tick={{ fontSize: 10 }} width={40} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
          <Tooltip contentStyle={DARK_TOOLTIP}
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
          { key: 'date', label: 'Date' },
          { key: 'producer', label: 'Producer', render: (r) => <ProducerTag producer={r.producer} /> },
          { key: 'ticker', label: 'Ticker', render: (r) => <b>{r.ticker}</b> },
          { key: 'ret_since', label: 'Since', align: 'right', render: (r) => <Pct v={r.ret_since} /> },
          { key: 'state', label: 'Status', render: (r) => <StateTag state={r.state} /> },
        ]}
      />
    </Card>
  )
}
