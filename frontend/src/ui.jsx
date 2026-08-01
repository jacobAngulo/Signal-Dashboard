import React, { useId, useMemo, useState } from 'react'
import { PRODUCER_META } from './api.js'
import { href } from './nav.js'
import { signCls, fmtPct, fmtMoney } from './format.js'

export function Tag({ kind, children, title }) {
  return <span title={title} className={`tag tag-${kind || 'default'}`}>{children}</span>
}

export function ProducerTag({ producer }) {
  const meta = PRODUCER_META[producer] || { label: producer, color: '#888' }
  return (
    <span className="tag" style={{ background: meta.color + '22', color: meta.color, borderColor: meta.color + '55' }}>
      {meta.label}
    </span>
  )
}

export function StatusTag({ status, title }) {
  if (!status) return <Tag kind="muted">no status</Tag>
  const kind = status === 'ok' ? 'ok' : status === 'stale' ? 'warn' : 'err'
  return <Tag kind={kind} title={title}>{status}</Tag>
}

// Performance status of a signal (price-based, since signal date).
// `stale`: the ticker is no longer scored, so the status is frozen in the past.
export function PerfTag({
  status, stale, asOf, actionWarning = false, actionIds = [], statusBasis,
}) {
  const map = {
    pending: ['warn', '⧗ pending'],
    up: ['ok', '▲ up'],
    down: ['err', '▼ down'],
    flat: ['muted', '— flat'],
    no_action: ['muted', 'no action'],
    no_px: ['muted', '∅ no px'],
    corporate_action_unresolved: ['muted', '— return limited'],
    return_limited: ['muted', '— return limited'],
  }
  const [kind, label] = map[status] || ['muted', status || '–']
  const title = status === 'corporate_action_unresolved'
    ? 'return excluded: corporate-action terms or confirmation are unresolved'
    : status === 'no_px'
    ? 'no price coverage — the ticker is outside the scored universe, so this signal can\'t be tracked'
    : status === 'pending'
      ? 'awaiting the next scored close after the signal'
      : stale ? `frozen as of ${asOf || 'last scored day'} — ticker no longer scored` : undefined
  const basisTitle = statusBasis && statusBasis !== 'since'
    ? `direction uses the longest available safe return (${statusBasis})`
    : title
  const actionTitle = actionIds.length
    ? `corporate-action review flag: ${actionIds.join(', ')}`
    : 'corporate-action review flag; only affected return windows are excluded'
  return (
    <span className="performance-tags">
      <Tag kind={kind} title={basisTitle}>{label}{stale ? ' ⚠' : ''}</Tag>
      {actionWarning && <Tag kind="warn" title={actionTitle}>CA</Tag>}
    </span>
  )
}

export function TickerLink({ t, bold = true }) {
  return (
    <a className="tlink" href={href('ticker', t)} onClick={(e) => e.stopPropagation()}>
      {bold ? <b>{t}</b> : t}
    </a>
  )
}

export function DateLink({ d }) {
  if (!d) return <span className="muted">–</span>
  return <a className="dlink" href={href('day', d)} onClick={(e) => e.stopPropagation()}>{d}</a>
}

export function Pct({ v, digits = 1 }) {
  return <span className={signCls(v)}>{fmtPct(v, digits)}</span>
}

export function Money({ v }) {
  return <span className={signCls(v)}>{fmtMoney(v)}</span>
}

// Tiny inline sparkline for table cells; dot marks the signal date.
export function MiniSpark({ spark, ret }) {
  if (!spark || !spark.px || spark.px.length < 2) return <span className="muted">–</span>
  const { px, signal_i } = spark
  const w = 92, h = 24
  const min = Math.min(...px), max = Math.max(...px)
  const span = max - min || 1
  const X = (i) => 2 + (i / (px.length - 1)) * (w - 4)
  const Y = (v) => 2 + (1 - (v - min) / span) * (h - 4)
  const color = ret === null || ret === undefined ? '#7d8899' : ret > 0 ? '#3ecf8e' : ret < 0 ? '#f07070' : '#7d8899'
  const pts = px.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ')
  return (
    <svg width={w} height={h} className="minispark" role="img"
         aria-label={`price trend${ret == null ? '' : `, ${fmtPct(ret)} since signal`}`}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.3" />
      {signal_i !== null && signal_i !== undefined && signal_i < px.length && (
        <circle cx={X(signal_i)} cy={Y(px[signal_i])} r="2.6" fill="#f6c453" />
      )}
    </svg>
  )
}

