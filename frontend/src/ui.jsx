import React, { useId, useMemo, useState } from 'react'
import { PRODUCER_META } from './api.js'
import { href } from './nav.js'
import { signCls, fmtPct, fmtMoney } from './format.js'
import { C, signColor } from './theme.js'

export function Tag({ kind, children, title }) {
  return <span title={title} className={`tag tag-${kind || 'default'}`}>{children}</span>
}

// A producer reads as its own hue underlined, not as a filled chip -- the
// stylesheet carries the three hues so nothing here mixes colour into a fill.
export function ProducerTag({ producer }) {
  const meta = PRODUCER_META[producer]
  if (!meta) return <span className="tag tag-muted">{producer}</span>
  return <span className={`tag tag-${producer}`}>{meta.label}</span>
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

// Where to go look at a symbol outside this app. Pure URL templates over the
// bare ticker — nothing in the producers' output carries an exchange, so
// venues that need one in the path (Google Finance's AAPL:NASDAQ) stay out,
// as do crypto-only venues, which list none of these equities.
//
// The marks are each company's own logo, inlined so the page still makes no
// third-party requests: Robinhood and Yahoo! from Simple Icons (CC0), Alpaca
// from alpaca.markets' own webassets, brand colours sampled from the same.
// They are the companies' trademarks and are here only to point at them.
const SYMBOL_SITES = [
  {
    name: 'Robinhood',
    color: '#ccff00',
    ink: '#000000',
    box: 24,
    size: 16,
    url: (t) => `https://robinhood.com/stocks/${t}`,
    mark: () => <path d="M2.84 24h.53c.096 0 .192-.048.224-.128C7.591 13.696 11.94 8.656 14.67 5.638c.112-.128.064-.225-.096-.225h-4.88a.55.55 0 0 0-.45.225L5.746 9.972c-.514.642-.642 1.236-.642 2.086v4.43c-1.14 3.194-1.862 5.361-2.392 7.32-.032.125.016.192.129.192M20.447.646c-.754-.802-4.157-.834-5.73-.224a3 3 0 0 0-.786.465 41 41 0 0 0-3.323 3.178c-.112.113-.064.225.097.225h5.409c.497 0 .786.289.786.786v6.1c0 .16.128.208.225.064l3.258-4.254c.53-.69.69-.898.835-1.861.192-1.413.08-3.58-.77-4.479m-6.982 16.18 2.231-3.676a.7.7 0 0 0 .064-.29V6.73c0-.16-.112-.225-.224-.097-3.355 3.74-5.971 7.672-8.395 12.407-.06.12.016.225.16.177l5.009-1.54c.565-.174.882-.402 1.155-.852" />,
  },
  {
    name: 'Alpaca',
    color: '#f1cc21',
    ink: '#ffffff',
    // The alpaca is drawn to the edge of its badge, so it fills the whole
    // tile and reuses the tile's circle as its clip.
    box: 378,
    size: 26,
    url: (t) => `https://app.alpaca.markets/trade/${t}`,
    mark: (id) => (
      <>
        <defs>
          <clipPath id={id}><circle cx="189" cy="189" r="189" /></clipPath>
        </defs>
        <g clipPath={`url(#${id})`}>
          <path d="M261.969 357.639C259.185 357.639 256.514 356.533 254.545 354.564C252.576 352.595 251.469 349.924 251.469 347.139V157.089C251.473 148.025 249.216 139.103 244.904 131.13C240.592 123.158 234.361 116.386 226.773 111.427C229.107 107.607 230.381 103.234 230.465 98.7584C230.548 94.2827 229.437 89.8656 227.247 85.9613C225.058 82.057 221.867 78.8066 218.004 76.5443C214.142 74.282 209.746 73.0894 205.269 73.0894V94.0894H204.917C203.924 88.2174 200.884 82.8867 196.336 79.0426C191.787 75.1985 186.025 73.0894 180.069 73.0894V102.489H171.669V102.54C159.235 103.079 147.489 108.398 138.881 117.388C130.273 126.377 125.469 138.343 125.469 150.789C125.469 150.865 125.469 150.941 125.469 151.016L97.2202 169.278C99.1196 181.11 105.173 191.878 114.294 199.65C123.415 207.423 133.327 211.691 145.31 211.689C145.772 211.689 146.217 211.689 146.671 211.689L129.669 390.609L250.419 399.009L256.719 383.259L377.411 379.059V357.639H261.969Z" />
          <path d="M152.247 159.714C152.25 158.184 152.858 156.717 153.94 155.635C155.022 154.553 156.488 153.944 158.018 153.942H174.818C174.818 157.006 173.602 159.944 171.435 162.111C169.269 164.277 166.332 165.494 163.268 165.494H151.718L152.247 159.714Z" fill="#f1cc21" />
        </g>
      </>
    ),
  },
  {
    name: 'Yahoo Finance',
    color: '#6001d2',
    ink: '#ffffff',
    box: 24,
    size: 15,
    // Yahoo writes class shares with a dash (BRK-B) where the brokers use a dot.
    url: (t) => `https://finance.yahoo.com/quote/${t.replace(/\./g, '-')}`,
    mark: () => <path d="M18.86 1.56L14.27 11.87H19.4L24 1.56H18.86M0 6.71L5.15 18.27L3.3 22.44H7.83L14.69 6.71H10.19L7.39 13.44L4.62 6.71H0M15.62 12.87C13.95 12.87 12.71 14.12 12.71 15.58C12.71 17 13.91 18.19 15.5 18.19C17.18 18.19 18.43 16.96 18.43 15.5C18.43 14.03 17.23 12.87 15.62 12.87Z" />,
  },
]

// Outbound quote/trade links for one ticker, as brand-coloured badges. Login,
// if a site wants one, is the reader's problem — these just land on the
// symbol's page.
export function SymbolLinks({ ticker }) {
  const clipId = useId().replace(/:/g, '')
  const t = String(ticker || '').trim().toUpperCase()
  if (!t) return null
  return (
    <span className="symbol-links">
      {SYMBOL_SITES.map((site) => (
        <a key={site.name} className="symbol-link" href={site.url(encodeURIComponent(t))}
           target="_blank" rel="noreferrer" title={`${t} on ${site.name}`}
           style={{ background: site.color, color: site.ink }}>
          <svg width={site.size} height={site.size} viewBox={`0 0 ${site.box} ${site.box}`}
               fill="currentColor" aria-hidden="true">
            {site.mark(`${clipId}-${site.name}`)}
          </svg>
          <span className="sr-only">Open {t} on {site.name}</span>
        </a>
      ))}
    </span>
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
  const color = signColor(ret)
  const pts = px.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ')
  return (
    <svg width={w} height={h} className="minispark" role="img"
         aria-label={`price trend${ret == null ? '' : `, ${fmtPct(ret)} since signal`}`}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.3" />
      {signal_i !== null && signal_i !== undefined && signal_i < px.length && (
        <circle cx={X(signal_i)} cy={Y(px[signal_i])} r="2.2" fill={C.pending} />
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
