import React, { useMemo, useState } from 'react'
import {
  Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, LineChart,
  ReferenceDot, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip,
  XAxis, YAxis, ZAxis,
} from 'recharts'
import { PRODUCER_META } from './api.js'
import { navigate } from './nav.js'
import { fmtPct, fmtPx } from './format.js'

export const TOOLTIP_STYLE = {
  backgroundColor: '#1a2130', border: '1px solid #2c3648',
  borderRadius: 6, fontSize: 12,
}

const RANGE_DAYS = { '1D': 1, '5D': 5, '1M': 31, '3M': 93, '6M': 186, '1Y': 366 }

export function chartWindow(series, range) {
  if (!series?.length || range === 'ALL') return series || []
  const last = new Date(`${series[series.length - 1].date}T00:00:00Z`)
  const start = new Date(last)
  start.setUTCDate(start.getUTCDate() - RANGE_DAYS[range])
  const iso = start.toISOString().slice(0, 10)
  return series.filter((point) => point.date >= iso)
}

function signalGroups(signals, series, intraday) {
  const grouped = new Map()
  for (const signal of signals || []) {
    const candidates = series.filter((point) => point.date === signal.date)
    if (!candidates.length) continue
    let x = signal.date
    if (intraday) {
      const target = signal.chart_time ? new Date(signal.chart_time).getTime() : NaN
      const point = Number.isFinite(target)
        ? candidates.reduce((best, candidate) => (
            Math.abs(new Date(candidate.timestamp).getTime() - target)
              < Math.abs(new Date(best.timestamp).getTime() - target)
              ? candidate : best
          ))
        : candidates[candidates.length - 1]
      x = point.timestamp
    }
    const group = grouped.get(x) || {
      x, date: signal.date, decisions: [], producers: [],
    }
    group.decisions.push(signal.decision || 'BUY')
    if (!group.producers.includes(signal.producer)) group.producers.push(signal.producer)
    grouped.set(x, group)
  }
  return [...grouped.values()]
}

