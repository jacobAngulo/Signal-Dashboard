import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { navigate, useRoute } from './nav.js'
import Analytics from './views/Analytics.jsx'
import DayPage from './views/DayPage.jsx'
import Explore from './views/Explore.jsx'
import Overview from './views/Overview.jsx'
import Runs from './views/Runs.jsx'
import Scores from './views/Scores.jsx'
import LstmWindows from './views/LstmWindows.jsx'
import TickerPage from './views/TickerPage.jsx'
import { ProducerTag } from './ui.jsx'
import FeedbackWidget from './components/FeedbackWidget.jsx'

const TABS = [
  ['overview', 'Overview', ''],
  ['explore', 'Explore', 'explore'],
  ['lstm-windows', 'LSTM', 'lstm-windows'],
  ['analytics', 'Analytics', 'analytics'],
  ['runs', 'Runs', 'runs'],
  ['scores', 'Scores', 'scores'],
]

const TITLES = { overview: null, explore: 'Explore', analytics: 'Analytics', runs: 'Runs', scores: 'Scores', 'lstm-windows': 'LSTM' }

export default function App() {
  const route = useRoute()
  const [dataVersion, setDataVersion] = useState(0)

  // Hash navigation keeps the old scroll position; a new page should start at the top.
  useEffect(() => {
    window.scrollTo(0, 0)
    const part = route.page === 'ticker' || route.page === 'day'
      ? route.args[0] : TITLES[route.page]
    document.title = part ? `${part} · Signal Dashboard` : 'Signal Dashboard'
    requestAnimationFrame(() => document.querySelector('main h1')?.focus({ preventScroll: true }))
  }, [route])

  return (
    <div className="app">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header>
        <div className="brand">
          <a href="#/" className="brand-link"><span className="brand-mark">◆</span> Signal Dashboard</a>
          <span className="muted brand-sub">LSTM + Intrinsic + Foundry</span>
        </div>
        <SearchBox />
        <DataStatus onPricesReady={() => setDataVersion((value) => value + 1)} />
        <nav aria-label="Primary navigation">
          {TABS.map(([key, label, path]) => (
            <a key={key} href={'#/' + path}
               aria-current={route.page === key ? 'page' : undefined}
               className={route.page === key ? 'active' : ''}>{label}</a>
          ))}
        </nav>
      </header>
      <main id="main-content" tabIndex="-1">
        <div className="route-view" key={dataVersion}>
        {route.page === 'overview' && <Overview />}
        {route.page === 'explore' && <Explore query={route.query} />}
        {route.page === 'analytics' && <Analytics />}
        {route.page === 'runs' && <Runs />}
        {route.page === 'scores' && (
          <Scores key={route.args.join('/')} producer={route.args[0]} date={route.args[1]} />
        )}
        {route.page === 'lstm-windows' && <LstmWindows />}
        {route.page === 'ticker' && route.args[0] && <TickerPage ticker={route.args[0].toUpperCase()} />}
        {route.page === 'day' && route.args[0] && <DayPage date={route.args[0]} />}
        {!['overview', 'explore', 'analytics', 'runs', 'scores', 'lstm-windows', 'ticker', 'day'].includes(route.page) && (
          <PageNotFound />
        )}
        </div>
      </main>
      <FeedbackWidget />
    </div>
  )
}

function DataStatus({ onPricesReady }) {
  const [health, setHealth] = useState(null)
  const wasBuilding = useRef(false)

  useEffect(() => {
    let active = true
    const check = () => api('health')
      .then((next) => {
        if (!active) return
        if (wasBuilding.current && !next.price_build_running && !next.price_load_error) onPricesReady()
        wasBuilding.current = next.price_build_running
        setHealth(next)
      })
      .catch(() => {})
    check()
    const timer = setInterval(check, 10000)
    return () => { active = false; clearInterval(timer) }
  }, [onPricesReady])

  const kind = !health ? 'busy' : health.price_load_error ? 'err' : health.price_build_running ? 'busy' : 'ok'
  const label = !health ? 'Checking data' : health.price_load_error ? 'Price data issue'
    : health.price_build_running ? 'Prices updating' : 'Live data'
  return <span className={`data-status data-status-${kind}`} title={health?.price_load_error || label}>
    <span className="status-dot" aria-hidden="true" />{label}
  </span>
}

