import React, { useState } from 'react'
import Analytics from './views/Analytics.jsx'
import Execution from './views/Execution.jsx'
import Runs from './views/Runs.jsx'
import Scores from './views/Scores.jsx'
import Signals from './views/Signals.jsx'
import Today from './views/Today.jsx'

const TABS = ['Today', 'Signals', 'Runs', 'Scores', 'Analytics', 'Execution']

export default function App() {
  const [tab, setTab] = useState('Today')
  const [scoresTarget, setScoresTarget] = useState(null)

  const openScores = (producer, date) => {
    setScoresTarget({ producer, date })
    setTab('Scores')
  }

  return (
    <div className="app">
      <header>
        <div className="brand">
          <span className="brand-mark">◆</span> Signal Dashboard
          <span className="muted brand-sub">LSTM + Intrinsic · read-only</span>
        </div>
        <nav>
          {TABS.map((t) => (
            <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>
              {t}
            </button>
          ))}
        </nav>
      </header>
      <main>
        {tab === 'Today' && <Today />}
        {tab === 'Signals' && <Signals />}
        {tab === 'Runs' && <Runs openScores={openScores} />}
        {tab === 'Scores' && <Scores key={JSON.stringify(scoresTarget)} initial={scoresTarget} />}
        {tab === 'Analytics' && <Analytics />}
        {tab === 'Execution' && <Execution />}
      </main>
    </div>
  )
}
