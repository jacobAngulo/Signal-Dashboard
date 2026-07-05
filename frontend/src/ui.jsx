import React, { useMemo, useState } from 'react'
import { PRODUCER_META } from './api.js'
import { signCls, fmtPct, fmtMoney } from './format.js'

export function Tag({ kind, children }) {
  return <span className={`tag tag-${kind || 'default'}`}>{children}</span>
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

export function StateTag({ state }) {
  const map = {
    open: ['ok', 'open'],
    partial: ['warn', 'partial'],
    closed: ['info', 'closed'],
    pending: ['warn', 'pending'],
    not_traded: ['muted', 'not traded'],
    no_action: ['muted', 'no action'],
  }
  const [kind, label] = map[state] || ['muted', state || '–']
  return <Tag kind={kind}>{label}</Tag>
}

export function Pct({ v, digits = 1 }) {
  return <span className={signCls(v)}>{fmtPct(v, digits)}</span>
}

export function Money({ v }) {
  return <span className={signCls(v)}>{fmtMoney(v)}</span>
}

// Generic client-side sortable table.
// columns: [{ key, label, render(row), sortVal(row), align, title }]
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

// Inline SVG price sparkline with optional signal markers.
export function Spark({ series, markers = [], width = 560, height = 120 }) {
  if (!series || series.length < 2) return <div className="muted">no price series</div>
  const px = series.map((p) => p.px)
  const min = Math.min(...px), max = Math.max(...px)
  const span = max - min || 1
  const X = (i) => 4 + (i / (series.length - 1)) * (width - 8)
  const Y = (v) => 6 + (1 - (v - min) / span) * (height - 12)
  const path = series.map((p, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(p.px).toFixed(1)}`).join(' ')
  const markerSet = new Set(markers)
  return (
    <svg width={width} height={height} className="spark">
      <path d={path} fill="none" stroke="#5b9cf6" strokeWidth="1.5" />
      {series.map((p, i) =>
        markerSet.has(p.date) ? (
          <circle key={p.date + i} cx={X(i)} cy={Y(p.px)} r="3.5" fill="#f6c453" stroke="#111" />
        ) : null
      )}
      <text x={width - 6} y={12} textAnchor="end" className="spark-label">{max.toPrecision(4)}</text>
      <text x={width - 6} y={height - 4} textAnchor="end" className="spark-label">{min.toPrecision(4)}</text>
    </svg>
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
