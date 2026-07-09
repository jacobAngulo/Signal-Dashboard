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

  useEffect(() => { api('runs').then(setData).catch(setErr) }, [])

  if (err) return <ErrorBox err={err} />
  if (!data) return <Spinner />

  const rows = data.runs
    .filter((r) => !producer || r.producer === producer)
    .map((r) => ({ ...r, key: r.producer + r.date }))

  return (
    <div>
      <Card title="Run calendar">
        <Heatmap calendar={data.runs} />
      </Card>

      <Card
        title="All runs"
        right={
          <select value={producer} onChange={(e) => setProducer(e.target.value)}>
            <option value="">all producers</option>
            {Object.entries(PRODUCER_META).map(([name, meta]) => (
              <option key={name} value={name}>{meta.label}</option>
            ))}
          </select>
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
            { key: 'status', label: 'Run status', render: (r) => <StatusTag status={r.status} /> },
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
