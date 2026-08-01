import React from 'react'
import { PRODUCER_META } from './api.js'
import { fmtDayTime, fmtNum, fmtPx, fmtTime, fmtTs } from './format.js'
import { DateLink, MiniSpark, Pct, PerfTag, ProducerTag, Table, TickerLink, Tag } from './ui.jsx'

// Foundry rows: the moment the source item was published is the signal time
// (its calendar day can differ from the trade date the event maps to).
function EventTime({ r }) {
  if (!r.published_at) return '–'
  const pub = String(r.published_at).length === 10 ? r.published_at : fmtTs(r.published_at)
  const tip = `published ${pub}${r.created_at ? ` · extracted ${fmtTs(r.created_at)}` : ''}`
  return <span className="muted" title={tip}>{fmtDayTime(r.published_at)}</span>
}

// The standard enriched-signal table used by Overview / Explore / Ticker / Day.
export default function SignalTable({ rows, onRow, empty, maxHeight, hide = [] }) {
  const H = new Set(hide)
  const decisionKind = (d) => d === 'BUY' ? 'ok' : d === 'SELL' ? 'err' : d === 'WATCH' ? 'info' : 'muted'
  const columns = [
    !H.has('date') && {
      key: 'date', label: 'Date',
      title: 'trading day the signal applies to',
      render: (r) => <DateLink d={r.date} />,
    },
    !H.has('created') && {
      key: 'created_at', label: 'Time (PT)',
      title: 'daily producers: when the decision file was written · foundry: when the source item was published',
      sortVal: (r) => r.producer === 'foundry' ? (r.published_at || r.created_at) : r.created_at,
      render: (r) => r.producer === 'foundry'
        ? <EventTime r={r} />
        : r.created_at
          ? <span className="muted" title={fmtTs(r.created_at)}>{fmtTime(r.created_at)}</span>
          : '–',
    },
    !H.has('producer') && {
      key: 'producer', label: 'Producer', render: (r) => <ProducerTag producer={r.producer} />,
    },
    !H.has('ticker') && {
      key: 'ticker', label: 'Ticker',
      render: (r) => {
        const n = r.n_events || r.n_grouped
        return (
          <span>
            <TickerLink t={r.ticker} />
            {n > 1 && (
              <span className="muted small" title={`${n} events rolled into this one signal — open the row to see them`}
              > ×{n}</span>
            )}
          </span>
        )
      },
    },
    !H.has('decision') && {
      key: 'decision', label: 'Decision',
      render: (r) => <Tag kind={decisionKind(r.decision)}>{r.decision}</Tag>,
    },
    {
      key: 'metric', label: 'Metric', align: 'right',
      title: 'LSTM: adjusted probability · Intrinsic: discount to intrinsic value · Foundry: event signal score',
      render: (r) => (
        <span>
          {fmtNum(r.metric, 3)} <span className="muted small">{PRODUCER_META[r.producer]?.metric}</span>
          {r.event_type ? <span className="muted small"> · {r.event_type}</span> : null}
          {r.horizon ? <span className="muted small"> · {r.horizon}</span> : null}
        </span>
      ),
    },
    {
      key: 'entry_px', label: 'Entry', align: 'right',
      title: 'price at signal time — gateway close of the last session at/before the signal (foundry: the close before its actionable session); producer value is retained as signal_price',
      render: (r) => <span title={`entry session ${r.entry_date || 'unavailable'} · basis: ${r.price_basis || 'unavailable'} · action: ${r.action_status || 'unavailable'}`}>
        {fmtPx(r.entry_px)}
      </span>,
    },
    { key: 'ret_1d', label: '1d', align: 'right', title: 'close-to-close from the actionable session', render: (r) => <Pct v={r.ret_1d} /> },
    { key: 'ret_5d', label: '5d', align: 'right', title: 'close-to-close from the actionable session', render: (r) => <Pct v={r.ret_5d} /> },
    { key: 'ret_20d', label: '20d', align: 'right', title: 'close-to-close from the actionable session', render: (r) => <Pct v={r.ret_20d} /> },
    {
      key: 'ret_since', label: 'Since', align: 'right',
      title: 'change from the signal-time entry to the last close — includes the overnight gap for foundry events',
      render: (r) => (
        <span title={r.px_stale ? `price data ends ${r.last_date} — ticker no longer scored` : undefined}>
          <Pct v={r.ret_since} />{r.px_stale && r.ret_since != null ? <span className="warn"> ⚠</span> : null}
        </span>
      ),
    },
    !H.has('spark') && {
      key: 'spark', label: 'Trend', sortVal: (r) => r.ret_since,
      render: (r) => <MiniSpark spark={r.spark} ret={r.ret_since} />,
    },
    {
      key: 'status_perf', label: 'Status',
      render: (r) => (
        <PerfTag status={r.status_perf} stale={r.px_stale} asOf={r.last_date}
                 actionWarning={r.has_action_warning} actionIds={r.action_warning_ids}
                 statusBasis={r.status_basis} />
      ),
    },
  ].filter(Boolean)

  return (
    <Table columns={columns} rows={rows} initSort="date" onRow={onRow}
           empty={empty} maxHeight={maxHeight} tableClassName="signal-table" />
  )
}
