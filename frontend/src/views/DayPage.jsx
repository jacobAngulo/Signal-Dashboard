import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtNum, fmtPx } from '../format.js'
import { href } from '../nav.js'
import { Card, EmptyState, ErrorBox, ProducerTag, Spinner, StatusTag, Table, Tag, TickerLink } from '../ui.jsx'
import SignalTable from '../SignalTable.jsx'
import SignalDetail from '../SignalDetail.jsx'

// The day is fixed and the card names the producer, so the ledger drops both
// and leads with the time the decision was written.
const DAY_COLS = [
  'when', 'ticker_plain', 'call', 'metric', 'entry',
  'ret_1d', 'ret_5d', 'ret_20d', 'since', 'since_bar', 'status',
]

// One trade date: what each producer generated, with what, and the decisions.
export default function DayPage({ date }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [sel, setSel] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    setData(null); setErr(null)
    api(`day/${date}`, null, { signal: controller.signal }).then(setData)
      .catch((nextErr) => { if (nextErr.name !== 'AbortError') setErr(nextErr) })
    return () => controller.abort()
  }, [date])

  if (err) return <ErrorBox err={err} />
  if (!data) return <Spinner />

  return (
    <div className="day-page">
      <div className="crumb">
        {data.prev ? <a className="dlink" href={href('day', data.prev)}>‹ {data.prev}</a> : <span />}
        <h1 className="crumb-title">{data.date}</h1>
        {data.next ? <a className="dlink" href={href('day', data.next)}>{data.next} ›</a> : <span />}
      </div>

      <div className="day-scroll">
      {Object.entries(data.producers).map(([name, p]) => (
        <Card className={`day-producer producer-${name}`}
          key={name}
          title={<span><ProducerTag producer={name} /> {p.run ? <StatusTag status={p.run.status} title={p.run.failure_reason} /> : <Tag kind="muted">no run</Tag>}</span>}
          right={p.scores_available && (
            <a className="dlink" href={href('scores', name, data.date)}>
              browse all {p.n_scores} scores →
            </a>
          )}
        >
          {p.status_raw && <details className="detail-disclosure run-metadata">
            <summary>Run metadata</summary>
            <div className="kv-grid small">
              {Object.entries(p.status_raw)
                .filter(([k, v]) => !k.startsWith('_') && typeof v !== 'object')
                .map(([k, v]) => (
                  <React.Fragment key={k}><span>{k}</span><b>{String(v)}</b></React.Fragment>
                ))}
            </div>
          </details>}

          <h3 className="section-h">Decisions · {p.n_decisions_total}</h3>
          {p.decisions.length > 0
            ? <SignalTable rows={p.decisions} onRow={setSel} cols={DAY_COLS} />
            : <EmptyState title="No decision rows" detail="This producer did not emit a ticker-level decision for the day." />}
          {p.decisions_truncated && (
            <div className="inline-notice">
              Showing the 75 highest-priority decisions of {p.n_decisions_total.toLocaleString()}.
              {' '}<a className="dlink" href={`${href('explore')}?producer=${name}&from=${data.date}&to=${data.date}&buys=0`}>
                Open the full day in Explore →
              </a>
            </div>
          )}

          {p.top_scores.length > 0 && (
            <>
              <h3 className="section-h">Top scores · {p.metric_col}</h3>
              <Table
                rows={p.top_scores.map((r, i) => ({ ...r, key: i }))}
                columns={scoreColumns(name, p.metric_col)}
              />
            </>
          )}
        </Card>
      ))}
      </div>

      <SignalDetail signal={sel} onClose={() => setSel(null)} />
    </div>
  )
}

function scoreColumns(name, metricCol) {
  const base = [
    { key: 'ticker', label: 'Ticker', render: (r) => <TickerLink t={String(r.ticker).toUpperCase()} /> },
    { key: metricCol, label: metricCol, align: 'right', render: (r) => fmtNum(r[metricCol], 4) },
  ]
  if (name === 'lstm') {
    return [
      ...base,
      { key: 'best_horizon', label: 'Horizon' },
      { key: 'close', label: 'Close', align: 'right', render: (r) => fmtPx(r.close) },
    ]
  }
  if (name === 'intrinsic') {
    return [
      ...base,
      { key: 'price', label: 'Price', align: 'right', render: (r) => fmtPx(r.price) },
      { key: 'intrinsic_value', label: 'Intrinsic', align: 'right', render: (r) => fmtNum(r.intrinsic_value, 2) },
      { key: 'status', label: 'Status' },
    ]
  }
  return [
    ...base,
    { key: 'decision', label: 'Decision' },
    { key: 'event_type', label: 'Event' },
    { key: 'sentiment', label: 'Sentiment', align: 'right' },
    { key: 'confidence', label: 'Confidence', align: 'right', render: (r) => fmtNum(r.confidence, 3) },
    { key: 'source', label: 'Source' },
  ]
}