function compactVolume(value) {
  if (value === null || value === undefined) return '–'
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)}K`
  return String(Math.round(value))
}

function Candle({ x, y, width, height, payload }) {
  if (!payload || !Number.isFinite(payload.low) || !Number.isFinite(payload.high)) return null
  const high = payload.high, low = payload.low
  const open = Number.isFinite(payload.open) ? payload.open : payload.close
  const close = payload.close
  const up = close >= open
  const color = up ? '#3ecf8e' : '#f07070'
  const span = high - low || 1
  const valueY = (value) => y + ((high - value) / span) * height
  const openY = valueY(open), closeY = valueY(close)
  const bodyY = Math.min(openY, closeY)
  const bodyH = Math.max(1.5, Math.abs(closeY - openY))
  const bodyW = Math.max(2, Math.min(width * 0.7, 9))
  const cx = x + width / 2
  return (
    <g>
      <line x1={cx} x2={cx} y1={y} y2={y + Math.max(height, 1)}
            stroke={color} strokeWidth="1" />
      <rect x={cx - bodyW / 2} y={bodyY} width={bodyW} height={bodyH}
            fill={up ? '#163d2c' : color} stroke={color} strokeWidth="1" />
    </g>
  )
}

function OHLCBar({ x, y, width, height, payload }) {
  if (!payload || !Number.isFinite(payload.low) || !Number.isFinite(payload.high)) return null
  const high = payload.high, low = payload.low
  const open = Number.isFinite(payload.open) ? payload.open : payload.close
  const close = payload.close
  const color = close >= open ? '#3ecf8e' : '#f07070'
  const span = high - low || 1
  const valueY = (value) => y + ((high - value) / span) * height
  const cx = x + width / 2
  const tick = Math.max(2, Math.min(width * 0.35, 5))
  return (
    <g stroke={color} strokeWidth="1.2">
      <line x1={cx} x2={cx} y1={y} y2={y + Math.max(height, 1)} />
      <line x1={cx - tick} x2={cx} y1={valueY(open)} y2={valueY(open)} />
      <line x1={cx} x2={cx + tick} y1={valueY(close)} y2={valueY(close)} />
    </g>
  )
}

function TradingTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const point = payload.find((item) => item?.payload)?.payload
  if (!point) return null
  return (
    <div style={{ ...TOOLTIP_STYLE, padding: '7px 10px' }}>
      <b>{point.timestamp ? formatMarketTime(point.timestamp) : point.date}</b>
      <div>O {fmtPx(point.open)} · H {fmtPx(point.high)}</div>
      <div>L {fmtPx(point.low)} · C {fmtPx(point.close)}</div>
      <div className="muted">volume {compactVolume(point.volume)}</div>
      {point.signalLabels?.length > 0 && (
        <div className="chart-tooltip-signals">
          {point.signalLabels.map((signal, index) => (
            <div key={`${signal.producer}-${signal.decision}-${index}`}>
              {signal.decision} · {PRODUCER_META[signal.producer]?.label || signal.producer}
            </div>
          ))}
        </div>
      )}
      {point.actionUnresolved && <div className="warn">corporate-action boundary under review</div>}
    </div>
  )
}

// Trading-style OHLCV with every signal marked. Intraday and daily series share
// the renderer; range controls are shown for daily history.
export function PriceChart({
  series, signals = [], height = 260, controls = height >= 240, interval = '1Day',
  range: controlledRange, mode: controlledMode,
}) {
  const [localRange, setLocalRange] = useState('6M')
  const [localMode, setLocalMode] = useState('candles')
  const range = controlledRange || localRange
  const mode = controlledMode || localMode
  const visible = useMemo(() => chartWindow(series, range), [series, range])
  const intraday = Boolean(visible[0]?.timestamp)
  const groups = useMemo(
    () => signalGroups(signals, visible, intraday),
    [signals, visible, intraday],
  )
  if (!series || series.length < 2) return <div className="muted" style={{ padding: 16 }}>no price series</div>
  const byX = Object.fromEntries(visible.map((point) => [
    point.timestamp || point.date, point.close ?? point.px,
  ]))
  const signalsByX = Object.fromEntries(groups.map((group) => [group.x, group]))
  const hasActionWarning = visible.some((point) => (
    point.blocked_action_ids?.length
    || !['confirmed', 'clear', 'not_applicable'].includes(point.confirmation_status)
  ))
  const prepared = visible.map((point, index) => {
    const close = point.close ?? point.px
    const chartX = point.timestamp || point.date
    const group = signalsByX[chartX]
    return {
      ...point,
      chart_x: chartX,
      open: point.open ?? close,
      high: point.high ?? close,
      low: point.low ?? close,
      close,
      range: [point.low ?? close, point.high ?? close],
      signalLabels: group
        ? group.decisions.map((decision, index) => ({
            decision, producer: group.producers[index] || group.producers[0],
          }))
        : [],
      actionUnresolved: Boolean(index > 0 && (
        point.continuity_segment !== visible[index - 1]?.continuity_segment
        || JSON.stringify(point.blocked_action_ids || [])
          !== JSON.stringify(visible[index - 1]?.blocked_action_ids || [])
      ) && (
        point.blocked_action_ids?.length
        || !['confirmed', 'clear', 'not_applicable'].includes(point.confirmation_status)
      )),
    }
  })
  const maxVolume = Math.max(0, ...prepared.map((point) => point.volume || 0))
  return (
    <div className="trading-chart">
      {controls && (
        <div className="chart-toolbar" aria-label="Price chart controls">
          <div className="chart-ranges">
            {['1M', '3M', '6M', '1Y', 'ALL'].map((value) => (
              <button key={value} type="button"
                      className={`chart-control ${range === value ? 'active' : ''}`}
                      aria-pressed={range === value} onClick={() => setLocalRange(value)}>
                {value === 'ALL' ? 'All' : value}
              </button>
            ))}
          </div>
          <div className="chart-ranges">
            {[
              ['candles', 'Candles'],
              ['ohlc', 'OHLC'],
              ['line', 'Line'],
              ['area', 'Area'],
            ].map(([value, label]) => (
              <button key={value} type="button"
                      className={`chart-control ${mode === value ? 'active' : ''}`}
                      aria-pressed={mode === value}
                      onClick={() => setLocalMode(value)}>
                {label}
              </button>
            ))}
          </div>
        </div>
      )}
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={prepared} margin={{ top: 18, right: 12, bottom: 0, left: 0 }}
                       accessibilityLayer>
          <CartesianGrid stroke="#222b3a" vertical={false} />
          <XAxis dataKey="chart_x" tick={{ fontSize: 10 }} minTickGap={52}
                 tickFormatter={(value) => intraday ? formatMarketTick(value) : value} />
          <YAxis yAxisId="price" tick={{ fontSize: 10 }} width={58}
                 domain={['auto', 'auto']} tickFormatter={(v) => fmtPx(v)} />
          <YAxis yAxisId="volume" hide domain={[0, maxVolume ? maxVolume * 4 : 1]} />
          <Tooltip content={<TradingTooltip />} />
          {maxVolume > 0 && (
            <Bar yAxisId="volume" dataKey="volume" fill="#5b9cf6" opacity={0.18}
                 isAnimationActive={false} />
          )}
          {mode === 'candles' ? (
            <Bar yAxisId="price" dataKey="range" shape={<Candle />}
                 isAnimationActive={false} />
          ) : mode === 'ohlc' ? (
            <Bar yAxisId="price" dataKey="range" shape={<OHLCBar />}
                 isAnimationActive={false} />
          ) : mode === 'area' ? (
            <Area yAxisId="price" dataKey="close" name="close"
                  stroke="#8ab4f8" fill="#315d913d" strokeWidth={1.7}
                  dot={false} isAnimationActive={false} />
          ) : (
            <Line yAxisId="price" dataKey="close" name="close" stroke="#8ab4f8"
                  strokeWidth={1.7} dot={false} isAnimationActive={false} />
          )}
          {groups.map((group) => {
            const hasBuy = group.decisions.includes('BUY')
            const hasSell = group.decisions.includes('SELL')
            const fill = hasBuy ? '#f6c453' : hasSell ? '#f07070' : '#8b96a8'
            const label = group.decisions.length > 1
              ? `${hasBuy ? '▲' : hasSell ? '▼' : '•'}×${group.decisions.length}`
              : hasBuy ? '▲' : hasSell ? '▼' : '•'
            return (
              <ReferenceDot key={group.x} yAxisId="price"
                            x={group.x} y={byX[group.x]} r={5}
                            fill={fill}
                            stroke={PRODUCER_META[group.producers[0]]?.color || '#fff'}
                            strokeWidth={2}
                            label={{ value: label, position: 'top', fontSize: 10, fill }} />
            )
          })}
        </ComposedChart>
      </ResponsiveContainer>
      <div className="chart-legend muted small">
        <span><i className="legend-swatch buy" /> BUY</span>
        <span><i className="legend-swatch sell" /> SELL</span>
        <span><i className="legend-swatch watch" /> WATCH</span>
        {hasActionWarning && <span className="warn">CA review flagged</span>}
        <span>{prepared.length} {intraday ? interval : 'daily'} bars</span>
      </div>
    </div>
  )
}

function formatMarketTick(timestamp) {
  try {
    return new Date(timestamp).toLocaleString('en-US', {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
      timeZone: 'America/New_York',
    })
  } catch {
    return timestamp
  }
}

function formatMarketTime(timestamp) {
  try {
    return new Date(timestamp).toLocaleString('en-US', {
      month: 'short', day: 'numeric', year: 'numeric',
      hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York',
      timeZoneName: 'short',
    })
  } catch {
    return timestamp
  }
}

// A ticker's daily score metric over time (adj_prob / discount).
export function HistoryChart({ history, producer, threshold, height = 180 }) {
  const meta = PRODUCER_META[producer]
  if (!history || history.length < 2) {
    return <div className="muted" style={{ padding: 16 }}>not scored by {meta?.label || producer} often enough to chart</div>
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={history} margin={{ top: 8, right: 12, bottom: 0, left: 0 }} accessibilityLayer>
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

// One producer's signal strength vs what happened: click a point to open the
// ticker. adj_prob and discount live on different scales, so each producer
// gets its own chart and x-axis — never plot them on a shared metric axis.
export function PerfScatter({ points, producer, height = 240, yKey = 'ret_5d', yLabel = '5-day return' }) {
  const meta = PRODUCER_META[producer]
  const pts = points.filter(
    (p) => p.producer === producer && p[yKey] !== null && p[yKey] !== undefined)
  if (!pts.length) return <div className="muted" style={{ padding: 16 }}>no scored signals yet</div>
  const open = (d) => {
    const p = d && (d.payload || d)
    if (p && p.ticker) navigate('ticker', p.ticker)
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ top: 8, right: 12, bottom: 4, left: 0 }} accessibilityLayer>
        <CartesianGrid stroke="#222b3a" />
        <XAxis dataKey="metric" name={meta?.metric || 'metric'} type="number"
               tick={{ fontSize: 10 }} domain={['auto', 'auto']}
               label={{ value: meta?.metric, position: 'insideBottomRight',
                        offset: -2, fontSize: 10, fill: '#7a8699' }} />
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
                {meta?.metric || 'metric'} {Number(p.metric).toFixed(3)} · {yLabel} {fmtPct(p[yKey])}
              </div>
            )
          }}
        />
        <ReferenceLine y={0} stroke="#556" />
        <Scatter name={meta?.label || producer} data={pts} fill={meta?.color || '#888'}
                 onClick={open} cursor="pointer" />
      </ScatterChart>
    </ResponsiveContainer>
  )
}

// Where signals sit inside the whole scored universe (share-normalized).
export function DistHist({ bins, color, height = 190 }) {
  if (!bins || !bins.length) return <div className="muted" style={{ padding: 16 }}>no distribution data</div>
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={bins} margin={{ top: 8, right: 12, bottom: 0, left: 0 }} barGap={0} accessibilityLayer>
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
