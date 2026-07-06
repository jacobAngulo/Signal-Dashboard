import React from 'react'
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceDot,
  ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip,
  XAxis, YAxis, ZAxis,
} from 'recharts'
import { PRODUCER_META } from './api.js'
import { navigate } from './nav.js'
import { fmtPct, fmtPx } from './format.js'

export const TOOLTIP_STYLE = {
  backgroundColor: '#1a2130', border: '1px solid #2c3648',
  borderRadius: 6, fontSize: 12,
}
const C = { lstm: PRODUCER_META.lstm.color, intrinsic: PRODUCER_META.intrinsic.color }

// Price line with signal markers (gold dots, colored ring per producer).
export function PriceChart({ series, signals = [], height = 260 }) {
  if (!series || series.length < 2) return <div className="muted" style={{ padding: 16 }}>no price series</div>
  const byDate = Object.fromEntries(series.map((p) => [p.date, p.px]))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={series} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="#222b3a" vertical={false} />
        <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={40} />
        <YAxis tick={{ fontSize: 10 }} width={54} domain={['auto', 'auto']}
               tickFormatter={(v) => fmtPx(v)} />
        <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => [fmtPx(v), 'close']} />
        <Line dataKey="px" name="close" stroke="#8ab4f8" strokeWidth={1.6} dot={false} />
        {signals.map((s, i) =>
          byDate[s.date] !== undefined ? (
            <ReferenceDot key={s.date + s.producer + i} x={s.date} y={byDate[s.date]} r={5}
                          fill="#f6c453" stroke={C[s.producer] || '#fff'} strokeWidth={2}
                          label={{ value: 'BUY', position: 'top', fontSize: 9, fill: '#f6c453' }} />
          ) : null
        )}
      </LineChart>
    </ResponsiveContainer>
  )
}

// A ticker's daily score metric over time (adj_prob / discount).
export function HistoryChart({ history, producer, threshold, height = 180 }) {
  const meta = PRODUCER_META[producer]
  if (!history || history.length < 2) {
    return <div className="muted" style={{ padding: 16 }}>not scored by {meta?.label || producer} often enough to chart</div>
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={history} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="#222b3a" vertical={false} />
        <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={40} />
        <YAxis tick={{ fontSize: 10 }} width={44} domain={['auto', 'auto']} />
        <Tooltip contentStyle={TOOLTIP_STYLE} />
        {threshold !== undefined && (
          <ReferenceLine y={threshold} stroke="#f6c453" strokeDasharray="4 3"
                         label={{ value: `signal threshold ${threshold}`, fontSize: 9, fill: '#f6c453', position: 'insideTopRight' }} />
        )}
        <Line dataKey="metric" name={meta?.metric || 'metric'} stroke={meta?.color || '#888'}
              strokeWidth={1.5} dot={{ r: 1.5 }} connectNulls />
      </LineChart>
    </ResponsiveContainer>
  )
}

// Signal strength vs what happened: click a point to open the ticker.
export function PerfScatter({ points, height = 240, yKey = 'ret_5d', yLabel = '5-day return' }) {
  const groups = { lstm: [], intrinsic: [] }
  for (const p of points) {
    if (p[yKey] !== null && p[yKey] !== undefined && groups[p.producer]) groups[p.producer].push(p)
  }
  const open = (d) => {
    const p = d && (d.payload || d)
    if (p && p.ticker) navigate('ticker', p.ticker)
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        <CartesianGrid stroke="#222b3a" />
        <XAxis dataKey="metric" name="signal metric" type="number" tick={{ fontSize: 10 }}
               domain={['auto', 'auto']} />
        <YAxis dataKey={yKey} name={yLabel} type="number" tick={{ fontSize: 10 }} width={48}
               tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
        <ZAxis range={[45, 46]} />
        <Tooltip
          contentStyle={TOOLTIP_STYLE} cursor={{ strokeDasharray: '3 3' }}
          formatter={(v, name) => (name === yLabel ? fmtPct(v) : v)}
          labelFormatter={() => ''}
          content={({ payload }) => {
            const p = payload && payload[0] && payload[0].payload
            if (!p) return null
            return (
              <div style={{ ...TOOLTIP_STYLE, padding: '6px 10px' }}>
                <b>{p.ticker}</b> · {p.date}<br />
                metric {Number(p.metric).toFixed(3)} · {yLabel} {fmtPct(p[yKey])}
              </div>
            )
          }}
        />
        <ReferenceLine y={0} stroke="#556" />
        <Legend />
        <Scatter name="LSTM" data={groups.lstm} fill={C.lstm} onClick={open} cursor="pointer" />
        <Scatter name="Intrinsic" data={groups.intrinsic} fill={C.intrinsic} onClick={open} cursor="pointer" />
      </ScatterChart>
    </ResponsiveContainer>
  )
}

// Where signals sit inside the whole scored universe (share-normalized).
export function DistHist({ bins, color, height = 190 }) {
  if (!bins || !bins.length) return <div className="muted" style={{ padding: 16 }}>no distribution data</div>
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={bins} margin={{ top: 8, right: 12, bottom: 0, left: 0 }} barGap={0}>
        <CartesianGrid stroke="#222b3a" vertical={false} />
        <XAxis dataKey="label" tick={{ fontSize: 9 }} interval={1} />
        <YAxis tick={{ fontSize: 10 }} width={40} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
        <Tooltip contentStyle={TOOLTIP_STYLE}
                 formatter={(v, name, item) => [
                   `${(v * 100).toFixed(1)}% (${name === 'universe' ? item.payload.n_universe : item.payload.n_signals} rows)`,
                   name,
                 ]} />
        <Legend />
        <Bar dataKey="universe" name="universe" fill="#3a4356" />
        <Bar dataKey="signals" name="signals" fill={color} />
      </BarChart>
    </ResponsiveContainer>
  )
}
