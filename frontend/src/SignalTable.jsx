import React, { useMemo, useState } from 'react'
import { PRODUCER_META } from './api.js'
import { fmtDayTime, fmtNum, fmtPct, fmtPx, fmtTime, fmtTs } from './format.js'
import { DateLink, MiniSpark, Pct, PerfTag, ProducerTag, TickerLink, Tag } from './ui.jsx'

// The merged signal ledger (design turns 3b / 4a / 7a). Sixteen columns
// collapsed to thirteen by pairing the things that are read together --
// date+time, ticker+producer, decision+window, entry price+entry session,
// status+exit -- with nothing dropped. Every page that lists signals renders
// this one table so Overview, Explore, Day and Ticker can't drift apart;
// `cols` is the only thing that varies between them.

// Foundry rows: the moment the source item was published is the signal time
// (its calendar day can differ from the trade date the event maps to).
function EventTime({ r }) {
  if (!r.published_at) return null
  const pub = String(r.published_at).length === 10 ? r.published_at : fmtTs(r.published_at)
  const tip = `published ${pub}${r.created_at ? ` · extracted ${fmtTs(r.created_at)}` : ''}`
  return <span className="muted" title={tip}>{fmtDayTime(r.published_at)}</span>
}

const decisionKind = (d) =>
  d === 'BUY' ? 'ok' : d === 'SELL' ? 'err' : d === 'WATCH' ? 'info' : 'muted'

// A signed return as a bar around a centre line: a column of percentages is
// a list, the same column with bars is a shape. Scale is the slice's own
// largest absolute move, floored so a quiet slice doesn't read as violent.
function SinceBar({ v, scale }) {
  if (v === null || v === undefined) {
    return <span className="dbar" aria-hidden="true"><i className="dbar-zero" /></span>
  }
  const half = Math.min(50, (Math.abs(v) / scale) * 50)
  const style = v >= 0
    ? { left: '50%', width: `${half}%` }
    : { right: '50%', width: `${half}%` }
  return (
    <span className="dbar" aria-hidden="true">
      <i className="dbar-zero" />
      <i className={`dbar-fill ${v >= 0 ? 'pos' : 'neg'}`} style={style} />
    </span>
  )
}

function ExitCell({ r }) {
  if (r.exit_state === 'closed') {
    return (
      <span title={r.exit_note || undefined}>
        <DateLink d={r.exit_date} /> <Pct v={r.exit_return} />
      </span>
    )
  }
  if (r.exit_state === 'open') {
    const fraction = r.sessions_elapsed != null && r.window_sessions
      ? ` ${r.sessions_elapsed}/${r.window_sessions}` : ''
    return <span className="muted" title={r.exit_note || undefined}>open{fraction}</span>
  }
  return (
    <span className="muted" title={r.exit_note || 'this producer publishes no exit signal'}>–</span>
  )
}

// The rule the simulation closed a row by, in the same cell as the status --
// "how it is doing" and "how it ended" are one question.
function SimCell({ r }) {
  if (r.sim_blocked_reason) {
    return (
      <span className="muted" title={`corporate-action review flagged: ${r.sim_blocked_reason}`}>CA</span>
    )
  }
  if (!r.sim_outcome) return <span className="muted">–</span>
  const label = { target: 'target', stop: 'stop', held: 'max hold', open: 'open' }[r.sim_outcome]
    || r.sim_outcome
  const kind = r.sim_outcome === 'target' ? 'ok' : r.sim_outcome === 'stop' ? 'err' : 'muted'
  return (
    <span>
      <Tag kind={kind}>{label}</Tag>
      {r.sim_ambiguous && (
        <span className="warn" title="stop and target both triggered in the same daily bar — resolved as stop"> ⚠</span>
      )}
      {r.sim_exit_date && <span className="muted small"> {r.sim_exit_date}</span>}
      {r.sim_return != null && <> <Pct v={r.sim_return} /></>}
    </span>
  )
}

