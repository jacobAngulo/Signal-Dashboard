import React, { useEffect, useMemo, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts'
import { api, PRODUCER_META } from '../api.js'
import { fmtPct } from '../format.js'
import { DateLink, ErrorBox, Pct, PerfTag, ProducerTag, Spinner, TickerLink } from '../ui.jsx'
import { axisTick, DistHist, TOOLTIP_STYLE } from '../charts.jsx'
import { navigate } from '../nav.js'
import { C } from '../theme.js'
import LstmWindows from './LstmWindows.jsx'

// Design turn 5a, "one question per band": a single scroll of full-width
// bands, each titled with a question and answered by one chart. Producers
// overlay as series instead of getting a card each. Picking a producer keeps
// every band and appends that producer's own workbench underneath -- which is
// where the LSTM tab now lives.
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
  const nSignals = producers.reduce((t, p) => t + (data.by_producer[p].n_signals || 0), 0)

  const presetFrom = (days) =>
    new Date(Date.now() - days * 86400000).toISOString().slice(0, 10)
  const preset = (days) => { setFrom(days === null ? '' : presetFrom(days)); setTo('') }
  const activePreset = to !== '' ? undefined : from === '' ? null
    : [30, 90].find((d) => presetFrom(d) === from)

  return (
    <div className="bands">
      <h1 className="sr-only">Signal performance</h1>

      <div className="control-band">
        <div className="query-field">
          <div className="stat-label">Viewing</div>
          <select value={producer} onChange={(e) => setProducer(e.target.value)}
                  aria-label="Producer" style={{ minWidth: 230 }}>
            <option value="">All producers — compared</option>
            {Object.entries(PRODUCER_META).map(([name, meta]) => (
              <option key={name} value={name}>{meta.label} only</option>
            ))}
          </select>
        </div>
        <div className="query-field">
          <div className="stat-label">Window</div>
          <div className="date-range">
            <div className="seg" role="group" aria-label="Window preset">
              {[[30, '30d'], [90, '90d'], [null, 'all']].map(([days, label]) => (
                <button key={label} type="button" className={`seg-btn ${activePreset === days ? 'active' : ''}`}
                        aria-pressed={activePreset === days}
                        onClick={() => preset(days)}>{label}</button>
              ))}
            </div>
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From" />
            <span className="muted">→</span>
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="To" />
          </div>
        </div>
        <div className="query-field control-note">
          <div>{nSignals.toLocaleString()} signals · score universe matches this window</div>
          <div className="muted small">
            {producer
              ? `metric axis: ${PRODUCER_META[producer]?.metric}`
              : 'the three metrics are not comparable in raw units — strength bands normalise them'}
          </div>
        </div>
      </div>

      <div className={loading ? 'refetching' : ''} aria-busy={loading}>
        <PayingBand data={data} producers={producers} />
        <HorizonBand data={data} producers={producers} />
        <StrengthBand data={data} producers={producers} />
        <SupplyBand data={data} producers={producers} />
        <DistributionBand data={data} producers={producers} />
      </div>

      {producer === 'lstm' && (
        <section className="band">
          <div className="band-head">
            <h2>Which candidates did the model publish?</h2>
            <span className="band-note">the LSTM tab, in place — every scored window this producer retained</span>
          </div>
          <LstmWindows embedded />
        </section>
      )}
    </div>
  )
}

function Band({ title, note, children }) {
  return (
    <section className="band">
      <div className="band-head">
        <h2>{title}</h2>
        {note && <span className="band-note">{note}</span>}
      </div>
      {children}
    </section>
  )
}

// One line per producer replaces three separate cumulative cards.
function PayingBand({ data, producers }) {
  return (
    <Band title="Which producer is actually paying?"
          note="equal weight · buy at close · 1-day hold">
      <div className="band-split">
        <ResponsiveContainer width="100%" height={248}>
          <LineChart data={data.cumulative} accessibilityLayer>
            <CartesianGrid stroke={C.hair} vertical={false} />
            <XAxis dataKey="date" tick={axisTick(10)} minTickGap={40} />
            <YAxis tick={axisTick(10)} width={48} domain={['auto', 'auto']}
                   tickFormatter={(v) => `${((v - 1) * 100).toFixed(0)}%`} />
            <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => fmtPct(v - 1)} />
            <ReferenceLine y={1} stroke={C.rule} strokeDasharray="4 4" />
            {producers.map((name) => (
              <Line key={name} dataKey={name} name={PRODUCER_META[name]?.label || name}
                    stroke={PRODUCER_META[name]?.color || C.muted} dot={false} connectNulls
                    strokeWidth={1.8} />
            ))}
          </LineChart>
        </ResponsiveContainer>
        <div className="band-rail">
          {producers.map((name) => {
            const p = data.by_producer[name]
            const last = [...data.cumulative].reverse().find((row) => row[name] != null)
            const total = last ? last[name] - 1 : null
            return (
              <div key={name} className="rail-line">
                <div className="rail-line-head">
                  <i className="series-swatch" style={{ background: PRODUCER_META[name]?.color }} />
                  <ProducerTag producer={name} />
                  <b className={total > 0 ? 'pos' : total < 0 ? 'neg' : 'muted'}>
                    {total == null ? '–' : fmtPct(total)}
                  </b>
                </div>
                <div className="rail-line-sub muted small">
                  {p.n_signals} sig · win 5d <b>{p.horizons['5d'].win_rate == null ? '–' : fmtPct(p.horizons['5d'].win_rate, 0)}</b>
                  {' · '}avg 5d <b className={p.horizons['5d'].avg > 0 ? 'pos' : p.horizons['5d'].avg < 0 ? 'neg' : ''}>
                    {fmtPct(p.horizons['5d'].avg)}
                  </b>
                </div>
              </div>
            )
          })}
          <div className="rail-foot muted small">
            {producers.length} series, one axis — the cards this replaces could not be compared to each other.
          </div>
        </div>
      </div>
    </Band>
  )
}

