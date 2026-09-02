import React, { useEffect, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, PRODUCER_META } from '../api.js'
import { fmtPct } from '../format.js'
import { Card, DateLink, ErrorBox, Pct, PerfTag, ProducerTag, Spinner, Stat, Table, TickerLink } from '../ui.jsx'
import { axisTick, DistHist, PerfScatter, TOOLTIP_STYLE } from '../charts.jsx'
import { C } from '../theme.js'

export default function Analytics() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [loading, setLoading] = useState(true)
  const [producer, setProducer] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')

  // Keep the previous window's charts (dimmed) while the new one loads.
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    api('analytics', { producer, date_from: from, date_to: to }, { signal: controller.signal })
      .then((d) => { setData(d); setErr(null) })
      .catch((nextErr) => { if (nextErr.name !== 'AbortError') setErr(nextErr) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [producer, from, to])

  if (err) return <ErrorBox err={err} />
  if (!data) return <Spinner />
  const producers = Object.keys(data.by_producer || {})

  const presetFrom = (days) =>
    new Date(Date.now() - days * 86400000).toISOString().slice(0, 10)
  const preset = (days) => { setFrom(days === null ? '' : presetFrom(days)); setTo('') }
  const activePreset = to !== '' ? undefined : from === '' ? null
    : [30, 90].find((d) => presetFrom(d) === from)

  return (
    <div>
      <h1 className="sr-only">Signal performance</h1>
      <Card>
        <div className="filter-row">
          <label>Producer
            <select value={producer} onChange={(e) => setProducer(e.target.value)}>
              <option value="">all producers</option>
              {Object.entries(PRODUCER_META).map(([name, meta]) => (
                <option key={name} value={name}>{meta.label}</option>
              ))}
            </select>
          </label>
          <span className="muted">Window</span>
          {[[30, '30d'], [90, '90d'], [null, 'all']].map(([days, label]) => (
            <button key={label} className="btn" aria-pressed={activePreset === days}
                    style={activePreset === days ? { borderColor: 'var(--accent)', color: 'var(--accent)' } : null}
                    onClick={() => preset(days)}>{label}</button>
          ))}
          <label className="inline-label">From
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label className="inline-label">To
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </label>
          <span className="muted" style={{ marginLeft: 'auto' }}>
            score universe matches this window
          </span>
        </div>
      </Card>

      <div className={loading ? 'refetching' : ''} aria-busy={loading}>
      <div className="grid-2">
        {producers.map((name) => {
          const p = data.by_producer[name]
          return (
          <Card key={name} title={<span><ProducerTag producer={name} /> <span className="muted">signal performance</span></span>}>
            <div className="stat-row">
              <Stat label="signals" value={p.n_signals}
                    sub={`${p.n_up} up · ${p.n_down} down · ${p.n_pending} pending`
                         + (p.n_no_px ? ` · ${p.n_no_px} no px` : '')} />
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
        )})}
      </div>

      <div className="grid-2">
        {producers.map((name) => {
          const meta = PRODUCER_META[name] || { label: name, metric: 'metric' }
          return (
            <Card key={name} title={`${meta.label}: signal strength (${meta.metric}) vs outcome`}
                  right={<span className="muted small">each dot is a signal · click to open the ticker</span>}>
              <PerfScatter points={data.scatter} producer={name} />
            </Card>
          )
        })}
      </div>

      <Card title="Cumulative return — every BUY at close, equal weight, 1-day hold">
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={data.cumulative} accessibilityLayer>
            <CartesianGrid stroke={C.hair} vertical={false} />
            <XAxis dataKey="date" tick={axisTick(10)} minTickGap={30} />
            <YAxis tick={axisTick(10)} width={46} domain={['auto', 'auto']}
                   tickFormatter={(v) => `${((v - 1) * 100).toFixed(0)}%`} />
            <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => fmtPct(v - 1)} />
            <Legend />
            <ReferenceLine y={1} stroke={C.rule} />
            {producers.map((name) => {
              const meta = PRODUCER_META[name] || { label: name, color: C.muted }
              return <Line key={name} dataKey={name} name={meta.label} stroke={meta.color} dot={false} connectNulls />
            })}
          </LineChart>
        </ResponsiveContainer>
      </Card>

      <div className="grid-2">
        {producers.map((name) => {
          const meta = PRODUCER_META[name] || { label: name, color: C.muted, metric: 'metric' }
          return (
            <Card key={name} title={`Where ${meta.label} signals sit in ${meta.metric}`}>
              <DistHist bins={data.histograms[name]} color={meta.color} />
            </Card>
          )
        })}
      </div>

      <div className="grid-2">
        <Card title="BUY signals per day">
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data.timeline} accessibilityLayer>
              <CartesianGrid stroke={C.hair} vertical={false} />
              <XAxis dataKey="date" tick={axisTick(10)} minTickGap={30} />
              <YAxis allowDecimals={false} tick={axisTick(10)} width={26} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Legend />
              {producers.map((name) => {
                const meta = PRODUCER_META[name] || { label: name, color: C.muted }
                return <Bar key={name} dataKey={`${name}_buys`} name={meta.label} stackId="a" fill={meta.color} />
              })}
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card title="5-day performance by signal weekday">
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data.weekday} accessibilityLayer>
              <CartesianGrid stroke={C.hair} vertical={false} />
              <XAxis dataKey="day" tick={axisTick(11)} />
              <YAxis tick={axisTick(10)} width={40} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
              <Tooltip contentStyle={TOOLTIP_STYLE}
                       formatter={(v, n, item) => [`${(v * 100).toFixed(1)}% (n=${item.payload.n})`, n]} />
              <ReferenceLine y={0} stroke={C.rule} />
              <Bar dataKey="avg" name="avg 5d return" fill={PRODUCER_META.lstm.text} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <div className="grid-2">
        {producers.map((name) => {
          const meta = PRODUCER_META[name] || { label: name, color: C.muted, metric: 'metric' }
          return <BucketCard key={name} title={`${meta.label}: fwd return by ${meta.metric} quartile`} buckets={data.buckets[name]} color={meta.color} />
        })}
      </div>

      <div className="grid-2">
        <LeaderCard title="Best signals (since signal)" rows={data.best} />
        <LeaderCard title="Worst signals (since signal)" rows={data.worst} />
      </div>
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
        <BarChart data={chart} accessibilityLayer>
          <CartesianGrid stroke={C.hair} vertical={false} />
          <XAxis dataKey="label" tick={axisTick(9)} interval={0} />
          <YAxis tick={axisTick(10)} width={40} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
          <Tooltip contentStyle={TOOLTIP_STYLE}
                   formatter={(v, n, item) => [`${(v * 100).toFixed(1)}% (n=${item.payload.n}, win ${item.payload.win5 === null ? '–' : (item.payload.win5 * 100).toFixed(0)}%)`, 'avg 5d']} />
          <ReferenceLine y={0} stroke={C.rule} />
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
          { key: 'status_perf', label: 'Status', render: (r) => (
            <PerfTag status={r.status_perf}
                     actionWarning={r.has_action_warning}
                     actionIds={r.action_warning_ids}
                     statusBasis={r.status_basis} />
          ) },
        ]}
      />
    </Card>
  )
}