// key -> column definition. `merged: true` means the column has no header of
// its own; the previous column's th spans it (Since value + Since bar).
function columnSet({ scale, hasSim, sparkWidth }) {
  return {
    when: {
      key: 'when', label: 'When',
      title: 'trading day the signal applies to · daily producers show when the decision file was written, foundry when the source item was published',
      sortVal: (r) => `${r.date} ${(r.producer === 'foundry' ? r.published_at : r.created_at) || ''}`,
      render: (r) => (
        <>
          <DateLink d={r.date} />
          <div className="led-sub">
            {r.producer === 'foundry'
              ? <EventTime r={r} />
              : r.created_at
                ? <span className="muted" title={fmtTs(r.created_at)}>{fmtTime(r.created_at)}</span>
                : <span className="muted">–</span>}
          </div>
        </>
      ),
    },
    ticker: {
      key: 'ticker', label: 'Ticker · producer',
      render: (r) => {
        const n = r.n_events || r.n_grouped
        return (
          <span className="led-ticker">
            <TickerLink t={r.ticker} />
            {n > 1 && (
              <span className="muted small" title={`${n} events rolled into this one signal — open the row to see them`}>×{n}</span>
            )}
            <ProducerTag producer={r.producer} />
          </span>
        )
      },
    },
    ticker_plain: {
      key: 'ticker', label: 'Ticker',
      render: (r) => {
        const n = r.n_events || r.n_grouped
        return (
          <span className="led-ticker">
            <TickerLink t={r.ticker} />
            {n > 1 && (
              <span className="muted small" title={`${n} events rolled into this one signal — open the row to see them`}>×{n}</span>
            )}
          </span>
        )
      },
    },
    producer: {
      key: 'producer', label: 'Producer',
      render: (r) => <ProducerTag producer={r.producer} />,
    },
    call: {
      key: 'call', label: 'Call · window',
      title: "decision, and the producer's own holding window — LSTM: model horizon in sessions · Intrinsic: none published · Foundry: the extraction model's own word, not a session count",
      sortVal: (r) => r.decision,
      render: (r) => (
        <span>
          <Tag kind={decisionKind(r.decision)}>{r.decision}</Tag>
          {r.window_label
            ? <span className="muted small" title={r.window_note || undefined}>{r.window_label}</span>
            : <span className="muted small" title={r.window_note || 'this producer publishes no holding window'}>n/a</span>}
        </span>
      ),
    },
    metric: {
      key: 'metric', label: 'Metric', align: 'right',
      title: 'LSTM: adjusted probability · Intrinsic: discount to intrinsic value · Foundry: event signal score',
      render: (r) => (
        <span>
          {fmtNum(r.metric, 3)}{' '}
          <span className="muted small">
            {PRODUCER_META[r.producer]?.metric}{r.event_type ? ` · ${r.event_type}` : ''}
          </span>
        </span>
      ),
    },
    entry: {
      key: 'entry_px', label: 'Entry', align: 'right',
      title: 'price at signal time — gateway close of the last session at/before the signal (foundry: the close before its actionable session); the producer\'s own value is retained as signal_price',
      sortVal: (r) => r.entry_px,
      render: (r) => (
        <span title={`entry session ${r.entry_date || 'unavailable'} · basis: ${r.price_basis || 'unavailable'} · action: ${r.action_status || 'unavailable'}`}>
          {fmtPx(r.entry_px)}
          <div className="led-sub muted">{r.entry_date ? r.entry_date.slice(5) : '–'}</div>
        </span>
      ),
    },
    ret_1d: {
      key: 'ret_1d', label: '1d', align: 'right',
      title: 'close-to-close from the actionable session',
      render: (r) => <Pct v={r.ret_1d} />,
    },
    ret_5d: {
      key: 'ret_5d', label: '5d', align: 'right',
      title: 'close-to-close from the actionable session',
      render: (r) => <Pct v={r.ret_5d} />,
    },
    ret_20d: {
      key: 'ret_20d', label: '20d', align: 'right',
      title: 'close-to-close from the actionable session',
      render: (r) => <Pct v={r.ret_20d} />,
    },
    since: {
      key: 'ret_since', label: 'Since entry', align: 'right',
      title: 'change from the signal-time entry to the last close — includes the overnight gap for foundry events',
      render: (r) => (
        r.ret_since == null
          ? <PerfTag status={r.status_perf} stale={r.px_stale} asOf={r.last_date}
                     statusBasis={r.status_basis} />
          : (
            <span title={r.px_stale ? `price data ends ${r.last_date} — ticker no longer scored` : undefined}>
              <Pct v={r.ret_since} />{r.px_stale ? <span className="warn"> ⚠</span> : null}
            </span>
          )
      ),
    },
    since_bar: {
      key: 'since_bar', merged: true, sortVal: (r) => r.ret_since,
      render: (r) => <SinceBar v={r.ret_since} scale={scale} />,
    },
    spark: {
      key: 'spark', label: `Trend — ${sparkWidth >= 120 ? '20 sessions' : 'since signal'}`,
      sortVal: (r) => r.ret_since,
      render: (r) => <MiniSpark spark={r.spark} ret={r.ret_since} width={sparkWidth} />,
    },
    exit: {
      key: 'exit_state', label: 'Exit',
      title: "when this signal's own logic would have sold — a producer with no native exit shows a dash",
      render: (r) => <ExitCell r={r} />,
    },
    status: {
      key: 'status_perf', label: 'Status · exit',
      title: 'price performance since the signal, and how the position closed',
      render: (r) => (
        <>
          <PerfTag status={r.status_perf} stale={r.px_stale} asOf={r.last_date}
                   actionWarning={r.has_action_warning} actionIds={r.action_warning_ids}
                   statusBasis={r.status_basis} />
          <div className="led-sub"><ExitCell r={r} /></div>
        </>
      ),
    },
    sim: hasSim && {
      key: 'sim_outcome', label: 'Rule exit',
      title: 'stop/target/max-hold simulation for this signal — simulated on daily high/low prices, historical, not advice',
      render: (r) => <SimCell r={r} />,
    },
  }
}

