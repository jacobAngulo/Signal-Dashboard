import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtMoney, fmtNum, fmtPct, fmtPx, fmtTs } from '../format.js'
import { Card, ErrorBox, Money, Pct, ProducerTag, Spinner, Stat, Table, Tag } from '../ui.jsx'

// Ground truth of what the arena bot fleet actually did with the signals —
// bots trade broader slices of the score files than the flagship decisions.
export default function Execution() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => { api('execution').then(setData).catch(setErr) }, [])

  if (err) return <ErrorBox err={err} />
  if (!data) return <Spinner />
  const t = data.totals

  const producers = (r) => (r.producers || []).map((p) => <ProducerTag key={p} producer={p} />)

  return (
    <div>
      <Card title="Fleet totals (signal-fed bots: lstm-*, intrinsic-*, mixed-*)">
        <div className="stat-row">
          <Stat label="round trips" value={t.n_trips} sub={t.win_rate === null ? null : `win rate ${fmtPct(t.win_rate, 0)}`} />
          <Stat label="realized P&L" value={fmtMoney(t.realized_pnl)} cls={t.realized_pnl >= 0 ? 'pos' : 'neg'} />
          <Stat label="open cost basis" value={fmtMoney(t.open_cost)} sub={`${data.open_positions.length} lots`} />
          <Stat label="open unrealized" value={fmtMoney(t.open_unrealized)} cls={t.open_unrealized >= 0 ? 'pos' : 'neg'}
                sub="live px from arena API (Alpaca)" />
        </div>
      </Card>

      <div className="grid-2">
        <Card title="P&L by bot (closed round trips)">
          <Table
            maxHeight="40vh"
            rows={data.by_bot.map((b) => ({ ...b, key: b.bot }))}
            initSort="pnl"
            columns={[
              { key: 'bot', label: 'Bot' },
              { key: 'trips', label: 'Trips', align: 'right' },
              { key: 'win_rate', label: 'Win', align: 'right', render: (r) => r.win_rate === null ? '–' : fmtPct(r.win_rate, 0) },
              { key: 'pnl', label: 'Realized', align: 'right', render: (r) => <Money v={r.pnl} /> },
            ]}
          />
        </Card>

        <Card title="Recent round trips">
          <Table
            maxHeight="40vh"
            rows={data.round_trips.slice(0, 60).map((r, i) => ({ ...r, key: i }))}
            columns={[
              { key: 'exit_date', label: 'Exit' },
              { key: 'symbol', label: 'Sym', render: (r) => <b>{r.symbol}</b> },
              { key: 'bot', label: 'Bot' },
              { key: 'entry_date', label: 'Entry' },
              { key: 'ret', label: 'Ret', align: 'right', render: (r) => <Pct v={r.ret} /> },
              { key: 'pnl', label: 'P&L', align: 'right', render: (r) => <Money v={r.pnl} /> },
            ]}
          />
        </Card>
      </div>

      <Card title={`Open lots (${data.open_positions.length})`}>
        <Table
          maxHeight="45vh"
          rows={data.open_positions.map((r, i) => ({ ...r, key: i }))}
          columns={[
            { key: 'entry_date', label: 'Entry' },
            { key: 'symbol', label: 'Sym', render: (r) => <b>{r.symbol}</b> },
            { key: 'bot', label: 'Bot' },
            { key: 'producers', label: 'Fed by', render: producers },
            { key: 'qty', label: 'Qty', align: 'right', render: (r) => fmtNum(r.qty, 3) },
            { key: 'entry_px', label: 'Entry px', align: 'right', render: (r) => fmtPx(r.entry_px) },
            { key: 'live_px', label: 'Live px', align: 'right', render: (r) => fmtPx(r.live_px) },
            { key: 'cost', label: 'Cost', align: 'right', render: (r) => fmtMoney(r.cost) },
            { key: 'ret', label: 'Ret', align: 'right', render: (r) => <Pct v={r.ret} /> },
            { key: 'unrealized_pnl', label: 'Unrealized', align: 'right', render: (r) => <Money v={r.unrealized_pnl} /> },
          ]}
        />
      </Card>

      <Card title="Recent orders">
        <Table
          maxHeight="45vh"
          rows={data.recent_orders.map((o) => ({ ...o, key: o.id }))}
          columns={[
            { key: 'timestamp', label: 'Time', render: (r) => fmtTs(r.timestamp) },
            { key: 'bot', label: 'Bot' },
            { key: 'symbol', label: 'Sym', render: (r) => <b>{r.symbol}</b> },
            { key: 'side', label: 'Side', render: (r) => <Tag kind={r.side === 'buy' ? 'ok' : 'info'}>{r.side}</Tag> },
            { key: 'status', label: 'Status', render: (r) => <Tag kind={r.status === 'filled' ? 'ok' : r.status === 'rejected' ? 'err' : 'warn'}>{r.status}</Tag> },
            { key: 'fill_qty', label: 'Qty', align: 'right', render: (r) => fmtNum(r.fill_qty ?? r.qty, 3) },
            { key: 'fill_price', label: 'Fill px', align: 'right', render: (r) => fmtPx(r.fill_price) },
            { key: 'reason', label: 'Reason', render: (r) => <span className="muted small">{r.reason}</span> },
          ]}
        />
      </Card>
    </div>
  )
}
