import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { Card, ErrorBox, Spinner } from '../ui.jsx'
import SignalDetail from '../SignalDetail.jsx'
import { DecisionTable } from './Today.jsx'

export default function Signals() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [sel, setSel] = useState(null)
  const [producer, setProducer] = useState('')
  const [ticker, setTicker] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [buysOnly, setBuysOnly] = useState(true)
  const [state, setState] = useState('')

  useEffect(() => {
    setData(null)
    api('signals', { producer, date_from: from, date_to: to, buys_only: buysOnly })
      .then(setData).catch(setErr)
  }, [producer, from, to, buysOnly])

  const rows = useMemo(() => {
    if (!data) return []
    let r = data.signals
    if (ticker) r = r.filter((s) => s.ticker.includes(ticker.toUpperCase()))
    if (state === 'traded') r = r.filter((s) => s.exec?.traded)
    else if (state) r = r.filter((s) => s.state === state)
    return r
  }, [data, ticker, state])

  return (
    <div>
      <Card>
        <div className="filter-row">
          <select value={producer} onChange={(e) => setProducer(e.target.value)}>
            <option value="">both producers</option>
            <option value="lstm">LSTM</option>
            <option value="intrinsic">Intrinsic</option>
          </select>
          <input placeholder="ticker…" value={ticker} onChange={(e) => setTicker(e.target.value)} style={{ width: 110 }} />
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          <span className="muted">to</span>
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          <select value={state} onChange={(e) => setState(e.target.value)}>
            <option value="">any status</option>
            <option value="traded">traded (any)</option>
            <option value="open">open</option>
            <option value="partial">partial</option>
            <option value="closed">closed</option>
            <option value="not_traded">not traded</option>
          </select>
          <label className="muted">
            <input type="checkbox" checked={buysOnly} onChange={(e) => setBuysOnly(e.target.checked)} /> BUYs only
          </label>
          <span className="muted" style={{ marginLeft: 'auto' }}>{rows.length} signals</span>
        </div>
      </Card>

      {err ? <ErrorBox err={err} /> : !data ? <Spinner /> : (
        <Card>
          <DecisionTable rows={rows} onRow={setSel} />
        </Card>
      )}
      <SignalDetail signal={sel} onClose={() => setSel(null)} />
    </div>
  )
}