// Generic client-side sortable table.
export function Table({ columns, rows, initSort, initDir = 'desc', onRow, empty = 'No rows', maxHeight, tableClassName = '' }) {
  const [sort, setSort] = useState(initSort)
  const [dir, setDir] = useState(initDir)

  const sorted = useMemo(() => {
    if (!sort) return rows
    const col = columns.find((c) => c.key === sort)
    if (!col) return rows
    const get = col.sortVal || ((r) => r[col.key])
    return [...rows].sort((a, b) => {
      const va = get(a), vb = get(b)
      if ((va === null || va === undefined) && (vb === null || vb === undefined)) return 0
      if (va === null || va === undefined) return 1
      if (vb === null || vb === undefined) return -1
      const cmp = typeof va === 'string' ? va.localeCompare(vb) : va - vb
      return dir === 'asc' ? cmp : -cmp
    })
  }, [rows, sort, dir, columns])

  const click = (key) => {
    if (sort === key) setDir(dir === 'asc' ? 'desc' : 'asc')
    else { setSort(key); setDir('desc') }
  }

  return (
    <div className="table-wrap" style={maxHeight ? { maxHeight, overflowY: 'auto' } : null}>
      <table className={tableClassName}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} title={c.title} style={{ textAlign: c.align || 'left' }} scope="col"
                  aria-sort={sort === c.key ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                  className={`${sort === c.key ? 'sorted ' : ''}col-${c.key}`}>
                <button type="button" className="sort-button" onClick={() => click(c.key)}>
                  {c.label}<span aria-hidden="true">{sort === c.key ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}</span>
                </button>
              </th>
            ))}
            {onRow && <th scope="col" className="row-action-head"><span className="sr-only">Actions</span></th>}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 && (
            <tr><td colSpan={columns.length + (onRow ? 1 : 0)} className="muted center">{empty}</td></tr>
          )}
          {sorted.map((r, i) => (
            <tr key={r.id || r.key || i} onClick={onRow ? () => onRow(r) : undefined}
                className={onRow ? 'clickable' : ''}>
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
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Card({ title, right, children, className = '' }) {
  const titleId = useId()
  return (
    <section className={`card ${className}`} aria-labelledby={title ? titleId : undefined}>
      {(title || right) && (
        <div className="card-head">
          <h2 className="card-title" id={title ? titleId : undefined}>{title}</h2>
          <div>{right}</div>
        </div>
      )}
      {children}
    </section>
  )
}

export function PageHeader({ eyebrow, title, description, actions, meta }) {
  return (
    <div className="page-head">
      <div className="page-head-copy">
        {eyebrow && <div className="page-eyebrow">{eyebrow}</div>}
        <h1 tabIndex="-1">{title}</h1>
        {description && <p>{description}</p>}
        {meta && <div className="page-meta">{meta}</div>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}

export function EmptyState({ title = 'Nothing here yet', detail, action }) {
  return (
    <div className="empty-state">
      <div className="empty-icon" aria-hidden="true">◇</div>
      <b>{title}</b>
      {detail && <div className="muted">{detail}</div>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  )
}

export function Stat({ label, value, sub, cls }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${cls || ''}`}>{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

export function Spinner() {
  return <div className="spinner" role="status" aria-live="polite">Loading…</div>
}

export function ErrorBox({ err }) {
  return (
    <div className="error-box" role="alert">
      <b>Couldn&apos;t load this view.</b>
      <span>{String(err.message || err)}</span>
    </div>
  )
}
