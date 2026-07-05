import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtTs } from '../format.js'
import { Card, ErrorBox, ProducerTag, Spinner, StatusTag, Table, Tag } from '../ui.jsx'
import SignalDetail from '../SignalDetail.jsx'
import { DecisionTable } from './Today.jsx'

export default function Runs({ openScores }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [day, setDay] = useState(null)      // selected date
  const [dayData, setDayData] = useState(null)
  const [sel, setSel] = useState(null)

  useEffect(() => { api('runs').then(setData).catch(setErr) }, [])
  useEffect(() => {
    setDayData(null)
    if (day) api(`day/${day}`).then(setDayData).catch(setErr)
  }, [day])

  if (err) return <ErrorBox err={err} />
  if (!data) return <Spinner />

  return (
    <div>
      <Card title="Signal generation runs" right={<span className="muted">click a row to inspect the day</span>}>
        <Table
          rows={data.runs.map((r) => ({ ...r, key: r.producer + r.date }))}
          initSort="date"
          onRow={(r) => setDay(r.date)}
          maxHeight="45vh"
          columns={[
            { key: 'date', label: 'Trade date' },
            { key: 'producer', label: 'Producer', render: (r) => <ProducerTag producer={r.producer} /> },
            { key: 'status', label: 'Run status', render: (r) => <StatusTag status={r.status} /> },
            {
              key: 'n_scores', label: 'Scores', align: 'right',
              render: (r) => r.has_scores ? r.n_scores : <span className="muted">missing</span>,
            },
            {
              key: 'n_buy', label: 'Buys', align: 'right',
              render: (r) => r.n_buy > 0 ? <b>{r.n_buy}</b> : <span className="muted">{r.decision_summary === 'NO_BUY' ? 'NO_BUY' : 0}</span>,
            },
            { key: 'stale', label: 'Stale rows', align: 'right', render: (r) => r.stale ?? '–' },
            { key: 'as_of_date', label: 'As-of close', render: (r) => r.as_of_date || '–' },
            { key: 'generated_at', label: 'Verified/generated', render: (r) => r.generated_at ? fmtTs(r.generated_at) : '–' },
          ]}
        />
      </Card>

      {day && (
        <Card title={`Day detail — ${day}`} right={<button className="btn" onClick={() => setDay(null)}>close</button>}>
          {!dayData ? <Spinner /> : Object.entries(dayData.producers).map(([name, p]) => (
            <div key={name} className="day-block">
              <div className="day-head">
                <ProducerTag producer={name} />
                {p.run ? <StatusTag status={p.run.status} /> : <Tag kind="muted">no run</Tag>}
                {p.scores_available && (
                  <button className="btn" onClick={() => openScores(name, day)}>
                    browse {p.n_scores} scores →
                  </button>
                )}
              </div>
              {p.status_raw && (
                <div className="kv-grid small">
                  {Object.entries(p.status_raw)
                    .filter(([k, v]) => !k.startsWith('_') && typeof v !== 'object')
                    .map(([k, v]) => (
                      <React.Fragment key={k}><span>{k}</span><b>{String(v)}</b></React.Fragment>
                    ))}
                </div>
              )}
              {p.decisions.length > 0
                ? <DecisionTable rows={p.decisions} onRow={setSel} />
                : <div className="muted" style={{ padding: '6px 0' }}>no decision rows</div>}
            </div>
          ))}
        </Card>
      )}
      <SignalDetail signal={sel} onClose={() => setSel(null)} />
    </div>
  )
}
