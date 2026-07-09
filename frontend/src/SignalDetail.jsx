import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import { fmtNum, fmtPx, fmtTs } from './format.js'
import { navigate } from './nav.js'
import { Pct, PerfTag, ProducerTag, Tag } from './ui.jsx'
import { PriceChart } from './charts.jsx'

const CORE_KEYS = new Set([
  'id', 'producer', 'date', 'ticker', 'decision', 'metric', 'status_perf', 'spark',
  'entry_px', 'last_px', 'last_date', 'ret_1d', 'ret_5d', 'ret_20d', 'ret_since',
  'created_at', 'px_stale',
  // shown in the header/gate lines instead of the raw field dump
  'event_date', 'published_at', 'extracted_at', 'as_of_timestamp', 'as_of_source',
  'source', 'n_grouped', 'n_events', 'gate_reason', 'w_pos', 'w_neg',
  'last_published_at',
])

// Date-only publish values (no time known) pass through untouched.
const fmtPub = (ts) => (String(ts).length === 10 ? ts : fmtTs(ts))

export default function SignalDetail({ signal, onClose }) {
  const [tickerData, setTickerData] = useState(null)

  useEffect(() => {
    setTickerData(null)
    if (signal) {
      api(`ticker/${signal.ticker}`).then(setTickerData).catch(() => setTickerData({ series: [] }))
    }
  }, [signal?.id])

  if (!signal) return null
  const raw = Object.entries(signal)
    .filter(([k, v]) => !CORE_KEYS.has(k) && v !== null && v !== undefined && typeof v !== 'object')
  const markers = (tickerData?.signals || [signal])
    .filter((s) => s.decision === 'BUY')
    .map((s) => ({ date: s.date, producer: s.producer }))

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <span className="drawer-ticker">{signal.ticker}</span>{' '}
            <ProducerTag producer={signal.producer} />{' '}
            <Tag kind="info">{signal.decision}</Tag>{' '}
            <PerfTag status={signal.status_perf} />
          </div>
          <div>
            <button className="btn" onClick={() => { onClose(); navigate('ticker', signal.ticker) }}>
              open ticker page →
            </button>
            <button className="btn" onClick={onClose}>✕</button>
          </div>
        </div>
        {signal.producer === 'foundry' ? (
          <div className="drawer-sub muted">
            trade day {signal.date}
            {signal.event_date && signal.event_date !== signal.date ? ` (first event on ${signal.event_date})` : ''}
            {signal.published_at ? ` · news from ${fmtPub(signal.published_at)}` : ''}
            {signal.n_events > 1 && signal.last_published_at ? ` to ${fmtPub(signal.last_published_at)}` : ''}
            {signal.gate_reason ? (
              <div className="gate-line">
                gate: {signal.gate_reason}
                {(signal.w_pos > 0 || signal.w_neg > 0) ? ` · weight +${signal.w_pos} / −${signal.w_neg}` : ''}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="drawer-sub muted">
            signaled {signal.date}
            {signal.created_at ? ` · created ${fmtTs(signal.created_at)}` : ''}
            {signal.as_of_timestamp ? ` · generated ${fmtTs(signal.as_of_timestamp)}` : ''}
            {signal.as_of_source ? ` · ${signal.as_of_source}` : ''}
          </div>
        )}

        <div className="stat-row">
          <MiniStat label="entry px" v={fmtPx(signal.entry_px)}
                    sub={signal.producer === 'foundry' ? 'prev close basis' : undefined} />
          <MiniStat label="last px" v={fmtPx(signal.last_px)}
                    sub={signal.px_stale ? `${signal.last_date} · stale ⚠` : signal.last_date} />
          <MiniStat label="1d" v={<Pct v={signal.ret_1d} />} />
          <MiniStat label="5d" v={<Pct v={signal.ret_5d} />} />
          <MiniStat label="20d" v={<Pct v={signal.ret_20d} />} />
          <MiniStat label="since" v={<Pct v={signal.ret_since} />} />
        </div>

        <h4>Price — signal dates marked</h4>
        <PriceChart series={tickerData?.series || []} signals={markers} height={200} />

        {signal.events?.length > 0 && (
          <>
            <h4>Contributing events ({signal.events.length})</h4>
            <div className="ev-list">
              {signal.events.map((e, i) => (
                <div key={i} className="ev-row">
                  <span className="muted small ev-time">{fmtPub(e.published_at)}</span>
                  <Tag kind="muted">{e.source}</Tag>
                  <Tag kind={e.sentiment > 0 ? 'ok' : e.sentiment < 0 ? 'err' : 'muted'}>
                    {e.sentiment > 0 ? `+${e.sentiment}` : e.sentiment ?? 0}
                  </Tag>
                  <span className="muted small">{fmtNum(e.signal_score, 3)}</span>
                  <a className="dlink ev-title" href={e.url} target="_blank" rel="noreferrer"
                     title={e.title}>{e.title || e.item_id}</a>
                </div>
              ))}
            </div>
          </>
        )}

        <h4>All signal fields</h4>
        <div className="kv-grid">
          {raw.map(([k, v]) => (
            <React.Fragment key={k}>
              <span>{k}</span>
              <b>
                {typeof v === 'number' ? fmtNum(v, 6)
                  : /^https?:\/\//.test(String(v))
                    ? <a className="dlink" href={v} target="_blank" rel="noreferrer">{String(v)}</a>
                    : String(v)}
              </b>
            </React.Fragment>
          ))}
        </div>
      </div>
    </div>
  )
}

function MiniStat({ label, v, sub }) {
  return (
    <div className="mini-stat">
      <div className="stat-label">{label}</div>
      <div className="mini-stat-v">{v}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}
