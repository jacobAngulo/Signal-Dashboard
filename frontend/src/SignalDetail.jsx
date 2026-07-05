import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import { fmtMoney, fmtNum, fmtPct, fmtPx, fmtTs } from './format.js'
import { Money, Pct, ProducerTag, Spark, StateTag, Table, Tag } from './ui.jsx'

const CORE_KEYS = new Set([
  'id', 'producer', 'date', 'ticker', 'decision', 'metric', 'exec', 'state',
  'entry_px', 'last_px', 'last_date', 'ret_1d', 'ret_5d', 'ret_20d', 'ret_since',
])

export default function SignalDetail({ signal, onClose }) {
  const [tickerData, setTickerData] = useState(null)

  useEffect(() => {
    setTickerData(null)
    if (signal) {
      api(`ticker/${signal.ticker}`).then(setTickerData).catch(() => setTickerData({ series: [] }))
    }
  }, [signal?.id])

  if (!signal) return null
  const ex = signal.exec || { traded: false }
  const raw = Object.entries(signal)
    .filter(([k, v]) => !CORE_KEYS.has(k) && v !== null && v !== undefined && typeof v !== 'object')

  const sigDates = tickerData?.signals?.map((s) => s.date) || [signal.date]

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <span className="drawer-ticker">{signal.ticker}</span>{' '}
            <ProducerTag producer={signal.producer} />{' '}
            <Tag kind="info">{signal.decision}</Tag>{' '}
            <StateTag state={signal.state} />
          </div>
          <button className="btn" onClick={onClose}>✕</button>
        </div>
        <div className="drawer-sub muted">
          signaled {signal.date}
          {signal.as_of_timestamp ? ` · generated ${fmtTs(signal.as_of_timestamp)}` : ''}
          {signal.as_of_source ? ` · ${signal.as_of_source}` : ''}
        </div>

        <div className="stat-row">
          <MiniStat label="entry px" v={fmtPx(signal.entry_px)} />
          <MiniStat label="last px" v={fmtPx(signal.last_px)} sub={signal.last_date} />
          <MiniStat label="1d" v={<Pct v={signal.ret_1d} />} />
          <MiniStat label="5d" v={<Pct v={signal.ret_5d} />} />
          <MiniStat label="20d" v={<Pct v={signal.ret_20d} />} />
          <MiniStat label="since" v={<Pct v={signal.ret_since} />} />
        </div>

        <h4>Price (from daily score files, signal dates marked)</h4>
        <Spark series={tickerData?.series} markers={sigDates} />

        <h4>Arena execution</h4>
        {!ex.traded ? (
          <div className="muted">No producer-linked bot bought {signal.ticker} on {signal.date}.</div>
        ) : (
          <div>
            <div className="kv-grid">
              <span>bots</span><b>{(ex.bots || []).join(', ')}</b>
              <span>filled qty</span><b>{fmtNum(ex.fill_qty, 4)}</b>
              <span>avg fill</span><b>{fmtPx(ex.avg_fill_px)}</b>
              <span>open qty</span><b>{fmtNum(ex.open_qty, 4)}</b>
              <span>realized P&L</span><b><Money v={ex.realized_pnl} /></b>
              <span>unrealized P&L</span><b><Money v={ex.unrealized_pnl} /></b>
            </div>
            {ex.exits?.length > 0 && (
              <Table
                columns={[
                  { key: 'date', label: 'Exit date' },
                  { key: 'bot', label: 'Bot' },
                  { key: 'qty', label: 'Qty', align: 'right', render: (r) => fmtNum(r.qty, 4) },
                  { key: 'px', label: 'Px', align: 'right', render: (r) => fmtPx(r.px) },
                  { key: 'pnl', label: 'P&L', align: 'right', render: (r) => <Money v={r.pnl} /> },
                ]}
                rows={ex.exits}
                initSort="date"
              />
            )}
          </div>
        )}

        <h4>All signal fields</h4>
        <div className="kv-grid">
          {raw.map(([k, v]) => (
            <React.Fragment key={k}>
              <span>{k}</span>
              <b>{typeof v === 'number' ? fmtNum(v, 6) : String(v)}</b>
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
