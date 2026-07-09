import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { href, navigate, useRoute } from './nav.js'
import Analytics from './views/Analytics.jsx'
import DayPage from './views/DayPage.jsx'
import Explore from './views/Explore.jsx'
import Overview from './views/Overview.jsx'
import Runs from './views/Runs.jsx'
import Scores from './views/Scores.jsx'
import TickerPage from './views/TickerPage.jsx'
import { ProducerTag } from './ui.jsx'

const TABS = [
  ['overview', 'Overview', ''],
  ['explore', 'Explore', 'explore'],
  ['analytics', 'Analytics', 'analytics'],
  ['runs', 'Runs', 'runs'],
  ['scores', 'Scores', 'scores'],
]

export default function App() {
  const route = useRoute()

  return (
    <div className="app">
      <header>
        <div className="brand">
          <a href="#/" className="brand-link"><span className="brand-mark">◆</span> Signal Dashboard</a>
          <span className="muted brand-sub">LSTM + Intrinsic + Foundry</span>
        </div>
        <SearchBox />
        <nav>
          {TABS.map(([key, label, path]) => (
            <a key={key} href={'#/' + path}
               className={route.page === key ? 'active' : ''}>{label}</a>
          ))}
        </nav>
      </header>
      <main>
        {route.page === 'overview' && <Overview />}
        {route.page === 'explore' && <Explore />}
        {route.page === 'analytics' && <Analytics />}
        {route.page === 'runs' && <Runs />}
        {route.page === 'scores' && (
          <Scores key={route.args.join('/')} producer={route.args[0]} date={route.args[1]} />
        )}
        {route.page === 'ticker' && route.args[0] && <TickerPage ticker={route.args[0].toUpperCase()} />}
        {route.page === 'day' && route.args[0] && <DayPage date={route.args[0]} />}
      </main>
    </div>
  )
}

// Global jump-to-ticker search with suggestions.
function SearchBox() {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState([])
  const [open, setOpen] = useState(false)
  const box = useRef(null)

  useEffect(() => {
    if (!q.trim()) { setHits([]); return }
    const t = setTimeout(() => {
      api('tickers', { q }).then((r) => { setHits(r.tickers); setOpen(true) }).catch(() => {})
    }, 150)
    return () => clearTimeout(t)
  }, [q])

  useEffect(() => {
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const go = (t) => { setQ(''); setOpen(false); navigate('ticker', t) }

  return (
    <div className="search-box" ref={box}>
      <input
        placeholder="jump to ticker…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => hits.length && setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (hits[0] || q.trim())) go(hits[0]?.ticker || q.trim().toUpperCase())
          if (e.key === 'Escape') { setOpen(false); e.target.blur() }
        }}
      />
      {open && hits.length > 0 && (
        <div className="search-drop">
          {hits.map((h) => (
            <div key={h.ticker} className="search-hit" onClick={() => go(h.ticker)}>
              <b>{h.ticker}</b>
              <span className="muted small" style={{ marginLeft: 'auto' }}>
                {h.n_signals > 0
                  ? `${h.n_signals} signal${h.n_signals > 1 ? 's' : ''} · last ${h.last_signal}`
                  : 'scored only'}
              </span>
              {h.producers.map((p) => <ProducerTag key={p} producer={p} />)}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
