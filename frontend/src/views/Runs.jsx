import React, { useEffect, useState } from 'react'
import { api, PRODUCER_META } from '../api.js'
import { fmtTs } from '../format.js'
import { navigate } from '../nav.js'
import { Card, DateLink, ErrorBox, ProducerTag, Spinner, StatusTag, Table } from '../ui.jsx'
import Heatmap from '../Heatmap.jsx'

// Chronological log of every producer run; click through to the day page.
export default function Runs() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [producer, setProducer] = useState('')
  const [status, setStatus] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    api('runs', null, { signal: controller.signal }).then(setData)
      .catch((nextErr) => { if (nextErr.name !== 'AbortError') setErr(nextErr) })
    return () => controller.abort()
  }, [])

  if (err) return <ErrorBox err={err} />
  if (!data) return <Spinner />

  const rows = data.runs
    .filter((r) => !producer || r.producer === producer)
    .filter((r) => !status || (status === 'ok' ? r.status === 'ok' : r.status && r.status !== 'ok'))
    .map((r) => ({ ...r, key: r.producer + r.date }))
  return (
    <div className="runs-page">
      <h1 className="sr-only">Producer runs</h1>

      <Card title="Run calendar" className="run-calendar-card">
        <Heatmap calendar={data.runs} />
      </Card>

      <Card
        className="runs-records"
        title={`${rows.length} run records`}
        right={
          <div className="filter-row compact-filters">
            <label>Producer
              <select value={producer} onChange={(e) => setProducer(e.target.value)}>
                <option value="">all producers</option>
                {Object.entries(PRODUCER_META).map(([name, meta]) => (
                  <option key={name} value={name}>{meta.label}</option>
                ))}
              </select>
            </label>
            <label>Status
              <select value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">all states</option>
                <option value="ok">healthy only</option>
                <option value="review">needs review</option>
              </select>
            </label>
          </div>
        }
      >
        <Table
          rows={rows}
          initSort="date"
          onRow={(r) => navigate('day', r.date)}
          maxHeight="62vh"
          columns={[
            { key: 'date', label: 'Trade date', render: (r) => <DateLink d={r.date} /> },
            { key: 'producer', label: 'Producer', render: (r) => <ProducerTag producer={r.producer} /> },
            { key: 'status', label: 'Run status', render: (r) => <StatusTag status={r.status} title={r.failure_reason} /> },
            {
              key: 'n_scores', label: 'Scores', align: 'right',
              render: (r) => r.has_scores ? r.n_scores : <span className="muted">missing</span>,
            },
            {
              key: 'n_buy', label: 'Buys', align: 'right',
              render: (r) => r.n_buy > 0 ? <b className="pos">{r.n_buy}</b> : <span className="muted">{r.decision_summary === 'NO_BUY' ? 'NO_BUY' : 0}</span>,
            },
            { key: 'stale', label: 'Stale rows', align: 'right', render: (r) => r.stale ?? '–' },
            { key: 'as_of_date', label: 'As-of close', render: (r) => r.as_of_date || '–' },
            { key: 'generated_at', label: 'Verified/generated', render: (r) => r.generated_at ? fmtTs(r.generated_at) : '–' },
          ]}
        />
      </Card>
    </div>
  )
}
