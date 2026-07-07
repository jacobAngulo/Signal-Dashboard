import React, { useMemo, useState } from 'react'
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

export function StatusTag({ status }) {
  if (!status) return <Tag kind="muted">no status</Tag>
  const kind = status === 'ok' ? 'ok' : status === 'stale' ? 'warn' : 'err'
  return <Tag kind={kind}>{status}</Tag>
}

// Performance status of a signal (price-based, since signal date).
// `stale`: the ticker is no longer scored, so the status is frozen in the past.
export function PerfTag({ status, stale, asOf }) {
  const map = {
    pending: ['warn', '⧗ pending'],
    up: ['ok', '▲ up'],
    down: ['err', '▼ down'],
    flat: ['muted', '— flat'],
    no_action: ['muted', 'no action'],
  }
  const [kind, label] = map[status] || ['muted', status || '–']
  const title = stale ? `frozen as of ${asOf || 'last scored day'} — ticker no longer scored` : undefined
  return <Tag kind={kind} title={title}>{label}{stale ? ' ⚠' : ''}</Tag>
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
    <svg width={w} height={h} className="minispark">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.3" />
      {signal_i !== null && signal_i !== undefined && signal_i < px.length && (
        <circle cx={X(signal_i)} cy={Y(px[signal_i])} r="2.6" fill="#f6c453" />
      )}
    </svg>
  )
}

// Generic client-side sortable table.
export function Table({ columns, rows, initSort, initDir = 'desc', onRow, empty = 'No rows', maxHeight }) {
  const [sort, setSort] = useState(initSort)
  const [dir, setDir] = useState(initDir)

  const sorted = useMemo(() => {
    if (!sort) return rows
    const col = columns.find((c) => c.key === sort)
    if (!col) return rows
    const get = col.sortVal || ((r) => r[col.key])
    return [...rows].sort((a, b) => {
      const va = get(a), vb = get(b)
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
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} title={c.title} style={{ textAlign: c.align || 'left' }}
                  className={sort === c.key ? 'sorted' : ''} onClick={() => click(c.key)}>
                {c.label}{sort === c.key ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 && (
            <tr><td colSpan={columns.length} className="muted center">{empty}</td></tr>
          )}
          {sorted.map((r, i) => (
            <tr key={r.id || r.key || i} onClick={onRow ? () => onRow(r) : undefined}
                className={onRow ? 'clickable' : ''}>
              {columns.map((c) => (
                <td key={c.key} style={{ textAlign: c.align || 'left' }}>
                  {c.render ? c.render(r) : r[c.key] ?? '–'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Card({ title, right, children, className = '' }) {
  return (
    <div className={`card ${className}`}>
      {(title || right) && (
        <div className="card-head">
          <div className="card-title">{title}</div>
          <div>{right}</div>
        </div>
      )}
      {children}
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
  return <div className="muted" style={{ padding: 24 }}>loading…</div>
}

export function ErrorBox({ err }) {
  return <div className="error-box">API error: {String(err.message || err)}</div>
}