// A column's header spans itself plus any merged columns that follow it, so
// "Since entry" covers both the number and its bar without either page
// hard-coding a colspan.
function headSpan(columns, i) {
  let span = 1
  while (columns[i + span]?.merged) span += 1
  return span
}

const DEFAULT_COLS = [
  'when', 'ticker', 'call', 'metric', 'entry',
  'ret_1d', 'ret_5d', 'ret_20d', 'since', 'since_bar', 'sim', 'status',
]

export default function SignalTable({
  rows, onRow, onSelect, selectedId, empty = 'No rows', maxHeight, hide = [],
  cols = DEFAULT_COLS, groups, sections, footer, sparkWidth = 92,
  initSort = 'when', initDir = 'desc', onScroll, className = '',
}) {
  const [sort, setSort] = useState(initSort)
  const [dir, setDir] = useState(initDir)

  const hasSim = rows.some((r) => r.sim_outcome !== undefined)
  // One shared scale for the whole slice, so two bars in the same table are
  // comparable. 5% floor: without it a slice where nothing moved draws
  // full-width bars for a tenth of a percent.
  const scale = useMemo(() => Math.max(
    0.05, ...rows.map((r) => Math.abs(r.ret_since ?? 0)),
  ), [rows])

  const columns = useMemo(() => {
    const set = columnSet({ scale, hasSim, sparkWidth })
    const hidden = new Set(hide)
    return cols.map((key) => set[key]).filter((c) => c && !hidden.has(c.key))
  }, [cols, hide, scale, hasSim, sparkWidth])

  const sortRows = useMemo(() => {
    const col = columns.find((c) => c.key === sort)
    if (!col) return (list) => list
    const get = col.sortVal || ((r) => r[col.key])
    return (list) => [...list].sort((a, b) => {
      const va = get(a), vb = get(b)
      if (va == null && vb == null) return 0
      if (va == null) return 1
      if (vb == null) return -1
      const cmp = typeof va === 'string' ? va.localeCompare(String(vb)) : va - vb
      return dir === 'asc' ? cmp : -cmp
    })
  }, [columns, sort, dir])

  const click = (key) => {
    if (sort === key) setDir(dir === 'asc' ? 'desc' : 'asc')
    else { setSort(key); setDir('desc') }
  }

  const span = columns.length + (onRow ? 1 : 0)
  const body = sections
    ? sections.filter((s) => s.rows.length || s.always).flatMap((s) => [
        <tr key={`h-${s.key}`} className="led-section">
          <td colSpan={span}>
            {s.label} — {s.rows.length}
            {s.note && <span className="muted small"> · {s.note}</span>}
          </td>
        </tr>,
        ...sortRows(s.rows).map((r) => renderRow(r)),
      ])
    : sortRows(rows).map((r) => renderRow(r))

  function renderRow(r) {
    const id = r.id || `${r.producer}-${r.ticker}-${r.date}`
    const pick = onSelect || onRow
    return (
      <tr key={id}
          className={`${pick ? 'clickable' : ''}${selectedId && selectedId === r.id ? ' selected' : ''}`}
          aria-selected={selectedId ? selectedId === r.id : undefined}
          onClick={pick ? () => pick(r) : undefined}>
        {columns.map((c) => (
          <td key={c.key} className={`col-${c.key}`} style={{ textAlign: c.align || 'left' }}>
            {c.render ? c.render(r) : r[c.key] ?? '–'}
          </td>
        ))}
        {onRow && (
          <td className="row-action">
            <button type="button" className="row-action-btn"
                    onClick={(e) => { e.stopPropagation(); onRow(r) }}>
              View<span className="sr-only"> {r.ticker || r.date || 'details'}</span>
            </button>
          </td>
        )}
      </tr>
    )
  }

  return (
    <div className={`table-wrap led-wrap ${className}`} onScroll={onScroll}
         style={maxHeight ? { maxHeight, overflowY: 'auto' } : null}>
      <table className="signal-table">
        <thead>
          {groups && (
            <tr className="led-groups">
              {groups.map((g, i) => (
                <th key={i} colSpan={g.span} scope="colgroup" className="led-group">{g.label}</th>
              ))}
              {onRow && <th aria-hidden="true" />}
            </tr>
          )}
          <tr>
            {columns.map((c, i) => (c.merged ? null : (
              <th key={c.key} title={c.title} colSpan={headSpan(columns, i)} scope="col"
                  style={{ textAlign: c.align || 'left' }}
                  aria-sort={sort === c.key ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                  className={`${sort === c.key ? 'sorted ' : ''}col-${c.key}`}>
                <button type="button" className="sort-button" onClick={() => click(c.key)}>
                  {c.label}<span aria-hidden="true">{sort === c.key ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}</span>
                </button>
              </th>
            )))}
            {onRow && <th scope="col" className="row-action-head"><span className="sr-only">Actions</span></th>}
          </tr>
        </thead>
        <tbody>
          {!rows.length && <tr><td colSpan={span} className="muted center">{empty}</td></tr>}
          {body}
          {footer && <tr className="led-footer"><td colSpan={span}>{footer}</td></tr>}
        </tbody>
      </table>
    </div>
  )
}