function PageNotFound() {
  return (
    <div className="empty-state page-not-found">
      <div className="page-eyebrow">404</div>
      <h1 tabIndex="-1">View not found</h1>
      <div className="muted">That dashboard route does not exist.</div>
      <a className="btn primary-btn" href="#/">Return to overview</a>
    </div>
  )
}

// Global jump-to-ticker search: "/" focuses it, arrows walk the suggestions.
function SearchBox() {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState([])
  const [open, setOpen] = useState(false)
  const [idx, setIdx] = useState(0)
  const [focused, setFocused] = useState(false)
  const [searching, setSearching] = useState(false)
  const box = useRef(null)
  const input = useRef(null)

  useEffect(() => {
    if (!q.trim()) { setHits([]); setOpen(false); return }
    const controller = new AbortController()
    const t = setTimeout(() => {
      setSearching(true)
      api('tickers', { q }, { signal: controller.signal })
        .then((r) => { setHits(r.tickers); setIdx(0); setOpen(true) })
        .catch((err) => { if (err.name !== 'AbortError') { setHits([]); setOpen(true) } })
        .finally(() => { if (!controller.signal.aborted) setSearching(false) })
    }, 150)
    return () => { clearTimeout(t); controller.abort() }
  }, [q])

  useEffect(() => {
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    const slash = (e) => {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return
      const tag = e.target.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return
      e.preventDefault()
      input.current?.focus()
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', slash)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', slash)
    }
  }, [])

  const go = (t) => { setQ(''); setOpen(false); input.current?.blur(); navigate('ticker', t) }

  return (
    <div className="search-box" ref={box}>
      <input
        ref={input}
        placeholder="jump to ticker…"
        aria-label="Jump to ticker"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-busy={searching}
        aria-controls="ticker-search-results"
        aria-activedescendant={open && hits[idx] ? `ticker-hit-${hits[idx].ticker}` : undefined}
        autoComplete="off"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => { setFocused(true); hits.length && setOpen(true) }}
        onBlur={() => {
          setFocused(false)
          setTimeout(() => { if (!box.current?.contains(document.activeElement)) setOpen(false) }, 0)
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' && hits.length) { e.preventDefault(); setIdx((idx + 1) % hits.length) }
          if (e.key === 'ArrowUp' && hits.length) { e.preventDefault(); setIdx((idx - 1 + hits.length) % hits.length) }
          if (e.key === 'Enter' && (hits.length || q.trim())) go(hits[idx]?.ticker || q.trim().toUpperCase())
          if (e.key === 'Escape') { setOpen(false); e.target.blur() }
        }}
      />
      {!focused && !q && <span className="kbd-hint">/</span>}
      {open && (
        <div className="search-drop" id="ticker-search-results" role="listbox">
          {hits.length === 0 && (
            <div className="search-empty muted small">no tickers match &ldquo;{q.trim()}&rdquo;</div>
          )}
          {hits.map((h, i) => (
            <button type="button" role="option" tabIndex="-1" aria-selected={i === idx}
                 id={`ticker-hit-${h.ticker}`} key={h.ticker}
                 className={`search-hit${i === idx ? ' active' : ''}`}
                 onMouseEnter={() => setIdx(i)} onClick={() => go(h.ticker)}>
              <b>{h.ticker}</b>
              <span className="muted small" style={{ marginLeft: 'auto' }}>
                {h.n_signals > 0
                  ? `${h.n_signals} signal${h.n_signals > 1 ? 's' : ''} · last ${h.last_signal}`
                  : 'scored only'}
              </span>
              {h.producers.map((p) => <ProducerTag key={p} producer={p} />)}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