// Win rate by horizon: four columns, one meter per producer, 50% marked.
function HorizonBand({ data, producers }) {
  const cols = [['1d', '1 day'], ['5d', '5 day'], ['20d', '20 day'], ['since', 'since signal']]
  return (
    <Band title="Does the edge survive the hold?" note="win rate by horizon · 50% is a coinflip">
      <div className="horizon-grid">
        {cols.map(([key, label]) => (
          <div key={key} className="horizon-col">
            <div className="stat-label">{label}</div>
            {producers.map((name) => {
              const stats = key === 'since' ? data.by_producer[name].since : data.by_producer[name].horizons[key]
              const wr = stats?.win_rate
              return (
                <div key={name} className="meter">
                  <div className="meter-head">
                    <ProducerTag producer={name} />
                    <b>{wr == null ? '–' : fmtPct(wr, 0)}</b>
                  </div>
                  <div className="meter-track" title={`n=${stats?.n ?? 0}`}>
                    <i className="meter-fill"
                       style={{ width: `${(wr ?? 0) * 100}%`, background: PRODUCER_META[name]?.color }} />
                    <i className="meter-mid" />
                  </div>
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </Band>
  )
}

// adj_prob, discount and score are not comparable in raw units, so the x-axis
// is each signal's percentile *within its own producer* and one chart replaces
// three. The quartile table beside it is the same question answered in
// numbers: does a stronger signal actually pay more?
function StrengthBand({ data, producers }) {
  const points = useMemo(() => {
    const out = {}
    for (const name of producers) {
      const rows = (data.scatter || [])
        .filter((p) => p.producer === name && p.metric != null && p.ret_5d != null)
        .sort((a, b) => a.metric - b.metric)
      out[name] = rows.map((p, i) => ({
        ...p, pct: rows.length > 1 ? (i / (rows.length - 1)) * 100 : 50,
      }))
    }
    return out
  }, [data.scatter, producers])

  const open = (d) => {
    const p = d && (d.payload || d)
    if (p && p.ticker) navigate('ticker', p.ticker)
  }

  return (
    <Band title="Does a stronger signal mean a better trade?"
          note="each dot is a signal · click to open the ticker">
      <p className="band-lede">
        X is the signal&apos;s <b>percentile within its own producer&apos;s metric</b> — adj_prob,
        discount and score share no scale, so ranking is the only honest common axis.
      </p>
      <div className="band-split band-split-wide">
        <ResponsiveContainer width="100%" height={230}>
          <ScatterChart margin={{ top: 8, right: 12, bottom: 4, left: 0 }} accessibilityLayer>
            <CartesianGrid stroke={C.hair} vertical={false} />
            <XAxis dataKey="pct" type="number" domain={[0, 100]} tick={axisTick(10)}
                   ticks={[0, 25, 50, 75, 100]} tickFormatter={(v) => `P${v}`} />
            <YAxis dataKey="ret_5d" type="number" tick={axisTick(10)} width={48}
                   tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
            <ZAxis range={[36, 37]} />
            <ReferenceLine y={0} stroke={C.dim} strokeDasharray="4 4" />
            <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ strokeDasharray: '3 3' }}
                     content={({ payload }) => {
                       const p = payload?.[0]?.payload
                       if (!p) return null
                       return (
                         <div style={{ ...TOOLTIP_STYLE, padding: '6px 10px' }}>
                           <b>{p.ticker}</b> · {p.date} · {PRODUCER_META[p.producer]?.label}<br />
                           {PRODUCER_META[p.producer]?.metric} {Number(p.metric).toFixed(3)}
                           {' '}(P{p.pct.toFixed(0)}) · 5d {fmtPct(p.ret_5d)}
                         </div>
                       )
                     }} />
            {producers.map((name) => (
              <Scatter key={name} name={PRODUCER_META[name]?.label || name} data={points[name]}
                       fill={PRODUCER_META[name]?.color || C.muted} fillOpacity={0.75}
                       onClick={open} cursor="pointer" />
            ))}
          </ScatterChart>
        </ResponsiveContainer>
        <div className="band-rail">
          <div className="stat-label">Avg 5d return by metric bucket</div>
          <LiftTable data={data} producers={producers} />
          <div className="rail-foot muted small">
            Lift = top bucket minus bottom bucket, in points. A producer whose lift is flat
            is not ranking anything — the threshold is doing all the work.
          </div>
        </div>
      </div>
    </Band>
  )
}

function LiftTable({ data, producers }) {
  const widest = Math.max(0, ...producers.map((n) => (data.buckets[n] || []).length))
  if (!widest) return <div className="muted small">not enough signals to bucket yet</div>
  return (
    <table className="lift-table">
      <thead>
        <tr>
          <th scope="col"></th>
          {Array.from({ length: widest }, (_, i) => <th key={i} scope="col">B{i + 1}</th>)}
          <th scope="col">lift</th>
        </tr>
      </thead>
      <tbody>
        {producers.map((name) => {
          const buckets = data.buckets[name] || []
          const first = buckets[0]?.ret_5d?.avg
          const last = buckets[buckets.length - 1]?.ret_5d?.avg
          const lift = first == null || last == null ? null : (last - first) * 100
          return (
            <tr key={name}>
              <th scope="row"><ProducerTag producer={name} /></th>
              {Array.from({ length: widest }, (_, i) => {
                const b = buckets[i]
                return (
                  <td key={i} title={b ? `${b.label} · n=${b.n}` : undefined}>
                    {b?.ret_5d?.avg == null ? '–' : <Pct v={b.ret_5d.avg} />}
                  </td>
                )
              })}
              <td className={lift > 0 ? 'pos' : lift < 0 ? 'neg' : 'muted'}>
                {lift == null ? '–' : `${lift > 0 ? '+' : ''}${lift.toFixed(1)}`}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// Supply, and the tails it produced.
function SupplyBand({ data, producers }) {
  const [tail, setTail] = useState('best')
  const rows = tail === 'best' ? data.best : data.worst
  return (
    <Band title="Where did the signals come from?" note="buy signals per day, stacked · and the tails">
      <div className="band-split band-split-tails">
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={data.timeline} accessibilityLayer>
            <CartesianGrid stroke={C.hair} vertical={false} />
            <XAxis dataKey="date" tick={axisTick(10)} minTickGap={40} />
            <YAxis allowDecimals={false} tick={axisTick(10)} width={30} />
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            <Legend />
            {producers.map((name) => (
              <Bar key={name} dataKey={`${name}_buys`} name={PRODUCER_META[name]?.label || name}
                   stackId="a" fill={PRODUCER_META[name]?.color || C.muted} />
            ))}
          </BarChart>
        </ResponsiveContainer>
        <div className="band-rail">
          <div className="rail-head">
            <span className="stat-label">Tails, since signal</span>
            <div className="seg" role="group" aria-label="Tail">
              {[['best', 'Best'], ['worst', 'Worst']].map(([value, label]) => (
                <button key={value} type="button" className={`seg-btn ${tail === value ? 'active' : ''}`}
                        aria-pressed={tail === value} onClick={() => setTail(value)}>{label}</button>
              ))}
            </div>
          </div>
          <table className="tail-table">
            <tbody>
              {(rows || []).map((r) => (
                <tr key={r.id || `${r.producer}-${r.ticker}-${r.date}`}>
                  <td><DateLink d={r.date} /></td>
                  <td><ProducerTag producer={r.producer} /></td>
                  <td><TickerLink t={r.ticker} /></td>
                  <td style={{ textAlign: 'right' }}><Pct v={r.ret_since} /></td>
                  <td>
                    <PerfTag status={r.status_perf} actionWarning={r.has_action_warning}
                             actionIds={r.action_warning_ids} statusBasis={r.status_basis} />
                  </td>
                </tr>
              ))}
              {!rows?.length && <tr><td className="muted">nothing scored yet</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </Band>
  )
}

// The two questions the four bands above don't answer: where a producer's
// signals sit inside its own scored universe, and whether the weekday matters.
function DistributionBand({ data, producers }) {
  return (
    <Band title="Where in the metric — and on which day — do signals land?"
          note="signal share against the whole scored universe · avg 5d by signal weekday">
      <div className="dist-grid">
        {producers.map((name) => (
          <div key={name} className="dist-cell">
            <div className="stat-label">
              {PRODUCER_META[name]?.label} · {PRODUCER_META[name]?.metric}
            </div>
            <DistHist bins={data.histograms[name]} color={PRODUCER_META[name]?.color} height={170} />
          </div>
        ))}
        <div className="dist-cell">
          <div className="stat-label">avg 5d by weekday</div>
          <ResponsiveContainer width="100%" height={170}>
            <BarChart data={data.weekday} accessibilityLayer>
              <CartesianGrid stroke={C.hair} vertical={false} />
              <XAxis dataKey="day" tick={axisTick(11)} />
              <YAxis tick={axisTick(10)} width={44} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
              <Tooltip contentStyle={TOOLTIP_STYLE}
                       formatter={(v, n, item) => [`${(v * 100).toFixed(1)}% (n=${item.payload.n})`, n]} />
              <ReferenceLine y={0} stroke={C.rule} />
              <Bar dataKey="avg" name="avg 5d return" fill={C.muted} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </Band>
  )
}
