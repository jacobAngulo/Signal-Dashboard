import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { fmtPct } from '../format.js'
import { Card, ErrorBox, Spinner } from '../ui.jsx'
import SignalTable from '../SignalTable.jsx'
import SignalDetail from '../SignalDetail.jsx'

// The dig-in surface: filter rail + enriched table + live summary of the slice.
export default function Explore() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [sel, setSel] = useState(null)

  const [producer, setProducer] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [buysOnly, setBuysOnly] = useState(true)
  const [ticker, setTicker] = useState('')
  const [status, setStatus] = useState('')
  const [minMetric, setMinMetric] = useState('')

  useEffect(() => {
    setData(null)
    api('signals', { producer, date_from: from, date_to: to, buys_only: buysOnly })
      .then(setData).catch(setErr)
  }, [producer, from, to, buysOnly])

  const rows = useMemo(() => {
    if (!data) return []
    let r = data.signals
    if (ticker) r = r.filter((s) => s.ticker.includes(ticker.toUpperCase()))
    if (status) r = r.filter((s) => s.status_perf === status)
    if (minMetric !== '' && !isNaN(+minMetric)) r = r.filter((s) => s.metric !== null && s.metric >= +minMetric)
    return r
  }, [data, ticker, status, minMetric])

  const summary = useMemo(() => {
    const vals = (k) => rows.map((r) => r[k]).filter((v) => v !== null && v !== undefined)
    const wr = (k) => {
      const v = vals(k)
      return v.length ? v.filter((x) => x > 0).length / v.length : null
    }
    const avg = (k) => {
      const v = vals(k)
      return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null
    }
    return { n: rows.length, wr1: wr('ret_1d'), wr5: wr('ret_5d'), avg5: avg('ret_5d'), avgS: avg('ret_since') }
  }, [rows])

  const reset = () => {
    setProducer(''); setFrom(''); setTo(''); setBuysOnly(true)
    setTicker(''); setStatus(''); setMinMetric('')
  }

  return (
    <div className="rail-layout">
      <aside>
        <Card title="Filters" right={<button className="btn" onClick={reset}>reset</button>}>
          <div className="filter-col">
            <label>Producer
              <select value={producer} onChange={(e) => setProducer(e.target.value)}>
                <option value="">both</option>
                <option value="lstm">LSTM</option>
                <option value="intrinsic">Intrinsic</option>
              </select>
            </label>
            <label>Ticker contains
              <input value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="e.g. GA" />
            </label>
            <label>From
              <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </label>
            <label>To
              <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </label>
            <label>Performance
              <select value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">any</option>
                <option value="up">up since signal</option>
                <option value="down">down since signal</option>
                <option value="pending">pending (no data yet)</option>
              </select>
            </label>
            <label>Min metric
              <input type="number" step="0.01" value={minMetric}
                     onChange={(e) => setMinMetric(e.target.value)} placeholder="e.g. 0.25" />
            </label>
            <label className="check">
              <input type="checkbox" checked={buysOnly} onChange={(e) => setBuysOnly(e.target.checked)} />
              BUY decisions only
            </label>
          </div>
        </Card>

        <Card title="This slice">
          <div className="kv-grid">
            <span>signals</span><b>{summary.n}</b>
            <span>win rate 1d</span><b>{summary.wr1 === null ? '–' : fmtPct(summary.wr1, 0)}</b>
            <span>win rate 5d</span><b>{summary.wr5 === null ? '–' : fmtPct(summary.wr5, 0)}</b>
            <span>avg 5d</span><b className={summary.avg5 > 0 ? 'pos' : summary.avg5 < 0 ? 'neg' : ''}>{summary.avg5 === null ? '–' : fmtPct(summary.avg5)}</b>
            <span>avg since</span><b className={summary.avgS > 0 ? 'pos' : summary.avgS < 0 ? 'neg' : ''}>{summary.avgS === null ? '–' : fmtPct(summary.avgS)}</b>
          </div>
          <div className="muted small">summary reflects current filters</div>
        </Card>
      </aside>

      <div>
        {err ? <ErrorBox err={err} /> : !data ? <Spinner /> : (
          <Card title={`${rows.length} signals`} right={<span className="muted small">click any row for detail · tickers and dates are links</span>}>
            <SignalTable rows={rows} onRow={setSel} maxHeight="74vh" />
          </Card>
        )}
      </div>
      <SignalDetail signal={sel} onClose={() => setSel(null)} />
    </div>
  )
}
