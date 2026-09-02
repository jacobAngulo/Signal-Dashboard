import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { fmtNum, fmtPx, fmtTs } from './format.js'
import { navigate } from './nav.js'
import { Pct, PerfTag, ProducerTag, Spinner, Tag } from './ui.jsx'
import { PriceChart } from './charts.jsx'

const CORE_KEYS = new Set([
  'id', 'producer', 'date', 'ticker', 'decision', 'metric', 'status_perf', 'spark',
  'entry_px', 'entry_date', 'last_px', 'last_date', 'ret_1d', 'ret_5d', 'ret_20d',
  'ret_since', 'ret_since_actionable', 'actionable_entry_px',
  'created_at', 'px_stale',
  // shown in the header/gate lines instead of the raw field dump
  'event_date', 'published_at', 'extracted_at', 'as_of_timestamp', 'as_of_source',
  'source', 'n_grouped', 'n_events', 'gate_reason', 'w_pos', 'w_neg',
  'last_published_at',
  // TB-46: shown in the "window"/"exit" stat cells instead
  'window_label', 'window_sessions', 'window_basis', 'window_note',
  'exit_basis', 'exit_state', 'exit_date', 'exit_px', 'exit_return',
  'sessions_elapsed', 'exit_note',
])

// Date-only publish values (no time known) pass through untouched.
const fmtPub = (ts) => (String(ts).length === 10 ? ts : fmtTs(ts))

export default function SignalDetail({ signal, onClose }) {
  const [tickerData, setTickerData] = useState(null)
  const [detail, setDetail] = useState(null)
  const drawerRef = useRef(null)
  const closeRef = useRef(null)
  const previousFocus = useRef(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    setTickerData(null)
    setDetail(null)
    const controller = new AbortController()
    if (signal) {
      api(`ticker/${signal.ticker}`, null, { signal: controller.signal })
        .then(setTickerData)
        .catch((err) => { if (err.name !== 'AbortError') setTickerData({ series: [] }) })
      if (signal.id && !signal.detail_inline) {
        api('signal', { id: signal.id }, { signal: controller.signal })
          .then((data) => setDetail(data.signal))
          .catch((err) => { if (err.name !== 'AbortError') setDetail(signal) })
      } else if (signal.detail_inline) {
        setDetail(signal)
      }
    }
    return () => controller.abort()
  }, [signal?.id, signal?.ticker])

  // Keep focus inside the modal, Escape closes, and restore focus to the row
  // that opened it. The page behind the overlay should not scroll.
  useEffect(() => {
    if (!signal) return
    previousFocus.current = document.activeElement
    const frame = requestAnimationFrame(() => closeRef.current?.focus())
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); onCloseRef.current() }
      if (e.key !== 'Tab' || !drawerRef.current) return
      const focusable = [...drawerRef.current.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )]
      if (!focusable.length) return
      const first = focusable[0], last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      cancelAnimationFrame(frame)
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previousOverflow
      previousFocus.current?.focus?.()
    }
  }, [signal?.id])

  if (!signal) return null
  const full = detail || signal
  const raw = Object.entries(full)
    .filter(([k, v]) => !CORE_KEYS.has(k) && v !== null && v !== undefined && typeof v !== 'object')
  const markers = (tickerData?.signals || [signal])
    .map((s) => ({ date: s.date, producer: s.producer, decision: s.decision }))

  return (
    <div className="drawer-overlay" onMouseDown={(e) => {
      if (e.target === e.currentTarget) onClose()
    }}>
      <section className="drawer" ref={drawerRef} role="dialog" aria-modal="true"
               aria-labelledby="signal-detail-title">
        <div className="drawer-head">
          <div>
            <span className="drawer-ticker" id="signal-detail-title">{signal.ticker}</span>{' '}
            <ProducerTag producer={signal.producer} />{' '}
            <Tag kind="info">{signal.decision}</Tag>{' '}
            <PerfTag status={signal.status_perf}
                     actionWarning={signal.has_action_warning}
                     actionIds={signal.action_warning_ids}
                     statusBasis={signal.status_basis} />
          </div>
          <div>
            <button className="btn" onClick={() => { onClose(); navigate('ticker', signal.ticker) }}>
              open ticker page →
            </button>
            <button ref={closeRef} className="btn icon-btn" onClick={onClose}
                    aria-label="Close signal details" title="close (Esc)">✕</button>
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
                    sub={signal.entry_date || (signal.producer === 'foundry' ? 'prev close basis' : undefined)} />
          <MiniStat label="last px" v={fmtPx(signal.last_px)}
                    sub={signal.px_stale ? `${signal.last_date} · stale ⚠` : signal.last_date} />
          <MiniStat label="1d" v={<Pct v={signal.ret_1d} />} />
          <MiniStat label="5d" v={<Pct v={signal.ret_5d} />} />
          <MiniStat label="20d" v={<Pct v={signal.ret_20d} />} />
          <MiniStat label="since" v={<Pct v={signal.ret_since} />}
                    sub={signal.ret_since_actionable != null
                      ? `session basis ${(signal.ret_since_actionable * 100).toFixed(1)}%`
                      : undefined} />
          <MiniStat label="window" v={signal.window_label || 'n/a'}
                    sub={signal.window_note} />
          <MiniStat label="exit"
                    v={signal.exit_state === 'closed' ? <Pct v={signal.exit_return} />
                      : signal.exit_state === 'open' ? 'open' : '–'}
                    sub={signal.exit_state === 'closed' ? signal.exit_date
                      : signal.exit_state === 'open' && signal.sessions_elapsed != null && signal.window_sessions
                        ? `${signal.sessions_elapsed}/${signal.window_sessions} sessions`
                        : signal.exit_note} />
        </div>

        <h4>Price — signal dates marked</h4>
        {tickerData ? <PriceChart series={tickerData.series || []} signals={markers} height={200} />
          : <Spinner />}

        {full.events?.length > 0 && (
          <>
            <h4>Contributing events ({full.events.length})</h4>
            <div className="ev-list">
              {full.events.map((e, i) => (
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

        <details className="detail-disclosure">
          <summary>All signal fields <span className="muted">({raw.length})</span></summary>
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
        </details>
      </section>
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
