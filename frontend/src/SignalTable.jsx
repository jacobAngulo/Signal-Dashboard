import React from 'react'
import { PRODUCER_META } from './api.js'
import { fmtNum, fmtPx, fmtTime, fmtTs } from './format.js'
import { DateLink, MiniSpark, Pct, PerfTag, ProducerTag, Table, TickerLink, Tag } from './ui.jsx'

// The standard enriched-signal table used by Overview / Explore / Ticker / Day.
export default function SignalTable({ rows, onRow, empty, maxHeight, hide = [] }) {
  const H = new Set(hide)
  const columns = [
    !H.has('date') && { key: 'date', label: 'Date', render: (r) => <DateLink d={r.date} /> },
    !H.has('created') && {
      key: 'created_at', label: 'Created (PT)',
      title: 'when the producer wrote the decision file',
      render: (r) => r.created_at
        ? <span className="muted" title={fmtTs(r.created_at)}>{fmtTime(r.created_at)}</span>
        : '–',
    },
    !H.has('producer') && {
      key: 'producer', label: 'Producer', render: (r) => <ProducerTag producer={r.producer} />,
    },
    !H.has('ticker') && { key: 'ticker', label: 'Ticker', render: (r) => <TickerLink t={r.ticker} /> },
    !H.has('decision') && {
      key: 'decision', label: 'Decision',
      render: (r) => <Tag kind={r.decision === 'BUY' ? 'ok' : 'muted'}>{r.decision}</Tag>,
    },
    {
      key: 'metric', label: 'Metric', align: 'right',
      title: 'LSTM: adjusted probability · Intrinsic: discount to intrinsic value',
      render: (r) => (
        <span>
          {fmtNum(r.metric, 3)} <span className="muted small">{PRODUCER_META[r.producer]?.metric}</span>
          {r.horizon ? <span className="muted small"> · {r.horizon}</span> : null}
        </span>
      ),
    },
    { key: 'entry_px', label: 'Entry', align: 'right', render: (r) => fmtPx(r.entry_px) },
    { key: 'ret_1d', label: '1d', align: 'right', render: (r) => <Pct v={r.ret_1d} /> },
    { key: 'ret_5d', label: '5d', align: 'right', render: (r) => <Pct v={r.ret_5d} /> },
    { key: 'ret_20d', label: '20d', align: 'right', render: (r) => <Pct v={r.ret_20d} /> },
    { key: 'ret_since', label: 'Since', align: 'right', render: (r) => <Pct v={r.ret_since} /> },
    !H.has('spark') && {
      key: 'spark', label: 'Trend', sortVal: (r) => r.ret_since,
      render: (r) => <MiniSpark spark={r.spark} ret={r.ret_since} />,
    },
    { key: 'status_perf', label: 'Status', render: (r) => <PerfTag status={r.status_perf} /> },
  ].filter(Boolean)

  return (
    <Table columns={columns} rows={rows} initSort="date" onRow={onRow}
           empty={empty} maxHeight={maxHeight} />
  )
}
